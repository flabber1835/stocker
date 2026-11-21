"""One atomic publication for a verified base and its original maintenance attempt."""
from __future__ import annotations

import json
import re


def progress_sql(progress, *, base_proof=None):
    payload = json.dumps(progress, sort_keys=True, separators=(',', ':')).replace("'", "''")
    base_cte = dependency = ''
    if base_proof is not None:
        base_payload = json.dumps(base_proof, sort_keys=True, separators=(',', ':')).replace("'", "''")
        base_cte = ("base_evidence AS (SELECT '" + base_payload + "'::jsonb AS proof), "
            "base_recorded AS (INSERT INTO sentinel_backup_evidence(kind,evidence_sha256,proof) "
            "SELECT 'BASE_BACKUP',encode(sha256(convert_to(proof::text,'UTF8')),'hex'),proof "
            "FROM base_evidence WHERE clock_timestamp()>=to_timestamp(" + str(progress['started_at']) + ") "
            "AND clock_timestamp()<to_timestamp(" + str(progress['deadline']) + ") RETURNING seq), ")
        dependency = ' CROSS JOIN base_recorded'
    return ("WITH evidence AS (SELECT '" + payload + "'::jsonb AS proof), " + base_cte + "recorded AS ("
        "INSERT INTO sentinel_backup_evidence(kind,evidence_sha256,proof) "
        "SELECT 'MAINTENANCE_PROGRESS',encode(sha256(convert_to(proof::text,'UTF8')),'hex'),proof "
        "FROM evidence" + dependency + " RETURNING proof) SELECT proof::text FROM recorded")


def validate_progress(original):
    fields = {'schema', 'attempt', 'started_at', 'deadline', 'system_identifier',
              'image', 'predecessor_base', 'base_backup', 'phase'}
    base = r'base-[0-9]{8}T[0-9]{6}Z'
    if (not isinstance(original, dict) or set(original) != fields
            or any(type(original[k]) is not str for k in fields-{'started_at','deadline'})
            or original['schema'] != 'sentinel.backup-maintenance-progress/1'
            or original['phase'] != 'BASE_BACKUP'
            or not re.fullmatch('[a-f0-9]{32}', str(original['attempt']))
            or not re.fullmatch(base, str(original['base_backup']))
            or not re.fullmatch(r'[1-9][0-9]{0,19}', str(original['system_identifier']))
            or original['base_backup'] != original['predecessor_base']
            or not re.fullmatch(r'(?:sha256:[a-f0-9]{64}|[A-Za-z0-9][A-Za-z0-9._/:-]*@sha256:[a-f0-9]{64})', str(original['image']))
            or type(original['started_at']) is not int or type(original['deadline']) is not int
            or original['started_at'] < 0
            or not 0 < original['deadline'] - original['started_at'] <= 3600
            ):
        raise ValueError('verified base transition identity is invalid')
    return original


def base_transition_sql(original, proof):
    validate_progress(original)
    base = r'base-[0-9]{8}T[0-9]{6}Z'
    if (not isinstance(proof, dict)
            or proof.get('schema') != 'sentinel.verified-base/1'
            or proof.get('physical_verified') is not True
            or proof.get('system_identifier') != original['system_identifier']
            or not re.fullmatch(r'[1-9][0-9]{0,19}', str(proof.get('system_identifier', '')))
            or not re.fullmatch(base, str(proof.get('base_backup', '')))
            or proof['base_backup'] == original['predecessor_base']):
        raise ValueError('verified base transition identity is invalid')
    proof_fields = {'schema', 'physical_verified', 'metadata_sha256', 'base_backup',
                    'marker', 'marker_lsn', 'marker_wal', 'system_identifier',
                    'xid8_before', 'xid8_after'}
    if (set(proof) != proof_fields
            or any(not isinstance(proof[k], str) for k in proof_fields - {'physical_verified'})
            or not re.fullmatch('[a-f0-9]{64}', proof['metadata_sha256'])
            or not re.fullmatch(r'sentinel-backup-[0-9]{8}T[0-9]{6}Z-[0-9]+', proof['marker'])
            or not re.fullmatch('[0-9A-F]+/[0-9A-F]+', proof['marker_lsn'])
            or not re.fullmatch('[0-9A-F]{24}', proof['marker_wal'])
            or any(not re.fullmatch('[0-9]+', proof[k]) for k in ('xid8_before', 'xid8_after'))
            or int(proof['xid8_before']) > int(proof['xid8_after'])
            or int(proof['xid8_before']) >> 32 != int(proof['xid8_after']) >> 32):
        raise ValueError('verified base producer evidence is malformed')
    successor = dict(original, base_backup=proof['base_backup'], phase='VERIFY_CHAIN')
    return progress_sql(successor, base_proof=proof)


if __name__ == '__main__':
    import sys
    keys = ('metadata_sha256', 'base_backup', 'marker', 'marker_lsn', 'marker_wal',
            'system_identifier', 'xid8_before', 'xid8_after')
    if len(sys.argv) != 10 or len(sys.argv[-1].encode()) > 8192:
        raise SystemExit('invalid verified base publication arguments')
    proof = dict(zip(keys, sys.argv[1:9]), schema='sentinel.verified-base/1', physical_verified=True)
    print(base_transition_sql(json.loads(sys.argv[-1]), proof))
