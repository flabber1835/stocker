"""
Unit tests for _has_universe() — the function that gates the cold-start path.

_has_universe() is the single point of truth the supervisor uses to decide
whether to trigger fetch-universe.  It must return three distinct values:

  True   — HTTP 200 with universe_tickers > 0   (universe exists, proceed)
  False  — HTTP 200 with universe_tickers == 0  (definitely empty, trigger fetch)
  None   — anything else (unreachable, 5xx, timeout, etc.)

None is the critical case: before the fix it collapsed into False, causing the
supervisor to trigger fetch-universe on every 30-second catch-up tick while
av-ingestor was still booting — burning Alpha Vantage quota on redundant
full-universe downloads even though the DB already had 6498 tickers.

These tests call _has_universe() directly (not mocked) to verify that the
real HTTP response → return-value mapping is correct.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Stub apscheduler so app.main can be imported without the real package ─────

def _make_apscheduler_stubs():
    sys.modules.setdefault("apscheduler", types.ModuleType("apscheduler"))
    schedulers_pkg = types.ModuleType("apscheduler.schedulers")
    asyncio_mod = types.ModuleType("apscheduler.schedulers.asyncio")
    asyncio_mod.AsyncIOScheduler = MagicMock()
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

from app.main import _has_universe  # noqa: E402
import httpx  # noqa: E402


def _mock_client(status_code: int, body: dict | None = None) -> MagicMock:
    """Build a mock httpx.AsyncClient whose GET returns the given status and body."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=body or {})
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    return client


# ── True: universe is populated ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_returns_true_when_tickers_populated():
    """/status 200 with universe_tickers=6498 → True."""
    client = _mock_client(200, {"universe_tickers": 6498, "price_rows": 19_000_000})
    result = await _has_universe(client)
    assert result is True


@pytest.mark.asyncio
async def test_returns_true_when_exactly_one_ticker():
    """/status 200 with universe_tickers=1 → True (boundary)."""
    client = _mock_client(200, {"universe_tickers": 1})
    result = await _has_universe(client)
    assert result is True


# ── False: definitively empty ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_returns_false_when_tickers_zero():
    """/status 200 with universe_tickers=0 → False (empty DB, trigger fetch)."""
    client = _mock_client(200, {"universe_tickers": 0})
    result = await _has_universe(client)
    assert result is False


@pytest.mark.asyncio
async def test_returns_false_when_tickers_missing_from_payload():
    """/status 200 with no universe_tickers key → False (treat as 0)."""
    client = _mock_client(200, {"price_rows": 100})
    result = await _has_universe(client)
    assert result is False


@pytest.mark.asyncio
async def test_returns_false_when_tickers_null_in_payload():
    """/status 200 with universe_tickers=null → False."""
    client = _mock_client(200, {"universe_tickers": None})
    result = await _has_universe(client)
    assert result is False


# ── None: can't determine — av-ingestor not reachable / not ready ─────────────
#
# REGRESSION: before the fix all of these returned False, causing the supervisor
# to treat "av-ingestor is booting" as "no universe" and trigger fetch-universe
# on every 30-second catch-up tick.

@pytest.mark.asyncio
async def test_returns_none_on_connection_refused():
    """ConnectError (av-ingestor not yet started) → None, not False.

    REGRESSION: was returning False, triggering runaway fetch-universe loop.
    """
    client = MagicMock()
    client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
    result = await _has_universe(client)
    assert result is None, (
        "ConnectError must return None (unknown), not False (no universe). "
        "Returning False here causes fetch-universe to fire on every startup tick."
    )


@pytest.mark.asyncio
async def test_returns_none_on_timeout():
    """ReadTimeout (av-ingestor overloaded / slow to start) → None, not False.

    REGRESSION: was returning False, triggering runaway fetch-universe loop.
    """
    client = MagicMock()
    client.get = AsyncMock(side_effect=httpx.ReadTimeout("timed out"))
    result = await _has_universe(client)
    assert result is None, (
        "ReadTimeout must return None, not False."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [500, 502, 503, 422])
async def test_returns_none_on_non_200_response(status_code: int):
    """Non-200 HTTP (av-ingestor booting, DB pool not ready) → None, not False.

    REGRESSION: was returning False because non-200 fell through the
    `if r.status_code == 200:` guard and hit `return False`.
    """
    client = _mock_client(status_code, {})
    result = await _has_universe(client)
    assert result is None, (
        f"HTTP {status_code} must return None (unknown), not False (no universe). "
        "Returning False here causes fetch-universe to fire while av-ingestor is "
        "still booting."
    )


@pytest.mark.asyncio
async def test_returns_none_on_general_exception():
    """Unexpected exception during GET → None, not False."""
    client = MagicMock()
    client.get = AsyncMock(side_effect=RuntimeError("unexpected"))
    result = await _has_universe(client)
    assert result is None
