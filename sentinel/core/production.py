"""The deterministic production brain for one Sentinel session.

This module deliberately stops before execution projection.  It owns one
authoritative, JSON-serialisable envelope and composes the already-certified
Wealth Core live step, recovered breadth classifier, SPY sensor and controller.
The caller supplies a published session snapshot; no broker or clock is read.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Mapping, Sequence

from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.engine import Reason, WealthCoreConfig
from stock_strategy_shared.wealth_core.feed import Feed, SecurityMeta, SecuritySeries, VendorBar
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.live import plan_session
from stock_strategy_shared.wealth_core.signals import REQUIRED_CLOSES
from stock_strategy_shared.wealth_core.state import PortfolioState
from stock_strategy_shared.wealth_core.terminal import TerminalTerms

from sentinel.breadth.classifier import Holding, session_breadth
from sentinel.controller.frozen_rule import ControllerConfig
from sentinel.controller.machine import Controller, Observation
from sentinel.regime.spy import spy_regime

ENVELOPE_VERSION = 3
LEGACY_ENVELOPE_VERSION = 2
FEED_RESTART_SESSIONS = REQUIRED_CLOSES
REQUIRED_IDENTITY_FIELDS = frozenset({
    "strategy", "controller_rule_sha256", "wealth_core_source_sha256"})

_SERIES_FIELDS = (
    "sessions", "session_indices", "signal_closes", "raw_closes", "volumes")
_PLAN_EVIDENCE_FIELDS = (
    "execution_model", "session", "intents", "blocked", "block_reason",
    "resolved_equity", "estimated_equity", "hashes", "warnings")


def _hash(value) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _bounded_feed_dict(raw: Mapping) -> dict:
    """Return the schema-v3 feed restart image.

    The absolute split factor and current identity are anchors.  Observation
    arrays are parallel and retain exactly t-126..t by GLOBAL session index;
    older rows are corpus history, not production state.
    """
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
        compact_series[str(sid)] = {
            "security_id": str(series.get("security_id", sid)),
            "ticker": str(series.get("ticker", sid)),
            "issuer_id": str(series.get("issuer_id", f"S:{sid}")),
            "split_factor": float(series.get("split_factor", 1.0)),
            **{name: [columns[name][i] for i in keep]
               for name in _SERIES_FIELDS},
        }
    return {"session_index": session_index, "seen_sessions": seen,
            "series": compact_series}


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
    version: int = ENVELOPE_VERSION

    @classmethod
    def fresh(cls, *, starting_cash: float, controller: Controller,
              strategy_identity: Mapping) -> "SessionState":
        missing = REQUIRED_IDENTITY_FIELDS - set(strategy_identity)
        if missing:
            raise ValueError("strategy identity is incomplete: "
                             + ", ".join(sorted(missing)))
        return cls(
            wealth_core=PortfolioState.fresh(starting_cash).to_dict(),
            pending=[], ledger=Ledger().to_dict(), last_known={},
            feed={"session_index": -1, "seen_sessions": {}, "series": {}},
            controller=controller.initial_state(),
            shadow_peak_nav=float(starting_cash),
            strategy_identity=dict(strategy_identity))

    def to_dict(self) -> dict:
        raw = asdict(self)
        raw["feed"] = _bounded_feed_dict(raw["feed"])
        raw["last_evidence"] = _bounded_evidence(raw["last_evidence"])
        raw["version"] = ENVELOPE_VERSION
        return raw

    @classmethod
    def from_dict(cls, raw: Mapping) -> "SessionState":
        version = int(raw.get("version", 0))
        if version == 1:
            raise ValueError("production state version 1 cannot be migrated safely: "
                             "lifetime shadow peak and trailing-stop history are absent")
        if version not in (LEGACY_ENVELOPE_VERSION, ENVELOPE_VERSION):
            raise ValueError(f"unsupported production state version {raw.get('version')!r}")
        migrated = dict(raw)
        migrated["feed"] = _bounded_feed_dict(migrated.get("feed") or {})
        migrated["last_evidence"] = _bounded_evidence(
            migrated.get("last_evidence"))
        migrated["version"] = ENVELOPE_VERSION
        state = cls(**migrated)
        missing = REQUIRED_IDENTITY_FIELDS - set(state.strategy_identity)
        if missing:
            raise ValueError("persisted strategy identity is incomplete: "
                             + ", ".join(sorted(missing)))
        return state

    @property
    def state_hash(self) -> str:
        return _hash(self.to_dict())


@dataclass(frozen=True)
class PublishedSession:
    session: str
    data_version: int
    bars: Sequence[VendorBar]
    meta: Mapping[str, SecurityMeta]
    sectors: Mapping[str, str | None]
    spy_closeadj: Sequence[float | None]
    terminal_events: Sequence[TerminalTerms] = ()


def load_published_session(conn, session: str, *, spy_sessions: int = 41
                           ) -> PublishedSession:
    """Load one coherent production input snapshot from the published corpus."""
    from sentinel.core.loader import load_meta, load_terminal_events
    from sentinel.feed.publication import assert_coherent, current, visible_predicate
    from sentinel.feed.universe import load_resolver

    assert_coherent(conn)
    publication = current(conn)
    if publication is None:
        raise RuntimeError("the corpus has never been published")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT security_id,ticker,close_unadjusted,open_unadjusted,volume,"
            " split_ratio,dividend_per_share FROM sentinel_bars b"
            f" WHERE session=%s AND {visible_predicate('b')}"
            " ORDER BY security_id", (session,))
        bars = [VendorBar(session, str(sid), str(ticker), close, op, volume,
                          float(split or 1.0), float(div or 0.0),
                          bool(close and volume))
                for sid, ticker, close, op, volume, split, div in cur.fetchall()]
        cur.execute(
            "SELECT closeadj FROM sentinel_spy_total_return r"
            f" WHERE session<=%s AND {visible_predicate('r')}"
            " ORDER BY session DESC LIMIT %s", (session, spy_sessions))
        spy = [float(row[0]) for row in reversed(cur.fetchall())]
        cur.execute(
            "SELECT permaticker,(ARRAY_REMOVE(ARRAY_AGG(sector ORDER BY"
            " snapshot_date DESC),NULL))[1] FROM sentinel_universe"
            " WHERE permaticker IS NOT NULL GROUP BY permaticker")
        sectors = {str(sid): sector for sid, sector in cur.fetchall()}
    if not bars:
        raise RuntimeError(f"no published bars for {session}")
    if len(spy) < spy_sessions:
        raise RuntimeError(f"only {len(spy)} published SPY closeadj observations")
    resolver = load_resolver(conn)
    terminals = load_terminal_events(
        conn, start=session, end=session,
        resolve_with_reason=resolver.resolve_with_reason).events
    return PublishedSession(session=session, data_version=publication.version,
                            bars=bars, meta=load_meta(conn), sectors=sectors,
                            spy_closeadj=spy, terminal_events=terminals)


def _feed_from_dict(raw: Mapping, meta, elig) -> Feed:
    feed = Feed(meta, elig)
    feed._session_index = int(raw.get("session_index", -1))
    feed._seen_sessions = {str(k): int(v) for k, v in
                           (raw.get("seen_sessions") or {}).items()}
    feed.series = {sid: SecuritySeries(**series) for sid, series in
                   (raw.get("series") or {}).items()}
    return feed


def _feed_to_dict(feed: Feed) -> dict:
    return _bounded_feed_dict({
        "session_index": feed._session_index,
        "seen_sessions": dict(feed._seen_sessions),
        "series": {sid: asdict(s) for sid, s in sorted(feed.series.items())}})


def _return(series: SecuritySeries, horizon: int) -> float | None:
    if not series.signal_closes or not series.session_indices:
        return None
    target = series.session_indices[-1] - horizon
    try:
        i = series.session_indices.index(target)
    except ValueError:
        return None
    now, then = series.signal_closes[-1], series.signal_closes[i]
    if now is None or then is None or then <= 0:
        return None
    return float(now) / float(then) - 1.0


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


def advance_state(prior: SessionState | Mapping, published: PublishedSession,
                  *, controller_config: ControllerConfig,
                  strategy_identity: Mapping,
                  wealth_config: WealthCoreConfig | None = None,
                  eligibility_config: EligibilityConfig | None = None
                  ) -> SessionState:
    """Pure one-session transition. Persist its return in the caller's txn."""
    env = (prior if isinstance(prior, SessionState)
           else SessionState.from_dict(prior))
    if env.version != ENVELOPE_VERSION:
        raise ValueError(f"unsupported production state version {env.version!r}")
    running_identity = dict(strategy_identity)
    missing = REQUIRED_IDENTITY_FIELDS - set(running_identity)
    if missing:
        raise ValueError("running strategy identity is incomplete: "
                         + ", ".join(sorted(missing)))
    if running_identity["strategy"] != controller_config.strategy_id \
            or running_identity["controller_rule_sha256"] != controller_config.digest:
        raise ValueError("running strategy/controller identity disagrees with configuration")
    if env.strategy_identity != running_identity:
        raise ValueError("persisted strategy/config/source identity differs from running identity")
    if env.last_processed_session and published.session <= env.last_processed_session:
        raise ValueError("production sessions must advance strictly")
    if env.data_version is not None and published.data_version < env.data_version:
        raise ValueError("corpus publication version moved backwards")

    elig = eligibility_config or EligibilityConfig()
    state = PortfolioState.from_dict(env.wealth_core)
    pending = [PendingOrder.from_dict(p) for p in env.pending]
    ledger = Ledger.from_dict(env.ledger)
    last_known = dict(env.last_known)
    feed = _feed_from_dict(env.feed, published.meta, elig)
    ledger_event_boundary = len(ledger.events)
    plan = plan_session(
        session=published.session, bars=published.bars, meta=published.meta,
        state=state, pending=pending, ledger=ledger, last_known=last_known,
        feed=feed, cfg=wealth_config, eligibility_cfg=elig,
        terminal_events=published.terminal_events)

    # A stop is evidence only when its pending SELL actually filled.  Plan
    # intents are close-time decisions; the append-only ledger records the
    # completed fill with canonical typed event and reason values.
    completed_stops = [
        event for event in ledger.events[ledger_event_boundary:]
        if event.session == published.session
        and event.event_type is EventType.SELL
        and event.reason == Reason.EXIT_TRAILING_STOP.value
    ]

    held = holdings_from_shadow(state, feed, published.sectors)
    breadth = session_breadth(held)
    navs = list(env.shadow_nav_history)
    nav = float(plan.estimated_equity)
    navs.append(nav)
    navs = navs[-41:]
    peak = max(float(env.shadow_peak_nav), nav)
    stops = list(env.trailing_stop_sessions)
    stops.extend([published.session] * len(completed_stops))
    # Retain every completed stop from the current controller session plus
    # exactly the preceding 19 controller sessions; never age by calendar day.
    recent_sessions = (list(env.controller_session_history) + [published.session])[-20:]
    recent_session_set = set(recent_sessions)
    stops = [stop_session for stop_session in stops
             if stop_session in recent_session_set]
    damaged = list(env.breadth_history) + [breadth.damaged_breadth]
    regime = spy_regime(published.spy_closeadj)
    ob = Observation(
        session=published.session, shadow_nav=nav,
        damaged_breadth=breadth.damaged_breadth,
        green_breadth=breadth.green_breadth,
        shadow_drawdown=(nav / peak - 1.0 if peak else None),
        shadow_r5=_period_return(navs, 5), shadow_r10=_period_return(navs, 10),
        shadow_r20=_period_return(navs, 20), shadow_r40=_period_return(navs, 40),
        damaged_breadth_delta5=(damaged[-1] - damaged[-6]
                                if len(damaged) >= 6 else None),
        spy_r20=regime.spy_r20, spy_vol_ratio=regime.spy_vol_ratio)
    ob = Observation(**{**asdict(ob), "stops20": len(stops)})
    ctl = Controller(controller_config)
    controller_state, decision = ctl.step(observation=ob, state=env.controller)
    evidence = {"observation": asdict(ob), "breadth": {
        "denominator": breadth.denominator, "greens": breadth.greens,
        "ambers": breadth.ambers, "reds": breadth.reds,
        "holdings": [asdict(h) for h in held]},
        "wealth_core": _bounded_evidence(
            {"wealth_core": plan.to_dict()})["wealth_core"]}
    return SessionState(
        wealth_core=state.to_dict(), pending=[p.to_dict() for p in pending],
        ledger=ledger.to_dict(), last_known=last_known, feed=_feed_to_dict(feed),
        controller=controller_state, shadow_nav_history=navs,
        shadow_peak_nav=peak, trailing_stop_sessions=stops,
        controller_session_history=recent_sessions,
        breadth_history=damaged[-6:], last_processed_session=published.session,
        data_version=published.data_version,
        strategy_identity=dict(env.strategy_identity),
        last_decision=decision.to_dict(), last_evidence=evidence)


def advance_and_persist(conn, session: str, prior: Mapping, *, load_published,
                        controller_config: ControllerConfig,
                        strategy_identity: Mapping, **kwargs) -> dict:
    """Catch-up callback: compute only; catch_up commits envelope + cursor."""
    from sentinel.feed.publication import pinned
    with pinned(conn) as publication:
        published = load_published(conn, session)
        if published.data_version != publication.version:
            raise RuntimeError("loaded publication version differs from session pin")
        result = advance_state(
            prior, published, controller_config=controller_config,
            strategy_identity=strategy_identity, **kwargs)
        return result.to_dict()


__all__ = ["PublishedSession", "REQUIRED_IDENTITY_FIELDS", "SessionState",
           "advance_and_persist",
           "advance_state", "holdings_from_shadow", "load_published_session"]
