"""Single independently owned broker-free verifier, in the common image."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import signal
from threading import BoundedSemaphore, Event
import time
import uuid

from psycopg.errors import LockNotAvailable, QueryCanceled

from sentinel.panel import authority_reader as financial, observer_codec, read_projection
from sentinel.panel import operational_schema as schema
from sentinel.panel.verification_monitor import paper_unknown

HEARTBEAT = Path('/tmp/sentinel-verification-heartbeat')
OWNER_LOCK = (1_397_050_964, 1_448_748_626)
OWNER_SECONDS = 610
RETRY_SECONDS = 20
RETRY_POLL_SECONDS = .5


def _identity_key(_database_url, _include_paper, evidence):
    return evidence


def _observe_once(database_url, include_paper, expected_key):
    if read_projection.subject_for(database_url, include_paper) != expected_key:
        raise ValueError('verification subject changed before observation')
    from sentinel.panel import sources
    if not include_paper:
        rows, details, history, errors = sources._dual_authority_rows(database_url,
            now=datetime.now(timezone.utc), include_paper=False, propagate_corpus_lock=True)
        if details or history:
            raise ValueError('unexpected shadow observation shape')
    else:
        from sentinel import informational_paper_mirror
        from sentinel.feed import readers, store
        conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=sources.STATEMENT_TIMEOUT_MS)
        try:
            conn.execute('BEGIN TRANSACTION READ ONLY')
            rows = [sources._dual_paper_row(conn, informational_paper_mirror=informational_paper_mirror,
                                            publication=readers, feed_store=store)]
            errors = []
        finally:
            conn.rollback(); conn.close()
    result = observer_codec.pack(rows, errors, observed_at=datetime.now(timezone.utc))
    if read_projection.subject_for(database_url, include_paper) != expected_key:
        raise ValueError('verification subject changed during observation')
    return result


def observe(database_url, include_paper, expected_key):
    from sentinel.feed.publication import CorpusLockUnavailable
    from sentinel.panel.shadow_source_wait import observe_preparation
    preparation = observe_preparation(database_url, include_paper, expected_key)
    if preparation is not None:
        return preparation
    try:
        return financial.retry_corpus_lock(lambda: _observe_once(database_url, include_paper, expected_key))
    except CorpusLockUnavailable:
        from sentinel.panel import publication_wait
        result=publication_wait.observe(database_url,include_paper,expected_key)
        if result is None:
            raise
        return result


def snapshot(reader, result, *, scope, now):
    """Preserve original completed or pending clocks, including negative results."""
    with reader.lock:
        key = reader.configuration
        if key is None:
            return None
        if reader.completed is not None:
            rows, errors, observed = reader.completed
            expiry = observed+timedelta(seconds=financial.FRESH_SECONDS)
        else:
            rows, _, _, errors = result
            observed = reader.last_result_at or reader.pending_at
            if observed is None:
                return None
            deadlines = [row.valid_until for row in rows if row.valid_until is not None]
            expiry = min([observed+timedelta(seconds=financial.FRESH_SECONDS), *deadlines])
        if not observed <= now <= expiry:
            return None
        return read_projection.make(scope,key,rows,errors,observed_at=observed,valid_until=expiry)


def _restore_readers(conn, readers, database_url, *, now):
    """Resume current completed display evidence, never another owner's job."""
    previous = {}
    conn.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    try:
        schema.require_schema(conn)
        try:
            facts = read_projection._subject_facts(conn)
        except (ValueError,TypeError,KeyError,OverflowError):
            return previous
        for scope, reader in readers.items():
            try:
                key = read_projection._subject(conn,database_url,scope,facts=facts)
                row = conn.execute(f'SELECT subject_sha256,observed_at,valid_until,envelope,signature FROM {schema.RECEIPTS} WHERE scope=%s',
                                   (scope,)).fetchone()
                if (row is None or row[0] != key or row[1].isoformat() != row[3].get('observed_at')
                        or row[2].isoformat() != row[3].get('valid_until')):
                    continue
                rows, _, _, errors = read_projection.decode(row[3],row[4],
                    current_subject=key,scope=scope,now=now)
                if (row[2] != row[1]+timedelta(seconds=financial.FRESH_SECONDS)
                        or any(item.recovery is not None
                               and item.recovery.phase == 'FINANCIAL_VERIFICATION' for item in rows)):
                    continue
                reader.answer = (key,observer_codec.pack(rows,errors,observed_at=row[1]),None,now)
                previous[scope] = (row[3],row[4])
            except (ValueError,TypeError,KeyError,OverflowError,AttributeError):
                # Absent or malformed display evidence starts ordinary work.
                # No current subject, owner or database failure is repaired.
                continue
    finally:
        conn.rollback()
    return previous


def _drain_readers(readers):
    # Reader already owns finite queue/work/subprocess-reap deadlines. Joining
    # those existing jobs creates no new admission or fresh time allowance.
    for reader in readers.values():
        with reader.lock:
            pending=reader.pending
        if pending is not None:
            pending.join()


def _release_owner(conn, readers):
    _drain_readers(readers)
    conn.rollback()
    conn.close()


def _owner_deadline(started, row):
    expires, database_now = row
    remaining = min(OWNER_SECONDS, (expires-database_now).total_seconds())
    deadline = started+remaining
    if not time.monotonic() < deadline:
        raise ValueError('verifier ownership expired')
    return deadline


