"""Evaluation runner.

Both systems see exactly the same transcript prefixes and neither ever sees a
future turn. Policy state evolves across the prefixes of one conversation, so
what is measured is the whole system, not a lone classifier.

  # cheap, no spend:
  python eval/run_eval.py --split dev  --system keyword
  # real inference (prints the call estimate and asks to continue):
  python eval/run_eval.py --split dev  --system nemotron
  python eval/run_eval.py --split test --system both --yes

Never generates TTS. Text classification only.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))

from app import classifier as clf                     # noqa: E402
from app.config import get_settings                   # noqa: E402
from app.policy import CallState, OPENING_LINE, advance_state, decide  # noqa: E402
from app.schemas import Turn                          # noqa: E402
from keyword_baseline import BASELINE_VERSION, classify_keywords  # noqa: E402

PROTECTIVE = {"end_simulated_call", "request_family_review"}


def load(split: str) -> list[dict]:
    path = ROOT / "eval" / f"{split}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def run_conversation(conv: dict, system: str, settings, client) -> list[dict]:
    """Replay one conversation prefix by prefix, carrying policy state forward."""
    turns = [Turn(turn_id="assistant-0", role="assistant", text=OPENING_LINE, source="opening")]
    state = CallState()
    rows: list[dict] = []

    for i, prefix in enumerate(conv["prefixes"], 1):
        caller = Turn(turn_id=f"caller-{i}", role="caller",
                      text=prefix["caller_text"], source="text")
        turns.append(caller)

        if system == "keyword":
            t0 = time.perf_counter()
            assessment = classify_keywords(turns)
            assessment.latency_ms = (time.perf_counter() - t0) * 1000
        else:
            assessment = await clf.classify(turns, settings, client)

        decision, alert = decide(assessment, state, caller)
        advance_state(state, decision, assessment)

        rows.append({
            "conv_id": conv["id"], "category": conv["category"], "scenario": conv["scenario"],
            "prefix_index": i, "through_turn": prefix["through_turn"],
            "caller_text": prefix["caller_text"],
            "acceptable_risk": prefix["acceptable_risk"],
            "forbidden_actions": prefix["forbidden_actions"],
            "expect_detect": prefix["expect_detect"],
            "risk": assessment.risk, "action": decision.action,
            "credential_request": assessment.credential_request,
            "emergency_claimed": assessment.emergency_claimed,
            "alert_level": alert.level if alert else None,
            "ends_call": decision.ends_call,
            "evidence": [{"quote": e.quote, "signal": e.signal, "verified": e.verified}
                         for e in assessment.evidence],
            "verified_evidence": len(assessment.verified_evidence),
            "total_evidence": len(assessment.evidence),
            "status": assessment.status, "degraded_reason": assessment.degraded_reason,
            "latency_ms": assessment.latency_ms, "model_id": assessment.model_id,
            "used_fallback_model": assessment.used_fallback_model,
            "risk_ok": assessment.risk in prefix["acceptable_risk"],
            "forbidden_violation": decision.action in prefix["forbidden_actions"],
            "assistant_text": decision.assistant_text,
            "policy_reason": decision.reason,
        })

        if decision.ends_call:
            break        # a real call would stop here; later prefixes are unreachable
    return rows


def metrics(rows: list[dict], convs: list[dict]) -> dict:
    by_conv: dict[str, list[dict]] = {}
    for r in rows:
        by_conv.setdefault(r["conv_id"], []).append(r)

    cat = {c["id"]: c["category"] for c in convs}
    scam_ids = [i for i in by_conv if cat[i] == "scam"]
    benign_ids = [i for i in by_conv if cat[i] == "benign"]

    def pct(n, d):
        return "N/A" if d == 0 else f"{n}/{d} ({100 * n / d:.0f}%)"

    # --- scam detection ---
    model_detected, system_detected, first_turns, missed = [], [], [], []
    for cid in scam_ids:
        rs = by_conv[cid]
        m = next((r["prefix_index"] for r in rs if r["risk"] == "high_risk"), None)
        s = next((r["prefix_index"] for r in rs if r["action"] in PROTECTIVE), None)
        if m is not None:
            model_detected.append(cid)
        if s is not None:
            system_detected.append(cid)
            first_turns.append(s)
        else:
            missed.append(cid)

    # --- benign errors ---
    benign_high_risk = [c for c in benign_ids
                        if any(r["risk"] == "high_risk" for r in by_conv[c])]
    benign_ended = [c for c in benign_ids
                    if any(r["action"] == "end_simulated_call" for r in by_conv[c])]
    benign_reviewed = [c for c in benign_ids
                       if any(r["action"] == "request_family_review" for r in by_conv[c])]
    benign_clean = [c for c in benign_ids if c not in benign_reviewed]

    lats = [r["latency_ms"] for r in rows if r["latency_ms"] is not None and r["status"] == "ok"]
    failures = [r for r in rows if r["status"] == "degraded"]
    ev_rows = [r for r in rows if r["total_evidence"] > 0]
    ev_verified = sum(r["verified_evidence"] for r in ev_rows)
    ev_total = sum(r["total_evidence"] for r in ev_rows)

    return {
        "counts": {
            "conversations": len(by_conv), "scam": len(scam_ids), "benign": len(benign_ids),
            "prefixes_evaluated": len(rows),
        },
        "scam_detection": {
            "model_high_risk_recall": pct(len(model_detected), len(scam_ids)),
            "system_protective_recall": pct(len(system_detected), len(scam_ids)),
            "missed_entirely": missed or "none",
            "first_protective_turn_mean":
                "N/A" if not first_turns else round(statistics.mean(first_turns), 2),
            "first_protective_turn_values": first_turns or "N/A",
            "note": "Mean is over DETECTED scams only; missed calls are listed separately.",
        },
        "benign_errors": {
            "high_risk_false_alarms": pct(len(benign_high_risk), len(benign_ids)),
            "high_risk_false_alarm_ids": benign_high_risk or "none",
            "incorrectly_terminated": pct(len(benign_ended), len(benign_ids)),
            "incorrectly_terminated_ids": benign_ended or "none",
            "sent_to_review": pct(len(benign_reviewed), len(benign_ids)),
            "sent_to_review_ids": benign_reviewed or "none",
            "handled_without_review": pct(len(benign_clean), len(benign_ids)),
        },
        "label_agreement": {
            "prefix_risk_within_acceptable_set": pct(
                sum(1 for r in rows if r["risk_ok"]), len(rows)),
            "forbidden_action_violations": pct(
                sum(1 for r in rows if r["forbidden_violation"]), len(rows)),
            "violation_detail": [
                f"{r['conv_id']}/{r['through_turn']}: {r['action']}"
                for r in rows if r["forbidden_violation"]
            ] or "none",
        },
        "evidence_grounding": {
            "quotes_verified_against_transcript": pct(ev_verified, ev_total),
        },
        "latency_ms": {
            "n": len(lats),
            "median": round(statistics.median(lats), 1) if lats else "N/A",
            "p95": round(sorted(lats)[max(0, int(len(lats) * 0.95) - 1)], 1) if lats else "N/A",
            "max": round(max(lats), 1) if lats else "N/A",
            "provider_failures": len(failures),
            "failure_reasons": sorted({r["degraded_reason"] for r in failures}) or "none",
            "fallback_model_used": sum(1 for r in rows if r["used_fallback_model"]),
        },
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--system", choices=["nemotron", "keyword", "both"], default="both")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--yes", action="store_true", help="skip the inference-cost prompt")
    ap.add_argument("--model", default=None,
                    help="override NVIDIA_MODEL for this run (model comparison)")
    args = ap.parse_args()

    convs = load(args.split)
    if args.limit:
        convs = convs[: args.limit]
    n_prefixes = sum(len(c["prefixes"]) for c in convs)

    versions = json.loads((ROOT / "eval" / "dataset_versions.json").read_text())
    if args.split == "test" and not versions.get("frozen"):
        print("WARNING: the test set is NOT frozen yet (pending human label review).")
        print("         Results from it are provisional. See eval/test_review.md.\n")

    systems = ["keyword", "nemotron"] if args.system == "both" else [args.system]
    settings = get_settings()
    if args.model:
        settings.nvidia_model = args.model
        settings.nvidia_model_fallback = ""   # isolate the model under test

    if "nemotron" in systems:
        if not settings.classifier_configured:
            print("NVIDIA is not configured; cannot run the nemotron system.")
            return 2
        print(f"About to make up to {n_prefixes} inference calls "
              f"(one per prefix, plus retries) against {settings.nvidia_model}.")
        if not args.yes and input("Continue? [y/N] ").strip().lower() != "y":
            return 1

    started = datetime.now(timezone.utc)
    out: dict = {
        "run_at": started.isoformat(),
        "split": args.split,
        "dataset_hash": versions.get(args.split),
        "dataset_frozen": versions.get("frozen", False),
        "conversations": len(convs),
        "prefixes": n_prefixes,
        "systems": {},
    }

    async with httpx.AsyncClient() as client:
        for system in systems:
            label = (f"{settings.nvidia_model} / prompt {clf.PROMPT_VERSION}"
                     if system == "nemotron" else BASELINE_VERSION)
            print(f"\n=== {system} ({label}) ===")
            rows: list[dict] = []
            t0 = time.perf_counter()
            for conv in convs:                      # sequential: kind to rate limits
                conv_rows = await run_conversation(conv, system, settings, client)
                rows.extend(conv_rows)
                last = conv_rows[-1]
                flag = "!" if any(r["forbidden_violation"] for r in conv_rows) else " "
                print(f" {flag} {conv['id']:8s} {conv['category']:6s} "
                      f"{len(conv_rows)} prefix -> risk={last['risk']:17s} action={last['action']}")
                if system == "nemotron":
                    await asyncio.sleep(0.4)
            out["systems"][system] = {
                "label": label,
                "model_id": settings.nvidia_model if system == "nemotron" else BASELINE_VERSION,
                "prompt_version": clf.PROMPT_VERSION if system == "nemotron" else BASELINE_VERSION,
                "wall_seconds": round(time.perf_counter() - t0, 1),
                "metrics": metrics(rows, convs),
                "rows": rows,
            }

    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / "eval" / "results" / f"{args.split}_{args.system}_{stamp}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")

    print(f"\n{'=' * 78}\nRESULTS  split={args.split}  dataset={out['dataset_hash']}  "
          f"frozen={out['dataset_frozen']}\n{'=' * 78}")
    for system, data in out["systems"].items():
        print(f"\n--- {system} ({data['label']}) ---")
        print(json.dumps(data["metrics"], indent=2))
    print(f"\nwrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
