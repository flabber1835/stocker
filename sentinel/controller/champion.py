"""Production binding of compact champion transitions to canonical state."""
from __future__ import annotations

from copy import deepcopy
import math

from .champion_frozen import CandidateA, Native

NATIVE_FIELDS = {
    "ordinary": "ordinary_stress_active", "binary_armed": "binary_armed",
    "ordinary_age": "ordinary_stress_age", "ordinary_h": "ordinary_healthy_streak",
    "base_fast": "base_fast_active", "base_fast_armed": "base_fast_armed",
    "base_fast_age": "base_fast_age", "base_fast_h": "base_fast_healthy_streak",
    "base_anchor": "base_stress_start_shadow_nav", "base_dur": "base_stress_duration",
    "fast": "fast_severe_active", "fast_armed": "fast_rearm_armed",
    "fast_age": "fast_severe_age", "fast_h": "fast_healthy_streak",
    "slow": "slow_severe_active", "slow_age": "slow_severe_age",
    "slow_h": "slow_healthy_streak",
}


def validate_native(state):
    from .machine import validate_controller_state
    before = validate_controller_state(state)
    if (before["ramp_active"] or before["ramp_step_index"] is not None
            or before["ramp_entry_session"] is not None
            or before["ramp_healthy_streak"] or before["_r40_history"]
            or before["last_target_core"] not in (0., 1.)):
        raise ValueError("champion state contains incompatible ramp history")
    Native.from_snapshot({"schema": Native._schema,
        "state": {key: before[field] for key, field in NATIVE_FIELDS.items()}})
    return before


def native_step(*, observation, state):
    from .machine import Decision, validate_controller_state
    before = validate_native(state)
    if before["last_session"] is not None and observation.session <= before["last_session"]:
        raise ValueError("champion native sessions must advance strictly once")
    native = Native.from_snapshot({"schema": Native._schema,
        "state": {key: before[field] for key, field in NATIVE_FIELDS.items()}})
    ob = observation
    target, fast, slow = native.step((ob.shadow_drawdown, ob.shadow_r5,
        ob.shadow_r10, ob.shadow_r20, ob.shadow_r40, ob.damaged_breadth,
        ob.green_breadth, ob.damaged_breadth_delta5, ob.spy_r20,
        ob.spy_vol_ratio, ob.stops20, ob.shadow_nav))
    after = deepcopy(before)
    after.update({field: getattr(native, key) for key, field in NATIVE_FIELDS.items()})
    after.update(last_session=ob.session, last_target_core=target)
    for active, stamp in (("ordinary_stress_active", "ordinary_stress_start_session"),
                          ("fast_severe_active", "fast_severe_entry_session"),
                          ("slow_severe_active", "slow_severe_entry_session")):
        if after[active] and not before[active]:
            after[stamp] = ob.session
    if after["ordinary_stress_active"] and not before["ordinary_stress_active"]:
        after["ordinary_stress_start_shadow_nav"] = ob.shadow_nav
    decision = Decision(session=ob.session, target_core_exposure=target,
        reason="CHAMPION_SEVERE" if target == 0 else "CHAMPION_NATIVE_FULL",
        fast_severe_active=native.fast, slow_severe_active=native.slow,
        evidence={"fast_signal": fast, "slow_signal": slow,
                  "native_snapshot": native.snapshot()})
    return validate_controller_state(after), decision


def validate_recovery(state):
    audit = state.get("champion_audit")
    if (not isinstance(audit, dict) or set(audit) != {"episodes", "concordance_releases"}
            or any(type(n) is not int or n < 0 for n in audit.values())):
        raise ValueError("champion audit state is invalid")
    if state.get("version") != 2:
        raise ValueError("champion requires recovery state version 2")
    for field in ("full_streak", "recent_positive_streak"):
        if type(state[field]) is not int or not 0 <= state[field] <= 8:
            raise ValueError("invalid champion snapshot counter: " + field)
    if any(type(state[field]) not in (int, float) or state[field] not in (0., 1.)
           for field in ("previous_native", "effective_native")):
        raise ValueError("champion prior native allocation must be binary")
    if state["previous_desired"] not in (0., .55, 1.):
        raise ValueError("invalid champion desired allocation")


def recover(*, state, native, wc_drawdown, recent_r20, recent_r40, spy_r20, wc_r20):
    from .median5 import validate
    result = deepcopy(validate(state))
    validate_recovery(state)
    if state["previous_native"] not in (0., 1.) or state["effective_native"] not in (0., 1.):
        raise ValueError("champion prior native allocation must be binary")
    candidate = CandidateA.from_snapshot({"schema": CandidateA._schema, "state": {
        "episode": state["episode"], "latched": state["latched"],
        "full_streak": state["full_streak"],
        "recent_positive_streak": state["recent_positive_streak"],
        "previous_native_was_full": state["previous_native"] == 1.,
        "_audit": deepcopy(state["champion_audit"]),
    }})
    target, reason = candidate.step(native, state["effective_native"], wc_drawdown,
        recent_r20, recent_r40, spy_r20, wc_r20)
    if not math.isfinite(target) or not 0 <= target <= native:
        raise ValueError("champion target violates native envelope")
    result.update(episode=candidate.episode, latched=candidate.latched,
        full_streak=candidate.full_streak,
        recent_positive_streak=candidate.recent_positive_streak,
        previous_native=native, previous_desired=target,
        effective_native=state["previous_native"], champion_audit=deepcopy(candidate._audit))
    return validate(result), {"desired_allocation": target, "reason": reason}
