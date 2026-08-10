"""A valuation must not depend on WHERE THE RUN STOPPED.

THE CONTRADICTION, reproduced 2026-08-09 before anything changed. A holding in
an active C1 grace, with a trustworthy carried mark:

    during the session    resolved_equity 10,950.00   blocked False
    final report          marked_equity   None        "unmarkable"

Same holding, same state, one line apart. `Mark.resolves_equity` includes
PENDING_TERMS_CARRIED — the waterfall has already checked that mark against the
recency bound — but `final_report` tested `status is CURRENT`, so ending the run
on such a session made the position economically invisible.

THE DISTINCTION THE FIX RESTORES, and it is a real one rather than a relaxation:

    marked_equity              may use CURRENT or PENDING_TERMS_CARRIED
    forced_liquidation_equity  requires an EXECUTABLE price, and may legitimately
                               remain unresolved

A carried valuation is not a fill price: no print happened, so there is nothing
to trade against. The book is worth something AND part of it cannot be sold
today at any price anyone has quoted. Those are both true, and collapsing them
in either direction loses information — the old code lost the valuation, and the
lazy fix would have turned a carried mark into an executable one.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.adapter import (
    build_marks, step_session, tradeability_only_bars)
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.marks import MarkStatus
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.settlement import empty_counters
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import (
    TerminalKind, TerminalTerms, final_report)

CFG = WealthCoreConfig()
SID, VER = "stocker_wealth_core_v1", 1


def seated(cash=10_000.0, shares=10, entry=100.0):
    st = PortfolioState.fresh(cash)
    st.slots[0].occupied_by = "S1"
    st.episodes[0] = HoldingEpisode("S1", "T1", "I1", 0, "d0", "d0",
                                    entry, entry, shares, shares, entry)
    st.initialized = True
    st.last_valid_mark_session["S1"] = "d0"
    return st


def bar(session="d1", close=95.0):
    return DailyBar(security_id="S1", ticker="T1", issuer_id="I1",
                    session=session, signal_close_split_adj_div_unadj=close,
                    raw_open=close, raw_mark_close=close, tradeable=True,
                    split_ratio=1.0, dividend_per_share=0.0,
                    unresolved_corporate_action=False)


def carry(bars=()):
    """Put the holding into an active C1 grace and stop the run there."""
    st, led = seated(), Ledger()
    lk, c = {"S1": 95.0}, empty_counters()
    res = step_session(
        session="d1", state=st, bars=list(bars), pending=[], ledger=led,
        last_known=lk, cfg=CFG, strategy_id=SID, strategy_version=VER,
        security_bars=tradeability_only_bars(list(bars), None),
        terminal_terms=[TerminalTerms(session="d1", security_id="S1",
                                      kind=TerminalKind.CASH_MERGER,
                                      reference="test/pending")],
        settlement_counters=c)
    marks = build_marks(list(bars), st.held_security_ids(), lk,
                        st.unresolved_terminals, st.terminal_pending_sessions)
    rep = final_report(session="d1", state=st, marks=marks, ledger=led, cfg=CFG)
    return st, res, marks, rep


# ── 1. the falsifier ─────────────────────────────────────────────────────────

class TestEndingMidGraceKeepsTheValuation:

    def test_the_mark_really_is_CARRIED(self):
        """Without this the rest could pass on a mark that was CURRENT all
        along, proving nothing about the carried path."""
        _, _, marks, _ = carry()
        assert marks["S1"].status is MarkStatus.PENDING_TERMS_CARRIED

    def test_marked_equity_MATCHES_the_session_before_it(self):
        _, res, _, rep = carry()
        assert res.resolved_equity is not None and not res.blocked
        assert rep.marked_equity == pytest.approx(res.resolved_equity), (
            "the same holding resolved equity during the session and became "
            "unmarkable at the report — a valuation that depends on where the "
            "run stopped is not a valuation")

    def test_the_position_is_NOT_listed_unmarkable(self):
        _, _, _, rep = carry()
        assert [p["security_id"] for p in rep.unmarkable_positions] == []
        assert [p["security_id"] for p in rep.marked_positions] == ["S1"]

    def test_the_report_says_WHICH_basis_each_position_was_valued_on(self):
        """A carried valuation and a live one are different facts, and a total
        that does not distinguish them cannot be audited."""
        _, _, _, rep = carry()
        assert rep.marked_positions[0]["mark_status"] == "PENDING_TERMS_CARRIED"


# ── 2. and does NOT make it sellable ─────────────────────────────────────────

class TestACarriedMarkIsNotAnExecutablePrice:

    def test_forced_liquidation_equity_stays_UNRESOLVED(self):
        _, _, _, rep = carry()
        assert rep.marked_equity is not None
        assert rep.forced_liquidation_equity is None, (
            "a carried valuation became a hypothetical SALE price; no print "
            "happened, so there is nothing to fill against")

    def test_no_forced_liquidation_row_is_produced_for_it(self):
        _, _, _, rep = carry()
        assert [p["security_id"] for p in rep.forced_liquidation] == []

    def test_the_forced_liquidation_LEDGER_stays_empty(self):
        _, _, _, rep = carry()
        assert rep.forced_liquidation_ledger.events == []

    def test_the_mark_ledger_DOES_record_it(self):
        """Valuing is not selling. The mark ledger is the valuation record and
        must contain the position the forced-liquidation ledger refuses."""
        _, _, _, rep = carry()
        assert [e.security_id for e in rep.mark_ledger.events] == ["S1"]

    def test_is_tradeable_mark_is_the_gate_and_stays_CURRENT_only(self):
        from stock_strategy_shared.wealth_core.marks import Mark
        carried = Mark("S1", MarkStatus.PENDING_TERMS_CARRIED,
                       stale_raw_close=95.0, carried_raw_close=95.0)
        assert carried.resolves_equity is True
        assert carried.is_tradeable_mark is False
        live = Mark("S1", MarkStatus.CURRENT, raw_mark_close=95.0)
        assert live.resolves_equity and live.is_tradeable_mark


# ── 3. the control: a live book is completely unchanged ──────────────────────

class TestALiveBookIsUnaffected:

    def test_a_CURRENT_mark_still_values_AND_liquidates(self):
        st, led = seated(), Ledger()
        marks = build_marks([bar()], st.held_security_ids(), {"S1": 95.0}, {}, {})
        rep = final_report(session="d1", state=st, marks=marks, ledger=led,
                           cfg=CFG)
        assert marks["S1"].status is MarkStatus.CURRENT
        assert rep.marked_equity == pytest.approx(10_000.0 + 10 * 95.0)
        assert rep.forced_liquidation_equity is not None
        assert rep.forced_liquidation_equity < rep.marked_equity, (
            "the forced liquidation must still carry its transaction cost")

    def test_a_genuinely_UNMARKABLE_holding_still_blocks_BOTH(self):
        """The rule that must not be relaxed: a stale holding resolves nothing,
        and both totals stay None."""
        st, led = seated(), Ledger()
        marks = build_marks([], st.held_security_ids(), {}, {}, {})
        rep = final_report(session="d1", state=st, marks=marks, ledger=led,
                           cfg=CFG)
        assert marks["S1"].status is MarkStatus.STALE
        assert rep.marked_equity is None
        assert rep.forced_liquidation_equity is None


# ── 4. one rule, one place ───────────────────────────────────────────────────

class TestTheFinalMarksUseTheSameContext:
    """`run.py`'s final `build_marks` omitted `terminal_pending_sessions`, which
    ordinary session marking supplies. A holding in an active grace was
    therefore marked by a DIFFERENT rule at the run boundary than on every
    session before it — the same divergence `final_report` had, one layer down.
    """

    def test_run_passes_the_pending_context_to_the_final_build_marks(self):
        import inspect

        from stock_strategy_shared.wealth_core import run as run_mod
        src = inspect.getsource(run_mod)
        i = src.index("final_marks = build_marks(")
        call = src[i:i + 400]
        assert "terminal_pending_sessions" in call, (
            "the final marks are built without the grace context, so a carried "
            "holding is marked by a different rule at the boundary")

    def test_a_carried_holding_that_STILL_PRINTS_marks_CURRENT(self):
        """The asymmetry that must survive: a carried security which is still
        trading marks on its own print, and only falls back to the carried value
        when it stops printing. It is therefore fully liquidatable."""
        _, _, marks, rep = carry(bars=[bar(close=97.0)])
        assert marks["S1"].status is MarkStatus.CURRENT
        assert rep.forced_liquidation_equity is not None
