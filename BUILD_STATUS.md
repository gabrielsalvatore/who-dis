# BUILD_STATUS

Progress log for CallKind. Newest entry last. Purpose: resume work after a context reset.

Deadline note: build started 2026-09-19 ~16:50 local, ~17 h budget → feature freeze target
2026-09-20 ~06:50, submission by ~09:50. **Reconfirm the real SteelHacks XIII deadline.**

---

## M0 — scaffold + provider access (hour 0–1) — IN PROGRESS

Done:
- `git init`; `.gitignore` excludes `.env`, venvs, `node_modules`, generated audio cache, eval output.
- Build spec preserved verbatim at `docs/BUILD_SPEC.md`.
- `.env.example` written with placeholders only; local `.env` created (git-ignored, empty values).
- Python 3.12 venv at `.venv` via `uv`; backend deps installed (fastapi, httpx, pydantic, pytest…).
- `backend/app/config.py` — settings read from env, missing keys reported as *setup needs*
  rather than import-time crashes.
- Provider request shapes verified against primary docs (2026-09-19):
  - **STT**: `POST https://api.elevenlabs.io/v1/speech-to-text`, `xi-api-key`,
    multipart fields `file` + `model_id`; transcript in response field `text`.
  - **TTS**: `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}`, `xi-api-key`,
    JSON `{text, model_id, output_format}`, default `mp3_44100_128`; returns raw audio.
  - **ElevenLabs model ids**: STT `scribe_v2` (current; `scribe_v1` deprecated).
    TTS `eleven_flash_v2_5` = fastest, correct choice here (`eleven_turbo_*` deprecated).
  - **NVIDIA**: OpenAI-compatible `POST {base}/chat/completions`, bearer auth. Supports
    `chat_template_kwargs.enable_thinking` — we set it **False** for low-latency classification.
    The build.nvidia.com page renders its model id client-side, so the id was NOT readable from
    the docs; it must come from `GET /v1/models` on Gabriel's own key.
- `backend/scripts/smoke_nvidia.py`, `backend/scripts/smoke_elevenlabs.py` — tiny access checks.
  Both run and fail cleanly with "BLOCKED: key empty" (expected; no keys yet).

Blocked on Gabriel (does not block other work):
- `NVIDIA_API_KEY` + `NVIDIA_MODEL` (nemotron id from the smoke script's catalogue listing)
- `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` (stock voice id from the smoke script's listing)

## M1 — text-turn vertical slice (next)
Not started.
