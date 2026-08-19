"""Sharadar-specific economic-domain conversions shared by live and replay paths.

Sharadar SEP publishes split-adjusted `close` and split-adjusted `volume`, while
`closeunadj` is the actual as-traded close. Dollar liquidity is invariant only
when price and volume are expressed in the same split domain.
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
