"""
Tests for the non-blocking supervisor pattern in app.main.

We stub out apscheduler before importing so the module can be loaded without
the real package and without needing a running event loop during import.
"""
import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Stub out apscheduler so app.main can be imported without the real package ──

def _make_apscheduler_stubs():
    """Insert lightweight stubs for apscheduler modules into sys.modules."""
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
    _StepDef,
    _STEPS,
    _chain_status,
    _restore_force_pending,
    _run_supervised_fast,
    _step_state,
    _supervisor_tick,
    run_now,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_response(status_code: int = 200, payload: dict | None = None):
    """Build a minimal mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload or {}
    resp.text = ""
    return resp


def _async_client_returning(payload: dict, status_code: int = 200):
    """Return an AsyncMock httpx.AsyncClient whose GET/POST return the given payload."""
    resp = _mock_response(status_code, payload)
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.post = AsyncMock(return_value=resp)
    return client


# ── TestStepState ─────────────────────────────────────────────────────────────

class TestStepState:

    def _make_step(self, **kwargs) -> _StepDef:
        defaults = dict(
            name="test-step",
            url="http://fake",
            start_path="/jobs/run",
            date_field="run_date",
        )
        defaults.update(kwargs)
        return _StepDef(**defaults)

    @pytest.mark.asyncio
    async def test_done_on_success(self):
        """Service returns status=success with correct date → 'done'."""
        today = "2026-05-21"
        step = self._make_step()
        client = _async_client_returning({"status": "success", "run_date": today})
        result = await _step_state(client, step, today, today, "2026-05-20")
        assert result == "done"

    @pytest.mark.asyncio
    async def test_done_on_extra_ok(self):
        """Service returns status=partial_success, which is in extra_ok → 'done'."""
        today = "2026-05-21"
        step = self._make_step(extra_ok=("partial_success",))
        client = _async_client_returning({"status": "partial_success", "run_date": today})
        result = await _step_state(client, step, today, today, "2026-05-20")
        assert result == "done"

    @pytest.mark.asyncio
    async def test_running(self):
        """Service returns status=running with correct date → 'running'."""
        today = "2026-05-21"
        step = self._make_step()
        client = _async_client_returning({"status": "running", "run_date": today})
        result = await _step_state(client, step, today, today, "2026-05-20")
        assert result == "running"

    @pytest.mark.asyncio
    async def test_failed(self):
        """Service returns status=failed with correct date → 'failed'."""
        today = "2026-05-21"
        step = self._make_step()
        client = _async_client_returning({"status": "failed", "run_date": today})
        result = await _step_state(client, step, today, today, "2026-05-20")
        assert result == "failed"

    @pytest.mark.asyncio
    async def test_restart_aborted_failed_treated_as_idle(self):
        """Regression: when a service was killed mid-run (e.g. user `docker compose down`),
        its startup orphan cleanup marks the row 'failed' with RESTART_ABORT_MARKER in
        error_message. The scheduler must treat this as recoverable ('idle' → re-trigger)
        rather than as a real failure (chain suspended until tomorrow)."""
        from stock_strategy_shared.tracing import RESTART_ABORT_MARKER
        today = "2026-05-21"
        step = self._make_step()
        client = _async_client_returning({
            "status": "failed",
            "run_date": today,
            "error_message": f"{RESTART_ABORT_MARKER} service restarted while run was active",
        })
        result = await _step_state(client, step, today, today, "2026-05-20")
        assert result == "idle", (
            "restart-aborted runs must be treated as idle so the supervisor re-triggers "
            "instead of suspending the chain until midnight"
        )

    @pytest.mark.asyncio
    async def test_real_failure_still_blocks_chain(self):
        """Sanity: a 'failed' row WITHOUT the restart-abort marker is still treated as
        a real failure — the chain should suspend, not silently re-trigger every tick."""
        today = "2026-05-21"
        step = self._make_step()
        client = _async_client_returning({
            "status": "failed",
            "run_date": today,
            "error_message": "Connection refused by Alpha Vantage API",
        })
        result = await _step_state(client, step, today, today, "2026-05-20")
        assert result == "failed"

    @pytest.mark.asyncio
    async def test_idle_wrong_date(self):
        """Status is success but date is yesterday → 'idle'."""
        today = "2026-05-21"
        step = self._make_step()
        client = _async_client_returning({"status": "success", "run_date": "2026-05-20"})
        result = await _step_state(client, step, today, today, "2026-05-19")
        assert result == "idle"

    @pytest.mark.asyncio
    async def test_stale_running_across_midnight_marked_failed(self):
        """Regression: a job that started yesterday and is still 'running' today must be
        treated as failed by the max_running_minutes guard, even though its run_date
        does not match today. Without this, _step_state used to early-return 'idle'
        and the supervisor would attempt to re-trigger the step forever while the
        original stuck job kept its lock — silently neutralising the timeout."""
        from datetime import datetime, timedelta, timezone
        yesterday_late = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        step = self._make_step(max_running_minutes=90, date_field="started_at")
        client = _async_client_returning({"status": "running", "started_at": yesterday_late})
        result = await _step_state(client, step, today, today, yesterday)
        assert result == "failed", (
            "stale running job spanning midnight must be marked failed so the chain "
            "can advance, regardless of run_date mismatch"
        )

    @pytest.mark.asyncio
    async def test_recent_running_within_limit_stays_running(self):
        """Sanity check: a job that started 30 min ago with a 90-min limit stays 'running'."""
        from datetime import datetime, timedelta, timezone
        recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        step = self._make_step(max_running_minutes=90, date_field="started_at")
        client = _async_client_returning({"status": "running", "started_at": recent})
        result = await _step_state(client, step, today, today, today)
        assert result == "running"

    @pytest.mark.asyncio
    async def test_idle_wrong_job_type(self):
        """Status ok, date ok, but job_type doesn't match → 'idle'."""
        today = "2026-05-21"
        step = self._make_step(job_type="fetch-data")
        client = _async_client_returning({
            "status": "success",
            "run_date": today,
            "job_type": "fetch-prices",  # wrong type
        })
        result = await _step_state(client, step, today, today, "2026-05-20")
        assert result == "idle"

    @pytest.mark.asyncio
    async def test_idle_on_http_error(self):
        """Service returns 500 → 'idle'."""
        today = "2026-05-21"
        step = self._make_step()
        client = _async_client_returning({}, status_code=500)
        result = await _step_state(client, step, today, today, "2026-05-20")
        assert result == "idle"

    @pytest.mark.asyncio
    async def test_idle_on_exception(self):
        """Network exception → 'idle'."""
        today = "2026-05-21"
        step = self._make_step()
        client = MagicMock()
        client.get = AsyncMock(side_effect=Exception("connection refused"))
        result = await _step_state(client, step, today, today, "2026-05-20")
        assert result == "idle"

    @pytest.mark.asyncio
    async def test_idle_on_empty_payload(self):
        """Service returns {} (no status, no date) — must not raise and must
        not classify as 'done' or 'running'. Defensive against an upstream
        service that returns a malformed response during a deploy."""
        today = "2026-05-21"
        step = self._make_step()
        client = _async_client_returning({})
        result = await _step_state(client, step, today, today, "2026-05-20")
        assert result == "idle"

    @pytest.mark.asyncio
    async def test_idle_on_status_none(self):
        """status=None should be treated as idle, not done/running/failed."""
        today = "2026-05-21"
        step = self._make_step()
        client = _async_client_returning({"status": None, "run_date": today})
        result = await _step_state(client, step, today, today, "2026-05-20")
        assert result == "idle"

    @pytest.mark.asyncio
    async def test_idle_on_unknown_status(self):
        """An unexpected status string (e.g. 'cancelled') falls through to idle."""
        today = "2026-05-21"
        step = self._make_step()
        client = _async_client_returning({"status": "cancelled", "run_date": today})
        result = await _step_state(client, step, today, today, "2026-05-20")
        assert result == "idle"

    @pytest.mark.asyncio
    async def test_trading_day_flag(self):
        """use_trading_day=True: date comparison uses trading_day, not today."""
        today = "2026-05-21"           # Thursday
        trading_day = "2026-05-21"
        step = self._make_step(date_field="score_date", use_trading_day=True)
        # Payload date matches trading_day → done
        client = _async_client_returning({"status": "success", "score_date": trading_day})
        result = await _step_state(client, step, today, trading_day, "2026-05-20")
        assert result == "done"

    @pytest.mark.asyncio
    async def test_also_accept_prev(self):
        """also_accept_prev=True: prev_trading_day is also accepted as a valid date."""
        today = "2026-05-21"
        trading_day = "2026-05-21"
        prev_trading_day = "2026-05-20"
        step = self._make_step(date_field="score_date", use_trading_day=True, also_accept_prev=True)
        # Payload uses prev trading day → still done
        client = _async_client_returning({"status": "success", "score_date": prev_trading_day})
        result = await _step_state(client, step, today, trading_day, prev_trading_day)
        assert result == "done"

    @pytest.mark.asyncio
    async def test_upstream_rank_date_done_on_match(self):
        """use_upstream_rank_date=True: 'done' when step's date matches latest rank_date
        even though it lags trading_day. Stops the post-close pre-AV-publish retrigger loop.
        """
        today = "2026-05-27"
        trading_day = "2026-05-27"
        prev_trading_day = "2026-05-26"
        latest_rank_date = "2026-05-26"  # SPY data still at yesterday
        step = self._make_step(date_field="portfolio_date", use_upstream_rank_date=True)
        client = _async_client_returning({"status": "success", "portfolio_date": latest_rank_date})
        result = await _step_state(client, step, today, trading_day, prev_trading_day,
                                   latest_rank_date=latest_rank_date)
        assert result == "done"

    @pytest.mark.asyncio
    async def test_upstream_rank_date_idle_on_stale(self):
        """use_upstream_rank_date=True: 'idle' when step lags the latest rank_date.
        New ranking has landed; step needs to re-run against it.
        """
        today = "2026-05-27"
        trading_day = "2026-05-27"
        prev_trading_day = "2026-05-26"
        latest_rank_date = "2026-05-27"
        step = self._make_step(date_field="portfolio_date", use_upstream_rank_date=True)
        # Step's last run was against yesterday's ranking
        client = _async_client_returning({"status": "success", "portfolio_date": "2026-05-26"})
        result = await _step_state(client, step, today, trading_day, prev_trading_day,
                                   latest_rank_date=latest_rank_date)
        assert result == "idle"

    @pytest.mark.asyncio
    async def test_upstream_rank_date_fallback_when_no_ranking(self):
        """use_upstream_rank_date=True but latest_rank_date=None (no ranking yet): falls
        back to trading_day so the chain still triggers ranking via the earlier steps.
        """
        today = "2026-05-27"
        trading_day = "2026-05-27"
        step = self._make_step(date_field="portfolio_date", use_upstream_rank_date=True)
        client = _async_client_returning({"status": "success", "portfolio_date": "2026-05-27"})
        result = await _step_state(client, step, today, trading_day, "2026-05-26",
                                   latest_rank_date=None)
        assert result == "done"


