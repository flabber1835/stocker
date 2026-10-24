"""Production feature warm-up, corpus loading, and persistence seams.

The durable state model lives in :mod:`sentinel.core.session` and the pure
economic transition lives in :mod:`sentinel.core.kernel`. This adapter module
contains no historical portfolio simulator.
"""
from __future__ import annotations
from sentinel.core.feature_warmup import warm_session_state, _warm_median5

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
from sentinel.controller import median5 as median5_controller






def load_median5_warmup_inputs(conn, window):
    """Load the peer benchmark and terminal stream under the caller's pin."""
    from sentinel.feed.publication import visible_predicate
    from sentinel.feed.universe import load_resolver
    from sentinel.core.terminal import load_terminal_events
    start, end = window.sessions[0], window.sessions[-1]
    with conn.cursor() as cur:
        cur.execute("SELECT session,closeadj FROM sentinel_spy_total_return r "
                    "WHERE session BETWEEN %s AND %s AND "
                    + visible_predicate("r", sep_retirements=False) + " ORDER BY session", (start, end))
        window.median5_spy_closes = {str(s): float(p) for s, p in cur.fetchall()}
    resolver = load_resolver(conn)
    result = load_terminal_events(conn, start=start, end=end,
                                   resolve_with_reason=resolver.resolve_with_reason)
    if result.unresolved or not result.conservation_holds() or not result.normalized_stream_holds():
        raise ValueError("Median-5 warmup terminal evidence is incomplete")
    window.median5_terminals = {}
    for event in result.events:
        window.median5_terminals.setdefault(event.session, set()).add(event.security_id)


def load_signal_basis_anchors(conn, *, session: str, security_ids: Sequence[str]):
    """One last positive source observation per retained security under the caller's pin."""
    from sentinel.feed.publication import visible_predicate
    signal_basis_anchors = {}
    if security_ids:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ids.security_id,b.session,b.ticker,b.close_unadjusted,b.close_signal"
                " FROM unnest(%s::text[]) AS ids(security_id) CROSS JOIN LATERAL ("
                " SELECT b.session,b.ticker,b.close_unadjusted,b.close_signal"
                " FROM sentinel_bars b WHERE b.security_id=ids.security_id"
                " AND b.session<%s AND b.close_unadjusted>0 AND b.close_signal>0 AND "
                f"{visible_predicate('b')} ORDER BY b.session DESC LIMIT 1) b",
                (sorted(set(security_ids)), session))
            for sid, day, ticker, raw, signal in cur.fetchall():
                signal_basis_anchors[str(sid)] = VendorBar(
                    str(day), str(sid), str(ticker), raw, None, None, signal_close=signal)
    return signal_basis_anchors


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
            " dividend_per_share, close_signal FROM sentinel_bars b"
            f" WHERE session=%s AND {visible_predicate('b')}"
            " ORDER BY security_id", (session,))
        bars = []
        for row in cur.fetchall():
            sid, ticker, close, op, volume, split, div = row[:7]
            bars.append(VendorBar(session, str(sid), str(ticker), close, op, volume,
                                  float(split or 1.0), float(div or 0.0),
                                  bool(close and volume), signal_close=(row[7] if len(row) > 7 else None)))
        cur.execute(
            "SELECT session,closeadj FROM sentinel_spy_total_return r"
            f" WHERE session<=%s AND {visible_predicate('r', sep_retirements=False)}"
            " ORDER BY session DESC LIMIT %s", (session, spy_sessions))
        spy_rows = list(reversed(cur.fetchall()))
        actual_spy_sessions = [str(row[0]) for row in spy_rows]
        spy = [float(row[1]) for row in spy_rows]
        defensive_previous_session = expected_spy_sessions[-2]
        cur.execute(
            "SELECT session,security_id,ticker,open_signal,close_signal,"
            " close_adjusted,close_unadjusted"
            " FROM sentinel_defensive_bars d WHERE session=ANY(%s::date[]) AND "
            f"{visible_predicate('d', sep_retirements=False)} ORDER BY session",
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
    from sentinel.core.spinoffs import load_distributions
    from sentinel.feed.history_mutations import EVIDENCE_KEY
    return PublishedSession(
        session=session, data_version=publication.version, bars=bars, meta=meta,
        sectors=sectors, spy_closeadj=spy, signal_basis_anchors=load_signal_basis_anchors(
            conn, session=session, security_ids=known_feed_security_ids),
        spy_sessions=actual_spy_sessions,
        spy_expected_sessions=expected_spy_sessions,
        terminal_events=terminals,
        feed_anchors=anchors,
        defensive_bar=defensive,
        defensive_previous_bar=defensive_previous,
        history_proof=publication.evidence.get(EVIDENCE_KEY),
        spinoff_distributions=load_distributions(conn, session=session))


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
