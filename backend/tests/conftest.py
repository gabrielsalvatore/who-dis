import pytest
from fastapi.testclient import TestClient

from app import classifier as classifier_mod
from app import providers as providers_mod
from app.config import get_settings
from app.main import app
from app.schemas import Assessment, Evidence
from app.sessions import store


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture
def settings():
    s = get_settings()
    # Tests never reach a real provider; give the app enough config to take the
    # speech path so the mocked cache is exercised.
    s.nvidia_api_key = s.nvidia_api_key or "test-key"
    s.nvidia_model = s.nvidia_model or "nvidia/test-nemotron"
    s.elevenlabs_api_key = s.elevenlabs_api_key or "test-key"
    s.elevenlabs_voice_id = s.elevenlabs_voice_id or "test-voice"
    return s


@pytest.fixture
def fake_tts(monkeypatch):
    """Never call ElevenLabs in tests."""
    async def _get_or_create(self, text, client):
        return b"ID3-fake-mp3", True
    monkeypatch.setattr(providers_mod.PhraseCache, "get_or_create", _get_or_create)


@pytest.fixture
def stub_classifier(monkeypatch):
    """Install a canned assessment for the next classify() call."""
    holder = {}

    async def _classify(turns, settings, client):
        a = holder["assessment"]
        result = a() if callable(a) else a.model_copy(deep=True)
        # Mirror production: the backend always re-verifies quotes itself.
        classifier_mod.verify_evidence(result.evidence, turns)
        return result

    monkeypatch.setattr(classifier_mod, "classify", _classify)

    def _set(assessment):
        holder["assessment"] = assessment

    return _set


@pytest.fixture
def client(settings, fake_tts):
    with TestClient(app) as c:
        yield c


def assessment(**kw) -> Assessment:
    base = dict(risk="needs_review", scam_type="unknown", emergency_claimed=False,
                credential_request=False, evidence=[], summary="s", question_id=None)
    base.update(kw)
    return Assessment(**base)


def ev(turn_id: str, quote: str, signal: str = "otp_request") -> Evidence:
    return Evidence(turn_id=turn_id, quote=quote, signal=signal)
