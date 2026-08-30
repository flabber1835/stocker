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
from backtester.canonical_pit_dataset import CanonicalPITDataset

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


def _consume_path(flag: str) -> Path:
    args = list(sys.argv[1:])
    for i, value in enumerate(args):
        if value == flag and i + 1 < len(args):
            result = Path(args[i + 1])
            del args[i:i + 2]
            sys.argv = [sys.argv[0], *args]
            return result
        prefix = flag + "="
        if value.startswith(prefix):
            result = Path(value[len(prefix):])
            del args[i]
            sys.argv = [sys.argv[0], *args]
            return result
    raise RuntimeError(f"missing required {flag}")


def _verify_canonical_consumption(output_root: Path, expected_hash: str) -> None:
    summaries = {}
    hash_files = {}
    for role in ("research", "production"):
        summaries[role] = json.loads(
            (output_root / role / "summary.json").read_text(encoding="utf-8")
        )
        observed = summaries[role].get("canonical_pit_dataset_hash")
        if observed != expected_hash:
            raise RuntimeError(
                f"{role} canonical dataset hash mismatch: {observed} != {expected_hash}"
            )
        path = output_root / role / "canonical_input_session_hashes.csv"
        hash_files[role] = path.read_bytes()
    if hash_files["research"] != hash_files["production"]:
        raise RuntimeError("research/production canonical per-session hashes differ")
    audit = {
        "schema": "backtester.canonical-input-consumption/1",
        "dataset_hash": expected_hash,
        "roles": {role: summaries[role]["canonical_pit_dataset_hash"] for role in summaries},
        "per_session_hashes_identical": True,
    }
    (output_root / "canonical_input_consumption_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


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


def _first_exact_divergence(
    merged: pd.DataFrame, production_column: str, research_column: str
) -> dict | None:
    for row in merged.itertuples(index=False):
        production = getattr(row, production_column)
        research = getattr(row, research_column)
        if (pd.isna(production) and pd.isna(research)):
            continue
        if str(production) != str(research):
            return {
                "date": pd.Timestamp(row.date).date().isoformat(),
                "production": None if pd.isna(production) else str(production),
                "research": None if pd.isna(research) else str(research),
            }
    return None


def _first_strategy_divergence(
    merged: pd.DataFrame,
    numeric_pairs: dict[str, tuple[str, str]],
    exact_pairs: dict[str, tuple[str, str]],
    ordered_fields: tuple[str, ...],
    tolerance: float,
) -> dict | None:
    for index in range(len(merged)):
        session = merged.iloc[[index]]
        for field in ordered_fields:
            if field in exact_pairs:
                production_column, research_column = exact_pairs[field]
                found = _first_exact_divergence(
                    session, production_column, research_column
                )
            else:
                production_column, research_column = numeric_pairs[field]
                found = _first_field_divergence(
                    session, production_column, research_column, tolerance
                )
            if found is not None:
                return {"field": field, **found}
    return None


def _strong_equivalence(
    output_root: Path, tolerance: float = 1e-10, *, require_match: bool = True
) -> int:
    production = pd.read_csv(
        output_root / "production" / "daily.csv.gz", compression="gzip", parse_dates=["date"]
    )
    research = pd.read_csv(
        output_root / "research" / "daily.csv.gz", compression="gzip", parse_dates=["date"]
    )
    numeric_pairs = {
        "eligible_universe": ("D_eligible_universe", "research_eligible_universe"),
        "ranking_count": ("D_ranking_count", "research_ranking_count"),
        "nav": ("D_nav", "research_nav"),
        "wealth_core_equity": ("D_wealth_core_equity", "research_wealth_core_equity"),
        "allocation": ("D_allocation", "research_allocation"),
        "native_target": ("D_native", "native_close_target"),
        "damaged_breadth": ("D_damaged", "damaged"),
    }
    exact_pairs = {
        "rankings": ("D_ranking_sha256", "research_ranking_sha256"),
        "selected_positions": (
            "D_selected_positions_sha256", "research_selected_positions_sha256"
        ),
        "ldrc_state": ("D_ldrc_state", "research_ldrc_state"),
    }
    ordered_fields = (
        "eligible_universe", "ranking_count", "rankings", "selected_positions",
        "wealth_core_equity", "damaged_breadth", "native_target", "ldrc_state",
        "allocation", "nav",
    )
    required_p = {"date", *(pair[0] for pair in numeric_pairs.values()),
                  *(pair[0] for pair in exact_pairs.values())}
    required_r = {"date", *(pair[1] for pair in numeric_pairs.values()),
                  *(pair[1] for pair in exact_pairs.values())}
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
        merged = merged.drop(columns=["_merge"])
        divergence = _first_strategy_divergence(
            merged, numeric_pairs, exact_pairs, ordered_fields, tolerance
        )

    audit = {
        "schema": "backtester.strict-pit-20y-strong-equivalence/1",
        "measurement_start": MEASUREMENT_START.date().isoformat(),
        "tolerance": tolerance,
        "numeric_fields": numeric_pairs,
        "exact_fields": exact_pairs,
        "first_divergence": divergence,
        "sessions_compared": int(len(merged)),
    }
    (output_root / "strong_equivalence_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if divergence is not None:
        print("[STRONG EQUIVALENCE FAIL] " + json.dumps(divergence, sort_keys=True), flush=True)
        return 3 if require_match else 0
    print(
        "[STRONG EQUIVALENCE PASS] NAV, Wealth Core equity, allocation, native target, and damaged breadth match",
        flush=True,
    )
    return 0


def main() -> int:
    end = _consume_end_session()
    canonical_path = _consume_path("--canonical-dataset")
    canonical = CanonicalPITDataset(
        canonical_path, expected_start=WARMUP_START.date().isoformat(), expected_end=end
    )
    output_root = _option_path("--output-root")
    os.environ["CERTIFICATION_END_SESSION"] = end
    os.environ["CERTIFICATION_WARMUP_START"] = WARMUP_START.date().isoformat()
    os.environ["CERTIFICATION_MEASUREMENT_START"] = MEASUREMENT_START.date().isoformat()
    os.environ["CANONICAL_PIT_DATASET"] = str(canonical_path.resolve())

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
    _verify_canonical_consumption(output_root, canonical.dataset_hash)
    return _strong_equivalence(
        output_root, require_match=(end == "2026-07-31")
    )


if __name__ == "__main__":
    raise SystemExit(main())
