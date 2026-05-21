"""
Tests for _already_ran_today and _startup_catch_up in app.main.

We avoid importing the full FastAPI app (which requires APScheduler and network
services). Instead we stub out the missing optional dependencies at the module
level before importing, then import the helper functions directly and patch
httpx client responses with a minimal mock.
"""
import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Stub out apscheduler so app.main can be imported without the real package ──

def _make_apscheduler_stubs():
    """Insert lightweight stubs for apscheduler modules into sys.modules."""
    # apscheduler.schedulers.asyncio
    schedulers_pkg = types.ModuleType("apscheduler.schedulers")
    asyncio_mod = types.ModuleType("apscheduler.schedulers.asyncio")
    asyncio_mod.AsyncIOScheduler = MagicMock()
    sys.modules.setdefault("apscheduler", types.ModuleType("apscheduler"))
    sys.modules.setdefault("apscheduler.schedulers", schedulers_pkg)
    sys.modules.setdefault("apscheduler.schedulers.asyncio", asyncio_mod)

    # apscheduler.triggers.cron
    triggers_pkg = types.ModuleType("apscheduler.triggers")
    cron_mod = types.ModuleType("apscheduler.triggers.cron")
    cron_mod.CronTrigger = MagicMock()
    sys.modules.setdefault("apscheduler.triggers", triggers_pkg)
    sys.modules.setdefault("apscheduler.triggers.cron", cron_mod)


_make_apscheduler_stubs()

from app.main import _already_ran_today, _startup_catch_up, _supervisor_tick  # noqa: E402


# ── Minimal httpx response mock ───────────────────────────────────────────────

def _mock_client(status_code: int = 200, payload: dict | None = None):
    """Return an AsyncMock httpx.AsyncClient whose GET returns the given payload."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload or {}

    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    return client


# ── _already_ran_today ────────────────────────────────────────────────────────

class TestAlreadyRanToday:

    @pytest.mark.asyncio
    async def test_accepts_success(self):
        """A 'success' run dated today is accepted."""
        payload = {
            "status": "success",
            "completed_at": "2026-05-17T10:00:00",
            "job_type": "fetch-data",
        }
        client = _mock_client(200, payload)
        result = await _already_ran_today(
            client,
            service_url="http://fake",
            date_field="completed_at",
            today="2026-05-17",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_rejects_partial_success_without_extra_statuses(self):
        """partial_success is NOT accepted by default (extra_ok_statuses empty)."""
        payload = {
            "status": "partial_success",
            "completed_at": "2026-05-17T10:00:00",
        }
        client = _mock_client(200, payload)
        result = await _already_ran_today(
            client,
            service_url="http://fake",
            date_field="completed_at",
            today="2026-05-17",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_accepts_partial_success_with_extra_statuses(self):
        """partial_success is accepted when passed via extra_ok_statuses."""
        payload = {
            "status": "partial_success",
            "completed_at": "2026-05-17T10:00:00",
        }
        client = _mock_client(200, payload)
        result = await _already_ran_today(
            client,
            service_url="http://fake",
            date_field="completed_at",
            today="2026-05-17",
            extra_ok_statuses=("partial_success",),
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_rejects_wrong_date(self):
        """Yesterday's successful run does not count for today."""
        payload = {
            "status": "success",
            "completed_at": "2026-05-16T10:00:00",
        }
        client = _mock_client(200, payload)
        result = await _already_ran_today(
            client,
            service_url="http://fake",
            date_field="completed_at",
            today="2026-05-17",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_uses_started_at_field(self):
        """
        A run that started today but completed after UTC midnight is still
        recognised as today's run when date_field='started_at'.
        """
        payload = {
            "status": "success",
            "started_at": "2026-05-17T23:55:00",
            "completed_at": "2026-05-18T00:05:00",
        }
        client = _mock_client(200, payload)
        result = await _already_ran_today(
            client,
            service_url="http://fake",
            date_field="started_at",
            today="2026-05-17",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_non_200(self):
        """Non-200 HTTP response is treated as 'not done'."""
        client = _mock_client(status_code=404, payload={})
        result = await _already_ran_today(
            client,
            service_url="http://fake",
            date_field="completed_at",
            today="2026-05-17",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        """Network exception is swallowed and treated as 'not done'."""
        client = MagicMock()
        client.get = AsyncMock(side_effect=Exception("connection refused"))
        result = await _already_ran_today(
            client,
            service_url="http://fake",
            date_field="completed_at",
            today="2026-05-17",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_job_type_filter_passes(self):
        """job_type_filter matches → accepted."""
        payload = {
            "status": "success",
            "completed_at": "2026-05-17T10:00:00",
            "job_type": "fetch-data",
        }
        client = _mock_client(200, payload)
        result = await _already_ran_today(
            client,
            service_url="http://fake",
            date_field="completed_at",
            today="2026-05-17",
            job_type_filter="fetch-data",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_job_type_filter_blocks_wrong_type(self):
        """job_type_filter mismatch → rejected even though status/date match."""
        payload = {
            "status": "success",
            "completed_at": "2026-05-17T10:00:00",
            "job_type": "fetch-prices",  # different job type
        }
        client = _mock_client(200, payload)
        result = await _already_ran_today(
            client,
            service_url="http://fake",
            date_field="completed_at",
            today="2026-05-17",
            job_type_filter="fetch-data",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_rejects_failed_status(self):
        """A 'failed' run is not considered as already ran successfully."""
        payload = {
            "status": "failed",
            "completed_at": "2026-05-17T10:00:00",
        }
        client = _mock_client(200, payload)
        result = await _already_ran_today(
            client,
            service_url="http://fake",
            date_field="completed_at",
            today="2026-05-17",
        )
        assert result is False


# ── _startup_catch_up ────────────────────────────────────────────────────────

class TestStartupCatchUp:

    @pytest.mark.asyncio
    async def test_exception_in_chain_is_caught(self):
        """
        If _supervisor_tick raises, _startup_catch_up must catch it
        and not propagate the exception to the caller.
        """
        with (
            patch("app.main.asyncio.sleep", new=AsyncMock()),  # skip the 10s delay
            patch.dict(
                _startup_catch_up.__globals__,
                {"_supervisor_tick": AsyncMock(side_effect=RuntimeError("test error"))},
            ),
        ):
            # Should complete without raising
            await _startup_catch_up()

    @pytest.mark.asyncio
    async def test_supervisor_tick_called_once_on_startup(self):
        """
        _startup_catch_up always fires exactly one supervisor tick after the delay.
        """
        mock_tick = AsyncMock()
        with (
            patch("app.main.asyncio.sleep", new=AsyncMock()),
            patch.dict(_startup_catch_up.__globals__, {"_supervisor_tick": mock_tick}),
        ):
            await _startup_catch_up()
        mock_tick.assert_called_once()

    @pytest.mark.asyncio
    async def test_catchup_triggered_when_stale(self):
        """
        _startup_catch_up fires the supervisor tick regardless of staleness.
        The staleness logic now lives inside the tick itself.
        """
        mock_tick = AsyncMock()
        with (
            patch.dict(_startup_catch_up.__globals__, {"_supervisor_tick": mock_tick}),
            patch("asyncio.sleep", new=AsyncMock()),   # patches real asyncio module
        ):
            await _startup_catch_up()
        mock_tick.assert_called_once()
