"""Generate any missing fixed assistant phrases. Safe to re-run; skips what exists.

  .venv/bin/python backend/scripts/warm_cache.py

Does not need the server to be running.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.policy import CACHEABLE_PHRASES  # noqa: E402
from app.providers import PhraseCache  # noqa: E402


async def main() -> int:
    s = get_settings()
    if not s.speech_configured:
        print("ElevenLabs is not configured; see .env")
        return 2
    cache = PhraseCache(s)
    async with httpx.AsyncClient() as client:
        result = await cache.warm(CACHEABLE_PHRASES, client)
    print(f"voice={s.elevenlabs_voice_id} model={s.elevenlabs_tts_model}")
    print(f"  created        : {result['created'] or 'none'}")
    print(f"  already cached : {len(result['already_cached'])}")
    print(f"  failed         : {result['failed'] or 'none'}")
    print(f"  elapsed        : {result['elapsed_ms']} ms")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
