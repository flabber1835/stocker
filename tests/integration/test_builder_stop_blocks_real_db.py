"""The builder excludes trailing-stop re-entry blocks — against a real Postgres.

This is the live half of the backfill fix. The first cut had the DELTA step filter
blocked names out of an already-composed target, which removed them and put nothing
in their place: the book shrank below max_positions and the removed weight fell to
cash, turning the stop into a market-timing overlay nobody configured (observed in
the wind tunnel as 35 names drifting to 26 during a drawdown).

Only the builder can backfill, because only the builder knows the next-best
candidate. So the block has to reach it, and it does so as a plain exclusion —
same set, same seam (selection, after clustering) as the vetter's.

The query is the thing worth testing against a real database: it is a two-CTE join
whose correctness depends on DISTINCT ON ordering, and a unit test with a mocked
connection would assert nothing about it.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio

# Verbatim mirror of the query in services/portfolio-builder/app/main.py. Kept in
# sync deliberately, like the other contract tests in this tier — a drift here
# fails in CI rather than silently un-blocking a stopped name in production.
_BLOCKED_SQL = text(
    "WITH last_stop AS ("
    "  SELECT DISTINCT ON (ticker) ticker, stop_peak FROM position_episodes"
    "  WHERE close_reason = 'trailing_stop' AND closed_on IS NOT NULL"
    "    AND stop_peak IS NOT NULL"
    "  ORDER BY ticker, closed_on DESC),"
    "px AS ("
    "  SELECT DISTINCT ON (ticker) ticker, adjusted_close FROM daily_prices"
    "  WHERE ticker IN (SELECT ticker FROM last_stop)"
    "    AND adjusted_close IS NOT NULL"
    "  ORDER BY ticker, date DESC) "
    "SELECT l.ticker FROM last_stop l JOIN px ON px.ticker = l.ticker "
    "WHERE px.adjusted_close <= l.stop_peak")


@pytest_asyncio.fixture
async def eng(async_dsn):
    engine = create_async_engine(async_dsn, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE position_episodes, daily_prices RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


async def _price(conn, ticker: str, px: float, d: date):
    await conn.execute(text(
        "INSERT INTO daily_prices (ticker, date, close, adjusted_close, volume) "
        "VALUES (:t, :d, :p, :p, 1000000)"), {"t": ticker, "d": d, "p": px})


async def _stop(conn, ticker: str, peak: float, closed: date):
    await conn.execute(text(
        "INSERT INTO position_episodes (ticker, opened_on, closed_on, close_reason, "
        "stop_peak) VALUES (:t, :o, :c, 'trailing_stop', :p)"),
        {"t": ticker, "o": closed - timedelta(days=60), "c": closed, "p": peak})


async def test_a_name_below_its_stop_peak_is_blocked(eng):
    today = date(2026, 7, 30)
    async with eng.begin() as conn:
        await _stop(conn, "AAA", 100.0, today - timedelta(days=10))
        await _price(conn, "AAA", 80.0, today)
    async with eng.connect() as conn:
        assert {r.ticker for r in (await conn.execute(_BLOCKED_SQL)).all()} == {"AAA"}


async def test_recovery_above_the_peak_clears_the_block(eng):
    today = date(2026, 7, 30)
    async with eng.begin() as conn:
        await _stop(conn, "AAA", 100.0, today - timedelta(days=10))
        await _price(conn, "AAA", 80.0, today - timedelta(days=1))
        await _price(conn, "AAA", 101.0, today)      # newest print clears it
    async with eng.connect() as conn:
        assert (await conn.execute(_BLOCKED_SQL)).all() == []


async def test_exactly_at_the_peak_is_still_blocked(eng):
    """Inclusive, matching reentry_blocked: recovery means EXCEEDING the peak."""
    today = date(2026, 7, 30)
    async with eng.begin() as conn:
        await _stop(conn, "AAA", 100.0, today - timedelta(days=10))
        await _price(conn, "AAA", 100.0, today)
    async with eng.connect() as conn:
        assert {r.ticker for r in (await conn.execute(_BLOCKED_SQL)).all()} == {"AAA"}


async def test_only_the_most_recent_stop_peak_counts(eng):
    """A name stopped twice is judged against the LATEST peak. If DISTINCT ON
    ordering were wrong, an old higher peak would block a recovered name forever."""
    today = date(2026, 7, 30)
    async with eng.begin() as conn:
        await _stop(conn, "AAA", 200.0, today - timedelta(days=90))   # older, higher
        await _stop(conn, "AAA", 100.0, today - timedelta(days=10))   # newer, lower
        await _price(conn, "AAA", 150.0, today)
    async with eng.connect() as conn:
        assert (await conn.execute(_BLOCKED_SQL)).all() == [], (
            "judged against the stale 200 peak instead of the current 100")


async def test_an_orphan_close_never_blocks(eng):
    """Only a STOP blocks. A name the orphan timer sold must be immediately
    re-buyable when the builder wants it again."""
    today = date(2026, 7, 30)
    async with eng.begin() as conn:
        await conn.execute(text(
            "INSERT INTO position_episodes (ticker, opened_on, closed_on, close_reason) "
            "VALUES ('AAA', :o, :c, 'gone')"),
            {"o": today - timedelta(days=60), "c": today - timedelta(days=10)})
        await _price(conn, "AAA", 10.0, today)
    async with eng.connect() as conn:
        assert (await conn.execute(_BLOCKED_SQL)).all() == []


async def test_an_open_episode_never_blocks(eng):
    """A currently-held name has no closed stop, so nothing blocks it."""
    today = date(2026, 7, 30)
    async with eng.begin() as conn:
        await conn.execute(text(
            "INSERT INTO position_episodes (ticker, opened_on) VALUES ('AAA', :o)"),
            {"o": today - timedelta(days=30)})
        await _price(conn, "AAA", 10.0, today)
    async with eng.connect() as conn:
        assert (await conn.execute(_BLOCKED_SQL)).all() == []


async def test_a_stopped_name_with_no_prices_is_not_blocked(eng):
    """No print means nothing can buy it anyway; inventing a block on missing data
    would strand the name permanently once prices returned."""
    today = date(2026, 7, 30)
    async with eng.begin() as conn:
        await _stop(conn, "GONE", 100.0, today - timedelta(days=10))
    async with eng.connect() as conn:
        assert (await conn.execute(_BLOCKED_SQL)).all() == []
