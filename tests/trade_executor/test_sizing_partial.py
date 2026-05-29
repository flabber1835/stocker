"""Unit tests for _size_partial (buy_add / sell_trim sizing).

Mirrors the pattern in test_sizing.py — mock the async DB connection so the
helper can be exercised in isolation without a real Postgres.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.main import _size_partial


def _now():
    return datetime.now(timezone.utc)


def _mock_conn(rows: list):
    """Fake async connection whose conn.execute(...).mappings().first() pops rows in order."""
    conn = AsyncMock()
    call_count = [0]

    async def _execute(query, params=None):
        result = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        row = rows[idx] if idx < len(rows) else None
        mp = MagicMock()
        mp.first = MagicMock(return_value=row)
        result.mappings = MagicMock(return_value=mp)
        return result

    conn.execute = _execute
    return conn


def _intent(action: str, current_weight: float, actual_weight: float) -> dict:
    return {
        "action": action,
        "current_weight": current_weight,
        "actual_weight": actual_weight,
    }


# ── buy_add ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_buy_add_basic():
    """buy_add: (target - actual) × account / price, floored to whole shares."""
    # target=10%, actual=8%, account=$100k, price=$50
    # drift=2% × $100k = $2k, qty=floor($2k/$50)=40 shares
    conn = _mock_conn([
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},  # alpaca_sync_runs
        {"current_price": 50.0},                               # live_positions
    ])
    intent = _intent("buy_add", current_weight=0.10, actual_weight=0.08)
    qty, notional, summary = await _size_partial(conn, "AAPL", intent)
    assert qty == 40.0
    assert notional == pytest.approx(2000.0)
    assert summary["drift_weight"] == pytest.approx(0.02)
    assert summary["target_notional"] == pytest.approx(2000.0)


@pytest.mark.asyncio
async def test_buy_add_uses_daily_price_when_no_live():
    """buy_add falls back to daily_prices.close when no live_positions row."""
    conn = _mock_conn([
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
        None,             # no live_positions
        {"close": 40.0},  # daily_prices
    ])
    intent = _intent("buy_add", current_weight=0.10, actual_weight=0.08)
    qty, notional, summary = await _size_partial(conn, "AAPL", intent)
    # drift=2%×$100k=$2k, qty=floor($2k/$40)=50
    assert qty == 50.0
    assert summary["price_source"] == "daily_prices"


@pytest.mark.asyncio
async def test_buy_add_drift_too_small_raises_400():
    """buy_add aborted when drift rounds to zero shares."""
    # drift=0.1%×$100k=$100, price=$50k → qty=0
    conn = _mock_conn([
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
        {"current_price": 50_000.0},
    ])
    intent = _intent("buy_add", current_weight=0.10, actual_weight=0.099)
    with pytest.raises(HTTPException) as exc_info:
        await _size_partial(conn, "AAPL", intent)
    assert exc_info.value.status_code == 400
    assert "drift too small" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_buy_add_always_uses_account_value():
    """buy_add sizes against account_value (not buying_power) per spec:
    floor(account_value × drift / price).
    With account_value=$100k, drift=2% → notional=$2000 → floor($2000/$50)=40 shares.
    A separate buying_power guard is checked after sizing (tested below)."""
    conn = _mock_conn([
        {"account_value": 100_000.0, "buying_power": 20_000.0, "completed_at": _now()},
        {"current_price": 50.0},
    ])
    intent = _intent("buy_add", current_weight=0.10, actual_weight=0.08)
    qty, notional, summary = await _size_partial(conn, "AAPL", intent)
    assert qty == 40.0
    assert notional == pytest.approx(2000.0)
    assert summary["sizing_basis"] == "account_value"
    assert summary["buying_power"] == 20_000.0


@pytest.mark.asyncio
async def test_buy_add_raises_400_when_notional_exceeds_buying_power():
    """buy_add raises 400 if the target notional exceeds buying_power by >5%.
    This guards against submitting a buy when all cash is committed to pending sells."""
    conn = _mock_conn([
        # buying_power=$500 — much less than the $2000 notional for 2% drift on $100k
        {"account_value": 100_000.0, "buying_power": 500.0, "completed_at": _now()},
        {"current_price": 50.0},
    ])
    intent = _intent("buy_add", current_weight=0.10, actual_weight=0.08)
    with pytest.raises(HTTPException) as exc_info:
        await _size_partial(conn, "AAPL", intent)
    assert exc_info.value.status_code == 400
    assert "buying power" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_sell_trim_uses_account_value_not_buying_power():
    """sell_trim doesn't consume cash — it generates cash. So buying_power
    drained by pending orders shouldn't shrink a sell_trim's size."""
    conn = _mock_conn([
        {"account_value": 100_000.0, "buying_power": 20_000.0, "completed_at": _now()},
        {"current_price": 100.0},
    ])
    intent = _intent("sell_trim", current_weight=0.10, actual_weight=0.12)
    qty, notional, summary = await _size_partial(conn, "AAPL", intent)
    # drift=0.02 × $100k = $2000 → 20 shares (using account_value, not buying_power)
    assert qty == 19.0  # floating-point: 0.12-0.10 = 0.01999... → 19 floored
    assert summary["sizing_basis"] == "account_value"
    assert summary["account_value"] == 100_000.0


@pytest.mark.asyncio
async def test_buy_add_missing_weights_raises_400():
    """buy_add aborted when target_weight or actual_weight is missing."""
    conn = _mock_conn([])  # no queries should reach DB
    intent = {"action": "buy_add", "current_weight": None, "actual_weight": 0.08}
    with pytest.raises(HTTPException) as exc_info:
        await _size_partial(conn, "AAPL", intent)
    assert exc_info.value.status_code == 400
    assert "missing" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_buy_add_stale_sync_raises_409():
    """buy_add aborted when alpaca-sync is older than EXIT_SYNC_MAX_AGE_HOURS."""
    stale = _now() - timedelta(hours=48)
    conn = _mock_conn([
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": stale},
        {"current_price": 50.0},
    ])
    intent = _intent("buy_add", current_weight=0.10, actual_weight=0.08)
    with pytest.raises(HTTPException) as exc_info:
        await _size_partial(conn, "AAPL", intent)
    assert exc_info.value.status_code == 409
    assert "alpaca-sync" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_buy_add_no_account_raises_400():
    """buy_add aborted when no alpaca_sync_run row exists."""
    conn = _mock_conn([None])  # no sync run
    intent = _intent("buy_add", current_weight=0.10, actual_weight=0.08)
    with pytest.raises(HTTPException) as exc_info:
        await _size_partial(conn, "AAPL", intent)
    assert exc_info.value.status_code == 400


# ── sell_trim ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sell_trim_basic():
    """sell_trim: (actual - target) × account / price, floored to whole shares.

    Note: 0.12 - 0.10 = 0.01999... in IEEE 754 float, so
    notional = 0.01999... × $100k = $1999.99... → floor($1999.99/$100) = 19 shares.
    """
    conn = _mock_conn([
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
        {"current_price": 100.0},
    ])
    intent = _intent("sell_trim", current_weight=0.10, actual_weight=0.12)
    qty, notional, summary = await _size_partial(conn, "AAPL", intent)
    assert qty == 19.0
    assert notional == pytest.approx(1900.0)
    assert summary["drift_weight"] == pytest.approx(0.02, rel=1e-3)


@pytest.mark.asyncio
async def test_sell_trim_drift_too_small_raises_400():
    """sell_trim aborted when drift rounds to zero shares."""
    # drift=0.1%×$100k=$100, price=$10k → qty=0
    conn = _mock_conn([
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
        {"current_price": 10_000.0},
    ])
    intent = _intent("sell_trim", current_weight=0.10, actual_weight=0.101)
    with pytest.raises(HTTPException) as exc_info:
        await _size_partial(conn, "AAPL", intent)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_sell_trim_no_price_raises_400():
    """sell_trim aborted when neither live_positions nor daily_prices has a price."""
    conn = _mock_conn([
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
        None,   # no live_positions
        None,   # no daily_prices
    ])
    intent = _intent("sell_trim", current_weight=0.10, actual_weight=0.12)
    with pytest.raises(HTTPException) as exc_info:
        await _size_partial(conn, "AAPL", intent)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_sell_trim_actual_weight_missing_raises_400():
    """sell_trim aborted when actual_weight is None (intent lacks drift data)."""
    conn = _mock_conn([])
    intent = {"action": "sell_trim", "current_weight": 0.10, "actual_weight": None}
    with pytest.raises(HTTPException) as exc_info:
        await _size_partial(conn, "AAPL", intent)
    assert exc_info.value.status_code == 400
    assert "missing" in exc_info.value.detail.lower()


# ── Negative / non-finite weight guard ───────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_actual", [-0.05, -1.0, float("nan"), float("inf")])
async def test_buy_add_rejects_invalid_actual_weight(bad_actual):
    """buy_add with negative or non-finite actual_weight must return 400.

    Before the fix: negative actual_weight silently doubled the drift
    (target - (-actual) = target + actual), producing an over-sized order
    with no error.  NaN/Inf propagated into math.floor, raising an unhandled
    ValueError (500).
    """
    conn = _mock_conn([])  # guards fire before any DB queries
    intent = {"action": "buy_add", "current_weight": 0.05, "actual_weight": bad_actual}
    with pytest.raises(HTTPException) as exc_info:
        await _size_partial(conn, "AAPL", intent)
    assert exc_info.value.status_code == 400
    assert "invalid" in exc_info.value.detail.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_actual", [-0.05, -1.0, float("nan"), float("inf")])
async def test_sell_trim_rejects_invalid_actual_weight(bad_actual):
    """sell_trim with negative or non-finite actual_weight must return 400.

    Before the fix: negative actual_weight produced a negative drift
    (negative - target < 0) which caused qty < 1 and a misleading 'drift
    too small' error rather than a clear 'invalid weights' error.
    """
    conn = _mock_conn([])
    intent = {"action": "sell_trim", "current_weight": 0.05, "actual_weight": bad_actual}
    with pytest.raises(HTTPException) as exc_info:
        await _size_partial(conn, "AAPL", intent)
    assert exc_info.value.status_code == 400
    assert "invalid" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_buy_add_negative_actual_weight_would_have_over_bought():
    """Regression: actual_weight=-0.05 with target=0.05 previously gave
    drift=0.10 instead of 0.05, silently doubling the order size."""
    # This test documents the pre-fix behaviour by showing the guard now fires.
    conn = _mock_conn([])
    intent = {"action": "buy_add", "current_weight": 0.05, "actual_weight": -0.05}
    with pytest.raises(HTTPException) as exc_info:
        await _size_partial(conn, "AAPL", intent)
    assert exc_info.value.status_code == 400
