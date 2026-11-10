#!/usr/bin/env python3
"""Broker-free host transport for explicitly selected common WAL integrity."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid

from sentinel_backup_maintenance import COMPOSE, Refused, runtime_image
from sentinel_backup_integrity_report import FAILURE_PREFIX, failure, parse_failure, validate
from sentinel_maintenance_process import run_bounded

PAPER_URL = 'https://paper-api.alpaca.markets'
MODE = 'OWNER_AUTHORIZED_FUNCTION_FIRST_V1'
PREFIX = 'shared_integrity_proof:'


class IntegrityFailure(Refused):
    def __init__(self, record):
        self.record = record
        super().__init__('common integrity '+record['code'])


def _quiet_run(command, *, timeout=120):
    result = run_bounded(command, timeout=timeout, private_group=False)
    if result.returncode == 124:
        raise TimeoutError('common integrity preflight deadline exceeded')
    if result.returncode:
        raise Refused('common integrity preflight command failed')
    return result.stdout.strip()


def environment(values):
    """Project only the identities needed by the existing runtime owner."""
    required = ('SENTINEL_POSTGRES_PASSWORD', 'SENTINEL_PUBLICATION_RECEIPT_KEY',
                'SENTINEL_LOCAL_PAPER_ACCOUNT_ID')
    if (values.get('ALPACA_BASE_URL', PAPER_URL).rstrip('/') != PAPER_URL
            or values.get('SENTINEL_LOCAL_PAPER_MODE') != MODE
            or values.get('SENTINEL_LOCAL_PAPER_BACKUP_POLICY') != 'REQUIRED_V1'
            or values.get('SENTINEL_RUNTIME_BACKUP_AUTHORITY', 'REQUIRED_V1') != 'REQUIRED_V1'
            or any(not values.get(k) for k in required)
            or len(values['SENTINEL_PUBLICATION_RECEIPT_KEY']) < 32
            or re.fullmatch(r'PA[A-Za-z0-9]+', values['SENTINEL_LOCAL_PAPER_ACCOUNT_ID']) is None):
        raise Refused('common integrity requires explicit backed PAPER policy')
    password = values['SENTINEL_POSTGRES_PASSWORD']
    if any(c in password for c in ':?/@#[]%') or any(c.isspace() for c in password):
        raise Refused('common integrity database password is not safely representable')
    return dict(SENTINEL_DATABASE_URL='postgresql://sentinel:'+password+'@127.0.0.1:5432/sentinel',
        SENTINEL_PUBLICATION_RECEIPT_KEY=values['SENTINEL_PUBLICATION_RECEIPT_KEY'],
        SENTINEL_LOCAL_PAPER_ACCOUNT_ID=values['SENTINEL_LOCAL_PAPER_ACCOUNT_ID'],
        SENTINEL_LOCAL_PAPER_MODE=MODE, SENTINEL_LOCAL_PAPER_BACKUP_POLICY='REQUIRED_V1',
        SENTINEL_RUNTIME_BACKUP_AUTHORITY='REQUIRED_V1', ALPACA_BASE_URL=PAPER_URL)


def observe(args, *, values=None, runner=None, bounded=run_bounded):
    values = os.environ if values is None else values
    started = time.monotonic()
    budget = getattr(args, 'timeout_seconds', 580)
    deadline = started+budget if type(budget) is int and 0 <= budget <= 600 else started
    def remaining(maximum):
        value = min(maximum, deadline-time.monotonic()-10)
        if value <= 0:
            raise TimeoutError('common integrity transport budget exhausted')
        return value
    runner = (lambda command: _quiet_run(command, timeout=remaining(120))) if runner is None else runner
    stage, record, name, transport = 'HOST_POLICY', None, None, None
    proof = None
    try:
        if type(budget) is not int or not 0 <= budget <= 600:
            raise Refused('common integrity transport budget is invalid')
        remaining(120)
        child = environment(values)
        stage = 'HOST_IMAGE'
        image = runtime_image(runner)
        stage = 'HOST_POSTGRES'
        container = runner(COMPOSE+['ps', '-q', 'sentinel-postgres'])
        if re.fullmatch(r'[0-9a-f]{64}', container) is None:
            raise Refused('common integrity requires one canonical PostgreSQL container')
        state = runner(['docker', 'inspect', '--format', '{{.Id}} {{.State.Running}}', container])
        if state != container+' true':
            raise Refused('common integrity PostgreSQL process changed')
        stage = 'HOST_WORKER'
        wait = remaining(560)
        if wait <= 5:
            raise TimeoutError('common integrity worker budget exhausted')
        name = 'sentinel-maintenance-integrity-'+uuid.uuid4().hex
        command = ['docker', 'run', '--rm', '--name', name, '--network', 'container:'+container,
            '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--memory', '512m', '--cpus', '1', '--pids-limit', '64']
        for key in child:
            command += ['--env', key]
        command += ['--entrypoint', 'python', image, '-m', 'sentinel.backup_maintenance_integrity',
            '--base-backup', args.base_backup, '--system-identifier', args.system_identifier,
            '--wal-segment-bytes', str(args.wal_segment_bytes), '--observed-frontier', args.observed_frontier]
        transport = {key: values[key] for key in ('PATH', 'HOME', 'LANG') if key in values}
        transport.update(child)
        stage = 'HOST_WORKER'
        command += ['--timeout-seconds', str(min(540, max(1, int(wait)-5)))]
        result = bounded(command, env=transport, timeout=wait)
        if result.returncode:
            try:
                record = parse_failure(getattr(result, 'stderr', ''),
                    returncode=result.returncode, origin='WORKER')
            except (TypeError, ValueError, KeyError):
                record = failure(origin='HOST', code='TRANSPORT_FAILURE', stage=stage,
                    cause_type='TimeoutError' if result.returncode == 124 else 'PROTOCOL',
                    elapsed_seconds=time.monotonic()-started, worker_container='FAILED')
            raise IntegrityFailure(record)
        stage = 'HOST_VALIDATE'
        if len(result.stdout) > 16384:
            raise ValueError('common integrity evidence exceeds output bound')
        try:
            proof = json.loads(result.stdout)
        except (TypeError, ValueError):
            raise Refused('common integrity worker returned malformed evidence') from None
        validate(proof)
        if (proof.get('schema') != 'sentinel.maintenance-integrity/1'
                or proof.get('base_backup') != args.base_backup
                or proof.get('system_identifier') != args.system_identifier
                or proof.get('wal_segment_bytes') != args.wal_segment_bytes
                or proof['recoverable_through_wal'][:8] != args.observed_frontier[:8]
                or proof['recoverable_through_wal'] < args.observed_frontier):
            raise Refused('common integrity worker selected another physical horizon')
    except IntegrityFailure:
        pass
    except Exception as exc:
        record = failure(origin='HOST', code='DEADLINE_EXCEEDED' if isinstance(exc, TimeoutError)
            else 'POLICY_REFUSED' if isinstance(exc, Refused)
            and stage in {'HOST_POLICY', 'HOST_IMAGE', 'HOST_POSTGRES'} else 'PROTOCOL_FAILURE',
            stage=stage, cause_type='TimeoutError' if isinstance(exc, TimeoutError)
                else 'Refused' if isinstance(exc, Refused) else 'ValueError'
                if isinstance(exc, ValueError) else 'UNCLASSIFIED',
            elapsed_seconds=time.monotonic()-started, worker_container='NOT_STARTED')
    finally:
        # This unique worker owns no broker or caller SQL work. A lost/expired
        # Docker client must not leave its proof process or session lock alive.
        if name is not None:
            removed = False
            try:
                cleanup_wait = min(5, max(.001, deadline-time.monotonic()))
                result = bounded(['docker', 'rm', '-f', name], env=transport, timeout=cleanup_wait)
                removed = result.returncode == 0
                if not removed:
                    cleanup_wait = min(5, max(.001, deadline-time.monotonic()))
                    result = bounded(['docker', 'ps', '-a', '--filter', 'name=^/'+name+'$',
                        '--format', '{{.ID}}'], env=transport, timeout=cleanup_wait)
                    removed = result.returncode == 0 and result.stdout.strip() == ''
            except Exception:
                pass
            if record is not None:
                record = failure(**{key: record[key] for key in ('code', 'stage', 'cause_type',
                    'elapsed_seconds', 'owner_wait_seconds', 'proof_seconds',
                    'proof_completed_uptime', 'proof_observed_uptime', 'exception_chain')}, origin='HOST',
                    proof_lock=record['cleanup']['proof_lock'],
                    worker_container='REMOVED' if removed else 'FAILED')
            elif not removed:
                record = failure(origin='HOST', code='TRANSPORT_FAILURE', stage='HOST_CLEANUP',
                    cause_type='PROTOCOL', elapsed_seconds=time.monotonic()-started,
                    proof_lock='RELEASED', worker_container='FAILED')
    if record is not None:
        raise IntegrityFailure(record)
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--base-backup', required=True)
    parser.add_argument('--system-identifier', required=True)
    parser.add_argument('--wal-segment-bytes', type=int, required=True)
    parser.add_argument('--observed-frontier', required=True)
    parser.add_argument('--timeout-seconds', type=int, default=580)
    args = parser.parse_args()
    try:
        proof = observe(args)
        size = proof['wal_segment_bytes']; start = proof['recoverable_from_wal']
        start_index = int(start[8:16], 16)*(2**32//size)+int(start[16:], 16)
        print('wal_chain_ready:true start_index='+str(start_index)
              +' end='+proof['recoverable_through_wal']+' segments='+str(proof['wal_segments'])
              +' marker='+proof['recovery_marker_wal']+' history='+(proof['timeline_history'] or 'none'))
        print(PREFIX+json.dumps(proof, sort_keys=True, separators=(',', ':'), allow_nan=False))
    except IntegrityFailure as exc:
        print(FAILURE_PREFIX+json.dumps(exc.record, sort_keys=True, separators=(',', ':'), allow_nan=False), file=sys.stderr)
        return 75 if exc.record['retryable'] else 4
    except Exception:
        record = failure(origin='HOST', code='INTERNAL_FAILURE', stage='HOST_VALIDATE', cause_type='UNCLASSIFIED')
        print(FAILURE_PREFIX+json.dumps(record, sort_keys=True, separators=(',', ':')), file=sys.stderr)
        return 4
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
