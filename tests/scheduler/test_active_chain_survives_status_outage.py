"""An ACTIVE chain must never be stalled by the universe pre-flight.

The freeze this pins down: av-ingestor's /status ran exact COUNT(*)s over
daily_prices (millions of rows). The manual-run loop ticks every 3s, the
overlapping full scans pegged postgres until every /status call exceeded the
scheduler's 10s timeout, _has_universe returned None, and EVERY tick bailed with
"av-ingestor unreachable" BEFORE the step loop — freezing the chain display at
"calculating factors" half an hour after the pipeline had actually succeeded,
with vet/builder/delta never fired.

The cold-start guard exists to stop fetch-universe trigger loops when the
service is BOOTING. Once a chain is open, fetch has already run — the universe
self-evidently exists — so consulting the check there can only produce false
negatives. These tests pin the split: active chain skips it entirely; cold
start keeps the full protection (its 24-row decision table is untouched).
"""
from __future__ import annotations

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

from app import main as scheduler_main  # noqa: E402
from app.main import _chain_status, _force_pending, _supervisor_tick  # noqa: E402


def _current_session() -> str:
    return scheduler_main.latest_closed_session(scheduler_main._local_now()).isoformat()


@pytest.fixture(autouse=True)
def _reset_state():
    _chain_status.clear()
    _chain_status.update({"date": None, "status": None, "steps": {}, "run_ids": {},
                          "current_run_id": None, "next_run": None})
    _force_pending.clear()
    yield
    _chain_status.clear()
    _force_pending.clear()


def _client_mock():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"job_type": "fetch-data", "status": "success"}
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _tick_patches(has_universe, step_state):
    httpx_mock = MagicMock()
    httpx_mock.AsyncClient = MagicMock(return_value=_client_mock())
    return [
        patch.object(scheduler_main, "httpx", httpx_mock),
        patch.object(scheduler_main, "_has_universe", new=has_universe),
        patch.object(scheduler_main, "_is_after_scheduled_time", new=MagicMock(return_value=True)),
        patch.object(scheduler_main, "_latest_rank_date", new=AsyncMock(return_value=None)),
        patch.object(scheduler_main, "_latest_delta_date", new=AsyncMock(return_value=None)),
        patch.object(scheduler_main, "_db_open_run", new=AsyncMock(return_value="db-run")),
        patch.object(scheduler_main, "_db_update_run", new=AsyncMock()),
        patch.object(scheduler_main, "_db_close_run", new=AsyncMock()),
        patch.object(scheduler_main, "_get_latest_run_id", new=AsyncMock(return_value="svc-run")),
        patch.object(scheduler_main, "_trigger_step", new=AsyncMock(return_value=True)),
        patch.object(scheduler_main, "_step_state", new=step_state),
        patch.object(scheduler_main, "_maybe_trigger_evaluator", new=AsyncMock()),
        patch.object(scheduler_main, "_maybe_refresh_universe", new=AsyncMock()),
        patch.object(scheduler_main, "_maybe_label_outcomes", new=AsyncMock()),
    ]


@pytest.mark.asyncio
async def test_active_chain_reaches_the_step_loop_despite_status_outage():
    """THE regression. Chain open + _has_universe → None must still advance the
    steps — the frozen production state was steps stuck at {pipeline: running}
    for 30+ minutes while the pipeline row said success."""
    _chain_status.update({"date": _current_session(), "status": "running",
                          "current_run_id": "open-chain",
                          "steps": {"fetch-data": "done", "pipeline": "running"}})
    has_universe = AsyncMock(return_value=None)          # the outage
    step_state = AsyncMock(return_value="done")

    patches = _tick_patches(has_universe, step_state)
    for p in patches:
        p.start()
    try:
        await _supervisor_tick()
    finally:
        for p in patches:
            p.stop()

    assert step_state.await_count > 0, (
        "tick bailed before the step loop — the /status outage froze an ACTIVE chain")
    # The stale 'running' must have been recomputed, not held.
    assert _chain_status["steps"].get("pipeline") == "done"
    # And the pre-flight was not even consulted: an open chain proves the
    # universe exists, so there is nothing to ask av-ingestor.
    has_universe.assert_not_awaited()


@pytest.mark.asyncio
async def test_cold_start_still_waits_on_status_outage():
    """The mirror: with NO chain open, None must still mean WAIT — that guard
    prevents the fetch-universe trigger loop that burned AV quota, and this
    change must not weaken it."""
    _chain_status.update({"date": _current_session(), "status": None,
                          "current_run_id": None})
    _force_pending.add("fetch-data")     # bypass the start gates like run-now does
    has_universe = AsyncMock(return_value=None)
    step_state = AsyncMock(return_value="done")

    patches = _tick_patches(has_universe, step_state)
    for p in patches:
        p.start()
    try:
        await _supervisor_tick()
    finally:
        for p in patches:
            p.stop()

    has_universe.assert_awaited()
    assert step_state.await_count == 0, (
        "cold start advanced past an unreachable av-ingestor — the quota-burning "
        "trigger loop this guard exists for is possible again")


@pytest.mark.asyncio
async def test_run_now_fast_loop_survives_a_raising_tick():
    """The run-now loop had NO per-tick guard: one raising tick silently ended
    the manual run's fast polling for the entire session. It must log and keep
    ticking instead."""
    calls = {"n": 0}

    async def flaky_tick():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        _chain_status["status"] = "success"     # terminal → loop exits

    with patch.object(scheduler_main, "_supervisor_tick", new=flaky_tick), \
         patch.object(scheduler_main.asyncio, "sleep", new=AsyncMock()):
        await scheduler_main._run_supervised_fast()

    assert calls["n"] >= 2, (
        "the loop died on the first raising tick instead of continuing")


@pytest.mark.asyncio
async def test_fast_drain_survives_a_raising_tick():
    calls = {"n": 0}

    async def flaky_tick():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        _chain_status["status"] = "success"

    _chain_status.update({"current_run_id": "open-chain", "status": "running"})
    with patch.object(scheduler_main, "_supervisor_tick", new=flaky_tick), \
         patch.object(scheduler_main.asyncio, "sleep", new=AsyncMock()):
        await scheduler_main._fast_drain()

    assert calls["n"] >= 2
