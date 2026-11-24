"""Daily feature replacement with continuity of retained economic state."""
import math

from sentinel.feed.normalized_layout import candidate_query
from sentinel.core import window_features
from sentinel.core.history import CurrentWindowProof
from sentinel.core.rolling_inputs import (
    SnapshotReferences, merger_anchor_bar, merger_owned_security_ids,
    merger_provider_assets, merger_terminal_terms,
)
from sentinel.core.rolling_reader import RollingPriceReader
from sentinel.feed import calendar, rolling_store
from sentinel.feed.rolling_contract import canonical_json, digest
class MergerActionPending(RuntimeError):
    """A selected-only prior identity needs newly observed source action terms."""

    def __init__(self, session, security_id):
        self.session = session
        self.security_id = security_id
        super().__init__('SELECTED_IDENTITY_ACTION_PENDING:' + session + ':' + security_id)


def protected_economics(conn, *, previous, current, live, start, cursor):
    """Past cash/share events for retained identities cannot be applied twice."""
    from sentinel.core.rolling_continuity import RollingContinuityRefused

    def events(refs):
        return sorted(canonical_json(payload) for _, payload, _ in refs.actions
            if start <= payload['date'] <= cursor
            and payload['action'].lower() != 'dividend'
            and (refs.resolver.resolve(payload['ticker'], payload['date']) in live
                 or refs.resolver.resolve(payload.get('contraticker') or '', payload['date']) in live))

    def distributions(refs):
        rows = conn.execute(candidate_query(conn, 'SELECT session,security_id,split_ratio,dividend_per_share '
            'FROM sentinel_snapshot_bars WHERE candidate_id=%s AND session BETWEEN %s AND %s '
            'AND security_id=ANY(%s) AND (split_ratio<>1 OR dividend_per_share<>0) '
            'ORDER BY session,security_id COLLATE "C"'),
            (refs.candidate_id, start, cursor, sorted(live))).fetchall()
        return [(str(day), sid, split) for day, sid, split, cash in rows if split != 1]

    evidence = {'actions': events(previous), 'distributions': distributions(previous)}
    if evidence != {'actions': events(current), 'distributions': distributions(current)}:
        raise RollingContinuityRefused('RETAINED_ECONOMIC_EVENT_CHANGED')
    return digest(evidence)


def _provider_assets(conn, refs):
    """Recover published provider UUIDs without consulting today's broker."""
    return merger_provider_assets(conn, refs)


def _pending_selected_action(*, prior, previous, current, cursor, session):
    """Ask orchestration to reobserve only a source-visible selected gap."""
    if (previous.manifest.provider != 'ALPACA_OPENFIGI'
            or current.manifest.provider != 'ALPACA_OPENFIGI'):
        return
    selected = set((prior.median5 or {}).get('selected', ()))
    owned = merger_owned_security_ids(prior)
    converted = {row.old_security_id for row in current.merger_conversions}
    for sid in sorted(selected - owned - converted):
        former = previous.resolver.ticker_for_security(sid, cursor)
        if former is None or previous.resolver.resolve(former, cursor) != sid:
            continue
        current_name = current.resolver.ticker_for_security(sid, session)
        if current_name is None or current.resolver.resolve(current_name, session) != sid:
            raise MergerActionPending(session, sid)


