"""Thematic-universe scoring — the orthogonalized-sector residual-correlation method
(validated in tools/theme_ai/build_ai_universe.py).

Pure math helpers (stdlib/numpy/pandas, unit-testable) + an async run that reads
daily_prices/fundamentals READ-ONLY and writes the theme_exposures table. Nothing
here references the trading pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import text


@dataclass(frozen=True)
class ThemeConfig:
    theme: str
    seed: list[str]
    sector_etf: str = "SOXX"            # orthogonalized against the basket before stripping
    window_days: int = 400             # ~252 trading rows
    min_obs: int = 120
    min_avg_dollar_vol: float = 20_000_000.0


AI_INFRA = ThemeConfig(
    theme="ai_infra",
    seed=[
        "NVDA", "AVGO", "AMD",          # compute / accelerators
        "TSM", "MU",                    # foundry / memory
        "AMAT", "LRCX", "KLAC", "ASML", # semicap
        "ANET", "CRDO", "ALAB",         # networking / interconnect
        "COHR", "LITE",                 # optical
        "VRT", "POWL", "ETN", "GEV",    # power / electrical / thermal
        "EQIX", "DLR",                  # data-center REITs
    ],
)


def _residual(y: pd.Series, x: pd.Series, min_obs: int) -> pd.Series:
    """OLS residual of y on x over common non-NaN dates."""
    df = pd.concat([y, x], axis=1, keys=["y", "x"]).dropna()
    if len(df) < min_obs:
        return pd.Series(dtype=float)
    yv, xv = df["y"].to_numpy(), df["x"].to_numpy()
    var = xv.var()
    if var <= 0:
        return pd.Series(dtype=float)
    beta = np.cov(yv, xv, bias=True)[0, 1] / var
    alpha = yv.mean() - beta * xv.mean()
    return pd.Series(yv - alpha - beta * xv, index=df.index)


def _residual_multi(y: pd.Series, X: pd.DataFrame, min_obs: int) -> pd.Series:
    """OLS residual of y on multiple factors X (with intercept), over common dates."""
    df = pd.concat([y.rename("y"), X], axis=1).dropna()
    if len(df) < min_obs:
        return pd.Series(dtype=float)
    yv = df["y"].to_numpy()
    Xv = df.drop(columns="y").to_numpy()
    A = np.column_stack([np.ones(len(Xv)), Xv])
    coef, *_ = np.linalg.lstsq(A, yv, rcond=None)
    return pd.Series(yv - A @ coef, index=df.index)


def _corr(a: pd.Series, b: pd.Series, min_obs: int) -> float | None:
    df = pd.concat([a, b], axis=1).dropna()
    if len(df) < min_obs:
        return None
    c = df.iloc[:, 0].corr(df.iloc[:, 1])
    return None if pd.isna(c) else float(c)


def score_exposures(prices: pd.DataFrame, equities: set[str], liq: pd.Series,
                    cfg: ThemeConfig) -> pd.DataFrame:
    """Given a price panel (date index × ticker columns of adjusted_close), the set
    of real equities (has fundamentals), and per-ticker avg dollar volume, return a
    DataFrame [ticker, exposure, in_seed, avg_dollar_vol] ranked by exposure desc.

    exposure = max(0, corr(stock_resid, basket_resid)) where residuals strip
    [SPY, generic_semi], generic_semi = residual of SOXX on [SPY, basket]. Pure."""
    rets = prices.pct_change()
    if "SPY" not in rets.columns:
        raise ValueError("SPY not in price panel — cannot residualize")
    spy = rets["SPY"]
    sector_on = cfg.sector_etf in rets.columns

    seed_present = [t for t in cfg.seed if t in rets.columns]
    if len(seed_present) < 3:
        raise ValueError(f"too few seed names present: {seed_present}")
    basket = rets[seed_present].mean(axis=1)

    if sector_on:
        gsemi = _residual_multi(
            rets[cfg.sector_etf],
            pd.concat([spy.rename("SPY"), basket.rename("BSK")], axis=1),
            cfg.min_obs,
        ).rename("GSEMI")
        ai_factors = pd.concat([spy.rename("SPY"), gsemi], axis=1)
    else:
        ai_factors = spy.to_frame("SPY")

    basket_resid = _residual_multi(basket, ai_factors, cfg.min_obs)
    if basket_resid.empty:
        raise ValueError("could not residualize the basket")

    rows = []
    for t in rets.columns:
        if t in ("SPY", cfg.sector_etf):
            continue
        col = rets[t]
        if col.dropna().shape[0] < cfg.min_obs:
            continue
        ai = _corr(_residual_multi(col, ai_factors, cfg.min_obs), basket_resid, cfg.min_obs)
        if ai is None:
            continue
        rows.append({
            "ticker": t,
            "exposure": round(max(0.0, ai), 4),
            "in_seed": t in seed_present,
            "avg_dollar_vol": round(float(liq.get(t, 0.0)), 2),
        })
    return pd.DataFrame(rows).sort_values("exposure", ascending=False).reset_index(drop=True)


async def load_panel(engine, cfg: ThemeConfig):
    """Read daily_prices (read-only) into a price panel + liquidity + equity set."""
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT ticker, date, adjusted_close, volume FROM daily_prices "
            "WHERE date >= (CURRENT_DATE - make_interval(days => :w)) "
            "AND adjusted_close IS NOT NULL AND adjusted_close > 0"
        ), {"w": cfg.window_days})).fetchall()
        fund_rows = (await conn.execute(text(
            "SELECT DISTINCT ticker FROM fundamentals WHERE source != 'no_data'"
        ))).fetchall()

    if not rows:
        raise ValueError("no price data")
    df = pd.DataFrame(rows, columns=["ticker", "date", "adjusted_close", "volume"])
    df["adjusted_close"] = df["adjusted_close"].astype(float)
    df["volume"] = df["volume"].fillna(0).astype(float)
    df["dollar_vol"] = df["adjusted_close"] * df["volume"]
    liq = df.groupby("ticker")["dollar_vol"].mean()
    equities = {r[0] for r in fund_rows}
    liquid = ((set(liq[liq >= cfg.min_avg_dollar_vol].index) & equities)
              | set(cfg.seed) | {"SPY", cfg.sector_etf})
    panel = df[df["ticker"].isin(liquid)].pivot_table(
        index="date", columns="ticker", values="adjusted_close").sort_index()
    as_of = df["date"].max()
    return panel, equities, liq, as_of


async def run_and_store(engine, cfg: ThemeConfig) -> dict:
    """Compute exposures and replace the theme's snapshot for as_of_date. Returns a
    summary dict. Writes ONLY theme_exposures."""
    panel, equities, liq, as_of = await load_panel(engine, cfg)
    res = score_exposures(panel, equities, liq, cfg)
    as_of_d = as_of if isinstance(as_of, date) else pd.to_datetime(as_of).date()

    records = [
        {"theme": cfg.theme, "ticker": r["ticker"], "exposure": float(r["exposure"]),
         "in_seed": bool(r["in_seed"]), "avg_dollar_vol": float(r["avg_dollar_vol"]),
         "as_of_date": as_of_d}
        for _, r in res.iterrows()
    ]
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM theme_exposures WHERE theme = :t AND as_of_date = :d"),
            {"t": cfg.theme, "d": as_of_d},
        )
        if records:
            await conn.execute(text(
                "INSERT INTO theme_exposures "
                "(theme, ticker, exposure, in_seed, avg_dollar_vol, as_of_date) "
                "VALUES (:theme, :ticker, :exposure, :in_seed, :avg_dollar_vol, :as_of_date)"
            ), records)
    return {"theme": cfg.theme, "as_of_date": str(as_of_d), "scored": len(records),
            "seed": len([r for r in records if r["in_seed"]])}
