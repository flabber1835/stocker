"""Safety regression tests for the trade-executor hardening fixes.

Covers:
  A1/A2  deferred-order submission re-runs the FULL risk gate and fails CLOSED
         (does NOT submit when risk-service is unreachable or returns not-approved)
  A3     the open/working status set includes accepted/new/partially_filled so a
         working-but-unfilled order is deduped (no double-submit)
  A4     an APPROVED risk response with no check_id is a hard failure — never
         fabricate a check_id and submit
"""
from __future__ import annotations

import os
import sys
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

import app.main as te_main  # noqa: E402
from app.main import (  # noqa: E402
    OPEN_ORDER_STATUSES,
    _OPEN_STATUS_SQL,
    _call_risk,
    _submit_deferred_order,
)


# ══════════════════════════════════════════════════════════════════════════════
# A3 — open/working status set
# ══════════════════════════════════════════════════════════════════════════════


def test_open_status_set_includes_alpaca_working_states():
    """The dedup set must include the Alpaca-working states alpaca-sync maps into,
    not just our local pre-broker states — else a working-but-unfilled order is
    not deduped and gets double-submitted."""
    for s in ("pending", "submitted", "deferred", "accepted", "new", "partially_filled"):
        assert s in OPEN_ORDER_STATUSES, f"{s} missing from OPEN_ORDER_STATUSES"


def test_open_status_sql_literal_matches_constant():
    """The SQL literal used in the IN (...) clauses is derived from the one shared
    constant so the three guards can't drift."""
    for s in OPEN_ORDER_STATUSES:
        assert f"'{s}'" in _OPEN_STATUS_SQL


@pytest.mark.asyncio
async def test_inflight_sell_guard_query_uses_full_open_set():
    """_open_sell_order_for_ticker must match accepted/new/partially_filled too."""
    captured = {}

    async def _execute(query, params=None):
        captured["sql"] = str(query)
        result = MagicMock()
        mr = MagicMock()
        mr.first = MagicMock(return_value=None)
        result.mappings = MagicMock(return_value=mr)
        return result

    conn = AsyncMock()
    conn.execute = _execute
    await te_main._open_sell_order_for_ticker(conn, "AAPL", "intent-1")
    sql = captured["sql"].lower()
    assert "accepted" in sql and "new" in sql and "partially_filled" in sql
    # and the original three are still present
    assert "pending" in sql and "submitted" in sql and "deferred" in sql


@pytest.mark.asyncio
async def test_inflight_buy_guard_query_uses_full_open_set():
    """_open_buy_order_for_ticker must match accepted/new/partially_filled too."""
    captured = {}

    async def _execute(query, params=None):
        captured["sql"] = str(query)
        result = MagicMock()
        mr = MagicMock()
        mr.first = MagicMock(return_value=None)
        result.mappings = MagicMock(return_value=mr)
        return result

    conn = AsyncMock()
    conn.execute = _execute
    await te_main._open_buy_order_for_ticker(conn, "AAPL", "intent-1")
    sql = captured["sql"].lower()
    assert "accepted" in sql and "new" in sql and "partially_filled" in sql


# ══════════════════════════════════════════════════════════════════════════════
# A4 — _call_risk never fabricates a check_id
# ══════════════════════════════════════════════════════════════════════════════


def _risk_response(payload: dict):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_call_risk_returns_none_check_id_when_missing():
    """Risk omits check_id → _call_risk returns None (NOT a fabricated UUID)."""
    client = _risk_response({"approved": True, "reason": "ok", "rule_triggered": "ok"})
    with patch.object(te_main, "httpx") as httpx_mock:
        httpx_mock.AsyncClient = MagicMock(return_value=client)
        approved, reason, check_id, rule = await _call_risk({"ticker": "AAPL"})
    assert approved is True
    assert check_id is None


@pytest.mark.asyncio
async def test_call_risk_passes_through_real_check_id():
    cid = str(uuid.uuid4())
    client = _risk_response({"approved": True, "reason": "ok", "check_id": cid, "rule_triggered": "ok"})
    with patch.object(te_main, "httpx") as httpx_mock:
        httpx_mock.AsyncClient = MagicMock(return_value=client)
        _approved, _reason, check_id, _rule = await _call_risk({"ticker": "AAPL"})
    assert check_id == cid


# ══════════════════════════════════════════════════════════════════════════════
# A1 / A2 — deferred submit re-runs the full risk gate, fails CLOSED
# ══════════════════════════════════════════════════════════════════════════════


