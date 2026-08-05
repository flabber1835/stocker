"""Stage 6 — terminal actions and final-session accounting.

The governing rule is NEVER INVENT TERMINAL PROCEEDS, and almost every test here
is a variation on it. What makes this area dangerous is that all the wrong
answers produce a complete run: assuming last price, assuming zero, or skipping
the event each yield a finished backtest of a strategy nobody ran.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.adapter import build_marks
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.marks import Mark, MarkStatus
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import (
    TerminalKind,
    TerminalTerms,
    apply_terminal,
    final_report,
)

CFG = WealthCoreConfig()


def book(shares=100, entry=50.0, peak=60.0, sec="S1", cash=10_000.0):
    st = PortfolioState.fresh(cash)
    st.slots[0].occupied_by = sec
    st.episodes[0] = HoldingEpisode(
        security_id=sec, ticker="T1", issuer_id="I1", slot_id=0,
        signal_date="d0", entry_date="d1", entry_raw_open=entry,
        entry_split_adjusted_price=entry, initial_shares=shares,
        current_shares=shares, episode_peak_split_adjusted_close=peak,
        market_sessions_held=40)
    st.initialized = True
    return st


def terms(kind, **kw):
    return TerminalTerms(session="d9", security_id="S1", kind=kind, **kw)


# ── completeness: the block, not the guess ──────────────────────────────────

class TestIncompleteTermsBlock:

    @pytest.mark.parametrize("kind,kw,expected", [
        (TerminalKind.CASH_MERGER, {}, "MISSING_CASH_PER_SHARE"),
        (TerminalKind.CONVERSION, {"exchange_ratio": 0.5},
         "MISSING_DELIVERED_SECURITY"),
        (TerminalKind.CONVERSION,
         {"delivered_security_id": "S2", "delivered_ticker": "T2",
          "delivered_issuer_id": "I2"}, "MISSING_EXCHANGE_RATIO"),
        (TerminalKind.CASH_PLUS_STOCK,
         {"delivered_security_id": "S2", "delivered_ticker": "T2",
          "delivered_issuer_id": "I2", "exchange_ratio": 0.5},
         "MISSING_CASH_PER_SHARE"),
    ])
    def test_a_missing_term_blocks_with_a_named_reason(self, kind, kw, expected):
        st, led = book(), Ledger()
        res = apply_terminal(st, terms(kind, **kw), ledger=led, session="d9", cfg=CFG)
        assert res["applied"] is False and res["reason"] == expected
        assert st.unresolved_terminals["S1"] == expected
        assert 0 in st.episodes, "the holding must be PRESERVED, not dropped"
        assert st.cash == 10_000.0, "no proceeds may be invented"
        assert not led.events, "a blocked action posts nothing"

    def test_the_block_makes_equity_unresolvable_which_stops_admissions(self):
        st = book()
        apply_terminal(st, terms(TerminalKind.CASH_MERGER), ledger=Ledger(),
                       session="d9", cfg=CFG)
        assert st.unresolved_terminals == {"S1": "MISSING_CASH_PER_SHARE"}
        # The security may still be PRINTING — a contested bid trades right up
        # to closing — so the block cannot come from an absent price. It comes
        # from the state, and build_marks is where it outranks the print.
        marks = build_marks([], {"S1"}, {"S1": 55.0}, st.unresolved_terminals)
        assert marks["S1"].status is MarkStatus.UNRESOLVED_TERMINAL
        # 4% of an unknown is not a number, so there must be no sizing base.
        assert st.equity_view(marks).resolved_equity is None

    def test_supplying_the_terms_later_lifts_the_block(self):
        st, led = book(), Ledger()
        apply_terminal(st, terms(TerminalKind.CASH_MERGER), ledger=led,
                       session="d9", cfg=CFG)
        res = apply_terminal(st, terms(TerminalKind.CASH_MERGER, cash_per_share=61.5),
                             ledger=led, session="d10", cfg=CFG)
        assert res["applied"] is True
        assert st.unresolved_terminals == {}
        assert st.cash == pytest.approx(10_000.0 + 100 * 61.5)

    def test_zero_cash_is_a_TERM_not_a_missing_one(self):
        """A deal that genuinely pays nothing is complete. Treating 0.0 as
        absent would block forever on a legitimate wipeout, and treating
        `None` as 0.0 would invent that wipeout."""
        st = book()
        res = apply_terminal(st, terms(TerminalKind.CASH_MERGER, cash_per_share=0.0),
                             ledger=Ledger(), session="d9", cfg=CFG)
        assert res["applied"] is True and st.cash == 10_000.0
        assert 0 not in st.episodes


# ── conversion ──────────────────────────────────────────────────────────────

class TestConversion:

    def conv(self, ratio=0.5, lieu=140.0, cash=None, kind=TerminalKind.CONVERSION):
        return terms(kind, delivered_security_id="S2", delivered_ticker="T2",
                     delivered_issuer_id="I2", exchange_ratio=ratio,
                     cash_in_lieu_price_per_delivered_share=lieu,
                     cash_per_share=cash)

    def test_the_episode_CONTINUES_rather_than_restarting(self):
        st, led = book(shares=100), Ledger()
        apply_terminal(st, self.conv(), ledger=led, session="d9", cfg=CFG)
        ep = st.episodes[0]
        assert ep.security_id == "S2" and ep.ticker == "T2" and ep.issuer_id == "I2"
        assert ep.market_sessions_held == 40, (
            "a conversion is not an exit — restarting the clock would reset the "
            "review age and the stop peak for a position never left")
        assert st.slots[0].occupied_by == "S2"

    def test_accounting_state_rescales_so_POSITION_VALUE_is_preserved(self):
        st = book(shares=100, entry=50.0, peak=60.0)
        apply_terminal(st, self.conv(ratio=0.5), ledger=Ledger(), session="d9",
                       cfg=CFG)
        ep = st.episodes[0]
        assert ep.current_shares == 50
        # 100 shares at a 60.0 peak is the same position value as 50 shares at
        # 120.0, so the drawdown the stop measures is unchanged.
        assert ep.episode_peak_split_adjusted_close == pytest.approx(120.0)
        assert ep.entry_split_adjusted_price == pytest.approx(100.0)
        assert ep.entry_raw_open == pytest.approx(100.0)

    def test_a_fraction_is_paid_in_cash_and_is_attributable(self):
        st, led = book(shares=101), Ledger()
        res = apply_terminal(st, self.conv(ratio=0.5, lieu=140.0), ledger=led,
                             session="d9", cfg=CFG)
        assert st.episodes[0].current_shares == 50          # floor(50.5)
        assert res["cash_in_lieu"] == pytest.approx(0.5 * 140.0)
        ev = next(e for e in led.events if e.event_type.value == "CONVERSION")
        # Attributable: the fraction and its price are BOTH on the event, so the
        # cash can be traced back to the entitlement that produced it.
        assert ev.detail["fractional_entitlement"] == pytest.approx(0.5)
        assert ev.detail["cash_in_lieu"] == pytest.approx(70.0)
        assert st.cash == pytest.approx(10_000.0 + 70.0)

    def test_a_fraction_is_never_rounded_UP_into_shares_nobody_delivered(self):
        st = book(shares=199)
        apply_terminal(st, self.conv(ratio=0.5), ledger=Ledger(), session="d9",
                       cfg=CFG)
        assert st.episodes[0].current_shares == 99, "floor(99.5), not round()"

    def test_a_fractional_conversion_without_a_lieu_price_is_refused(self):
        st = book(shares=101)
        res = apply_terminal(st, self.conv(ratio=0.5, lieu=None), ledger=Ledger(),
                             session="d9", cfg=CFG)
        assert res["reason"] == "MISSING_CASH_IN_LIEU_PRICE"
        assert st.episodes[0].security_id == "S1", "nothing may be applied"

    def test_a_clean_ratio_needs_no_lieu_price(self):
        """Demanding one unconditionally would block ordinary 1:2 deals that
        never round."""
        st = book(shares=100)
        res = apply_terminal(st, self.conv(ratio=0.5, lieu=None), ledger=Ledger(),
                             session="d9", cfg=CFG)
        assert res["applied"] is True

    def test_cash_plus_stock_pays_BOTH_legs(self):
        st, led = book(shares=100), Ledger()
        res = apply_terminal(st, self.conv(ratio=0.5, cash=18.0,
                                           kind=TerminalKind.CASH_PLUS_STOCK),
                             ledger=led, session="d9", cfg=CFG)
        assert res["cash_consideration"] == pytest.approx(1800.0)
        assert st.episodes[0].current_shares == 50
        assert st.cash == pytest.approx(11_800.0)

    def test_an_entitlement_rounding_to_nothing_becomes_a_cash_settlement(self):
        """Otherwise the position persists at ZERO shares in a security it does
        not really hold, and is marked forever."""
        st = book(shares=1)
        res = apply_terminal(st, self.conv(ratio=0.4, lieu=140.0), ledger=Ledger(),
                             session="d9", cfg=CFG)
        assert res["converted"] is False
        assert 0 not in st.episodes
        assert st.cash == pytest.approx(10_000.0 + 0.4 * 140.0)

    def test_two_conversions_into_one_acquirer_are_both_counted(self):
        """The issuer rule governs ADMISSION, not takeovers. A dict keyed on
        security_id lost one of the two positions, and equity undercounted a
        holding the book still owned — found by the golden fixture."""
        st = book(shares=100)
        st.slots[1].occupied_by = "S9"
        st.episodes[1] = HoldingEpisode(
            security_id="S9", ticker="T9", issuer_id="I9", slot_id=1,
            signal_date="d0", entry_date="d1", entry_raw_open=20.0,
            entry_split_adjusted_price=20.0, initial_shares=200,
            current_shares=200, episode_peak_split_adjusted_close=25.0)
        apply_terminal(st, self.conv(ratio=0.5), ledger=Ledger(), session="d9",
                       cfg=CFG)
        apply_terminal(st, TerminalTerms(
            session="d9", security_id="S9", kind=TerminalKind.CONVERSION,
            delivered_security_id="S2", delivered_ticker="T2",
            delivered_issuer_id="I2", exchange_ratio=0.5),
            ledger=Ledger(), session="d9", cfg=CFG)
        assert st.shares_by_security()["S2"] == 150, "50 + 100, not one of them"


def test_an_action_for_a_security_that_is_not_held_is_a_no_op_not_an_error():
    st = book(sec="S1")
    res = apply_terminal(st, TerminalTerms(session="d9", security_id="OTHER",
                                           kind=TerminalKind.WRITE_OFF),
                         ledger=Ledger(), session="d9", cfg=CFG)
    assert res["applied"] is False and res["reason"] == "NOT_HELD"
    assert "blocked" not in res, "a deal we do not own must not block the book"


# ── final-session accounting ────────────────────────────────────────────────

class TestFinalReport:

    def test_marking_is_not_a_trade_and_never_touches_the_run_ledger(self):
        st, led = book(shares=100), Ledger()
        rep = final_report(session="d9", state=st, cfg=CFG, ledger=led,
                           marks={"S1": Mark("S1", MarkStatus.CURRENT,
                                             raw_mark_close=70.0)})
        assert st.cash == 10_000.0 and st.episodes[0].current_shares == 100
        assert led.events == [], (
            "TERMINAL_MARK in the run ledger made the ledger depend on where the "
            "run stopped, so a resumed run could not reproduce an uninterrupted "
            "one — caught by the restart test")
        assert [e.event_type.value for e in rep.mark_ledger.events] == ["TERMINAL_MARK"]

    def test_the_three_final_numbers_stay_apart(self):
        st, led = book(shares=100), Ledger()
        rep = final_report(session="d9", state=st, cfg=CFG, ledger=led,
                           marks={"S1": Mark("S1", MarkStatus.CURRENT,
                                             raw_mark_close=70.0)})
        assert rep.marked_equity == pytest.approx(10_000.0 + 7_000.0)
        # The forced number is LOWER by exactly the cost of a sale that never
        # happened. Folding it into the headline would charge the strategy for a
        # trade it never made.
        cost = 7_000.0 * CFG.transaction_cost_bps / 10_000.0
        assert rep.forced_liquidation_equity == pytest.approx(17_000.0 - cost)
        assert rep.forced_liquidation_equity < rep.marked_equity

    def test_the_hypothetical_liquidation_lives_in_its_own_ledger(self):
        st, led = book(), Ledger()
        rep = final_report(session="d9", state=st, cfg=CFG, ledger=led,
                           marks={"S1": Mark("S1", MarkStatus.CURRENT,
                                             raw_mark_close=70.0)})
        kinds = [e.event_type.value for e in rep.forced_liquidation_ledger.events]
        assert kinds == ["TERMINAL_LIQUIDATION"]
        assert all(e.detail.get("hypothetical") for e
                   in rep.forced_liquidation_ledger.events)
        assert led.events == []

    def test_one_unmarkable_holding_makes_the_whole_equity_unresolved(self):
        """The same fail-closed rule the running gate uses. A total that
        silently omits an unmarkable holding reads as a complete valuation."""
        st = book()
        rep = final_report(session="d9", state=st, cfg=CFG, ledger=Ledger(),
                           marks={"S1": Mark("S1", MarkStatus.STALE,
                                             stale_raw_close=70.0)})
        assert rep.marked_equity is None
        assert rep.forced_liquidation_equity is None
        assert rep.unmarkable_positions[0]["security_id"] == "S1"
        assert rep.unmarkable_positions[0]["last_known_raw_close"] == 70.0

    def test_positions_closed_during_the_run_are_reported_separately(self):
        st, led = book(), Ledger()
        led.post(session="d5", event_type=EventType.SELL, cash_before=0.0,
                 cash_delta=500.0, security_id="OLD", ticker="OLD",
                 shares_delta=-10, price=50.0, reason="EXIT")
        rep = final_report(session="d9", state=st, cfg=CFG, ledger=led,
                           marks={"S1": Mark("S1", MarkStatus.CURRENT,
                                             raw_mark_close=70.0)})
        assert [p["security_id"] for p in rep.liquidated_during_run] == ["OLD"]
        assert [p["security_id"] for p in rep.marked_positions] == ["S1"]
