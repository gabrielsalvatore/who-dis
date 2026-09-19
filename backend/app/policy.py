"""The backend decision layer.

This is deliberately the only place that decides what CallKind *does*. The
classifier supplies observations; this module supplies actions. The separation
matters for two reasons:

  * A model that is confidently wrong cannot hang up on anyone by itself. Every
    escalation is gated on evidence the backend re-checked against the transcript.
  * The family view can show "what the model said" next to "what CallKind did",
    which is the whole point of the product.

Measured design note: on the hosted Nemotron endpoints the structured
`credential_request` field is markedly more reliable than the free-text `risk`
label (see eval/ and BUILD_STATUS.md), so the narrow end-call policy keys off
verified evidence, not off the model's chosen risk word.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from .schemas import (
    Alert,
    Assessment,
    Evidence,
    PolicyDecision,
    QUESTION_BANK,
    Turn,
)

# --- fixed assistant phrases. The backend picks one; nothing is generated. ---
OPENING_LINE = (
    "Hello, this is a call screening assistant answering on behalf of this household. "
    "May I ask who's calling and what it's about?"
)
DECLINE_CREDENTIAL = (
    "I'm not able to share verification codes, PINs or passwords, and neither is anyone "
    "here. I'm ending this call now and flagging it for the family to review."
)
REVIEW_URGENT = (
    "I can't confirm who you are, and I'm not able to act on an urgent request for money. "
    "I'm flagging this call for the family to review right away."
)
REVIEW_GENERAL = (
    "I'm not able to help with that directly. I'll pass this on for the family to review."
)
TAKE_MESSAGE = (
    "I can take a message and pass it on. Please say what you'd like me to tell them."
)
MESSAGE_CLOSE = (
    "Thank you, I've noted that and I'll pass it on. Goodbye."
)
DEGRADED_REVIEW = (
    "Sorry, I'm having trouble on my end. I'll pass this call on for the family to review."
)
CALL_LIMIT_CLOSE = (
    "I'll pass on what you've told me. Goodbye."
)

# Every fixed phrase that gets spoken, so TTS can be pre-cached once per voice.
CACHEABLE_PHRASES: dict[str, str] = {
    "filler": "One moment.",
    "opening": OPENING_LINE,
    "decline_credential": DECLINE_CREDENTIAL,
    "review_urgent": REVIEW_URGENT,
    "review_general": REVIEW_GENERAL,
    "take_message": TAKE_MESSAGE,
    "message_close": MESSAGE_CLOSE,
    "degraded_review": DEGRADED_REVIEW,
    "call_limit_close": CALL_LIMIT_CLOSE,
    **{f"q_{k}": v for k, v in QUESTION_BANK.items()},
}

MAX_FOLLOWUPS = 2

# Published, frozen lexical guard for the end-call policy. A verified quote must
# actually mention a credential before CallKind will hang up on it. This exists
# so that `credential_request=True` with an unrelated supporting quote downgrades
# to review instead of terminating a call.
CREDENTIAL_TERMS = re.compile(
    r"\b(one[\s-]?time\s+(?:code|password|pin)|"
    r"otp|passcode|pass\s?word|password|"
    r"pin(?:\s+number|\s+code)?|"
    r"(?:verification|security|login|log[\s-]?in|authentication|confirmation|access)\s+code|"
    r"code\s+(?:we|i|they)\s+(?:just\s+)?(?:sent|texted|messaged)|"
    r"(?:six|6|four|4|five|5|eight|8)[\s-]?digit\s+(?:code|number|pin)|"
    r"read\s+(?:it|the\s+code)\s+back)\b",
    re.IGNORECASE,
)


@dataclass
class CallState:
    """The slice of session state the policy needs. Kept tiny and explicit."""

    followups_asked: int = 0
    message_taken: bool = False
    purpose_asked: bool = False
    turn_count: int = 0
    max_turns: int = 24
    # Questions already put to this caller. Without this the classifier can pick
    # the same follow-up twice and the call loops on one question.
    asked_questions: set[str] = field(default_factory=set)
    # Headlines already raised, so a caller repeating an emergency claim does not
    # produce a fresh urgent alert on every turn.
    raised_headlines: set[str] = field(default_factory=set)

    def next_question(self, question_id: str | None) -> str | None:
        """The model's suggested question, unless we have already asked it."""
        if question_id and question_id in QUESTION_BANK and question_id not in self.asked_questions:
            return question_id
        return None


def supporting_credential_quote(assessment: Assessment) -> Evidence | None:
    """Return the verified quote that supports ending the call, if any.

    Requires all three: the model flagged a credential request, the quote was
    re-matched against the caller turn it named, and the quote itself names a
    credential. Anything less is not grounds for termination.
    """
    if not assessment.credential_request:
        return None
    for ev in assessment.verified_evidence:
        if CREDENTIAL_TERMS.search(ev.quote):
            return ev
    return None


def _alert(
    level: str,
    headline: str,
    assessment: Assessment,
    action: str,
    caller_turn_id: str | None,
) -> Alert:
    return Alert(
        alert_id=f"alert-{uuid.uuid4().hex[:8]}",
        level=level,  # type: ignore[arg-type]
        headline=headline,
        summary=assessment.summary or "No summary available.",
        evidence=list(assessment.verified_evidence),
        caller_turn_id=caller_turn_id,
        model_risk=assessment.risk,
        policy_action=action,  # type: ignore[arg-type]
    )


def _dedupe(state: CallState, alert: Alert | None) -> Alert | None:
    """Suppress a repeat of an alert this call has already raised.

    The action still stands - CallKind keeps refusing - but the family sees one
    alert per distinct concern rather than one per caller turn.
    """
    if alert is None:
        return None
    if alert.headline in state.raised_headlines:
        return None
    state.raised_headlines.add(alert.headline)
    return alert


