"""Pure trailing-stop arithmetic: peak_to_now / trailing_stop_hit.

These live beside recent_drawdown() but must NOT behave like it. recent_drawdown
applies `baseline_window` give-back suppression so that a spike-and-round-trip nets
to ~0 — correct for the falling-knife ENTRY veto (a round trip is volatility, not a
knife), and exactly backwards for a trailing STOP, whose entire job is to act when a
run-up is given back. The regression this file guards against is someone later
noticing "we already have drawdown math" and routing the stop through
recent_drawdown, which would silently disarm it on the names it most needs to catch.
"""
import pytest

from stock_strategy_shared.drawdown import (
    peak_to_now,
    recent_drawdown,
    trailing_stop_hit,
)


class TestPeakToNow:
    def test_at_peak_is_zero(self):
        assert peak_to_now(100.0, 100.0) == 0.0

    def test_below_peak_is_negative(self):
        assert peak_to_now(100.0, 85.0) == pytest.approx(-0.15)

    def test_above_peak_is_positive(self):
        """The caller ratchets the peak; if a fresher close exceeds a stale peak the
        answer must be positive rather than clamped, so a stop can never fire on it."""
        assert peak_to_now(100.0, 110.0) == pytest.approx(0.10)

    @pytest.mark.parametrize("peak,last", [
        (None, 100.0), (100.0, None), (None, None),
        (0.0, 100.0), (-5.0, 100.0), (100.0, 0.0), (100.0, -5.0),
        (float("nan"), 100.0), (100.0, float("nan")),
        ("abc", 100.0), (100.0, object()),
    ])
    def test_unusable_inputs_return_none(self, peak, last):
        assert peak_to_now(peak, last) is None

    def test_numeric_strings_and_decimals_coerce(self):
        """Peaks arrive from a NUMERIC(14,4) column, so Decimal must work; a numeric
        string coercing is a harmless consequence of the same float() call."""
        from decimal import Decimal
        assert peak_to_now(Decimal("100.0"), Decimal("85.0")) == pytest.approx(-0.15)
        assert peak_to_now("100", 85.0) == pytest.approx(-0.15)


class TestTrailingStopHit:
    @pytest.mark.parametrize("last,expected", [
        (100.0, False),   # at peak
        (90.0, False),    # -10%, inside a 15% stop
        (85.0, True),     # exactly -15% — inclusive boundary
        (85.01, False),   # a hair inside
        (84.99, True),    # a hair through
        (50.0, True),
    ])
    def test_boundary_is_inclusive(self, last, expected):
        assert trailing_stop_hit(100.0, last, 0.15) is expected

    @pytest.mark.parametrize("stop_pct", [0.0, -0.1])
    def test_non_positive_stop_never_fires(self, stop_pct):
        assert trailing_stop_hit(100.0, 1.0, stop_pct) is False

    @pytest.mark.parametrize("peak,last", [
        (None, 50.0), (100.0, None), (0.0, 50.0), (float("nan"), 50.0),
        (100.0, float("nan")),
    ])
    def test_never_fires_on_unusable_data(self, peak, last):
        """A stop that fires sells the WHOLE position and cannot be undone, so
        missing or corrupt data must read as 'no signal', never as 'sell'."""
        assert trailing_stop_hit(peak, last, 0.15) is False

    def test_returns_a_real_bool(self):
        assert trailing_stop_hit(100.0, 50.0, 0.15) is True
        assert trailing_stop_hit(100.0, 99.0, 0.15) is False


class TestNotConfusableWithRecentDrawdown:
    def test_a_round_trip_fires_the_stop_but_not_the_knife_veto(self):
        """The defining behavioural difference. A name that ran 100 → 150 and gave it
        all back is net-flat, so the entry veto correctly reads ~0 damage — but a
        trailing stop MUST fire, because 150 was the peak the position reached."""
        closes = [100.0] * 3 + [120.0, 135.0, 150.0, 140.0, 120.0, 100.0]

        knife = recent_drawdown(closes, window=21, baseline_window=3)
        assert knife == pytest.approx(0.0), "give-back suppression should net this out"

        peak = max(closes)
        assert trailing_stop_hit(peak, closes[-1], 0.15) is True, (
            "a trailing stop must act on a given-back run-up — routing it through "
            "recent_drawdown would disarm it here"
        )

    def test_pure_measure_disagrees_with_the_suppressed_one(self):
        closes = [100.0, 150.0, 120.0]
        assert peak_to_now(max(closes), closes[-1]) == pytest.approx(-0.20)
        assert recent_drawdown(closes, baseline_window=3) != pytest.approx(-0.20)

    def test_a_one_way_collapse_agrees_with_both(self):
        """Sanity: on a genuine one-way decline from a flat base the two measures
        coincide, so the split above is about round trips specifically and not a
        general disagreement. The base must be flat — a decline that starts inside
        the 3-close baseline window drags the baseline down with it and the
        suppressed measure reads LESS damage (that is by design there)."""
        closes = [100.0, 100.0, 100.0, 95.0, 90.0, 80.0, 70.0]
        pure = peak_to_now(max(closes), closes[-1])
        knife = recent_drawdown(closes, baseline_window=3)
        assert pure == pytest.approx(-0.30)
        assert knife == pytest.approx(pure)

    def test_a_decline_starting_inside_the_baseline_window_diverges(self):
        """Documents the consequence of the above: recent_drawdown understates a
        collapse whose start is inside its own baseline window. Another reason the
        stop cannot borrow it."""
        closes = [100.0, 95.0, 90.0, 80.0, 70.0]
        assert peak_to_now(max(closes), closes[-1]) == pytest.approx(-0.30)
        assert recent_drawdown(closes, baseline_window=3) == pytest.approx(-0.2631578, abs=1e-6)
