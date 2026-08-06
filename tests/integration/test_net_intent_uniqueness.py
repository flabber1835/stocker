"""The net-intent invariant, against a real migrated Postgres (defect 4).

Two claims are being tested, and only a real database can test either:

  1. `net_intents` REFUSES a second row for the same (run_id, account_id,
     ticker). A unique index that was never shown to reject anything is an
     assertion about a CREATE statement, not about the database.
  2. `delta_intents` STILL ACCEPTS duplicates. That is not an oversight being
     grandfathered — it is the design. Constraining `delta_intents` would turn
     conflicting logic into an insertion failure at the moment the crash brake
     first engages, and the operator would learn that two controls disagreed
     without learning what either wanted. If someone later "fixes" that table
     with a unique index, this test fails and points them at the reason.

The third test is the reason the split exists at all: the append-only proposals
table must keep BOTH sides of a conflict while the net table keeps one.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db(async_dsn: str):
    eng = create_async_engine(async_dsn, future=True)
    try:
        yield eng
    finally:
        await eng.dispose()


async def _make_run(conn) -> uuid.UUID:
    run_id = uuid.uuid4()
    await conn.execute(
        text("INSERT INTO delta_runs (run_id, run_date, status, strategy_id) "
             "VALUES (:rid, :rd, 'success', 'test_strategy')"),
        {"rid": run_id, "rd": date(2026, 8, 6)},
    )
    return run_id


async def _insert_net(conn, run_id, ticker="AMD", action="exit", account="default"):
    await conn.execute(
        text("INSERT INTO net_intents "
             "(run_id, account_id, ticker, action, source, resolved_by) "
             "VALUES (:rid, :acct, :t, :a, 'delta_engine', 'sole_proposal')"),
        {"rid": run_id, "acct": account, "t": ticker, "a": action},
    )


async def test_net_intents_rejects_a_second_intent_for_one_ticker(db):
    """The invariant, SHOWN TO FIRE. Without the unique index this passes
    silently and the table is decorative."""
    async with db.begin() as conn:
        run_id = await _make_run(conn)
        await _insert_net(conn, run_id, "AMD", "exit")

    with pytest.raises(Exception) as exc:
        async with db.begin() as conn:
            await _insert_net(conn, run_id, "AMD", "risk_reduce")
    assert "uq_net_intents_run_account_ticker" in str(exc.value).lower() \
        or "unique" in str(exc.value).lower()


async def test_the_same_ticker_in_two_accounts_is_allowed(db):
    """The key is per-account. A unique index on (run_id, ticker) alone would
    make a second book's instruction for the same name unstorable."""
    async with db.begin() as conn:
        run_id = await _make_run(conn)
        await _insert_net(conn, run_id, "AMD", "exit", account="paper")
        await _insert_net(conn, run_id, "AMD", "entry", account="live")

    async with db.connect() as conn:
        n = (await conn.execute(
            text("SELECT COUNT(*) FROM net_intents WHERE run_id=:r"),
            {"r": run_id})).scalar_one()
    assert n == 2


async def test_the_same_ticker_in_two_runs_is_allowed(db):
    async with db.begin() as conn:
        run_a = await _make_run(conn)
        run_b = await _make_run(conn)
        await _insert_net(conn, run_a, "AMD", "exit")
        await _insert_net(conn, run_b, "AMD", "exit")
    # No exception is the assertion; a key missing run_id would have raised.


async def test_delta_intents_still_accepts_duplicates_by_design(db):
    """Deliberate. See the module docstring — the fix is reconciliation on a new
    table, not an insertion failure on this one."""
    async with db.begin() as conn:
        run_id = await _make_run(conn)
        for action in ("exit", "risk_reduce"):
            await conn.execute(
                text("INSERT INTO delta_intents (run_id, ticker, action) "
                     "VALUES (:rid, 'AMD', :a)"),
                {"rid": run_id, "a": action},
            )

    async with db.connect() as conn:
        n = (await conn.execute(
            text("SELECT COUNT(*) FROM delta_intents WHERE run_id=:r AND ticker='AMD'"),
            {"r": run_id})).scalar_one()
    assert n == 2, "delta_intents must stay unconstrained — see the docstring"


