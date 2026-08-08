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
    MARK_RECENCY_SESSIONS,
    ORPHAN_TIMEOUT_SESSIONS,
    SETTLEMENT_COUNTERS,
    SettlementSource,
    counter_for,
    empty_counters,
    resolve_settlement,
    tally,
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
        d = resolve_settlement(terms=_terms(), shares=100, executable_price=12.5,
                               last_valid_mark=40.0,
                               sessions_since_last_valid_print=0)
        assert d.source is SettlementSource.EXECUTABLE_PRINT
        assert d.price_per_share == 12.5
        assert d.settlement_exact is False, (
            "a real fill is not EXACT TERMS — the consideration is still unknown")

    def test_it_outranks_the_last_mark(self):
        d = resolve_settlement(terms=_terms(), shares=100, executable_price=12.5,
                               last_valid_mark=99.0,
                               sessions_since_last_valid_print=0)
        assert d.price_per_share == 12.5

    @pytest.mark.parametrize("bad", [0.0, -1.0, None, float("nan"),
                                     float("inf"), "x"])
    def test_an_UNUSABLE_print_is_not_a_print(self, bad):
        """No print, no fill. A zero or non-finite price would execute a trade
        against a security with no market."""
        d = resolve_settlement(terms=_terms(), shares=100, executable_price=bad,
                               last_valid_mark=40.0,
                               sessions_since_last_valid_print=1)
        assert d.source is SettlementSource.LAST_TRUSTWORTHY_MARK


# ── 3. C1: a KNOWN event with unreadable terms ───────────────────────────────

class TestC1KnownEventUnreadableTerms:

    def test_a_recent_mark_settles_and_is_flagged_DERIVED(self):
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=1)
        assert d.source is SettlementSource.LAST_TRUSTWORTHY_MARK
        assert d.price_per_share == 40.0
        assert d.event_known is True and d.terms_complete is False
        assert d.settlement_exact is False
        assert d.reason == "DERIVED_TERMINAL_SETTLEMENT_LAST_MARK"

    def test_the_recency_boundary_INSIDE_settles(self):
        d = resolve_settlement(terms=_terms(), shares=100, last_valid_mark=40.0,
                               sessions_since_last_valid_print=MARK_RECENCY_SESSIONS)
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
