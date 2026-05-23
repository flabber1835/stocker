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
    _step_state,
    _supervisor_tick,
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
        }):
            await _supervisor_tick()

        mock_trigger.assert_not_called()
        assert _chain_status["status"] == "running"

    @pytest.mark.asyncio
    async def test_advances_to_second_step(self):
        """fetch-data done, all others idle → triggers factor-calculate."""
        self._reset_chain_status()

        call_count = [0]

        async def _fake_step_state(client, step, today, trading_day, prev_trading_day):
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

        async def _fake_step_state(client, step, today, trading_day, prev_trading_day):
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
        }):
            await _supervisor_tick()

        mock_trigger.assert_not_called()
        assert _chain_status["status"] == "failed"
        mock_db_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_optional_failure(self):
        """vet failed (optional=True) → chain succeeds (no steps after vet in new sequence)."""
        self._reset_chain_status()
        mock_trigger = AsyncMock()
        mock_db_close = AsyncMock()

        async def _fake_step_state(client, step, today, trading_day, prev_trading_day):
            if step.name in ("fetch-data", "pipeline", "portfolio-builder", "delta"):
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
            "asyncio": type("_FakeAsyncio", (), {
                "create_task": staticmethod(lambda coro: (coro.close() if hasattr(coro, "close") else None) or MagicMock()),
            })(),
        }):
            await _supervisor_tick()

        # vet is optional and last step — chain should complete successfully
        mock_trigger.assert_not_called()
        assert _chain_status["status"] == "success"

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
