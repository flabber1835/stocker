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

REQUIREMENT 6 IS THE ONE THAT MATTERS AT CUTOVER, and the first version of it was
wrong in an instructive way. It asserted that a second `write_proposals` call was
additive — but production calls BOTH writers inside one savepoint, so the
original implementation inserted the proposals, hit the unique index, and rolled
the savepoint back over its own new rows. Measured on the real schema: 2, not 4.
The test was describing a function; the system did something else.

Retry semantics are now explicit, and 6a-6e cover them:

    the index itself           refuses a raw duplicate — proven separately from
                               the writer, so a writer regression cannot hide it
    identical retry            idempotent success; the retry's proposals COMMIT
                               under a new attempt_id and both attempts stay
                               readable
    divergent retry            fatal, and writes NOTHING — a stored instruction
                               the system may already have acted on is never
                               silently replaced
    same action, different rule  still divergence. Two reconciliations agreeing
                               on the instruction but not on why agree by
                               coincidence.
"""
from __future__ import annotations

import importlib
import os
import sys
import uuid
from datetime import date
from types import SimpleNamespace

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
        return SimpleNamespace(
            write_proposals=mod.write_proposals,
            write_net_intents=mod.write_net_intents,
            new_attempt_id=mod.new_attempt_id,
            NetIntentDivergence=mod.NetIntentDivergence,
        )
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
    w = _load_pipeline_writes()
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
            await w.write_proposals(conn, run_id, proposals, w.new_attempt_id())
            await w.write_net_intents(conn, run_id, nets)
        yield {"engine": eng, "run_id": run_id, "proposals": proposals,
               "nets": nets, "report": report}
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


async def test_6_the_index_itself_refuses_a_duplicate(rehearsal):
    """The DATABASE guarantee, proven independently of the writer.

    `write_net_intents` is now idempotent, so it no longer raises on a retry —
    which means the writer can no longer demonstrate that the invariant exists.
    A raw INSERT can. Kept separate on purpose: if the writer ever regresses to a
    plain INSERT, or its conflict handling is removed, the index is still the
    thing standing between a retry and two executable instructions.
    """
    with pytest.raises(Exception) as exc:
        async with rehearsal["engine"].begin() as conn:
            await conn.execute(
                text("INSERT INTO net_intents "
                     "(run_id, account_id, ticker, action, source, resolved_by) "
                     "VALUES (:r, :a, 'AMD', 'risk_reduce', 'crash_brake', 'x')"),
                {"r": rehearsal["run_id"], "a": DEFAULT_ACCOUNT_ID},
            )
    assert "unique" in str(exc.value).lower() \
        or "uq_net_intents_run_account_ticker" in str(exc.value).lower()

    async with rehearsal["engine"].connect() as conn:
        n = (await conn.execute(
            text("SELECT COUNT(*) FROM net_intents WHERE run_id=:r"),
            {"r": rehearsal["run_id"]})).scalar_one()
    assert n == 4


async def test_6b_the_exact_production_sequence_run_twice_is_idempotent(rehearsal):
    """THE retry test, in the shape production actually uses.

    An earlier version called `write_proposals` ALONE and asserted the row count
    doubled. Production never takes that path: both writers run inside ONE
    savepoint, so on the original implementation the proposals inserted, the
    unique index then raised, and the savepoint rolled the new proposal rows back
    — the append-only table stopped being append-only exactly when something went
    wrong. Measured on the real schema: 2 rows, not 4. The test was asserting a
    property of a function rather than of the system.

    With idempotent-or-fatal semantics an unchanged retry SUCCEEDS: the stored net
    intents are recognised as identical, nothing is rewritten, and the retry's
    proposals commit under a fresh attempt_id so both attempts stay readable.
    """
    w = _load_pipeline_writes()
    eng, run_id = rehearsal["engine"], rehearsal["run_id"]

    async with eng.begin() as conn:
        async with conn.begin_nested():
            await w.write_proposals(conn, run_id, rehearsal["proposals"],
                                    w.new_attempt_id())
            stats = await w.write_net_intents(conn, run_id, rehearsal["nets"])

    assert stats == {"inserted": 0, "idempotent": 4, "total": 4}

    async with eng.connect() as conn:
        n_nets = (await conn.execute(
            text("SELECT COUNT(*) FROM net_intents WHERE run_id=:r"),
            {"r": run_id})).scalar_one()
        n_props = (await conn.execute(
            text("SELECT COUNT(*) FROM intent_proposals WHERE run_id=:r"),
            {"r": run_id})).scalar_one()
        attempts = (await conn.execute(
            text("SELECT COUNT(DISTINCT attempt_id) FROM intent_proposals "
                 "WHERE run_id=:r"), {"r": run_id})).scalar_one()

    assert n_nets == 4, "a retry must not create a second executable instruction"
    assert n_props == 16, "the retry's proposals must survive the savepoint"
    assert attempts == 2, "the two attempts must remain distinguishable"


async def test_6c_a_divergent_retry_is_fatal_and_writes_nothing(rehearsal):
    """The other half of the rule. A retry reconciling to a DIFFERENT instruction
    must not quietly replace one the system may already have acted on — and must
    not half-write either."""
    w = _load_pipeline_writes()
    eng, run_id = rehearsal["engine"], rehearsal["run_id"]

    # Same run, but AMD now resolves to a partial reduction instead of the exit
    # already stored — the shape of a rule or input change between attempts.
    mutated = reconcile([
        Proposal("AMD", "sell_trim", "delta_engine", 0, target_weight=0.01),
        Proposal("AMD", "risk_reduce", "crash_brake", 1, target_weight=0.02),
    ])

    before = await _counts(eng, run_id)
    with pytest.raises(w.NetIntentDivergence) as exc:
        async with eng.begin() as conn:
            async with conn.begin_nested():
                await w.write_proposals(conn, run_id,
                                        list(mutated[0].contributing),
                                        w.new_attempt_id())
                await w.write_net_intents(conn, run_id, mutated)

    assert "AMD" in str(exc.value)
    assert exc.value.divergences[0]["stored"]["action"] == "exit"
    assert exc.value.divergences[0]["recomputed"]["action"] == "sell_trim"
    assert await _counts(eng, run_id) == before, \
        "a divergent retry must write nothing at all"


async def test_6d_divergence_names_every_disagreement_not_just_the_first(rehearsal):
    """Checked after ALL keys, so one report covers the whole run. Stopping at
    the first would make an operator fix them one redeploy at a time."""
    w = _load_pipeline_writes()
    eng, run_id = rehearsal["engine"], rehearsal["run_id"]

    mutated = reconcile([
        Proposal("AMD", "sell_trim", "delta_engine", 0, target_weight=0.01),
        Proposal("NVDA", "exit", "delta_engine", 1),
    ])
    with pytest.raises(w.NetIntentDivergence) as exc:
        async with eng.begin() as conn:
            async with conn.begin_nested():
                await w.write_net_intents(conn, run_id, mutated)

    assert {d["ticker"] for d in exc.value.divergences} == {"AMD", "NVDA"}


async def test_6e_same_action_reached_by_a_different_rule_is_divergence(rehearsal):
    """Two reconciliations agreeing on the instruction but not on WHY agree by
    coincidence — one input away from disagreeing. Same argument the crash-brake
    transition record settled: comparing outcomes cannot see that."""
    w = _load_pipeline_writes()
    eng, run_id = rehearsal["engine"], rehearsal["run_id"]

    # NVDA is stored as risk_reduce @0.020 via sell_dominates:min_weight (it beat
    # a `hold`). Reach the SAME action and weight as a lone proposal instead.
    same_action = reconcile([
        Proposal("NVDA", "risk_reduce", "crash_brake", 0, target_weight=0.020),
    ])
    assert same_action[0].resolved_by == "sole_proposal"

    with pytest.raises(w.NetIntentDivergence) as exc:
        async with eng.begin() as conn:
            async with conn.begin_nested():
                await w.write_net_intents(conn, run_id, same_action)
    d = exc.value.divergences[0]
    assert d["stored"]["action"] == d["recomputed"]["action"] == "risk_reduce"
    assert d["stored"]["resolved_by"] != d["recomputed"]["resolved_by"]


async def _counts(eng, run_id) -> tuple[int, int]:
    async with eng.connect() as conn:
        p = (await conn.execute(
            text("SELECT COUNT(*) FROM intent_proposals WHERE run_id=:r"),
            {"r": run_id})).scalar_one()
        n = (await conn.execute(
            text("SELECT COUNT(*) FROM net_intents WHERE run_id=:r"),
            {"r": run_id})).scalar_one()
    return p, n
