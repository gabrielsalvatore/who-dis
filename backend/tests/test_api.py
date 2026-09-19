"""API tests. Providers are mocked; no network, no spend."""
import io

import pytest

from app import providers as providers_mod
from app.classifier import degraded

from .conftest import assessment, ev


def start_call(client) -> str:
    r = client.post("/api/calls", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["turns"][0]["turn_id"] == "assistant-0"     # opening line exists
    return body["call_id"]


def send(client, call_id, text, request_id):
    return client.post(f"/api/calls/{call_id}/turns",
                       data={"request_id": request_id, "text": text})


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------
def test_health_reports_config_without_leaking_credentials(client):
    body = client.get("/api/health").json()
    assert set(body) >= {"classifier_configured", "speech_configured", "prompt_version"}
    blob = repr(body).lower()
    assert "nvapi" not in blob and "sk_" not in blob
    for v in body.values():
        assert not (isinstance(v, str) and len(v) > 60)


# --------------------------------------------------------------------------
# the turn pipeline
# --------------------------------------------------------------------------
def test_full_turn_returns_assessment_and_decision_separately(client, stub_classifier):
    call_id = start_call(client)
    stub_classifier(assessment(risk="high_risk", credential_request=True,
                               evidence=[ev("caller-1", "read me the six digit code")]))
    r = send(client, call_id, "Please read me the six digit code.", "req-1")
    assert r.status_code == 200
    body = r.json()
    assert body["assessment"]["risk"] == "high_risk"          # what the model said
    assert body["decision"]["action"] == "end_simulated_call"  # what CallKind did
    assert body["call_status"] == "ended"
    assert body["alert"]["level"] == "urgent"
    assert body["assessment"]["evidence"][0]["verified"] is True


def test_duplicate_request_id_replays_and_does_not_duplicate_alerts(client, stub_classifier):
    call_id = start_call(client)
    stub_classifier(assessment(risk="needs_review", emergency_claimed=True,
                               evidence=[ev("caller-1", "I need money now", "emergency_claim")]))
    first = send(client, call_id, "I need money now, it's an emergency.", "req-dup")
    assert first.status_code == 200 and first.json()["cached"] is False

    second = send(client, call_id, "I need money now, it's an emergency.", "req-dup")
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert second.json()["alert"]["alert_id"] == first.json()["alert"]["alert_id"]

    view = client.get(f"/api/calls/{call_id}").json()
    assert len(view["alerts"]) == 1                 # not two
    assert len(view["assessments"]) == 1            # pipeline ran once
    assert sum(1 for t in view["turns"] if t["role"] == "caller") == 1


def test_distinct_request_ids_are_processed_separately(client, stub_classifier):
    call_id = start_call(client)
    stub_classifier(assessment(risk="no_warning_signs", question_id="ask_purpose"))
    assert send(client, call_id, "Hello there.", "req-a").status_code == 200
    assert send(client, call_id, "It's about a parcel.", "req-b").status_code == 200
    view = client.get(f"/api/calls/{call_id}").json()
    assert len(view["assessments"]) == 2


def test_turns_are_rejected_after_the_call_ends(client, stub_classifier):
    call_id = start_call(client)
    stub_classifier(assessment(risk="high_risk", credential_request=True,
                               evidence=[ev("caller-1", "tell me your password")]))
    assert send(client, call_id, "Just tell me your password.", "req-1").json()["call_status"] == "ended"

    r = send(client, call_id, "Are you still there?", "req-2")
    assert r.status_code == 409
    view = client.get(f"/api/calls/{call_id}").json()
    assert sum(1 for t in view["turns"] if t["role"] == "caller") == 1


def test_a_turn_needs_either_audio_or_text(client, stub_classifier):
    call_id = start_call(client)
    stub_classifier(assessment())
    assert send(client, call_id, "   ", "req-blank").status_code == 400


def test_unknown_call_id_is_404(client):
    assert client.get("/api/calls/call-nope").status_code == 404
    assert send(client, "call-nope", "hi", "r").status_code == 404


# --------------------------------------------------------------------------
# degraded + failure handling
# --------------------------------------------------------------------------
def test_provider_failure_routes_to_review_and_shows_a_degraded_status(client, stub_classifier):
    call_id = start_call(client)
    stub_classifier(lambda: degraded("provider_timeout", "nvidia/test"))
    body = send(client, call_id, "Hello, it's about your account.", "req-1").json()
    assert body["assessment"]["status"] == "degraded"
    assert body["assessment"]["risk"] == "needs_review"      # never "safe"
    assert body["decision"]["action"] == "request_family_review"
    assert body["call_status"] == "active"                   # never auto-ends
    assert body["alert"]["level"] == "review"


def test_tts_failure_preserves_the_assessment(client, stub_classifier, monkeypatch):
    async def boom(self, text, http):
        raise providers_mod.ProviderError("speech generation failed (HTTP 401)")
    monkeypatch.setattr(providers_mod.PhraseCache, "get_or_create", boom)

    call_id = start_call(client)
    stub_classifier(assessment(risk="needs_review", emergency_claimed=True))
    body = send(client, call_id, "It's an emergency, I need money.", "req-1").json()
    assert body["audio_url"] is None
    assert "speech generation failed" in body["audio_error"]
    assert body["assessment"]["risk"] == "needs_review"      # assessment survived
    assert body["decision"]["action"] == "request_family_review"
    assert body["assistant_text"]                            # text still shown


def test_transcription_failure_returns_502_and_records_no_turn(client, stub_classifier, monkeypatch):
    async def boom(*a, **k):
        raise providers_mod.ProviderError("no speech detected in that recording")
    monkeypatch.setattr(providers_mod, "transcribe", boom)

    call_id = start_call(client)
    stub_classifier(assessment())
    r = client.post(f"/api/calls/{call_id}/turns",
                    data={"request_id": "req-audio"},
                    files={"audio": ("turn.webm", io.BytesIO(b"\x00" * 64), "audio/webm")})
    assert r.status_code == 502
    assert "no speech detected" in r.json()["detail"]
    view = client.get(f"/api/calls/{call_id}").json()
    assert sum(1 for t in view["turns"] if t["role"] == "caller") == 0


def test_audio_upload_takes_the_speech_path_and_is_labelled_live(client, stub_classifier, monkeypatch):
    async def fake_transcribe(audio, name, ctype, settings, http):
        return "Read me the six digit code."
    monkeypatch.setattr(providers_mod, "transcribe", fake_transcribe)

    call_id = start_call(client)
    stub_classifier(assessment(risk="high_risk", credential_request=True,
                               evidence=[ev("caller-1", "Read me the six digit code")]))
    r = client.post(f"/api/calls/{call_id}/turns",
                    data={"request_id": "req-audio"},
                    files={"audio": ("turn.webm", io.BytesIO(b"\x00" * 64), "audio/webm")})
    body = r.json()
    assert body["mode"] == "live_api"
    assert body["caller_text"] == "Read me the six digit code."
    assert body["audio_url"].endswith("/audio/assistant-1")
    assert client.get(body["audio_url"]).status_code == 200


def test_typed_turn_is_labelled_text_fallback(client, stub_classifier):
    call_id = start_call(client)
    stub_classifier(assessment(risk="no_warning_signs"))
    assert send(client, call_id, "Hello.", "req-1").json()["mode"] == "text_fallback"


# --------------------------------------------------------------------------
# current-call tracking and reset
# --------------------------------------------------------------------------
def test_current_is_none_before_any_call(client):
    assert client.get("/api/calls/current").json()["call_id"] is None


def test_current_follows_a_new_session_after_reset(client, stub_classifier):
    first = start_call(client)
    assert client.get("/api/calls/current").json()["call_id"] == first

    assert client.delete(f"/api/calls/{first}").status_code == 200
    assert client.get("/api/calls/current").json()["call_id"] is None   # gone, not stale
    assert client.get(f"/api/calls/{first}").status_code == 404

    second = start_call(client)
    assert second != first
    current = client.get("/api/calls/current").json()
    assert current["call_id"] == second
    assert current["status"] == "active"


def test_creating_a_new_call_without_deleting_moves_current(client):
    first = start_call(client)
    second = start_call(client)
    assert client.get("/api/calls/current").json()["call_id"] == second
    assert client.get(f"/api/calls/{first}").status_code == 200   # old one still readable


def test_version_increments_so_pollers_can_diff(client, stub_classifier):
    call_id = start_call(client)
    v0 = client.get(f"/api/calls/{call_id}").json()["version"]
    stub_classifier(assessment(risk="no_warning_signs"))
    send(client, call_id, "Hello.", "req-1")
    assert client.get(f"/api/calls/{call_id}").json()["version"] > v0


def test_deleting_a_call_removes_its_stored_content(client, stub_classifier):
    call_id = start_call(client)
    stub_classifier(assessment(risk="needs_review", emergency_claimed=True))
    send(client, call_id, "I need money urgently.", "req-1")
    client.delete(f"/api/calls/{call_id}")
    assert client.get(f"/api/calls/{call_id}").status_code == 404
    assert client.delete(f"/api/calls/{call_id}").status_code == 404
