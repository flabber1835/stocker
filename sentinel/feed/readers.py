"""Authenticated publication-version dispatch for broker-free operational readers."""
from contextlib import contextmanager
from datetime import datetime

from sentinel.feed import publication, operational_snapshot as snapshots
from sentinel.feed import rolling_go_inputs, store, readiness as legacy_readiness
from sentinel.core.decision import publication_fingerprint

def is_rolling(pub):
    return rolling_go_inputs.is_rolling(pub)


def current(conn):
    from sentinel.feed import readiness_scope
    readiness_scope.require(conn)
    try:
        return publication.current(conn)
    except publication.CorpusIncoherent as exc:
        if str(exc) != "ROLLING_SNAPSHOT_REQUIRES_VERSIONED_READER":
            raise
    pub = snapshots._current(conn)
    snapshots._bound(conn, pub)
    return pub


def require_current(conn):
    from sentinel.feed import readiness_scope
    readiness_scope.require(conn)
    # Dispatch only the authenticated publication's explicit reader-version
    # refusal. Integrity, receipt and all other legacy failures remain failures.
    try:
        return publication.require_current(conn)
    except publication.CorpusIncoherent as exc:
        if str(exc) != "ROLLING_SNAPSHOT_REQUIRES_VERSIONED_READER":
            raise
    pub = snapshots._current(conn)
    snapshots._bound(conn, pub)
    return pub


@contextmanager
def pinned(conn, *, commit=True):
    with publication._core.pinned(conn, commit=commit) as pub:
        publication._validate_publication(conn, pub, allow_snapshot=True)
        if is_rolling(pub):
            snapshots._bound(conn, pub)
        from sentinel.feed import readiness_scope
        with readiness_scope.pinned(conn, pub):
            yield pub


def frontier(conn, pub=None):
    pub = current(conn) if pub is None else pub
    return pub.window_end if is_rolling(pub) else store.latest_visible_session(conn)


def readiness(conn, *, today=None):
    if current(conn) is None:
        return legacy_readiness.check_readiness(conn, today=today)
    with pinned(conn, commit=False) as pub:
        if is_rolling(pub):
            now = None if today is None else datetime.fromisoformat(today)
            report = rolling_go_inputs.assessment(conn, pub, now=now)
            return bound_readiness(pub, report)
        return legacy_readiness.check_readiness(conn, today=today)


def bound_readiness(pub, report):
    """Copy a measured rolling report with its exact display-cache binding."""
    if not is_rolling(pub):
        raise ValueError("rolling readiness requires a rolling publication")
    bound = legacy_readiness.Readiness(checks=list(report.checks))
    bound.add("rolling publication binding", legacy_readiness.PASS,
              publication_fingerprint(pub))
    return bound


def status_snapshot(conn, *, include_publication=False):
    """Cheap publication-bound status; never rescan the window in a page load."""
    if current(conn) is None:
        result = store.latest_visible_session(conn), legacy_readiness.latest_snapshot(conn)
        return (*result, None) if include_publication else result
    with pinned(conn, commit=False) as pub:
        snapshot = legacy_readiness.latest_snapshot(conn)
        result = frontier(conn, pub), snapshot if snapshot_matches(pub, snapshot) else None
        return (*result, pub.version) if include_publication else result


def display_status_snapshot(conn, *, include_publication=False):
    """One read-only rolling metadata frame; never financial data admission.

    Caller owns a fresh transaction and its rollback. Legacy/default readers
    retain their corpus pin; rolling display reads only authenticated immutable
    publication metadata and the exactly matching measured verdict.
    """
    if conn.autocommit:
        raise ValueError('DISPLAY_STATUS_REQUIRES_CALLER_TRANSACTION')
    with conn.cursor() as cur:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    pub = _display_current(conn)
    if pub is None or not is_rolling(pub):
        return status_snapshot(conn, include_publication=include_publication)
    snapshot = legacy_readiness.latest_snapshot(conn)
    result = pub.window_end, snapshot if snapshot_matches(pub, snapshot) else None
    return (*result, pub.version) if include_publication else result


def _display_current(conn):
    from sentinel.feed import readiness_scope
    readiness_scope.require(conn)
    try:
        return publication.current(conn)
    except publication.CorpusIncoherent as exc:
        if str(exc) != 'ROLLING_SNAPSHOT_REQUIRES_VERSIONED_READER':
            raise
    pub = snapshots._current(conn)
    snapshots.display_binding(conn, pub)
    return pub


def snapshot_matches(pub, snapshot):
    if not is_rolling(pub):
        return True
    return snapshot is not None and any(
        item.get("name") == "rolling publication binding"
        and item.get("status") == legacy_readiness.PASS
        and item.get("detail") == publication_fingerprint(pub)
        for item in snapshot.checks)
