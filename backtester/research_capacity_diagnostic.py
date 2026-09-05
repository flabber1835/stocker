#!/usr/bin/env python3
"""UNCERTIFIED diagnostic for the Research Champion execution-capacity collapse.

Keeps the frozen Champion profile, canonical input package, PIT classification
policy, terminal assumptions, and all other best-effort mechanics unchanged.
Only the named diagnostic axis changes:

* capacity_off_100m: remove the research-only 10% trailing-volume guard and use
  the pinned Production adapter's ordinary next-positive-volume-open fill rule.
* capacity_on_10m / capacity_on_1m: retain the 10% guard while reducing the
  synthetic starting account notional to expose account-size dependence.

These are diagnostics, not certification results.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

from backtester import research_best_effort as best_effort

CASES = {
    "capacity_off_100m": {"capacity_guard": False, "initial_cash": 100_000_000.0},
    "capacity_on_10m": {"capacity_guard": True, "initial_cash": 10_000_000.0},
    "capacity_on_1m": {"capacity_guard": True, "initial_cash": 1_000_000.0},
}

_BOOK = "    cash:float=100_000_000.; receivables:list=field(default_factory=list)"
_SELL_GUARD = """                    if _be.capacity(_research_capacity_guard,_BE,s.qty,_capacity_volumes.get(int(s.tid),()),security_id=str(sid[int(s.tid)]),session=ds,defer_excess=True) is None:\n                        continue\n"""
_BUY_GUARD = """                    if _be.capacity(_research_capacity_guard,_BE,s.pending_shares,_capacity_volumes.get(int(tid),()),security_id=str(sid[int(tid)]),session=ds,defer_excess=True) is None:\n                        continue\n"""


def diagnostic_source(source: str, case: str) -> str:
    cfg = CASES[case]
    if source.count(_BOOK) != 1:
        raise RuntimeError(f"initial-cash seam changed: {source.count(_BOOK)}")
    source = source.replace(
        _BOOK,
        f"    cash:float={cfg['initial_cash']:.1f}; receivables:list=field(default_factory=list)",
        1,
    )
    if cfg["capacity_guard"]:
        if source.count(_SELL_GUARD) != 1 or source.count(_BUY_GUARD) != 1:
            raise RuntimeError("capacity guard seam changed")
    else:
        if source.count(_SELL_GUARD) != 1 or source.count(_BUY_GUARD) != 1:
            raise RuntimeError("capacity guard seam changed")
        source = source.replace(_SELL_GUARD, "", 1).replace(_BUY_GUARD, "", 1)
    compile(source, f"<capacity-diagnostic-{case}>", "exec")
    return source


def run(case: str, output: Path) -> int:
    cfg = CASES[case]
    original_build = best_effort.build_source

    def build(output_path):
        source, champion = original_build(output_path)
        return diagnostic_source(source, case), champion

    best_effort.build_source = build
    try:
        rc = best_effort.run(SimpleNamespace(
            scenario="baseline", output=output, self_test=False
        ))
    finally:
        best_effort.build_source = original_build
    if rc:
        return int(rc)

    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["diagnostic"] = {
        "case": case,
        "capacity_guard_enabled": cfg["capacity_guard"],
        "initial_cash": cfg["initial_cash"],
        "purpose": "isolate research-only 10pct participation rule and synthetic-notional dependence",
        "certification_status": "NOT_CERTIFIED",
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    import pandas as pd
    metrics = pd.read_csv(output / "metrics.csv")
    metrics["diagnostic_case"] = case
    metrics["capacity_guard_enabled"] = cfg["capacity_guard"]
    metrics["initial_cash"] = cfg["initial_cash"]
    metrics.to_csv(output / "metrics.csv", index=False)

    max_rows = metrics[metrics.window_years.astype(str) == "max"].to_dict("records")
    audit = json.loads((output / "assumption-audit.json").read_text(encoding="utf-8"))
    result = {
        "case": case,
        "capacity_guard_enabled": cfg["capacity_guard"],
        "initial_cash": cfg["initial_cash"],
        "metrics": max_rows,
        "capacity_deferred": int((audit.get("event_counts") or {}).get("CAPACITY_DEFERRED", 0)),
        "certification_status": "NOT_CERTIFIED",
    }
    (output / "capacity-diagnostic.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("[CAPACITY_DIAGNOSTIC] " + json.dumps(result, sort_keys=True), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=CASES, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("PIT_OFFICIAL_BACKTEST", "0") not in ("", "0"):
        raise RuntimeError("capacity diagnostic must remain explicitly uncertified")
    return run(args.case, args.output.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
