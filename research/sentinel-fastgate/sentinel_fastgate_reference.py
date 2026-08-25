"""Canonical reference implementation of Sentinel Fastgate.

Sentinel Fastgate changes exactly two boundaries around the authoritative
Simplified Concordance LD-RC strategy:

1. FAST may enter the existing native severe controller only after causal
   confirmation or a second consecutive warning.
2. The first unconfirmed warning applies a 55% ceiling after the unchanged
   LD-RC decision. Native Sentinel and LD-RC never observe that provisional
   ceiling, so clearing it cannot create or prolong a recovery episode.

This file owns the exact Fastgate decision logic. The causal feature builder is
an upstream, point-in-time data product: it must provide histories/features
ending before the decision session. Ordinary/slow stress, confirmed severe
holding/recovery, the Sentinel 1.1 ramp, recent-leadership witness, divergence
latch, and LD-RC remain pinned authoritative dependencies.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from typing import Mapping

STRATEGY_NAME = "Sentinel Fastgate"
STRATEGY_ID = "sentinel-fastgate"
STRATEGY_VERSION = 1
STATE_VERSION = 1
BASE_MAIN_COMMIT = "722aa14ae0e452437b80425528ba30fcf133b029"
AUTHORITATIVE_STRATEGY_COMMIT = "22ebcf48addadbc7ec4531df415041d1b8674f48"
AUTHORITATIVE_DEPENDENCY_GIT_BLOBS: Mapping[str, str] = {
    "sentinel/controller/concordance.py": "f1b49d3b6e942633eea126d834995a11cc896c3e",
    "sentinel/controller/concordance_parent.py": "bd2cea533479cabe502081c5d8c69a9535f315e0",
    "sentinel/controller/frozen_rule.py": "2af87eb7502f55642270da972a27cde8d526d8e9",
    "sentinel/controller/ldrc.py": "619d9faece5dcec7a87631b5b67c6df671701548",
    "sentinel/controller/machine.py": "64395d42355a34ee4a8df1a89263b523a54efd31",
    "sentinel/controller/recent_leadership.py": "12bc736bbe34ca9f665cecc8086d8267c538119a",
}


@dataclass(frozen=True)
class Config:
    fast_shadow_drawdown: float = -0.10
    fast_damaged_breadth: float = 0.85
    fast_green_breadth: float = 0.20
    fast_shadow_r5: float = -0.05
    fast_shadow_r10: float = -0.08
    fast_damage_delta5: float = 0.30
    fast_spy_vol_ratio: float = 0.04
    fast_spy_r20: float = -0.01
    fast_shadow_r10_confirmation: float = -0.10
    residual_thresholds: tuple[float, ...] = (0.145, 0.150, 0.155)
    residual_votes_required: int = 2
    symbolic_core_floor: float = 0.75
    provisional_ceiling: float = 0.55
    persistence_sessions: int = 2


@dataclass(frozen=True)
class FastSnapshot:
    """Causal close-time inputs; history_end_session must be earlier than session."""

    session: str
    history_end_session: str
    shadow_drawdown: float | None
    green_breadth: float | None
    shadow_r5: float | None
    shadow_r10: float | None
    damaged_5_sessions_ago: float | None
    spy_vol5_over_vol20_minus_1: float | None
    spy_r20: float | None
    minimum_damaged: float
    maximum_damaged: float
    residual_breadths: tuple[tuple[float, float], ...]
    codistress_breadth: float
    holdings: int
    residual_coverage: int
    codistress_coverage: int


@dataclass(frozen=True)
class FastEvidence:
    session: str
    status: str
    warning: bool
    causal_confirmed: bool
    residual_votes: int
    codistress_confirmed: bool
    symbolic_floor_confirmed: bool
    reason: str


@dataclass(frozen=True)
class State:
    version: int = STATE_VERSION
    warning_streak: int = 0
    last_session: str | None = None


@dataclass(frozen=True)
class Decision:
    session: str
    warning_streak: int
    parent_fast_signal: bool
    provisional_ceiling: float | None
    reason: str
    evidence_reason: str


@dataclass(frozen=True)
class CompositionResult:
    allocation: float
    provisional_applied: bool
    reason: str


class FastgateEvidenceUnavailable(RuntimeError):
    pass


def _finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _session(value: object, name: str) -> date:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty YYYY-MM-DD string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD") from exc


def _validate_config(cfg: Config) -> None:
    if not isinstance(cfg, Config):
        raise ValueError("cfg must be Config")
    if cfg.persistence_sessions < 2:
        raise ValueError("persistence_sessions must be at least two")
    if not cfg.residual_thresholds:
        raise ValueError("residual_thresholds cannot be empty")
    if not 1 <= cfg.residual_votes_required <= len(cfg.residual_thresholds):
        raise ValueError("invalid residual vote requirement")
    for name in ("fast_damaged_breadth", "fast_green_breadth", "symbolic_core_floor", "provisional_ceiling"):
        value = getattr(cfg, name)
        if not _finite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be finite in [0,1]")


def _validate_state(state: State) -> None:
    if not isinstance(state, State) or state.version != STATE_VERSION:
        raise ValueError("unsupported Sentinel Fastgate state")
    if isinstance(state.warning_streak, bool) or not isinstance(state.warning_streak, int) or state.warning_streak < 0:
        raise ValueError("warning_streak must be a non-negative integer")
    if state.last_session is not None:
        _session(state.last_session, "last_session")


def _damage_pass(damaged: float, prior: float, cfg: Config) -> bool:
    return damaged >= cfg.fast_damaged_breadth and damaged - prior >= cfg.fast_damage_delta5


def evaluate_fast_snapshot(snapshot: FastSnapshot, cfg: Config = Config()) -> FastEvidence:
    """Classify FAST geometry and causal peer confirmation deterministically."""

    _validate_config(cfg)
    if not isinstance(snapshot, FastSnapshot):
        raise ValueError("snapshot must be FastSnapshot")
    decision_session = _session(snapshot.session, "session")
    if _session(snapshot.history_end_session, "history_end_session") >= decision_session:
        raise ValueError("causal histories must end before the decision session")
    if not (
        _finite(snapshot.minimum_damaged)
        and _finite(snapshot.maximum_damaged)
        and 0.0 <= snapshot.minimum_damaged <= snapshot.maximum_damaged <= 1.0
    ):
        raise ValueError("invalid exact symbolic damage bounds")
    if len(snapshot.residual_breadths) != len(cfg.residual_thresholds):
        raise ValueError("residual vote count does not match configuration")
    for expected, observed in zip(cfg.residual_thresholds, snapshot.residual_breadths):
        threshold, breadth = observed
        if abs(threshold - expected) > 1e-15 or not _finite(breadth) or not 0.0 <= breadth <= 1.0:
            raise ValueError("invalid residual breadth vote")
    if not _finite(snapshot.codistress_breadth) or not 0.0 <= snapshot.codistress_breadth <= 1.0:
        raise ValueError("invalid co-distress breadth")
    for value in (snapshot.holdings, snapshot.residual_coverage, snapshot.codistress_coverage):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("coverage counts must be non-negative integers")
    if snapshot.holdings <= 0 or snapshot.residual_coverage > snapshot.holdings or snapshot.codistress_coverage > snapshot.holdings:
        raise ValueError("invalid peer coverage")

    required = (
        snapshot.shadow_drawdown,
        snapshot.green_breadth,
        snapshot.damaged_5_sessions_ago,
        snapshot.spy_vol5_over_vol20_minus_1,
    )
    if (
        not all(_finite(value) for value in required)
        or not (_finite(snapshot.shadow_r5) or _finite(snapshot.shadow_r10))
        or not (_finite(snapshot.spy_r20) or _finite(snapshot.shadow_r10))
    ):
        return FastEvidence(snapshot.session, "unavailable", False, False, 0, False, False, "FAST_EVIDENCE_UNAVAILABLE")

    short_loss = bool(
        (_finite(snapshot.shadow_r5) and snapshot.shadow_r5 <= cfg.fast_shadow_r5)
        or (_finite(snapshot.shadow_r10) and snapshot.shadow_r10 <= cfg.fast_shadow_r10)
    )
    market_confirmation = bool(
        (_finite(snapshot.spy_r20) and snapshot.spy_r20 <= cfg.fast_spy_r20)
        or (_finite(snapshot.shadow_r10) and snapshot.shadow_r10 <= cfg.fast_shadow_r10_confirmation)
    )
    non_peer = bool(
        snapshot.shadow_drawdown <= cfg.fast_shadow_drawdown
        and snapshot.green_breadth <= cfg.fast_green_breadth
        and short_loss
        and snapshot.spy_vol5_over_vol20_minus_1 >= cfg.fast_spy_vol_ratio
        and market_confirmation
    )
    if not non_peer:
        return FastEvidence(snapshot.session, "impossible", False, False, 0, False, False, "FAST_NON_PEER_CONDITIONS_NOT_MET")

    prior = float(snapshot.damaged_5_sessions_ago)
    minimum_passes = _damage_pass(snapshot.minimum_damaged, prior, cfg)
    maximum_passes = _damage_pass(snapshot.maximum_damaged, prior, cfg)
    status = "inevitable" if minimum_passes else "impossible" if not maximum_passes else "controllable"
    residual_votes = sum(_damage_pass(breadth, prior, cfg) for _, breadth in snapshot.residual_breadths)
    codistress_confirmed = _damage_pass(snapshot.codistress_breadth, prior, cfg)
    symbolic_floor_confirmed = snapshot.minimum_damaged <= cfg.symbolic_core_floor
    causal_confirmed = bool(
        status == "inevitable"
        or (
            status == "controllable"
            and residual_votes >= cfg.residual_votes_required
            and (codistress_confirmed or symbolic_floor_confirmed)
        )
    )
    warning = status != "impossible"
    reason = (
        "FAST_PEER_GEOMETRY_INEVITABLE"
        if status == "inevitable"
        else "FAST_PEER_GEOMETRY_IMPOSSIBLE"
        if status == "impossible"
        else "FAST_DYNAMIC_CONTAGION_CONFIRMED"
        if causal_confirmed
        else "FAST_DYNAMIC_CONTAGION_UNCONFIRMED"
    )
    return FastEvidence(
        snapshot.session,
        status,
        warning,
        causal_confirmed,
        residual_votes,
        codistress_confirmed,
        symbolic_floor_confirmed,
        reason,
    )


def state_to_dict(state: State) -> dict[str, object]:
    _validate_state(state)
    return asdict(state)


def state_from_dict(payload: Mapping[str, object]) -> State:
    if not isinstance(payload, Mapping) or set(payload) != {"version", "warning_streak", "last_session"}:
        raise ValueError("Sentinel Fastgate state payload schema mismatch")
    state = State(payload["version"], payload["warning_streak"], payload["last_session"])  # type: ignore[arg-type]
    _validate_state(state)
    return state


def step(*, evidence: FastEvidence, state: State, cfg: Config = Config()) -> tuple[State, Decision]:
    """Advance Fastgate state without touching authoritative Sentinel or LD-RC."""

    _validate_config(cfg)
    _validate_state(state)
    if not isinstance(evidence, FastEvidence):
        raise ValueError("evidence must be FastEvidence")
    current = _session(evidence.session, "evidence session")
    if state.last_session is not None and current <= _session(state.last_session, "last_session"):
        raise ValueError("sessions must advance strictly")
    if evidence.status == "unavailable":
        raise FastgateEvidenceUnavailable("preserve state and withhold the close-time decision")
    if evidence.causal_confirmed and not evidence.warning:
        raise ValueError("causal confirmation requires a warning")

    streak = state.warning_streak + 1 if evidence.warning else 0
    confirmed = evidence.causal_confirmed or (evidence.warning and streak >= cfg.persistence_sessions)
    if confirmed:
        ceiling = None
        reason = "FASTGATE_CONFIRMED_CAUSAL" if evidence.causal_confirmed else "FASTGATE_CONFIRMED_PERSISTENCE"
    elif evidence.warning:
        ceiling = float(cfg.provisional_ceiling)
        reason = "FASTGATE_PROVISIONAL_FIRST_WARNING"
    else:
        ceiling = None
        reason = "FASTGATE_PROVISIONAL_CLEAR_IMMEDIATE" if state.warning_streak else "FASTGATE_NO_WARNING"

    next_state = State(STATE_VERSION, streak, evidence.session)
    return next_state, Decision(evidence.session, streak, bool(confirmed), ceiling, reason, evidence.reason)


def compose_after_authoritative_ldrc(
    *,
    authoritative_desired_allocation: float,
    authoritative_native_allocation: float,
    authoritative_fast_active: bool,
    authoritative_slow_active: bool,
    decision: Decision,
) -> CompositionResult:
    """Apply only the first-warning ceiling after unchanged authoritative LD-RC."""

    for name, value in (
        ("desired", authoritative_desired_allocation),
        ("native", authoritative_native_allocation),
    ):
        if not _finite(value) or not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"authoritative {name} allocation must be finite in [0,1]")
    if authoritative_desired_allocation > authoritative_native_allocation + 1e-15:
        raise ValueError("LD-RC desired allocation cannot exceed native allocation")
    if not isinstance(authoritative_fast_active, bool) or not isinstance(authoritative_slow_active, bool):
        raise ValueError("authoritative active-state flags must be boolean")

    eligible = bool(
        decision.provisional_ceiling is not None
        and not decision.parent_fast_signal
        and not authoritative_fast_active
        and not authoritative_slow_active
        and authoritative_native_allocation > 1e-15
    )
    if not eligible:
        return CompositionResult(float(authoritative_desired_allocation), False, "AUTHORITATIVE_PATH_UNCHANGED")
    final = min(float(authoritative_desired_allocation), float(decision.provisional_ceiling))
    return CompositionResult(final, final < authoritative_desired_allocation - 1e-15, "FASTGATE_EXTERNAL_55_CEILING")


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()  # noqa: S324


def verify_authoritative_dependencies(repo_root: str | Path) -> Mapping[str, str]:
    root = Path(repo_root)
    observed: dict[str, str] = {}
    failures: list[str] = []
    for relative, expected in AUTHORITATIVE_DEPENDENCY_GIT_BLOBS.items():
        path = root / relative
        if not path.is_file():
            failures.append(f"{relative}: missing")
            continue
        actual = _git_blob_sha(path.read_bytes())
        observed[relative] = actual
        if actual != expected:
            failures.append(f"{relative}: expected {expected}, got {actual}")
    if failures:
        raise RuntimeError("Sentinel Fastgate dependency mismatch: " + "; ".join(failures))
    return observed


def strategy_identity(cfg: Config = Config()) -> Mapping[str, object]:
    _validate_config(cfg)
    payload: dict[str, object] = {
        "schema": "sentinel.fastgate/1",
        "strategy_name": STRATEGY_NAME,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "state_version": STATE_VERSION,
        "base_main_commit": BASE_MAIN_COMMIT,
        "authoritative_strategy_commit": AUTHORITATIVE_STRATEGY_COMMIT,
        "authoritative_dependency_git_blobs": dict(sorted(AUTHORITATIVE_DEPENDENCY_GIT_BLOBS.items())),
        "config": asdict(cfg),
        "composition": [
            "causal FAST snapshot -> Fastgate confirmation -> authoritative native Sentinel",
            "authoritative native Sentinel -> authoritative LD-RC",
            "unconfirmed first warning -> external 55% ceiling after LD-RC",
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    payload["strategy_digest_sha256"] = hashlib.sha256(encoded).hexdigest()
    return payload


class SentinelFastgate:
    def __init__(self, *, state: State = State(), cfg: Config = Config()) -> None:
        _validate_config(cfg)
        _validate_state(state)
        self.state = state
        self.cfg = cfg

    def decide(self, evidence: FastEvidence) -> Decision:
        self.state, decision = step(evidence=evidence, state=self.state, cfg=self.cfg)
        return decision


__all__ = [
    "AUTHORITATIVE_DEPENDENCY_GIT_BLOBS",
    "AUTHORITATIVE_STRATEGY_COMMIT",
    "BASE_MAIN_COMMIT",
    "CompositionResult",
    "Config",
    "Decision",
    "FastEvidence",
    "FastSnapshot",
    "FastgateEvidenceUnavailable",
    "STATE_VERSION",
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "STRATEGY_VERSION",
    "SentinelFastgate",
    "State",
    "compose_after_authoritative_ldrc",
    "evaluate_fast_snapshot",
    "state_from_dict",
    "state_to_dict",
    "step",
    "strategy_identity",
    "verify_authoritative_dependencies",
]
