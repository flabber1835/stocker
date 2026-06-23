"""Unit tests for trade-executor sizing helpers (_size_entry and _size_exit).

These tests mock the SQLAlchemy connection so each helper can be exercised in
isolation without a real Postgres. The mock connection serves a configured
sequence of dict rows for each conn.execute(...).mappings().first() call.
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import app.main as te_main
from app.main import _size_entry, _size_exit, _size_partial


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
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},      # alpaca_sync_runs.account_value
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
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
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
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},       # alpaca_sync_runs.account_value
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
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
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
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
        {"current_price": 45.0},
    ])
    _, _, summary = await _size_entry(conn, "AAPL", intent_weight=0.05)
    assert summary["last_price"] == 45.0
    assert summary["price_source"] == "live_positions"


@pytest.mark.asyncio
async def test_size_entry_falls_back_to_daily_close_when_no_live():
    # intent_weight provided. Queries: account_value, live_price(None), daily_prices.close
    conn = _mock_conn_returning([
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
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
        {"account_value": 1000.0, "buying_power": 1000.0, "completed_at": _now()},
        {"current_price": 500.0},
    ])
    with pytest.raises(HTTPException) as exc_info:
        await _size_entry(conn, "AAPL", intent_weight=0.01)
    assert exc_info.value.status_code == 400
    assert "Position too small" in exc_info.value.detail


@pytest.mark.asyncio
async def test_size_entry_uses_account_value_not_buying_power():
    # account_value=$100k, buying_power=$30k (partially invested portfolio)
    # Entry must size against account_value so we target the correct equity weight.
    # Using buying_power would produce an undersized order when the portfolio is
    # fully invested and exits haven't cleared yet ($30k << $100k / 10 = $10k).
    # weight=0.10 × account_value=$100k = $10000 notional ÷ $50 price = 200 shares
    conn = _mock_conn_returning([
        {"account_value": 100_000.0, "buying_power": 30_000.0, "completed_at": _now()},
        {"current_price": 50.0},
    ])
    qty, notional, summary = await _size_entry(conn, "AAPL", intent_weight=0.10)
    assert qty == 200.0
    assert notional == 10_000.0
    assert summary["buying_power"] == 30_000.0
    assert summary["account_value"] == 100_000.0
    assert summary["sizing_basis"] == "account_value"


@pytest.mark.asyncio
async def test_size_entry_falls_back_to_account_value_when_no_buying_power():
    # Pre-migration alpaca_sync_runs rows may have buying_power=NULL.
    conn = _mock_conn_returning([
        {"account_value": 100_000.0, "buying_power": None, "completed_at": _now()},
        {"current_price": 50.0},
    ])
    qty, notional, summary = await _size_entry(conn, "AAPL", intent_weight=0.05)
    assert qty == 100.0
    assert notional == 5000.0
    assert summary["sizing_basis"] == "account_value"


@pytest.mark.asyncio
async def test_size_entry_aborts_when_no_sync_row():
    # audit P0: no successful sync row is a FRESHNESS failure (fail closed) → 409
    # with re-sync guidance, caught before the generic "cannot compute" path.
    conn = _mock_conn_returning([
        None,                               # alpaca_sync_runs returns None
    ])
    with pytest.raises(HTTPException) as exc_info:
        await _size_entry(conn, "AAPL", intent_weight=0.05)
    assert exc_info.value.status_code == 409
    assert "alpaca-sync" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_size_entry_aborts_when_sync_present_but_values_null():
    # A FRESH sync row (completed_at set) that nonetheless has NULL account_value AND
    # buying_power still aborts at the "cannot compute" guard (400) — the freshness
    # gate passes (it's fresh), so the original sizing-data error path is preserved.
    conn = _mock_conn_returning([
        {"account_value": None, "buying_power": None, "completed_at": _now()},
        {"current_price": 50.0},
    ])
    with pytest.raises(HTTPException) as exc_info:
        await _size_entry(conn, "AAPL", intent_weight=0.05)
    assert exc_info.value.status_code == 400
    assert "account_value=None" in exc_info.value.detail
    assert "buying_power=None" in exc_info.value.detail


@pytest.mark.asyncio
async def test_size_entry_aborts_when_no_price():
    conn = _mock_conn_returning([
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
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
    assert summary["source"] == "live_positions_latest_sync"
    assert summary["current_price"] == 60.0


@pytest.mark.asyncio
async def test_size_exit_not_in_latest_sync_raises_409():
    """Position absent from the latest sync (already closed) → 409 refusal, not a
    phantom sell. This is the production bug: a stale exit proposal outlived the
    position close; the executor must refuse rather than size from an old sync."""
    conn = _mock_conn_returning([None])
    with pytest.raises(HTTPException) as exc_info:
        await _size_exit(conn, "AAPL")
    assert exc_info.value.status_code == 409
    assert "already closed" in exc_info.value.detail


@pytest.mark.asyncio
async def test_size_exit_zero_qty_in_latest_sync_raises_409():
    """A qty=0 row in the latest sync is also 'not held' → refuse."""
    now = datetime.now(timezone.utc)
    conn = _mock_conn_returning([
        {"qty": 0.0, "current_price": 60.0, "completed_at": now},
    ])
    with pytest.raises(HTTPException) as exc_info:
        await _size_exit(conn, "AAPL")
    assert exc_info.value.status_code == 409


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


# ── FIX E: exit must not produce a $0 notional when current_price is missing ───


@pytest.mark.asyncio
async def test_size_exit_missing_price_falls_back_to_market_value():
    """current_price absent → notional would be qty×0=0, which the risk-service
    notional_zero guard rejected before its close exemption. _size_exit now falls
    back to the broker's last-known market_value for a positive audit notional so
    the de-risking exit is never $0."""
    now = datetime.now(timezone.utc)
    conn = _mock_conn_returning([
        {"qty": 50.0, "current_price": None, "market_value": 3120.0, "completed_at": now},
    ])
    qty, notional, summary = await _size_exit(conn, "AAPL")
    assert qty == 50.0
    assert notional == 3120.0  # from market_value, NOT qty×0
    assert summary["notional_source"] == "market_value_fallback"


@pytest.mark.asyncio
async def test_size_exit_uses_price_when_present():
    """When current_price is present, notional is qty×price (market_value ignored)."""
    now = datetime.now(timezone.utc)
    conn = _mock_conn_returning([
        {"qty": 50.0, "current_price": 60.0, "market_value": 9999.0, "completed_at": now},
    ])
    qty, notional, summary = await _size_exit(conn, "AAPL")
    assert notional == 3000.0
    assert summary["notional_source"] == "qty_x_current_price"


# ── NaN weight guard ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_weight", [float("nan"), float("inf"), float("-inf")])
async def test_size_entry_nan_weight_falls_back_to_default(bad_weight):
    """NaN/Inf intent_weight must not reach the sizing formula.

    Before the fix: nan <= 0 is False in Python, so both guards silently passed
    and math.floor(buying_power * nan / price) raised ValueError (unhandled 500).
    After the fix: math.isfinite() catches it and the default weight is used instead,
    producing a valid order.
    """
    conn = _mock_conn_returning([
        # idempotency check skipped — this goes straight to _size_entry
        # query 0: portfolio_holdings fallback (NaN triggered the fallback)
        None,
        # query 1: alpaca_sync_runs account
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
        # query 2: live_positions price
        {"current_price": 150.0},
    ])
    qty, notional, summary = await _size_entry(conn, "AAPL", bad_weight)
    assert qty >= 1.0, f"Expected valid qty, got {qty}"
    assert summary["weight_source"] == "default"
    assert summary["weight"] > 0


@pytest.mark.asyncio
async def test_size_entry_nan_from_portfolio_holdings_uses_default():
    """NaN returned by the portfolio_holdings fallback query is also caught."""
    conn = _mock_conn_returning([
        # query 0: portfolio_holdings returns a NaN weight (corrupt DB row)
        {"weight": float("nan")},
        # query 1: alpaca_sync_runs
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
        # query 2: live_positions price
        {"current_price": 150.0},
    ])
    qty, notional, summary = await _size_entry(conn, "AAPL", None)
    assert qty >= 1.0
    assert summary["weight_source"] == "default"


# ── FIX F: BUY-side daily_prices fallback must be freshness-bounded ────────────


@pytest.mark.asyncio
async def test_size_entry_stale_daily_price_refused(monkeypatch):
    """An entry (always a buy) whose ONLY price is a stale daily close is refused —
    sizing a buy off a stale print places a wrong-sized order."""
    monkeypatch.setattr(te_main, "MAX_PRICE_AGE_DAYS", 7)
    stale = date.today() - timedelta(days=30)
    conn = _mock_conn_returning([
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
        {"current_price": None},                      # live price missing → fallback
        {"close": 48.0, "date": stale},               # stale daily_prices fallback
    ])
    with pytest.raises(HTTPException) as exc_info:
        await _size_entry(conn, "AAPL", intent_weight=0.05)
    assert exc_info.value.status_code == 422
    assert "stale daily price" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_size_entry_fresh_daily_price_ok(monkeypatch):
    """A FRESH daily close fallback sizes normally."""
    monkeypatch.setattr(te_main, "MAX_PRICE_AGE_DAYS", 7)
    fresh = date.today() - timedelta(days=1)
    conn = _mock_conn_returning([
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
        {"current_price": None},
        {"close": 50.0, "date": fresh},
    ])
    qty, notional, summary = await _size_entry(conn, "AAPL", intent_weight=0.05)
    assert qty == 100.0
    assert summary["price_source"] == "daily_prices"


@pytest.mark.asyncio
async def test_size_buy_add_stale_daily_price_refused(monkeypatch):
    monkeypatch.setattr(te_main, "MAX_PRICE_AGE_DAYS", 7)
    stale = date.today() - timedelta(days=30)
    intent = {"action": "buy_add", "current_weight": 0.10, "actual_weight": 0.05}
    conn = _mock_conn_returning([
        # _size_partial query order: account_value, live_price(None), daily_prices
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
        {"current_price": None},
        {"close": 48.0, "date": stale},
    ])
    with pytest.raises(HTTPException) as exc_info:
        await _size_partial(conn, "AAPL", intent)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_size_sell_trim_stale_daily_price_allowed(monkeypatch):
    """A sell_trim is NOT bounded by the buy-side freshness rule — de-risking on a
    stale price is safe."""
    monkeypatch.setattr(te_main, "MAX_PRICE_AGE_DAYS", 7)
    stale = date.today() - timedelta(days=30)
    intent = {"action": "sell_trim", "current_weight": 0.05, "actual_weight": 0.10}
    conn = _mock_conn_returning([
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": _now()},
        {"current_price": None},
        {"close": 50.0, "date": stale},
        # sell_trim over-sell guard then reads held qty
        {"qty": 100.0},
    ])
    qty, notional, summary = await _size_partial(conn, "AAPL", intent)
    assert qty >= 1.0  # sized despite the stale price
    assert summary["price_source"] == "daily_prices"
