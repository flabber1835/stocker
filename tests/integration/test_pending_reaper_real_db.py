"""Audit P1 — the orphaned-'pending' reaper, against a real Postgres.

A 'pending' alpaca_orders row is the reservation committed inside the submit lock
just before the broker submit. If the process dies between that commit and the
submit/defer transition, the row lingers as an open order (blocking re-proposal +
consuming a projected MAX_POSITIONS slot) until the next restart. _reap_orphaned_pending
fails such rows once older than PENDING_REAP_MINUTES, without touching deferred/submitted.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Load the trade-executor app (evict any other service's `app` first).
for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_TE = os.path.join(_ROOT, "services", "trade-executor")
if _TE not in sys.path:
    sys.path.insert(0, _TE)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x/y")  # import-time guard only

import app.main as te_main  # noqa: E402

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    # Point the module global at the test engine for the duration.
    prev = te_main.engine
    te_main.engine = eng
    async with eng.begin() as conn:
        await conn.execute(text("DELETE FROM alpaca_orders"))
    yield eng
    te_main.engine = prev
    await eng.dispose()


async def _insert(conn, *, status, age_min, ticker="AAA", side="buy"):
    created = datetime.now(timezone.utc) - timedelta(minutes=age_min)
    row = (await conn.execute(text(
        "INSERT INTO alpaca_orders (ticker, action, side, status, created_at) "
        "VALUES (:t, 'entry', :s, :st, :c) RETURNING id"
    ), {"t": ticker, "s": side, "st": status, "c": created})).scalar()
    return str(row)


async def _status(conn, oid):
    return (await conn.execute(text(
        "SELECT status FROM alpaca_orders WHERE id=:id"), {"id": oid})).scalar()


async def test_reaps_only_stale_pending(engine, monkeypatch):
    monkeypatch.setattr(te_main, "PENDING_REAP_MINUTES", 15.0)
    async with engine.begin() as conn:
        stale_pending = await _insert(conn, status="pending", age_min=20)
        fresh_pending = await _insert(conn, status="pending", age_min=2)
        stale_deferred = await _insert(conn, status="deferred", age_min=60, side="sell")
        stale_submitted = await _insert(conn, status="submitted", age_min=60)

    await te_main._reap_orphaned_pending()

    async with engine.connect() as conn:
        assert await _status(conn, stale_pending) == "failed"      # reaped
        assert await _status(conn, fresh_pending) == "pending"     # too young
        assert await _status(conn, stale_deferred) == "deferred"   # not pending → untouched
        assert await _status(conn, stale_submitted) == "submitted" # not pending → untouched


async def test_reaper_disabled_when_threshold_zero(engine, monkeypatch):
    monkeypatch.setattr(te_main, "PENDING_REAP_MINUTES", 0.0)
    async with engine.begin() as conn:
        old_pending = await _insert(conn, status="pending", age_min=120)
    await te_main._reap_orphaned_pending()
    async with engine.connect() as conn:
        assert await _status(conn, old_pending) == "pending"  # disabled → no reap


async def test_reaper_sets_diagnostic_error_message(engine, monkeypatch):
    monkeypatch.setattr(te_main, "PENDING_REAP_MINUTES", 15.0)
    async with engine.begin() as conn:
        oid = await _insert(conn, status="pending", age_min=30)
    await te_main._reap_orphaned_pending()
    async with engine.connect() as conn:
        msg = (await conn.execute(text(
            "SELECT error_message FROM alpaca_orders WHERE id=:id"), {"id": oid})).scalar()
    assert msg and "REAPED" in msg


class _FakeBrokerOrder:
    """Minimal stand-in for shared BrokerOrder as the reaper reads it."""
    def __init__(self, client_order_id, broker_order_id, status, raw_status):
        self.broker_order_id = broker_order_id
        self.status = status
        self.raw_status = raw_status
        self.raw = {"client_order_id": client_order_id}


async def test_reaper_recovers_live_order_instead_of_failing(engine, monkeypatch):
    """F2: a stale 'pending' whose order the broker ACTUALLY has (the lost
    pending->submitted UPDATE) must be RECOVERED to the broker's status with its
    alpaca_order_id set — not falsely reaped 'failed'."""
    monkeypatch.setattr(te_main, "PENDING_REAP_MINUTES", 15.0)
    async with engine.begin() as conn:
        live = await _insert(conn, status="pending", age_min=30)      # broker HAS it
        dead = await _insert(conn, status="pending", age_min=30, ticker="BBB")  # broker doesn't

    # Broker reports the 'live' order (keyed by client_order_id = the row id).
    class _FakeBroker:
        async def list_orders(self, *, status="all", limit=500):
            return [_FakeBrokerOrder(live, "alp-123", "submitted", "accepted")]

    monkeypatch.setattr(te_main, "_has_broker_credentials", lambda: True)
    monkeypatch.setattr(te_main, "_broker", lambda: _FakeBroker())

    await te_main._reap_orphaned_pending()

    async with engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT status, alpaca_order_id, alpaca_status, error_message "
            "FROM alpaca_orders WHERE id=:id"), {"id": live})).mappings().first()
        assert row["status"] == "submitted"                # recovered, not failed
        assert row["alpaca_order_id"] == "alp-123"         # broker id now recorded
        assert row["alpaca_status"] == "accepted"
        assert "RECOVERED" in (row["error_message"] or "")
        # The order the broker never heard of is still reaped.
        assert await _status(conn, dead) == "failed"


async def test_reaper_reaps_all_when_broker_list_fails(engine, monkeypatch):
    """If the broker list call errors, reconcile is best-effort → fall through to the
    safe reap (an unreconcilable pending is still failed, never left limbo)."""
    monkeypatch.setattr(te_main, "PENDING_REAP_MINUTES", 15.0)
    async with engine.begin() as conn:
        oid = await _insert(conn, status="pending", age_min=30)

    class _BoomBroker:
        async def list_orders(self, *, status="all", limit=500):
            raise RuntimeError("broker unreachable")

    monkeypatch.setattr(te_main, "_has_broker_credentials", lambda: True)
    monkeypatch.setattr(te_main, "_broker", lambda: _BoomBroker())

    await te_main._reap_orphaned_pending()
    async with engine.connect() as conn:
        assert await _status(conn, oid) == "failed"
