"""Liquidity-domain normalization shared by every Wealth Core adapter.

Sharadar SEP publishes ``close`` and ``volume`` on the same split-adjusted basis,
while ``closeunadj`` is the as-traded/raw price.  Multiplying ``closeunadj`` by
Sharadar's reported ``volume`` therefore mixes split bases and can change the
$5M/$20M eligibility predicates.

Wealth Core's feed carries a raw/as-traded price, so its compatible volume is:

    raw_volume = reported_volume * signal_close / raw_close

and the invariant is:

    raw_close * raw_volume == signal_close * reported_volume

This module is intentionally vendor-small and strategy-shared.  Sentinel's live
corpus loader and the canonical replay loader must call the same function; parity
around the old wrong formula is not correctness.
"""
from __future__ import annotations

import math
from typing import Optional


class LiquidityDomainError(ValueError):
    """The three vendor quantities cannot establish one coherent liquidity domain."""


def raw_compatible_volume(signal_close, raw_close, reported_volume
                          ) -> Optional[float]:
    """Return volume compatible with ``raw_close`` for dollar-volume arithmetic.

    Missing/non-positive price or volume is represented as ``None`` because it
    cannot establish positive executable liquidity.  Non-finite values are also
    absent rather than permitted to poison an ADV window.  No fallback to the
    reported volume is allowed when the price-domain ratio is unavailable: that
    fallback is exactly the mixed-domain defect this boundary exists to prevent.
    """
    try:
        signal = float(signal_close)
        raw = float(raw_close)
        volume = float(reported_volume)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (signal, raw, volume)):
        return None
    if signal <= 0 or raw <= 0 or volume <= 0:
        return None
    result = volume * signal / raw
    if not math.isfinite(result) or result <= 0:
        raise LiquidityDomainError(
            "split-compatible volume calculation produced an invalid result")
    return result


def split_invariant_dollar_volume(signal_close, reported_volume
                                  ) -> Optional[float]:
    """Vendor-domain turnover, useful as the independent invariant witness."""
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


__all__ = [
    "LiquidityDomainError", "raw_compatible_volume",
    "split_invariant_dollar_volume",
]
