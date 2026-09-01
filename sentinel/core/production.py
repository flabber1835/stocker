"""Production feature warm-up, corpus loading, and persistence seams.

The durable state model lives in :mod:`sentinel.core.session` and the pure
economic transition lives in :mod:`sentinel.core.kernel`. This adapter module
contains no historical portfolio simulator.
"""
from __future__ import annotations

import math
from typing import Mapping, Sequence

from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.engine import (
    WealthCoreConfig,
    score_universe,
)
from stock_strategy_shared.wealth_core.feed import Feed, VendorBar
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import PortfolioState

from sentinel.controller.concordance import (
    advance_recent_leadership,
    is_concordance_identity,
    state_from_dict as leadership_state_from_dict,
    state_to_dict as leadership_state_to_dict,
)
from sentinel.controller.frozen_rule import ControllerConfig
from sentinel.core.session import (
    CONCORDANCE_WITNESS_HISTORICAL,
    CONCORDANCE_WITNESS_PROSPECTIVE,
    REQUIRED_IDENTITY_FIELDS,
    DefensiveBar,
    FeedAnchor,
    PublishedSession,
    SessionState,
    _feed_to_dict,
    holdings_from_shadow,
)
from sentinel.feed.requirements import REQUIRED_SPY_SESSIONS as MIN_CLOSES


def warm_session_state(state: SessionState | Mapping, window, *,
                       publication_version: int,
                       eligibility_config: EligibilityConfig | None = None,
                       prospective_concordance_witness: bool = False,
                       ) -> SessionState:
    """Prime canonical rolling feed features without inventing book history.

    A fresh account has no episodes, peaks, ages, cooldowns, pending actions or
    controller memory to reconstruct. Running those historical sessions through
    ``plan_session`` would manufacture all of them. ``Feed.warmup`` is the
    canonical feature-only path; its bounded restart form is installed into the
    otherwise-fresh version-3 envelope and the decision session is advanced
    later, exactly once.
    """
    env = (state if isinstance(state, SessionState)
           else SessionState.from_dict(state))
    portfolio = PortfolioState.from_dict(env.wealth_core)
    ledger = Ledger.from_dict(env.ledger)
    if (env.last_processed_session is not None or portfolio.episodes
            or env.pending or ledger.events or env.controller_session_history):
        raise ValueError("feature-only warm-up requires a fresh canonical state")
    sessions = list(window.sessions)
    if (not sessions
            or any(left >= right for left, right in zip(sessions, sessions[1:]))):
        raise ValueError(
            "warm-up window sessions must be strictly increasing and unique")
    if type(prospective_concordance_witness) is not bool:
        raise ValueError(
            "prospective_concordance_witness must be an explicit boolean")
    elig = eligibility_config or EligibilityConfig()
    witness_state = None
    concordance = is_concordance_identity(env.strategy_identity)
    if prospective_concordance_witness and not concordance:
        raise ValueError(
            "prospective Concordance witness mode requires Concordance identity")
    if concordance and not prospective_concordance_witness:
        timeline = getattr(window, "metadata_timeline", None)
        if (timeline is None or list(timeline.sessions) != sessions):
            raise ValueError(
                "Concordance warm-up requires exact session-effective metadata")
        feed = Feed({}, elig, metadata_timeline=timeline)
        witness_state = leadership_state_from_dict(env.recent_leadership or {})
        wealth_cfg = WealthCoreConfig()
        for session in sessions:
            bars = window.bars_by_session.get(session, ())
            normalized = feed.advance(session, bars)
            scored = score_universe(normalized.security_bars, wealth_cfg)
            candidates = tuple(
                row for row in scored
                if row.momentum is not None and row.recent is not None)
            eligible_count = sum(
                1 for row in normalized.security_bars if row.eligible)
            # Before the canonical 127-close formation window exists there is
            # no leadership population and therefore no witness observation.
            # Appending flat NAVs here would manufacture r20/r40 readiness from
            # sessions on which the sensor could not yet exist.
            if eligible_count == 0:
                continue
            signal_closes = {}
            for bar in bars:
                series = feed.series.get(bar.security_id)
                if (series is None or not series.sessions
                        or series.sessions[-1] != session
                        or not series.signal_closes):
                    continue
                close = series.signal_closes[-1]
                if close is not None:
                    signal_closes[bar.security_id] = float(close)
            witness_state, _ = advance_recent_leadership(
                session=session, candidate_rows=candidates,
                eligible_universe_count=eligible_count,
                signal_closes=signal_closes, state=witness_state)
    else:
        # In the authenticated current-only paper cold start this primes only
        # price/volume/split features.  It makes no historical strategy or
        # witness decision; the zero-capital witness begins on the first live
        # close.  Non-Concordance warmup has always used this same feature-only
        # path.
        feed = Feed(window.meta, elig)
        feed.warmup(sessions, window.bars_by_session)
    warmed = SessionState.from_dict(env.to_dict())
    warmed.feed = _feed_to_dict(feed, set())
    if witness_state is not None:
        warmed.recent_leadership = leadership_state_to_dict(witness_state)
    if concordance:
        warmed.concordance_witness_origin = (
            CONCORDANCE_WITNESS_PROSPECTIVE
            if prospective_concordance_witness
            else CONCORDANCE_WITNESS_HISTORICAL)
    warmed.data_version = int(publication_version)
    return warmed


