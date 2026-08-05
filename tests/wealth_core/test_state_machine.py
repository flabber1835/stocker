"""Wealth Core v1 state machine — the mandatory acceptance tests.

Wealth Core's edge is entirely path-dependent: a winner compounds because it was
never trimmed, never rank-exited and never reviewed twice. Every one of those is
an off-by-one away from a different strategy, and none of them would show up as
an obvious failure — the backtest would simply return a different number and look
just as plausible. So the boundaries are pinned exactly: 118/119/120, 20/21/22,
and 29.99%/30.00%/30.01%.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.engine import (
    Op,
    Operation,
    Reason,
    SecurityBar,
    WealthCoreConfig,
    apply_entry,
    apply_exit,
    decide,
    score_universe,
    whole_shares,
)
from stock_strategy_shared.wealth_core.marks import Mark, MarkStatus
from stock_strategy_shared.wealth_core.state import (
    COOLDOWN_SESSIONS,
    REVIEW_AGE_SESSIONS,
    STOP_RETENTION,
    HoldingEpisode,
    PortfolioState,
)

CFG = WealthCoreConfig()
SID, VER = "stocker_wealth_core_v1", 1


def rising(n=127, start=100.0, step=1.0):
    return [start + step * i for i in range(n)]


def bar(i, step=1.0, closes=None, eligible=True):
    return SecurityBar(f"S{i}", f"T{i}", f"I{i}",
                       closes if closes is not None else rising(step=step),
                       eligible=eligible)


def cur(**px):
    """CURRENT marks from {security_id: raw close} — the ordinary case."""
    return {k: Mark(k, MarkStatus.CURRENT, raw_mark_close=v) for k, v in px.items()}


def run(state, bars, marks=None, session="2026-08-03"):
    if marks is None:
        marks = cur(**{b.security_id: b.closes[-1] for b in bars})
        # Held securities absent from `bars` still need a mark, or the equity
        # gate correctly blocks and the test measures the wrong thing.
        for e in state.episodes.values():
            marks.setdefault(e.security_id,
                             Mark(e.security_id, MarkStatus.CURRENT,
                                  raw_mark_close=e.entry_split_adjusted_price))
    return decide(session=session, state=state, bars=bars, marks=marks, cfg=CFG,
                  strategy_id=SID, strategy_version=VER)


def ops_of(d, kind):
    return [o for o in d.operations if o.operation == kind]


def seat(state, slot, sec="S1", tic="T1", entry=100.0, peak=100.0, age=0,
         shares=10, reviewed=False, issuer=None):
    """Place a holding directly, so a test can start at an exact age rather than
    simulating 119 sessions to reach one."""
    state.slots[slot].occupied_by = sec
    state.episodes[slot] = HoldingEpisode(
        security_id=sec, ticker=tic, issuer_id=issuer or f"I_{sec}", slot_id=slot,
        signal_date="2026-01-01", entry_date="2026-01-02", entry_raw_open=entry,
        entry_split_adjusted_price=entry, initial_shares=shares,
        current_shares=shares, episode_peak_split_adjusted_close=peak,
        market_sessions_held=age, review_completed=reviewed)
    state.initialized = True
    return state.episodes[slot]


# ── the one-time 119-session review (spec §8) ───────────────────────────────

class TestReviewBoundary:
    def _run_at_age(self, age, last_close, entry=100.0, qualified=False):
        # last_close must stay ABOVE peak*0.70 or the trailing stop fires first
        # and the review is never reached — which is correct behaviour, and was
        # exactly what these fixtures did on the first run.
        st = PortfolioState.fresh(10_000.0)
        seat(st, 0, age=age, entry=entry, peak=max(entry, last_close))
        closes = rising()[:-1] + [last_close]
        # A qualified holding must sit in the top decile of the scored universe;
        # a disqualified one must not. Padding with strong names pushes it out.
        others = [bar(i, step=5.0) for i in range(2, 20)] if not qualified else []
        bars = [SecurityBar("S1", "T1", "I_S1", closes)] + others
        return st, run(st, bars)

    @pytest.mark.parametrize("age,expect_review", [
        (REVIEW_AGE_SESSIONS - 1, False),   # 118
        (REVIEW_AGE_SESSIONS, True),        # 119
        (REVIEW_AGE_SESSIONS + 1, False),   # 120 — the window has passed
    ])
    def test_review_fires_only_at_exactly_119(self, age, expect_review):
        """MANDATORY 118/119/120. `==` not `>=`: the review happens once, and a
        holding that somehow passes 119 without being reviewed is not reviewed
        retroactively — it is held, which is the safe direction."""
        st, d = self._run_at_age(age, last_close=75.0)   # underwater, no stop
        closed = ops_of(d, Operation.CLOSE_POSITION)
        assert bool(closed) is expect_review

    def test_a_holding_is_not_reviewed_before_119(self):
        st, d = self._run_at_age(REVIEW_AGE_SESSIONS - 1, last_close=75.0)
        holds = ops_of(d, Operation.HOLD_UNCHANGED)
        assert holds and holds[0].reason is Reason.HOLD_NOT_REVIEW_ELIGIBLE

    @pytest.mark.parametrize("underwater,qualified,exits", [
        (True,  False, True),    # MANDATORY: underwater AND disqualified -> exit
        (True,  True,  False),   # MANDATORY: underwater but still qualified -> survive
        (False, False, False),   # MANDATORY: disqualified but profitable -> survive
        (False, True,  False),   # healthy -> survive
    ])
    def test_every_combination_at_review(self, underwater, qualified, exits):
        """The exit is an AND of two conditions. Three of the four cells survive,
        which is the whole asymmetry the strategy rests on — a naive 'sell the
        losers' or 'sell the laggards' rule gets two of them wrong."""
        st = PortfolioState.fresh(10_000.0)
        closes = rising()                      # rises to 226; recent return > 0
        last = closes[-1]
        # UNDERWATER is set by the ENTRY price, not by making the price fall.
        # The first attempt used a falling last close, which also fails the
        # freshness gate — so the "underwater but still qualified" cell was
        # unreachable and the test was checking a case that cannot exist.
        entry = 300.0 if underwater else 100.0

        if not qualified:
            # Spike close[t-21] so the recent 21-session return is negative.
            # That fails freshness regardless of where the decile cutoff lands.
            closes = list(closes)
            closes[-22] = last * 3.0

        # peak == last close, so the 30% stop is not armed and the REVIEW is
        # what decides.
        seat(st, 0, age=REVIEW_AGE_SESSIONS, entry=entry, peak=last)
        bars = [SecurityBar("S1", "T1", "I_S1", closes)]

        d = run(st, bars)
        assert bool(ops_of(d, Operation.CLOSE_POSITION)) is exits
        if exits:
            assert ops_of(d, Operation.CLOSE_POSITION)[0].reason is Reason.EXIT_REVIEW_WEAKNESS

    def test_a_survivor_is_NEVER_rank_reviewed_again(self):
        """MANDATORY. Passing review completes it permanently. Without this the
        strategy degenerates into a daily rank exit and every compounding winner
        is sold the first time it slips out of the decile."""
        st = PortfolioState.fresh(10_000.0)
        ep = seat(st, 0, age=REVIEW_AGE_SESSIONS, entry=100.0, peak=100.0)
        run(st, [SecurityBar("S1", "T1", "I_S1", rising()[:-1] + [400.0])])
        assert ep.review_completed is True

        # Now make it look terrible: underwater and disqualified. It must hold.
        ep.market_sessions_held = REVIEW_AGE_SESSIONS + 50
        bars = [SecurityBar("S1", "T1", "I_S1", rising()[:-1] + [90.0])] + \
               [bar(i, step=5.0) for i in range(2, 20)]
        d2 = run(st, bars)
        assert not ops_of(d2, Operation.CLOSE_POSITION)
        assert ops_of(d2, Operation.HOLD_UNCHANGED)[0].reason is \
            Reason.HOLD_REVIEW_ALREADY_COMPLETED


