#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

METRICS = ("cagr", "max_drawdown", "sharpe_daily_252")


def load(path: Path):
    return json.loads(path.read_text())


def finite(x):
    try:
        return math.isfinite(float(x))
    except Exception:
        return False


def metric_stats(values):
    a = np.asarray([float(x) for x in values if finite(x)], dtype=float)
    if not len(a):
        return {"count": 0}
    aa = np.abs(a)
    return {
        "count": int(len(a)),
        "min": float(a.min()),
        "max": float(a.max()),
        "median": float(np.median(a)),
        "abs_median": float(np.median(aa)),
        "abs_p95": float(np.quantile(aa, 0.95)),
        "abs_max": float(aa.max()),
    }


def case_identity(case):
    return case.get("security_id") or case.get("case") or "unknown"


def suite_summary(rows, baseline_metrics):
    out = {"cases": len(rows)}
    for metric in METRICS:
        deltas = []
        ranked = []
        base = float(baseline_metrics[metric])
        for row in rows:
            m = row.get("result", {}).get("sentinel", {}).get("20", {})
            if not finite(m.get(metric)):
                continue
            delta = float(m[metric]) - base
            deltas.append(delta)
            ranked.append({
                "case": case_identity(row),
                "delta": delta,
                "value": float(m[metric]),
            })
        ranked.sort(key=lambda x: abs(x["delta"]), reverse=True)
        out[f"{metric}_delta"] = metric_stats(deltas)
        out[f"{metric}_largest_absolute_moves"] = ranked[:20]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True, type=Path)
    ap.add_argument("--shards", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    baseline = load(args.baseline)
    if baseline.get("status") != "PASS":
        raise RuntimeError("baseline is not PASS")
    bm = baseline["baseline"]["sentinel"]["20"]

    suites = {"controller": [], "structural": [], "execution": [], "universe": [], "security-loo": []}
    result_files = sorted(args.shards.rglob("RESULT.json"))
    for p in result_files:
        r = load(p)
        suite = r.get("suite")
        if suite in suites:
            suites[suite].extend(r.get("cases", []))

    summary = {
        "schema": "research.wealth-core-v5-sentinel-ex3-v6-butterfly-stability/1",
        "system": "Wealth Core V5 + Sentinel EX3 V6",
        "classification": "FRESH_CAUSAL_STRESS_STABILITY_SUMMARY",
        "baseline_20y": {k: bm[k] for k in METRICS},
        "suites": {name: suite_summary(rows, bm) for name, rows in suites.items()},
        "security_loo_case_count": len(suites["security-loo"]),
        "result_files_scanned": len(result_files),
        "interpretation_rule": (
            "Butterfly stability is evaluated from the matched single-security leave-one-out dispersion. "
            "A V6-vs-V5 conclusion requires comparing these deltas to the same V5 stress campaign; "
            "this artifact intentionally does not infer a verdict from V6 alone."
        ),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    sec = summary["suites"]["security-loo"]
    print(f"security_loo_cases={summary['security_loo_case_count']}")
    for metric in METRICS:
        s = sec[f"{metric}_delta"]
        print(f"security_loo_{metric}_abs_p95={s.get('abs_p95')}")
        print(f"security_loo_{metric}_abs_max={s.get('abs_max')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
