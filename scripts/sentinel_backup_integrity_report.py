"""Closed common byte-proof wire validation, standard library on the host."""
import math
import re
import json
from datetime import datetime, timezone, timedelta


FAILURE_PREFIX = 'shared_integrity_failure:'
FAILURE_SCHEMA = 'sentinel.maintenance-integrity-failure/2'
FAILURE_CODES = frozenset(('BUSY PROOF_WINDOW_EXPIRED SELECTION_MOVED POLICY_REFUSED PHYSICAL_UNAVAILABLE '
    'INTEGRITY_REFUSED DATABASE_FAILURE DEADLINE_EXCEEDED TRANSPORT_FAILURE '
    'PROTOCOL_FAILURE INTERNAL_FAILURE').split())
FAILURE_STAGES = frozenset(('CONNECT ADMISSION OWNER_WAIT PROOF RESULT LOCK_RELEASE '
    'HOST_POLICY HOST_IMAGE HOST_POSTGRES HOST_WORKER HOST_VALIDATE HOST_CLEANUP').split())
FAILURE_CAUSES = frozenset(('BackupIntegrityBusy BackupIntegrityProofExpired BackupIntegritySelectionMoved BackupRuntimeUnavailable '
    'BackupRuntimeRefused BackupHorizonExceeded PsycopgError OSError ValueError RuntimeError '
    'TimeoutError Refused PROTOCOL UNCLASSIFIED').split())
FAILURE_KEYS = frozenset(('schema origin code retryable stage cause_type elapsed_seconds '
    'owner_wait_seconds proof_seconds proof_completed_uptime proof_observed_uptime cleanup exception_chain').split())
FAILURE_V2_KEYS = FAILURE_KEYS | {'timing', 'cleanup_exception_chain'}
CHAIN_TYPES = FAILURE_CAUSES | frozenset(('PsycopgOperationalError PsycopgInterfaceError '
    'PsycopgProgrammingError PsycopgDataError PsycopgIntegrityError PsycopgInternalError '
    'PsycopgNotSupportedError PsycopgDatabaseError').split())


