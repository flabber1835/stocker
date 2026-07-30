"""Volatility-scaled stop width.

A flat `stop_pct` treats every holding alike, which they are not: 15% off the peak
is a broken trend for a utility and ordinary noise for a small-cap momentum name.
`width_method='vol_scaled'` sizes the give-back by the ticker's own realised
volatility.

Two properties matter most:

  1. `fixed` — the DEFAULT — must be bit-identical to the behaviour that shipped
     before this existed. Otherwise adding a mode silently changed live.
  2. Unknown vol must fall back to the flat width, never to a width derived from
     nothing. A stop sells the whole position and cannot be undone.

The scaling itself reuses `scaled_excess_threshold`, the SAME function the
entry-side falling-knife veto uses, so the two vol-scaled thresholds cannot drift.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/pipeline"))

from app.engine import StopState, plan_trailing_stops  # noqa: E402
from stock_strategy_shared.drawdown import realized_vol  # noqa: E402


def _state(peak=100.0, last=100.0, held=30, since=0, vol=None) -> StopState:
    return StopState(peak_close=peak, last_close=last, sessions_held=held,
                     sessions_since_close=since, vol=vol)


def _plan(states, **over):
    kwargs = dict(enabled=True, stop_pct=0.15, arm_after_sessions=5,
                  max_stale_sessions=2, max_stops_per_run=99,
                  width_method="fixed", vol_anchor=0.35,
                  stop_pct_min=0.08, stop_pct_max=0.35)
    kwargs.update(over)
    return plan_trailing_stops(states, **kwargs)


class TestFixedIsUnchanged:
    def test_vol_is_ignored_under_the_fixed_default(self):
        """A config carrying vol data but width_method='fixed' must behave exactly
        as one carrying none — otherwise the mode switch is not really a switch."""
        for vol in (None, 0.05, 0.35, 2.0):
            plan = _plan({"AAA": _state(last=85.0, vol=vol)})
            assert set(plan.stopped) == {"AAA"}, f"vol={vol} changed a FIXED width"
        assert _plan({"AAA": _state(last=86.0, vol=2.0)}).stopped == {}

    def test_default_arguments_are_fixed(self):
        """Callers that predate this feature omit the width kwargs entirely."""
        plan = plan_trailing_stops(
            {"AAA": _state(last=85.0, vol=0.05)},
            enabled=True, stop_pct=0.15, arm_after_sessions=5,
            max_stale_sessions=2, max_stops_per_run=99)
        assert set(plan.stopped) == {"AAA"}


class TestScaling:
    def test_a_calm_name_gets_a_TIGHTER_width(self):
        """vol 0.175 = half the 0.35 anchor → width 0.075, clamped up to the 0.08
        floor. A 10% drop stops it where the flat 15% would not."""
        plan = _plan({"AAA": _state(last=90.0, vol=0.175)},
                     width_method="vol_scaled")
        assert set(plan.stopped) == {"AAA"}
        assert _plan({"AAA": _state(last=90.0, vol=0.175)}).stopped == {}, (
            "the same position must NOT stop under the flat width — otherwise this "
            "test proves nothing about scaling")

    def test_a_wild_name_gets_MORE_rope(self):
        """vol 0.70 = twice the anchor → width 0.30. An 18% drop is inside it."""
        plan = _plan({"AAA": _state(last=82.0, vol=0.70)},
                     width_method="vol_scaled")
        assert plan.stopped == {}
        assert set(_plan({"AAA": _state(last=82.0, vol=0.70)}).stopped) == {"AAA"}

    def test_a_typical_name_keeps_the_base_width(self):
        """At the anchor exactly, scaling is the identity — so the base number
        still means what the operator thinks it means."""
        at_anchor = _state(last=85.0, vol=0.35)
        assert set(_plan({"A": at_anchor}, width_method="vol_scaled").stopped) == {"A"}
        assert _plan({"A": _state(last=85.01, vol=0.35)},
                     width_method="vol_scaled").stopped == {}


class TestClamps:
    def test_the_floor_stops_a_hair_trigger(self):
        """Without a floor, a near-zero-vol name would stop on rounding noise."""
        plan = _plan({"AAA": _state(last=93.0, vol=0.001)},
                     width_method="vol_scaled", stop_pct_min=0.08)
        assert plan.stopped == {}, "a 7% drop is inside the 8% floor"
        assert set(_plan({"AAA": _state(last=91.0, vol=0.001)},
                         width_method="vol_scaled").stopped) == {"AAA"}

    def test_the_cap_keeps_it_a_risk_control(self):
        """Without a cap a wild name is effectively unstoppable."""
        plan = _plan({"AAA": _state(last=60.0, vol=5.0)},
                     width_method="vol_scaled", stop_pct_max=0.35)
        assert set(plan.stopped) == {"AAA"}, "a 40% drop must exceed the 35% cap"


class TestUnknownVol:
    @pytest.mark.parametrize("vol", [None, 0.0, -1.0, float("nan")])
    def test_falls_back_to_the_flat_width(self, vol):
        """A name with too little history gets the ORDINARY width, never one
        derived from nothing.

        0.0 and NaN matter as much as None: scaled_excess_threshold only guards
        None, so a 0.0 would scale to the FLOOR (the tightest possible stop) and a
        NaN would fall through min/max unpredictably. A zero-vol equity is far more
        likely a frozen or padded series than a genuinely riskless one, so the
        conservative reading of a suspicious input on a SELL rule is the ordinary
        width."""
        stopped = _plan({"AAA": _state(last=85.0, vol=vol)},
                        width_method="vol_scaled").stopped
        assert set(stopped) == {"AAA"}
        assert _plan({"AAA": _state(last=86.0, vol=vol)},
                     width_method="vol_scaled").stopped == {}


class TestBreakerOrdering:
    def test_breaker_ranks_by_RAW_drawdown_not_by_width(self):
        """When the breaker binds, the deepest losses go first regardless of how
        wide their individual stop happened to be. BBB is down more; AAA merely
        breached a tighter width."""
        states = {
            "AAA": _state(last=88.0, vol=0.10),   # -12%, tight width
            "BBB": _state(last=55.0, vol=0.70),   # -45%, wide width
        }
        plan = _plan(states, width_method="vol_scaled", max_stops_per_run=1)
        assert set(plan.stopped) == {"BBB"}
        assert set(plan.deferred) == {"AAA"}


class TestRealizedVol:
    def test_annualisation_matches_the_factor_definition(self):
        """One definition of 'annualised realised vol' in the codebase, not three.
        compute_low_volatility (factors.py) uses LOG returns and this uses simple
        ones, so they agree only to the extent log(1+r) ≈ r — i.e. closely for
        realistic daily moves and not at all for large ones. The fixture is
        therefore a realistic ~1.5%-a-day series, not a pathological one."""
        import numpy as np
        rng = np.random.default_rng(11)
        rets = rng.normal(0.0003, 0.015, 250)
        closes = list(100.0 * np.cumprod(1.0 + rets))

        mine = realized_vol(closes, lookback=120)
        arr = np.array(closes[-120:])
        theirs = float(np.std(np.diff(np.log(arr)), ddof=1) * np.sqrt(252))
        assert mine == pytest.approx(theirs, rel=0.02)

    @pytest.mark.parametrize("closes", [[], [100.0], [100.0] * 5, None])
    def test_too_little_history_is_none(self, closes):
        assert realized_vol(closes or [], lookback=120, min_observations=20) is None

    def test_ignores_unusable_prices(self):
        assert realized_vol([100.0, 0.0, -5.0, None] + [100.0 + i for i in range(30)],
                            lookback=120) is not None

    def test_a_flat_series_has_zero_vol(self):
        assert realized_vol([100.0] * 60, lookback=120) == pytest.approx(0.0)

    def test_a_wilder_series_has_higher_vol(self):
        calm = [100.0 + 0.1 * ((-1) ** i) for i in range(120)]
        wild = [100.0 + 5.0 * ((-1) ** i) for i in range(120)]
        assert realized_vol(wild) > realized_vol(calm) > 0
