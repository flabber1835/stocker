"""Audit #8 — atomic approve-and-reserve, exercised against a REAL Postgres.

The defect: risk-approval and the local creation of the reservation (the committed
`pending` alpaca_orders row that risk-service counts in its MAX_POSITIONS / turnover
SQL) are not atomic across DIFFERENT intents. Two concurrent submits for two new
tickers both run risk /check BEFORE either commits its reservation, both pass the
same cap, both reserve → the cap is breached (the confirmed "42 projected" race).

Fix: serialize [check → reserve] per (account, trading_day) with a Postgres
SESSION-level advisory lock (app.submit_lock.with_submit_lock).

These tests run the REAL advisory lock on a REAL Postgres concurrently. The
stress test models the production critical section (count-under-cap then INSERT
a reservation, with a deliberate await between the two halves to widen the TOCTOU
window) and asserts the cap holds; the paired test-the-test runs the SAME
concurrent workload WITHOUT the lock and asserts it over-reserves — so the test
would fail if the lock were a no-op.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# The integration tier doesn't put service code on the path (its other tests use
# raw SQL only). submit_lock is a small, dependency-light module (sqlalchemy +
# stdlib); add the trade-executor service dir so we can exercise the REAL helper.
# Another integration test imports a DIFFERENT service's `app` package
# (portfolio-builder's app.select), so evict any cached `app` first or this import
# resolves against the wrong package.
for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_TE = os.path.join(_ROOT, "services", "trade-executor")
if _TE not in sys.path:
    sys.path.insert(0, _TE)

from app.submit_lock import SubmitLockTimeout, submit_lock_key, with_submit_lock  # noqa: E402

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def engine(async_dsn):
    # Generous pool: each concurrent task may hold the lock's dedicated connection
    # AND a second connection for its reservation INSERT at the same time.
    eng = create_async_engine(async_dsn, future=True, pool_size=25, max_overflow=25)
    # Scratch table for the reservation model. A real (non-TEMP) table so every
    # pooled connection / concurrent task sees the same committed rows (TEMP tables
    # are per-connection and would defeat the cross-connection race we test).
    async with eng.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS _reserve_test"))
        await conn.execute(text("CREATE TABLE _reserve_test (ticker text PRIMARY KEY)"))
    yield eng
    async with eng.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS _reserve_test"))
    await eng.dispose()


# ── lock primitive behavior ───────────────────────────────────────────────────

async def test_same_key_is_mutually_exclusive(engine):
    """While one holder owns the lock, a second acquire for the SAME key times out."""
    acct, day = "alpaca-paper", "2026-06-19"
    async with with_submit_lock(engine, acct, day):
        with pytest.raises(SubmitLockTimeout):
            async with with_submit_lock(engine, acct, day, timeout_secs=0.5, poll_secs=0.05):
                pass  # pragma: no cover - must not be reached


async def test_distinct_keys_do_not_block(engine):
    """Different (account, day) → different lock → no serialization."""
    async with with_submit_lock(engine, "alpaca-paper", "2026-06-19"):
        # A different day must be acquirable immediately even while the first is held.
        async with with_submit_lock(engine, "alpaca-paper", "2026-06-20",
                                    timeout_secs=1.0, poll_secs=0.05):
            pass


async def test_lock_released_on_exception(engine):
    """An exception inside the body still releases the lock (finally path)."""
    acct, day = "alpaca-paper", "2026-06-19"
    with pytest.raises(RuntimeError):
        async with with_submit_lock(engine, acct, day):
            raise RuntimeError("boom inside critical section")
    # If the lock leaked we could not re-acquire it; this must succeed promptly.
    async with with_submit_lock(engine, acct, day, timeout_secs=1.0, poll_secs=0.05):
        pass


async def test_lock_actually_held_in_pg_locks(engine):
    """Sanity: the session advisory lock is visible in pg_locks while held."""
    acct, day = "alpaca-paper", "2026-06-19"
    key = submit_lock_key(acct, day)
    # Postgres splits a bigint advisory key into (classid, objid) hi/lo int4 halves.
    hi = (key >> 32) & 0xFFFFFFFF
    lo = key & 0xFFFFFFFF
    # interpret as signed int4 the way pg_locks reports them
    hi = hi - (1 << 32) if hi >= (1 << 31) else hi
    lo = lo - (1 << 32) if lo >= (1 << 31) else lo
    async with with_submit_lock(engine, acct, day):
        async with engine.connect() as conn:
            n = (await conn.execute(text(
                "SELECT count(*) FROM pg_locks WHERE locktype='advisory' "
                "AND classid=:hi AND objid=:lo"
            ), {"hi": hi, "lo": lo})).scalar()
        assert n >= 1


# ── the headline race: count-under-cap then reserve ───────────────────────────

async def _attempt_reserve(engine, ticker: str, cap: int, *, use_lock: bool):
    """Model ONE submit's critical section: check the projected count against the
    cap, then (if room) INSERT a reservation. The await between the two halves
    simulates the risk-service round-trip and widens the TOCTOU window."""
    acct, day = "alpaca-paper", "2026-06-19"

    async def _critical():
        async with engine.connect() as conn:
            held = (await conn.execute(text("SELECT count(*) FROM _reserve_test"))).scalar()
        if held >= cap:
            return False  # at capacity — risk-service would REJECT this entry
        await asyncio.sleep(0.05)  # widen the window (the real risk HTTP call)
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO _reserve_test (ticker) VALUES (:t)"),
                               {"t": ticker})
        return True

    if use_lock:
        async with with_submit_lock(engine, acct, day, timeout_secs=30, poll_secs=0.02):
            return await _critical()
    return await _critical()


async def test_concurrent_entries_respect_cap_with_lock(engine):
    """Audit scenario: book one short of the cap, fire N concurrent NEW-ticker
    entries. With the lock exactly ONE may reserve; the book lands exactly at cap."""
    cap = 30
    # Seed cap-1 held positions.
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO _reserve_test (ticker) "
                                "SELECT 'HELD' || g FROM generate_series(1, :n) g"),
                           {"n": cap - 1})

    results = await asyncio.gather(*[
        _attempt_reserve(engine, f"NEW{i}", cap, use_lock=True) for i in range(10)
    ])

    async with engine.connect() as conn:
        total = (await conn.execute(text("SELECT count(*) FROM _reserve_test"))).scalar()
    assert sum(results) == 1, f"expected exactly 1 reservation, got {sum(results)}"
    assert total == cap, f"book breached cap: {total} > {cap}"


async def test_without_lock_over_reserves(engine):
    """Test-the-test: the SAME concurrent workload WITHOUT the lock breaches the
    cap (proving the lock is what enforces it — not the modeling)."""
    cap = 30
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO _reserve_test (ticker) "
                                "SELECT 'HELD' || g FROM generate_series(1, :n) g"),
                           {"n": cap - 1})

    results = await asyncio.gather(*[
        _attempt_reserve(engine, f"NEW{i}", cap, use_lock=False) for i in range(10)
    ])

    async with engine.connect() as conn:
        total = (await conn.execute(text("SELECT count(*) FROM _reserve_test"))).scalar()
    # Without serialization, multiple racers all read held==cap-1 and all insert.
    assert sum(results) > 1, "expected the unserialized race to over-reserve"
    assert total > cap, f"expected cap breach without the lock; got {total}"
