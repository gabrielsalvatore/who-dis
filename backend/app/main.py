"""CallKind API.

Endpoints are intentionally few. The interesting logic lives in classifier.py
(what the model claims), policy.py (what CallKind does) and sessions.py (the
concurrency guards).
"""
from __future__ import annotations

import logging
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import classifier, fixtures, providers
from .masking import mask_call_view, mask_turn_result
from .config import get_settings
from .policy import CACHEABLE_PHRASES, CallState, advance_state, decide
from .schemas import (
    Alert,
    Assessment,
    CallView,
    HealthResponse,
    Mode,
    PolicyDecision,
    StageTimings,
    Turn,
    TurnResult,
)
from .sessions import store

logger = logging.getLogger("callkind")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.http = httpx.AsyncClient()
    app.state.phrase_cache = providers.PhraseCache(settings)
    logger.info(
        "CallKind starting | mode=%s classifier=%s speech=%s model=%s prompt=%s",
        settings.app_mode,
        settings.classifier_configured,
        settings.speech_configured,
        settings.nvidia_model or "-",
        classifier.PROMPT_VERSION,
    )
    for need in settings.setup_needs():
        logger.warning("setup need: %s", need)
    try:
        yield
    finally:
        await app.state.http.aclose()


app = FastAPI(title="CallKind", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _phrase_cache() -> providers.PhraseCache:
    return app.state.phrase_cache


def _http() -> httpx.AsyncClient:
    return app.state.http


# --------------------------------------------------------------------------
# health / setup
# --------------------------------------------------------------------------
def _lan_address() -> Optional[str]:
    """The IPv4 address another device on the same network would reach us on.

    Opening a UDP socket toward an address that is never routed (TEST-NET-1)
    makes the OS pick the interface the default route would use, without
    sending anything. There is no portable API that just asks for this.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.2)
            sock.connect(("192.0.2.1", 9))
            ip = str(sock.getsockname()[0])
    except OSError:
        return None
    return None if ip.startswith("127.") else ip


@app.get("/api/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Configuration only. Never returns credentials and never bills inference."""
    s = get_settings()
    cache = _phrase_cache()
    # Demo affordance: a judge scans this and watches the alert land on their own
    # phone. Only meaningful when uvicorn is bound to 0.0.0.0; the port comes from
    # the request so it is right whichever port the presenter used.
    ip = _lan_address()
    port = request.url.port or (443 if request.url.scheme == "https" else 80)
    return HealthResponse(
        lan_family_url=f"http://{ip}:{port}/family" if ip else None,
        app_mode=s.app_mode,
        classifier_configured=s.classifier_configured,
        speech_configured=s.speech_configured,
        stt_configured=s.stt_configured,
        classifier_model=s.nvidia_model or None,
        tts_model=s.elevenlabs_tts_model if s.speech_configured else None,
        stt_model=s.elevenlabs_stt_model if s.stt_configured else None,
        prompt_version=classifier.PROMPT_VERSION,
        filler_cached=cache.get(CACHEABLE_PHRASES["filler"]) is not None,
        setup_needs=s.setup_needs(),
    )


@app.post("/api/admin/warm-cache")
async def warm_cache() -> dict:
    """Generate the fixed assistant phrases once for the configured voice.

    Small and bounded: one short TTS call per phrase, only for phrases not
    already on disk.
    """
    s = get_settings()
    if not s.speech_configured:
        raise HTTPException(400, "ElevenLabs is not configured; see /api/health")
    result = await _phrase_cache().warm(CACHEABLE_PHRASES, _http())
    logger.info("phrase cache warmed: %s", {k: v for k, v in result.items() if k != "failed"})
    return {"voice_id": s.elevenlabs_voice_id, "tts_model": s.elevenlabs_tts_model, **result}


# --------------------------------------------------------------------------
# calls
# --------------------------------------------------------------------------
@app.post("/api/calls", response_model=CallView)
async def create_call(payload: Optional[dict] = None) -> CallView:
    """Create a call. Pass `replay_scenario` to deliberately enter offline replay.

    Replay is never entered implicitly: a provider failure degrades to review, it
    does not quietly start playing a recording.
    """
    payload = payload or {}
    settings = get_settings()
    replay_scenario = payload.get("replay_scenario")

    if replay_scenario or settings.app_mode == "fixture":
        replay_scenario = replay_scenario or (fixtures.available_scenarios() or [None])[0]
        if replay_scenario not in fixtures.available_scenarios():
            raise HTTPException(
                400,
                f"no recorded replay named {replay_scenario!r}; "
                f"available: {fixtures.available_scenarios()}",
            )
        session = store.create(mode="fixture_replay",
                               scenario_label=replay_scenario,
                               replay_scenario=replay_scenario)
        logger.info("call created %s mode=fixture_replay scenario=%s",
                    session.call_id, replay_scenario)
        return mask_call_view(session.to_view())

    session = store.create(mode="live_api", scenario_label=payload.get("scenario_label"))
    logger.info("call created %s mode=live_api", session.call_id)
    return mask_call_view(session.to_view())


@app.get("/api/replays")
async def list_replays() -> dict:
    """What offline replays exist, and when they were recorded."""
    return fixtures.metadata()


@app.get("/api/calls/current")
async def current_call() -> dict:
    """Lets a separately opened family window follow the active call across resets."""
    session = store.current()
    if session is None:
        return {"call_id": None, "status": None, "version": 0}
    return {
        "call_id": session.call_id,
        "status": session.status,
        "version": session.version,
        "mode": session.mode,
    }


@app.get("/api/calls/{call_id}", response_model=CallView)
async def get_call(call_id: str) -> CallView:
    session = store.get(call_id)
    if session is None:
        raise HTTPException(404, "call not found")
    return mask_call_view(session.to_view())


@app.delete("/api/calls/{call_id}")
async def delete_call(call_id: str) -> dict:
    """Reset: drops the synthetic session and everything stored with it."""
    if not store.delete(call_id):
        raise HTTPException(404, "call not found")
    logger.info("call deleted %s", call_id)
    return {"deleted": call_id}


# --------------------------------------------------------------------------
# the turn pipeline
# --------------------------------------------------------------------------
@app.post("/api/calls/{call_id}/turns", response_model=TurnResult)
async def submit_turn(
    call_id: str,
    request_id: str = Form(...),
    text: Optional[str] = Form(None),
    audio: Optional[UploadFile] = File(None),
) -> TurnResult:
    """One caller turn: transcribe if needed, classify, decide, speak.

    Serialised per session. A repeated `request_id` replays the stored result
    rather than re-running (and re-paying for) the pipeline.
    """
    session = store.get(call_id)
    if session is None:
        raise HTTPException(404, "call not found")

    settings = get_settings()
    t_start = time.perf_counter()

    # Read the upload before taking the lock so a slow client cannot hold it.
    audio_bytes = b""
    audio_name, audio_type = "", ""
    if audio is not None:
        audio_bytes = await audio.read()
        audio_name, audio_type = audio.filename or "turn.webm", audio.content_type or ""
        if len(audio_bytes) > settings.max_upload_bytes:
            raise HTTPException(413, "recording too large")

    if session.lock.locked():
        raise HTTPException(409, "a turn is already being processed for this call")

    async with session.lock:
        replay = session.cached_result(request_id)
        if replay is not None:
            logger.info("replaying cached result for request_id=%s", request_id)
            return replay

        if session.status == "ended":
            raise HTTPException(409, "this call has ended; reset to start a new one")

        timings = StageTimings()
        turn_mode: Mode = session.mode

        # --- 0. offline replay: no providers, no inference ----------------
        if session.replay_scenario is not None:
            result = _replay_turn(session, request_id)
            timings.total_ms = (time.perf_counter() - t_start) * 1000
            result.timings = timings
            result = mask_turn_result(result)
            session.cache_result(request_id, result)
            return result

        # --- 1. get the caller's words -----------------------------------
        if audio_bytes:
            t0 = time.perf_counter()
            try:
                caller_text = await providers.transcribe(
                    audio_bytes, audio_name, audio_type, settings, _http()
                )
            except providers.ProviderError as exc:
                raise HTTPException(502, f"Transcription failed: {exc}") from exc
            timings.transcribe_ms = (time.perf_counter() - t0) * 1000
            turn_mode = "live_api"
        elif text and text.strip():
            caller_text = text.strip()[: settings.max_transcript_chars]
            turn_mode = "text_fallback" if session.mode == "live_api" else session.mode
        else:
            raise HTTPException(400, "provide either an audio recording or text")

        caller_turn = session.add_turn(
            Turn(
                turn_id=session.next_caller_turn_id(),
                role="caller",
                text=caller_text,
                source="speech" if audio_bytes else "text",
            )
        )

        # --- 2. classify (Nemotron) --------------------------------------
        assessment = await classifier.classify(session.turns, settings, _http())
        timings.classify_ms = assessment.latency_ms

        # --- 3. decide (backend policy, not the model) --------------------
        session.state.max_turns = settings.max_turns_per_call
        decision, alert = decide(assessment, session.state, caller_turn)
        advance_state(session.state, decision, assessment)

        assistant_turn = session.add_turn(
            Turn(
                turn_id=session.next_assistant_turn_id(),
                role="assistant",
                text=decision.assistant_text,
                source="opening" if session.mode != "fixture_replay" else "fixture",
            )
        )

        # --- 4. speak ----------------------------------------------------
        audio_url: Optional[str] = None
        audio_error: Optional[str] = None
        audio_cached = False
        if settings.speech_configured:
            t0 = time.perf_counter()
            try:
                clip, was_cached = await _phrase_cache().get_or_create(
                    decision.assistant_text, _http()
                )
            except providers.ProviderError as exc:
                # The assessment is complete and must survive a speech failure.
                audio_error = str(exc)
                logger.warning("tts failed for %s: %s", assistant_turn.turn_id, exc)
            else:
                session.audio[assistant_turn.turn_id] = clip
                audio_url = f"/api/calls/{call_id}/audio/{assistant_turn.turn_id}"
                audio_cached = was_cached
                timings.tts_ms = (time.perf_counter() - t0) * 1000
        else:
            audio_error = "ElevenLabs voice is not configured"

        session.record(assessment, decision, timings, alert)
        timings.total_ms = (time.perf_counter() - t_start) * 1000

        result = TurnResult(
            call_id=call_id,
            turn_id=caller_turn.turn_id,
            caller_text=caller_text,
            assistant_text=decision.assistant_text,
            assessment=assessment,
            decision=decision,
            alert=alert,
            call_status=session.status,
            mode=turn_mode,
            audio_url=audio_url,
            audio_error=audio_error,
            audio_cached=audio_cached,
            timings=timings,
        )
        # Masked before it is cached, so a replayed request returns exactly what
        # the first one did.
        result = mask_turn_result(result)
        session.cache_result(request_id, result)
        logger.info(
            "turn %s/%s risk=%s action=%s classify=%sms total=%sms",
            call_id, caller_turn.turn_id, assessment.risk, decision.action,
            round(timings.classify_ms or 0), round(timings.total_ms or 0),
        )
        return result


def _replay_turn(session, request_id: str) -> TurnResult:
    """Advance one step through a recorded scenario. Never calls a provider."""
    step = fixtures.step(session.replay_scenario or "", session.replay_index)
    if step is None:
        raise HTTPException(409, "this replay has no further recorded turns")
    session.replay_index += 1

    assessment = Assessment(**step["assessment"])
    decision = PolicyDecision(**step["decision"])
    alert = Alert(**step["alert"]) if step.get("alert") else None

    caller_turn = session.add_turn(
        Turn(turn_id=session.next_caller_turn_id(), role="caller",
             text=step["caller_text"], source="fixture")
    )
    assistant_turn = session.add_turn(
        Turn(turn_id=session.next_assistant_turn_id(), role="assistant",
             text=decision.assistant_text, source="fixture")
    )
    session.record(assessment, decision, StageTimings(), alert)

    audio_url = None
    cache = _phrase_cache()
    if cache.get(decision.assistant_text) is not None:
        session.audio[assistant_turn.turn_id] = cache.get(decision.assistant_text)  # type: ignore[arg-type]
        audio_url = f"/api/calls/{session.call_id}/audio/{assistant_turn.turn_id}"

    return TurnResult(
        call_id=session.call_id,
        turn_id=caller_turn.turn_id,
        caller_text=step["caller_text"],
        assistant_text=decision.assistant_text,
        assessment=assessment,
        decision=decision,
        alert=alert,
        call_status=session.status,
        mode="fixture_replay",
        audio_url=audio_url,
        audio_cached=audio_url is not None,
    )


# --------------------------------------------------------------------------
# audio
# --------------------------------------------------------------------------
@app.get("/api/calls/{call_id}/audio/{turn_id}")
async def get_turn_audio(call_id: str, turn_id: str) -> Response:
    session = store.get(call_id)
    if session is None:
        raise HTTPException(404, "call not found")
    clip = session.audio.get(turn_id)
    if clip is None:
        raise HTTPException(404, "no audio for that turn")
    return Response(content=clip, media_type="audio/mpeg",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/audio/phrase/{name}")
async def get_phrase_audio(name: str) -> Response:
    """Serves a cached fixed phrase, e.g. the filler. Generates on first request."""
    text = CACHEABLE_PHRASES.get(name)
    if text is None:
        raise HTTPException(404, "unknown phrase")
    settings = get_settings()
    if not settings.speech_configured:
        raise HTTPException(503, "ElevenLabs voice is not configured")
    try:
        clip, _ = await _phrase_cache().get_or_create(text, _http())
    except providers.ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return Response(content=clip, media_type="audio/mpeg",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.post("/api/calls/{call_id}/audio/{turn_id}/retry")
async def retry_turn_audio(call_id: str, turn_id: str) -> dict:
    """Retry speech for a turn whose assessment succeeded but whose TTS failed."""
    session = store.get(call_id)
    if session is None:
        raise HTTPException(404, "call not found")
    turn = next((t for t in session.turns if t.turn_id == turn_id), None)
    if turn is None or turn.role != "assistant":
        raise HTTPException(404, "no such assistant turn")
    try:
        clip, cached = await _phrase_cache().get_or_create(turn.text, _http())
    except providers.ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    session.audio[turn_id] = clip
    return {"audio_url": f"/api/calls/{call_id}/audio/{turn_id}", "cached": cached}


# --------------------------------------------------------------------------
# optional single-process serving of the built frontend
# --------------------------------------------------------------------------
if FRONTEND_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/")
    @app.get("/family")
    async def spa_index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")
