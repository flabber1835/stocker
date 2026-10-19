"""Callback-local pure verification reuse, fenced by fresh database row versions.

No readiness, time, certificate, lease or broker authorization verdict lives here.
Outside the guarded callback all callers execute their complete verifier.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import pickle
from typing import Literal

from sentinel.execution.journal import WRITER_LOCK_KEY
from sentinel.feed import readiness_scope
from sentinel.retained_input_namespaces import PAPER_CURSOR_NAMES, PAPER_CURSOR_PREFIXES


class VerificationScopeRefused(ValueError):
    pass


_current = ContextVar('structural_verification_scope', default=None)
_ECONOMIC_INPUT_SLOTS: frozenset[Literal['rolling-checkpoint', 'dual-sizing']] = frozenset({
    'rolling-checkpoint', 'dual-sizing',
})


def active():
    """Only a performance hint; material() still checks all ownership fences."""
    return _current.get() is not None


def _inventory(conn, slot):
    # Do not detoast multi-megabyte state just to discover whether it changed.
    relation = conn.execute(
        "SELECT 'sentinel_processed_sessions'::regclass::oid, "
        "pg_relation_filenode('sentinel_processed_sessions'), "
        "floor(pg_snapshot_xmax(pg_current_snapshot())::text::numeric / 4294967296)::bigint"
    ).fetchone()
    rows = conn.execute(
        "SELECT cursor_name,session,tableoid,xmin::text,ctid::text "
        "FROM sentinel_processed_sessions "
        "WHERE %s OR (cursor_name <> ALL(%s) AND NOT (cursor_name LIKE ANY(%s))) "
        "ORDER BY cursor_name",
        (slot not in _ECONOMIC_INPUT_SLOTS, list(PAPER_CURSOR_NAMES),
         [prefix + '%' for prefix in PAPER_CURSOR_PREFIXES]),
    ).fetchall()
    return relation, rows


class Scope:
    def __init__(self, owner):
        self.owner = owner
        self.pin = readiness_scope.capture(owner)
        self.values = {}

    def require(self, conn):
        readiness_scope.require_token(conn, self.pin)
        held = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' "
            "AND pid=%s AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) "
            "AND classid=%s AND objid=%s AND objsubid=1 AND mode='ExclusiveLock' AND granted)",
            (self.owner.info.backend_pid, WRITER_LOCK_KEY >> 32,
             WRITER_LOCK_KEY & 0xffffffff)).fetchone()[0]
        if self.owner.closed or not held:
            raise VerificationScopeRefused('STRUCTURAL_WRITER_LOCK_LOST')

    @contextmanager
    def guard(self, conn):
        if self.pin is None:
            yield
            return
        self.require(conn)
        token = _current.set(self)
        try:
            yield
        finally:
            _current.reset(token)


@contextmanager
def callback(owner):
    """Warm one proof scope inside the existing writer and publication pin."""
    scope = Scope(owner)
    with scope.guard(owner):
        yield scope


def owned(owner):
    """Reuse only the exact callback owner; never borrow another connection."""
    scope = _current.get()
    if scope is not None and scope.owner is owner:
        scope.require(owner)
        return scope
    return None


def material(conn, *, slot, key, load):
    scope = _current.get()
    if scope is None:
        return load()
    scope.require(conn)
    before = _inventory(conn, slot)
    retained = scope.values.get(slot)
    if retained is None or retained[:2] != (key, before):
        value = load()
        scope.require(conn)
        if _inventory(conn, slot) != before:
            raise VerificationScopeRefused('STRUCTURAL_INPUTS_CHANGED_DURING_VERIFICATION')
        # This byte string is produced only from the just-authenticated private
        # value. It never crosses a process or storage boundary. Restoring it
        # gives each guard an independent graph without recursively copying the
        # large retained book in Python on every broker read.
        scope.values[slot] = (deepcopy(key), before, pickle.dumps(value, protocol=5))
    result = pickle.loads(scope.values[slot][2])
    scope.require(conn)
    return result
