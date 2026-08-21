"""Shared split-orientation semantics for production and canonical replay.

Sharadar ACTIONS values are not consistently oriented: a value greater than
one can be either a forward multiplier or a reverse-split denominator.  The
independently derived price-domain ratio selects the direct or reciprocal
orientation.  Disagreement applies no share transformation.

This module deliberately owns both the tolerance and the resolver.  Keeping a
copy in each corpus adapter allowed production and the canonical replay to make
different economic decisions from identical source rows.
"""
from __future__ import annotations


# Clean split fractions agree well inside one percent.  A larger discrepancy
# is conflicting share-count evidence, not rounding noise.
SPLIT_AGREEMENT_TOLERANCE = 0.01
# Ratios this close to one are quote/cross-vintage noise, not independent
# evidence that a share-count event occurred.  Both corpus adapters use the
# same two-percent event/no-event boundary.
SPLIT_PRICE_EVENT_THRESHOLD = 0.02

SPLIT_AUTHORITATIVE_APPLIED = "authoritative_applied"
SPLIT_CORROBORATED_DIRECT = "corroborated_direct"
SPLIT_CORROBORATED_RECIPROCAL = "corroborated_reciprocal"
SPLIT_UNRESOLVED = "unresolved"


def _ratios_close(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= (
        SPLIT_AGREEMENT_TOLERANCE
        * max(abs(float(left)), abs(float(right)), 1e-12))


def split_price_evidence(derived: float | None) -> float | None:
    """Return usable price-domain event evidence, or ``None`` for no event."""
    if derived is None:
        return None
    value = float(derived)
    if value <= 0 or abs(value - 1.0) <= SPLIT_PRICE_EVENT_THRESHOLD:
        return None
    return value


def resolve_split_orientation(
        stated: float, derived: float | None) -> tuple[float, str]:
    """Return the canonical post/pre multiplier and evidence disposition.

    Agreement with ``stated`` preserves a forward multiplier.  Agreement with
    ``1 / stated`` proves that ACTIONS supplied a reverse-split denominator.
    A material value greater than one without usable orientation evidence is
    ambiguous and fails closed as ``1.0``.  Values at or below one are already
    in canonical reverse-split form and may be applied from ACTIONS alone.
    """
    value = float(stated)
    if value <= 0:
        return 1.0, SPLIT_UNRESOLVED

    evidence = split_price_evidence(derived)
    if evidence is not None and evidence > 0:
        # Sub-unit ACTIONS values are already canonical post/pre multipliers.
        # Reciprocal evidence contradicts them; inverting 0.1 into 10 would
        # turn a known 1-for-10 into a 10-for-1 and create a 100x difference in
        # resulting shares.
        if value <= 1.0:
            if _ratios_close(evidence, value):
                return value, SPLIT_CORROBORATED_DIRECT
            return 1.0, SPLIT_UNRESOLVED

        reciprocal = 1.0 / value
        direct_matches = _ratios_close(evidence, value)
        reciprocal_matches = _ratios_close(evidence, reciprocal)
        # Close to one, the tolerance bands can overlap.  In that region the
        # same price witness purports to prove opposite share directions; it is
        # ambiguity, not corroboration, even if one comparison happened first.
        if direct_matches and reciprocal_matches:
            return 1.0, SPLIT_UNRESOLVED
        if direct_matches:
            return value, SPLIT_CORROBORATED_DIRECT

        if reciprocal_matches:
            # Sharadar reverse denominators are sometimes slightly noisy
            # (30.003, 9.00009, 6.99986).  Independent reciprocal evidence
            # permits snapping a near-integral denominator so a 1-for-30 is
            # represented as exactly 1/30.
            denominator = round(value)
            if (denominator > 0
                    and _ratios_close(value, denominator)
                    and _ratios_close(evidence, 1.0 / denominator)):
                reciprocal = 1.0 / denominator
            return reciprocal, SPLIT_CORROBORATED_RECIPROCAL

        if not _ratios_close(evidence, 1.0):
            return 1.0, SPLIT_UNRESOLVED

    if value <= 1.0:
        return value, SPLIT_AUTHORITATIVE_APPLIED
    return 1.0, SPLIT_UNRESOLVED


__all__ = [
    "SPLIT_AGREEMENT_TOLERANCE",
    "SPLIT_PRICE_EVENT_THRESHOLD",
    "SPLIT_AUTHORITATIVE_APPLIED",
    "SPLIT_CORROBORATED_DIRECT",
    "SPLIT_CORROBORATED_RECIPROCAL",
    "SPLIT_UNRESOLVED",
    "resolve_split_orientation",
    "split_price_evidence",
]
