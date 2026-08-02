"""Migration 0050 — episodes for holdings that predate the trailing stop.

Without it, enabling the stop starts every episode on the activation date, so
`build_stop_states` derives each peak from prices since TODAY. A position already
25% off its real high reads as perfectly flat, cannot trip a 30% stop, and would
have to fall another 30% from here before the rule notices — the names most in
need of the stop are precisely the ones it would ignore.

The tests pin the direction of every judgement call, because all of them fail
safe in one direction and dangerously in the other: an entry date that is too
RECENT costs a late exit, while one that is too OLD invents a peak the position
never lived through and sells on a drawdown that never happened.
"""
from __future__ import annotations

import os
import subprocess
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SQL = open(os.path.join(
    _ROOT, "db", "migrations", "versions",
    "0050_bootstrap_position_episodes.py")).read()


def _bootstrap_sql() -> str:
    """The migration's upgrade() body, run directly — the alembic chain is
    exercised elsewhere; this is about the SQL's semantics."""
    start = _SQL.index('op.execute("""') + len('op.execute("""')
    return _SQL[start:_SQL.index('""")', start)]


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        for t in ("position_episodes", "live_positions", "alpaca_sync_runs",
                  "alpaca_orders"):
            await conn.execute(text(f"DELETE FROM {t}"))
    yield eng
    await eng.dispose()


async def _seed_sync(conn, tickers, when: datetime) -> str:
    rid = str(uuid.uuid4())
    await conn.execute(text(
        "INSERT INTO alpaca_sync_runs (run_id, status, completed_at) "
        "VALUES (CAST(:r AS uuid), 'success', :w)"), {"r": rid, "w": when})
    for t in tickers:
        await conn.execute(text(
            "INSERT INTO live_positions (sync_run_id, ticker, qty) "
            "VALUES (CAST(:r AS uuid), :t, 10)"), {"r": rid, "t": t})
    return rid


async def _seed_fill(conn, ticker, when: datetime):
    await conn.execute(text(
        "INSERT INTO alpaca_orders (ticker, action, side, status, filled_at, "
        " created_at) VALUES (:t, 'entry', 'buy', 'filled', :w, :w)"),
        {"t": ticker, "w": when})


async def test_the_fill_date_wins_over_first_sighting(engine):
    """The fill is the real event; live_positions only records that we already
    held it. Preferring the sighting would date every legacy holding to whenever
    broker syncing happened to start."""
    now = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        await _seed_fill(conn, "AAA", now - timedelta(days=200))
        await _seed_sync(conn, ["AAA"], now - timedelta(days=90))
        await _seed_sync(conn, ["AAA"], now)
        await conn.execute(text(_bootstrap_sql()))
        row = (await conn.execute(text(
            "SELECT opened_on FROM position_episodes WHERE ticker='AAA'"))).first()
    assert row.opened_on == (now - timedelta(days=200)).date()


async def test_it_falls_back_to_first_sighting_without_a_fill(engine):
    """Positions can reach the broker by routes alpaca_orders never saw."""
    now = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        await _seed_sync(conn, ["BBB"], now - timedelta(days=120))
        await _seed_sync(conn, ["BBB"], now)
        await conn.execute(text(_bootstrap_sql()))
        row = (await conn.execute(text(
            "SELECT opened_on FROM position_episodes WHERE ticker='BBB'"))).first()
    assert row.opened_on == (now - timedelta(days=120)).date()


async def test_only_CURRENTLY_held_names_get_episodes(engine):
    """Scoped to the latest sync. A name sold months ago must not acquire an open
    episode — the partial unique index would then block a genuine re-entry."""
    now = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        await _seed_sync(conn, ["OLD", "KEPT"], now - timedelta(days=60))
        await _seed_sync(conn, ["KEPT"], now)
        await conn.execute(text(_bootstrap_sql()))
        got = {r.ticker for r in (await conn.execute(text(
            "SELECT ticker FROM position_episodes"))).fetchall()}
    assert got == {"KEPT"}


async def test_the_latest_sync_is_chosen_by_TIME_not_by_uuid(engine):
    """run_id is a UUID and does not order by recency. MAX(sync_run_id) would pick
    an arbitrary past sync and could resurrect a name that has since been sold."""
    now = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        for _ in range(6):      # enough draws that a uuid-max would likely differ
            await _seed_sync(conn, ["GONE"], now - timedelta(days=30))
        await _seed_sync(conn, ["NOW"], now)
        await conn.execute(text(_bootstrap_sql()))
        got = {r.ticker for r in (await conn.execute(text(
            "SELECT ticker FROM position_episodes"))).fetchall()}
    assert got == {"NOW"}


async def test_an_existing_open_episode_is_left_alone(engine):
    """Idempotent, and it must never overwrite a real episode with a
    reconstructed one — the real one carries the peak the position actually
    lived through."""
    now = datetime.now(timezone.utc)
    kept = date(2020, 1, 6)
    async with engine.begin() as conn:
        await _seed_sync(conn, ["CCC"], now)
        await _seed_fill(conn, "CCC", now - timedelta(days=10))
        await conn.execute(text(
            "INSERT INTO position_episodes (ticker, opened_on) VALUES ('CCC', :d)"),
            {"d": kept})
        await conn.execute(text(_bootstrap_sql()))
        await conn.execute(text(_bootstrap_sql()))    # twice: idempotent
        rows = (await conn.execute(text(
            "SELECT opened_on FROM position_episodes WHERE ticker='CCC'"))).fetchall()
    assert len(rows) == 1 and rows[0].opened_on == kept


async def test_no_evidence_means_no_episode(engine):
    """The safe direction. A fabricated entry date invents a peak the position
    never lived through; the normal sync will open one at today's date instead,
    which merely arms the stop late."""
    async with engine.begin() as conn:
        # held per live_positions but the sync row has no completed_at
        rid = str(uuid.uuid4())
        await conn.execute(text(
            "INSERT INTO alpaca_sync_runs (run_id, status) "
            "VALUES (CAST(:r AS uuid), 'running')"), {"r": rid})
        await conn.execute(text(
            "INSERT INTO live_positions (sync_run_id, ticker, qty) "
            "VALUES (CAST(:r AS uuid), 'DDD', 5)"), {"r": rid})
        await conn.execute(text(_bootstrap_sql()))
        n = (await conn.execute(text(
            "SELECT COUNT(*) FROM position_episodes"))).scalar_one()
    assert n == 0
