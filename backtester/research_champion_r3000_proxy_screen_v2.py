#!/usr/bin/env python3
"""Russell-3000-proxy observation screen for the frozen Research Champion.

RESEARCH / NOT CERTIFIED.

Uses IWV (iShares Russell 3000 ETF) as a fixed broad-market observation series.
Champion economics and the V2 Candidate-A state-machine mechanics remain frozen.
The IWV observations are mapped onto the existing V2 market-price/volatility
observation slots so the comparison against SPY is mechanically identical.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from research_champion_market_risk_screen_v2 import (
    MEASUREMENT_END,
    MEASUREMENT_START,
    current_proxy,
    episode_stats,
    metrics,
    simulate,
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_iwv(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    names = {str(c).strip().upper(): c for c in raw.columns}
    dc = names.get("DATE")
    cc = names.get("CLOSE") or names.get("IWV_CLOSE")
    if dc is None or cc is None:
        raise RuntimeError(f"unsupported IWV columns {list(raw.columns)}")
    d = raw[[dc, cc]].copy()
    d.columns = ["date", "iwv_close"]
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["iwv_close"] = pd.to_numeric(d["iwv_close"], errors="coerce")
    d = d.dropna().drop_duplicates("date", keep="last").sort_values("date")
    d = d[(d.date >= MEASUREMENT_START - pd.Timedelta(days=400)) & (d.date <= MEASUREMENT_END)]
    if d.empty:
        raise RuntimeError("IWV series empty in required window")
    return d


def enrich_iwv(baseline: pd.DataFrame, iwv: pd.DataFrame) -> pd.DataFrame:
    d = baseline.copy()
    d["date"] = pd.to_datetime(d.date)
    d = d.sort_values("date").reset_index(drop=True)
    if d.iloc[0].date != MEASUREMENT_START or d.iloc[-1].date != MEASUREMENT_END:
        raise RuntimeError("baseline measurement window changed")

    m = iwv.copy().set_index("date")
    px = m.iwv_close.astype(float)
    ret = px.pct_change()
    m["iwv_r20"] = px.pct_change(20)
    m["iwv_r40"] = px.pct_change(40)
    m["iwv_dd"] = px / px.cummax() - 1.0
    m["iwv_rv20"] = ret.rolling(20).std(ddof=1) * math.sqrt(252)
    m["iwv_rv40"] = ret.rolling(40).std(ddof=1) * math.sqrt(252)
    m["iwv_vol_ratio"] = m.iwv_rv20 / m.iwv_rv40

    d = d.join(m[["iwv_close", "iwv_r20", "iwv_r40", "iwv_dd", "iwv_rv20", "iwv_rv40", "iwv_vol_ratio"]], on="date")
    if int(d.iwv_close.isna().sum()):
        d["iwv_close"] = d.iwv_close.ffill(limit=1)
        for c in ["iwv_r20", "iwv_r40", "iwv_dd", "iwv_rv20", "iwv_rv40", "iwv_vol_ratio"]:
            d[c] = d[c].ffill(limit=1)
    if d.iwv_close.isna().any():
        raise RuntimeError("unresolved IWV dates in baseline window")

    d["spy_r20"] = d.iwv_r20
    d["spy_r40"] = d.iwv_r40
    d["spy_dd"] = d.iwv_dd
    d["spy_rv20"] = d.iwv_rv20
    d["spy_rv40"] = d.iwv_rv40
    d["spy_vol_ratio"] = d.iwv_vol_ratio
    d["wc_r20"] = d.research_wealth_core_equity.astype(float).pct_change(20)
    return d


def grids():
    for r20, dd in itertools.product((-0.04, -0.06, -0.08, -0.10), (-0.06, -0.10, -0.14, -0.18)):
        yield "r3000_price", "spy_price", dict(r20_stress=r20, dd_stress=dd, r20_healthy=0.0, r40_healthy=0.0)
    for rv, ratio, healthy in itertools.product((0.18, 0.22, 0.26, 0.30), (1.0, 1.1, 1.2), (0.16, 0.18, 0.20)):
        yield "r3000_vol", "spy_vol", dict(rv20_stress=rv, ratio_stress=ratio, rv20_healthy=healthy, ratio_healthy=1.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-daily", type=Path, required=True)
    ap.add_argument("--iwv-csv", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    iwv = load_iwv(args.iwv_csv)
    frame = enrich_iwv(pd.read_csv(args.baseline_daily), iwv)
    cur = current_proxy(frame)
    current_alloc = frame.research_allocation.astype(float).to_numpy()

    rows = []
    for n, (label, family, params) in enumerate(grids()):
        sim, state = simulate(frame, family, params)
        m = metrics(sim.proxy_nav, sim.date)
        alloc = sim.allocation.astype(float).to_numpy()
        changed = np.flatnonzero(abs(alloc - current_alloc) > 1e-12)
        eps, avg, mx = episode_stats(alloc)
        rows.append({
            "candidate_id": f"v2-{label}-{n:04d}",
            "family": label,
            "engine_family": family,
            "params": json.dumps(params, sort_keys=True, separators=(",", ":")),
            **m,
            **state,
            "reduced_sessions": int((alloc < 1 - 1e-12).sum()),
            "defensive_episodes": eps,
            "mean_defensive_duration": avg,
            "max_defensive_duration": mx,
            "allocation_sessions_changed_vs_current": int(len(changed)),
            "first_allocation_divergence": str(frame.iloc[int(changed[0])].date.date()) if len(changed) else "",
        })

    out = pd.DataFrame(rows)
    out["proxy_cagr_gap_vs_current"] = out.proxy_cagr - cur["proxy_cagr"]
    out["proxy_dd_gap_vs_current"] = out.proxy_max_dd - cur["proxy_max_dd"]
    out.to_csv(args.output / "coarse-grid-r3000-v2.csv", index=False)

    summary = []
    for fam, g in out.groupby("family"):
        acceptable = g[(g.proxy_cagr_gap_vs_current >= -0.02) & (g.proxy_dd_gap_vs_current <= 0.03)]
        best = g.sort_values(["proxy_cagr", "proxy_max_dd"], ascending=[False, False]).iloc[0]
        summary.append({
            "family": fam,
            "grid_points": len(g),
            "acceptable_points": len(acceptable),
            "proxy_cagr_median": g.proxy_cagr.median(),
            "proxy_cagr_max": g.proxy_cagr.max(),
            "proxy_max_dd_median": g.proxy_max_dd.median(),
            "best_candidate_id": best.candidate_id,
            "best_params": best.params,
            "best_proxy_cagr": best.proxy_cagr,
            "best_proxy_max_dd": best.proxy_max_dd,
            "best_proxy_sharpe": best.proxy_sharpe,
        })
    pd.DataFrame(summary).to_csv(args.output / "family-summary-r3000-v2.csv", index=False)

    source_cut = iwv[(iwv.date >= pd.Timestamp("2005-01-01")) & (iwv.date <= MEASUREMENT_END)].copy()
    source_cut.to_csv(args.output / "iwv-cutoff-through-2026-07-31.csv", index=False)
    manifest = {
        "status": "RESEARCH / NOT CERTIFIED",
        "proxy": "IWV - iShares Russell 3000 ETF",
        "measurement_start": str(MEASUREMENT_START.date()),
        "measurement_end": str(MEASUREMENT_END.date()),
        "baseline_daily_sha256": sha256(args.baseline_daily),
        "iwv_input_sha256": sha256(args.iwv_csv),
        "iwv_cutoff_sha256": sha256(args.output / "iwv-cutoff-through-2026-07-31.csv"),
        "current_proxy": cur,
        "mechanics": "V2 state machine unchanged; IWV observations mapped into SPY price/vol slots",
    }
    (args.output / "manifest-r3000-v2.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(pd.DataFrame(summary).to_string(index=False))
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
