"""Per-ticker in-flight dedup race — exercised against a REAL Postgres.

Root cause (seam audit): the trade-executor's per-ticker in-flight guards
(_open_buy_order_for_ticker / _open_sell_order_for_ticker) ran OUTSIDE the submit
lock — a check-then-act with no DB unique index on ticker (unlike intent_id). Two
concurrent same-ticker / different-intent approvals both pass the guard before
either records → two open orders for the same ticker (a doubled position).

Fix: re-check the guard INSIDE with_submit_lock, just before the reservation INSERT.
The lock serializes all account submits, so the in-lock [check → reserve] is atomic:
the loser sees the winner's committed order and skips.

These tests model the two critical-section shapes on the REAL advisory lock and a
real committed scratch table:
  - guard_inside_lock=True  (the FIX)         → exactly ONE reservation
  - guard_inside_lock=False (the OLD shape:   → TWO reservations (the race)
    guard outside, reserve inside the lock)
The paired "old shape over-reserves" test is the test-the-test: it fails if the
race weren't real, proving the fix (not the modeling) is what enforces the invariant.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Evict any cached `app` (a sibling integration test imports a different service's
# app package) then load the REAL submit lock from trade-executor.
for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_TE = os.path.join(_ROOT, "services", "trade-executor")
if _TE not in sys.path:
    sys.path.insert(0, _TE)

from app.submit_lock import with_submit_lock  # noqa: E402

pytestmark = pytest.mark.asyncio

_ACCT, _DAY = "alpaca-paper", "2026-06-20"


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True, pool_size=25, max_overflow=25)
    async with eng.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS _orders_test"))
        # one row per order; an 'open' row for a ticker means a live in-flight order
        await conn.execute(text(
            "CREATE TABLE _orders_test (id serial PRIMARY KEY, ticker text, "
            "intent text, status text)"))
    yield eng
    async with eng.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS _orders_test"))
    await eng.dispose()


async def _has_open(conn, ticker: str, exclude_intent: str) -> bool:
    n = (await conn.execute(text(
        "SELECT count(*) FROM _orders_test WHERE ticker=:t AND status='open' "
        "AND intent <> :i"), {"t": ticker, "i": exclude_intent})).scalar()
    return n > 0


async def _attempt(engine, ticker: str, intent: str, *, guard_inside_lock: bool) -> bool:
    """Model one submit's per-ticker dedup + reservation."""
    async def _guard_then_reserve():
        async with engine.connect() as conn:
            if await _has_open(conn, ticker, intent):
                return False
        await asyncio.sleep(0.05)  # widen the window (the real risk round-trip)
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO _orders_test (ticker, intent, status) "
                "VALUES (:t, :i, 'open')"), {"t": ticker, "i": intent})
        return True

    if guard_inside_lock:
        # THE FIX: guard re-check AND reserve both under the lock → atomic.
        async with with_submit_lock(engine, _ACCT, _DAY, timeout_secs=30, poll_secs=0.02):
            return await _guard_then_reserve()
    else:
        # OLD SHAPE: guard OUTSIDE the lock, reserve inside it.
        async with engine.connect() as conn:
            if await _has_open(conn, ticker, intent):
                return False
        await asyncio.sleep(0.05)
        async with with_submit_lock(engine, _ACCT, _DAY, timeout_secs=30, poll_secs=0.02):
            async with engine.begin() as conn:
                await conn.execute(text(
                    "INSERT INTO _orders_test (ticker, intent, status) "
                    "VALUES (:t, :i, 'open')"), {"t": ticker, "i": intent})
            return True


async def _count_open(engine, ticker: str) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(text(
            "SELECT count(*) FROM _orders_test WHERE ticker=:t AND status='open'"),
            {"t": ticker})).scalar()


async def test_in_lock_recheck_yields_exactly_one_order(engine):
    """Two concurrent approvals for the SAME ticker (different intents). With the
    in-lock re-check exactly ONE reserves — no doubled position."""
    results = await asyncio.gather(
        _attempt(engine, "CF", "intent-A", guard_inside_lock=True),
        _attempt(engine, "CF", "intent-B", guard_inside_lock=True),
    )
    assert sum(results) == 1, f"expected exactly 1 reservation, got {sum(results)}"
    assert await _count_open(engine, "CF") == 1


async def test_old_out_of_lock_guard_double_reserves(engine):
    """Test-the-test: the OLD shape (guard outside the lock) lets both concurrent
    same-ticker approvals through → two open orders. Proves the race is real and
    that moving the check inside the lock is what fixes it."""
    results = await asyncio.gather(
        _attempt(engine, "CF", "intent-A", guard_inside_lock=False),
        _attempt(engine, "CF", "intent-B", guard_inside_lock=False),
    )
    assert sum(results) == 2, "expected the unserialized guard to double-reserve"
    assert await _count_open(engine, "CF") == 2


async def test_different_tickers_both_reserve(engine):
    """Sanity: distinct tickers are independent — both reserve under the fix."""
    results = await asyncio.gather(
        _attempt(engine, "AAA", "intent-A", guard_inside_lock=True),
        _attempt(engine, "BBB", "intent-B", guard_inside_lock=True),
    )
    assert sum(results) == 2
