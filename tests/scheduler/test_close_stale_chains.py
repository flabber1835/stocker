"""Tests for _close_stale_running_chains — startup cleanup of orphaned chain rows.

A chain interrupted by a deploy/crash leaves a scheduler_runs row at
status='running'. The date-rollover path only closes the run held in memory; a
row abandoned across a restart is never closed (we observed 05-28/29/30 all stuck
'running'). On startup we mark prior-day 'running' rows 'failed'. Today's row is
left untouched so _restore_force_pending can legitimately resume it.
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_apscheduler_stubs():
    for name in ("apscheduler", "apscheduler.schedulers", "apscheduler.schedulers.asyncio",
                 "apscheduler.triggers", "apscheduler.triggers.cron", "apscheduler.triggers.interval"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["apscheduler.schedulers.asyncio"].AsyncIOScheduler = MagicMock()
    sys.modules["apscheduler.triggers.cron"].CronTrigger = MagicMock()
    sys.modules["apscheduler.triggers.interval"].IntervalTrigger = MagicMock()


_make_apscheduler_stubs()

from app.main import _close_stale_running_chains  # noqa: E402


@pytest.mark.asyncio
async def test_closes_prior_day_running_rows_and_spares_today():
    """The UPDATE targets only chain_date < today; returns the count parsed from
    asyncpg's 'UPDATE n' status string."""
    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 3")
    conn.close = AsyncMock()

    with patch.dict(_close_stale_running_chains.__globals__,
                    {"_db_connect": AsyncMock(return_value=conn)}):
        n = await _close_stale_running_chains()

    assert n == 3
    # Verify the query filters by chain_date < today (the bind param) and only
    # touches 'running' rows.
    sql, param = conn.execute.await_args.args
    assert "status='running'" in sql
    # chain_date is compared as text (::text cast) so a future DATE migration of the
    # column can't make asyncpg reject the ISO-string bind param.
    assert "chain_date::text < $1" in sql
    assert "SET status='failed'" in sql
    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_zero_rows_when_nothing_stale():
    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 0")
    conn.close = AsyncMock()
    with patch.dict(_close_stale_running_chains.__globals__,
                    {"_db_connect": AsyncMock(return_value=conn)}):
        n = await _close_stale_running_chains()
    assert n == 0


@pytest.mark.asyncio
async def test_no_db_returns_zero():
    with patch("app.main._db_connect", new=AsyncMock(return_value=None)):
        n = await _close_stale_running_chains()
    assert n == 0


@pytest.mark.asyncio
async def test_db_error_is_swallowed():
    """A failure here must never crash startup — returns 0, still closes conn."""
    conn = MagicMock()
    conn.execute = AsyncMock(side_effect=RuntimeError("boom"))
    conn.close = AsyncMock()
    with patch.dict(_close_stale_running_chains.__globals__,
                    {"_db_connect": AsyncMock(return_value=conn)}):
        n = await _close_stale_running_chains()
    assert n == 0
    conn.close.assert_awaited_once()
