"""Dividend entitlement, settlement, and the ways both can silently go wrong.

WHY THIS IS A SEPARATE FILE. A dividend is the only cash event in Wealth Core
that is EARNED on one session and RECEIVED on another. Everything else — a buy,
a sell, a cash merger — moves shares and cash in the same instant. That gap is
where the failure modes live, and all of them produce a complete, plausible run:

    settled on the ex-date      the money funds an admission it could not have
    entitlement read too late   a position bought at today's open collects a
                                dividend it did not own the shares for
    recomputed at settlement    a split between ex and pay doubles the payment
    dropped on a delisting      real cash vanishes with no event explaining it
    lost across a restart       ditto, and only on deploy days
    taken from the adjusted     the distribution is counted twice, once in the
    price series                price and once in the ledger

The engine's own reconciliation cannot catch most of these: `reconcile_cash`
replays the ledger's own deltas, so a wrong-but-recorded payment reconciles
perfectly.
"""
from __future__ import annotations

import json

import pytest

from stock_strategy_shared.wealth_core.adapter import (
    PendingOrder,
    apply_dividends,
    step_session,
    tradeability_only_bars,
)
from stock_strategy_shared.wealth_core.engine import Operation, Reason, WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import (
    TerminalKind,
    TerminalTerms,
    apply_terminal,
)

SID, VER = "stocker_wealth_core_v1", 1
CFG = WealthCoreConfig()                       # lag 1, the default


def bar(sec="S1", session="d1", *, signal=100.0, open_=99.0, mark=100.0,
        div=0.0, split=1.0, tradeable=True):
    return DailyBar(security_id=sec, ticker=f"T{sec[1:]}", issuer_id=f"I{sec[1:]}",
                    session=session, signal_close_split_adj_div_unadj=signal,
                    raw_open=open_, raw_mark_close=mark, tradeable=tradeable,
                    split_ratio=split, dividend_per_share=div)


def seated(cash=10_000.0, sec="S1", shares=100, entry=100.0):
    st = PortfolioState.fresh(cash, n_slots=2)
    st.slots[0].occupied_by = sec
    st.episodes[0] = HoldingEpisode(sec, f"T{sec[1:]}", f"I{sec[1:]}", 0, "d0",
                                    "d0", entry, entry, shares, shares, entry)
    st.initialized = True
    return st


def run_session(st, bars, ledger, session, cfg=CFG, pending=None):
    return step_session(session=session, state=st, bars=bars,
                        pending=pending if pending is not None else [],
                        ledger=ledger, last_known={}, cfg=cfg,
                        strategy_id=SID, strategy_version=VER,
                        security_bars=tradeability_only_bars(bars, None))


# ── 1. entitlement ──────────────────────────────────────────────────────────

class TestEntitlement:

    def test_a_hand_computed_ordinary_dividend(self):
        """100 shares x $0.50 = $50.00. Worked by hand, not read back."""
        st, led = seated(cash=1_000.0, shares=100), Ledger()
        apply_dividends(st, [bar(div=0.50)], led, "d1", CFG)
        assert led.receivable_total() == 50.0
        ev = led.events[0]
        assert ev.event_type is EventType.DIVIDEND_ACCRUED
        assert ev.detail["shares"] == 100 and ev.detail["amount"] == 50.0
        assert ev.cash_delta == 0.0, "an accrual moves no cash"

    def test_only_HELD_securities_accrue(self):
        st, led = seated(), Ledger()
        apply_dividends(st, [bar("S9", div=1.0)], led, "d1", CFG)
        assert led.receivables == [] and led.events == []

    def test_ENTITLEMENT_IS_READ_BEFORE_THIS_SESSION_S_FILLS(self):
        """MANDATORY, and the ordering is the whole content of the rule.

        Dividends are step 2; pending orders fill at step 4. A position BOUGHT
        at this session's open did not own the shares when the security went ex,
        and a position SOLD at this open did. Reading the share count after the
        fills gets both backwards — and the error is invisible, because the
        resulting payment is internally consistent.
        """
        st, led = seated(cash=100_000.0, shares=100), Ledger()
        # An entry for a DIFFERENT security queued from yesterday, filling today
        # into the free slot, on a session where it also goes ex.
        pending = [PendingOrder(Operation.OPEN_SLOT_POSITION, "S2", "T2", 1, 10,
                                "d0", Reason.ENTRY_DURABLE_RANK.value)]
        bars = [bar("S1", div=0.50), bar("S2", div=5.00)]
        run_session(st, bars, led, "d1", pending=pending)

        accrued = {e.security_id: e.detail["amount"] for e in led.events
                   if e.event_type is EventType.DIVIDEND_ACCRUED}
        assert accrued == {"S1": 50.0}, (
            "S2 was not held when it went ex — it was bought at THIS session's "
            "open. Accruing for it would pay a dividend on shares the book did "
            "not own on the ex-date")
        assert "S2" in st.held_security_ids(), "...but the fill did happen"


