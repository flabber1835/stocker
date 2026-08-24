"""Research-only alpha-recovery reference for Simplified Concordance LD-RC.

Pinned baseline: flabber1835/stocker main
22ebcf48addadbc7ec4531df415041d1b8674f48.

The module is deliberately isolated from production.  It implements two
falsifiable changes: (1) a causal dynamic peer-contagion gate for symbolically
controllable FAST decisions, and (2) a 55% provisional warning state that does
not create an LD-RC recovery episode.  All close-t decisions apply at the next
executable open.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
import json
import math
from typing import Iterable, Mapping, Sequence

BASE_MAIN_COMMIT = "22ebcf48addadbc7ec4531df415041d1b8674f48"
EXPLORATORY_PEER_LINEAGE_COMMIT = "d98b7f9d39537abffa731f26f348628a290285f8"
REFERENCE_ID = "sentinel-concordance-alpha-recovery-reference"
REFERENCE_VERSION = 1
STATE_VERSION = 1


class BranchStatus(str, Enum):
    UNAVAILABLE = "unavailable"
    IMPOSSIBLE = "impossible"
    CONTROLLABLE = "controllable"
    INEVITABLE = "inevitable"


@dataclass(frozen=True)
class Config:
    # Current hardened 30pp FAST geometry.
    fast_dd: float = -0.10
    fast_damaged: float = 0.85
    fast_green: float = 0.20
    fast_r5: float = -0.05
    fast_r10: float = -0.08
    fast_damage_delta5: float = 0.30
    fast_vol_accel: float = 0.04
    fast_spy_r20: float = -0.01
    fast_shadow_r10_confirm: float = -0.10

    # Dynamic peer approximation, based only on histories ending at t-1.
    peer_lookback: int = 252
    peer_min_obs: int = 120
    residual_thresholds: tuple[float, ...] = (0.145, 0.150, 0.155)
    residual_votes_required: int = 2
    codistress_neighbors: int = 3
    codistress_min_union: int = 5
    symbolic_core_floor: float = 0.75

    # Two-stage actuator and confirmed recovery.
    provisional: float = 0.55
    warning_confirm_sessions: int = 2
    severe: float = 0.0
    severe_min_sessions: int = 10
    severe_recovery_sessions: int = 3
    healthy_r20: float = 0.0
    healthy_damaged: float = 0.60
    healthy_green: float = 0.20
    ramp_steps: tuple[float, ...] = (0.55, 0.65, 1.0)
    ramp_confirm_sessions: tuple[int, ...] = (10, 10)
    fragile_delta_r40_5: float = 0.0

    # Simplified LD-RC witness/divergence semantics.
    witness_sessions: int = 7
    spy_v_rebound: float = 0.11
    divergence_ceiling: float = 0.55
    wc_dd_trigger: float = -0.10
    witness_r20_trigger: float = -0.08
    spy_r20_floor: float = 0.0
    one_way_cost_bps: float = 10.0


@dataclass(frozen=True)
class HoldingHistory:
    security_id: str
    returns: tuple[float | None, ...]
    distress: tuple[bool | None, ...]
    red: bool
    green: bool
    core_amber: bool


@dataclass(frozen=True)
class PeerSnapshot:
    minimum_damaged: float
    maximum_damaged: float
    residual_breadths: tuple[tuple[float, float], ...]
    codistress_breadth: float
    holdings: int
    residual_coverage: int
    codistress_coverage: int


@dataclass(frozen=True)
class FastContext:
    shadow_dd: float | None
    green: float | None
    r5: float | None
    r10: float | None
    damaged_5_sessions_ago: float | None
    spy_vol_ratio: float | None
    spy_r20: float | None


@dataclass(frozen=True)
class FastDecision:
    status: BranchStatus
    warning: bool
    confirmed: bool
    residual_votes: int
    residual_vote_count: int
    codistress_confirmed: bool
    symbolic_floor_confirmed: bool
    reason: str
    evidence: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    session: str
    fast: FastDecision
    slow_severe: bool
    shadow_r20: float | None
    shadow_r40: float | None
    damaged: float | None
    green: float | None
    witness_r20: float | None
    witness_r40: float | None
    spy_r20: float | None
    wc_dd: float | None


@dataclass(frozen=True)
class State:
    version: int = STATE_VERSION
    provisional_active: bool = False
    warning_streak: int = 0
    fast_severe: bool = False
    fast_age: int = 0
    fast_healthy_streak: int = 0
    prior_slow_severe: bool = False
    recovery_episode: bool = False
    ramp_active: bool = False
    ramp_index: int | None = None
    ramp_streak: int = 0
    divergence_latched: bool = False
    witness_streak: int = 0
    previous_allocation: float = 1.0
    r40_history: tuple[float | None, ...] = ()
    last_session: str | None = None


@dataclass(frozen=True)
class Decision:
    session: str
    allocation: float
    provisional_active: bool
    fast_severe: bool
    slow_severe: bool
    recovery_episode: bool
    ramp_active: bool
    ramp_index: int | None
    divergence_latched: bool
    witness_streak: int
    reason: str
    fast_reason: str


@dataclass(frozen=True)
class ExecutionInterval:
    wealth_overnight: float
    wealth_intraday: float
    defense_overnight: float
    defense_intraday: float


@dataclass(frozen=True)
class ReplayInput:
    observation: Observation
    interval_from_previous_close: ExecutionInterval | None = None


@dataclass(frozen=True)
class ReplayRow:
    session: str
    nav: float
    effective_allocation: float
    pending_allocation: float
    transition_factor: float
    transition_executed: bool
    reason: str
    fast_reason: str
    state: Mapping[str, object]


@dataclass(frozen=True)
class ReplayMetrics:
    start: str
    end: str
    sessions: int
    cagr: float
    sharpe: float
    max_drawdown: float
    ending_multiple: float
    transitions: int
    provisional_decisions: int
    zero_decisions: int
    partial_decisions: int
    full_decisions: int


@dataclass(frozen=True)
class ReplayResult:
    metrics: ReplayMetrics
    rows: tuple[ReplayRow, ...]
    final_state: State
    final_effective_allocation: float
    final_pending_allocation: float


# ---------- numeric and validation helpers ----------

def _finite(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _validate_config(cfg: Config) -> None:
    if not isinstance(cfg, Config):
        raise ValueError("cfg must be Config")
    for name in ("peer_lookback", "peer_min_obs", "residual_votes_required",
                 "codistress_neighbors", "codistress_min_union",
                 "warning_confirm_sessions", "severe_min_sessions",
                 "severe_recovery_sessions", "witness_sessions"):
        value = getattr(cfg, name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if cfg.peer_min_obs > cfg.peer_lookback:
        raise ValueError("peer_min_obs cannot exceed peer_lookback")
    if (not isinstance(cfg.residual_thresholds, tuple)
            or not cfg.residual_thresholds
            or any(not _finite(v) or not -1 <= float(v) <= 1
                   for v in cfg.residual_thresholds)):
        raise ValueError("residual_thresholds must be a finite tuple in [-1,1]")
    if cfg.residual_votes_required > len(cfg.residual_thresholds):
        raise ValueError("residual vote requirement exceeds vote count")
    if (not isinstance(cfg.ramp_steps, tuple) or len(cfg.ramp_steps) < 2
            or any(not _finite(v) or not 0 <= float(v) <= 1
                   for v in cfg.ramp_steps)
            or any(a >= b for a, b in zip(cfg.ramp_steps, cfg.ramp_steps[1:]))
            or abs(cfg.ramp_steps[-1] - 1.0) > 1e-12):
        raise ValueError("invalid recovery ramp steps")
    if (not isinstance(cfg.ramp_confirm_sessions, tuple)
            or len(cfg.ramp_confirm_sessions) != len(cfg.ramp_steps)-1
            or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0
                   for v in cfg.ramp_confirm_sessions)):
        raise ValueError("invalid recovery ramp confirmations")
    unit_interval = ("provisional", "severe", "fast_damaged", "fast_green",
                     "healthy_damaged", "healthy_green",
                     "divergence_ceiling", "symbolic_core_floor")
    for name in unit_interval:
        value = getattr(cfg, name)
        if not _finite(value) or not 0 <= float(value) <= 1:
            raise ValueError(f"{name} must be finite in [0,1]")
    finite_fields = ("fast_dd", "fast_r5", "fast_r10",
                     "fast_damage_delta5", "fast_vol_accel",
                     "fast_spy_r20", "fast_shadow_r10_confirm",
                     "healthy_r20", "fragile_delta_r40_5",
                     "spy_v_rebound", "wc_dd_trigger",
                     "witness_r20_trigger", "spy_r20_floor",
                     "one_way_cost_bps")
    for name in finite_fields:
        if not _finite(getattr(cfg, name)):
            raise ValueError(f"{name} must be finite")
    if not 0 <= cfg.one_way_cost_bps < 10_000:
        raise ValueError("one_way_cost_bps must be in [0,10000)")


def _validate_fast(decision: FastDecision) -> None:
    if not isinstance(decision, FastDecision):
        raise ValueError("fast must be FastDecision")
    if not isinstance(decision.status, BranchStatus):
        raise ValueError("fast status must be BranchStatus")
    for name in ("warning", "confirmed", "codistress_confirmed",
                 "symbolic_floor_confirmed"):
        if not isinstance(getattr(decision, name), bool):
            raise ValueError(f"fast {name} must be boolean")
    for name in ("residual_votes", "residual_vote_count"):
        value = getattr(decision, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"fast {name} must be a non-negative integer")
    if decision.residual_votes > decision.residual_vote_count:
        raise ValueError("fast residual votes exceed vote count")
    if decision.confirmed and not decision.warning:
        raise ValueError("confirmed FAST evidence must also be a warning")
    if decision.status in (BranchStatus.UNAVAILABLE, BranchStatus.IMPOSSIBLE):
        if decision.warning or decision.confirmed:
            raise ValueError("unavailable/impossible FAST evidence cannot warn")
    if decision.status is BranchStatus.INEVITABLE:
        if not decision.warning or not decision.confirmed:
            raise ValueError("inevitable FAST evidence must be confirmed")
    if decision.status is BranchStatus.CONTROLLABLE and not decision.warning:
        raise ValueError("controllable FAST evidence must be a warning")
    if not isinstance(decision.reason, str) or not decision.reason:
        raise ValueError("fast reason must be non-empty")


def _validate_peer_snapshot(peers: PeerSnapshot) -> None:
    if not isinstance(peers, PeerSnapshot):
        raise ValueError("peers must be PeerSnapshot")
    if not (_finite(peers.minimum_damaged) and _finite(peers.maximum_damaged)
            and 0 <= peers.minimum_damaged <= peers.maximum_damaged <= 1):
        raise ValueError("invalid peer damage bounds")
    if not _finite(peers.codistress_breadth) or not 0 <= peers.codistress_breadth <= 1:
        raise ValueError("invalid co-distress breadth")
    if not isinstance(peers.residual_breadths, tuple):
        raise ValueError("residual breadths must be a tuple")
    for threshold, breadth in peers.residual_breadths:
        if not (_finite(threshold) and -1 <= threshold <= 1
                and _finite(breadth) and 0 <= breadth <= 1):
            raise ValueError("invalid residual breadth vote")
    for name in ("holdings", "residual_coverage", "codistress_coverage"):
        value = getattr(peers, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if peers.residual_coverage > peers.holdings or peers.codistress_coverage > peers.holdings:
        raise ValueError("peer coverage exceeds holdings")


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("empty mean")
    return sum(values) / len(values)


def _corr(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    lm, rm = _mean(left), _mean(right)
    cov = sum((x-lm)*(y-rm) for x, y in zip(left, right))
    lv = sum((x-lm)**2 for x in left)
    rv = sum((y-rm)**2 for y in right)
    if lv <= 0 or rv <= 0:
        return None
    value = cov / math.sqrt(lv * rv)
    return max(-1.0, min(1.0, value)) if math.isfinite(value) else None


def _residuals(asset: Sequence[float | None], market: Sequence[float | None],
               cfg: Config) -> dict[int, float]:
    if len(asset) != len(market):
        raise ValueError("asset/market histories are misaligned")
    start = max(0, len(asset) - cfg.peer_lookback)
    positions = [i for i in range(start, len(asset))
                 if _finite(asset[i]) and _finite(market[i])]
    if len(positions) < cfg.peer_min_obs:
        return {}
    av = [float(asset[i]) for i in positions]
    mv = [float(market[i]) for i in positions]
    mm = _mean(mv)
    var = sum((v-mm)**2 for v in mv)
    if var <= 0:
        return {}
    am = _mean(av)
    beta = sum((a-am)*(m-mm) for a, m in zip(av, mv)) / var
    return {i: float(asset[i]) - beta*float(market[i]) for i in positions}


def _residual_corr(left: HoldingHistory, right: HoldingHistory,
                   market: Sequence[float | None], cfg: Config) -> float | None:
    lr, rr = _residuals(left.returns, market, cfg), _residuals(right.returns, market, cfg)
    common = sorted(set(lr).intersection(rr))
    if len(common) < cfg.peer_min_obs:
        return None
    return _corr([lr[i] for i in common], [rr[i] for i in common])


def _jaccard(left: Sequence[bool | None], right: Sequence[bool | None],
             cfg: Config) -> float | None:
    if len(left) != len(right):
        raise ValueError("distress histories are misaligned")
    start = max(0, len(left) - cfg.peer_lookback)
    pairs = [(left[i], right[i]) for i in range(start, len(left))
             if isinstance(left[i], bool) and isinstance(right[i], bool)]
    if len(pairs) < cfg.peer_min_obs:
        return None
    union = sum(bool(a or b) for a, b in pairs)
    if union < cfg.codistress_min_union:
        return None
    return sum(bool(a and b) for a, b in pairs) / union


# ---------- causal fast-contagion signal ----------

def build_peer_snapshot(*, holdings: Iterable[HoldingHistory],
                        market_returns: Sequence[float | None],
                        exact_minimum: float | None = None,
                        exact_maximum: float | None = None,
                        cfg: Config = Config()) -> PeerSnapshot:
    """Build prior-only residual and co-distress peer breadth.

    Exact symbolic minimum/maximum breadth is the promotion-grade input.  The
    fallback bounds (core amber; every non-green name) are conservative research
    scaffolding and are not an exact replacement for the retained DP geometry.
    """
    _validate_config(cfg)
    rows = tuple(holdings)
    if (not rows or any(not isinstance(r.security_id, str) or not r.security_id
                        for r in rows)
            or len({r.security_id for r in rows}) != len(rows)):
        raise ValueError("holdings must be non-empty and uniquely identified")
    if any(not all(isinstance(v, bool) for v in (r.red, r.green, r.core_amber))
           for r in rows):
        raise ValueError("holding state flags must be boolean")
    if any(len(r.returns) != len(market_returns) or
           len(r.distress) != len(market_returns) for r in rows):
        raise ValueError("all histories must align")
    minimum = _mean([float(r.core_amber) for r in rows])
    maximum = _mean([float(r.core_amber or not r.green) for r in rows])
    if exact_minimum is not None:
        if not _finite(exact_minimum):
            raise ValueError("exact_minimum must be finite")
        minimum = float(exact_minimum)
    if exact_maximum is not None:
        if not _finite(exact_maximum):
            raise ValueError("exact_maximum must be finite")
        maximum = float(exact_maximum)
    if not (_finite(minimum) and _finite(maximum) and 0 <= minimum <= maximum <= 1):
        raise ValueError("invalid symbolic damage bounds")

    red = [i for i, row in enumerate(rows) if row.red]
    pair_corr: dict[tuple[int, int], float | None] = {}
    covered: set[int] = set()
    for i, row in enumerate(rows):
        for j in red:
            if i == j:
                continue
            key = (min(i, j), max(i, j))
            pair_corr.setdefault(key, _residual_corr(row, rows[j], market_returns, cfg))
            if pair_corr[key] is not None:
                covered.add(i)

    residual_breadths = []
    for threshold in cfg.residual_thresholds:
        amber = []
        for i, row in enumerate(rows):
            correlations = [pair_corr[(min(i, j), max(i, j))] for j in red if i != j]
            correlations = [v for v in correlations if v is not None]
            promoted = (not row.green and not row.core_amber and correlations
                        and max(correlations) >= threshold)
            amber.append(bool(row.core_amber or promoted))
        residual_breadths.append((threshold, _mean([float(v) for v in amber])))

    codistress_covered: set[int] = set()
    codistress_amber = []
    for i, row in enumerate(rows):
        promoted = False
        if not row.green and not row.core_amber:
            scores = []
            for j, peer in enumerate(rows):
                if i != j and (score := _jaccard(row.distress, peer.distress, cfg)) is not None:
                    scores.append((score, peer.security_id, j))
            if scores:
                codistress_covered.add(i)
                chosen = [j for _, _, j in sorted(scores, key=lambda x: (-x[0], x[1]))
                          [:cfg.codistress_neighbors]]
                promoted = _mean([float(rows[j].red) for j in (i, *chosen)]) >= 0.5
        codistress_amber.append(bool(row.core_amber or promoted))

    snapshot = PeerSnapshot(
        minimum_damaged=minimum,
        maximum_damaged=maximum,
        residual_breadths=tuple(residual_breadths),
        codistress_breadth=_mean([float(v) for v in codistress_amber]),
        holdings=len(rows),
        residual_coverage=len(covered),
        codistress_coverage=len(codistress_covered),
    )
    _validate_peer_snapshot(snapshot)
    return snapshot


def _damage_pass(damaged: float, prior: float, cfg: Config) -> bool:
    return damaged >= cfg.fast_damaged and damaged-prior >= cfg.fast_damage_delta5


def evaluate_fast(*, context: FastContext, peers: PeerSnapshot,
                  cfg: Config = Config()) -> FastDecision:
    """Return high-recall warning plus higher-precision confirmation."""
    _validate_config(cfg)
    _validate_peer_snapshot(peers)
    required = (context.shadow_dd, context.green,
                context.damaged_5_sessions_ago, context.spy_vol_ratio)
    short_available = _finite(context.r5) or _finite(context.r10)
    confirmation_available = _finite(context.spy_r20) or _finite(context.r10)
    if not all(_finite(v) for v in required) or not short_available or not confirmation_available:
        return FastDecision(BranchStatus.UNAVAILABLE, False, False, 0,
                            len(peers.residual_breadths), False, False,
                            "FAST_EVIDENCE_UNAVAILABLE")
    short = ((_finite(context.r5) and context.r5 <= cfg.fast_r5) or
             (_finite(context.r10) and context.r10 <= cfg.fast_r10))
    confirmation = ((_finite(context.spy_r20) and context.spy_r20 <= cfg.fast_spy_r20) or
                    (_finite(context.r10) and context.r10 <= cfg.fast_shadow_r10_confirm))
    non_peer = (context.shadow_dd <= cfg.fast_dd and context.green <= cfg.fast_green
                and short and context.spy_vol_ratio >= cfg.fast_vol_accel and confirmation)
    if not non_peer:
        return FastDecision(BranchStatus.IMPOSSIBLE, False, False, 0,
                            len(peers.residual_breadths), False, False,
                            "FAST_NON_PEER_CONDITIONS_NOT_MET")

    prior = float(context.damaged_5_sessions_ago)
    min_pass = _damage_pass(peers.minimum_damaged, prior, cfg)
    max_pass = _damage_pass(peers.maximum_damaged, prior, cfg)
    status = (BranchStatus.INEVITABLE if min_pass else
              BranchStatus.IMPOSSIBLE if not max_pass else BranchStatus.CONTROLLABLE)
    residual_votes = sum(_damage_pass(value, prior, cfg)
                         for _, value in peers.residual_breadths)
    codistress = _damage_pass(peers.codistress_breadth, prior, cfg)
    symbolic_floor = peers.minimum_damaged <= cfg.symbolic_core_floor
    dynamic = (residual_votes >= cfg.residual_votes_required and
               (codistress or symbolic_floor))
    warning = status is not BranchStatus.IMPOSSIBLE
    confirmed = status is BranchStatus.INEVITABLE or (
        status is BranchStatus.CONTROLLABLE and dynamic)
    reason = ("FAST_PEER_GEOMETRY_INEVITABLE" if status is BranchStatus.INEVITABLE
              else "FAST_PEER_GEOMETRY_IMPOSSIBLE" if status is BranchStatus.IMPOSSIBLE
              else "FAST_DYNAMIC_CONTAGION_CONFIRMED" if confirmed
              else "FAST_DYNAMIC_CONTAGION_UNCONFIRMED")
    return FastDecision(
        status, warning, confirmed, residual_votes, len(peers.residual_breadths),
        codistress, symbolic_floor, reason,
        {"minimum_damaged": peers.minimum_damaged,
         "maximum_damaged": peers.maximum_damaged,
         "residual_breadths": list(peers.residual_breadths),
         "codistress_breadth": peers.codistress_breadth,
         "residual_coverage": [peers.residual_coverage, peers.holdings],
         "codistress_coverage": [peers.codistress_coverage, peers.holdings]},
    )


# ---------- state machine ----------

def _state_payload(state: State) -> dict:
    payload = asdict(state)
    payload["r40_history"] = list(state.r40_history)
    return payload


def _validate_state(state: State) -> None:
    if not isinstance(state, State):
        raise ValueError("state must be State")
    if isinstance(state.version, bool) or not isinstance(state.version, int) \
            or state.version != STATE_VERSION:
        raise ValueError("unsupported state version")
    for name in ("provisional_active", "fast_severe", "prior_slow_severe",
                 "recovery_episode", "ramp_active", "divergence_latched"):
        if not isinstance(getattr(state, name), bool):
            raise ValueError(f"{name} must be boolean")
    for name in ("warning_streak", "fast_age", "fast_healthy_streak",
                 "ramp_streak", "witness_streak"):
        value = getattr(state, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if state.ramp_index is not None and (isinstance(state.ramp_index, bool)
                                         or not isinstance(state.ramp_index, int)
                                         or state.ramp_index < 0):
        raise ValueError("ramp_index must be null or non-negative integer")
    if state.ramp_active != (state.ramp_index is not None):
        raise ValueError("ramp_active/ramp_index mismatch")
    if not _finite(state.previous_allocation) or not 0 <= state.previous_allocation <= 1:
        raise ValueError("invalid previous allocation")
    if len(state.r40_history) > 6 or any(v is not None and not _finite(v)
                                            for v in state.r40_history):
        raise ValueError("invalid r40 history")
    if state.last_session is not None and (not isinstance(state.last_session, str)
                                           or not state.last_session):
        raise ValueError("invalid last session")
    json.dumps(_state_payload(state), sort_keys=True, allow_nan=False)


def state_to_dict(state: State) -> dict:
    _validate_state(state)
    return _state_payload(state)


def state_from_dict(payload: Mapping[str, object]) -> State:
    required = set(_state_payload(State()))
    if not isinstance(payload, Mapping) or set(payload) != required:
        raise ValueError("state payload schema mismatch")
    raw = dict(payload)
    raw["r40_history"] = tuple(raw["r40_history"])
    state = State(**raw)  # type: ignore[arg-type]
    _validate_state(state)
    return state


def _healthy(ob: Observation, cfg: Config) -> bool:
    return bool(_finite(ob.shadow_r20) and _finite(ob.damaged) and _finite(ob.green)
                and ob.shadow_r20 > cfg.healthy_r20
                and ob.damaged <= cfg.healthy_damaged
                and ob.green >= cfg.healthy_green)


def _witness_healthy(ob: Observation) -> bool:
    return bool(_finite(ob.witness_r20) and _finite(ob.witness_r40)
                and ob.witness_r20 > 0 and ob.witness_r40 > 0)


def _prior_delta_r40(history: Sequence[float | None]) -> float | None:
    if len(history) < 6 or not _finite(history[-1]) or not _finite(history[-6]):
        return None
    return float(history[-1])-float(history[-6])


def step(*, observation: Observation, state: State,
         cfg: Config = Config()) -> tuple[State, Decision]:
    """Advance one close-time decision; the output applies next open."""
    _validate_config(cfg)
    _validate_state(state)
    ob = observation
    if not isinstance(ob.session, str) or not ob.session:
        raise ValueError("session must be non-empty")
    try:
        current_session = date.fromisoformat(ob.session)
        prior_session = (date.fromisoformat(state.last_session)
                         if state.last_session is not None else None)
    except ValueError as exc:
        raise ValueError("session must be YYYY-MM-DD") from exc
    if prior_session is not None and current_session <= prior_session:
        raise ValueError("sessions must advance strictly")
    if not isinstance(ob.slow_severe, bool):
        raise ValueError("slow_severe must be boolean")
    _validate_fast(ob.fast)
    if ob.fast.status is BranchStatus.UNAVAILABLE:
        raise ValueError("FAST evidence unavailable: withhold the decision")
    for name in ("shadow_r20", "shadow_r40", "damaged", "green",
                 "witness_r20", "witness_r40", "spy_r20", "wc_dd"):
        value = getattr(ob, name)
        if value is not None and not _finite(value):
            raise ValueError(f"{name} must be finite or null")

    healthy = _healthy(ob, cfg)
    witness_streak = state.witness_streak+1 if _witness_healthy(ob) else 0
    v_rebound = bool(_finite(ob.spy_r20) and ob.spy_r20 > cfg.spy_v_rebound)
    reasons: list[str] = []

    warning_streak = state.warning_streak+1 if ob.fast.warning else 0
    independent = ob.fast.warning and ob.fast.confirmed
    persistent = ob.fast.warning and warning_streak >= cfg.warning_confirm_sessions
    fast = state.fast_severe
    fast_age = state.fast_age
    fast_health = state.fast_healthy_streak
    if not fast and (independent or persistent):
        fast, fast_age, fast_health = True, 1, 0
        reasons.append("FAST_CONFIRMED_INDEPENDENT" if independent
                       else "FAST_CONFIRMED_PERSISTENCE")
    elif fast:
        fast_age += 1
        fast_health = fast_health+1 if healthy and not ob.fast.warning else 0
        if fast_age >= cfg.severe_min_sessions and fast_health >= cfg.severe_recovery_sessions:
            fast, fast_health = False, 0
            reasons.append("FAST_CONFIRMED_RECOVERY")

    slow = ob.slow_severe
    severe = fast or slow
    prior_severe = state.fast_severe or state.prior_slow_severe
    ramp, ramp_index, ramp_streak = state.ramp_active, state.ramp_index, state.ramp_streak
    episode, divergence, provisional = state.recovery_episode, state.divergence_latched, False

    cleared_divergence = divergence and (witness_streak >= cfg.witness_sessions or v_rebound)
    if cleared_divergence:
        divergence = False
        reasons.append("DIVERGENCE_CLEAR_PERSISTENCE" if witness_streak >= cfg.witness_sessions
                       else "DIVERGENCE_CLEAR_SPY_V_REBOUND")

    if severe:
        allocation, episode = cfg.severe, True
        ramp, ramp_index, ramp_streak = False, None, 0
        reasons.append("SLOW_SEVERE" if slow else "FAST_SEVERE")
    else:
        recovering = prior_severe and not severe
        if recovering:
            delta = _prior_delta_r40(state.r40_history)
            fragile = delta is None or delta <= cfg.fragile_delta_r40_5
            if v_rebound:
                allocation, episode, ramp, ramp_index, ramp_streak = 1.0, False, False, None, 0
                reasons.append("RECOVERY_SPY_V_REBOUND_FULL")
            elif not fragile and witness_streak >= cfg.witness_sessions:
                allocation, episode, ramp, ramp_index, ramp_streak = 1.0, False, False, None, 0
                reasons.append("RECOVERY_NONFRAGILE_CONCORDANT_FULL")
            else:
                allocation, episode, ramp, ramp_index = cfg.ramp_steps[0], True, True, 0
                ramp_streak = 1 if healthy and not ob.fast.warning else 0
                reasons.append("RECOVERY_FRAGILE_RAMP" if fragile
                               else "RECOVERY_CONCORDANCE_HOLD_55")
        elif ramp:
            if ramp_index is None or ramp_index >= len(cfg.ramp_steps)-1:
                raise ValueError("invalid active ramp")
            allocation = cfg.ramp_steps[ramp_index]
            need = cfg.ramp_confirm_sessions[ramp_index]
            ready = ramp_streak >= need
            if not ready:
                ramp_streak = ramp_streak+1 if healthy and not ob.fast.warning else 0
                ready = ramp_streak >= need
            if ready:
                proposed_index = ramp_index+1
                proposed = cfg.ramp_steps[proposed_index]
                if proposed >= 1-1e-12:
                    if witness_streak >= cfg.witness_sessions or v_rebound:
                        allocation, episode, ramp, ramp_index, ramp_streak = 1.0, False, False, None, 0
                        reasons.append("RAMP_COMPLETE_CONCORDANT")
                    else:
                        # Native full-risk readiness stays latched while only
                        # the independent witness remains outstanding.
                        ramp_streak = need
                        reasons.append("RAMP_FULL_HELD_FOR_CONCORDANCE")
                else:
                    allocation, ramp_index, ramp_streak = proposed, proposed_index, 0
                    reasons.append("RAMP_PROMOTED")
            else:
                reasons.append("RAMP_HOLDING")
        else:
            allocation, episode = 1.0, False

        unconfirmed = ob.fast.warning and not fast and not independent and not persistent
        if unconfirmed:
            provisional = True
            allocation = min(allocation, cfg.provisional)
            reasons.append("FAST_PROVISIONAL_55")
        elif state.provisional_active and not ob.fast.warning:
            reasons.append("FAST_PROVISIONAL_CLEAR_IMMEDIATE" if not episode
                           else "FAST_PROVISIONAL_CLEAR_WITHIN_CONFIRMED_RECOVERY")

        entry_available = (_finite(ob.wc_dd) and _finite(ob.witness_r20)
                           and _finite(ob.spy_r20))
        if (not divergence and not cleared_divergence and not provisional and not episode
                and allocation >= 1-1e-12 and entry_available
                and ob.wc_dd <= cfg.wc_dd_trigger
                and ob.witness_r20 <= cfg.witness_r20_trigger
                and ob.spy_r20 >= cfg.spy_r20_floor):
            divergence = True
            reasons.append("LD_ENTER_DIVERGENCE")
        elif not divergence and allocation >= 1-1e-12 and not entry_available:
            reasons.append("LD_ENTRY_EVIDENCE_UNAVAILABLE")
        if divergence:
            allocation = min(allocation, cfg.divergence_ceiling)

    history = (*state.r40_history,
               float(ob.shadow_r40) if _finite(ob.shadow_r40) else None)[-6:]
    next_state = State(
        provisional_active=provisional, warning_streak=warning_streak,
        fast_severe=fast, fast_age=fast_age if fast else 0,
        fast_healthy_streak=fast_health if fast else 0,
        prior_slow_severe=slow, recovery_episode=episode,
        ramp_active=ramp, ramp_index=ramp_index, ramp_streak=ramp_streak,
        divergence_latched=divergence, witness_streak=witness_streak,
        previous_allocation=float(allocation), r40_history=tuple(history),
        last_session=ob.session)
    _validate_state(next_state)
    return next_state, Decision(
        ob.session, float(allocation), provisional, fast, slow, episode,
        ramp, ramp_index, divergence, witness_streak,
        "|".join(reasons) if reasons else "RISK_ON", ob.fast.reason)


# ---------- execution and generic replay ----------

def transition_factor(*, old_allocation: float, new_allocation: float,
                      interval: ExecutionInterval,
                      cfg: Config = Config()) -> float:
    """Old allocation owns overnight; new allocation owns intraday."""
    _validate_config(cfg)
    values = (old_allocation, new_allocation, interval.wealth_overnight,
              interval.wealth_intraday, interval.defense_overnight,
              interval.defense_intraday)
    if not all(_finite(v) for v in values) or not (0 <= old_allocation <= 1
                                                   and 0 <= new_allocation <= 1):
        raise ValueError("invalid execution inputs")
    overnight = (1 + old_allocation*interval.wealth_overnight
                 + (1-old_allocation)*interval.defense_overnight)
    cost = 1-cfg.one_way_cost_bps/10_000*abs(new_allocation-old_allocation)
    intraday = (1 + new_allocation*interval.wealth_intraday
                + (1-new_allocation)*interval.defense_intraday)
    factor = overnight*cost*intraday
    if not _finite(factor) or factor <= 0:
        raise ValueError("non-positive transition factor")
    return factor


def _metrics(rows: tuple[ReplayRow, ...]) -> ReplayMetrics:
    if len(rows) < 2:
        raise ValueError("at least two replay rows required")
    try:
        start, end = date.fromisoformat(rows[0].session), date.fromisoformat(rows[-1].session)
    except ValueError as exc:
        raise ValueError("sessions must be YYYY-MM-DD") from exc
    years = (end-start).days/365.2425
    if years <= 0:
        raise ValueError("replay window must span positive time")
    nav = [row.nav for row in rows]
    returns = [nav[i]/nav[i-1]-1 for i in range(1, len(nav))]
    ending = nav[-1]/nav[0]
    cagr = ending**(1/years)-1
    mean = _mean(returns)
    variance = (sum((r-mean)**2 for r in returns)/(len(returns)-1)
                if len(returns) > 1 else 0.0)
    sharpe = mean/math.sqrt(variance)*math.sqrt(252) if variance > 0 else 0.0
    peak, mdd = nav[0], 0.0
    for value in nav:
        peak, mdd = max(peak, value), min(mdd, value/peak-1)
    allocations = [row.pending_allocation for row in rows]
    return ReplayMetrics(
        rows[0].session, rows[-1].session, len(rows), cagr, sharpe, mdd, ending,
        sum(row.transition_executed for row in rows),
        sum("FAST_PROVISIONAL_55" in row.reason for row in rows),
        sum(a <= 1e-12 for a in allocations),
        sum(1e-12 < a < 1-1e-12 for a in allocations),
        sum(a >= 1-1e-12 for a in allocations))


def run_replay(inputs: Iterable[ReplayInput], *, cfg: Config = Config(),
               initial_state: State = State(), initial_nav: float = 1.0,
               initial_effective_allocation: float | None = None) -> ReplayResult:
    """Run already-causal observations with next-open application."""
    source = tuple(inputs)
    if len(source) < 2 or not _finite(initial_nav) or initial_nav <= 0:
        raise ValueError("invalid replay inputs")
    state = initial_state
    _validate_state(state)
    effective = (state.previous_allocation if initial_effective_allocation is None
                 else float(initial_effective_allocation))
    if not _finite(effective) or not 0 <= effective <= 1:
        raise ValueError("invalid initial effective allocation")
    pending, nav, out = state.previous_allocation, float(initial_nav), []
    for i, item in enumerate(source):
        if i == 0 and item.interval_from_previous_close is not None:
            raise ValueError("first row cannot have prior interval")
        if i > 0 and item.interval_from_previous_close is None:
            raise ValueError("later rows require prior interval")
        factor, executed = 1.0, False
        if i > 0:
            executed = abs(pending-effective) > 1e-15
            factor = transition_factor(old_allocation=effective,
                                       new_allocation=pending,
                                       interval=item.interval_from_previous_close,
                                       cfg=cfg)  # type: ignore[arg-type]
            nav *= factor
            effective = pending
        state, decision = step(observation=item.observation, state=state, cfg=cfg)
        pending = decision.allocation
        out.append(ReplayRow(item.observation.session, nav, effective, pending,
                             factor, executed, decision.reason,
                             decision.fast_reason, state_to_dict(state)))
    rows = tuple(out)
    return ReplayResult(_metrics(rows), rows, state, effective, pending)


def metric_delta(control: ReplayResult, candidate: ReplayResult) -> dict:
    if (control.metrics.start, control.metrics.end, control.metrics.sessions) != (
            candidate.metrics.start, candidate.metrics.end, candidate.metrics.sessions):
        raise ValueError("replay windows are not aligned")
    return {name: getattr(candidate.metrics, name)-getattr(control.metrics, name)
            for name in ("cagr", "sharpe", "max_drawdown", "ending_multiple",
                         "transitions")}


__all__ = [
    "BASE_MAIN_COMMIT", "BranchStatus", "Config", "Decision",
    "EXPLORATORY_PEER_LINEAGE_COMMIT", "ExecutionInterval", "FastContext",
    "FastDecision", "HoldingHistory", "Observation", "PeerSnapshot",
    "REFERENCE_ID", "REFERENCE_VERSION", "ReplayInput", "ReplayMetrics",
    "ReplayResult", "ReplayRow", "STATE_VERSION", "State",
    "build_peer_snapshot", "evaluate_fast", "metric_delta", "run_replay",
    "state_from_dict", "state_to_dict", "step", "transition_factor",
]
