"""
Red-team regression tests for three confirmed scheduler bugs.

B1 (re-trigger loop): an UPSTREAM_RANK step whose data-date reference
    (latest_rank_date) is None — e.g. on ANY DB error in _latest_rank_date —
    must NOT fall back to comparing its data-date against wall-clock `today`.
    It falls back to the SESSION date (data-date vs data-date); if that too is
    unavailable it returns "blocked" and is NOT re-triggered.

B2 (run-now race): /jobs/run-now resets _chain_status/_force_pending under
    _chain_lock so a concurrent cron _supervisor_tick cannot interleave between
    clearing current_run_id and the new chain opening.

B3 (breaker defeated): the crash-loop breaker dedups distinct crash cycles by
    the orphan's run_id (unique per attempt), not started_at (which collapsed to
    run_date when absent → counter capped at 1, breaker never fired). When no
    run_id is available the cycle is COUNTED anyway (never dedup-skipped), and the
    per-(step, run_date) bookkeeping is cleared on a clean success.
"""
import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


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

from app.main import (  # noqa: E402
    DateAnchor,
    MAX_RESTART_ABORT_RETRIES,
    _StepDef,
    _STEPS,
    _clear_restart_abort_state,
    _step_state,
    run_now,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_response(payload: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.text = ""
    return resp


def _async_client_returning(payload: dict, status_code: int = 200):
    resp = _mock_response(payload, status_code)
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.post = AsyncMock(return_value=resp)
    return client


def _g():
    # Reach the exact module-level dicts _step_state mutates (the scheduler
    # conftest's del sys.modules can otherwise hand back a parallel module copy).
    return _step_state.__globals__


@pytest.fixture(autouse=True)
def _reset_globals():
    g = _g()
    for name in ("_last_trigger_at", "_restart_abort_cycles", "_restart_abort_seen"):
        if name in g:
            g[name].clear()
    yield


def _upstream_step():
    return _StepDef(
        name="portfolio-builder", url="http://fake", start_path="/jobs/build",
        date_field="portfolio_date", date_anchor=DateAnchor.UPSTREAM_RANK,
    )


def _aborted_payload(*, run_id=None, run_date="2026-05-21", started_at="2026-05-21T10:00:00Z"):
    from stock_strategy_shared.tracing import RESTART_ABORT_MARKER
    p = {
        "status": "failed",
        "run_date": run_date,
        "started_at": started_at,
        "error_message": f"{RESTART_ABORT_MARKER} restarted mid-run",
    }
    if run_id is not None:
        p["run_id"] = run_id
    return p


# ── B1: UPSTREAM_RANK must never compare against wall-clock today ──────────────

class TestB1NoWallClockFallback:
    @pytest.mark.asyncio
    async def test_none_rank_date_no_session_is_blocked_not_idle_or_done(self):
        """latest_rank_date=None AND session=None (DB outage): the step's data-date
        equals wall-clock today, which under the OLD bug matched today → 'done'/'idle'
        and re-triggered. Now it must return 'blocked' and be left for the next tick."""
        client = _async_client_returning({"status": "success", "portfolio_date": "2026-05-27"})
        state = await _step_state(
            client, _upstream_step(),
            today="2026-05-27", trading_day="2026-05-27", prev_trading_day="2026-05-26",
            latest_rank_date=None, session=None,
        )
        assert state == "blocked"
        assert state not in ("idle", "done")

    @pytest.mark.asyncio
    async def test_none_rank_date_falls_back_to_session_done(self):
        """With latest_rank_date=None the step compares against the SESSION date (a
        data-date), NOT today — matching session reads 'done'."""
        client = _async_client_returning({"status": "success", "portfolio_date": "2026-05-26"})
        state = await _step_state(
            client, _upstream_step(),
            today="2026-05-27", trading_day="2026-05-27", prev_trading_day="2026-05-25",
            latest_rank_date=None, session="2026-05-26",
        )
        assert state == "done"

    @pytest.mark.asyncio
    async def test_none_rank_date_session_mismatch_is_idle(self):
        """Falling back to session still re-triggers (idle) when the step lags the
        session — but it is the SESSION data-date driving that, never wall-clock today."""
        client = _async_client_returning({"status": "success", "portfolio_date": "2026-05-25"})
        state = await _step_state(
            client, _upstream_step(),
            today="2026-05-27", trading_day="2026-05-27", prev_trading_day="2026-05-24",
            latest_rank_date=None, session="2026-05-26",
        )
        assert state == "idle"

    @pytest.mark.asyncio
    async def test_running_orphan_with_no_refs_stays_running(self):
        """A running job with neither rank_date nor session still reports running —
        it must not be re-triggered as idle."""
        client = _async_client_returning({"status": "running", "portfolio_date": "2026-05-27"})
        state = await _step_state(
            client, _upstream_step(),
            today="2026-05-27", trading_day="2026-05-27", prev_trading_day="2026-05-26",
            latest_rank_date=None, session=None,
        )
        assert state == "running"


# ── B3: crash-loop breaker actually fires; dedup by run_id; state is cleared ───

class TestB3BreakerFires:
    def _step(self):
        return _StepDef(name="pipeline", url="http://fake", start_path="/jobs/run", date_field="run_date")

    @pytest.mark.asyncio
    async def test_distinct_run_ids_trip_the_breaker(self):
        step = self._step()
        results = []
        for i in range(MAX_RESTART_ABORT_RETRIES + 1):
            client = _async_client_returning(_aborted_payload(run_id=f"run-{i}"))
            results.append(await _step_state(client, step, "2026-05-21", "2026-05-21", "2026-05-20"))
        assert results[:MAX_RESTART_ABORT_RETRIES] == ["idle"] * MAX_RESTART_ABORT_RETRIES
        assert results[-1] == "failed"

    @pytest.mark.asyncio
    async def test_no_run_id_counts_every_cycle_and_trips(self):
        """B3 core: started_at-less / run_id-less orphans must NOT collapse to a
        single cycle (the old defeat). With no run_id to dedup, COUNT every
        observation so the breaker still fires."""
        step = self._step()
        payload = _aborted_payload(run_id=None)  # identical every call, no run_id
        results = [
            await _step_state(_async_client_returning(payload), step, "2026-05-21", "2026-05-21", "2026-05-20")
            for _ in range(MAX_RESTART_ABORT_RETRIES + 2)
        ]
        assert "failed" in results, f"breaker must fire without a run_id, got {results}"

    @pytest.mark.asyncio
    async def test_same_run_id_across_ticks_counts_once(self):
        step = self._step()
        payload = _aborted_payload(run_id="run-stable")
        results = [
            await _step_state(_async_client_returning(payload), step, "2026-05-21", "2026-05-21", "2026-05-20")
            for _ in range(MAX_RESTART_ABORT_RETRIES + 5)
        ]
        assert results == ["idle"] * len(results)

    @pytest.mark.asyncio
    async def test_clean_success_clears_both_dicts(self):
        step = self._step()
        # Two distinct crash cycles, not yet at the limit.
        for i in range(2):
            await _step_state(
                _async_client_returning(_aborted_payload(run_id=f"run-{i}")),
                step, "2026-05-21", "2026-05-21", "2026-05-20",
            )
        g = _g()
        assert g["_restart_abort_cycles"].get(("pipeline", "2026-05-21")) == 2
        assert ("pipeline", "2026-05-21") in g["_restart_abort_seen"]
        # A clean success must clear BOTH the cycle count and the seen-token set.
        ok = await _step_state(
            _async_client_returning({"status": "success", "run_date": "2026-05-21"}),
            step, "2026-05-21", "2026-05-21", "2026-05-20",
        )
        assert ok == "done"
        assert ("pipeline", "2026-05-21") not in g["_restart_abort_cycles"]
        assert ("pipeline", "2026-05-21") not in g["_restart_abort_seen"]

    def test_clear_helper_drops_all_run_dates_for_step(self):
        g = _g()
        g["_restart_abort_cycles"].update({
            ("pipeline", "2026-05-20"): 1,
            ("pipeline", "2026-05-21"): 2,
            ("vet", "2026-05-21"): 1,
        })
        g["_restart_abort_seen"].update({
            ("pipeline", "2026-05-20"): {"a"},
            ("pipeline", "2026-05-21"): {"b"},
            ("vet", "2026-05-21"): {"c"},
        })
        _clear_restart_abort_state("pipeline")
        # All pipeline keys gone (across every run_date); other steps untouched.
        assert not any(k[0] == "pipeline" for k in g["_restart_abort_cycles"])
        assert not any(k[0] == "pipeline" for k in g["_restart_abort_seen"])
        assert ("vet", "2026-05-21") in g["_restart_abort_cycles"]
        assert ("vet", "2026-05-21") in g["_restart_abort_seen"]


# ── B2: run-now resets chain state under _chain_lock (no interleave with ticks) ─

class TestB2RunNowUnderLock:
    @pytest.mark.asyncio
    async def test_run_now_holds_chain_lock_during_reset(self):
        """If a cron _supervisor_tick is mid-flight (holding _chain_lock), run_now's
        reset must wait for it — proving the mutation is serialized w.r.t. ticks and
        cannot interleave between clearing current_run_id and opening the new chain."""
        g = _step_state.__globals__
        chain_lock = g["_chain_lock"]
        chain_status = g["_chain_status"]
        force_pending = g["_force_pending"]
        run_now_lock = g["_run_now_lock"]

        # Ensure a clean starting point.
        run_now_lock._locked = False if hasattr(run_now_lock, "_locked") else None
        force_pending.clear()
        chain_status.update({"current_run_id": "stale-cron-run", "origin": "scheduled",
                             "status": "running", "steps": {"x": "running"}})

        observed_during_lock = {}

        bg = MagicMock()
        bg.add_task = MagicMock()

        async def call_run_now():
            return await run_now(bg)

        # Hold _chain_lock to simulate an in-flight cron tick, kick off run_now,
        # confirm it has NOT yet mutated state (it is blocked on the lock), then
        # release and let it complete.
        async with chain_lock:
            task = asyncio.create_task(call_run_now())
            await asyncio.sleep(0.05)
            # While we hold the lock, run_now must be blocked → state unchanged.
            observed_during_lock["current_run_id"] = chain_status.get("current_run_id")
            observed_during_lock["origin"] = chain_status.get("origin")
        result = await task

        assert observed_during_lock["current_run_id"] == "stale-cron-run", (
            "run_now mutated _chain_status while a tick held _chain_lock — the race is not fixed"
        )
        assert observed_during_lock["origin"] == "scheduled"
        # After the lock released, run_now completed the reset atomically.
        assert result["status"] == "started"
        assert chain_status.get("current_run_id") is None
        assert chain_status.get("origin") == "manual"
        assert force_pending == {s.name for s in _STEPS}

    @pytest.mark.asyncio
    async def test_run_now_returns_already_running_when_run_now_lock_held(self):
        g = _step_state.__globals__
        run_now_lock = g["_run_now_lock"]
        bg = MagicMock()
        bg.add_task = MagicMock()
        async with run_now_lock:
            result = await run_now(bg)
        assert result == {"status": "already_running"}
