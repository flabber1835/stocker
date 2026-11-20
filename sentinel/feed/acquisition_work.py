"""Bounded historical capture reads and scheduling."""
from __future__ import annotations

import hashlib
import json
import os
import time

from sentinel.archive_identifiers import FEED
from sentinel.feed import provider_budget, archive_tables, acquisition_limits as limits
from sentinel.feed.provider_budget import cache_root, remaining

SLICE_SECONDS = 600


def pause(seconds, *, sleep=None):
    left = remaining()
    if left is not None and seconds >= left:
        raise archive_tables.RetryDeferred(seconds)
    (sleep or time.sleep)(seconds)


def budget(seconds=None):
    return provider_budget.budget(SLICE_SECONDS if seconds is None else seconds)


def file_key(snapshot):
    return hashlib.sha256(json.dumps({
        "provider": FEED['ARCHIVE_CACHE_PROVIDER'], "table": snapshot.table,
        "params": dict(snapshot.params), "snapshot": snapshot.snapshot.isoformat(),
        "refreshed": snapshot.refreshed.isoformat(),
    }, sort_keys=True).encode()).hexdigest()


def read_cached(snapshot):
    path = cache_root() / (file_key(snapshot) + ".zip")
    try:
        with path.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            limits.check("ZIP_BYTES", size, limits.ZIP_BYTES)
            blob = stream.read(size + 1)
            limits.check("ZIP_BYTES", len(blob), limits.ZIP_BYTES)
        with path.with_suffix(".sha256").open("rb") as stream:
            expected = stream.read(65)
    except FileNotFoundError:
        return None
    return blob if hashlib.sha256(blob).hexdigest().encode("ascii") == expected else None


def retry_source(operation, *, rollback, target_session, wait_seconds=3600,
                 sleep=None, monotonic=None):
    """Keep one explicit target while retrying only reviewed source availability."""
    from sentinel.feed import progress
    from sentinel.feed.authority import VendorPublicationUnstable
    sleep = sleep or time.sleep
    monotonic = monotonic or time.monotonic
    deadline = monotonic() + wait_seconds
    while True:
        try:
            return operation()
        except (archive_tables.RetryDeferred, VendorPublicationUnstable) as exc:
            rollback()
            delay = max(1, getattr(exc, "delay", 30))
            left = deadline - monotonic()
            if delay >= left:
                raise
            progress.emit("source_preflight", "working", date_to=target_session,
                          reason="SOURCE_RETRY_WAIT", retry_seconds=int(delay),
                          remaining_seconds=int(left))
            sleep(delay)
