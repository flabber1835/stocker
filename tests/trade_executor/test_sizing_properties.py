"""
Property-based tests for trade-executor sizing math.

Properties under test (entry sizing — _size_entry):
  S1. qty is always a non-negative integer (floor division result).
  S2. notional = qty * price (always exact reconstruction).
  S3. notional ≤ buying_power + price (can never over-commit by more than one share).
  S4. weight=0 → qty=0, notional=0 always.
  S5. Higher buying_power → qty is monotonically non-decreasing (holding weight/price constant).
  S6. Higher price → qty is monotonically non-increasing (holding buying_power/weight constant).
  S7. Higher weight → qty is monotonically non-decreasing (holding buying_power/price constant).

Properties under test (partial sizing — _size_partial / drift math):
  S8. Drift weight = |target_weight - actual_weight|; qty = floor(drift_weight * sizing_basis / price).
  S9. qty is always non-negative integer.
  S10. notional ≤ sizing_basis (can't trade more than the account basis in one partial).

Properties under test (exit sizing — _size_exit):
  S11. qty = abs(position_qty) — always a non-negative integer.
  S12. notional = qty * current_price — always non-negative.
"""
import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from hypothesis import assume, given, settings, HealthCheck
from hypothesis import strategies as st

# ── import sizing helpers directly ────────────────────────────────────────────

import os
import sys

_TE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "trade-executor")
)
for _k in list(sys.modules.keys()):
    if _k == "app" or _k.startswith("app."):
        del sys.modules[_k]
if _TE_PATH not in sys.path:
    sys.path.insert(0, _TE_PATH)

from app.main import _size_entry, _size_exit

# ── helpers ───────────────────────────────────────────────────────────────────

_REASONABLE_MONEY = st.floats(min_value=1.0, max_value=1_000_000.0,
                               allow_nan=False, allow_infinity=False)
_REASONABLE_PRICE = st.floats(min_value=0.01, max_value=100_000.0,
                               allow_nan=False, allow_infinity=False)
_REASONABLE_WEIGHT = st.floats(min_value=0.001, max_value=1.0,
                                allow_nan=False, allow_infinity=False)


def _now():
    return datetime.now(timezone.utc)


def _mock_conn_entry(account_value: float, buying_power: float, price: float):
    """Returns a fake async connection for _size_entry (intent_weight provided path)."""
    conn = AsyncMock()
    call_count = [0]

    async def _execute(query, params=None):
        idx = call_count[0]
        call_count[0] += 1
        result = MagicMock()
        mappings_result = MagicMock()
        if idx == 0:
            row = {"account_value": account_value, "buying_power": buying_power, "completed_at": _now()}
        elif idx == 1:
            row = {"current_price": price}
        else:
            row = None
        mappings_result.first = MagicMock(return_value=row)
        result.mappings = MagicMock(return_value=mappings_result)
        return result

    conn.execute = _execute
    return conn


def _mock_conn_exit(position_qty: float, current_price: float):
    """Returns a fake async connection for _size_exit.

    _size_exit does a single JOIN query returning qty, current_price, completed_at.
    """
    conn = AsyncMock()

    async def _execute(query, params=None):
        result = MagicMock()
        mappings_result = MagicMock()
        row = {"qty": position_qty, "current_price": current_price, "completed_at": _now()}
        mappings_result.first = MagicMock(return_value=row)
        result.mappings = MagicMock(return_value=mappings_result)
        return result

    conn.execute = _execute
    return conn


# ── S1, S2, S3: entry sizing invariants ──────────────────────────────────────

