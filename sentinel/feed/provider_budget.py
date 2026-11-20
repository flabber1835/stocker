"""Monotonic acquisition units and isolated, restart-safe provider cooldowns."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import time


_deadline = ContextVar("source_acquisition_deadline", default=None)
_COOLDOWNS = "provider-rate-limits.sqlite"


def remaining():
    end = _deadline.get()
    return None if end is None else max(0.0, end - time.monotonic())


@contextmanager
def budget(seconds):
    end = time.monotonic() + seconds
    outer = _deadline.get()
    token = _deadline.set(end if outer is None else min(end, outer))
    try:
        yield
    finally:
        _deadline.reset(token)


def cache_root():
    root = Path(os.environ.get("SENTINEL_STATE_DIR", tempfile.gettempdir())) / "source-cache-v1"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _connection():
    left = remaining()
    conn = sqlite3.connect(cache_root() / _COOLDOWNS, timeout=5 if left is None else min(left, 5))
    conn.execute("CREATE TABLE IF NOT EXISTS cooldown (provider TEXT PRIMARY KEY, until REAL)")
    return conn


def defer_for(seconds, *, provider):
    key = hashlib.sha256(provider.encode()).hexdigest()
    conn = _connection()
    try:
        with conn:
            conn.execute("INSERT INTO cooldown VALUES (?,?) ON CONFLICT(provider) "
                         "DO UPDATE SET until=MAX(until,excluded.until)",
                         (key, time.time() + seconds))
    finally:
        conn.close()


def cooldown_remaining(provider):
    if not (cache_root() / _COOLDOWNS).exists():
        return 0
    key = hashlib.sha256(provider.encode()).hexdigest()
    conn = _connection()
    try:
        row = conn.execute("SELECT until FROM cooldown WHERE provider=?", (key,)).fetchone()
    finally:
        conn.close()
    return max(0, row[0] - time.time()) if row else 0
