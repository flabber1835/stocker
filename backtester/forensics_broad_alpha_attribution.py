#!/usr/bin/env python3
"""Attribute broad-universe Wealth Core alpha to market-cap/liquidity/member buckets.

Diagnostic research only. This script consumes a broad full-PIT daily result plus
its retained holdings/ranking traces and classifies realized contribution by:
- market-cap bucket,
- liquidity bucket,
- S&P 500 membership status when available,
- concentration in top contributors.

It does not alter strategy economics and does not claim formal PIT certification.
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
    edges = np.linspace(0, 1, len(labels) + 1)
    vals = pd.cut(ranks, bins=edges, labels=labels, include_lowest=True)
    out.loc[valid] = vals.astype(str)
    out.loc[~valid] = "unknown"
    return out


def _summarize(df: pd.DataFrame, bucket: str, ret_col: str, weight_col: str) -> list[dict]:
    rows = []
    for key, g in df.groupby(bucket, dropna=False):
        contrib = pd.to_numeric(g[ret_col], errors="coerce") * pd.to_numeric(g[weight_col], errors="coerce")
        rows.append({
            "bucket": str(key),
            "rows": int(len(g)),
            "unique_tickers": int(g["ticker"].nunique()),
            "mean_weight": float(pd.to_numeric(g[weight_col], errors="coerce").mean()),
            "mean_security_return": float(pd.to_numeric(g[ret_col], errors="coerce").mean()),
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

    holdings, holdings_name = _read_first(args.broad_root, [
        "holdings_daily.csv.gz", "holdings.csv.gz", "research_holdings.csv.gz",
        "position_trace.csv.gz", "positions.csv.gz",
    ])
    holdings.columns = [str(c).strip() for c in holdings.columns]

    date_col = _pick(holdings, ["date", "session", "trade_date"])
    ticker_col = _pick(holdings, ["ticker", "symbol", "security"])
    weight_col = _pick(holdings, ["weight", "portfolio_weight", "close_weight", "target_weight"])
    ret_col = _pick(holdings, ["return", "session_return", "daily_return", "security_return", "ret"])
    mcap_col = _pick(holdings, ["marketcap", "market_cap", "mktcap", "market_capitalization"], required=False)
    adv_col = _pick(holdings, ["adv20", "avg_dollar_volume_20d", "dollar_volume_20d", "adv", "liquidity"], required=False)

    h = holdings.rename(columns={date_col: "date", ticker_col: "ticker", weight_col: "weight", ret_col: "security_return"}).copy()
    h["date"] = pd.to_datetime(h["date"])
    h["ticker"] = h["ticker"].astype(str)
    h = h[h["date"] >= pd.Timestamp("2006-07-31")].copy()
    if h.empty:
        raise RuntimeError("no post-2006 holdings rows")

    if mcap_col:
        h["market_cap"] = pd.to_numeric(h[mcap_col], errors="coerce")
        h["market_cap_bucket"] = h.groupby("date", group_keys=False)["market_cap"].apply(
            lambda s: _bucket_quantile(s, ["smallest_q", "lower_mid_q", "upper_mid_q", "largest_q"])
        )
    else:
        h["market_cap_bucket"] = "unavailable"

    if adv_col:
        h["adv20"] = pd.to_numeric(h[adv_col], errors="coerce")
        h["liquidity_bucket"] = h.groupby("date", group_keys=False)["adv20"].apply(
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
        sp = sp.rename(columns={sd: "date", st: "ticker"})[["date", "ticker"]].copy()
        sp["date"] = pd.to_datetime(sp["date"])
        sp["ticker"] = sp["ticker"].astype(str)
        sp["sp500_member"] = True
        sp = sp.drop_duplicates(["date", "ticker"])
        h = h.merge(sp, on=["date", "ticker"], how="left")
        h["sp500_member"] = h["sp500_member"].fillna(False)
        h["sp500_membership_bucket"] = np.where(h["sp500_member"], "sp500_member", "outside_sp500")
        membership_available = True
    else:
        h["sp500_membership_bucket"] = "unavailable"

    h["weighted_return_contribution"] = pd.to_numeric(h["security_return"], errors="coerce") * pd.to_numeric(h["weight"], errors="coerce")

    ticker = (h.groupby("ticker", as_index=False)
              .agg(rows=("ticker", "size"),
                   weighted_return_contribution=("weighted_return_contribution", "sum"),
                   mean_weight=("weight", "mean"),
                   first_date=("date", "min"),
                   last_date=("date", "max")))
    ticker = ticker.sort_values("weighted_return_contribution", ascending=False)
    total_positive = float(ticker.loc[ticker["weighted_return_contribution"] > 0, "weighted_return_contribution"].sum())
    top_share = {}
    for n in [5, 10, 20, 50, 100]:
        numerator = float(ticker.head(n)["weighted_return_contribution"].clip(lower=0).sum())
        top_share[str(n)] = None if total_positive == 0 else numerator / total_positive

    result = {
        "schema": "backtester.broad-alpha-attribution/1",
        "status": "PASS",
        "scope": "diagnostic_realized_contribution_attribution",
        "formal_pit_certified": False,
        "holdings_source": holdings_name,
        "rows": int(len(h)),
        "unique_tickers": int(h["ticker"].nunique()),
        "date_start": str(h["date"].min().date()),
        "date_end": str(h["date"].max().date()),
        "market_cap_available": bool(mcap_col),
        "liquidity_available": bool(adv_col),
        "sp500_membership_available": membership_available,
        "market_cap_attribution": _summarize(h, "market_cap_bucket", "security_return", "weight"),
        "liquidity_attribution": _summarize(h, "liquidity_bucket", "security_return", "weight"),
        "sp500_membership_attribution": _summarize(h, "sp500_membership_bucket", "security_return", "weight"),
        "top_positive_contributor_share": top_share,
        "top_contributors": ticker.head(100).assign(
            first_date=lambda x: x["first_date"].astype(str),
            last_date=lambda x: x["last_date"].astype(str),
        ).to_dict(orient="records"),
    }

    (args.output / "attribution.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    ticker.to_csv(args.output / "ticker_contributions.csv", index=False)
    h.to_csv(args.output / "holding_contributions.csv.gz", index=False, compression="gzip")

    lines = [
        "# Broad-universe alpha attribution",
        "",
        "Diagnostic only; this is a realized-contribution attribution and does not claim a new PIT certification.",
        "",
        f"Rows: {result['rows']:,}; unique tickers: {result['unique_tickers']:,}; period: {result['date_start']} to {result['date_end']}.",
        "",
        "## Market-cap buckets",
    ]
    for r in result["market_cap_attribution"]:
        lines.append(f"- {r['bucket']}: contribution {r['sum_weighted_return_contribution']:.6f}, tickers {r['unique_tickers']}")
    lines += ["", "## Liquidity buckets"]
    for r in result["liquidity_attribution"]:
        lines.append(f"- {r['bucket']}: contribution {r['sum_weighted_return_contribution']:.6f}, tickers {r['unique_tickers']}")
    lines += ["", "## S&P 500 membership"]
    for r in result["sp500_membership_attribution"]:
        lines.append(f"- {r['bucket']}: contribution {r['sum_weighted_return_contribution']:.6f}, tickers {r['unique_tickers']}")
    lines += ["", "## Contributor concentration"]
    for n, share in top_share.items():
        lines.append(f"- Top {n}: {'NA' if share is None else f'{share:.2%}'} of positive ticker contribution")
    (args.output / "ATTRIBUTION.md").write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
