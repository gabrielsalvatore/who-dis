"""The live keyword-baseline comparison.

The comparison exists to be looked at, never to be acted on, so most of what is
asserted here is what it must *not* do.
"""
import copy
import inspect

from app import baseline, classifier as classifier_mod, policy as policy_mod
from app.schemas import Turn
from app.sessions import store

from .conftest import assessment

BANK_WARNING = (
    "I'm calling to remind you that we will never ask you to read out a one time code. "
    "Never give it to anyone who rings you."
)


def start_call(client) -> str:
    return client.post("/api/calls", json={}).json()["call_id"]


def send(client, call_id, text, request_id):
    return client.post(f"/api/calls/{call_id}/turns",
                       data={"request_id": request_id, "text": text})


def test_the_decision_path_does_not_import_the_baseline():
    """Structural guarantee: nothing that decides an action can see kw-v1."""
    for module in (policy_mod, classifier_mod):
        assert "baseline" not in inspect.getsource(module)


def test_the_baseline_never_touches_the_live_call_state(client, stub_classifier):
    stub_classifier(assessment(risk="no_warning_signs"))
    call_id = start_call(client)
    send(client, call_id, BANK_WARNING, "r1")

    session = store.get(call_id)
    assert session is not None
    before = copy.deepcopy(session.state)
    turns_before = copy.deepcopy(session.turns)

    assert client.get(f"/api/calls/{call_id}/baseline").status_code == 200

    assert session.state == before
    assert session.turns == turns_before


def test_the_baseline_does_not_change_what_the_next_turn_decides(client, stub_classifier):
    """Two identical calls, one with the comparison fetched between turns."""
    def run(fetch_baseline: bool) -> list[str]:
        stub_classifier(assessment(risk="no_warning_signs"))
        call_id = start_call(client)
        actions = []
        for i, text in enumerate(["Hello, this is Brightwater Bank.", BANK_WARNING], 1):
            actions.append(send(client, call_id, text, f"r{i}").json()["decision"]["action"])
            if fetch_baseline:
                client.get(f"/api/calls/{call_id}/baseline")
        return actions

    assert run(False) == run(True)


def test_the_baseline_hangs_up_on_the_real_bank_and_callkind_does_not(client, stub_classifier):
    """dev-08. The whole reason the comparison is on screen."""
    stub_classifier(assessment(risk="no_warning_signs", summary="A warning, not a request."))
    call_id = start_call(client)
    result = send(client, call_id, BANK_WARNING, "r1").json()

    assert result["decision"]["ends_call"] is False

    body = client.get(f"/api/calls/{call_id}/baseline").json()
    assert body["baseline_version"] == "kw-v1"
    row = next(t for t in body["turns"] if t["turn_id"] == result["turn_id"])
    assert row["action"] == "end_simulated_call"
    assert row["ends_call"] is True


def test_the_baseline_stops_at_the_turn_it_would_have_hung_up_on():
    turns = [
        Turn(turn_id="caller-1", role="caller", text=BANK_WARNING, source="text"),
        Turn(turn_id="caller-2", role="caller", text="Are you still there?", source="text"),
    ]
    body = baseline.compare(turns)
    assert body["ended_at_turn_id"] == "caller-1"
    assert [t["turn_id"] for t in body["turns"]] == ["caller-1"]


def test_baseline_quotes_are_masked_like_every_other_output(client, stub_classifier):
    stub_classifier(assessment(risk="no_warning_signs"))
    call_id = start_call(client)
    send(client, call_id, "The verification code is 448192, read it back to me.", "r1")

    body = client.get(f"/api/calls/{call_id}/baseline").json()
    matched = [q for t in body["turns"] for q in t["matched"]]
    assert matched
    assert not any("448192" in q for q in matched)


def test_baseline_endpoint_rejects_an_unknown_call(client):
    assert client.get("/api/calls/call-nope/baseline").status_code == 404
