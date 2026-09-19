"""Tiny NVIDIA hosted-Nemotron access check.

Run:  .venv/bin/python backend/scripts/smoke_nvidia.py

Step 1 lists the Nemotron models your account can see (free catalogue call).
Step 2 sends ONE tiny chat completion using NVIDIA_MODEL from .env.
Prints no key material. Makes no large requests.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402


def main() -> int:
    s = get_settings()
    print(f"base_url : {s.nvidia_base_url}")
    print(f"model    : {s.nvidia_model or '(unset)'}")
    if not s.nvidia_api_key:
        print("\nBLOCKED: NVIDIA_API_KEY is empty in .env")
        print("Get a key at https://build.nvidia.com (Build with this NIM -> Get API Key).")
        return 2

    headers = {"Authorization": f"Bearer {s.nvidia_api_key}"}

    # --- Step 1: catalogue ---
    print("\n[1/2] GET /models ...")
    try:
        r = httpx.get(f"{s.nvidia_base_url}/models", headers=headers, timeout=20.0)
    except httpx.HTTPError as exc:
        print(f"  network error: {type(exc).__name__}: {exc}")
        return 1
    if r.status_code != 200:
        print(f"  HTTP {r.status_code}: {r.text[:300]}")
        return 1
    ids = sorted(m.get("id", "") for m in r.json().get("data", []))
    nemotron = [i for i in ids if "nemotron" in i.lower()]
    print(f"  {len(ids)} models visible, {len(nemotron)} matching 'nemotron':")
    for i in nemotron:
        mark = "  <-- NVIDIA_MODEL" if i == s.nvidia_model else ""
        print(f"    {i}{mark}")
    if not nemotron:
        print("  No Nemotron models visible to this key.")
    if not s.nvidia_model:
        print("\nNext: copy one id above into NVIDIA_MODEL in .env, then re-run.")
        return 2
    if nemotron and s.nvidia_model not in ids:
        print(f"\nWARNING: NVIDIA_MODEL={s.nvidia_model!r} is not in the catalogue listing.")

    # --- Step 2: one tiny bounded completion ---
    print(f"\n[2/2] POST /chat/completions  model={s.nvidia_model} ...")
    body = {
        "model": s.nvidia_model,
        "messages": [{"role": "user", "content": 'Reply with exactly: {"ok": true}'}],
        "max_tokens": 32,
        "temperature": 0.0,
        # Low-latency classifier config: reasoning OFF. Ignored by endpoints
        # that do not support it.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    t0 = time.perf_counter()
    try:
        r = httpx.post(
            f"{s.nvidia_base_url}/chat/completions", headers=headers, json=body, timeout=30.0
        )
    except httpx.HTTPError as exc:
        print(f"  network error: {type(exc).__name__}: {exc}")
        return 1
    dt = (time.perf_counter() - t0) * 1000
    print(f"  HTTP {r.status_code} in {dt:.0f} ms")
    if r.status_code != 200:
        print(f"  body: {r.text[:500]}")
        if r.status_code in (401, 403):
            print("  -> key rejected or model not enabled for this account.")
        return 1
    data = r.json()
    msg = data["choices"][0]["message"]
    print(f"  content         : {msg.get('content', '')[:200]!r}")
    if msg.get("reasoning_content"):
        print("  reasoning_content: present (endpoint supports thinking; we keep it OFF)")
    print(f"  usage           : {json.dumps(data.get('usage', {}))}")
    print("\nOK: Nemotron classification is reachable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
