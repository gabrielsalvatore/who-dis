"""Live comparison against the frozen keyword baseline.

This is a comparison and nothing else. It never feeds the policy: it runs in
its own request, after the real turn has already been decided and returned,
over a CallState of its own. The baseline itself lives in
`eval/keyword_baseline.py`, is frozen at `kw-v1`, and is imported here rather
than copied so there is exactly one published copy of those rules.

The point it makes on stage is `dev-08`: a real bank calling to warn a customer
never to read out a one time code. kw-v1 matches the words and hangs up on the
bank. WhoDis reads who is asking whom to do what, and does not.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from .masking import mask_text
from .policy import CallState, advance_state, decide
from .schemas import Turn

_EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"

try:
    if str(_EVAL_DIR) not in sys.path:
        sys.path.append(str(_EVAL_DIR))
    from keyword_baseline import BASELINE_VERSION, classify_keywords  # type: ignore[import-not-found]
except ImportError:  # eval/ not shipped alongside the app
    BASELINE_VERSION: Optional[str] = None
    classify_keywords = None


def available() -> bool:
    return classify_keywords is not None


def _whole_words(quote: str, source: str) -> str:
    """Trim a quote to whole words for display.

    kw-v1 quotes a fixed character window around whatever it matched, so a quote
    can start or end mid-word. Only the presentation changes here; the baseline's
    own matching is left exactly as it was frozen.
    """
    start = source.find(quote)
    if start == -1:
        return quote
    out = quote
    if start > 0 and not source[start - 1].isspace() and " " in out:
        out = "\u2026" + out.split(" ", 1)[1]
    end = start + len(quote)
    if end < len(source) and not source[end].isspace() and " " in out:
        out = out.rsplit(" ", 1)[0] + "\u2026"
    return out


def compare(turns: list[Turn]) -> dict:
    """Replay a transcript through kw-v1 and the same policy, from a fresh state.

    Recomputed from the transcript every time rather than stored, so there is no
    second copy of call state that could drift out of step with the real one or
    be mistaken for it. kw-v1 is pure regex over a handful of turns, so this is
    cheap enough to do on demand.
    """
    if classify_keywords is None:
        raise RuntimeError("keyword baseline is not available")

    state = CallState()
    prefix: list[Turn] = []
    rows: list[dict] = []
    ended_at: Optional[str] = None

    for turn in turns:
        prefix.append(turn)
        if turn.role != "caller":
            continue
        assessment = classify_keywords(prefix)
        by_turn = {t.turn_id: t.text for t in prefix}
        decision, alert = decide(assessment, state, turn)
        advance_state(state, decision, assessment)
        rows.append({
            "turn_id": turn.turn_id,
            "risk": assessment.risk,
            "action": decision.action,
            "ends_call": decision.ends_call,
            "alert_level": alert.level if alert else None,
            "matched": [
                mask_text(_whole_words(e.quote, by_turn.get(e.turn_id, "")))
                for e in assessment.evidence
            ],
        })
        if decision.ends_call:
            # Under kw-v1 the caller would have been hung up on here, so the
            # later turns of this call never happen. Stop rather than score
            # turns the baseline would not have heard.
            ended_at = turn.turn_id
            break

    return {"baseline_version": BASELINE_VERSION, "ended_at_turn_id": ended_at, "turns": rows}
