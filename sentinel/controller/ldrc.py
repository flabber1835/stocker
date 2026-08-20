"""Authoritative Simplified Sentinel Concordance LD-RC state machine.

This module preserves the complete corrected research architecture. The earlier
mini-spec retained only the divergence latch and accidentally omitted the
independent recovery gate that delays an ordinary native 65% -> 100% restoration.
That omission materially changes the historical strategy and is therefore a
strategy-semantic defect, not a documentation nit.

Complete architecture:

1. Native Sentinel systemic risk-off is always authoritative.
2. Native Sentinel may recover normally through 55% and 65%.
3. Returning to 100% is independently certified: recent-leadership r20 > 0 and
   r40 > 0 for seven consecutive sessions, or SPY r20 > 11%.
4. While native Sentinel is fully risk-on, a strategy-specific divergence
   (WC drawdown <= -10%, recent-leadership r20 <= -8%, SPY r20 >= 0%) latches a
   tighter 55% ceiling until the same independent recovery evidence clears it.
5. Close-time decisions are intents for the next executable open.

The overlay can only reduce native exposure:
    final = min(native, recovery_ceiling, divergence_ceiling)

Research lineage:
- corrected post-dividend architecture: 2809eef7948ef1a98452dce677ec3f920405cdbe
- simplification pass: b0a700cf82ae58af8e3bbdcc91ff053b0341d9e2
- incomplete historical mini-spec: f29f67951b11150e2ef26147652549a0092dad61

This is pure strategy code. It performs no I/O and has no broker authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Optional, Tuple

STRATEGY_ID = "sentinel-concordance-simplified-ldrc"
STRATEGY_VERSION = 2
STATE_VERSION = 2

RESEARCH_ARCHITECTURE_COMMIT = "2809eef7948ef1a98452dce677ec3f920405cdbe"
SIMPLIFICATION_COMMIT = "b0a700cf82ae58af8e3bbdcc91ff053b0341d9e2"
INCOMPLETE_MINISPEC_COMMIT = "f29f67951b11150e2ef26147652549a0092dad61"


@dataclass(frozen=True)
class LDRCConfig:
    recovery_ceiling: float = 0.65
    divergence_ceiling: float = 0.55
    wc_drawdown_trigger: float = -0.10
    recent_r20_trigger: float = -0.08
    spy_r20_floor: float = 0.00
    recovery_sessions: int = 7
    spy_v_rebound: float = 0.11


@dataclass(frozen=True)
class LDRCState:
    """Durable LD-RC strategy state.

    ``full_risk_blocked`` is the missing recovery-only Concordance state. It is
    armed when native Sentinel is below 100% and prevents a later native 100%
    target from exceeding 65% until independent recovery is certified.

    ``divergence_latched`` is the separate simplified three-signal protection
    state and imposes the tighter 55% ceiling.
    """

    version: int = STATE_VERSION
    full_risk_blocked: bool = False
    divergence_latched: bool = False
    recovery_streak: int = 0
    last_session: Optional[str] = None


@dataclass(frozen=True)
class LDRCDecision:
    session: str
    native_allocation: float
    recovery_ceiling: float
    divergence_ceiling: float
    final_allocation: float
    full_risk_blocked: bool
    divergence_latched: bool
    recovery_streak: int
    reason: str
    entry_evidence_available: bool
    recovery_evidence_available: bool
    v_rebound: bool


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _validate_config(cfg: LDRCConfig) -> None:
    for name in ("recovery_ceiling", "divergence_ceiling"):
        value = getattr(cfg, name)
        if not _finite(value) or not (0.0 <= float(value) <= 1.0):
            raise ValueError(f"{name} must be finite and in [0, 1]")
    if cfg.divergence_ceiling > cfg.recovery_ceiling:
        raise ValueError("divergence ceiling must be no greater than recovery ceiling")
    if not isinstance(cfg.recovery_sessions, int) or cfg.recovery_sessions <= 0:
        raise ValueError("recovery_sessions must be a positive integer")


def _validate_state(state: LDRCState, cfg: LDRCConfig) -> None:
    _validate_config(cfg)
    if state.version != STATE_VERSION:
        raise ValueError(f"unsupported LD-RC state version {state.version!r}")
    if not isinstance(state.full_risk_blocked, bool):
        raise ValueError("full_risk_blocked must be bool")
    if not isinstance(state.divergence_latched, bool):
        raise ValueError("divergence_latched must be bool")
    if state.divergence_latched and not state.full_risk_blocked:
        raise ValueError("a divergence latch must also block uncertified full risk")
    if not isinstance(state.recovery_streak, int) or state.recovery_streak < 0:
        raise ValueError("recovery_streak must be a non-negative integer")
    if not state.full_risk_blocked and state.recovery_streak != 0:
        raise ValueError("an open full-risk gate cannot carry a recovery streak")
    if state.full_risk_blocked and state.recovery_streak >= cfg.recovery_sessions:
        raise ValueError("blocked state cannot persist after completed recovery")
    if state.last_session is not None and (not isinstance(state.last_session, str) or not state.last_session):
        raise ValueError("last_session must be None or a non-empty ISO session string")


def state_to_dict(state: LDRCState, cfg: LDRCConfig = LDRCConfig()) -> dict:
    _validate_state(state, cfg)
    return {
        "version": state.version,
        "full_risk_blocked": state.full_risk_blocked,
        "divergence_latched": state.divergence_latched,
        "recovery_streak": state.recovery_streak,
        "last_session": state.last_session,
    }


def state_from_dict(payload: Mapping[str, object], cfg: LDRCConfig = LDRCConfig()) -> LDRCState:
    if not isinstance(payload, Mapping):
        raise ValueError("LD-RC state payload must be a mapping")
    required = {
        "version",
        "full_risk_blocked",
        "divergence_latched",
        "recovery_streak",
        "last_session",
    }
    if set(payload) != required:
        raise ValueError("LD-RC state payload has missing or unknown fields")
    state = LDRCState(
        version=payload["version"],  # type: ignore[arg-type]
        full_risk_blocked=payload["full_risk_blocked"],  # type: ignore[arg-type]
        divergence_latched=payload["divergence_latched"],  # type: ignore[arg-type]
        recovery_streak=payload["recovery_streak"],  # type: ignore[arg-type]
        last_session=payload["last_session"],  # type: ignore[arg-type]
    )
    _validate_state(state, cfg)
    return state


def ldrc_step(
    *,
    session: str,
    native_allocation: float,
    wc_drawdown: Optional[float],
    recent_r20: Optional[float],
    recent_r40: Optional[float],
    spy_r20: Optional[float],
    state: LDRCState,
    cfg: LDRCConfig = LDRCConfig(),
) -> Tuple[LDRCState, LDRCDecision]:
    """Advance the complete Simplified LD-RC architecture one decision session.

    Duplicate or out-of-order session advancement is refused so a crash/retry
    cannot double-age the seven-session recovery counter. Production persistence
    must commit this state atomically with the decision session.
    """

    _validate_state(state, cfg)
    if not isinstance(session, str) or not session:
        raise ValueError("session must be a non-empty ISO session string")
    if state.last_session is not None and session <= state.last_session:
        raise ValueError("LD-RC sessions must advance strictly once")
    if not _finite(native_allocation):
        raise ValueError("native_allocation must be finite")
    native = float(native_allocation)
    if not 0.0 <= native <= 1.0:
        raise ValueError("native_allocation must be in [0, 1]")

    entry_available = _finite(wc_drawdown) and _finite(recent_r20) and _finite(spy_r20)
    recovery_available = _finite(recent_r20) and _finite(recent_r40)
    independent_recovery = bool(
        recovery_available and float(recent_r20) > 0.0 and float(recent_r40) > 0.0
    )
    v_rebound = bool(_finite(spy_r20) and float(spy_r20) > cfg.spy_v_rebound)

    blocked = state.full_risk_blocked
    latched = state.divergence_latched
    streak = state.recovery_streak
    reasons = []

    # Any native de-risking episode arms the independent full-risk recovery gate.
    # Arm once; do not reset the streak every day native remains below 100%.
    if native < 1.0 and not blocked:
        blocked = True
        streak = 0
        reasons.append("RECOVERY_GATE_ARMED_NATIVE_RISK_OFF")

    # The same independent recovery authority clears both the ordinary 65->100
    # gate and the tighter divergence latch. Missing evidence resets persistence.
    if blocked:
        if v_rebound:
            blocked = False
            latched = False
            streak = 0
            reasons.append("RECOVERY_CLEAR_SPY_V_REBOUND")
        else:
            streak = streak + 1 if independent_recovery else 0
            if streak >= cfg.recovery_sessions:
                blocked = False
                latched = False
                streak = 0
                reasons.append("RECOVERY_CLEAR_INDEPENDENT_PERSISTENCE")
            elif independent_recovery:
                reasons.append("RECOVERY_STREAK_ADVANCE")
            else:
                reasons.append("RECOVERY_STREAK_RESET")

    # Strong V-rebound is an explicit recovery escape and must not clear then
    # immediately re-enter divergence on the same close.
    if not latched and not v_rebound:
        divergence = bool(
            native == 1.0
            and entry_available
            and float(wc_drawdown) <= cfg.wc_drawdown_trigger
            and float(recent_r20) <= cfg.recent_r20_trigger
            and float(spy_r20) >= cfg.spy_r20_floor
        )
        if divergence:
            blocked = True
            latched = True
            streak = 0
            reasons.append("LD_ENTER_DIVERGENCE")
        elif native == 1.0 and not entry_available:
            reasons.append("LD_ENTRY_EVIDENCE_UNAVAILABLE")

    recovery_ceiling = cfg.recovery_ceiling if blocked else 1.0
    divergence_ceiling = cfg.divergence_ceiling if latched else 1.0
    final = min(native, recovery_ceiling, divergence_ceiling)
    if final > native:
        raise AssertionError("LD-RC must never increase native exposure")

    next_state = LDRCState(
        version=STATE_VERSION,
        full_risk_blocked=blocked,
        divergence_latched=latched,
        recovery_streak=streak,
        last_session=session,
    )
    _validate_state(next_state, cfg)

    return next_state, LDRCDecision(
        session=session,
        native_allocation=native,
        recovery_ceiling=recovery_ceiling,
        divergence_ceiling=divergence_ceiling,
        final_allocation=final,
        full_risk_blocked=blocked,
        divergence_latched=latched,
        recovery_streak=streak,
        reason="|".join(reasons) if reasons else "NORMAL",
        entry_evidence_available=entry_available,
        recovery_evidence_available=recovery_available,
        v_rebound=v_rebound,
    )


__all__ = [
    "STRATEGY_ID",
    "STRATEGY_VERSION",
    "STATE_VERSION",
    "RESEARCH_ARCHITECTURE_COMMIT",
    "SIMPLIFICATION_COMMIT",
    "INCOMPLETE_MINISPEC_COMMIT",
    "LDRCConfig",
    "LDRCState",
    "LDRCDecision",
    "state_to_dict",
    "state_from_dict",
    "ldrc_step",
]