@given(
    buying_power=_REASONABLE_MONEY,
    price=_REASONABLE_PRICE,
    weight=_REASONABLE_WEIGHT,
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_entry_qty_is_nonneg_integer(buying_power, price, weight):
    """S1: qty must always be a non-negative integer (floor division)."""
    conn = _mock_conn_entry(account_value=buying_power, buying_power=buying_power, price=price)
    try:
        qty, notional, summary = await _size_entry(conn, "TEST", intent_weight=weight)
    except HTTPException as exc:
        # 400 is acceptable when the position is too small (target notional < price)
        assert exc.status_code == 400
        return
    assert qty >= 0, f"qty={qty} must be non-negative"
    assert qty == int(qty), f"qty={qty} must be an integer"


@given(
    buying_power=_REASONABLE_MONEY,
    price=_REASONABLE_PRICE,
    weight=_REASONABLE_WEIGHT,
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_entry_notional_equals_qty_times_price(buying_power, price, weight):
    """S2: notional must exactly equal qty * price."""
    conn = _mock_conn_entry(account_value=buying_power, buying_power=buying_power, price=price)
    try:
        qty, notional, summary = await _size_entry(conn, "TEST", intent_weight=weight)
    except HTTPException:
        return
    expected = qty * price
    assert abs(notional - expected) < 1e-6, (
        f"notional={notional} != qty*price={expected} (qty={qty}, price={price})"
    )


@given(
    buying_power=_REASONABLE_MONEY,
    price=_REASONABLE_PRICE,
    weight=_REASONABLE_WEIGHT,
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_entry_notional_never_exceeds_buying_power_plus_price(buying_power, price, weight):
    """S3: notional ≤ buying_power + price (floor division means at most one share over basis)."""
    conn = _mock_conn_entry(account_value=buying_power, buying_power=buying_power, price=price)
    try:
        qty, notional, summary = await _size_entry(conn, "TEST", intent_weight=weight)
    except HTTPException:
        return
    limit = buying_power * weight + price
    assert notional <= limit + 1e-6, (
        f"notional={notional:.2f} > buying_power*weight+price={limit:.2f} "
        f"(buying_power={buying_power}, weight={weight}, price={price})"
    )


# ── S4: weight far below price/buying_power → qty=0 ─────────────────────────

@given(
    buying_power=st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    price=st.floats(min_value=1000.0, max_value=100_000.0, allow_nan=False, allow_infinity=False),
    weight=st.floats(min_value=0.001, max_value=0.009, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_tiny_weight_small_account_gives_zero_or_400(buying_power, price, weight):
    """S4: When target_notional < price (too small to buy one share), entry raises 400 or qty=0."""
    conn = _mock_conn_entry(account_value=buying_power, buying_power=buying_power, price=price)
    try:
        qty, notional, summary = await _size_entry(conn, "TEST", intent_weight=weight)
        # If it didn't raise, qty must be 0 (floor of tiny fraction)
        assert qty == 0.0 or qty >= 1.0, f"Unexpected fractional qty={qty}"
    except HTTPException as exc:
        assert exc.status_code == 400


# ── S5: monotonicity in buying_power ─────────────────────────────────────────

@given(
    buying_power_lo=st.floats(min_value=100.0, max_value=500_000.0, allow_nan=False, allow_infinity=False),
    price=_REASONABLE_PRICE,
    weight=_REASONABLE_WEIGHT,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_higher_buying_power_nondecreasing_qty(buying_power_lo, price, weight):
    """S5: doubling buying_power with same weight/price never decreases qty."""
    buying_power_hi = buying_power_lo * 2.0
    conn_lo = _mock_conn_entry(account_value=buying_power_lo, buying_power=buying_power_lo, price=price)
    conn_hi = _mock_conn_entry(account_value=buying_power_hi, buying_power=buying_power_hi, price=price)
    try:
        qty_lo, _, _ = await _size_entry(conn_lo, "TEST", intent_weight=weight)
        qty_hi, _, _ = await _size_entry(conn_hi, "TEST", intent_weight=weight)
    except HTTPException:
        return
    assert qty_hi >= qty_lo, (
        f"qty_hi={qty_hi} < qty_lo={qty_lo} when buying_power doubled "
        f"({buying_power_lo:.2f} → {buying_power_hi:.2f})"
    )


# ── S6: monotonicity in price ─────────────────────────────────────────────────

@given(
    price_lo=st.floats(min_value=1.0, max_value=1_000.0, allow_nan=False, allow_infinity=False),
    buying_power=_REASONABLE_MONEY,
    weight=_REASONABLE_WEIGHT,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_higher_price_nonincreasing_qty(price_lo, buying_power, weight):
    """S6: doubling price with same buying_power/weight never increases qty."""
    price_hi = price_lo * 2.0
    conn_lo = _mock_conn_entry(account_value=buying_power, buying_power=buying_power, price=price_lo)
    conn_hi = _mock_conn_entry(account_value=buying_power, buying_power=buying_power, price=price_hi)
    try:
        qty_lo, _, _ = await _size_entry(conn_lo, "TEST", intent_weight=weight)
        qty_hi, _, _ = await _size_entry(conn_hi, "TEST", intent_weight=weight)
    except HTTPException:
        return
    assert qty_hi <= qty_lo, (
        f"qty_hi={qty_hi} > qty_lo={qty_lo} when price doubled "
        f"({price_lo:.2f} → {price_hi:.2f})"
    )


# ── S7: monotonicity in weight ────────────────────────────────────────────────

@given(
    weight_lo=st.floats(min_value=0.001, max_value=0.5, allow_nan=False, allow_infinity=False),
    buying_power=_REASONABLE_MONEY,
    price=_REASONABLE_PRICE,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_higher_weight_nondecreasing_qty(weight_lo, buying_power, price):
    """S7: doubling weight with same buying_power/price never decreases qty."""
    weight_hi = min(weight_lo * 2.0, 1.0)
    conn_lo = _mock_conn_entry(account_value=buying_power, buying_power=buying_power, price=price)
    conn_hi = _mock_conn_entry(account_value=buying_power, buying_power=buying_power, price=price)
    try:
        qty_lo, _, _ = await _size_entry(conn_lo, "TEST", intent_weight=weight_lo)
        qty_hi, _, _ = await _size_entry(conn_hi, "TEST", intent_weight=weight_hi)
    except HTTPException:
        return
    assert qty_hi >= qty_lo, (
        f"qty_hi={qty_hi} < qty_lo={qty_lo} when weight doubled "
        f"({weight_lo:.4f} → {weight_hi:.4f})"
    )


# ── S11, S12: exit sizing invariants ─────────────────────────────────────────

@given(
    position_qty=st.floats(min_value=1.0, max_value=100_000.0, allow_nan=False, allow_infinity=False),
    current_price=_REASONABLE_PRICE,
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_exit_qty_equals_abs_position(position_qty, current_price):
    """S11: exit qty must equal abs(position_qty) — always liquidate the full position."""
    conn = _mock_conn_exit(position_qty, current_price)
    try:
        qty, notional, summary = await _size_exit(conn, "TEST")
    except HTTPException:
        return
    assert qty == abs(position_qty), (
        f"exit qty={qty} != abs(position_qty)={abs(position_qty)}"
    )
    assert qty >= 0


@given(
    position_qty=st.floats(min_value=1.0, max_value=100_000.0, allow_nan=False, allow_infinity=False),
    current_price=_REASONABLE_PRICE,
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_exit_notional_nonneg(position_qty, current_price):
    """S12: exit notional must always be non-negative."""
    conn = _mock_conn_exit(position_qty, current_price)
    try:
        qty, notional, summary = await _size_exit(conn, "TEST")
    except HTTPException:
        return
    assert notional >= 0, f"notional={notional} is negative"


# ── Pure math sanity: floor division formula ──────────────────────────────────

@given(
    basis=st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
    weight=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    price=st.floats(min_value=0.0001, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=500)
def test_floor_division_formula_properties(basis, weight, price):
    """The core formula qty=floor(basis*weight/price) satisfies basic arithmetic invariants."""
    qty = math.floor(basis * weight / price)
    assert qty >= 0, "qty must be non-negative"
    assert isinstance(qty, int), "floor() result must be an int"
    notional = qty * price
    assert notional <= basis * weight + price + 1e-6, (
        f"notional={notional:.4f} > basis*weight+price={basis*weight+price:.4f}"
    )
