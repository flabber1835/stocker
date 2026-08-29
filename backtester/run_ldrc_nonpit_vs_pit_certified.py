#!/usr/bin/env python3
"""Certified LD-RC comparison: current-metadata baseline vs retained full-PIT economic path.

This launcher layers reporting/certification requirements on the already-proven
A/D chronological replay. It pins the exact requested current-main Wealth Core
source, emits exact calendar-year cumulative CAGR checkpoints, and adds a
maximum-common-history measurement window alongside 5/10/15/20-year windows.
"""
from __future__ import annotations

from datetime import date
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

EXPECTED_MAIN_SHA = "887f479b15ad861313da666ad698034d3847121c"
LAB_ROOT = Path(__file__).resolve().parents[1]
BASE_LAUNCHER = LAB_ROOT / "backtester" / "run_sector_ad_causal_terminal_terms_v2.py"

spec = importlib.util.spec_from_file_location("ldrc_ad_base", BASE_LAUNCHER)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load base launcher from {BASE_LAUNCHER}")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

# Bind the experiment to the exact current-main Wealth Core implementation.
base.runner.EXPECTED_MAIN_SHA = EXPECTED_MAIN_SHA
base.runner.EXPERIMENT_ID = "2026-08-29-ldrc-nonpit-vs-pit-certified"

_year_end_sessions: set[str] = set()
_real_build_sfp_levels = base.runner.build_sfp_levels
_real_overlay_step = base.runner.OverlayAccount.step


def _build_sfp_levels_with_year_ends(*args, **kwargs):
    result = _real_build_sfp_levels(*args, **kwargs)
    sessions = list(result[0])
    _year_end_sessions.clear()
    for i, session in enumerate(sessions):
        if i + 1 < len(sessions) and sessions[i + 1][:4] != session[:4]:
            _year_end_sessions.add(str(session))
    return result


def _overlay_step_with_calendar_year_cagr(self, *args, **kwargs):
    nav = _real_overlay_step(self, *args, **kwargs)
    if str(self.name) == "B":
        session = str(base._current_session or "")
        if session in _year_end_sessions:
            a = base._account_refs.get("A")
            if a is None:
                raise RuntimeError("A account missing at calendar-year CAGR checkpoint")
            print(
                f"[YEAR-END] year={session[:4]} session={session} "
                f"A_nonpit_multiple={float(a.nav):.10f} "
                f"A_nonpit_cagr={base._running_cagr(float(a.nav), session):.10%} "
                f"D_pit_multiple={float(self.nav):.10f} "
                f"D_pit_cagr={base._running_cagr(float(self.nav), session):.10%}",
                flush=True,
            )
    return nav


base.runner.build_sfp_levels = _build_sfp_levels_with_year_ends
base.runner.OverlayAccount.step = _overlay_step_with_calendar_year_cagr


def _max_metric_block(frame: pd.DataFrame, column: str) -> dict:
    x = frame[["date", column]].dropna().copy()
    if x.empty or str(x.iloc[-1]["date"]) != str(base.runner.END_SESSION):
        raise RuntimeError(f"{column} has incomplete maximum-history measurement window")
    values = x[column].astype(float).to_numpy()
    if len(values) < 2 or values[0] <= 0 or values[-1] <= 0:
        raise RuntimeError(f"{column} invalid maximum-history measurement values")
    start = str(x.iloc[0]["date"])
    end = str(x.iloc[-1]["date"])
    elapsed_years = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.2425
    if elapsed_years <= 0:
        raise RuntimeError("maximum-history elapsed years is non-positive")
    normalized = values / values[0]
    rets = normalized[1:] / normalized[:-1] - 1.0
    std = float(np.std(rets, ddof=1)) if len(rets) > 1 else float("nan")
    sharpe = float(np.mean(rets) / std * math.sqrt(252.0)) if std > 0 else float("nan")
    peak = np.maximum.accumulate(normalized)
    max_dd = float(np.min(normalized / peak - 1.0))
    cagr = float(normalized[-1] ** (1.0 / elapsed_years) - 1.0)
    return {
        "start": start,
        "end": end,
        "sessions": int(len(x)),
        "elapsed_years": float(elapsed_years),
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "ending_multiple": float(normalized[-1]),
    }


def _write_final_comparison() -> None:
    output = base.OUTPUT
    daily_path = output / "daily.csv.gz"
    metrics_path = output / "metrics.csv"
    summary_path = output / "summary.json"
    manifest_path = output / "manifest.json"
    sums_path = output / "SHA256SUMS.txt"

    daily = pd.read_csv(daily_path, compression="gzip")
    required = {"date", "A_nav", "D_nav", "SPY_level"}
    missing = required.difference(daily.columns)
    if missing:
        raise RuntimeError(f"daily output missing required comparison columns: {sorted(missing)}")

    max_blocks = {
        "A": _max_metric_block(daily, "A_nav"),
        "D": _max_metric_block(daily, "D_nav"),
        "SPY": _max_metric_block(daily, "SPY_level"),
    }

    metrics = pd.read_csv(metrics_path, dtype={"window_years": str})
    metrics = metrics[metrics["window_years"].astype(str) != "max"].copy()
    max_rows = []
    for label, block in max_blocks.items():
        max_rows.append({
            "window_years": "max",
            "variant": label,
            "start": block["start"],
            "end": block["end"],
            "sessions": block["sessions"],
            "cagr": block["cagr"],
            "sharpe": block["sharpe"],
            "max_drawdown": block["max_drawdown"],
            "ending_multiple": block["ending_multiple"],
        })
    metrics = pd.concat([metrics, pd.DataFrame(max_rows)], ignore_index=True)
    metrics.to_csv(metrics_path, index=False)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.setdefault("metrics", {})["max"] = max_blocks
    summary["comparison_contract"] = {
        "A": "LD-RC with existing current/non-PIT Sharadar metadata baseline",
        "D": "same LD-RC with retained full-PIT economic data path",
        "wealth_core": f"exact current main {EXPECTED_MAIN_SHA}; A/D parity required every session",
        "measurement_windows": ["5", "10", "15", "20", "max"],
        "spy": "same frozen PIT-reconstructed SPY total-return factor series used for both comparison columns",
    }
    summary["calendar_year_cagr_checkpoints"] = sorted(_year_end_sessions)
    summary["calendar_year_cagr_definition"] = (
        "cumulative strategy NAV from replay inception annualized through each completed calendar-year final trading session"
    )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["experiment"] = base.runner.EXPERIMENT_ID
    manifest["current_main_sha"] = EXPECTED_MAIN_SHA
    outputs = manifest.setdefault("outputs", {})
    for path in (daily_path, metrics_path, summary_path):
        outputs[path.name] = {"sha256": base._sha256(path), "bytes": path.stat().st_size}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files = (daily_path, metrics_path, summary_path, manifest_path)
    sums_path.write_text(
        "".join(f"{base._sha256(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )

    print("[FINAL METRICS] 5/10/15/20/max trailing windows", flush=True)
    print(metrics.to_csv(index=False), flush=True)


def main() -> int:
    print(f"[RUN] certified comparison current-main={EXPECTED_MAIN_SHA}", flush=True)
    rc = int(base.main())
    if rc != 0:
        return rc
    _write_final_comparison()
    print("[PASS] certified non-PIT/PIT LD-RC comparison bundle complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
