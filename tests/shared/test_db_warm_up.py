"""
Tests for stock_strategy_shared.db.warm_up_db_in_background.

Regression for the slow-NAS startup loop: blocking on wait_for_db inside the
FastAPI lifespan kept uvicorn from accepting HTTP requests, so docker's
healthcheck (start_period=20s + 5*5s = 45s) failed before wait_for_db's 90s
max could finish — restart: unless-stopped then put the container into a loop
the service could never escape. User-visible: "Container … Error78.4s" in
docker compose up output on Synology NAS.

The fix is warm_up_db_in_background: schedule wait_for_db as a background task
so lifespan can yield immediately. /health responds the moment uvicorn binds;
DB-dependent endpoints fail naturally (engine.begin raises) until the warm-up
task succeeds.
"""
import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from stock_strategy_shared.db import warm_up_db_in_background


class _FakeEngine:
    """Minimal stand-in for an AsyncEngine — only the methods wait_for_db touches."""
    def __init__(self, *, fail_count: int = 0, sleep_per_attempt: float = 0.0):
        self.fail_count = fail_count
        self.sleep_per_attempt = sleep_per_attempt
        self.attempts = 0

    def begin(self):
        return _FakeContext(self)


class _FakeContext:
    def __init__(self, engine: _FakeEngine):
        self.engine = engine

    async def __aenter__(self):
        if self.engine.sleep_per_attempt:
            await asyncio.sleep(self.engine.sleep_per_attempt)
        self.engine.attempts += 1
        if self.engine.attempts <= self.engine.fail_count:
            raise ConnectionError("DB not ready")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, *args, **kwargs):
        return None


class TestWarmUpDoesNotBlock:
    """warm_up_db_in_background must return a task immediately, not block on
    the DB ping. This is the whole point — lifespan needs to yield within
    seconds so uvicorn can serve /health before docker's healthcheck expires."""

    @pytest.mark.asyncio
    async def test_returns_immediately_even_when_db_is_unreachable(self):
        """Even with a DB that will never come up, warm_up returns immediately."""
        # 10 retries × 0.05s delay = 0.5s — short enough that the test doesn't
        # actually wait, but verifies the background task doesn't block the caller.
        from stock_strategy_shared import db as db_mod
        original_wait = db_mod.wait_for_db
        async def slow_wait(*args, **kwargs):
            await asyncio.sleep(1.0)
        db_mod.wait_for_db = slow_wait
        try:
            engine = _FakeEngine(fail_count=999)  # never succeeds
            t0 = time.monotonic()
            task = warm_up_db_in_background(engine, "test-service")
            elapsed = time.monotonic() - t0
            assert elapsed < 0.1, (
                f"warm_up_db_in_background must return immediately; took {elapsed:.3f}s. "
                f"If this is slow, the lifespan refactor's whole purpose is defeated — "
                f"uvicorn can't bind /health in time for docker's healthcheck."
            )
            assert isinstance(task, asyncio.Task)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        finally:
            db_mod.wait_for_db = original_wait

    @pytest.mark.asyncio
    async def test_warm_up_task_completes_when_db_becomes_available(self):
        """The task awaits wait_for_db; once it succeeds, the task ends cleanly."""
        engine = _FakeEngine(fail_count=0)  # succeeds first try
        # Patch the module-level wait_for_db to use a very short delay so the
        # task completes in test-time.
        from stock_strategy_shared import db as db_mod
        original = db_mod.wait_for_db
        async def quick_wait(eng, retries=30, delay=3.0):
            return await original(eng, retries=2, delay=0.05)
        db_mod.wait_for_db = quick_wait
        try:
            task = warm_up_db_in_background(engine, "test-service")
            await asyncio.wait_for(task, timeout=1.0)
            assert task.done()
            assert task.exception() is None
            assert engine.attempts >= 1
        finally:
            db_mod.wait_for_db = original

    @pytest.mark.asyncio
    async def test_warm_up_failure_does_not_propagate(self):
        """If wait_for_db ultimately fails, the task records the error but does
        NOT raise out — otherwise unhandled task exceptions would log loudly
        and confuse operators. The service stays up serving /health."""
        engine = _FakeEngine(fail_count=999)
        from stock_strategy_shared import db as db_mod
        original = db_mod.wait_for_db
        async def quick_fail(eng, retries=30, delay=3.0):
            return await original(eng, retries=2, delay=0.01)
        db_mod.wait_for_db = quick_fail
        try:
            task = warm_up_db_in_background(engine, "test-service")
            await asyncio.wait_for(task, timeout=1.0)
            assert task.done()
            # Crucially: the task swallowed the exception, NOT re-raised.
            assert task.exception() is None, (
                "warm_up task must not raise — an unhandled exception would log "
                "loudly and might trigger asyncio error handlers, and there's "
                "nothing for the caller to do about a DB that's never coming up"
            )
        finally:
            db_mod.wait_for_db = original
