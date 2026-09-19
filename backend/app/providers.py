"""ElevenLabs speech-in / speech-out, plus the fixed-phrase audio cache.

Request shapes verified against the primary docs on 2026-09-19:
  STT: POST /v1/speech-to-text  - multipart, fields `file` + `model_id`,
       header `xi-api-key`; transcript is response field `text`.
  TTS: POST /v1/text-to-speech/{voice_id} - JSON {text, model_id, output_format},
       header `xi-api-key`; returns raw audio bytes.

Only the small set of fixed assistant phrases is cached (see policy.CACHEABLE_PHRASES).
Cached audio is a *recording of a fixed phrase*, never a model output, and the API
labels it as such so the UI cannot present it as inference.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Optional

import httpx

from .config import Settings

ELEVEN_BASE = "https://api.elevenlabs.io"
OUTPUT_FORMAT = "mp3_44100_128"


class ProviderError(Exception):
    """Raised with a short, safe summary. Never contains key material."""


# --------------------------------------------------------------------------
# speech to text
# --------------------------------------------------------------------------
async def transcribe(
    audio: bytes,
    filename: str,
    content_type: str,
    settings: Settings,
    client: httpx.AsyncClient,
) -> str:
    if not settings.stt_configured:
        raise ProviderError("ElevenLabs API key is not configured")
    if not audio:
        raise ProviderError("empty audio upload")
    if len(audio) > settings.max_upload_bytes:
        raise ProviderError(
            f"audio upload too large ({len(audio)} bytes > {settings.max_upload_bytes})"
        )

    files = {"file": (filename or "turn.webm", audio, content_type or "audio/webm")}
    data = {"model_id": settings.elevenlabs_stt_model}
    try:
        resp = await client.post(
            f"{ELEVEN_BASE}/v1/speech-to-text",
            headers={"xi-api-key": settings.elevenlabs_api_key},
            files=files,
            data=data,
            timeout=settings.stt_timeout_s,
        )
    except httpx.TimeoutException as exc:
        raise ProviderError("transcription timed out") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"transcription network error: {type(exc).__name__}") from exc

    if resp.status_code != 200:
        raise ProviderError(_safe_http_summary("transcription", resp))

    try:
        text = (resp.json().get("text") or "").strip()
    except ValueError as exc:
        raise ProviderError("transcription returned a non-JSON response") from exc
    if not text:
        raise ProviderError("no speech detected in that recording")
    return text[: settings.max_transcript_chars]


# --------------------------------------------------------------------------
# text to speech
# --------------------------------------------------------------------------
async def synthesize(
    text: str,
    settings: Settings,
    client: httpx.AsyncClient,
) -> bytes:
    if not settings.speech_configured:
        raise ProviderError("ElevenLabs voice is not configured")
    try:
        resp = await client.post(
            f"{ELEVEN_BASE}/v1/text-to-speech/{settings.elevenlabs_voice_id}",
            headers={
                "xi-api-key": settings.elevenlabs_api_key,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": settings.elevenlabs_tts_model,
                "output_format": OUTPUT_FORMAT,
            },
            timeout=settings.tts_timeout_s,
        )
    except httpx.TimeoutException as exc:
        raise ProviderError("speech generation timed out") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"speech network error: {type(exc).__name__}") from exc

    if resp.status_code != 200:
        raise ProviderError(_safe_http_summary("speech generation", resp))
    if not resp.content:
        raise ProviderError("speech generation returned no audio")
    return resp.content


def _safe_http_summary(what: str, resp: httpx.Response) -> str:
    """A short error summary safe to show a user and to log."""
    detail = ""
    try:
        body = resp.json()
        if isinstance(body, dict):
            d = body.get("detail")
            if isinstance(d, dict):
                detail = str(d.get("message") or d.get("status") or "")
            elif d:
                detail = str(d)
    except ValueError:
        pass
    detail = (detail or "")[:160]
    return f"{what} failed (HTTP {resp.status_code}){': ' + detail if detail else ''}"


# --------------------------------------------------------------------------
# fixed-phrase audio cache
# --------------------------------------------------------------------------
class PhraseCache:
    """On-disk cache of the fixed assistant phrases for one voice+model pair.

    Keyed by (voice, tts model, exact text) so changing the voice regenerates
    rather than silently serving the old one.
    """

    def __init__(self, settings: Settings) -> None:
        self.dir = settings.audio_cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self._manifest_path = self.dir / "manifest.json"
        self._manifest: dict[str, str] = {}
        if self._manifest_path.exists():
            try:
                self._manifest = json.loads(self._manifest_path.read_text())
            except ValueError:
                self._manifest = {}

    def _key(self, text: str) -> str:
        raw = f"{self.settings.elevenlabs_voice_id}|{self.settings.elevenlabs_tts_model}|{text}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def path_for(self, text: str) -> Path:
        return self.dir / f"{self._key(text)}.mp3"

    def get(self, text: str) -> Optional[bytes]:
        p = self.path_for(text)
        if p.exists() and p.stat().st_size > 0:
            return p.read_bytes()
        return None

    def put(self, text: str, audio: bytes) -> None:
        p = self.path_for(text)
        p.write_bytes(audio)
        self._manifest[self._key(text)] = text[:120]
        self._manifest_path.write_text(json.dumps(self._manifest, indent=2))

    async def get_or_create(
        self, text: str, client: httpx.AsyncClient
    ) -> tuple[bytes, bool]:
        """Return (audio, was_cached)."""
        cached = self.get(text)
        if cached is not None:
            return cached, True
        audio = await synthesize(text, self.settings, client)
        self.put(text, audio)
        return audio, False

    async def warm(self, phrases: dict[str, str], client: httpx.AsyncClient) -> dict:
        """Pre-generate any missing fixed phrases. Safe to call repeatedly."""
        created, cached, failed = [], [], {}
        t0 = time.perf_counter()
        for name, text in phrases.items():
            if self.get(text) is not None:
                cached.append(name)
                continue
            try:
                audio = await synthesize(text, self.settings, client)
            except ProviderError as exc:
                failed[name] = str(exc)
                continue
            self.put(text, audio)
            created.append(name)
        return {
            "created": created,
            "already_cached": cached,
            "failed": failed,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000),
        }
