"""Owned read-only proofs of committed state, preserving borrowed work."""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
import hashlib
import io
import os
import pickle


class CommittedReadRefused(ValueError):
    pass


_checkpoint_owner = ContextVar('committed_checkpoint_owner', default=None)
_UNSET = object()
_CHECKPOINTS = frozenset({'rolling-cold-start:v1', 'rolling-daily-checkpoint:v1'})
MAX_CHECKPOINT_BUFFER_BYTES = 64 * 1024 * 1024


class _CheckpointBufferFull(Exception):
    pass


class _CheckpointBuffer:
    def __init__(self, limit):
        self.limit = limit
        self.buffer = io.BytesIO()

    def write(self, value):
        if self.buffer.tell() + len(value) > self.limit:
            raise _CheckpointBufferFull
        return self.buffer.write(value)


def _pack_checkpoint(value, remaining):
    if remaining <= 0:
        return None
    target = _CheckpointBuffer(remaining)
    try:
        pickle.Pickler(target, protocol=5).dump(value)
    except _CheckpointBufferFull:
        return None
    return target.buffer.getvalue()


class _CheckpointOwner:
    """Raw authenticated inputs only, inside one exact committed transaction."""
    def __init__(self, conn):
        self.conn = conn
        self.backend = conn.info.backend_pid
        self.database = (conn.info.host, conn.info.port, conn.info.dbname, conn.info.user)
        self.transaction = None
        self.pin = _UNSET
        self.active = True
        self.values = {}
        self.buffered_bytes = 0
        self.serialization_refusals = {}

    def metadata(self, conn, cursor):
        from psycopg.pq import TransactionStatus
        from sentinel.feed import readiness_scope
        if (not self.active or conn is not self.conn or conn.closed
                or conn.info.backend_pid != self.backend
                or (conn.info.host, conn.info.port, conn.info.dbname, conn.info.user) != self.database
                or conn.info.transaction_status != TransactionStatus.INTRANS):
            raise CommittedReadRefused('COMMITTED_CHECKPOINT_OWNER_CHANGED')
        pin = readiness_scope.capture(conn)
        if self.pin is _UNSET:
            self.pin = pin
        elif pin is not self.pin:
            raise CommittedReadRefused('COMMITTED_CHECKPOINT_PIN_CHANGED')
        if pin is not None:
            readiness_scope.require_token(conn, pin)
        row = conn.execute(
            "SELECT current_database(),pg_backend_pid(),transaction_timestamp(),"
            "current_setting('transaction_read_only'),current_setting('transaction_isolation'),"
            "'sentinel_processed_sessions'::regclass::oid,"
            "pg_relation_filenode('sentinel_processed_sessions'),"
            "floor(pg_snapshot_xmax(pg_current_snapshot())::text::numeric / 4294967296)::bigint,"
            "r.session,r.tableoid,r.xmin::text,r.ctid::text "
            "FROM (VALUES(1)) AS seed(n) LEFT JOIN sentinel_processed_sessions r ON r.cursor_name=%s",
            (cursor,)).fetchone()
        if row is None or row[3:5] != ('on', 'repeatable read'):
            raise CommittedReadRefused('COMMITTED_CHECKPOINT_TRANSACTION_REQUIRED')
        if self.transaction is None:
            self.transaction = row[:8]
        elif row[:8] != self.transaction:
            raise CommittedReadRefused('COMMITTED_CHECKPOINT_TRANSACTION_CHANGED')
        # This is a configuration identity, not a retained secret or authority.
        from sentinel.receipt_authentication import KEY_ENV
        key = hashlib.sha256(os.environ.get(KEY_ENV, '').strip().encode()).digest()
        return row, key


def checkpoint(conn, *, cursor, read):
    """Detach canonical checkpoint input; unknown/unowned readers stay complete."""
    owner = _checkpoint_owner.get()
    if owner is None or owner.conn is not conn or cursor not in _CHECKPOINTS:
        return read(conn)
    before = owner.metadata(conn, cursor)
    retained = owner.values.get(cursor)
    if retained is None or retained[:2] != (before, read):
        if retained is not None:
            del owner.values[cursor]
            owner.buffered_bytes -= len(retained[2])
            retained = None
        remaining = MAX_CHECKPOINT_BUFFER_BYTES-owner.buffered_bytes
        admission = before, read, remaining
        refused = owner.serialization_refusals.get(cursor)
        if refused is not None and refused != admission:
            del owner.serialization_refusals[cursor]
            refused = None
        value = read(conn)
        if owner.metadata(conn, cursor) != before:
            raise CommittedReadRefused('COMMITTED_CHECKPOINT_CHANGED_DURING_READ')
        packed = _pack_checkpoint(value, remaining) if refused is None else None
        if packed is not None:
            owner.values[cursor] = before, read, packed
            owner.buffered_bytes += len(packed)
            owner.serialization_refusals.pop(cursor, None)
        elif refused is None:
            owner.serialization_refusals[cursor] = admission
        # Only immutable bytes are retained. The first canonical graph is
        # already detached from those bytes; do not reconstruct it again.
        result = value
    else:
        result = pickle.loads(retained[2])
    if owner.metadata(conn, cursor) != before:
        raise CommittedReadRefused('COMMITTED_CHECKPOINT_CHANGED_DURING_RESTORE')
    return result


@contextmanager
def _checkpoint_scope(conn):
    owner = _CheckpointOwner(conn)
    token = _checkpoint_owner.set(owner)
    try:
        yield
    finally:
        owner.active = False
        owner.values.clear()
        owner.buffered_bytes = 0
        owner.serialization_refusals.clear()
        _checkpoint_owner.reset(token)


@contextmanager
def proof_connection(conn, *, serialize_snapshot=False):
    """Keep borrowed work intact; canonical status observes committed rows."""
    from psycopg.pq import TransactionStatus
    from sentinel.feed import readiness_scope
    borrowed = conn.info.transaction_status != TransactionStatus.IDLE
    with conn.transaction(force_rollback=True):
        pin = readiness_scope.capture(conn)
        statement_timeout = conn.execute('SHOW statement_timeout').fetchone()[0]
        lock_timeout = conn.execute('SHOW lock_timeout').fetchone()[0]
    borrowed = borrowed or pin is not None
    if borrowed:
        from sentinel.guarded_administration import fresh_connection_factory
        proof = fresh_connection_factory(conn)()
    else:
        proof = conn
    try:
        from sentinel.snapshot_scan_admission import admitted
        with admitted(proof) if serialize_snapshot else nullcontext():
            proof.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            if borrowed:
                proof.execute("SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true)",
                              (statement_timeout,lock_timeout))
            with _checkpoint_scope(proof):
                yield proof
                if pin is not None:
                    with conn.transaction(force_rollback=True):
                        readiness_scope.require_token(conn,pin)
    finally:
        try:
            proof.rollback()
        finally:
            if borrowed:
                proof.close()
