"""Classifier failure-path tests: timeouts, capacity errors, fallback, budget.

These drive the real `classify()` against a stubbed transport, so the retry and
fallback logic is exercised rather than mocked away.
"""
import asyncio
import json

import httpx
import pytest

from app import classifier as clf
from app.config import get_settings
from app.schemas import Turn

GOOD = {
    "risk": "high_risk", "scam_type": "bank_impersonation", "emergency_claimed": False,
    "credential_request": True,
    "evidence": [{"turn_id": "caller-1", "quote": "read me the code", "signal": "otp_request"}],
    "summary": "Caller asked for a code.", "question_id": None,
}


def turns():
    return [
        Turn(turn_id="assistant-0", role="assistant", text="Who's calling?", source="opening"),
        Turn(turn_id="caller-1", role="caller", text="Please read me the code.", source="text"),
    ]


def settings_for(primary="nvidia/primary", fallback=""):
    s = get_settings()
    s.nvidia_api_key = "test-key"
    s.nvidia_model = primary
    s.nvidia_model_fallback = fallback
    s.classify_timeout_s = 0.5
    s.classify_total_budget_s = 2.0
    return s


def responder(script):
    """script: list of callables or (status, payload) tuples, consumed in order."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        item = script[min(len(calls) - 1, len(script) - 1)]
        if callable(item):
            return item(request)
        status, payload = item
        if status == 200:
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})
        return httpx.Response(status, json={"error": {"message": "ResourceExhausted"}})

    return handler, calls


@pytest.mark.asyncio
async def test_timeout_degrades_to_needs_review_never_to_safe():
    def timeout(request):
        raise httpx.ReadTimeout("too slow", request=request)
    handler, calls = responder([timeout])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        a = await clf.classify(turns(), settings_for(), c)
    assert a.status == "degraded"
    assert a.risk == "needs_review"
    assert "timeout" in (a.degraded_reason or "")


@pytest.mark.asyncio
async def test_capacity_error_is_retried_once_then_succeeds():
    handler, calls = responder([(503, None), (200, GOOD)])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        a = await clf.classify(turns(), settings_for(), c)
    assert a.status == "ok"
    assert a.risk == "high_risk"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_persistent_capacity_error_falls_back_to_the_second_model():
    """503 is exactly what the hosted endpoints return under load."""
    def handler(request):
        model = json.loads(request.content)["model"]
        if model == "nvidia/primary":
            return httpx.Response(503, json={"error": {"message": "ResourceExhausted"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(GOOD)}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        a = await clf.classify(turns(), settings_for(fallback="nvidia/secondary"), c)
    assert a.status == "ok"
    assert a.model_id == "nvidia/secondary"
    assert a.used_fallback_model is True       # a fallback is visible, never silent


@pytest.mark.asyncio
async def test_both_models_failing_still_degrades_to_review():
    handler, calls = responder([(503, None)])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        a = await clf.classify(turns(), settings_for(fallback="nvidia/secondary"), c)
    assert a.status == "degraded"
    assert a.risk == "needs_review"


@pytest.mark.asyncio
async def test_budget_stops_retrying_instead_of_stacking_timeouts():
    """A hung endpoint must not cost timeout x retries x models of dead air.

    The stub actually spends wall-clock time, because the budget is measured in
    wall-clock time; an instantly-raising mock would not exercise it at all.
    """
    calls = []

    async def slow_timeout(request):
        calls.append(json.loads(request.content)["model"])
        await asyncio.sleep(0.25)
        raise httpx.ReadTimeout("hang", request=request)

    s = settings_for(fallback="nvidia/secondary")
    s.classify_timeout_s = 1.0
    s.classify_total_budget_s = 0.1        # gone before the retry could start
    async with httpx.AsyncClient(transport=httpx.MockTransport(slow_timeout)) as c:
        a = await clf.classify(turns(), s, c)
    assert a.status == "degraded"
    assert a.risk == "needs_review"
    assert "budget_exhausted" in (a.degraded_reason or "")
    assert len(calls) == 1                 # no retry, no fallback: budget was gone


async def test_budget_allows_a_retry_when_there_is_room():
    """The ceiling must not be so tight that it kills a legitimate retry."""
    calls = []

    async def slow_timeout(request):
        calls.append(json.loads(request.content)["model"])
        await asyncio.sleep(0.05)
        raise httpx.ReadTimeout("hang", request=request)

    s = settings_for()
    s.classify_timeout_s = 1.0
    s.classify_total_budget_s = 5.0
    async with httpx.AsyncClient(transport=httpx.MockTransport(slow_timeout)) as c:
        a = await clf.classify(turns(), s, c)
    assert a.status == "degraded"
    assert len(calls) == 2                 # original + one retry, then stop


@pytest.mark.asyncio
async def test_non_transient_error_is_not_retried():
    handler, calls = responder([(401, None)])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        a = await clf.classify(turns(), settings_for(), c)
    assert a.status == "degraded"
    assert len(calls) == 1                 # 401 will not fix itself


@pytest.mark.asyncio
async def test_garbage_output_degrades_rather_than_guessing():
    def junk(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "sorry, I can't"}}]})
    handler, calls = responder([junk])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        a = await clf.classify(turns(), settings_for(), c)
    assert a.status == "degraded"
    assert a.risk == "needs_review"
