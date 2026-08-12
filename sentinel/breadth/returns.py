"""The numeric contract behind `r21`, `r63` and `own_dd`.

This module exists as its own file because the precision rule below is the
single most silent hazard in the whole breadth path. It is not a rounding
preference — it decides classifications.

## Lag closes are float32. The current close is not.

The retained position replay held its rolling price history in a `np.float32`
ring buffer and divided a float64 current close by a float32 lag close:

```text
sentinel_1p1_standalone.py:326   close_ring = np.full((L, n), np.nan, np.float32)
sentinel_1p1_standalone.py:359   lag21 = close_ring[(gday - 21) % L, tids]
sentinel_1p1_standalone.py:362   rr    = np.divide(c, lag21, ...) - 1
sentinel_1p1_standalone.py:532   lag63 = float(close_ring[(gday - 63) % L, tid])
sentinel_1p1_standalone.py:533   r63   = sigpx / lag63 - 1
```

So the lag price is rounded to binary32 BEFORE the division, and the division
itself happens in float64. Reproducing this in all-float64 shifts `r21` and
`r63` by ~1e-8 relative — which sounds ignorable until you notice that every
boundary in the classifier is strict-vs-inclusive. A holding whose price is
unchanged over 21 sessions has `r21 == 0.0` in float64 and is NOT green, and
has `r21 > 0` in the float32 contract and IS green. `tests/sentinel/
test_breadth_classifier.py` carries that exact fixture as a falsifier.

`own_dd` is deliberately NOT part of this: the episode peak is stored as a
Python float (`standalone:474`, `float(cl_sig[tid])`), never through the ring,
so the drawdown is pure float64. Rounding the peak would be a defect, not a
tightening.
"""
from __future__ import annotations

import math
import struct
from typing import Optional

NaN = float("nan")


def to_float32(value: float) -> float:
    """Round a float64 to IEEE-754 binary32, then widen back.

    Bit-identical to `float(numpy.float32(value))`; `tests/sentinel/
    test_breadth_classifier.py` asserts that equivalence against numpy rather
    than assuming it. Implemented with `struct` so that `sentinel/` keeps its
    stdlib-only dependency closure — the appliance does not import numpy.
    """
    return struct.unpack("f", struct.pack("f", value))[0]


def is_available(value: Optional[float]) -> bool:
    """The reference's `np.isfinite` guard, extended to accept None.

    The standalone marks an unusable metric with NaN; `sentinel/` marks an
    unavailable one with None. Both mean "we could not evaluate this", and both
    must fail every predicate rather than being coerced to a passing zero — the
    same rule the controller's evidence records enforce.
    """
    return value is not None and math.isfinite(value)


def lag_return(current_close: Optional[float],
               lag_close: Optional[float]) -> float:
    """`current / lag - 1` under the float32 lag contract. NaN when unusable.

    `lag_close` is the RAW lag price; this function applies the binary32
    rounding the ring buffer applied, so callers pass what they read from the
    corpus and cannot forget the step.

    A non-positive lag yields NaN, matching `standalone:362` (`where=... &
    (lag21 > 0)`) and `standalone:533` (`... and lag63 > 0`). Zero and negative
    prices are absent data, not a -100% return.
    """
    if not is_available(current_close) or not is_available(lag_close):
        return NaN
    lag32 = to_float32(lag_close)
    if not math.isfinite(lag32) or lag32 <= 0.0:
        return NaN
    return current_close / lag32 - 1.0


def own_drawdown(signal_close: Optional[float],
                 episode_peak_signal: Optional[float]) -> float:
    """`close / episode_peak - 1` in float64. NaN when unusable.

    `standalone:531`. Ownership drawdown is measured against the peak reached
    DURING THE CURRENT EPISODE, not an all-time high — a re-entered name starts
    its drawdown clock again, and using a global peak would mark a fresh
    position as damaged on the day it is bought.
    """
    if not is_available(signal_close) or not is_available(episode_peak_signal):
        return NaN
    if episode_peak_signal <= 0.0:
        return NaN
    return signal_close / episode_peak_signal - 1.0
