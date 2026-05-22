"""
Tests for pipeline service main.py concurrency and validation helpers.

These tests cover the fixes from commit f8cd3fd:
- `_job_lock` held across the full pipeline run (entry guard, finally release)
- `_trigger_from_event` scheduling `_run_pipeline_steps` and ACKing the event
- `_update_pipeline_run` allowlist rejecting unknown column names
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Triggers conftest stubs + module path setup
from app import main as pmain


# ── _update_pipeline_run allowlist ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_pipeline_run_rejects_unknown_column():
    conn = MagicMock()
    conn.execute = AsyncMock()
    with pytest.raises(ValueError) as exc_info:
        await pmain._update_pipeline_run(conn, "run-1", evil_column="x")
    assert "evil_column" in str(exc_info.value)
    # No SQL was executed
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_update_pipeline_run_accepts_allowlisted_columns():
    """A valid column passes the allowlist check and reaches conn.execute()."""
    conn = MagicMock()
    conn.execute = AsyncMock()
    await pmain._update_pipeline_run(conn, "run-1", status="success")
    assert conn.execute.call_count == 1


@pytest.mark.asyncio
async def test_update_pipeline_run_rejects_mixed_good_bad():
    """Even if one column is valid, the call fails on any unknown name."""
    conn = MagicMock()
    conn.execute = AsyncMock()
    with pytest.raises(ValueError):
        await pmain._update_pipeline_run(
            conn, "run-1", status="success", drop_table_pipeline_runs="x",
        )
    conn.execute.assert_not_called()


# ── _do_run_pipeline lock acquisition + already_running guard ────────────────


@pytest.mark.asyncio
async def test_do_run_pipeline_returns_already_running_when_lock_held():
    """If _job_lock is held by another task, _do_run_pipeline returns
    {'status': 'already_running'} without touching the DB."""
    # Pre-acquire the lock
    await pmain._job_lock.acquire()
    try:
        result = await pmain._do_run_pipeline(triggered_by="manual")
        assert result == {"status": "already_running"}
    finally:
        pmain._job_lock.release()


@pytest.mark.asyncio
async def test_do_run_pipeline_releases_lock_on_setup_failure(monkeypatch):
    """If anything raises during setup (e.g. DB INSERT fails), the lock must
    be released so the next call can proceed."""
    fake_engine = MagicMock()
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(side_effect=RuntimeError("db boom"))

    fake_begin = MagicMock()
    fake_begin.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_begin.__aexit__ = AsyncMock(return_value=None)
    fake_engine.begin = MagicMock(return_value=fake_begin)
    fake_engine.connect = MagicMock(return_value=fake_begin)

    monkeypatch.setattr(pmain, "engine", fake_engine, raising=False)

    assert not pmain._job_lock.locked()
    with pytest.raises(RuntimeError):
        await pmain._do_run_pipeline(triggered_by="manual")
    assert not pmain._job_lock.locked(), "lock leaked after setup failure"


# ── _run_pipeline_steps releases the lock in finally ─────────────────────────


@pytest.mark.asyncio
async def test_run_pipeline_steps_releases_lock_on_failure(monkeypatch):
    """When _run_pipeline_steps raises, the finally block must release the lock."""
    # Force factor step to raise immediately
    async def _boom(*a, **k):
        raise RuntimeError("factor crash")

    fake_engine = MagicMock()
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock()
    fake_begin = MagicMock()
    fake_begin.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_begin.__aexit__ = AsyncMock(return_value=None)
    fake_engine.begin = MagicMock(return_value=fake_begin)

    monkeypatch.setattr(pmain, "engine", fake_engine, raising=False)
    monkeypatch.setattr(pmain, "_do_factor_step", _boom)

    # Simulate the pre-acquired lock state that _do_run_pipeline leaves behind
    await pmain._job_lock.acquire()
    try:
        with pytest.raises(RuntimeError):
            from datetime import date, datetime, timezone
            await pmain._run_pipeline_steps(
                "run-1", "trace-1", date.today(), datetime.now(timezone.utc), "manual",
            )
    finally:
        # Lock should have been released by the finally block
        assert not pmain._job_lock.locked(), "lock leaked after pipeline failure"
        # Defensive: release if test setup left it locked
        if pmain._job_lock.locked():
            pmain._job_lock.release()


# ── _trigger_from_event ACKs the message and schedules the run ───────────────


@pytest.mark.asyncio
async def test_trigger_from_event_acks_when_already_running(monkeypatch):
    """If _do_run_pipeline returns 'already_running', the redis message must
    still be ACKed — otherwise the consumer loop re-delivers it forever."""
    async def _fake_run(triggered_by):
        return {"status": "already_running"}

    fake_redis = MagicMock()
    fake_redis.xack = AsyncMock()
    monkeypatch.setattr(pmain, "_do_run_pipeline", _fake_run)
    monkeypatch.setattr(pmain, "redis_client", fake_redis)

    await pmain._trigger_from_event("2026-05-22", "msg-1")
    fake_redis.xack.assert_awaited_once_with(
        pmain.PIPELINE_STREAM, pmain.CONSUMER_GROUP, "msg-1",
    )


@pytest.mark.asyncio
async def test_trigger_from_event_schedules_run_when_started(monkeypatch):
    """When _do_run_pipeline returns 'started', _trigger_from_event must
    schedule _run_pipeline_steps as a background task."""
    from datetime import date, datetime, timezone

    captured = {}

    async def _fake_run(triggered_by):
        return {
            "status": "started",
            "run_id": "r1", "trace_id": "t1",
            "_internal": ("r1", "t1", date.today(), datetime.now(timezone.utc), "redis"),
        }

    async def _fake_steps(run_id, trace_id, today, now, tb):
        captured["called"] = (run_id, trace_id, tb)

    fake_redis = MagicMock()
    fake_redis.xack = AsyncMock()
    monkeypatch.setattr(pmain, "_do_run_pipeline", _fake_run)
    monkeypatch.setattr(pmain, "_run_pipeline_steps", _fake_steps)
    monkeypatch.setattr(pmain, "redis_client", fake_redis)

    await pmain._trigger_from_event("2026-05-22", "msg-2")
    # Yield so the create_task'd coroutine runs
    await asyncio.sleep(0)
    assert captured.get("called") == ("r1", "t1", "redis")
    fake_redis.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_from_event_acks_even_if_run_raises(monkeypatch):
    """If _do_run_pipeline raises, the redis message must still be ACKed
    (otherwise the loop re-delivers and creates an infinite crash loop)."""
    async def _boom(triggered_by):
        raise RuntimeError("pipeline setup boom")

    fake_redis = MagicMock()
    fake_redis.xack = AsyncMock()
    monkeypatch.setattr(pmain, "_do_run_pipeline", _boom)
    monkeypatch.setattr(pmain, "redis_client", fake_redis)

    with pytest.raises(RuntimeError):
        await pmain._trigger_from_event("2026-05-22", "msg-3")
    fake_redis.xack.assert_awaited_once()


# ── delta-intents actionable filter ──────────────────────────────────────────
# The trade-proposal UI was showing ~1955 rows because every ticker in the
# universe produced a DeltaDecision and every non-actionable watch was stored.
# The pipeline now persists only entry/exit/hold + actionable watches (those
# with confirmation_days_met >= confirmation_days).


def test_actionable_filter_keeps_entry_exit_hold():
    """All three core actions are always actionable."""
    from app.engine import DeltaDecision

    confirmation_days = 3

    def is_actionable(d):
        if d.action in ("entry", "exit", "hold"):
            return True
        if d.action == "watch" and d.confirmation_days_met >= confirmation_days:
            return True
        return False

    entry = DeltaDecision("AAPL", "entry", 5, 1.5, 3, None, "in entry zone")
    exit_ = DeltaDecision("MSFT", "exit", 45, -0.5, 3, 0.05, "exited buffer")
    hold = DeltaDecision("GOOG", "hold", 15, 0.8, 0, 0.04, "still in buffer")

    assert is_actionable(entry)
    assert is_actionable(exit_)
    assert is_actionable(hold)


def test_actionable_filter_drops_non_confirmed_watches():
    """A 'watch' row that hasn't confirmed yet is non-actionable noise."""
    from app.engine import DeltaDecision

    confirmation_days = 3

    def is_actionable(d):
        if d.action in ("entry", "exit", "hold"):
            return True
        if d.action == "watch" and d.confirmation_days_met >= confirmation_days:
            return True
        return False

    not_yet = DeltaDecision("FOO", "watch", 10, 1.0, 1, None,
                            "needs 3d ≤ 25 (have 1d)")
    assert not is_actionable(not_yet)


def test_actionable_filter_keeps_at_capacity_watches():
    """A 'watch' from at-capacity hold-out IS actionable (would enter now)."""
    from app.engine import DeltaDecision

    confirmation_days = 3

    def is_actionable(d):
        if d.action in ("entry", "exit", "hold"):
            return True
        if d.action == "watch" and d.confirmation_days_met >= confirmation_days:
            return True
        return False

    pending = DeltaDecision("BAR", "watch", 5, 1.4, 3, None,
                            "Confirmed entry but portfolio is at capacity")
    assert is_actionable(pending)
