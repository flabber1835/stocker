"""
Bug C1 (duplicate-fetch race) regression tests.

`_reserve_run` MUST make the no-running-job check and the 'running' ingest_runs
INSERT atomic (one DB transaction, under `_job_lock`). The old design checked in
`_assert_no_running_job` but INSERTed the row LATER inside the detached
BackgroundTask via `_start_run` — so two requests arriving close together both
saw "no running job" and both launched a full fetch (two concurrent jobs
hammering Alpha Vantage, double-writing prices, "fetch starts at 0 again").

These tests drive the REAL `_reserve_run` against an in-memory fake of the
`ingest_runs` table (monkeypatching `app.main.engine.begin`) so the check +
insert path is exercised without a live Postgres.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import app.main as main


class _FakeResult:
    """Mimics the subset of a SQLAlchemy Result that _reserve_run uses."""

    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeConn:
    """In-memory stand-in for an `engine.begin()` connection.

    Backed by a shared list of run dicts so an INSERT made in one transaction is
    visible to the next SELECT — exactly the visibility the atomicity fix relies
    on. Recognises the three statements _reserve_run issues by substring.
    """

    def __init__(self, runs: list):
        self.runs = runs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "SELECT run_id, started_at FROM ingest_runs" in sql:
            running = [r for r in self.runs if r["status"] == "running"]
            running.sort(key=lambda r: r["started_at"], reverse=True)
            return _FakeResult(running[0] if running else None)
        if sql.strip().startswith("UPDATE ingest_runs SET status='failed'"):
            for r in self.runs:
                if r["run_id"] == params["rid"]:
                    r["status"] = "failed"
                    r["error_message"] = params["msg"]
            return _FakeResult(None)
        if "INSERT INTO ingest_runs" in sql:
            self.runs.append({
                "run_id": params["run_id"],
                "job_type": params["job_type"],
                "status": "running",
                "started_at": params["now"],
                "error_message": None,
            })
            return _FakeResult(None)
        raise AssertionError(f"unexpected SQL in fake conn: {sql!r}")


class _FakeEngine:
    def __init__(self, runs: list):
        self.runs = runs

    def begin(self):
        return _FakeConn(self.runs)


@pytest.fixture
def fake_engine(monkeypatch):
    runs: list = []
    monkeypatch.setattr(main, "engine", _FakeEngine(runs))
    return runs


@pytest.mark.asyncio
async def test_first_reserve_inserts_running_row(fake_engine):
    """A reserve on an empty table claims a slot and leaves exactly one running row."""
    run_id = await main._reserve_run("fetch-data")
    assert run_id
    running = [r for r in fake_engine if r["status"] == "running"]
    assert len(running) == 1
    assert running[0]["run_id"] == run_id
    assert running[0]["job_type"] == "fetch-data"


@pytest.mark.asyncio
async def test_second_reserve_while_running_is_rejected(fake_engine):
    """The core race fix: a second reserve while one is running gets 409.

    The first reserve's INSERT is committed before it returns (atomic with the
    check), so the second caller's check sees the running row — no second job
    launches. This is what `already_running` / 409 protects against.
    """
    first = await main._reserve_run("fetch-data")
    assert first

    with pytest.raises(HTTPException) as exc:
        await main._reserve_run("fetch-data")
    assert exc.value.status_code == 409
    assert "already running" in exc.value.detail.lower()

    # Still exactly ONE running row — the rejected caller inserted nothing.
    running = [r for r in fake_engine if r["status"] == "running"]
    assert len(running) == 1
    assert running[0]["run_id"] == first


@pytest.mark.asyncio
async def test_stale_running_is_reclaimed_then_new_slot_claimed(fake_engine, monkeypatch):
    """A presumed-dead stale 'running' row is reclaimed, not 409-wedged."""
    monkeypatch.setattr(main, "STALE_INGEST_HOURS", 6.0)
    stale_started = datetime.now(timezone.utc) - timedelta(hours=8)
    fake_engine.append({
        "run_id": "stale-run-1",
        "job_type": "fetch-data",
        "status": "running",
        "started_at": stale_started,
        "error_message": None,
    })

    new_id = await main._reserve_run("fetch-data")
    assert new_id != "stale-run-1"

    by_id = {r["run_id"]: r for r in fake_engine}
    # Old orphan marked failed with the restart-abort marker (scheduler re-triggers).
    assert by_id["stale-run-1"]["status"] == "failed"
    assert main.RESTART_ABORT_MARKER in by_id["stale-run-1"]["error_message"]
    # And the new job is the only running row.
    running = [r for r in fake_engine if r["status"] == "running"]
    assert len(running) == 1
    assert running[0]["run_id"] == new_id


@pytest.mark.asyncio
async def test_recent_running_blocks_even_under_stale_threshold(fake_engine, monkeypatch):
    """A recent (non-stale) running row is a LIVE job → 409, never reclaimed."""
    monkeypatch.setattr(main, "STALE_INGEST_HOURS", 6.0)
    recent_started = datetime.now(timezone.utc) - timedelta(minutes=10)
    fake_engine.append({
        "run_id": "live-run-1",
        "job_type": "fetch-data",
        "status": "running",
        "started_at": recent_started,
        "error_message": None,
    })

    with pytest.raises(HTTPException) as exc:
        await main._reserve_run("fetch-data")
    assert exc.value.status_code == 409
    # The live row is untouched (not reclaimed).
    assert fake_engine[0]["status"] == "running"
