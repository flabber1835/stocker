"""PERMANENT regression coverage for the conversion-collision defect.

THE DEFECT. Two predecessor positions taken over by the same acquirer become two
episodes carrying the same `security_id`. `shares_by_security` was a dict
comprehension keyed on it, so the second overwrote the first: one holding
vanished from equity, and because every admission is 4% of equity, every position
opened afterwards was sized off the short number. Found by the golden fixture the
moment two conversions delivered the same acquirer.

WHY THIS FILE EXISTS SEPARATELY. The fix is one line and looks obviously correct
in isolation, which is exactly why it is easy to undo. A dict-comprehension
rewrite during any future tidy-up reintroduces it, and nothing else in the suite
would notice: the run still completes, every position is still in `episodes`, and
only the total is wrong.

The invariant is asserted at FIVE reader surfaces, not one. Equity, risk exposure,
ownership, final reporting and provenance each read the book through a different
accessor, and the original defect only affected one of them — so a test that
checked equity alone would pass while risk was still blind.

AGGREGATION AND PROVENANCE ARE BOTH REQUIRED. Execution and marking need the
aggregated security-level quantity, because that is what the broker holds. But
aggregation destroys the answer to "where did these shares come from?", and after
a takeover that question has no other source — it is what distinguishes one 8%
holding from two 4% holdings that collided, which changes what a human should do
about it. So both views are preserved and both are tested.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.marks import Mark, MarkStatus
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import (
    TerminalKind,
    TerminalTerms,
    apply_terminal,
    final_report,
)

CFG = WealthCoreConfig()
STATE_PY = (pathlib.Path(__file__).resolve().parents[2] / "shared"
            / "stock_strategy_shared" / "wealth_core" / "state.py")

ACQUIRER = "SEC_ACQ"
ACQ_TICKER = "ACQ"
ACQ_ISSUER = "P:ACQ"


def lot(slot_id, sec, ticker, issuer, shares, price):
    return HoldingEpisode(
        security_id=sec, ticker=ticker, issuer_id=issuer, slot_id=slot_id,
        signal_date="d0", entry_date="d1", entry_raw_open=price,
        entry_split_adjusted_price=price, initial_shares=shares,
        current_shares=shares, episode_peak_split_adjusted_close=price * 1.2,
        market_sessions_held=30 + slot_id,
        source_lots=[{"kind": "ADMISSION", "session": "d1",
                      "security_id": sec, "ticker": ticker, "shares": shares,
                      "raw_open": price}])


@pytest.fixture
def collided():
    """Two independent holdings, both converted into ONE acquirer.

    Different exchange ratios and different share counts on purpose: equal
    values would let an off-by-one aggregation still produce a plausible total.
    """
    st = PortfolioState.fresh(50_000.0)
    st.initialized = True
    st.slots[0].occupied_by = "SEC_TARGET_A"
    st.slots[1].occupied_by = "SEC_TARGET_B"
    st.episodes[0] = lot(0, "SEC_TARGET_A", "TGTA", "P:A", 400, 25.0)
    st.episodes[1] = lot(1, "SEC_TARGET_B", "TGTB", "P:B", 250, 40.0)

    led = Ledger()
    for sec, ratio in (("SEC_TARGET_A", 0.5), ("SEC_TARGET_B", 0.8)):
        apply_terminal(st, TerminalTerms(
            session="d9", security_id=sec, kind=TerminalKind.CONVERSION,
            delivered_security_id=ACQUIRER, delivered_ticker=ACQ_TICKER,
            delivered_issuer_id=ACQ_ISSUER, exchange_ratio=ratio,
            cash_in_lieu_price_per_delivered_share=100.0,
            reference=f"regression/{sec}"),
            ledger=led, session="d9", cfg=CFG)
    return st, led


# floor(400 x 0.5) = 200 and floor(250 x 0.8) = 200 -> 400 aggregated
EXPECTED_A, EXPECTED_B = 200, 200
EXPECTED_TOTAL = EXPECTED_A + EXPECTED_B


class TestNeitherHoldingDisappears:
    """Five reader surfaces. The original defect affected exactly one."""

    def test_the_setup_really_collided(self, collided):
        """Without this the whole file could pass on two distinct securities."""
        st, _ = collided
        secs = [ep.security_id for ep in st.episodes.values()]
        assert secs == [ACQUIRER, ACQUIRER]
        assert len(st.episodes) == 2

    def test_ownership_keeps_both_episodes_in_their_own_slots(self, collided):
        st, _ = collided
        assert sorted(st.episodes) == [0, 1]
        assert st.episodes[0].current_shares == EXPECTED_A
        assert st.episodes[1].current_shares == EXPECTED_B
        assert st.slots[0].occupied_by == ACQUIRER
        assert st.slots[1].occupied_by == ACQUIRER

    def test_equity_counts_the_aggregate_not_one_of_the_two(self, collided):
        st, _ = collided
        assert st.shares_by_security()[ACQUIRER] == EXPECTED_TOTAL
        ev = st.equity_view({ACQUIRER: Mark(ACQUIRER, MarkStatus.CURRENT,
                                            raw_mark_close=120.0)})
        assert ev.resolved_equity == pytest.approx(50_000.0
                                                   + EXPECTED_TOTAL * 120.0)

    def test_risk_exposure_sees_one_aggregated_position(self, collided):
        """The exposure check must treat the collision as ONE security. Reading
        per-episode would report two 4% positions where the book has one 8%
        position, which is the number a concentration limit exists to catch."""
        st, _ = collided
        exposure = st.shares_by_security()[ACQUIRER] * 120.0
        equity = 50_000.0 + exposure
        assert exposure / equity > 0.04, (
            "the fixture must actually breach the nominal weight, or this "
            "asserts nothing about concentration")
        assert st.held_issuer_ids() == {ACQ_ISSUER}

    def test_final_reporting_shows_both_lots_AND_the_aggregate(self, collided):
        st, led = collided
        rep = final_report(session="d9", state=st, ledger=led, cfg=CFG,
                           marks={ACQUIRER: Mark(ACQUIRER, MarkStatus.CURRENT,
                                                 raw_mark_close=120.0)})
        assert len(rep.marked_positions) == 2, "one row per HOLDING"
        agg = rep.aggregate_by_security[ACQUIRER]
        assert agg["shares"] == EXPECTED_TOTAL and agg["lots"] == 2
        assert sorted(agg["slots"]) == [0, 1]
        assert rep.marked_equity == pytest.approx(50_000.0
                                                  + EXPECTED_TOTAL * 120.0)

    def test_provenance_survives_the_identity_being_overwritten(self, collided):
        """After the conversion there is no other record that these shares were
        once two different companies."""
        st, _ = collided
        lots = st.lots_by_security()[ACQUIRER]
        assert len(lots) == 2
        origins = {o["from_security_id"]
                   for row in lots for o in row["origin"]
                   if o["kind"] == "CONVERSION"}
        assert origins == {"SEC_TARGET_A", "SEC_TARGET_B"}
        # ...and each lot still knows its own admission, not just its takeover.
        assert all(row["origin"][0]["kind"] == "ADMISSION" for row in lots)
        assert {row["origin"][0]["security_id"] for row in lots} == \
            {"SEC_TARGET_A", "SEC_TARGET_B"}

    def test_the_lot_chain_records_the_terms_that_produced_the_shares(self,
                                                                     collided):
        st, _ = collided
        conv = [o for row in st.lots_by_security()[ACQUIRER]
                for o in row["origin"] if o["kind"] == "CONVERSION"]
        by_from = {c["from_security_id"]: c for c in conv}
        a = by_from["SEC_TARGET_A"]
        assert a["shares_in"] == 400 and a["exchange_ratio"] == 0.5
        assert a["shares_delivered"] == EXPECTED_A
        assert a["to_security_id"] == ACQUIRER


class TestAThirdCollisionStillAggregates:
    """Two is the case that broke; three is where an ad-hoc two-way fix fails."""

    def test_three_predecessors(self):
        st = PortfolioState.fresh(10_000.0)
        st.initialized = True
        for i, (sec, shares) in enumerate([("SEC_X", 100), ("SEC_Y", 200),
                                           ("SEC_Z", 300)]):
            st.slots[i].occupied_by = sec
            st.episodes[i] = lot(i, sec, f"T{sec[-1]}", f"P:{sec[-1]}",
                                 shares, 20.0)
        led = Ledger()
        for sec in ("SEC_X", "SEC_Y", "SEC_Z"):
            apply_terminal(st, TerminalTerms(
                session="d9", security_id=sec, kind=TerminalKind.CONVERSION,
                delivered_security_id=ACQUIRER, delivered_ticker=ACQ_TICKER,
                delivered_issuer_id=ACQ_ISSUER, exchange_ratio=1.0),
                ledger=led, session="d9", cfg=CFG)
        assert st.shares_by_security()[ACQUIRER] == 600
        assert len(st.lots_by_security()[ACQUIRER]) == 3


def test_the_aggregation_is_not_a_dict_comprehension_keyed_on_security_id():
    """The specific shape of the original defect, forbidden structurally.

    A dict comprehension `{e.security_id: ... for e in ...}` silently keeps the
    LAST match. Asserting over the AST catches a tidy-up that rewrites the
    accumulator back into one, which no behavioural test in the rest of the suite
    would notice — the run still completes and only the total is wrong.
    """
    tree = ast.parse(STATE_PY.read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "shares_by_security")
    assert not any(isinstance(n, ast.DictComp) for n in ast.walk(fn)), (
        "shares_by_security must ACCUMULATE per security_id. A dict "
        "comprehension keyed on security_id drops every holding but the last, "
        "which is the conversion-collision defect verbatim.")
    # And it must genuinely add rather than assign.
    assert any(isinstance(n, ast.AugAssign) or isinstance(n, ast.BinOp)
               for n in ast.walk(fn))
