"""FIX C — cancel_all_orders must only mark CONFIRMED broker cancels as 'canceled'.

Previously the endpoint flipped EVERY local open row to 'canceled' regardless of
which per-order broker cancels actually succeeded — so the DB could claim an order
was canceled while it was still live at the broker. The fix maps Alpaca's per-order
multi-status result by alpaca_order_id and only marks 'canceled' the confirmed ids
(plus local-only rows with no broker order); failed/unknown rows get the distinct
non-terminal 'cancel_failed'.

These tests capture the UPDATE statements the endpoint runs and assert the
confirmed id is canceled while the failed id is routed to 'cancel_failed' (NOT
canceled).
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_TE_PATH = os.path.join(ROOT, "services", "trade-executor")
if _TE_PATH not in sys.path:
    sys.path.insert(0, _TE_PATH)
sys.path.insert(0, os.path.join(ROOT, "shared"))

import app.main as te_main  # noqa: E402


class _RecordingConn:
    """Records every execute(sql, params); returns a result whose rowcount equals
    the number of bound `confirmed`/`open` matches we choose to simulate."""

    def __init__(self, statements: list):
        self._statements = statements

    async def execute(self, query, params=None):
        sql = str(query)
        self._statements.append((sql, params or {}))
        res = MagicMock()
        # Give UPDATEs a deterministic rowcount so the endpoint's counters work.
        res.rowcount = 1
        mr = MagicMock()
        mr.first = MagicMock(return_value=None)
        res.mappings = MagicMock(return_value=mr)
        return res


def _recording_engine(statements: list):
    def _ctx():
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=_RecordingConn(statements))
        ctx.__aexit__ = AsyncMock(return_value=None)
        return ctx

    eng = MagicMock()
    eng.begin = MagicMock(side_effect=lambda: _ctx())
    eng.connect = MagicMock(side_effect=lambda: _ctx())
    return eng


def _alpaca_multistatus(items):
    resp = MagicMock()
    resp.status_code = 207
    resp.json.return_value = items
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.delete = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_failed_broker_cancel_not_marked_canceled():
    # Alpaca returns one confirmed cancel (200) and one failed (500).
    items = [
        {"id": "alp-ok", "status": 200},
        {"id": "alp-bad", "status": 500, "body": "still working"},
    ]
    statements: list = []
    with patch.object(te_main, "ALPACA_API_KEY", "k"), \
         patch.object(te_main, "ALPACA_SECRET_KEY", "s"), \
         patch.object(te_main, "engine", _recording_engine(statements)), \
         patch.object(te_main, "httpx") as httpx_mock:
        httpx_mock.AsyncClient = MagicMock(return_value=_alpaca_multistatus(items))
        resp = await te_main.cancel_all_orders(confirm="yes")

    # Only the confirmed cancel counts toward alpaca_cancel_count.
    assert resp.alpaca_cancel_count == 1
    assert len(resp.alpaca_errors) == 1
    assert resp.status == "partial"

    # Find the two UPDATE statements on alpaca_orders.
    canceled_stmt = next(
        (s for s in statements if "set status='canceled'" in s[0].lower()), None
    )
    failed_stmt = next(
        (s for s in statements if "set status='cancel_failed'" in s[0].lower()), None
    )
    assert canceled_stmt is not None, "expected a SET status='canceled' UPDATE"
    assert failed_stmt is not None, "expected a SET status='cancel_failed' UPDATE"

    # CRITICAL: the canceled UPDATE is scoped to the confirmed broker ids (or NULL),
    # so the failed id ('alp-bad') is NOT in its confirmed bind list.
    confirmed = canceled_stmt[1].get("confirmed")
    assert confirmed == ["alp-ok"], f"confirmed bind should be only the OK id, got {confirmed}"
    # The cancel_failed UPDATE targets rows whose broker cancel was NOT confirmed.
    assert "not (alpaca_order_id = any(:confirmed))" in failed_stmt[0].lower()


@pytest.mark.asyncio
async def test_whole_call_failure_marks_broker_orders_cancel_failed():
    # HTTP transport blows up entirely → no per-order info; every broker-backed
    # row must be 'cancel_failed', and only local-only (NULL alpaca_order_id) rows
    # may be 'canceled'.
    statements: list = []
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.delete = AsyncMock(side_effect=RuntimeError("connection refused"))
    with patch.object(te_main, "ALPACA_API_KEY", "k"), \
         patch.object(te_main, "ALPACA_SECRET_KEY", "s"), \
         patch.object(te_main, "engine", _recording_engine(statements)), \
         patch.object(te_main, "httpx") as httpx_mock:
        httpx_mock.AsyncClient = MagicMock(return_value=client)
        resp = await te_main.cancel_all_orders(confirm="yes")

    assert resp.alpaca_cancel_count == 0
    canceled_stmt = next(
        (s for s in statements if "set status='canceled'" in s[0].lower()), None
    )
    failed_stmt = next(
        (s for s in statements if "set status='cancel_failed'" in s[0].lower()), None
    )
    assert canceled_stmt is not None and failed_stmt is not None
    # In the whole-call-failed branch the canceled UPDATE is restricted to NULL
    # broker ids (local-only rows) and the failed UPDATE to NON-NULL ones.
    assert "alpaca_order_id is null" in canceled_stmt[0].lower()
    assert "alpaca_order_id is not null" in failed_stmt[0].lower()