def validate_failure(value):
    """Validate only closed facts; no exception message or arbitrary peer text."""
    if (not isinstance(value, dict) or set(value) != (FAILURE_KEYS
            if value.get('schema') == 'sentinel.maintenance-integrity-failure/1' else FAILURE_V2_KEYS)
            or any(type(value[k]) is not str for k in ('schema', 'origin', 'code', 'stage', 'cause_type'))
            or value['schema'] not in {FAILURE_SCHEMA, 'sentinel.maintenance-integrity-failure/1'}
            or value['origin'] not in {'WORKER', 'HOST'}
            or value['code'] not in FAILURE_CODES or value['stage'] not in FAILURE_STAGES
            or value['cause_type'] not in FAILURE_CAUSES or type(value['retryable']) is not bool):
        raise ValueError('common integrity failure fields are invalid')
    timings = [value[k] for k in ('elapsed_seconds', 'owner_wait_seconds', 'proof_seconds')]
    if (any(type(t) not in (int, float) or not math.isfinite(t) or not 0 <= t <= 3600 for t in timings)
            or any(t > timings[0]+.001 for t in timings[1:])):
        raise ValueError('common integrity failure timing is invalid')
    cleanup = value['cleanup']
    if (not isinstance(cleanup, dict) or set(cleanup) != {'proof_lock', 'worker_container'}
            or any(type(v) is not str for v in cleanup.values())
            or cleanup['proof_lock'] not in {'NOT_ACQUIRED', 'RELEASED', 'FAILED', 'UNKNOWN'}
            or cleanup['worker_container'] not in {'NOT_STARTED', 'NOT_OBSERVED', 'REMOVED', 'FAILED'}
            or value['origin'] == 'WORKER' and cleanup['worker_container'] != 'NOT_OBSERVED'
            or value['origin'] == 'HOST' and cleanup['worker_container'] == 'NOT_OBSERVED'):
        raise ValueError('common integrity failure cleanup is invalid')
    clocks = [value[k] for k in ('proof_completed_uptime', 'proof_observed_uptime')]
    if value['code'] == 'PROOF_WINDOW_EXPIRED':
        if (value['cause_type'] != 'BackupIntegrityProofExpired'
                or any(type(t) not in (int, float) or not math.isfinite(t) or t < 0 for t in clocks)
                or clocks[1]-clocks[0] < 300):
            raise ValueError('common integrity failure lacks original expiry clocks')
    elif clocks != [None, None]:
        raise ValueError('common integrity failure invented proof clocks')
    if value['code'] == 'BUSY' and value['cause_type'] != 'BackupIntegrityBusy':
        raise ValueError('common integrity failure lacks actual busy ownership')
    if value['code'] == 'SELECTION_MOVED' and value['cause_type'] != 'BackupIntegritySelectionMoved':
        raise ValueError('common integrity failure lacks proved selection movement')
    chain = value['exception_chain']
    _validate_chain(chain, minimum=1)
    if value['schema'] == FAILURE_SCHEMA:
        _validate_chain(value['cleanup_exception_chain'], minimum=0)
        timing = value['timing']
        if (not isinstance(timing, dict) or set(timing) != {'alarm_budget_seconds', 'alarm_fired', 'started_at', 'failed_at'}
                or type(timing['alarm_fired']) is not bool
                or timing['alarm_budget_seconds'] is not None and (type(timing['alarm_budget_seconds']) is not int
                    or not 1 <= timing['alarm_budget_seconds'] <= 540)
                or timing['alarm_fired'] and timing['alarm_budget_seconds'] is None
                or any(type(timing[k]) is not str for k in ('started_at', 'failed_at'))):
            raise ValueError('common integrity owner timing is invalid')
        clocks = [datetime.fromisoformat(timing[k].replace('Z', '+00:00')) for k in ('started_at', 'failed_at')]
        if (any(c.utcoffset() is None or c.utcoffset().total_seconds() != 0 for c in clocks)
                or clocks[1] < clocks[0]):
            raise ValueError('common integrity owner clocks are invalid')
    stages = {'BUSY': {'OWNER_WAIT', 'PROOF'}, 'PROOF_WINDOW_EXPIRED': {'PROOF', 'RESULT'},
              'SELECTION_MOVED': {'RESULT'}}
    if (value['origin'] == 'WORKER' and value['stage'].startswith('HOST_')
            or value['code'] in stages and (value['stage'] not in stages[value['code']]
                or chain[0]['type'] != value['cause_type'])):
        raise ValueError('common integrity original cause or stage contradicts its code')
    safe_cleanup = (cleanup['proof_lock'] in {'NOT_ACQUIRED', 'RELEASED'}
        and (value['origin'] == 'WORKER' or cleanup['worker_container'] == 'REMOVED'))
    if value['retryable'] != (value['code'] in {'BUSY', 'PROOF_WINDOW_EXPIRED', 'SELECTION_MOVED'} and safe_cleanup):
        raise ValueError('common integrity failure retry classification is invalid')
    return value


def _validate_chain(chain, *, minimum):
    if (type(chain) is not list or not minimum <= len(chain) <= 4
            or any(not isinstance(item, dict) or set(item) != {'type', 'sqlstate', 'errno'}
                or type(item['type']) is not str or item['type'] not in CHAIN_TYPES
                or item['sqlstate'] is not None and (type(item['sqlstate']) is not str
                    or re.fullmatch(r'[0-9A-Z]{5}', item['sqlstate']) is None)
                or item['errno'] is not None and (type(item['errno']) is not int
                    or not -(2**31) <= item['errno'] < 2**31) for item in chain)):
        raise ValueError('common integrity exception chain is invalid')


