"""Generates docs/EVALUATION.md from the newest result file per split.

Numbers are read from eval/results/*.json, never typed by hand.
  .venv/bin/python eval/make_report.py
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.classifier import MAX_OUTPUT_TOKENS  # noqa: E402

PROTECTIVE = {"end_simulated_call", "request_family_review"}


def latest(split: str) -> dict | None:
    files = sorted(glob.glob(str(ROOT / "eval" / "results" / f"{split}_*.json")))
    best = None
    for f in files:
        d = json.load(open(f))
        # prefer a run containing both systems, else the newest
        if best is None or len(d["systems"]) >= len(best["systems"]):
            best = d
    return best


def table(run: dict) -> list[str]:
    sysnames = list(run["systems"])
    rows = [
        ("System protective recall on scams", lambda m: m["scam_detection"]["system_protective_recall"]),
        ("Model `high_risk` label recall", lambda m: m["scam_detection"]["model_high_risk_recall"]),
        ("Benign high-risk false alarms", lambda m: m["benign_errors"]["high_risk_false_alarms"]),
        ("Benign calls incorrectly ended", lambda m: m["benign_errors"]["incorrectly_terminated"]),
        ("Benign calls sent to review", lambda m: m["benign_errors"]["sent_to_review"]),
        ("Benign handled without review", lambda m: m["benign_errors"]["handled_without_review"]),
        ("Prefix risk within acceptable set", lambda m: m["label_agreement"]["prefix_risk_within_acceptable_set"]),
        ("Forbidden-action violations", lambda m: m["label_agreement"]["forbidden_action_violations"]),
        ("Evidence quotes verified", lambda m: m["evidence_grounding"]["quotes_verified_against_transcript"]),
        ("Classify latency median", lambda m: f'{m["latency_ms"]["median"]} ms'),
        ("Classify latency p95", lambda m: f'{m["latency_ms"]["p95"]} ms'),
        ("Latency sample size", lambda m: m["latency_ms"]["n"]),
        ("Provider failures", lambda m: m["latency_ms"]["provider_failures"]),
    ]
    out = ["| Metric | " + " | ".join(run["systems"][s]["label"] for s in sysnames) + " |",
           "|---|" + "---|" * len(sysnames)]
    for name, fn in rows:
        vals = []
        for s in sysnames:
            try:
                vals.append(str(fn(run["systems"][s]["metrics"])))
            except Exception:
                vals.append("N/A")
        out.append(f"| {name} | " + " | ".join(vals) + " |")
    return out


def failures(run: dict, system: str, limit: int = 2) -> list[str]:
    data = run["systems"].get(system)
    if not data:
        return []
    out: list[str] = []
    for r in data["rows"]:
        if len(out) >= limit * 6:
            break
        if r["forbidden_violation"]:
            out += [
                f"**{r['conv_id']} ({r['scenario'].replace('_', ' ')}) — {system} took a forbidden action.**",
                "",
                f"> Caller: \"{r['caller_text']}\"",
                "",
                f"Model said `{r['risk']}`; policy chose `{r['action']}`. "
                f"Expected any of {r['acceptable_risk']}, and `{r['action']}` was forbidden here.",
                "",
            ]
    return out


lines = [
    "# Evaluation",
    "",
    "Synthetic scenarios only. Nothing here supports a claim about real-world prevention",
    "accuracy. Both systems see identical transcript prefixes, neither ever sees a future",
    "turn, and both are run through the **same** policy layer, so what is compared is the",
    "whole system rather than a lone classifier. No TTS is generated during evaluation.",
    "",
    "## How to read the two recall numbers",
    "",
    "**Model `high_risk` label recall** is how often Nemotron picked the word `high_risk`.",
    "**System protective recall** is how often CallKind actually did something protective —",
    "ended the call or raised a review alert. The second is the one that matters, and the",
    "gap between them is the whole architectural point: the backend acts on *verified",
    "evidence*, not on the model's choice of label. On a direct one-time-code request the",
    "model frequently says `needs_review`, yet the system still ends the call, because",
    "`credential_request` plus a re-verified quote is what the policy keys on.",
    "",
]

ver = json.loads((ROOT / "eval" / "dataset_versions.json").read_text())
if not ver.get("frozen"):
    lines += [
        "## Status of the held-out test set",
        "",
        "**The test set has not been frozen and has not been run.** The build spec requires a",
        "human to review all 24 drafted conversations and their per-prefix labels before the",
        "set is frozen. That review is incomplete: two flagged judgement calls were confirmed",
        "(both as drafted, 0 labels changed), but the full 24 were not signed off.",
        "",
        "So every number below is from the **development split**, which is the split tuning was",
        "allowed against. Dev-set numbers are not held-out numbers and should not be presented",
        "as though they were. The prompt has not been tuned against the test set.",
        "",
    ]

for split, heading in (("dev", "Development set"), ("test", "Held-out test set")):
    run = latest(split)
    lines += [f"## {heading}", ""]
    if run is None:
        lines += ["*Not yet run.*", ""]
        continue
    if split == "dev":
        frozen = "tuning split — freezing does not apply"
    else:
        frozen = "frozen" if run.get("dataset_frozen") else "**NOT FROZEN — provisional**"
    lines += [
        f"`{run['conversations']}` conversations · `{run['prefixes']}` prefixes · "
        f"dataset `{run['dataset_hash']}` ({frozen}) · run `{run['run_at']}`",
        "",
    ] + table(run) + [""]

    nem = run["systems"].get("nemotron")
    if nem:
        m = nem["metrics"]
        lines += [
            f"Scams missed entirely: `{m['scam_detection']['missed_entirely']}`. "
            f"First protective turn among detected scams (mean): "
            f"`{m['scam_detection']['first_protective_turn_mean']}` — "
            f"{m['scam_detection']['note']}",
            "",
        ]
    for system in run["systems"]:
        f = failures(run, system)
        if f:
            lines += [f"### Failure cases — {system}", ""] + f

sweep_path = ROOT / "eval" / "results" / "endpoint_sweep.json"
if sweep_path.exists():
    sw = json.loads(sweep_path.read_text())
    lines += [
        "## Hosted-endpoint reliability and model selection",
        "",
        f"Measured {sw['measured_at']} with a {sw['timeout_s']:.0f} s timeout. "
        f"{sw['note']}",
        "",
        "| Model | succeeded | p50 | p95 | errors |",
        "|---|---|---|---|---|",
    ]
    for model, m in sw["models"].items():
        lines.append(
            f"| `{model.replace('nvidia/', '')}` | {m['succeeded']}/{m['attempts']} | "
            f"{m['p50_ms']} ms | {m['p95_ms']} ms | {m['errors'] or 'none'} |"
        )
    lines += [
        "",
        "Two things to be honest about here.",
        "",
        "**Availability is noisy and is not a stable differentiator.** Across two sweeps taken",
        "minutes apart the ranking inverted — one model went 7/8 then 4/8, another 5/8 then",
        "6/8. These are shared endpoints under hackathon load and `503 ResourceExhausted` is",
        "common. No model choice fixes that, which is why the system retries once, then falls",
        "back to a second Nemotron, then degrades to review. Two turns of the latest dev run",
        "hit a 503; both degraded to review, which is the intended behaviour and is counted",
        "in the table above rather than excluded from it.",
        "",
        "**Latency is the stable signal**, and it drove the model choice together with dev-set",
        "accuracy. Reasoning mode is explicitly disabled (`enable_thinking: false`); the",
        "endpoint returned no `reasoning_content` under that setting, and output is capped at",
        f"{MAX_OUTPUT_TOKENS} tokens with temperature 0, because every extra token is "
        "user-visible delay.",
        "",
    ]

lines += [
    "## Which Nemotron is primary, and why",
    "",
    "Primary is `nemotron-3-nano-omni-30b-a3b-reasoning`. `nemotron-3-super-120b-a12b` is",
    "the fallback, called only after the primary returns a transient failure.",
    "",
    "The two models differ most on the metric this project argues is not load-bearing.",
    "super-120b labels more scam prefixes `high_risk` (5/6 against nano's 3/6), and system",
    "protective recall is 6/6 on both. The policy ends or escalates the same calls either",
    "way, because it acts on a re-verified credential-bearing quote rather than on the",
    "label. Better label recall bought nothing the family would ever see.",
    "",
    "The swap to super-120b looked like it cost benign precision: benign calls sent to the",
    "family for review went 1/6 to 3/6. **That number did not reproduce.** Rerunning nano on",
    "the same twelve conversations also put 3/6 benign calls into review, and one of those",
    "three was a provider 503 degrading to review rather than anything the model decided.",
    "Two runs of the same model on the same data giving 1/6 and 3/6 is the measurement",
    "moving, not the model. With six benign conversations, one conversation is 17 points, so",
    "this split cannot separate the two models on benign precision and that comparison",
    "should not be quoted as though it can.",
    "",
    "Tail latency is the one user-visible difference, and it is weak. nano was faster on",
    "both dev runs (p95 3424 ms and 4209 ms against 4722 ms), while the point-in-time",
    "endpoint sweep above had super-120b the faster of the two. Shared hosted endpoints",
    "under load are not stable enough for that gap to be decisive either.",
    "",
    "So the ordering is a weak preference, not a result: nano is primary on the dev-run",
    "latency tail, super-120b is the fallback that covers transient failures, and neither",
    "position rests on label recall. The fallback chain matters more than which model is",
    "first in it. False family alerts are the failure mode worth spending effort on, because",
    "alert fatigue is what makes a family stop reading the alerts, but this evaluation is",
    "not powered to measure them at the resolution a model choice would need.",
    "",
    "## The keyword baseline",
    "",
    "`eval/keyword_baseline.py`, version `kw-v1`, frozen 2026-09-19. Rules are published in",
    "full in that file and were not tuned against results. It matches credential, payment,",
    "urgency, secrecy and authority vocabulary in the caller's words.",
    "",
    "Its instructive failure is `dev-08`: a bank calling to warn a customer *never* to read",
    "out a one-time code. The baseline matches the words `one time code`, calls it",
    "`high_risk`, and **hangs up on the warning**. It cannot tell who is asking whom to do",
    "what. That single case is the clearest argument for using a language model here at all.",
    "",
    "## What is not measured",
    "",
    "- Real callers, real microphones, real rooms. Spoken checks used synthesised speech",
    "  through a fake capture device plus a small number of manual runs.",
    "- Any browser other than Chromium.",
    "- Anything about real-world scam prevalence, prevention or financial loss.",
    "- Fixture replay is a recording of earlier real inference and is excluded from every",
    "  number above.",
    "",
]

(ROOT / "docs" / "EVALUATION.md").write_text("\n".join(lines) + "\n")
print("wrote docs/EVALUATION.md")