# ── TestSupervisorTick ────────────────────────────────────────────────────────

class TestSupervisorTick:
    """Tests for _supervisor_tick() decisions."""

    def _reset_chain_status(self, status="idle", chain_date=None):
        """Reset the shared _chain_status dict to a clean state.
        Use the globals dict of _supervisor_tick to get the same object the function mutates."""
        _supervisor_tick.__globals__["_chain_status"].update({
            "status": status,
            "date": chain_date or "2026-05-21",
            "steps": {},
            "run_ids": {},
            "last_completed": None,
            "current_run_id": None,
            "next_run": None,
        })
        # _force_pending is module-level mutable state shared across the supervisor.
        # Clear it so a prior run-now test can't leak forced steps into this one —
        # the failed-step self-heal branch now keys on _force_pending membership.
        _supervisor_tick.__globals__["_force_pending"].clear()

    @pytest.mark.asyncio
    async def test_triggers_first_step_when_idle(self):
        """All steps idle → triggers fetch-data (first step) and returns."""
        self._reset_chain_status()
        mock_trigger = AsyncMock()
        mock_db_open = AsyncMock(return_value="run-uuid-1")
        mock_db_update = AsyncMock()
        mock_db_close = AsyncMock()
        mock_get_run_id = AsyncMock(return_value=None)

        with (
            patch.dict(_supervisor_tick.__globals__, {
                "_has_universe": AsyncMock(return_value=True),
                "_step_state": AsyncMock(return_value="idle"),
                "_trigger_step": mock_trigger,
                "_get_latest_run_id": mock_get_run_id,
                "_db_open_run": mock_db_open,
                "_db_update_run": mock_db_update,
                "_db_close_run": mock_db_close,
                "_is_after_scheduled_time": MagicMock(return_value=True),
                "_latest_rank_date": AsyncMock(return_value=None),
            }),
        ):
            await _supervisor_tick()

        # Should have triggered the first step (fetch-data)
        assert mock_trigger.call_count == 1
        triggered_step = mock_trigger.call_args[0][1]
        assert triggered_step.name == "fetch-data"
        # Chain should be running, not complete
        assert _chain_status["status"] == "running"

    @pytest.mark.asyncio
    async def test_waits_when_first_step_running(self):
        """fetch-data is running → does not trigger anything, returns immediately."""
        self._reset_chain_status()
        mock_trigger = AsyncMock()
        mock_db_open = AsyncMock(return_value="run-uuid-1")
        mock_db_update = AsyncMock()

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="running"),
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value=None),
            "_db_open_run": mock_db_open,
            "_db_update_run": mock_db_update,
            "_db_close_run": AsyncMock(),
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()

        mock_trigger.assert_not_called()
        assert _chain_status["status"] == "running"

    @pytest.mark.asyncio
    async def test_advances_to_second_step(self):
        """fetch-data done, all others idle → triggers factor-calculate."""
        self._reset_chain_status()

        call_count = [0]

        async def _fake_step_state(client, step, today, trading_day, prev_trading_day, latest_rank_date=None):
            call_count[0] += 1
            if step.name == "fetch-data":
                return "done"
            return "idle"

        mock_trigger = AsyncMock()

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": _fake_step_state,
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value=None),
            "_db_open_run": AsyncMock(return_value="run-uuid-1"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()

        assert mock_trigger.call_count == 1
        triggered_step = mock_trigger.call_args[0][1]
        assert triggered_step.name == "pipeline"

    @pytest.mark.asyncio
    async def test_suspends_on_required_failure(self):
        """fetch-data failed (required) → marks chain failed, does not trigger next step."""
        self._reset_chain_status()
        mock_trigger = AsyncMock()
        mock_db_close = AsyncMock()

        async def _fake_step_state(client, step, today, trading_day, prev_trading_day, latest_rank_date=None):
            if step.name == "fetch-data":
                return "failed"
            return "idle"

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": _fake_step_state,
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value=None),
            "_db_open_run": AsyncMock(return_value="run-uuid-1"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": mock_db_close,
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()

        mock_trigger.assert_not_called()
        assert _chain_status["status"] == "failed"
        mock_db_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_vet_failure_fails_chain(self):
        """vet failed (optional=False) → chain fails, portfolio-builder is never triggered."""
        self._reset_chain_status()
        mock_trigger = AsyncMock()
        mock_db_close = AsyncMock()

        async def _fake_step_state(client, step, today, trading_day, prev_trading_day, latest_rank_date=None):
            if step.name in ("fetch-data", "pipeline"):
                return "done"
            if step.name == "vet":
                return "failed"
            return "idle"

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": _fake_step_state,
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value=None),
            "_db_open_run": AsyncMock(return_value="run-uuid-1"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": mock_db_close,
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()

        # vet is mandatory — failure must halt the chain
        mock_trigger.assert_not_called()
        assert _chain_status["status"] == "failed"
        mock_db_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_now_self_heals_failed_step(self):
        """A step that failed earlier today but is queued by run-now (_force_pending)
        must be re-triggered, not suspend the chain — so a fixed-and-redeployed bug
        recovers without waiting for midnight or manually clearing the failed row."""
        self._reset_chain_status()
        mock_trigger = AsyncMock(return_value=True)
        mock_db_close = AsyncMock()

        async def _fake_step_state(client, step, today, trading_day, prev_trading_day, latest_rank_date=None):
            if step.name in ("fetch-data", "pipeline"):
                return "done"
            if step.name == "vet":
                return "failed"
            return "idle"

        force_pending = _supervisor_tick.__globals__["_force_pending"]
        force_pending.clear()
        force_pending.add("vet")
        try:
            with patch.dict(_supervisor_tick.__globals__, {
                "_has_universe": AsyncMock(return_value=True),
                "_step_state": _fake_step_state,
                "_trigger_step": mock_trigger,
                "_get_latest_run_id": AsyncMock(return_value=None),
                "_db_open_run": AsyncMock(return_value="run-uuid-1"),
                "_db_update_run": AsyncMock(),
                "_db_close_run": mock_db_close,
                "_is_after_scheduled_time": MagicMock(return_value=True),
                "_latest_rank_date": AsyncMock(return_value=None),
            }):
                await _supervisor_tick()

            # vet was re-triggered (not suspended); chain stays running
            mock_trigger.assert_awaited_once()
            assert mock_trigger.await_args.args[1].name == "vet"
            assert _chain_status["status"] == "running"
            mock_db_close.assert_not_called()
            # the forced retry is consumed, so a second consecutive failure falls
            # through to suspend instead of looping forever
            assert "vet" not in force_pending
        finally:
            force_pending.clear()

    @pytest.mark.asyncio
    async def test_marks_success_when_all_done(self):
        """All steps done → marks chain success, fires alpaca sync task."""
        self._reset_chain_status()
        mock_db_close = AsyncMock()
        create_task_calls = []

        def _consume_create_task(coro):
            """Close the coroutine instead of scheduling it, to avoid RuntimeWarning."""
            create_task_calls.append(coro)
            if hasattr(coro, "close"):
                coro.close()
            return MagicMock()

        class _FakeAsyncio:
            @staticmethod
            def create_task(coro):
                return _consume_create_task(coro)

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="done"),
            "_trigger_step": AsyncMock(),
            "_get_latest_run_id": AsyncMock(return_value="fake-run-id"),
            "_db_open_run": AsyncMock(return_value="run-uuid-1"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": mock_db_close,
            "asyncio": _FakeAsyncio,
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()

        assert _supervisor_tick.__globals__["_chain_status"]["status"] == "success"
        mock_db_close.assert_called_once()
        # create_task called once for alpaca sync fire-and-forget
        assert len(create_task_calls) == 1

    @pytest.mark.asyncio
    async def test_triggers_fetch_universe_when_no_universe(self):
        """has_universe=False and no prior run → triggers fetch-universe and returns early."""
        self._reset_chain_status()
        mock_trigger = AsyncMock()
        mock_db_open = AsyncMock(return_value=None)

        # Build a fake httpx async context manager; GET /runs/latest returns 404
        # (no prior run), POST /jobs/fetch-universe returns 200.
        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fetch_universe_resp = _mock_response(200, {"status": "started"})
        fake_client.post = AsyncMock(return_value=fetch_universe_resp)
        fake_client.get = AsyncMock(return_value=_mock_response(404, {}))

        with (
            patch.dict(_supervisor_tick.__globals__, {
                "_has_universe": AsyncMock(return_value=False),
                "_step_state": AsyncMock(return_value="idle"),
                "_trigger_step": mock_trigger,
                "_db_open_run": mock_db_open,
                "_db_update_run": AsyncMock(),
                "_db_close_run": AsyncMock(),
                "_is_after_scheduled_time": MagicMock(return_value=True),
                "_latest_rank_date": AsyncMock(return_value=None),
            }),
            patch("httpx.AsyncClient", return_value=fake_client),
        ):
            await _supervisor_tick()

        # _trigger_step (for pipeline steps) should NOT be called
        mock_trigger.assert_not_called()
        # fetch-universe POST should have been called
        fake_client.post.assert_called_once()
        post_url = fake_client.post.call_args[0][0]
        assert "fetch-universe" in post_url
        assert _chain_status["status"] == "running"

    @pytest.mark.asyncio
    async def test_marks_chain_failed_when_fetch_universe_failed(self):
        """has_universe=False and last fetch-universe run failed → chain marked failed,
        no new trigger fired.

        Regression test: previously the supervisor had no failure detection in the
        cold-start guard and would re-trigger fetch-universe on every tick forever,
        producing an infinite retry loop when AV_API_KEY is missing.
        """
        self._reset_chain_status()
        mock_trigger = AsyncMock()
        mock_db_open = AsyncMock(return_value=None)

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        # GET /runs/latest returns a failed fetch-universe run
        failed_run_resp = _mock_response(200, {"job_type": "fetch-universe", "status": "failed"})
        fake_client.get = AsyncMock(return_value=failed_run_resp)
        fake_client.post = AsyncMock()

        with (
            patch.dict(_supervisor_tick.__globals__, {
                "_has_universe": AsyncMock(return_value=False),
                "_step_state": AsyncMock(return_value="idle"),
                "_trigger_step": mock_trigger,
                "_db_open_run": mock_db_open,
                "_db_update_run": AsyncMock(),
                "_db_close_run": AsyncMock(),
                "_is_after_scheduled_time": MagicMock(return_value=True),
                "_latest_rank_date": AsyncMock(return_value=None),
            }),
            patch("httpx.AsyncClient", return_value=fake_client),
        ):
            await _supervisor_tick()

        # Chain must be marked failed — no re-trigger allowed
        assert _chain_status["status"] == "failed", (
            "fetch-universe failure must mark the chain as failed and stop the infinite "
            "retry loop — check AV_API_KEY / MOCK_DATA=true message should be logged"
        )
        mock_trigger.assert_not_called()
        fake_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_universe_restart_aborted_retriggers_not_fails(self):
        """has_universe=False, last fetch-universe failed with RESTART_ABORT_MARKER →
        re-trigger (not chain-suspend).

        Regression test: a service crash during the first universe fetch leaves
        ingest_runs.status='failed' with RESTART_ABORTED: prefix. Without the
        marker check the supervisor would treat that as a real failure and
        suspend the chain until midnight, blocking the very first cold-boot.
        """
        from stock_strategy_shared.tracing import RESTART_ABORT_MARKER
        self._reset_chain_status()
        mock_trigger = AsyncMock()
        mock_db_open = AsyncMock(return_value=None)

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        # GET /runs/latest returns a failed fetch-universe with the marker
        aborted_resp = _mock_response(200, {
            "job_type": "fetch-universe",
            "status": "failed",
            "error_message": f"{RESTART_ABORT_MARKER} service restarted while run was active",
        })
        fake_client.get = AsyncMock(return_value=aborted_resp)
        fake_client.post = AsyncMock(return_value=_mock_response(200, {"run_id": "new"}))

        with (
            patch.dict(_supervisor_tick.__globals__, {
                "_has_universe": AsyncMock(return_value=False),
                "_step_state": AsyncMock(return_value="idle"),
                "_trigger_step": mock_trigger,
                "_db_open_run": mock_db_open,
                "_db_update_run": AsyncMock(),
                "_db_close_run": AsyncMock(),
                "_is_after_scheduled_time": MagicMock(return_value=True),
                "_latest_rank_date": AsyncMock(return_value=None),
            }),
            patch("httpx.AsyncClient", return_value=fake_client),
        ):
            await _supervisor_tick()

        # Chain must NOT be failed; fetch-universe must be re-triggered via POST
        assert _chain_status["status"] != "failed", (
            "restart-aborted fetch-universe must be re-triggered, not chain-failed"
        )
        assert _chain_status["status"] == "running"
        # POST to /jobs/fetch-universe should have been called
        fake_client.post.assert_called_once()
        post_url = fake_client.post.call_args[0][0]
        assert "fetch-universe" in post_url

    @pytest.mark.asyncio
    async def test_waits_when_fetch_universe_already_running(self):
        """has_universe=False and fetch-universe is currently running → waits, no new trigger."""
        self._reset_chain_status()
        mock_trigger = AsyncMock()

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        running_resp = _mock_response(200, {"job_type": "fetch-universe", "status": "running"})
        fake_client.get = AsyncMock(return_value=running_resp)
        fake_client.post = AsyncMock()

        with (
            patch.dict(_supervisor_tick.__globals__, {
                "_has_universe": AsyncMock(return_value=False),
                "_step_state": AsyncMock(return_value="idle"),
                "_trigger_step": mock_trigger,
                "_db_open_run": AsyncMock(return_value=None),
                "_db_update_run": AsyncMock(),
                "_db_close_run": AsyncMock(),
                "_is_after_scheduled_time": MagicMock(return_value=True),
                "_latest_rank_date": AsyncMock(return_value=None),
            }),
            patch("httpx.AsyncClient", return_value=fake_client),
        ):
            await _supervisor_tick()

        assert _chain_status["status"] == "running"
        mock_trigger.assert_not_called()
        fake_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_chain_blocks_subsequent_ticks_same_day(self):
        """Once chain is marked failed today, further ticks return immediately.

        This verifies the retry-loop fix: after fetch-universe fails and the chain
        is set to 'failed', every subsequent supervisor tick for the same calendar
        day must return early without firing any new triggers.
        """
        import datetime
        today = datetime.date.today().isoformat()
        chain_status = _supervisor_tick.__globals__["_chain_status"]
        chain_status.update({
            "status": "failed",
            "date": today,
            "steps": {},
            "run_ids": {},
            "current_run_id": None,
        })

        mock_has_universe = AsyncMock(return_value=False)
        mock_trigger = AsyncMock()

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": mock_has_universe,
            "_trigger_step": mock_trigger,
        }):
            await _supervisor_tick()

        # has_universe and trigger_step must not be called — early exit on failed
        mock_has_universe.assert_not_called()
        mock_trigger.assert_not_called()
        assert chain_status["status"] == "failed"

    @pytest.mark.asyncio
    async def test_skips_tick_when_lock_held(self):
        """If the chain lock is already held, the tick returns without doing anything."""
        self._reset_chain_status()
        mock_has_universe = AsyncMock(return_value=True)

        # Acquire the lock from the same globals dict that _supervisor_tick uses,
        # so the same lock object is seen by the function's _chain_lock.locked() check.
        chain_lock = _supervisor_tick.__globals__["_chain_lock"]
        async with chain_lock:
            with patch.dict(_supervisor_tick.__globals__, {
                "_has_universe": mock_has_universe,
            }):
                await _supervisor_tick()

        # _has_universe should not have been called since we returned early
        mock_has_universe.assert_not_called()

    @pytest.mark.asyncio
    async def test_resets_state_on_date_change(self):
        """chain_status.date is yesterday → steps and run_ids reset for today."""
        # Use the _chain_status from the same globals dict that _supervisor_tick references
        chain_status = _supervisor_tick.__globals__["_chain_status"]
        chain_status.update({
            "date": "2026-05-20",  # yesterday
            "steps": {"fetch-data": "done"},
            "run_ids": {"fetch-data": "old-run"},
            "current_run_id": "old-db-run-id",
            "status": "success",
        })

        mock_trigger = AsyncMock()
        mock_db_open = AsyncMock(return_value="new-run-uuid")

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="idle"),
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value=None),
            "_db_open_run": mock_db_open,
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
        }):
            await _supervisor_tick()

        import datetime
        today = datetime.date.today().isoformat()
        assert chain_status["date"] == today
        # Old state from yesterday should be cleared (run_ids reset to {})
        assert chain_status.get("run_ids", {}).get("fetch-data") != "old-run"

    @pytest.mark.asyncio
    async def test_skips_after_success_same_day(self):
        """If today's chain already succeeded, the next tick must return
        without opening a new scheduler_runs row (no tick-spam after done)."""
        import datetime
        today = datetime.date.today().isoformat()
        chain_status = _supervisor_tick.__globals__["_chain_status"]
        chain_status.update({
            "status": "success",
            "date": today,
            "steps": {"fetch-data": "done", "pipeline": "done", "portfolio-builder": "done", "delta": "done", "vet": "done"},
            "run_ids": {},
            "current_run_id": None,
        })

        mock_db_open = AsyncMock()
        mock_db_update = AsyncMock()
        mock_db_close = AsyncMock()
        mock_trigger = AsyncMock()

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="done"),
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value=None),
            "_db_open_run": mock_db_open,
            "_db_update_run": mock_db_update,
            "_db_close_run": mock_db_close,
        }):
            await _supervisor_tick()

        # Nothing should fire — no DB rows opened/closed, no step triggered
        mock_db_open.assert_not_called()
        mock_db_close.assert_not_called()
        mock_trigger.assert_not_called()

    @pytest.mark.asyncio
    async def test_date_rollover_clears_failed_status(self):
        """Yesterday's 'failed' chain status must NOT block today's chain.

        Regression test for a bug where _chain_status['status'] was not reset
        on date rollover, causing the supervisor to return early on every tick
        for the entire following day.
        """
        import datetime
        chain_status = _supervisor_tick.__globals__["_chain_status"]
        chain_status.update({
            "status": "failed",     # yesterday ended in failure
            "date": "2026-05-20",   # yesterday's date
            "steps": {},
            "run_ids": {},
            "current_run_id": None,
        })

        mock_trigger = AsyncMock()
        mock_db_open = AsyncMock(return_value="new-run-uuid")

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="idle"),
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value=None),
            "_db_open_run": mock_db_open,
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()

        today = datetime.date.today().isoformat()
        assert chain_status["date"] == today
        assert chain_status["status"] != "failed", (
            "status must be cleared on date rollover — yesterday's 'failed' "
            "must not block today's chain"
        )
        # Supervisor should have triggered the first step
        mock_trigger.assert_called_once()

    @pytest.mark.asyncio
    async def test_date_rollover_closes_open_scheduler_run(self):
        """A chain that spans midnight while status='running' must have its
        scheduler_runs row closed when the date rolls over.

        Regression test: previously the rollover reset _chain_status["current_run_id"]
        to None without calling _db_close_run, leaving an orphaned status='running'
        row in scheduler_runs forever.
        """
        import datetime
        chain_status = _supervisor_tick.__globals__["_chain_status"]
        chain_status.update({
            "status": "running",          # yesterday's chain is still mid-run
            "date": "2026-05-20",         # yesterday's date
            "steps": {"fetch-data": "running"},
            "run_ids": {},
            "current_run_id": "yesterday-run-uuid",
        })

        mock_db_close = AsyncMock()
        mock_db_open = AsyncMock(return_value="today-run-uuid")

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="idle"),
            "_trigger_step": AsyncMock(),
            "_get_latest_run_id": AsyncMock(return_value=None),
            "_db_open_run": mock_db_open,
            "_db_update_run": AsyncMock(),
            "_db_close_run": mock_db_close,
        }):
            await _supervisor_tick()

        # The yesterday run-id must have been closed before opening today's.
        mock_db_close.assert_called_once()
        closed_run_id, closed_status, *_ = mock_db_close.call_args.args
        assert closed_run_id == "yesterday-run-uuid"
        # 'running' is not a terminal state — must coerce to failed on rollover
        assert closed_status == "failed", (
            "open scheduler_runs row from yesterday must close as 'failed' "
            "(not 'running') on midnight rollover"
        )

    @pytest.mark.asyncio
    async def test_date_rollover_clears_success_status(self):
        """Yesterday's 'success' must not prevent today's chain from running."""
        import datetime
        chain_status = _supervisor_tick.__globals__["_chain_status"]
        chain_status.update({
            "status": "success",    # yesterday succeeded
            "date": "2026-05-20",   # yesterday
            "steps": {},
            "run_ids": {},
            "current_run_id": None,
        })

        mock_trigger = AsyncMock()
        mock_db_open = AsyncMock(return_value="new-run-uuid")

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="idle"),
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value=None),
            "_db_open_run": mock_db_open,
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()

        today = datetime.date.today().isoformat()
        assert chain_status["date"] == today
        assert chain_status["status"] != "success" or mock_trigger.call_count > 0, (
            "Either status was cleared (allowing the chain to start) or "
            "the chain already processed the first idle step"
        )
        mock_trigger.assert_called_once()


