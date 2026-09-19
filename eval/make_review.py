"""Renders eval/test_review.md so the drafted labels can be checked by a human."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rows = [json.loads(l) for l in (ROOT / "eval" / "test.jsonl").read_text().splitlines() if l.strip()]
ver = json.loads((ROOT / "eval" / "dataset_versions.json").read_text())

RISK_SHORT = {"no_warning_signs": "calm", "needs_review": "review", "high_risk": "high"}

out = [
    "# Test set — label review (DRAFT, not frozen)",
    "",
    f"24 conversations · {sum(len(r['prefixes']) for r in rows)} prefixes · dataset hash `{ver['test']}`",
    "",
    "**Gabriel: this needs your sign-off before the test set is frozen.**",
    "",
    "How to read a row: after the caller says that line, which risk labels would you",
    "accept as defensible, and which actions would be a genuine failure? `acceptable`",
    "is a *set* on purpose — a benign but unverifiable call may correctly need review.",
    "`forbidden` is the part that decides pass/fail. `detect?` marks the first point a",
    "scam is genuinely knowable; detection earlier is not rewarded.",
    "",
    "Legend: calm = no_warning_signs · review = needs_review · high = high_risk",
    "",
    "Reply with corrections like: `test-07 prefix 1 acceptable should be calm only`,",
    "or just say the labels look right.",
    "",
    "---",
    "",
]

for cat in ("scam", "benign"):
    out.append(f"## {cat.upper()} scenarios ({sum(1 for r in rows if r['category']==cat)})")
    out.append("")
    for r in rows:
        if r["category"] != cat:
            continue
        out.append(f"### {r['id']} — {r['scenario'].replace('_', ' ')}")
        out.append(f"*{r['notes']}*")
        out.append("")
        out.append("| # | caller says | acceptable | forbidden | detect? |")
        out.append("|---|---|---|---|---|")
        for i, p in enumerate(r["prefixes"], 1):
            text = p["caller_text"].replace("|", "\\|")
            acc = ", ".join(RISK_SHORT[x] for x in p["acceptable_risk"])
            forb = ", ".join(p["forbidden_actions"]) or "—"
            det = "**yes**" if p["expect_detect"] else "no"
            out.append(f"| {i} | {text} | {acc} | {forb} | {det} |")
        out.append("")

(ROOT / "eval" / "test_review.md").write_text("\n".join(out) + "\n")
print(f"wrote eval/test_review.md ({len(rows)} conversations)")