def load_published_session(conn, session: str, *, spy_sessions: int = MIN_CLOSES,
                           known_feed_security_ids: Sequence[str] = ()
                           ) -> PublishedSession:
    """Load one causal production input snapshot from the published corpus.

    Strategy metadata is always bounded to ``session``. There is intentionally
    no production switch for current/future TICKERS metadata: a missed session
    either has a causally available observation or planning refuses. Historical
    integration-only experiments that cannot make that causality claim must
    override their inputs outside this production API.
    """
    from sentinel.core.loader import load_meta, load_sectors
    from sentinel.core.terminal import load_terminal_events
    from sentinel.feed.calendar import previous_sessions
    from sentinel.feed.publication import (
        assert_operationally_coherent, current, effective_split_ratio,
        visible_predicate,
    )
    from sentinel.feed.universe import load_resolver

    assert_operationally_coherent(
        conn, frontier=session,
        extra_security_ids=tuple(known_feed_security_ids))
    publication = current(conn)
    if publication is None:
        raise RuntimeError("the corpus has never been published")
    if (isinstance(spy_sessions, bool) or not isinstance(spy_sessions, int)
            or spy_sessions < MIN_CLOSES):
        raise ValueError(
            f"spy_sessions must be an integer >= {MIN_CLOSES}")
    expected_spy_sessions = previous_sessions(session, spy_sessions)
    if (len(expected_spy_sessions) != spy_sessions
            or expected_spy_sessions[-1] != session):
        raise RuntimeError(
            f"{session} is not the end of a complete {spy_sessions}-session "
            "XNYS SPY window")
    meta = load_meta(conn, as_of=session)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT security_id,ticker,close_unadjusted,open_unadjusted,volume,"
            f" {effective_split_ratio('b')} AS split_ratio,"
            " dividend_per_share FROM sentinel_bars b"
            f" WHERE session=%s AND {visible_predicate('b')}"
            " ORDER BY security_id", (session,))
        bars = [VendorBar(session, str(sid), str(ticker), close, op, volume,
                          float(split or 1.0), float(div or 0.0),
                          bool(close and volume))
                for sid, ticker, close, op, volume, split, div in cur.fetchall()]
        cur.execute(
            "SELECT session,closeadj FROM sentinel_spy_total_return r"
            f" WHERE session<=%s AND {visible_predicate('r')}"
            " ORDER BY session DESC LIMIT %s", (session, spy_sessions))
        spy_rows = list(reversed(cur.fetchall()))
        actual_spy_sessions = [str(row[0]) for row in spy_rows]
        spy = [float(row[1]) for row in spy_rows]
        defensive_previous_session = expected_spy_sessions[-2]
        cur.execute(
            "SELECT session,security_id,ticker,open_signal,close_signal,"
            " close_adjusted,close_unadjusted"
            " FROM sentinel_defensive_bars d WHERE session=ANY(%s::date[]) AND "
            f"{visible_predicate('d')} ORDER BY session",
            ([defensive_previous_session, session],))
        defensive_rows = cur.fetchall()
        sectors = load_sectors(conn, as_of=session)
    if not bars:
        raise RuntimeError(f"no published bars for {session}")
    if actual_spy_sessions != expected_spy_sessions:
        raise RuntimeError(
            "published SPY closeadj rows are not the exact dated XNYS tail "
            f"ending {session}: expected {expected_spy_sessions}, got "
            f"{actual_spy_sessions}")
    if len(defensive_rows) != 2:
        raise RuntimeError(
            f"expected adjacent published SENTINEL:BIL rows for "
            f"{defensive_previous_session} and {session}, got "
            f"{len(defensive_rows)}")
    defensive_bars = [DefensiveBar(
        session=str(row[0]), security_id=str(row[1]), ticker=str(row[2]),
        open_signal=row[3], close_signal=row[4], close_adjusted=row[5],
        close_unadjusted=row[6]) for row in defensive_rows]
    defensive_previous, defensive = defensive_bars
    if (defensive_previous.session != defensive_previous_session
            or defensive.session != session):
        raise RuntimeError(
            "published defensive rows are not the exact adjacent XNYS "
            f"sessions {defensive_previous_session}, {session}")
    resolver = load_resolver(conn)
    terminal_result = load_terminal_events(
        conn, start=session, end=session,
        resolve_with_reason=resolver.resolve_with_reason)
    if (not terminal_result.conservation_holds()
            or not terminal_result.normalized_stream_holds()):
        raise RuntimeError(
            f"terminal normalization for {session} did not produce a "
            "conserved, unique Wealth Core event stream")
    if terminal_result.unresolved:
        raise RuntimeError(
            f"unresolved terminal evidence for {session}: "
            + "; ".join(row.describe()
                        for row in terminal_result.unresolved[:10]))
    terminals = terminal_result.events
    missing = sorted(
        {bar.security_id for bar in bars} - set(known_feed_security_ids))
    factors = {sid: 1.0 for sid in missing}
    counts = {sid: 0 for sid in missing}
    if missing:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT security_id,"
                f" {effective_split_ratio('b')} AS split_ratio"
                " FROM sentinel_bars b"
                " WHERE security_id=ANY(%s) AND session<%s AND "
                f"{visible_predicate('b')} ORDER BY security_id,session",
                (missing, session))
            for sid, ratio in cur.fetchall():
                sid = str(sid)
                ratio = float(ratio)
                if not math.isfinite(ratio) or ratio <= 0:
                    raise RuntimeError(
                        f"cannot reconstruct split anchor for {sid!r}: "
                        f"invalid published ratio {ratio!r}")
                factors[sid] *= ratio
                counts[sid] += 1
    by_security = {bar.security_id: bar for bar in bars}
    anchors: dict[str, FeedAnchor] = {}
    for sid in missing:
        security_meta = meta.get(sid)
        if security_meta is None:
            raise RuntimeError(
                f"cannot reconstruct feed anchor for {sid!r}: metadata absent")
        issuer_id, _ = security_meta.issuer_key()
        if counts[sid]:
            if issuer_id is None:
                raise RuntimeError(
                    f"cannot reconstruct feed anchor for returning {sid!r}: "
                    "issuer identity is unresolved")
            anchors[sid] = FeedAnchor(
                security_id=sid, ticker=by_security[sid].ticker,
                issuer_id=issuer_id, prior_split_factor=factors[sid])
        elif security_meta.first_session != session:
            raise RuntimeError(
                f"cannot prove {sid!r} is a first corpus observation on "
                f"{session}; refusing a default split/identity anchor")
    return PublishedSession(
        session=session, data_version=publication.version, bars=bars, meta=meta,
        sectors=sectors, spy_closeadj=spy,
        spy_sessions=actual_spy_sessions,
        spy_expected_sessions=expected_spy_sessions,
        terminal_events=terminals,
        feed_anchors=anchors,
        defensive_bar=defensive,
        defensive_previous_bar=defensive_previous)


def advance_and_persist(conn, session: str, prior: SessionState | Mapping, *,
                        load_published,
                        controller_config: ControllerConfig,
                        strategy_identity: Mapping,
                        commit_pin: bool = True, **kwargs) -> dict:
    """Catch-up callback: compute only; catch_up commits envelope + cursor."""
    from sentinel.core.kernel import advance_session
    from sentinel.feed.publication import pinned
    canonical_prior = SessionState.from_dict(
        prior.to_dict() if isinstance(prior, SessionState) else prior)
    pin = pinned(conn) if commit_pin else pinned(conn, commit=False)
    with pin as publication:
        published = load_published(
            conn, session,
            known_feed_security_ids=tuple(
                canonical_prior.feed["series"].keys()))
        if published.data_version != publication.version:
            raise RuntimeError("loaded publication version differs from session pin")
        result = advance_session(
            canonical_prior, published, controller_config=controller_config,
            strategy_identity=strategy_identity, **kwargs)
        return result.to_dict()


__all__ = ["DefensiveBar", "FeedAnchor", "PublishedSession",
           "REQUIRED_IDENTITY_FIELDS", "SessionState",
           "advance_and_persist",
           "holdings_from_shadow", "load_published_session",
           "warm_session_state"]
