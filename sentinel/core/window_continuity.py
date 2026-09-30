"""Daily feature replacement with continuity of retained economic state."""
from sentinel.core import window_features
from sentinel.core.history import CurrentWindowProof
from sentinel.core.rolling_inputs import SnapshotReferences
from sentinel.core.rolling_reader import RollingPriceReader
from sentinel.feed import calendar, rolling_store
from sentinel.feed.rolling_contract import canonical_json, digest


def protected_economics(conn, *, previous, current, live, start, cursor):
    """Past cash/share events for retained identities cannot be applied twice."""
    from sentinel.core.rolling_continuity import RollingContinuityRefused

    def events(refs):
        return sorted(canonical_json(payload) for _, payload, _ in refs.actions
            if start <= payload['date'] <= cursor
            and (refs.resolver.resolve(payload['ticker'], payload['date']) in live
                 or refs.resolver.resolve(payload.get('contraticker') or '', payload['date']) in live))

    def distributions(refs):
        rows = conn.execute('SELECT session,security_id,split_ratio,dividend_per_share '
            'FROM sentinel_snapshot_bars WHERE candidate_id=%s AND session BETWEEN %s AND %s '
            'AND security_id=ANY(%s) AND (split_ratio<>1 OR dividend_per_share<>0) '
            'ORDER BY session,security_id COLLATE "C"',
            (refs.candidate_id, start, cursor, sorted(live))).fetchall()
        return [(str(day), sid, split, cash) for day, sid, split, cash in rows]

    evidence = {'actions': events(previous), 'distributions': distributions(previous)}
    if evidence != {'actions': events(current), 'distributions': distributions(current)}:
        raise RollingContinuityRefused('RETAINED_ECONOMIC_EVENT_CHANGED')
    return digest(evidence)


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
    anchors = {}
    for sid in sorted(live):
        anchor = prior.feed.get('series', {}).get(sid, {}).get('signal_basis_anchor')
        if not anchor:
            raise RollingContinuityRefused('LIVE_SIGNAL_ANCHOR_REQUIRED: '+sid)
        anchors[sid] = anchor[0]
    prices = reader.prices(session=session, spy_sessions=254, anchor_sessions=anchors)
    economics = protected_economics(conn, previous=previous, current=refs, live=live,
        start=str(refs.manifest.window.start), cursor=cursor)
    meta, sectors = refs.current_metadata()
    features = window_features.load(conn, prior=prior, refs=refs, publication=publication)
    terminals = refs.terminals(start=session, end=session)
    material = DailyInputs(session, prices.bars, meta, sectors, prices.benchmarks,
        tuple(terminals.events), refs.distributions(session=session),
        window_features=features.model_dump(mode='json', by_alias=True))
    proof = CurrentWindowProof(prior_version=prior.data_version,
        publication_version=publication.version, prior_session=cursor, session=session,
        prior_state_sha256=prior.state_hash, snapshot_sha256=refs.manifest.snapshot_id,
        features_sha256=features.sha256, protected_economics_sha256=economics)
    return material, prices.signal_basis_anchors, proof.model_dump(by_alias=True)
