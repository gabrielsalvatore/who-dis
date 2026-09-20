"""Masks code- and account-like numbers on the way out.

Why at the output boundary rather than at capture: evidence quotes are validated
by matching the model's quote against the exact caller turn. Masking the stored
transcript would break that check. So the raw text lives only in memory for the
life of the session, and everything that leaves the process - API responses, the
family view, anything written to disk - goes through here.

Quotes and transcripts are masked with the *same* function, so a masked quote
still matches inside a masked turn and the family view can still highlight it.

Conservative by design. Over-masking makes a transcript unreadable, which is its
own failure: "I'll come by at 10:30 for number 42" must survive intact.
"""
from __future__ import annotations

import re

MASK = "•••• (number masked)"

# Card-like: 13-19 digits, optionally separated by spaces or dashes. Matched
# before _CODE so a spaced card number becomes ONE mask, not four.
_CARD = re.compile(r"(?<![\d.])(?:\d[ -]?){12,18}\d(?!\d)(?![.,]\d)")
# SSN-like: 3-2-4.
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
# Standalone runs of 4-8 digits: verification codes, PINs, account references.
# The trailing guard excludes decimals ("1.2345"), times and percentages, but NOT
# a sentence-final full stop - "read me the code 483920." must still be masked.
_CODE = re.compile(r"(?<![\d.,:/$£€-])\d{4,8}(?!\d)(?![.,]\d)(?![:/%-])")

# Things that are 4-8 digits but are not secrets.
_YEAR = re.compile(r"^(?:1[89]|20)\d{2}$")


def _code_repl(m: re.Match[str]) -> str:
    return m.group(0) if _YEAR.match(m.group(0)) else MASK


def mask_text(text: str) -> str:
    """Replace credential-shaped numbers. Leaves times, prices and years alone."""
    if not text:
        return text
    out = _SSN.sub(MASK, text)
    out = _CARD.sub(MASK, out)
    out = _CODE.sub(_code_repl, out)
    return out


def mask_assessment(assessment):
    """Return a masked copy. The original stays raw for quote validation."""
    copy = assessment.model_copy(deep=True)
    copy.summary = mask_text(copy.summary)
    for ev in copy.evidence:
        ev.quote = mask_text(ev.quote)
    return copy


def mask_alert(alert):
    if alert is None:
        return None
    copy = alert.model_copy(deep=True)
    copy.summary = mask_text(copy.summary)
    for ev in copy.evidence:
        ev.quote = mask_text(ev.quote)
    return copy


def mask_call_view(view):
    copy = view.model_copy(deep=True)
    for turn in copy.turns:
        turn.text = mask_text(turn.text)
    copy.assessments = [mask_assessment(a) for a in copy.assessments]
    copy.alerts = [mask_alert(a) for a in copy.alerts]
    for decision in copy.decisions:
        decision.reason = mask_text(decision.reason)
    return copy


def mask_turn_result(result):
    copy = result.model_copy(deep=True)
    copy.caller_text = mask_text(copy.caller_text)
    copy.assessment = mask_assessment(copy.assessment)
    copy.alert = mask_alert(copy.alert)
    copy.decision.reason = mask_text(copy.decision.reason)
    return copy
