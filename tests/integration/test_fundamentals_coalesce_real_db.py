"""Audit P1 — _upsert_fundamentals must COALESCE: a degraded re-fetch (NULL fields)
must NOT blank previously-good values. Verified against real Postgres SQL semantics.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Load av-ingestor's app.main (evict any other service's `app` first).
for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_AV = os.path.join(_ROOT, "services", "av-ingestor")
if _AV not in sys.path:
    sys.path.insert(0, _AV)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x/y")  # import guard only

import app.main as ing  # noqa: E402

pytestmark = pytest.mark.asyncio

_FULL = {"pe_ratio": 15.0, "pb_ratio": 2.0, "roe": 0.20, "debt_to_equity": 0.5,
         "revenue_growth": 0.10, "eps_growth": 0.12, "market_cap": 1.0e9,
         "avg_volume": 1.0e6}


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        await conn.execute(text("DELETE FROM fundamentals WHERE ticker='AAA'"))
    yield eng
    async with eng.begin() as conn:
        await conn.execute(text("DELETE FROM fundamentals WHERE ticker='AAA'"))
    await eng.dispose()


async def _read(engine, today):
    async with engine.connect() as conn:
        return (await conn.execute(text(
            "SELECT pe_ratio, roe, market_cap, avg_volume FROM fundamentals "
            "WHERE ticker='AAA' AND as_of_date=:d"), {"d": today})).mappings().first()


async def test_degraded_refetch_preserves_good_values(engine):
    today = dt.date(2026, 6, 22)
    async with engine.begin() as conn:
        await ing._upsert_fundamentals(conn, "AAA", dict(_FULL), today)
    # A same-day degraded OVERVIEW returns all-NULL fields.
    async with engine.begin() as conn:
        await ing._upsert_fundamentals(conn, "AAA", {k: None for k in _FULL}, today)
    row = await _read(engine, today)
    assert float(row["pe_ratio"]) == 15.0     # preserved, not blanked
    assert float(row["roe"]) == 0.20
    assert float(row["market_cap"]) == 1.0e9


async def test_partial_refetch_updates_present_preserves_missing(engine):
    today = dt.date(2026, 6, 22)
    async with engine.begin() as conn:
        await ing._upsert_fundamentals(conn, "AAA", dict(_FULL), today)
    # New fetch has a fresh pe_ratio but NULL roe → pe updates, roe preserved.
    partial = {k: None for k in _FULL}
    partial["pe_ratio"] = 18.0
    async with engine.begin() as conn:
        await ing._upsert_fundamentals(conn, "AAA", partial, today)
    row = await _read(engine, today)
    assert float(row["pe_ratio"]) == 18.0     # updated
    assert float(row["roe"]) == 0.20          # preserved
