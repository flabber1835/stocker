"""Research attachment of the exact frozen controller to the canonical state.

Installed only in the disposable application tree by stage.py. The canonical
Wealth Core book, loader, persistence and execution layers own their usual state.
"""
from __future__ import annotations

from copy import deepcopy
import math

from .champion_frozen import CandidateA, Native


def warmup_regime(published, prior):
    """Exact available initial SPY prefix; the ordinary loader owns close 41+."""
    from sentinel.feed.calendar import sessions_in_range
    from sentinel.regime.spy import spy_regime
    expected=sessions_in_range("2006-01-03",published.session)
    if (not 1<=len(expected)<=40 or list(published.spy_sessions)!=expected
            or list(published.spy_expected_sessions)!=expected
            or len(published.spy_closeadj)!=len(expected)
            or prior.feed["session_index"]!=len(expected)-2
            or prior.wealth_core["episodes"] or prior.pending):
        raise ValueError("invalid champion SPY bootstrap prefix")
    return spy_regime(published.spy_closeadj)

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


def native_step(*, observation, state):
    from .machine import Decision, validate_controller_state
    before = validate_controller_state(state)
    if before["last_session"] is not None and observation.session <= before["last_session"]:
        raise ValueError("champion native sessions must advance strictly once")
    if before["ramp_active"] or before["ramp_step_index"] is not None or before["ramp_healthy_streak"] or before["_r40_history"]:
        raise ValueError("champion state contains incompatible ramp history")
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


def recover(*, state, native, wc_drawdown, recent_r20, recent_r40, spy_r20, wc_r20):
    from .median5 import validate
    result = deepcopy(validate(state))
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
