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
        assert triggered_step.name == "factor-calculate"

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
        """vet failed (optional=True) → chain continues to delta step."""
        self._reset_chain_status()
        mock_trigger = AsyncMock()

        async def _fake_step_state(client, step, today, trading_day, prev_trading_day):
            if step.name in ("fetch-data", "factor-calculate", "rank"):
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
            "_db_close_run": AsyncMock(),
        }):
            await _supervisor_tick()

        assert mock_trigger.call_count == 1
        triggered_step = mock_trigger.call_args[0][1]
        assert triggered_step.name == "delta"

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
        """has_universe=False → triggers fetch-universe and returns early."""
        self._reset_chain_status()
        mock_trigger = AsyncMock()
        mock_db_open = AsyncMock(return_value=None)

        # Build a fake httpx async context manager
        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fetch_universe_resp = _mock_response(200, {"status": "started"})
        fake_client.post = AsyncMock(return_value=fetch_universe_resp)

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
