#!/usr/bin/env python3
"""Zero-budget accepted-E3 Wealth Core market-beta drawdown decomposition.

Read-only diagnostic. No strategy mechanics are changed and no future return is
used to estimate beta. Wealth Core beta to SPY is estimated from strictly prior
rolling daily returns, then each day's raw Wealth Core P&L is decomposed exactly:

    market_beta_pnl = prior_equity * prior_beta * spy_return
    residual_pnl    = actual_wc_pnl - market_beta_pnl

The components therefore sum exactly to realized Wealth Core P&L. Results are
reported for 63/126/252-session prior-only beta windows; 126 is the primary view.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

LABEL = "WC_MARKET_BETA_DRAWDOWN_DECOMPOSITION_ZERO_BUDGET"
E3_HEAD = "3f27834db427e71d9bb8d0b6160c8835b739c906"
E3_RUN_ID = 33912976460
E3_ARTIFACT_ID = 9953264982
E3_DIGEST = "sha256:22011d018a336c6da4d92b31e8786811a4f4288daa91d56a80c30c9f144f174f"
WINDOWS = (63, 126, 252)
PRIMARY = 126
MEASUREMENT_START = pd.Timestamp("2006-07-31")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def prior_rolling_beta(wc_ret: pd.Series, spy_ret: pd.Series, window: int) -> pd.Series:
    # rolling() at t contains return_t, so shift(1) makes the estimate strictly prior.
    cov = wc_ret.rolling(window, min_periods=window).cov(spy_ret)
    var = spy_ret.rolling(window, min_periods=window).var(ddof=1)
    beta = cov / var
    beta = beta.replace([np.inf, -np.inf], np.nan)
    return beta.shift(1)


def drawdown_episodes(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame.reset_index(drop=True)
    eq = x.wc_equity.to_numpy(float)
    dates = pd.to_datetime(x.date).to_numpy()
    rows = []
    peak_i = 0
    in_dd = False
    trough_i = 0
    for i in range(1, len(x)):
        if eq[i] >= eq[peak_i]:
            if in_dd:
                rows.append((peak_i, trough_i, i))
                in_dd = False
            peak_i = i
            trough_i = i
        else:
            if not in_dd:
                in_dd = True
                trough_i = i
            elif eq[i] < eq[trough_i]:
                trough_i = i
    if in_dd:
        rows.append((peak_i, trough_i, None))

    out = []
    for p, t, r in rows:
        if pd.Timestamp(dates[t]) < MEASUREMENT_START:
            continue
        depth = eq[t] / eq[p] - 1.0
        out.append({
            "peak_index": int(p),
            "trough_index": int(t),
            "recovery_index": None if r is None else int(r),
            "peak_date": str(pd.Timestamp(dates[p]).date()),
            "trough_date": str(pd.Timestamp(dates[t]).date()),
            "recovery_date": "" if r is None else str(pd.Timestamp(dates[r]).date()),
            "sessions_peak_to_trough": int(t - p),
            "drawdown": float(depth),
        })
    return pd.DataFrame(out).sort_values(["drawdown", "peak_date"], kind="mergesort").reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--accepted-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    daily = pd.read_csv(args.accepted_root / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    required = {"date", "research_wealth_core_equity", "spy_nav"}
    missing = required.difference(daily.columns)
    if missing:
        raise RuntimeError(f"accepted E3 daily missing columns: {sorted(missing)}")

    x = daily[["date", "research_wealth_core_equity", "spy_nav"]].copy()
    x.rename(columns={"research_wealth_core_equity": "wc_equity"}, inplace=True)
    x = x.sort_values("date", kind="mergesort").reset_index(drop=True)
    x["wc_ret"] = x.wc_equity.pct_change()
    x["spy_ret"] = x.spy_nav.pct_change()
    x["wc_pnl"] = x.wc_equity.diff()
    x["prior_equity"] = x.wc_equity.shift(1)

    for w in WINDOWS:
        b = prior_rolling_beta(x.wc_ret, x.spy_ret, w)
        x[f"beta_{w}"] = b
        x[f"market_pnl_{w}"] = x.prior_equity * b * x.spy_ret
        x[f"residual_pnl_{w}"] = x.wc_pnl - x[f"market_pnl_{w}"]

    episodes = drawdown_episodes(x)
    if episodes.empty:
        raise RuntimeError("no measurement-period drawdown episodes found")

    attrs = []
    for rank, e in enumerate(episodes.head(15).itertuples(index=False), start=1):
        p = int(e.peak_index); t = int(e.trough_index)
        block = x.iloc[p + 1:t + 1].copy()
        total_pnl = float(x.iloc[t].wc_equity - x.iloc[p].wc_equity)
        row = {
            "rank": rank,
            "peak_date": e.peak_date,
            "trough_date": e.trough_date,
            "recovery_date": e.recovery_date,
            "sessions_peak_to_trough": int(e.sessions_peak_to_trough),
            "drawdown": float(e.drawdown),
            "total_wc_pnl": total_pnl,
            "peak_equity": float(x.iloc[p].wc_equity),
            "trough_equity": float(x.iloc[t].wc_equity),
        }
        for w in WINDOWS:
            valid = block[[f"market_pnl_{w}", f"residual_pnl_{w}"]].dropna()
            market = float(valid[f"market_pnl_{w}"].sum()) if len(valid) else float("nan")
            residual = float(valid[f"residual_pnl_{w}"].sum()) if len(valid) else float("nan")
            covered_actual = float(block.loc[valid.index, "wc_pnl"].sum()) if len(valid) else float("nan")
            row[f"covered_sessions_beta_{w}"] = int(len(valid))
            row[f"market_beta_pnl_{w}"] = market
            row[f"residual_pnl_{w}"] = residual
            row[f"covered_actual_pnl_{w}"] = covered_actual
            row[f"market_share_of_covered_loss_{w}"] = (
                float(market / covered_actual)
                if np.isfinite(market) and np.isfinite(covered_actual) and covered_actual < 0
                else float("nan")
            )
            row[f"mean_prior_beta_{w}"] = float(block[f"beta_{w}"].mean())
        attrs.append(row)
    attr = pd.DataFrame(attrs)
    attr.to_csv(args.output / "wc_drawdown_beta_attribution.csv", index=False)

    # Daily tape allows independent review and later hedge design without replay.
    keep = ["date", "wc_equity", "wc_ret", "spy_ret", "wc_pnl", "prior_equity"]
    for w in WINDOWS:
        keep += [f"beta_{w}", f"market_pnl_{w}", f"residual_pnl_{w}"]
    x.loc[x.date >= MEASUREMENT_START, keep].to_csv(
        args.output / "wc_daily_beta_decomposition.csv.gz",
        index=False,
        compression={"method": "gzip", "compresslevel": 6, "mtime": 0},
    )

    # Regime-independent summary over negative Wealth Core days and top drawdowns.
    m = x.date >= MEASUREMENT_START
    neg = x[m & (x.wc_pnl < 0)].copy()
    top = attr.head(10)
    primary_shares = top[f"market_share_of_covered_loss_{PRIMARY}"].replace([np.inf, -np.inf], np.nan).dropna()
    summary = {
        "status": "PASS",
        "zero_budget_diagnostic": True,
        "strategy_mechanics_changed": False,
        "label": LABEL,
        "accepted_e3": {
            "head": E3_HEAD,
            "run_id": E3_RUN_ID,
            "artifact_id": E3_ARTIFACT_ID,
            "digest": E3_DIGEST,
        },
        "measurement_start": str(MEASUREMENT_START.date()),
        "beta_method": "strictly-prior rolling covariance(WC,SPY)/variance(SPY)",
        "beta_windows_sessions": list(WINDOWS),
        "primary_beta_window_sessions": PRIMARY,
        "major_drawdowns_reported": int(len(attr)),
        "top10_primary_market_share_of_covered_loss": {
            "mean": float(primary_shares.mean()) if len(primary_shares) else None,
            "median": float(primary_shares.median()) if len(primary_shares) else None,
            "min": float(primary_shares.min()) if len(primary_shares) else None,
            "max": float(primary_shares.max()) if len(primary_shares) else None,
        },
        "negative_wc_days_primary": {
            "sessions": int(len(neg)),
            "actual_pnl": float(neg.wc_pnl.sum()),
            "market_beta_pnl": float(neg[f"market_pnl_{PRIMARY}"].sum(skipna=True)),
            "residual_pnl": float(neg[f"residual_pnl_{PRIMARY}"].sum(skipna=True)),
            "mean_prior_beta": float(neg[f"beta_{PRIMARY}"].mean()),
        },
        "interpretation_contract": {
            "market_component": "mechanical prior-beta exposure to same-day SPY return",
            "residual_component": "all remaining Wealth Core P&L; not assumed to be pure alpha",
            "future_information_used_for_beta": False,
            "hedge_strategy_tested": False,
        },
    }
    (args.output / "wc_beta_drawdown_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    files = [
        args.output / "wc_drawdown_beta_attribution.csv",
        args.output / "wc_daily_beta_decomposition.csv.gz",
        args.output / "wc_beta_drawdown_summary.json",
    ]
    (args.output / "WC_BETA_DRAWDOWN_SHA256SUMS.txt").write_text(
        "".join(f"{sha256(p)}  {p.name}\n" for p in files)
    )

    print("[SUMMARY]")
    print(json.dumps(summary, indent=2, sort_keys=True))
    show = [
        "rank", "peak_date", "trough_date", "drawdown", "sessions_peak_to_trough",
        f"mean_prior_beta_{PRIMARY}", f"market_beta_pnl_{PRIMARY}",
        f"residual_pnl_{PRIMARY}", f"market_share_of_covered_loss_{PRIMARY}",
    ]
    print("[TOP DRAWDOWNS]")
    print(attr[show].head(15).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
