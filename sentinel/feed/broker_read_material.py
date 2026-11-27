"""Sealed data under one broker reader's independently observed PostgreSQL snapshot."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from functools import wraps
from inspect import signature
from os import getpid

from sentinel.feed.rolling_contract import digest


_active = ContextVar('broker_sealed_read_material', default=None)
_sources = ('sentinel_price_candidates', 'sentinel_candidate_layouts', 'sentinel_candidate_blocks',
            'sentinel_normalized_blocks', 'sentinel_snapshot_evidence', 'sentinel_snapshot_retirements',
            'sentinel_operational_snapshots', 'sentinel_snapshot_jobs')


def _snapshot(conn):
    # Equal full MVCC snapshots include the same committed writes, including DDL and
    # writes from transactions which were already in progress when a proof began.
    # A writer's own invisible-to-others changes and temporary or policy-dependent
    # relations cannot be shared between readers, even when their snapshot texts match.
    return conn.execute("""
        SELECT CASE WHEN has_function_privilege('pg_catalog.pg_control_system()', 'EXECUTE')
                    THEN (SELECT system_identifier FROM pg_catalog.pg_control_system()) END,
               pg_postmaster_start_time(), d.oid, current_user, session_user,
               current_setting('search_path'), current_setting('TimeZone'), current_setting('DateStyle'),
               pg_current_snapshot()::text,
               ARRAY(SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n
                     ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname=ANY(%s)
                     AND c.relkind='r' AND NOT c.relrowsecurity ORDER BY c.oid)
        FROM pg_catalog.pg_database d WHERE d.datname=current_database()
          AND current_setting('transaction_read_only')='on' AND NOT pg_is_in_recovery()
          AND current_setting('session_replication_role')='origin'
          AND current_schemas(true)=ARRAY['pg_catalog','public']::name[]
          AND pg_my_temp_schema()=0 AND pg_current_xact_id_if_assigned() IS NULL
        """, (list(_sources),)).fetchone()


@dataclass
class _Record:
    key: str
    snapshot: tuple
    source: tuple | None
    started: tuple
    value: object


@dataclass
class _Book:
    pid: int = field(default_factory=getpid)
    records: dict = field(default_factory=dict)
    witness: tuple | None = None


class ReadScope:
    """Owned by one canonical guard closure. Only exact canonical readers can populate a slot."""

    def __init__(self):
        self.owner = None
        self.book = _Book()

    @contextmanager
    def enter(self, grant):
        if self.owner is not grant or self.book.pid != getpid():
            self.book = _Book()
            self.owner = grant
        token = _active.set(self.book if grant is not None else None)
        try:
            yield
        finally:
            _active.reset(token)


def _pinned_witness(conn, subject, snapshot, scope):
    from sentinel.feed import readiness_scope, shadow_readiness_memo
    pin = readiness_scope.capture(conn)
    if pin is None:
        return None
    pub = pin.publication_object
    binding = pub.evidence.get('rolling_snapshot', {})
    if isinstance(subject, str):
        if subject != str(binding.get('candidate_id')):
            return None
    elif subject != pub:
        return None
    key = (snapshot, pin.publication)
    if scope.witness is not None and scope.witness[0] == key:
        return scope.witness[1]
    value = shadow_readiness_memo._witness(conn, pub, financial_pin=True)
    if value is None:
        return None
    # The domain witness is reusable across unrelated commits. All visibility
    # coordinates except the full transaction snapshot still have to match.
    witness = (snapshot[:-2], snapshot[-1], value)
    if snapshot != _snapshot(conn):
        return None
    scope.witness = (key, witness)
    return witness


def sealed(reader):
    """The loader itself owns the slot. Callers cannot supply verified material."""
    if (reader.__module__, reader.__qualname__) not in {
            ('sentinel.feed.rolling_store', 'manifest'),
            ('sentinel.feed.operational_snapshot', '_bound_and_manifest')}:
        raise TypeError('only the sealed manifest and operational binding have this data contract')
    parameters = signature(reader)
    @wraps(reader)
    def read(*args, **kwargs):
        scope = _active.get()
        if scope is None or scope.pid != getpid():
            return reader(*args, **kwargs)
        conn, subject = parameters.bind(*args, **kwargs).arguments.values()
        try:
            from psycopg import Connection
        except ImportError:
            return reader(conn, subject)
        if not isinstance(conn, Connection):
            return reader(conn, subject)
        from sentinel.feed import readiness_scope, rolling_store, shadow_readiness_memo
        readiness_scope.require(conn)
        rolling_store._pin_reader(conn)
        before = _snapshot(conn)
        if before is None or before[0] is None or len(before[-1]) != len(_sources):
            return reader(conn, subject)
        key = subject if isinstance(subject, str) else digest(subject.to_dict())
        prior = scope.records.get(reader)
        now = shadow_readiness_memo._clock()
        current = (prior is not None and prior.key == key
                   and shadow_readiness_memo._age_current(prior.started, now))
        if current and prior.snapshot == before:
            return deepcopy(prior.value)
        witness = _pinned_witness(conn, subject, before, scope)
        if current and witness is not None and prior.source == witness:
            prior.snapshot = before
            return deepcopy(prior.value)
        value = reader(conn, subject)
        after = _snapshot(conn)
        if after is not None and (before == after or witness is not None
                                  and witness == _pinned_witness(conn, subject, after, scope)):
            scope.records[reader] = _Record(key, after, witness, now, deepcopy(value))
        return value
    return read
