#!/usr/bin/env python3
"""Forensic decomposition of S&P-gated LD-RC versus frozen broad-universe reference.

This is diagnostic, not a certification harness.  It compares:
- S&P-gated Wealth Core (pre-LD-RC) and control LD-RC path,
- frozen broad-universe Wealth Core and control LD-RC path,
- SPY,
using the same retained LD-RC strategy source and the same end date.

It also measures controller-input drift (recent leadership, native target and
allocation) and S&P identity-exclusion geometry.  No strategy parameters are
changed and no candidate A/B performance is consumed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

WINDOWS = {
    "5": "2021-07-30",
    "10": "2016-07-29",
    "15": "2011-07-29",
    "20": "2006-07-31",
}
END = pd.Timestamp("2026-07-31")
MAX_START = pd.Timestamp("1998-07-06")


def metric(frame: pd.DataFrame, column: str, start: pd.Timestamp) -> dict:
    x = frame[(frame["date"] >= start) & (frame["date"] <= END)][["date", column]].dropna().copy()
    if len(x) < 2:
        raise RuntimeError(f"{column}: insufficient rows from {start.date()}")
    v = x[column].astype(float).to_numpy()
    if not np.all(np.isfinite(v)) or np.min(v) <= 0:
        raise RuntimeError(f"{column}: invalid metric values")
    n = v / v[0]
    r = n[1:] / n[:-1] - 1.0
    years = (x.iloc[-1]["date"] - x.iloc[0]["date"]).days / 365.2425
    peak = np.maximum.accumulate(n)
    sd = float(np.std(r, ddof=1)) if len(r) > 1 else float("nan")
    return {
        "start": str(x.iloc[0]["date"].date()),
        "end": str(x.iloc[-1]["date"].date()),
        "sessions": int(len(x)),
        "elapsed_years": years,
        "cagr": float(n[-1] ** (1.0 / years) - 1.0),
        "ending_multiple": float(n[-1]),
        "max_drawdown": float(np.min(n / peak - 1.0)),
        "sharpe": float(np.mean(r) / sd * math.sqrt(252.0)) if sd > 0 else float("nan"),
    }


def yearly(frame: pd.DataFrame, column: str, start_year: int = 2006) -> dict:
    x = frame[frame["date"].dt.year >= start_year][["date", column]].dropna().copy()
    out = {}
    for year, g in x.groupby(x["date"].dt.year):
        v = g[column].astype(float).to_numpy()
        if len(v) < 2 or v[0] <= 0 or v[-1] <= 0:
            continue
        out[str(int(year))] = float(v[-1] / v[0] - 1.0)
    return out


def alloc_stats(frame: pd.DataFrame, column: str) -> dict:
    x = frame[(frame["date"] >= pd.Timestamp("2006-07-31")) & (frame["date"] <= END)][column].astype(float)
    vals, counts = np.unique(np.round(x.to_numpy(), 10), return_counts=True)
    return {
        "mean": float(x.mean()),
        "median": float(x.median()),
        "fraction_below_1": float((x < 1 - 1e-12).mean()),
        "fraction_at_or_below_0_65": float((x <= 0.65 + 1e-12).mean()),
        "fraction_at_zero": float((x <= 1e-12).mean()),
        "levels": {f"{float(v):.4f}": int(c) for v, c in zip(vals, counts)},
    }


def corr(a: pd.Series, b: pd.Series) -> float | None:
    m = a.notna() & b.notna()
    if int(m.sum()) < 3:
        return None
    x = a[m].astype(float).to_numpy()
    y = b[m].astype(float).to_numpy()
    if np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sp500-result-root", type=Path, required=True)
    ap.add_argument("--sp500-universe-root", type=Path, required=True)
    ap.add_argument("--broad-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    sp = pd.read_csv(args.sp500_result_root / "daily.csv.gz", parse_dates=["date"])
    broad = pd.read_csv(args.broad_root / "daily.csv.gz", parse_dates=["date"])
    excl = pd.read_csv(args.sp500_universe_root / "sp500-best-effort-excluded-sessions.csv.gz", parse_dates=["date"])
    elig = pd.read_csv(args.sp500_universe_root / "sp500-best-effort-eligibility.csv.gz", parse_dates=["date"])

    need_broad = {
        "date", "research_wealth_core_equity", "research_nav", "research_allocation",
        "spy_nav", "recent_r20", "recent_r40", "native_close_target", "spy_r20"
    }
    missing = need_broad.difference(broad.columns)
    if missing:
        raise RuntimeError(f"broad daily missing {sorted(missing)}")

    need_sp = {
        "date", "shadow_equity", "control_nav", "control_allocation",
        "spy_nav", "recent_r20", "recent_r40", "native_close_target",
        "spy_r20", "control_reason", "wc_dd"
    }
    missing = need_sp.difference(sp.columns)
    if missing:
        raise RuntimeError(f"S&P daily missing {sorted(missing)}")

    windows = {}
    for label, start_text in {**WINDOWS, "Max": str(MAX_START.date())}.items():
        start = pd.Timestamp(start_text)
        blocks = {
            "sp500_core": metric(sp, "shadow_equity", start),
            "sp500_ldrc": metric(sp, "control_nav", start),
            "broad_core": metric(broad, "research_wealth_core_equity", start),
            "broad_ldrc": metric(broad, "research_nav", start),
            "spy": metric(sp, "spy_nav", start),
        }
        blocks["sp500_ldrc_effect_cagr_pp"] = 100.0 * (blocks["sp500_ldrc"]["cagr"] - blocks["sp500_core"]["cagr"])
        blocks["broad_ldrc_effect_cagr_pp"] = 100.0 * (blocks["broad_ldrc"]["cagr"] - blocks["broad_core"]["cagr"])
        blocks["core_universe_effect_cagr_pp"] = 100.0 * (blocks["broad_core"]["cagr"] - blocks["sp500_core"]["cagr"])
        blocks["control_universe_effect_cagr_pp"] = 100.0 * (blocks["broad_ldrc"]["cagr"] - blocks["sp500_ldrc"]["cagr"])
        windows[label] = blocks

    m = sp.merge(
        broad[[
            "date", "recent_r20", "recent_r40", "native_close_target",
            "research_allocation", "research_nav", "research_wealth_core_equity"
        ]],
        on="date",
        how="inner",
        suffixes=("_sp500", "_broad"),
    )
    m = m[(m["date"] >= pd.Timestamp("2006-07-31")) & (m["date"] <= END)].copy()
    if m.empty:
        raise RuntimeError("no aligned forensic sessions")

    leadership = {
        "sessions": int(len(m)),
        "recent_r20_correlation": corr(m["recent_r20_sp500"], m["recent_r20_broad"]),
        "recent_r40_correlation": corr(m["recent_r40_sp500"], m["recent_r40_broad"]),
        "native_target_correlation": corr(m["native_close_target_sp500"], m["native_close_target_broad"]),
        "recent_r20_sign_disagreement_fraction": float(
            ((m["recent_r20_sp500"] > 0) != (m["recent_r20_broad"] > 0)).mean()
        ),
        "recent_r40_sign_disagreement_fraction": float(
            ((m["recent_r40_sp500"] > 0) != (m["recent_r40_broad"] > 0)).mean()
        ),
        "recent_r20_le_minus_8pct_sp500_days": int((m["recent_r20_sp500"] <= -0.08).sum()),
        "recent_r20_le_minus_8pct_broad_days": int((m["recent_r20_broad"] <= -0.08).sum()),
        "native_target_disagreement_days": int(
            (np.abs(m["native_close_target_sp500"] - m["native_close_target_broad"]) > 1e-12).sum()
        ),
        "mean_abs_recent_r20_difference": float(
            (m["recent_r20_sp500"] - m["recent_r20_broad"]).abs().dropna().mean()
        ),
        "mean_abs_recent_r40_difference": float(
            (m["recent_r40_sp500"] - m["recent_r40_broad"]).abs().dropna().mean()
        ),
    }

    elig["year"] = elig["date"].dt.year
    excl["year"] = excl["date"].dt.year
    ed = elig.groupby("date").size().rename("eligible")
    xd = excl.groupby("date").size().rename("excluded")
    day = pd.concat([ed, xd], axis=1).fillna(0.0)
    day["source"] = day["eligible"] + day["excluded"]
    day["year"] = day.index.year
    yearly_exclusions = {}
    for year, g in day[day["year"] >= 2006].groupby("year"):
        yearly_exclusions[str(int(year))] = {
            "eligible_mean": float(g["eligible"].mean()),
            "eligible_min": int(g["eligible"].min()),
            "eligible_max": int(g["eligible"].max()),
            "source_membership_mean": float(g["source"].mean()),
            "excluded_sessions": int(g["excluded"].sum()),
            "source_membership_sessions": int(g["source"].sum()),
            "exclusion_fraction": float(g["excluded"].sum() / g["source"].sum()),
        }

    top_excluded = [
        {"source_ticker": str(t), "reason": str(r), "sessions": int(n)}
        for (t, r), n in (
            excl[excl["year"] >= 2006]
            .groupby(["source_ticker", "reason"])
            .size()
            .sort_values(ascending=False)
            .head(30)
            .items()
        )
    ]

    reasons = Counter(sp[(sp["date"] >= pd.Timestamp("2006-07-31"))]["control_reason"].fillna("NA").astype(str))
    controller = {
        "sp500_allocation": alloc_stats(sp, "control_allocation"),
        "broad_allocation": alloc_stats(broad, "research_allocation"),
        "sp500_control_reason_counts": dict(reasons),
    }

    result = {
        "schema": "backtester.sp500-vs-broad-forensics/1",
        "status": "PASS",
        "scope": "diagnostic_universe_and_controller_decomposition",
        "formal_pit_certified": False,
        "broad_reference_caveat": (
            "Broad reference uses the frozen corrected full-PIT wrapper for SEC sector/issuer and PIT actions, "
            "but retains current Sharadar TICKERS category identity for broad-universe common-stock discovery. "
            "Use it to measure the mechanical opportunity-set effect, not as a new certified performance claim."
        ),
        "windows": windows,
        "leadership_input_drift": leadership,
        "controller": controller,
        "yearly_returns_2006_onward": {
            "sp500_core": yearly(sp, "shadow_equity"),
            "sp500_ldrc": yearly(sp, "control_nav"),
            "broad_core": yearly(broad, "research_wealth_core_equity"),
            "broad_ldrc": yearly(broad, "research_nav"),
            "spy": yearly(sp, "spy_nav"),
        },
        "sp500_identity_exclusions_by_year": yearly_exclusions,
        "top_sp500_excluded_names_2006_onward": top_excluded,
    }

    (args.output / "forensics.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# S&P 500 vs broad-universe LD-RC forensics",
        "",
        "Diagnostic only; formal PIT certification is not claimed for the broad reference.",
        "",
        "| Window | S&P core | S&P LD-RC | Broad core | Broad LD-RC | SPY | Broad-core minus S&P-core |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label in ["5", "10", "15", "20", "Max"]:
        b = windows[label]
        lines.append(
            f"| {label} | {b['sp500_core']['cagr']:.2%} | {b['sp500_ldrc']['cagr']:.2%} | "
            f"{b['broad_core']['cagr']:.2%} | {b['broad_ldrc']['cagr']:.2%} | {b['spy']['cagr']:.2%} | "
            f"{b['core_universe_effect_cagr_pp']:+.2f} pp |"
        )
    lines += [
        "",
        "## Controller-input drift",
        f"- recent-R20 correlation: {leadership['recent_r20_correlation']}",
        f"- recent-R40 correlation: {leadership['recent_r40_correlation']}",
        f"- recent-R20 sign disagreement: {leadership['recent_r20_sign_disagreement_fraction']:.2%}",
        f"- native-target disagreement days: {leadership['native_target_disagreement_days']}",
        "",
        "## S&P data coverage",
        f"- 2006 exclusion fraction: {yearly_exclusions['2006']['exclusion_fraction']:.2%}",
        f"- 2015 exclusion fraction: {yearly_exclusions['2015']['exclusion_fraction']:.2%}",
        f"- 2020 exclusion fraction: {yearly_exclusions['2020']['exclusion_fraction']:.2%}",
        f"- 2025 exclusion fraction: {yearly_exclusions['2025']['exclusion_fraction']:.2%}",
        "",
    ]
    (args.output / "FORENSICS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