# ── 2. settlement ───────────────────────────────────────────────────────────

class TestSettlement:

    def test_the_receivable_is_NOT_cash_on_the_ex_date(self):
        """The property the whole lag exists for. `decide()` runs at step 7
        against `state.cash`, so a dividend settled at step 2 is spendable on
        the session it was declared."""
        st, led = seated(cash=1_000.0, shares=100), Ledger()
        run_session(st, [bar(div=0.50)], led, "d1")
        assert st.cash == 1_000.0
        assert led.receivable_total() == 50.0

    def test_it_becomes_cash_exactly_once_at_the_configured_lag(self):
        st, led = seated(cash=1_000.0, shares=100), Ledger()
        cfg = WealthCoreConfig(dividend_settlement_lag_sessions=3)
        run_session(st, [bar(div=0.50)], led, "d1", cfg)
        for s in ("d2", "d3"):
            run_session(st, [bar(session=s)], led, s, cfg)
            assert st.cash == 1_000.0, f"paid too early, on {s}"
        run_session(st, [bar(session="d4")], led, "d4", cfg)
        assert st.cash == 1_050.0
        for s in ("d5", "d6"):
            run_session(st, [bar(session=s)], led, s, cfg)
        assert st.cash == 1_050.0, "paid more than once"
        assert sum(1 for e in led.events
                   if e.event_type is EventType.DIVIDEND_PAID) == 1

    def test_MULTIPLE_dividends_outstanding_at_once_stay_separate(self):
        """A dict keyed on security_id would merge these into one payment on
        one date. Two dividends from the same security CAN be outstanding
        simultaneously with different due dates, and the second must not drag
        the first along or be dragged by it."""
        st, led = seated(cash=1_000.0, shares=100), Ledger()
        cfg = WealthCoreConfig(dividend_settlement_lag_sessions=2)
        run_session(st, [bar(div=0.50)], led, "d1", cfg)               # due d3
        run_session(st, [bar(session="d2", div=0.25)], led, "d2", cfg)  # due d4
        assert led.receivable_total() == 75.0

        run_session(st, [bar(session="d3")], led, "d3", cfg)
        assert st.cash == 1_050.0, "only the first is due"
        assert led.receivable_total() == 25.0
        run_session(st, [bar(session="d4")], led, "d4", cfg)
        assert st.cash == 1_075.0
        assert led.receivables == []

    def test_the_paid_event_names_the_session_it_was_ACCRUED_on(self):
        """Without it the audit cannot connect a payment to its entitlement,
        which is the only way to check a lag after the fact."""
        st, led = seated(shares=100), Ledger()
        run_session(st, [bar(div=0.50)], led, "d1")
        run_session(st, [bar(session="d2")], led, "d2")
        paid = next(e for e in led.events if e.event_type is EventType.DIVIDEND_PAID)
        assert paid.detail["accrued_session"] == "d1"
        assert paid.session == "d2"


# ── 3. interaction with corporate actions ───────────────────────────────────

