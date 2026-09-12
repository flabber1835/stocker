"""Sharadar-specific economic-domain conversions shared by live and replay paths.

Sharadar SEP publishes split-adjusted `close`, `open`, and `volume`, while
`closeunadj` is the actual as-traded close. Dollar liquidity and opening price
are invariant only when every value is expressed in the same split domain.

Sharadar ACTIONS dividend values are stated on the vendor's current
split-adjusted share basis. Wealth Core, however, owns historical as-traded share
quantities. Dividend cash is therefore invariant only after the per-share amount
is converted back to the raw/as-traded share domain using the same cumulative
split factor visible in SEP.closeunadj / SEP.close.

The source boundary is DECIMAL, even though the canonical engine stores floats.
Equivalent Sharadar publication rebases must therefore be reduced in an exact
rational domain before the one final float conversion. Performing the ratio in
binary float makes representations such as 20.002/100.01 change the last bits of
volume, dividend, or raw-open economics even when the source publications are
exactly algebraically equivalent.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import math
from typing import Optional


@dataclass(frozen=True)
class AdjudicatedCashDistribution:
    """Separate vendor-adjusted cash from issuer cash per participating old share.

    The source component remains evidence. Its replacement has a fixed raw
    entitlement basis, independent of subsequent vendor adjustment rebases.
    """
    ordinary_split_adjusted_per_share: Decimal
    source_per_share: Decimal
    stale_raw_per_share: Decimal
    cash_per_old_share: Decimal
    new_shares_per_old_share: Decimal


def _finite_decimal(value: object) -> Decimal | None:
    """Recover the canonical decimal spelling of one vendor scalar.

    Source adapters may already have parsed a field to ``float``.  ``str`` is
    intentional in that case: it recovers the shortest decimal spelling that the
    adapter committed to, instead of importing the float's binary expansion into
    the economic calculation.
    """
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _finite_float(value: Fraction) -> float | None:
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    return result if math.isfinite(result) else None


def raw_compatible_volume(
    split_adjusted_close: object,
    raw_close: object,
    reported_split_adjusted_volume: object,
) -> Optional[float]:
    """Convert Sharadar SEP volume into the raw/as-traded share domain.

    The conversion preserves dollar liquidity in exact source-decimal arithmetic:

        raw_close * raw_volume
        == split_adjusted_close * reported_split_adjusted_volume

    The exact rational result is converted to ``float`` once at this boundary so
    algebraically equivalent publication rebases canonicalize to the same engine
    value. Missing, non-finite, or non-positive inputs return ``None``. A
    non-split row is unchanged because adjusted and raw close are equal.
    """
    adjusted = _finite_decimal(split_adjusted_close)
    raw = _finite_decimal(raw_close)
    reported = _finite_decimal(reported_split_adjusted_volume)
    if any(v is None or v <= 0 for v in (adjusted, raw, reported)):
        return None
    result = Fraction(reported) * Fraction(adjusted) / Fraction(raw)
    out = _finite_float(result)
    return out if out is not None and out > 0 else None


def raw_compatible_price(
    split_adjusted_price: object,
    split_adjusted_close: object,
    raw_close: object,
) -> Optional[float]:
    """Convert another split-adjusted SEP price to the raw/as-traded domain.

    ``SEP.open`` and ``SEP.close`` share the same vendor split basis.  The raw
    open is therefore:

        split_adjusted_open * raw_close / split_adjusted_close

    The ratio is evaluated over exact source-decimal spellings.  Callers may
    apply their existing presentation/execution rounding after this function;
    that rounding remains a separate canonical engine contract.
    """
    price = _finite_decimal(split_adjusted_price)
    adjusted = _finite_decimal(split_adjusted_close)
    raw = _finite_decimal(raw_close)
    if any(v is None or v <= 0 for v in (price, adjusted, raw)):
        return None
    result = Fraction(price) * Fraction(raw) / Fraction(adjusted)
    out = _finite_float(result)
    return out if out is not None and out > 0 else None


def raw_dividend_per_share(
    split_adjusted_close: object,
    raw_close: object,
    reported_split_adjusted_dividend: object,
    *, split_ratio: object | None = None,
) -> Optional[float]:
    """Convert an ACTIONS dividend to the historical as-traded share domain.

    ACTIONS dividend ``value`` follows the vendor's current split-adjusted share
    basis. A historical holder owns the contemporaneous raw/as-traded share
    count, so the economic cash entitlement is preserved by:

        raw_dividend_per_share
        = reported_split_adjusted_dividend * raw_close / split_adjusted_close

    Example: Apple's 2014-08-07 ACTIONS value is 0.1175. On that historical SEP
    row closeunadj/close is 4 after Apple's later 4:1 split, so the historical
    dividend is 0.47 per then-outstanding share.

    The ratio is evaluated as an exact rational over the source decimal
    spellings. This is load-bearing: a mathematically equivalent vendor rebase
    must not turn 0.47 into 0.4700000000000001 and thereby change cash, NAV, or a
    committed economic identity.

    Reviewed combined events carry issuer cash per participating old share
    separately. That fixed cash is divided by the declared new/old share ratio
    to match the ledger's post-consolidation share count. Only the ordinary
    vendor component follows the cumulative SEP adjustment. When supplied, the
    normalized split ratio must agree with the issuer's consolidation terms.

    Zero is a valid no-dividend value and does not require price-domain evidence.
    A positive dividend requires finite positive adjusted and raw closes. Negative,
    non-finite, or otherwise unconvertible values return ``None`` so callers can
    fail closed rather than fabricate cash.
    """
    if isinstance(reported_split_adjusted_dividend, AdjudicatedCashDistribution):
        cash = reported_split_adjusted_dividend
        adjusted = _finite_decimal(split_adjusted_close)
        raw = _finite_decimal(raw_close)
        ratio = _finite_decimal(cash.new_shares_per_old_share)
        if any(v is None or v <= 0 for v in (adjusted, raw, ratio)):
            return None
        if split_ratio is not None and _finite_decimal(split_ratio) != ratio:
            return None
        factor = Fraction(raw) / Fraction(adjusted)
        source = Fraction(cash.source_per_share) * factor
        # Compare source evidence on its historical basis. A later equivalent
        # vendor rebase scales the source component, never the issuer term.
        if source not in (Fraction(cash.stale_raw_per_share),
                          Fraction(cash.cash_per_old_share)):
            return None
        if cash.ordinary_split_adjusted_per_share < 0:
            return None
        result = (Fraction(cash.ordinary_split_adjusted_per_share) * factor
                  + Fraction(cash.cash_per_old_share) / Fraction(ratio))
        return _finite_float(result)
    reported = _finite_decimal(reported_split_adjusted_dividend)
    if reported is None or reported < 0:
        return None
    if reported == 0:
        return 0.0
    adjusted = _finite_decimal(split_adjusted_close)
    raw = _finite_decimal(raw_close)
    if any(v is None or v <= 0 for v in (adjusted, raw)):
        return None
    result = Fraction(reported) * Fraction(raw) / Fraction(adjusted)
    out = _finite_float(result)
    return out if out is not None and out >= 0 else None
