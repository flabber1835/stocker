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
  3. Build an ORTHOGONALIZED semis-sector factor: generic_semi = residual of SOXX
     on [SPY, AI_basket] — the part of the chip sector that is neither market nor
     AI. Then strip [SPY, generic_semi] from every stock and the basket. This
     removes generic-semi co-movement (mobile RF, auto/industrial analog) WITHOUT
     eating AI signal (the factor is orthogonal to the basket by construction), so
     the core AI semis (NVDA/AVGO/MU) stay on top.
  4. Exposure score = max(0, corr(stock_residual, basket_residual)) in [0,1].
  5. Rank the whole liquid universe by that one score and print the top N.

It prints expo (the AI-specific score) next to mkt (market-only) and raw (no
controls), and at the end shows where known GENERIC semis landed — they should be
low, confirming the sector strip works without burying the real AI names.

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
    # HBM / advanced packaging / test / materials
    "ONTO", "CAMT", "ENTG", "TER",
    # networking / interconnect / custom silicon
    "ANET", "CRDO", "ALAB", "MRVL",
    # optical (modules + manufacturing + DCI)
    "COHR", "LITE", "FN", "CIEN",
    # AI servers / ODM
    "SMCI", "CLS",
    # AI cloud
    "CRWV",
    # power / electrical / thermal for data centers
    "VRT", "POWL", "ETN", "GEV",
    # data-center REITs
    "EQIX", "DLR",
]

WINDOW_CALENDAR_DAYS = 400      # pull ~400 calendar days → ~252 trading rows
MIN_OBS = 120                   # min overlapping return pairs to score a ticker
MIN_AVG_DOLLAR_VOL = 20_000_000 # self-contained liquidity gate ($/day), matches the live universe filter

# Semiconductor sector factor. Raw SOXX is cap-weighted and IS the core AI semis
# (NVDA/AVGO/AMD/TSM/MU), so regressing it out directly buries those very names. We
# instead ORTHOGONALIZE it to the AI basket first: generic_semi = residual of SOXX
# on [SPY, AI_basket] — "the part of the semi sector that is NOT market and NOT AI".
# Stripping [SPY, generic_semi] then removes generic-semi co-movement (mobile RF,
# auto/industrial analog) WITHOUT touching AI signal (generic_semi is orthogonal to
# the basket by construction). One clean AI-specific score; NVDA stays on top.
# SOXX is used only to build the factor, never scored.
SECTOR_ETF = "SOXX"

# Known generic (non-AI) semis — printed at the end as a validation check; they
# should land with LOW scores once the orthogonalized sector factor is stripped.
GENERIC_SEMI_CHECK = ["SWKS", "QRVO", "NXPI", "ADI", "TXN", "MCHP", "ON"]


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
    sector_on = SECTOR_ETF in rets.columns

    seed_present = [t for t in SEED if t in rets.columns]
    seed_missing = [t for t in SEED if t not in rets.columns]
    if len(seed_present) < 3:
        print(f"Too few seed names present ({seed_present}); aborting.")
        return
    basket = rets[seed_present].mean(axis=1)        # equal-weight theme return

    # Orthogonalized sector factor: the part of SOXX that is NEITHER market NOR AI.
    # generic_semi = residual of SOXX on [SPY, basket]. Stripping [SPY, generic_semi]
    # removes generic-semi co-movement without eating AI signal (it's orthogonal to
    # the basket). Falls back to market-only if SOXX is absent.
    if sector_on:
        gsemi = _residual_multi(rets[SECTOR_ETF], pd.concat([spy.rename("SPY"), basket.rename("BSK")], axis=1))
        gsemi = gsemi.rename("GSEMI")
        ai_factors = pd.concat([spy.rename("SPY"), gsemi], axis=1)
    else:
        ai_factors = spy.to_frame("SPY")

    basket_resid_spy = _residual(basket, spy)                 # market-only
    basket_resid_ai = _residual_multi(basket, ai_factors)     # market + orthogonalized sector
    if basket_resid_ai.empty:
        print("Could not residualize the basket. Aborting.")
        return

    out = []
    for t in rets.columns:
        if t in ("SPY", SECTOR_ETF):
            continue
        col = rets[t]
        if col.dropna().shape[0] < MIN_OBS:
            continue
        ai = _corr(_residual_multi(col, ai_factors), basket_resid_ai)  # AI-specific (market + ortho-sector stripped)
        if ai is None:
            continue
        mkt = _corr(_residual(col, spy), basket_resid_spy)            # market-only stripped
        raw = _corr(col, basket)                                      # no controls
        out.append({
            "ticker": t,
            "exposure": round(max(0.0, ai), 3),      # rank key: AI-specific (market + ortho-sector stripped)
            "ai_corr": round(ai, 3),
            "mkt_corr": round(mkt, 3) if mkt is not None else None,
            "raw_corr": round(raw, 3) if raw is not None else None,
            "in_seed": t in seed_present,
            "avg_$vol_M": round(float(liq.get(t, 0)) / 1e6, 1),
        })

    df_all = pd.DataFrame(out)
    res = df_all.sort_values("exposure", ascending=False).reset_index(drop=True)
    rank_of = {r["ticker"]: i + 1 for i, (_, r) in enumerate(res.iterrows())}

    print(f"\nWindow: last {WINDOW_CALENDAR_DAYS} calendar days  |  liquid universe: "
          f"{len(df_all)} scored  |  seed: {len(seed_present)}  |  "
          f"sector factor: {'orthogonalized '+SECTOR_ETF if sector_on else SECTOR_ETF+' MISSING (market-only)'}")
    if seed_missing:
        print(f"Seed names missing from daily_prices (skipped): {seed_missing}")
    print(f"\nAI-INFRA UNIVERSE — top {top_n}, ranked by AI-SPECIFIC corr (expo).")
    print("  expo = market + orthogonalized-sector stripped (rank key) | mkt = market-only | raw = no controls\n")
    print(f"{'#':>3}  {'ticker':<7} {'expo':>5} {'mkt':>6} {'raw':>6}  {'seed':<5} {'$vol(M)':>8}")
    for i, r in res.head(top_n).iterrows():
        print(f"{i+1:>3}  {r['ticker']:<7} {r['exposure']:>5} {str(r['mkt_corr']):>6} "
              f"{str(r['raw_corr']):>6}  {'YES' if r['in_seed'] else '':<5} {r['avg_$vol_M']:>8}")

    # Validation: known GENERIC (non-AI) semis should now land LOW — confirms the
    # orthogonalized sector strip removes them without burying the real AI names.
    print("\nValidation — where known GENERIC semis landed (should be low expo / deep rank):")
    print(f"{'ticker':<7} {'expo':>5} {'rank':>6}")
    for t in GENERIC_SEMI_CHECK:
        if t in rank_of:
            rr = df_all[df_all["ticker"] == t].iloc[0]
            print(f"{t:<7} {rr['exposure']:>5} {rank_of[t]:>6}")
        else:
            print(f"{t:<7} {'—':>5} {'(absent)':>8}")

    # Optional CSV to the mounted artifacts volume for easy off-box review.
    try:
        path = "/artifacts/ai_universe_eyeball.csv"
        res.to_csv(path, index=False)
        print(f"\nFull ranked list written to {path}")
    except Exception as e:  # noqa: BLE001
        print(f"\n(Could not write CSV: {e})")


if __name__ == "__main__":
    asyncio.run(main())
