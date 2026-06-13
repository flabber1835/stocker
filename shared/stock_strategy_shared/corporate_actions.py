"""Spinoff / corporate-action price adjustment — pure, deterministic, dependency-free.

Alpha Vantage's `adjusted_close` accounts for splits and dividends but NOT spinoffs.
When a company spins off a subsidiary, the parent's price drops on the ex-date by the
distributed value — a one-day discontinuity that AV leaves in the series. Anything
that reads a trailing window straddling that date then sees a *false* cliff: the
21-day peak-to-now drawdown (the vetter's falling-knife) and the 12-1 momentum factor
both misread a value distribution as a crash. (Concrete case: FedEx's FedEx Freight
spinoff on 2026-06-01 produced a ~-18% cliff that force-excluded FDX as a falling
knife — a value handed to shareholders, not a loss.)

Fix: stitch the discontinuity by scaling all PRE-ex prices by the ex-date gap factor,
exactly as a split adjustment would — so the series is continuous on the current
(post-event) basis. The factor is derived from the price data itself
(first close on/after ex ÷ last close before ex), so no external spinoff valuation is
needed; curated ex-dates live in the `corporate_actions` table.
"""
from __future__ import annotations

from datetime import date
from typing import Mapping, Optional

# A spinoff REDUCES the parent price, so a plausible stitch factor is < 1. Guard the
# computed gap against noise / a mis-tagged date: a price that ROSE across the ex-date
# (>5%) is not a spinoff signature, and a >80% drop is implausibly large for a clean
# spinoff (likely a data error or a real crash we must NOT erase). Outside this band we
# skip the adjustment (return None) and leave the series untouched.
SPINOFF_FACTOR_MIN = 0.2
SPINOFF_FACTOR_MAX = 1.05


def spinoff_factor(
    prices_by_date: Mapping[date, Optional[float]],
    ex_date: date,
) -> Optional[float]:
    """Multiplicative factor to apply to all closes BEFORE ``ex_date`` to stitch a
    spinoff discontinuity, computed from the ex-date price gap:

        factor = (first close on/after ex_date) / (last close before ex_date)

    Returns None (→ no adjustment) when either side is missing/non-positive or the
    factor falls outside [SPINOFF_FACTOR_MIN, SPINOFF_FACTOR_MAX].
    """
    before_dates = [d for d, v in prices_by_date.items() if d < ex_date and v and v > 0]
    after_dates = [d for d, v in prices_by_date.items() if d >= ex_date and v and v > 0]
    if not before_dates or not after_dates:
        return None
    pb = prices_by_date[max(before_dates)]
    pa = prices_by_date[min(after_dates)]
    if not pb or not pa or pb <= 0 or pa <= 0:
        return None
    factor = pa / pb
    if factor < SPINOFF_FACTOR_MIN or factor > SPINOFF_FACTOR_MAX:
        return None
    return factor


def apply_corporate_actions(
    raw_by_date: Mapping[date, Optional[float]],
    ex_dates: list[date],
) -> dict[date, Optional[float]]:
    """Return {date: spinoff-adjusted close} given the IMMUTABLE raw (AV) closes and a
    list of corporate-action ex-dates for the ticker.

    For each date the adjustment is the product of the gap factors of every action
    whose ex_date is STRICTLY AFTER that date (a later spinoff scales earlier history
    down). Each factor is computed from the raw series, so the result is a pure,
    idempotent function of (raw, ex_dates) — recomputing always lands on the same
    values, which is what makes re-ingestion safe. None/0 raws are passed through.
    """
    factors: list[tuple[date, float]] = []
    for ex in sorted(set(ex_dates)):
        f = spinoff_factor(raw_by_date, ex)
        if f is not None:
            factors.append((ex, f))

    out: dict[date, Optional[float]] = {}
    for d, v in raw_by_date.items():
        if v is None:
            out[d] = None
            continue
        cum = 1.0
        for ex, f in factors:
            if d < ex:
                cum *= f
        out[d] = v * cum
    return out
