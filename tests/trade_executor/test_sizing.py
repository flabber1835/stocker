"""Unit tests for trade-executor sizing helpers (_size_entry and _size_exit).

These tests mock the SQLAlchemy connection so each helper can be exercised in
isolation without a real Postgres. The mock connection serves a configured
sequence of dict rows for each conn.execute(...).mappings().first() call.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.main import _size_entry, _size_exit


def _now():
    """Fresh-sync timestamp for entry-sizing mocks (within EXIT_SYNC_MAX_AGE_HOURS)."""
    return datetime.now(timezone.utc)


def _mock_conn_returning(rows_by_query):
    """Return a fake async connection whose conn.execute(...).mappings().first()
    yields rows from `rows_by_query` in order. `None` means "no row found"."""
    conn = AsyncMock()
    call_count = [0]

    async def _execute(query, params=None):
        result = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        row = rows_by_query[idx] if idx < len(rows_by_query) else None
        mappings_result = MagicMock()
        mappings_result.first = MagicMock(return_value=row)
        result.mappings = MagicMock(return_value=mappings_result)
        return result

    conn.execute = _execute
    return conn


# ── _size_entry tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_size_entry_basic():
    # Order of queries in _size_entry when intent_weight is provided:
    # 1. account_value, 2. live_positions price
    conn = _mock_conn_returning([
        {"account_value": 100_000.0, "completed_at": _now()},      # alpaca_sync_runs.account_value
        {"current_price": 50.0},           # live_positions.current_price
    ])
    qty, notional, summary = await _size_entry(conn, "AAPL", intent_weight=0.05)
    assert qty == 100.0
    assert notional == 5000.0
    assert summary["weight"] == 0.05
    assert summary["weight_source"] == "intent"
    assert summary["account_value"] == 100_000.0
    assert summary["last_price"] == 50.0
    assert summary["price_source"] == "live_positions"


@pytest.mark.asyncio
async def test_size_entry_uses_intent_weight_first():
    conn = _mock_conn_returning([
        {"account_value": 100_000.0, "completed_at": _now()},
        {"current_price": 50.0},
    ])
    _, _, summary = await _size_entry(conn, "AAPL", intent_weight=0.04)
    assert summary["weight"] == 0.04
    assert summary["weight_source"] == "intent"


@pytest.mark.asyncio
async def test_size_entry_falls_back_to_portfolio_holdings():
    # intent_weight=None → query portfolio_holdings first, then account, then price
    conn = _mock_conn_returning([
        {"weight": 0.06},                   # portfolio_holdings.weight
        {"account_value": 100_000.0, "completed_at": _now()},       # alpaca_sync_runs.account_value
        {"current_price": 50.0},            # live_positions.current_price
    ])
    qty, notional, summary = await _size_entry(conn, "AAPL", intent_weight=None)
    assert summary["weight"] == 0.06
    assert summary["weight_source"] == "portfolio_holdings"
    # 100000 * 0.06 / 50 = 120
    assert qty == 120.0


@pytest.mark.asyncio
async def test_size_entry_falls_back_to_default_when_all_missing():
    conn = _mock_conn_returning([
        None,                               # no portfolio_holdings row
        {"account_value": 100_000.0, "completed_at": _now()},
        {"current_price": 50.0},
    ])
    _, _, summary = await _size_entry(conn, "AAPL", intent_weight=None)
    # DEFAULT_MAX_POSITIONS=30 → 1/30
    assert summary["weight"] == pytest.approx(1.0 / 30)
    assert summary["weight_source"] == "default"


@pytest.mark.asyncio
async def test_size_entry_uses_live_price_when_available():
    # intent_weight provided → only 2 queries: account_value, live_price
    conn = _mock_conn_returning([
        {"account_value": 100_000.0, "completed_at": _now()},
        {"current_price": 45.0},
    ])
    _, _, summary = await _size_entry(conn, "AAPL", intent_weight=0.05)
    assert summary["last_price"] == 45.0
    assert summary["price_source"] == "live_positions"


@pytest.mark.asyncio
async def test_size_entry_falls_back_to_daily_close_when_no_live():
    # intent_weight provided. Queries: account_value, live_price(None), daily_prices.close
    conn = _mock_conn_returning([
        {"account_value": 100_000.0, "completed_at": _now()},
        None,                               # no live_positions row
        {"close": 48.0},                    # daily_prices.close
    ])
    _, _, summary = await _size_entry(conn, "AAPL", intent_weight=0.05)
    assert summary["last_price"] == 48.0
    assert summary["price_source"] == "daily_prices"


@pytest.mark.asyncio
async def test_size_entry_aborts_when_qty_below_one():
    # account=$1000, weight=0.01 → notional $10, price $500 → qty_int = 0
    conn = _mock_conn_returning([
        {"account_value": 1000.0, "completed_at": _now()},
        {"current_price": 500.0},
    ])
    with pytest.raises(HTTPException) as exc_info:
        await _size_entry(conn, "AAPL", intent_weight=0.01)
    assert exc_info.value.status_code == 400
    assert "Position too small" in exc_info.value.detail


@pytest.mark.asyncio
async def test_size_entry_aborts_when_no_account_value():
    conn = _mock_conn_returning([
        None,                               # alpaca_sync_runs returns None
        {"current_price": 50.0},
    ])
    with pytest.raises(HTTPException) as exc_info:
        await _size_entry(conn, "AAPL", intent_weight=0.05)
    assert exc_info.value.status_code == 400
    assert "account_value=None" in exc_info.value.detail


@pytest.mark.asyncio
async def test_size_entry_aborts_when_no_price():
    conn = _mock_conn_returning([
        {"account_value": 100_000.0, "completed_at": _now()},
        None,                               # no live_positions
        None,                               # no daily_prices
    ])
    with pytest.raises(HTTPException) as exc_info:
        await _size_entry(conn, "AAPL", intent_weight=0.05)
    assert exc_info.value.status_code == 400


# ── _size_exit tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_size_exit_basic():
    now = datetime.now(timezone.utc)
    conn = _mock_conn_returning([
        {"qty": 50.0, "current_price": 60.0, "completed_at": now},
    ])
    qty, notional, summary = await _size_exit(conn, "AAPL")
    assert qty == 50.0
    assert notional == 3000.0
    assert summary["source"] == "live_positions"
    assert summary["current_price"] == 60.0


@pytest.mark.asyncio
async def test_size_exit_no_position_raises_400():
    conn = _mock_conn_returning([None])
    with pytest.raises(HTTPException) as exc_info:
        await _size_exit(conn, "AAPL")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_size_exit_stale_sync_raises_409():
    stale = datetime.now(timezone.utc) - timedelta(hours=48)
    conn = _mock_conn_returning([
        {"qty": 50.0, "current_price": 60.0, "completed_at": stale},
    ])
    with pytest.raises(HTTPException) as exc_info:
        await _size_exit(conn, "AAPL")
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_size_exit_returns_abs_qty_for_short():
    now = datetime.now(timezone.utc)
    conn = _mock_conn_returning([
        {"qty": -25.0, "current_price": 60.0, "completed_at": now},
    ])
    qty, notional, _ = await _size_exit(conn, "AAPL")
    assert qty == 25.0
    assert notional == 1500.0
