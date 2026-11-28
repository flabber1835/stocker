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
    pub = snapshots._current(conn)
    if pub is not None and "rolling_snapshot" in pub.evidence:
        snapshots._bound(conn, pub)
    return pub


def require_current(conn):
    pub = current(conn)
    if pub is None:
        raise publication.NoPublishedVersion("no corpus generation has been published")
    return pub


@contextmanager
def pinned(conn, *, commit=True, reuse_owned=False):
    from sentinel.feed import readiness_scope
    if reuse_owned and not commit:
        owned = readiness_scope.owned_publication(conn)
        if owned is not None:
            yield owned
            return
    with pinned_binding(conn, commit=commit) as (pub, _):
        yield pub


@contextmanager
def pinned_binding(conn, *, commit):
    """Expose the canonical rolling binding and manifest while their publication is pinned."""
    from sentinel.feed import readiness_scope

    with publication._core.pinned(conn, commit=commit) as pub:
        publication._validate_publication(conn, pub, allow_snapshot=True)
        bound = snapshots._bound_and_manifest(conn, pub) if is_rolling(pub) else None
        with readiness_scope.pinned(conn, pub):
            yield pub, bound


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


def snapshot_matches(pub, snapshot):
    if not is_rolling(pub):
        return True
    return snapshot is not None and any(
        item.get("name") == "rolling publication binding"
        and item.get("status") == legacy_readiness.PASS
        and item.get("detail") == publication_fingerprint(pub)
        for item in snapshot.checks)
