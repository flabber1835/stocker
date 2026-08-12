"""Differentials against the retained standalone controller state machines."""
import importlib.util
from pathlib import Path
import sys

from sentinel.controller.frozen_rule import load
from sentinel.controller.machine import Controller, Observation


def _reference():
    path = (Path(__file__).parents[2] / "docs" /
            "sentinel-reference-implementation" / "sentinel_1p1_standalone.py")
    spec = importlib.util.spec_from_file_location("sentinel_standalone", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ob(i, *, dd=-0.05, shock=False, healthy=False, stops20=0):
    return Observation(
        session=f"S{i:03d}", shadow_nav=100.0 * (1.0 + dd),
        shadow_drawdown=dd,
        shadow_r5=-0.06 if shock else 0.01,
        shadow_r10=-0.10 if shock else 0.01,
        shadow_r20=0.01 if healthy else -0.01,
        shadow_r40=-0.04, damaged_breadth=0.50 if healthy else (0.90 if shock else 0.70),
        green_breadth=0.30 if healthy else (0.10 if shock else 0.15),
        damaged_breadth_delta5=0.50 if shock else 0.0,
        spy_r20=-0.02 if shock else 0.01,
        spy_vol_ratio=0.05 if shock else 0.0, stops20=stops20)


def test_binary_and_parent_fast_match_standalone_on_boundaries():
    ref = _reference()
    binary = ref.BinaryStress()
    base = ref.FastState(base_mode=True)
    parent = ref.FastState(base_mode=False)
    ctl = Controller(load())
    state = ctl.initial_state()
    sequence = []
    # binary entry, exact 20-session dwell and healthy exit; fast entry/exit,
    # attempted retrigger while disarmed, exact rearm, then retrigger.
    sequence += [(-0.155, False, False, 0)]
    sequence += [(-0.14, False, False, 0)] * 17
    sequence += [(-0.14, False, True, 2)] * 3
    sequence += [(-0.10, True, False, 0)]
    sequence += [(-0.09, False, False, 0)] * 6
    sequence += [(-0.09, False, True, 0)] * 3
    sequence += [(-0.10, True, False, 0), (-0.05, False, False, 0),
                 (-0.10, True, False, 0)]
    for i, (dd, shock, healthy, stops) in enumerate(sequence):
        ob = _ob(i, dd=dd, shock=shock, healthy=healthy, stops20=stops)
        regular = binary.step(i, dd, ob.shadow_r20, stops)
        expected_base = base.step(i, shock, dd, healthy,
                                  entry_allowed=not regular)
        expected_fast = parent.step(i, shock, dd, healthy, entry_allowed=True)
        state, _ = ctl.step(observation=ob, state=state)
        assert state["ordinary_stress_active"] == regular
        assert state["base_fast_active"] == expected_base
        assert state["fast_severe_active"] == expected_fast


def test_stops20_two_is_healthy_but_three_breaks_the_streak():
    ctl = Controller(load())
    state = ctl.initial_state()
    state, _ = ctl.step(observation=_ob(0, dd=-0.155), state=state)
    for i in range(1, 19):
        state, _ = ctl.step(observation=_ob(i, dd=-0.14), state=state)
    state, _ = ctl.step(observation=_ob(19, dd=-0.14, healthy=True, stops20=2), state=state)
    assert state["ordinary_healthy_streak"] == 1
    state, _ = ctl.step(observation=_ob(20, dd=-0.14, healthy=True, stops20=3), state=state)
    assert state["ordinary_stress_active"]
    assert state["ordinary_healthy_streak"] == 0


def test_slow_state_exact_minimum_dwell_and_sixth_healthy_exit():
    ref = _reference()
    expected = ref.SlowState()
    ctl = Controller(load())
    state = ctl.initial_state()
    # Seed slow directly: this isolates the exact standalone SlowState ordering.
    state.update(slow_severe_active=True, slow_severe_age=0,
                 slow_healthy_streak=0)
    expected.step(0, True, False)
    for i in range(1, 26):
        healthy = i >= 20
        state, _ = ctl.step(observation=_ob(i, healthy=healthy), state=state)
        want = expected.step(i, False, healthy)
        assert state["slow_severe_active"] == want
    assert not state["slow_severe_active"]
