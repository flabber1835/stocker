import math
import pytest
from sentinel.controller.ldrc import LDRCState, ldrc_step


def step(day, *, native=1.0, effective=1.0, dd=-0.05, r20=0.01, r40=0.01, spy=0.01, state=None):
    return ldrc_step(
        session=f"2026-01-{day:02d}", native_allocation=native,
        effective_native_allocation=effective, wc_drawdown=dd,
        recent_r20=r20, recent_r40=r40, spy_r20=spy,
        state=state or LDRCState())


def test_native_partial_recovery_is_not_blocked():
    state, decision = step(1, native=.55, r20=-.01, r40=-.01)
    assert state.recovery_episode and decision.desired_allocation == .55
    state, decision = step(2, native=.65, effective=.55, r20=-.01, r40=-.01, state=state)
    assert decision.desired_allocation == .65


def test_live_streak_gates_return_to_full():
    state, _ = step(1, native=.55, r20=-.01, r40=-.01)
    for day in range(2, 8):
        state, _ = step(day, native=.65, effective=.65, state=state)
    state, decision = step(8, native=1.0, effective=.65, state=state)
    assert state.recovery_streak == 7
    assert not state.recovery_episode
    assert decision.desired_allocation == 1.0


def test_unhealthy_session_erases_earned_streak():
    state, _ = step(1, native=.55, r20=-.01, r40=-.01)
    for day in range(2, 9):
        state, _ = step(day, native=.65, effective=.65, state=state)
    state, _ = step(9, native=.65, effective=.65, r20=-.01, r40=.01, state=state)
    state, decision = step(10, native=1.0, effective=.65, state=state)
    assert state.recovery_episode
    assert decision.desired_allocation == .65


def test_divergence_exact_boundary_latches_55():
    state, decision = step(1, dd=-.10, r20=-.08, r40=-.2, spy=0.0)
    assert state.divergence_latched
    assert decision.desired_allocation == .55


def test_spy_rebound_is_strictly_greater_than_11_percent():
    state, _ = step(1, native=.55, r20=-.1, r40=-.1)
    state, decision = step(2, native=1.0, effective=.65, r20=-.1, r40=-.1, spy=.11, state=state)
    assert state.recovery_episode and decision.desired_allocation == .55
    state2, _ = step(1, native=.55, r20=-.1, r40=-.1)
    state2, decision2 = step(2, native=1.0, effective=.65, r20=-.1, r40=-.1,
                             spy=math.nextafter(.11, math.inf), state=state2)
    assert not state2.recovery_episode and decision2.desired_allocation == 1.0
