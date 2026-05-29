"""
Schema-contract tests: run the real, type-sensitive service queries against a
real migrated Postgres through async SQLAlchemy + asyncpg (the production stack).

Each test seeds the minimum rows needed and executes the actual query a service
runs. A wrong column name, a uuid/integer mismatch, or a str-bound-to-DATE param
raises here — in CI — instead of silently 500-ing a service in production.

The two queries that recently broke in deployment are covered explicitly:
  - vetter held-tickers  (live_positions.sync_run_id UUID = alpaca_sync_runs.run_id)
  - penalty-box lookup    (DATE column compared to a date param)
plus the dashboard's rankings/with-overlays join chain.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    # Clean slate per test so row counts are deterministic.
    async with eng.begin() as conn:
        await conn.execute(text(
            "TRUNCATE live_positions, alpaca_sync_runs, vetter_penalty_box, "
            "rankings, ranking_runs, universe_tickers, universe_snapshots "
            "RESTART IDENTITY CASCADE"
        ))
    yield eng
    await eng.dispose()


# ── vetter held-tickers query (regression: SELECT id → uuid = integer) ────────

class TestVetterHeldTickersQuery:
    async def test_held_query_runs_and_returns_held_tickers(self, engine):
        sync_run_id = uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO alpaca_sync_runs (run_id, status, completed_at) "
                "VALUES (:rid, 'success', NOW())"
            ), {"rid": sync_run_id})
            await conn.execute(text(
                "INSERT INTO live_positions (sync_run_id, ticker, qty) VALUES "
                "(:rid, 'AAPL', 10), (:rid, 'MSFT', 5), (:rid, 'TSLA', 0)"
            ), {"rid": sync_run_id})

        # The exact query from services/llm-vetter/app/main.py
        async with engine.connect() as conn:
            rows = await conn.execute(text(
                "SELECT ticker FROM live_positions "
                "WHERE sync_run_id = ("
                "  SELECT run_id FROM alpaca_sync_runs "
                "  WHERE status = 'success' "
                "  ORDER BY completed_at DESC LIMIT 1"
                ") AND qty > 0"
            ))
            held = {r.ticker for r in rows.fetchall()}

        assert held == {"AAPL", "MSFT"}  # TSLA qty=0 excluded

    async def test_selecting_id_instead_of_run_id_raises(self, engine):
        """Proves the test tier actually catches the original bug: comparing a
        UUID column to alpaca_sync_runs.id (integer) must error."""
        from sqlalchemy.exc import DBAPIError

        sync_run_id = uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO alpaca_sync_runs (run_id, status, completed_at) "
                "VALUES (:rid, 'success', NOW())"
            ), {"rid": sync_run_id})

        with pytest.raises(DBAPIError):
            async with engine.connect() as conn:
                await conn.execute(text(
                    "SELECT ticker FROM live_positions "
                    "WHERE sync_run_id = ("
                    "  SELECT id FROM alpaca_sync_runs "
                    "  WHERE status = 'success' "
                    "  ORDER BY completed_at DESC LIMIT 1"
                    ") AND qty > 0"
                ))


# ── penalty-box query (regression: str bound to DATE column) ──────────────────

class TestPenaltyBoxDateParam:
    async def test_date_object_param_runs(self, engine):
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO vetter_penalty_box "
                "(ticker, first_flagged_date, last_flagged_date, penalty_box_until) "
                "VALUES ('NVDA', :d, :d, :until)"
            ), {"d": date.today(), "until": date.today() + timedelta(days=30)})

        # The exact query from services/api/app/main.py _load_penalty_box
        async with engine.connect() as conn:
            rows = await conn.execute(text(
                "SELECT ticker, penalty_box_until FROM vetter_penalty_box "
                "WHERE penalty_box_until >= :today"
            ), {"today": date.today()})
            tickers = {r.ticker for r in rows.fetchall()}

        assert tickers == {"NVDA"}

    async def test_isoformat_string_param_raises(self, engine):
        """Proves the tier catches the original bug: asyncpg rejects a str for a
        DATE-typed parameter ('str' object has no attribute 'toordinal')."""
        from sqlalchemy.exc import DBAPIError

        with pytest.raises(DBAPIError):
            async with engine.connect() as conn:
                await conn.execute(text(
                    "SELECT ticker FROM vetter_penalty_box "
                    "WHERE penalty_box_until >= :today"
                ), {"today": date.today().isoformat()})  # str → bug


# ── dashboard rankings/with-overlays core join (the "NO DATA" endpoint) ───────

class TestRankingsWithOverlaysQuery:
    async def test_latest_run_join_returns_rows(self, engine):
        run_id = uuid.uuid4()
        factor_run_id = uuid.uuid4()
        async with engine.begin() as conn:
            # ranking_runs requires a source_factor_run_id FK → seed a factor_run
            await conn.execute(text(
                "INSERT INTO factor_runs (run_id, strategy_id, status, started_at) "
                "VALUES (:frid, 'quality_core_v1', 'success', NOW())"
            ), {"frid": factor_run_id})
            await conn.execute(text(
                "INSERT INTO ranking_runs "
                "(run_id, source_factor_run_id, strategy_id, status, rank_date, regime, "
                " universe_count, ranked_count, completed_at) "
                "VALUES (:rid, :frid, 'quality_core_v1', 'success', :d, 'bull_calm', 2, 2, NOW())"
            ), {"rid": run_id, "frid": factor_run_id, "d": date.today()})
            await conn.execute(text(
                "INSERT INTO rankings "
                "(run_id, source_factor_run_id, strategy_id, regime, rank_date, "
                " ticker, rank, composite_score, percentile) "
                "VALUES (:rid, :frid, 'quality_core_v1', 'bull_calm', :d, 'AAPL', 1, 1.5, 1.0), "
                "       (:rid, :frid, 'quality_core_v1', 'bull_calm', :d, 'MSFT', 2, 1.2, 0.0)"
            ), {"rid": run_id, "frid": factor_run_id, "d": date.today()})

        # Core of get_rankings_with_overlays: latest successful run + rank slopes.
        async with engine.connect() as conn:
            rows = await conn.execute(text(
                "WITH recent_runs AS ("
                "  SELECT run_id, ROW_NUMBER() OVER (ORDER BY rank_date ASC) - 1 AS x_pos"
                "  FROM ranking_runs WHERE status='success' ORDER BY rank_date DESC LIMIT 5"
                "),"
                "ticker_slopes AS ("
                "  SELECT r.ticker,"
                "    REGR_SLOPE(r.rank::double precision, rr.x_pos::double precision) AS rank_slope"
                "  FROM rankings r JOIN recent_runs rr ON rr.run_id = r.run_id"
                "  GROUP BY r.ticker"
                ")"
                "SELECT r.ticker, r.rank, ts.rank_slope "
                "FROM rankings r LEFT JOIN ticker_slopes ts ON ts.ticker = r.ticker "
                "WHERE r.run_id = ("
                "  SELECT run_id FROM ranking_runs WHERE status='success' "
                "  ORDER BY rank_date DESC, completed_at DESC NULLS LAST LIMIT 1"
                ") ORDER BY r.rank ASC"
            ))
            ranked = [(r.ticker, r.rank) for r in rows.fetchall()]

        assert ranked == [("AAPL", 1), ("MSFT", 2)]
