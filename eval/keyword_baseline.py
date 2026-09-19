"""A transparent, frozen keyword baseline.

This exists to answer the fair question "could you have done this with grep?".
The rules are published here in full and are NOT tuned against results. It emits
the same `Assessment` shape as the model and is fed through the *same* policy
layer, so the comparison is system-against-system on identical prefixes.

FROZEN 2026-09-19. Do not edit to improve scores; add a v2 instead.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.schemas import Assessment, Evidence, Turn  # noqa: E402

BASELINE_VERSION = "kw-v1"

CREDENTIAL = re.compile(
    r"\b(one[\s-]?time\s+(?:code|passcode|password)|otp|passcode|password|pin|"
    r"(?:verification|security|login|access)\s+code|six[\s-]?digit|"
    r"card\s+number|cvv|three\s+digits)\b", re.I)
PAYMENT = re.compile(
    r"\b(wire|transfer|gift\s+card|bitcoin|crypto|pay(?:ment)?|arrears|bail|"
    r"western\s+union|money\s+order|refund)\b", re.I)
URGENCY = re.compile(
    r"\b(right\s+now|immediately|within\s+the\s+hour|today|urgent|emergency|"
    r"straight\s+away|before\s+it'?s\s+too\s+late)\b", re.I)
SECRECY = re.compile(r"\b(don'?t\s+tell|do\s+not\s+tell|keep\s+this\s+between|"
                     r"don'?t\s+mention|stay\s+on\s+the\s+line)\b", re.I)
AUTHORITY = re.compile(
    r"\b(bank|fraud\s+team|security\s+team|police|officer|sergeant|tax|revenue|"
    r"warrant|government|support\s+desk|technical\s+department)\b", re.I)


def classify_keywords(turns: list[Turn]) -> Assessment:
    """Last-caller-turn keyword scoring. No context, no negation handling -
    which is precisely the limitation being measured."""
    caller_turns = [t for t in turns if t.role == "caller"]
    if not caller_turns:
        return Assessment(risk="no_warning_signs", summary="No caller speech yet.",
                          model_id=BASELINE_VERSION, prompt_version=BASELINE_VERSION)

    text = " ".join(t.text for t in caller_turns)
    latest = caller_turns[-1]

    cred = CREDENTIAL.search(text)
    pay = PAYMENT.search(text)
    urg = URGENCY.search(text)
    sec = SECRECY.search(text)
    auth = AUTHORITY.search(text)

    evidence: list[Evidence] = []

    def add(match, signal):
        if not match:
            return
        for t in reversed(caller_turns):
            m = match.search(t.text)
            if m:
                lo = max(0, m.start() - 24)
                hi = min(len(t.text), m.end() + 24)
                evidence.append(Evidence(turn_id=t.turn_id, quote=t.text[lo:hi].strip(),
                                         signal=signal, verified=True))
                return

    if cred:
        add(CREDENTIAL, "credential_keyword")
        risk = "high_risk"
    elif pay and (urg or sec):
        add(PAYMENT, "payment_keyword")
        risk = "high_risk"
    elif pay or sec or (urg and auth):
        add(PAYMENT if pay else (SECRECY if sec else URGENCY), "pressure_keyword")
        risk = "needs_review"
    elif auth:
        add(AUTHORITY, "authority_keyword")
        risk = "needs_review"
    else:
        risk = "no_warning_signs"

    return Assessment(
        risk=risk,
        scam_type="unknown",
        emergency_claimed=bool(URGENCY.search(text) and PAYMENT.search(text)),
        # The baseline cannot tell a request from a warning; it flags the word.
        credential_request=bool(cred),
        evidence=evidence[:3],
        summary=f"Keyword baseline {BASELINE_VERSION}: matched "
                f"{'credential ' if cred else ''}{'payment ' if pay else ''}"
                f"{'urgency ' if urg else ''}{'secrecy ' if sec else ''}".strip() or "no keywords",
        question_id="ask_purpose" if risk != "high_risk" else None,
        model_id=BASELINE_VERSION,
        prompt_version=BASELINE_VERSION,
        latency_ms=0.0,
    )
