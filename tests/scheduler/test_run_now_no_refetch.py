"""Regression: a manual run-now must not restart a multi-hour fetch that already
has the target session's data — and the fetch watchdog must not fire before a
legitimate fetch can finish.

Incident (2026-07-27/28). Two bugs compounded into a chain that could not advance:

  A. fetch-data's max_running_minutes was 240 (comment: "comfortably covers a
     legit cold full rebuild (~3h)"). The measured worst case is a UNIVERSE-
     REFRESH evening: the fresh LISTING_STATUS snapshot nulls every sector and
     the OVERVIEW backfill re-fetches thousands of fundamentals. That run took
     4h30m (5900/5918 tickers, partial_success). The watchdog coerced it to
     'failed' at the 4h mark — 30 minutes before it actually succeeded.

  B. /jobs/run-now put EVERY step in _force_pending, and the supervisor's
     done+force branch re-triggers unconditionally. So clicking "Run" — the
     natural response to a stuck chain — restarted the fetch from scratch
     instead of advancing to the pipeline, even though the session's bars were
     already in the DB. Loop: click Run → 4.5h fetch → killed at 4h → ranking
     still stale → click Run.

Fixes under test:
  A. the fetch watchdog exceeds a realistic full-universe fetch and is
     env-tunable (FETCH_MAX_RUNNING_MINUTES).
  B. run-now suppresses the forced re-run of a fetch that already reads 'done'
     (_NO_RERUN_WHEN_DONE), while still force-retrying a FAILED fetch and still
     force-re-running the whole strategy segment. ?refetch=true opts back in.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "scheduler"))

from app.main import (  # noqa: E402
    _NO_RERUN_WHEN_DONE,
    _STEPS,
    _STRATEGY_STEPS,
    _supervisor_tick,
    run_now,
)

_G = _supervisor_tick.__globals__


def _step(name):
    return next(s for s in _STEPS if s.name == name)


# ── Bug A: the watchdog must not be shorter than a legitimate fetch ───────────

class TestFetchWatchdogHeadroom:
    def test_fetch_limit_exceeds_measured_worst_case(self):
        """The 2026-07-27 universe-refresh fetch ran 4h30m and SUCCEEDED. A limit
        at or below that turns the watchdog itself into the outage."""
        measured_worst_case_minutes = 270  # 4h30m, observed
        limit = _step("fetch-data").max_running_minutes
        assert limit is not None, "fetch-data must keep a hang watchdog"
        assert limit > measured_worst_case_minutes, (
            f"fetch watchdog {limit}m does not cover the measured {measured_worst_case_minutes}m "
            "universe-refresh fetch — it will coerce a working fetch to 'failed'"
        )

    def test_fetch_limit_is_env_tunable(self):
        """Re-tuning the limit on the NAS must not require a code change — the
        next surprise fetch duration should be a config edit, not a redeploy."""
        src = (Path(__file__).resolve().parents[2] / "services" / "scheduler"
               / "app" / "main.py").read_text()
        assert "FETCH_MAX_RUNNING_MINUTES" in src
        assert 'os.getenv("FETCH_MAX_RUNNING_MINUTES", "480")' in src, (
            "fetch watchdog must read FETCH_MAX_RUNNING_MINUTES with a documented default"
        )


# ── Bug B: run-now must not redo a finished fetch ────────────────────────────

class TestRunNowDoesNotRefetch:
    def _reset(self):
        _G["_chain_status"].update({
            "status": "idle", "date": "2026-07-27", "steps": {}, "run_ids": {},
            "last_completed": None, "current_run_id": None, "next_run": None,
            "origin": "scheduled", "config_hash": None,
        })
        _G["_force_pending"].clear()
        _G["_no_rerun_when_done"].clear()

    async def _tick_with(self, state, trigger):
        with patch.dict(_G, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value=state),
            "_trigger_step": trigger,
            "_get_latest_run_id": AsyncMock(return_value="fake-run-id"),
            "_db_open_run": AsyncMock(return_value="run-uuid-1"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()

    @pytest.mark.asyncio
    async def test_done_fetch_is_not_re_triggered(self):
        """The session's bars are already ingested → advance, do not re-ingest."""
        self._reset()
        _G["_force_pending"].update(s.name for s in _STEPS)
        _G["_no_rerun_when_done"].update(_NO_RERUN_WHEN_DONE)

        trigger = AsyncMock(return_value=True)
        await self._tick_with("done", trigger)

        triggered = [c.args[1].name for c in trigger.call_args_list]
        assert "fetch-data" not in triggered, (
            "run-now re-triggered a fetch that already has this session's data — "
            "that is the multi-hour restart loop"
        )
        # ...and the flag is drained so the step does not linger pending forever.
        assert "fetch-data" not in _G["_force_pending"]

    @pytest.mark.asyncio
    async def test_chain_advances_to_pipeline_after_done_fetch(self):
        """Suppressing the fetch must not stall the chain: the very next step in
        the same tick is the pipeline, force-re-run as a manual run should."""
        self._reset()
        _G["_force_pending"].update(s.name for s in _STEPS)
        _G["_no_rerun_when_done"].update(_NO_RERUN_WHEN_DONE)

        trigger = AsyncMock(return_value=True)
        await self._tick_with("done", trigger)

        assert trigger.call_count == 1
        assert trigger.call_args.args[1].name == "pipeline"
        assert trigger.call_args.kwargs.get("force") is True

    @pytest.mark.asyncio
    async def test_failed_fetch_is_still_force_retried(self):
        """Suppression applies ONLY to work that is already done. A fetch that
        genuinely failed must still self-heal on a manual run."""
        self._reset()
        _G["_force_pending"].update(s.name for s in _STEPS)
        _G["_no_rerun_when_done"].update(_NO_RERUN_WHEN_DONE)

        trigger = AsyncMock(return_value=True)
        await self._tick_with("failed", trigger)

        assert trigger.call_count == 1
        assert trigger.call_args.args[1].name == "fetch-data"
        assert trigger.call_args.kwargs.get("force") is True

    @pytest.mark.asyncio
    async def test_refetch_opt_in_re_triggers_done_fetch(self):
        """An explicit re-ingest is still possible (suspected bad/partial fetch)."""
        self._reset()
        _G["_force_pending"].update(s.name for s in _STEPS)
        # refetch=true → nothing suppressed
        trigger = AsyncMock(return_value=True)
        await self._tick_with("done", trigger)

        assert trigger.call_args.args[1].name == "fetch-data"


