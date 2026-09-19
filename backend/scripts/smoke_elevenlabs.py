"""Tiny ElevenLabs access check: entitlement, voices, models, one short TTS.

Run:  .venv/bin/python backend/scripts/smoke_elevenlabs.py

Prints no key material. Generates at most one very short phrase.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402

BASE = "https://api.elevenlabs.io"


def main() -> int:
    s = get_settings()
    if not s.elevenlabs_api_key:
        print("BLOCKED: ELEVENLABS_API_KEY is empty in .env")
        print("Claim the event offer, then create a key at https://elevenlabs.io/app/settings/api-keys")
        return 2
    headers = {"xi-api-key": s.elevenlabs_api_key}

    # --- 1. entitlement / credits (confirms real API billing, not just a UI plan) ---
    print("[1/4] GET /v1/user/subscription ...")
    r = httpx.get(f"{BASE}/v1/user/subscription", headers=headers, timeout=20.0)
    if r.status_code == 200:
        sub = r.json()
        print(f"  tier       : {sub.get('tier')}")
        print(f"  characters : {sub.get('character_count')} / "
              f"{sub.get('character_limit')} used this period")
        print(f"  status     : {sub.get('status')}")
    elif r.status_code in (401, 403):
        # A key scoped without `user_read` still works for STT/TTS. Not fatal:
        # it only means we cannot read the quota programmatically.
        print("  SKIPPED: key lacks the 'user_read' permission.")
        print("  Speech still works; check remaining credits in the ElevenLabs dashboard.")
    else:
        print(f"  HTTP {r.status_code}: {r.text[:300]}")
        return 1

    # --- 2. stock voices actually available to THIS account ---
    print("\n[2/4] GET /v1/voices ...")
    r = httpx.get(f"{BASE}/v1/voices", headers=headers, timeout=20.0)
    if r.status_code != 200:
        print(f"  HTTP {r.status_code}: {r.text[:300]}")
        return 1
    voices = r.json().get("voices", [])
    print(f"  {len(voices)} voices available:")
    for v in voices[:15]:
        mark = "  <-- ELEVENLABS_VOICE_ID" if v.get("voice_id") == s.elevenlabs_voice_id else ""
        print(f"    {v.get('voice_id')}  {v.get('name')}  ({v.get('category')}){mark}")

    # --- 3. model ids ---
    print("\n[3/4] GET /v1/models ...")
    r = httpx.get(f"{BASE}/v1/models", headers=headers, timeout=20.0)
    if r.status_code == 200:
        for m in r.json():
            mid = m.get("model_id", "")
            if m.get("can_do_text_to_speech") or "scribe" in mid:
                print(f"    {mid}")
    else:
        print(f"  HTTP {r.status_code} (non-fatal): {r.text[:200]}")

    if not s.elevenlabs_voice_id:
        print("\nNext: copy a voice_id above into ELEVENLABS_VOICE_ID in .env, then re-run.")
        return 2

    # --- 4. one very short TTS call ---
    print(f"\n[4/4] POST /v1/text-to-speech/{s.elevenlabs_voice_id}  model={s.elevenlabs_tts_model} ...")
    t0 = time.perf_counter()
    r = httpx.post(
        f"{BASE}/v1/text-to-speech/{s.elevenlabs_voice_id}",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "text": "One moment.",
            "model_id": s.elevenlabs_tts_model,
            "output_format": "mp3_44100_128",
        },
        timeout=30.0,
    )
    dt = (time.perf_counter() - t0) * 1000
    print(f"  HTTP {r.status_code} in {dt:.0f} ms, {len(r.content)} bytes")
    if r.status_code != 200:
        print(f"  body: {r.text[:400]}")
        return 1
    out = Path(__file__).resolve().parents[2] / "eval" / "results" / "smoke_tts.mp3"
    out.write_bytes(r.content)
    print(f"  wrote {out} (play it to confirm the voice)")
    print(f"\nOK: speech synthesis reachable. STT model configured as {s.elevenlabs_stt_model!r}")
    print("    (STT is exercised by the first spoken turn in the app.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
