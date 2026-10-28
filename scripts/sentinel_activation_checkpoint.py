"""Reuse a proven base; archive the newly committed activation state once."""
from datetime import datetime, timezone
import hashlib
import json
import re
import time
import uuid

import sentinel_backup_maintenance as maintenance
from sentinel_backup_deadlines import CHAIN_STATUS_SECONDS

ARCHIVE_SECONDS = 60


def _boundary_document(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate checkpoint field')
            value[key] = item
        return value
    def invalid_constant(_value):
        raise ValueError('nonfinite checkpoint field')
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
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


def require_coverage(proof, barrier, observation, *, allow_pending=False):
    if (barrier.get('system_identifier') != observation['system_id']
            or proof['system_identifier'] != observation['system_id']):
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
    first, last = proof['recoverable_from_wal'], proof['recoverable_through_wal']
    if wal < first or (wal > last and not allow_pending):
        raise RuntimeError('activation state has not reached the verified archive')
    return wal <= last


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
    status = command(['bash', 'scripts/sentinel-backup-status.sh', '--backup', backup],
                     CHAIN_STATUS_SECONDS)
    chain = maintenance.runtime_chain_proof(status, selected, before, str(root))
    receipt = maintenance.verified_base_chain_receipt(selected, before, chain, runner)
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
        # pg_stat_archiver can briefly name .backup/.history metadata. The
        # canonical status command handles that with its existing bounded wait.
        status = command(['bash', 'scripts/sentinel-backup-status.sh', '--backup', backup],
                         remaining)
        after = maintenance.observe_primary(runner)
        current = maintenance.worker('observe', image, str(root), after, runner)
        if current != selected or after['system_id'] != before['system_id'] or after['timeline'] != before['timeline']:
            raise RuntimeError('activation checkpoint selected generation changed')
        if _lsn(after['lsn']) < _lsn(barrier['lsn']):
            raise RuntimeError('activation checkpoint boundary is ahead of primary WAL')
        if maintenance.renewal_due(selected, after):
            raise RuntimeError('activation checkpoint exhausted renewal headroom')
        proof = maintenance.runtime_chain_proof(status, selected, after, str(root))
        # Incomplete coverage may be normal archive latency; malformed identity
        # and geometry are refusals. Never retry arbitrary integrity failures.
        if require_coverage(proof, barrier, after, allow_pending=True):
            if time.monotonic() >= archive_deadline:
                raise RuntimeError('activation checkpoint archive deadline exhausted')
            maintenance.publish_runtime_chain(status, selected, after, str(root), runner)
            if time.monotonic() >= archive_deadline:
                raise RuntimeError('activation checkpoint archive deadline exhausted')
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
        time.sleep(min(1, max(0, archive_deadline - time.monotonic())))