# ── the 30% episode-peak stop (spec §9) ─────────────────────────────────────

class TestTrailingStop:
    def _stop_run(self, decline):
        st = PortfolioState.fresh(10_000.0)
        peak = 200.0
        last = peak * (1.0 - decline)
        seat(st, 0, age=5, entry=100.0, peak=peak)
        return run(st, [SecurityBar("S1", "T1", "I_S1", rising()[:-1] + [last])])

    @pytest.mark.parametrize("decline,triggers", [
        (0.2999, False),   # MANDATORY: 29.99% does NOT trigger
        (0.3000, True),    # MANDATORY: exactly 30% DOES
        (0.3001, True),
    ])
    def test_the_boundary_is_inclusive_at_thirty_percent(self, decline, triggers):
        d = self._stop_run(decline)
        closed = ops_of(d, Operation.CLOSE_POSITION)
        assert bool(closed) is triggers
        if triggers:
            assert closed[0].reason is Reason.EXIT_TRAILING_STOP

    def test_the_peak_ratchets_up_and_never_down(self):
        ep = HoldingEpisode("S1", "T1", "I1", 0, "d", "d", 100.0, 100.0, 10, 10, 100.0)
        ep.observe_close(150.0); assert ep.episode_peak_split_adjusted_close == 150.0
        ep.observe_close(120.0); assert ep.episode_peak_split_adjusted_close == 150.0
        assert ep.market_sessions_held == 2

    def test_the_stop_applies_before_review_age(self):
        """The stop is unconditional; the review is once. A holding 40% off its
        peak at age 5 exits, without waiting 114 more sessions."""
        assert ops_of(self._stop_run(0.40), Operation.CLOSE_POSITION)

    def test_a_new_episode_resets_the_peak(self):
        """Spec §9: the peak 'does not reset except when a new holding episode
        begins'. Re-entry after a stop must not inherit the old high-water mark,
        or the fresh position would start already stopped out.

        Under the locked convention the new episode's peak is UNSET at the fill
        and only becomes real at the entry session's close."""
        st = PortfolioState.fresh(100_000.0)
        seat(st, 0, sec="S1", tic="T1", entry=100.0, peak=500.0)
        apply_exit(st, slot_id=0, raw_open=100.0, cfg=CFG)
        apply_entry(st, op=Op(Operation.OPEN_SLOT_POSITION, Reason.ENTRY_DURABLE_RANK,
                              0, "S1", "T1", 10),
                    session="d2", signal_session="d1", raw_open=100.0,
                    split_adjusted_price=100.0, issuer_id="I_S1", cfg=CFG)
        assert st.episodes[0].episode_peak_split_adjusted_close is None
        st.episodes[0].observe_entry_close(102.0)
        assert st.episodes[0].episode_peak_split_adjusted_close == 102.0

    def test_the_stop_cannot_fire_before_an_owned_close_exists(self):
        """LOCKED convention. Between the opening fill and that session's close
        the position has no peak, so a close-based stop has nothing to measure
        against. Firing here would use a price the position never owned."""
        st = PortfolioState.fresh(100_000.0)
        apply_entry(st, op=Op(Operation.OPEN_SLOT_POSITION, Reason.ENTRY_DURABLE_RANK,
                              0, "S1", "T1", 10),
                    session="d2", signal_session="d1", raw_open=100.0,
                    split_adjusted_price=100.0, issuer_id="I_S1", cfg=CFG)
        ep = st.episodes[0]
        assert ep.stop_triggered(1.0) is False        # a 99% collapse still cannot fire
        ep.observe_entry_close(100.0)
        assert ep.stop_triggered(70.0) is True

    @pytest.mark.parametrize("entry_close,expect_peak", [
        (140.0, 140.0),   # entry-day move far ABOVE the entry open
        (60.0, 60.0),     # entry-day move far BELOW the entry open
    ])
    def test_a_large_entry_day_move_sets_the_peak_from_the_CLOSE(
            self, entry_close, expect_peak):
        """MANDATED by the locked convention. The peak is the entry session's
        CLOSE, not the entry open and not the signal-day close — so a stock that
        gapped up and closed higher has a HIGHER peak than its entry price, and
        one that collapsed intraday has a LOWER one. Seeding from the open would
        get the second case wrong in the dangerous direction: the stop would be
        armed 40% above where the position actually closed."""
        st = PortfolioState.fresh(100_000.0)
        apply_entry(st, op=Op(Operation.OPEN_SLOT_POSITION, Reason.ENTRY_DURABLE_RANK,
                              0, "S1", "T1", 10),
                    session="d2", signal_session="d1", raw_open=100.0,
                    split_adjusted_price=100.0, issuer_id="I_S1", cfg=CFG)
        st.episodes[0].observe_entry_close(entry_close)
        assert st.episodes[0].episode_peak_split_adjusted_close == expect_peak
        # ...and the stop measures from THAT peak, not from 100.
        assert st.episodes[0].stop_triggered(expect_peak * 0.70) is True
        assert st.episodes[0].stop_triggered(expect_peak * 0.7001) is False

    def test_the_entry_close_does_NOT_age_the_holding(self):
        """Entry close is age 0 (locked). observe_entry_close must not increment
        the age, or every holding would review one session early."""
        st = PortfolioState.fresh(100_000.0)
        apply_entry(st, op=Op(Operation.OPEN_SLOT_POSITION, Reason.ENTRY_DURABLE_RANK,
                              0, "S1", "T1", 10),
                    session="d2", signal_session="d1", raw_open=100.0,
                    split_adjusted_price=100.0, issuer_id="I_S1", cfg=CFG)
        st.episodes[0].observe_entry_close(105.0)
        assert st.episodes[0].market_sessions_held == 0


