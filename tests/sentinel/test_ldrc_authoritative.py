import json
import math

import pytest

from sentinel.controller.ldrc import (
    LDRCState,
    STATE_VERSION,
    ldrc_step,
    state_from_dict,
    state_to_dict,
)


def step(day, native=1.0, dd=-0.05, r20=0.01, r40=0.01, spy=0.01, state=None):
    return ldrc_step(
        session=f"2026-01-{day:02d}",
        native_allocation=native,
        wc_drawdown=dd,
        recent_r20=r20,
        recent_r40=r40,
        spy_r20=spy,
        state=state or LDRCState(),
    )


def test_missing_recovery_gate_is_present_and_caps_native_100_at_65():
    s, d = step(1, native=0.55)
    assert s.full_risk_blocked is True
    assert s.divergence_latched is False
    assert d.final_allocation == 0.55

    s, d = step(2, native=0.65, r20=-0.01, r40=-0.01, state=s)
    assert d.final_allocation == 0.65
    s, d = step(3, native=1.0, r20=-0.01, r40=-0.01, state=s)
    assert d.final_allocation == 0.65
    assert s.full_risk_blocked is True


def test_recovery_gate_clears_on_seventh_consecutive_healthy_session():
    s, _ = step(1, native=0.55, r20=-0.01, r40=-0.01)
    for day in range(2, 8):
        s, d = step(day, native=1.0, r20=0.01, r40=0.02, state=s)
        assert s.full_risk_blocked is True
        assert d.final_allocation == 0.65
    s, d = step(8, native=1.0, r20=0.01, r40=0.02, state=s)
    assert s.full_risk_blocked is False
    assert d.final_allocation == 1.0


def test_failed_or_missing_recovery_evidence_resets_streak():
    s, _ = step(1, native=0.55, r20=-0.01, r40=-0.01)
    s, _ = step(2, native=0.65, r20=0.01, r40=0.01, state=s)
    s, _ = step(3, native=0.65, r20=0.01, r40=0.01, state=s)
    assert s.recovery_streak == 2
    s, _ = step(4, native=0.65, r20=None, r40=0.01, state=s)
    assert s.recovery_streak == 0


def test_spy_v_rebound_is_strictly_greater_than_11_percent():
    s, _ = step(1, native=0.55, r20=-0.01, r40=-0.01)
    s, d = step(2, native=1.0, r20=-0.01, r40=-0.01, spy=0.11, state=s)
    assert s.full_risk_blocked is True
    assert d.final_allocation == 0.65
    s, d = step(
        3,
        native=1.0,
        r20=-0.01,
        r40=-0.01,
        spy=math.nextafter(0.11, math.inf),
        state=s,
    )
    assert s.full_risk_blocked is False
    assert d.final_allocation == 1.0


def test_three_signal_divergence_boundary_latches_55_and_arms_recovery_gate():
    s, d = step(1, native=1.0, dd=-0.10, r20=-0.08, r40=-0.20, spy=0.0)
    assert s.divergence_latched is True
    assert s.full_risk_blocked is True
    assert d.final_allocation == 0.55


def test_divergence_boundaries_are_inclusive_and_one_ulp_outside_does_not_fire():
    s, d = step(
        1,
        dd=math.nextafter(-0.10, math.inf),
        r20=-0.08,
        r40=-0.20,
        spy=0.0,
    )
    assert not s.divergence_latched and d.final_allocation == 1.0
    s, d = step(
        1,
        dd=-0.10,
        r20=math.nextafter(-0.08, math.inf),
        r40=-0.20,
        spy=0.0,
    )
    assert not s.divergence_latched and d.final_allocation == 1.0
    s, d = step(
        1,
        dd=-0.10,
        r20=-0.08,
        r40=-0.20,
        spy=math.nextafter(0.0, -math.inf),
    )
    assert not s.divergence_latched and d.final_allocation == 1.0


def test_divergence_latch_is_persistent_and_native_risk_off_always_wins():
    s, _ = step(1, native=1.0, dd=-0.10, r20=-0.08, r40=-0.20, spy=0.0)
    s, d = step(
        2,
        native=1.0,
        dd=0.0,
        r20=-0.01,
        r40=-0.01,
        spy=-0.05,
        state=s,
    )
    assert s.divergence_latched and d.final_allocation == 0.55
    s, d = step(
        3,
        native=0.0,
        dd=0.0,
        r20=-0.01,
        r40=-0.01,
        spy=-0.05,
        state=s,
    )
    assert s.divergence_latched and d.final_allocation == 0.0


def test_divergence_and_recovery_gate_clear_together_only_on_independent_recovery():
    s, _ = step(1, native=1.0, dd=-0.10, r20=-0.08, r40=-0.20, spy=0.0)
    for day in range(2, 8):
        s, d = step(
            day,
            native=1.0,
            dd=-0.02,
            r20=0.01,
            r40=0.01,
            spy=0.01,
            state=s,
        )
        assert d.final_allocation == 0.55
    s, d = step(
        8,
        native=1.0,
        dd=-0.02,
        r20=0.01,
        r40=0.01,
        spy=0.01,
        state=s,
    )
    assert not s.divergence_latched
    assert not s.full_risk_blocked
    assert d.final_allocation == 1.0


def test_missing_entry_evidence_cannot_create_a_new_divergence_latch():
    s, d = step(1, native=1.0, dd=None, r20=-0.20, r40=-0.20, spy=0.02)
    assert not s.divergence_latched
    assert d.final_allocation == 1.0
    assert d.entry_evidence_available is False


def test_state_json_roundtrip_is_exact_and_schema_is_strict():
    s = LDRCState(
        version=STATE_VERSION,
        full_risk_blocked=True,
        divergence_latched=True,
        recovery_streak=3,
        last_session="2026-01-05",
    )
    payload = json.loads(json.dumps(state_to_dict(s)))
    assert state_from_dict(payload) == s
    payload["unknown"] = 1
    with pytest.raises(ValueError):
        state_from_dict(payload)


def test_duplicate_or_out_of_order_session_refuses_instead_of_double_aging():
    s, _ = step(1, native=0.55, r20=-0.01, r40=-0.01)
    s, _ = step(2, native=0.65, r20=0.01, r40=0.01, state=s)
    with pytest.raises(ValueError, match="strictly once"):
        step(2, native=0.65, r20=0.01, r40=0.01, state=s)


def test_overlay_never_raises_native_exposure_for_all_standard_native_levels():
    s = LDRCState(full_risk_blocked=True, divergence_latched=True)
    for i, native in enumerate((0.0, 0.55, 0.65, 1.0), start=1):
        s, d = step(i, native=native, r20=-0.01, r40=-0.01, state=s)
        assert d.final_allocation <= native
