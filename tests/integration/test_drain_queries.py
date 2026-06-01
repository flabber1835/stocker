"""Schema-contract tests for the fill-gated market-open drain (Option B).

Runs the EXACT SQL the trade-executor drain (services/trade-executor/app/main.py
`_drain_pass`) and the api approval idempotency check execute, against a real
migrated Postgres. Catches in CI — not in production — a wrong column name, a
missing migration (0015 `expires_at`), or a mis-scoped status UPDATE.

The pure sequencing decision (sells-first / buying-power gate / expiry) is covered
by tests/trade_executor/test_drain_planner.py; this tier proves the queries that
FEED that planner return the right rows from the real schema.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio

# Column list the drain selects for each queue partition.
_COLS = "id, side, notional, submitted_at, expires_at"


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        await conn.execute(text("TRUNCATE alpaca_orders RESTART IDENTITY CASCADE"))
    yield eng
    await eng.dispose()


async def _insert_order(conn, *, ticker, side, action, status,
                        notional=1000.0, deferred_until=None, expires_at=None,
                        filled_at=None, submitted_at=None, alpaca_order_id=None,
                        intent_id=None, created_at=None):
    # created_at is set explicitly (NOW() is constant within a transaction, so
    # rows inserted together would tie and break ORDER BY created_at tests).
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    oid = uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO alpaca_orders "
        "(id, intent_id, ticker, action, side, notional, status, "
        " deferred_until, expires_at, filled_at, submitted_at, alpaca_order_id, created_at) "
        "VALUES (:id, :iid, :tk, :act, :sd, :nt, :st, :du, :ea, :fa, :sa, :aoid, :ca)"
    ), {"id": oid, "iid": intent_id, "tk": ticker, "act": action, "sd": side,
        "nt": notional, "st": status, "du": deferred_until, "ea": expires_at,
        "fa": filled_at, "sa": submitted_at, "aoid": alpaca_order_id, "ca": created_at})
    return str(oid)


# ── migration 0015 ────────────────────────────────────────────────────────────

async def test_expires_at_column_exists(engine):
    """0015 must have added alpaca_orders.expires_at (the drain selects it)."""
    async with engine.connect() as conn:
        col = (await conn.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name='alpaca_orders' AND column_name='expires_at'"
        ))).scalar()
    assert col is not None, "migration 0015 did not add expires_at"
    assert "timestamp" in col


# ── drain queue partition queries ─────────────────────────────────────────────

async def test_deferred_sells_query_partitions_correctly(engine):
    """The deferred-sells SELECT returns only due sell-side deferred orders."""
    async with engine.begin() as conn:
        s_due = await _insert_order(conn, ticker="AAPL", side="sell", action="exit",
                                    status="deferred", deferred_until=None)
        # a buy (wrong side), a submitted sell (wrong status), and a not-yet-due sell
        await _insert_order(conn, ticker="MSFT", side="buy", action="entry", status="deferred")
        await _insert_order(conn, ticker="NVDA", side="sell", action="exit", status="submitted")
        await _insert_order(conn, ticker="TSLA", side="sell", action="exit",
                            status="deferred",
                            deferred_until=datetime.now(timezone.utc) + timedelta(days=1))

    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            f"SELECT {_COLS} FROM alpaca_orders WHERE status='deferred' AND side='sell' "
            "AND (deferred_until IS NULL OR deferred_until <= NOW()) ORDER BY created_at ASC"
        ))).mappings().fetchall()
    assert [str(r["id"]) for r in rows] == [s_due]  # only the due deferred sell


async def test_unfilled_submitted_sells_query(engine):
    """The fill-gate query finds submitted, not-yet-filled sells only."""
    async with engine.begin() as conn:
        unfilled = await _insert_order(conn, ticker="AAPL", side="sell", action="exit",
                                       status="submitted", filled_at=None,
                                       alpaca_order_id="abc")
        # filled sell (excluded) and a submitted buy (excluded)
        await _insert_order(conn, ticker="MSFT", side="sell", action="exit",
                            status="filled", filled_at=datetime.now(timezone.utc),
                            alpaca_order_id="def")
        await _insert_order(conn, ticker="NVDA", side="buy", action="entry", status="submitted")

    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            f"SELECT {_COLS} FROM alpaca_orders WHERE status='submitted' AND side='sell' "
            "AND filled_at IS NULL"
        ))).mappings().fetchall()
    assert [str(r["id"]) for r in rows] == [unfilled]


async def test_deferred_buys_query_ordered_oldest_first(engine):
    """Deferred buys are returned oldest-first (the planner releases in that order)."""
    t0 = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        b1 = await _insert_order(conn, ticker="AAPL", side="buy", action="entry",
                                 status="deferred", created_at=t0)
        b2 = await _insert_order(conn, ticker="MSFT", side="buy", action="buy_add",
                                 status="deferred", created_at=t0 + timedelta(seconds=1))

    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            f"SELECT {_COLS} FROM alpaca_orders WHERE status='deferred' AND side='buy' "
            "AND (deferred_until IS NULL OR deferred_until <= NOW()) ORDER BY created_at ASC"
        ))).mappings().fetchall()
    assert [str(r["id"]) for r in rows] == [b1, b2]


# ── expiry UPDATE ─────────────────────────────────────────────────────────────

async def test_expire_update_only_touches_deferred(engine):
    """The expire UPDATE flips a deferred buy to 'expired' and must NOT touch a
    submitted order with the same id guard."""
    async with engine.begin() as conn:
        deferred = await _insert_order(conn, ticker="AAPL", side="buy", action="entry",
                                       status="deferred")
        submitted = await _insert_order(conn, ticker="MSFT", side="buy", action="entry",
                                        status="submitted")

    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE alpaca_orders SET status='expired', "
            "error_message='unfunded at session close' WHERE id=:id AND status='deferred'"
        ), {"id": deferred})
        # same statement against the submitted order must be a no-op (status guard)
        await conn.execute(text(
            "UPDATE alpaca_orders SET status='expired' WHERE id=:id AND status='deferred'"
        ), {"id": submitted})

    async with engine.connect() as conn:
        statuses = dict((await conn.execute(text(
            "SELECT id, status FROM alpaca_orders"
        ))).fetchall())
    assert statuses[uuid.UUID(deferred)] == "expired"
    assert statuses[uuid.UUID(submitted)] == "submitted"   # guard held


# ── api approval idempotency now includes 'deferred' ──────────────────────────

async def test_approval_idempotency_detects_queued_order(engine):
    """A re-approval must see an already-queued (deferred) order as open, so it is
    not enqueued twice (api/app/main.py approve idempotency check)."""
    # alpaca_orders.intent_id has an FK to delta_intents (fk_alpaca_orders_intent),
    # so seed the delta_runs → delta_intents parents first.
    run_id, iid = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO delta_runs (run_id, strategy_id, run_date) "
            "VALUES (:rid, 'test', CURRENT_DATE)"
        ), {"rid": run_id})
        await conn.execute(text(
            "INSERT INTO delta_intents (id, run_id, ticker, action) "
            "VALUES (:iid, :rid, 'AAPL', 'entry')"
        ), {"iid": iid, "rid": run_id})
        await _insert_order(conn, ticker="AAPL", side="buy", action="entry",
                            status="deferred", intent_id=iid)
    async with engine.connect() as conn:
        existing = (await conn.execute(text(
            "SELECT id, status FROM alpaca_orders "
            "WHERE intent_id = :iid AND status IN "
            "('pending','submitted','deferred','risk_rejected') LIMIT 1"
        ), {"iid": iid})).mappings().first()
    assert existing is not None
    assert existing["status"] == "deferred"
