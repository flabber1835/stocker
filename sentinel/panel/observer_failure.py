"""Closed financial-observer failures; private exception text never crosses IPC."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA = 'sentinel.financial-observer-failure/1'
ATTEMPT_SCHEMA = 'sentinel.financial-observer-attempt/1'
MAX_BYTES = 2048
SUPERSESSION_SECONDS = 600
MAX_FINGERPRINT_BYTES = 32 * 1024

Phase = Literal['BEFORE_OBSERVATION', 'OBSERVATION', 'AFTER_OBSERVATION',
                'QUEUE', 'TRANSPORT', 'VALIDATION', 'SUPERSESSION']
Code = Literal['SUBJECT_CHANGED', 'READ_TIMEOUT', 'READ_LOCK_UNAVAILABLE',
               'CORPUS_LOCK_UNAVAILABLE', 'OBSERVATION_TIMEOUT',
               'VALIDATION_REFUSED', 'OBSERVER_EXCEPTION', 'TRANSPORT_TIMEOUT',
               'TRANSPORT_FAILED', 'INVALID_OUTCOME', 'SUPERSESSION_EXHAUSTED',
               'CLOCK_REGRESSION', 'NEGATIVE_RESULT']


class ObservationSuperseded(ValueError):
    """The original subject changed; this work establishes no current verdict."""

    def __init__(self, phase: Literal['BEFORE_OBSERVATION', 'AFTER_OBSERVATION'],
                 message: str):
        super().__init__(message)
        self.phase = phase


class Failure(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    schema_version: Literal['sentinel.financial-observer-failure/1'] = Field(alias='schema')
    outcome: Literal['FAILED', 'SUPERSEDED']
    code: Code
    phase: Phase
    exception_type: str | None = Field(default=None, pattern=r'^[A-Za-z_][A-Za-z0-9_]{0,79}$')
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def coherent(self):
        allowed = ({'BEFORE_OBSERVATION', 'AFTER_OBSERVATION'} if self.code == 'SUBJECT_CHANGED'
                   else {'TRANSPORT', 'QUEUE'} if self.code in {'TRANSPORT_TIMEOUT', 'TRANSPORT_FAILED'}
                   else {'VALIDATION'} if self.code in {'INVALID_OUTCOME', 'NEGATIVE_RESULT'}
                   else {'SUPERSESSION'} if self.code in {'SUPERSESSION_EXHAUSTED', 'CLOCK_REGRESSION'}
                   else {'OBSERVATION'})
        if ((self.outcome == 'SUPERSEDED') != (self.code == 'SUBJECT_CHANGED')
                or self.phase not in allowed):
            raise ValueError('observer failure classification is contradictory')
        return self

    def safe_detail(self):
        return (self.code+' · phase '+self.phase
                +(' · '+self.exception_type if self.exception_type else '')
                +' · diagnostic '+self.fingerprint)


class Attempt(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    schema_version: Literal['sentinel.financial-observer-attempt/1'] = Field(alias='schema')
    attempt_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    subject_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    outcome: Literal['QUEUED', 'RUNNING', 'COMPLETED', 'VERIFIED', 'SUPERSEDED', 'FAILED']
    admitted_at: datetime
    deadline: datetime
    work_started_at: datetime | None = None
    work_deadline: datetime | None = None
    completed_at: datetime | None = None
    supersession_started_at: datetime | None = None
    supersession_deadline: datetime | None = None
    diagnostic: Failure | None = None
    latched_failure: Failure | None = None

    @model_validator(mode='after')
    def clocks(self):
        values = (self.admitted_at, self.deadline, self.work_started_at,
                  self.work_deadline, self.completed_at,
                  self.supersession_started_at, self.supersession_deadline)
        if any(value is not None and value.utcoffset() != timedelta(0) for value in values):
            raise ValueError('observer attempt clocks require UTC')
        if not timedelta(0) < self.deadline-self.admitted_at <= timedelta(seconds=SUPERSESSION_SECONDS):
            raise ValueError('observer attempt deadline is outside its original budget')
        if ((self.work_started_at is None) != (self.work_deadline is None)
                or self.work_started_at is not None and not (
                    self.work_started_at < self.work_deadline <= self.deadline)):
            raise ValueError('observer work deadline is outside its original budget')
        if ((self.supersession_started_at is None) != (self.supersession_deadline is None)
                or self.supersession_started_at is not None
                and self.supersession_deadline-self.supersession_started_at != timedelta(seconds=SUPERSESSION_SECONDS)):
            raise ValueError('observer supersession deadline changed')
        if self.latched_failure is not None and self.latched_failure.outcome != 'FAILED':
            raise ValueError('superseded work is not a latched failure')
        return self


def failure(code: Code, phase: Phase, *, error: Exception | None = None,
            material: bytes | None = None) -> Failure:
    kind = type(error).__name__ if error is not None else None
    if kind is not None and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', kind) is None:
        kind = 'Exception'
    # Only the digest leaves this boundary. No exception argument, SQL, DSN,
    # traceback or account payload is serialized into a diagnostic.
    if material is not None and (not isinstance(material, bytes) or len(material) > MAX_FINGERPRINT_BYTES):
        raise ValueError('observer diagnostic fingerprint material exceeds bound')
    digest = hashlib.sha256(json.dumps([code, phase, kind,
        str(error)[:1000] if error is not None else None], separators=(',', ':')).encode())
    if material is not None:
        digest.update(b'\0'+material)
    return Failure.model_validate(dict(schema=SCHEMA,
        outcome='SUPERSEDED' if code == 'SUBJECT_CHANGED' else 'FAILED',
        code=code, phase=phase, exception_type=kind, fingerprint=digest.hexdigest()))


def classify(error: Exception, *, transport=False,
             phase: Literal['TRANSPORT', 'QUEUE'] = 'TRANSPORT') -> Failure:
    if transport:
        return failure('TRANSPORT_TIMEOUT' if isinstance(error, TimeoutError)
                       else 'TRANSPORT_FAILED', phase, error=error)
    if isinstance(error, ObservationSuperseded):
        return failure('SUBJECT_CHANGED', error.phase, error=error)
    from psycopg.errors import LockNotAvailable, QueryCanceled
    from sentinel.feed.publication import CorpusLockUnavailable
    if isinstance(error, QueryCanceled):
        code = 'READ_TIMEOUT'
    elif isinstance(error, LockNotAvailable):
        code = 'READ_LOCK_UNAVAILABLE'
    elif isinstance(error, CorpusLockUnavailable):
        code = 'CORPUS_LOCK_UNAVAILABLE'
    elif isinstance(error, TimeoutError):
        code = 'OBSERVATION_TIMEOUT'
    elif isinstance(error, ValueError):
        code = 'VALIDATION_REFUSED'
    else:
        code = 'OBSERVER_EXCEPTION'
    return failure(code, 'OBSERVATION', error=error)


def capture(operation, *args):
    """Successful payloads are unchanged; capture failures inside the child."""
    try:
        return operation(*args)
    except Exception as error:
        return classify(error).model_dump(mode='json', by_alias=True)


def decode(value) -> Failure:
    if (not isinstance(value, dict)
            or len(json.dumps(value, allow_nan=False).encode()) > MAX_BYTES):
        raise ValueError('observer failure envelope is malformed or oversized')
    return Failure.model_validate(value)