def _merger_bridges(conn, *, prior, previous, current, cursor, session):
    """Read prior published anchors only for source-proven controller exits."""
    from sentinel.core.rolling_continuity import RollingContinuityRefused

    selected = set((prior.median5 or {}).get('selected', ()))
    owned = merger_owned_security_ids(prior)
    conversions = [row for row in current.merger_conversions
                   if row.old_security_id in selected or row.old_security_id in owned]
    if not conversions:
        return {}, ()
    if any(row.old_security_id in owned for row in conversions):
        raise RollingContinuityRefused('OWNED_MERGER_CONVERSION_UNSUPPORTED')
    if previous.manifest.provider != 'ALPACA_OPENFIGI' or str(previous.manifest.window.end) != cursor:
        raise RollingContinuityRefused('MERGER_PRIOR_PUBLICATION_MISMATCH')
    prior_assets = _provider_assets(conn, previous)
    current_assets = _provider_assets(conn, current)
    for row in conversions:
        sid = row.old_security_id
        if (row.effective_session != session
                or row.origin_snapshot_id != previous.manifest.snapshot_id
                or prior_assets.get(row.old_symbol) != row.old_provider_asset_id
                or previous.resolver.resolve(row.old_symbol, cursor) != sid):
            raise RollingContinuityRefused('MERGER_SOURCE_IDENTITY_MISMATCH: ' + sid)
        successor_provider = current_assets.get(row.successor_symbol)
        successor_id = current.resolver.resolve(row.successor_symbol, session)
        if successor_provider is None and successor_id is None:
            raise RollingContinuityRefused('MERGER_SUCCESSOR_CURRENT_CLOSE_REQUIRED: ' + sid)
        if (successor_provider != row.successor_provider_asset_id
                or successor_id != row.successor_security_id):
            raise RollingContinuityRefused('MERGER_SOURCE_IDENTITY_MISMATCH: ' + sid)
    rolling_store.verify_content(conn, previous.candidate_id)
    bridges = {}
    for row in conversions:
        sid = row.old_security_id
        series = prior.feed.get('series', {}).get(sid, {})
        anchor = series.get('signal_basis_anchor')
        if not isinstance(anchor, (list, tuple)) or len(anchor) != 3 or anchor[0] != cursor:
            raise RollingContinuityRefused('MERGER_PRIOR_SIGNAL_ANCHOR_REQUIRED: ' + sid)
        rows = conn.execute(candidate_query(conn,
            'SELECT session,security_id,ticker,close_unadjusted,close_signal '
            'FROM sentinel_snapshot_bars WHERE candidate_id=%s AND security_id=%s AND session=%s'),
            (previous.candidate_id, sid, cursor)).fetchall()
        if len(rows) != 1:
            raise RollingContinuityRefused('MERGER_PRIOR_PUBLISHED_ANCHOR_REQUIRED: ' + sid)
        day, observed_sid, ticker, raw, signal = rows[0]
        try:
            retained_raw, retained_signal = float(anchor[1]), float(anchor[2])
            published_raw, published_signal = float(raw), float(signal)
            multiplier = float(series.get('signal_basis_multiplier', 1.0))
        except (TypeError, ValueError, OverflowError):
            raise RollingContinuityRefused('MERGER_PRIOR_SIGNAL_ANCHOR_INVALID: ' + sid) from None
        if (str(day) != cursor or observed_sid != sid or ticker != row.old_symbol
                or not all(math.isfinite(value) and value > 0 for value in (
                    retained_raw, retained_signal, published_raw, published_signal, multiplier))
                or published_raw != retained_raw
                or published_signal * multiplier != retained_signal):
            raise RollingContinuityRefused('MERGER_PRIOR_SIGNAL_ANCHOR_CHANGED: ' + sid)
        bridges[sid] = merger_anchor_bar(cursor, sid, ticker, published_raw, published_signal)
    return bridges, tuple(conversions)


def _merger_terminals(*, conversions, prices, metadata, session):
    from sentinel.core.rolling_continuity import RollingContinuityRefused

    bars = {bar.security_id: bar for bar in prices.bars}
    result = []
    for row in conversions:
        sid, successor = row.old_security_id, row.successor_security_id
        bar = bars.get(successor)
        meta = metadata.get(successor)
        if (bar is None or meta is None or bar.session != session
                or bar.ticker != row.successor_symbol
                or bar.raw_close is None or not math.isfinite(bar.raw_close)
                or bar.raw_close <= 0):
            raise RollingContinuityRefused('MERGER_SUCCESSOR_CURRENT_CLOSE_REQUIRED: ' + sid)
        issuer = meta.issuer_key()[0] or 'S:' + successor
        terms = merger_terminal_terms(row, session=session, issuer=issuer)
        if not terms.completeness(0)[0]:
            raise RollingContinuityRefused('MERGER_TERMS_INCOMPLETE: ' + sid)
        result.append(terms)
    return tuple(result)


