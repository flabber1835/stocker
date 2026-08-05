"""Stage 5 — the shared session adapter, ledger and the unmarkable-holding rule.

The rule adopted 2026-08-03 exists because BOTH obvious treatments of an
unmarkable holding are wrong and silent:

    zero it          invents an immediate total loss and permanently shrinks
                     every admission afterwards, since each is 4% of equity
    carry last price presents stale value as current and overstates the base

So the tests here are mostly about the THIRD option: represent the condition,
keep the holding, block admissions, and change equity only when a human confirms
an outcome. Every one of these would pass silently under either wrong treatment,
which is exactly why they are written.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.adapter import (
    PendingOrder,
    build_marks,
    cash_merger,
    step_session,
    tradeability_only_bars,
    write_off,
)
from stock_strategy_shared.wealth_core.engine import Operation, Reason, WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.marks import MarkStatus
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState

CFG = WealthCoreConfig()
SID, VER = "stocker_wealth_core_v1", 1


def db(sec="S1", session="d1", *, signal=100.0, open_=99.0, mark=100.0,
       tradeable=True, split=1.0, div=0.0, unresolved=False):
    return DailyBar(security_id=sec, ticker=f"T{sec[1:]}", issuer_id=f"I{sec[1:]}",
                    session=session, signal_close_split_adj_div_unadj=signal,
                    raw_open=open_, raw_mark_close=mark, tradeable=tradeable,
                    split_ratio=split, dividend_per_share=div,
                    unresolved_corporate_action=unresolved)


def seated(cash=10_000.0, sec="S1", shares=10, entry=100.0):
    st = PortfolioState.fresh(cash)
    st.slots[0].occupied_by = sec
    st.episodes[0] = HoldingEpisode(sec, f"T{sec[1:]}", f"I{sec[1:]}", 0, "d0", "d0",
                                    entry, entry, shares, shares, entry)
    st.initialized = True
    return st


def rising(n=127, start=100.0, step=1.0):
    return [start + step * i for i in range(n)]


def step(st, bars, pending=None, ledger=None, last_known=None, session="d1",
         windows=None):
    return step_session(session=session, state=st, bars=bars,
                        pending=pending if pending is not None else [],
                        ledger=ledger or Ledger(),
                        last_known=last_known if last_known is not None else {},
                        cfg=CFG, strategy_id=SID, strategy_version=VER,
                        security_bars=tradeability_only_bars(bars, windows))


# ── the unmarkable-holding rule ─────────────────────────────────────────────

class TestUnmarkableHoldings:
    def test_an_unmarkable_holding_is_NOT_silently_valued_at_zero(self):
        """MANDATORY. Zeroing invents a total loss the market never delivered,
        and because admissions are 4% of equity it shrinks every later position
        permanently."""
        st = seated()
        marks = build_marks([], {"S1"}, {"S1": 95.0})
        ev = st.equity_view(marks)
        assert ev.resolved_equity is None            # not 10_000, and not zero
        assert ev.estimated_equity_including_stale_marks == 10_000.0 + 10 * 95.0

    def test_a_stale_price_is_NOT_accepted_as_a_current_mark(self):
        """MANDATORY. The last known close survives as INFORMATION; it never
        becomes equity."""
        marks = build_marks([], {"S1"}, {"S1": 95.0})
        assert marks["S1"].status is MarkStatus.STALE
        assert marks["S1"].raw_mark_close is None
        assert marks["S1"].stale_raw_close == 95.0
        assert marks["S1"].resolves_equity is False

    def test_new_admissions_are_BLOCKED_while_equity_is_unresolved(self):
        """MANDATORY. 4% of an unknown is not a number."""
        st = seated()
        st.slots[1].occupied_by = None
        r = step(st, [db("S2", mark=50.0, signal=50.0)],
                 windows={"S2": rising()})
        assert r.blocked is True
        ops = [o.operation for o in r.decision.operations]
        assert Operation.BLOCK_NEW_ADMISSIONS_UNRESOLVED_EQUITY in ops
        assert Operation.OPEN_SLOT_POSITION not in ops

    def test_a_temporary_missing_mark_does_NOT_close_the_position(self):
        """MANDATORY. Losing a price is not a sell signal, and the slot stays
        the holding's — releasing it would let a different name take the seat of
        a position that still exists."""
        st = seated()
        r = step(st, [], last_known={"S1": 95.0})
        assert 0 in st.episodes and st.episodes[0].current_shares == 10
        assert st.slots[0].occupied_by == "S1"
        assert not [o for o in r.decision.operations
                    if o.operation is Operation.CLOSE_POSITION]

    def test_resolution_restores_admission_eligibility_deterministically(self):
        """MANDATORY. Once every holding marks again the gate opens, with no
        residue from having been blocked."""
        st = seated()
        assert step(st, [], last_known={"S1": 95.0}).blocked is True
        r2 = step(st, [db("S1", mark=95.0, signal=95.0)], session="d2")
        assert r2.blocked is False
        assert r2.resolved_equity == 10_000.0 + 10 * 95.0

    def test_the_two_equity_numbers_are_separately_named(self):
        """Only `resolved_equity` may be called trustworthy, and it is None —
        not a number — when anything is unresolved."""
        st = seated()
        ev = st.equity_view(build_marks([], {"S1"}, {"S1": 95.0}))
        assert ev.is_resolved is False and ev.sizing_base is None
        assert ev.estimated_equity_including_stale_marks > 0

    def test_an_unresolved_terminal_action_blocks_rather_than_zeroing(self):
        st = seated()
        marks = build_marks([db("S1", tradeable=False, unresolved=True)],
                            {"S1"}, {"S1": 95.0})
        assert marks["S1"].status is MarkStatus.UNRESOLVED_TERMINAL
        assert st.equity_view(marks).resolved_equity is None


# ── terminal events ─────────────────────────────────────────────────────────

class TestTerminalEvents:
    def test_a_write_off_changes_equity_ONLY_when_the_event_is_processed(self):
        """MANDATORY, and the crux of the rule. Before the event the holding is
        UNRESOLVED — worth we-don't-know. After it, zero is a fact and equity is
        trustworthy again."""
        st = seated()
        led = Ledger()
        before = st.equity_view(build_marks([], {"S1"}, {"S1": 95.0}))
        assert before.resolved_equity is None

        write_off(st, security_id="S1", ledger=led, session="d5")
        after = st.equity_view(build_marks([], set(), {}))
        assert after.resolved_equity == 10_000.0        # resolved, and it IS zero
        assert [e.event_type for e in led.events] == [EventType.WRITE_OFF]
        assert led.events[0].shares_delta == -10

    def test_cash_merger_proceeds_replace_the_security_via_the_ledger(self):
        """MANDATORY. Shares leave and ACTUAL proceeds arrive, both as events —
        not as a price that happens to equal the offer."""
        st = seated(cash=1_000.0, shares=10)
        led = Ledger()
        cash_merger(st, security_id="S1", per_share=42.0, ledger=led, session="d5")
        assert st.cash == 1_000.0 + 420.0
        assert 0 not in st.episodes
        ev = led.events[0]
        assert ev.event_type is EventType.CASH_MERGER
        assert ev.cash_delta == 420.0 and ev.shares_delta == -10
        assert ev.cash_after == ev.cash_before + 420.0

    def test_a_terminal_event_starts_both_cooldowns(self):
        st = seated()
        cash_merger(st, security_id="S1", per_share=10.0, ledger=Ledger(), session="d")
        assert st.slots[0].in_cooldown and st.ticker_in_cooldown("T1")


# ── corporate actions ───────────────────────────────────────────────────────

class TestCorporateActions:
    def test_a_split_changes_shares_BEFORE_anything_reads_them(self):
        """Ordering, not arithmetic: marks, equity and exit sizing all read the
        share count, so the split has to land first or one of them uses the
        pre-split figure."""
        st = seated(shares=10)
        led = Ledger()
        step(st, [db("S1", split=2.0, mark=50.0, signal=50.0)], ledger=led)
        assert st.episodes[0].current_shares == 20
        assert led.events[0].event_type is EventType.SPLIT

    def test_a_split_does_not_rescale_the_split_adjusted_peak(self):
        """The signal domain is ALREADY split-adjusted — that is why it exists.
        Rescaling the peak here would apply the split twice and move the stop."""
        st = seated(shares=10, entry=100.0)
        st.episodes[0].episode_peak_split_adjusted_close = 120.0
        step(st, [db("S1", split=2.0, mark=50.0, signal=60.0)])
        assert st.episodes[0].episode_peak_split_adjusted_close == 120.0

    def test_a_dividend_is_a_RECEIVABLE_then_cash_two_events(self):
        """Spec §2: 'explicit receivable and cash ledger events'. Posting
        straight to cash would let an unsettled dividend fund an admission on
        the session it was declared."""
        st = seated(cash=1_000.0, shares=10)
        led = Ledger()
        step(st, [db("S1", div=0.50, mark=100.0, signal=100.0)], ledger=led)
        kinds = [e.event_type for e in led.events]
        assert EventType.DIVIDEND_ACCRUED in kinds and EventType.DIVIDEND_PAID in kinds
        assert kinds.index(EventType.DIVIDEND_ACCRUED) < kinds.index(EventType.DIVIDEND_PAID)
        assert st.cash == 1_000.0 + 5.0
        assert led.receivables == {}


# ── pending orders ──────────────────────────────────────────────────────────

class TestPendingOrders:
    def _pending_exit(self):
        return [PendingOrder(Operation.CLOSE_POSITION, "S1", "T1", 0, 10, "d0",
                             Reason.EXIT_TRAILING_STOP.value)]

    def test_an_order_PERSISTS_across_a_non_tradeable_session(self):
        """MANDATORY. A halted security's exit is still wanted tomorrow.
        Dropping it would leave a stopped-out position in the book with nothing
        recording why it stayed."""
        st, pend = seated(), self._pending_exit()
        r = step(st, [db("S1", tradeable=False)], pending=pend)
        assert len(pend) == 1 and pend[0].sessions_waiting == 1
        assert r.fills == [] and 0 in st.episodes

    def test_it_executes_at_the_NEXT_positive_volume_raw_open(self):
        st, pend = seated(cash=0.0), self._pending_exit()
        r = step(st, [db("S1", open_=88.0, tradeable=True)], pending=pend)
        assert pend == []
        assert r.fills[0]["raw_open"] == 88.0
        assert 0 not in st.episodes
        assert st.cash == pytest.approx(10 * 88.0 * (1 - CFG.transaction_cost_bps / 10_000))

    def test_a_missing_bar_also_defers_rather_than_dropping(self):
        st, pend = seated(), self._pending_exit()
        step(st, [], pending=pend)
        assert len(pend) == 1

    def test_restart_with_an_order_pending_between_signal_and_fill(self):
        """MANDATORY. The queue is state: serialise, restore, and the fill must
        happen exactly as if the process had never stopped."""
        st, pend = seated(cash=0.0), self._pending_exit()
        step(st, [db("S1", tradeable=False)], pending=pend)          # deferred

        restored_state = PortfolioState.from_dict(st.to_dict())
        restored_pend = [PendingOrder(**vars(pend[0]))]
        a = step(st, [db("S1", open_=88.0)], pending=pend, session="d2")
        b = step(restored_state, [db("S1", open_=88.0)], pending=restored_pend,
                 session="d2")
        assert a.decision.decision_hash() == b.decision.decision_hash()
        assert a.fills == b.fills
        assert st.state_hash() == restored_state.state_hash()

    def test_restart_DURING_unresolved_status_is_identical(self):
        """MANDATORY. Being blocked is itself state — a restart must stay
        blocked and produce the same hash."""
        st = seated()
        a = step(st, [], last_known={"S1": 95.0})
        b = step(PortfolioState.from_dict(seated().to_dict()), [],
                 last_known={"S1": 95.0})
        assert a.blocked and b.blocked
        assert a.decision.decision_hash() == b.decision.decision_hash()


# ── no same-open replacement ────────────────────────────────────────────────

def test_a_position_sold_at_this_open_is_not_replaced_using_this_open():
    """Spec §11. `decide()` runs AFTER the fills, so its decisions cannot reach
    back to the session they were executed on — the replacement is queued for
    the next open, one session later."""
    st = seated(cash=0.0)
    pend = [PendingOrder(Operation.CLOSE_POSITION, "S1", "T1", 0, 10, "d0",
                         Reason.EXIT_TRAILING_STOP.value)]
    r = step(st, [db("S1", open_=100.0, mark=100.0, signal=100.0)], pending=pend,
             windows={"S1": rising()})
    assert r.fills[0]["operation"] == Operation.CLOSE_POSITION.value
    # slot 0 just emptied and is in cooldown, so nothing takes its seat today
    assert st.slots[0].in_cooldown
    assert not [o for o in r.decision.operations
                if o.operation is Operation.OPEN_SLOT_POSITION and o.slot_id == 0]


# ── the ledger reconciles ───────────────────────────────────────────────────

def test_the_ledger_reproduces_the_cash_balance_independently():
    """§15.7 in miniature: replaying every cash delta must land on the running
    balance. A disagreement means the simulator moved money without saying so."""
    st = seated(cash=5_000.0, shares=10)
    led = Ledger()
    start = st.cash
    step(st, [db("S1", div=1.0, mark=100.0, signal=100.0)], ledger=led)
    pend = [PendingOrder(Operation.CLOSE_POSITION, "S1", "T1", 0, 10, "d1",
                         Reason.EXIT_TRAILING_STOP.value)]
    step(st, [db("S1", open_=110.0, mark=110.0, signal=110.0)], pending=pend,
         ledger=led, session="d2")
    assert led.reconcile_cash(start) == pytest.approx(st.cash)
