#!/usr/bin/env python3
"""Attribute broad-universe Wealth Core realized contribution.

Diagnostic research only. Consumes the observational prior-close position trace
emitted by the frozen replay and classifies contribution by liquidity, S&P 500
membership, and contributor concentration. Market-cap attribution is reported
only when a point-in-time market-cap field is actually present in the trace.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def _read_first(root: Path, names: list[str]) -> tuple[pd.DataFrame, str]:
    for name in names:
        p = root / name
        if p.exists():
            return pd.read_csv(p), name
    raise RuntimeError(f"none of required files found under {root}: {names}")


def _pick(df: pd.DataFrame, candidates: list[str], required: bool = True) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    if required:
        raise RuntimeError(f"missing required column; tried {candidates}; have={list(df.columns)}")
    return None


def _bucket_quantile(s: pd.Series, labels: list[str]) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    out = pd.Series(index=s.index, dtype="object")
    valid = x.notna()
    if valid.sum() < len(labels):
        out.loc[valid] = "available"
        out.loc[~valid] = "unknown"
        return out
    ranks = x[valid].rank(method="first", pct=True)
    vals = pd.cut(ranks, bins=np.linspace(0, 1, len(labels) + 1), labels=labels, include_lowest=True)
    out.loc[valid] = vals.astype(str)
    out.loc[~valid] = "unknown"
    return out


def _summarize(df: pd.DataFrame, bucket: str) -> list[dict]:
    rows = []
    for key, g in df.groupby(bucket, dropna=False):
        contrib = pd.to_numeric(g["weighted_return_contribution"], errors="coerce")
        rows.append({
            "bucket": str(key),
            "rows": int(len(g)),
            "unique_tickers": int(g["ticker"].nunique()),
            "mean_weight": float(pd.to_numeric(g["weight"], errors="coerce").mean()),
            "mean_security_return": float(pd.to_numeric(g["security_return"], errors="coerce").mean()),
            "sum_weighted_return_contribution": float(contrib.sum()),
            "positive_contribution_fraction": float((contrib > 0).mean()),
        })
    rows.sort(key=lambda r: r["sum_weighted_return_contribution"], reverse=True)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broad-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--sp500-eligibility", type=Path)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    holdings, holdings_name = _read_first(args.broad_root, ["position_trace.csv.gz"])
    holdings.columns = [str(c).strip() for c in holdings.columns]
    required = {"date", "holding_date", "ticker", "weight", "security_return"}
    missing = required.difference(holdings.columns)
    if missing:
        raise RuntimeError(f"position trace missing required columns: {sorted(missing)}")

    h = holdings.copy()
    h["date"] = pd.to_datetime(h["date"])
    h["holding_date"] = pd.to_datetime(h["holding_date"])
    h["ticker"] = h["ticker"].astype(str)
    h = h[h["date"] >= pd.Timestamp("2006-07-31")].copy()
    if h.empty:
        raise RuntimeError("no post-2006 holdings rows")
    h["weight"] = pd.to_numeric(h["weight"], errors="coerce")
    h["security_return"] = pd.to_numeric(h["security_return"], errors="coerce")
    h["weighted_return_contribution"] = h["weight"] * h["security_return"]

    mcap_col = _pick(h, ["marketcap", "market_cap", "mktcap", "market_capitalization"], required=False)
    if mcap_col:
        h["market_cap"] = pd.to_numeric(h[mcap_col], errors="coerce")
        h["market_cap_bucket"] = h.groupby("holding_date", group_keys=False)["market_cap"].apply(
            lambda s: _bucket_quantile(s, ["smallest_q", "lower_mid_q", "upper_mid_q", "largest_q"])
        )
    else:
        h["market_cap_bucket"] = "unavailable_no_PIT_market_cap_authority"

    adv_col = _pick(h, ["adv20", "avg_dollar_volume_20d", "dollar_volume_20d", "adv", "liquidity"], required=False)
    if adv_col:
        h["adv20"] = pd.to_numeric(h[adv_col], errors="coerce")
        h["liquidity_bucket"] = h.groupby("holding_date", group_keys=False)["adv20"].apply(
            lambda s: _bucket_quantile(s, ["lowest_q", "lower_mid_q", "upper_mid_q", "highest_q"])
        )
    else:
        h["liquidity_bucket"] = "unavailable"

    membership_available = False
    if args.sp500_eligibility and args.sp500_eligibility.exists():
        sp = pd.read_csv(args.sp500_eligibility)
        sp.columns = [str(c).strip() for c in sp.columns]
        sd = _pick(sp, ["date", "session", "trade_date"])
        st = _pick(sp, ["ticker", "source_ticker", "symbol"])
        sp = sp.rename(columns={sd: "holding_date", st: "ticker"})[["holding_date", "ticker"]].copy()
        sp["holding_date"] = pd.to_datetime(sp["holding_date"])
        sp["ticker"] = sp["ticker"].astype(str)
        sp["sp500_member"] = True
        sp = sp.drop_duplicates(["holding_date", "ticker"])
        h = h.merge(sp, on=["holding_date", "ticker"], how="left")
        h["sp500_member"] = h["sp500_member"].fillna(False)
        h["sp500_membership_bucket"] = np.where(h["sp500_member"], "sp500_member", "outside_sp500")
        membership_available = True
    else:
        h["sp500_membership_bucket"] = "unavailable"

    ticker = (h.groupby("ticker", as_index=False)
              .agg(rows=("ticker", "size"),
                   weighted_return_contribution=("weighted_return_contribution", "sum"),
                   mean_weight=("weight", "mean"),
                   first_date=("holding_date", "min"),
                   last_date=("date", "max")))
    ticker = ticker.sort_values("weighted_return_contribution", ascending=False)
    total_positive = float(ticker.loc[ticker["weighted_return_contribution"] > 0, "weighted_return_contribution"].sum())
    top_share = {}
    for n in [5, 10, 20, 50, 100]:
        numerator = float(ticker.head(n)["weighted_return_contribution"].clip(lower=0).sum())
        top_share[str(n)] = None if total_positive == 0 else numerator / total_positive

    # Reconcile the trace against the raw Wealth Core daily close-to-close return.
    daily = pd.read_csv(args.broad_root / "daily.csv.gz", parse_dates=["date"])
    daily = daily[daily["date"] >= pd.Timestamp("2006-07-31")].copy()
    daily["wc_return"] = pd.to_numeric(daily["research_wealth_core_equity"], errors="coerce").pct_change()
    trace_daily = h.groupby("date", as_index=False)["weighted_return_contribution"].sum().rename(
        columns={"weighted_return_contribution": "trace_stock_contribution"})
    rec = daily[["date", "wc_return"]].merge(trace_daily, on="date", how="inner").dropna()
    reconciliation = {
        "sessions": int(len(rec)),
        "correlation_trace_vs_wc_return": None if len(rec) < 3 else float(rec["trace_stock_contribution"].corr(rec["wc_return"])),
        "mean_abs_residual": float((rec["wc_return"] - rec["trace_stock_contribution"]).abs().mean()),
        "sum_wc_return": float(rec["wc_return"].sum()),
        "sum_trace_stock_contribution": float(rec["trace_stock_contribution"].sum()),
        "note": "Residual includes cash, trading/open-gap effects, dividends, transaction costs, and holdings entering/exiting within the session.",
    }

    result = {
        "schema": "backtester.broad-alpha-attribution/2",
        "status": "PASS",
        "scope": "diagnostic_prior_close_realized_stock_contribution_attribution",
        "formal_pit_certified": False,
        "holdings_source": holdings_name,
        "rows": int(len(h)),
        "unique_tickers": int(h["ticker"].nunique()),
        "date_start": str(h["date"].min().date()),
        "date_end": str(h["date"].max().date()),
        "market_cap_available": bool(mcap_col),
        "market_cap_limitation": None if mcap_col else "No point-in-time market-cap authority is present in the frozen replay trace; no market-cap claim is made.",
        "liquidity_available": bool(adv_col),
        "sp500_membership_available": membership_available,
        "market_cap_attribution": _summarize(h, "market_cap_bucket"),
        "liquidity_attribution": _summarize(h, "liquidity_bucket"),
        "sp500_membership_attribution": _summarize(h, "sp500_membership_bucket"),
        "top_positive_contributor_share": top_share,
        "reconciliation": reconciliation,
        "top_contributors": ticker.head(100).assign(
            first_date=lambda x: x["first_date"].astype(str),
            last_date=lambda x: x["last_date"].astype(str),
        ).to_dict(orient="records"),
    }

    (args.output / "attribution.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    ticker.to_csv(args.output / "ticker_contributions.csv", index=False)
    h.to_csv(args.output / "holding_contributions.csv.gz", index=False, compression="gzip")
    rec.to_csv(args.output / "daily_reconciliation.csv", index=False)

    lines = [
        "# Broad-universe alpha attribution",
        "",
        "Diagnostic realized-stock contribution attribution; no new formal PIT certification claim.",
        "",
        f"Rows: {result['rows']:,}; unique tickers: {result['unique_tickers']:,}; period: {result['date_start']} to {result['date_end']}.",
        "",
        "## Market cap",
        f"- {result['market_cap_limitation'] or 'PIT market-cap field available.'}",
        "",
        "## Liquidity buckets",
    ]
    for r in result["liquidity_attribution"]:
        lines.append(f"- {r['bucket']}: contribution {r['sum_weighted_return_contribution']:.6f}, tickers {r['unique_tickers']}")
    lines += ["", "## S&P 500 membership"]
    for r in result["sp500_membership_attribution"]:
        lines.append(f"- {r['bucket']}: contribution {r['sum_weighted_return_contribution']:.6f}, tickers {r['unique_tickers']}")
    lines += ["", "## Contributor concentration"]
    for n, share in top_share.items():
        lines.append(f"- Top {n}: {'NA' if share is None else f'{share:.2%}'} of positive ticker contribution")
    lines += [
        "",
        "## Trace reconciliation",
        f"- sessions: {reconciliation['sessions']}",
        f"- trace/WC daily-return correlation: {reconciliation['correlation_trace_vs_wc_return']}",
        f"- mean absolute residual: {reconciliation['mean_abs_residual']:.6f}",
    ]
    (args.output / "ATTRIBUTION.md").write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())