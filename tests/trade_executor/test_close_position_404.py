"""FIX H — a close-position 404 must yield a TERMINAL no-op status, not 'submitted'.

_close_position_alpaca returns (None, 'position_already_closed', None) on a 404
(position already flat). The success branch previously wrote status='submitted'
with alpaca_order_id NULL — a fake in-flight order that lingers forever and could
be re-submitted. The fix records the terminal no-op status 'closed'.
"""
from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_TE_PATH = os.path.join(ROOT, "services", "trade-executor")
if _TE_PATH not in sys.path:
    sys.path.insert(0, _TE_PATH)
sys.path.insert(0, os.path.join(ROOT, "shared"))

import app.main as te_main  # noqa: E402
from app.main import _submit_deferred_order  # noqa: E402


def _noop_engine(captured: dict):
    conn = AsyncMock()

    async def _exec(query, params=None):
        sql = str(query)
        if "set status=" in sql.lower() and params and "st" in params:
            captured["status"] = params["st"]
        return MagicMock()

    conn.execute = _exec

    def _ctx():
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=None)
        return ctx

    eng = MagicMock()
    eng.begin = MagicMock(side_effect=lambda: _ctx())
    eng.connect = MagicMock(side_effect=lambda: _ctx())
    return eng


def _exit_row():
    return {
        "id": str(uuid.uuid4()),
        "intent_id": str(uuid.uuid4()),
        "ticker": "AAPL",
        "action": "exit",
        "side": "sell",
        "qty": 10.0,
        "notional": 1500.0,
        "order_type": "market",
        "time_in_force": "day",
        "mode": "scheduled",
        "trace_id": str(uuid.uuid4()),
        "sim_date": None,
    }


@pytest.mark.asyncio
async def test_deferred_close_404_records_closed_not_submitted():
    captured: dict = {}
    with patch.object(te_main, "ALPACA_API_KEY", "k"), \
         patch.object(te_main, "ALPACA_SECRET_KEY", "s"), \
         patch.object(te_main, "engine", _noop_engine(captured)), \
         patch.object(te_main, "_call_risk",
                      new=AsyncMock(return_value=(True, "ok", str(uuid.uuid4()), "ok"))), \
         patch.object(te_main, "_submit_for_action",
                      new=AsyncMock(return_value=(None, "position_already_closed", None))):
        status, err = await _submit_deferred_order(_exit_row())

    assert err is None
    assert status == "closed", f"expected terminal 'closed', got {status!r}"
    assert captured.get("status") == "closed"


@pytest.mark.asyncio
async def test_deferred_real_submit_still_submitted():
    """A genuine broker submission (real order id) is still 'submitted'."""
    captured: dict = {}
    with patch.object(te_main, "ALPACA_API_KEY", "k"), \
         patch.object(te_main, "ALPACA_SECRET_KEY", "s"), \
         patch.object(te_main, "engine", _noop_engine(captured)), \
         patch.object(te_main, "_call_risk",
                      new=AsyncMock(return_value=(True, "ok", str(uuid.uuid4()), "ok"))), \
         patch.object(te_main, "_submit_for_action",
                      new=AsyncMock(return_value=("alp-123", "accepted", None))):
        status, err = await _submit_deferred_order(_exit_row())

    assert err is None
    assert status == "submitted"
    assert captured.get("status") == "submitted"


def test_close_position_alpaca_404_sentinel():
    """Guard the contract: the 404 sentinel string matches the executor constant."""
    assert te_main._ALREADY_CLOSED_ALPACA_STATUS == "position_already_closed"
    assert te_main._CLOSED_NOOP_STATUS == "closed"
