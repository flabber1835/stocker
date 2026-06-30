"""Durable approval queue (enqueue + single-consumer worker) against a real,
migrated Postgres.

Proves, on the production schema:
  - _enqueue_one marks delta_intents.approved_at and is idempotent (a pre-existing
    OPEN order → 'duplicate', no re-mark).
  - _select_approved_pending (the worker's hot scan) returns exactly the right
    intents: approved + unprocessed + LATEST delta run + no open order — and excludes
    the superseded run, the already-processed, the not-approved, and the in-flight.

The pure routing/sizing is covered elsewhere; this tier runs the EXACT SQL the
trade-executor approval worker executes, so a column typo / mis-scoped predicate
fails in CI rather than wedging approvals in production.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Load the trade-executor's app.main (clear any other service's cached `app`).
for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
sys.path.insert(0, os.path.join(_ROOT, "shared"))
sys.path.insert(0, os.path.join(_ROOT, "services", "trade-executor"))
import app.main as te  # noqa: E402

pytestmark = pytest.mark.asyncio

OLD = date(2026, 6, 28)
NEW = date(2026, 6, 29)


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        await conn.execute(text("TRUNCATE alpaca_orders RESTART IDENTITY CASCADE"))
        await conn.execute(text("TRUNCATE delta_intents RESTART IDENTITY CASCADE"))
        await conn.execute(text("TRUNCATE delta_runs RESTART IDENTITY CASCADE"))
    yield eng
    await eng.dispose()


async def _run(conn, run_date) -> str:
    rid = str(uuid.uuid4())
    await conn.execute(text(
        "INSERT INTO delta_runs (run_id, strategy_id, status, run_date) "
        "VALUES (CAST(:r AS uuid), 't', 'success', :d)"
    ), {"r": rid, "d": run_date})
    return rid


async def _intent(conn, run_id, ticker, action="entry") -> str:
    iid = str(uuid.uuid4())
    await conn.execute(text(
        "INSERT INTO delta_intents (id, run_id, ticker, action) "
        "VALUES (CAST(:i AS uuid), CAST(:r AS uuid), :t, :a)"
    ), {"i": iid, "r": run_id, "t": ticker, "a": action})
    return iid


async def _open_order(conn, intent_id, ticker, status="pending"):
    await conn.execute(text(
        "INSERT INTO alpaca_orders (id, intent_id, ticker, action, side, status) "
        "VALUES (gen_random_uuid(), CAST(:i AS uuid), :t, 'entry', 'buy', :s)"
    ), {"i": intent_id, "t": ticker, "s": status})


async def test_enqueue_marks_and_is_idempotent(engine):
    async with engine.begin() as conn:
        rid = await _run(conn, NEW)
        iid = await _intent(conn, rid, "AAA")

    # First enqueue → queued, approved_at set.
    async with engine.begin() as conn:
        res = await te._enqueue_one(conn, iid, "immediate")
    assert res.status == "queued"
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT approved_at, approval_mode, approval_processed_at "
            "FROM delta_intents WHERE id = CAST(:i AS uuid)"
        ), {"i": iid})).mappings().first()
    assert row["approved_at"] is not None
    assert row["approval_mode"] == "immediate"
    assert row["approval_processed_at"] is None

    # A pre-existing OPEN order makes a re-enqueue a no-op duplicate.
    async with engine.begin() as conn:
        await _open_order(conn, iid, "AAA", status="pending")
        res2 = await te._enqueue_one(conn, iid, "immediate")
    assert res2.status == "duplicate"

    # Unknown intent → not_found; bad uuid → invalid.
    async with engine.begin() as conn:
        assert (await te._enqueue_one(conn, str(uuid.uuid4()), "immediate")).status == "not_found"
        assert (await te._enqueue_one(conn, "not-a-uuid", "immediate")).status == "invalid"


async def test_select_approved_pending_scoping(engine):
    async with engine.begin() as conn:
        old = await _run(conn, OLD)
        new = await _run(conn, NEW)
        # latest run, approved, unprocessed, no order → SHOULD be selected
        want = await _intent(conn, new, "WANT")
        # latest run, NOT approved → excluded
        await _intent(conn, new, "NOPE")
        # latest run, approved but already has an OPEN order → excluded (idempotency)
        held = await _intent(conn, new, "HELD")
        # latest run, approved but already processed → excluded
        done = await _intent(conn, new, "DONE")
        # OLD (superseded) run, approved → excluded (latest-run guard)
        stale = await _intent(conn, old, "STALE")

        for iid in (want, held, done, stale):
            await te._enqueue_one(conn, iid, "immediate")
        await _open_order(conn, held, "HELD", status="deferred")
        await conn.execute(text(
            "UPDATE delta_intents SET approval_processed_at = NOW() "
            "WHERE id = CAST(:i AS uuid)"
        ), {"i": done})

    async with engine.connect() as conn:
        rows = await te._select_approved_pending(conn, 100)
    selected = {str(r["id"]) for r in rows}
    assert selected == {want}, f"expected only WANT, got {selected}"

    # A DEAD order does NOT block re-selection (retry semantics): a failed order +
    # a fresh re-approval makes the intent eligible again.
    async with engine.begin() as conn:
        await _open_order(conn, want, "WANT", status="failed")  # dead, not open
        await te._enqueue_one(conn, want, "immediate")          # re-approve
    async with engine.connect() as conn:
        rows = await te._select_approved_pending(conn, 100)
    assert str(want) in {str(r["id"]) for r in rows}
