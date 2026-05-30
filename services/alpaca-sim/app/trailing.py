"""Pure trailing-stop logic shared by the Alpaca simulator and the A/B simulation.

A *sell* trailing stop tracks the highest reference price seen since the order
was armed (the high-water mark, HWM). The stop price trails ``trail_percent``
below the HWM and ratchets up — it never moves down. The order triggers (and
fills as a market sell) the first time the reference price falls to or below the
stop price.

This module is deliberately dependency-free so it is the single source of truth
for the simulator service (``services/alpaca-sim``) and the self-contained
trailing-stop comparison simulation (``tests/simulation``). Both evaluate the
stop at daily-close resolution: feed each day's reference price to ``update``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TrailingStopState:
    """Mutable trailing-stop tracker for a single sell stop.

    trail_percent : trail distance as a percentage (e.g. 5.0 for a 5% trail)
    hwm           : highest reference price observed since the stop was armed
    """

    trail_percent: float
    hwm: float

    @property
    def stop_price(self) -> float:
        return self.hwm * (1.0 - self.trail_percent / 100.0)

    def update(self, price: float) -> bool:
        """Feed a new reference price.

        Ratchets the HWM up when ``price`` is a new peak, then reports whether the
        stop is triggered. Returns True when ``price`` has fallen to or below the
        (post-update) stop price — i.e. a >= ``trail_percent`` drawdown from the
        peak — meaning the position should be sold at market.
        """
        if price > self.hwm:
            self.hwm = price
        return price <= self.stop_price


def arm(trail_percent: float, price: float) -> TrailingStopState:
    """Arm a trailing stop at ``price`` (the HWM starts at the current price)."""
    if trail_percent <= 0:
        raise ValueError("trail_percent must be > 0")
    return TrailingStopState(trail_percent=float(trail_percent), hwm=float(price))
