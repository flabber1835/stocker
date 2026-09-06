#!/usr/bin/env python3
"""Coarse market-risk controller screen for the frozen Research Champion.

RESEARCH / NOT CERTIFIED.

This phase uses the authoritative corrected Champion daily artifact as a frozen
underlying Wealth Core + Native Sentinel path. It changes only the LDRC market-
risk observation layer. Exact finalists must be rerun through the full replay.
The screen's NAV is deliberately labelled a proxy because the baseline artifact
omits canonical defensive-cash factors; zero cash return is used for screening.
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

LDRC_REC = 8
LDRC_DD = -0.10
LDRC_CEIL = 0.55
COST = 0.001
BASELINE_RUN_ID = 34007704385
BASELINE_ARTIFACT_ID = 9981966560
BASELINE_ARTIFACT_DIGEST = "sha256:4860751ea45f7480f785e927bc4cebba1c8be3783b354d186ce059d6fb09a841"
MEASUREMENT_START = pd.Timestamp("2006-07-31")
MEASUREMENT_END = pd.Timestamp("2026-07-31")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def finite(x) -> bool:
    return x is not None and np.isfinite(x)


def load_vix(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    names = {str(c).strip().upper(): c for c in raw.columns}
    date_col = names.get("DATE") or names.get("OBSERVATION_DATE")
    close_col = names.get("CLOSE") or names.get("VIXCLS")
    if date_col is None or close_col is None:
        raise RuntimeError(f"unsupported VIX columns: {list(raw.columns)}")
    v = raw[[date_col, close_col]].copy()
    v.columns = ["date", "vix"]
    v["date"] = pd.to_datetime(v["date"], errors="coerce")
    v["vix"] = pd.to_numeric(v["vix"], errors="coerce")
    v = v.dropna().drop_duplicates("date", keep="last").sort_values("date").set_index("date")
    v["vix_chg5"] = v["vix"].pct_change(5)
    v["vix_chg20"] = v["vix"].pct_change(20)
    roll = v["vix"].rolling(252, min_periods=126)
    v["vix_z252"] = (v["vix"] - roll.mean()) / roll.std(ddof=1)
    v["vix_pct252"] = v["vix"].rolling(252, min_periods=126).apply(
        lambda a: float(np.mean(a <= a[-1])), raw=True
    )
    return v


def enrich(baseline: pd.DataFrame, vix: pd.DataFrame) -> pd.DataFrame:
    d = baseline.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date").reset_index(drop=True)
    if d.iloc[0]["date"] != MEASUREMENT_START or d.iloc[-1]["date"] != MEASUREMENT_END:
        raise RuntimeError("baseline measurement window changed")
    spy = d["spy_nav"].astype(float)
    d["spy_ret"] = spy.pct_change()
    d["spy_r40"] = spy.pct_change(40)
    d["spy_dd"] = spy / spy.cummax() - 1.0
    d["spy_rv20"] = d["spy_ret"].rolling(20).std(ddof=1) * math.sqrt(252.0)
    d["spy_rv40"] = d["spy_ret"].rolling(40).std(ddof=1) * math.sqrt(252.0)
    d["spy_vol_ratio"] = d["spy_rv20"] / d["spy_rv40"]
    wc = d["research_wealth_core_equity"].astype(float)
    d["wc_r20"] = wc.pct_change(20)
    d = d.join(vix, on="date")
    if int(d.loc[d["date"] >= pd.Timestamp("2007-01-03"), "vix"].isna().sum()) > 5:
        raise RuntimeError("VIX alignment has too many missing sessions")
    for c in ("vix", "vix_chg5", "vix_chg20", "vix_z252", "vix_pct252"):
        d[c] = d[c].ffill(limit=1)
    return d


class MarketController:
    def __init__(self, family: str, params: dict[str, float]):
        self.family = family
        self.p = params
        self.episode = False
        self.latched = False
        self.healthy_streak = 0
        self.prev_native = 1.0
        self.prev_desired = 1.0
        self.episodes = 0
        self.entries = 0
        self.releases = 0

    def signals(self, r) -> tuple[bool, bool, bool]:
        p = self.p
        f = self.family
        if f == "spy_price":
            stress = finite(r.spy_r20) and finite(r.spy_dd) and (
                r.spy_r20 <= p["r20_stress"] or r.spy_dd <= p["dd_stress"]
            )
            healthy = finite(r.spy_r20) and finite(r.spy_r40) and (
                r.spy_r20 > p["r20_healthy"] and r.spy_r40 > p["r40_healthy"]
            )
            rebound = finite(r.spy_r20) and r.spy_r20 >= p["rebound"]
        elif f == "spy_vol":
            stress = finite(r.spy_rv20) and finite(r.spy_vol_ratio) and (
                r.spy_rv20 >= p["rv20_stress"] and r.spy_vol_ratio >= p["ratio_stress"]
            )
            healthy = finite(r.spy_rv20) and finite(r.spy_vol_ratio) and (
                r.spy_rv20 <= p["rv20_healthy"] and r.spy_vol_ratio <= p["ratio_healthy"]
            )
            rebound = healthy
        elif f == "vix_level_change":
            stress = finite(r.vix) and finite(r.vix_chg5) and (
                r.vix >= p["vix_stress"] and r.vix_chg5 >= p["chg5_stress"]
            )
            healthy = finite(r.vix) and finite(r.vix_chg5) and (
                r.vix <= p["vix_healthy"] and r.vix_chg5 <= p["chg5_healthy"]
            )
            rebound = healthy
        elif f == "vix_percentile":
            stress = finite(r.vix_pct252) and finite(r.vix_z252) and (
                r.vix_pct252 >= p["pct_stress"] and r.vix_z252 >= p["z_stress"]
            )
            healthy = finite(r.vix_pct252) and r.vix_pct252 <= p["pct_healthy"]
            rebound = healthy
        elif f == "spy_vix":
            spy_stress = finite(r.spy_r20) and finite(r.spy_dd) and (
                r.spy_r20 <= p["r20_stress"] or r.spy_dd <= p["dd_stress"]
            )
            vix_stress = finite(r.vix) and finite(r.vix_z252) and (
                r.vix >= p["vix_stress"] or r.vix_z252 >= p["z_stress"]
            )
            stress = spy_stress and vix_stress
            healthy = finite(r.spy_r20) and finite(r.spy_r40) and finite(r.vix) and (
                r.spy_r20 > 0.0 and r.spy_r40 > 0.0 and r.vix <= p["vix_healthy"]
            )
            rebound = finite(r.spy_r20) and finite(r.vix_chg5) and (
                r.spy_r20 >= p["rebound"] or r.vix_chg5 <= p["vix_rebound_chg5"]
            )
        else:
            raise RuntimeError(f"unknown family {f}")
        return bool(stress), bool(healthy), bool(rebound)

    def step(self, r) -> tuple[float, str]:
        native = float(r.native_close_target)
        effective_native = float(r.effective_native)
        stress, healthy, rebound = self.signals(r)
        self.healthy_streak = self.healthy_streak + 1 if healthy else 0
        reasons: list[str] = []
        if self.prev_native >= 1 - 1e-12 and native < 1 - 1e-12:
            if not self.episode:
                self.episodes += 1
            self.episode = True
            reasons.append("RECOVERY_EPISODE_START")
        cleared = self.latched and (self.healthy_streak >= LDRC_REC or rebound)
        if cleared:
            self.latched = False
            self.releases += 1
            reasons.append("MARKET_RISK_CLEAR")
        desired = native
        if self.episode and native >= 1 - 1e-12:
            if self.healthy_streak >= LDRC_REC or rebound:
                self.episode = False
                desired = 1.0
                self.releases += 1
                reasons.append("FULL_RISK_MARKET_RECOVERY")
            else:
                desired = self.prev_desired
                reasons.append("FULL_RISK_HELD")
        avail = finite(r.wc_dd) and finite(effective_native)
        if not self.latched and not cleared and avail:
            entry = (
                native >= 1 - 1e-12
                and effective_native >= 1 - 1e-12
                and float(r.wc_dd) <= LDRC_DD
                and stress
            )
            if entry:
                self.latched = True
                self.entries += 1
                reasons.append("MARKET_RISK_ENTER")
        if self.latched:
            desired = min(desired, LDRC_CEIL)
        desired = min(native, desired)
        self.prev_native = native
        self.prev_desired = desired
        return float(desired), "|".join(reasons) if reasons else "NORMAL"


def simulate(frame: pd.DataFrame, family: str, params: dict[str, float]) -> tuple[pd.DataFrame, dict]:
    ctl = MarketController(family, params)
    pending = 1.0
    effective = 1.0
    nav = 1.0
    prev_close = None
    prev_eff = 1.0
    rows = []
    transition_cost = 0.0
    for i, r in enumerate(frame.itertuples(index=False)):
        effective = pending if i else 1.0
        if prev_close is not None:
            close_eq = float(r.research_wealth_core_equity)
            open_eq = float(r.research_wealth_core_open_equity)
            if abs(effective - prev_eff) < 1e-15:
                wcf = close_eq / prev_close
                fac = prev_eff * wcf + (1 - prev_eff)
            else:
                won = open_eq / prev_close - 1.0
                win = close_eq / open_eq - 1.0
                tc = COST * abs(effective - prev_eff)
                transition_cost += tc
                fac = (1 + prev_eff * won) * (1 - tc) * (1 + effective * win)
            nav *= fac
        desired, reason = ctl.step(r)
        rows.append((r.date, effective, desired, nav, reason))
        pending = desired
        prev_eff = effective
        prev_close = float(r.research_wealth_core_equity)
    out = pd.DataFrame(rows, columns=["date", "allocation", "close_target", "proxy_nav", "reason"])
    return out, {
        "episodes": ctl.episodes,
        "entries": ctl.entries,
        "releases": ctl.releases,
        "transition_cost_fraction_sum": transition_cost,
    }


def metrics(curve: pd.Series, dates: pd.Series) -> dict[str, float]:
    v = curve.astype(float).to_numpy()
    t = pd.to_datetime(dates).reset_index(drop=True)
    years = (t.iloc[-1] - t.iloc[0]).days / 365.2425
    rets = pd.Series(v).pct_change().dropna()
    peak = np.maximum.accumulate(v)
    return {
        "proxy_cagr": float((v[-1] / v[0]) ** (1 / years) - 1),
        "proxy_max_dd": float(np.min(v / peak - 1)),
        "proxy_sharpe": float(rets.mean() / rets.std(ddof=1) * math.sqrt(252)) if rets.std(ddof=1) > 0 else float("nan"),
        "proxy_ending_multiple": float(v[-1] / v[0]),
    }


def grids():
    for r20, dd, rebound in itertools.product(
        (-0.04, -0.06, -0.08, -0.10), (-0.06, -0.10, -0.14, -0.18), (0.08, 0.11, 0.14)
    ):
        yield "spy_price", dict(r20_stress=r20, dd_stress=dd, r20_healthy=0.0, r40_healthy=0.0, rebound=rebound)
    for rv, ratio, healthy in itertools.product((0.18, 0.22, 0.26, 0.30), (1.00, 1.10, 1.20), (0.16, 0.18, 0.20)):
        yield "spy_vol", dict(rv20_stress=rv, ratio_stress=ratio, rv20_healthy=healthy, ratio_healthy=1.0)
    for level, chg, healthy in itertools.product((20.0, 22.5, 25.0, 27.5, 30.0), (0.0, 0.10, 0.20), (18.0, 20.0, 22.0)):
        yield "vix_level_change", dict(vix_stress=level, chg5_stress=chg, vix_healthy=healthy, chg5_healthy=0.0)
    for pct, z, healthy in itertools.product((0.75, 0.85, 0.90), (0.5, 1.0, 1.5), (0.50, 0.60)):
        yield "vix_percentile", dict(pct_stress=pct, z_stress=z, pct_healthy=healthy)
    for r20, dd, vix, z, rebound in itertools.product(
        (-0.05, -0.08), (-0.08, -0.12, -0.16), (20.0, 25.0), (0.5, 1.0), (0.08, 0.11)
    ):
        yield "spy_vix", dict(r20_stress=r20, dd_stress=dd, vix_stress=vix, z_stress=z,
                              vix_healthy=22.0, rebound=rebound, vix_rebound_chg5=-0.10)


def episode_stats(allocation: pd.Series) -> tuple[int, float, int]:
    red = allocation.astype(float).to_numpy() < 1 - 1e-12
    lengths = []
    start = None
    for i, flag in enumerate(red):
        if flag and start is None:
            start = i
        if start is not None and (not flag or i == len(red) - 1):
            end = i if flag and i == len(red)-1 else i-1
            lengths.append(end-start+1)
            start = None
    return len(lengths), float(np.mean(lengths)) if lengths else 0.0, max(lengths) if lengths else 0


def simulate_current_proxy(frame: pd.DataFrame) -> tuple[dict, pd.Series]:
    alloc = frame["research_allocation"].astype(float).reset_index(drop=True)
    nav = 1.0
    vals = [nav]
    for i in range(1, len(frame)):
        r = frame.iloc[i]
        olda = float(alloc.iloc[i-1]); newa = float(alloc.iloc[i])
        prev_close = float(frame.iloc[i-1].research_wealth_core_equity)
        close_eq = float(r.research_wealth_core_equity); open_eq = float(r.research_wealth_core_open_equity)
        if abs(newa-olda) < 1e-15:
            fac = olda*(close_eq/prev_close)+(1-olda)
        else:
            won=open_eq/prev_close-1.; win=close_eq/open_eq-1.; tc=COST*abs(newa-olda)
            fac=(1+olda*won)*(1-tc)*(1+newa*win)
        nav *= fac; vals.append(nav)
    s = pd.Series(vals)
    return metrics(s, frame.date), s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-daily", type=Path, required=True)
    ap.add_argument("--vix-csv", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    baseline = pd.read_csv(args.baseline_daily)
    vix = load_vix(args.vix_csv)
    frame = enrich(baseline, vix)
    baseline_alloc = frame["research_allocation"].astype(float).reset_index(drop=True)
    baseline_proxy, _ = simulate_current_proxy(frame)

    results = []
    for n, (family, params) in enumerate(grids()):
        sim, state = simulate(frame, family, params)
        m = metrics(sim.proxy_nav, sim.date)
        alloc = sim.allocation.astype(float)
        changed = np.flatnonzero(np.abs(alloc.to_numpy() - baseline_alloc.to_numpy()) > 1e-12)
        episodes, avgdur, maxdur = episode_stats(alloc)
        row = {
            "candidate_id": f"{family}-{n:04d}",
            "family": family,
            "params": json.dumps(params, sort_keys=True, separators=(",", ":")),
            **m,
            **state,
            "reduced_sessions": int(np.sum(alloc < 1 - 1e-12)),
            "defensive_episodes": episodes,
            "mean_defensive_duration": avgdur,
            "max_defensive_duration": maxdur,
            "allocation_sessions_changed_vs_current": int(len(changed)),
            "first_allocation_divergence": str(frame.iloc[int(changed[0])].date.date()) if len(changed) else "",
        }
        for year in (2008, 2018, 2020, 2022):
            mask = frame.date.dt.year.eq(year)
            row[f"reduced_sessions_{year}"] = int(np.sum(alloc[mask] < 1 - 1e-12))
        results.append(row)

    out = pd.DataFrame(results)
    out["proxy_cagr_gap_vs_current"] = out.proxy_cagr - baseline_proxy["proxy_cagr"]
    out["proxy_dd_gap_vs_current"] = out.proxy_max_dd - baseline_proxy["proxy_max_dd"]
    out.to_csv(args.output / "coarse-grid.csv", index=False)

    summary_families = []
    for family, g in out.groupby("family"):
        acceptable = g[(g.proxy_cagr_gap_vs_current >= -0.02) & (g.proxy_dd_gap_vs_current <= 0.03)]
        summary_families.append({
            "family": family,
            "grid_points": int(len(g)),
            "screen_acceptable_points": int(len(acceptable)),
            "proxy_cagr_median": float(g.proxy_cagr.median()),
            "proxy_cagr_p10": float(g.proxy_cagr.quantile(.10)),
            "proxy_cagr_p90": float(g.proxy_cagr.quantile(.90)),
            "proxy_max_dd_median": float(g.proxy_max_dd.median()),
            "reduced_sessions_median": float(g.reduced_sessions.median()),
        })
    pd.DataFrame(summary_families).to_csv(args.output / "family-summary.csv", index=False)

    shortlist = []
    for family, g in out.groupby("family"):
        a = g[(g.proxy_cagr_gap_vs_current >= -0.02) & (g.proxy_dd_gap_vs_current <= 0.03)].copy()
        if a.empty:
            a = g.copy()
        a["median_distance"] = (a.proxy_cagr - a.proxy_cagr.median()).abs() + (a.proxy_max_dd - a.proxy_max_dd.median()).abs()
        shortlist.extend(a.sort_values(["median_distance", "allocation_sessions_changed_vs_current"]).head(3).to_dict("records"))
    pd.DataFrame(shortlist).to_csv(args.output / "shortlist.csv", index=False)

    cutoff = vix[(vix.index >= pd.Timestamp("1997-01-01")) & (vix.index <= MEASUREMENT_END)][["vix"]].copy()
    cutoff_path = args.output / "vix-cboe-cutoff-through-2026-07-31.csv"
    cutoff.reset_index().to_csv(cutoff_path, index=False, date_format="%Y-%m-%d")
    manifest = {
        "status": "RESEARCH / NOT CERTIFIED",
        "phase": "COARSE_SIGNAL_SCREEN",
        "baseline_run_id": BASELINE_RUN_ID,
        "baseline_artifact_id": BASELINE_ARTIFACT_ID,
        "baseline_artifact_digest": BASELINE_ARTIFACT_DIGEST,
        "baseline_daily_sha256": sha256(args.baseline_daily),
        "vix_source": "Cboe VIX Index historical daily closing values",
        "vix_source_url": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
        "vix_download_sha256": sha256(args.vix_csv),
        "vix_cutoff_sha256": sha256(cutoff_path),
        "vix_cutoff_end": str(MEASUREMENT_END.date()),
        "decision_timing": "same-session market close observations determine next-session-open LDRC target",
        "screen_proxy_cash_assumption": "zero return on defensive cash; full-replay finalist validation required",
        "current_proxy_metrics": baseline_proxy,
        "current_actual_metrics": {"cagr": 0.2009, "max_drawdown": -0.2383, "sharpe": 1.10},
        "grid_points": int(len(out)),
        "families": sorted(out.family.unique().tolist()),
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    lines = [
        "# Research Champion market-risk controller — coarse screen", "",
        "**RESEARCH / NOT CERTIFIED**", "",
        "This run freezes the corrected Champion Wealth Core and Native Sentinel path and changes only the LDRC market-risk observation layer.",
        "Proxy economics use zero defensive-cash return and are used only for coarse screening. Finalists require exact full replay.", "",
        "## Family summary", "",
        "| Family | Grid | Screen-acceptable | Median proxy CAGR | Median proxy max DD |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in summary_families:
        lines.append(f"| {r['family']} | {r['grid_points']} | {r['screen_acceptable_points']} | {r['proxy_cagr_median']:.2%} | {r['proxy_max_dd_median']:.2%} |")
    lines += ["", "Cboe daily VIX close is treated as a close-of-session observation; any decision based on it is effective at the next session open."]
    (args.output / "REPORT.md").write_text("\n".join(lines) + "\n")
    sums = [p for p in args.output.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt"]
    (args.output / "SHA256SUMS.txt").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in sorted(sums)))
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
