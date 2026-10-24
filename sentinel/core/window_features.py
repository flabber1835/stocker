"""Caller-owned storage adapter for the pure current-window input compiler."""
from sentinel.feed.normalized_layout import candidate_query
from sentinel.feed import calendar, rolling_store, store
from sentinel.feed.rolling_contract import CanonicalBar
from sentinel.core.window_material import Signal, WindowFeatures, protected, install, compile_rows


def load(conn, *, prior, refs, publication, session=None):
    """Execute one identity-ordered stream; the pure compiler owns interpretation."""
    session = session or publication.window_end
    axis = calendar.previous_sessions(session, 300)
    meta, _ = refs.current_metadata(session=session)
    columns = rolling_store.BAR_COLUMNS
    query = candidate_query(conn,
        f"SELECT {','.join(columns)} FROM sentinel_snapshot_bars WHERE candidate_id=%s "
        'AND session BETWEEN %s AND %s ORDER BY security_id COLLATE "C",session')
    with store.streaming_cursor(conn, query, (refs.candidate_id, axis[0], axis[-1])) as cursor:
        rows = (CanonicalBar.model_validate(dict(zip(columns, row))) for row in cursor)
        return compile_rows(prior=prior,manifest=refs.manifest,metadata=meta,
            resolve_identity=refs.resolver.resolve,publication_version=publication.version,
            session=session,rows=rows)
