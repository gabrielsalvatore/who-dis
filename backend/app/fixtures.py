"""Offline replay of previously *recorded real* runs.

This exists so a dead venue network cannot kill the demo. Two rules keep it
honest, and both are enforced rather than documented:

  * Replay is only ever entered by explicit request - there is no code path that
    silently falls back to it when a provider fails.
  * Every replayed turn is labelled `fixture_replay`, and the recording metadata
    (when it was captured, from which model) travels with it.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

REPLAY_PATH = Path(__file__).resolve().parent / "fixtures" / "replay.json"


@lru_cache(maxsize=1)
def load_replay() -> dict:
    if not REPLAY_PATH.exists():
        return {"scenarios": {}, "recorded_at": None, "model_id": None}
    try:
        return json.loads(REPLAY_PATH.read_text())
    except ValueError:
        return {"scenarios": {}, "recorded_at": None, "model_id": None}


def available_scenarios() -> list[str]:
    return sorted(load_replay().get("scenarios", {}))


def step(scenario: str, index: int) -> Optional[dict]:
    """The `index`-th recorded turn of `scenario`, or None if the script is done."""
    steps = load_replay().get("scenarios", {}).get(scenario) or []
    return steps[index] if 0 <= index < len(steps) else None


def metadata() -> dict:
    d = load_replay()
    return {
        "recorded_at": d.get("recorded_at"),
        "recorded_model": d.get("model_id"),
        "recorded_prompt_version": d.get("prompt_version"),
        "scenarios": available_scenarios(),
    }