def _renew_owner(conn, owner_id, deadline):
    started = time.monotonic()
    if not started < deadline:
        raise ValueError('verifier ownership expired')
    row = conn.execute(
        f'UPDATE {schema.OWNER} SET expires_at=clock_timestamp()+INTERVAL \'610 seconds\' '
        'WHERE id=1 AND owner_id=%s AND expires_at>clock_timestamp() '
        'RETURNING expires_at,clock_timestamp()', (owner_id,)).fetchone()
    if row is None:
        raise ValueError('verifier ownership lost')
    if not time.monotonic() < deadline:
        conn.rollback()
        raise ValueError('verifier ownership expired during renewal')
    renewed = _owner_deadline(started, row)
    conn.commit()
    if not time.monotonic() < deadline:
        raise ValueError('verifier ownership expired during commit')
    return renewed


def _require_iteration_time(deadline):
    if not time.monotonic() < deadline:
        raise TimeoutError('verifier retry or ownership deadline expired')


def _refresh_readers(conn, readers, database_url, owner_id, previous, stopped, deadline):
    for scope, reader in readers.items():
        if stopped.is_set():
            break
        _require_iteration_time(deadline)
        result = reader.read(database_url, include_paper=scope == 'PAPER')
        value = snapshot(reader, result, scope=scope, now=datetime.now(timezone.utc))
        if value is not None and previous.get(scope) != value:
            # Recheck exact subject in the publishing transaction.
            if read_projection.subject(conn, database_url, scope) == value[0]['subject_sha256']:
                _require_iteration_time(deadline)
                read_projection.publish(conn, owner_id=owner_id, value=value[0], signature=value[1])
                conn.commit()
                _require_iteration_time(deadline)
                previous[scope] = value
            else:
                conn.rollback()


def _run_owned_loop(conn, readers, database_url, owner_id, previous, stopped, deadline):
    retry_until = None
    while not stopped.is_set():
        started = time.monotonic()
        _require_iteration_time(min(deadline, retry_until) if retry_until is not None else deadline)
        try:
            deadline = _renew_owner(conn, owner_id, deadline)
            iteration_deadline = min(deadline, retry_until) if retry_until is not None else deadline
            _refresh_readers(conn, readers, database_url, owner_id, previous, stopped, iteration_deadline)
            _require_iteration_time(iteration_deadline)
        except (QueryCanceled, LockNotAvailable):
            conn.rollback()
            # The session lock belongs to this connection. Reconnecting here
            # would silently discard exclusive ownership of admitted work.
            if conn.closed or conn.broken:
                raise
            if retry_until is None:
                retry_until = min(deadline, started+RETRY_SECONDS)
            remaining = retry_until-time.monotonic()
            if remaining <= 0:
                raise
            stopped.wait(min(RETRY_POLL_SECONDS, remaining))
            continue
        retry_until = None
        if not stopped.is_set():
            HEARTBEAT.write_text(datetime.now(timezone.utc).isoformat(), encoding='ascii')
            stopped.wait(15)


def run(*, stopped=None):
    from sentinel.feed import store
    database_url = os.environ.get('SENTINEL_DATABASE_URL','')
    if not database_url or os.environ.get('ALPACA_API_KEY') or os.environ.get('ALPACA_SECRET_KEY'):
        raise ValueError('verifier requires database and no broker credentials')
    stopped = stopped or Event()
    for signum in (signal.SIGTERM,signal.SIGINT):
        signal.signal(signum,lambda *_:stopped.set())
    conn = store.connect(database_url,connect_timeout=3,statement_timeout_ms=3000)
    owner_id = str(uuid.uuid4())
    readers = {}
    try:
        schema.require_schema(conn)
        if not conn.execute('SELECT pg_try_advisory_lock(%s,%s)',OWNER_LOCK).fetchone()[0]:
            raise ValueError('another verifier owns operational projections')
        started = time.monotonic()
        claimed = conn.execute(f'INSERT INTO {schema.OWNER} VALUES (1,%s,clock_timestamp()+INTERVAL \'610 seconds\') '
            'ON CONFLICT (id) DO UPDATE SET owner_id=EXCLUDED.owner_id,expires_at=EXCLUDED.expires_at '
            'RETURNING expires_at,clock_timestamp()', (owner_id,)).fetchone()
        conn.commit()
        deadline = _owner_deadline(started, claimed)
        slot = BoundedSemaphore(1)
        readers = {scope:financial.Reader(evidence_reader=read_projection.subject_for, observer=observe,
            key_factory=_identity_key, expected_keys=read_projection.PAPER_KEYS if scope == 'PAPER' else read_projection.SHADOW_KEYS,
            unknown_factory=paper_unknown if scope == 'PAPER' else None,execution_slot=slot,
            scope_label='paper alignment verification' if scope == 'PAPER' else 'retained portfolio verification')
            for scope in ('SHADOW','PAPER')}
        previous = _restore_readers(conn,readers,database_url,now=datetime.now(timezone.utc))
        _run_owned_loop(conn, readers, database_url, owner_id, previous, stopped, deadline)
    finally:
        _release_owner(conn,readers)
        HEARTBEAT.unlink(missing_ok=True)
    return 0


def health():
    try:
        stamp = datetime.fromisoformat(HEARTBEAT.read_text(encoding='ascii'))
        return 0 if timedelta(0) <= datetime.now(timezone.utc)-stamp <= timedelta(seconds=45) else 1
    except (OSError,ValueError):
        return 1


if __name__ == '__main__':
    import sys
    raise SystemExit(health() if sys.argv[1:] == ['--health'] else run())
