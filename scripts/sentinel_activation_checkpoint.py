"""Reuse a proven base; archive the newly committed activation state once."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import uuid

# Direct host-script execution starts with scripts/ on sys.path, not repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sentinel.backup_archive_names import archive_kind
import sentinel_backup_maintenance as maintenance
from sentinel_backup_deadlines import CHAIN_STATUS_SECONDS

ARCHIVE_SECONDS = 60


def _document(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate checkpoint field')
            value[key] = item
        return value
    def invalid_constant(_value):
        raise ValueError('nonfinite checkpoint field')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def _boundary_document(raw):
    try:
        value = _document(raw)
        if (not isinstance(value, dict)
                or set(value) != {'system_identifier', 'lsn', 'wal'}
                or not isinstance(value['system_identifier'], str)
                or not re.fullmatch('[0-9]{1,20}', value['system_identifier'])
                or not isinstance(value['wal'], str)
                or not re.fullmatch('[0-9A-F]{24}', value['wal'])):
            raise ValueError('unexpected checkpoint shape')
        _lsn(value['lsn'])
        return value
    except (ValueError, TypeError) as exc:
        raise RuntimeError('activation checkpoint boundary is malformed') from exc


def _lsn(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9A-F]{1,8}/[0-9A-F]{1,8}', value):
        raise RuntimeError('activation checkpoint LSN is malformed')
    high, low = value.split('/')
    return int(high, 16) * 2**32 + int(low, 16)


def _barrier_wal(barrier, observation):
    if barrier.get('system_identifier') != observation['system_id']:
        raise RuntimeError('activation checkpoint cluster changed')
    wal = barrier.get('wal')
    if not isinstance(wal, str) or not re.fullmatch(r'[0-9A-F]{24}', wal):
        raise RuntimeError('activation checkpoint WAL is malformed')
    size = observation['segment_size']
    index = int(wal[8:16], 16) * (2**32 // size) + int(wal[16:], 16)
    if (wal[:8] != observation['timeline']
            or int(wal[16:], 16) >= 2**32 // size
            or index != (_lsn(barrier.get('lsn')) - 1) // size):
        raise RuntimeError('activation checkpoint WAL geometry changed')
    return wal


def require_coverage(proof, barrier, observation, *, allow_pending=False):
    wal = _barrier_wal(barrier, observation)
    if proof['system_identifier'] != observation['system_id']:
        raise RuntimeError('activation checkpoint cluster changed')
    first, last = proof['recoverable_from_wal'], proof['recoverable_through_wal']
    if wal < first or (wal > last and not allow_pending):
        raise RuntimeError('activation state has not reached the verified archive')
    return wal <= last


def archive_reached(barrier, observation, runner):
    """A cheap arrival hint, never authority for WAL integrity or durability."""
    target = _barrier_wal(barrier, observation)
    raw = maintenance.sql("""SELECT json_build_object(
        'mode',current_setting('archive_mode'),'system_identifier',system_identifier::text,
        'wal',last_archived_wal,
        'last_ok',floor(extract(epoch FROM last_archived_time))::bigint,
        'now',floor(extract(epoch FROM clock_timestamp()))::bigint,
        'future',(coalesce(last_archived_time>clock_timestamp(),false) OR
                  coalesce(last_failed_time>clock_timestamp(),false)),
        'unresolved',coalesce(last_failed_time>last_archived_time,false))
        FROM pg_stat_archiver,pg_control_system()""", runner)
    try:
        value = _document(raw)
        if (not isinstance(value, dict) or set(value) != {
                'mode','system_identifier','wal','last_ok','now','future','unresolved'}
                or value['mode'] != 'on'
                or value['system_identifier'] != observation['system_id']
                or type(value['last_ok']) is not int or type(value['now']) is not int
                or not 0 < value['last_ok'] <= value['now']
                or value['future'] is not False or value['unresolved'] is not False
                or not isinstance(value['wal'], str)):
            raise ValueError('archive observation is unavailable or inconsistent')
        kind = archive_kind(value['wal'], observation['segment_size'])
        if value['wal'][:8] != observation['timeline']:
            raise ValueError('archive timeline changed')
    except (ValueError, TypeError, KeyError) as exc:
        raise RuntimeError('activation checkpoint archive observation refused') from exc
    return kind == 'SEGMENT' and value['wal'] >= target


def commit_boundary(runner):
    """Commit a witness, then observe the flushed boundary in a new session."""
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    marker = 'sentinel-backup-' + stamp + '-' + str(uuid.uuid4().int)
    query = ("WITH configured AS MATERIALIZED (SELECT set_config("
             "'synchronous_commit','on',true)), inserted AS ("
             "INSERT INTO sentinel_backup_recovery_markers(marker) "
             "SELECT '" + marker + "' FROM configured RETURNING marker) "
             "SELECT marker FROM inserted")
    if maintenance.sql(query, runner) != marker:
        raise RuntimeError('activation checkpoint marker was not committed exactly')
    barrier = _boundary_document(maintenance.sql("""WITH boundary AS MATERIALIZED
        (SELECT pg_current_wal_flush_lsn() AS lsn)
        SELECT json_build_object('system_identifier',system_identifier::text,
        'lsn',lsn::text,'wal',pg_walfile_name(lsn))
        FROM boundary,pg_control_system()""", runner))
    return marker, barrier


def reuse(root, command):
    """Return None only before mutation when a fresh full milestone is needed.

    command owns the outer invocation deadline and verified target lock. Failed
    archive/identity proof after selecting reuse refuses; it cannot fall back to
    another allocation or masquerade as a newly performed semantic restore.
    """
    archive_deadline = None
    def runner(argv, timeout=120, stdin=None):
        if stdin is not None:
            raise RuntimeError('activation checkpoint does not accept mutable worker input')
        if archive_deadline is not None:
            remaining = archive_deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('activation checkpoint archive deadline exhausted')
            timeout = min(timeout, remaining)
        return command(argv, timeout).strip()

    image = maintenance.runtime_image(runner)
    before = maintenance.observe_primary(runner)
    selected = maintenance.worker('observe', image, str(root), before, runner)
    if maintenance.renewal_due(selected, before):
        return None
    backup = str(root / 'base' / selected['name'])
    receipt = maintenance.verified_base_receipt(selected, before, runner)
    verified_base = receipt is not None
    if receipt is None:
        # An older base may have genuine semantic restore evidence. Its
        # immutable application image does not have to be the current image.
        receipt = maintenance._selected_full_restore_receipt(selected, before, runner)
    if receipt is None:
        return None
    method = ('REUSED_VERIFIED_BASE_AND_ARCHIVED_STATE' if verified_base
              else 'REUSED_FULL_RESTORE_AND_ARCHIVED_STATE')
    print('activation recovery: reusing proven base; archiving saved state', flush=True)
    # The statement commits before the next psql invocation captures the flush
    # boundary. Earlier plan/authority commits are therefore before this LSN.
    marker, barrier = commit_boundary(runner)
    if _lsn(barrier.get('lsn')) < _lsn(before['lsn']):
        raise RuntimeError('activation checkpoint flush boundary regressed')
    # This clock never resets during polling or command retries.
    archive_deadline = time.monotonic() + ARCHIVE_SECONDS
    maintenance.sql('SELECT pg_switch_wal()', runner)
    while True:
        remaining = archive_deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError('activation checkpoint archive deadline exhausted')
        if archive_reached(barrier, before, runner):
            if time.monotonic() >= archive_deadline:
                raise RuntimeError('activation checkpoint archive deadline exhausted')
            break
        time.sleep(min(1, max(0, archive_deadline - time.monotonic())))
    # Arrival and traversal have separate existing budgets. The enclosing
    # milestone still bounds every command and the complete invocation.
    archive_deadline = None
    status = command(['bash', 'scripts/sentinel-backup-status.sh', '--backup', backup],
                     CHAIN_STATUS_SECONDS)
    after = maintenance.observe_primary(runner)
    current = maintenance.worker('observe', image, str(root), after, runner)
    if current != selected or after['system_id'] != before['system_id'] or after['timeline'] != before['timeline']:
        raise RuntimeError('activation checkpoint selected generation changed')
    if _lsn(after['lsn']) < _lsn(barrier['lsn']):
        raise RuntimeError('activation checkpoint boundary is ahead of primary WAL')
    if maintenance.renewal_due(selected, after):
        raise RuntimeError('activation checkpoint exhausted renewal headroom')
    proof = maintenance.runtime_chain_proof(status, selected, after, str(root))
    require_coverage(proof, barrier, after)
    if verified_base:
        receipt = maintenance._base_chain_receipt(selected, after, proof)
    maintenance.publish_runtime_chain(status, selected, after, str(root), runner)
    evidence_sha256 = hashlib.sha256(json.dumps(
        receipt, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    checkpoint = dict(schema='sentinel.activation-recovery-checkpoint/1',
        method=method,
        base_backup=selected['name'], runtime_image=image,
        system_identifier=after['system_id'], metadata_sha256=selected['metadata_sha256'],
        base_evidence_sha256=evidence_sha256,
        marker=marker, state_lsn=barrier['lsn'], state_wal=barrier['wal'],
        recoverable_through_wal=proof['recoverable_through_wal'],
        new_base_created=False, full_restore_performed=False)
    if not verified_base:
        checkpoint['full_restore_receipt_sha256'] = evidence_sha256
    print('activation_recovery_checkpoint:' + json.dumps(checkpoint, sort_keys=True), flush=True)
    return backup
