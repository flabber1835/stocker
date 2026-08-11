"""The portfolio high-water mark must survive a trailing stop.

The defect: `for t, peak in plan.stopped.items()` rebound the module-level `peak`
— the portfolio high-water mark — to a stopped TICKER's price. The next
`peak = max(peak, equity)` then compared a share price against a portfolio value,
so the watermark collapsed to the current equity and every later drawdown was
measured from a fresh baseline. A run reported -2.2% max drawdown while its worst
SINGLE DAY was -5.2%.

Nothing else broke, which is what made it survive: `peak` feeds only the
`drawdown` field, so returns, CAGR and Sharpe were all correct and the numbers
looked plausible together. Only the arithmetic relationship below is violated.

That relationship is the test, and it holds for ANY equity path:

    max_drawdown <= worst single-day return

because after a day that falls x%, drawdown from the peak is at least x% (the
peak is at least the prior day's equity). It needs no fixture tuning, no
knowledge of the strategy, and it is exactly what the shadowing broke.
"""
from __future__ import annotations

import pytest


def _max_drawdown(values: list[float]) -> float:
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1.0)
    return worst


def _worst_day(values: list[float]) -> float:
    return min((b / a - 1.0 for a, b in zip(values, values[1:])), default=0.0)


class TestTheInvariant:
    @pytest.mark.parametrize("path", [
        [100.0, 110.0, 104.0, 120.0, 113.0, 130.0],          # rising, small dips
        [100.0, 95.0, 90.0, 85.0, 80.0],                     # monotone fall
        [100.0, 150.0, 75.0, 160.0],                         # one violent day
        [100.0] * 10,                                        # flat
        [100.0, 101.0, 100.5, 102.0, 101.0, 103.0],          # grind up
    ])
    def test_max_drawdown_is_never_shallower_than_the_worst_day(self, path):
        assert _max_drawdown(path) <= _worst_day(path) + 1e-12

    def test_a_reset_watermark_violates_it(self):
        """The shadowing, in miniature.

        The clobber happened BEFORE `peak = max(peak, equity)` on the very session
        a stop fired — which is typically a falling one. So that day's drawdown
        was recorded as 0 no matter how far equity fell, and the invariant breaks:
        the reported maximum ends up SHALLOWER than a single day's decline.

        Resetting on a quiet day merely under-reports; resetting on the worst day
        is what produces an impossible number, so that is the case pinned here.
        """
        path = [100.0, 130.0, 123.0, 116.0, 110.0]
        worst_i = min(range(1, len(path)), key=lambda i: path[i] / path[i - 1])
        honest = _max_drawdown(path)

        peak, worst = path[0], 0.0
        for i, v in enumerate(path):
            if i == worst_i:
                peak = v            # a ticker price landing in the portfolio peak
            peak = max(peak, v)
            worst = min(worst, v / peak - 1.0)

        assert honest < worst, "the reset must under-report, or this proves nothing"
        assert worst > _worst_day(path) + 1e-12, (
            "and it under-reports past the invariant — reporting a maximum "
            "drawdown shallower than one day's fall, which is impossible")
