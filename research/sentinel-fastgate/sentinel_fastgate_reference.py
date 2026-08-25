"""Canonical reference implementation of Sentinel Fastgate.

Sentinel Fastgate changes exactly two boundaries around the authoritative
Simplified Concordance LD-RC strategy:

1. FAST may enter the existing native severe controller only after causal
   confirmation or a second consecutive warning.
2. The first unconfirmed warning applies a 55% ceiling after the unchanged
   LD-RC decision. Native Sentinel and LD-RC never observe that provisional
   ceiling, so clearing it cannot create or prolong a recovery episode.

This file owns every behavior introduced by Sentinel Fastgate, including the
point-in-time dynamic-peer confirmation builder. Ordinary/slow stress,
confirmed severe holding and recovery, the Sentinel 1.1 ramp, the
recent-leadership witness, the divergence latch, LD-RC, and portfolio
accounting remain pinned authoritative dependencies rather than being copied
or modified here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence

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
    # Authoritative hardened non-peer FAST predicates.
    fast_shadow_drawdown: float = -0.10
    fast_damaged_breadth: float = 0.85
    fast_green_breadth: float = 0.20
    fast_shadow_r5: float = -0.05
    fast_shadow_r10: float = -0.08
    fast_damage_delta5: float = 0.30
    fast_spy_vol_ratio: float = 0.04
    fast_spy_r20: float = -0.01
    fast_shadow_r10_confirmation: float = -0.10

    # Point-in-time dynamic-peer confirmation.
    peer_lookback: int = 252
    peer_min_observations: int = 120
    residual_thresholds: tuple[float, ...] = (0.145, 0.150, 0.155)
    residual_votes_required: int = 2
    codistress_neighbors: int = 3
    codistress_min_union: int = 5
    symbolic_core_floor: float = 0.75

    # First-warning ownership.
    provisional_ceiling: float = 0.55
    persistence_sessions: int = 2


@dataclass(frozen=True)
class MarketHistory:
    """Aligned market history available before the decision session."""

    sessions: tuple[str, ...]
    returns: tuple[float | None, ...]


@dataclass(frozen=True)
class HoldingHistory:
    """One held security's aligned prior-only history and current state."""

    security_id: str
    returns: tuple[float | None, ...]
    distress: tuple[bool | None, ...]
    red: bool
    green: bool
    core_amber: bool


@dataclass(frozen=True)
class FastContext:
    """Current non-peer FAST inputs and exact symbolic damage bounds."""

    session: str
    shadow_drawdown: float | None
    green_breadth: float | None
    shadow_r5: float | None
    shadow_r10: float | None
    damaged_5_sessions_ago: float | None
    spy_vol5_over_vol20_minus_1: float | None
    spy_r20: float | None
    minimum_damaged: float
    maximum_damaged: float


@dataclass(frozen=True)
class FastSnapshot:
    """Complete causal close-time input to Sentinel Fastgate."""

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
    """The close-time decision must be withheld without mutating state."""


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


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("cannot calculate the mean of an empty sequence")
    return sum(values) / len(values)


def _validate_config(cfg: Config) -> None:
    if not isinstance(cfg, Config):
        raise ValueError("cfg must be Config")

    positive_integers = (
        "peer_lookback",
        "peer_min_observations",
        "residual_votes_required",
        "codistress_neighbors",
        "codistress_min_union",
        "persistence_sessions",
    )
    for name in positive_integers:
        value = getattr(cfg, name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")

    if cfg.peer_min_observations > cfg.peer_lookback:
        raise ValueError("peer_min_observations cannot exceed peer_lookback")
    if cfg.persistence_sessions < 2:
        raise ValueError("persistence_sessions must be at least two")
    if not cfg.residual_thresholds:
        raise ValueError("residual_thresholds cannot be empty")
    if cfg.residual_votes_required > len(cfg.residual_thresholds):
        raise ValueError("residual vote requirement exceeds vote count")
    if any(
        not _finite(value) or not -1.0 <= float(value) <= 1.0
        for value in cfg.residual_thresholds
    ):
        raise ValueError("residual thresholds must be finite in [-1,1]")

    unit_interval = (
        "fast_damaged_breadth",
        "fast_green_breadth",
        "symbolic_core_floor",
        "provisional_ceiling",
    )
    for name in unit_interval:
        value = getattr(cfg, name)
        if not _finite(value) or not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"{name} must be finite in [0,1]")

    finite_fields = (
        "fast_shadow_drawdown",
        "fast_shadow_r5",
        "fast_shadow_r10",
        "fast_damage_delta5",
        "fast_spy_vol_ratio",
        "fast_spy_r20",
        "fast_shadow_r10_confirmation",
    )
    for name in finite_fields:
        if not _finite(getattr(cfg, name)):
            raise ValueError(f"{name} must be finite")


