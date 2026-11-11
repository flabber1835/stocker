"""Explicit backed-PAPER maintenance client of the common WAL proof owner.

No broker transport, continuity admission or restore qualification is provided.
The CLI owns its database session; ordinary runtime callers keep nonblocking
admission and the existing physical-clock-bound five-minute proof policy.
"""
from __future__ import annotations

import argparse
import math
import os
import re
import signal
import time
from dataclasses import dataclass, field
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sentinel import backup_integrity_reuse as reuse
from sentinel import backup_runtime_authority as authority


PREFIX = 'shared_integrity_proof:'
FAILURE_PREFIX = 'shared_integrity_failure:'


class FailureCleanup(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    proof_lock: Literal['NOT_ACQUIRED', 'RELEASED', 'FAILED', 'UNKNOWN']
    worker_container: Literal['NOT_STARTED', 'NOT_OBSERVED', 'REMOVED', 'FAILED']


class FailureCause(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    type: Literal['BackupIntegrityBusy', 'BackupIntegrityProofExpired', 'BackupIntegritySelectionMoved', 'BackupRuntimeUnavailable',
        'BackupRuntimeRefused', 'BackupHorizonExceeded', 'PsycopgError', 'OSError', 'ValueError',
        'RuntimeError', 'TimeoutError', 'Refused', 'PROTOCOL', 'UNCLASSIFIED',
        'PsycopgOperationalError', 'PsycopgInterfaceError', 'PsycopgProgrammingError',
        'PsycopgDataError', 'PsycopgIntegrityError', 'PsycopgInternalError',
        'PsycopgNotSupportedError', 'PsycopgDatabaseError']
    sqlstate: str | None = Field(pattern=r'^[0-9A-Z]{5}$')
    errno: int | None = Field(ge=-(2**31), lt=2**31)


class FailureTiming(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    alarm_budget_seconds: int | None = Field(ge=1, le=540)
    alarm_fired: bool
    started_at: str
    failed_at: str

    @model_validator(mode='after')
    def clocks(self):
        clocks = [datetime.fromisoformat(v.replace('Z', '+00:00'))
                  for v in (self.started_at, self.failed_at)]
        if (any(c.utcoffset() is None or c.utcoffset().total_seconds() != 0 for c in clocks)
                or clocks[1] < clocks[0] or self.alarm_fired and self.alarm_budget_seconds is None):
            raise ValueError('invalid owner failure timing')
        return self


class MaintenanceFailure(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True, allow_inf_nan=False)
    schema: Literal['sentinel.maintenance-integrity-failure/2']
    origin: Literal['WORKER', 'HOST']
    code: Literal['BUSY', 'PROOF_WINDOW_EXPIRED', 'SELECTION_MOVED', 'POLICY_REFUSED', 'PHYSICAL_UNAVAILABLE',
                  'INTEGRITY_REFUSED', 'DATABASE_FAILURE', 'DEADLINE_EXCEEDED',
                  'TRANSPORT_FAILURE', 'PROTOCOL_FAILURE', 'INTERNAL_FAILURE']
    retryable: bool
    stage: Literal['CONNECT', 'ADMISSION', 'OWNER_WAIT', 'PROOF', 'RESULT', 'LOCK_RELEASE',
                   'HOST_POLICY', 'HOST_IMAGE', 'HOST_POSTGRES', 'HOST_WORKER',
                   'HOST_VALIDATE', 'HOST_CLEANUP']
    cause_type: Literal['BackupIntegrityBusy', 'BackupIntegrityProofExpired', 'BackupIntegritySelectionMoved', 'BackupRuntimeUnavailable',
                        'BackupRuntimeRefused', 'BackupHorizonExceeded', 'PsycopgError', 'OSError',
                        'ValueError', 'RuntimeError', 'TimeoutError', 'Refused', 'PROTOCOL', 'UNCLASSIFIED']
    elapsed_seconds: float = Field(ge=0, le=3600)
    owner_wait_seconds: float = Field(ge=0, le=3600)
    proof_seconds: float = Field(ge=0, le=3600)
    proof_completed_uptime: float | None
    proof_observed_uptime: float | None
    cleanup: FailureCleanup
    exception_chain: list[FailureCause] = Field(min_length=1, max_length=4)
    cleanup_exception_chain: list[FailureCause] = Field(max_length=4)
    timing: FailureTiming

    @model_validator(mode='after')
    def coherent_failure(self):
        cleanup = self.cleanup
        if (max(self.owner_wait_seconds, self.proof_seconds) > self.elapsed_seconds+.001
                or self.origin == 'WORKER' and cleanup.worker_container != 'NOT_OBSERVED'
                or self.origin == 'HOST' and cleanup.worker_container == 'NOT_OBSERVED'):
            raise ValueError('invalid failure timing or cleanup origin')
        clocks = (self.proof_completed_uptime, self.proof_observed_uptime)
        if self.code == 'PROOF_WINDOW_EXPIRED':
            if (self.cause_type != 'BackupIntegrityProofExpired'
                    or any(t is None or t < 0 for t in clocks) or clocks[1]-clocks[0] < 300):
                raise ValueError('failure lacks actual original-clock expiry')
        elif clocks != (None, None):
            raise ValueError('failure invented proof clocks')
        if self.code == 'BUSY' and self.cause_type != 'BackupIntegrityBusy':
            raise ValueError('failure lacks actual owner contention')
        if self.code == 'SELECTION_MOVED' and self.cause_type != 'BackupIntegritySelectionMoved':
            raise ValueError('failure lacks proved selection movement')
        stages = {'BUSY': {'OWNER_WAIT', 'PROOF'}, 'PROOF_WINDOW_EXPIRED': {'PROOF', 'RESULT'},
                  'SELECTION_MOVED': {'RESULT'}}
        if (self.origin == 'WORKER' and self.stage.startswith('HOST_')
                or self.code in stages and (self.stage not in stages[self.code]
                    or self.exception_chain[0].type != self.cause_type)):
            raise ValueError('original failure cause or stage contradicts its code')
        retry = (self.code in {'BUSY', 'PROOF_WINDOW_EXPIRED', 'SELECTION_MOVED'}
            and cleanup.proof_lock in {'NOT_ACQUIRED', 'RELEASED'}
            and (self.origin == 'WORKER' or cleanup.worker_container == 'REMOVED'))
        if self.retryable != retry:
            raise ValueError('failure retry classification differs')
        return self


@dataclass
class _Trace:
    started: float = field(default_factory=time.monotonic)
    stage: str = 'CONNECT'
    phase_started: float = field(default_factory=time.monotonic)
    wait: float = 0.
    proof: float = 0.
    lock_cleanup: str = 'NOT_ACQUIRED'
    primary: BaseException | None = None
    failure_stage: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    failed_at: str | None = None
    alarm_budget_seconds: int | None = None
    alarm_fired: bool = False
    cleanup_error: BaseException | None = None

    def mark(self, stage):
        now = time.monotonic()
        if self.stage == 'OWNER_WAIT': self.wait += now-self.phase_started
        if self.stage == 'PROOF': self.proof += now-self.phase_started
        self.stage, self.phase_started = stage, now

    def remember(self, exc):
        if self.primary is None:
            self.primary, self.failure_stage = exc, self.stage
            self.failed_at = datetime.now(timezone.utc).isoformat()
            self.mark('FAILED')
        elif exc is not self.primary:
            self.cleanup_error = exc


@contextmanager
def _capture_failure(trace):
    try:
        yield
    except BaseException as exc:
        trace.remember(exc)
        raise


def _alarm(trace):
    trace.alarm_fired = True
    exc = TimeoutError('maintenance integrity worker deadline exceeded')
    trace.remember(exc)
    raise exc


def failure_record(exc, trace):
    """Describe the original exception by closed type, never its private text."""
    import psycopg
    original = trace.primary or exc
    stage = trace.failure_stage or trace.stage
    code, cause, clocks = 'INTERNAL_FAILURE', 'UNCLASSIFIED', (None, None)
    if isinstance(original, authority.BackupIntegrityBusy):
        code, cause = 'BUSY', 'BackupIntegrityBusy'
    elif isinstance(original, authority.BackupIntegrityProofExpired):
        code, cause = 'PROOF_WINDOW_EXPIRED', 'BackupIntegrityProofExpired'
        clocks = (original.completed_uptime, original.observed_uptime)
    elif isinstance(original, authority.BackupIntegritySelectionMoved):
        code, cause = 'SELECTION_MOVED', 'BackupIntegritySelectionMoved'
    elif isinstance(original, authority.BackupHorizonExceeded):
        code, cause = 'INTEGRITY_REFUSED', 'BackupHorizonExceeded'
    elif isinstance(original, authority.BackupRuntimeRefused):
        code = 'POLICY_REFUSED' if stage == 'ADMISSION' else 'INTEGRITY_REFUSED'
        cause = 'BackupRuntimeRefused'
    elif isinstance(original, authority.BackupRuntimeUnavailable):
        code, cause = 'PHYSICAL_UNAVAILABLE', 'BackupRuntimeUnavailable'
    elif isinstance(original, psycopg.Error): code, cause = 'DATABASE_FAILURE', 'PsycopgError'
    elif isinstance(original, TimeoutError): code, cause = 'DEADLINE_EXCEEDED', 'TimeoutError'
    elif isinstance(original, OSError): code, cause = 'DATABASE_FAILURE', 'OSError'
    elif isinstance(original, ValueError): cause = 'ValueError'
    elif isinstance(original, RuntimeError): cause = 'RuntimeError'
    chain = _exception_chain(original)
    cleanup = trace.cleanup_error or (exc if exc is not original else None)
    now = time.monotonic()
    wait = trace.wait+(now-trace.phase_started if trace.stage == 'OWNER_WAIT' else 0)
    proof = trace.proof+(now-trace.phase_started if trace.stage == 'PROOF' else 0)
    return MaintenanceFailure.model_validate(dict(schema='sentinel.maintenance-integrity-failure/2',
        origin='WORKER', code=code, cause_type=cause, stage=stage,
        elapsed_seconds=now-trace.started, owner_wait_seconds=wait, proof_seconds=proof,
        proof_completed_uptime=clocks[0], proof_observed_uptime=clocks[1], exception_chain=chain,
        cleanup_exception_chain=_exception_chain(cleanup) if cleanup is not None else [],
        timing=dict(alarm_budget_seconds=trace.alarm_budget_seconds, alarm_fired=trace.alarm_fired,
            started_at=trace.started_at, failed_at=trace.failed_at or datetime.now(timezone.utc).isoformat()),
        cleanup=dict(proof_lock=trace.lock_cleanup, worker_container='NOT_OBSERVED'),
        retryable=code in {'BUSY', 'PROOF_WINDOW_EXPIRED', 'SELECTION_MOVED'}
            and trace.lock_cleanup in {'NOT_ACQUIRED', 'RELEASED'}))


def _exception_chain(original):
    import psycopg
    chain, seen, current = [], set(), original
    while current is not None and id(current) not in seen and len(chain) < 4:
        seen.add(id(current))
        kind = 'UNCLASSIFIED'
        for cls in (authority.BackupIntegrityBusy, authority.BackupIntegrityProofExpired,
                authority.BackupIntegritySelectionMoved,
                authority.BackupHorizonExceeded, authority.BackupRuntimeRefused,
                authority.BackupRuntimeUnavailable, psycopg.OperationalError, psycopg.InterfaceError,
                psycopg.ProgrammingError, psycopg.DataError, psycopg.IntegrityError,
                psycopg.InternalError, psycopg.NotSupportedError, psycopg.DatabaseError,
                psycopg.Error, TimeoutError, OSError, ValueError, RuntimeError):
            if isinstance(current, cls):
                kind = ('Psycopg'+cls.__name__) if issubclass(cls, psycopg.Error) else cls.__name__
                break
        state = getattr(current, 'sqlstate', None) if isinstance(current, psycopg.Error) else None
        number = getattr(current, 'errno', None) if isinstance(current, OSError) else None
        chain.append(dict(type=kind,
            sqlstate=state if type(state) is str and re.fullmatch(r'[0-9A-Z]{5}', state) else None,
            errno=number if type(number) is int and -(2**31) <= number < 2**31 else None))
        current = current.__cause__ or current.__context__
    return chain


class MaintenanceProof(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True, allow_inf_nan=False)
    schema: Literal['sentinel.maintenance-integrity/1']
    enabled: Literal[True]
    system_identifier: str = Field(pattern=r'^[1-9][0-9]{0,19}$')
    base_backup: str = Field(pattern=r'^base-[0-9]{8}T[0-9]{6}Z$')
    recoverable_from_wal: str = Field(pattern=r'^[0-9A-F]{24}$')
    recovery_marker_wal: str = Field(pattern=r'^[0-9A-F]{24}$')
    recoverable_through_wal: str = Field(pattern=r'^[0-9A-F]{24}$')
    wal_segments: int = Field(ge=1, le=1024)
    timeline_history: str | None
    wal_integrity: Literal['sha256-sidecar-v1']
    integrity_objects_hashed: int = Field(ge=0, le=2050)
    integrity_full_scrub: bool
    integrity_read_passes: Literal[0, 2]
    integrity_max_reuse_seconds: Literal[300]
    wal_segment_bytes: int
    integrity_completed_uptime: float = Field(ge=0)
    integrity_observed_uptime: float = Field(ge=0)

    @model_validator(mode='after')
    def coherent(self):
        size = self.wal_segment_bytes
        if not 1024**2 <= size <= 1024**3 or size & (size-1):
            raise ValueError('invalid WAL geometry')
        timeline = self.recoverable_from_wal[:8]
        per_log = 2**32 // size
        names = (self.recoverable_from_wal, self.recovery_marker_wal, self.recoverable_through_wal)
        indices = [int(n[8:16], 16)*per_log+int(n[16:], 16) for n in names]
        expected_history = None if timeline == '00000001' else timeline+'.history'
        objects = self.wal_segments + (self.timeline_history is not None)
        count = self.integrity_objects_hashed
        if (int(timeline, 16) < 1 or any(n[:8] != timeline or int(n[16:], 16) >= per_log for n in names)
                or not indices[0] <= indices[1] <= indices[2]
                or self.wal_segments != indices[2]-indices[0]+1
                or self.wal_segments*size > authority.RUNTIME_MAX_VERIFIED_BYTES
                or self.timeline_history != expected_history
                or count % 2 or count > 2*objects
                or self.integrity_read_passes != (2 if count else 0)
                or self.integrity_full_scrub and count != 2*objects
                or not 0 <= self.integrity_observed_uptime-self.integrity_completed_uptime < 300):
            raise ValueError('contradictory maintenance integrity proof')
        return self


def prove(conn, *, base_backup: str, system_identifier: str,
          wal_segment_bytes: int, observed_frontier: str, wait_seconds: float = 20,
          _trace: _Trace | None = None) -> MaintenanceProof:
    """Join existing ownership before work; never renew a hit's original clock."""
    trace = _trace or _Trace()
    trace.mark('ADMISSION')
    if (not reuse.selected() or not authority.enabled() or not conn.autocommit
            or type(wait_seconds) not in (int, float)
            or not math.isfinite(wait_seconds) or not 0 <= wait_seconds <= 20
            or type(wal_segment_bytes) is not int
            or not 1024**2 <= wal_segment_bytes <= 1024**3
            or wal_segment_bytes & (wal_segment_bytes-1)
            or type(base_backup) is not str or type(system_identifier) is not str
            or type(observed_frontier) is not str
            or re.fullmatch(r'base-[0-9]{8}T[0-9]{6}Z', base_backup) is None
            or re.fullmatch(r'[1-9][0-9]{0,19}', system_identifier) is None
            or re.fullmatch(r'[0-9A-F]{24}', observed_frontier) is None):
        raise authority.BackupRuntimeRefused('shared maintenance requires selected backed PAPER and an owned session')
    if (int(observed_frontier[:8], 16) < 1
            or int(observed_frontier[16:], 16) >= 2**32//wal_segment_bytes):
        raise authority.BackupRuntimeRefused('shared maintenance observed frontier geometry is invalid')
    deadline = time.monotonic()+wait_seconds
    acquired = False
    try:
        trace.mark('OWNER_WAIT')
        while True:
            acquired = conn.execute('SELECT pg_try_advisory_lock(%s)', (reuse.LOCK_KEY,)).fetchone() == (True,)
            if acquired:
                trace.lock_cleanup = 'UNKNOWN'
                break
            if time.monotonic() >= deadline:
                raise authority.BackupIntegrityBusy('shared maintenance proof owner wait expired')
            time.sleep(min(.1, max(0, deadline-time.monotonic())))
        trace.mark('PROOF')
        with conn.transaction(), _capture_failure(trace):
            # The inner owner reacquires this session lock and releases exactly
            # its own count. The outer count serializes the entire admission.
            result = authority.require(conn, operation='maintenance common WAL integrity',
                                       allow_continuity=False, maintenance_refresh=True)
            trace.mark('RESULT')
            size = conn.execute("SELECT pg_size_bytes(current_setting('wal_segment_size'))").fetchone()[0]
            if (result.get('enabled') is not True or result.get('system_identifier') != system_identifier
                    or size != wal_segment_bytes
                    or result.get('recoverable_through_wal', '')[:8] != observed_frontier[:8]
                    or result.get('recoverable_through_wal', '') < observed_frontier):
                raise authority.BackupRuntimeRefused('shared maintenance proof differs from selected media')
            current_base = result.get('base_backup')
            if (type(current_base) is not str
                    or re.fullmatch(r'base-[0-9]{8}T[0-9]{6}Z', current_base) is None):
                raise authority.BackupRuntimeRefused('shared maintenance returned malformed base identity')
            if current_base != base_backup:
                raise authority.BackupIntegritySelectionMoved('proved runtime base selection moved')
            owner = reuse.Owner(conn, dict(system_id=system_identifier, base=base_backup,
                start=result['recoverable_from_wal'], segment_size=size))
            if owner.proof is None and owner.expired_window is not None:
                raise authority.BackupIntegrityProofExpired(
                    completed_uptime=owner.expired_window[0], observed_uptime=owner.expired_window[1])
            if owner.proof is None or owner.proof.end != result['recoverable_through_wal']:
                raise authority.BackupRuntimeRefused('shared maintenance completed receipt unavailable')
            return MaintenanceProof.model_validate(dict(result,
                schema='sentinel.maintenance-integrity/1', wal_segment_bytes=size,
                integrity_completed_uptime=owner.proof.completed_uptime,
                integrity_observed_uptime=owner.uptime))
    except BaseException as exc:
        trace.remember(exc)
        raise
    finally:
        if acquired:
            try:
                if conn.execute('SELECT pg_advisory_unlock(%s)', (reuse.LOCK_KEY,)).fetchone() != (True,):
                    raise authority.BackupRuntimeRefused('shared maintenance proof ownership lost')
                trace.lock_cleanup = 'RELEASED'
            except BaseException as exc:
                trace.lock_cleanup = 'FAILED'
                if trace.primary is None: trace.mark('LOCK_RELEASE')
                trace.remember(exc)
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--base-backup', required=True)
    parser.add_argument('--system-identifier', required=True)
    parser.add_argument('--wal-segment-bytes', required=True, type=int)
    parser.add_argument('--observed-frontier', required=True)
    parser.add_argument('--timeout-seconds', type=int, default=540)
    args = parser.parse_args()
    budget = args.timeout_seconds
    del args.timeout_seconds
    trace = _Trace()
    import psycopg
    def expired(_signum, _frame):
        _alarm(trace)
    signal.signal(signal.SIGALRM, expired)
    if not 1 <= budget <= 540:
        record = failure_record(ValueError('worker transport budget invalid'), trace)
        parser.exit(4, FAILURE_PREFIX+record.model_dump_json()+'\n')
    trace.alarm_budget_seconds = budget
    signal.alarm(budget)
    try:
        with psycopg.connect(os.environ['SENTINEL_DATABASE_URL'], autocommit=True,
                             connect_timeout=5, options='-c statement_timeout=120000') as conn:
            result = prove(conn, **vars(args), _trace=trace)
        print(result.model_dump_json())
    except Exception as exc:
        try:
            record = failure_record(exc, trace)
        except Exception:
            # Even a malformed third-party exception/clock cannot print its
            # private repr through a diagnostic-construction traceback.
            record = MaintenanceFailure.model_validate(dict(
                schema='sentinel.maintenance-integrity-failure/2', origin='WORKER',
                code='INTERNAL_FAILURE', retryable=False, stage='CONNECT', cause_type='UNCLASSIFIED',
                elapsed_seconds=0., owner_wait_seconds=0., proof_seconds=0.,
                proof_completed_uptime=None, proof_observed_uptime=None,
                cleanup=dict(proof_lock=trace.lock_cleanup, worker_container='NOT_OBSERVED'),
                exception_chain=[dict(type='UNCLASSIFIED', sqlstate=None, errno=None)],
                cleanup_exception_chain=[],timing=dict(alarm_budget_seconds=trace.alarm_budget_seconds,
                    alarm_fired=trace.alarm_fired,started_at=trace.started_at,
                    failed_at=trace.failed_at or datetime.now(timezone.utc).isoformat())))
        parser.exit(75 if record.retryable else 4, FAILURE_PREFIX+record.model_dump_json()+'\n')
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    main()
