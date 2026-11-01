"""One bounded SEC maintenance owner; BUY checks consume only retained local facts."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from math import ceil

from pydantic import Field, model_validator

from sentinel.execution import issuer_admission as admission, journal
from sentinel.feed import issuer_reference as reference
from sentinel.feed import issuer_refresh as acquisition
from sentinel.feed.rolling_contract import Digest, digest

REFRESH_LOCK = 0x5E27_1EC3
DEADLINE_SECONDS = 15
RETRY_SECONDS = 3600


class RefreshBusy(ValueError):
    pass


class _Sealed(admission._Typed):
    sha256: Digest

    @model_validator(mode='after')
    def authentic(self):
        if digest(self.model_dump(mode='json', exclude={'sha256'})) != self.sha256:
            raise ValueError('issuer refresh record digest changed')
        return self

    @classmethod
    def create(cls, **values):
        body = cls.model_construct(**values).model_dump(mode='json', exclude={'sha256'})
        return cls.model_validate({**body, 'sha256': digest(body)})


class Anchors(_Sealed):
    binding: admission.Binding
    rows: tuple[reference.IssuerAssociation, ...] = Field(max_length=50000)
    quarantined_symbols: tuple[reference.Symbol, ...] = Field(max_length=30000)


class Current(_Sealed):
    binding: admission.Binding
    source_sha256: Digest
    anchors_sha256: Digest
    attempted_at: datetime
    next_attempt_at: datetime
    last_success_at: datetime | None
    reason: str = Field(max_length=100, pattern=r'^[A-Za-z0-9_]+$')

    @model_validator(mode='after')
    def clocks(self):
        times = (self.attempted_at, self.next_attempt_at, self.last_success_at)
        if (any(value is not None and value.utcoffset() != timedelta(0) for value in times)
                or self.next_attempt_at < self.attempted_at + timedelta(seconds=60)
                or self.last_success_at is not None and self.last_success_at > self.attempted_at):
            raise ValueError('issuer refresh record clock changed')
        return self


def _key(kind, owner):
    return admission.SOURCE_PREFIX + kind + ':' + admission._scope(owner)


def _load(conn, owner, fallback):
    owner = admission._binding(owner)
    raw = admission._read(conn, _key('current', owner), 'refresh-current')
    anchor = admission._read(conn, _key('anchors', owner), 'refresh-anchors')
    if raw is None and anchor is None:
        return None, None, fallback
    if raw is None or anchor is None:
        raise ValueError('issuer refresh cache is incomplete')
    state, catalog = Current.model_validate(raw), Anchors.model_validate(anchor)
    if state.binding != owner or catalog.binding != owner or state.anchors_sha256 != catalog.sha256:
        raise ValueError('issuer refresh cache binding changed')
    source_raw = admission._read(conn, admission.SOURCE_PREFIX + state.source_sha256, 'source')
    if source_raw is None:
        raise ValueError('issuer refresh source is absent')
    source = reference.IssuerReferenceSnapshot.model_validate(source_raw)
    if source.snapshot_digest != state.source_sha256:
        raise ValueError('issuer refresh source digest changed')
    return state, catalog, source


def _save(conn, owner, kind, value, now):
    admission._lock(conn)
    expected = Anchors if kind == 'anchors' else Current if kind == 'current' else None
    if expected is None or not isinstance(value, expected) or value.binding != admission._binding(owner):
        raise ValueError('issuer refresh mutable key is not admitted')
    label = 'refresh-' + kind
    body = value.model_dump(mode='json')
    record = {'schema': 'sentinel.issuer-operational-record/1', 'kind': label,
              'body': body, 'sha256': digest({'kind': label, 'body': body})}
    raw = json.dumps(record, sort_keys=True, separators=(',', ':'))
    if len(raw.encode()) > reference.MAX_RESPONSE_BYTES:
        raise ValueError('issuer refresh record exceeds size bound')
    old = admission._read(conn, _key(kind, owner), label)
    if old == body:
        return
    conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,%s,%s::jsonb)'
                 ' ON CONFLICT(cursor_name) DO UPDATE SET session=EXCLUDED.session,state=EXCLUDED.state',
                 (_key(kind, owner), now.date(), raw))


@contextmanager
def _writer(conn):
    try:
        if conn.execute('SELECT pg_try_advisory_xact_lock(%s)', (journal.WRITER_LOCK_KEY,)).fetchone()[0] is not True:
            raise RefreshBusy('issuer reference publication deferred while execution owns its writer lock')
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _owner(conn):
    from sentinel import local_paper
    owner = local_paper.bound_account(conn)
    if owner is None:
        raise ValueError('issuer refresh requires the exact owner PAPER account')
    value = admission._binding(owner.identity)
    admission.load_enrollment(conn, binding=value)
    return value


def _opening_delay(now):
    from sentinel.feed import calendar
    from zoneinfo import ZoneInfo
    day = now.astimezone(ZoneInfo('America/New_York')).date()
    if not calendar.sessions_in_range(day, day):
        return 0
    opened, _closed = calendar.session_window(day)
    end = opened + timedelta(minutes=10)
    return max(60, ceil((end-now).total_seconds())) if opened-timedelta(minutes=5) <= now < end else 0


def _owned(conn):
    row = conn.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid()"
        " AND locktype='advisory' AND classid=0 AND objid=%s AND objsubid=1"
        " AND mode='ExclusiveLock' AND granted)", (REFRESH_LOCK,)).fetchone()
    if row is None or row[0] is not True:
        raise ValueError('issuer refresh ownership lost')


def collect(conn, *, email, now=None, opener=None):
    """One scheduled attempt. Persist backoff BEFORE HTTP; no retry loop or broker."""
    acquisition.declared_user_agent(email)
    fixed = now is not None
    now = reference._now(now)
    acquired = False
    try:
        acquired = conn.execute('SELECT pg_try_advisory_lock(%s)', (REFRESH_LOCK,)).fetchone()[0] is True
        conn.rollback()
        if not acquired:
            return {'status': 'DEFERRED', 'retry_after_seconds': 60}
        with _writer(conn):
            owner = _owner(conn)
            state, catalog, source = _load(conn, owner, reference.load_snapshot())
            if state is not None and now < state.attempted_at:
                raise ValueError('issuer refresh clock reversed')
            if state is not None and now < state.next_attempt_at:
                return {'status': 'CACHED', 'retry_after_seconds': max(60, ceil((state.next_attempt_at-now).total_seconds()))}
            if catalog is None:
                catalog = Anchors.create(binding=owner, rows=source.associations, quarantined_symbols=())
                _save(conn, owner, 'anchors', catalog, now)
                admission._store_source(conn, source, now.date())
            delay = _opening_delay(now)
            pending = Current.create(binding=owner, source_sha256=source.snapshot_digest,
                anchors_sha256=catalog.sha256, attempted_at=now,
                next_attempt_at=now+timedelta(seconds=delay or RETRY_SECONDS),
                last_success_at=state.last_success_at if state else None,
                reason='deferred_opening_window' if delay else 'attempt_started')
            _save(conn, owner, 'current', pending, now)
        if delay:
            return {'status': 'DEFERRED', 'retry_after_seconds': delay}
        # The session refresh lock stays held, but no transaction/writer lock
        # survives this boundary. Network failures cannot stall execution.
        result = acquisition.refresh(source, email=email, anchors=catalog.rows,
            quarantined=catalog.quarantined_symbols, now=now, opener=opener)
        completed = now if fixed else reference._now(None)
        if completed < now:
            raise ValueError('issuer refresh clock reversed during acquisition')
        with _writer(conn):
            _owned(conn)
            if _owner(conn) != owner:
                raise ValueError('issuer refresh account changed during acquisition')
            fresh, original_catalog, _current = _load(conn, owner, source)
            if fresh.sha256 != pending.sha256 or original_catalog.sha256 != catalog.sha256:
                raise ValueError('issuer refresh cache changed during acquisition')
            updated = Anchors.create(binding=owner, rows=result.anchor_rows or catalog.rows,
                quarantined_symbols=tuple(sorted(set(catalog.quarantined_symbols) | set(result.quarantined_symbols))))
            _save(conn, owner, 'anchors', updated, completed)
            chosen = source
            if result.status == 'REFRESHED' and acquisition.needs_version(source, result.snapshot, completed):
                chosen = admission._store_source(conn, result.snapshot, completed.date())
            success = completed if result.status == 'REFRESHED' else pending.last_success_at
            final = Current.create(binding=owner, source_sha256=chosen.snapshot_digest,
                anchors_sha256=updated.sha256, attempted_at=completed,
                next_attempt_at=completed+timedelta(seconds=result.retry_after_seconds),
                last_success_at=success, reason=result.reason)
            _save(conn, owner, 'current', final, completed)
        return {'status': result.status, 'reason': result.reason, 'retry_after_seconds': result.retry_after_seconds}
    except RefreshBusy:
        return {'status': 'DEFERRED', 'retry_after_seconds': RETRY_SECONDS}
    finally:
        conn.rollback()
        if acquired:
            conn.execute('SELECT pg_advisory_unlock(%s)', (REFRESH_LOCK,))
            conn.commit()


def current_snapshot(conn, *, binding, fallback, now):
    state, _catalog, source = _load(conn, binding, fallback)
    if state is not None and now < state.attempted_at:
        raise ValueError('issuer refresh cache is from the future')
    return source


class Eligibility:
    def __init__(self, original, current, quarantined):
        self.original, self.current, self.quarantined = original, current, frozenset(quarantined)
        self.snapshot_digest = current.snapshot_digest

    def resolve(self, symbol, exchange, kind, broad, *, now):
        if acquisition.symbol_key(symbol) in self.quarantined:
            return self.current._identity(symbol, 'issuer_association_quarantined')
        present = self.current.resolve(symbol, exchange, kind, broad, now=now)
        known = self.original.resolve(symbol, exchange, kind, broad,
                                      now=self.original.provenance.observed_at_utc)
        if known.status != 'VERIFIED' or known.issuer_id != present.issuer_id:
            return self.current._identity(symbol, 'pinned_historical_issuer_not_confirmed')
        return present


def eligibility(conn, *, binding, original, now):
    state, catalog, current = _load(conn, binding, original)
    if state is not None and now < state.attempted_at:
        raise ValueError('issuer refresh cache is from the future')
    return Eligibility(original, current, catalog.quarantined_symbols if catalog else ())


def diagnostic(conn, *, binding, now):
    state, catalog, source = _load(conn, binding, reference.load_snapshot())
    if state is None:
        return None
    if now < state.attempted_at:
        raise ValueError('issuer refresh cache is from the future')
    expires = min([source.provenance.expires_at_utc] + [p.expires_at_utc for p in source.corroborations])
    return {'valid': source.valid_at(now) and now < expires, 'expires_at': expires,
            'source_observed_at': source.provenance.observed_at_utc,
            'last_success_at': state.last_success_at, 'next_attempt_at': state.next_attempt_at,
            'reason': state.reason, 'quarantined': len(catalog.quarantined_symbols),
            'coverage': source.provenance.coverage, 'source_sha256': source.snapshot_digest}
