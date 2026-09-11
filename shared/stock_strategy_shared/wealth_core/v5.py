"""Frozen V5 admission and opening sizing on the canonical Wealth Core book."""
from __future__ import annotations

import math

PROFILE = "wealth-core-v5-total-cash-open-sizing-v1"
REFERENCE_SOURCE_SHA256 = "335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d"
BUFFER_FRACTION = 0.001
EPSILON = 1e-12


def config():
    from .engine import WealthCoreConfig
    return WealthCoreConfig(n_slots=20, entry_weight=0.05, economic_profile=PROFILE)


def admission(*, equity: float, cash: float, price: float | None,
              cost_bps: float = 10.0) -> tuple[float | None, str]:
    """The close binds dollars only; settled total cash funds feasibility."""
    if (not all(math.isfinite(x) for x in (equity, cash, cost_bps))
            or equity <= 0 or cash < 0 or cost_bps < 0):
        raise ValueError("invalid V5 admission economics")
    reserve = max(0., equity * BUFFER_FRACTION)
    if max(0., cash - reserve) <= EPSILON:
        return None, "CASH_SCARCITY"
    if price is None or not math.isfinite(price) or price <= 0:
        return None, "INVALID_CLOSE_MARKET"
    if cash + EPSILON < price * (1 + cost_bps / 10_000):
        return None, "TOTAL_CASH_ONE_SHARE_UNAFFORDABLE_AT_CLOSE"
    return equity * 0.05, ""


def opening_quantity(*, intended: float, cash: float, price: float,
                     cost_bps: float = 10.0) -> int:
    if (not all(math.isfinite(x) for x in (intended, cash, price, cost_bps))
            or intended <= 0 or cash < 0 or price <= 0 or cost_bps < 0):
        raise ValueError("invalid V5 opening sizing economics")
    return math.floor(max(0., min(intended, cash)) / (price * (1 + cost_bps / 10_000)))