def _validate_market_history(history: MarketHistory, decision_session: str) -> None:
    if not isinstance(history, MarketHistory):
        raise ValueError("market_history must be MarketHistory")
    if not history.sessions or len(history.sessions) != len(history.returns):
        raise ValueError("market sessions and returns must be non-empty and aligned")

    parsed = [_session(value, "market history session") for value in history.sessions]
    if any(right <= left for left, right in zip(parsed, parsed[1:])):
        raise ValueError("market history sessions must advance strictly")
    if parsed[-1] >= _session(decision_session, "decision session"):
        raise ValueError("causal histories must end before the decision session")

    for value in history.returns:
        if value is not None and not _finite(value):
            raise ValueError("market returns must be finite or null")


def _validate_holding_history(
    rows: Sequence[HoldingHistory],
    market_history: MarketHistory,
) -> None:
    if not rows:
        raise ValueError("holdings must be non-empty")
    if len({row.security_id for row in rows}) != len(rows):
        raise ValueError("holding security IDs must be unique")

    expected = len(market_history.sessions)
    for row in rows:
        if not isinstance(row.security_id, str) or not row.security_id:
            raise ValueError("holding security_id must be non-empty")
        if len(row.returns) != expected or len(row.distress) != expected:
            raise ValueError("all holding histories must align to market history")
        if not all(isinstance(flag, bool) for flag in (row.red, row.green, row.core_amber)):
            raise ValueError("holding state flags must be boolean")
        for value in row.returns:
            if value is not None and not _finite(value):
                raise ValueError("holding returns must be finite or null")
        for value in row.distress:
            if value is not None and not isinstance(value, bool):
                raise ValueError("distress history must contain bool or null")


def _validate_exact_bounds(context: FastContext) -> None:
    if not isinstance(context, FastContext):
        raise ValueError("context must be FastContext")
    _session(context.session, "context session")
    if not (
        _finite(context.minimum_damaged)
        and _finite(context.maximum_damaged)
        and 0.0 <= float(context.minimum_damaged)
        <= float(context.maximum_damaged)
        <= 1.0
    ):
        raise ValueError("exact symbolic damage bounds must be finite in [0,1]")


