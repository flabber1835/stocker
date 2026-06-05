"""Unit tests for the in-flight-sell guard (_open_sell_order_for_ticker).

Regression guard for the "insufficient qty available (available: 0)" failures:
a position whose sell is still UNFILLED has its shares reserved at the broker,
but the latest sync still shows it HELD — so a re-proposed exit/sell_trim from a
NEW delta run (a new intent_id, which the Step-1 idempotency check does not
catch) would be sized from the held qty and double-submitted. This helper finds
the existing OPEN sell order for the ticker so submit_order can skip the dup.

Mocks the SQLAlchemy connection (no real Postgres), capturing the query so the
guard's SQL semantics (sell-side, open statuses, intent exclusion) are asserted.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.main import _open_sell_order_for_ticker


def _mock_conn_returning(row):
    """Fake async conn whose execute(...).mappings().first() yields `row`, and
    records the last query text + params for assertions."""
    conn = AsyncMock()
    captured = {}

    async def _execute(query, params=None):
        captured["sql"] = str(query)
        captured["params"] = params
        result = MagicMock()
        mr = MagicMock()
        mr.first = MagicMock(return_value=row)
        result.mappings = MagicMock(return_value=mr)
        return result

    conn.execute = _execute
    return conn, captured


@pytest.mark.asyncio
async def test_returns_none_when_no_open_sell():
    conn, _ = _mock_conn_returning(None)
    got = await _open_sell_order_for_ticker(conn, "BNS", "intent-2")
    assert got is None


@pytest.mark.asyncio
async def test_returns_order_dict_when_open_sell_exists():
    row = {"id": "ord-1", "intent_id": "intent-1", "action": "exit", "status": "submitted"}
    conn, _ = _mock_conn_returning(row)
    got = await _open_sell_order_for_ticker(conn, "BNS", "intent-2")
    assert got is not None
    assert got["id"] == "ord-1"
    assert got["action"] == "exit"
    assert got["status"] == "submitted"


@pytest.mark.asyncio
async def test_query_scopes_to_sell_side_open_statuses_and_excludes_intent():
    """The guard must only match SELL-side, OPEN orders, and exclude this intent."""
    conn, captured = _mock_conn_returning(None)
    await _open_sell_order_for_ticker(conn, "TD", "intent-99")
    sql = captured["sql"].lower()
    assert "side = 'sell'" in sql                       # never blocked by an open buy
    assert "pending" in sql and "submitted" in sql and "deferred" in sql  # open set
    assert "is distinct from" in sql                    # exclude this intent's own row
    assert captured["params"] == {"t": "TD", "iid": "intent-99"}


@pytest.mark.asyncio
async def test_params_thread_ticker_and_intent_through():
    row = {"id": "ord-x", "intent_id": "morning", "action": "sell_trim", "status": "deferred"}
    conn, captured = _mock_conn_returning(row)
    got = await _open_sell_order_for_ticker(conn, "CM", "evening")
    assert got["action"] == "sell_trim"
    assert captured["params"]["t"] == "CM"
    assert captured["params"]["iid"] == "evening"
