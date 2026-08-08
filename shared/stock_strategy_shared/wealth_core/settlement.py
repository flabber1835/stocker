"""Wealth Core v1 — the TERMINAL SETTLEMENT WATERFALL. PURE: no DB, no clock.

WHY THIS EXISTS, and it is a fact about the DATA rather than a preference:

    Sharadar ACTIONS gives event IDENTITY and AGGREGATE TRANSACTION VALUE. It
    gives no holder-level settlement terms — no cash per share, no exchange
    ratio, at any action type.

`value` is the deal size in millions (identical on the `delisted` and
`acquisitionby` rows of one event; TMHC/Berkshire 6768.8, NUVL/GSK 9792.6) and
`contraticker` is the acquirer's symbol only when the acquirer is public. So
`completeness()` refuses EVERY one of the 19,216 delisted securities, whichever
branch it takes. A settlement policy is therefore not an optional fallback for
rare cases: it is the ONLY route by which a delisted holding can leave the book.

Measured cost of not having one: a 2021-2023 chain rehearsal blocked from
2023-02 to the end of its window — 218 of 753 sessions, 29% of the run — because
one held security stopped printing and no ACTIONS row could resolve it.

THIS IS AN ACCOUNTING POLICY, NOT AN ALPHA CHOICE. It is deliberately NOT
modelled on the wind tunnel's `SimParams.delist_recovery_pct` (0.70), which is a
bias correction for securities whose terms ARE modelled. Here the contractual
consideration is unknowable from the corpus. So the rule sits outside the
strategy, is stated in advance, and is never tuned. See docs/architecture.md
"terminal settlement and orphan resolution".

WHY THE GRACE OUTRANKS AN EXECUTABLE PRINT (amendment, 2026-08-08). The waterfall
as first documented put "executable terminal-day print" ABOVE the pending state,
on the reasoning that a real transaction beats valuing an unresolved claim. True
on a terminal day, and false on every other day — and nothing in the data marks
which is which. A contested bid TRADES right up to closing, so a security whose
deal was merely ANNOUNCED still prints an ordinary, fully executable close; taking
it settles the position at market on announcement day and forecloses the terms
that arrive afterwards. That is the same foreclosure defect the grace period was
introduced to fix, reached through a different branch.

The golden fixture caught it, for the third time: its SEC_STRANDED case is
explicitly a security that "keeps PRINTING and stays tradeable throughout",
announced with no terms at one session and resolved for $61.50 cash ten sessions
later. Under print-before-grace it liquidated at 90.98 on the announcement.

So the print settles only once there is nothing left to wait for — after the
grace expires, or where no trustworthy mark makes carrying possible at all. An
ANNOUNCEMENT IS NOT A TERMINAL DAY, and no ordering that treats them alike can be
right.

THE ONE DISTINCTION EVERYTHING RESTS ON:

    incomplete terms   the event is DOCUMENTED and the terms are unreadable
    no record at all   nothing in the corpus says this security ever terminated

Collapsing them would write off 19,216 KNOWN acquisitions at zero — holders of
TMHC were paid $6.77bn — while the run reported clean completion rather than a
block. A zero is far harder to notice than a freeze: a freeze stops the run, a
zero merely lowers the return. Every branch below keeps them apart, and
`test_incomplete_terms_NEVER_reach_the_orphan_zero` is the falsifier.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from stock_strategy_shared.wealth_core.terminal import TerminalTerms

#: Sessions a security may be absent before its holding is treated as dead.
#: PREDECLARED and never optimised against Wealth Core returns — a timeout fitted
#: to the equity curve is a strategy parameter wearing an accounting label. Its
#: only job is to separate a halt or a vendor gap from a security that is gone.
ORPHAN_TIMEOUT_SESSIONS = 20

#: How stale the last mark may be and still settle a KNOWN terminal event.
#: Chosen from market-data semantics, not from returns: a security that last
#: traded three months before its effective date has no credible settlement
#: proxy, and using one reintroduces the invented-trade objection in a different
#: costume. Two genuine one-company trading holes in the corpus run 238 and 269
#: sessions, which is the scale this bound exists to exclude.
MARK_RECENCY_SESSIONS = 10

#: How long a DOCUMENTED terminal event with unreadable terms is CARRIED before
#: its last trustworthy mark becomes a settlement. Deliberately SHORTER than
#: ORPHAN_TIMEOUT_SESSIONS: under C1 the event is known to exist, so less
#: waiting is warranted than for an undocumented disappearance.
#:
#: This exists because the first implementation settled C1 on the FIRST session
#: a terms-less event appeared, which forecloses terms that arrive after the
#: announcement. Harmless over a frozen corpus, where terms never arrive at all;
#: wrong on a live book, where a documented announcement routinely precedes the
#: consideration by days or weeks. The golden fixture's SEC_STRANDED case —
#: announced with no terms, resolved for $54 cash later — rejected it, and was
#: right to.
#:
#: PREDECLARED accounting semantics and FROZEN. 5 vs 10 vs 20 is not chosen on
#: CAGR. See docs/architecture.md "C1 needs its OWN grace period".
C1_GRACE_SESSIONS = 10


class SettlementSource(str, Enum):
    """WHERE a settlement price came from. Persisted, never inferred.

    A cash inflow with no provenance invites a reader six months later to assume
    the vendor supplied acquisition consideration. It did not, and cannot.
    """
    EXACT_TERMS = "EXACT_TERMS"
    """The deal terms themselves. The only `settlement_exact` source."""

    EXECUTABLE_PRINT = "EXECUTABLE_PRINT"
    """A real tradeable print on the terminal session — an actual transaction,
    not a proxy."""

    PENDING_TERMS = "PENDING_TERMS"
    """C1, DURING the grace period. A KNOWN event whose terms are unreadable,
    CARRIED at its last trustworthy mark.

    This is the state that distinguishes a MARK from a SETTLEMENT, and it is not
    a shade of UNRESOLVED. The mark VALUES the position without CONVERTING it to
    cash: equity stays measurable (so admissions may continue), the position
    stays economically unresolved, the slot is NOT released, and exact terms or
    an executable print arriving later REPLACE the provisional valuation with no
    retrospective mutation of anything already settled.

    Conflating this with UNRESOLVED is what forced the false choice between
    freezing the book and inventing a settlement."""

    LAST_TRUSTWORTHY_MARK = "LAST_TRUSTWORTHY_MARK"
    """C1, AFTER the grace expires. A KNOWN event whose terms never became
    readable, settled at the most recent valid mark inside the recency window.
    NOT a simulated sale: no transaction occurred, and the claim being valued is
    real."""

    ZERO_ORPHAN = "ZERO_ORPHAN"
    """C2. No terminal record at all, absent beyond the timeout. Zero because
    last-mark liquidation here would invent a trade that could not have happened
    — there was no market and no documented event — and a percentage haircut is a
    free parameter that gets tuned until the backtest improves."""

    UNRESOLVED = "UNRESOLVED"
    """Nothing may be settled. The holding is PRESERVED and admissions stop. An
    unknown outcome is not a loss."""


#: Sources that remove the holding from the book.
#: PENDING_TERMS is deliberately absent: it carries a position, it does not
#: settle one. A source that valued a holding and also released its slot would
#: be the mark/settlement conflation this module exists to keep apart.
SETTLING_SOURCES = frozenset({
    SettlementSource.EXACT_TERMS, SettlementSource.EXECUTABLE_PRINT,
    SettlementSource.LAST_TRUSTWORTHY_MARK, SettlementSource.ZERO_ORPHAN})

#: Sources that VALUE an open holding without settling it. Equity is measurable
#: (so admissions continue) while the position stays economically unresolved.
CARRYING_SOURCES = frozenset({SettlementSource.PENDING_TERMS})


@dataclass(frozen=True)
class SettlementDecision:
    """One security's resolution, with the provenance a reader needs to judge it.

    `price_per_share` is None only when nothing settles. A ZERO_ORPHAN settles at
    exactly 0.0, which is a decision — distinguishable from None, which is the
    absence of one. Conflating those is how a block becomes a silent write-off.
    """
    source: SettlementSource
    price_per_share: Optional[float]
    event_known: bool
    terms_complete: bool
    settlement_exact: bool
    reason: str
    detail: dict = field(default_factory=dict)

    @property
    def settles(self) -> bool:
        return self.source in SETTLING_SOURCES

    @property
    def carries(self) -> bool:
        """The holding stays open and IS valued. Distinct from `settles` (open
        -> closed) and from neither (blocked, `resolved_equity` goes None)."""
        return self.source in CARRYING_SOURCES

    def provenance(self) -> dict:
        """The audit record. `event_source` is supplied by the caller because
        only it knows which corpus the event came from."""
        return {"settlement_source": self.source.value,
                "event_known": self.event_known,
                "terms_complete": self.terms_complete,
                "settlement_exact": self.settlement_exact,
                "price_per_share": self.price_per_share,
                # NAMESPACED. A bare `reason` collides with the block reason the
                # caller already returns (MISSING_CASH_PER_SHARE and friends),
                # and dict-spread order decided which survived — so the audit
                # said NO_TRUSTWORTHY_MARK where the terms gap belonged. Two
                # different questions, two different keys.
                "settlement_reason": self.reason, **self.detail}


def _positive(x) -> bool:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return f == f and f not in (float("inf"), float("-inf")) and f > 0


def resolve_settlement(*,
                       terms: Optional[TerminalTerms],
                       shares: int,
                       last_valid_mark: Optional[float] = None,
                       sessions_since_last_valid_print: Optional[int] = None,
                       executable_price: Optional[float] = None,
                       sessions_pending_terms: int = 0,
                       orphan_timeout_sessions: int = ORPHAN_TIMEOUT_SESSIONS,
                       mark_recency_sessions: int = MARK_RECENCY_SESSIONS,
                       c1_grace_sessions: int = C1_GRACE_SESSIONS,
                       ) -> SettlementDecision:
    """The waterfall, in one place, for both engines.

    `terms=None` means NO TERMINAL RECORD EXISTS — the C2 population. It does not
    mean "terms were unreadable"; that is `terms` present and incomplete, and the
    two lead to opposite outcomes.

    `sessions_since_last_valid_print` is None when unknown. Unknown staleness can
    never satisfy a bound, so it resolves to UNRESOLVED on both the C1 and C2
    branches — ignorance settles nothing, in either direction. That is the same
    rule the crash brake's `evaluable` third state encodes, and for the same
    reason: one boolean must not answer both "the evidence says no" and "there is
    no evidence".

    `sessions_pending_terms` is how many sessions this security has ALREADY been
    carried under a documented terms-less event. 0 means the event is new this
    session. It is a separate count from `sessions_since_last_valid_print`
    because the two measure different things and routinely diverge: a security
    can keep printing every session while its announced deal has no terms, in
    which case staleness stays 0 forever and the grace period would never expire
    if it were driven off staleness.
    """
    stale = sessions_since_last_valid_print

    # ── 1. exact terms, whenever genuinely known ────────────────────────────
    if terms is not None:
        complete, why = terms.completeness(shares)
        if complete:
            # WRITE_OFF carries no price and needs none: a stated zero is a term.
            px = terms.cash_per_share
            return SettlementDecision(
                source=SettlementSource.EXACT_TERMS,
                price_per_share=(float(px) if px is not None else None),
                event_known=True, terms_complete=True, settlement_exact=True,
                reason="EXACT_TERMS", detail={"kind": terms.kind.value,
                                              "reference": terms.reference})

        # ── 2. the GRACE PERIOD, BEFORE ANY settling branch ─────────────────
        # Ordering is the whole rule, and it outranks the executable print as
        # well as the last mark. See the module docstring, "WHY THE GRACE
        # OUTRANKS AN EXECUTABLE PRINT" — an ANNOUNCEMENT is not a terminal day,
        # and settling into an ordinary session's print forecloses the terms
        # exactly as an immediate last-mark settlement did.
        #
        # A trustworthy mark inside the recency window is what makes carrying
        # possible at all: a mark too stale to settle on is also too stale to
        # CARRY on, because every admission sizes at 4% of equity, so a bad
        # carry propagates into every position opened afterwards. Where there is
        # no such mark, fall through — an executable print can still settle.
        if _positive(last_valid_mark) and stale is not None \
                and stale <= mark_recency_sessions \
                and sessions_pending_terms < c1_grace_sessions:
            return SettlementDecision(
                source=SettlementSource.PENDING_TERMS,
                price_per_share=float(last_valid_mark),
                event_known=True, terms_complete=False, settlement_exact=False,
                reason="TERMINAL_PENDING_TERMS",
                detail={"kind": terms.kind.value, "terms_gap": why,
                        "sessions_since_last_valid_print": stale,
                        "sessions_pending_terms": sessions_pending_terms,
                        "c1_grace_sessions": c1_grace_sessions})

        # ── 3. a real executable print BEATS any proxy ──────────────────────
        # Once there is nothing left to wait for, an actual transaction is
        # preferable to valuing an unresolved claim.
        if _positive(executable_price):
            return SettlementDecision(
                source=SettlementSource.EXECUTABLE_PRINT,
                price_per_share=float(executable_price),
                event_known=True, terms_complete=False, settlement_exact=False,
                reason="EXECUTABLE_TERMINAL_PRINT",
                detail={"kind": terms.kind.value, "terms_gap": why,
                        "sessions_pending_terms": sessions_pending_terms})

        # ── 4. C1: known event, terms unreadable, nothing left to wait for ──
        if not _positive(last_valid_mark):
            return SettlementDecision(
                source=SettlementSource.UNRESOLVED, price_per_share=None,
                event_known=True, terms_complete=False, settlement_exact=False,
                reason="NO_TRUSTWORTHY_MARK",
                detail={"kind": terms.kind.value, "terms_gap": why})

        # Deliberately NOT downgraded to a zero: the event is documented and
        # holders were paid something, so zero would be a worse answer than
        # refusing.
        if stale is None or stale > mark_recency_sessions:
            return SettlementDecision(
                source=SettlementSource.UNRESOLVED, price_per_share=None,
                event_known=True, terms_complete=False, settlement_exact=False,
                reason="MARK_OUTSIDE_RECENCY_WINDOW",
                detail={"kind": terms.kind.value, "terms_gap": why,
                        "sessions_since_last_valid_print": stale,
                        "mark_recency_sessions": mark_recency_sessions})

        # ── 3c. the grace expired and nothing better ever arrived ───────────
        return SettlementDecision(
            source=SettlementSource.LAST_TRUSTWORTHY_MARK,
            price_per_share=float(last_valid_mark),
            event_known=True, terms_complete=False, settlement_exact=False,
            reason="DERIVED_TERMINAL_SETTLEMENT_LAST_MARK",
            detail={"kind": terms.kind.value, "terms_gap": why,
                    "sessions_since_last_valid_print": stale,
                    "sessions_pending_terms": sessions_pending_terms,
                    "c1_grace_sessions": c1_grace_sessions})

    # ── 4. C2: NO terminal record at all ────────────────────────────────────
    # Reached only when `terms is None`. An incomplete-terms event can never
    # arrive here — every branch above returns — which is the whole point: the
    # zero is for securities whose fate is undocumented, not for the 19,216
    # documented acquisitions whose per-share consideration the vendor omits.
    if stale is None:
        return SettlementDecision(
            source=SettlementSource.UNRESOLVED, price_per_share=None,
            event_known=False, terms_complete=False, settlement_exact=False,
            reason="ABSENCE_DURATION_UNKNOWN")
    if stale < orphan_timeout_sessions:
        return SettlementDecision(
            source=SettlementSource.UNRESOLVED, price_per_share=None,
            event_known=False, terms_complete=False, settlement_exact=False,
            reason="WITHIN_ORPHAN_GRACE_PERIOD",
            detail={"sessions_since_last_valid_print": stale,
                    "orphan_timeout_sessions": orphan_timeout_sessions})
    return SettlementDecision(
        source=SettlementSource.ZERO_ORPHAN, price_per_share=0.0,
        event_known=False, terms_complete=False, settlement_exact=False,
        reason="ORPHANED_UNRESOLVED_NO_ACTION",
        detail={"sessions_since_last_valid_print": stale,
                "orphan_timeout_sessions": orphan_timeout_sessions})


#: Summary keys every run must report, so the uncertainty is visible rather than
#: the dataset being made to look more complete than it is. A run over ~2000
#: names for three years reporting none of these has not measured what it claims.
SETTLEMENT_COUNTERS = (
    "exact_terminal_settlements",
    "market_exit_terminal_settlements",
    "derived_last_mark_settlements",
    "orphan_zero_writeoffs",
    "unresolved_terminal_events",
    # Counted SEPARATELY from both settlements and blocks, because it is
    # neither. A run carrying twenty pending deals is in a materially different
    # condition from one that settled twenty at their last mark, and folding
    # them together would hide exactly the population whose valuation is
    # provisional.
    #
    # ONE PER SECURITY THAT ENTERS THE STATE, not one per carry-session. The
    # decision recurs every session of the grace period, so tallying each one
    # would report a single ten-session carry as ten events and inflate the
    # notional tenfold. The caller tallies only on ENTRY; `tally_pending_entry`
    # is the guard that makes that hard to get wrong.
    "pending_terms_carried",
)

#: Counters that are POSITION-EVENT counts rather than settlement counts, so a
#: total settled + blocked reconciliation does not double-count them.
NON_SETTLING_COUNTERS = frozenset({
    "unresolved_terminal_events", "pending_terms_carried"})

_COUNTER_BY_SOURCE = {
    SettlementSource.EXACT_TERMS: "exact_terminal_settlements",
    SettlementSource.EXECUTABLE_PRINT: "market_exit_terminal_settlements",
    SettlementSource.LAST_TRUSTWORTHY_MARK: "derived_last_mark_settlements",
    SettlementSource.ZERO_ORPHAN: "orphan_zero_writeoffs",
    SettlementSource.UNRESOLVED: "unresolved_terminal_events",
    SettlementSource.PENDING_TERMS: "pending_terms_carried",
}


def counter_for(source: SettlementSource) -> str:
    """Total, so a new source cannot be silently uncounted."""
    try:
        return _COUNTER_BY_SOURCE[source]
    except KeyError:  # pragma: no cover - guarded by a test
        raise ValueError(
            f"no summary counter for {source!r}. Every settlement source must be "
            f"counted; an uncounted one is invisible in exactly the reports that "
            f"exist to make proxy settlements visible.")


def empty_counters() -> dict:
    """Zeroed counters plus per-category dollar contribution.

    Zeroed rather than absent: a missing key reads as "not measured", and the
    difference between "no orphan write-offs happened" and "nobody looked" is the
    difference this whole module exists to preserve.
    """
    d: dict = {k: 0 for k in SETTLEMENT_COUNTERS}
    d.update({f"{k}_notional": 0.0 for k in SETTLEMENT_COUNTERS
              if k != "unresolved_terminal_events"})
    return d


def tally(counters: dict, decision: SettlementDecision, shares: int) -> dict:
    """Record one decision. Mutates and returns `counters`.

    A PENDING_TERMS decision recurs every session of the grace period, so
    passing every one of them here counts one carry as many. Use
    `tally_pending_entry` for that source; this function raises rather than
    silently over-counting, because an inflated provisional-notional is exactly
    the number a reader would use to judge how much of equity is uncertain.
    """
    if decision.source is SettlementSource.PENDING_TERMS:
        raise ValueError(
            "PENDING_TERMS recurs every session of the grace period; tally it "
            "once on ENTRY via tally_pending_entry(), or a single ten-session "
            "carry is reported as ten events with ten times the notional.")
    return _tally_unchecked(counters, decision, shares)


def _tally_unchecked(counters: dict, decision: SettlementDecision,
                     shares: int) -> dict:
    key = counter_for(decision.source)
    counters[key] = counters.get(key, 0) + 1
    if key != "unresolved_terminal_events":
        px = decision.price_per_share or 0.0
        nk = f"{key}_notional"
        counters[nk] = round(counters.get(nk, 0.0) + shares * float(px), 2)
    return counters


def tally_pending_entry(counters: dict, decision: SettlementDecision,
                        shares: int, *, already_pending: bool) -> dict:
    """Record a PENDING_TERMS carry, but only the session it BEGINS.

    `already_pending` comes from the caller's persisted state, so a restart in
    the middle of a grace period does not re-count the carry it was already
    tracking.
    """
    if decision.source is not SettlementSource.PENDING_TERMS:
        raise ValueError(f"not a pending-terms decision: {decision.source!r}")
    if already_pending:
        return counters
    return _tally_unchecked(counters, decision, shares)


__all__ = ["C1_GRACE_SESSIONS", "CARRYING_SOURCES", "MARK_RECENCY_SESSIONS",
           "NON_SETTLING_COUNTERS", "ORPHAN_TIMEOUT_SESSIONS",
           "SETTLEMENT_COUNTERS", "SETTLING_SOURCES", "SettlementDecision",
           "SettlementSource", "counter_for", "empty_counters",
           "resolve_settlement", "tally", "tally_pending_entry"]
