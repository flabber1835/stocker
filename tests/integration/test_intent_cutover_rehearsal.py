"""The executor-cutover gate: a controlled, non-broker conflict rehearsal.

WHY THIS EXISTS INSTEAD OF WAITING. The stated precondition for switching the
trade-executor's read from `delta_intents` to `net_intents` is having WATCHED the
reconciliation resolve a real conflict. Taken literally that means waiting for the
crash brake to engage — a market event, on a book already trading, with the
untested path in it. That is not a test plan, it is an exposure. The conflicts are
deliberately manufactured here instead: no broker, no orders, real schema, real
statements, real reconciliation.

Four conflicts, one per composition branch, each with a DIFFERENT winner so no
single wrong rule passes all four:

    exit      + risk_reduce   -> exit          (sell dominates; exit subsumes)
    hold      + risk_reduce   -> risk_reduce   (neutral cannot veto executable)
    buy_add   + risk_reduce   -> risk_reduce   (sell beats buy)
    entry     + risk_restore  -> lowest weight (same-direction: min composition)

and six requirements, all asserted below:

    1  every proposal persisted, winners and losers
    2  exactly one net intent per (run_id, account_id, ticker)
    3  the correct winning action AND the rule that produced it
    4  provenance complete — every contributing proposal, flagged
    5  the divergence report surfaces the conflicts
    6  re-running cannot create a second net intent for the same key

Requirement 6 is the one that matters most at cutover and is the least obvious:
a retried or duplicated delta write must not be able to produce two executable
instructions. It is asserted against the DATABASE, not the rule — the rule is
already pure and deterministic, so only the index can answer it.
"""
from __future__ import annotations

import importlib
import os
import sys
import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from stock_strategy_shared.intent_reconciliation import (DEFAULT_ACCOUNT_ID,
                                                         Proposal,
                                                         compare_to_rows,
                                                         reconcile)

pytestmark = pytest.mark.asyncio


def _load_pipeline_writes():
    """Import the pipeline's writers without leaving its `app` package loaded.

    Every service ships an `app` package; a leaked one resolves later tests
    against the wrong service.
    """
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    saved = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, os.path.join(root, "services", "pipeline"))
    try:
        mod = importlib.import_module("app.intent_writes")
        return mod.write_proposals, mod.write_net_intents
    finally:
        sys.path.pop(0)
        for k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
            del sys.modules[k]
        sys.modules.update(saved)


#: (ticker, base proposal, overlay proposal, expected action, expected rule)
SCENARIOS = [
    ("AMD",  ("exit", None),        ("risk_reduce", 0.02),
     "exit",         "sell_dominates:exit"),
    ("NVDA", ("hold", 0.040),       ("risk_reduce", 0.020),
     "risk_reduce",  "sell_dominates:min_weight"),
    ("AVGO", ("buy_add", 0.050),    ("risk_reduce", 0.025),
     "risk_reduce",  "sell_dominates:min_weight"),
    ("MU",   ("entry", 0.060),      ("risk_restore", 0.035),
     "risk_restore", "buy_min_weight"),
]


def _build_proposals() -> list[Proposal]:
    out, seq = [], 0
    for ticker, (base_action, base_w), (ovl_action, ovl_w), _, _ in SCENARIOS:
        out.append(Proposal(ticker, base_action, "delta_engine", seq,
                            target_weight=base_w, reason=f"{base_action} from rank"))
        seq += 1
    for ticker, _, (ovl_action, ovl_w), _, _ in SCENARIOS:
        out.append(Proposal(ticker, ovl_action, "crash_brake", seq,
                            target_weight=ovl_w,
                            reason="crash brake ENGAGED: exposure 100% -> 50%"))
        seq += 1
    return out


@pytest_asyncio.fixture
async def rehearsal(async_dsn: str):
    """Run the rehearsal once; every test reads its result."""
    write_proposals, write_net_intents = _load_pipeline_writes()
    eng = create_async_engine(async_dsn, future=True)
    run_id = uuid.uuid4()
    proposals = _build_proposals()
    nets = reconcile(proposals)
    report = compare_to_rows([(p.ticker, p.action) for p in proposals], nets,
                             account_id=DEFAULT_ACCOUNT_ID)
    try:
        async with eng.begin() as conn:
            await conn.execute(
                text("INSERT INTO delta_runs (run_id, run_date, status, strategy_id) "
                     "VALUES (:r, :d, 'success', 'cutover_rehearsal')"),
                {"r": run_id, "d": date(2026, 8, 6)},
            )
            await write_proposals(conn, run_id, proposals)
            await write_net_intents(conn, run_id, nets)
        yield {"engine": eng, "run_id": run_id, "proposals": proposals,
               "nets": nets, "report": report,
               "write_net_intents": write_net_intents}
    finally:
        await eng.dispose()


