"""Authenticated publication-version dispatch for broker-free operational readers."""
from contextlib import contextmanager, ExitStack
from datetime import datetime

from sentinel.feed import publication, operational_snapshot as snapshots
from sentinel.feed import rolling_go_inputs, store, readiness as legacy_readiness
from sentinel.core.decision import publication_fingerprint

def is_rolling(pub):
    return rolling_go_inputs.is_rolling(pub)


def current(conn):
    try:
        return publication.current(conn)
    except publication.CorpusIncoherent as exc:
        if str(exc) != "ROLLING_SNAPSHOT_REQUIRES_VERSIONED_READER":
            raise
    pub = snapshots._current(conn)
    snapshots._bound(conn, pub)
    return pub


def require_current(conn):
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
    with ExitStack() as stack:
        snapshot_reader = False
        try:
            pub = stack.enter_context(publication.pinned(conn, commit=commit))
        except publication.CorpusIncoherent as exc:
            if str(exc) != "ROLLING_SNAPSHOT_REQUIRES_VERSIONED_READER":
                raise
            snapshot_reader = True
        if snapshot_reader:
            pub, _ = stack.enter_context(snapshots.pinned(conn, commit=commit))
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
            report.add("rolling publication binding", legacy_readiness.PASS,
                       publication_fingerprint(pub))
            return report
        return legacy_readiness.check_readiness(conn, today=today)


def status_snapshot(conn):
    """Cheap publication-bound status; never rescan the window in a page load."""
    if current(conn) is None:
        return store.latest_visible_session(conn), legacy_readiness.latest_snapshot(conn)
    with pinned(conn, commit=False) as pub:
        snapshot = legacy_readiness.latest_snapshot(conn)
        return frontier(conn, pub), snapshot if snapshot_matches(pub, snapshot) else None


def snapshot_matches(pub, snapshot):
    if not is_rolling(pub):
        return True
    return snapshot is not None and any(
        item.get("name") == "rolling publication binding"
        and item.get("status") == legacy_readiness.PASS
        and item.get("detail") == publication_fingerprint(pub)
        for item in snapshot.checks)
