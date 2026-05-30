"""
Fault injection tests for trade-executor.

Three failure modes tested directly against the functions that own them:

  1. risk-service unreachable — _call_risk raises httpx errors; submit_order
     catches, writes a failed audit row, returns HTTP 502

  2. Alpaca returns 4xx — _submit_to_alpaca returns (None, None, error_text);
     submit_order detects alpaca_err, marks order failed

  3. Alpaca network exception — _submit_to_alpaca raises; submit_order catches,
     marks order failed

  4. Boot cleanup — _trade_executor_warm_up marks pending orders as failed on
     restart so ghost orders never accumulate across container restarts

Tests 1–3 exercise _call_risk and _submit_to_alpaca in isolation (no engine
needed), then verify the error surfaces correctly in the HTTP response via a
lightweight engine mock.  Test 4 exercises _trade_executor_warm_up directly.
"""
from __future__ import annotations

import sys
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_TE_PATH = os.path.join(ROOT, "services", "trade-executor")
if _TE_PATH not in sys.path:
    sys.path.insert(0, _TE_PATH)
sys.path.insert(0, os.path.join(ROOT, "shared"))

from app.main import (  # noqa: E402
    _call_risk,
    _close_position_alpaca,
    _submit_to_alpaca,
    _trade_executor_warm_up,
)
import app.main as te_main  # noqa: E402


def _httpx_client_mock(*, post_side_effect=None, post_return=None, get_return=None,
                       delete_return=None, delete_side_effect=None):
    """Create an async httpx client mock for use with patch.object(te_main, 'httpx').

    Usage:
        mock_client = _httpx_client_mock(post_side_effect=SomeException())
        with patch.object(te_main, "httpx") as httpx_mock:
            httpx_mock.AsyncClient = MagicMock(return_value=mock_client)
            ...
    """
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    if post_side_effect is not None:
        client.post = AsyncMock(side_effect=post_side_effect)
    elif post_return is not None:
        client.post = AsyncMock(return_value=post_return)
    if get_return is not None:
        client.get = AsyncMock(return_value=get_return)
    return client


# ── Engine mock factory ───────────────────────────────────────────────────────

def _make_engine(rows: list):
    """Async engine mock that returns rows[i] for the i-th execute() call.

    Falls through to None for any call beyond the list end — write operations
    (INSERTs, UPDATEs) don't consume a result so those extra calls are fine.
    """
    call_idx = [0]

    async def _exec(sql, params=None):
        result = MagicMock()
        idx = call_idx[0]
        call_idx[0] += 1
        row = rows[idx] if idx < len(rows) else None
        m = MagicMock()
        m.first = MagicMock(return_value=row)
        m.fetchall = MagicMock(return_value=[row] if row else [])
        result.mappings = MagicMock(return_value=m)
        result.rowcount = 0 if row is None else 1
        return result

    conn = AsyncMock()
    conn.execute = _exec

    def _ctx():
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=None)
        return ctx

    engine = MagicMock()
    engine.begin = MagicMock(side_effect=lambda: _ctx())
    engine.connect = MagicMock(side_effect=lambda: _ctx())
    engine.dispose = AsyncMock()
    return engine, conn


def _intent_rows(ticker="AAPL", action="entry", weight=0.05):
    """Minimal row sequence to drive submit_order through steps 1-6 (pre risk_check)."""
    rows = [
        None,                               # execute_traces INSERT (begin 1)
        None,                               # idempotency check → no existing order (connect 1)
        {                                   # load_intent SELECT (connect 2)
            "id": str(uuid.uuid4()),
            "ticker": ticker,
            "action": action,
            "rank": 5,
            "composite_score": 0.8,
            "current_weight": weight,
            "actual_weight": weight,
            "weight_drift": 0.0,
        },
        None,                               # log_step load_intent (begin 2)
    ]
    if action == "entry":
        rows.append(None)                   # _is_already_held: ticker not in live_positions
    rows += [
        {                                   # _size_entry: alpaca_sync_runs
            "account_value": 100_000.0,
            "buying_power": 100_000.0,
            "completed_at": datetime.now(timezone.utc),
        },
        {"current_price": 150.0},           # _size_entry: live_positions price
        None,                               # log_step size_order (begin 3)
        # beyond here: error handling writes → all fall through to None
    ]
    return rows


# ── 1. _call_risk error propagation ──────────────────────────────────────────

_RISK_PAYLOAD = {
    "ticker": "AAPL", "action": "entry", "side": "buy",
    "qty": 10.0, "notional": 1500.0,
    "mode": "immediate", "trade_type": "paper",
}


@pytest.mark.asyncio
async def test_call_risk_raises_on_connection_refused():
    """_call_risk propagates ConnectError so submit_order can catch and audit it."""
    client = _httpx_client_mock(
        post_side_effect=httpx.ConnectError("Connection refused by risk-service")
    )
    with patch.object(te_main, "httpx") as httpx_mock:
        httpx_mock.AsyncClient = MagicMock(return_value=client)
        with pytest.raises(httpx.ConnectError):
            await _call_risk(_RISK_PAYLOAD)


