#!/usr/bin/env python3
"""STANDALONE AI-infrastructure universe generator — EYEBALL TOOL.

Completely decoupled from the live system: reads ONLY daily_prices (read-only),
writes NOTHING to the database, imports NOTHING from services/. Running it changes
no existing behavior. Its sole job is to print a ranked list of likely AI-infra
names so you can eyeball whether the universe looks right BEFORE any service/tab is
built.

Method (the residualized-correlation approach we discussed):
  1. Seed = a small, hand-picked set of PURE-PLAY AI-infra names (editable below).
  2. Theme basket return = equal-weight daily return of the seed names.
  3. Strip the market AND the semis sector: regress every stock AND the basket on
     [SPY, SOXX], keep residuals — so we measure AI-SPECIFIC co-movement, not "both
     are high-beta tech" (SPY) and not "both are semiconductors" (SOXX). The sector
     strip is what drops generic non-AI chip names (mobile RF, auto analog).
  4. Exposure score = max(0, corr(stock_residual, basket_residual)) in [0,1].
  5. Rank the whole liquid universe by that score and print the top N.

It prints three correlations side by side: ai (market+sector stripped, the ranking
key), mkt (market-only stripped, the previous method), and raw (no controls). A
name whose mkt is high but ai collapses is a generic semi riding the sector, not AI.

Run it inside the pipeline container (which has the deps + DB access):

    docker cp tools/theme_ai/build_ai_universe.py stocker-pipeline-1:/tmp/
    docker exec stocker-pipeline-1 python /tmp/build_ai_universe.py            # top 80
    docker exec stocker-pipeline-1 python /tmp/build_ai_universe.py 120        # top 120

Env: DATABASE_URL (already set in the pipeline container).
"""
import asyncio
import os
import sys

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# ── Pure-play AI-infra seed (edit freely; missing tickers are skipped) ──────────
# Kept deliberately tight and pure so the basket isn't muddied by diversified
# mega-caps (e.g. MSFT/AMZN are mostly NOT AI-infra in revenue terms).
SEED = [
    # compute / accelerators
    "NVDA", "AVGO", "AMD",
    # foundry / memory
    "TSM", "MU",
    # semicap (the equipment that builds the chips)
    "AMAT", "LRCX", "KLAC", "ASML",
    # networking / interconnect
    "ANET", "CRDO", "ALAB",
    # optical
    "COHR", "LITE",
    # power / electrical / thermal for data centers
    "VRT", "POWL", "ETN", "GEV",
    # data-center REITs
    "EQIX", "DLR",
]

WINDOW_CALENDAR_DAYS = 400      # pull ~400 calendar days → ~252 trading rows
MIN_OBS = 120                   # min overlapping return pairs to score a ticker
MIN_AVG_DOLLAR_VOL = 20_000_000 # self-contained liquidity gate ($/day), matches the live universe filter

# Sector factor stripped IN ADDITION to the market. The AI-infra basket is
# semis-heavy, so generic (non-AI) chip names — mobile RF (SWKS/QRVO), auto/
# industrial analog (NXPI/ADI) — co-move with it purely via the semiconductor
# sector, not via AI. Regressing out SOXX (the semis sector) as well leaves only
# AI-SPECIFIC co-movement (optical, HBM, accelerators, power, packaging), so those
# generic semis fall away. SOXX itself is never scored — used only as a factor.
SECTOR_ETF = "SOXX"


def _residual(y: pd.Series, x: pd.Series) -> pd.Series:
    """OLS residual of y on x over their common non-NaN dates: y - (alpha + beta*x)."""
    df = pd.concat([y, x], axis=1, keys=["y", "x"]).dropna()
    if len(df) < MIN_OBS:
        return pd.Series(dtype=float)
    yv, xv = df["y"].to_numpy(), df["x"].to_numpy()
    var = xv.var()
    if var <= 0:
        return pd.Series(dtype=float)
    beta = np.cov(yv, xv, bias=True)[0, 1] / var
    alpha = yv.mean() - beta * xv.mean()
    return pd.Series(yv - alpha - beta * xv, index=df.index)


def _residual_multi(y: pd.Series, X: pd.DataFrame) -> pd.Series:
    """OLS residual of y on multiple factors X (with intercept), over common dates.
    Used to strip BOTH the market (SPY) and the semis sector (SOXX) at once, so the
    leftover is AI-specific co-movement only."""
    df = pd.concat([y.rename("y"), X], axis=1).dropna()
    if len(df) < MIN_OBS:
        return pd.Series(dtype=float)
    yv = df["y"].to_numpy()
    Xv = df.drop(columns="y").to_numpy()
    A = np.column_stack([np.ones(len(Xv)), Xv])
    coef, *_ = np.linalg.lstsq(A, yv, rcond=None)
    return pd.Series(yv - A @ coef, index=df.index)


def _corr(a: pd.Series, b: pd.Series) -> float | None:
    df = pd.concat([a, b], axis=1).dropna()
    if len(df) < MIN_OBS:
        return None
    c = df.iloc[:, 0].corr(df.iloc[:, 1])
    return None if pd.isna(c) else float(c)


