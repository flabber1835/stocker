"""Versioned certified Median-5 native parent and Candidate A recovery."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
import math

from stock_strategy_shared.wealth_core.median5 import PROFILE, REFERENCE_AST
from .frozen_rule import load as load_frozen

STRATEGY_ID = "sentinel-median5-v1"


def enabled(identity):
    from .ex3_v5 import STRATEGY_ID as V5_ID
    return identity.get("strategy") in (STRATEGY_ID, V5_ID)


def wealth_config(identity):
    from .ex3_v5 import enabled as v5_enabled
    from stock_strategy_shared.wealth_core import median5, v5
    if not enabled(identity):
        raise ValueError("unknown Median-5 family strategy identity")
    return v5.config() if v5_enabled(identity) else median5.config()


def controller_config(identity):
    from .ex3_v5 import enabled as v5_enabled, load as v5_load
    if not enabled(identity):
        raise ValueError("unknown Median-5 family strategy identity")
    return v5_load() if v5_enabled(identity) else load()


def load():
    source = load_frozen()
    fast = {**source.fast_entry, "min_damaged_breadth": 0.88,
            "min_damaged_breadth_delta5": 0.30}
    healthy = replace(source.healthy, max_damaged_breadth=0.63)
    fast_recovery = deepcopy(source.fast_recovery)
    fast_recovery["healthy"]["max_damaged_breadth"] = 0.63
    slow_recovery = {**source.slow_recovery, "confirmation_sessions": 6,
                     "max_damaged_breadth": 0.63}
    cfg = replace(source, strategy_id=STRATEGY_ID, fast_entry=fast,
                  healthy=healthy, fast_recovery=fast_recovery,
                  slow_recovery=slow_recovery)
    payload = {"source": asdict(cfg), "profile": PROFILE,
               "reference_ast": REFERENCE_AST,
               "recovery": [0.55, -0.10, -0.085, 0., 8, 0.11, "CandidateA"]}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    return replace(cfg, digest=digest)


def fresh():
    return {"version": 1, "episode": False, "latched": False,
            "full_streak": 0, "recent_positive_streak": 0,
            "previous_native": 1., "previous_desired": 1.,
            "effective_native": 1., "last_session": None,
            "witness_nav": [1.], "selected": [], "selected_closes": {},
            "spy_history": [], "peer_keys": {}}


def remember_peer_keys(state, metadata):
    """Freeze the first observed metadata ordering across ticker renames."""
    for sid, item in metadata.items():
        state["peer_keys"].setdefault(sid, [item.ticker, item.first_session or "", sid])


def finite(value):
    return value is not None and math.isfinite(value)


def validate(raw):
    if set(raw) != set(fresh()) or raw["version"] != 1:
        raise ValueError("invalid Median-5 controller state schema")
    for key in ("episode", "latched"):
        if type(raw[key]) is not bool:
            raise ValueError("invalid Median-5 recovery flag")
    for key in ("full_streak", "recent_positive_streak"):
        if type(raw[key]) is not int or raw[key] < 0:
            raise ValueError("invalid Median-5 recovery counter")
    for key in ("previous_native", "previous_desired", "effective_native"):
        if not finite(raw[key]) or not 0 <= raw[key] <= 1:
            raise ValueError("invalid Median-5 allocation state")
    if raw["previous_desired"] > raw["previous_native"]:
        raise ValueError("Median-5 overlay exceeds native allocation")
    if (not 1 <= len(raw["witness_nav"]) <= 41
            or any(not finite(x) or x <= 0 for x in raw["witness_nav"])
            or len(raw["spy_history"]) > 254):
        raise ValueError("invalid Median-5 witness/peer history")
    if len(set(raw["selected"])) != len(raw["selected"]):
        raise ValueError("duplicate Median-5 witness member")
    if set(raw["selected_closes"]) != set(raw["selected"]):
        raise ValueError("Median-5 witness membership and marks disagree")
    if any(not finite(x) or x <= 0 for x in raw["selected_closes"].values()):
        raise ValueError("invalid Median-5 witness mark")
    for sid, key in raw["peer_keys"].items():
        if (not isinstance(sid, str) or not isinstance(key, list) or len(key) != 3
                or any(not isinstance(x, str) for x in key) or not key[0] or key[2] != sid):
            raise ValueError("invalid Median-5 immutable peer ordering key")
    json.dumps(raw, allow_nan=False)
    return raw


def recover(*, state, native, wc_drawdown, recent_r20, recent_r40,
            spy_r20, wc_r20, r40_floor=0., rec_sessions=8):
    """Candidate A: decisions depend solely on shadow strategy observations."""
    result = deepcopy(validate(state))
    if not finite(native) or not 0 <= native <= 1:
        raise ValueError("invalid Median-5 native allocation")
    full = finite(recent_r20) and finite(recent_r40) and recent_r20 > 0 and recent_r40 > r40_floor
    result["full_streak"] = state["full_streak"]+1 if full else 0
    rebound = finite(spy_r20) and spy_r20 > 0.11
    reasons = []
    if state["previous_native"] >= 1-1e-12 and native < 1-1e-12:
        result["episode"] = True
        result["recent_positive_streak"] = 0
        reasons.append("RECOVERY_EPISODE_START")
    positive = result["episode"] and native > 0 and finite(recent_r20) and recent_r20 > 0
    result["recent_positive_streak"] = result["recent_positive_streak"]+1 if positive else 0
    cleared = result["latched"] and (result["full_streak"] >= rec_sessions or rebound)
    if cleared:
        result["latched"] = False
        reasons.append("DIVERGENCE_CLEAR")
    desired = native
    if result["episode"] and native >= 1-1e-12:
        concordant = (result["recent_positive_streak"] >= rec_sessions
                      and finite(wc_r20) and wc_r20 > 0
                      and finite(recent_r20) and recent_r20 >= wc_r20
                      and finite(spy_r20) and spy_r20 >= wc_r20)
        if result["full_streak"] >= rec_sessions or rebound or concordant:
            result["episode"] = False
            desired = 1.
            reason = ("FULL_RISK_CERTIFIED_PERSISTENCE" if result["full_streak"] >= rec_sessions
                      else "FULL_RISK_CERTIFIED_SPY_V_REBOUND" if rebound
                      else "FULL_RISK_CERTIFIED_CROSS_SURFACE")
            reasons.append(reason)
            result["recent_positive_streak"] = 0
        else:
            desired = state["previous_desired"]
            reasons.append("FULL_RISK_HELD")
    if not result["latched"] and not cleared:
        if (native >= 1-1e-12 and state["effective_native"] >= 1-1e-12
                and finite(wc_drawdown) and wc_drawdown <= -0.10
                and finite(recent_r20) and recent_r20 <= -0.085
                and finite(spy_r20) and spy_r20 >= 0):
            result["latched"] = True
            reasons.append("LD_ENTER_DIVERGENCE")
    if result["latched"]:
        desired = min(desired, 0.55)
    desired = min(desired, native)
    result["effective_native"] = state["previous_native"]
    result["previous_native"] = native
    result["previous_desired"] = desired
    return validate(result), {"desired_allocation": desired,
                              "reason": "|".join(reasons) or "NORMAL"}


def witness(state, *, session, candidates, closes, terminals=()):
    """Prior membership earns today's return; terminated names leave at close."""
    result = deepcopy(state)
    if state["last_session"] is not None and session <= state["last_session"]:
        raise ValueError("Median-5 witness sessions must advance strictly once")
    returns = []
    for sid in state["selected"]:
        now, before = closes.get(sid), state["selected_closes"].get(sid)
        if not (finite(now) and now > 0 and finite(before) and before > 0):
            raise ValueError(f"unresolved recent-leadership return: {session} {sid}")
        returns.append(now/before-1)
    change = sum(returns)/len(returns) if returns else 0.
    navs = (state["witness_nav"] + [state["witness_nav"][-1]*(1+change)])[-41:]
    k = min(len(candidates), max(25, math.ceil(len(candidates)*0.1)))
    selected = [c.security_id for c in sorted(candidates, key=lambda c: (-c.recent, c.security_id))[:k]
                if c.security_id not in terminals]
    result.update(last_session=session, witness_nav=navs, selected=selected,
                  selected_closes={sid: closes[sid] for sid in selected})
    return result, {"recent_r20": navs[-1]/navs[-21]-1 if len(navs) > 20 else None,
                    "recent_r40": navs[-1]/navs[-41]-1 if len(navs) > 40 else None}
