"""Configuration. All provider keys live here, on the backend, never in the client."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


class Settings:
    """Plain settings object read from the environment.

    Deliberately not a pydantic BaseSettings: we want missing keys to be a
    reported *setup need* in /api/health, not an import-time crash.
    """

    def __init__(self) -> None:
        self.app_mode: str = os.getenv("APP_MODE", "live").strip().lower()

        self.nvidia_api_key: str = os.getenv("NVIDIA_API_KEY", "").strip()
        self.nvidia_base_url: str = os.getenv(
            "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
        ).strip().rstrip("/")
        self.nvidia_model: str = os.getenv("NVIDIA_MODEL", "").strip()
        # Second Nemotron used only when the primary returns a transient capacity
        # error. The hosted endpoints return 503 "Worker local total request limit
        # reached" under load, which would otherwise degrade a live demo turn.
        self.nvidia_model_fallback: str = os.getenv("NVIDIA_MODEL_FALLBACK", "").strip()

        self.elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "").strip()
        self.elevenlabs_voice_id: str = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
        self.elevenlabs_stt_model: str = os.getenv("ELEVENLABS_STT_MODEL", "scribe_v2").strip()
        self.elevenlabs_tts_model: str = os.getenv(
            "ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5"
        ).strip()

        self.allowed_origins: list[str] = [
            o.strip()
            for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
            if o.strip()
        ]

        # Bounds. Tuned for a demo, not for production throughput.
        self.max_upload_bytes: int = 8 * 1024 * 1024       # 8 MB audio upload cap
        self.max_transcript_chars: int = 1200              # per caller turn
        self.max_turns_per_call: int = 24
        # Per-attempt timeout. Measured p95 on the dev set is ~4.6 s, so 8 s is
        # generous for a healthy endpoint and short enough that a hung request
        # does not become a silent demo.
        self.classify_timeout_s: float = 8.0
        # Hard ceiling across the original attempt, the retry and the fallback
        # model. Once this is gone, degrade rather than keep trying.
        self.classify_total_budget_s: float = 12.0
        self.stt_timeout_s: float = 30.0
        self.tts_timeout_s: float = 20.0

        self.audio_cache_dir: Path = Path(__file__).resolve().parent / "audio_cache"

    # --- capability flags (safe to expose; never expose key material) ---
    @property
    def classifier_configured(self) -> bool:
        return bool(self.nvidia_api_key and self.nvidia_model)

    @property
    def speech_configured(self) -> bool:
        return bool(self.elevenlabs_api_key and self.elevenlabs_voice_id)

    @property
    def stt_configured(self) -> bool:
        return bool(self.elevenlabs_api_key)

    def setup_needs(self) -> list[str]:
        needs: list[str] = []
        if not self.nvidia_api_key:
            needs.append("NVIDIA_API_KEY is not set (Nemotron classification unavailable)")
        if not self.nvidia_model:
            needs.append("NVIDIA_MODEL is not set (run backend/scripts/smoke_nvidia.py to pick one)")
        if not self.elevenlabs_api_key:
            needs.append("ELEVENLABS_API_KEY is not set (no transcription, no speech)")
        if not self.elevenlabs_voice_id:
            needs.append(
                "ELEVENLABS_VOICE_ID is not set "
                "(run backend/scripts/smoke_elevenlabs.py to list stock voices)"
            )
        return needs


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
