"""Finite authenticated observer diagnostics; no financial or execution authority.

Callers own the existing validated receipt catalog, transaction and owner lock.
These readers/writers never commit, migrate, renew ownership or resume a job.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import hmac
import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from psycopg.types.json import Jsonb

from sentinel.panel import observer_failure, operational_schema as schema, review_store

SCHEMA = 'sentinel.financial-observer-diagnostics/1'
PURPOSE = 'sentinel.financial-observer-attempt-history/1'
MAX_BYTES = 64 * 1024
MAX_FAILURES = 16
OBSERVATION_SECONDS = 600
Scope = Literal['DIAGNOSTIC:SHADOW', 'DIAGNOSTIC:PAPER']


class DiagnosticsRefused(ValueError):
    pass


def _require(value, code):
    if not value:
        raise DiagnosticsRefused(code)


class Runtime(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    git_commit: str | None = Field(default=None, pattern=r'^(?:[a-f0-9]{40}|[a-f0-9]{64})$')
    image_digest: str | None = Field(default=None, pattern=r'^sha256:[a-f0-9]{64}$')


class FailedAttempt(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    first: observer_failure.Attempt
    latest: observer_failure.Attempt
    first_recorded_at: datetime
    last_recorded_at: datetime
    runtime: Runtime

    @model_validator(mode='after')
    def consistent(self):
        immutable = ('attempt_id', 'subject_sha256', 'admitted_at', 'deadline')
        if (self.first.outcome != 'FAILED' or self.first.diagnostic is None
                or self.first.diagnostic.outcome != 'FAILED'
                or any(getattr(self.first, key) != getattr(self.latest, key) for key in immutable)
                or any(value.utcoffset() != timedelta(0)
                       for value in (self.first_recorded_at, self.last_recorded_at))
                or self.last_recorded_at < self.first_recorded_at):
            raise ValueError('failed attempt summary is contradictory')
        return self


class History(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    schema_version: Literal['sentinel.financial-observer-diagnostics/1'] = Field(alias='schema')
    scope: Scope
    context_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    latest: observer_failure.Attempt
    failures: tuple[FailedAttempt, ...] = Field(max_length=MAX_FAILURES)
    recorded_at: datetime
    valid_until: datetime
    runtime: Runtime

    @model_validator(mode='after')
    def consistent(self):
        if (any(value.utcoffset() != timedelta(0) for value in (self.recorded_at, self.valid_until))
                or self.valid_until-self.recorded_at != timedelta(seconds=OBSERVATION_SECONDS)
                or len({item.first.attempt_id for item in self.failures}) != len(self.failures)
                or any(item.last_recorded_at > self.recorded_at for item in self.failures)):
            raise ValueError('observer diagnostic history clocks or identity changed')
        return self


def scope_key(scope):
    _require(scope in {'SHADOW', 'PAPER'}, 'DIAGNOSTIC_SCOPE_INVALID')
    return 'DIAGNOSTIC:'+scope


def context(conn):
    physical = conn.execute('SELECT system_identifier::text,current_database() FROM pg_control_system()').fetchone()
    _require(physical is not None, 'DIAGNOSTIC_DATABASE_SCOPE_MISSING')
    return hashlib.sha256(review_store.canonical(dict(
        physical=list(physical), account=review_store.scope(conn)))).hexdigest()


def _runtime():
    return Runtime.model_validate(dict(git_commit=os.environ.get('SENTINEL_GIT_COMMIT') or None,
        image_digest=os.environ.get('SENTINEL_RUNTIME_IMAGE_DIGEST') or None))


def _canonical(value):
    try:
        raw = review_store.canonical(value)
    except (ValueError, TypeError, OverflowError):
        raise DiagnosticsRefused('DIAGNOSTIC_ENCODING_INVALID') from None
    _require(len(raw) <= MAX_BYTES, 'DIAGNOSTIC_SIZE_EXCEEDED')
    return raw


def decode(value, signature, *, scope, context_sha256, now):
    raw = _canonical(value)
    _require(isinstance(signature, str) and len(signature) == 64
        and all(character in '0123456789abcdef' for character in signature)
        and hmac.compare_digest(signature,
        review_store.signature(value, purpose=PURPOSE)), 'DIAGNOSTIC_AUTHENTICATION_FAILED')
    try:
        history = History.model_validate_json(raw)
    except (ValueError, TypeError, KeyError):
        raise DiagnosticsRefused('DIAGNOSTIC_HISTORY_INVALID') from None
    _require(history.scope == scope_key(scope) and history.context_sha256 == context_sha256,
             'DIAGNOSTIC_CONTEXT_CHANGED')
    _require(isinstance(now, datetime) and now.utcoffset() == timedelta(0)
             and history.recorded_at <= now, 'DIAGNOSTIC_CLOCK_INVALID')
    # History remains readable after its observation window. It cannot resume
    # work or confer a current verification verdict at any age.
    return history


def _read_owned(conn, *, scope, context_sha256, now, lock=False):
    row = conn.execute(f'SELECT subject_sha256,observed_at,valid_until,envelope,signature '
        f'FROM {schema.RECEIPTS} WHERE scope=%s'+(' FOR UPDATE' if lock else ''),
        (scope_key(scope),)).fetchone()
    if row is None:
        return None
    value = decode(row[3], row[4], scope=scope, context_sha256=context_sha256, now=now)
    _require(row[0] == value.context_sha256 and row[1] == value.recorded_at
             and row[2] == value.valid_until, 'DIAGNOSTIC_METADATA_CHANGED')
    return value


def read_owned(conn, *, scope, now):
    history = _read_owned(conn, scope=scope, context_sha256=context(conn), now=now)
    if history is None:
        return None
    return {**history.model_dump(mode='json', by_alias=True),
            'observation_fresh': now < history.valid_until, 'financial_authority': False}


def publish_owned(conn, *, owner_id, scope, attempt, now):
    """Preserve first failures and original clocks in the caller's transaction."""
    from sentinel.panel.review import record_verification_failure_owned
    _require(isinstance(now, datetime) and now.utcoffset() == timedelta(0),
             'DIAGNOSTIC_CLOCK_INVALID')
    try:
        current = observer_failure.Attempt.model_validate_json(_canonical(attempt))
        runtime = _runtime()
    except (ValueError, TypeError, KeyError):
        raise DiagnosticsRefused('DIAGNOSTIC_ATTEMPT_INVALID') from None
    owner = conn.execute(f'SELECT owner_id FROM {schema.OWNER} WHERE id=1 AND owner_id=%s '
        'AND expires_at>clock_timestamp() FOR UPDATE', (owner_id,)).fetchone()
    _require(owner is not None, 'DIAGNOSTIC_OWNER_LOST')
    bound = context(conn)
    previous = _read_owned(conn, scope=scope, context_sha256=bound, now=now, lock=True)
    if previous is not None and previous.latest == current and previous.runtime == runtime:
        return record_verification_failure_owned(conn, scope=scope, attempt=current)
    failures = list(previous.failures) if previous is not None else []
    matched = False
    for index, item in enumerate(failures):
        if item.first.attempt_id == current.attempt_id:
            failures[index] = FailedAttempt.model_validate(dict(
                first=item.first, latest=current, first_recorded_at=item.first_recorded_at,
                last_recorded_at=now, runtime=item.runtime))
            matched = True
            break
    if current.outcome == 'FAILED' and not matched:
        failures.append(FailedAttempt.model_validate(dict(first=current, latest=current,
            first_recorded_at=now, last_recorded_at=now, runtime=runtime)))
    value = History.model_validate(dict(schema=SCHEMA, scope=scope_key(scope),
        context_sha256=bound, latest=current, failures=tuple(failures[-MAX_FAILURES:]),
        recorded_at=now, valid_until=now+timedelta(seconds=OBSERVATION_SECONDS), runtime=runtime))
    encoded = value.model_dump(mode='json', by_alias=True)
    _canonical(encoded)
    signed = review_store.signature(encoded, purpose=PURPOSE)
    row = conn.execute(f'INSERT INTO {schema.RECEIPTS} '
        '(scope,subject_sha256,observed_at,valid_until,envelope,signature) '
        'SELECT %s,%s,%s,%s,%s,%s WHERE EXISTS '
        f'(SELECT 1 FROM {schema.OWNER} WHERE id=1 AND owner_id=%s AND expires_at>clock_timestamp()) '
        'ON CONFLICT (scope) DO UPDATE SET subject_sha256=EXCLUDED.subject_sha256,'
        'observed_at=EXCLUDED.observed_at,valid_until=EXCLUDED.valid_until,'
        'envelope=EXCLUDED.envelope,signature=EXCLUDED.signature WHERE EXISTS '
        f'(SELECT 1 FROM {schema.OWNER} WHERE id=1 AND owner_id=%s AND expires_at>clock_timestamp()) '
        'RETURNING scope',
        (value.scope, bound, value.recorded_at, value.valid_until, Jsonb(encoded), signed,
         owner_id, owner_id)).fetchone()
    _require(row is not None, 'DIAGNOSTIC_OWNER_LOST_AT_WRITE')
    record_verification_failure_owned(conn, scope=scope, attempt=current)
    return True
