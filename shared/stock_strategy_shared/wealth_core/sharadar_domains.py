"""Sharadar-specific economic-domain conversions shared by live and replay paths.

Sharadar SEP publishes split-adjusted `close` and split-adjusted `volume`, while
`closeunadj` is the actual as-traded close. Dollar liquidity is invariant only
when price and volume are expressed in the same split domain.

Sharadar ACTIONS dividend values are stated on the vendor's current
split-adjusted share basis. Wealth Core, however, owns historical as-traded share
quantities. Dividend cash is therefore invariant only after the per-share amount
is converted back to the raw/as-traded share domain using the same cumulative
split factor visible in SEP.closeunadj / SEP.close.
"""
from __future__ import annotations

import math
from typing import Optional


def raw_compatible_volume(
    split_adjusted_close: object,
    raw_close: object,
    reported_split_adjusted_volume: object,
) -> Optional[float]:
    """Convert Sharadar SEP volume into the raw/as-traded share domain.

    The conversion preserves dollar liquidity exactly (subject to floating point):

        raw_close * raw_volume
        == split_adjusted_close * reported_split_adjusted_volume

    Missing, non-finite, or non-positive inputs return ``None``. A non-split row
    is unchanged because adjusted and raw close are equal.
    """
    try:
        adjusted = float(split_adjusted_close)
        raw = float(raw_close)
        reported = float(reported_split_adjusted_volume)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) and v > 0 for v in (adjusted, raw, reported)):
        return None
    result = reported * adjusted / raw
    return result if math.isfinite(result) and result > 0 else None


def raw_dividend_per_share(
    split_adjusted_close: object,
    raw_close: object,
    reported_split_adjusted_dividend: object,
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

    Zero is a valid no-dividend value and does not require price-domain evidence.
    A positive dividend requires finite positive adjusted and raw closes. Negative,
    non-finite, or otherwise unconvertible values return ``None`` so callers can
    fail closed rather than fabricate cash.
    """
    try:
        reported = float(reported_split_adjusted_dividend)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(reported) or reported < 0:
        return None
    if reported == 0:
        return 0.0
    try:
        adjusted = float(split_adjusted_close)
        raw = float(raw_close)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) and v > 0 for v in (adjusted, raw)):
        return None
    result = reported * raw / adjusted
    return result if math.isfinite(result) and result >= 0 else None
