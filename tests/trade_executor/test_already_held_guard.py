"""Unit tests for the _is_already_held helper in trade-executor.

Tests mock the SQLAlchemy connection so the helper can be exercised in
isolation without a real Postgres. The mock connection serves a configured
sequence of dict rows for each conn.execute(...).mappings().first() call.

_is_already_held makes exactly ONE DB query, so rows is a list of one item.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.main import EXIT_SYNC_MAX_AGE_HOURS, _is_already_held


def _mock_conn_returning(rows):
    """Return a fake async connection whose conn.execute(...).mappings().first()
    yields rows from `rows` in order. None means 'no row found'."""
    conn = AsyncMock()
    call_count = [0]

    async def _execute(query, params=None):
        result = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        row = rows[idx] if idx < len(rows) else None
        mr = MagicMock()
        mr.first = MagicMock(return_value=row)
        result.mappings = MagicMock(return_value=mr)
        return result

    conn.execute = _execute
    return conn


@pytest.mark.asyncio
async def test_not_held_when_no_sync_data():
    """No sync data at all → (False, None)."""
    conn = _mock_conn_returning([None])
    held, qty = await _is_already_held(conn, "AAPL")
    assert held is False
    assert qty is None


@pytest.mark.asyncio
async def test_held_when_qty_positive():
    """Row with qty=150 and recent completed_at → (True, 150.0)."""
    conn = _mock_conn_returning([
        {"qty": 150.0, "completed_at": datetime.now(timezone.utc) - timedelta(hours=1)},
    ])
    held, qty = await _is_already_held(conn, "MSFT")
    assert held is True
    assert qty == pytest.approx(150.0)


@pytest.mark.asyncio
async def test_not_held_when_qty_is_zero():
    """SQL filters qty>0 so a zero-qty row would not be returned — None → (False, None)."""
    # The SQL has `lp.qty > 0` so a 0-qty position returns no row.
    conn = _mock_conn_returning([None])
    held, qty = await _is_already_held(conn, "GOOG")
    assert held is False
    assert qty is None


@pytest.mark.asyncio
async def test_not_held_when_sync_is_stale():
    """Row present but completed_at is EXIT_SYNC_MAX_AGE_HOURS+1 hours ago → (False, None).

    The stale-sync guard delegates to _size_entry's dedicated error instead of
    blocking with a misleading 'already held' message.
    """
    stale_at = datetime.now(timezone.utc) - timedelta(hours=EXIT_SYNC_MAX_AGE_HOURS + 1)
    conn = _mock_conn_returning([
        {"qty": 100.0, "completed_at": stale_at},
    ])
    held, qty = await _is_already_held(conn, "NVDA")
    assert held is False
    assert qty is None


@pytest.mark.asyncio
async def test_held_when_sync_is_fresh_at_boundary():
    """completed_at exactly EXIT_SYNC_MAX_AGE_HOURS-0.1 hours ago (NOT stale) → (True, 100.0)."""
    fresh_at = datetime.now(timezone.utc) - timedelta(hours=EXIT_SYNC_MAX_AGE_HOURS - 0.1)
    conn = _mock_conn_returning([
        {"qty": 100.0, "completed_at": fresh_at},
    ])
    held, qty = await _is_already_held(conn, "TSLA")
    assert held is True
    assert qty == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_held_with_fractional_qty():
    """Fractional shares (qty=0.5) are held → (True, 0.5)."""
    conn = _mock_conn_returning([
        {"qty": 0.5, "completed_at": datetime.now(timezone.utc) - timedelta(minutes=30)},
    ])
    held, qty = await _is_already_held(conn, "AMZN")
    assert held is True
    assert qty == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_not_held_when_completed_at_is_none():
    """Row returned but completed_at is None → staleness check skipped, trust the data → (True, qty)."""
    conn = _mock_conn_returning([
        {"qty": 75.0, "completed_at": None},
    ])
    held, qty = await _is_already_held(conn, "META")
    assert held is True
    assert qty == pytest.approx(75.0)