# ── cooldowns (spec §10) ────────────────────────────────────────────────────

class TestCooldown:
    @pytest.mark.parametrize("elapsed,blocked", [
        (COOLDOWN_SESSIONS - 1, True),    # 20 — still blocked
        (COOLDOWN_SESSIONS, False),       # 21 — available
        (COOLDOWN_SESSIONS + 1, False),   # 22
    ])
    def test_slot_cooldown_expires_after_exactly_21(self, elapsed, blocked):
        """MANDATORY 20/21/22, on the SLOT."""
        st = PortfolioState.fresh(100_000.0)
        st.slots[0].cooldown_sessions_elapsed = elapsed
        assert st.slots[0].in_cooldown is blocked
        assert (0 in st.ready_slots()) is (not blocked)

    @pytest.mark.parametrize("elapsed,blocked", [
        (COOLDOWN_SESSIONS - 1, True), (COOLDOWN_SESSIONS, False),
        (COOLDOWN_SESSIONS + 1, False),
    ])
    def test_ticker_cooldown_expires_after_exactly_21(self, elapsed, blocked):
        """MANDATORY 20/21/22, on the TICKER — a separate lock, so the name
        cannot re-enter through a different slot."""
        st = PortfolioState.fresh(100_000.0)
        st.ticker_cooldowns["T1"] = elapsed
        assert st.ticker_in_cooldown("T1") is blocked

    def test_an_exit_starts_BOTH_cooldowns(self):
        st = PortfolioState.fresh(100_000.0)
        seat(st, 3, sec="S9", tic="T9")
        apply_exit(st, slot_id=3, raw_open=100.0, cfg=CFG)
        assert st.slots[3].in_cooldown and st.ticker_in_cooldown("T9")

    def test_COOLDOWN_CASH_IS_NOT_REDISTRIBUTED(self):
        """MANDATORY. The slot stays cash. A strategy that spread it across the
        survivors would be scaling into existing positions, which §12 forbids —
        and the drawdown profile would change without any rule appearing to."""
        st = PortfolioState.fresh(100_000.0)
        seat(st, 0, sec="S1", tic="T1", shares=100)
        before = {s: e.current_shares for s, e in st.episodes.items()}
        seat(st, 1, sec="S2", tic="T2", shares=50)
        apply_exit(st, slot_id=0, raw_open=100.0, cfg=CFG)
        cash_after = st.cash
        d = run(st, [SecurityBar("S2", "T2", "I_S2", rising())])
        assert st.episodes[1].current_shares == 50           # untouched
        assert st.cash == cash_after                          # nothing spent on survivors
        assert ops_of(d, Operation.KEEP_SLOT_IN_COOLDOWN)

    def test_a_different_ready_slot_can_still_be_filled(self):
        """Spec §10: cooldown locks ITS slot, not the portfolio."""
        st = PortfolioState.fresh(100_000.0)
        st.slots[0].cooldown_sessions_elapsed = 3
        st.initialized = True
        d = run(st, [bar(1)])
        assert ops_of(d, Operation.OPEN_SLOT_POSITION)
        assert ops_of(d, Operation.OPEN_SLOT_POSITION)[0].slot_id != 0


