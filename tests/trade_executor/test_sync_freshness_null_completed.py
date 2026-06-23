"""Audit P0 — a 'success' alpaca-sync row with NULL completed_at must NOT bypass the
sizing staleness gate.

Previously `_size_entry` / `_size_partial` only ran the EXIT_SYNC_MAX_AGE_HOURS check
`if completed_at is not None`, so a success row with no completion timestamp silently
SKIPPED the guard and sized off an unknown-age snapshot. Fix: unknown freshness fails
CLOSED on the OPENING side (entry, buy_add); reducing trades (sell_trim) stay permissive
(de-risking must never be trapped), mirroring exits.
"""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.main import _size_entry, _size_partial


def _capturing_conn(rows_by_query):
    captured = []
    call_count = [0]

    async def _execute(query, params=None):
        captured.append(str(query))
        from unittest.mock import MagicMock
        idx = call_count[0]
        call_count[0] += 1
        row = rows_by_query[idx] if idx < len(rows_by_query) else None
        result = MagicMock()
        mr = MagicMock()
        mr.first = MagicMock(return_value=row)
        result.mappings = MagicMock(return_value=mr)
        return result

    from unittest.mock import AsyncMock
    conn = AsyncMock()
    conn.execute = _execute
    return conn


# ── _size_entry (always opening → fail closed) ──────────────────────────────────

@pytest.mark.asyncio
async def test_entry_null_completed_at_refuses():
    # acct row exists but completed_at is NULL → must refuse, not size.
    conn = _capturing_conn([
        {"account_value": 100_000.0, "buying_power": 0.0, "completed_at": None},
    ])
    with pytest.raises(HTTPException) as ei:
        await _size_entry(conn, "AAPL", 0.05)
    assert ei.value.status_code == 409
    assert "no completion timestamp" in ei.value.detail.lower() or "no fresh" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_entry_no_sync_row_refuses():
    conn = _capturing_conn([None])  # no successful sync at all
    with pytest.raises(HTTPException) as ei:
        await _size_entry(conn, "AAPL", 0.05)
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_entry_fresh_sync_sizes_normally():
    now = datetime.now(timezone.utc)
    conn = _capturing_conn([
        {"account_value": 100_000.0, "buying_power": 50_000.0, "completed_at": now},  # acct
        {"current_price": 50.0},                                                      # live price
    ])
    qty, notional, summary = await _size_entry(conn, "AAPL", 0.05)
    assert qty == 100.0            # floor(100000*0.05/50)
    assert notional == pytest.approx(5000.0)


# ── _size_partial: buy_add fails closed, sell_trim stays permissive ─────────────

@pytest.mark.asyncio
async def test_buy_add_null_completed_at_refuses():
    conn = _capturing_conn([
        {"account_value": 100_000.0, "buying_power": 0.0, "completed_at": None},  # acct
    ])
    intent = {"action": "buy_add", "current_weight": 0.10, "actual_weight": 0.05}
    with pytest.raises(HTTPException) as ei:
        await _size_partial(conn, "AAPL", intent)
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_sell_trim_null_completed_at_is_permitted():
    # Reducing risk on an unknown-age sync is allowed (like an exit). Should size, not raise.
    conn = _capturing_conn([
        {"account_value": 100_000.0, "buying_power": 0.0, "completed_at": None},  # acct
        {"current_price": 50.0},                                                  # live price
        {"qty": 100.0},                                                           # held_now
    ])
    intent = {"action": "sell_trim", "current_weight": 0.05, "actual_weight": 0.10}
    qty, notional, summary = await _size_partial(conn, "AAPL", intent)
    assert qty == 100.0   # floor((0.10-0.05)*100000/50), clamped to held 100
