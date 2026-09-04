#!/usr/bin/env python3
"""Continuous S&P best-effort PIT LD-RC replay through 2026-07-31.

This deliberately reuses the exact sealed-OOS harness and frozen LD-RC source,
extends only the dated S&P eligibility horizon, and preserves one continuous
portfolio/controller state path across the 2005/2006 boundary.  It emits the
standard 5y/10y/15y/20y/Max views from that single path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

import backtester.run_sp500_ldrc_sealed_oos as base

WINDOW_END = "2026-07-31"
WINDOWS = {
    "5": "2021-07-30",
    "10": "2016-07-29",
    "15": "2011-07-29",
    "20": "2006-07-31",
}
EXPECTED_PRE2006_END = "2005-12-30"
EXPECTED_PRE2006_CONTROL_NAV = 2.8822811536528485
EXPECTED_PRE2006_SPY_NAV = 1.4394278879361175
EXPECTED_PRE2006_SESSIONS = 2013


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _fixed_generated_source(corrected, output: Path) -> str:
    """Repair the sealed helper's generated-code scope without changing economics."""
    text = _ORIGINAL_SEALED_SOURCE(corrected, output)
    replacements = (
        (
            "def sp500_security_id(tid,ds):\n    _tk=str(tick[int(tid)])",
            "def sp500_security_id(ticker_value,ds):\n    _tk=str(ticker_value)",
            1,
        ),
        (
            "sp500_security_id(int(_i),ds)",
            "sp500_security_id(tick[int(_i)],ds)",
            2,
        ),
        (
            "sp500_security_id(tid,ds)",
            "sp500_security_id(tick[tid],ds)",
            2,
        ),
    )
    for old, new, expected in replacements:
        observed = text.count(old)
        if observed != expected:
            raise RuntimeError(
                f"sealed generated-source seam changed: {old!r}: {observed} != {expected}"
            )
        text = text.replace(old, new)
    return text


def _seam_witness(daily: pd.DataFrame) -> dict:
    prior = daily[daily["date"] <= pd.Timestamp(EXPECTED_PRE2006_END)].copy()
    if len(prior) != EXPECTED_PRE2006_SESSIONS:
        raise RuntimeError(
            f"pre-2006 session count drift: {len(prior)} != {EXPECTED_PRE2006_SESSIONS}"
        )
    row = prior.iloc[-1]
    control = float(row["control_nav"])
    spy = float(row["spy_nav"])
    if abs(control - EXPECTED_PRE2006_CONTROL_NAV) > 1e-10:
        raise RuntimeError(
            f"continuous replay changed sealed OOS control path: {control} != "
            f"{EXPECTED_PRE2006_CONTROL_NAV}"
        )
    if abs(spy - EXPECTED_PRE2006_SPY_NAV) > 1e-10:
        raise RuntimeError(
            f"continuous replay changed sealed OOS SPY path: {spy} != "
            f"{EXPECTED_PRE2006_SPY_NAV}"
        )
    after = daily[daily["date"] > pd.Timestamp(EXPECTED_PRE2006_END)]
    if after.empty:
        raise RuntimeError("continuous replay has no post-2005 sessions")
    return {
        "pre2006_end": EXPECTED_PRE2006_END,
        "pre2006_sessions": int(len(prior)),
        "control_nav": control,
        "spy_nav": spy,
        "next_session": str(after.iloc[0]["date"].date()),
        "state_reset": False,
        "matches_sealed_oos_exactly": True,
    }


def run(*, universe_root: Path, output: Path) -> dict:
    # The base harness reads these globals at execution time.  No strategy,
    # ranking, sizing, exit, transaction-cost, or controller constant changes.
    base.WINDOW_END = WINDOW_END
    base._sealed_source = _fixed_generated_source

    base_summary = base.run(universe_root=universe_root, output=output)
    daily_path = output / "daily.csv.gz"
    daily = pd.read_csv(daily_path, parse_dates=["date"])
    if daily.empty or str(daily.iloc[-1]["date"].date()) != WINDOW_END:
        raise RuntimeError("continuous S&P replay did not reach requested endpoint")

    seam = _seam_witness(daily)
    first_invested = pd.Timestamp(base_summary["first_invested_session"])

    metric_rows = []
    for window, start_text in WINDOWS.items():
        start = pd.Timestamp(start_text)
        for variant, column in (("LD_RC", "control_nav"), ("SPY", "spy_nav")):
            metric_rows.append({
                "window_years": window,
                "variant": variant,
                **base._metric(daily, column, start),
            })
    for variant, column in (("LD_RC", "control_nav"), ("SPY", "spy_nav")):
        metric_rows.append({
            "window_years": "Max",
            "variant": variant,
            **base._metric(daily, column, first_invested),
        })

    metrics = pd.DataFrame(metric_rows)
    metrics.to_csv(output / "metrics.csv", index=False)
    by_window = {
        window: {
            row["variant"].lower(): row
            for row in metric_rows
            if row["window_years"] == window
        }
        for window in ["5", "10", "15", "20", "Max"]
    }
    for block in by_window.values():
        block["cagr_spread_ldrc_minus_spy"] = (
            block["ld_rc"]["cagr"] - block["spy"]["cagr"]
        )

    summary = {
        "schema": "backtester.sp500-ldrc-continuous/1",
        "status": "PASS",
        "experiment": "SP500_BEST_EFFORT_PIT_CONTINUOUS_1997_2026",
        "formal_pit_certified": False,
        "best_effort_pit": True,
        "continuous_state_path": True,
        "window": [base.WINDOW_START, WINDOW_END],
        "first_invested_session": str(first_invested.date()),
        "strategy_embedded_commit": base.EXPECTED_RESEARCH_COMMIT,
        "strategy_git_blob_sha1": base.EXPECTED_BLOBS[str(base.STRATEGY_SOURCE)],
        "membership_dataset_hash": base.EXPECTED_MEMBERSHIP_DATASET_HASH,
        "eligibility_sha256": base_summary["eligibility_sha256"],
        "pre2006_seam_witness": seam,
        "windows": by_window,
        "universe": base_summary["universe"],
        "pre2006_oos_evidence": {
            "status": "CONSUMED_AND_PRESERVED",
            "repository_file": "backtester/evidence/sp500_ldrc_oos_1998_2005.json",
            "original_run_id": 33827090507,
            "original_artifact_id": 9920465803,
            "original_artifact_zip_sha256": "a006c2c87360e016262f46c211a9e10c1dad29ba4d6ec3f6e39d49da47e07568"
        },
        "interpretation_guard": (
            "All 5/10/15/20/Max metrics come from one uninterrupted state path. "
            "The pre-2001 S&P membership region remains explicitly best-effort; "
            "formal PIT certification is not claimed."
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    members = [
        output / "freeze.json",
        output / "engine-summary.json",
        output / "summary.json",
        output / "metrics.csv",
        output / "daily.csv.gz",
    ]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(p)}  {p.name}\n" for p in sorted(members)),
        encoding="utf-8",
    )
    return summary


_ORIGINAL_SEALED_SOURCE = base._sealed_source


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--universe-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(run(**vars(args)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