def _deferred_row(ticker="AAPL", action="entry", side="buy"):
    return {
        "id": str(uuid.uuid4()),
        "intent_id": str(uuid.uuid4()),
        "ticker": ticker,
        "action": action,
        "side": side,
        "qty": 10.0,
        "notional": 1500.0,
        "order_type": "market",
        "time_in_force": "day",
        "mode": "scheduled",
        "trace_id": str(uuid.uuid4()),
        "sim_date": None,
    }


def _noop_engine():
    """Engine whose begin()/connect() yield a no-op conn (used for the
    risk_check_id UPDATE)."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=MagicMock())

    def _ctx():
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=None)
        return ctx

    engine = MagicMock()
    engine.begin = MagicMock(side_effect=lambda: _ctx())
    engine.connect = MagicMock(side_effect=lambda: _ctx())
    return engine


@pytest.mark.asyncio
async def test_deferred_submit_calls_full_risk_check():
    """A deferred submit must call risk-service /check (the full gate), not just
    peek at the kill switch on /health."""
    submit_called = {"n": 0}

    async def _fake_submit_for_action(action, ticker, payload):
        submit_called["n"] += 1
        return "alp-1", "accepted", None

    with patch.object(te_main, "ALPACA_API_KEY", "k"), \
         patch.object(te_main, "ALPACA_SECRET_KEY", "s"), \
         patch.object(te_main, "engine", _noop_engine()), \
         patch.object(te_main, "_call_risk",
                      new=AsyncMock(return_value=(True, "ok", str(uuid.uuid4()), "ok"))) as risk_mock, \
         patch.object(te_main, "_submit_for_action", new=_fake_submit_for_action):
        status, err = await _submit_deferred_order(_deferred_row())

    assert risk_mock.await_count == 1, "deferred path must re-call risk-service /check"
    assert status == "submitted"
    assert err is None
    assert submit_called["n"] == 1


@pytest.mark.asyncio
async def test_deferred_submit_fails_closed_when_risk_unreachable():
    """Risk-service unreachable on a deferred submit → do NOT submit (fail closed)."""
    submit_called = {"n": 0}

    async def _fake_submit_for_action(action, ticker, payload):
        submit_called["n"] += 1
        return "alp-1", "accepted", None

    with patch.object(te_main, "ALPACA_API_KEY", "k"), \
         patch.object(te_main, "ALPACA_SECRET_KEY", "s"), \
         patch.object(te_main, "engine", _noop_engine()), \
         patch.object(te_main, "_call_risk",
                      new=AsyncMock(side_effect=httpx.ConnectError("refused"))), \
         patch.object(te_main, "_submit_for_action", new=_fake_submit_for_action):
        status, err = await _submit_deferred_order(_deferred_row())

    assert status == "failed"
    assert submit_called["n"] == 0, "must NOT submit when risk-service is unreachable"
    assert "risk re-check unavailable" in err.lower()


@pytest.mark.asyncio
async def test_deferred_submit_fails_closed_when_risk_rejects():
    """Risk-service now rejects (e.g. daily-loss tripped since approval) → no submit."""
    submit_called = {"n": 0}

    async def _fake_submit_for_action(action, ticker, payload):
        submit_called["n"] += 1
        return "alp-1", "accepted", None

    with patch.object(te_main, "ALPACA_API_KEY", "k"), \
         patch.object(te_main, "ALPACA_SECRET_KEY", "s"), \
         patch.object(te_main, "engine", _noop_engine()), \
         patch.object(te_main, "_call_risk",
                      new=AsyncMock(return_value=(False, "Daily loss limit", None, "daily_loss_limit"))), \
         patch.object(te_main, "_submit_for_action", new=_fake_submit_for_action):
        status, err = await _submit_deferred_order(_deferred_row())

    assert status == "failed"
    assert submit_called["n"] == 0
    assert "rejected" in err.lower()


@pytest.mark.asyncio
async def test_deferred_submit_fails_closed_when_approved_but_no_check_id():
    """Approved but no check_id → hard failure, no submit (no fabricated audit id)."""
    submit_called = {"n": 0}

    async def _fake_submit_for_action(action, ticker, payload):
        submit_called["n"] += 1
        return "alp-1", "accepted", None

    with patch.object(te_main, "ALPACA_API_KEY", "k"), \
         patch.object(te_main, "ALPACA_SECRET_KEY", "s"), \
         patch.object(te_main, "engine", _noop_engine()), \
         patch.object(te_main, "_call_risk",
                      new=AsyncMock(return_value=(True, "ok", None, "ok"))), \
         patch.object(te_main, "_submit_for_action", new=_fake_submit_for_action):
        status, err = await _submit_deferred_order(_deferred_row())

    assert status == "failed"
    assert submit_called["n"] == 0
    assert "check_id" in err
