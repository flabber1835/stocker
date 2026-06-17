"""Canonical 'is this name investable?' definition — ONE source of truth for the
universe floor (min_price + min_avg_dollar_volume_20d), shared by:
  - the pipeline factor step (the primary gate: which names get ranked),
  - the delta below-floor exit (a held name that fell below the floor must orphan-exit),
  - the portfolio-builder candidate filter.

Before this, each computed average dollar volume differently — the factor step and
delta use `close × volume` over the last 20 sessions, but the builder filtered on
`fundamentals.avg_volume` (av-ingestor's `adjusted_close × volume`, computed at
ingestion). So 'investable' could mean different things in different steps (the
split-brain bug class). This module pins the definition so they can't disagree.

Pure / dependency-free (no pandas/numpy) so it's usable everywhere and unit-testable.
"""
from __future__ import annotations

from typing import Optional, Sequence

# Trailing window (sessions) for the average-dollar-volume liquidity measure.
DOLLAR_VOLUME_WINDOW = 20


def avg_dollar_volume(
    closes: Sequence[float],
    volumes: Sequence[float],
    window: int = DOLLAR_VOLUME_WINDOW,
) -> Optional[float]:
    """Average daily DOLLAR volume = mean(close × volume) over the last `window`
    sessions. `closes`/`volumes` are chronological (oldest→newest) and same-indexed.
    Uses raw close (actual traded price), matching the factor step. Returns None when
    there are no usable (close, volume) pairs — callers treat None as 'unknown', not
    'below floor'."""
    n = min(len(closes), len(volumes))
    dv: list[float] = []
    for i in range(n):
        c, v = closes[i], volumes[i]
        # skip None and NaN (pandas passes NaN for missing rows; NaN != NaN)
        if c is not None and v is not None and c == c and v == v:
            dv.append(float(c) * float(v))
    dv = dv[-window:]
    if not dv:
        return None
    return sum(dv) / len(dv)


def below_investability_floor(
    last_price: Optional[float],
    avg_dv: Optional[float],
    *,
    min_price: float,
    min_avg_dollar_volume: float,
) -> bool:
    """True iff a name FAILS the strategy investability floor — price < min_price OR
    average dollar volume < min_avg_dollar_volume. A None metric is treated as NOT
    below (we never drop a name on a missing measure; it must fail an actual
    threshold). This is the single floor test used by the factor universe filter, the
    delta below-floor exit, and the builder filter."""
    if last_price is not None and last_price < min_price:
        return True
    if avg_dv is not None and avg_dv < min_avg_dollar_volume:
        return True
    return False
