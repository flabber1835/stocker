"""FIX G — _size_partial current-holding lookups scope to the LATEST sync run.

Previously _size_partial's actual_weight fallback, live price, and sell_trim
held-qty lookups used `WHERE lp.ticker=:t AND sr.status='success' ORDER BY
sr.completed_at DESC LIMIT 1`, which reaches back across syncs to ANY run holding
the ticker — so a name absent from the LATEST sync (rotated out / closed) gets
resurrected from an OLDER run and mis-sized. The fix scopes every current-holding
lookup to the single latest successful sync run (the deterministic latest-run-id
subquery used by _size_exit / _is_already_held).

This test captures the SQL each lookup runs and asserts it uses the latest-run-id
subquery, NOT a bare cross-sync ORDER BY against live_positions.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.main import _size_partial


def _capturing_conn(rows_by_query):
    captured: list[str] = []
    call_count = [0]

    async def _execute(query, params=None):
        captured.append(str(query))
        result = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        row = rows_by_query[idx] if idx < len(rows_by_query) else None
        mr = MagicMock()
        mr.first = MagicMock(return_value=row)
        result.mappings = MagicMock(return_value=mr)
        return result

    conn = AsyncMock()
    conn.execute = _execute
    conn._captured = captured
    return conn


def _live_pos_lookups(captured):
    """SQL statements that read live_positions joined to alpaca_sync_runs."""
    return [
        s for s in captured
        if "live_positions" in s.lower() and "alpaca_sync_runs" in s.lower()
    ]


def _scoped_ok(sql: str) -> bool:
    """A correctly-scoped lookup pins the sync run via the latest-run-id subquery
    (sr.run_id = (SELECT run_id ... ORDER BY completed_at DESC ... LIMIT 1)) rather
    than ordering live_positions rows across syncs by sr.completed_at."""
    low = sql.lower()
    return "sr.run_id = (" in low and "select run_id from alpaca_sync_runs" in low


@pytest.mark.asyncio
async def test_buy_add_actual_weight_and_price_lookups_scoped_to_latest_run():
    now = datetime.now(timezone.utc)
    # actual_weight omitted → triggers the fallback live_pos lookup; then price.
    intent = {"action": "buy_add", "current_weight": 0.10, "actual_weight": None}
    conn = _capturing_conn([
        {"market_value": 5000.0, "account_value": 100_000.0},   # actual_weight fallback
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": now},  # acct
        {"current_price": 50.0},                                # live price
    ])
    await _size_partial(conn, "AAPL", intent)
    lookups = _live_pos_lookups(conn._captured)
    assert lookups, "expected live_positions lookups"
    for sql in lookups:
        assert _scoped_ok(sql), f"unscoped live_positions lookup: {sql}"


@pytest.mark.asyncio
async def test_sell_trim_held_qty_lookup_scoped_to_latest_run():
    now = datetime.now(timezone.utc)
    intent = {"action": "sell_trim", "current_weight": 0.05, "actual_weight": 0.10}
    conn = _capturing_conn([
        {"account_value": 100_000.0, "buying_power": 100_000.0, "completed_at": now},  # acct
        {"current_price": 50.0},                                # live price
        {"qty": 100.0},                                         # held-qty over-sell guard
    ])
    await _size_partial(conn, "AAPL", intent)
    lookups = _live_pos_lookups(conn._captured)
    assert lookups
    for sql in lookups:
        assert _scoped_ok(sql), f"unscoped live_positions lookup: {sql}"
