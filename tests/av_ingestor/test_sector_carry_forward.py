"""Sector CARRY-FORWARD on universe snapshot save (ephemeral Postgres).

AV LISTING_STATUS carries no sector, so every fresh snapshot inserts
sector=NULL for all rows; sector only arrives later via the OVERVIEW
fundamentals trickle. Before the fix, the first weekly universe refresh
created an all-NULL-sector snapshot that blinded every "newest snapshot"
sector reader at once (builder max_sector_weight cap, pipeline sector
neutralization, dashboards, evaluator packet — the W29 inert-sector-cap
finding). save_universe_snapshot must inherit the latest known non-null
sector per ticker from prior snapshots.
"""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.integration.conftest import _EphemeralPostgres, _alembic_upgrade  # noqa: E402


@pytest.fixture(scope="module")
def make_engine():
    try:
        pg = _EphemeralPostgres()
        pg.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"could not start ephemeral Postgres: {exc}")
    try:
        try:
            _alembic_upgrade(pg.sync_dsn)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"alembic upgrade unavailable: {exc}")
        from sqlalchemy.pool import NullPool
        from sqlalchemy.ext.asyncio import create_async_engine

        def _mk():
            # NullPool: each asyncio.run() uses its own event loop; pooled
            # asyncpg connections are loop-bound and would break across tests.
            return create_async_engine(pg.async_dsn, poolclass=NullPool)

        yield _mk
    finally:
        pg.stop()


async def _with_engine(make_engine, fn):
    engine = make_engine()
    try:
        return await fn(engine)
    finally:
        await engine.dispose()


def _save(make_engine, tickers):
    from app.universe import save_universe_snapshot

    async def _inner(engine):
        async with engine.begin() as conn:
            return await save_universe_snapshot(conn, "AV_LISTING", tickers)
    return asyncio.run(_with_engine(make_engine, _inner))


def _sectors_of(make_engine, snapshot_id):
    from sqlalchemy import text

    async def _inner(engine):
        async with engine.connect() as conn:
            rows = await conn.execute(text(
                "SELECT ticker, sector FROM universe_tickers "
                "WHERE snapshot_id = :sid ORDER BY ticker"), {"sid": snapshot_id})
            return {r.ticker: r.sector for r in rows.fetchall()}
    return asyncio.run(_with_engine(make_engine, _inner))


def test_fresh_snapshot_inherits_latest_nonnull_sector(make_engine):
    from sqlalchemy import text

    # Snapshot 1: the LISTING_STATUS shape — sector always None.
    sid1 = _save(make_engine, [
        {"ticker": "AAA", "name": "Alpha", "sector": None, "asset_class": "Equity"},
        {"ticker": "BBB", "name": "Beta", "sector": None, "asset_class": "Equity"},
        {"ticker": "CCC", "name": "Gamma", "sector": None, "asset_class": "Equity"},
    ])
    assert set(_sectors_of(make_engine, sid1).values()) == {None}

    # OVERVIEW trickle labels AAA and BBB (the production UPDATE is unscoped
    # by snapshot — replicate its effect directly).
    async def _label(engine):
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE universe_tickers SET sector = :s WHERE ticker = :t"),
                [{"t": "AAA", "s": "ENERGY"}, {"t": "BBB", "s": "TECHNOLOGY"}])
    asyncio.run(_with_engine(make_engine, _label))

    # Snapshot 2: the weekly refresh — all-NULL again from LISTING_STATUS,
    # plus a new IPO DDD with no history. Pre-fix: AAA/BBB reset to NULL.
    sid2 = _save(make_engine, [
        {"ticker": "AAA", "name": "Alpha", "sector": None, "asset_class": "Equity"},
        {"ticker": "BBB", "name": "Beta", "sector": None, "asset_class": "Equity"},
        {"ticker": "DDD", "name": "Delta", "sector": None, "asset_class": "Equity"},
    ])
    got = _sectors_of(make_engine, sid2)
    assert got == {"AAA": "ENERGY", "BBB": "TECHNOLOGY", "DDD": None}

    # A ticker whose sector was already non-null at insert (mock universe path)
    # must NOT be overwritten by an older label.
    sid3 = _save(make_engine, [
        {"ticker": "AAA", "name": "Alpha", "sector": "UTILITIES", "asset_class": "Equity"},
    ])
    assert _sectors_of(make_engine, sid3) == {"AAA": "UTILITIES"}
