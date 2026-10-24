"""Compact immutable readiness material, reusable only under a live corpus pin.

This never stores a readiness verdict or broker authority. Publication receipts,
strategy, clocks and execution grants are rechecked by their existing owners.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field

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
    publication_object: object = None
    verified_snapshots: dict = field(default_factory=dict)


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


def require_owned_publication(conn, pub):
    """Strict mutation boundary; an absent optional reuse scope grants nothing."""
    scope = _current.get()
    if (scope is None or scope.owner is not conn or scope.backend_pid != conn.info.backend_pid
            or scope.database != _database(conn) or scope.publication != digest(pub.to_dict())):
        raise publication.CorpusIncoherent('READINESS_OWNED_PUBLICATION_PIN_REQUIRED')
    _require_pin(conn, scope)


def capture(conn):
    """Opaque lifetime token for other read-only work under this exact pin."""
    scope = _current.get()
    if scope is None or scope.database != _database(conn):
        return None
    _require_pin(conn, scope)
    return scope


def require_token(conn, token):
    if token is not _current.get() or token.database != _database(conn):
        raise publication.CorpusIncoherent('READINESS_SCOPE_CHANGED')
    _require_pin(conn, token)


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
    scope = _Scope(conn, conn.info.backend_pid, database, identity,
                   publication_object=deepcopy(pub))
    _require_pin(conn, scope)
    token = _current.set(scope)
    try:
        yield
    finally:
        scope.active = False
        scope.material = None
        scope.verified_snapshots.clear()
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


def verified_snapshot(conn, candidate_id, load, *, summary_only=False):
    """Reuse only a completed full scan under the original live corpus pin."""
    from sentinel.feed import rolling_store

    def detached(completed):
        if not isinstance(completed, rolling_store.VerifiedSnapshot):
            raise publication.CorpusIncoherent('VERIFIED_SNAPSHOT_RESULT_INCOMPLETE')
        return deepcopy(completed.readiness if summary_only else completed.manifest)

    scope = _current.get()
    if scope is None or scope.database != _database(conn):
        return detached(load()) if load is not None else None
    _require_pin(conn, scope)
    pub = scope.publication_object
    if pub is None or digest(pub.to_dict()) != scope.publication:
        raise publication.CorpusIncoherent('VERIFIED_SNAPSHOT_SCOPE_CHANGED')
    publication._validate_publication(conn, pub, allow_snapshot=True)
    binding = pub.evidence.get('rolling_snapshot')
    if (not isinstance(binding, dict) or not isinstance(binding.get('candidate_id'), str)
            or not isinstance(binding.get('snapshot_id'), str)):
        raise publication.CorpusIncoherent('VERIFIED_SNAPSHOT_BINDING_CHANGED')
    if binding['candidate_id'] != candidate_id:
        return detached(load()) if load is not None else None
    key = (candidate_id, binding['snapshot_id'])
    current = rolling_store.manifest(conn, candidate_id)
    if current.snapshot_id != binding['snapshot_id']:
        raise publication.CorpusIncoherent('VERIFIED_SNAPSHOT_MANIFEST_CHANGED')
    cached = scope.verified_snapshots.get(key)
    if cached is None:
        if load is None:
            return None
        completed = load()
        _require_pin(conn, scope)
        publication._validate_publication(conn, pub, allow_snapshot=True)
        if (not isinstance(completed, rolling_store.VerifiedSnapshot)
                or completed.manifest != current
                or rolling_store.manifest(conn, candidate_id) != current):
            raise publication.CorpusIncoherent('VERIFIED_SNAPSHOT_RESULT_CHANGED')
        scope.verified_snapshots[key] = deepcopy(completed)
        cached = completed
    if not isinstance(cached, rolling_store.VerifiedSnapshot) or cached.manifest != current:
        raise publication.CorpusIncoherent('VERIFIED_SNAPSHOT_MANIFEST_CHANGED')
    _require_pin(conn, scope)
    return detached(cached)
