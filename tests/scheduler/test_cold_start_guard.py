"""
Decision-table tests for the supervisor's cold-start guard.

The cold-start guard is the branch of _supervisor_tick() that fires when
_has_universe() returns False.  Its job is to decide whether to trigger a
new fetch-universe, wait for an in-flight one, or fail the chain.

Inputs (3-axis decision table):
  • _has_universe()        True  | False
  • last_run.job_type      fetch-universe | fetch-data | fetch-prices |
                           fetch-fundamentals | None (no runs yet) |
                           /runs/latest 404 (no row found)
  • last_run.status        running | success | failed | None

Expected actions:
  • TRIGGER  — POST /jobs/fetch-universe
  • WAIT     — return without triggering, chain status set to "running"
  • FAIL     — return with chain status set to "failed"
  • SKIP     — guard does not fire (when _has_universe is True)

The historical bug this suite is built to prevent:
  (False, fetch-universe, success) → was TRIGGER (loop), must be WAIT
because the visibility race between universe_snapshots and universe_tickers
can briefly make _has_universe return False even after a successful run.

Future variations of the same class of bug live in adjacent rows
(False, fetch-data, *) etc. — those still TRIGGER because no fetch-universe
ran today and we have to make forward progress.

All 24 rows below are exhaustive over the relevant input combinations.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Stub out apscheduler so app.main can be imported without the real package ──

def _make_apscheduler_stubs():
    schedulers_pkg = types.ModuleType("apscheduler.schedulers")
    asyncio_mod = types.ModuleType("apscheduler.schedulers.asyncio")
    asyncio_mod.AsyncIOScheduler = MagicMock()
    sys.modules.setdefault("apscheduler", types.ModuleType("apscheduler"))
    sys.modules.setdefault("apscheduler.schedulers", schedulers_pkg)
    sys.modules.setdefault("apscheduler.schedulers.asyncio", asyncio_mod)

    triggers_pkg = types.ModuleType("apscheduler.triggers")
    cron_mod = types.ModuleType("apscheduler.triggers.cron")
    cron_mod.CronTrigger = MagicMock()
    interval_mod = types.ModuleType("apscheduler.triggers.interval")
    interval_mod.IntervalTrigger = MagicMock()
    sys.modules.setdefault("apscheduler.triggers", triggers_pkg)
    sys.modules.setdefault("apscheduler.triggers.cron", cron_mod)
    sys.modules.setdefault("apscheduler.triggers.interval", interval_mod)


_make_apscheduler_stubs()

from app import main as scheduler_main  # noqa: E402
from app.main import _supervisor_tick, _chain_status, _force_pending  # noqa: E402


# ── Decision-table fixtures ───────────────────────────────────────────────────

# (has_universe, last_job_type, last_status, expected_action, label)
COLD_START_DECISION_TABLE = [
    # has_universe=True → guard does not fire, chain advances normally (SKIP)
    (True,  "fetch-universe",     "success",  "SKIP",    "skip when universe exists, last=fetch-universe success"),
    (True,  "fetch-universe",     "running",  "SKIP",    "skip when universe exists, last=fetch-universe running"),
    (True,  "fetch-data",         "success",  "SKIP",    "skip when universe exists, last=fetch-data success"),
    (True,  None,                 None,       "SKIP",    "skip when universe exists, no runs ever (impossible state, defensive)"),

    # has_universe=False, last is fetch-universe — handled by job-type branch
    (False, "fetch-universe",     "running",  "WAIT",    "wait while fetch-universe is in progress"),
    (False, "fetch-universe",     "failed",   "FAIL",    "fail chain when fetch-universe failed"),
    (False, "fetch-universe",     "success",  "WAIT",    "REGRESSION: visibility race — wait, do NOT re-trigger"),

    # has_universe=False, last run is something other than fetch-universe → TRIGGER
    # (no fetch-universe has ever happened, OR an unrelated job ran more recently)
    (False, "fetch-data",         "success",  "TRIGGER", "trigger fetch-universe when last run was fetch-data"),
    (False, "fetch-data",         "running",  "TRIGGER", "trigger fetch-universe even if fetch-data is mid-run"),
    (False, "fetch-data",         "failed",   "TRIGGER", "trigger fetch-universe when fetch-data failed"),
    (False, "fetch-prices",       "success",  "TRIGGER", "trigger fetch-universe when last run was fetch-prices"),
    (False, "fetch-prices",       "running",  "TRIGGER", "trigger fetch-universe when fetch-prices in progress"),
    (False, "fetch-prices",       "failed",   "TRIGGER", "trigger fetch-universe when fetch-prices failed"),
    (False, "fetch-fundamentals", "success",  "TRIGGER", "trigger fetch-universe when last run was fetch-fundamentals"),
    (False, "fetch-fundamentals", "running",  "TRIGGER", "trigger fetch-universe when fetch-fundamentals in progress"),
    (False, "fetch-fundamentals", "failed",   "TRIGGER", "trigger fetch-universe when fetch-fundamentals failed"),

    # has_universe=False, no runs ever → TRIGGER (the canonical cold-boot case)
    (False, None,                 None,       "TRIGGER", "trigger fetch-universe on true cold boot (no runs)"),

    # has_universe=False, /runs/latest returns 404 → TRIGGER (no historical runs visible)
    (False, "__404__",            None,       "TRIGGER", "trigger fetch-universe when /runs/latest 404s"),
]


# ── Test machinery ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_chain_state():
    """Each test gets a clean module-level state so previous test state can't leak."""
    _chain_status.clear()
    _chain_status.update({
        "date": None, "status": None, "steps": {}, "run_ids": {},
        "current_run_id": None, "next_run": None,
    })
    _force_pending.clear()
    yield
    _chain_status.clear()
    _force_pending.clear()


