"""Explicit bounded owner-PAPER operation during absent backup media.

These primary-local authenticated records describe a previously checked external
chain and current primary capacity. They never claim a new external archive.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import shlex

from sentinel.backup_guard import BackupConfigurationRefused, BackupUnavailable

POLICY_ENV = 'SENTINEL_BACKUP_OUTAGE_POLICY'
POLICY = 'BOUNDED_30H_V1'
CHECKPOINT = 'sentinel-backup-continuity-v1.json'
CAPACITY = 'sentinel-backup-capacity-v1.json'
MAX_BYTES = 16384
MAX_AGE = 30 * 3600
CAPACITY_MAX_AGE = 600
RESERVE_BYTES = 10 * 1024**3
MAX_PRIMARY_WAL_BYTES = 8 * 1024**3
KEY_ENV = 'SENTINEL_PUBLICATION_RECEIPT_KEY'


def selected(values=None):
    values = os.environ if values is None else values
    value = values.get(POLICY_ENV, '')
    if value not in ('', POLICY):
        raise BackupConfigurationRefused('unsupported backup outage policy')
    if not value:
        return False
    from sentinel import local_paper
    if (not local_paper.enabled(values)
            or local_paper.backup_policy(values) != local_paper.BACKUP_POLICY):
        raise BackupConfigurationRefused('backup continuity requires backed owner PAPER')
    return True


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('ascii')


def _key():
    value = os.environ.get(KEY_ENV, '').encode('utf-8')
    if len(value) < 32:
        raise BackupConfigurationRefused('backup continuity signing key unavailable')
    return value


def seal(kind, proof):
    body = {'schema': 'sentinel.backup-continuity/1', 'kind': kind, 'proof': proof}
    digest = hmac.new(_key(), b'sentinel.backup-continuity/1\0' + _bytes(body),
                      hashlib.sha256).hexdigest()
    return dict(body, hmac_sha256=digest)


def authenticate(raw, kind):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate record member')
            value[key] = item
        return value
    try:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
            raise ValueError('record byte bound')
        value = json.loads(raw, object_pairs_hook=unique)
        if (set(value) != {'schema', 'kind', 'proof', 'hmac_sha256'}
                or value['schema'] != 'sentinel.backup-continuity/1'
                or value['kind'] != kind or not isinstance(value['proof'], dict)):
            raise ValueError('record shape')
        expected = seal(kind, value['proof'])['hmac_sha256']
        if not isinstance(value['hmac_sha256'], str) or not hmac.compare_digest(
                value['hmac_sha256'], expected):
            raise ValueError('record authentication')
        return value['proof']
    except (TypeError, ValueError, KeyError, UnicodeError) as exc:
        raise BackupConfigurationRefused('backup continuity record is invalid') from exc


def publication_sql(name, record):
    """Only fixed primary-local files; SQL contains receipt bytes, never a key."""
    if name not in (CHECKPOINT, CAPACITY):
        raise ValueError('unsupported continuity record destination')
    raw = _bytes(record)
    if len(raw) > MAX_BYTES:
        raise ValueError('continuity record byte bound')
    encoded = base64.b64encode(raw).decode('ascii')
    script = f'''set -eu
target={shlex.quote(name)}
[ ! -L "$target" ]
if [ -e "$target" ]; then
  [ -f "$target" ] && [ "$(stat -c %h "$target")" = 1 ]
fi
temporary=$(mktemp "./.$target.XXXXXX")
trap 'rm -f -- "$temporary"' EXIT
chmod 0600 "$temporary"
IFS= read -r payload
printf '%s' "$payload" | base64 -d > "$temporary"
sync "$temporary"
mv -Tf -- "$temporary" "$target"
sync .'''
    program = 'sh -ceu ' + shlex.quote(script)
    literal = program.replace("'", "''")
    return f"COPY (SELECT '{encoded}') TO PROGRAM '{literal}'"


def _read(conn, name, kind):
    with conn.cursor() as cur:
        cur.execute('SELECT pg_read_binary_file(%s,0,%s,true)', (name, MAX_BYTES + 1))
        row = cur.fetchone()
    if row is None or row[0] is None:
        raise BackupUnavailable('backup continuity record is missing')
    return authenticate(bytes(row[0]), kind)


def primary(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT system_identifier::text,"
            "floor(extract(epoch FROM pg_postmaster_start_time())*1000000)::bigint,"
            "floor(extract(epoch FROM clock_timestamp()))::bigint,"
            "last_archived_wal,floor(extract(epoch FROM last_archived_time))::bigint,"
            "current_setting('archive_mode'),"
            "coalesce((SELECT sum(size) FROM pg_ls_waldir()),0)::bigint"
            " FROM pg_control_system() CROSS JOIN pg_stat_archiver")
        row = cur.fetchone()
    if (not row or len(row) != 7 or not re.fullmatch(r'[1-9][0-9]{0,19}', str(row[0]))
            or any(type(row[i]) is not int for i in (1, 2, 6))
            or row[1] <= 0 or row[2] <= 0 or row[6] < 0):
        raise BackupConfigurationRefused('invalid continuity primary observation')
    return dict(system_identifier=str(row[0]), postmaster_start_us=row[1],
        now=row[2], last_archived_wal=row[3], last_archive_at=row[4],
        archive_mode=row[5], primary_wal_bytes=row[6])


def _context(conn, observation):
    from sentinel import local_paper
    bound = local_paper.bound_account(conn)
    if bound is None:
        raise BackupConfigurationRefused('backup continuity requires bound owner PAPER')
    commit = os.environ.get('SENTINEL_GIT_COMMIT', '')
    image = os.environ.get('SENTINEL_RUNTIME_IMAGE_DIGEST', '')
    if (not re.fullmatch(r'[0-9a-f]{40}', commit)
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', image)):
        raise BackupConfigurationRefused('backup continuity runtime identity is missing')
    return dict(system_identifier=observation['system_identifier'],
        postmaster_start_us=observation['postmaster_start_us'],
        deployment_id=bound.deployment_id, broker=bound.broker,
        broker_account_id=bound.broker_account_id, takeover_epoch=bound.takeover_epoch,
        git_commit=commit, runtime_image_digest=image)


def validate_capacity(proof, observation, *, expected_engine=None):
    if (set(proof) != {'system_identifier', 'postmaster_start_us', 'observed_at',
            'physical_free_bytes', 'engine_id'}
            or proof['system_identifier'] != observation['system_identifier']
            or proof['postmaster_start_us'] != observation['postmaster_start_us']
            or type(proof['observed_at']) is not int
            or not 0 <= observation['now'] - proof['observed_at'] < CAPACITY_MAX_AGE
            or type(proof['physical_free_bytes']) is not int
            or proof['physical_free_bytes'] < RESERVE_BYTES
            or not isinstance(proof['engine_id'], str) or not proof['engine_id']
            or (expected_engine is not None and proof['engine_id'] != expected_engine)):
        raise BackupUnavailable('backup continuity physical capacity is unsafe or unverifiable')
    return proof


def _capacity(conn, observation, *, expected_engine=None):
    proof = validate_capacity(_read(conn, CAPACITY, 'CAPACITY'), observation,
                              expected_engine=expected_engine)
    # The Windows receipt measures the physical VHD backing disk. Separately
    # inspect the database filesystem now, under PostgreSQL's own OS identity.
    script = ('set -eu; cat >/dev/null; set -- $(stat -f -c "%S %a" .); '
        '[ "$#" = 2 ]; case "$1:$2" in *[!0-9:]*|:*) exit 1;; esac; '
        f'[ "$(( $1 * $2 ))" -ge {RESERVE_BYTES} ]')
    program = ('sh -ceu ' + shlex.quote(script)).replace("'", "''")
    try:
        with conn.cursor() as cur:
            cur.execute(f"COPY (SELECT 1) TO PROGRAM '{program}'")
    except Exception as exc:
        raise BackupUnavailable('backup continuity primary filesystem reserve unavailable') from exc
    if observation['primary_wal_bytes'] >= MAX_PRIMARY_WAL_BYTES:
        raise BackupUnavailable('backup continuity retained WAL exceeds capacity budget')
    return proof


def remember(conn, chain):
    """Persist only an actual successful external proof; never degraded reuse."""
    observation = primary(conn)
    if (chain.get('enabled') is not True or chain.get('backup_state') == 'DEGRADED'
            or chain.get('system_identifier') != observation['system_identifier']
            or type(observation['last_archive_at']) is not int
            or not 0 <= observation['now'] - observation['last_archive_at'] < MAX_AGE):
        raise BackupUnavailable('external proof changed before continuity checkpoint')
    if chain.get('recoverable_through_wal') != observation['last_archived_wal']:
        return  # A later archive success needs its own chain proof, never a retimed prefix.
    try:
        with conn.transaction():
            capacity = _capacity(conn, observation)
    except BackupUnavailable:
        # Healthy external proof remains sufficient under REQUIRED_V1. No
        # checkpoint is issued until independent capacity becomes available;
        # missing/stale capacity can never authorize the degraded path.
        return
    proof = dict(context=_context(conn, observation), engine_id=capacity['engine_id'],
        last_archive_at=observation['last_archive_at'], chain=chain)
    # Avoid shell/file work when no successfully archived frontier changed.
    try:
        previous = _read(conn, CHECKPOINT, 'CHECKPOINT')
    except BackupUnavailable:
        previous = None
    if previous != proof:
        with conn.cursor() as cur:
            cur.execute(publication_sql(CHECKPOINT, seal('CHECKPOINT', proof)))


def require_absent_media(conn):
    """A mounted but corrupt/incomplete archive is never an outage exception."""
    script = ('set -eu; cat >/dev/null; '
        "awk '$5==\"/sentinel-backup/base\" || $5==\"/sentinel-backup/wal\" {child=1} "
        "$5==\"/sentinel-backup\" && $6 ~ /(^|,)ro(,|$)/ && / - tmpfs / {parent=1} "
        "END {exit !(parent && !child)}' /proc/self/mountinfo; "
        '[ -d /sentinel-backup/base ] && [ ! -L /sentinel-backup/base ]; '
        '[ -d /sentinel-backup/wal ] && [ ! -L /sentinel-backup/wal ]; '
        '[ ! -e /sentinel-backup/base/.sentinel-independent-durable-target-v1 ]; '
        '[ ! -L /sentinel-backup/base/.sentinel-independent-durable-target-v1 ]; '
        '[ ! -L /sentinel-backup/wal/.sentinel-independent-durable-target-v1 ]; '
        '[ ! -e /sentinel-backup/wal/.sentinel-independent-durable-target-v1 ]')
    program = ('sh -ceu ' + shlex.quote(script)).replace("'", "''")
    try:
        with conn.cursor() as cur:
            cur.execute(f"COPY (SELECT 1) TO PROGRAM '{program}'")
    except Exception as exc:
        raise BackupUnavailable('media absence is not proven; strict backup gate remains') from exc


def degraded(conn, *, operation, base_backup=None):
    """Authorize bounded ordinary work, returning explicit degraded evidence."""
    require_absent_media(conn)
    observation = primary(conn)
    proof = _read(conn, CHECKPOINT, 'CHECKPOINT')
    if (set(proof) != {'context', 'engine_id', 'last_archive_at', 'chain'}
            or proof['context'] != _context(conn, observation)
            or observation['archive_mode'] != 'on'
            or type(proof['last_archive_at']) is not int
            or not 0 <= observation['now'] - proof['last_archive_at'] < MAX_AGE
            or type(observation['last_archive_at']) is not int
            or observation['last_archive_at'] < proof['last_archive_at']
            or not isinstance(proof['chain'], dict)
            or not re.fullmatch(r'[0-9A-F]{24}',str(observation['last_archived_wal']))
            or not re.fullmatch(r'[0-9A-F]{24}',str(proof['chain'].get('recoverable_through_wal')))
            or proof['chain']['recoverable_through_wal'][:8] != observation['last_archived_wal'][:8]
            or proof['chain']['recoverable_through_wal'] > observation['last_archived_wal']
            or (base_backup is not None and proof['chain'].get('base_backup') != base_backup)):
        raise BackupUnavailable('backup continuity checkpoint expired or identity changed')
    _capacity(conn, observation, expected_engine=proof['engine_id'])
    # Recheck after capacity work so a reconnect never bypasses strict proof of
    # newly present media. The next ordinary attempt validates its full chain.
    require_absent_media(conn)
    return dict(enabled=True, backup_state='DEGRADED', independent_archive_current=False,
        system_identifier=observation['system_identifier'],
        last_verified_external_archive_at=proof['last_archive_at'],
        continuity_deadline=proof['last_archive_at'] + MAX_AGE,
        operation=operation, checkpoint_sha256=hashlib.sha256(_bytes(proof)).hexdigest())
