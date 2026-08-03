"""Regression: a forced re-run must actually re-run.

INCIDENT (2026-08-02, observed in production). A manual run-now walked all five
steps and reported "chain complete" in about ten seconds, and no new
`pipeline_runs` row was ever written. The scheduler log is the whole story:

    supervisor: pipeline: triggered
    supervisor: pipeline → done          ← next tick
    supervisor: vet: triggered
    supervisor: vet → done
    supervisor: portfolio-builder: already running (409)
    supervisor: portfolio-builder → done ← while it was demonstrably RUNNING
    supervisor: chain complete

The forced trigger is fire-and-forget. `_step_state` re-derives state on the
next tick from the service's own `/runs/latest`, which still returns the
PREVIOUS cycle's successful run because the new one has not been created yet.
That reads `done`, so the chain advances — and repeats down the whole chain.
`_force_pending` cannot prevent it: it records that a re-run was REQUESTED, not
that one has STARTED.

The fix records the run_id observed at trigger time and refuses to accept a
terminal state until the service reports a DIFFERENT one. The tests below pin
both failure directions, because the same masking hurts twice:

    stale `done`   → the chain walks past work that never ran (silent no-op)
    stale `failed` → the chain SUSPENDS on a step that was re-triggered fine

and one liveness property: the guard must never wedge the chain when a trigger
is accepted but no run ever appears.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "scheduler"))

from app.main import _NO_RERUN_WHEN_DONE, _STEPS, _supervisor_tick  # noqa: E402

_G = _supervisor_tick.__globals__


def _reset():
    _G["_chain_status"].update({
        "status": "idle", "date": "2026-07-31", "steps": {}, "run_ids": {},
        "last_completed": None, "current_run_id": None, "next_run": None,
        "origin": "manual", "config_hash": None,
    })
    _G["_force_pending"].clear()
    _G["_no_rerun_when_done"].clear()
    # Mirror the real run-now: fetch-data is protected from a forced redo, so the
    # first step that actually re-runs is the pipeline. Without this the tests
    # would exercise fetch-data and never reach the step the incident was about.
    _G["_no_rerun_when_done"].update(_NO_RERUN_WHEN_DONE)
    _G["_forced_supersede"].clear()


async def _tick(state, *, run_id, trigger=None):
    """One supervisor tick with every step reporting `state` and the services
    reporting `run_id` as their latest run."""
    trigger = trigger or AsyncMock(return_value=True)
    with patch.dict(_G, {
        "_has_universe": AsyncMock(return_value=True),
        "_step_state": AsyncMock(return_value=state),
        "_trigger_step": trigger,
        "_get_latest_run_id": AsyncMock(return_value=run_id),
        "_db_open_run": AsyncMock(return_value="chain-uuid"),
        "_db_update_run": AsyncMock(),
        "_db_close_run": AsyncMock(),
        "_is_after_scheduled_time": MagicMock(return_value=True),
        "_latest_rank_date": AsyncMock(return_value=None),
    }):
        await _supervisor_tick()
    return trigger


class TestStaleDoneCannotAdvanceTheChain:
    @pytest.mark.asyncio
    async def test_the_chain_WAITS_when_the_old_run_is_still_the_latest(self):
        """THE regression. Trigger pipeline, then tick again while /runs/latest
        still returns the run that existed BEFORE the trigger. The step must read
        as running, not done — otherwise the chain advances past a job that has
        not started."""
        _reset()
        _G["_force_pending"].update(s.name for s in _STEPS)

        await _tick("done", run_id="OLD")                 # triggers pipeline
        assert "pipeline" in _G["_forced_supersede"]

        trigger = await _tick("done", run_id="OLD")       # nothing new yet
        assert _G["_chain_status"]["steps"]["pipeline"] == "running"
        assert trigger.call_count == 0, "must not re-trigger while waiting"

    @pytest.mark.asyncio
    async def test_it_advances_once_a_NEW_run_appears(self):
        """The complement — the guard must release, not block forever."""
        _reset()
        _G["_force_pending"].update(s.name for s in _STEPS)

        await _tick("done", run_id="OLD")
        await _tick("done", run_id="NEW")                 # the re-run exists now

        assert "pipeline" not in _G["_forced_supersede"]
        assert _G["_chain_status"]["steps"]["pipeline"] == "done"

    @pytest.mark.asyncio
    async def test_a_step_that_was_never_forced_is_unaffected(self):
        """The ordinary cron path must be bit-identical. Regular ticks never
        populate _force_pending, so the guard must be entirely inert there."""
        _reset()
        trigger = await _tick("done", run_id="OLD")
        assert _G["_forced_supersede"] == {}
        assert trigger.call_count == 0
        assert _G["_chain_status"]["steps"]["delta"] == "done"


class TestStaleFailedCannotSuspendTheChain:
    @pytest.mark.asyncio
    async def test_a_re_triggered_FAILED_step_is_not_suspended_on(self):
        """The same masking, opposite direction, and arguably worse. The failed
        row survives until the new run row exists — and by then the step has been
        drained from _force_pending, so the next tick reads 'failed' with no
        forced retry left and halts the chain."""
        _reset()
        _G["_force_pending"].update(s.name for s in _STEPS)

        await _tick("failed", run_id="OLD")               # force-retries fetch-data
        assert "fetch-data" in _G["_forced_supersede"]

        await _tick("failed", run_id="OLD")               # new run not visible yet
        assert _G["_chain_status"]["steps"]["fetch-data"] == "running"
        assert _G["_chain_status"]["status"] != "failed", (
            "the chain suspended on a step whose re-trigger was accepted")


class TestItCannotWedgeTheChain:
    @pytest.mark.asyncio
    async def test_it_gives_up_after_the_timeout(self):
        """A supervisor that waits forever is a worse failure than one that
        advances too eagerly. If a trigger is accepted but no run ever appears,
        the guard must expire rather than hold the chain open indefinitely."""
        _reset()
        _G["_force_pending"].update(s.name for s in _STEPS)

        await _tick("done", run_id="OLD")
        prior, _since = _G["_forced_supersede"]["pipeline"]
        # rewind the clock past the timeout
        _G["_forced_supersede"]["pipeline"] = (
            prior, -_G["FORCE_SUPERSEDE_TIMEOUT_SECS"] - 1)

        await _tick("done", run_id="OLD")
        assert "pipeline" not in _G["_forced_supersede"]
        assert _G["_chain_status"]["steps"]["pipeline"] == "done"

    @pytest.mark.asyncio
    async def test_an_unreadable_run_id_keeps_waiting_rather_than_advancing(self):
        """None means the status call failed, not that the run is unchanged.
        Treating it as 'new' would re-open the original bug on exactly the ticks
        where the service is least healthy."""
        _reset()
        _G["_force_pending"].update(s.name for s in _STEPS)

        await _tick("done", run_id="OLD")
        await _tick("done", run_id=None)
        assert _G["_chain_status"]["steps"]["pipeline"] == "running"
        assert "pipeline" in _G["_forced_supersede"]

    @pytest.mark.asyncio
    async def test_a_new_chain_clears_stale_waits(self):
        """A guard left over from the previous session would make the first step
        of a fresh chain read 'running' against a run_id nobody is waiting for."""
        _reset()
        _G["_forced_supersede"]["pipeline"] = ("GHOST", 0.0)
        _G["_chain_status"]["date"] = "1999-01-01"        # force a session rollover
        with patch.dict(_G, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="done"),
            "_trigger_step": AsyncMock(return_value=True),
            "_get_latest_run_id": AsyncMock(return_value="OLD"),
            "_db_open_run": AsyncMock(return_value="chain-uuid"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()
        assert "pipeline" not in _G["_forced_supersede"]


def test_the_run_id_poll_is_scoped_to_the_step_job_type():
    """av-ingestor's unscoped /runs/latest returns whatever ingest job ran most
    recently, so an unscoped comparison would compare two different jobs' ids and
    'supersede' on an unrelated run."""
    import inspect

    from app import main as sched
    src = inspect.getsource(sched._supervisor_tick)
    assert src.count("step.status_path, step.job_type") >= 2, (
        "the supersede guard must scope its run_id poll by job_type")
