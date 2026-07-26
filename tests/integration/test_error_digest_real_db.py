"""GET /system/errors — the surface that makes a recorded failure VISIBLE.

Every failure this week was already recorded: in error_message columns, in
execution_steps, in stdout. The `_cb()` arity bug killed every manual backtest
for months and surfaced only because a human happened to watch a progress bar
stall at 5%. Recording an error is not surfacing it.

This queries nine run tables by name, so it is exactly the kind of code that
passes every mocked test and fails on the real schema — run it against the real
migrated database.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        await conn.execute(text(
            "TRUNCATE ingest_runs, pipeline_runs, alpaca_orders "
            "RESTART IDENTITY CASCADE"))
    yield eng
    await eng.dispose()


async def _digest(engine, hours=24):
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                    "services", "api"))
    import app.main as api
    api.engine = engine
    return await api.system_errors(hours=hours)


class TestErrorDigest:
    async def test_every_source_table_is_queryable(self, engine):
        """A wrong table or column name would silently blank that source. The
        digest reports `digest_error` instead of returning nothing — a digest
        that hides its own breakage is the bug it exists to prevent."""
        out = await _digest(engine)
        assert [e for e in out["errors"] if e.get("status") == "digest_error"] == []

    async def test_failures_are_collected_across_tables(self, engine):
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO ingest_runs (run_id, job_type, status, error_message, "
                " started_at) VALUES (CAST(:r AS uuid), 'fetch-data', 'failed', "
                "'AV throttled', NOW())"), {"r": str(uuid.uuid4())})
            await conn.execute(text(
                "INSERT INTO pipeline_runs (run_id, strategy_id, status, "
                " error_message, started_at) VALUES (CAST(:r AS uuid), 's1', "
                "'failed', 'factor step OOM', NOW())"), {"r": str(uuid.uuid4())})
        out = await _digest(engine)
        by_src = {e["source"]: e for e in out["errors"]}
        assert "AV throttled" in by_src["ingest"]["message"]
        assert "factor step OOM" in by_src["pipeline"]["message"]
        assert out["error_count"] >= 2

    async def test_a_repeating_fault_is_collapsed_not_repeated(self, engine):
        """One noisy failure must not bury every other fault in the window."""
        async with engine.begin() as conn:
            for _ in range(5):
                await conn.execute(text(
                    "INSERT INTO ingest_runs (run_id, job_type, status, "
                    " error_message, started_at) VALUES (CAST(:r AS uuid), "
                    "'fetch-data', 'failed', 'same failure', NOW())"),
                    {"r": str(uuid.uuid4())})
        out = await _digest(engine)
        ingest = [e for e in out["errors"] if e["source"] == "ingest"]
        assert len(ingest) == 1
        assert ingest[0]["occurrences"] == 5
        assert out["distinct_faults"] == 1

    async def test_failed_orders_count_even_though_no_run_row_failed(self, engine):
        """An order that never executed is an operational failure. Nothing marks
        a run failed for it — this week's CPRX 'asset is not active' and the
        cancel_failed rows are exactly this class."""
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO alpaca_orders (id, ticker, action, side, qty, "
                " status, error_message, created_at) VALUES "
                "(CAST(:i AS uuid), 'CPRX', 'exit', 'sell', 89, 'failed', "
                "'asset CPRX is not active', NOW())"), {"i": str(uuid.uuid4())})
        out = await _digest(engine)
        orders = [e for e in out["errors"] if e["source"] == "orders"]
        assert orders and "not active" in orders[0]["message"]

    async def test_a_clean_window_reports_zero_rather_than_erroring(self, engine):
        out = await _digest(engine)
        assert out["error_count"] == 0 and out["errors"] == []

    async def test_old_failures_fall_out_of_the_window(self, engine):
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO ingest_runs (run_id, job_type, status, error_message, "
                " started_at) VALUES (CAST(:r AS uuid), 'fetch-data', 'failed', "
                "'ancient', NOW() - INTERVAL '10 days')"), {"r": str(uuid.uuid4())})
        assert (await _digest(engine, hours=24))["error_count"] == 0
        assert (await _digest(engine, hours=24 * 30))["error_count"] == 1

    async def test_autonomy_state_is_reported_next_to_the_errors(self, engine):
        """An autonomous default is not dangerous because it is on — it is
        dangerous because it is on and nobody can see that it is."""
        out = await _digest(engine)
        a = out["autonomy"]
        assert set(a) >= {"auto_promotion_enabled", "revert_enabled",
                          "promotion_state"}
        assert isinstance(a["auto_promotion_enabled"], bool)
        assert isinstance(a["revert_enabled"], bool)
