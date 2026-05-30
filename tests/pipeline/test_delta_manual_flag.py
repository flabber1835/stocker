"""Tests for the manual flag on the standalone /jobs/delta endpoint.

A manual (human-initiated run-now) delta must persist delta_runs.manual=TRUE so the
dashboard refuses to auto-approve its proposals; the after-close cron chain passes
manual=false (the default). The flag is independent of triggered_by, which stays
'scheduler' for both so /runs/delta-latest keeps tracking the standalone step.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import main as pmain


class _FakeStrategy:
    strategy_id = "test_strategy_v1"
    delta_engine = None  # _do_delta is mocked, so the value is never read


class _FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args, **kwargs):
        # Don't run the background delta — we only assert on the synchronous INSERT.
        self.tasks.append((fn, args, kwargs))


def _capture_engine():
    """Engine mock whose begin() ctx captures every execute(sql, params) call."""
    captured = []

    conn = AsyncMock()

    async def _exec(sql, params=None):
        captured.append({"sql": str(sql), "params": params})
        return MagicMock()

    conn.execute = _exec

    begin_ctx = MagicMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=conn)
    begin_ctx.__aexit__ = AsyncMock(return_value=None)

    engine = MagicMock()
    engine.begin = MagicMock(return_value=begin_ctx)
    return engine, captured


def _delta_insert_params(captured):
    """Pull the params of the INSERT INTO delta_runs call."""
    for c in captured:
        if "INSERT INTO delta_runs" in c["sql"]:
            return c["params"]
    raise AssertionError("no delta_runs INSERT captured")


@pytest.fixture(autouse=True)
def _free_job_lock():
    """Ensure the module _job_lock is free before/after each test."""
    if pmain._job_lock.locked():
        pmain._job_lock.release()
    yield
    if pmain._job_lock.locked():
        pmain._job_lock.release()


@pytest.mark.asyncio
async def test_delta_manual_true_persists_manual_flag():
    engine, captured = _capture_engine()
    bt = _FakeBackgroundTasks()
    with patch.object(pmain, "engine", engine, create=True), \
         patch.object(pmain, "strategy", _FakeStrategy(), create=True), \
         patch.object(pmain, "_create_sub_trace", new=AsyncMock()):
        resp = await pmain.start_delta_only(bt, manual=True)
    assert resp["status"] in ("started", "running", "accepted") or "run_id" in resp
    params = _delta_insert_params(captured)
    assert params["manual"] is True
    # triggered_by stays 'scheduler' regardless so /runs/delta-latest still tracks it.
    assert params["tb"] == "scheduler"


@pytest.mark.asyncio
async def test_delta_default_is_not_manual():
    engine, captured = _capture_engine()
    bt = _FakeBackgroundTasks()
    with patch.object(pmain, "engine", engine, create=True), \
         patch.object(pmain, "strategy", _FakeStrategy(), create=True), \
         patch.object(pmain, "_create_sub_trace", new=AsyncMock()):
        await pmain.start_delta_only(bt)
    params = _delta_insert_params(captured)
    assert params["manual"] is False
    assert params["tb"] == "scheduler"


@pytest.mark.asyncio
async def test_delta_manual_false_explicit():
    engine, captured = _capture_engine()
    bt = _FakeBackgroundTasks()
    with patch.object(pmain, "engine", engine, create=True), \
         patch.object(pmain, "strategy", _FakeStrategy(), create=True), \
         patch.object(pmain, "_create_sub_trace", new=AsyncMock()):
        await pmain.start_delta_only(bt, manual=False)
    params = _delta_insert_params(captured)
    assert params["manual"] is False


@pytest.mark.asyncio
async def test_delta_already_running_returns_guard():
    """When the job lock is held, the endpoint short-circuits without an INSERT."""
    engine, captured = _capture_engine()
    bt = _FakeBackgroundTasks()
    await pmain._job_lock.acquire()
    try:
        with patch.object(pmain, "engine", engine, create=True):
            resp = await pmain.start_delta_only(bt, manual=True)
    finally:
        pmain._job_lock.release()
    assert resp["status"] == "already_running"
    assert captured == []


@pytest.mark.asyncio
async def test_do_delta_step_threads_manual_into_insert():
    """_do_delta_step (the non-pre-created path) carries manual into its own INSERT."""
    engine, captured = _capture_engine()
    with patch.object(pmain, "engine", engine, create=True), \
         patch.object(pmain, "strategy", _FakeStrategy(), create=True), \
         patch.object(pmain, "_create_sub_trace", new=AsyncMock()), \
         patch.object(pmain, "_do_delta", new=AsyncMock()):
        # run_id=None forces the in-function INSERT branch.
        await pmain._do_delta_step(triggered_by="scheduler", manual=True)
    params = _delta_insert_params(captured)
    assert params["manual"] is True
