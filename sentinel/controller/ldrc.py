"""Authoritative Simplified Sentinel Concordance LD-RC state machine."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Optional, Tuple

STRATEGY_ID = "sentinel-concordance-simplified-ldrc"
STRATEGY_VERSION = 3
STATE_VERSION = 3

RESEARCH_ARCHITECTURE_COMMIT = "2809eef7948ef1a98452dce677ec3f920405cdbe"
SIMPLIFICATION_COMMIT = "b0a700cf82ae58af8e3bbdcc91ff053b0341d9e2"
INCOMPLETE_MINISPEC_COMMIT = "f29f67951b11150e2ef26147652549a0092dad61"


@dataclass(frozen=True)
class LDRCConfig:
    divergence_ceiling: float = 0.55
    wc_drawdown_trigger: float = -0.10
    recent_r20_trigger: float = -0.08
    spy_r20_floor: float = 0.00
    recovery_sessions: int = 7
    spy_v_rebound: float = 0.11


@dataclass(frozen=True)
class LDRCState:
    version: int = STATE_VERSION
    recovery_episode: bool = False
    divergence_latched: bool = False
    recovery_streak: int = 0
    previous_native_allocation: float = 1.0
    previous_desired_allocation: float = 1.0
    last_session: Optional[str] = None


@dataclass(frozen=True)
class LDRCDecision:
    session: str
    native_allocation: float
    desired_allocation: float
    recovery_episode: bool
    divergence_latched: bool
    recovery_streak: int
    healthy: bool
    v_rebound: bool
    reason: str
    entry_evidence_available: bool
    recovery_evidence_available: bool


def _finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _validate_config(cfg: LDRCConfig) -> None:
    if not _finite(cfg.divergence_ceiling) or not 0.0 <= cfg.divergence_ceiling <= 1.0:
        raise ValueError("divergence_ceiling must be finite and in [0, 1]")
    if (isinstance(cfg.recovery_sessions, bool)
            or not isinstance(cfg.recovery_sessions, int)
            or cfg.recovery_sessions <= 0):
        raise ValueError("recovery_sessions must be a positive integer")
    for name in ("wc_drawdown_trigger", "recent_r20_trigger", "spy_r20_floor", "spy_v_rebound"):
        if not _finite(getattr(cfg, name)):
            raise ValueError(f"{name} must be finite")


def _validate_state(state: LDRCState, cfg: LDRCConfig) -> None:
    _validate_config(cfg)
    if state.version != STATE_VERSION:
        raise ValueError(f"unsupported LD-RC state version {state.version!r}")
    if not isinstance(state.recovery_episode, bool):
        raise ValueError("recovery_episode must be bool")
    if not isinstance(state.divergence_latched, bool):
        raise ValueError("divergence_latched must be bool")
    if (isinstance(state.recovery_streak, bool)
            or not isinstance(state.recovery_streak, int)
            or state.recovery_streak < 0):
        raise ValueError("recovery_streak must be a non-negative integer")
    if not _finite(state.previous_native_allocation) or not 0.0 <= state.previous_native_allocation <= 1.0:
        raise ValueError("previous_native_allocation must be finite and in [0, 1]")
    if not _finite(state.previous_desired_allocation) or not 0.0 <= state.previous_desired_allocation <= 1.0:
        raise ValueError("previous_desired_allocation must be finite and in [0, 1]")
    if state.previous_desired_allocation > state.previous_native_allocation + 1e-15:
        raise ValueError("previous desired allocation cannot exceed previous native allocation")
    if state.last_session is not None and (not isinstance(state.last_session, str) or not state.last_session):
        raise ValueError("last_session must be None or a non-empty session string")


def state_to_dict(state: LDRCState, cfg: LDRCConfig = LDRCConfig()) -> dict:
    _validate_state(state, cfg)
    return {
        "version": state.version,
        "recovery_episode": state.recovery_episode,
        "divergence_latched": state.divergence_latched,
        "recovery_streak": state.recovery_streak,
        "previous_native_allocation": state.previous_native_allocation,
        "previous_desired_allocation": state.previous_desired_allocation,
        "last_session": state.last_session,
    }


def state_from_dict(payload: Mapping[str, object], cfg: LDRCConfig = LDRCConfig()) -> LDRCState:
    if not isinstance(payload, Mapping):
        raise ValueError("LD-RC state payload must be a mapping")
    required = {
        "version", "recovery_episode", "divergence_latched",
        "recovery_streak", "previous_native_allocation",
        "previous_desired_allocation", "last_session",
    }
    if set(payload) != required:
        raise ValueError("LD-RC state payload has missing or unknown fields")
    state = LDRCState(
        version=payload["version"],  # type: ignore[arg-type]
        recovery_episode=payload["recovery_episode"],  # type: ignore[arg-type]
        divergence_latched=payload["divergence_latched"],  # type: ignore[arg-type]
        recovery_streak=payload["recovery_streak"],  # type: ignore[arg-type]
        previous_native_allocation=payload["previous_native_allocation"],  # type: ignore[arg-type]
        previous_desired_allocation=payload["previous_desired_allocation"],  # type: ignore[arg-type]
        last_session=payload["last_session"],  # type: ignore[arg-type]
    )
    _validate_state(state, cfg)
    return state


def ldrc_step(
    *, session: str, native_allocation: float,
    effective_native_allocation: Optional[float], wc_drawdown: Optional[float],
    recent_r20: Optional[float], recent_r40: Optional[float],
    spy_r20: Optional[float], state: LDRCState,
    cfg: LDRCConfig = LDRCConfig(),
) -> Tuple[LDRCState, LDRCDecision]:
    _validate_state(state, cfg)
    if not isinstance(session, str) or not session:
        raise ValueError("session must be a non-empty session string")
    if state.last_session is not None and session <= state.last_session:
        raise ValueError("LD-RC sessions must advance strictly once")
    if not _finite(native_allocation):
        raise ValueError("native_allocation must be finite")
    native = float(native_allocation)
    if not 0.0 <= native <= 1.0:
        raise ValueError("native_allocation must be in [0, 1]")
    if effective_native_allocation is not None:
        if not _finite(effective_native_allocation) or not 0.0 <= float(effective_native_allocation) <= 1.0:
            raise ValueError("effective_native_allocation must be None or finite in [0, 1]")

    recovery_available = _finite(recent_r20) and _finite(recent_r40)
    healthy = bool(recovery_available and float(recent_r20) > 0.0 and float(recent_r40) > 0.0)
    streak = state.recovery_streak + 1 if healthy else 0
    v_rebound = bool(_finite(spy_r20) and float(spy_r20) > cfg.spy_v_rebound)

    episode = state.recovery_episode
    latched = state.divergence_latched
    reasons = []

    if state.previous_native_allocation >= 1.0 - 1e-12 and native < 1.0 - 1e-12:
        episode = True
        reasons.append("RECOVERY_EPISODE_START")

    cleared_this_session = bool(
        latched and (streak >= cfg.recovery_sessions or v_rebound))
    if cleared_this_session:
        latched = False
        reasons.append("DIVERGENCE_CLEAR_PERSISTENCE" if streak >= cfg.recovery_sessions else "DIVERGENCE_CLEAR_SPY_V_REBOUND")

    desired = native
    if episode and native >= 1.0 - 1e-12:
        if streak >= cfg.recovery_sessions or v_rebound:
            episode = False
            desired = 1.0
            reasons.append("FULL_RISK_CERTIFIED_PERSISTENCE" if streak >= cfg.recovery_sessions else "FULL_RISK_CERTIFIED_SPY_V_REBOUND")
        else:
            desired = state.previous_desired_allocation
            reasons.append("FULL_RISK_HELD_FOR_CONCORDANCE")

    entry_available = (
        _finite(wc_drawdown) and _finite(recent_r20) and _finite(spy_r20)
        and effective_native_allocation is not None and _finite(effective_native_allocation)
    )
    if not latched and not cleared_this_session:
        effective_full = bool(effective_native_allocation is not None and float(effective_native_allocation) >= 1.0 - 1e-12)
        divergence = bool(
            native >= 1.0 - 1e-12 and effective_full and entry_available
            and float(wc_drawdown) <= cfg.wc_drawdown_trigger
            and float(recent_r20) <= cfg.recent_r20_trigger
            and float(spy_r20) >= cfg.spy_r20_floor
        )
        if divergence:
            latched = True
            reasons.append("LD_ENTER_DIVERGENCE")
        elif native >= 1.0 - 1e-12 and not entry_available:
            reasons.append("LD_ENTRY_EVIDENCE_UNAVAILABLE")

    if latched:
        desired = min(desired, cfg.divergence_ceiling)
    desired = min(native, desired)
    if desired > native + 1e-15:
        raise AssertionError("LD-RC must never increase native exposure")

    next_state = LDRCState(
        version=STATE_VERSION, recovery_episode=episode,
        divergence_latched=latched, recovery_streak=streak,
        previous_native_allocation=native,
        previous_desired_allocation=desired, last_session=session,
    )
    _validate_state(next_state, cfg)
    return next_state, LDRCDecision(
        session=session, native_allocation=native,
        desired_allocation=desired, recovery_episode=episode,
        divergence_latched=latched, recovery_streak=streak,
        healthy=healthy, v_rebound=v_rebound,
        reason="|".join(reasons) if reasons else "NORMAL",
        entry_evidence_available=entry_available,
        recovery_evidence_available=recovery_available,
    )


__all__ = [
    "STRATEGY_ID", "STRATEGY_VERSION", "STATE_VERSION",
    "RESEARCH_ARCHITECTURE_COMMIT", "SIMPLIFICATION_COMMIT",
    "INCOMPLETE_MINISPEC_COMMIT", "LDRCConfig", "LDRCState",
    "LDRCDecision", "state_to_dict", "state_from_dict", "ldrc_step",
]
