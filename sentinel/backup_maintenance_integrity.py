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
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sentinel import backup_integrity_reuse as reuse
from sentinel import backup_runtime_authority as authority


PREFIX = 'shared_integrity_proof:'


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
          wal_segment_bytes: int, observed_frontier: str, wait_seconds: float = 20) -> MaintenanceProof:
    """Join existing ownership before work; never renew a hit's original clock."""
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
        while True:
            acquired = conn.execute('SELECT pg_try_advisory_lock(%s)', (reuse.LOCK_KEY,)).fetchone() == (True,)
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise authority.BackupRuntimeUnavailable('shared maintenance proof owner wait expired')
            time.sleep(min(.1, max(0, deadline-time.monotonic())))
        with conn.transaction():
            # The inner owner reacquires this session lock and releases exactly
            # its own count. The outer count serializes the entire admission.
            result = authority.require(conn, operation='maintenance common WAL integrity',
                                       allow_continuity=False, base_backup=None)
            size = conn.execute("SELECT pg_size_bytes(current_setting('wal_segment_size'))").fetchone()[0]
            if (result.get('enabled') is not True or result.get('system_identifier') != system_identifier
                    or result.get('base_backup') != base_backup or size != wal_segment_bytes
                    or result.get('recoverable_through_wal', '')[:8] != observed_frontier[:8]
                    or result.get('recoverable_through_wal', '') < observed_frontier):
                raise authority.BackupRuntimeRefused('shared maintenance proof differs from selected media')
            owner = reuse.Owner(conn, dict(system_id=system_identifier, base=base_backup,
                start=result['recoverable_from_wal'], segment_size=size))
            if owner.proof is None or owner.proof.end != result['recoverable_through_wal']:
                raise authority.BackupRuntimeRefused('shared maintenance completed receipt unavailable')
            return MaintenanceProof.model_validate(dict(result,
                schema='sentinel.maintenance-integrity/1', wal_segment_bytes=size,
                integrity_completed_uptime=owner.proof.completed_uptime,
                integrity_observed_uptime=owner.uptime))
    finally:
        if acquired:
            if conn.execute('SELECT pg_advisory_unlock(%s)', (reuse.LOCK_KEY,)).fetchone() != (True,):
                raise authority.BackupRuntimeRefused('shared maintenance proof ownership lost')


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--base-backup', required=True)
    parser.add_argument('--system-identifier', required=True)
    parser.add_argument('--wal-segment-bytes', required=True, type=int)
    parser.add_argument('--observed-frontier', required=True)
    args = parser.parse_args()
    import psycopg
    def expired(_signum, _frame):
        raise TimeoutError('maintenance integrity worker deadline exceeded')
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(540)
    try:
        with psycopg.connect(os.environ['SENTINEL_DATABASE_URL'], autocommit=True,
                             connect_timeout=5, options='-c statement_timeout=120000') as conn:
            result = prove(conn, **vars(args))
        print(result.model_dump_json())
    except Exception as exc:
        # Driver messages can contain connection details. Export only a closed
        # refusal class; the host retains its existing status failure reason.
        parser.exit(4, 'shared maintenance integrity refused: '+type(exc).__name__+'\n')
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    main()
