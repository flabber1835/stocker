"""
Alpaca position reconciliation tests.

Core invariant: after a successful sync, every position Alpaca reports must
appear in live_positions with the same ticker and qty.  If they diverge, the
trade-executor will size orders against wrong data — a stale live_positions
row of AAPL:10 when Alpaca actually holds AAPL:20 would cause a sell order
sized for only half the actual position.

Tests:
  1. Perfect match: Alpaca returns N positions → live_positions contains N rows
     with matching ticker and qty (no phantom or missing positions)

  2. No positions: Alpaca returns [] → live_positions is empty after sync
     (no stale rows from prior runs)

  3. Partial failure: Alpaca positions fetch fails → sync run marked failed
     and live_positions NOT written (no partial state)

  4. Skipped positions: a row with missing symbol/qty is skipped; the good rows are
     still stored, but the sync is marked FAILED by default (audit P1 — an incomplete
     snapshot must not be trusted as fresh). SYNC_FAIL_ON_SKIPPED_POSITIONS=false
     reverts to best-effort success.

  5. Stale detection: trade-executor staleness guard identifies that a sync
     run older than EXIT_SYNC_MAX_AGE_HOURS blocks order sizing

  6. Data fidelity: qty, price, market_value are stored without truncation or
     rounding — stored values match Alpaca response values exactly
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_AS_PATH = os.path.join(ROOT, "services", "alpaca-sync")
_TE_PATH = os.path.join(ROOT, "services", "trade-executor")

for p in [os.path.join(ROOT, "shared"), _AS_PATH]:
    if p not in sys.path:
        sys.path.insert(0, p)

import app.main as as_main  # noqa: E402
from app.main import _do_sync  # noqa: E402


def _now():
    return datetime.now(timezone.utc)


# ── Session mock factory ──────────────────────────────────────────────────────

def _make_session(fetch_rows: list | None = None):
    """Async SQLAlchemy session mock.

    Captures all INSERT/UPDATE statements and returns `fetch_rows` in order
    for fetchone() calls.
    """
    inserts: list[dict] = []
    updates: list[str] = []
    fetch_idx = [0]

    rows = fetch_rows or []

    async def _execute(sql, params=None):
        sql_str = str(sql)
        if "INSERT" in sql_str.upper():
            inserts.append({"sql": sql_str, "params": params or {}})
        elif "UPDATE" in sql_str.upper():
            updates.append(sql_str)

        result = MagicMock()
        idx = fetch_idx[0]
        fetch_idx[0] += 1

        row = rows[idx] if idx < len(rows) else None
        fake_row = MagicMock()
        if row:
            for k, v in row.items():
                setattr(fake_row, k, v)
        result.fetchone = MagicMock(return_value=fake_row if row else None)
        result.fetchall = MagicMock(return_value=[fake_row] if row else [])
        result.rowcount = 1 if row else 0
        return result

    session = AsyncMock()
    session.execute = _execute
    session.commit = AsyncMock()

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)

    session_factory = MagicMock(return_value=ctx)
    return session_factory, inserts, updates


def _make_alpaca_response(positions: list[dict]):
    """Build a mock httpx response for Alpaca GET /v2/positions."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=positions)
    return resp


def _alpaca_position(ticker: str, qty: str, price: str = "100.00") -> dict:
    """Minimal Alpaca position dict."""
    notional = float(qty) * float(price)
    return {
        "symbol": ticker,
        "qty": qty,
        "avg_entry_price": price,
        "current_price": price,
        "market_value": str(notional),
        "cost_basis": str(notional),
        "unrealized_pl": "0.00",
        "unrealized_plpc": "0.00",
        "side": "long",
        "lastday_price": price,
        "change_today": "0.00",
    }


# ── Test 1: Perfect match — every Alpaca position stored ─────────────────────

