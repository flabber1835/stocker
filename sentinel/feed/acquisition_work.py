"""Bounded network work and restart-safe, non-authoritative source cache."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from sentinel.feed import sharadar

SLICE_SECONDS = 600
_DEADLINE = ContextVar("source_acquisition_deadline", default=None)


def cache_root():
    root = Path(os.environ.get("SENTINEL_STATE_DIR", tempfile.gettempdir())) / "source-cache-v1"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _cooldown_connection():
    conn = sqlite3.connect(cache_root() / "cooldown.sqlite", timeout=5)
    conn.execute("CREATE TABLE IF NOT EXISTS cooldown (provider TEXT PRIMARY KEY, until REAL)")
    return conn


def defer_for(seconds):
    # Never persist an authenticated URL. Endpoint identity is sufficient here.
    key = hashlib.sha256(sharadar.NDL_BASE.encode()).hexdigest()
    conn = _cooldown_connection()
    try:
        with conn:
            conn.execute("INSERT INTO cooldown VALUES (?,?) ON CONFLICT(provider) "
                         "DO UPDATE SET until=MAX(until,excluded.until)",
                         (key, time.time() + seconds))
    finally:
        conn.close()


def check_cooldown():
    key = hashlib.sha256(sharadar.NDL_BASE.encode()).hexdigest()
    conn = _cooldown_connection()
    try:
        row = conn.execute("SELECT until FROM cooldown WHERE provider=?", (key,)).fetchone()
    finally:
        conn.close()
    if row and row[0] > time.time():
        raise sharadar.SharadarRetryDeferred(row[0] - time.time())


def remaining():
    deadline = _DEADLINE.get()
    return None if deadline is None else max(0.0, deadline - time.monotonic())


def request_options():
    left = remaining()
    if left is None:
        return {}
    if left <= 0:
        raise sharadar.SharadarRetryDeferred(30)
    return {"timeout": min(sharadar.FETCH_TIMEOUT_SECS, left)}


def pause(seconds, *, sleep=None):
    left = remaining()
    if left is not None and seconds >= left:
        raise sharadar.SharadarRetryDeferred(seconds)
    (sleep or time.sleep)(seconds)


@contextmanager
def budget(seconds=None):
    check_cooldown()
    deadline = time.monotonic() + (SLICE_SECONDS if seconds is None else seconds)
    if _DEADLINE.get() is not None:
        deadline = min(deadline, _DEADLINE.get())
    token = _DEADLINE.set(deadline)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def file_key(snapshot):
    return hashlib.sha256(json.dumps({
        "provider": sharadar.NDL_BASE, "table": snapshot.table,
        "params": dict(snapshot.params), "snapshot": snapshot.snapshot.isoformat(),
        "refreshed": snapshot.refreshed.isoformat(),
    }, sort_keys=True).encode()).hexdigest()


@contextmanager
def cached_file(snapshot):
    """Serialize same-file downloads without holding the corpus writer lock."""
    import fcntl
    root = cache_root()
    key = file_key(snapshot)
    deadline = time.monotonic() + SLICE_SECONDS
    # Fixed lock stripes do not accumulate per-generation lock files.
    with (root / (key[:2] + ".lock")).open("a+b") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise sharadar.SharadarRetryDeferred(30) from None
                pause(1)
        try:
            yield root / (key + ".zip")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def read_cached(path):
    try:
        blob = path.read_bytes()
        expected = path.with_suffix(".sha256").read_text(encoding="ascii")
    except FileNotFoundError:
        return None
    return blob if hashlib.sha256(blob).hexdigest() == expected else None


def _atomic_write(path, blob):
    fd, name = tempfile.mkstemp(prefix=".partial-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(blob)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def save_cached(path, blob):
    _atomic_write(path, blob)
    _atomic_write(path.with_suffix(".sha256"), hashlib.sha256(blob).hexdigest().encode("ascii"))
    # Only cache artifacts are pruned; open/locked readers remain valid on Linux.
    ages = []
    for item in path.parent.glob("*.zip"):
        try:
            ages.append((item.stat().st_mtime, item))
        except FileNotFoundError:
            pass
    files = [item for _, item in sorted(ages, reverse=True)]
    for old in files[64:]:
        old.unlink(missing_ok=True)
        old.with_suffix(".sha256").unlink(missing_ok=True)
    for partial in path.parent.glob(".partial-*"):
        try:
            if time.time() - partial.stat().st_mtime > 86400:
                partial.unlink(missing_ok=True)
        except FileNotFoundError:
            pass


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
        except (sharadar.SharadarRetryDeferred, VendorPublicationUnstable) as exc:
            rollback()
            delay = max(1, getattr(exc, "delay", 30))
            left = deadline - monotonic()
            if delay >= left:
                raise
            progress.emit("source_preflight", "working", date_to=target_session,
                          reason="SOURCE_RETRY_WAIT", retry_seconds=int(delay),
                          remaining_seconds=int(left))
            sleep(delay)
