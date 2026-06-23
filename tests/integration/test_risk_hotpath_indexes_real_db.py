"""Audit P0 — migration 0027 creates the risk-service hot-path indexes.

These back the freshness MAX(completed_at) WHERE status='success' probe and the
projected-positions/turnover status/action filters. Without them the queries scan,
lengthening connection hold time and starving the pool under concurrent /check.
Verified on a real, fully-migrated Postgres.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    yield eng
    await eng.dispose()


async def _indexes_on(conn, table):
    rows = (await conn.execute(text(
        "SELECT indexname FROM pg_indexes WHERE tablename = :t"
    ), {"t": table})).scalars().all()
    return set(rows)


async def test_sync_runs_status_completed_index_exists(engine):
    async with engine.connect() as conn:
        idx = await _indexes_on(conn, "alpaca_sync_runs")
    assert "idx_alpaca_sync_runs_status_completed" in idx, idx


async def test_alpaca_orders_status_indexes_exist(engine):
    async with engine.connect() as conn:
        idx = await _indexes_on(conn, "alpaca_orders")
    assert "idx_alpaca_orders_status" in idx, idx
    assert "idx_alpaca_orders_action_status" in idx, idx


async def test_status_completed_index_definition(engine):
    """The freshness index must cover (status, completed_at) so MAX(completed_at)
    WHERE status='success' is an index probe, not a scan."""
    async with engine.connect() as conn:
        indexdef = (await conn.execute(text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE indexname = 'idx_alpaca_sync_runs_status_completed'"
        ))).scalar()
    assert indexdef is not None
    low = indexdef.lower()
    assert "status" in low and "completed_at" in low
