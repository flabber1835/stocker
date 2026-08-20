"""Production integration state for the zero-capital recent-leadership witness.

The pure ranking/return math lives in :mod:`recent_leadership`.  This module
owns only the small durable restart image and the one-session causal advance.
No broker or execution vocabulary exists here.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Sequence

from sentinel.controller.ldrc import STRATEGY_ID as LDRC_STRATEGY_ID
from sentinel.controller.recent_leadership import (
    LeadershipCandidate,
    advance_shadow_nav,
    equal_weight_next_close_return,
    select_leadership,
    session_return,
)

WITNESS_STATE_VERSION = 1
WITNESS_HISTORY_SESSIONS = 41
IDENTITY_OVERLAY_FIELD = "allocation_overlay"


def _finite(value: object) -> bool:
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


@dataclass(frozen=True)
class RecentLeadershipState:
    version: int = WITNESS_STATE_VERSION
    selected_recent: tuple[str, ...] = ()
    selected_close: tuple[tuple[str, float], ...] = ()
    nav_history: tuple[float, ...] = ()
    session_history: tuple[str, ...] = ()
    last_session: str | None = None


@dataclass(frozen=True)
class RecentLeadershipDecision:
    session: str
    eligible_count: int
    population_size: int
    overlap_count: int
    one_session_return: float
    nav: float
    recent_r20: float | None
    recent_r40: float | None
    recent_members: tuple[str, ...]
    established_members: tuple[str, ...]


def is_concordance_identity(identity: Mapping[str, object]) -> bool:
    return identity.get(IDENTITY_OVERLAY_FIELD) == LDRC_STRATEGY_ID


def state_to_dict(state: RecentLeadershipState) -> dict:
    _validate_state(state)
    return {
        "version": state.version,
        "selected_recent": list(state.selected_recent),
        "selected_close": [[security_id, close]
                           for security_id, close in state.selected_close],
        "nav_history": list(state.nav_history),
        "session_history": list(state.session_history),
        "last_session": state.last_session,
    }


def state_from_dict(payload: Mapping[str, object]) -> RecentLeadershipState:
    if not isinstance(payload, Mapping):
        raise ValueError("recent-leadership state payload must be a mapping")
    required = {
        "version", "selected_recent", "selected_close", "nav_history",
        "session_history", "last_session",
    }
    if set(payload) != required:
        raise ValueError(
            "recent-leadership state payload has missing or unknown fields")
    try:
        selected_recent = tuple(payload["selected_recent"])  # type: ignore[arg-type]
        selected_close = tuple(
            (row[0], row[1]) for row in payload["selected_close"]  # type: ignore[index,arg-type]
        )
        nav_history = tuple(payload["nav_history"])  # type: ignore[arg-type]
        session_history = tuple(payload["session_history"])  # type: ignore[arg-type]
    except (TypeError, IndexError) as exc:
        raise ValueError("malformed recent-leadership state payload") from exc
    state = RecentLeadershipState(
        version=payload["version"],  # type: ignore[arg-type]
        selected_recent=selected_recent,  # type: ignore[arg-type]
        selected_close=selected_close,  # type: ignore[arg-type]
        nav_history=nav_history,  # type: ignore[arg-type]
        session_history=session_history,  # type: ignore[arg-type]
        last_session=payload["last_session"],  # type: ignore[arg-type]
    )
    _validate_state(state)
    return state


def _validate_state(state: RecentLeadershipState) -> None:
    if state.version != WITNESS_STATE_VERSION:
        raise ValueError(
            f"unsupported recent-leadership state version {state.version!r}")
    if state.last_session is not None and (
            not isinstance(state.last_session, str) or not state.last_session):
        raise ValueError("recent-leadership last_session must be null or string")
    if len(state.nav_history) != len(state.session_history):
        raise ValueError("recent-leadership NAV/session histories are misaligned")
    if len(state.nav_history) > WITNESS_HISTORY_SESSIONS:
        raise ValueError("recent-leadership history exceeds bounded window")
    if state.session_history and any(
            left >= right
            for left, right in zip(state.session_history, state.session_history[1:])):
        raise ValueError("recent-leadership sessions are not strictly increasing")
    if state.last_session is not None and (
            not state.session_history or state.session_history[-1] != state.last_session):
        raise ValueError("recent-leadership last_session disagrees with history")
    if any(not isinstance(value, str) or not value
           for value in state.selected_recent):
        raise ValueError("recent-leadership selected ids must be non-empty strings")
    if len(state.selected_recent) != len(set(state.selected_recent)):
        raise ValueError("recent-leadership selected ids contain duplicates")
    close_ids = [security_id for security_id, _ in state.selected_close]
    if tuple(close_ids) != state.selected_recent:
        raise ValueError("recent-leadership selected closes do not match membership")
    if any(not _finite(close) or float(close) <= 0
           for _, close in state.selected_close):
        raise ValueError("recent-leadership selected closes must be positive finite")
    if any(not _finite(nav) or float(nav) <= 0 for nav in state.nav_history):
        raise ValueError("recent-leadership NAV history must be positive finite")


def _candidate(value) -> LeadershipCandidate | None:
    """Convert Wealth Core's ephemeral DurableScore-like row without importing it.

    Duck-typing here is intentional: Sentinel consumes an audit surface, not a
    Wealth Core execution type. Eligibility is represented by the presence of
    the two finite raw return signals; the production caller separately proves
    the count equals Wealth Core's canonical eligible_universe_count.
    """
    security_id = getattr(value, "security_id", None)
    momentum = getattr(value, "momentum", None)
    recent = getattr(value, "recent", None)
    if (not isinstance(security_id, str) or not security_id
            or not _finite(momentum) or not _finite(recent)):
        return None
    return LeadershipCandidate(
        security_id=security_id,
        momentum_6_to_1=float(momentum),
        recent_21_return=float(recent),
    )


def advance_recent_leadership(
    *, session: str, candidate_rows: Iterable[object],
    eligible_universe_count: int, signal_closes: Mapping[str, float],
    state: RecentLeadershipState,
) -> tuple[RecentLeadershipState, RecentLeadershipDecision]:
    """Advance close ``t`` using membership selected at close ``t-1``.

    Current membership is selected only *after* the t-1 -> t return has been
    earned. This is the causal ordering recovered in PR #199.
    """
    _validate_state(state)
    if not isinstance(session, str) or not session:
        raise ValueError("recent-leadership session must be non-empty")
    if state.last_session is not None and session <= state.last_session:
        raise ValueError("recent-leadership sessions must advance strictly once")
    if (isinstance(eligible_universe_count, bool)
            or not isinstance(eligible_universe_count, int)
            or eligible_universe_count < 0):
        raise ValueError("eligible_universe_count must be non-negative integer")

    candidates = tuple(
        candidate for row in candidate_rows
        if (candidate := _candidate(row)) is not None)
    if len(candidates) != eligible_universe_count:
        raise ValueError(
            "Wealth Core eligible population disagrees with leadership audit "
            f"rows: count={eligible_universe_count}, rows={len(candidates)}")

    previous_close = dict(state.selected_close)
    current_close = {
        str(security_id): float(close)
        for security_id, close in signal_closes.items()
        if _finite(close) and float(close) > 0
    }
    one_return = equal_weight_next_close_return(
        state.selected_recent, previous_close, current_close)
    prior_nav = state.nav_history[-1] if state.nav_history else 1.0
    nav = advance_shadow_nav(prior_nav, one_return)
    nav_history = (*state.nav_history, nav)[-WITNESS_HISTORY_SESSIONS:]
    sessions = (*state.session_history, session)[-WITNESS_HISTORY_SESSIONS:]

    selection = select_leadership(candidates)
    # The recent membership is the investable witness for t -> t+1. A current
    # signal close is required to earn that next return. A theoretically
    # selected name without one is invalid causal evidence rather than a zero
    # return: zero applies only when the *next* session print is missing.
    missing_close = [security_id for security_id in selection.recent
                     if security_id not in current_close]
    if missing_close:
        raise ValueError(
            "current leadership membership lacks canonical signal close: "
            + ", ".join(missing_close))
    selected_close = tuple(
        (security_id, current_close[security_id])
        for security_id in selection.recent)

    next_state = RecentLeadershipState(
        selected_recent=selection.recent,
        selected_close=selected_close,
        nav_history=tuple(nav_history),
        session_history=tuple(sessions),
        last_session=session,
    )
    _validate_state(next_state)
    decision = RecentLeadershipDecision(
        session=session, eligible_count=eligible_universe_count,
        population_size=len(selection.recent),
        overlap_count=selection.overlap_count,
        one_session_return=one_return, nav=nav,
        recent_r20=session_return(nav_history, 20),
        recent_r40=session_return(nav_history, 40),
        recent_members=selection.recent,
        established_members=selection.established,
    )
    return next_state, decision


__all__ = [
    "IDENTITY_OVERLAY_FIELD", "RecentLeadershipDecision",
    "RecentLeadershipState", "WITNESS_HISTORY_SESSIONS",
    "WITNESS_STATE_VERSION", "advance_recent_leadership",
    "is_concordance_identity", "state_from_dict", "state_to_dict",
]
