"""Pydantic models for CallKind.

Vocabulary note, deliberately enforced here rather than by convention:
  * There is no "legitimate" / "verified" / "safe" risk label, and no confidence
    percentage. The strongest thing CallKind may say is "no warning signs
    detected; identity unverified".
  * `Assessment` is what the *model* produced. `PolicyDecision` is what the
    *backend* chose to do. They are stored separately so the family view can
    show which is which.
"""
from __future__ import annotations

import time
from typing import Literal, Optional

from pydantic import BaseModel, Field

Risk = Literal["no_warning_signs", "needs_review", "high_risk"]
Action = Literal["continue", "take_message", "request_family_review", "end_simulated_call"]
Role = Literal["caller", "assistant"]
CallStatus = Literal["active", "ended"]
TurnSource = Literal["speech", "text", "opening", "fixture"]
Mode = Literal["live_api", "text_fallback", "fixture_replay"]

# The classifier may only pick a follow-up question from this allowlist. It never
# composes its own question, so it can never be steered into asking the caller
# for a credential.
QUESTION_BANK: dict[str, str] = {
    "ask_purpose": "May I ask what the call is about?",
    "ask_organisation": "Which organisation are you calling from?",
    "ask_callback": "I can take a number for the family to call you back on.",
    "ask_message": "Would you like to leave a message?",
}

# Scam type is free-form from the model but normalised into this set for display.
KNOWN_SCAM_TYPES = {
    "unknown",
    "bank_impersonation",
    "family_impersonation",
    "government_impersonation",
    "tech_support",
    "prize_or_refund",
    "delivery_pretext",
    "investment",
    "romance",
    "utility",
}


class Evidence(BaseModel):
    """A quote the model says supports its assessment.

    `verified` is set by the backend, not the model: it is True only if `quote`
    occurs verbatim in the caller turn named by `turn_id`. Unverified evidence is
    kept for display/debugging but may never justify an action.
    """

    turn_id: str
    quote: str = Field(max_length=300)
    signal: str = Field(max_length=80)
    verified: bool = False


class Assessment(BaseModel):
    """Structured output of the Nemotron classifier, after local validation."""

    risk: Risk = "needs_review"
    scam_type: str = "unknown"
    emergency_claimed: bool = False
    # Drives the single narrow end-the-call policy. The backend requires this to
    # be True *and* backed by a verified quote before it will hang up.
    credential_request: bool = False
    evidence: list[Evidence] = Field(default_factory=list, max_length=3)
    summary: str = Field(default="", max_length=400)
    question_id: Optional[str] = None

    # --- provenance, set by the backend, never by the model ---
    status: Literal["ok", "degraded"] = "ok"
    degraded_reason: Optional[str] = None
    model_id: Optional[str] = None
    prompt_version: Optional[str] = None
    latency_ms: Optional[float] = None
    used_fallback_model: bool = False

    @property
    def verified_evidence(self) -> list[Evidence]:
        return [e for e in self.evidence if e.verified]


class PolicyDecision(BaseModel):
    """What the backend decided to do. Separate from the model's opinion."""

    action: Action
    assistant_text: str
    reason: str            # short human-readable justification, shown to the family
    ends_call: bool = False
    alert_level: Optional[Literal["review", "urgent"]] = None


class Turn(BaseModel):
    turn_id: str           # "assistant-0", "caller-1", "assistant-1", ...
    role: Role
    text: str
    source: TurnSource
    ts: float = Field(default_factory=time.time)


class Alert(BaseModel):
    alert_id: str
    level: Literal["review", "urgent"]
    headline: str
    summary: str
    evidence: list[Evidence] = Field(default_factory=list)
    caller_turn_id: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    model_risk: Optional[Risk] = None
    policy_action: Optional[Action] = None
    # Callback-verification advice, set when the caller claimed an identity.
    # CallKind never verifies identity itself; it tells the family how to.
    recommended_action: Optional[str] = None


class StageTimings(BaseModel):
    """Milliseconds per stage. `total_ms` is server-side; the client measures
    time-to-filler and time-to-response separately (the filler never counts as
    reduced processing latency)."""

    transcribe_ms: Optional[float] = None
    classify_ms: Optional[float] = None
    tts_ms: Optional[float] = None
    total_ms: Optional[float] = None


class TurnResult(BaseModel):
    """Response to POST /api/calls/{id}/turns."""

    call_id: str
    turn_id: str
    caller_text: str
    assistant_text: str
    assessment: Assessment
    decision: PolicyDecision
    alert: Optional[Alert] = None
    call_status: CallStatus
    mode: Mode
    audio_url: Optional[str] = None
    audio_error: Optional[str] = None     # TTS failed but the assessment survived
    audio_cached: bool = False            # served from the fixed-phrase cache, not fresh TTS
    timings: StageTimings = Field(default_factory=StageTimings)
    cached: bool = False                  # replayed from the request-id cache


class CallView(BaseModel):
    """Response to GET /api/calls/{id} — everything the family view renders."""

    call_id: str
    status: CallStatus
    mode: Mode
    created_at: float
    scenario_label: Optional[str] = None
    turns: list[Turn] = Field(default_factory=list)
    assessments: list[Assessment] = Field(default_factory=list)
    decisions: list[PolicyDecision] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)
    timings: list[StageTimings] = Field(default_factory=list)
    version: int = 0                      # bumps on every change; lets pollers diff cheaply


class HealthResponse(BaseModel):
    status: str = "ok"
    app_mode: str
    classifier_configured: bool
    speech_configured: bool
    stt_configured: bool
    classifier_model: Optional[str] = None
    tts_model: Optional[str] = None
    stt_model: Optional[str] = None
    prompt_version: Optional[str] = None
    filler_cached: bool = False
    setup_needs: list[str] = Field(default_factory=list)
