"""Pure recent-drawdown helper, shared by the vetter (prompt + backstop) and tests.

Recent drawdown = how far a stock trades below its own trailing peak:

    drawdown = last_close / max(close over the trailing window) - 1.0   (<= 0)

A stock at a fresh high → 0.0; one trading 27% below its recent peak → -0.27.
This is the "falling knife" signal: unlike the 12-1 momentum factor (which skips
the most recent ~21 days), drawdown has NO skip window, so it reflects a crash
that happened in the last few weeks — exactly the blind spot on the buy side.

Dependency-free on purpose: one definition used by the live vetter and its tests.
"""
from __future__ import annotations

from typing import Sequence


def recent_drawdown(closes: Sequence[float], window: int = 21) -> float | None:
    """Trailing peak-to-now drawdown over the last `window` closes.

    closes: chronological adjusted closes (oldest → newest). Only the last
            `window` are considered.
    Returns a value in (-1.0, 0.0] (0.0 = at peak), or None if there is no
    usable price data (empty, or no positive peak).
    """
    if not closes:
        return None
    recent = [float(c) for c in closes[-window:] if c is not None and float(c) > 0]
    if not recent:
        return None
    peak = max(recent)
    last = recent[-1]
    if peak <= 0:
        return None
    return last / peak - 1.0