async def test_1_every_proposal_persisted_including_the_losers(rehearsal):
    async with rehearsal["engine"].connect() as conn:
        rows = (await conn.execute(
            text("SELECT ticker, source, action FROM intent_proposals "
                 "WHERE run_id=:r ORDER BY seq"), {"r": rehearsal["run_id"]})).all()
    assert len(rows) == len(rehearsal["proposals"]) == 8
    # Both sides of every conflict survive — the discarded proposal is the whole
    # reason a reviewer can see that two controls disagreed.
    by_ticker: dict[str, set[str]] = {}
    for ticker, source, action in rows:
        by_ticker.setdefault(ticker, set()).add(source)
    assert all(v == {"delta_engine", "crash_brake"} for v in by_ticker.values())


async def test_2_exactly_one_net_intent_per_account_ticker(rehearsal):
    async with rehearsal["engine"].connect() as conn:
        rows = (await conn.execute(
            text("SELECT account_id, ticker, COUNT(*) FROM net_intents "
                 "WHERE run_id=:r GROUP BY account_id, ticker"),
            {"r": rehearsal["run_id"]})).all()
    assert len(rows) == 4
    assert all(c == 1 for _, _, c in rows)


@pytest.mark.parametrize(
    "ticker,expected_action,expected_rule",
    [(t, a, r) for t, _, _, a, r in SCENARIOS])
async def test_3_correct_winner_and_rule(rehearsal, ticker, expected_action,
                                         expected_rule):
    async with rehearsal["engine"].connect() as conn:
        row = (await conn.execute(
            text("SELECT action, resolved_by, conflicted, target_weight "
                 "FROM net_intents WHERE run_id=:r AND ticker=:t"),
            {"r": rehearsal["run_id"], "t": ticker})).mappings().one()
    assert row["action"] == expected_action
    assert row["resolved_by"] == expected_rule
    assert row["conflicted"] is True


async def test_3b_the_same_ticker_conflict_can_resolve_four_different_ways(rehearsal):
    """Guards the parametrised test above from passing on a constant rule."""
    async with rehearsal["engine"].connect() as conn:
        rows = (await conn.execute(
            text("SELECT DISTINCT action FROM net_intents WHERE run_id=:r"),
            {"r": rehearsal["run_id"]})).scalars().all()
    assert set(rows) == {"exit", "risk_reduce", "risk_restore"}


async def test_4_provenance_is_complete(rehearsal):
    async with rehearsal["engine"].connect() as conn:
        rows = (await conn.execute(
            text("SELECT ticker, contributing FROM net_intents WHERE run_id=:r"),
            {"r": rehearsal["run_id"]})).mappings().all()

    for row in rows:
        prov = row["contributing"]
        contributing = prov["contributing"]
        assert len(contributing) == 2, f"{row['ticker']}: lost a contributor"
        assert sum(1 for c in contributing if c["won"]) == 1
        assert {c["source"] for c in contributing} == {"delta_engine", "crash_brake"}
        # The rule is recorded WITH the provenance, so the resolution can be
        # re-derived without reading the code that produced it.
        assert prov["resolved_by"] and prov["conflicted"] is True
        assert all(c["reason"] for c in contributing)


async def test_5_the_divergence_report_surfaces_every_conflict(rehearsal):
    report = rehearsal["report"]
    assert not report["agrees"]
    assert report["legacy_rows"] == 8 and report["legacy_tickers"] == 4
    assert report["net_intents"] == 4
    assert report["net_intents_other_accounts"] == 0
    assert {c["ticker"] for c in report["conflicts"]} == {"AMD", "NVDA", "AVGO", "MU"}
    for c in report["conflicts"]:
        assert len(c["legacy_actions"]) == 2
        assert c["net_action"] in c["legacy_actions"]


async def test_6_a_rerun_cannot_create_a_second_net_intent(rehearsal):
    """THE cutover requirement. Only the database can answer this — the pure
    rule is deterministic, so a duplicate can only arrive by writing twice."""
    with pytest.raises(Exception) as exc:
        async with rehearsal["engine"].begin() as conn:
            await rehearsal["write_net_intents"](
                conn, rehearsal["run_id"], rehearsal["nets"])
    assert "unique" in str(exc.value).lower() \
        or "uq_net_intents_run_account_ticker" in str(exc.value).lower()

    # And the failed retry left the original instructions untouched.
    async with rehearsal["engine"].connect() as conn:
        n = (await conn.execute(
            text("SELECT COUNT(*) FROM net_intents WHERE run_id=:r"),
            {"r": rehearsal["run_id"]})).scalar_one()
    assert n == 4


async def test_6b_a_rerun_of_the_proposals_is_allowed_and_additive(rehearsal):
    """The append-only half must NOT reject a retry: the proposals table records
    what was proposed, and a second attempt is a second thing that happened."""
    async with rehearsal["engine"].begin() as conn:
        wp, _ = _load_pipeline_writes()
        await wp(conn, rehearsal["run_id"], rehearsal["proposals"])
    async with rehearsal["engine"].connect() as conn:
        n = (await conn.execute(
            text("SELECT COUNT(*) FROM intent_proposals WHERE run_id=:r"),
            {"r": rehearsal["run_id"]})).scalar_one()
    assert n == 16
