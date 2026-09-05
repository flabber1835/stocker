#!/usr/bin/env python3
"""Zero-budget Wealth Core overflow-capacity diagnostic.

Consumes immutable accepted broad-E3 attribution and blocked-leader artifacts.
No strategy replay or mechanics are changed.

Exact close cash derivation:
  equity = cash + one-session dividend receivables + held market value
The attribution marks store cumulative dividends per trade. Because prior
receivables settle at the next session open, the positive same-trade dividend
increment on a session is exactly the close receivable created that session.
Thus close cash is equity minus held market value minus current receivable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

LABEL = "WC_OVERFLOW_CAPACITY_ZERO_BUDGET_DIAGNOSTIC"
ENTRY_W = 0.04
START = pd.Timestamp("2020-01-02")
END = pd.Timestamp("2026-07-31")
N_SLOTS = 25

ATTR_RUN_ID = 33943672769
ATTR_HEAD = "ab5a9b9ba8c09bb99ad95fda554b332749756bad"
ATTR_DIGEST = "sha256:22f1cc9bd78eb325c89204a89c7e43358db41805e9907077111fad3ed78b1467"
SLOT_RUN_ID = 33947807175
SLOT_HEAD = "1057d244b03e1b997edfb9d38ed655396f6764cc"
SLOT_DIGEST = "sha256:42cd4b224b9b70ce578e48f02e5b44ea3ef9d0fafc8bbad20e436fcbfc837338"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_cash_path(attr_root: Path) -> pd.DataFrame:
    daily = pd.read_csv(attr_root / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    marks = pd.read_csv(attr_root / "broad_r3000_daily_position_marks.csv.gz", compression="gzip", parse_dates=["date"])
    marks = marks.sort_values(["trade_id", "date"], kind="mergesort").copy()

    # Attribution dividends are cumulative per trade. Positive daily increments are
    # exactly that session's newly-created one-session receivable.
    marks["new_dividend_receivable"] = (
        marks.groupby("trade_id", sort=False)["dividends"].diff()
        .fillna(marks["dividends"])
        .clip(lower=0.0)
    )
    agg = marks.groupby("date", as_index=False).agg(
        held_market_value=("market_value", "sum"),
        new_dividend_receivable=("new_dividend_receivable", "sum"),
        marked_holdings=("ticker", "size"),
    )
    out = daily.merge(agg, on="date", how="left")
    out[["held_market_value", "new_dividend_receivable", "marked_holdings"]] = out[[
        "held_market_value", "new_dividend_receivable", "marked_holdings"
    ]].fillna(0.0)
    out["close_cash"] = (
        out["research_wealth_core_equity"]
        - out["held_market_value"]
        - out["new_dividend_receivable"]
    )
    out["cash_fraction"] = out["close_cash"] / out["research_wealth_core_equity"]
    out["normal_entry_target"] = ENTRY_W * out["research_wealth_core_equity"]
    out["normal_entry_funding_fraction"] = out["close_cash"] / out["normal_entry_target"]
    # Allow only tiny floating-point residue below zero.
    tol = np.maximum(out["research_wealth_core_equity"].abs() * 1e-10, 1.0)
    if ((out["close_cash"] < -tol)).any():
        bad = out[out["close_cash"] < -tol].head(5)
        raise RuntimeError(f"negative reconstructed cash beyond tolerance: {bad.to_dict('records')}")
    out.loc[out["close_cash"].abs() <= tol, "close_cash"] = 0.0
    return out


def attach_natural_unwind(episodes: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.sort_values("date").reset_index(drop=True)
    index = {pd.Timestamp(x): i for i, x in enumerate(d.date)}
    held = d.held_count.astype(int).to_numpy()
    dates = pd.to_datetime(d.date).to_numpy()
    next_below = np.full(len(d), -1, dtype=int)
    nxt = -1
    for i in range(len(d) - 1, -1, -1):
        next_below[i] = nxt
        if held[i] < N_SLOTS:
            nxt = i
    sessions = []
    unwind_dates = []
    for row in episodes.itertuples(index=False):
        i = index[pd.Timestamp(row.date)]
        j = int(next_below[i])
        sessions.append(np.nan if j < 0 else j - i)
        unwind_dates.append("" if j < 0 else str(pd.Timestamp(dates[j]).date()))
    out = episodes.copy()
    out["sessions_to_next_natural_below25"] = sessions
    out["next_natural_below25_date"] = unwind_dates
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--attribution-root", type=Path, required=True)
    ap.add_argument("--slot-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    cash = load_cash_path(args.attribution_root)
    cash = cash[(cash.date >= START) & (cash.date <= END)].copy()
    episodes = pd.read_csv(args.slot_root / "broad_slot_opportunity_episodes.csv", parse_dates=["date"])
    if len(episodes) != 107:
        raise RuntimeError(f"expected 107 blocked-leader episodes, got {len(episodes)}")

    cols = [
        "date", "research_wealth_core_equity", "held_count", "held_market_value",
        "new_dividend_receivable", "close_cash", "cash_fraction",
        "normal_entry_target", "normal_entry_funding_fraction",
    ]
    ep = episodes.merge(cash[cols], on="date", how="left", validate="many_to_one")
    if ep["close_cash"].isna().any():
        raise RuntimeError("cash path missing blocked-leader dates")
    ep["can_fund_full_4pct_without_sale_or_leverage"] = ep["close_cash"] >= ep["normal_entry_target"]
    ep = attach_natural_unwind(ep, cash)
    ep.to_csv(args.output / "overflow_capacity_blocked_episodes.csv", index=False)

    full = cash[cash.held_count.astype(int).eq(N_SLOTS)].copy()
    full["can_fund_full_4pct_without_sale_or_leverage"] = full.close_cash >= full.normal_entry_target
    full.to_csv(args.output / "overflow_capacity_full_slot_sessions.csv.gz", index=False,
                compression={"method": "gzip", "compresslevel": 6, "mtime": 0})

    unwind = ep["sessions_to_next_natural_below25"].dropna().astype(float)
    summary = {
        "status": "PASS",
        "zero_budget_diagnostic": True,
        "strategy_mechanics_changed": False,
        "label": LABEL,
        "window": [str(START.date()), str(END.date())],
        "source_attribution": {"run_id": ATTR_RUN_ID, "head": ATTR_HEAD, "digest": ATTR_DIGEST},
        "source_slot_diagnostic": {"run_id": SLOT_RUN_ID, "head": SLOT_HEAD, "digest": SLOT_DIGEST},
        "full_slot_sessions": int(len(full)),
        "full_slot_sessions_funding_full_4pct": int(full.can_fund_full_4pct_without_sale_or_leverage.sum()),
        "blocked_leader_episodes": int(len(ep)),
        "blocked_episodes_funding_full_4pct": int(ep.can_fund_full_4pct_without_sale_or_leverage.sum()),
        "blocked_episode_cash_fraction": {
            "mean": float(ep.cash_fraction.mean()),
            "median": float(ep.cash_fraction.median()),
            "max": float(ep.cash_fraction.max()),
            "p90": float(ep.cash_fraction.quantile(.90)),
        },
        "blocked_episode_funding_fraction_of_normal_4pct_entry": {
            "mean": float(ep.normal_entry_funding_fraction.mean()),
            "median": float(ep.normal_entry_funding_fraction.median()),
            "max": float(ep.normal_entry_funding_fraction.max()),
        },
        "blocked_episodes_with_cash_at_least_1pct_equity": int((ep.cash_fraction >= .01).sum()),
        "blocked_episodes_with_cash_at_least_0_5pct_equity": int((ep.cash_fraction >= .005).sum()),
        "blocked_episodes_with_cash_at_least_0_1pct_equity": int((ep.cash_fraction >= .001).sum()),
        "hypothetical_sessions_until_natural_exit_restores_25": {
            "mean": float(unwind.mean()),
            "median": float(unwind.median()),
            "p90": float(unwind.quantile(.90)),
            "max": float(unwind.max()),
            "within_5_sessions": int((unwind <= 5).sum()),
            "within_21_sessions": int((unwind <= 21).sum()),
            "over_21_sessions": int((unwind > 21).sum()),
        },
        "cash_derivation": "close equity - held market value - same-session newly accrued one-session dividend receivable",
        "decision": "NO_GO_FOR_CASH_FUNDED_26TH_FULL_POSITION" if int(ep.can_fund_full_4pct_without_sale_or_leverage.sum()) == 0 else "REVIEW",
    }
    (args.output / "overflow_capacity_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    files = [
        args.output / "overflow_capacity_blocked_episodes.csv",
        args.output / "overflow_capacity_full_slot_sessions.csv.gz",
        args.output / "overflow_capacity_summary.json",
    ]
    (args.output / "OVERFLOW_CAPACITY_SHA256SUMS.txt").write_text(
        "".join(f"{sha256(p)}  {p.name}\n" for p in files)
    )

    print("[SUMMARY]")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("[TOP CASH BLOCKED EPISODES]")
    print(ep.nlargest(20, "cash_fraction")[[
        "date", "ticker", "durable_rank", "cash_fraction", "close_cash",
        "normal_entry_target", "normal_entry_funding_fraction",
        "sessions_to_next_natural_below25",
    ]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
