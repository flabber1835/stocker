"""The terminal-settlement waterfall.

WHAT THESE ARE ABOUT. The corpus cannot settle anything: Sharadar ACTIONS states
a deal SIZE and a counterparty, never a per-share consideration, so
`completeness()` refuses all 19,216 delisted securities. The waterfall is the
only route by which a delisted holding leaves the book, which makes every branch
of it load-bearing rather than a fallback.

THE DISTINCTION EVERY TEST HERE GUARDS: an event that is DOCUMENTED with
unreadable terms is not the same as a security with NO record at all. Collapsing
them writes off 19,216 known acquisitions at zero — TMHC holders were paid
$6.77bn by Berkshire — and does it while the run reports clean completion. A zero
is much harder to spot than a freeze: a freeze stops the run, a zero merely
lowers the return.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.settlement import (
    C1_GRACE_SESSIONS,
    MARK_RECENCY_SESSIONS,
    ORPHAN_TIMEOUT_SESSIONS,
    SETTLEMENT_COUNTERS,
    SettlementSource,
    counter_for,
    empty_counters,
    resolve_settlement,
    tally,
    tally_pending_entry,
)
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms


def _terms(**over):
    """Terms as the corpus actually produces them: a known event with NO
    per-share consideration (defect D2)."""
    base = dict(session="2023-02-02", security_id="P:1",
                kind=TerminalKind.CASH_MERGER, cash_per_share=None,
                reference="actions/acquisitionby deal_value_musd=6768.8")
    base.update(over)
    return TerminalTerms(**base)


def _exact(**over):
    return _terms(cash_per_share=54.0, **over)


# ── 1. exact terms win ───────────────────────────────────────────────────────

class TestExactTermsWin:

    def test_stated_cash_settles_exactly(self):
        d = resolve_settlement(terms=_exact(), shares=100,
                               last_valid_mark=40.0,
                               sessions_since_last_valid_print=0)
        assert d.source is SettlementSource.EXACT_TERMS
        assert d.price_per_share == 54.0
        assert d.settlement_exact is True and d.terms_complete is True

    def test_a_stated_zero_write_off_settles_with_NO_price(self):
        """A WRITE_OFF needs no price — the zero IS the term. `price_per_share`
        stays None rather than 0.0 so it is not confused with an orphan zero,
        which is a decision made in the absence of terms."""
        d = resolve_settlement(terms=_terms(kind=TerminalKind.WRITE_OFF),
                               shares=100)
        assert d.source is SettlementSource.EXACT_TERMS
        assert d.settlement_exact is True
        assert d.price_per_share is None

    def test_exact_terms_beat_an_available_mark_and_an_available_print(self):
        """Otherwise a proxy could silently outrank real terms."""
        d = resolve_settlement(terms=_exact(), shares=100, last_valid_mark=40.0,
                               executable_price=41.0,
                               sessions_since_last_valid_print=0)
        assert d.price_per_share == 54.0


# ── 2. a real print beats any proxy ──────────────────────────────────────────

class TestARealPrintBeatsAProxy:

    def test_an_executable_print_settles_as_a_REAL_transaction(self):
        """Once the grace has expired — see TestAnAnnouncementIsNotATerminalDay
        for why it may not settle before then."""
        d = resolve_settlement(terms=_terms(), shares=100, executable_price=12.5,
                               last_valid_mark=40.0,
                               sessions_since_last_valid_print=0,
                               sessions_pending_terms=C1_GRACE_SESSIONS)
        assert d.source is SettlementSource.EXECUTABLE_PRINT
        assert d.price_per_share == 12.5
        assert d.settlement_exact is False, (
            "a real fill is not EXACT TERMS — the consideration is still unknown")

    def test_it_outranks_the_last_mark(self):
        d = resolve_settlement(terms=_terms(), shares=100, executable_price=12.5,
                               last_valid_mark=99.0,
                               sessions_since_last_valid_print=0,
                               sessions_pending_terms=C1_GRACE_SESSIONS)
        assert d.price_per_share == 12.5

    def test_a_print_settles_when_no_mark_makes_CARRYING_possible(self):
        """The fall-through the grace deliberately leaves open. With no
        trustworthy mark there is nothing to carry at, so a real print is
        better than blocking — even inside the grace window."""
        d = resolve_settlement(terms=_terms(), shares=100, executable_price=12.5,
                               last_valid_mark=None,
                               sessions_since_last_valid_print=0,
                               sessions_pending_terms=0)
        assert d.source is SettlementSource.EXECUTABLE_PRINT
        assert d.price_per_share == 12.5

    def test_a_print_settles_when_the_mark_is_too_stale_to_carry(self):
        d = resolve_settlement(terms=_terms(), shares=100, executable_price=12.5,
                               last_valid_mark=40.0,
                               sessions_since_last_valid_print=MARK_RECENCY_SESSIONS + 1,
                               sessions_pending_terms=0)
        assert d.source is SettlementSource.EXECUTABLE_PRINT

    @pytest.mark.parametrize("bad", [0.0, -1.0, None, float("nan"),
                                     float("inf"), "x"])
    def test_an_UNUSABLE_print_is_not_a_print(self, bad):
        """No print, no fill. A zero or non-finite price would execute a trade
        against a security with no market.

        Asserted on the PRICE as well as the source: the discriminating claim is
        that the bogus value never reaches the position, and a source check
        alone would pass if the price leaked through on a different branch.
        """
        d = resolve_settlement(terms=_terms(), shares=100, executable_price=bad,
                               last_valid_mark=40.0,
                               sessions_since_last_valid_print=1)
        assert d.source is not SettlementSource.EXECUTABLE_PRINT
        assert d.price_per_share == 40.0

    @pytest.mark.parametrize("bad", [0.0, -1.0, None, float("nan"),
                                     float("inf"), "x"])
    def test_an_UNUSABLE_print_is_not_a_print_after_the_grace_either(self, bad):
        """The same claim on the settling branch. Without this the parametrised
        case above only ever exercises the carry, and a bogus price could still
        reach the one decision that converts a holding to cash."""
        d = resolve_settlement(terms=_terms(), shares=100, executable_price=bad,
                               last_valid_mark=40.0,
                               sessions_since_last_valid_print=1,
                               sessions_pending_terms=C1_GRACE_SESSIONS)
        assert d.source is SettlementSource.LAST_TRUSTWORTHY_MARK
        assert d.price_per_share == 40.0


# ── 3. C1: a KNOWN event with unreadable terms ───────────────────────────────

class TestC1KnownEventUnreadableTerms:

    def test_a_recent_mark_settles_and_is_flagged_DERIVED(self):
        """AFTER the grace expires. Before it, the same inputs CARRY — see
        TestC1GracePeriod."""
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=1,
                               sessions_pending_terms=C1_GRACE_SESSIONS)
        assert d.source is SettlementSource.LAST_TRUSTWORTHY_MARK
        assert d.price_per_share == 40.0
        assert d.event_known is True and d.terms_complete is False
        assert d.settlement_exact is False
        assert d.reason == "DERIVED_TERMINAL_SETTLEMENT_LAST_MARK"

    def test_the_recency_boundary_INSIDE_settles(self):
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=MARK_RECENCY_SESSIONS,
                               sessions_pending_terms=C1_GRACE_SESSIONS)
        assert d.source is SettlementSource.LAST_TRUSTWORTHY_MARK

    def test_the_recency_boundary_OUTSIDE_refuses(self):
        """A stock that last traded long before its effective date has no
        credible proxy. Checked rather than assumed, because off by one here
        silently changes which securities get valued."""
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=MARK_RECENCY_SESSIONS + 1)
        assert d.source is SettlementSource.UNRESOLVED
        assert d.reason == "MARK_OUTSIDE_RECENCY_WINDOW"

    def test_a_stale_mark_is_NOT_downgraded_to_a_zero(self):
        """THE trap. The event is documented and holders were paid something, so
        zero is a WORSE answer than refusing — and it would be invisible."""
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=500)
        assert d.source is not SettlementSource.ZERO_ORPHAN
        assert d.price_per_share is None

    def test_no_mark_at_all_refuses(self):
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=None,
                               sessions_since_last_valid_print=0)
        assert d.source is SettlementSource.UNRESOLVED
        assert d.reason == "NO_TRUSTWORTHY_MARK"

    def test_UNKNOWN_staleness_settles_nothing(self):
        """Ignorance moves nothing in either direction — the same third-state
        rule the crash brake's `evaluable` encodes. Unknown staleness cannot
        satisfy a bound, so it must not be read as satisfying one."""
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=None)
        assert d.source is SettlementSource.UNRESOLVED

    def test_UNKNOWN_staleness_does_not_CARRY_either(self):
        """The grace period must not become a way around the third-state rule.
        An unknown staleness cannot satisfy the recency bound, so it cannot
        support a carrying mark any more than a settling one."""
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=None,
                               sessions_pending_terms=0)
        assert d.source is SettlementSource.UNRESOLVED
        assert d.price_per_share is None


# ── 3b. C1's grace period: a MARK is not a SETTLEMENT ────────────────────────

class TestC1GracePeriod:
    """The owner decision of 2026-08-08.

    The first implementation settled C1 on the FIRST session a terms-less event
    appeared, which forecloses terms arriving after the announcement. The golden
    fixture's SEC_STRANDED case — announced with no terms, resolved for $54 cash
    later — rejected it, and was right to. These tests are that scenario at unit
    scale, so a regression is caught here rather than by a fixture hash.
    """

    def test_a_terms_less_event_CARRIES_rather_than_settling(self):
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=0,
                               sessions_pending_terms=0)
        assert d.source is SettlementSource.PENDING_TERMS
        assert d.reason == "TERMINAL_PENDING_TERMS"

    def test_a_carry_VALUES_the_position_without_converting_it(self):
        """The distinction the whole state exists for. The mark supplies a
        price, so equity stays measurable and admissions continue; but the
        holding does not settle, so the slot is not released."""
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=0,
                               sessions_pending_terms=0)
        assert d.price_per_share == 40.0, "equity must stay measurable"
        assert d.settles is False, "a carry must never release the holding"
        assert d.carries is True
        assert d.settlement_exact is False

    def test_a_carry_is_NOT_unresolved(self):
        """Conflating the two is what forced the false choice between freezing
        the book and inventing a settlement. UNRESOLVED has no price and stops
        admissions; PENDING_TERMS has one and does not."""
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=0,
                               sessions_pending_terms=0)
        assert d.source is not SettlementSource.UNRESOLVED
        assert d.price_per_share is not None

    @pytest.mark.parametrize("n", list(range(C1_GRACE_SESSIONS)))
    def test_it_carries_for_every_session_of_the_grace(self, n):
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=0,
                               sessions_pending_terms=n)
        assert d.source is SettlementSource.PENDING_TERMS

    def test_the_grace_boundary_EXPIRES_into_a_settlement(self):
        """Off by one here decides whether a deal is carried forever or settled
        a session early, and neither is visible in a summary."""
        last = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                                  sessions_since_last_valid_print=0,
                                  sessions_pending_terms=C1_GRACE_SESSIONS - 1)
        first = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                                   sessions_since_last_valid_print=0,
                                   sessions_pending_terms=C1_GRACE_SESSIONS)
        assert last.source is SettlementSource.PENDING_TERMS
        assert first.source is SettlementSource.LAST_TRUSTWORTHY_MARK

    def test_the_grace_does_not_run_forever(self):
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=0,
                               sessions_pending_terms=10_000)
        assert d.source is SettlementSource.LAST_TRUSTWORTHY_MARK

    def test_EXACT_TERMS_arriving_during_the_grace_win(self):
        """The entire point of waiting. SEC_STRANDED resolves for $54 cash after
        being announced with none, and the carry must not have foreclosed it."""
        d = resolve_settlement(terms=_terms(cash_per_share=54.0), shares=100,
                               last_valid_mark=40.0,
                               sessions_since_last_valid_print=0,
                               sessions_pending_terms=3)
        assert d.source is SettlementSource.EXACT_TERMS
        assert d.price_per_share == 54.0
        assert d.settlement_exact is True

    def test_an_EXECUTABLE_PRINT_during_the_grace_does_NOT_settle(self):
        """AN ANNOUNCEMENT IS NOT A TERMINAL DAY.

        The waterfall as first documented ranked the print above the carry, on
        the reasoning that a real transaction beats valuing an unresolved claim.
        True on a terminal day and false on every other day — and nothing in the
        data distinguishes them. A contested bid trades right up to closing, so
        an announced-but-unpriced deal still prints an ordinary executable
        close; taking it liquidates the position at market on the announcement
        and forecloses the terms, which is the very defect the grace exists to
        prevent, reached through a different branch.
        """
        d = resolve_settlement(terms=_terms(), shares=100, executable_price=12.5,
                               last_valid_mark=40.0,
                               sessions_since_last_valid_print=0,
                               sessions_pending_terms=3)
        assert d.source is SettlementSource.PENDING_TERMS
        assert d.price_per_share == 40.0, "carried at the mark, not the print"
        assert d.settles is False

    def test_a_STALE_mark_refuses_rather_than_carrying(self):
        """THE trap the grace period could have introduced. A mark too stale to
        settle on is also too stale to carry on: admissions size at 4% of
        equity, so an untrustworthy carry propagates into every position opened
        afterwards. Refusing is the conservative direction."""
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=MARK_RECENCY_SESSIONS + 1,
                               sessions_pending_terms=0)
        assert d.source is SettlementSource.UNRESOLVED
        assert d.reason == "MARK_OUTSIDE_RECENCY_WINDOW"
        assert d.price_per_share is None

    def test_no_mark_at_all_refuses_rather_than_carrying(self):
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=None,
                               sessions_since_last_valid_print=0,
                               sessions_pending_terms=0)
        assert d.source is SettlementSource.UNRESOLVED
        assert d.reason == "NO_TRUSTWORTHY_MARK"

    def test_the_grace_is_SHORTER_than_the_orphan_timeout(self):
        """Predeclared asymmetry: under C1 an event is KNOWN to exist, so less
        waiting is warranted than for an undocumented disappearance. Asserted so
        a later edit to either constant cannot quietly invert the relationship."""
        assert C1_GRACE_SESSIONS < ORPHAN_TIMEOUT_SESSIONS

    def test_a_carry_never_reaches_the_orphan_zero(self):
        """The module's founding distinction, restated for the new state. A
        documented deal being carried must never be reclassified as an
        undocumented disappearance, whatever the session counts say."""
        for pending in (0, C1_GRACE_SESSIONS - 1, C1_GRACE_SESSIONS,
                        ORPHAN_TIMEOUT_SESSIONS + 50):
            d = resolve_settlement(
                terms=_terms(), shares=100, last_valid_mark=40.0,
                sessions_since_last_valid_print=0,
                sessions_pending_terms=pending)
            assert d.source is not SettlementSource.ZERO_ORPHAN
            assert d.event_known is True


# ── 4. C2: NO record at all ──────────────────────────────────────────────────

class TestC2NoRecordAtAll:

    def test_absence_past_the_timeout_writes_off_at_zero(self):
        d = resolve_settlement(terms=None, shares=100,
                               sessions_since_last_valid_print=ORPHAN_TIMEOUT_SESSIONS)
        assert d.source is SettlementSource.ZERO_ORPHAN
        assert d.price_per_share == 0.0
        assert d.event_known is False
        assert d.reason == "ORPHANED_UNRESOLVED_NO_ACTION"

    def test_one_missing_day_is_STILL_BLOCKED(self):
        """The grace period is the whole reason there is a timeout rather than an
        immediate write-off: a halt and a dead security look identical on day
        one."""
        d = resolve_settlement(terms=None, shares=100,
                               sessions_since_last_valid_print=1)
        assert d.source is SettlementSource.UNRESOLVED
        assert d.reason == "WITHIN_ORPHAN_GRACE_PERIOD"
        assert d.price_per_share is None

    def test_the_timeout_boundary_one_session_short(self):
        d = resolve_settlement(terms=None, shares=100,
                               sessions_since_last_valid_print=ORPHAN_TIMEOUT_SESSIONS - 1)
        assert d.source is SettlementSource.UNRESOLVED

    def test_a_recent_MARK_does_not_rescue_an_undocumented_absence(self):
        """C1's proxy is licensed by a DOCUMENTED event. With no record there is
        nothing to license valuing the claim, so the mark is irrelevant."""
        d = resolve_settlement(terms=None, shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=ORPHAN_TIMEOUT_SESSIONS)
        assert d.source is SettlementSource.ZERO_ORPHAN
        assert d.price_per_share == 0.0

    def test_UNKNOWN_absence_duration_settles_nothing(self):
        d = resolve_settlement(terms=None, shares=100,
                               sessions_since_last_valid_print=None)
        assert d.source is SettlementSource.UNRESOLVED
        assert d.reason == "ABSENCE_DURATION_UNKNOWN"


# ── THE falsifier ────────────────────────────────────────────────────────────

class TestTheTwoPopulationsNeverMix:

    @pytest.mark.parametrize("stale", [0, 1, 19, 20, 100, 5000])
    def test_incomplete_terms_NEVER_reach_the_orphan_zero(self, stale):
        """THE test this module exists for, swept across the whole staleness
        range including far past the orphan timeout.

        Every ACTIONS-sourced termination has incomplete terms (defect D2), so if
        any of them could fall through to C2, all 19,216 documented acquisitions
        would settle at zero — and the run would look finished rather than
        blocked.
        """
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=stale)
        assert d.source is not SettlementSource.ZERO_ORPHAN, (
            f"a documented event with unreadable terms reached the orphan zero "
            f"at staleness {stale}")
        assert d.event_known is True

    def test_a_documented_event_ALWAYS_reports_event_known(self):
        for stale in (None, 0, 500):
            for mark in (None, 40.0):
                d = resolve_settlement(terms=_terms(), shares=100,
                                       last_valid_mark=mark,
                                       sessions_since_last_valid_print=stale)
                assert d.event_known is True

    def test_an_UNDOCUMENTED_absence_never_claims_an_event(self):
        for stale in (None, 0, 500):
            d = resolve_settlement(terms=None, shares=100, last_valid_mark=40.0,
                                   sessions_since_last_valid_print=stale)
            assert d.event_known is False
            assert d.terms_complete is False

    def test_only_EXACT_TERMS_is_ever_flagged_exact(self):
        """`settlement_exact` is what stops a reader treating a proxy as
        vendor-supplied consideration."""
        cases = [
            resolve_settlement(terms=_terms(), shares=1, executable_price=5.0),
            resolve_settlement(terms=_terms(), shares=1, last_valid_mark=5.0,
                               sessions_since_last_valid_print=0),
            resolve_settlement(terms=None, shares=1,
                               sessions_since_last_valid_print=999),
            resolve_settlement(terms=None, shares=1,
                               sessions_since_last_valid_print=0),
        ]
        assert all(d.settlement_exact is False for d in cases)
        assert resolve_settlement(terms=_exact(), shares=1).settlement_exact


# ── the constants are PREDECLARED, not tuned ─────────────────────────────────

def test_the_timeout_is_longer_than_the_recency_window():
    """They answer different questions and the orphan grace must be the more
    patient of the two: writing a position off is irreversible, valuing a
    documented claim is not."""
    assert ORPHAN_TIMEOUT_SESSIONS > MARK_RECENCY_SESSIONS


def test_the_recency_window_excludes_the_corpus_real_trading_holes():
    """The two genuine one-company holes in bt_prices are 238 and 269 sessions.
    A window that admitted those would settle a live company's holding off a
    year-old print."""
    assert MARK_RECENCY_SESSIONS < 238


# ── reporting: an uncounted source is an invisible one ───────────────────────

class TestTheCountersAreTotal:

    def test_every_source_has_a_counter(self):
        for src in SettlementSource:
            assert counter_for(src) in SETTLEMENT_COUNTERS

    def test_the_counters_start_at_ZERO_rather_than_absent(self):
        """A missing key reads as 'not measured'. The difference between 'no
        orphan write-offs happened' and 'nobody looked' is the difference this
        whole module preserves."""
        c = empty_counters()
        for k in SETTLEMENT_COUNTERS:
            assert c[k] == 0

    def test_a_settlement_records_its_dollar_contribution(self):
        c = empty_counters()
        tally(c, resolve_settlement(terms=_exact(), shares=100), 100)
        assert c["exact_terminal_settlements"] == 1
        assert c["exact_terminal_settlements_notional"] == pytest.approx(5400.0)

    def test_an_orphan_zero_is_COUNTED_even_though_it_pays_nothing(self):
        """Its notional is 0.0, so only the COUNT reveals it. A category that
        contributes no dollars is exactly the one an operator would otherwise
        never notice."""
        c = empty_counters()
        tally(c, resolve_settlement(terms=None, shares=100,
                                    sessions_since_last_valid_print=999), 100)
        assert c["orphan_zero_writeoffs"] == 1
        assert c["orphan_zero_writeoffs_notional"] == 0.0

    def test_unresolved_events_are_counted_but_carry_no_notional(self):
        c = empty_counters()
        tally(c, resolve_settlement(terms=None, shares=100,
                                    sessions_since_last_valid_print=1), 100)
        assert c["unresolved_terminal_events"] == 1
        assert "unresolved_terminal_events_notional" not in c


class TestAPendingCarryIsCountedOnce:
    """A PENDING_TERMS decision recurs every session of the grace period. The
    counter answers "how many deals are we carrying and for how much", so
    counting each recurrence would report one ten-session carry as ten events
    with ten times the notional — inflating precisely the number an operator
    would use to judge how much of equity is provisional.
    """

    def _carry(self):
        return resolve_settlement(terms=_terms(), shares=100,
                                  last_valid_mark=40.0,
                                  sessions_since_last_valid_print=0,
                                  sessions_pending_terms=0)

    def test_plain_tally_REFUSES_a_pending_decision(self):
        """Raises rather than over-counting. A silent double-count would look
        like a busier corpus, which is not an error anyone goes looking for."""
        with pytest.raises(ValueError, match="tally_pending_entry"):
            tally(empty_counters(), self._carry(), 100)

    def test_entry_is_counted_with_its_provisional_notional(self):
        c = empty_counters()
        tally_pending_entry(c, self._carry(), 100, already_pending=False)
        assert c["pending_terms_carried"] == 1
        assert c["pending_terms_carried_notional"] == pytest.approx(4000.0)

    def test_a_continuing_carry_is_NOT_re_counted(self):
        c = empty_counters()
        tally_pending_entry(c, self._carry(), 100, already_pending=False)
        for _ in range(C1_GRACE_SESSIONS):
            tally_pending_entry(c, self._carry(), 100, already_pending=True)
        assert c["pending_terms_carried"] == 1
        assert c["pending_terms_carried_notional"] == pytest.approx(4000.0)

    def test_a_restart_mid_grace_does_not_re_count(self):
        """`already_pending` is read from persisted state precisely so a
        redeploy in the middle of a grace period does not re-count the carry it
        was already tracking."""
        c = empty_counters()
        tally_pending_entry(c, self._carry(), 100, already_pending=True)
        assert c["pending_terms_carried"] == 0

    def test_it_refuses_a_non_pending_decision(self):
        with pytest.raises(ValueError):
            tally_pending_entry(empty_counters(),
                                resolve_settlement(terms=_exact(), shares=100),
                                100, already_pending=False)


# ── the counters must actually be PRODUCED, not merely producible ────────────

class TestTheCountersReachTheRunResult:
    """REGRESSION. `step_session` took a `settlement_counters` argument and
    nothing ever passed one, so every run reported no counters at all and the
    certification acceptance criterion "the settlement counters PRESENT" was
    unmeetable. The plumbing existed and looked wired; it recorded nothing.

    That is the same shape as the `intent reconciliation skipped` trap — a
    reporting path that is deployed, silent, and mistaken for coverage.
    """

    def _run(self):
        from stock_strategy_shared.wealth_core.golden import golden_scenario
        from stock_strategy_shared.wealth_core.run import run_sessions
        g = golden_scenario()
        return g, run_sessions(
            sessions=g.sessions, bars_by_session=g.bars_by_session, meta=g.meta,
            starting_cash=g.starting_cash, terminal_events=g.terminal_events)

    def test_a_run_reports_every_counter(self):
        _, r = self._run()
        for k in SETTLEMENT_COUNTERS:
            assert k in r.settlement_counters, (
                f"{k} absent — a missing key reads as 'not measured', which is "
                f"the distinction these counters exist to preserve")

    def test_the_counters_are_not_all_zero_on_a_scenario_with_terminals(self):
        """The falsifier for the defect itself. The golden scenario applies five
        terminal events, so a run reporting nothing but zeros has not counted
        them — which is exactly what shipped."""
        _, r = self._run()
        counted = sum(r.settlement_counters[k] for k in SETTLEMENT_COUNTERS)
        assert counted > 0, (
            "every counter is zero on a scenario with five terminal events: "
            "the tally is not being called")

    def test_the_settling_paths_are_counted_not_only_the_carry(self):
        """The first fix wired ONLY `tally_pending_entry`, so `pending_terms_carried`
        moved and every settlement stayed at zero — a counter set that looked
        alive while under-reporting the thing it exists to report."""
        _, r = self._run()
        c = r.settlement_counters
        assert c["exact_terminal_settlements"] > 0, (
            "the golden scenario settles terminals on exact terms; a zero here "
            "means only the pending branch is tallied")

    def test_the_counters_NEVER_reach_the_parity_hash(self):
        """They are a REPORT. The settlement events themselves are already
        hashed through the ledger, so a counter disagreeing with its run shows
        up there; hashing the report as well would add a second artefact to
        re-pin for no extra evidence — and would make an operator-facing
        summary field a parity input."""
        _, r = self._run()
        assert "settlement_counters" not in r.to_dict()
        before = r.result_hash()
        r.settlement_counters["orphan_zero_writeoffs"] = 999_999
        assert r.result_hash() == before, (
            "mutating a derived counter moved the parity hash")
