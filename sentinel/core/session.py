"""Durable session envelope and pure transition support.

This lower-level module owns the immutable published-session inputs, the
JSON-serialisable strategy state, and deterministic helper functions shared by
the canonical kernel and production adapters. It has no database, persistence,
clock, execution, or broker seam.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Mapping, Sequence

from stock_strategy_shared.wealth_core.feed import (
    Feed, FeedError, SecurityMeta, SecuritySeries, VendorBar)
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.signals import REQUIRED_CLOSES
from stock_strategy_shared.wealth_core.state import DEFAULT_SLOTS, PortfolioState
from stock_strategy_shared.wealth_core.terminal import TerminalTerms

from sentinel.breadth.classifier import Holding
from sentinel.breadth.returns import lag_return
from sentinel.controller.concordance import (
    RecentLeadershipState,
    is_concordance_identity, state_from_dict as leadership_state_from_dict,
    state_to_dict as leadership_state_to_dict)
from sentinel.controller.ldrc import (
    LDRCState, state_from_dict as ldrc_state_from_dict,
    state_to_dict as ldrc_state_to_dict)
from sentinel.controller.machine import (
    Controller, validate_controller_state)

ENVELOPE_VERSION = 5
LEGACY_ENVELOPE_VERSIONS = frozenset({2, 3, 4})
FEED_RESTART_SESSIONS = REQUIRED_CLOSES
CONCORDANCE_WITNESS_HISTORICAL = "HISTORICAL_CAUSAL_METADATA"
CONCORDANCE_WITNESS_PROSPECTIVE = "PROSPECTIVE_PAPER_OBSERVATION"
_CONCORDANCE_WITNESS_ORIGINS = frozenset({
    CONCORDANCE_WITNESS_HISTORICAL,
    CONCORDANCE_WITNESS_PROSPECTIVE,
})
REQUIRED_IDENTITY_FIELDS = frozenset({
    "strategy", "controller_rule_sha256", "wealth_core_source_sha256",
    "data_semantics_source_sha256"})

_SERIES_FIELDS = (
    "sessions", "session_indices", "signal_closes", "raw_closes", "volumes")
_PLAN_EVIDENCE_FIELDS = (
    "execution_model", "session", "intents", "blocked", "block_reason",
    "resolved_equity", "estimated_equity", "resolved_open_equity",
    "open_unresolved_security_ids", "hashes", "warnings")


def _hash(value) -> str:
    blob = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def _path_dependent_security_ids(wealth_core: Mapping,
                                 pending: Sequence[Mapping]) -> set[str]:
    """Security anchors/cached marks whose next transition can still matter."""
    protected: set[str] = set()

    def add(value) -> None:
        if value is not None and str(value):
            protected.add(str(value))

    for episode in (wealth_core.get("episodes") or {}).values():
        add(episode.get("security_id"))
    for slot in (wealth_core.get("slots") or {}).values():
        add(slot.get("occupied_by"))
        add(slot.get("reserved_for"))
    for order in pending:
        add(order.get("security_id"))
    for field_name in (
            "security_cooldowns", "unresolved_terminals",
            "sessions_since_valid_mark", "terminal_pending_sessions",
            "terminal_pending_terms", "terminal_carry_audit",
            "last_valid_mark_session"):
        for security_id in (wealth_core.get(field_name) or {}):
            add(security_id)
    return protected


def _bounded_last_known(raw: Mapping, protected_security_ids: set[str]) -> dict:
    return {
        str(sid): float(mark) for sid, mark in sorted(raw.items())
        if str(sid) in protected_security_ids}


def _bounded_feed_dict(raw: Mapping,
                       protected_security_ids: set[str] | None = None) -> dict:
    """Return the schema-v3 feed restart image.

    The absolute split factor and current identity are anchors.  Observation
    arrays are parallel and retain exactly t-126..t by GLOBAL session index;
    older rows are corpus history, not production state.
    """
    protected = set(protected_security_ids or ())
    session_index = int(raw.get("session_index", -1))
    cutoff = session_index - FEED_RESTART_SESSIONS + 1
    seen: dict[str, int] = {}
    for session, index in (raw.get("seen_sessions") or {}).items():
        index = int(index)
        if index > session_index:
            raise ValueError("feed restart state contains a future session index")
        if index >= cutoff:
            seen[str(session)] = index
    seen = dict(sorted(seen.items(), key=lambda item: (item[1], item[0])))

    compact_series: dict[str, dict] = {}
    for sid, value in sorted((raw.get("series") or {}).items()):
        series = dict(value)
        columns = {name: list(series.get(name) or []) for name in _SERIES_FIELDS}
        lengths = {len(column) for column in columns.values()}
        if len(lengths) != 1:
            raise ValueError(
                f"feed restart series {sid!r} has misaligned observation arrays")
        keep = [i for i, index in enumerate(columns["session_indices"])
                if int(index) >= cutoff]
        if any(int(columns["session_indices"][i]) > session_index for i in keep):
            raise ValueError(
                f"feed restart series {sid!r} contains a future observation")
        sid = str(sid)
        if not keep and sid not in protected:
            continue
        required = ("security_id", "ticker", "issuer_id", "split_factor")
        missing_anchor = [name for name in required if name not in series]
        if missing_anchor:
            raise ValueError(
                f"feed restart series {sid!r} has incomplete anchor: missing "
                + ", ".join(missing_anchor))
        security_id = series["security_id"]
        ticker = series["ticker"]
        issuer_id = series["issuer_id"]
        if not isinstance(security_id, str) or not security_id.strip():
            raise ValueError(
                f"feed restart series {sid!r} has invalid security_id anchor")
        if security_id != sid:
            raise ValueError(
                f"feed restart series key {sid!r} disagrees with security_id "
                f"anchor {security_id!r}")
        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError(
                f"feed restart series {sid!r} has invalid ticker anchor")
        if not isinstance(issuer_id, str) or not issuer_id.strip():
            raise ValueError(
                f"feed restart series {sid!r} has invalid issuer_id anchor")
        try:
            split_factor = float(series["split_factor"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"feed restart series {sid!r} has invalid split_factor anchor"
            ) from exc
        if (isinstance(series["split_factor"], bool)
                or not math.isfinite(split_factor) or split_factor <= 0):
            raise ValueError(
                f"feed restart series {sid!r} has invalid split_factor anchor")
        compact_series[sid] = {
            "security_id": security_id,
            "ticker": ticker,
            "issuer_id": issuer_id,
            "split_factor": split_factor,
            **{name: [columns[name][i] for i in keep]
               for name in _SERIES_FIELDS},
        }
    missing = protected - set(compact_series)
    if missing:
        raise ValueError(
            "feed restart state lacks path-dependent anchors for: "
            + ", ".join(sorted(missing)))
    return {"session_index": session_index, "seen_sessions": seen,
            "series": compact_series}


def _canonical_concordance_state(
        strategy_identity: Mapping[str, object],
        recent_leadership: Mapping | None, ldrc: Mapping | None
        ) -> tuple[dict | None, dict | None]:
    enabled = is_concordance_identity(strategy_identity)
    if enabled:
        if recent_leadership is None or ldrc is None:
            raise ValueError(
                "Concordance strategy identity requires durable witness and LD-RC state")
        return (
            leadership_state_to_dict(
                leadership_state_from_dict(recent_leadership)),
            ldrc_state_to_dict(ldrc_state_from_dict(ldrc)),
        )
    if recent_leadership is not None or ldrc is not None:
        raise ValueError(
            "Concordance state exists under a non-Concordance strategy identity")
    return None, None


def _bounded_evidence(raw: Mapping | None) -> dict | None:
    """Strip recursive plan state from diagnostic evidence.

    The whitelist is intentional: a future plan field does not become durable
    production state merely because it was added to ``LiveSessionPlan``.
    """
    if raw is None:
        return None
    evidence = dict(raw)
    plan = evidence.get("wealth_core")
    if isinstance(plan, Mapping):
        evidence["wealth_core"] = {
            key: plan[key] for key in _PLAN_EVIDENCE_FIELDS if key in plan}
    return evidence


@dataclass
class SessionState:
    wealth_core: dict
    pending: list[dict]
    ledger: dict
    last_known: dict[str, float]
    feed: dict
    controller: dict
    shadow_peak_nav: float
    shadow_nav_history: list[float] = field(default_factory=list)
    trailing_stop_sessions: list[str] = field(default_factory=list)
    controller_session_history: list[str] = field(default_factory=list)
    breadth_history: list[float] = field(default_factory=list)
    last_processed_session: str | None = None
    data_version: int | None = None
    strategy_identity: dict = field(default_factory=dict)
    last_decision: dict | None = None
    last_evidence: dict | None = None
    recent_leadership: dict | None = None
    ldrc: dict | None = None
    concordance_witness_origin: str | None = None
    version: int = ENVELOPE_VERSION

    @classmethod
    def fresh(cls, *, starting_cash: float, controller: Controller,
              strategy_identity: Mapping) -> "SessionState":
        missing = REQUIRED_IDENTITY_FIELDS - set(strategy_identity)
        if missing:
            raise ValueError("strategy identity is incomplete: "
                             + ", ".join(sorted(missing)))
        concordance = is_concordance_identity(strategy_identity)
        return cls(
            wealth_core=PortfolioState.fresh(starting_cash).to_dict(),
            pending=[], ledger=Ledger().to_dict(), last_known={},
            feed={"session_index": -1, "seen_sessions": {}, "series": {}},
            controller=controller.initial_state(),
            shadow_peak_nav=float(starting_cash),
            strategy_identity=dict(strategy_identity),
            recent_leadership=(
                leadership_state_to_dict(RecentLeadershipState())
                if concordance else None),
            ldrc=(ldrc_state_to_dict(LDRCState()) if concordance else None),
            # Before prospective paper formation existed, every Concordance
            # state was formed under the historical-causality contract.  The
            # warm-up boundary overwrites this only for the explicitly signed
            # current-only observation path.
            concordance_witness_origin=(
                CONCORDANCE_WITNESS_HISTORICAL if concordance else None))

    def to_dict(self) -> dict:
        recent_leadership, ldrc = _canonical_concordance_state(
            self.strategy_identity, self.recent_leadership, self.ldrc)
        concordance = is_concordance_identity(self.strategy_identity)
        origin = self.concordance_witness_origin
        if concordance and origin is None:
            # Pre-field v4 objects have the same unambiguous meaning as a
            # persisted missing field: historical formation. They still cannot
            # cross the v5 data-semantics identity boundary unless that required
            # identity is explicitly present.
            origin = CONCORDANCE_WITNESS_HISTORICAL
        if concordance:
            if origin not in _CONCORDANCE_WITNESS_ORIGINS:
                raise ValueError(
                    "Concordance state lacks a valid witness-formation origin")
        elif self.concordance_witness_origin is not None:
            raise ValueError(
                "non-Concordance state carries Concordance witness provenance")
        raw = asdict(self)
        # Backward-compatible discriminated encoding: absence is the only
        # historical formation that pre-dates this field; prospective
        # formation is always explicit. Omitting the historical/irrelevant
        # default keeps the discriminated encoding stable while v5 separately
        # invalidates state that lacks the required data-semantics identity.
        if origin != CONCORDANCE_WITNESS_PROSPECTIVE:
            raw.pop("concordance_witness_origin", None)
        else:
            raw["concordance_witness_origin"] = origin
        raw["recent_leadership"] = recent_leadership
        raw["ldrc"] = ldrc
        protected = _path_dependent_security_ids(
            raw["wealth_core"], raw["pending"])
        raw["feed"] = _bounded_feed_dict(raw["feed"], protected)
        raw["last_known"] = _bounded_last_known(raw["last_known"], protected)
        raw["last_evidence"] = _bounded_evidence(raw["last_evidence"])
        raw["controller"] = validate_controller_state(raw["controller"])
        raw["version"] = ENVELOPE_VERSION
        json.dumps(raw, sort_keys=True, allow_nan=False)
        return raw

    @classmethod
    def from_dict(cls, raw: Mapping) -> "SessionState":
        version = int(raw.get("version", 0))
        if version == 1:
            raise ValueError("production state version 1 cannot be migrated safely: "
                             "lifetime shadow peak and trailing-stop history are absent")
        if version not in (*LEGACY_ENVELOPE_VERSIONS, ENVELOPE_VERSION):
            raise ValueError(f"unsupported production state version {raw.get('version')!r}")
        migrated = dict(raw)
        if "concordance_witness_origin" not in migrated:
            # Version-4 states written before prospective formation existed can
            # only have used the historical metadata path.  This is a typed
            # migration of old evidence, not a guess about a new state.
            migrated["concordance_witness_origin"] = (
                CONCORDANCE_WITNESS_HISTORICAL
                if is_concordance_identity(
                    migrated.get("strategy_identity") or {}) else None)
        if version in LEGACY_ENVELOPE_VERSIONS:
            migrated.setdefault("recent_leadership", None)
            migrated.setdefault("ldrc", None)
        protected = _path_dependent_security_ids(
            migrated.get("wealth_core") or {}, migrated.get("pending") or [])
        migrated["feed"] = _bounded_feed_dict(
            migrated.get("feed") or {}, protected)
        migrated["last_known"] = _bounded_last_known(
            migrated.get("last_known") or {}, protected)
        migrated["last_evidence"] = _bounded_evidence(
            migrated.get("last_evidence"))
        migrated["controller"] = validate_controller_state(
            migrated.get("controller") or {})
        migrated["version"] = ENVELOPE_VERSION
        json.dumps(migrated, sort_keys=True, allow_nan=False)
        state = cls(**migrated)
        portfolio = PortfolioState.from_dict(state.wealth_core)
        if sorted(portfolio.slots) != list(range(DEFAULT_SLOTS)):
            raise ValueError(
                f"production Wealth Core state requires exactly {DEFAULT_SLOTS} "
                "canonical slots")
        missing = REQUIRED_IDENTITY_FIELDS - set(state.strategy_identity)
        if missing:
            raise ValueError("persisted strategy identity is incomplete: "
                             + ", ".join(sorted(missing)))
        state.recent_leadership, state.ldrc = _canonical_concordance_state(
            state.strategy_identity, state.recent_leadership, state.ldrc)
        concordance = is_concordance_identity(state.strategy_identity)
        if (concordance
                and state.concordance_witness_origin not in
                _CONCORDANCE_WITNESS_ORIGINS):
            raise ValueError(
                "persisted Concordance witness-formation origin is invalid")
        if not concordance and state.concordance_witness_origin is not None:
            raise ValueError(
                "persisted non-Concordance state carries witness provenance")
        return state

    @property
    def state_hash(self) -> str:
        return _hash(self.to_dict())


@dataclass(frozen=True)
class FeedAnchor:
    """Pinned-corpus basis for a current security absent from restart state."""
    security_id: str
    ticker: str
    issuer_id: str
    prior_split_factor: float


@dataclass(frozen=True)
class DefensiveBar:
    """Exact published Sharadar SFP fields consumed by Core/BIL accounting."""

    session: str
    security_id: str
    ticker: str
    open_signal: float
    close_signal: float
    close_adjusted: float
    close_unadjusted: float

    def __post_init__(self) -> None:
        if self.security_id != "SENTINEL:BIL" or self.ticker != "BIL":
            raise ValueError("defensive bar is not the fixed SENTINEL:BIL identity")
        if not isinstance(self.session, str) or not self.session:
            raise ValueError("defensive bar session is required")
        for name in (
                "open_signal", "close_signal", "close_adjusted",
                "close_unadjusted"):
            try:
                value = float(getattr(self, name))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"defensive bar {name} is not a positive finite value"
                ) from exc
            if not math.isfinite(value) or value <= 0:
                raise ValueError(
                    f"defensive bar {name} is not a positive finite value")

    @property
    def adjusted_open(self) -> float:
        """Retained reference formula: SFP open * closeadj / close."""
        value = (float(self.open_signal) * float(self.close_adjusted)
                 / float(self.close_signal))
        if not math.isfinite(value) or value <= 0:
            raise ValueError("defensive adjusted open is not positive and finite")
        return value


@dataclass(frozen=True)
class PublishedSession:
    session: str
    data_version: int
    bars: Sequence[VendorBar]
    meta: Mapping[str, SecurityMeta]
    sectors: Mapping[str, str | None]
    spy_closeadj: Sequence[float | None]
    spy_sessions: Sequence[str] = ()
    spy_expected_sessions: Sequence[str] = ()
    terminal_events: Sequence[TerminalTerms] = ()
    feed_anchors: Mapping[str, FeedAnchor] = field(default_factory=dict)
    defensive_bar: DefensiveBar | None = None
    # The denominator must come from the SAME held publication as the current
    # row. SFP adjusted-close history may be rescaled when a distribution
    # lands; carrying yesterday's old-publication value into today's numerator
    # would turn a harmless scale revision into artificial strategy P/L.
    defensive_previous_bar: DefensiveBar | None = None


def _feed_from_dict(raw: Mapping, meta, elig) -> Feed:
    feed = Feed(meta, elig)
    feed._session_index = int(raw.get("session_index", -1))
    feed._seen_sessions = {str(k): int(v) for k, v in
                           (raw.get("seen_sessions") or {}).items()}
    if feed._seen_sessions:
        feed._last_session = max(
            feed._seen_sessions, key=feed._seen_sessions.__getitem__)
    # `Feed.update()` appends to every SecuritySeries array.  Constructing the
    # dataclass directly from persisted mappings aliases those nested lists and
    # mutates the caller's supposedly immutable prior SessionState.  Copy every
    # mutable column at this boundary so `advance_session` remains a pure
    # transition and a pre-transition commitment cannot change under its own
    # verifier.
    feed.series = {
        sid: SecuritySeries(**{
            **dict(series),
            **{name: list(series.get(name) or []) for name in _SERIES_FIELDS},
        })
        for sid, series in (raw.get("series") or {}).items()
    }
    return feed


def _feed_to_dict(feed: Feed, protected_security_ids: set[str]) -> dict:
    return _bounded_feed_dict({
        "session_index": feed._session_index,
        "seen_sessions": dict(feed._seen_sessions),
        "series": {sid: asdict(s) for sid, s in sorted(feed.series.items())}},
        protected_security_ids)


def _restore_missing_feed_anchors(feed: Feed,
                                  published: PublishedSession) -> None:
    """Restore evicted returning series before canonical Feed sees the bars."""
    for bar in sorted(published.bars, key=lambda item: item.security_id):
        if bar.security_id in feed.series:
            continue
        anchor = published.feed_anchors.get(bar.security_id)
        if anchor is None:
            meta = published.meta.get(bar.security_id)
            if meta is None or meta.first_session != published.session:
                raise FeedError(
                    f"returning security {bar.security_id!r} has no pinned-corpus "
                    "split/identity anchor")
            continue
        factor = float(anchor.prior_split_factor)
        if (anchor.security_id != bar.security_id or not anchor.issuer_id
                or not math.isfinite(factor) or factor <= 0):
            raise FeedError(
                f"invalid pinned-corpus feed anchor for {bar.security_id!r}")
        feed.series[bar.security_id] = SecuritySeries(
            security_id=bar.security_id, ticker=anchor.ticker,
            issuer_id=anchor.issuer_id, split_factor=factor)


def _return(series: SecuritySeries, horizon: int) -> float | None:
    if not series.signal_closes or not series.session_indices:
        return None
    target = series.session_indices[-1] - horizon
    try:
        i = series.session_indices.index(target)
    except ValueError:
        return None
    now, then = series.signal_closes[-1], series.signal_closes[i]
    value = lag_return(now, then)
    return value if math.isfinite(value) else None


def holdings_from_shadow(state: PortfolioState, feed: Feed,
                         sectors: Mapping[str, str | None]) -> list[Holding]:
    """Build breadth inputs from filled episodes, never target/oracle rows."""
    out = []
    for slot in sorted(state.episodes):
        ep = state.episodes[slot]
        series = feed.series.get(ep.security_id)
        close = series.signal_closes[-1] if series and series.signal_closes else None
        peak = ep.episode_peak_split_adjusted_close
        own_dd = (None if close is None or peak is None or peak <= 0 else
                  float(close) / float(peak) - 1.0)
        out.append(Holding(
            ticker=ep.ticker, sector=sectors.get(ep.security_id),
            own_dd=own_dd, r21=_return(series, 21) if series else None,
            r63=_return(series, 63) if series else None,
            age_sessions=ep.market_sessions_held))
    return out


def _period_return(values: Sequence[float], horizon: int) -> float | None:
    if len(values) <= horizon or values[-1 - horizon] <= 0:
        return None
    return values[-1] / values[-1 - horizon] - 1.0


__all__ = [
    "CONCORDANCE_WITNESS_HISTORICAL",
    "CONCORDANCE_WITNESS_PROSPECTIVE",
    "DefensiveBar",
    "ENVELOPE_VERSION",
    "FeedAnchor",
    "PublishedSession",
    "REQUIRED_IDENTITY_FIELDS",
    "SessionState",
    "holdings_from_shadow",
]
