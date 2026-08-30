#!/usr/bin/env python3
"""Parallel strict-PIT certification for 2006-07-31 through 2026-07-31."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

import backtester.run_certification_parallel as base

WARMUP_START = pd.Timestamp("2006-01-03")
MEASUREMENT_START = pd.Timestamp("2006-07-31")
PRODUCTION_WRAPPER = Path("backtester/run_production_strict_pit_20y.py")
RESEARCH_WRAPPER = Path("backtester/run_research_strict_pit_20y.py")


def _consume_end_session() -> str:
    args = list(sys.argv[1:])
    end = "2026-07-31"
    if "--end-session" in args:
        i = args.index("--end-session")
        try:
            end = args[i + 1]
        except IndexError as exc:
            raise RuntimeError("--end-session requires YYYY-MM-DD") from exc
        del args[i : i + 2]
    sys.argv = [sys.argv[0], *args]
    return end


def _option_path(flag: str) -> Path:
    args = list(sys.argv[1:])
    for i, value in enumerate(args):
        if value == flag and i + 1 < len(args):
            return Path(args[i + 1])
        prefix = flag + "="
        if value.startswith(prefix):
            return Path(value[len(prefix):])
    raise RuntimeError(f"missing required {flag}")


def _first_field_divergence(
    merged: pd.DataFrame,
    production_column: str,
    research_column: str,
    tolerance: float,
) -> dict | None:
    for row in merged.itertuples(index=False):
        p = getattr(row, production_column)
        r = getattr(row, research_column)
        p_nan = pd.isna(p)
        r_nan = pd.isna(r)
        if p_nan and r_nan:
            continue
        if p_nan != r_nan:
            return {
                "date": pd.Timestamp(row.date).date().isoformat(),
                "production": None if p_nan else float(p),
                "research": None if r_nan else float(r),
                "reason": "missingness_mismatch",
            }
        p = float(p)
        r = float(r)
        if not math.isfinite(p) or not math.isfinite(r):
            if p != r:
                return {
                    "date": pd.Timestamp(row.date).date().isoformat(),
                    "production": p,
                    "research": r,
                    "reason": "nonfinite_mismatch",
                }
            continue
        delta = abs(p - r)
        scale = max(abs(p), abs(r), 1.0)
        if delta > tolerance * scale:
            return {
                "date": pd.Timestamp(row.date).date().isoformat(),
                "production": p,
                "research": r,
                "absolute_delta": delta,
                "relative_delta": delta / scale,
            }
    return None


def _strong_equivalence(output_root: Path, tolerance: float = 1e-10) -> int:
    production = pd.read_csv(
        output_root / "production" / "daily.csv.gz", compression="gzip", parse_dates=["date"]
    )
    research = pd.read_csv(
        output_root / "research" / "daily.csv.gz", compression="gzip", parse_dates=["date"]
    )
    pairs = {
        "nav": ("D_nav", "research_nav"),
        "wealth_core_equity": ("D_wealth_core_equity", "research_wealth_core_equity"),
        "allocation": ("D_allocation", "research_allocation"),
        "native_target": ("D_native", "native_close_target"),
        "damaged_breadth": ("D_damaged", "damaged"),
    }
    required_p = {"date", *(pair[0] for pair in pairs.values())}
    required_r = {"date", *(pair[1] for pair in pairs.values())}
    if not required_p.issubset(production.columns):
        raise RuntimeError(
            f"production strong-equivalence evidence missing {sorted(required_p-set(production.columns))}"
        )
    if not required_r.issubset(research.columns):
        raise RuntimeError(
            f"research strong-equivalence evidence missing {sorted(required_r-set(research.columns))}"
        )
    merged = production[list(required_p)].merge(
        research[list(required_r)], on="date", how="outer", indicator=True
    ).sort_values("date")
    if not merged["_merge"].eq("both").all():
        bad = merged.loc[~merged["_merge"].eq("both")].iloc[0]
        divergence = {
            "field": "session_axis",
            "date": pd.Timestamp(bad.date).date().isoformat(),
            "side": str(bad["_merge"]),
        }
    else:
        divergence = None
        merged = merged.drop(columns=["_merge"])
        for field, (p_col, r_col) in pairs.items():
            found = _first_field_divergence(merged, p_col, r_col, tolerance)
            if found is not None:
                divergence = {"field": field, **found}
                break

    audit = {
        "schema": "backtester.strict-pit-20y-strong-equivalence/1",
        "measurement_start": MEASUREMENT_START.date().isoformat(),
        "tolerance": tolerance,
        "fields": pairs,
        "first_divergence": divergence,
        "sessions_compared": int(len(merged)),
    }
    (output_root / "strong_equivalence_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if divergence is not None:
        print("[STRONG EQUIVALENCE FAIL] " + json.dumps(divergence, sort_keys=True), flush=True)
        return 3
    print(
        "[STRONG EQUIVALENCE PASS] NAV, Wealth Core equity, allocation, native target, and damaged breadth match",
        flush=True,
    )
    return 0


def main() -> int:
    end = _consume_end_session()
    output_root = _option_path("--output-root")
    os.environ["CERTIFICATION_END_SESSION"] = end
    os.environ["CERTIFICATION_WARMUP_START"] = WARMUP_START.date().isoformat()
    os.environ["CERTIFICATION_MEASUREMENT_START"] = MEASUREMENT_START.date().isoformat()

    base.WARMUP_START = WARMUP_START
    base.MEASUREMENT_START = MEASUREMENT_START
    base.PRODUCTION_WRAPPER = PRODUCTION_WRAPPER
    base.RESEARCH_WRAPPER = RESEARCH_WRAPPER

    real_print = print

    def certification_print(*args, **kwargs):
        first = str(args[0]) if args else ""
        if first.startswith("[WARMUP] 1997-"):
            return
        real_print(*args, **kwargs)
        if first.startswith("[CERTIFICATION] strict PIT"):
            for session in ("2006-03-31", "2006-06-30", "2006-07-28"):
                real_print(
                    f"[WARMUP] {session} full machine state accumulating; CAGR=N/A",
                    flush=True,
                )

    base.print = certification_print
    rc = int(base.main())
    if rc != 0:
        return rc
    return _strong_equivalence(output_root)


if __name__ == "__main__":
    raise SystemExit(main())
