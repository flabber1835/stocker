"""The bt corpus advisory lock is cross-connection, not process-local."""
from __future__ import annotations

import asyncio
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app import main as bt_main
from app.main import CORPUS_LOCK_KEY
from tests.support.postgres import _EphemeralPostgres


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


def test_writer_exclusive_and_reader_shared_cannot_overlap(pg):
    async def run() -> None:
        engine = create_async_engine(pg.async_dsn)
        writer = await engine.connect()
        competing_writer = await engine.connect()
        reader = await engine.connect()
        try:
            assert (await writer.execute(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": CORPUS_LOCK_KEY})).scalar_one() is True
            await writer.commit()

            assert (await competing_writer.execute(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": CORPUS_LOCK_KEY})).scalar_one() is False
            await competing_writer.rollback()

            # Transaction-level shared acquisition must fail while the separate
            # writer session holds its exclusive lock.
            assert (await reader.execute(
                text("SELECT pg_try_advisory_xact_lock_shared(:key)"),
                {"key": CORPUS_LOCK_KEY})).scalar_one() is False
            await reader.rollback()

            await writer.execute(text("SELECT pg_advisory_unlock(:key)"),
                                 {"key": CORPUS_LOCK_KEY})
            await writer.commit()
            assert (await reader.execute(
                text("SELECT pg_try_advisory_xact_lock_shared(:key)"),
                {"key": CORPUS_LOCK_KEY})).scalar_one() is True
            await reader.rollback()
        finally:
            await writer.close()
            await competing_writer.close()
            await reader.close()
            await engine.dispose()

    asyncio.run(run())


def test_two_price_and_filing_vintages_preserve_pit_truth(pg, monkeypatch):
    async def run() -> None:
        engine = create_async_engine(pg.async_dsn)
        monkeypatch.setattr(bt_main, "engine", engine)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("""
                    CREATE TABLE bt_prices (
                        ticker TEXT NOT NULL, date DATE NOT NULL,
                        open NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC,
                        adjusted_close NUMERIC, close_unadjusted NUMERIC,
                        volume NUMERIC, PRIMARY KEY (ticker, date))
                """))
                await conn.execute(text("""
                    CREATE TABLE bt_earnings (
                        ticker TEXT NOT NULL,
                        fiscal_date_ending DATE NOT NULL,
                        reported_date DATE NOT NULL,
                        reported_eps NUMERIC,
                        PRIMARY KEY (ticker, fiscal_date_ending, reported_date))
                """))

            first = {
                "ticker": "AAA", "date": "2025-01-02", "open": 10,
                "high": 11, "low": 9, "close": 10.5,
                "adjusted_close": 10.25, "close_unadjusted": 10.5,
                "volume": 100,
            }
            revised = {
                "ticker": "AAA", "date": "2025-01-02", "open": 20,
                "high": 22, "low": 18, "close": 21,
                "adjusted_close": 20.5, "close_unadjusted": 21,
                "volume": 200,
            }
            await bt_main._upsert_prices([first])
            await bt_main._upsert_prices([revised])

            original_filing = {
                "ticker": "AAA", "fiscal_date_ending": "2024-12-31",
                "reported_date": "2025-01-15", "reported_eps": 1,
            }
            later_revision = {
                "ticker": "AAA", "fiscal_date_ending": "2024-12-31",
                "reported_date": "2025-02-15", "reported_eps": 2,
            }
            await bt_main._upsert_bt_earnings([original_filing])
            await bt_main._upsert_bt_earnings([later_revision])

            async with engine.connect() as conn:
                price = (await conn.execute(text(
                    "SELECT open, high, low, close, adjusted_close, "
                    "close_unadjusted, volume FROM bt_prices "
                    "WHERE ticker='AAA'"))).one()
                assert tuple(map(float, price)) == (
                    20, 22, 18, 21, 20.5, 21, 200)

                count = (await conn.execute(text(
                    "SELECT COUNT(*) FROM bt_earnings WHERE ticker='AAA'"
                ))).scalar_one()
                assert count == 2
                visible = (await conn.execute(text(
                    "SELECT reported_eps FROM bt_earnings "
                    "WHERE ticker='AAA' AND fiscal_date_ending='2024-12-31' "
                    "AND reported_date <= :asof "
                    "ORDER BY reported_date DESC LIMIT 1"),
                    {"asof": date(2025, 2, 1)})).scalar_one()
                assert float(visible) == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_narrow_sf1_context_reads_four_prior_quarters(pg, monkeypatch):
    async def run() -> None:
        engine = create_async_engine(pg.async_dsn)
        monkeypatch.setattr(bt_main, "engine", engine)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("""
                    CREATE TABLE bt_fundamentals (
                        ticker TEXT NOT NULL, as_of_date DATE NOT NULL,
                        revenue NUMERIC, eps NUMERIC,
                        shares_outstanding NUMERIC,
                        PRIMARY KEY (ticker, as_of_date))
                """))
                await conn.execute(text("""
                    INSERT INTO bt_fundamentals
                        (ticker, as_of_date, revenue, eps, shares_outstanding)
                    VALUES
                        ('AAA','2023-03-31', 10, 1.0, 100),
                        ('AAA','2023-06-30', 20, 2.0, 101),
                        ('AAA','2023-09-30', 30, 3.0, 102),
                        ('AAA','2023-12-31', 40, 4.0, 103),
                        ('AAA','2024-03-31', 50, 5.0, 104)
                """))

            context = await bt_main._load_prior_fundamental_context(
                ["AAA"], "2024-06-30")
            rows = context["AAA"]
            assert [r["as_of_date"] for r in rows] == [
                date(2023, 6, 30), date(2023, 9, 30),
                date(2023, 12, 31), date(2024, 3, 31),
            ]
            assert [float(r["_revenue"]) for r in rows] == [20, 30, 40, 50]
        finally:
            await engine.dispose()

    asyncio.run(run())