class TestCorporateActionInteraction:

    def test_a_SPLIT_between_ex_and_pay_does_not_change_the_amount(self):
        """The entitlement is a DOLLAR amount fixed by the shares held on the
        ex-date. Recomputing at settlement from the then-current share count
        would double the payment on a 2:1 — a bug that looks like a dividend
        and reconciles perfectly."""
        st, led = seated(cash=1_000.0, shares=100), Ledger()
        cfg = WealthCoreConfig(dividend_settlement_lag_sessions=2)
        run_session(st, [bar(div=0.50)], led, "d1", cfg)
        run_session(st, [bar(session="d2", split=2.0)], led, "d2", cfg)
        assert st.episodes[0].current_shares == 200, "the split did happen"
        run_session(st, [bar(session="d3")], led, "d3", cfg)
        assert st.cash == 1_050.0, "50.00, not 100.00"

    def test_a_dividend_SURVIVES_a_delisting_before_it_settles(self):
        """MANDATORY. Money earned before the position terminated is still
        owed. Cancelling it because the holding has left would lose real cash
        with no event saying where it went."""
        st, led = seated(cash=1_000.0, shares=100), Ledger()
        cfg = WealthCoreConfig(dividend_settlement_lag_sessions=2)
        run_session(st, [bar(div=0.50)], led, "d1", cfg)

        apply_terminal(st, TerminalTerms(session="d2", security_id="S1",
                                         kind=TerminalKind.WRITE_OFF),
                       ledger=led, session="d2", cfg=cfg)
        assert "S1" not in st.held_security_ids()
        assert led.receivable_total() == 50.0, "the claim is not the position"

        run_session(st, [bar(session="d3")], led, "d3", cfg)
        run_session(st, [bar(session="d4")], led, "d4", cfg)
        assert st.cash == 1_050.0
        assert any(e.event_type is EventType.DIVIDEND_PAID for e in led.events)

    def test_a_dividend_survives_a_CASH_MERGER_too(self):
        st, led = seated(cash=1_000.0, shares=100), Ledger()
        cfg = WealthCoreConfig(dividend_settlement_lag_sessions=2)
        run_session(st, [bar(div=0.50)], led, "d1", cfg)
        apply_terminal(st, TerminalTerms(session="d2", security_id="S1",
                                         kind=TerminalKind.CASH_MERGER,
                                         cash_per_share=10.0),
                       ledger=led, session="d2", cfg=cfg)
        run_session(st, [bar(session="d3")], led, "d3", cfg)
        run_session(st, [bar(session="d4")], led, "d4", cfg)
        # 1000 starting + 1000 merger proceeds + 50 dividend
        assert st.cash == pytest.approx(2_050.0)


# ── 4. restart safety ───────────────────────────────────────────────────────

class TestRestartBetweenExDateAndPayment:

    def _accrued(self, cfg):
        st, led = seated(cash=1_000.0, shares=100), Ledger()
        run_session(st, [bar(div=0.50)], led, "d1", cfg)
        return st, led

    def test_an_outstanding_receivable_ROUND_TRIPS_as_bytes(self):
        """Objects surviving is not the test; a restart reads storage."""
        cfg = WealthCoreConfig(dividend_settlement_lag_sessions=2)
        _, led = self._accrued(cfg)
        back = Ledger.from_dict(json.loads(json.dumps(led.to_dict())))
        assert back.receivable_total() == 50.0
        assert back.receivables[0]["due_in"] == led.receivables[0]["due_in"]
        assert back.receivables[0]["accrued_session"] == "d1"

    def test_a_restart_between_ex_and_pay_produces_THE_SAME_CASH(self):
        cfg = WealthCoreConfig(dividend_settlement_lag_sessions=2)

        straight, led_a = self._accrued(cfg)
        for s in ("d2", "d3"):
            run_session(straight, [bar(session=s)], led_a, s, cfg)

        restarted, led_b = self._accrued(cfg)
        crossed = Ledger.from_dict(json.loads(json.dumps(led_b.to_dict())))
        state_b = PortfolioState.from_dict(
            json.loads(json.dumps(restarted.to_dict())))
        for s in ("d2", "d3"):
            run_session(state_b, [bar(session=s)], crossed, s, cfg)

        assert state_b.cash == straight.cash == 1_050.0
        assert crossed.ledger_hash() == led_a.ledger_hash()

    def test_LOSING_the_receivable_across_the_restart_LOSES_THE_MONEY(self):
        """The mutation control. Without it the test above proves the restart
        machinery runs, not that it carried the receivable.

        The comparison is DAMAGED vs a CLEAN resumption over the same sessions.
        Comparing against the pre-restart ledger would be vacuous: the damaged
        run posts no payment, so its event log is identical to the one it
        started from.
        """
        cfg = WealthCoreConfig(dividend_settlement_lag_sessions=2)

        st, led = self._accrued(cfg)
        blob = json.loads(json.dumps(led.to_dict()))
        blob["receivables"] = []                       # the corruption
        damaged = Ledger.from_dict(blob)
        state = PortfolioState.from_dict(json.loads(json.dumps(st.to_dict())))
        for s in ("d2", "d3"):
            run_session(state, [bar(session=s)], damaged, s, cfg)

        st2, led2 = self._accrued(cfg)
        clean = Ledger.from_dict(json.loads(json.dumps(led2.to_dict())))
        state2 = PortfolioState.from_dict(json.loads(json.dumps(st2.to_dict())))
        for s in ("d2", "d3"):
            run_session(state2, [bar(session=s)], clean, s, cfg)

        assert state2.cash == 1_050.0, "the clean resumption pays"
        assert state.cash == 1_000.0, (
            "dropping the receivable must lose exactly the dividend — if this "
            "still pays, the receivable is not what settlement reads")
        assert damaged.ledger_hash() != clean.ledger_hash()

    def test_the_LEDGER_HASH_sees_a_dropped_receivable_IMMEDIATELY(self):
        """The hash used to cover the event log alone, so money the book was
        owed sat outside it: a restart that dropped a receivable produced an
        identical ledger hash AT THE BOUNDARY and diverged only later, when the
        payment failed to appear. A hash that cannot see a difference until its
        downstream consequence shows up is worth far less than one that sees it
        at once."""
        cfg = WealthCoreConfig(dividend_settlement_lag_sessions=2)
        _, led = self._accrued(cfg)

        blob = json.loads(json.dumps(led.to_dict()))
        blob["receivables"] = []
        assert Ledger.from_dict(blob).ledger_hash() != led.ledger_hash()
        # ...and the event logs are identical, which is what made it invisible.
        assert [e.to_dict() for e in Ledger.from_dict(blob).events] == \
            [e.to_dict() for e in led.events]

    def test_corrupting_the_DUE_COUNTER_moves_the_payment(self):
        """A second, independent control: persistence of the amount and
        persistence of the SCHEDULE are different facts, and a restart that
        reset every counter to zero would pay everything a session early while
        the totals still reconciled."""
        cfg = WealthCoreConfig(dividend_settlement_lag_sessions=3)
        st, led = self._accrued(cfg)

        blob = json.loads(json.dumps(led.to_dict()))
        for r in blob["receivables"]:
            r["due_in"] = 0                            # the corruption
        damaged = Ledger.from_dict(blob)
        state = PortfolioState.from_dict(json.loads(json.dumps(st.to_dict())))
        run_session(state, [bar(session="d2")], damaged, "d2", cfg)
        assert state.cash == 1_050.0, "paid early, as the corruption dictates"

        clean = Ledger.from_dict(json.loads(json.dumps(led.to_dict())))
        state2 = PortfolioState.from_dict(json.loads(json.dumps(st.to_dict())))
        run_session(state2, [bar(session="d2")], clean, "d2", cfg)
        assert state2.cash == 1_000.0, "the intact schedule does NOT pay yet"


