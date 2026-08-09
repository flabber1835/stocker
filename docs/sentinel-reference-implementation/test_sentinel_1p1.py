"""Synthetic unit tests for Sentinel 1.1. No historical oracle data is used."""
import math
from sentinel_1p1_standalone import BinaryStress, FastState, SlowState, SentinelRamp


def test_binary_stress_hysteresis():
    s = BinaryStress()
    assert s.step(0, -0.10, math.nan, 0) is False
    assert s.step(1, -0.155, -0.05, 3) is True
    for i in range(2, 21):
        assert s.step(i, -0.16, 0.01, 0) is True
    # Three healthy closes after minimum hold permit exit.
    s.step(21, -0.14, 0.01, 0)
    s.step(22, -0.14, 0.01, 0)
    assert s.step(23, -0.14, 0.01, 0) is False


def test_fast_state_minimum_hold_and_rearm():
    f = FastState(base_mode=False)
    healthy = False
    assert f.step(0, True, -0.12, healthy, True) is True
    for i in range(1, 9):
        assert f.step(i, False, -0.08, False, True) is True
    f.step(9, False, -0.08, True, True)
    f.step(10, False, -0.08, True, True)
    assert f.step(11, False, -0.08, True, True) is False
    # Not rearmed until DD recovers above -6 and the trigger is absent.
    assert f.armed is False
    f.step(12, False, -0.05, False, True)
    assert f.armed is True


def test_slow_state_recovery():
    s = SlowState()
    assert s.step(0, True, False) is True
    for i in range(1, 20):
        assert s.step(i, False, False) is True
    # Historical controller ordering exits after established recovery streak.
    for i in range(20, 25):
        assert s.step(i, False, True) is True
    assert s.step(25, False, True) is False


def test_sentinel_recovery_ramp():
    r = SentinelRamp()
    # Six r40 observations; falling five-session delta forces 55% recovery.
    hist = [0.05, 0.04, 0.03, 0.02, 0.01, 0.00]
    assert r.next_target(10, 0.0, 1.0, hist, True) == 0.55
    for i in range(9):
        assert r.next_target(11+i, 1.0, 1.0, hist, True) == 0.55
    assert r.next_target(20, 1.0, 1.0, hist, True) == 0.65
    for i in range(9):
        assert r.next_target(21+i, 1.0, 1.0, hist, True) == 0.65
    assert r.next_target(30, 1.0, 1.0, hist, True) == 1.0


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for test in tests:
        test()
        print('PASS', test.__name__)