async def test_proposals_keep_both_sides_of_a_conflict(db):
    """The append-only half of the design: the discarded proposal survives, so a
    reviewer can see that two controls disagreed and what the loser wanted."""
    attempt = uuid.uuid4()
    async with db.begin() as conn:
        run_id = await _make_run(conn)
        for seq, (src, action, w) in enumerate([
            ("delta_engine", "exit", None),
            ("crash_brake", "risk_reduce", 0.02),
        ]):
            await conn.execute(
                text("INSERT INTO intent_proposals "
                     "(run_id, attempt_id, ticker, source, action, seq, target_weight) "
                     "VALUES (:rid, :aid, 'AMD', :s, :a, :seq, :w)"),
                {"rid": run_id, "aid": attempt, "s": src, "a": action,
                 "seq": seq, "w": w},
            )
        await _insert_net(conn, run_id, "AMD", "exit")

    async with db.connect() as conn:
        proposals = (await conn.execute(
            text("SELECT source, action FROM intent_proposals "
                 "WHERE run_id=:r ORDER BY seq"), {"r": run_id})).all()
        nets = (await conn.execute(
            text("SELECT ticker, action FROM net_intents WHERE run_id=:r"),
            {"r": run_id})).all()

    assert [tuple(r) for r in proposals] == [
        ("delta_engine", "exit"), ("crash_brake", "risk_reduce")]
    assert [tuple(r) for r in nets] == [("AMD", "exit")]


async def test_the_pipelines_own_write_statements_run_against_the_real_schema(db):
    """The EXACT statements the delta step executes, on the real migrated schema.

    The shadow write is wrapped in a `try` that logs and continues, so a
    mistyped column would surface only as `intent reconciliation skipped (…)`
    in a log and the tables would stay empty while the feature looked deployed.
    This is the test that makes that impossible; it is why the SQL lives in
    `app.intent_writes` rather than inline.
    """
    import importlib
    import os
    import sys

    # Every service ships an `app` package, so importing the pipeline's leaves a
    # LOADED `app` in sys.modules that later tests in the same session resolve
    # against — which silently broke five unrelated integration tests the first
    # time this was written. Snapshot and restore rather than merely deleting.
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    saved = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, os.path.join(root, "services", "pipeline"))
    try:
        writes = importlib.import_module("app.intent_writes")
        write_proposals = writes.write_proposals
        write_net_intents = writes.write_net_intents
        new_attempt_id = writes.new_attempt_id
    finally:
        sys.path.pop(0)
        for k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
            del sys.modules[k]
        sys.modules.update(saved)

    from stock_strategy_shared.intent_reconciliation import Proposal, reconcile

    proposals = [
        Proposal("AMD", "exit", "delta_engine", 0, reason="dropped from target"),
        Proposal("AMD", "risk_reduce", "crash_brake", 1, target_weight=0.02,
                 actual_weight=0.041, weight_drift=-0.021,
                 reason="crash brake ENGAGED: exposure 100% -> 50%"),
        Proposal("NVDA", "hold", "delta_engine", 2, target_weight=0.04,
                 rank=3, composite_score=1.2345678, confirmation_days_met=2),
    ]
    nets = reconcile(proposals)

    async with db.begin() as conn:
        run_id = await _make_run(conn)
        assert await write_proposals(conn, run_id, proposals,
                                     new_attempt_id()) == 3
        assert await write_net_intents(conn, run_id, nets) == {
            "inserted": 2, "idempotent": 0, "total": 2}

    async with db.connect() as conn:
        rows = (await conn.execute(
            text("SELECT ticker, action, resolved_by, conflicted, "
                 "       contributing->'contributing'->0->>'source' AS first_src "
                 "FROM net_intents WHERE run_id=:r ORDER BY ticker"),
            {"r": run_id})).mappings().all()

    amd, nvda = rows
    assert (amd["ticker"], amd["action"]) == ("AMD", "exit")
    assert amd["resolved_by"] == "sell_dominates:exit"
    assert amd["conflicted"] is True
    assert amd["first_src"] == "delta_engine"      # provenance survived the JSONB cast
    assert nvda["conflicted"] is False