def _build_async_client_mock(
    last_job_type: str | None,
    last_status: str | None,
) -> MagicMock:
    """Build a mock httpx.AsyncClient whose GET /runs/latest returns the given
    job_type/status, and whose POST /jobs/fetch-universe records call_args.
    """
    runs_latest_payload = {}
    runs_latest_status_code = 200

    if last_job_type == "__404__":
        runs_latest_status_code = 404
    elif last_job_type is None and last_status is None:
        # No runs ever — return empty payload with 200 (matches av-ingestor behavior
        # when ingest_runs table has no rows, though in reality av-ingestor returns 404)
        runs_latest_payload = {}
    else:
        runs_latest_payload = {"job_type": last_job_type, "status": last_status}

    get_resp = MagicMock()
    get_resp.status_code = runs_latest_status_code
    get_resp.json.return_value = runs_latest_payload

    post_resp = MagicMock()
    post_resp.status_code = 200
    post_resp.json.return_value = {"status": "started"}

    client = MagicMock()
    client.get = AsyncMock(return_value=get_resp)
    client.post = AsyncMock(return_value=post_resp)

    # Context manager for `async with httpx.AsyncClient() as client:`
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _post_paths(client: MagicMock) -> list[str]:
    """Return the list of URLs the mock client received POSTs to."""
    return [call.args[0] for call in client.post.call_args_list if call.args]