# ── TestWeekendDateFields ─────────────────────────────────────────────────────

class TestWeekendDateFields:
    """
    Regression tests for the weekend cold-boot bug.

    On a Saturday, use_trading_day=True makes target = last Friday.  Steps that
    used started_at as date_field would compare Saturday's run timestamp against
    Friday's target and perpetually return 'idle', causing infinite re-triggering.

    portfolio-builder must use portfolio_date (the trading-day of the underlying
    data) and delta must use run_date.  Both are set to the last trading day by
    the respective services regardless of what calendar day they execute on.
    """

    def _make_step(self, **kwargs) -> _StepDef:
        defaults = dict(name="test-step", url="http://fake", start_path="/jobs/run",
                        date_field="run_date")
        defaults.update(kwargs)
        return _StepDef(**defaults)

    @pytest.mark.asyncio
    async def test_portfolio_builder_done_when_portfolio_date_matches_trading_day(self):
        """portfolio-builder ran on a Saturday but portfolio_date = last Friday → done."""
        saturday = "2026-05-23"
        friday   = "2026-05-22"
        thursday = "2026-05-21"
        step = self._make_step(date_field="portfolio_date", use_trading_day=True)
        client = _async_client_returning({"status": "success", "portfolio_date": friday})
        result = await _step_state(client, step, saturday, friday, thursday)
        assert result == "done", (
            "portfolio-builder must be 'done' when portfolio_date equals last trading day, "
            "even if the job ran on a weekend"
        )

    @pytest.mark.asyncio
    async def test_portfolio_builder_started_at_fails_on_weekend(self):
        """Demonstrates the old bug: started_at on Saturday != Friday target → 'idle'."""
        saturday = "2026-05-23"
        friday   = "2026-05-22"
        thursday = "2026-05-21"
        step = self._make_step(date_field="started_at", use_trading_day=True)
        # Service ran on Saturday — started_at[:10] = Saturday
        client = _async_client_returning({"status": "success",
                                          "started_at": "2026-05-23T10:00:00+00:00"})
        result = await _step_state(client, step, saturday, friday, thursday)
        assert result == "idle", (
            "This test reproduces the old bug: started_at on a Saturday does not match "
            "Friday's trading-day target → 'idle'.  portfolio-builder and delta must "
            "not use started_at as their date_field."
        )

    @pytest.mark.asyncio
    async def test_delta_done_when_run_date_matches_trading_day(self):
        """delta ran on Saturday but run_date = last Friday → done."""
        saturday = "2026-05-23"
        friday   = "2026-05-22"
        thursday = "2026-05-21"
        step = self._make_step(date_field="run_date", use_trading_day=True)
        client = _async_client_returning({"status": "success", "run_date": friday})
        result = await _step_state(client, step, saturday, friday, thursday)
        assert result == "done", (
            "delta must be 'done' when run_date equals last trading day, "
            "even if the job ran on a weekend"
        )

    @pytest.mark.asyncio
    async def test_delta_started_at_fails_on_weekend(self):
        """Demonstrates the old bug: started_at on Saturday != Friday target → 'idle'."""
        saturday = "2026-05-23"
        friday   = "2026-05-22"
        thursday = "2026-05-21"
        step = self._make_step(date_field="started_at", use_trading_day=True)
        client = _async_client_returning({"status": "success",
                                          "started_at": "2026-05-23T10:00:00+00:00"})
        result = await _step_state(client, step, saturday, friday, thursday)
        assert result == "idle"

    @pytest.mark.asyncio
    async def test_pipeline_done_when_chain_date_matches_trading_day_even_if_score_date_lags(self):
        """Regression: cold-start loop when pipeline score_date (data date) lags trading_day.

        When the system boots in the morning of a trading day, the latest price data
        may only be from yesterday (AV hasn't published today's data yet, or it's a
        mock environment).  The pipeline sets run_date=score_date=yesterday but
        chain_date=today.  Using run_date (old behaviour) caused:
          scheduler sees run_date=yesterday != trading_day=today → "idle"
          → triggers pipeline → "already_ran_today" → loops forever
        Using chain_date fixes this: chain_date=today == trading_day=today → "done".
        """
        tuesday  = "2026-05-26"   # today (a normal trading day)
        monday   = "2026-05-25"   # Memorial Day — non-trading; latest mock data goes here
        friday   = "2026-05-22"   # prev_trading_day (last session before holiday)
        # Pipeline ran today; run_date=score_date=Monday (latest data), chain_date=Tuesday
        step = self._make_step(date_field="chain_date", use_trading_day=True,
                               also_accept_prev=False)
        client = _async_client_returning({
            "status": "success",
            "run_date": monday,     # score date (data from yesterday)
            "chain_date": tuesday,  # wall-clock date of the run (today)
        })
        result = await _step_state(client, step, tuesday, tuesday, friday)
        assert result == "done", (
            "pipeline must be 'done' when chain_date=today==trading_day, even when "
            "run_date (score_date) lags behind trading_day. Regression: using run_date "
            "caused an infinite idle→trigger→already_ran_today loop on cold start."
        )

    @pytest.mark.asyncio
    async def test_pipeline_run_date_mismatch_causes_old_idle_loop(self):
        """Documents the OLD bug: run_date=yesterday != trading_day=today → 'idle'."""
        tuesday = "2026-05-26"
        monday  = "2026-05-25"  # score_date from mock data
        friday  = "2026-05-22"
        # Old step definition used run_date — this reproduces the loop
        step = self._make_step(date_field="run_date", use_trading_day=True,
                               also_accept_prev=False)
        client = _async_client_returning({
            "status": "success",
            "run_date": monday,
            "chain_date": tuesday,
        })
        result = await _step_state(client, step, tuesday, tuesday, friday)
        assert result == "idle", (
            "This test reproduces the old cold-start bug: run_date=yesterday does not "
            "match trading_day=today, so _step_state returns 'idle' and the scheduler "
            "re-triggers the pipeline indefinitely."
        )

    @pytest.mark.asyncio
    async def test_portfolio_builder_idle_when_portfolio_date_is_prev_trading_day(self):
        """Regression: also_accept_prev=False must make yesterday's run appear idle today.

        With also_accept_prev=True, a run from prev_trading_day would be accepted as
        'done', causing the scheduler to skip portfolio-builder on every non-holiday
        trading day and never re-run it with today's fresh vetter exclusions.

        Exchange calendar correctly returns last_trading_day(holiday) = last session,
        so also_accept_prev is NOT needed for the holiday case.
        """
        tuesday  = "2026-05-26"  # today (new trading day after Memorial Day)
        friday   = "2026-05-22"  # trading_day = last_trading_day(Tuesday)
        # prev_trading_day on a normal week would be Monday (here Friday due to holiday)
        # But on a REGULAR week tuesday/trading_day=Tuesday, prev=Monday:
        monday   = "2026-05-19"
        tuesday2 = "2026-05-20"  # trading_day
        # Simulate regular Tuesday: yesterday's pb run has portfolio_date=Monday
        step = self._make_step(date_field="portfolio_date", use_trading_day=True,
                               also_accept_prev=False)
        client = _async_client_returning({"status": "success",
                                          "portfolio_date": monday})
        result = await _step_state(client, step, tuesday, tuesday2, monday)
        assert result == "idle", (
            "portfolio-builder must be 'idle' when portfolio_date = prev_trading_day "
            "and also_accept_prev=False, so it re-runs with today's fresh vetter exclusions. "
            "Regression: fc4366e added also_accept_prev=True which broke this."
        )

    @pytest.mark.asyncio
    async def test_portfolio_builder_done_on_holiday_via_exchange_calendar(self):
        """On a market holiday, last_trading_day(holiday) returns the prior session.

        Memorial Day 2026-05-25: last_trading_day(May25) = May22 = trading_day.
        portfolio_date from Friday's run = May22 matches trading_day = May22 exactly.
        also_accept_prev=False is sufficient — no need for prev_trading_day acceptance.
        """
        monday_holiday = "2026-05-25"  # Memorial Day (today)
        friday         = "2026-05-22"  # both trading_day AND prev_trading_day point here
        step = self._make_step(date_field="portfolio_date", use_trading_day=True,
                               also_accept_prev=False)
        client = _async_client_returning({"status": "success",
                                          "portfolio_date": friday})
        # On the holiday: trading_day = May22, prev_trading_day = May22 (same)
        result = await _step_state(client, step, monday_holiday, friday, friday)
        assert result == "done", (
            "portfolio-builder must be 'done' on a market holiday when portfolio_date "
            "matches trading_day (= last_trading_day(holiday)), without needing "
            "also_accept_prev=True."
        )