def decide(
    assessment: Assessment,
    state: CallState,
    latest_caller_turn: Turn | None = None,
) -> tuple[PolicyDecision, Alert | None]:
    """Map a validated assessment plus call state onto one action.

    Ordered most-protective-first. Returns the decision and an alert if one
    should be raised.
    """
    caller_turn_id = latest_caller_turn.turn_id if latest_caller_turn else None

    # 1. Screening failed. Never conclude "safe", never end the call as though
    #    fraud were proven.
    if assessment.status == "degraded":
        decision = PolicyDecision(
            action="request_family_review",
            assistant_text=DEGRADED_REVIEW,
            reason=f"Screening unavailable ({assessment.degraded_reason}); "
                   "routed to review rather than assumed safe.",
            ends_call=False,
            alert_level="review",
        )
        return decision, _dedupe(state, _alert(
            "review", "Screening unavailable - please review this call",
            assessment, "request_family_review", caller_turn_id,
        ))

    # 2. The one narrow termination policy: a re-verified, credential-bearing
    #    request for a password / PIN / one-time code.
    quote = supporting_credential_quote(assessment)
    if quote is not None:
        decision = PolicyDecision(
            action="end_simulated_call",
            assistant_text=DECLINE_CREDENTIAL,
            reason=f"Caller directly requested a credential: \"{quote.quote}\" "
                   f"({quote.turn_id}). Verified against the transcript.",
            ends_call=True,
            alert_level="urgent",
        )
        return decision, _dedupe(state, _alert(
            "urgent", "Call ended: caller asked for a security code",
            assessment, "end_simulated_call", quote.turn_id,
        ))

    # 3. High risk without a verified credential request: review, do not hang up.
    if assessment.risk == "high_risk":
        decision = PolicyDecision(
            action="request_family_review",
            assistant_text=REVIEW_URGENT if assessment.emergency_claimed else REVIEW_GENERAL,
            reason="Model reported high risk; no verified credential request, so the call "
                   "is sent for review rather than ended.",
            ends_call=False,
            alert_level="urgent",
        )
        return decision, _dedupe(state, _alert(
            "urgent", "High risk call - please review",
            assessment, "request_family_review", caller_turn_id,
        ))

    # 4. A claimed emergency goes to a person promptly and is never authenticated
    #    by the model.
    if assessment.emergency_claimed:
        decision = PolicyDecision(
            action="request_family_review",
            assistant_text=REVIEW_URGENT,
            reason="Caller claimed an urgent emergency. CallKind cannot verify who is "
                   "calling, so a person is asked to review it immediately.",
            ends_call=False,
            alert_level="urgent",
        )
        return decision, _dedupe(state, _alert(
            "urgent", "Urgent: caller claims a family emergency",
            assessment, "request_family_review", caller_turn_id,
        ))

    # 5. Out of turns.
    if state.turn_count >= state.max_turns:
        return PolicyDecision(
            action="take_message",
            assistant_text=CALL_LIMIT_CLOSE,
            reason="Reached the turn limit for this screened call.",
            ends_call=True,
        ), None

    # 6. Needs review: a couple of neutral follow-ups, then escalate or take a message.
    if assessment.risk == "needs_review":
        question_id = state.next_question(assessment.question_id)
        if state.followups_asked < MAX_FOLLOWUPS and question_id:
            return PolicyDecision(
                action="continue",
                assistant_text=QUESTION_BANK[question_id],
                reason=f"Unclear so far; asking a neutral follow-up "
                       f"({state.followups_asked + 1} of {MAX_FOLLOWUPS}).",
                ends_call=False,
            ), None
        if assessment.verified_evidence:
            decision = PolicyDecision(
                action="request_family_review",
                assistant_text=REVIEW_GENERAL,
                reason="Concerns remain after follow-up questions; sending to the family "
                       "to review.",
                ends_call=False,
                alert_level="review",
            )
            return decision, _dedupe(state, _alert(
                "review", "Please review this call",
                assessment, "request_family_review", caller_turn_id,
            ))
        return _take_message(state), None

    # 7. No warning signs. Never a verified identity, never an auto-transfer.
    question_id = state.next_question(assessment.question_id)
    if not state.purpose_asked and question_id:
        return PolicyDecision(
            action="continue",
            assistant_text=QUESTION_BANK[question_id],
            reason="No warning signs detected; identity unverified. Asking the caller's "
                   "purpose before taking a message.",
            ends_call=False,
        ), None
    return _take_message(state), None


def _take_message(state: CallState) -> PolicyDecision:
    """Offer to take a message, then close once one has been left."""
    if state.message_taken:
        return PolicyDecision(
            action="take_message",
            assistant_text=MESSAGE_CLOSE,
            reason="Message recorded. No warning signs detected; identity unverified.",
            ends_call=True,
        )
    return PolicyDecision(
        action="take_message",
        assistant_text=TAKE_MESSAGE,
        reason="No warning signs detected; identity unverified. Offering to take a message.",
        ends_call=False,
    )


def advance_state(state: CallState, decision: PolicyDecision, assessment: Assessment) -> None:
    """Fold a decision back into the call state."""
    state.turn_count += 1
    if decision.action == "continue":
        if assessment.risk == "needs_review":
            state.followups_asked += 1
        # Any neutral follow-up satisfies "have we asked what this is about";
        # keying this on ask_purpose alone made benign calls loop on one question.
        state.purpose_asked = True
        for qid, text in QUESTION_BANK.items():
            if text == decision.assistant_text:
                state.asked_questions.add(qid)
                break
    elif decision.action == "take_message":
        state.message_taken = True