# ── admissions and sizing (spec §6, §7) ─────────────────────────────────────

class TestAdmissions:
    def test_initial_construction_may_fill_every_slot(self):
        st = PortfolioState.fresh(1_000_000.0)
        bars = [bar(i, step=1.0 + i * 0.05) for i in range(60)]
        d = run(st, bars)
        assert len(ops_of(d, Operation.OPEN_SLOT_POSITION)) > 1

    def test_ONE_ADMISSION_PER_SESSION_after_initialization(self):
        """MANDATORY."""
        st = PortfolioState.fresh(1_000_000.0)
        st.initialized = True
        bars = [bar(i, step=1.0 + i * 0.05) for i in range(60)]
        assert len(ops_of(run(st, bars), Operation.OPEN_SLOT_POSITION)) == 1

    def test_a_winner_above_4_percent_is_NOT_RESIZED(self):
        """MANDATORY, and the core of the strategy. The holding is worth ~40% of
        the book; nothing trims it and no operation touches it beyond HOLD."""
        st = PortfolioState.fresh(10_000.0)
        last = rising()[-1]
        seat(st, 0, sec="S1", tic="T1", entry=10.0, peak=last, shares=100, age=5)
        marks = cur(S1=last)
        d = decide(session="s", state=st, bars=[SecurityBar("S1", "T1", "I_S1", rising())],
                   marks=marks, cfg=CFG, strategy_id=SID, strategy_version=VER)
        assert st.equity_view(marks).resolved_equity > 30_000   # ~69% of the book
        assert st.episodes[0].current_shares == 100
        assert [o.operation for o in d.operations if o.slot_id == 0] == \
            [Operation.HOLD_UNCHANGED]

    def test_sizing_is_four_percent_in_whole_shares_including_cost(self):
        """10bps is inside the affordability test, not applied afterwards —
        otherwise every admission overdraws by the commission."""
        assert whole_shares(100_000.0, 100.0, 100_000.0, CFG) == 39   # 4000/100.1
        assert whole_shares(100_000.0, 100.0, 500.0, CFG) == 4        # cash-bound
        assert whole_shares(100_000.0, 0.0, 100_000.0, CFG) == 0

    def test_an_already_held_issuer_is_not_admitted_twice(self):
        """Spec §1: one position per economic issuer, so two share classes of
        the same company cannot both be held."""
        st = PortfolioState.fresh(1_000_000.0)
        st.initialized = True
        seat(st, 0, sec="S1", tic="T1", issuer="ACME")
        b = SecurityBar("S2", "T2", "ACME", rising(step=9.0))
        assert not ops_of(run(st, [b]), Operation.OPEN_SLOT_POSITION)

    def test_a_slot_emptying_this_session_is_not_refilled_same_session(self):
        """Spec §11: a position sold at an open must not be implicitly replaced
        using same-open information. Its cash is not available yet."""
        st = PortfolioState.fresh(0.0)
        seat(st, 0, sec="S1", tic="T1", entry=100.0, peak=200.0, shares=10)
        for i in range(1, 25):
            st.slots[i].cooldown_sessions_elapsed = 0        # only slot 0 could open
        bars = [SecurityBar("S1", "T1", "I_S1", rising()[:-1] + [100.0]),
                bar(2, step=9.0)]
        d = run(st, bars)
        assert ops_of(d, Operation.CLOSE_POSITION)
        assert not ops_of(d, Operation.OPEN_SLOT_POSITION)


