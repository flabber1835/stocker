"""Re-entry after a stop: peak recovery vs a fixed cooldown.

Both exist because the right rule DEPENDS ON STOP WIDTH, and the original code
shipped only one. The peak rule ("blocked until the close exceeds the peak that
stopped you") is a strictly stronger filter than any timer — but it does not
scale. Regaining the peak needs roughly:

    stop 15%  ->  17.6% rally
    stop 30%  ->  42.9% rally

At 30% that stops being hysteresis and becomes near-permanent exclusion of a name
the ranker keeps nominating, which is why the wide-stop challenger uses the
cooldown. Neither is asserted to be better here; the wind tunnel scores them.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/pipeline/app"))

from engine import reentry_blocked  # noqa: E402


class TestPeakPolicyIsTheDefault:
    def test_default_policy_is_peak(self):
        """The champion must not silently change rules."""
        assert reentry_blocked(90.0, 100.0) is True
        assert reentry_blocked(101.0, 100.0) is False

    def test_at_the_peak_still_blocks(self):
        assert reentry_blocked(100.0, 100.0) is True

    def test_elapsed_sessions_are_ignored_under_peak(self):
        assert reentry_blocked(90.0, 100.0, sessions_since_stop=999) is True

    def test_unknown_inputs_never_block(self):
        assert reentry_blocked(None, 100.0) is False
        assert reentry_blocked(90.0, None) is False
        assert reentry_blocked(90.0, float("nan")) is False


class TestCooldownPolicy:
    def test_blocked_inside_the_window_regardless_of_price(self):
        """Price is irrelevant here — that is the whole difference. A name that has
        already recovered past its peak stays out until the timer expires."""
        assert reentry_blocked(500.0, 100.0, sessions_since_stop=5,
                               policy="cooldown", cooldown_sessions=21) is True

    def test_free_once_the_window_elapses(self):
        assert reentry_blocked(10.0, 100.0, sessions_since_stop=21,
                               policy="cooldown", cooldown_sessions=21) is False

    def test_the_boundary_is_inclusive_of_release(self):
        assert reentry_blocked(10.0, 100.0, sessions_since_stop=20,
                               policy="cooldown", cooldown_sessions=21) is True
        assert reentry_blocked(10.0, 100.0, sessions_since_stop=21,
                               policy="cooldown", cooldown_sessions=21) is False

    def test_an_unknown_stop_date_does_not_block(self):
        """Absence of evidence. Blocking here would silently drop a name out of the
        investable set with nothing recording why."""
        assert reentry_blocked(90.0, 100.0, sessions_since_stop=None,
                               policy="cooldown") is False

    def test_zero_cooldown_never_blocks(self):
        assert reentry_blocked(90.0, 100.0, sessions_since_stop=0,
                               policy="cooldown", cooldown_sessions=0) is False


class TestWhyBothExist:
    @pytest.mark.parametrize("stop_pct,needed_rally", [(0.15, 0.176), (0.30, 0.429)])
    def test_the_peak_rule_hardens_as_the_stop_widens(self, stop_pct, needed_rally):
        """Documents the arithmetic behind the design decision: the rally required
        to clear a peak block is stop_pct/(1-stop_pct), so a wider stop makes the
        block disproportionately harder to clear. This is not a property of the
        code so much as the reason the code has two policies."""
        stop_price = 100.0 * (1 - stop_pct)
        assert (100.0 / stop_price - 1) == pytest.approx(needed_rally, abs=0.001)
        # one tick under the peak is still blocked, however long it has been
        assert reentry_blocked(99.99, 100.0) is True
