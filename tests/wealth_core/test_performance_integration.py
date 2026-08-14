"""Performance measurement against the golden scenario, and the hash guarantee.

`test_performance.py` pins the arithmetic. This file pins the three properties
that only show up once the module is WIRED IN:

  1. measuring changes no certified hash — a reading must not re-pin the anchor;
  2. the chain rehearsal and the bulk replay measure to the same numbers;
  3. eliding the per-session detail does not remove the measurement, which is
     the defect that made a three-year rehearsal unmeasurable in the first place.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from stock_strategy_shared.wealth_core.golden import STARTING_CASH, golden_scenario
from stock_strategy_shared.wealth_core.performance import (measure,
                                                           measure_run_result,
                                                           SessionFacts)
from stock_strategy_shared.wealth_core.run import run_sessions

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "golden_wealth_core_v1.json"


def _run():
    sc = golden_scenario()
    return run_sessions(sessions=sc.sessions, bars_by_session=sc.bars_by_session,
                        meta=sc.meta, starting_cash=STARTING_CASH,
                        terminal_events=sc.terminal_events)


# ── 1. the hash guarantee ────────────────────────────────────────────────────

@pytest.mark.xfail(
    strict=True,
    reason="intentional golden result-hash drift; one authorized re-pin pending",
)
def test_measuring_does_not_move_the_pinned_result_hash():
    """THE non-negotiable. Performance is DERIVED output; if computing it could
    change `result_hash` the certification anchor would be re-pinned by a change
    with no economic content."""
    pinned = json.loads(FIXTURE.read_text())["result_hash"]

    run = _run()
    before = run.result_hash()
    assert before == pinned, "fixture drift — unrelated to this change"

    measure_run_result(run, STARTING_CASH)

    assert run.result_hash() == pinned
    assert run.result_hash() == before


def test_performance_is_absent_from_the_hashed_serialisation():
    """A stronger form of the same claim: the key must not exist in `to_dict`,
    which is what the hash is taken over. An equal hash today could otherwise be
    a coincidence of ordering."""
    run = _run()
    measure_run_result(run, STARTING_CASH)
    assert "performance" not in run.to_dict()


def test_state_and_ledger_hashes_are_unmoved_by_measuring():
    run = _run()
    state_before = run.state.state_hash()
    ledger_before = run.ledger.ledger_hash()
    measure_run_result(run, STARTING_CASH)
    assert run.state.state_hash() == state_before
    assert run.ledger.ledger_hash() == ledger_before


# ── 2. the golden run is measurable, and its numbers are sane ────────────────

def test_the_golden_run_is_strictly_unevaluable_because_it_blocks():
    """The golden scenario BLOCKS 9 of its 260 sessions — a designed state that
    leaves those sessions with no valuation. Under the strict rule that makes the
    run unevaluable, and the reason must say BLOCKED so an operator does not
    diagnose corruption.

    WAS 19 before C1's grace period (2026-08-08). The ten sessions from
    SEC_STRANDED's terms-less announcement to its resolution are now CARRIED at a
    trustworthy mark rather than blocked, so they have a valuation and no longer
    make the run unevaluable. The remaining 9 come from securities flagged
    `unresolved_corporate_action` on the vendor bar, which have no mark at all —
    the case where refusing is still the only honest answer."""
    p = measure_run_result(_run(), STARTING_CASH)
    assert not p.evaluable
    assert "BLOCKED" in p.unevaluable_reason
    assert "allow_blocked_gaps" in p.unevaluable_reason
    assert p.blocked_session_count == 9


def test_an_unexplained_gap_is_never_tolerated_even_with_the_opt_in():
    """`allow_blocked_gaps` relaxes the BLOCKED case only. A session with no
    valuation and no explanation is the corruption case and stays fatal."""
    p = measure(starting_cash=1000.0, sessions=[
        SessionFacts("2021-01-01", 1000.0),
        SessionFacts("2021-06-01", None, blocked=False),
        SessionFacts("2022-01-01", 1200.0),
    ], allow_blocked_gaps=True)
    assert not p.evaluable
    assert "not blocked" in p.unevaluable_reason


def test_the_golden_run_measures():
    run = _run()
    p = measure_run_result(run, STARTING_CASH, allow_blocked_gaps=True)

    assert p.evaluable, p.unevaluable_reason
    # The drawdown is a FLOOR: the blocked days could hide a deeper trough, and
    # anything quoting it must carry that.
    assert p.maximum_drawdown_is_lower_bound is True
    assert len(p.excluded_blocked_sessions) == 9
    assert p.session_count == len(run.sessions)
    assert p.starting_equity == pytest.approx(STARTING_CASH)
    assert p.ending_equity is not None
    assert p.maximum_drawdown is not None and 0.0 <= p.maximum_drawdown <= 1.0
    # The golden sessions are synthetic labels, so the two calendar-scaled
    # figures are unavailable BY DESIGN and say so rather than being wrong.
    assert p.cagr is None and "calendar dates" in p.cagr_unavailable_reason
    assert p.annualized_turnover is None


def test_the_golden_run_traded_and_the_turnover_reflects_it():
    run = _run()
    p = measure_run_result(run, STARTING_CASH, allow_blocked_gaps=True)
    n_fills = sum(len(s.fills or ()) for s in run.sessions)
    assert n_fills > 0, "a scenario with no fills cannot exercise turnover"
    assert p.trade_count == n_fills
    assert p.gross_traded_notional > 0.0
    assert p.gross_turnover > 0.0


# ── 3. chain and bulk agree; elision does not remove the measurement ─────────

def test_the_equity_series_alone_reproduces_the_return_metrics():
    """What the chain rehearsal computes from its OWN resolved-equity series
    must match the bulk run's, or the two paths disagree about the money even
    while their state and ledger hashes match — which the hashes cannot see.
    """
    run = _run()
    bulk = measure_run_result(run, STARTING_CASH, allow_blocked_gaps=True)

    # The chain's view: the same valuations and blocked flags, no fills.
    chain = measure(starting_cash=STARTING_CASH, sessions=[
        SessionFacts(session=s.session, resolved_equity=s.resolved_equity,
                     blocked=s.blocked)
        for s in run.sessions], allow_blocked_gaps=True)

    assert chain.evaluable == bulk.evaluable
    assert chain.ending_equity == pytest.approx(bulk.ending_equity)
    assert chain.total_return == pytest.approx(bulk.total_return)
    assert chain.maximum_drawdown == pytest.approx(bulk.maximum_drawdown)
    assert chain.max_drawdown_trough_date == bulk.max_drawdown_trough_date
    # …and it honestly reports no turnover rather than a misleading zero-ish one.
    assert chain.trade_count == 0 and bulk.trade_count > 0


def test_elision_of_session_detail_does_not_remove_performance():
    """The exact shape the API applies. `performance` is a SIBLING of
    `sessions`, so the >400-session elision cannot reach it — the property that
    makes a three-year rehearsal measurable at all."""
    run = _run()
    summary = {
        "sessions": [{"session": s.session} for s in run.sessions],
        "performance": measure_run_result(
            run, STARTING_CASH, allow_blocked_gaps=True).to_dict(),
    }
    # Simulate the API's elision at a threshold this fixture will cross.
    if len(summary["sessions"]) > 1:
        summary["sessions"] = f"{len(summary['sessions'])} sessions elided"

    assert isinstance(summary["sessions"], str)
    assert summary["performance"]["evaluable"] is True
    assert summary["performance"]["ending_equity"] is not None
    assert summary["performance"]["maximum_drawdown"] is not None
    json.dumps(summary)   # must survive the summary JSONB round trip
