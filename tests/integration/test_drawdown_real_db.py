"""Falling-knife drawdown signal — end-to-end against a REAL migrated Postgres.

Why this tier (not a mock): the per-service unit tests feed Python lists straight
into the math. They never exercise the actual `daily_prices` query (the
ROW_NUMBER() window, `ticker = ANY(:tickers)`, the NUMERIC `adjusted_close`
column, Decimal round-tripping). A schema/column/type drift there ships green and
only breaks in production — exactly the class of bug this repo has hit before. So
here we seed real rows, run the EXACT SQL the pipeline runs, and feed the result
through the shared drawdown math — proving the round-trip fix works on real data
end to end, including the veto outcome flipping for the ENPH case.

Seeds three tickers over 130 aligned sessions:
  - SPY      : low-drift benchmark (so beta is defined, net move ≈ 0)
  - ENPH     : real 47→72→48 round-trip in the last 21 sessions (the false knife)
  - COLLAPSE : a genuine one-way -30% decline in the last 21 (a true knife)
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from stock_strategy_shared.drawdown import (
    recent_drawdown,
    excess_drawdown,
    scaled_excess_threshold,
)

pytestmark = pytest.mark.asyncio

# Real ENPH 2026-05-19→06-17 adjusted closes (21 sessions): 47 → 72 → 48.
ENPH_21 = [46.76, 53.15, 62.34, 64.03, 66.90, 70.28, 69.50, 68.36, 63.74, 72.33,
           69.02, 68.30, 56.07, 56.88, 53.51, 50.57, 54.93, 54.59, 52.40, 50.26, 47.78]

WINDOW = 21
LOOKBACK = 120                      # pipeline BETA_LOOKBACK_DAYS / DRAWDOWN_BETA_LOOKBACK
BASELINE = 3                        # DRAWDOWN_BASELINE_WINDOW default
N = 130                             # >= LOOKBACK + 1 so the excess/beta path has history

# Same default vol-scaled excess limit env the pipeline + vetter use.
EXCESS_BASE, VOL_ANCHOR, EXCESS_LO, EXCESS_HI = 0.15, 0.35, 0.10, 0.30


def _series():
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(N)]
    spy = [580.0 + (0.5 if i % 2 else 0.0) for i in range(N)]          # low-drift
    enph = [46.76] * (N - WINDOW) + ENPH_21                            # round-trip tail
    collapse = [100.0] * (N - WINDOW) + [round(100 - 1.5 * i, 2) for i in range(WINDOW)]
    return dates, {"SPY": spy, "ENPH": enph, "COLLAPSE": collapse}


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    dates, prices = _series()
    async with eng.begin() as conn:
        await conn.execute(text("TRUNCATE daily_prices RESTART IDENTITY"))
        rows = [
            {"t": t, "d": d, "ac": px[i]}
            for t, px in prices.items()
            for i, d in enumerate(dates)
        ]
        await conn.execute(text(
            "INSERT INTO daily_prices (ticker, date, adjusted_close, close, source) "
            "VALUES (:t, :d, :ac, :ac, 'test')"
        ), rows)
    yield eng
    await eng.dispose()


async def _fetch_window_closes(eng, tickers, w):
    """The EXACT pipeline drawdown query → {ticker: [closes oldest→newest]}."""
    async with eng.connect() as conn:
        res = await conn.execute(text(
            "SELECT ticker, adjusted_close FROM ("
            "  SELECT ticker, adjusted_close, date, "
            "         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn "
            "  FROM daily_prices WHERE ticker = ANY(:tickers)"
            ") s WHERE rn <= :w ORDER BY ticker, date ASC"
        ), {"tickers": tickers, "w": w})
        out: dict[str, list[float]] = {}
        for r in res.fetchall():
            out.setdefault(r.ticker, []).append(float(r.adjusted_close))
        return out


class TestRawDrawdownThroughRealDB:
    async def test_enph_roundtrip_suppressed_collapse_kept(self, engine):
        closes = await _fetch_window_closes(engine, ["ENPH", "COLLAPSE"], WINDOW)

        # ENPH: naive peak-to-now is a scary -34% (would trip the 25% floor)...
        raw = recent_drawdown(closes["ENPH"], window=WINDOW, baseline_window=0)
        assert raw <= -0.33
        # ...but it round-tripped → effective ~-12%, NO floor trip.
        eff = recent_drawdown(closes["ENPH"], window=WINDOW, baseline_window=BASELINE)
        assert -0.13 < eff < -0.10
        assert eff > -0.25

        # COLLAPSE: a real one-way decline is essentially unchanged → still fires.
        col = recent_drawdown(closes["COLLAPSE"], window=WINDOW, baseline_window=BASELINE)
        assert col <= -0.25


class TestExcessVetoOutcomeThroughRealDB:
    async def test_enph_veto_flips_off_collapse_stays_on(self, engine):
        # Pull the same rows the pipeline's excess/beta path pulls (lookback+1).
        async with engine.connect() as conn:
            res = await conn.execute(text(
                "SELECT ticker, date, adjusted_close FROM ("
                "  SELECT ticker, date, adjusted_close, "
                "         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn "
                "  FROM daily_prices WHERE ticker = ANY(:tickers)"
                ") s WHERE rn <= :w ORDER BY ticker, date ASC"
            ), {"tickers": ["ENPH", "COLLAPSE"], "w": LOOKBACK + 1})
            by_t: dict[str, dict] = {}
            for r in res.fetchall():
                by_t.setdefault(r.ticker, {})[r.date] = float(r.adjusted_close)
            spy_res = await conn.execute(text(
                "SELECT date, adjusted_close FROM ("
                "  SELECT date, adjusted_close, "
                "         ROW_NUMBER() OVER (ORDER BY date DESC) AS rn "
                "  FROM daily_prices WHERE ticker = 'SPY'"
                ") s WHERE rn <= :w ORDER BY date ASC"
            ), {"w": LOOKBACK + 1})
            spy = {r.date: float(r.adjusted_close) for r in spy_res.fetchall()}

        def veto(ticker: str, baseline: int) -> bool:
            dmap = by_t[ticker]
            common = sorted(d for d in dmap if d in spy)
            stock = [dmap[d] for d in common]
            mkt = [spy[d] for d in common]
            detail = excess_drawdown(stock, mkt, window=WINDOW, beta_lookback=LOOKBACK,
                                     baseline_window=baseline)
            limit = scaled_excess_threshold(detail["idio_vol"], base=EXCESS_BASE,
                                            anchor=VOL_ANCHOR, lo=EXCESS_LO, hi=EXCESS_HI)
            return detail["excess_dd"] is not None and detail["excess_dd"] <= -limit

        # ENPH: the round-trip fix turns a false excess veto OFF.
        assert veto("ENPH", baseline=0) is True       # legacy peak-to-now → vetoed
        assert veto("ENPH", baseline=BASELINE) is False  # round-trip aware → kept

        # COLLAPSE: a genuine decline is still vetoed under the new logic.
        assert veto("COLLAPSE", baseline=BASELINE) is True
