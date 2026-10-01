"""Compact immutable readiness material, reusable only under a live corpus pin.

This never stores a readiness verdict or broker authority. Publication receipts,
strategy, clocks and execution grants are rechecked by their existing owners.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass

from sentinel.feed import publication
from sentinel.feed.rolling_contract import digest


@dataclass
class _Scope:
    owner: object
    backend_pid: int
    database: tuple
    publication: str
    active: bool = True
    material: object = None


_current: ContextVar[_Scope | None] = ContextVar('rolling_readiness_pin', default=None)


def _database(conn):
    info = conn.info
    return (info.host, info.port, info.dbname, info.user)


def _require_pin(conn, scope):
    if not scope.active or scope.owner.closed:
        raise publication.CorpusIncoherent('READINESS_SCOPE_EXPIRED')
    key = publication.CORPUS_LOCK_KEY
    held = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' "
        "AND pid=%s AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) "
        "AND classid=%s AND objid=%s AND objsubid=1 AND mode='ShareLock' AND granted)",
        (scope.backend_pid, key >> 32, key & 0xffffffff)).fetchone()[0]
    if not held:
        raise publication.CorpusIncoherent('READINESS_PUBLICATION_PIN_LOST')


def require(conn):
    """Check before a storage reader could reacquire a transaction-level pin."""
    scope = _current.get()
    if scope is not None and scope.database == _database(conn):
        _require_pin(conn, scope)


@contextmanager
def pinned(conn, pub):
    """Enter after acquiring the real publication lock; release before unlock."""
    if 'rolling_snapshot' not in pub.evidence:
        yield
        return
    identity, database = digest(pub.to_dict()), _database(conn)
    previous = _current.get()
    if previous is not None and (previous.publication, previous.database) == (identity, database):
        _require_pin(conn, previous)
        yield
        return
    scope = _Scope(conn, conn.info.backend_pid, database, identity)
    _require_pin(conn, scope)
    token = _current.set(scope)
    try:
        yield
    finally:
        scope.active = False
        scope.material = None
        _current.reset(token)


def material(conn, pub, load):
    """Reuse counts/domains only; callers recompute all current verdicts."""
    scope = _current.get()
    if scope is None or (scope.publication, scope.database) != (digest(pub.to_dict()), _database(conn)):
        return load()
    _require_pin(conn, scope)
    publication._validate_publication(conn, pub, allow_snapshot=True)
    if scope.material is None:
        value = load()
        _require_pin(conn, scope)
        scope.material = deepcopy(value)
    value = deepcopy(scope.material)
    _require_pin(conn, scope)
    return value
