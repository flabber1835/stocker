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

import math


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


def coalesce_split_sibling_values(
        values: list[float | None],
) -> float | None:
    """Return one stated ratio when every source sibling describes it.

    Sharadar can publish the same reverse event in both canonical multiplier
    and denominator form, for example ``0.1`` and ``10``. A sub-unit value is
    already canonical. A value above one remains orientation-ambiguous until
    the independent price domains are consulted, so identical ``10`` siblings
    preserve ``10`` rather than guessing ``0.1``.

    Distinct reciprocal spellings resolve only when their possible economics
    have exactly one common ratio. Non-equivalent rows, multiple distinct
    sub-unit spellings, invalid values, and any multi-valued intersection stay
    unresolved. The rule is deliberately shared by production normalization
    and canonical replay.
    """
    if not values or any(value is None for value in values):
        return None
    usable = [float(value) for value in values if value is not None]
    if any(value <= 0 or not math.isfinite(value) for value in usable):
        return None
    if len(set(usable)) == 1:
        return usable[0]

    possibilities = [
        (value,) if value <= 1.0 else (value, 1.0 / value)
        for value in usable
    ]
    common: list[float] = []
    for candidate in (item for group in possibilities for item in group):
        if not all(any(_ratios_close(candidate, item) for item in group)
                   for group in possibilities):
            continue
        if not any(_ratios_close(candidate, item) for item in common):
            common.append(candidate)
    if len(common) != 1:
        return None

    matching_subunits = {
        value for value in usable
        if value <= 1.0 and _ratios_close(value, common[0])
    }
    if len(matching_subunits) != 1:
        return None
    # Preserve the source's canonical sub-unit spelling. This avoids replacing
    # 0.03333 with a computed reciprocal carrying representation noise.
    return matching_subunits.pop()


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
    "coalesce_split_sibling_values",
    "resolve_split_orientation",
    "split_price_evidence",
]