# ── 5. double-count prevention ──────────────────────────────────────────────

class TestTheDistributionIsCountedExactlyOnce:

    def test_the_signal_domain_REFUSES_a_total_return_field_name(self):
        """The book is marked on dividend-UNADJUSTED prices, which is why the
        explicit ledger event is needed at all. If an adjusted series reached
        the price domains the distribution would be counted twice — once inside
        the price and once in the ledger — and the run would look fine.

        `DailyBar.from_mapping` refuses the field names outright, because a
        field called `close` cannot say WHICH domain it belongs to and a
        contract that relies on the caller remembering is a comment.
        """
        from stock_strategy_shared.wealth_core.prices import PriceDomainError

        for banned in ("closeadj", "adjusted_close", "close", "price"):
            with pytest.raises(PriceDomainError):
                DailyBar.from_mapping({
                    "security_id": "S1", "ticker": "T1", "issuer_id": "I1",
                    "session": "d1", banned: 100.0, "raw_open": 99.0,
                    "raw_mark_close": 100.0})

    def test_a_zero_dividend_is_NOT_an_event(self):
        """0.0 means 'no distribution', which must produce no ledger row. An
        engine that accrued zeroes would fill the ledger with events that
        change nothing and make the hash depend on which bars happened to
        carry an explicit 0.0."""
        st, led = seated(), Ledger()
        apply_dividends(st, [bar(div=0.0)], led, "d1", CFG)
        assert led.events == [] and led.receivables == []


# ── 6. the money is never invisible ─────────────────────────────────────────

def test_an_unsettled_receivable_at_the_end_of_a_run_is_REPORTED():
    """A run that stops between ex and pay is owed money. Reporting cash alone
    would understate it by exactly the amount in flight, and silently — the
    ledger reconciles perfectly either way, because an accrual has no cash
    delta to reconcile."""
    from stock_strategy_shared.wealth_core.run import RunResult

    st, led = seated(cash=1_000.0, shares=100), Ledger()
    run_session(st, [bar(div=0.50)], led, "d1")
    out = RunResult(state=st, ledger=led)
    assert out.to_dict()["outstanding_receivables"] == 50.0

    # ...and it is NOT folded into cash, which would make it spendable.
    assert st.cash == 1_000.0
    assert led.reconcile_cash(1_000.0) == st.cash


def test_the_settlement_lag_is_in_the_config_hash():
    """Two runs whose dividends settle on different sessions are different
    strategies, and a result must be attributable to the one that produced it."""
    a = WealthCoreConfig(dividend_settlement_lag_sessions=1)
    b = WealthCoreConfig(dividend_settlement_lag_sessions=2)
    assert a.config_hash() != b.config_hash()
