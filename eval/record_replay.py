"""Records real live runs of the three demo scenarios for offline replay.

The replay is a *recording of actual inference*, not invented output. It exists
so the demo survives a dead venue network. It is always labelled Fixture replay
in the UI and is excluded from every evaluation result.

  .venv/bin/python eval/record_replay.py        # backend must be running
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://localhost:8000"
OUT = ROOT / "backend" / "app" / "fixtures" / "replay.json"

SCENARIOS = {
    "bank_impersonation": [
        "Hello, this is Dan calling from the fraud team at Northbridge Bank.",
        "We've blocked a suspicious charge on the account. I'm sending a six digit code to "
        "your phone right now - read it back to me so I can verify you.",
    ],
    "routine_delivery": [
        "Hi there, it's Marcus from Lakeside Parcel.",
        "I've got a package that needs a signature, I'll try again tomorrow between nine "
        "and eleven.",
    ],
    "family_emergency": [
        "Grandma, it's me, it's Tom. I'm in real trouble.",
        "I had an accident and I'm at the police station. I need three thousand dollars for "
        "bail right now, and please don't tell mum and dad.",
    ],
}


def main() -> int:
    health = httpx.get(f"{BASE}/api/health", timeout=10).json()
    if health.get("app_mode") != "live":
        print(f"backend is in app_mode={health.get('app_mode')!r}; run it live to record.")
        return 2

    recorded = {}
    for name, lines in SCENARIOS.items():
        print(f"\n=== {name} ===")
        call_id = httpx.post(f"{BASE}/api/calls", json={}, timeout=30).json()["call_id"]
        steps = []
        for line in lines:
            r = httpx.post(
                f"{BASE}/api/calls/{call_id}/turns",
                data={"request_id": uuid.uuid4().hex, "text": line},
                timeout=90,
            )
            r.raise_for_status()
            b = r.json()
            steps.append({
                "caller_text": line,
                "assistant_text": b["assistant_text"],
                "assessment": b["assessment"],
                "decision": b["decision"],
                "alert": b["alert"],
                "call_status": b["call_status"],
            })
            print(f"  risk={b['assessment']['risk']:17s} action={b['decision']['action']}")
            if b["call_status"] == "ended":
                break
            time.sleep(0.3)
        httpx.delete(f"{BASE}/api/calls/{call_id}", timeout=10)
        recorded[name] = steps

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "model_id": health.get("classifier_model"),
        "prompt_version": health.get("prompt_version"),
        "note": "Recording of real inference. Replayed offline it is NOT live inference "
                "and is always labelled Fixture replay.",
        "scenarios": recorded,
    }, indent=2) + "\n")
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
