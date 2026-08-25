"""Research-only FAST confirmation/provisional-ownership overlay.

This module intentionally does not implement Sentinel severe recovery or LD-RC.
It produces only two outputs:

1. whether the existing authoritative native controller may see a confirmed
   FAST entry signal; and
2. an optional external 55% ceiling for the first unconfirmed warning.

The provisional ceiling is composed *after* the unchanged native controller and
unchanged LD-RC decision. It therefore cannot open, clear, or mutate an LD-RC
recovery episode.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import json
import math
from typing import Mapping

STATE_VERSION = 1
REFERENCE_ID = "sentinel-fast-confirmation-provisional-owner-v1"


@dataclass(frozen=True)
class Config:
    provisional_ceiling: float = 0.55
    persistence_sessions: int = 2


@dataclass(frozen=True)
class State:
    version: int = STATE_VERSION
    warning_streak: int = 0
    last_session: str | None = None


@dataclass(frozen=True)
class Evidence:
    session: str
    warning: bool
    causal_confirmed: bool


@dataclass(frozen=True)
class Decision:
    session: str
    warning_streak: int
    parent_fast_signal: bool
    provisional_ceiling: float | None
    reason: str


def _finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _validate_config(cfg: Config) -> None:
    if not isinstance(cfg, Config):
        raise ValueError("cfg must be Config")
    if not _finite(cfg.provisional_ceiling) or not 0.0 <= cfg.provisional_ceiling <= 1.0:
        raise ValueError("provisional_ceiling must be finite in [0,1]")
    if (
        isinstance(cfg.persistence_sessions, bool)
        or not isinstance(cfg.persistence_sessions, int)
        or cfg.persistence_sessions < 2
    ):
        raise ValueError("persistence_sessions must be an integer >= 2")


def _validate_state(state: State) -> None:
    if not isinstance(state, State) or state.version != STATE_VERSION:
        raise ValueError("unsupported FAST confirmation state")
    if (
        isinstance(state.warning_streak, bool)
        or not isinstance(state.warning_streak, int)
        or state.warning_streak < 0
    ):
        raise ValueError("warning_streak must be a non-negative integer")
    if state.last_session is not None:
        if not isinstance(state.last_session, str) or not state.last_session:
            raise ValueError("last_session must be null or non-empty")
        date.fromisoformat(state.last_session)


def state_to_dict(state: State) -> dict:
    _validate_state(state)
    payload = asdict(state)
    json.dumps(payload, sort_keys=True, allow_nan=False)
    return payload


def state_from_dict(payload: Mapping[str, object]) -> State:
    if not isinstance(payload, Mapping) or set(payload) != {"version", "warning_streak", "last_session"}:
        raise ValueError("FAST confirmation state payload schema mismatch")
    state = State(
        version=payload["version"],  # type: ignore[arg-type]
        warning_streak=payload["warning_streak"],  # type: ignore[arg-type]
        last_session=payload["last_session"],  # type: ignore[arg-type]
    )
    _validate_state(state)
    return state


def step(*, evidence: Evidence, state: State, cfg: Config = Config()) -> tuple[State, Decision]:
    """Advance one close-time warning decision.

    `parent_fast_signal=True` is the only output that may enter the existing
    native severe controller. The optional ceiling is applied outside LD-RC.
    """
    _validate_config(cfg)
    _validate_state(state)
    if not isinstance(evidence, Evidence):
        raise ValueError("evidence must be Evidence")
    if not isinstance(evidence.session, str) or not evidence.session:
        raise ValueError("session must be non-empty")
    current = date.fromisoformat(evidence.session)
    if state.last_session is not None and current <= date.fromisoformat(state.last_session):
        raise ValueError("sessions must advance strictly")
    if not isinstance(evidence.warning, bool) or not isinstance(evidence.causal_confirmed, bool):
        raise ValueError("warning and causal_confirmed must be boolean")
    if evidence.causal_confirmed and not evidence.warning:
        raise ValueError("causal confirmation requires a warning")

    streak = state.warning_streak + 1 if evidence.warning else 0
    confirmed = evidence.causal_confirmed or streak >= cfg.persistence_sessions
    if confirmed:
        ceiling = None
        reason = "FAST_CONFIRMED_CAUSAL" if evidence.causal_confirmed else "FAST_CONFIRMED_PERSISTENCE"
    elif evidence.warning:
        ceiling = float(cfg.provisional_ceiling)
        reason = "FAST_PROVISIONAL_FIRST_WARNING"
    else:
        ceiling = None
        reason = "FAST_WARNING_CLEAR" if state.warning_streak else "NO_FAST_WARNING"

    next_state = State(warning_streak=streak, last_session=evidence.session)
    _validate_state(next_state)
    return next_state, Decision(
        session=evidence.session,
        warning_streak=streak,
        parent_fast_signal=confirmed,
        provisional_ceiling=ceiling,
        reason=reason,
    )


def compose_after_ldrc(*, authoritative_allocation: float, provisional_ceiling: float | None) -> float:
    """Apply the provisional ceiling without mutating native or LD-RC state."""
    if not _finite(authoritative_allocation) or not 0.0 <= authoritative_allocation <= 1.0:
        raise ValueError("authoritative_allocation must be finite in [0,1]")
    if provisional_ceiling is None:
        return float(authoritative_allocation)
    if not _finite(provisional_ceiling) or not 0.0 <= provisional_ceiling <= 1.0:
        raise ValueError("provisional_ceiling must be null or finite in [0,1]")
    return min(float(authoritative_allocation), float(provisional_ceiling))


__all__ = [
    "Config", "Decision", "Evidence", "REFERENCE_ID", "STATE_VERSION", "State",
    "compose_after_ldrc", "state_from_dict", "state_to_dict", "step",
]
