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
  3. Strip the market: regress every stock AND the basket on SPY, keep residuals
     (so we measure AI-specific co-movement, not "both are high-beta tech").
  4. Exposure score = max(0, corr(stock_residual, basket_residual)) in [0,1].
  5. Rank the whole liquid universe by that score and print the top N.

It also prints the RAW (non-residualized) correlation next to the residual one so
you can see how much the market-strip matters (raw mostly rediscovers high beta).

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
    # Liquid AND a real equity (has fundamentals) — drops ETFs/funds. SPY is kept
    # only as the market benchmark for residualization, not scored.
    liquid = ((set(liq[liq >= MIN_AVG_DOLLAR_VOL].index) & equities) | set(SEED) | {"SPY"})

    px = df[df["ticker"].isin(liquid)].pivot_table(
        index="date", columns="ticker", values="adjusted_close"
    ).sort_index()
    rets = px.pct_change()

    if "SPY" not in rets.columns:
        print("SPY not found in daily_prices — cannot residualize. Aborting.")
        return
    spy = rets["SPY"]

    seed_present = [t for t in SEED if t in rets.columns]
    seed_missing = [t for t in SEED if t not in rets.columns]
    if len(seed_present) < 3:
        print(f"Too few seed names present ({seed_present}); aborting.")
        return
    basket = rets[seed_present].mean(axis=1)        # equal-weight theme return
    basket_resid = _residual(basket, spy)
    if basket_resid.empty:
        print("Could not residualize the basket. Aborting.")
        return

    out = []
    for t in rets.columns:
        if t == "SPY":
            continue
        col = rets[t]
        if col.dropna().shape[0] < MIN_OBS:
            continue
        r_resid = _residual(col, spy)
        if r_resid.empty:
            continue
        rc = _corr(r_resid, basket_resid)        # residual (market-stripped) corr
        raw = _corr(col, basket)                 # raw corr (for comparison)
        if rc is None:
            continue
        out.append({
            "ticker": t,
            "exposure": round(max(0.0, rc), 3),
            "resid_corr": round(rc, 3),
            "raw_corr": round(raw, 3) if raw is not None else None,
            "in_seed": t in seed_present,
            "avg_$vol_M": round(float(liq.get(t, 0)) / 1e6, 1),
        })

    res = pd.DataFrame(out).sort_values("exposure", ascending=False).reset_index(drop=True)

    print(f"\nWindow: last {WINDOW_CALENDAR_DAYS} calendar days  |  liquid universe: "
          f"{len(liquid)-1} tickers  |  seed used: {len(seed_present)}")
    if seed_missing:
        print(f"Seed names missing from daily_prices (skipped): {seed_missing}")
    print(f"\nTop {top_n} by residual (market-stripped) correlation to the AI-infra basket:\n")
    print(f"{'#':>3}  {'ticker':<7} {'expo':>5} {'resid':>6} {'raw':>6}  {'seed':<5} {'$vol(M)':>8}")
    for i, r in res.head(top_n).iterrows():
        print(f"{i+1:>3}  {r['ticker']:<7} {r['exposure']:>5} {r['resid_corr']:>6} "
              f"{str(r['raw_corr']):>6}  {'YES' if r['in_seed'] else '':<5} {r['avg_$vol_M']:>8}")

    # Optional CSV to the mounted artifacts volume for easy off-box review.
    try:
        path = "/artifacts/ai_universe_eyeball.csv"
        res.to_csv(path, index=False)
        print(f"\nFull ranked list written to {path}")
    except Exception as e:  # noqa: BLE001
        print(f"\n(Could not write CSV: {e})")


if __name__ == "__main__":
    asyncio.run(main())