async def main() -> None:
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url)

    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT ticker, date, adjusted_close, volume FROM daily_prices "
            "WHERE date >= (CURRENT_DATE - INTERVAL '%d days') "
            "AND adjusted_close IS NOT NULL AND adjusted_close > 0" % WINDOW_CALENDAR_DAYS
        ))).fetchall()
        # Equities only: ETFs/funds (SOXX, QQQ, leveraged products…) have no
        # fundamentals row and otherwise leak in because they co-move with the
        # basket by construction. Read-only; keeps the tool decoupled.
        fund_rows = (await conn.execute(text(
            "SELECT DISTINCT ticker FROM fundamentals WHERE source != 'no_data'"
        ))).fetchall()
    await engine.dispose()

    equities = {r[0] for r in fund_rows}

    if not rows:
        print("No price data found.")
        return

    df = pd.DataFrame(rows, columns=["ticker", "date", "adjusted_close", "volume"])
    df["adjusted_close"] = df["adjusted_close"].astype(float)
    df["volume"] = df["volume"].fillna(0).astype(float)

    # Liquidity gate (self-contained — no dependency on the live universe tables).
    df["dollar_vol"] = df["adjusted_close"] * df["volume"]
    liq = df.groupby("ticker")["dollar_vol"].mean()
    # Liquid AND a real equity (has fundamentals) — drops ETFs/funds. SPY and SOXX
    # are kept only as residualization FACTORS (market + semis sector), not scored.
    liquid = ((set(liq[liq >= MIN_AVG_DOLLAR_VOL].index) & equities)
              | set(SEED) | {"SPY", SECTOR_ETF})

    px = df[df["ticker"].isin(liquid)].pivot_table(
        index="date", columns="ticker", values="adjusted_close"
    ).sort_index()
    rets = px.pct_change()

    if "SPY" not in rets.columns:
        print("SPY not found in daily_prices — cannot residualize. Aborting.")
        return
    spy = rets["SPY"]
    factor_names = ["SPY"] + ([SECTOR_ETF] if SECTOR_ETF in rets.columns else [])
    factors = rets[factor_names]
    sector_on = SECTOR_ETF in rets.columns

    seed_present = [t for t in SEED if t in rets.columns]
    seed_missing = [t for t in SEED if t not in rets.columns]
    if len(seed_present) < 3:
        print(f"Too few seed names present ({seed_present}); aborting.")
        return
    basket = rets[seed_present].mean(axis=1)        # equal-weight theme return
    basket_resid_spy = _residual(basket, spy)               # market-only
    basket_resid_ms = _residual_multi(basket, factors)      # market + semis sector
    if basket_resid_ms.empty:
        print("Could not residualize the basket. Aborting.")
        return

    out = []
    for t in rets.columns:
        if t in ("SPY", SECTOR_ETF):
            continue
        col = rets[t]
        if col.dropna().shape[0] < MIN_OBS:
            continue
        ai = _corr(_residual_multi(col, factors), basket_resid_ms)   # AI-specific (market+sector stripped)
        if ai is None:
            continue
        mkt = _corr(_residual(col, spy), basket_resid_spy)           # market-only stripped (prev method)
        raw = _corr(col, basket)                                     # no controls
        out.append({
            "ticker": t,
            "exposure": round(max(0.0, ai), 3),     # primary: AI-specific
            "ai_corr": round(ai, 3),
            "mkt_corr": round(mkt, 3) if mkt is not None else None,
            "raw_corr": round(raw, 3) if raw is not None else None,
            "in_seed": t in seed_present,
            "avg_$vol_M": round(float(liq.get(t, 0)) / 1e6, 1),
        })

    res = pd.DataFrame(out).sort_values("exposure", ascending=False).reset_index(drop=True)

    nfac = len(factor_names)
    print(f"\nWindow: last {WINDOW_CALENDAR_DAYS} calendar days  |  liquid universe: "
          f"{len(liquid)-nfac} tickers  |  seed used: {len(seed_present)}  |  "
          f"factors stripped: {'SPY+'+SECTOR_ETF if sector_on else 'SPY only ('+SECTOR_ETF+' MISSING)'}")
    if seed_missing:
        print(f"Seed names missing from daily_prices (skipped): {seed_missing}")
    print(f"\nTop {top_n} by AI-SPECIFIC correlation (market + semis-sector stripped).")
    print("  ai = market+SOXX stripped (rank by this) | mkt = market-only stripped | raw = no controls")
    print("  Watch names where mkt is high but ai drops sharply → generic semis, not AI.\n")
    print(f"{'#':>3}  {'ticker':<7} {'expo':>5} {'ai':>6} {'mkt':>6} {'raw':>6}  {'seed':<5} {'$vol(M)':>8}")
    for i, r in res.head(top_n).iterrows():
        print(f"{i+1:>3}  {r['ticker']:<7} {r['exposure']:>5} {str(r['ai_corr']):>6} "
              f"{str(r['mkt_corr']):>6} {str(r['raw_corr']):>6}  "
              f"{'YES' if r['in_seed'] else '':<5} {r['avg_$vol_M']:>8}")

    # Optional CSV to the mounted artifacts volume for easy off-box review.
    try:
        path = "/artifacts/ai_universe_eyeball.csv"
        res.to_csv(path, index=False)
        print(f"\nFull ranked list written to {path}")
    except Exception as e:  # noqa: BLE001
        print(f"\n(Could not write CSV: {e})")


if __name__ == "__main__":
    asyncio.run(main())
