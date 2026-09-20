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
    assert body["decision"]["action"] == "end_simulated_call"  # what WhoDis did
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


# --------------------------------------------------------------------------
# offline replay
# --------------------------------------------------------------------------
def test_replay_is_never_entered_implicitly(client, stub_classifier):
    """A provider failure must degrade to review, not start playing a recording."""
    from app.classifier import degraded
    call_id = start_call(client)
    stub_classifier(lambda: degraded("provider_timeout", "nvidia/test"))
    body = send(client, call_id, "Hello there.", "req-1").json()
    assert body["mode"] != "fixture_replay"
    assert body["assessment"]["status"] == "degraded"


def test_unknown_replay_scenario_is_rejected(client):
    r = client.post("/api/calls", json={"replay_scenario": "not-a-real-scenario"})
    assert r.status_code == 400
    assert "no recorded replay" in r.json()["detail"]


def test_replay_runs_offline_and_is_labelled(client, monkeypatch):
    """Replay must work with no providers reachable at all."""
    from app import classifier as classifier_mod
    from app import providers as providers_mod

    async def never(*a, **k):
        raise AssertionError("replay must not call a provider")
    monkeypatch.setattr(classifier_mod, "classify", never)
    monkeypatch.setattr(providers_mod, "transcribe", never)

    from app import fixtures
    scenarios = fixtures.available_scenarios()
    if not scenarios:
        import pytest
        pytest.skip("no replay recorded; run eval/record_replay.py")

    view = client.post("/api/calls", json={"replay_scenario": scenarios[0]}).json()
    assert view["mode"] == "fixture_replay"

    body = send(client, view["call_id"], "anything at all", "req-1").json()
    assert body["mode"] == "fixture_replay"
    # The recorded caller line is used, not whatever was typed.
    assert body["caller_text"] != "anything at all"
    assert body["assessment"]["risk"] in ("no_warning_signs", "needs_review", "high_risk")


def test_replay_rejects_turns_past_the_end_of_the_recording(client):
    from app import fixtures
    scenarios = fixtures.available_scenarios()
    if not scenarios:
        import pytest
        pytest.skip("no replay recorded")
    view = client.post("/api/calls", json={"replay_scenario": scenarios[0]}).json()
    cid = view["call_id"]
    codes = []
    for i in range(6):
        r = send(client, cid, "x", f"req-{i}")
        codes.append(r.status_code)
        if r.status_code != 200:
            break
    assert 200 in codes
    assert codes[-1] == 409          # ran out of script, or the call ended


# --------------------------------------------------------------------------
# masking at the output boundary
# --------------------------------------------------------------------------
def test_codes_are_masked_in_responses_but_validation_used_raw_text(client, stub_classifier):
    """The quote is still verified against the RAW turn, then masked on the way out."""
    call_id = start_call(client)
    stub_classifier(assessment(
        risk="high_risk", credential_request=True,
        evidence=[ev("caller-1", "the code is 483920")]))
    body = send(client, call_id, "Read it back, the code is 483920.", "req-1").json()

    assert "483920" not in body["caller_text"]
    assert "number masked" in body["caller_text"]
    quote = body["assessment"]["evidence"][0]
    assert "483920" not in quote["quote"]
    assert quote["verified"] is True          # verified against raw text, before masking

    view = client.get(f"/api/calls/{call_id}").json()
    assert "483920" not in json_dump(view)


def json_dump(obj) -> str:
    import json
    return json.dumps(obj)


def test_card_and_ssn_shaped_numbers_are_masked(client, stub_classifier):
    call_id = start_call(client)
    stub_classifier(assessment(risk="needs_review"))
    body = send(client, call_id,
                "My card is 4539 1488 0343 6467 and my ssn is 123-45-6789.", "req-1").json()
    assert "4539" not in body["caller_text"]
    assert "123-45-6789" not in body["caller_text"]


def test_ordinary_numbers_survive_masking(client, stub_classifier):
    """Over-masking would make the transcript useless to the family."""
    call_id = start_call(client)
    stub_classifier(assessment(risk="no_warning_signs"))
    text = "I'll come by at 10:30, it's house number 42, and the fee is $20."
    body = send(client, call_id, text, "req-1").json()
    assert "10:30" in body["caller_text"]
    assert "42" in body["caller_text"]
    assert "$20" in body["caller_text"]
    assert "number masked" not in body["caller_text"]


def test_masking_is_consistent_between_quote_and_transcript(client, stub_classifier):
    """A masked quote must still be findable inside the masked turn, or the
    family view cannot highlight it."""
    call_id = start_call(client)
    stub_classifier(assessment(
        risk="high_risk", credential_request=True,
        evidence=[ev("caller-1", "read me the code 998877")]))
    send(client, call_id, "Please read me the code 998877 now.", "req-1")
    view = client.get(f"/api/calls/{call_id}").json()
    caller_turn = next(t for t in view["turns"] if t["role"] == "caller")
    quote = view["assessments"][0]["evidence"][0]["quote"]
    assert quote.lower() in caller_turn["text"].lower()


def test_a_spaced_card_number_masks_as_one_token(client, stub_classifier):
    """Four masks in a row is unreadable; the family has to be able to read this."""
    call_id = start_call(client)
    stub_classifier(assessment(risk="needs_review"))
    body = send(client, call_id, "My card is 4539 1488 0343 6467.", "req-1").json()
    assert body["caller_text"].count("number masked") == 1