def failure(*, origin, code, stage, cause_type, elapsed_seconds=0., owner_wait_seconds=0.,
            proof_seconds=0., proof_completed_uptime=None, proof_observed_uptime=None,
            proof_lock='UNKNOWN', worker_container='NOT_STARTED', exception_chain=None,
            timing=None, cleanup_exception_chain=None):
    now = datetime.now(timezone.utc)
    value = dict(schema=FAILURE_SCHEMA, origin=origin, code=code, stage=stage, cause_type=cause_type,
        elapsed_seconds=elapsed_seconds, owner_wait_seconds=owner_wait_seconds,
        proof_seconds=proof_seconds, proof_completed_uptime=proof_completed_uptime,
        proof_observed_uptime=proof_observed_uptime,
        exception_chain=exception_chain or [dict(type=cause_type, sqlstate=None, errno=None)],
        cleanup_exception_chain=[] if cleanup_exception_chain is None else cleanup_exception_chain,
        timing=timing or dict(alarm_budget_seconds=None,alarm_fired=False,
            started_at=(now-timedelta(seconds=elapsed_seconds)).isoformat(),failed_at=now.isoformat()),
        cleanup=dict(proof_lock=proof_lock, worker_container=worker_container), retryable=False)
    value['retryable'] = (code in {'BUSY', 'PROOF_WINDOW_EXPIRED', 'SELECTION_MOVED'}
        and proof_lock in {'NOT_ACQUIRED', 'RELEASED'}
        and (origin == 'WORKER' or worker_container == 'REMOVED'))
    return validate_failure(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate common integrity field')
        result[key] = value
    return result


def parse_failure(output, *, returncode, origin='HOST'):
    if type(output) is not str or len(output) > 16384:
        raise ValueError('common integrity failure output exceeds bound')
    lines = [line[len(FAILURE_PREFIX):] for line in output.splitlines() if line.startswith(FAILURE_PREFIX)]
    if len(lines) != 1:
        raise ValueError('common integrity failure is missing or ambiguous')
    value = validate_failure(json.loads(lines[0], object_pairs_hook=_unique_object))
    if value['origin'] != origin or type(returncode) is not int or returncode != (75 if value['retryable'] else 4):
        raise ValueError('common integrity failure transport classification differs')
    return value


KEYS = frozenset(('schema enabled system_identifier base_backup recoverable_from_wal '
    'recovery_marker_wal recoverable_through_wal wal_segments timeline_history wal_integrity '
    'integrity_objects_hashed integrity_full_scrub integrity_read_passes integrity_max_reuse_seconds '
    'wal_segment_bytes integrity_completed_uptime integrity_observed_uptime').split())


def validate(value):
    if not isinstance(value, dict) or set(value) != KEYS:
        raise ValueError('common integrity report fields are invalid')
    for key, pattern in (('system_identifier', r'[1-9][0-9]{0,19}'),
            ('base_backup', r'base-[0-9]{8}T[0-9]{6}Z'),
            *((key, r'[0-9A-F]{24}') for key in ('recoverable_from_wal',
                 'recovery_marker_wal', 'recoverable_through_wal'))):
        if not isinstance(value[key], str) or re.fullmatch(pattern, value[key]) is None:
            raise ValueError('common integrity identity is invalid')
    numbers = ('wal_segments', 'wal_segment_bytes', 'integrity_objects_hashed',
               'integrity_read_passes', 'integrity_max_reuse_seconds')
    if (any(type(value[k]) is not int for k in numbers)
            or type(value['integrity_full_scrub']) is not bool
            or value['enabled'] is not True or value['schema'] != 'sentinel.maintenance-integrity/1'
            or value['wal_integrity'] != 'sha256-sidecar-v1'):
        raise ValueError('common integrity types are invalid')
    size = value['wal_segment_bytes']; count = value['wal_segments']
    if (not 1024**2 <= size <= 1024**3 or size & (size-1)
            or not 1 <= count <= 1024 or size*count > 16*1024**3):
        raise ValueError('common integrity resource bounds are invalid')
    names = [value[k] for k in ('recoverable_from_wal', 'recovery_marker_wal', 'recoverable_through_wal')]
    timeline = names[0][:8]; per_log = 2**32//size
    indices = [int(n[8:16], 16)*per_log+int(n[16:], 16) for n in names]
    history = None if timeline == '00000001' else timeline+'.history'
    reads = value['integrity_objects_hashed']
    if (int(timeline, 16) < 1 or any(n[:8] != timeline or int(n[16:], 16) >= per_log for n in names)
            or not indices[0] <= indices[1] <= indices[2]
            or count != indices[2]-indices[0]+1 or value['timeline_history'] != history
            or not 0 <= reads <= 2*(count+(history is not None)) or reads % 2
            or value['integrity_read_passes'] != (2 if reads else 0)
            or value['integrity_full_scrub'] and reads != 2*(count+(history is not None))
            or value['integrity_max_reuse_seconds'] != 300):
        raise ValueError('common integrity interval or work counts are invalid')
    stamps = [value[k] for k in ('integrity_completed_uptime', 'integrity_observed_uptime')]
    if (any(type(s) not in (int, float) or not math.isfinite(s) or s < 0 for s in stamps)
            or not 0 <= stamps[1]-stamps[0] < 300):
        raise ValueError('common integrity original clock is invalid')
    return value