@pytest.mark.asyncio
async def test_call_risk_raises_on_timeout():
    """_call_risk propagates ReadTimeout so the caller knows the service is slow."""
    client = _httpx_client_mock(
        post_side_effect=httpx.ReadTimeout("risk-service timed out")
    )
    with patch.object(te_main, "httpx") as httpx_mock:
        httpx_mock.AsyncClient = MagicMock(return_value=client)
        with pytest.raises(httpx.ReadTimeout):
            await _call_risk(_RISK_PAYLOAD)


@pytest.mark.asyncio
async def test_call_risk_raises_on_server_500():
    """_call_risk raises via raise_for_status() when risk-service returns 500."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=MagicMock(),
            response=mock_response,
        )
    )
    client = _httpx_client_mock(post_return=mock_response)
    with patch.object(te_main, "httpx") as httpx_mock:
        httpx_mock.AsyncClient = MagicMock(return_value=client)
        with pytest.raises(httpx.HTTPStatusError):
            await _call_risk(_RISK_PAYLOAD)


# ── 2. _submit_to_alpaca 4xx handling ────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("status_code,expected_err_fragment", [
    (400, ""),      # bad request — error text returned, no exception
    (401, ""),      # unauthorized
    (403, ""),      # forbidden
    (422, ""),      # unprocessable
    (500, ""),      # server error — Alpaca doesn't raise_for_status in this fn
])
async def test_submit_to_alpaca_returns_error_tuple_on_non_2xx(status_code, expected_err_fragment):
    """_submit_to_alpaca returns (None, None, error_text) for any non-200/201 response.

    Critically: it does NOT raise — the error is surfaced as the third element
    of the tuple so submit_order can record the audit row before returning.
    """
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.text = f"Alpaca error {status_code}: something went wrong"
    client = _httpx_client_mock(post_return=mock_response)
    with patch.object(te_main, "httpx") as httpx_mock:
        httpx_mock.AsyncClient = MagicMock(return_value=client)
        alpaca_order_id, alpaca_status, err = await _submit_to_alpaca({
            "symbol": "AAPL", "qty": "10", "side": "buy",
            "type": "market", "time_in_force": "opg",
        })
    assert alpaca_order_id is None
    assert alpaca_status is None
    assert err is not None
    assert str(status_code) in err


@pytest.mark.asyncio
async def test_submit_to_alpaca_raises_on_connection_error():
    """_submit_to_alpaca propagates ConnectError for Alpaca being unreachable."""
    client = _httpx_client_mock(
        post_side_effect=httpx.ConnectError("Alpaca API unreachable")
    )
    with patch.object(te_main, "httpx") as httpx_mock:
        httpx_mock.AsyncClient = MagicMock(return_value=client)
        with pytest.raises(httpx.ConnectError):
            await _submit_to_alpaca({
                "symbol": "AAPL", "qty": "10", "side": "buy",
                "type": "market", "time_in_force": "opg",
            })


# ── 3. submit_order HTTP responses when dependencies fail ─────────────────────

@pytest.mark.asyncio
async def test_submit_order_returns_502_when_risk_service_down():
    """When risk-service is unreachable, submit_order must return HTTP 502 and
    record a failed alpaca_orders row so the failure is auditable."""
    engine, conn = _make_engine(_intent_rows())
    executed_sqls: list[str] = []

    # Capture SQL to verify the failed audit row is written
    original_exec = conn.execute

    async def _capturing_exec(sql, params=None):
        executed_sqls.append(str(sql))
        return await original_exec(sql, params)

    conn.execute = _capturing_exec

    with patch.object(te_main, "engine", engine), \
         patch.object(te_main, "_call_risk",
                      new=AsyncMock(side_effect=httpx.ConnectError("refused"))):
        from fastapi.testclient import TestClient
        client = TestClient(te_main.app, raise_server_exceptions=False)
        resp = client.post(
            "/jobs/submit",
            json={"intent_id": str(uuid.uuid4()), "mode": "immediate"},
        )

    assert resp.status_code == 502
    body = resp.json()
    assert "detail" in body
    # The failed order ID should appear in the detail so the caller can look it up
    assert "order" in body["detail"].lower() or "risk" in body["detail"].lower()

    # Verify a failed alpaca_orders INSERT was executed (audit trail exists)
    failed_inserts = [s for s in executed_sqls if "alpaca_orders" in s and "INSERT" in s.upper()]
    assert len(failed_inserts) >= 1, (
        "No alpaca_orders INSERT found after risk-service failure — "
        "the trade has no audit trail"
    )


@pytest.mark.asyncio
async def test_submit_order_records_failed_order_when_alpaca_errors():
    """When Alpaca returns an error, submit_order marks the order as failed.

    The order row must exist (status=failed) even though the trade did not execute —
    this is the audit guarantee that no trade is silently dropped.
    """
    # Need credentials set so the code reaches _submit_to_alpaca
    engine, conn = _make_engine(_intent_rows())
    executed_sqls: list[str] = []

    original_exec = conn.execute

    async def _capturing_exec(sql, params=None):
        executed_sqls.append(str(sql))
        return await original_exec(sql, params)

    conn.execute = _capturing_exec

    with patch.object(te_main, "engine", engine), \
         patch.object(te_main, "ALPACA_API_KEY", "test-key"), \
         patch.object(te_main, "ALPACA_SECRET_KEY", "test-secret"), \
         patch.object(te_main, "_call_risk",
                      new=AsyncMock(return_value=(True, "ok", str(uuid.uuid4()), "ok"))), \
         patch.object(te_main, "_submit_to_alpaca",
                      new=AsyncMock(return_value=(None, None, "400 Bad Request: symbol not found"))):
        from fastapi.testclient import TestClient
        client = TestClient(te_main.app, raise_server_exceptions=False)
        resp = client.post(
            "/jobs/submit",
            json={"intent_id": str(uuid.uuid4()), "mode": "immediate"},
        )

    # Should return 200 with status="failed" (not a 5xx — the trade was attempted)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"

    # An UPDATE setting status='failed' on alpaca_orders must exist
    failed_updates = [
        s for s in executed_sqls
        if "alpaca_orders" in s and "failed" in s
    ]
    assert len(failed_updates) >= 1, (
        "No failed status written to alpaca_orders when Alpaca returned an error"
    )


# ── 4. Boot cleanup ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_boot_cleanup_marks_pending_orders_as_failed():
    """On startup, _trade_executor_warm_up must UPDATE pending orders to failed.

    This prevents ghost orders from appearing submitted when the service
    restarts mid-submission — a pending order was never sent to Alpaca, so
    it must be failed so the user can retry.
    """
    executed_sqls: list[str] = []

    async def _capture_exec(sql, params=None):
        executed_sqls.append(str(sql))
        result = MagicMock()
        result.mappings = MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
        result.rowcount = 0
        return result

    conn = AsyncMock()
    conn.execute = _capture_exec

    begin_ctx = MagicMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=conn)
    begin_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_engine = MagicMock()
    mock_engine.begin = MagicMock(return_value=begin_ctx)

    with patch.object(te_main, "engine", mock_engine), \
         patch("app.main.wait_for_db", new=AsyncMock()):
        await _trade_executor_warm_up()

    update_stmts = [s for s in executed_sqls if "UPDATE" in s.upper()]
    assert len(update_stmts) >= 1, "No UPDATE executed during boot cleanup"

    combined = " ".join(update_stmts)
    assert "failed" in combined, "Boot cleanup did not set status=failed"
    assert "pending" in combined, "Boot cleanup did not target pending orders"
    assert "restarted" in combined or "service" in combined, (
        "Boot cleanup error_message should explain why the order failed"
    )


# ── 4. _close_position_alpaca (full-exit close, no fractional over-sell) ──────
# Full exits use DELETE /v2/positions/{symbol} so Alpaca computes the exact held
# quantity — fixing the bug where a stored qty rounded up past the true holding
# (live_positions.qty NUMERIC(16,6) → 0.878611682 stored as 0.878612) made a
# qty-based sell fail with "insufficient qty available".

@pytest.mark.asyncio
async def test_close_position_success_returns_order_id():
    """A 200 from close-position returns (order_id, status, None) — no qty sent."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"id": "ord-123", "status": "accepted"}
    client = _httpx_client_mock(delete_return=resp)
    with patch.object(te_main, "httpx") as httpx_mock:
        httpx_mock.AsyncClient = MagicMock(return_value=client)
        oid, status, err = await _close_position_alpaca("SNDK")
    assert (oid, status, err) == ("ord-123", "accepted", None)
    # Must hit the positions endpoint, not /v2/orders, and send no qty.
    called_url = client.__aenter__.return_value.delete.call_args[0][0]
    assert called_url.endswith("/v2/positions/SNDK")


@pytest.mark.asyncio
async def test_close_position_404_is_benign_already_flat():
    """404 = position already flat. The exit goal (be out of the name) is met, so
    treat as success (None id, sentinel status, no error) — not a failure."""
    resp = MagicMock()
    resp.status_code = 404
    resp.text = "position not found"
    client = _httpx_client_mock(delete_return=resp)
    with patch.object(te_main, "httpx") as httpx_mock:
        httpx_mock.AsyncClient = MagicMock(return_value=client)
        oid, status, err = await _close_position_alpaca("SNDK")
    assert oid is None
    assert status == "position_already_closed"
    assert err is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 403, 422, 500])
async def test_close_position_other_errors_return_error_tuple(status_code):
    """Any other non-2xx returns (None, None, error_text) — surfaced, not raised."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = f"Alpaca error {status_code}"
    client = _httpx_client_mock(delete_return=resp)
    with patch.object(te_main, "httpx") as httpx_mock:
        httpx_mock.AsyncClient = MagicMock(return_value=client)
        oid, status, err = await _close_position_alpaca("SNDK")
    assert oid is None and status is None
    assert err is not None and str(status_code) in err