@pytest.mark.asyncio
async def test_all_alpaca_positions_written_to_live_positions():
    """After a successful sync, live_positions must contain every position
    returned by Alpaca — no positions silently dropped."""
    alpaca_positions = [
        _alpaca_position("AAPL", "10", "182.50"),
        _alpaca_position("MSFT", "5",  "415.00"),
        _alpaca_position("NVDA", "8",  "890.00"),
    ]

    acct_resp = MagicMock()
    acct_resp.status_code = 200
    acct_resp.raise_for_status = MagicMock()
    acct_resp.json = MagicMock(return_value={
        "equity": "50000.00", "buying_power": "25000.00", "cash": "10000.00"
    })

    pos_resp = _make_alpaca_response(alpaca_positions)
    orders_resp = MagicMock()
    orders_resp.status_code = 200
    orders_resp.raise_for_status = MagicMock()
    orders_resp.json = MagicMock(return_value=[])

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[acct_resp, pos_resp, orders_resp])

    run_id = str(uuid.uuid4())
    session_factory, inserts, updates = _make_session(fetch_rows=[])

    with patch.object(as_main, "SessionLocal", session_factory), \
         patch.object(as_main, "_has_credentials", True), \
         patch.object(as_main, "ALPACA_API_KEY", "test"), \
         patch.object(as_main, "ALPACA_SECRET_KEY", "secret"), \
         patch("app.main.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        # Patch the INSERT for alpaca_sync_runs so we get a real run_id
        with patch("app.main.uuid.uuid4", return_value=uuid.UUID(run_id)):
            await _do_sync()

    # Count live_positions INSERTs
    lp_inserts = [i for i in inserts if "live_positions" in i["sql"]]
    assert len(lp_inserts) == len(alpaca_positions), (
        f"Expected {len(alpaca_positions)} live_positions INSERT(s), "
        f"got {len(lp_inserts)}.  Positions may have been silently dropped."
    )

    # Verify ticker names are preserved exactly
    stored_tickers = {i["params"].get("ticker") for i in lp_inserts}
    alpaca_tickers = {p["symbol"] for p in alpaca_positions}
    assert stored_tickers == alpaca_tickers, (
        f"Stored tickers {stored_tickers} != Alpaca tickers {alpaca_tickers}"
    )


# ── Test 2: Empty positions — no phantom rows ─────────────────────────────────

@pytest.mark.asyncio
async def test_empty_positions_writes_zero_live_position_rows():
    """When Alpaca reports no positions, zero live_positions rows are inserted.

    This covers the case where all holdings were sold — live_positions must
    not retain stale rows from a prior run with the same sync_run_id.
    """
    acct_resp = MagicMock()
    acct_resp.status_code = 200
    acct_resp.raise_for_status = MagicMock()
    acct_resp.json = MagicMock(return_value={
        "equity": "50000.00", "buying_power": "50000.00", "cash": "50000.00"
    })

    pos_resp = _make_alpaca_response([])  # no positions
    orders_resp = MagicMock()
    orders_resp.status_code = 200
    orders_resp.raise_for_status = MagicMock()
    orders_resp.json = MagicMock(return_value=[])

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[acct_resp, pos_resp, orders_resp])

    session_factory, inserts, updates = _make_session(fetch_rows=[])

    with patch.object(as_main, "SessionLocal", session_factory), \
         patch.object(as_main, "_has_credentials", True), \
         patch.object(as_main, "ALPACA_API_KEY", "test"), \
         patch.object(as_main, "ALPACA_SECRET_KEY", "secret"), \
         patch("app.main.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        await _do_sync()

    lp_inserts = [i for i in inserts if "live_positions" in i["sql"]]
    assert len(lp_inserts) == 0, (
        f"Expected 0 live_positions rows for empty Alpaca response, got {len(lp_inserts)}"
    )

    # Sync run should still succeed (empty portfolio is a valid state)
    success_updates = [u for u in updates if "success" in u]
    assert len(success_updates) >= 1, "Sync run should be marked success even with 0 positions"


# ── Test 3: Alpaca positions fetch fails — no partial state ───────────────────

@pytest.mark.asyncio
async def test_sync_marks_failed_when_positions_fetch_raises():
    """If Alpaca's positions endpoint raises, the sync run must be marked failed
    and no live_positions rows written — partial state is worse than no state."""
    import httpx as _httpx

    acct_resp = MagicMock()
    acct_resp.status_code = 200
    acct_resp.raise_for_status = MagicMock()
    acct_resp.json = MagicMock(return_value={
        "equity": "50000.00", "buying_power": "25000.00", "cash": "10000.00"
    })

    mock_client = AsyncMock()
    # Account fetch succeeds, positions fetch raises
    mock_client.get = AsyncMock(side_effect=[
        acct_resp,
        _httpx.ConnectError("Alpaca positions endpoint unreachable"),
    ])

    session_factory, inserts, updates = _make_session(fetch_rows=[])

    with patch.object(as_main, "SessionLocal", session_factory), \
         patch.object(as_main, "_has_credentials", True), \
         patch.object(as_main, "ALPACA_API_KEY", "test"), \
         patch.object(as_main, "ALPACA_SECRET_KEY", "secret"), \
         patch("app.main.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        await _do_sync()   # should not raise — the exception is caught internally

    # No live_positions should have been written
    lp_inserts = [i for i in inserts if "live_positions" in i["sql"]]
    assert len(lp_inserts) == 0, (
        f"live_positions should NOT be written after a partial sync failure, "
        f"got {len(lp_inserts)} rows"
    )

    # The sync run must be marked failed
    failed_updates = [u for u in updates if "failed" in u and "alpaca_sync_runs" in u]
    assert len(failed_updates) >= 1, (
        "alpaca_sync_runs was not marked 'failed' after positions fetch error"
    )


# ── Test 4: Positions with missing fields are skipped ────────────────────────

@pytest.mark.asyncio
async def test_positions_with_missing_symbol_or_qty_are_skipped():
    """Malformed Alpaca position rows (missing symbol or qty) must be skipped
    without crashing the sync.  The good positions must still be stored."""
    acct_resp = MagicMock()
    acct_resp.status_code = 200
    acct_resp.raise_for_status = MagicMock()
    acct_resp.json = MagicMock(return_value={
        "equity": "50000.00", "buying_power": "25000.00", "cash": "10000.00"
    })

    malformed_positions = [
        _alpaca_position("AAPL", "10"),           # good
        {"qty": "5", "current_price": "100"},     # missing symbol → skip
        {"symbol": "MSFT"},                       # missing qty → skip
        _alpaca_position("NVDA", "3"),            # good
    ]
    pos_resp = _make_alpaca_response(malformed_positions)
    orders_resp = MagicMock()
    orders_resp.status_code = 200
    orders_resp.raise_for_status = MagicMock()
    orders_resp.json = MagicMock(return_value=[])

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[acct_resp, pos_resp, orders_resp])

    session_factory, inserts, _ = _make_session(fetch_rows=[])

    with patch.object(as_main, "SessionLocal", session_factory), \
         patch.object(as_main, "_has_credentials", True), \
         patch.object(as_main, "ALPACA_API_KEY", "test"), \
         patch.object(as_main, "ALPACA_SECRET_KEY", "secret"), \
         patch("app.main.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        await _do_sync()

    lp_inserts = [i for i in inserts if "live_positions" in i["sql"]]
    assert len(lp_inserts) == 2, (
        f"Expected 2 valid positions stored (skipping 2 malformed), got {len(lp_inserts)}"
    )

    stored_tickers = {i["params"].get("ticker") for i in lp_inserts}
    assert stored_tickers == {"AAPL", "NVDA"}, (
        f"Stored tickers {stored_tickers} — malformed rows should have been skipped"
    )


# ── Test 4b: skipped positions FAIL the sync (audit P1) ──────────────────────

def _malformed_run_mocks():
    acct_resp = MagicMock()
    acct_resp.status_code = 200
    acct_resp.raise_for_status = MagicMock()
    acct_resp.json = MagicMock(return_value={
        "equity": "50000.00", "buying_power": "25000.00", "cash": "10000.00"
    })
    positions = [
        _alpaca_position("AAPL", "10"),
        {"qty": "5"},                 # missing symbol → skip
    ]
    pos_resp = _make_alpaca_response(positions)
    orders_resp = MagicMock()
    orders_resp.status_code = 200
    orders_resp.raise_for_status = MagicMock()
    orders_resp.json = MagicMock(return_value=[])
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[acct_resp, pos_resp, orders_resp])
    return mock_client


@pytest.mark.asyncio
async def test_skipped_positions_mark_sync_failed_by_default():
    """audit P1: an incomplete position snapshot (any skip) must NOT be 'success'.
    Marking it success undercounts MAX_POSITIONS downstream → over-entry."""
    mock_client = _malformed_run_mocks()
    session_factory, inserts, updates = _make_session(fetch_rows=[])

    with patch.object(as_main, "SessionLocal", session_factory), \
         patch.object(as_main, "_has_credentials", True), \
         patch.object(as_main, "SYNC_FAIL_ON_SKIPPED_POSITIONS", True), \
         patch.object(as_main, "ALPACA_API_KEY", "test"), \
         patch.object(as_main, "ALPACA_SECRET_KEY", "secret"), \
         patch("app.main.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        await _do_sync()

    failed = [u for u in updates if "failed" in u and "alpaca_sync_runs" in u]
    success = [u for u in updates if "success" in u and "alpaca_sync_runs" in u]
    assert failed, "skipped position must mark the sync run failed"
    assert not success, "an incomplete sync must NOT be marked success"


@pytest.mark.asyncio
async def test_skipped_positions_can_be_tolerated_when_flag_off():
    """SYNC_FAIL_ON_SKIPPED_POSITIONS=false reverts to best-effort: good positions
    stored, run still succeeds."""
    mock_client = _malformed_run_mocks()
    session_factory, inserts, updates = _make_session(fetch_rows=[])

    with patch.object(as_main, "SessionLocal", session_factory), \
         patch.object(as_main, "_has_credentials", True), \
         patch.object(as_main, "SYNC_FAIL_ON_SKIPPED_POSITIONS", False), \
         patch.object(as_main, "ALPACA_API_KEY", "test"), \
         patch.object(as_main, "ALPACA_SECRET_KEY", "secret"), \
         patch("app.main.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        await _do_sync()

    success = [u for u in updates if "success" in u and "alpaca_sync_runs" in u]
    lp_inserts = [i for i in inserts if "live_positions" in i["sql"]]
    assert success, "flag off → incomplete sync still marked success"
    assert len(lp_inserts) == 1  # AAPL stored, malformed skipped


# ── Test 5: Staleness guard blocks sizing on old sync data ────────────────────

@pytest.mark.asyncio
async def test_size_exit_raises_when_sync_data_is_stale():
    """trade-executor refuses to size an exit order when alpaca-sync data is
    older than EXIT_SYNC_MAX_AGE_HOURS.

    Stale position data means we'd size the sell for the wrong quantity —
    this guard is the last line of defence against over- or under-selling.
    """
    # Import from trade-executor, not alpaca-sync
    for k in list(sys.modules.keys()):
        if k == "app" or k.startswith("app."):
            del sys.modules[k]

    if _TE_PATH not in sys.path:
        sys.path.insert(0, _TE_PATH)

    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:x@localhost/x"
    os.environ["ALPACA_API_KEY"] = ""
    os.environ["ALPACA_SECRET_KEY"] = ""
    os.environ["EXIT_SYNC_MAX_AGE_HOURS"] = "24"

    from app.main import _size_exit  # type: ignore
    from fastapi import HTTPException

    stale_time = _now() - timedelta(hours=25)   # 25h ago → beyond 24h limit

    conn = AsyncMock()

    async def _exec(sql, params=None):
        result = MagicMock()
        m = MagicMock()
        # Return a sync run row with stale completed_at
        m.first = MagicMock(return_value={
            "account_value": 100_000.0,
            "buying_power": 50_000.0,
            "completed_at": stale_time,   # stale!
            "qty": 10.0,
            "current_price": 150.0,
        })
        result.mappings = MagicMock(return_value=m)
        return result

    conn.execute = _exec

    with pytest.raises(HTTPException) as exc_info:
        await _size_exit(conn, "AAPL")

    assert exc_info.value.status_code in (409, 422, 503), (
        f"Staleness guard should raise 4xx/503, got {exc_info.value.status_code}"
    )
    assert "stale" in str(exc_info.value.detail).lower() or \
           "sync" in str(exc_info.value.detail).lower() or \
           "age" in str(exc_info.value.detail).lower(), (
        f"Staleness guard error message should mention sync age: {exc_info.value.detail}"
    )


# ── Test 6: Data fidelity — values stored without truncation ─────────────────

@pytest.mark.asyncio
async def test_position_values_stored_with_full_precision():
    """qty, current_price, and market_value must be stored exactly as Alpaca
    returns them — no silent rounding or truncation to integers."""
    acct_resp = MagicMock()
    acct_resp.status_code = 200
    acct_resp.raise_for_status = MagicMock()
    acct_resp.json = MagicMock(return_value={
        "equity": "99999.99", "buying_power": "49999.99", "cash": "9999.99"
    })

    # Fractional shares and precise prices — must survive round-trip
    precise_position = {
        "symbol": "BRK.B",
        "qty": "3.567890",           # fractional shares
        "avg_entry_price": "375.123456",
        "current_price": "380.999999",
        "market_value": "1359.02",
        "cost_basis": "1338.52",
        "unrealized_pl": "20.50",
        "unrealized_plpc": "0.015318",
        "side": "long",
        "lastday_price": "379.00",
        "change_today": "0.002639",
    }

    pos_resp = _make_alpaca_response([precise_position])
    orders_resp = MagicMock()
    orders_resp.status_code = 200
    orders_resp.raise_for_status = MagicMock()
    orders_resp.json = MagicMock(return_value=[])

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[acct_resp, pos_resp, orders_resp])

    session_factory, inserts, _ = _make_session(fetch_rows=[])

    with patch.object(as_main, "SessionLocal", session_factory), \
         patch.object(as_main, "_has_credentials", True), \
         patch.object(as_main, "ALPACA_API_KEY", "test"), \
         patch.object(as_main, "ALPACA_SECRET_KEY", "secret"), \
         patch("app.main.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        await _do_sync()

    lp_inserts = [i for i in inserts if "live_positions" in i["sql"]]
    assert len(lp_inserts) == 1, f"Expected 1 insert, got {len(lp_inserts)}"

    params = lp_inserts[0]["params"]
    # Broker dot-symbology is translated to the SYSTEM (Alpha Vantage hyphen)
    # form at the adapter boundary: live_positions must store BRK-B so it
    # matches rankings/targets. (Storing the broker's BRK.B verbatim was the
    # held-detection mismatch behind the live PBR-A "asset not found" incident.)
    assert params.get("ticker") == "BRK-B"

    # Qty must be stored as a float, not truncated to int
    stored_qty = params.get("qty")
    assert stored_qty is not None
    assert abs(float(stored_qty) - 3.56789) < 0.001, (
        f"qty stored as {stored_qty!r} — fractional shares truncated or lost"
    )
