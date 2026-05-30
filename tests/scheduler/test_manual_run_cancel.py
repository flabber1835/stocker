"""Tests for the manual-run cancel-all pre-step and manual-vs-scheduled tagging.

Behaviour under test:
  - run_now() (the dashboard "Run" button path) schedules a cancel-all-orders
    pre-step and tags the chain origin='manual'
  - the cron/scheduled chain does NOT cancel and is origin='scheduled'
  - _trigger_step appends manual=true to the delta POST only when the chain is
    origin='manual' (and never to other steps)
  - _cancel_all_open_orders calls trade-executor with confirm=yes and then re-syncs
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

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
    _STEPS,
    _cancel_all_open_orders,
    _chain_status,
    _trigger_step,
    run_now,
)


def _delta_step():
    return next(s for s in _STEPS if s.name == "delta")


def _pipeline_step():
    return next(s for s in _STEPS if s.name == "pipeline")


def _mock_resp(status_code=200, payload=None, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = payload or {}
    r.text = text
    return r


@pytest.fixture(autouse=True)
def _reset_origin():
    """Reset origin after each test so cases don't bleed."""
    g = _trigger_step.__globals__
    saved = g["_chain_status"].get("origin")
    yield
    g["_chain_status"]["origin"] = saved


# ── _trigger_step: manual tagging on the delta step only ─────────────────────

class TestTriggerStepManualTag:

    async def _capture_post_params(self, step, origin):
        captured = {}

        async def fake_post(url, timeout=None, params=None):
            captured["url"] = url
            captured["params"] = params or {}
            return _mock_resp(200, {"status": "started"})

        client = MagicMock()
        client.post = fake_post
        _trigger_step.__globals__["_chain_status"]["origin"] = origin
        ok = await _trigger_step(client, step)
        assert ok is True
        return captured

    @pytest.mark.asyncio
    async def test_delta_manual_origin_adds_manual_param(self):
        captured = await self._capture_post_params(_delta_step(), "manual")
        assert captured["params"].get("manual") == "true"

    @pytest.mark.asyncio
    async def test_delta_scheduled_origin_no_manual_param(self):
        captured = await self._capture_post_params(_delta_step(), "scheduled")
        assert "manual" not in captured["params"]

    @pytest.mark.asyncio
    async def test_non_delta_step_never_tagged_manual(self):
        """Even on a manual chain, only the delta step carries manual=true."""
        captured = await self._capture_post_params(_pipeline_step(), "manual")
        assert "manual" not in captured["params"]


# ── _cancel_all_open_orders ──────────────────────────────────────────────────

class TestCancelAllOpenOrders:

    @pytest.mark.asyncio
    async def test_calls_executor_with_confirm_and_resyncs(self):
        captured = {}

        async def fake_post(url, params=None, timeout=None):
            captured["url"] = url
            captured["params"] = params or {}
            return _mock_resp(200, {"status": "ok", "alpaca_cancel_count": 3,
                                    "local_orders_updated": 3})

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.post = fake_post

        mock_sync = AsyncMock()
        with patch("httpx.AsyncClient", return_value=fake_client), \
             patch.dict(_cancel_all_open_orders.__globals__, {"_trigger_alpaca_sync": mock_sync}):
            result = await _cancel_all_open_orders("test")

        assert result is True
        assert captured["url"].endswith("/jobs/cancel-all-orders")
        assert captured["params"].get("confirm") == "yes"
        # Must re-sync afterward so the delta sees the cleared book.
        mock_sync.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_http_error_returns_false_and_skips_resync(self):
        async def fake_post(url, params=None, timeout=None):
            return _mock_resp(500, text="boom")

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.post = fake_post

        mock_sync = AsyncMock()
        with patch("httpx.AsyncClient", return_value=fake_client), \
             patch.dict(_cancel_all_open_orders.__globals__, {"_trigger_alpaca_sync": mock_sync}):
            result = await _cancel_all_open_orders("test")

        assert result is False
        mock_sync.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_network_exception_returns_false_does_not_raise(self):
        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.post = AsyncMock(side_effect=RuntimeError("conn refused"))

        mock_sync = AsyncMock()
        with patch("httpx.AsyncClient", return_value=fake_client), \
             patch.dict(_cancel_all_open_orders.__globals__, {"_trigger_alpaca_sync": mock_sync}):
            result = await _cancel_all_open_orders("test")

        assert result is False
        mock_sync.assert_not_awaited()


# ── run_now: schedules cancel-all + sets origin=manual ───────────────────────

class _FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


class TestRunNowManual:

    def _reset(self):
        g = run_now.__globals__
        # Ensure no in-flight run-now lock from a prior test.
        lock = g["_run_now_lock"]
        if lock.locked():
            lock.release()
        g["_force_pending"].clear()
        g["_chain_status"]["origin"] = "scheduled"

    @pytest.mark.asyncio
    async def test_run_now_sets_origin_manual(self):
        self._reset()
        bt = _FakeBackgroundTasks()
        with patch.dict(run_now.__globals__, {"_run_supervised_fast": AsyncMock()}):
            resp = await run_now(bt)
        assert resp["status"] == "started"
        assert run_now.__globals__["_chain_status"]["origin"] == "manual"

    @pytest.mark.asyncio
    async def test_run_now_schedules_cancel_all_pre_step(self):
        self._reset()
        bt = _FakeBackgroundTasks()
        with patch.dict(run_now.__globals__, {"_run_supervised_fast": AsyncMock()}):
            await run_now(bt)
        # cancel-all must be among the scheduled background tasks.
        fns = [t[0] for t in bt.tasks]
        assert _cancel_all_open_orders in fns
        # and it forces all steps to re-run
        assert run_now.__globals__["_force_pending"] == {s.name for s in _STEPS}

    @pytest.mark.asyncio
    async def test_run_now_already_running_no_cancel(self):
        """A second concurrent run-now returns already_running and schedules nothing."""
        self._reset()
        g = run_now.__globals__
        await g["_run_now_lock"].acquire()
        try:
            bt = _FakeBackgroundTasks()
            resp = await run_now(bt)
        finally:
            g["_run_now_lock"].release()
        assert resp["status"] == "already_running"
        assert bt.tasks == []
