"""Shared split semantics for production and canonical replay.

Sharadar documents ``split`` as the stock-split new-float/old-float ratio and
``adrratiosplit`` as a separate ADR ratio-change action. Only the former is a
listed-instrument share multiplier. SEP's split-adjusted and unadjusted close
domains independently corroborate that multiplier.

This module owns the price-precision rule and the one-session stream state so
production ingest and canonical replay cannot make different economic decisions
from identical rows.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping


SPLIT_AGREEMENT_TOLERANCE = 0.01
# Sharadar SEP prices are delivered to a mill. Half a mill is therefore the
# maximum rounding displacement of each observed endpoint.
SPLIT_PRICE_QUANTUM = 0.001
# Used only to decide whether price-only evidence constitutes a split event.
# An explicit ACTIONS split is compared with the finite-precision price interval
# before this threshold is allowed to classify the observation as "no event".
SPLIT_PRICE_EVENT_THRESHOLD = 0.02
# Resolve an issuer-level action as not affecting the listed instrument only
# when its raw-price move is over an order of magnitude from the split-implied
# move as well as carrying no SEP adjustment transition.
SPLIT_RAW_REFUTATION_FACTOR = 10.0

SPLIT_AUTHORITATIVE_APPLIED = "authoritative_applied"
SPLIT_CORROBORATED_DIRECT = "corroborated_direct"
SPLIT_CORROBORATED_QUANTIZED = "corroborated_quantized"
SPLIT_CORROBORATED_SHIFTED = "corroborated_shifted_previous"
SPLIT_CORROBORATED_BRIDGED = "corroborated_two_session_bridge"
SPLIT_RESOLVED_NO_EVENT = "resolved_no_traded_event"
SPLIT_PENDING_BRIDGE = "pending_next_session_bridge"
SPLIT_DERIVED_ONLY = "derived_only_applied"
SPLIT_UNRESOLVED = "unresolved"


def _ratios_close(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= (
        SPLIT_AGREEMENT_TOLERANCE
        * max(abs(float(left)), abs(float(right)), 1e-12))


def canonical_split_multiplier(stated: float) -> float:
    """Recover an exact simple reverse ratio from vendor decimal spelling.

    ACTIONS commonly spells a 1-for-N stock split to five decimal places (for
    example ``0.03333``). Applying that decimal literally turns 300 shares into
    9.999, while the broker event creates 10. The direct value still owns the
    economics; this function only reconstructs ``1/N`` when that rational lies
    inside the same strict one-percent representation band.
    """
    value = float(stated)
    if not math.isfinite(value) or value <= 0 or value >= 1:
        return value
    denominator = round(1.0 / value)
    if denominator <= 1:
        return value
    rational = 1.0 / denominator
    return rational if _ratios_close(value, rational) else value


def split_ratio_from_prices(
        prev_close: float | None, prev_raw: float | None,
        close: float | None, raw: float | None) -> float | None:
    values = (prev_close, prev_raw, close, raw)
    if any(value is None or not math.isfinite(float(value)) or value <= 0
           for value in values):
        return None
    return (float(prev_raw) * float(close)) / (
        float(prev_close) * float(raw))


def split_ratio_bounds(
        prev_close: float | None, prev_raw: float | None,
        close: float | None, raw: float | None,
        *, quantum: float = SPLIT_PRICE_QUANTUM,
) -> tuple[float, float] | None:
    """Ratio interval implied by four rounded SEP prices."""
    values = (prev_close, prev_raw, close, raw)
    if any(value is None or not math.isfinite(float(value)) or value <= 0
           for value in values):
        return None
    half = float(quantum) / 2.0
    pc, pr, cc, cr = (float(value) for value in values)
    if min(pc, pr, cc, cr) <= half:
        return None
    lower = ((pr - half) * (cc - half)) / (
        (pc + half) * (cr + half))
    upper = ((pr + half) * (cc + half)) / (
        (pc - half) * (cr - half))
    return lower, upper


def split_ratio_matches(
        stated: float, derived: float | None,
        bounds: tuple[float, float] | None = None) -> tuple[bool, bool]:
    """Return ``(matches, needed_quantization_interval)``."""
    if derived is not None and _ratios_close(float(stated), float(derived)):
        return True, False
    if bounds is not None and bounds[0] <= float(stated) <= bounds[1]:
        return True, True
    return False, False


def split_price_evidence(derived: float | None) -> float | None:
    """Return usable price-only event evidence, or ``None`` for no event.

    This threshold is intentionally for event DISCOVERY when price domains are
    the only witness. It must not erase finite-precision corroboration of an
    explicit ACTIONS split.
    """
    if derived is None:
        return None
    value = float(derived)
    if value <= 0 or abs(value - 1.0) <= SPLIT_PRICE_EVENT_THRESHOLD:
        return None
    return value


def raw_prices_refute_listed_split(
        stated: float, prev_raw: float | None, raw: float | None) -> bool:
    """Whether traded prices decisively refute a listed-share transformation."""
    if (stated <= 0 or prev_raw is None or raw is None
            or prev_raw <= 0 or raw <= 0):
        return False
    observed_move = float(raw) / float(prev_raw)
    split_implied_move = 1.0 / float(stated)
    residual = observed_move / split_implied_move
    return (residual >= SPLIT_RAW_REFUTATION_FACTOR
            or residual <= 1.0 / SPLIT_RAW_REFUTATION_FACTOR)


def resolve_split_orientation(
        stated: float, derived: float | None, *,
        bounds: tuple[float, float] | None = None,
        explicit_no_event: bool = False,
        raw_refutes_event: bool = False) -> tuple[float, str]:
    """Return the canonical stock-split multiplier and its disposition.

    ``split`` is already new-float/old-float authority; it is never inverted.
    Missing predecessor evidence permits the direct authoritative value. A real
    predecessor that explicitly shows no adjustment is different: it either
    proves the issuer action did not affect the listed instrument (when traded
    prices also decisively refute it) or remains a source conflict.

    Large price-domain events retain the ordinary direct/quantized agreement
    test. For a derived ratio inside the generic 2% "no event" band, an explicit
    ACTIONS split is accepted only when its stated ratio falls inside the exact
    finite-precision interval implied by the four mill-rounded SEP prices. That
    resolves TRI 2026-05-04 (0.984560 stated, ~0.984555 derived) without turning
    the broad 1% agreement tolerance into permission for arbitrary tiny splits.
    """
    value = float(stated)
    if value <= 0 or not math.isfinite(value):
        return 1.0, SPLIT_UNRESOLVED

    evidence = split_price_evidence(derived)
    if evidence is not None:
        matches, quantized = split_ratio_matches(value, evidence, bounds)
        if matches:
            return canonical_split_multiplier(value), (
                SPLIT_CORROBORATED_QUANTIZED
                if quantized else SPLIT_CORROBORATED_DIRECT)
        return 1.0, SPLIT_UNRESOLVED

    # Small explicit actions need stronger proof than the generic 1% ratio
    # tolerance: the stated ratio must be physically possible given SEP's known
    # mill rounding on all four prices.
    if (derived is not None and bounds is not None
            and bounds[0] <= value <= bounds[1]):
        return canonical_split_multiplier(value), SPLIT_CORROBORATED_QUANTIZED

    if explicit_no_event:
        if raw_refutes_event:
            return 1.0, SPLIT_RESOLVED_NO_EVENT
        return 1.0, SPLIT_UNRESOLVED
    return canonical_split_multiplier(value), SPLIT_AUTHORITATIVE_APPLIED


class SplitAuthority(dict):
    """Stock-split multipliers plus immediately-prior session probes."""

    def __init__(self, values: Mapping | None = None, *,
                 previous_session_candidates: Mapping | None = None):
        super().__init__(values or {})
        self.previous_session_candidates = dict(
            previous_session_candidates or {})


@dataclass(frozen=True)
class SplitDecision:
    ratio: float
    disposition: str | None
    stated: float | None
    derived: float | None
    prior_key: tuple[str, str] | None = None
    prior_disposition: str | None = None


@dataclass(frozen=True)
class _PendingBridge:
    prior_key: tuple[str, str]
    prev_close: float
    prev_raw: float


class SplitStreamReconciler:
    """Resolve direct, one-session-shifted, and two-session bridge events."""

    def __init__(self, authority: Mapping[tuple[str, str], float]):
        self.authority = authority
        self.previous_candidates = dict(getattr(
            authority, "previous_session_candidates", {}))
        self.consumed: set[tuple[str, str]] = set()
        self.pending: dict[tuple[str, str], _PendingBridge] = {}

    def decide(
            self, key: tuple[str, str], *,
            prev_close: float | None, prev_raw: float | None,
            close: float | None, raw: float | None,
            fallback_ratio: float) -> SplitDecision:
        derived = split_ratio_from_prices(prev_close, prev_raw, close, raw)
        evidence = split_price_evidence(derived)
        bounds = split_ratio_bounds(prev_close, prev_raw, close, raw)

        if key in self.consumed:
            return SplitDecision(
                1.0, SPLIT_RESOLVED_NO_EVENT,
                float(self.authority[key]), derived)

        stated = self.authority.get(key)
        if stated is not None:
            stated = float(stated)
            pending = self.pending.pop(key, None)
            if pending is not None:
                bridge = split_ratio_from_prices(
                    pending.prev_close, pending.prev_raw, close, raw)
                bridge_bounds = split_ratio_bounds(
                    pending.prev_close, pending.prev_raw, close, raw)
                matches, _quantized = split_ratio_matches(
                    stated, bridge, bridge_bounds)
                if matches:
                    return SplitDecision(
                        canonical_split_multiplier(stated),
                        SPLIT_CORROBORATED_BRIDGED, stated, bridge,
                        prior_key=pending.prior_key,
                        prior_disposition=SPLIT_RESOLVED_NO_EVENT)

            explicit_no_event = derived is not None and evidence is None
            ratio, disposition = resolve_split_orientation(
                stated, derived, bounds=bounds,
                explicit_no_event=explicit_no_event,
                raw_refutes_event=raw_prices_refute_listed_split(
                    stated, prev_raw, raw))
            return SplitDecision(ratio, disposition, stated, derived)

        future = self.previous_candidates.get(key)
        if future is not None and evidence is not None:
            future_key, future_stated = future
            future_stated = float(future_stated)
            matches, _quantized = split_ratio_matches(
                future_stated, evidence, bounds)
            if matches:
                self.consumed.add(future_key)
                return SplitDecision(
                    canonical_split_multiplier(future_stated),
                    SPLIT_CORROBORATED_SHIFTED,
                    future_stated, derived)
            if prev_close is not None and prev_raw is not None:
                self.pending[future_key] = _PendingBridge(
                    prior_key=key, prev_close=float(prev_close),
                    prev_raw=float(prev_raw))
                return SplitDecision(
                    1.0, SPLIT_PENDING_BRIDGE, future_stated, derived)

        if fallback_ratio != 1.0:
            return SplitDecision(
                float(fallback_ratio), SPLIT_DERIVED_ONLY, None, derived)
        return SplitDecision(float(fallback_ratio), None, None, derived)


__all__ = [
    "SPLIT_AGREEMENT_TOLERANCE",
    "SPLIT_AUTHORITATIVE_APPLIED",
    "SPLIT_CORROBORATED_BRIDGED",
    "SPLIT_CORROBORATED_DIRECT",
    "SPLIT_CORROBORATED_QUANTIZED",
    "SPLIT_CORROBORATED_SHIFTED",
    "SPLIT_DERIVED_ONLY",
    "SPLIT_PENDING_BRIDGE",
    "SPLIT_PRICE_EVENT_THRESHOLD",
    "SPLIT_PRICE_QUANTUM",
    "SPLIT_RESOLVED_NO_EVENT",
    "SPLIT_UNRESOLVED",
    "SplitAuthority",
    "SplitDecision",
    "SplitStreamReconciler",
    "canonical_split_multiplier",
    "raw_prices_refute_listed_split",
    "resolve_split_orientation",
    "split_price_evidence",
    "split_ratio_bounds",
    "split_ratio_from_prices",
    "split_ratio_matches",
]
