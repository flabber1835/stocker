"""Recovered independent recent-leadership witness for Sentinel Concordance.

This module pins the witness semantics that reproduce the retained historical
fingerprints. It is a zero-capital sensor and must never create broker orders.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Optional, Sequence, Tuple

MIN_LEADERS = 25
LEADERSHIP_FRACTION = 0.10


@dataclass(frozen=True)
class LeadershipCandidate:
    security_id: str
    momentum_6_to_1: float
    recent_21_return: float


@dataclass(frozen=True)
class LeadershipSelection:
    established: Tuple[str, ...]
    recent: Tuple[str, ...]

    @property
    def overlap_count(self) -> int:
        return len(set(self.established).intersection(self.recent))

    @property
    def overlap_fraction(self) -> float:
        if not self.established:
            return float("nan")
        return self.overlap_count / len(self.established)


def leadership_population_size(eligible_count: int) -> int:
    if not isinstance(eligible_count, int) or isinstance(eligible_count, bool) or eligible_count < 0:
        raise ValueError("eligible_count must be a non-negative integer")
    if eligible_count == 0:
        return 0
    if eligible_count < MIN_LEADERS:
        raise ValueError("eligible population is smaller than the 25-name leadership floor")
    return max(MIN_LEADERS, int(math.ceil(eligible_count * LEADERSHIP_FRACTION)))


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def select_leadership(candidates: Sequence[LeadershipCandidate]) -> LeadershipSelection:
    """Select established and recent leadership deterministically."""
    n = leadership_population_size(len(candidates))
    if n == 0:
        return LeadershipSelection((), ())
    ids = [c.security_id for c in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate security_id in leadership candidates")
    if any(not isinstance(c.security_id, str) or not c.security_id for c in candidates):
        raise ValueError("security_id must be a non-empty string")
    if any(not _finite_number(c.momentum_6_to_1) or not _finite_number(c.recent_21_return) for c in candidates):
        raise ValueError("leadership scores must be finite")

    established = tuple(
        c.security_id
        for c in sorted(candidates, key=lambda c: (-float(c.momentum_6_to_1), c.security_id))[:n]
    )
    recent = tuple(
        c.security_id
        for c in sorted(candidates, key=lambda c: (-float(c.recent_21_return), c.security_id))[:n]
    )
    return LeadershipSelection(established=established, recent=recent)


def equal_weight_next_close_return(
    selected_security_ids: Sequence[str],
    previous_close: Mapping[str, float],
    current_close: Mapping[str, float],
) -> float:
    ids = tuple(selected_security_ids)
    if not ids:
        return 0.0
    if len(ids) != len(set(ids)):
        raise ValueError("selected_security_ids contains duplicates")

    total = 0.0
    for security_id in ids:
        p0 = previous_close.get(security_id)
        p1 = current_close.get(security_id)
        if _finite_number(p0) and _finite_number(p1) and float(p0) > 0.0 and float(p1) > 0.0:
            total += float(p1) / float(p0) - 1.0
    return total / len(ids)


def advance_shadow_nav(nav: float, one_session_return: float) -> float:
    if not _finite_number(nav) or float(nav) <= 0.0:
        raise ValueError("nav must be finite and positive")
    if not _finite_number(one_session_return) or float(one_session_return) <= -1.0:
        raise ValueError("one_session_return must be finite and greater than -1")
    return float(nav) * (1.0 + float(one_session_return))


def session_return(nav_history: Sequence[float], sessions: int) -> Optional[float]:
    if (isinstance(sessions, bool)
            or not isinstance(sessions, int) or sessions <= 0):
        raise ValueError("sessions must be a positive integer")
    if len(nav_history) <= sessions:
        return None
    now = nav_history[-1]
    then = nav_history[-1 - sessions]
    if not _finite_number(now) or not _finite_number(then) or float(then) <= 0.0:
        return None
    return float(now) / float(then) - 1.0


__all__ = [
    "MIN_LEADERS",
    "LEADERSHIP_FRACTION",
    "LeadershipCandidate",
    "LeadershipSelection",
    "leadership_population_size",
    "select_leadership",
    "equal_weight_next_close_return",
    "advance_shadow_nav",
    "session_return",
]