def _corr(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = _mean(left)
    right_mean = _mean(right)
    covariance = sum(
        (x - left_mean) * (y - right_mean)
        for x, y in zip(left, right)
    )
    left_variance = sum((x - left_mean) ** 2 for x in left)
    right_variance = sum((y - right_mean) ** 2 for y in right)
    if left_variance <= 0.0 or right_variance <= 0.0:
        return None
    value = covariance / math.sqrt(left_variance * right_variance)
    if not math.isfinite(value):
        return None
    return max(-1.0, min(1.0, value))


def _residuals(
    asset_returns: Sequence[float | None],
    market_returns: Sequence[float | None],
    cfg: Config,
) -> dict[int, float]:
    if len(asset_returns) != len(market_returns):
        raise ValueError("asset and market histories are misaligned")

    start = max(0, len(asset_returns) - cfg.peer_lookback)
    positions = [
        index
        for index in range(start, len(asset_returns))
        if _finite(asset_returns[index]) and _finite(market_returns[index])
    ]
    if len(positions) < cfg.peer_min_observations:
        return {}

    asset = [float(asset_returns[index]) for index in positions]
    market = [float(market_returns[index]) for index in positions]
    asset_mean = _mean(asset)
    market_mean = _mean(market)
    market_variance = sum((value - market_mean) ** 2 for value in market)
    if market_variance <= 0.0:
        return {}

    beta = sum(
        (asset_value - asset_mean) * (market_value - market_mean)
        for asset_value, market_value in zip(asset, market)
    ) / market_variance
    return {
        index: float(asset_returns[index]) - beta * float(market_returns[index])
        for index in positions
    }


def _residual_correlation(
    left: HoldingHistory,
    right: HoldingHistory,
    market_returns: Sequence[float | None],
    cfg: Config,
) -> float | None:
    left_residuals = _residuals(left.returns, market_returns, cfg)
    right_residuals = _residuals(right.returns, market_returns, cfg)
    common = sorted(set(left_residuals).intersection(right_residuals))
    if len(common) < cfg.peer_min_observations:
        return None
    return _corr(
        [left_residuals[index] for index in common],
        [right_residuals[index] for index in common],
    )


def _jaccard(
    left: Sequence[bool | None],
    right: Sequence[bool | None],
    cfg: Config,
) -> float | None:
    if len(left) != len(right):
        raise ValueError("distress histories are misaligned")
    start = max(0, len(left) - cfg.peer_lookback)
    pairs = [
        (left[index], right[index])
        for index in range(start, len(left))
        if isinstance(left[index], bool) and isinstance(right[index], bool)
    ]
    if len(pairs) < cfg.peer_min_observations:
        return None
    union = sum(bool(left_value or right_value) for left_value, right_value in pairs)
    if union < cfg.codistress_min_union:
        return None
    intersection = sum(
        bool(left_value and right_value)
        for left_value, right_value in pairs
    )
    return intersection / union


def build_fast_snapshot(
    *,
    context: FastContext,
    market_history: MarketHistory,
    holdings: Iterable[HoldingHistory],
    cfg: Config = Config(),
) -> FastSnapshot:
    """Build the exact prior-only dynamic-peer feature snapshot.

    The caller must supply exact symbolic minimum and maximum damaged breadth
    from the retained authoritative geometry. Sentinel Fastgate does not
    approximate or replace that geometry.
    """

    _validate_config(cfg)
    _validate_exact_bounds(context)
    _validate_market_history(market_history, context.session)
    rows = tuple(holdings)
    _validate_holding_history(rows, market_history)

    red_indices = [index for index, row in enumerate(rows) if row.red]
    pair_correlations: dict[tuple[int, int], float | None] = {}
    residual_covered: set[int] = set()

    for left_index, left in enumerate(rows):
        for right_index in red_indices:
            if left_index == right_index:
                continue
            key = (min(left_index, right_index), max(left_index, right_index))
            if key not in pair_correlations:
                pair_correlations[key] = _residual_correlation(
                    left,
                    rows[right_index],
                    market_history.returns,
                    cfg,
                )
            if pair_correlations[key] is not None:
                residual_covered.add(left_index)

    residual_breadths: list[tuple[float, float]] = []
    for threshold in cfg.residual_thresholds:
        amber_flags: list[bool] = []
        for index, row in enumerate(rows):
            correlations = [
                pair_correlations[(min(index, red_index), max(index, red_index))]
                for red_index in red_indices
                if index != red_index
            ]
            available = [value for value in correlations if value is not None]
            promoted = bool(
                not row.green
                and not row.core_amber
                and available
                and max(available) >= threshold
            )
            amber_flags.append(bool(row.core_amber or promoted))
        residual_breadths.append(
            (float(threshold), _mean([float(flag) for flag in amber_flags]))
        )

    codistress_covered: set[int] = set()
    codistress_amber: list[bool] = []
    for index, row in enumerate(rows):
        promoted = False
        if not row.green and not row.core_amber:
            scores: list[tuple[float, str, int]] = []
            for peer_index, peer in enumerate(rows):
                if index == peer_index:
                    continue
                score = _jaccard(row.distress, peer.distress, cfg)
                if score is not None:
                    scores.append((score, peer.security_id, peer_index))
            if scores:
                codistress_covered.add(index)
                selected = [
                    peer_index
                    for _, _, peer_index in sorted(
                        scores,
                        key=lambda item: (-item[0], item[1]),
                    )[: cfg.codistress_neighbors]
                ]
                red_share = _mean(
                    [float(rows[peer_index].red) for peer_index in (index, *selected)]
                )
                promoted = red_share >= 0.5
        codistress_amber.append(bool(row.core_amber or promoted))

    return FastSnapshot(
        session=context.session,
        history_end_session=market_history.sessions[-1],
        shadow_drawdown=context.shadow_drawdown,
        green_breadth=context.green_breadth,
        shadow_r5=context.shadow_r5,
        shadow_r10=context.shadow_r10,
        damaged_5_sessions_ago=context.damaged_5_sessions_ago,
        spy_vol5_over_vol20_minus_1=context.spy_vol5_over_vol20_minus_1,
        spy_r20=context.spy_r20,
        minimum_damaged=float(context.minimum_damaged),
        maximum_damaged=float(context.maximum_damaged),
        residual_breadths=tuple(residual_breadths),
        codistress_breadth=_mean([float(flag) for flag in codistress_amber]),
        holdings=len(rows),
        residual_coverage=len(residual_covered),
        codistress_coverage=len(codistress_covered),
    )


def _damage_pass(damaged: float, prior: float, cfg: Config) -> bool:
    return (
        damaged >= cfg.fast_damaged_breadth
        and damaged - prior >= cfg.fast_damage_delta5
    )


def evaluate_fast_snapshot(
    snapshot: FastSnapshot,
    cfg: Config = Config(),
) -> FastEvidence:
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
    for expected, observed in zip(
        cfg.residual_thresholds,
        snapshot.residual_breadths,
    ):
        threshold, breadth = observed
        if (
            abs(float(threshold) - expected) > 1e-15
            or not _finite(breadth)
            or not 0.0 <= float(breadth) <= 1.0
        ):
            raise ValueError("invalid residual breadth vote")
    if (
        not _finite(snapshot.codistress_breadth)
        or not 0.0 <= snapshot.codistress_breadth <= 1.0
    ):
        raise ValueError("invalid co-distress breadth")
    for value in (
        snapshot.holdings,
        snapshot.residual_coverage,
        snapshot.codistress_coverage,
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("coverage counts must be non-negative integers")
    if (
        snapshot.holdings <= 0
        or snapshot.residual_coverage > snapshot.holdings
        or snapshot.codistress_coverage > snapshot.holdings
    ):
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
        return FastEvidence(
            snapshot.session,
            "unavailable",
            False,
            False,
            0,
            False,
            False,
            "FAST_EVIDENCE_UNAVAILABLE",
        )

    short_loss = bool(
        (
            _finite(snapshot.shadow_r5)
            and float(snapshot.shadow_r5) <= cfg.fast_shadow_r5
        )
        or (
            _finite(snapshot.shadow_r10)
            and float(snapshot.shadow_r10) <= cfg.fast_shadow_r10
        )
    )
    market_confirmation = bool(
        (
            _finite(snapshot.spy_r20)
            and float(snapshot.spy_r20) <= cfg.fast_spy_r20
        )
        or (
            _finite(snapshot.shadow_r10)
            and float(snapshot.shadow_r10)
            <= cfg.fast_shadow_r10_confirmation
        )
    )
    non_peer = bool(
        float(snapshot.shadow_drawdown) <= cfg.fast_shadow_drawdown
        and float(snapshot.green_breadth) <= cfg.fast_green_breadth
        and short_loss
        and float(snapshot.spy_vol5_over_vol20_minus_1)
        >= cfg.fast_spy_vol_ratio
        and market_confirmation
    )
    if not non_peer:
        return FastEvidence(
            snapshot.session,
            "impossible",
            False,
            False,
            0,
            False,
            False,
            "FAST_NON_PEER_CONDITIONS_NOT_MET",
        )

    prior = float(snapshot.damaged_5_sessions_ago)
    minimum_passes = _damage_pass(snapshot.minimum_damaged, prior, cfg)
    maximum_passes = _damage_pass(snapshot.maximum_damaged, prior, cfg)
    status = (
        "inevitable"
        if minimum_passes
        else "impossible"
        if not maximum_passes
        else "controllable"
    )
    residual_votes = sum(
        _damage_pass(float(breadth), prior, cfg)
        for _, breadth in snapshot.residual_breadths
    )
    codistress_confirmed = _damage_pass(
        float(snapshot.codistress_breadth),
        prior,
        cfg,
    )
    symbolic_floor_confirmed = (
        snapshot.minimum_damaged <= cfg.symbolic_core_floor
    )
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


def evaluate_fast_from_histories(
    *,
    context: FastContext,
    market_history: MarketHistory,
    holdings: Iterable[HoldingHistory],
    cfg: Config = Config(),
) -> tuple[FastSnapshot, FastEvidence]:
    """Build and evaluate one causal Sentinel Fastgate decision."""

    snapshot = build_fast_snapshot(
        context=context,
        market_history=market_history,
        holdings=holdings,
        cfg=cfg,
    )
    return snapshot, evaluate_fast_snapshot(snapshot, cfg)


def _validate_evidence(evidence: FastEvidence) -> None:
    if not isinstance(evidence, FastEvidence):
        raise ValueError("evidence must be FastEvidence")
    _session(evidence.session, "evidence session")
    if evidence.status not in {
        "unavailable",
        "impossible",
        "controllable",
        "inevitable",
    }:
        raise ValueError("unknown FAST evidence status")
    for name in (
        "warning",
        "causal_confirmed",
        "codistress_confirmed",
        "symbolic_floor_confirmed",
    ):
        if not isinstance(getattr(evidence, name), bool):
            raise ValueError(f"{name} must be boolean")
    if (
        isinstance(evidence.residual_votes, bool)
        or not isinstance(evidence.residual_votes, int)
        or evidence.residual_votes < 0
    ):
        raise ValueError("residual_votes must be a non-negative integer")
    if evidence.causal_confirmed and not evidence.warning:
        raise ValueError("causal confirmation requires a warning")
    if evidence.status in {"unavailable", "impossible"} and (
        evidence.warning or evidence.causal_confirmed
    ):
        raise ValueError("unavailable/impossible evidence cannot warn")
    if evidence.status == "inevitable" and not (
        evidence.warning and evidence.causal_confirmed
    ):
        raise ValueError("inevitable evidence must be confirmed")
    if evidence.status == "controllable" and not evidence.warning:
        raise ValueError("controllable evidence must be a warning")
    if not isinstance(evidence.reason, str) or not evidence.reason:
        raise ValueError("evidence reason must be non-empty")


def _validate_state(state: State) -> None:
    if not isinstance(state, State) or state.version != STATE_VERSION:
        raise ValueError("unsupported Sentinel Fastgate state")
    if (
        isinstance(state.warning_streak, bool)
        or not isinstance(state.warning_streak, int)
        or state.warning_streak < 0
    ):
        raise ValueError("warning_streak must be a non-negative integer")
    if state.last_session is not None:
        _session(state.last_session, "last_session")


def state_to_dict(state: State) -> dict[str, object]:
    _validate_state(state)
    payload = asdict(state)
    json.dumps(payload, sort_keys=True, allow_nan=False)
    return payload


def state_from_dict(payload: Mapping[str, object]) -> State:
    required = {"version", "warning_streak", "last_session"}
    if not isinstance(payload, Mapping) or set(payload) != required:
        raise ValueError("Sentinel Fastgate state payload schema mismatch")
    state = State(
        payload["version"],  # type: ignore[arg-type]
        payload["warning_streak"],  # type: ignore[arg-type]
        payload["last_session"],  # type: ignore[arg-type]
    )
    _validate_state(state)
    return state


def step(
    *,
    evidence: FastEvidence,
    state: State,
    cfg: Config = Config(),
) -> tuple[State, Decision]:
    """Advance Fastgate state without touching authoritative Sentinel or LD-RC."""

    _validate_config(cfg)
    _validate_state(state)
    _validate_evidence(evidence)

    current = _session(evidence.session, "evidence session")
    if (
        state.last_session is not None
        and current <= _session(state.last_session, "last_session")
    ):
        raise ValueError("sessions must advance strictly")
    if evidence.status == "unavailable":
        raise FastgateEvidenceUnavailable(
            "preserve state and withhold the close-time decision"
        )

    streak = state.warning_streak + 1 if evidence.warning else 0
    confirmed = bool(
        evidence.causal_confirmed
        or (evidence.warning and streak >= cfg.persistence_sessions)
    )
    if confirmed:
        ceiling = None
        reason = (
            "FASTGATE_CONFIRMED_CAUSAL"
            if evidence.causal_confirmed
            else "FASTGATE_CONFIRMED_PERSISTENCE"
        )
    elif evidence.warning:
        ceiling = float(cfg.provisional_ceiling)
        reason = "FASTGATE_PROVISIONAL_FIRST_WARNING"
    else:
        ceiling = None
        reason = (
            "FASTGATE_PROVISIONAL_CLEAR_IMMEDIATE"
            if state.warning_streak
            else "FASTGATE_NO_WARNING"
        )

    next_state = State(STATE_VERSION, streak, evidence.session)
    return next_state, Decision(
        evidence.session,
        streak,
        confirmed,
        ceiling,
        reason,
        evidence.reason,
    )


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
            raise ValueError(
                f"authoritative {name} allocation must be finite in [0,1]"
            )
    if (
        authoritative_desired_allocation
        > authoritative_native_allocation + 1e-15
    ):
        raise ValueError("LD-RC desired allocation cannot exceed native allocation")
    if not isinstance(authoritative_fast_active, bool) or not isinstance(
        authoritative_slow_active,
        bool,
    ):
        raise ValueError("authoritative active-state flags must be boolean")
    if not isinstance(decision, Decision):
        raise ValueError("decision must be Decision")

    eligible = bool(
        decision.provisional_ceiling is not None
        and not decision.parent_fast_signal
        and not authoritative_fast_active
        and not authoritative_slow_active
        and authoritative_native_allocation > 1e-15
    )
    if not eligible:
        return CompositionResult(
            float(authoritative_desired_allocation),
            False,
            "AUTHORITATIVE_PATH_UNCHANGED",
        )

    final = min(
        float(authoritative_desired_allocation),
        float(decision.provisional_ceiling),
    )
    return CompositionResult(
        final,
        final < authoritative_desired_allocation - 1e-15,
        "FASTGATE_EXTERNAL_55_CEILING",
    )


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(
        f"blob {len(data)}\0".encode("ascii") + data
    ).hexdigest()  # noqa: S324


def verify_authoritative_dependencies(
    repo_root: str | Path,
) -> Mapping[str, str]:
    """Fail closed unless every inherited strategy dependency is exact."""

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
            failures.append(
                f"{relative}: expected {expected}, got {actual}"
            )
    if failures:
        raise RuntimeError(
            "Sentinel Fastgate dependency mismatch: " + "; ".join(failures)
        )
    return observed


def strategy_identity(cfg: Config = Config()) -> Mapping[str, object]:
    """Return the deterministic identity of the Fastgate policy."""

    _validate_config(cfg)
    payload: dict[str, object] = {
        "schema": "sentinel.fastgate/1",
        "strategy_name": STRATEGY_NAME,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "state_version": STATE_VERSION,
        "base_main_commit": BASE_MAIN_COMMIT,
        "authoritative_strategy_commit": AUTHORITATIVE_STRATEGY_COMMIT,
        "authoritative_dependency_git_blobs": dict(
            sorted(AUTHORITATIVE_DEPENDENCY_GIT_BLOBS.items())
        ),
        "config": asdict(cfg),
        "peer_builder": {
            "history_domain": "held-security returns ending before decision session",
            "market_neutralization": "OLS beta to SPY over prior aligned observations",
            "residual_breadth": "vulnerable holdings promoted by max residual correlation to current RED holdings",
            "codistress_breadth": "three prior Jaccard peers; promote when self-plus-peers RED share >= 50%",
            "symbolic_bounds": "exact authoritative minimum/maximum damaged breadth required",
        },
        "composition": [
            "causal peer histories -> Fastgate confirmation -> authoritative native Sentinel",
            "authoritative native Sentinel -> authoritative LD-RC",
            "unconfirmed first warning -> external 55% ceiling after LD-RC",
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    payload["strategy_digest_sha256"] = hashlib.sha256(encoded).hexdigest()
    return payload


class SentinelFastgate:
    """Small stateful facade around the pure reference functions."""

    def __init__(
        self,
        *,
        state: State = State(),
        cfg: Config = Config(),
    ) -> None:
        _validate_config(cfg)
        _validate_state(state)
        self.state = state
        self.cfg = cfg

    def decide(self, evidence: FastEvidence) -> Decision:
        self.state, decision = step(
            evidence=evidence,
            state=self.state,
            cfg=self.cfg,
        )
        return decision

    def evaluate_and_decide(
        self,
        *,
        context: FastContext,
        market_history: MarketHistory,
        holdings: Iterable[HoldingHistory],
    ) -> tuple[FastSnapshot, FastEvidence, Decision]:
        snapshot, evidence = evaluate_fast_from_histories(
            context=context,
            market_history=market_history,
            holdings=holdings,
            cfg=self.cfg,
        )
        decision = self.decide(evidence)
        return snapshot, evidence, decision


__all__ = [
    "AUTHORITATIVE_DEPENDENCY_GIT_BLOBS",
    "AUTHORITATIVE_STRATEGY_COMMIT",
    "BASE_MAIN_COMMIT",
    "CompositionResult",
    "Config",
    "Decision",
    "FastContext",
    "FastEvidence",
    "FastSnapshot",
    "FastgateEvidenceUnavailable",
    "HoldingHistory",
    "MarketHistory",
    "STATE_VERSION",
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "STRATEGY_VERSION",
    "SentinelFastgate",
    "State",
    "build_fast_snapshot",
    "compose_after_authoritative_ldrc",
    "evaluate_fast_from_histories",
    "evaluate_fast_snapshot",
    "state_from_dict",
    "state_to_dict",
    "step",
    "strategy_identity",
    "verify_authoritative_dependencies",
]
