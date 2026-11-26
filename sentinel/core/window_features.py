"""Caller-owned storage adapter for the pure current-window input compiler."""
from contextlib import closing
from sentinel.feed import calendar, rolling_store
from sentinel.core.window_material import Signal, WindowFeatures, protected, install, compile_rows


def load(conn, *, prior, refs, publication, session=None):
    """Read in physical session order without sorting the entire expanded view."""
    session = session or publication.window_end
    axis = calendar.previous_sessions(session, 300)
    meta, _ = refs.current_metadata(session=session)
    with closing(rolling_store.read_bars(conn, refs.candidate_id, start=axis[0], end=axis[-1])) as rows:
        return compile_rows(prior=prior,manifest=refs.manifest,metadata=meta,
            resolve_identity=refs.resolver.resolve,publication_version=publication.version,
            session=session,rows=rows)
