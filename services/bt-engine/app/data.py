"""bt-engine DB loaders — the only DB-touching code besides main.py's run rows.

Reads the bt_* tables bt-data populated (Sharadar SEP prices, SF1 point-in-time
fundamentals, universe snapshots) into the frames sim.run_simulation expects.
All point-in-time slicing happens INSIDE the sim per day; these loaders just
bound the fetch window (prices back to start − FACTOR_LOOKBACK_DAYS, fundamentals
with as_of_date ≤ end) so nothing after `end` ever enters the process.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import text

from app.sim import FACTOR_LOOKBACK_DAYS


async def load_universe(engine, limit: int | None = None) -> tuple[list[str], dict[str, str]]:
    """Tickers + sector map from the LATEST bt_universe snapshot. `limit` keeps
    smoke runs small: top-N by latest dollar volume (deterministic order)."""
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT ticker, sector FROM bt_universe "
            "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM bt_universe) "
            "ORDER BY ticker"
        ))).fetchall()
        tickers = [r[0] for r in rows]
        sector_map = {r[0]: r[1] for r in rows if r[1]}
        if limit and len(tickers) > limit:
            dv = (await conn.execute(text(
                "SELECT ticker FROM ("
                "  SELECT ticker, AVG(close * volume) AS adv FROM bt_prices "
                "  WHERE date > (SELECT MAX(date) FROM bt_prices) - INTERVAL '30 days' "
                "  GROUP BY ticker) x ORDER BY adv DESC NULLS LAST LIMIT :n"
            ), {"n": limit})).fetchall()
            keep = {r[0] for r in dv}
            tickers = [t for t in tickers if t in keep]
    if "SPY" not in tickers:
        tickers.append("SPY")
    return tickers, sector_map


async def load_prices(engine, tickers: list[str], start: date, end: date) -> pd.DataFrame:
    px_from = start - timedelta(days=FACTOR_LOOKBACK_DAYS)
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT ticker, date, open, close, adjusted_close, volume FROM bt_prices "
            "WHERE ticker = ANY(:tk) AND date BETWEEN :f AND :t ORDER BY ticker, date"
        ), {"tk": tickers, "f": px_from, "t": end})).fetchall()
    return pd.DataFrame([{
        "ticker": r.ticker, "date": r.date,
        "open": float(r.open) if r.open is not None else None,
        "close": float(r.close) if r.close is not None else None,
        "adjusted_close": float(r.adjusted_close) if r.adjusted_close is not None else None,
        "volume": float(r.volume) if r.volume is not None else None,
    } for r in rows])


async def load_fundamentals(engine, tickers: list[str], end: date) -> pd.DataFrame:
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity, "
            "       revenue_growth, eps_growth FROM bt_fundamentals "
            "WHERE ticker = ANY(:tk) AND as_of_date <= :t ORDER BY ticker, as_of_date"
        ), {"tk": tickers, "t": end})).fetchall()
    return pd.DataFrame([{
        "ticker": r.ticker, "as_of_date": r.as_of_date,
        "pe_ratio": _f(r.pe_ratio), "pb_ratio": _f(r.pb_ratio), "roe": _f(r.roe),
        "debt_to_equity": _f(r.debt_to_equity),
        "revenue_growth": _f(r.revenue_growth), "eps_growth": _f(r.eps_growth),
    } for r in rows])


def _f(v):
    return float(v) if v is not None else None
