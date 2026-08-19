"""Compatibility helpers for Wealth Core liquidity-domain tests.

The canonical Sharadar conversion lives in ``sharadar_domains`` so live Sentinel
and bt-data share one provider-specific economic-domain implementation. This
module keeps the older #185 test/helper import stable without duplicating the
conversion formula.
"""
from __future__ import annotations

import math
from typing import Optional

from .sharadar_domains import raw_compatible_volume


def split_invariant_dollar_volume(signal_close, reported_volume) -> Optional[float]:
    """Sharadar vendor-domain turnover, used as an independent invariant witness."""
    try:
        signal = float(signal_close)
        volume = float(reported_volume)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(signal) or not math.isfinite(volume):
        return None
    if signal <= 0 or volume <= 0:
        return None
    return signal * volume


__all__ = ["raw_compatible_volume", "split_invariant_dollar_volume"]
