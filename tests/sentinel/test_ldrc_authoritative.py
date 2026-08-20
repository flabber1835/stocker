import json
import math
import pytest

from sentinel.controller.ldrc import LDRCState, STATE_VERSION, ldrc_step, state_from_dict, state_to_dict


def step(day, *, native=1.0, effective=1.0, dd=-0.05, r20=0.01, r40=0.01, spy=0.01, state=None):
    return ldrc_step(
        session=f"2026-01-{day:02d}",
        native_allocation=native,
        effective_native_allocation=effective,
        wc_drawdown=dd,
        recent_r20=r20,
        recent_r40=r40,
        spy_r20=spy,
        state=state or LDRCState(),
    )


def test_native_derisk_starts_episode_without_blocking_partial_recovery():
    s, d = step(1, native=0.55, effective=1.0, r20=-0.01, r40=-0.01)
    assert s.recovery_episode
    assert d.desired_allocation == 0.55
    s, d = step(2, native=0.65, effective=0.55, r20=-0.01, r40=-0.01, state=s)
    assert d.desired_allocation == 0.65


def test_live_streak_gates_only_the_native_return_to_100():
    s, _ = step(1, native=0.55, r20=-0.01, r40=-0.01)
    for day in range(2, 8):
        s, _ = step(day, native=0.65, effective=0.65, r20=0.01, r40=0.02, state=s)
    assert s.recovery_streak == 6
    s, d = step(8, native=1.0, effective=0.65, r20=0.01, r40=0.02, state=s)
    assert s.recovery_streak == 7
    assert not s.recovery_episode
    assert d.desired_allocation == 1.0


def test_earned_streak_is_not_a_permanent_certificate():
    s, _ = step(1, native=0.55, r20=-0.01, r40=-0.01)
    for day in range(2, 9):
        s, _ = step(day, native=0.65, effective=0.65, r20=0.01, r40=0.02, state=s)
    assert s.recovery_streak >= 7
    s, _ = step(9, native=0.65, effective=0.65, r20=-0.01, r40=0.02, state=s)
    assert s.recovery_streak == 0
    s, d = step(10, native=1.0, effective=0.65, r20=0.01, r40=0.02, state=s)
    assert s.recovery_episode
    assert d.desired_allocation == 0.65


def test_spy_rebound_does_not_clear_episode_while_native_still_defensive():
    s, _ = step(1, native=0.0, effective=1.0, r20=-0.1, r40=-0.1, spy=0.12)
    assert s.recovery_episode
    s, d = step(2, native=0.55, effective=0.0, r20=-0.1, r40=-0.1, spy=0.12, state=s)
    assert s.recovery_episode
    assert d.desired_allocation == 0.55


def test_spy_rebound_certifies_current_native_100_request_only():
    s, _ = step(1, native=0.55, r20=-0.1, r40=-0.1)
    s, d = step(2, native=1.0, effective=0.65, r20=-0.1, r40=-0.1, spy=math.nextafter(0.11, math.inf), state=s)
    assert not s.recovery_episode
    assert d.desired_allocation == 1.0


def test_spy_exactly_11_percent_does_not_certify():
    s, _ = step(1, native=0.55, r20=-0.1, r40=-0.1)
    s, d = step(2, native=1.0, effective=0.65, r20=-0.1, r40=-0.1, spy=0.11, state=s)
    assert s.recovery_episode
    assert d.desired_allocation == 0.55


def test_divergence_boundary_latches_55():
    s, d = step(1, native=1.0, effective=1.0, dd=-0.10, r20=-0.08, r40=-0.2, spy=0.0)
    assert s.divergence_latched
    assert d.desired_allocation == 0.55


def test_divergence_requires_effective_native_full_risk():
    s, d = step(1, native=1.0, effective=0.65, dd=-0.10, r20=-0.08, r40=-0.2, spy=0.0)
    assert not s.divergence_latched
    assert d.desired_allocation == 1.0


def test_divergence_latch_clears_on_continuous_recovery_even_if_native_below_100():
    s, _ = step(1, dd=-0.10, r20=-0.08, r40=-0.2, spy=0.0)
    for day in range(2, 9):
        s, d = step(day, native=0.65, effective=0.65, dd=-0.02, r20=0.01, r40=0.01, spy=0.01, state=s)
    assert not s.divergence_latched
    assert d.desired_allocation == 0.65


def test_missing_recovery_evidence_resets_live_streak():
    s, _ = step(1, native=0.55, r20=0.01, r40=0.01)
    assert s.recovery_streak == 1
    s, _ = step(2, native=0.65, effective=0.55, r20=None, r40=0.01, state=s)
    assert s.recovery_streak == 0


def test_state_json_roundtrip_strict():
    s = LDRCState(
        version=STATE_VERSION,
        recovery_episode=True,
        divergence_latched=True,
        recovery_streak=3,
        previous_native_allocation=0.65,
        previous_desired_allocation=0.55,
        last_session="2026-01-05",
    )
    payload = json.loads(json.dumps(state_to_dict(s)))
    assert state_from_dict(payload) == s
    payload["junk"] = 1
    with pytest.raises(ValueError):
        state_from_dict(payload)


def test_duplicate_session_refuses():
    s, _ = step(1, native=0.55)
    with pytest.raises(ValueError, match="strictly once"):
        step(1, native=0.65, state=s)
