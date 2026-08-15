"""Canonical coalescing for mapped SHARADAR terminal evidence.

This module deliberately lives beside, not inside, ``wealth_core``.  It is a
data-normalization contract shared by Sentinel and the canonical backtester;
it does not apply a terminal event or change Wealth Core state.

Sharadar commonly represents one termination with a reason-specific row plus a
bare ``delisted`` row.  The economic key is therefore the effective exchange
session and permanent security id.  Source action, ticker and vendor date are
provenance, never independent permission to apply the termination again.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from stock_strategy_shared.wealth_core.terminal import TerminalTerms


@dataclass(frozen=True)
class TerminalCandidate:
    """One mapped source row plus its caller-owned audit payload."""

    terms: TerminalTerms
    source_key: str
    payload: Any = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class TerminalCoalescingOutcome:
    """The one economic-key verdict for a group of mapped source rows."""

    key: tuple[str, str]
    selected: TerminalCandidate | None
    collapsed: tuple[TerminalCandidate, ...] = ()
    conflicting: tuple[TerminalCandidate, ...] = ()


def terminal_terms_economics(terms: TerminalTerms) -> tuple:
    """Mapped economics, excluding source-only reference text."""

    return (
        terms.session,
        terms.security_id,
        terms.kind.value,
        terms.cash_per_share,
        terms.delivered_security_id,
        terms.delivered_ticker,
        terms.delivered_issuer_id,
        terms.exchange_ratio,
        terms.cash_in_lieu_price_per_delivered_share,
    )


def terminal_terms_supported_rank(terms: TerminalTerms) -> tuple[bool, ...]:
    """The canonical backtester's supported-information ordering.

    ACTIONS ``value`` is absent by design: it is transaction-size provenance,
    not cash per share, an exchange ratio, or settlement consideration.
    """

    return (
        terms.delivered_security_id is not None,
        terms.delivered_ticker is not None,
        terms.exchange_ratio is not None,
        terms.cash_per_share is not None,
    )


def terminal_terms_richness(terms: TerminalTerms) -> tuple:
    """The canonical total ordering used to retain the richest record.

    Reference length/text only break ties after supported information.  They
    choose which complete provenance string survives; they never supply an
    economic term.
    """

    return (
        *terminal_terms_supported_rank(terms),
        len(terms.reference or ""),
        terms.reference or "",
    )


def _candidate_order(candidate: TerminalCandidate) -> tuple:
    return (terminal_terms_richness(candidate.terms), candidate.source_key)


def coalesce_terminal_terms(
        candidates: Iterable[TerminalCandidate],
) -> tuple[TerminalCoalescingOutcome, ...]:
    """Return one deterministic verdict per ``(session, security_id)``.

    Less-informative rows are subsumed by the richest supported level.  If two
    candidates at that level disagree economically, no candidate is selected:
    choosing either would invent an ordering for irreconcilable evidence.
    """

    groups: dict[tuple[str, str], list[TerminalCandidate]] = {}
    for candidate in candidates:
        terms = candidate.terms
        key = (str(terms.session), str(terms.security_id))
        groups.setdefault(key, []).append(candidate)

    outcomes: list[TerminalCoalescingOutcome] = []
    for key in sorted(groups):
        ordered = sorted(groups[key], key=_candidate_order)
        richest_supported = max(
            terminal_terms_supported_rank(candidate.terms)
            for candidate in ordered)
        richest = [
            candidate for candidate in ordered
            if terminal_terms_supported_rank(candidate.terms)
            == richest_supported
        ]
        signatures = {
            terminal_terms_economics(candidate.terms)
            for candidate in richest
        }
        if len(signatures) != 1:
            outcomes.append(TerminalCoalescingOutcome(
                key=key, selected=None, conflicting=tuple(ordered)))
            continue

        selected = max(richest, key=_candidate_order)
        outcomes.append(TerminalCoalescingOutcome(
            key=key,
            selected=selected,
            collapsed=tuple(
                candidate for candidate in ordered if candidate is not selected),
        ))
    return tuple(outcomes)


__all__ = [
    "TerminalCandidate",
    "TerminalCoalescingOutcome",
    "coalesce_terminal_terms",
    "terminal_terms_economics",
    "terminal_terms_richness",
    "terminal_terms_supported_rank",
]
