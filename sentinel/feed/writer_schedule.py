"""Give an owned rolling writer one finite place in the corpus lock queue."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import math
import os
import time

from sentinel import shadow_budget
from sentinel.feed import acquisition_work, rolling_jobs as jobs
from sentinel.feed.publication import CORPUS_LOCK_KEY, CorpusLockUnavailable

MAX_DRAIN_SECONDS = 330
_DISCARDED = '_sentinel_corpus_writer_session_discarded'


def connection_discarded(exc):
    """The outer publisher must not touch an uncertain/disposed session."""
    return getattr(exc, _DISCARDED, False) is True


def _sqlstate(exc):
    return getattr(exc, 'sqlstate', None) or getattr(exc, 'pgcode', None)


def _note(primary, stage, failure):
    state = _sqlstate(failure)
    suffix = (f' SQLSTATE={state}' if isinstance(state, str) and len(state) == 5
              and state.isascii() and state.isalnum() else '')
    primary.add_note(f'corpus writer {stage} failed: {type(failure).__name__}{suffix}')


def _dispose(conn, primary):
    setattr(primary, _DISCARDED, True)
    try:
        conn.close()
    except BaseException as failure:
        _note(primary, 'session disposal', failure)


def _interrupt(exc):
    return (isinstance(exc, (KeyboardInterrupt, SystemExit))
            or _sqlstate(exc) == '57014')


def _external_remaining():
    left = acquisition_work.remaining()
    raw = os.environ.get(shadow_budget.DEADLINE_ENV)
    if raw is not None:
        deadline = datetime.fromisoformat(raw)
        if deadline.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError('shadow advance deadline must be explicit UTC')
        seconds = (deadline - shadow_budget.now()).total_seconds()
        left = seconds if left is None else min(left, seconds)
    return left


def _milliseconds(seconds):
    if not math.isfinite(seconds) or seconds <= 0:
        raise jobs.JobDeadlineExceeded('corpus writer waiting authority exhausted')
    value = math.floor(seconds * 1000)
    if value < 1:
        raise jobs.JobDeadlineExceeded('corpus writer waiting authority exhausted')
    return value


def _release(conn):
    with conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_unlock(%s)', (CORPUS_LOCK_KEY,))
        if not bool(cur.fetchone()[0]):
            raise RuntimeError('owned corpus writer turn was not held')
    conn.commit()


def _failed_release(conn, primary):
    if _interrupt(primary):
        _dispose(conn, primary)
        return
    try:
        conn.rollback()
        _release(conn)
    except BaseException as failure:
        _note(primary, 'exception cleanup', failure)
        _dispose(conn, primary)


@contextmanager
def turn(conn, lease):
    """Queue before the existing writer context, without renewing authority.

    New readers still use their immediate shared try-lock. PostgreSQL's queue
    excludes those independent contenders while existing readers finish. The
    original writer context acquires this session lock reentrantly; each scope
    releases only its own acquisition. This scope does not replace its mutation
    guard, CAS, immutable validation or final job ownership checks.
    """
    sampled = time.monotonic()
    committing = False
    try:
        owned = jobs._owned(conn, lease)
        seconds = min(MAX_DRAIN_SECONDS, (owned[2] - owned[10]).total_seconds(),
                      (owned[3] - owned[10]).total_seconds())
        external = _external_remaining()
        if external is not None:
            seconds = min(seconds, external)
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('lock_timeout'),"
                        " EXTRACT(EPOCH FROM current_setting('lock_timeout')::interval)")
            original_timeout, original_seconds = cur.fetchone()
        if float(original_seconds) > 0:
            seconds = min(seconds, float(original_seconds))
        _milliseconds(seconds - (time.monotonic() - sampled))
        # _owned takes FOR UPDATE. Release its row lock and any transaction pin
        # before entering the corpus queue; the session pin, if any, is unchanged.
        committing = True
        conn.commit()
    except BaseException as primary:
        if committing or _interrupt(primary):
            _dispose(conn, primary)
        else:
            try:
                conn.rollback()
            except BaseException as failure:
                _note(primary, 'preflight rollback', failure)
                _dispose(conn, primary)
        raise

    acquired = False
    try:
        wait_ms = _milliseconds(seconds - (time.monotonic() - sampled))
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('lock_timeout', %s, true)", (f'{wait_ms}ms',))
            cur.execute('SELECT pg_advisory_lock(%s)', (CORPUS_LOCK_KEY,))
            # Consume the acknowledgement: a lost result leaves session-level
            # ownership unknown even if the server completed acquisition.
            if cur.fetchone() is None:
                raise RuntimeError('corpus writer acquisition acknowledgement is absent')
            acquired = True
            cur.execute("SELECT set_config('lock_timeout', %s, true)", (original_timeout,))
        jobs._owned(conn, lease)
        external = _external_remaining()
        if external is not None:
            _milliseconds(external)
        conn.commit()
    except BaseException as primary:
        if not acquired:
            if _sqlstate(primary) == '55P03':
                timeout = CorpusLockUnavailable('bounded corpus writer turn timed out')
                try:
                    # SET LOCAL is undone with the failed acquisition transaction.
                    conn.rollback()
                except BaseException as failure:
                    _note(timeout, 'timeout rollback', failure)
                    _dispose(conn, timeout)
                raise timeout from primary
            _dispose(conn, primary)
        else:
            # A failed commit is uncertain even if its server acknowledgement
            # was lost. Dispose rather than issuing more transactional work.
            if isinstance(primary, jobs.JobRefused):
                _failed_release(conn, primary)
            else:
                _dispose(conn, primary)
        raise

    try:
        yield
    except BaseException as primary:
        _failed_release(conn, primary)
        raise
    else:
        try:
            _release(conn)
        except BaseException as primary:
            _dispose(conn, primary)
            raise
