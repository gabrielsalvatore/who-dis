"""In-memory session storage.

Deliberately not a database: restarting the backend clears every call, which is
documented in the README. Sessions hold synthetic demo content only.

Two concurrency guards live here, because both protect real money:
  * a per-session lock, so two overlapping turns cannot interleave and produce
    two alerts or two sets of provider charges;
  * a request-id result cache, so a client retry or a double-tap replays the
    first result instead of paying for a second transcription + classification.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

from .policy import CallState, OPENING_LINE
from .schemas import (
    Alert,
    Assessment,
    CallStatus,
    CallView,
    Mode,
    PolicyDecision,
    StageTimings,
    Turn,
    TurnResult,
)

MAX_SESSIONS = 20          # demo-sized; oldest are evicted
MAX_CACHED_REQUESTS = 32


@dataclass
class CallSession:
    call_id: str
    created_at: float = field(default_factory=time.time)
    status: CallStatus = "active"
    mode: Mode = "live_api"
    scenario_label: Optional[str] = None

    turns: list[Turn] = field(default_factory=list)
    assessments: list[Assessment] = field(default_factory=list)
    decisions: list[PolicyDecision] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    timings: list[StageTimings] = field(default_factory=list)

    state: CallState = field(default_factory=CallState)
    version: int = 0

    # Offline replay position. Only set for explicitly requested fixture calls.
    replay_scenario: Optional[str] = None
    replay_index: int = 0

    # assistant turn id -> mp3 bytes for that specific spoken response
    audio: dict[str, bytes] = field(default_factory=dict)

    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    request_cache: "OrderedDict[str, TurnResult]" = field(
        default_factory=OrderedDict, repr=False
    )

    # --- turn ids -------------------------------------------------------
    def next_caller_turn_id(self) -> str:
        n = sum(1 for t in self.turns if t.role == "caller")
        return f"caller-{n + 1}"

    def next_assistant_turn_id(self) -> str:
        n = sum(1 for t in self.turns if t.role == "assistant")
        return f"assistant-{n}"

    def add_turn(self, turn: Turn) -> Turn:
        self.turns.append(turn)
        self.version += 1
        return turn

    def record(
        self,
        assessment: Assessment,
        decision: PolicyDecision,
        timings: StageTimings,
        alert: Optional[Alert],
    ) -> None:
        self.assessments.append(assessment)
        self.decisions.append(decision)
        self.timings.append(timings)
        if alert is not None:
            self.alerts.append(alert)
        if decision.ends_call:
            self.status = "ended"
        self.version += 1

    # --- request-id replay cache ---------------------------------------
    def cached_result(self, request_id: str) -> Optional[TurnResult]:
        if not request_id:
            return None
        hit = self.request_cache.get(request_id)
        if hit is None:
            return None
        replay = hit.model_copy(deep=True)
        replay.cached = True
        return replay

    def cache_result(self, request_id: str, result: TurnResult) -> None:
        if not request_id:
            return
        self.request_cache[request_id] = result
        while len(self.request_cache) > MAX_CACHED_REQUESTS:
            self.request_cache.popitem(last=False)

    # --- view ------------------------------------------------------------
    def to_view(self) -> CallView:
        return CallView(
            call_id=self.call_id,
            status=self.status,
            mode=self.mode,
            created_at=self.created_at,
            scenario_label=self.scenario_label,
            turns=self.turns,
            assessments=self.assessments,
            decisions=self.decisions,
            alerts=self.alerts,
            timings=self.timings,
            version=self.version,
        )


class SessionStore:
    """Process-local session registry. Also tracks the most recent call so a
    separately opened family window can follow along across a reset."""

    def __init__(self) -> None:
        self._sessions: "OrderedDict[str, CallSession]" = OrderedDict()
        self._current_id: Optional[str] = None

    def create(
        self,
        mode: Mode = "live_api",
        scenario_label: Optional[str] = None,
        replay_scenario: Optional[str] = None,
    ) -> CallSession:
        session = CallSession(
            call_id=f"call-{uuid.uuid4().hex[:8]}",
            mode=mode,
            scenario_label=scenario_label,
            replay_scenario=replay_scenario,
        )
        session.add_turn(
            Turn(
                turn_id=session.next_assistant_turn_id(),
                role="assistant",
                text=OPENING_LINE,
                source="opening",
            )
        )
        self._sessions[session.call_id] = session
        self._current_id = session.call_id
        while len(self._sessions) > MAX_SESSIONS:
            old_id, _ = self._sessions.popitem(last=False)
            if self._current_id == old_id:
                self._current_id = None
        return session

    def get(self, call_id: str) -> Optional[CallSession]:
        return self._sessions.get(call_id)

    def current(self) -> Optional[CallSession]:
        if self._current_id is None:
            return None
        return self._sessions.get(self._current_id)

    def delete(self, call_id: str) -> bool:
        existed = self._sessions.pop(call_id, None) is not None
        if self._current_id == call_id:
            self._current_id = None
        return existed

    def clear(self) -> None:
        self._sessions.clear()
        self._current_id = None


store = SessionStore()
