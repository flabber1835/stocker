"""FIX I — idx_alpaca_orders_intent_open predicate must use the DB token
'partial_fill', NOT the broker spelling 'partially_filled' (migration 0026).

Migration 0023's predicate used 'partially_filled', which alpaca-sync never
persists, so a partially-filled order was not covered by the dedup unique index.
0026 recreates the index with the correct 'partial_fill' token. This test inspects
the migrated index definition on a real Postgres.
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


async def test_intent_open_index_uses_partial_fill_token(engine):
    async with engine.connect() as conn:
        indexdef = (await conn.execute(text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE indexname = 'idx_alpaca_orders_intent_open'"
        ))).scalar()
    assert indexdef is not None, "idx_alpaca_orders_intent_open missing after migrations"
    low = indexdef.lower()
    # The corrected DB token must be present...
    assert "partial_fill" in low
    # ...and the broker spelling must NOT appear (it was the bug). Guard against a
    # substring false-positive: 'partial_fill' is not a substring of
    # 'partially_filled', so this is a clean check.
    assert "partially_filled" not in low