def prepare(conn, *, prior, previous_binding, publication, binding):
    from sentinel.core.rolling_continuity import DailyInputs, RollingContinuityRefused
    cursor, session = prior.last_processed_session, publication.window_end
    if not cursor or session != calendar.next_session(cursor):
        raise RollingContinuityRefused('ADJACENT_SOURCE_FINAL_SESSION_REQUIRED')
    refs = SnapshotReferences(conn, candidate_id=binding['candidate_id'], snapshot_id=binding['snapshot_id'])
    previous = SnapshotReferences(conn, candidate_id=previous_binding['candidate_id'],
                                  snapshot_id=previous_binding['snapshot_id'])
    if not refs.current_window or not previous.current_window:
        raise RollingContinuityRefused('CURRENT_WINDOW_PUBLICATION_REQUIRED')
    rolling_store.verify_content(conn, refs.candidate_id)
    reader = RollingPriceReader(conn, candidate_id=refs.candidate_id, snapshot_id=refs.manifest.snapshot_id)
    reader.require_checkpoint_window(prior)
    live = window_features.protected(prior)
    _pending_selected_action(prior=prior, previous=previous, current=refs,
                             cursor=cursor, session=session)
    bridges, conversions = _merger_bridges(
        conn, prior=prior, previous=previous, current=refs, cursor=cursor, session=session)
    anchors = {}
    for sid in sorted(live):
        anchor = prior.feed.get('series', {}).get(sid, {}).get('signal_basis_anchor')
        if not anchor:
            raise RollingContinuityRefused('LIVE_SIGNAL_ANCHOR_REQUIRED: '+sid)
        if sid not in bridges:
            anchors[sid] = anchor[0]
    try:
        prices = reader.prices(session=session, spy_sessions=254, anchor_sessions=anchors)
    except RuntimeError as exc:
        from sentinel.core.rolling_reader import RollingReaderRefused
        if (isinstance(exc, RollingReaderRefused) and str(exc) == 'LIVE_SIGNAL_ANCHOR_MISSING'
                and refs.manifest.provider == 'ALPACA_OPENFIGI'):
            from sentinel.rolling_reconstruction_evidence import InputsUnavailable
            raise InputsUnavailable('HELD_ECONOMIC_INPUT_PENDING:' + session) from exc
        raise
    economics = protected_economics(conn, previous=previous, current=refs, live=live,
        start=str(refs.manifest.window.start), cursor=cursor)
    from sentinel.core.cash_distributions import Inputs, observations
    pending_cash = list(getattr(refs, 'pending_cash', []))
    knowledge, floors = [], []
    cash_observations = observations(previous, refs, cursor=cursor, pending=pending_cash,
        retained=(prior.last_evidence or {}).get('cash_distributions'), knowledge=knowledge, floors=floors)
    cash = Inputs(prior_state_sha256=prior.state_hash, publication_version=publication.version,
        session=session, observations=cash_observations,
        pending=pending_cash,
        source_observations=knowledge, legacy_floors=floors).model_dump(mode='json', by_alias=True)
    meta, sectors = refs.current_metadata()
    features = window_features.load(conn, prior=prior, refs=refs, publication=publication)
    terminals = refs.terminals(start=session, end=session)
    merger_events = _merger_terminals(
        conversions=conversions, prices=prices, metadata=meta, session=session)
    if {event.security_id for event in terminals.events} & {event.security_id for event in merger_events}:
        raise RollingContinuityRefused('MERGER_TERMINAL_CONFLICT')
    material = DailyInputs(session, prices.bars, meta, sectors, prices.benchmarks,
        tuple(terminals.events) + merger_events, refs.distributions(session=session),
        window_features=features.model_dump(mode='json', by_alias=True), cash_distributions=cash)
    proof = CurrentWindowProof(prior_version=prior.data_version,
        publication_version=publication.version, prior_session=cursor, session=session,
        prior_state_sha256=prior.state_hash, snapshot_sha256=refs.manifest.snapshot_id,
        features_sha256=features.sha256, protected_economics_sha256=economics)
    return material, {**prices.signal_basis_anchors, **bridges}, proof.model_dump(by_alias=True)