# ── the decile is computed over ELIGIBLE names only (spec §3) ───────────────

def test_the_leadership_population_uses_only_eligible_securities():
    """MANDATORY. Including ineligible names in the ranked pool would move the
    cutoff and admit securities that are not in the leadership set of anything
    the strategy can trade.

    Under the CERTIFIED correction the count is max(25, ceil(N x 0.10)), so with
    10 eligible names all 10 lead — the assertion that matters is that none of
    the 50 strong INELIGIBLE names appear, not the size of the set."""
    strong_ineligible = [SecurityBar(f"X{i}", f"X{i}", f"IX{i}", rising(step=9.0),
                                     eligible=False, eligibility_reason="REJECT_LIQUIDITY")
                         for i in range(50)]
    eligible = [bar(i, step=1.0 + i * 0.1) for i in range(10)]
    scored = score_universe(eligible + strong_ineligible, CFG)
    in_top = [s for s in scored if s.in_top_decile]
    assert len(in_top) == 10                      # max(25, ceil(1)) capped at 10
    assert all(not s.security_id.startswith("X") for s in in_top)


# ── serialisation and replay (spec §12) ─────────────────────────────────────

class TestSerialisationAndReplay:
    def _mid_flight(self):
        st = PortfolioState.fresh(50_000.0)
        seat(st, 0, sec="S1", tic="T1", entry=100.0, peak=180.0, age=77, shares=25)
        seat(st, 1, sec="S2", tic="T2", entry=50.0, peak=60.0,
             age=REVIEW_AGE_SESSIONS - 2, shares=40, reviewed=True)
        st.slots[2].cooldown_sessions_elapsed = 13
        st.ticker_cooldowns["T9"] = 13
        st.session_index = 512
        return st

    def test_round_trip_preserves_every_field(self):
        """MANDATORY: restart mid-holding AND mid-cooldown. Age, peak, review
        flag and both cooldown clocks all survive, because losing any one of
        them silently changes the strategy."""
        st = self._mid_flight()
        back = PortfolioState.from_dict(st.to_dict())
        assert back.state_hash() == st.state_hash()
        assert back.episodes[0].market_sessions_held == 77
        assert back.episodes[0].episode_peak_split_adjusted_close == 180.0
        assert back.episodes[1].review_completed is True
        assert back.slots[2].cooldown_sessions_elapsed == 13
        assert back.ticker_cooldowns["T9"] == 13

    def test_a_restarted_run_makes_THE_SAME_DECISION(self):
        st = self._mid_flight()
        bars = [SecurityBar("S1", "T1", "I_S1", rising()), bar(5)]
        marks = cur(S1=150.0, S2=55.0, S5=120.0)
        a = decide(session="s", state=st, bars=bars, marks=marks, cfg=CFG,
                   strategy_id=SID, strategy_version=VER)
        b = decide(session="s", state=PortfolioState.from_dict(st.to_dict()),
                   bars=bars, marks=marks, cfg=CFG, strategy_id=SID,
                   strategy_version=VER)
        assert a.decision_hash() == b.decision_hash()

    def test_the_state_hash_is_order_independent(self):
        """A hash that depends on dict insertion order would differ between a
        live process and a replay that rebuilt the same state."""
        st = self._mid_flight()
        shuffled = PortfolioState.from_dict(st.to_dict())
        shuffled.ticker_cooldowns = dict(reversed(list(shuffled.ticker_cooldowns.items())))
        assert shuffled.state_hash() == st.state_hash()

    def test_review_age_survives_a_restart_at_the_boundary(self):
        """The nastiest replay case: restart at age 118, advance one session, and
        the review must fire exactly as if the process had never stopped."""
        st = PortfolioState.fresh(10_000.0)
        seat(st, 0, age=REVIEW_AGE_SESSIONS - 1, entry=100.0, peak=100.0)
        back = PortfolioState.from_dict(st.to_dict())
        back.age_one_session({"S1": 50.0})
        assert back.episodes[0].market_sessions_held == REVIEW_AGE_SESSIONS
        assert back.episodes[0].review_due is True


