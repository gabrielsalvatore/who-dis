"""Measures availability and latency of the hosted Nemotron endpoints.

Hackathon-time reality: these endpoints are shared and get saturated. Availability
turned out to matter more than raw speed for model selection, so it is measured
explicitly rather than assumed.

  .venv/bin/python eval/measure_endpoints.py [--n 8]

Writes eval/results/endpoint_sweep.json. Point-in-time: re-run before relying on it.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.classifier import MAX_OUTPUT_TOKENS, SYSTEM_PROMPT  # noqa: E402
from app.config import get_settings  # noqa: E402

CANDIDATES = [
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
]
PROBE = (
    "[assistant-0] May I ask who's calling?\n"
    "[caller-1] This is Dan from the fraud team at Northbridge Bank.\n"
    "[caller-2] I'm sending a six digit code, read it back to me so I can verify you."
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8)
    args = ap.parse_args()

    s = get_settings()
    headers = {"Authorization": f"Bearer {s.nvidia_api_key}"}
    results = {}
    print(f"{args.n} probes per model, 0.6 s apart, {s.classify_timeout_s:.0f} s timeout\n")

    for model in CANDIDATES:
        body = {
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": PROBE}],
            "max_tokens": MAX_OUTPUT_TOKENS, "temperature": 0.0, "top_p": 1.0,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_object"},
        }
        lat, errs, creds, risks = [], {}, [], []
        for _ in range(args.n):
            t0 = time.perf_counter()
            try:
                r = httpx.post(f"{s.nvidia_base_url}/chat/completions", headers=headers,
                               json=body, timeout=s.classify_timeout_s)
            except Exception as exc:
                k = type(exc).__name__
                errs[k] = errs.get(k, 0) + 1
                continue
            if r.status_code != 200:
                k = f"HTTP{r.status_code}"
                errs[k] = errs.get(k, 0) + 1
                continue
            lat.append((time.perf_counter() - t0) * 1000)
            try:
                o = json.loads(r.json()["choices"][0]["message"]["content"])
                risks.append(o.get("risk"))
                creds.append(o.get("credential_request"))
            except Exception:
                pass
            time.sleep(0.6)

        entry = {
            "attempts": args.n, "succeeded": len(lat), "errors": errs,
            "p50_ms": round(statistics.median(lat), 1) if lat else None,
            "p95_ms": round(sorted(lat)[max(0, int(len(lat) * 0.95) - 1)], 1) if lat else None,
            "max_ms": round(max(lat), 1) if lat else None,
            "risk_labels": sorted({str(x) for x in risks}) or None,
            "credential_request_values": sorted({str(x) for x in creds}) or None,
        }
        results[model] = entry
        name = model.replace("nvidia/", "")
        print(f"{name:42s} ok={entry['succeeded']}/{args.n} "
              f"p50={entry['p50_ms']} p95={entry['p95_ms']} errs={errs or 'none'}")

    out = ROOT / "eval" / "results" / "endpoint_sweep.json"
    out.write_text(json.dumps({
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "timeout_s": s.classify_timeout_s,
        "note": "Point-in-time measurement of shared hosted endpoints under hackathon load.",
        "models": results,
    }, indent=2) + "\n")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
