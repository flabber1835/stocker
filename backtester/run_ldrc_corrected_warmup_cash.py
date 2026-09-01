#!/usr/bin/env python3
"""Corrected production-code LD-RC replay.

Fixes two measurement defects in the earlier certified replay:
1. Runs the complete machine through 1997 as warm-up, carrying Wealth Core,
   Sentinel/controller, LD-RC, pending allocation and accounting state into the
   1998-01-02 measurement start.
2. Uses actual BIL factors when available and a causal strict-lag Treasury cash
   return before/missing BIL, sourced from frozen GS3M authority.

The strategy implementation remains the exact pinned current-main production
code. Internal comparison labels are removed from the finalized public bundle.
"""
from __future__ import annotations

from datetime import date
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

import numpy as np
import pandas as pd

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from backtester.historical_cash import complete_cash_factors
from backtester import production_public_reporting

SOURCE = LAB_ROOT / "backtester" / "run_ldrc_nonpit_vs_pit_certified.py"
WARMUP_START = "1997-01-02"
MEASUREMENT_START = "1998-01-02"
CASH_AUTHORITY = LAB_ROOT / "backtester" / "data" / "GS3M_1996-12_2007-05.csv"
RAW_SFP = LAB_ROOT / "sharadar" / "SHARADAR_SFP.zip"