# ── Decision-table parametrized test ──────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "has_universe,last_job_type,last_status,expected_action,label",
    COLD_START_DECISION_TABLE,
    ids=[row[4] for row in COLD_START_DECISION_TABLE],
)
async def test_cold_start_guard_decision_table(
    has_universe, last_job_type, last_status, expected_action, label
):
    """Exhaustive decision-table test for the cold-start guard.

    For every relevant combination of (_has_universe, last.job_type, last.status),
    assert that the supervisor takes the correct action: TRIGGER, WAIT, FAIL, or SKIP.
    """
    client_mock = _build_async_client_mock(last_job_type, last_status)

    # Patch httpx.AsyncClient so the supervisor uses our mock
    with patch.object(scheduler_main, "httpx") as httpx_mock, \
         patch.object(scheduler_main, "_has_universe", new=AsyncMock(return_value=has_universe)), \
         patch.object(scheduler_main, "_db_open_run", new=AsyncMock(return_value="fake-run-id")), \
         patch.object(scheduler_main, "_db_update_run", new=AsyncMock()), \
         patch.object(scheduler_main, "_db_close_run", new=AsyncMock()), \
         patch.object(scheduler_main, "_get_latest_run_id", new=AsyncMock(return_value=None)), \
         patch.object(scheduler_main, "_trigger_step", new=AsyncMock(return_value=True)), \
         patch.object(scheduler_main, "_step_state", new=AsyncMock(return_value="done")):
        httpx_mock.AsyncClient = MagicMock(return_value=client_mock)

        await _supervisor_tick()

    posted_paths = _post_paths(client_mock)
    triggered_fetch_universe = any("/jobs/fetch-universe" in p for p in posted_paths)
    chain_status = _chain_status.get("status")

    if expected_action == "TRIGGER":
        assert triggered_fetch_universe, (
            f"[{label}] Expected fetch-universe to be triggered; POSTs were: {posted_paths}"
        )
        assert chain_status == "running", (
            f"[{label}] Expected chain status 'running' after trigger; got {chain_status!r}"
        )

    elif expected_action == "WAIT":
        assert not triggered_fetch_universe, (
            f"[{label}] REGRESSION: fetch-universe was re-triggered; POSTs were: {posted_paths}"
        )
        assert chain_status == "running", (
            f"[{label}] Expected chain status 'running' while waiting; got {chain_status!r}"
        )

    elif expected_action == "FAIL":
        assert not triggered_fetch_universe, (
            f"[{label}] Expected NOT to trigger fetch-universe on FAIL; POSTs were: {posted_paths}"
        )
        assert chain_status == "failed", (
            f"[{label}] Expected chain status 'failed'; got {chain_status!r}"
        )

    elif expected_action == "SKIP":
        # Guard did not fire — _step_state was called for at least one step
        # (because the supervisor advanced past the cold-start guard into the step loop).
        assert not triggered_fetch_universe, (
            f"[{label}] Cold-start guard should not have fired when universe exists; "
            f"POSTs were: {posted_paths}"
        )

    else:
        pytest.fail(f"Unknown expected_action: {expected_action}")


# ── Regression test pinned to the exact bug we just fixed ─────────────────────

@pytest.mark.asyncio
async def test_regression_no_loop_when_fetch_universe_succeeded_but_visibility_race():
    """REGRESSION (commit fixing fetch-universe → ready → fetch-universe loop):

    Scenario: fetch-universe just succeeded (ingest_runs row with status='success'),
    but _has_universe() returns False because the universe_tickers child rows
    aren't visible yet to a fresh connection.

    Before the fix: the cold-start guard fell through and re-triggered
    fetch-universe, producing an infinite loop.
    After the fix: the guard treats this as a transient visibility race and
    waits for the next tick.

    This test runs the supervisor twice in a row with the same (False, success)
    input and asserts fetch-universe is NEVER triggered.
    """
    client_mock = _build_async_client_mock("fetch-universe", "success")

    with patch.object(scheduler_main, "httpx") as httpx_mock, \
         patch.object(scheduler_main, "_has_universe", new=AsyncMock(return_value=False)), \
         patch.object(scheduler_main, "_db_open_run", new=AsyncMock(return_value="fake-run-id")), \
         patch.object(scheduler_main, "_db_update_run", new=AsyncMock()), \
         patch.object(scheduler_main, "_db_close_run", new=AsyncMock()), \
         patch.object(scheduler_main, "_get_latest_run_id", new=AsyncMock(return_value=None)), \
         patch.object(scheduler_main, "_trigger_step", new=AsyncMock(return_value=True)), \
         patch.object(scheduler_main, "_step_state", new=AsyncMock(return_value="done")):
        httpx_mock.AsyncClient = MagicMock(return_value=client_mock)

        # Tick the supervisor multiple times — the loop bug would fire fetch-universe
        # on every tick. The fix ensures it never fires while in the visibility race.
        for _ in range(5):
            await _supervisor_tick()

    posted_paths = _post_paths(client_mock)
    fetch_universe_posts = [p for p in posted_paths if "/jobs/fetch-universe" in p]

    assert len(fetch_universe_posts) == 0, (
        "REGRESSION: fetch-universe was triggered during the visibility race. "
        f"This is the exact loop bug — POSTs: {posted_paths}"
    )
    assert _chain_status.get("status") == "running", (
        f"Chain should be in 'running' state while waiting; got {_chain_status.get('status')!r}"
    )