class TestForceRerunOverride:
    """Manual /jobs/run-now must re-execute steps that already finished today.

    Regression: with today's chain already at status='success', clicking the
    dashboard 'Run' button silently no-op'd because _supervisor_tick treats
    state=='done' as 'skip'. The fix populates _force_pending so the supervisor
    triggers a fresh run for each pending step on the next pass.
    """

    def _reset_chain_status(self, status="idle", chain_date=None):
        _supervisor_tick.__globals__["_chain_status"].update({
            "status": status,
            "date": chain_date or "2026-05-21",
            "steps": {},
            "run_ids": {},
            "last_completed": None,
            "current_run_id": None,
            "next_run": None,
        })

    def _reset_force_pending(self):
        _supervisor_tick.__globals__["_force_pending"].clear()

    @pytest.mark.asyncio
    async def test_force_pending_triggers_done_step(self):
        """A 'done' step listed in _force_pending must be re-triggered with force=True."""
        self._reset_chain_status()
        self._reset_force_pending()

        mock_trigger = AsyncMock()
        _supervisor_tick.__globals__["_force_pending"].add("pipeline")

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="done"),
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value="fake-run-id"),
            "_db_open_run": AsyncMock(return_value="run-uuid-1"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()

        # _trigger_step called once for pipeline with force=True
        mock_trigger.assert_called_once()
        _, kwargs = mock_trigger.call_args
        assert kwargs.get("force") is True, "force=True must be propagated to the step trigger"
        called_step = mock_trigger.call_args.args[1]
        assert called_step.name == "pipeline"
        # Drained from pending so next tick sees the new 'running' state, not double-trigger
        assert "pipeline" not in _supervisor_tick.__globals__["_force_pending"]

    @pytest.mark.asyncio
    async def test_done_step_not_in_force_pending_is_skipped(self):
        """Without _force_pending, a 'done' step must continue to skip (no regression
        for cron-driven ticks)."""
        self._reset_chain_status()
        self._reset_force_pending()

        mock_trigger = AsyncMock()
        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="done"),
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value="fake-run-id"),
            "_db_open_run": AsyncMock(return_value="run-uuid-1"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
            "asyncio": type("FA", (), {"create_task": staticmethod(lambda c: (c.close() if hasattr(c,'close') else None))})(),
        }):
            await _supervisor_tick()

        mock_trigger.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_trigger_keeps_step_pending(self):
        """Regression for review finding #10: if _trigger_step's POST fails (network
        blip, service down), we must NOT discard the step from _force_pending —
        otherwise the dashboard shows a fake 'running' state forever while no
        new run has actually started. The next tick should retry the trigger."""
        self._reset_chain_status()
        self._reset_force_pending()

        # _trigger_step returns False on failure
        mock_trigger = AsyncMock(return_value=False)
        _supervisor_tick.__globals__["_force_pending"].add("pipeline")

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="done"),
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value="fake-run-id"),
            "_db_open_run": AsyncMock(return_value="run-uuid-1"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()

        # Pipeline must STAY in _force_pending so the next tick retries
        assert "pipeline" in _supervisor_tick.__globals__["_force_pending"], (
            "trigger failure must not drain _force_pending — otherwise the chain "
            "is silently stuck"
        )
        # Step status must NOT be advertised as 'running' since nothing actually ran
        assert _supervisor_tick.__globals__["_chain_status"]["steps"].get("pipeline") != "running"

    @pytest.mark.asyncio
    async def test_successful_trigger_drains_force_pending(self):
        """Symmetric to the previous test: when _trigger_step succeeds, the step
        IS discharged so the next tick observes the new running run rather than
        firing twice."""
        self._reset_chain_status()
        self._reset_force_pending()

        mock_trigger = AsyncMock(return_value=True)
        _supervisor_tick.__globals__["_force_pending"].add("pipeline")

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="done"),
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value="fake-run-id"),
            "_db_open_run": AsyncMock(return_value="run-uuid-1"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()

        assert "pipeline" not in _supervisor_tick.__globals__["_force_pending"]
        assert _supervisor_tick.__globals__["_chain_status"]["steps"]["pipeline"] == "running"

    @pytest.mark.asyncio
    async def test_force_pending_discharged_one_step_per_tick(self):
        """With multiple steps in _force_pending, the supervisor triggers the FIRST
        one and returns — preserving the existing one-step-per-tick contract."""
        self._reset_chain_status()
        self._reset_force_pending()

        mock_trigger = AsyncMock()
        pending = _supervisor_tick.__globals__["_force_pending"]
        # Populate with the same names the real /jobs/run-now sets
        pending.update({"fetch-data", "pipeline", "vet", "portfolio-builder", "delta"})

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="done"),
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value="fake-run-id"),
            "_db_open_run": AsyncMock(return_value="run-uuid-1"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()

        assert mock_trigger.call_count == 1, (
            "supervisor must trigger only one step per tick, even with multiple pending"
        )
        # The first step in _STEPS order is fetch-data
        triggered_step = mock_trigger.call_args.args[1]
        assert triggered_step.name == "fetch-data"
        assert "fetch-data" not in pending
        # The other four are still pending for subsequent ticks
        assert pending == {"pipeline", "vet", "portfolio-builder", "delta"}


class TestRunNowRaceCondition:
    """Regression for review finding #2: clicking 'Run' twice while the first
    supervised loop is still in flight must not reset _chain_status mid-cycle
    or spawn a parallel _run_supervised_fast. _run_now_lock guarantees this."""

    @pytest.mark.asyncio
    async def test_second_run_now_returns_already_running(self):
        """While _run_now_lock is held, a second /jobs/run-now returns
        'already_running' instead of clobbering _chain_status."""
        lock = run_now.__globals__["_run_now_lock"]
        chain_status = run_now.__globals__["_chain_status"]
        force_pending = run_now.__globals__["_force_pending"]

        # Snapshot to verify they're untouched
        snapshot_status = dict(chain_status)
        snapshot_pending = set(force_pending)

        await lock.acquire()
        try:
            bg = MagicMock()
            bg.add_task = MagicMock()
            result = await run_now(bg)
            assert result == {"status": "already_running"}
            bg.add_task.assert_not_called()
            # _chain_status must NOT have been mutated by the rejected call
            assert chain_status == snapshot_status
            assert force_pending == snapshot_pending
        finally:
            lock.release()

    @pytest.mark.asyncio
    async def test_run_now_lock_released_after_run_supervised_fast(self):
        """When _run_supervised_fast exits, _run_now_lock must be released so the
        next Run click is accepted."""
        lock = _run_supervised_fast.__globals__["_run_now_lock"]
        chain_status = _run_supervised_fast.__globals__["_chain_status"]

        async def _one_shot_tick():
            chain_status["status"] = "success"

        assert not lock.locked()
        with patch.dict(_run_supervised_fast.__globals__, {"_supervisor_tick": _one_shot_tick}):
            await _run_supervised_fast()
        assert not lock.locked(), (
            "lock must be released after the supervised loop completes — "
            "otherwise the Run button is dead until the next process restart"
        )


class TestRestartResilience:
    """Regression for review finding #6: _force_pending is module-level memory.
    If the scheduler container restarts mid-force-rerun, the remaining pending
    steps must be recovered from the DB or the chain silently truncates."""

    @pytest.mark.asyncio
    async def test_restore_force_pending_from_inflight_chain(self):
        """_restore_force_pending reads scheduler_runs for today's in-flight row
        and returns the force_pending set stashed inside the steps JSONB."""
        import json as _json

        synthetic_steps = {
            "fetch-data": "done",
            "pipeline": "running",
            "__meta": {"force_pending": ["vet", "portfolio-builder", "delta"]},
        }
        fake_row = {"run_id": "restored-uuid", "steps": _json.dumps(synthetic_steps)}
        fake_conn = MagicMock()
        fake_conn.fetchrow = AsyncMock(return_value=fake_row)
        fake_conn.close = AsyncMock()

        with patch.dict(_restore_force_pending.__globals__, {
            "_db_connect": AsyncMock(return_value=fake_conn),
        }):
            run_id, pending = await _restore_force_pending()

        assert run_id == "restored-uuid"
        assert pending == {"vet", "portfolio-builder", "delta"}

    @pytest.mark.asyncio
    async def test_restore_returns_empty_when_no_inflight_chain(self):
        """No 'running' row for today → empty pending set, no run_id."""
        fake_conn = MagicMock()
        fake_conn.fetchrow = AsyncMock(return_value=None)
        fake_conn.close = AsyncMock()
        with patch.dict(_restore_force_pending.__globals__, {
            "_db_connect": AsyncMock(return_value=fake_conn),
        }):
            run_id, pending = await _restore_force_pending()
        assert run_id is None
        assert pending == set()

    @pytest.mark.asyncio
    async def test_restore_handles_missing_meta_gracefully(self):
        """An in-flight row without the __meta sentinel (e.g. cron-triggered chain
        that was interrupted) returns empty pending — the supervisor will just
        resume normal step evaluation on the next tick."""
        import json as _json
        fake_row = {"run_id": "abc", "steps": _json.dumps({"fetch-data": "running"})}
        fake_conn = MagicMock()
        fake_conn.fetchrow = AsyncMock(return_value=fake_row)
        fake_conn.close = AsyncMock()
        with patch.dict(_restore_force_pending.__globals__, {
            "_db_connect": AsyncMock(return_value=fake_conn),
        }):
            run_id, pending = await _restore_force_pending()
        assert run_id == "abc"
        assert pending == set()


class TestCrossMidnightRunningStep:
    """Regression: a step that started yesterday and is still 'running' today
    must return 'running' from _step_state, not 'idle'.

    Before the fix, _step_state hit the date-match check (run_date not in ok_dates)
    before checking run_status, so a cross-midnight job returned "idle". This caused
    an infinite trigger loop: scheduler saw "idle", triggered, got 409 (already
    running), saw "idle" again on the next tick — forever.
    """

    def _make_step(self, **kwargs) -> _StepDef:
        defaults = dict(name="fetch-data", url="http://fake", start_path="/jobs/fetch-data",
                        date_field="started_at", job_type="fetch-data")
        defaults.update(kwargs)
        return _StepDef(**defaults)

    @pytest.mark.asyncio
    async def test_running_step_from_yesterday_returns_running_not_idle(self):
        """A job that started yesterday and is still running today must return
        'running', not 'idle' — prevents the idle→409 trigger loop.

        Regression: _step_state used to check run_date against today BEFORE
        checking run_status, so a cross-midnight job with started_at=yesterday
        got classified as 'idle' instead of 'running'.
        """
        today = "2026-05-29"
        trading_day = "2026-05-29"
        yesterday = "2026-05-28"

        step = self._make_step()
        # Job started yesterday — still running today (cross-midnight hang)
        client = _async_client_returning({
            "job_type": "fetch-data",
            "status": "running",
            "started_at": f"{yesterday}T23:45:00+00:00",
        })
        result = await _step_state(client, step, today, trading_day, yesterday)
        assert result == "running", (
            "A cross-midnight running job must return 'running', not 'idle' — "
            "the 'idle' classification caused an infinite idle→409 trigger loop. "
            f"Got: {result!r}"
        )

    @pytest.mark.asyncio
    async def test_running_step_from_today_returns_running(self):
        """Normal case: job started today, still running — must return 'running'."""
        today = "2026-05-29"
        step = self._make_step()
        client = _async_client_returning({
            "job_type": "fetch-data",
            "status": "running",
            "started_at": f"{today}T16:30:00+00:00",
        })
        result = await _step_state(client, step, today, today, "2026-05-28")
        assert result == "running"

    @pytest.mark.asyncio
    async def test_running_step_exceeding_max_minutes_returns_failed(self):
        """A running job that exceeds max_running_minutes must return 'failed'
        so the chain can advance past a permanently stuck step."""
        today = "2026-05-29"
        step = self._make_step(max_running_minutes=1)  # 1 minute timeout
        # Job started 2 hours ago — timed out
        from datetime import datetime as _dt, timezone, timedelta
        two_hours_ago = (_dt.now(timezone.utc) - timedelta(hours=2)).isoformat()
        client = _async_client_returning({
            "job_type": "fetch-data",
            "status": "running",
            "started_at": two_hours_ago,
        })
        result = await _step_state(client, step, today, today, "2026-05-28")
        assert result == "failed", (
            "A running step that exceeds max_running_minutes must return 'failed' "
            f"so the chain can advance. Got: {result!r}"
        )


class TestTimeGateBypass:
    """Regression: the time gate must NOT block manual run-now requests.

    Before the fix, _supervisor_tick returned early if _is_after_scheduled_time()
    was False even when _force_pending was set. Clicking the dashboard Run button
    before 4:15 PM ET produced no chain advancement — the user saw empty rankings
    all day unless they happened to trigger it after the scheduled time.
    """

    def _reset(self):
        _supervisor_tick.__globals__["_chain_status"].update({
            "status": "idle", "date": "2026-05-29", "steps": {}, "run_ids": {},
            "last_completed": None, "current_run_id": None, "next_run": None,
        })
        _supervisor_tick.__globals__["_force_pending"].clear()

    @pytest.mark.asyncio
    async def test_run_now_before_scheduled_time_advances_chain(self):
        """With _force_pending set, the chain must advance even before 4:15 PM ET."""
        self._reset()
        _supervisor_tick.__globals__["_force_pending"].add("fetch-data")

        mock_trigger = AsyncMock(return_value=True)
        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="done"),
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value="run-id"),
            "_db_open_run": AsyncMock(return_value="run-uuid"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
            # Time gate returns False — it's before scheduled time
            "_is_after_scheduled_time": MagicMock(return_value=False),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()

        # The step should have been triggered despite the time gate
        mock_trigger.assert_called_once()

    @pytest.mark.asyncio
    async def test_automatic_tick_before_scheduled_time_is_blocked(self):
        """Without _force_pending, the time gate must still block automatic ticks."""
        self._reset()
        # _force_pending is empty — no manual run requested

        mock_trigger = AsyncMock(return_value=True)
        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="idle"),
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value=None),
            "_db_open_run": AsyncMock(return_value="run-uuid"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
            "_is_after_scheduled_time": MagicMock(return_value=False),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()

        # No trigger — blocked by time gate
        mock_trigger.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_pending_cleared_when_step_triggers_before_market(self):
        """After force-triggering a step outside market hours, _force_pending is drained."""
        self._reset()
        _supervisor_tick.__globals__["_force_pending"].add("pipeline")

        with patch.dict(_supervisor_tick.__globals__, {
            "_has_universe": AsyncMock(return_value=True),
            "_step_state": AsyncMock(return_value="done"),
            "_trigger_step": AsyncMock(return_value=True),
            "_get_latest_run_id": AsyncMock(return_value="run-id"),
            "_db_open_run": AsyncMock(return_value="run-uuid"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
            "_is_after_scheduled_time": MagicMock(return_value=False),
            "_latest_rank_date": AsyncMock(return_value=None),
        }):
            await _supervisor_tick()

        assert "pipeline" not in _supervisor_tick.__globals__["_force_pending"]


class TestRunsLatestStripsMetaKey:
    """The __meta sentinel inside steps JSONB must not leak through /runs/latest
    or the dashboard would iterate it as a real step."""

    @pytest.mark.asyncio
    async def test_runs_latest_filters_meta(self):
        from app.main import runs_latest as _runs_latest
        import json as _json

        steps_with_meta = {
            "fetch-data": "done",
            "pipeline": "running",
            "__meta": {"force_pending": ["vet"]},
        }
        fake_row = {
            "run_id": "abc", "started_at": None, "updated_at": None,
            "completed_at": None, "status": "running", "chain_date": "2026-05-23",
            "steps": _json.dumps(steps_with_meta), "run_ids": {},
        }
        fake_conn = MagicMock()
        fake_conn.fetchrow = AsyncMock(return_value=fake_row)
        fake_conn.close = AsyncMock()
        with patch.dict(_runs_latest.__globals__, {
            "_db_connect": AsyncMock(return_value=fake_conn),
        }):
            out = await _runs_latest()
        assert "__meta" not in out["steps"]
        assert out["steps"] == {"fetch-data": "done", "pipeline": "running"}


# ── Trading-calendar gate (should_run_chain wiring in _supervisor_tick) ─────────

from datetime import date as _date  # noqa: E402


class TestSupervisorTradingCalendarGate:
    """The supervisor consults should_run_chain() before STARTING a fresh chain,
    and bypasses it once a chain is already active (so multi-tick runs and
    weekend catch-ups advance to completion)."""

    def _reset_fresh(self):
        """Fresh, not-yet-started chain for today (so the date-rollover branch
        resets cleanly and current_run_id is None)."""
        _supervisor_tick.__globals__["_chain_status"].update({
            "status": None, "date": "2026-05-21", "steps": {}, "run_ids": {},
            "last_completed": None, "current_run_id": None, "next_run": None,
        })
        _supervisor_tick.__globals__["_force_pending"].clear()

    @pytest.mark.asyncio
    async def test_skips_when_should_run_chain_false(self):
        """Non-trading day, latest session already processed → gate returns False
        → supervisor returns BEFORE the universe check (no steps triggered)."""
        self._reset_fresh()
        mock_has_universe = AsyncMock(return_value=True)
        mock_trigger = AsyncMock()
        with patch.dict(_supervisor_tick.__globals__, {
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_delta_date": AsyncMock(return_value=_date(2026, 5, 29)),
            "should_run_chain": MagicMock(return_value=False),
            "_has_universe": mock_has_universe,
            "_trigger_step": mock_trigger,
            "_db_open_run": AsyncMock(return_value="run-x"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
        }):
            await _supervisor_tick()

        # Gate short-circuited: never reached the universe check or any trigger.
        mock_has_universe.assert_not_called()
        mock_trigger.assert_not_called()
        assert _chain_status["status"] != "running"

    @pytest.mark.asyncio
    async def test_proceeds_when_should_run_chain_true(self):
        """Trading session (or stale catch-up) → gate returns True → supervisor
        proceeds into the chain (universe check runs, first step triggered)."""
        self._reset_fresh()
        mock_has_universe = AsyncMock(return_value=True)
        mock_trigger = AsyncMock()
        with patch.dict(_supervisor_tick.__globals__, {
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_delta_date": AsyncMock(return_value=None),
            "should_run_chain": MagicMock(return_value=True),
            "_has_universe": mock_has_universe,
            "_step_state": AsyncMock(return_value="idle"),
            "_trigger_step": mock_trigger,
            "_get_latest_run_id": AsyncMock(return_value=None),
            "_db_open_run": AsyncMock(return_value="run-x"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
        }):
            await _supervisor_tick()

        mock_has_universe.assert_called_once()
        assert mock_trigger.call_count == 1
        assert _chain_status["status"] == "running"

    @pytest.mark.asyncio
    async def test_active_chain_bypasses_gate(self):
        """A chain already open for today (current_run_id set) advances even when
        should_run_chain would say False — so a started run, including a weekend
        catch-up, always runs to completion across ticks."""
        today = _date.today().isoformat()
        _supervisor_tick.__globals__["_chain_status"].update({
            "status": "running", "date": today, "steps": {}, "run_ids": {},
            "last_completed": None, "current_run_id": "active-run", "next_run": None,
        })
        _supervisor_tick.__globals__["_force_pending"].clear()

        mock_has_universe = AsyncMock(return_value=True)
        mock_should_run = MagicMock(return_value=False)  # would block a fresh start
        with patch.dict(_supervisor_tick.__globals__, {
            "_is_after_scheduled_time": MagicMock(return_value=True),
            "_latest_delta_date": AsyncMock(return_value=_date(2026, 5, 29)),
            "should_run_chain": mock_should_run,
            "_has_universe": mock_has_universe,
            "_step_state": AsyncMock(return_value="idle"),
            "_trigger_step": AsyncMock(),
            "_get_latest_run_id": AsyncMock(return_value=None),
            "_db_open_run": AsyncMock(return_value="active-run"),
            "_db_update_run": AsyncMock(),
            "_db_close_run": AsyncMock(),
        }):
            await _supervisor_tick()

        # Bypassed the gate entirely (never consulted) and proceeded.
        mock_should_run.assert_not_called()
        mock_has_universe.assert_called_once()


# ── TestRestartAbortLoopBreaker ───────────────────────────────────────────────

class TestRestartAbortLoopBreaker:
    """
    A RESTART_ABORTED orphan is re-triggered to recover from a transient restart.
    But a DETERMINISTIC crash (e.g. the factor step OOM-killing) reproduces every
    retry, turning recovery into an infinite crash loop. The supervisor must count
    distinct crash cycles and SUSPEND (return 'failed') after MAX_RESTART_ABORT_RETRIES.
    """

    # The scheduler conftests do `del sys.modules["app.*"]`, so `from app.main
    # import _step_state` and a fresh `import app.main` can resolve to DIFFERENT
    # module instances with different module-level dicts. Always reach the breaker
    # state through the running function's own globals so we touch the exact dicts
    # `_step_state` mutates — not a stale parallel copy.
    def _g(self):
        return _step_state.__globals__

    def _make_step(self, **kwargs) -> _StepDef:
        defaults = dict(name="pipeline", url="http://fake", start_path="/jobs/run", date_field="run_date")
        defaults.update(kwargs)
        return _StepDef(**defaults)

    def _reset(self):
        g = self._g()
        g["_restart_abort_cycles"].clear()
        g["_restart_abort_seen"].clear()

    def _max(self) -> int:
        return self._g()["MAX_RESTART_ABORT_RETRIES"]

    def _aborted_payload(self, started_at: str, run_date: str = "2026-05-21") -> dict:
        from stock_strategy_shared.tracing import RESTART_ABORT_MARKER
        return {
            "status": "failed",
            "run_date": run_date,
            "started_at": started_at,
            "error_message": f"{RESTART_ABORT_MARKER} service restarted while run was active",
        }

    @pytest.mark.asyncio
    async def test_suspends_after_max_distinct_crash_cycles(self):
        self._reset()
        today = "2026-05-21"
        step = self._make_step()
        results = []
        # Each distinct started_at = one crash cycle (a fresh run that died again).
        for i in range(self._max() + 1):
            client = _async_client_returning(self._aborted_payload(f"2026-05-21T10:0{i}:00Z"))
            results.append(await _step_state(client, step, today, today, "2026-05-20"))
        # First MAX cycles re-trigger; the one past the limit suspends.
        assert results[:self._max()] == ["idle"] * self._max()
        assert results[-1] == "failed", f"expected suspend after limit, got {results}"

    @pytest.mark.asyncio
    async def test_same_orphan_across_ticks_counts_once(self):
        """Re-seeing the SAME orphan (same started_at) over many ticks must NOT
        advance the crash count — it is one cycle until the re-trigger creates a
        new run. Otherwise a fast supervisor tick would trip the breaker spuriously."""
        self._reset()
        today = "2026-05-21"
        step = self._make_step()
        payload = self._aborted_payload("2026-05-21T10:00:00Z")
        results = [
            await _step_state(_async_client_returning(payload), step, today, today, "2026-05-20")
            for _ in range(self._max() + 5)
        ]
        assert results == ["idle"] * len(results), "identical orphan must keep re-triggering, never suspend"

    @pytest.mark.asyncio
    async def test_clean_success_resets_the_counter(self):
        """A clean success clears the crash count so a later transient restart can
        still be recovered normally."""
        self._reset()
        today = "2026-05-21"
        step = self._make_step()
        # Two crash cycles (not yet at the limit)…
        for i in range(2):
            await _step_state(_async_client_returning(self._aborted_payload(f"2026-05-21T10:0{i}:00Z")),
                              step, today, today, "2026-05-20")
        assert self._g()["_restart_abort_cycles"].get(("pipeline", today)) == 2
        # …then a clean success on the same (step, date) must reset the count.
        ok = await _step_state(_async_client_returning({"status": "success", "run_date": today}),
                               step, today, today, "2026-05-20")
        assert ok == "done"
        assert ("pipeline", today) not in self._g()["_restart_abort_cycles"]

    @pytest.mark.asyncio
    async def test_non_aborted_failure_still_fails_immediately(self):
        """A real failure (no RESTART_ABORT_MARKER) must still suspend on the first
        occurrence — the breaker only governs restart-aborted orphans."""
        self._reset()
        today = "2026-05-21"
        step = self._make_step()
        client = _async_client_returning(
            {"status": "failed", "run_date": today, "started_at": "2026-05-21T10:00:00Z",
             "error_message": "Connection refused by Alpha Vantage API"}
        )
        assert await _step_state(client, step, today, today, "2026-05-20") == "failed"
