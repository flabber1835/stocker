#!/usr/bin/env python3
"""Zero-budget attribution for Strategy 9 E6 exceptional-leader displacement failure."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

START = pd.Timestamp("2020-01-02")
END = pd.Timestamp("2026-07-31")
HORIZONS = (5, 21, 63, 119)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def metric(frame: pd.DataFrame, column: str) -> dict:
    x = frame[(frame.date >= START) & (frame.date <= END)][["date", column]].dropna().copy()
    v = x[column].astype(float).to_numpy()
    norm = v / v[0]
    rets = norm[1:] / norm[:-1] - 1.0
    years = (x.date.iloc[-1] - x.date.iloc[0]).days / 365.2425
    peak = np.maximum.accumulate(norm)
    std = float(np.std(rets, ddof=1)) if len(rets) > 1 else np.nan
    return {
        "cagr": float(norm[-1] ** (1.0 / years) - 1.0),
        "max_drawdown": float(np.min(norm / peak - 1.0)),
        "sharpe": float(np.mean(rets) / std * np.sqrt(252.0)) if std > 0 else np.nan,
        "ending_multiple": float(norm[-1]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--e6-root", type=Path, required=True)
    ap.add_argument("--accepted-root", type=Path, required=True)
    ap.add_argument("--slot-root", type=Path, required=True)
    ap.add_argument("--sharadar-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    events = pd.read_csv(args.e6_root / "e6_displacement_events.csv", parse_dates=["signal_date"])
    accepted = pd.read_csv(args.accepted_root / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    e6 = pd.read_csv(args.e6_root / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    opp = pd.read_csv(args.slot_root / "broad_slot_opportunities_raw.csv.gz", compression="gzip", parse_dates=["date"])

    accepted = accepted[(accepted.date >= START) & (accepted.date <= END)].copy()
    e6 = e6[(e6.date >= START) & (e6.date <= END)].copy()
    sessions = list(e6.date)
    sidx = {d: i for i, d in enumerate(sessions)}

    tickers = set(events.candidate_ticker.astype(str)) | set(events.victim_ticker.astype(str))
    price_parts = []
    for y in range(2020, 2027):
        p = args.sharadar_root / f"SHARADAR_SEP_{y}.csv.gz"
        d = pd.read_csv(p, usecols=["ticker", "date", "open", "close"], low_memory=False)
        d["ticker"] = d.ticker.astype(str)
        d = d[d.ticker.isin(tickers)].copy()
        if d.empty:
            continue
        d["date"] = pd.to_datetime(d.date)
        d = d[d.date <= END].drop_duplicates(["ticker", "date"], keep="last")
        price_parts.append(d)
    px = pd.concat(price_parts, ignore_index=True).sort_values(["ticker", "date"])
    px_idx = px.set_index(["ticker", "date"])

    diag = opp[opp.blocked_order.eq(1)][["date", "ticker", "weakest_held_ticker"]].copy()
    diag.rename(columns={"date": "signal_date", "ticker": "candidate_ticker", "weakest_held_ticker": "diagnostic_weakest_ticker"}, inplace=True)
    diag = diag.drop_duplicates(["signal_date", "candidate_ticker"], keep="first")

    rows = []
    for r in events.itertuples(index=False):
        signal = pd.Timestamp(r.signal_date)
        i = sidx.get(signal)
        rec = {
            "signal_date": signal,
            "year": signal.year,
            "candidate_ticker": str(r.candidate_ticker),
            "victim_ticker": str(r.victim_ticker),
            "candidate_score": float(r.candidate_score),
            "victim_score": float(r.victim_score),
            "score_gap": float(r.candidate_score) - float(r.victim_score),
            "candidate_recent_r21": float(r.candidate_recent_r21),
        }
        if i is None or i + 1 >= len(sessions):
            rec["execution_status"] = "NO_NEXT_SESSION"
            rows.append(rec)
            continue
        exdate = sessions[i + 1]
        rec["execution_date"] = exdate
        try:
            cop = float(px_idx.loc[(str(r.candidate_ticker), exdate), "open"])
            vop = float(px_idx.loc[(str(r.victim_ticker), exdate), "open"])
        except KeyError:
            rec["execution_status"] = "MISSING_EXECUTION_OPEN"
            rows.append(rec)
            continue
        rec["execution_status"] = "OK"
        rec["candidate_execution_open"] = cop
        rec["victim_execution_open"] = vop
        for h in HORIZONS:
            ti = i + h
            if ti >= len(sessions):
                continue
            td = sessions[ti]
            rec[f"target_date_{h}"] = td
            try:
                cc = float(px_idx.loc[(str(r.candidate_ticker), td), "close"])
                vc = float(px_idx.loc[(str(r.victim_ticker), td), "close"])
            except KeyError:
                continue
            cr = cc / cop - 1.0 if cop > 0 else np.nan
            vr = vc / vop - 1.0 if vop > 0 else np.nan
            rec[f"candidate_r{h}"] = cr
            rec[f"victim_r{h}"] = vr
            rec[f"spread_candidate_minus_victim_r{h}"] = cr - vr
        rows.append(rec)

    ev = pd.DataFrame(rows).merge(diag, on=["signal_date", "candidate_ticker"], how="left")
    ev["victim_matches_diagnostic_weakest"] = ev.victim_ticker.eq(ev.diagnostic_weakest_ticker)
    ev.to_csv(args.output / "e6_failure_event_attribution.csv", index=False)

    annual_rows = []
    for year, g in ev.groupby("year"):
        row = {"year": int(year), "events": int(len(g)), "victim_match_rate": float(g.victim_matches_diagnostic_weakest.mean())}
        for h in HORIZONS:
            c = f"spread_candidate_minus_victim_r{h}"
            z = pd.to_numeric(g.get(c), errors="coerce").dropna()
            row[f"n_r{h}"] = int(len(z))
            row[f"mean_spread_r{h}"] = float(z.mean()) if len(z) else np.nan
            row[f"median_spread_r{h}"] = float(z.median()) if len(z) else np.nan
            row[f"hit_rate_r{h}"] = float((z > 0).mean()) if len(z) else np.nan
        annual_rows.append(row)
    annual = pd.DataFrame(annual_rows)
    annual.to_csv(args.output / "e6_failure_direct_spread_by_year.csv", index=False)

    m = accepted[["date", "research_wealth_core_equity", "A_nav", "A_allocation"]].merge(
        e6[["date", "research_wealth_core_equity", "A_nav", "A_allocation"]], on="date", suffixes=("_accepted", "_e6")
    )
    m["core_relative"] = m.research_wealth_core_equity_e6 / m.research_wealth_core_equity_accepted
    m["e3_relative"] = m.A_nav_e6 / m.A_nav_accepted
    m["core_relative"] /= m.core_relative.iloc[0]
    m["e3_relative"] /= m.e3_relative.iloc[0]
    m["allocation_diff"] = m.A_allocation_e6 - m.A_allocation_accepted
    mask = m.allocation_diff.abs() > 1e-12
    grp = (mask != mask.shift(fill_value=False)).cumsum()
    feedback = []
    for _, b in m[mask].groupby(grp[mask]):
        feedback.append({
            "start": b.date.iloc[0],
            "end": b.date.iloc[-1],
            "sessions": int(len(b)),
            "accepted_allocation_mean": float(b.A_allocation_accepted.mean()),
            "e6_allocation_mean": float(b.A_allocation_e6.mean()),
            "mean_allocation_diff": float(b.allocation_diff.mean()),
            "core_relative_start": float(b.core_relative.iloc[0]),
            "core_relative_end": float(b.core_relative.iloc[-1]),
            "e3_relative_start": float(b.e3_relative.iloc[0]),
            "e3_relative_end": float(b.e3_relative.iloc[-1]),
        })
    feedback_df = pd.DataFrame(feedback)
    feedback_df.to_csv(args.output / "e6_failure_allocation_feedback.csv", index=False)

    am = metric(accepted, "A_nav"); em = metric(e6, "A_nav")
    ac = metric(accepted, "research_wealth_core_equity"); ec = metric(e6, "research_wealth_core_equity")
    direct_core_relative = float(m.core_relative.iloc[-1])
    final_e3_relative = float(m.e3_relative.iloc[-1])
    overlay_multiplier = final_e3_relative / direct_core_relative if direct_core_relative > 0 else np.nan
    summary = {
        "status": "PASS",
        "zero_budget_diagnostic": True,
        "events": int(len(ev)),
        "events_matching_original_diagnostic_weakest": int(ev.victim_matches_diagnostic_weakest.sum()),
        "victim_match_rate": float(ev.victim_matches_diagnostic_weakest.mean()),
        "accepted_core": ac,
        "e6_core": ec,
        "accepted_e3": am,
        "e6_e3": em,
        "final_core_relative_e6_vs_accepted": direct_core_relative,
        "final_e3_relative_e6_vs_accepted": final_e3_relative,
        "additional_overlay_relative_multiplier": float(overlay_multiplier),
        "allocation_divergence_sessions": int(mask.sum()),
        "allocation_divergence_episodes": int(len(feedback_df)),
        "interpretation": {
            "diagnostic_counterfactual": "original accepted-E3 path only",
            "e6_intervention": "endogenous path-changing repeated displacement",
            "forward_return_domain": "Sharadar split-adjusted next-open to future close",
        },
    }
    (args.output / "e6_failure_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    files = [
        args.output / "e6_failure_event_attribution.csv",
        args.output / "e6_failure_direct_spread_by_year.csv",
        args.output / "e6_failure_allocation_feedback.csv",
        args.output / "e6_failure_summary.json",
    ]
    (args.output / "E6_FAILURE_SHA256SUMS.txt").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files))

    print("[SUMMARY]")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("[DIRECT SPREAD BY YEAR]")
    print(annual.to_string(index=False))
    print("[ALLOCATION FEEDBACK]")
    print(feedback_df.to_string(index=False) if len(feedback_df) else "none")
    print("[WORST 119D EVENTS]")
    c = "spread_candidate_minus_victim_r119"
    if c in ev:
        print(ev.sort_values(c).head(12)[["signal_date", "candidate_ticker", "victim_ticker", "diagnostic_weakest_ticker", "victim_matches_diagnostic_weakest", c]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
