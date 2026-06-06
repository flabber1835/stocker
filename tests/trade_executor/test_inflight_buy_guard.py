"""Unit tests for the in-flight-buy guard (_open_buy_order_for_ticker).

Buy-side mirror of the in-flight-sell guard. A buy order that is SUBMITTED but
not yet FILLED (e.g. a day order queued after the close) leaves the position
un-held, so the already-held guard can't see it; a re-proposed entry/buy_add from
a NEW delta run is a new intent_id and slips past the Step-1 idempotency check —
which would stack a SECOND buy and double the position. This helper finds the
existing OPEN buy order for the ticker so submit_order can skip the dup.

Mocks the SQLAlchemy connection (no real Postgres), capturing the query so the
guard's SQL semantics (buy-side, open statuses, intent exclusion) are asserted.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.main import _open_buy_order_for_ticker


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
async def test_returns_none_when_no_open_buy():
    conn, _ = _mock_conn_returning(None)
    got = await _open_buy_order_for_ticker(conn, "NEM", "intent-2")
    assert got is None


@pytest.mark.asyncio
async def test_returns_order_dict_when_open_buy_exists():
    row = {"id": "ord-1", "intent_id": "intent-1", "action": "entry", "status": "submitted"}
    conn, _ = _mock_conn_returning(row)
    got = await _open_buy_order_for_ticker(conn, "NEM", "intent-2")
    assert got is not None
    assert got["id"] == "ord-1"
    assert got["action"] == "entry"
    assert got["status"] == "submitted"


@pytest.mark.asyncio
async def test_query_scopes_to_buy_side_open_statuses_and_excludes_intent():
    """The guard must only match BUY-side, OPEN orders, and exclude this intent."""
    conn, captured = _mock_conn_returning(None)
    await _open_buy_order_for_ticker(conn, "KGC", "intent-99")
    sql = captured["sql"].lower()
    assert "side = 'buy'" in sql                        # never blocked by an open sell
    assert "pending" in sql and "submitted" in sql and "deferred" in sql  # open set
    assert "is distinct from" in sql                    # exclude this intent's own row
    assert captured["params"] == {"t": "KGC", "iid": "intent-99"}


@pytest.mark.asyncio
async def test_params_thread_ticker_and_intent_through():
    row = {"id": "ord-x", "intent_id": "run-a", "action": "buy_add", "status": "deferred"}
    conn, captured = _mock_conn_returning(row)
    got = await _open_buy_order_for_ticker(conn, "AAPL", "run-b")
    assert got["action"] == "buy_add"
    assert captured["params"]["t"] == "AAPL"
    assert captured["params"]["iid"] == "run-b"
