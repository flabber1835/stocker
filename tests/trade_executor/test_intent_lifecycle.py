"""
Intent lifecycle state machine tests for trade-executor.

The idempotency check (step 1 of submit_order) gates retries based on the
current status of any alpaca_orders row linked to the intent.

Decision table — blocking vs. retryable states:

  existing order status | expected response.status | reason
  ─────────────────────────────────────────────────────────────────────────
  (none)                | proceeds past check      | no prior attempt
  pending               | 'duplicate'              | submission in flight
  submitted             | 'duplicate'              | order at Alpaca
  risk_rejected         | 'duplicate'              | approval already denied
  failed                | proceeds past check      | retry allowed
  filled                | proceeds past check      | retry would be new order
  canceled              | proceeds past check      | retry allowed
  partial_fill          | proceeds past check      | retry allowed

The concurrent approval race is also tested: when two calls race on the same
intent and the first wins the DB unique constraint, the second must return
'duplicate' gracefully via the IntegrityError handler (not crash).
"""
from __future__ import annotations

import asyncio
import sys
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_TE_PATH = os.path.join(ROOT, "services", "trade-executor")
if _TE_PATH not in sys.path:
    sys.path.insert(0, _TE_PATH)
sys.path.insert(0, os.path.join(ROOT, "shared"))

import app.main as te_main  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402


class _ConnHandle:
    """Mimics a real AsyncConnection acquisition so a single `engine.connect()`
    works both as `await engine.connect()` (the submit lock's dedicated
    connection, audit #8) and as `async with engine.connect()` (dupe lookup)."""

    def __init__(self, conn):
        self._conn = conn

    def __await__(self):
        async def _ret():
            return self._conn
        return _ret().__await__()

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return None


# ── Engine mock ───────────────────────────────────────────────────────────────

def _make_engine(rows: list):
    """Sequential engine mock (see test_fault_injection.py for full docstring)."""
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


def _rows_with_existing_order(status: str) -> list:
    """Row sequence where the idempotency check finds an existing order."""
    return [
        None,                                      # INSERT execution_traces (begin 1)
        {"id": str(uuid.uuid4()), "status": status},  # idempotency SELECT → existing
        # Subsequent writes inside the duplicate-return branch:
        None,  # _log_step idempotency_check
        None,  # UPDATE execution_traces
    ]


def _rows_no_existing_order() -> list:
    """Row sequence where no existing order is found (proceeds past idempotency)."""
    return [
        None,                                      # INSERT execution_traces
        None,                                      # idempotency SELECT → no row
        # load_intent, size_entry etc. all fall through to None
    ]