# ── determinism (spec §5, mandatory) ────────────────────────────────────────

def test_INPUT_ROW_ORDER_CANNOT_CHANGE_DECISIONS():
    """MANDATORY. Identical data in a different order must give an identical
    decision hash — otherwise the backtester and the live book can disagree
    purely because their queries returned rows differently."""
    bars = [bar(i, step=1.0 + i * 0.07) for i in range(40)]
    marks = cur(**{b.security_id: 100.0 for b in bars})

    def once(rows):
        st = PortfolioState.fresh(1_000_000.0)
        st.initialized = True
        return decide(session="s", state=st, bars=rows, marks=marks, cfg=CFG,
                      strategy_id=SID, strategy_version=VER).decision_hash()

    h = once(bars)
    assert once(list(reversed(bars))) == h
    assert once(bars[13:] + bars[:13]) == h


def test_the_config_hash_changes_when_a_knob_changes():
    assert WealthCoreConfig().config_hash() != \
        WealthCoreConfig(entry_weight=0.05).config_hash()


def test_session_ageing_advances_holdings_and_both_cooldowns():
    st = PortfolioState.fresh(10_000.0)
    seat(st, 0, age=10, peak=100.0)
    st.slots[1].cooldown_sessions_elapsed = COOLDOWN_SESSIONS - 1
    st.ticker_cooldowns["TX"] = COOLDOWN_SESSIONS - 1
    st.age_one_session({"S1": 150.0})
    assert st.episodes[0].market_sessions_held == 11
    assert st.episodes[0].episode_peak_split_adjusted_close == 150.0
    assert st.slots[1].cooldown_sessions_elapsed is None      # expired
    assert "TX" not in st.ticker_cooldowns
    assert st.session_index == 1
