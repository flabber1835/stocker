#!/usr/bin/env python3
"""Broker-free host transport for explicitly selected common WAL integrity."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid

from sentinel_backup_maintenance import COMPOSE, Refused, run, runtime_image
from sentinel_backup_integrity_report import validate
from sentinel_maintenance_process import run_bounded

PAPER_URL = 'https://paper-api.alpaca.markets'
MODE = 'OWNER_AUTHORIZED_FUNCTION_FIRST_V1'
PREFIX = 'shared_integrity_proof:'


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


def observe(args, *, values=None, runner=run, bounded=run_bounded):
    values = os.environ if values is None else values
    child = environment(values)
    image = runtime_image(runner)
    container = runner(COMPOSE+['ps', '-q', 'sentinel-postgres'])
    if re.fullmatch(r'[0-9a-f]{64}', container) is None:
        raise Refused('common integrity requires one canonical PostgreSQL container')
    state = runner(['docker', 'inspect', '--format', '{{.Id}} {{.State.Running}}', container])
    if state != container+' true':
        raise Refused('common integrity PostgreSQL process changed')
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
    try:
        result = bounded(command, env=transport, timeout=560)
        if result.returncode or len(result.stdout) > 16384:
            raise Refused('common integrity worker failed')
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
        return proof
    finally:
        # This unique worker owns no broker or caller SQL work. A lost/expired
        # Docker client must not leave its proof process or session lock alive.
        bounded(['docker', 'rm', '-f', name], env=transport, timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--base-backup', required=True)
    parser.add_argument('--system-identifier', required=True)
    parser.add_argument('--wal-segment-bytes', type=int, required=True)
    parser.add_argument('--observed-frontier', required=True)
    args = parser.parse_args()
    try:
        proof = observe(args)
        size = proof['wal_segment_bytes']; start = proof['recoverable_from_wal']
        start_index = int(start[8:16], 16)*(2**32//size)+int(start[16:], 16)
        print('wal_chain_ready:true start_index='+str(start_index)
              +' end='+proof['recoverable_through_wal']+' segments='+str(proof['wal_segments'])
              +' marker='+proof['recovery_marker_wal']+' history='+(proof['timeline_history'] or 'none'))
        print(PREFIX+json.dumps(proof, sort_keys=True, separators=(',', ':'), allow_nan=False))
    except Exception as exc:
        print('REFUSED: common integrity worker unavailable: '+type(exc).__name__, file=sys.stderr)
        return 4
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