spec = importlib.util.spec_from_file_location("corrected_production_base", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load production replay from {SOURCE}")
prod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = prod
spec.loader.exec_module(prod)
base = prod.base
runner = base.runner

runner.CHAIN_START = WARMUP_START
runner.EXPERIMENT_ID = "2026-08-29-ldrc-warmup-cash-corrected"

# Current public reporting is owned here. The retained comparison module still
# contains an obsolete direct finalizer that reads a pre-gzip filename; suppress
# that intermediate finalization and issue one authenticated public bundle after
# the measurement trim below.
prod._finalize_production_result = lambda result: int(result)
prod._year_end_sessions = set(getattr(prod, "_year_end_sessions", set()))
prod._production_measurement_start = MEASUREMENT_START
prod._public_production_daily = production_public_reporting.public_production_daily
prod._public_production_metrics = production_public_reporting.public_production_metrics
prod._public_metric_summary = production_public_reporting.public_metric_summary
prod._write_final_comparison = lambda: production_public_reporting.write_final_comparison(prod)

_cash_provenance: dict = {}
_original_sfp_builder = base._real_build_sfp_levels


def _read_raw_spy_until(end_session: str) -> pd.DataFrame:
    if not RAW_SFP.exists():
        raise RuntimeError(f"raw SFP archive is missing: {RAW_SFP}")
    parts = []
    with zipfile.ZipFile(RAW_SFP) as zf:
        names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise RuntimeError(f"raw SFP archive expected one CSV, got {names}")
        with zf.open(names[0]) as handle:
            for chunk in pd.read_csv(
                handle, usecols=["ticker", "date", "closeadj"],
                chunksize=450_000, low_memory=False,
            ):
                q = chunk[chunk["ticker"].astype(str).eq("SPY")].copy()
                if q.empty:
                    continue
                q["date"] = q["date"].astype(str).str[:10]
                q = q[(q["date"] >= WARMUP_START) & (q["date"] <= end_session)]
                if not q.empty:
                    parts.append(q[["date", "closeadj"]])
    if not parts:
        raise RuntimeError("raw SFP archive contains no SPY warm-up observations")
    spy = pd.concat(parts, ignore_index=True)
    spy = spy.sort_values("date", kind="mergesort").drop_duplicates("date", keep="last")
    spy["closeadj"] = pd.to_numeric(spy["closeadj"], errors="coerce")
    spy = spy[spy["closeadj"].notna() & (spy["closeadj"] > 0)].copy()
    return spy


def _corrected_sfp_builder(path: Path):
    global _cash_provenance
    sessions, spy_level, spy_return, bil_factors = _original_sfp_builder(path)
    if not sessions:
        raise RuntimeError("base SFP builder returned no sessions")
    first = str(sessions[0])
    raw = _read_raw_spy_until(first)
    first_row = raw[raw["date"].eq(first)]
    if first_row.empty:
        raise RuntimeError(f"raw SPY lacks measurement anchor {first}")
    anchor = float(first_row.iloc[-1]["closeadj"])
    warm = raw[raw["date"] < first].copy()
    if warm.empty or str(warm.iloc[0]["date"]) > WARMUP_START:
        raise RuntimeError("SPY warm-up does not reach requested 1997 start")

    combined_level: dict[str, float] = {}
    combined_return: dict[str, float] = {}
    prior_level = None
    for row in warm.itertuples(index=False):
        session = str(row.date)
        level = float(row.closeadj) / anchor
        combined_level[session] = level
        if prior_level is not None:
            combined_return[session] = level / prior_level - 1.0
        prior_level = level
    if prior_level is None:
        raise RuntimeError("warm-up SPY level construction failed")
    combined_return[first] = 1.0 / prior_level - 1.0
    for session in sessions:
        combined_level[str(session)] = float(spy_level[str(session)])
        if str(session) in spy_return:
            combined_return[str(session)] = float(spy_return[str(session)])

    combined_sessions = [str(x) for x in warm["date"].tolist()] + [str(x) for x in sessions]
    cash, provenance = complete_cash_factors(combined_sessions, bil_factors, CASH_AUTHORITY)
    _cash_provenance = provenance
    return combined_sessions, combined_level, combined_return, cash


base._real_build_sfp_levels = _corrected_sfp_builder


def _corrected_raw_sep_rows(root: Path, manifest, end: str, observed_inputs: dict):
    end_year = int(str(end)[:4])
    for year in range(int(WARMUP_START[:4]), end_year + 1):
        if year >= 1998:
            expected = runner.source_hash_for_year(manifest, year)
            path = runner.find_raw_sep(root, year, expected)
            digest = expected
        else:
            candidates = sorted(root.glob(f"SHARADAR_SEP_{year}.csv*.gz"))
            if not candidates:
                raise RuntimeError(f"missing raw warm-up SEP source for {year}")
            observed = [(p, runner.sha256_file(p)) for p in candidates]
            hashes = {digest for _p, digest in observed}
            if len(hashes) != 1:
                raise RuntimeError(
                    f"non-identical warm-up SEP duplicates for {year}: "
                    + ", ".join(f"{p.name}={digest}" for p, digest in observed)
                )
            path, digest = observed[0]
        observed_inputs[f"sharadar/{path.name}"] = {
            "sha256": digest, "bytes": path.stat().st_size,
        }
        cols = ["ticker", "date", "open", "close", "closeunadj", "volume"]
        frame = pd.read_csv(path, usecols=cols, low_memory=False)
        frame["ticker"] = frame["ticker"].astype(str)
        frame["date"] = frame["date"].astype(str).str[:10]
        frame = frame[(frame["date"] >= WARMUP_START) & (frame["date"] <= end)].copy()
        frame["_seq"] = np.arange(len(frame), dtype=np.int64)
        frame.sort_values(["date", "ticker", "_seq"], inplace=True, kind="mergesort")
        frame.drop_duplicates(["date", "ticker"], keep="last", inplace=True)
        frame.sort_values(["date", "ticker"], inplace=True, kind="mergesort")
        for row in frame.itertuples(index=False):
            yield {
                "ticker": row.ticker, "date": row.date,
                "open": row.open, "close": row.close,
                "closeunadj": row.closeunadj, "volume": row.volume,
            }
        del frame


runner.raw_sep_rows = _corrected_raw_sep_rows

# Compose with the already-installed full-stack PIT accounting wrapper. It owns
# Production's independent Wealth Core return stream and unresolved-open guard.
_pre_measurement_account_step = runner.OverlayAccount.step


def _measured_account_step(self, *args, **kwargs):
    nav = _pre_measurement_account_step(self, *args, **kwargs)
    base._account_refs[str(self.name)] = self
    session = str(base._current_session or "")
    if session == MEASUREMENT_START:
        self.nav = 1.0
        nav = 1.0
    if str(self.name) == "B" and session >= MEASUREMENT_START and session in prod._year_end_sessions:
        a = base._account_refs.get("A")
        if a is None:
            raise RuntimeError("A account missing at corrected year-end checkpoint")
        elapsed = (date.fromisoformat(session) - date.fromisoformat(MEASUREMENT_START)).days / 365.2425
        if elapsed <= 0:
            a_cagr = d_cagr = 0.0
        else:
            a_cagr = float(a.nav) ** (1.0 / elapsed) - 1.0
            d_cagr = float(self.nav) ** (1.0 / elapsed) - 1.0
        print(
            f"[YEAR-END] year={session[:4]} session={session} "
            f"A_nonpit_multiple={float(a.nav):.10f} A_nonpit_cagr={a_cagr:.10%} "
            f"D_fullpit_multiple={float(self.nav):.10f} D_fullpit_cagr={d_cagr:.10%}",
            flush=True,
        )
    return nav


runner.OverlayAccount.step = _measured_account_step


def _trim_measurement_output() -> None:
    daily_path = base.OUTPUT / "daily.csv.gz"
    daily = pd.read_csv(daily_path, compression="gzip")
    daily = daily[daily["date"].astype(str) >= MEASUREMENT_START].copy()
    if daily.empty or str(daily.iloc[0]["date"]) != MEASUREMENT_START:
        raise RuntimeError("corrected daily evidence does not start at measurement boundary")
    daily.to_csv(
        daily_path, index=False,
        compression={"method": "gzip", "compresslevel": 6, "mtime": 0},
    )


def _finalize_provenance() -> None:
    output = base.OUTPUT
    summary_path = output / "summary.json"
    manifest_path = output / "manifest.json"
    sums_path = output / "SHA256SUMS.txt"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["warmup"] = {
        "start": WARMUP_START,
        "measurement_start": MEASUREMENT_START,
        "full_machine_state_carried": True,
        "measured_warmup_sessions": 0,
        "purpose": "populate Wealth Core holdings/path state plus Sentinel and LD-RC state before measurement",
    }
    summary["defensive_cash_authority"] = {
        **_cash_provenance,
        "measurement_policy": "actual BIL when available; strict-prior completed-month GS3M before or when BIL unavailable",
    }
    summary["calendar_year_cagr_definition"] = (
        "cumulative measured Production NAV from 1998-01-02 after full 1997 machine warm-up"
    )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["warmup_start"] = WARMUP_START
    manifest["measurement_start"] = MEASUREMENT_START
    manifest["cash_authority"] = _cash_provenance
    for path in (output / "daily.csv.gz", output / "metrics.csv", summary_path):
        manifest.setdefault("outputs", {})[path.name] = {
            "sha256": base._sha256(path), "bytes": path.stat().st_size,
        }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = (output / "daily.csv.gz", output / "metrics.csv", summary_path, manifest_path)
    sums_path.write_text(
        "".join(f"{base._sha256(path)}  {path.name}\n" for path in files), encoding="utf-8"
    )


def main() -> int:
    print("[RUN] corrected production replay: 1997 full-machine warm-up + causal historical cash", flush=True)
    rc = int(prod.main())
    if rc != 0:
        return rc
    _trim_measurement_output()
    prod._write_final_comparison()
    _finalize_provenance()
    print("[PASS] corrected production replay bundle complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())