class TestRunNowHandler:
    def _reset(self):
        _G["_chain_status"].update({
            "status": "idle", "date": "2026-07-27", "steps": {}, "run_ids": {},
            "last_completed": None, "current_run_id": None, "next_run": None,
            "origin": "scheduled", "config_hash": None,
        })
        _G["_force_pending"].clear()
        _G["_no_rerun_when_done"].clear()

    @pytest.mark.asyncio
    async def test_default_suppresses_fetch_and_forces_strategy_segment(self):
        self._reset()
        bg = MagicMock()
        with patch.dict(_G, {"_db_close_run": AsyncMock(), "_run_supervised_fast": AsyncMock()}):
            resp = await run_now(bg)

        assert resp["status"] == "started"
        assert resp["refetch"] is False
        assert "fetch-data" not in resp["forced_steps"]
        assert set(_STRATEGY_STEPS) <= set(resp["forced_steps"]), (
            "a manual run must still re-run pipeline→vet→build→delta; that is its purpose"
        )
        # Every step stays eligible for the FAILED self-heal retry.
        assert _G["_force_pending"] == {s.name for s in _STEPS}
        assert _G["_no_rerun_when_done"] == set(_NO_RERUN_WHEN_DONE)

    @pytest.mark.asyncio
    async def test_refetch_true_clears_suppression(self):
        self._reset()
        bg = MagicMock()
        with patch.dict(_G, {"_db_close_run": AsyncMock(), "_run_supervised_fast": AsyncMock()}):
            resp = await run_now(bg, refetch=True)

        assert resp["refetch"] is True
        assert "fetch-data" in resp["forced_steps"]
        assert _G["_no_rerun_when_done"] == set()


def test_only_fetch_data_is_suppressed():
    """Guard against the suppression quietly widening: every strategy step must
    remain re-runnable, or a manual run stops picking up config changes."""
    assert _NO_RERUN_WHEN_DONE == frozenset({"fetch-data"})
    assert not (_NO_RERUN_WHEN_DONE & set(_STRATEGY_STEPS))
