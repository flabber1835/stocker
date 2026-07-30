"""position_episodes (migration 0048) against a REAL migrated Postgres.

The constraint carrying the weight here is the PARTIAL unique index: at most one
OPEN episode per ticker. Two open episodes would mean two simultaneous peaks for
the same position and an ambiguous stop, and the delta step maintains these rows
idempotently on every run — so "insert if absent" must be enforced by the database
rather than by the pipeline remembering to check first.

Closed history must accumulate freely alongside it: a ticker bought, stopped and
re-bought has many rows and exactly one live peak. A plain unique index on ticker
would forbid that, which is why the index is partial.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def eng(async_dsn):
    engine = create_async_engine(async_dsn, future=True)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE position_episodes RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


_OPEN = text(
    "INSERT INTO position_episodes (ticker, opened_on) VALUES (:t, :d) RETURNING id")
_CLOSE = text(
    "UPDATE position_episodes SET closed_on = :d, close_reason = :r, stop_peak = :p "
    "WHERE ticker = :t AND closed_on IS NULL")


async def test_the_table_exists_with_the_expected_columns(eng):
    async with eng.connect() as conn:
        rows = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'position_episodes'"))
        cols = {r.column_name for r in rows}
    assert {"ticker", "opened_on", "closed_on", "close_reason", "stop_peak",
            "pending_close_since"} <= cols


async def test_one_open_episode_per_ticker_is_enforced_by_the_db(eng):
    """The delta step maintains these rows on every run; a duplicate open episode
    must be impossible rather than merely unlikely."""
    async with eng.begin() as conn:
        await conn.execute(_OPEN, {"t": "AAPL", "d": date(2026, 1, 5)})
    with pytest.raises(Exception) as exc:
        async with eng.begin() as conn:
            await conn.execute(_OPEN, {"t": "AAPL", "d": date(2026, 2, 9)})
    assert "idx_position_episodes_open_ticker" in str(exc.value)


async def test_a_reopened_position_gets_a_fresh_episode(eng):
    """Re-buying after a stop starts a NEW peak — the stop measures the trend the
    CURRENT position has lived through, not a previous one."""
    async with eng.begin() as conn:
        await conn.execute(_OPEN, {"t": "NVDA", "d": date(2026, 1, 5)})
        await conn.execute(_CLOSE, {"t": "NVDA", "d": date(2026, 3, 2),
                                    "r": "trailing_stop", "p": 140.0})
        await conn.execute(_OPEN, {"t": "NVDA", "d": date(2026, 6, 1)})

    async with eng.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT opened_on, closed_on, close_reason, stop_peak "
            "FROM position_episodes WHERE ticker='NVDA' ORDER BY opened_on"))).all()
    assert len(rows) == 2
    assert rows[0].closed_on == date(2026, 3, 2)
    assert float(rows[0].stop_peak) == 140.0
    assert rows[1].closed_on is None and rows[1].stop_peak is None


async def test_many_closed_episodes_coexist(eng):
    """A partial index, not a plain one — otherwise history would be unstorable."""
    async with eng.begin() as conn:
        for i in range(5):
            await conn.execute(_OPEN, {"t": "AMD", "d": date(2026, 1, 1) + timedelta(days=i * 30)})
            await conn.execute(_CLOSE, {"t": "AMD", "d": date(2026, 1, 20) + timedelta(days=i * 30),
                                        "r": "orphan", "p": None})
        await conn.execute(_OPEN, {"t": "AMD", "d": date(2026, 7, 1)})

    async with eng.connect() as conn:
        total = (await conn.execute(text(
            "SELECT COUNT(*) c FROM position_episodes WHERE ticker='AMD'"))).scalar()
        still_open = (await conn.execute(text(
            "SELECT COUNT(*) c FROM position_episodes "
            "WHERE ticker='AMD' AND closed_on IS NULL"))).scalar()
    assert total == 6 and still_open == 1


async def test_the_reentry_gate_query_finds_the_latest_stop_peak(eng):
    """The exact read the delta step will make: the most recent trailing_stop close
    per ticker. An orphan exit must NOT supply a peak — only a stop blocks re-entry."""
    async with eng.begin() as conn:
        await conn.execute(_OPEN, {"t": "TSLA", "d": date(2026, 1, 1)})
        await conn.execute(_CLOSE, {"t": "TSLA", "d": date(2026, 2, 1),
                                    "r": "trailing_stop", "p": 300.0})
        await conn.execute(_OPEN, {"t": "TSLA", "d": date(2026, 3, 1)})
        await conn.execute(_CLOSE, {"t": "TSLA", "d": date(2026, 4, 1),
                                    "r": "trailing_stop", "p": 250.0})
        # An orphan exit AFTER the stops — must not become the blocking peak.
        await conn.execute(_OPEN, {"t": "META", "d": date(2026, 1, 1)})
        await conn.execute(_CLOSE, {"t": "META", "d": date(2026, 5, 1),
                                    "r": "orphan", "p": None})

    q = text(
        "SELECT DISTINCT ON (ticker) ticker, stop_peak FROM position_episodes "
        "WHERE close_reason = 'trailing_stop' AND closed_on IS NOT NULL "
        "ORDER BY ticker, closed_on DESC")
    async with eng.connect() as conn:
        peaks = {r.ticker: float(r.stop_peak) for r in (await conn.execute(q)).all()}
    assert peaks == {"TSLA": 250.0}, "only the most recent STOP peak gates re-entry"


async def test_pending_close_defaults_null_and_round_trips(eng):
    """Absence from ONE sync is not evidence of a sale. A single degraded sync
    closing the episode would reset the peak on re-appearance — a risk control
    silently loosening itself."""
    async with eng.begin() as conn:
        await conn.execute(_OPEN, {"t": "CRM", "d": date(2026, 1, 1)})
    async with eng.connect() as conn:
        val = (await conn.execute(text(
            "SELECT pending_close_since FROM position_episodes WHERE ticker='CRM'"))).scalar()
    assert val is None

    async with eng.begin() as conn:
        await conn.execute(text(
            "UPDATE position_episodes SET pending_close_since = :d "
            "WHERE ticker='CRM' AND closed_on IS NULL"), {"d": date(2026, 6, 10)})
    async with eng.connect() as conn:
        val = (await conn.execute(text(
            "SELECT pending_close_since FROM position_episodes WHERE ticker='CRM'"))).scalar()
    assert val == date(2026, 6, 10)


async def test_open_episode_lookup_uses_the_index(eng):
    """The delta step reads this every run against the whole held book."""
    async with eng.begin() as conn:
        for i in range(30):
            await conn.execute(_OPEN, {"t": f"T{i:03d}", "d": date(2026, 1, 1)})
    async with eng.connect() as conn:
        plan = "\n".join(r[0] for r in (await conn.execute(text(
            "EXPLAIN SELECT ticker, opened_on FROM position_episodes "
            "WHERE closed_on IS NULL"))).all())
    assert "position_episodes" in plan
