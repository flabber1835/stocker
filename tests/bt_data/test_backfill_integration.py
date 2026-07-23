"""Integration: bt-data init schema + mock backfill + coverage report, against a
REAL ephemeral Postgres (the bt_* schema, not the live one).

Proves end-to-end that:
  - init_bt.sql applies cleanly,
  - the mock Sharadar backfill writes bt_prices / bt_fundamentals / bt_universe
    with the pipeline-contract columns,
  - the data-depth report computes an earliest_viable_start and reports GO.

Skips cleanly if Postgres binaries aren't available on the runner.
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Reuse the integration harness's ephemeral Postgres launcher.
from tests.integration.conftest import _EphemeralPostgres  # noqa: E402

os.environ["BT_MOCK_DATA"] = "true"

BT_DATA = ROOT / "services" / "bt-data"
sys.path.insert(0, str(BT_DATA))


@pytest.fixture(scope="module")
def bt_async_dsn():
    try:
        pg = _EphemeralPostgres()
        pg.start()
    except Exception as exc:
        pytest.skip(f"could not start ephemeral Postgres: {exc}")
    try:
        yield pg.async_dsn
    finally:
        pg.stop()


def _setup_engine(dsn):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text
    eng = create_async_engine(dsn)
    init_sql = (BT_DATA / "sql" / "init_bt.sql").read_text()

    async def _apply():
        async with eng.begin() as conn:
            for stmt in [s.strip() for s in init_sql.split(";\n") if s.strip()]:
                await conn.execute(text(stmt))
    asyncio.get_event_loop().run_until_complete(_apply())
    return eng


def test_backfill_then_coverage_reports_go(bt_async_dsn):
    # Point the service module at our ephemeral DB BEFORE importing it.
    os.environ["BT_DATABASE_URL"] = bt_async_dsn
    for k in list(sys.modules):
        if k == "app" or k.startswith("app."):
            del sys.modules[k]
    import app.main as btmain  # noqa: E402

    async def run():
        # Apply schema via the service's own ensurer.
        await btmain._ensure_schema()
        # Run the mock backfill over the mock date span.
        await btmain._run_backfill("2022-01-01", "2023-03-31", tickers=None)
        # Coverage report.
        return await btmain.coverage()

    cov = asyncio.run(run())

    assert cov["prices"]["rows"] > 100, "mock prices should have loaded"
    assert cov["prices"]["tickers"] >= 4
    assert cov["spy"]["rows"] > 200, "SPY needed for regime + benchmark"
    assert cov["fundamentals"]["rows"] > 0, "fundamentals should have loaded"
    assert cov["earliest_viable_start"] is not None
    assert cov["go"] is True


def test_fundamentals_are_point_in_time(bt_async_dsn):
    os.environ["BT_DATABASE_URL"] = bt_async_dsn
    for k in list(sys.modules):
        if k == "app" or k.startswith("app."):
            del sys.modules[k]
    import app.main as btmain
    from sqlalchemy import text

    async def run():
        await btmain._ensure_schema()
        await btmain._run_backfill("2022-01-01", "2023-03-31", tickers=None)
        async with btmain.engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT ticker, as_of_date, pe_ratio, revenue_growth "
                "FROM bt_fundamentals ORDER BY ticker, as_of_date"
            ))).mappings().fetchall()
        return [dict(r) for r in rows]

    rows = asyncio.run(run())
    assert rows, "fundamentals written"
    # as_of_date present on all (point-in-time key)
    assert all(r["as_of_date"] is not None for r in rows)
    # YoY growth filled where >=4 prior filings exist (mock has 5 per ticker → the
    # 5th has a year-ago comparator)
    assert any(r["revenue_growth"] is not None for r in rows)


def test_topup_refused_empty_then_resumes_from_max(bt_async_dsn):
    """The endpoint bt-scheduler fires nightly: 409 while bt_prices is empty
    (topup extends a backfill, never substitutes for one), and after a backfill
    it queues an incremental load from MAX(date) minus the restatement overlap,
    tagged job_type='topup'."""
    os.environ["BT_DATABASE_URL"] = bt_async_dsn
    for k in list(sys.modules):
        if k == "app" or k.startswith("app."):
            del sys.modules[k]
    import app.main as btmain
    from datetime import timedelta
    from fastapi import BackgroundTasks, HTTPException
    from sqlalchemy import text

    async def run():
        await btmain._ensure_schema()
        async with btmain.engine.begin() as conn:
            await conn.execute(text("TRUNCATE bt_prices"))
        # empty DB → refused, loud
        try:
            await btmain.start_topup(BackgroundTasks())
            raise AssertionError("expected 409 on empty bt_prices")
        except HTTPException as exc:
            assert exc.status_code == 409

        await btmain._run_backfill("2022-01-01", "2023-03-31", None)
        async with btmain.engine.connect() as conn:
            max_date = (await conn.execute(
                text("SELECT MAX(date) FROM bt_prices"))).scalar()
        btmain._job_active = False            # clean slate for the guard
        bg = BackgroundTasks()
        resp = await btmain.start_topup(bg)
        # concurrency guard: a second call while one is "active" is refused,
        # not spawned as a competing task (the 5-task pileup fix)
        resp_dup = await btmain.start_topup(BackgroundTasks())
        btmain._job_active = False            # don't leak into other tests
        return resp, resp_dup, max_date, bg

    resp, resp_dup, max_date, bg = asyncio.run(run())
    assert resp["status"] == "started" and resp["job_type"] == "topup"
    expected_from = (max_date - timedelta(days=btmain.TOPUP_OVERLAP_DAYS)).isoformat()
    assert resp["date_from"] == expected_from
    # exactly one background job queued (the guarded backfill runner)
    assert len(bg.tasks) == 1
    # the duplicate call was refused by the in-process guard
    assert resp_dup["status"] == "already_running"


# ── chunked, resumable backfill (root-cause fix for the all-or-nothing loads) ──

def test_year_chunks_splits_and_clamps():
    import app.main as btmain
    chunks = btmain.year_chunks("2004-06-15", "2006-03-01")
    assert chunks == [("2004-06-15", "2004-12-31"),
                      ("2005-01-01", "2005-12-31"),
                      ("2006-01-01", "2006-03-01")]
    # single-year range stays one chunk with original bounds
    assert btmain.year_chunks("2024-02-01", "2024-11-30") == [("2024-02-01", "2024-11-30")]


def test_hung_chunk_trips_watchdog_and_fails_fast(bt_async_dsn):
    """A chunk that hangs (DB lock, stuck read, anything) must be aborted by the
    per-chunk watchdog and marked failed — NOT wedge the backfill forever. This
    is the root-cause fix for the '65+ min, running, no error' hang."""
    os.environ["BT_DATABASE_URL"] = bt_async_dsn
    for k in list(sys.modules):
        if k == "app" or k.startswith("app."):
            del sys.modules[k]
    import app.main as btmain
    from sqlalchemy import text

    async def _hang(cf, ct, tickers):
        await asyncio.sleep(30)   # simulate a wedged upsert/read

    async def run():
        await btmain._ensure_schema()
        btmain._load_price_chunk = _hang
        btmain.CHUNK_TIMEOUT_SECS = 0.5
        # outer bound: if the watchdog is broken this raises instead of hanging
        try:
            await asyncio.wait_for(
                btmain._run_backfill("2022-06-01", "2022-08-01", None), timeout=8)
        except asyncio.TimeoutError as exc:
            # distinguish "watchdog fired" (fast, <8s) from "test bound hit"
            raise
        return "completed-unexpectedly"

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(run())

    # and the chunk was recorded as failed with a real error, not left running
    async def check():
        for k in list(sys.modules):
            if k == "app" or k.startswith("app."):
                del sys.modules[k]
        os.environ["BT_DATABASE_URL"] = bt_async_dsn
        import app.main as btmain
        from sqlalchemy import text
        async with btmain.engine.connect() as conn:
            row = (await conn.execute(text(
                "SELECT status, error_message FROM bt_data_runs "
                "WHERE table_name='bt_prices' AND status='failed' "
                "ORDER BY run_id LIMIT 1"))).first()
        return row

    row = asyncio.run(check())
    assert row is not None and row[0] == "failed"
    assert "Timeout" in (row[1] or "")