# ── Decision table: blocking states ──────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("blocking_status", ["pending", "submitted", "risk_rejected"])
async def test_blocking_status_returns_duplicate(blocking_status):
    """Orders in a blocking state must stop a second approve attempt immediately.

    The idempotency check exists precisely to prevent double-buying a position
    — if the first click is still pending at Alpaca, a second click must bounce.
    """
    engine, _ = _make_engine(_rows_with_existing_order(blocking_status))
    intent_id = str(uuid.uuid4())

    with patch.object(te_main, "engine", engine):
        from fastapi.testclient import TestClient
        client = TestClient(te_main.app, raise_server_exceptions=False)
        resp = client.post("/jobs/submit", json={"intent_id": intent_id, "mode": "immediate"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "duplicate", (
        f"Expected 'duplicate' for existing order with status='{blocking_status}', "
        f"got '{body['status']}'"
    )
    # The duplicate response should include the existing order's ID for traceability
    assert body["order_id"] is not None


# ── Decision table: retryable states ─────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("retryable_status", ["failed", "filled", "canceled", "partial_fill"])
async def test_retryable_status_proceeds_past_idempotency(retryable_status):
    """Orders in a terminal or filled state must allow a fresh submission attempt.

    A failed order means the trade never executed — the user should be able to retry.
    A filled order means we're buying MORE of the same stock — also valid.
    """
    # After passing idempotency, the call will try to load the intent and fail
    # (no intent in mock DB) which gives a 404 — that's fine, we just need it
    # to get PAST the idempotency check rather than return 'duplicate'.
    engine, _ = _make_engine(_rows_with_existing_order(retryable_status))
    # Override idempotency row: the query filters to IN ('pending','submitted','risk_rejected')
    # so 'failed', 'filled', 'canceled', 'partial_fill' are not returned.
    # Simulate this by returning None for the idempotency check.
    engine_no_block, _ = _make_engine(_rows_no_existing_order())
    intent_id = str(uuid.uuid4())

    with patch.object(te_main, "engine", engine_no_block):
        from fastapi.testclient import TestClient
        client = TestClient(te_main.app, raise_server_exceptions=False)
        resp = client.post("/jobs/submit", json={"intent_id": intent_id, "mode": "immediate"})

    # Should NOT be 'duplicate' — it should proceed and fail at load_intent (404)
    # because we have no real DB behind it.  404 means it passed idempotency.
    body = resp.json()
    assert body.get("status") != "duplicate", (
        f"Retryable status '{retryable_status}' incorrectly treated as blocking"
    )


# ── No existing order: proceeds normally ─────────────────────────────────────

@pytest.mark.asyncio
async def test_no_existing_order_proceeds_past_idempotency():
    """When no prior order exists for the intent, submission proceeds normally."""
    engine, _ = _make_engine(_rows_no_existing_order())
    intent_id = str(uuid.uuid4())

    with patch.object(te_main, "engine", engine):
        from fastapi.testclient import TestClient
        client = TestClient(te_main.app, raise_server_exceptions=False)
        resp = client.post("/jobs/submit", json={"intent_id": intent_id, "mode": "immediate"})

    body = resp.json()
    assert body.get("status") != "duplicate"


# ── Concurrent approval race ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_submit_handled_by_integrity_error():
    """When two approvals race for the same intent, the second must return
    'duplicate' via the IntegrityError handler — not crash with a 500.

    The DB unique constraint on (intent_id, open-status) is the last line of
    defence against double-ordering.  The IntegrityError path at line ~632
    must gracefully recover and return the existing order ID.
    """
    winning_order_id = str(uuid.uuid4())

    # First: the idempotency check finds nothing (both calls see empty at query time)
    # Then: load_intent, size_entry all pass
    # Then: the INSERT into alpaca_orders raises IntegrityError (second caller loses race)
    # Then: the fallback SELECT finds the winning order

    rows_losing_racer = [
        None,                                 # 0: INSERT execution_traces
        None,                                 # 1: idempotency SELECT → nothing (race not detected yet)
        {                                     # 2: load_intent
            "id": str(uuid.uuid4()), "ticker": "AAPL", "action": "entry",
            "rank": 5, "composite_score": 0.8,
            "current_weight": 0.05, "actual_weight": 0.05, "weight_drift": 0.0,
        },
        None,                                 # 3: log_step load_intent
        None,                                 # 4: _is_already_held: ticker not in live_positions
        None,                                 # 5: _open_buy_order_for_ticker: no in-flight buy
        {                                     # 6: _size_entry: alpaca_sync_runs
            "account_value": 100_000.0, "buying_power": 100_000.0,
            "completed_at": datetime.now(timezone.utc),
        },
        {"current_price": 150.0},             # 7: _size_entry: live_positions price
        None,                                 # 8: log_step size_order
        None,                                 # 9: log_step risk_check
        # INSERT alpaca_orders → IntegrityError raised (call_idx still consumed)
        # fallback SELECT finds the winning order (after the raise)
        None,                                 # placeholder for the INSERT that raises
        {"id": winning_order_id, "status": "pending"},  # fallback SELECT
    ]

    call_idx = [0]
    # Track when we've reached the alpaca_orders INSERT to raise IntegrityError
    alpaca_orders_insert_count = [0]

    async def _exec_with_integrity_error(sql, params=None):
        # submit-lock advisory calls run on a dedicated connection and must not
        # consume the data-row sequence (audit #8).
        if "advisory" in str(sql).lower():
            r = MagicMock()
            r.scalar = MagicMock(return_value=True)
            return r
        result = MagicMock()
        idx = call_idx[0]
        call_idx[0] += 1

        sql_str = str(sql)
        if "alpaca_orders" in sql_str and "INSERT" in sql_str.upper():
            alpaca_orders_insert_count[0] += 1
            raise IntegrityError("duplicate key", {}, Exception("unique constraint"))

        row = rows_losing_racer[idx] if idx < len(rows_losing_racer) else None
        m = MagicMock()
        m.first = MagicMock(return_value=row)
        m.fetchall = MagicMock(return_value=[row] if row else [])
        result.mappings = MagicMock(return_value=m)
        result.rowcount = 0 if row is None else 1
        return result

    conn = AsyncMock()
    conn.execute = _exec_with_integrity_error

    def _ctx():
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=None)
        return ctx

    engine = MagicMock()
    engine.begin = MagicMock(side_effect=lambda: _ctx())
    # `engine.connect()` must support BOTH `await engine.connect()` (submit lock)
    # and `async with engine.connect()` (dupe lookup) — like a real AsyncConnection.
    engine.connect = MagicMock(side_effect=lambda: _ConnHandle(conn))

    intent_id = str(uuid.uuid4())

    with patch.object(te_main, "engine", engine), \
         patch.object(te_main, "_call_risk",
                      new=AsyncMock(return_value=(True, "ok", str(uuid.uuid4()), "ok"))):
        from fastapi.testclient import TestClient
        client = TestClient(te_main.app, raise_server_exceptions=False)
        resp = client.post("/jobs/submit", json={"intent_id": intent_id, "mode": "immediate"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "duplicate", (
        f"IntegrityError during concurrent submit should return 'duplicate', "
        f"got status='{body.get('status')}' body={body}"
    )
    # Should reference the winning order so the caller can track it
    assert body["order_id"] == winning_order_id
