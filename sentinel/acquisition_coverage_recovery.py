"""Transfer the two authenticated prefixes invalidated by the #613 installer."""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Literal

from psycopg import sql

from sentinel import chain_progress_recovery as shared
from sentinel import deployment_fence, operational_ddl_epoch, operational_schema, schema
from sentinel.automation import store as automation_store
from sentinel.execution import evidence_projection as coverage, evidence_schema, journal
from sentinel.feed import acquisition_guard_migration as guards
from sentinel.feed.publication import _receipt_hmac

SCHEMA = 'sentinel.acquisition-guard-coverage-witness/1'
RESULT_SCHEMA = 'sentinel.acquisition-guard-coverage-transfer/1'
BEFORE_EPOCH = 475
AFTER_EPOCH = 542
DOMAINS = shared.DOMAINS
_require = shared._require
_source_digests = shared._source_digests
# The protected prefix includes the evidence stream and its authenticated head.
# Include the command journal even though reading a projection never writes it.
EXTRA_SOURCES = frozenset({
    'sentinel_commands', 'sentinel_execution_evidence_heads', 'sentinel_execution_evidence_changes',
})


@dataclass(frozen=True)
class PhysicalBackup:
    name: str
    marker: str
    metadata_sha256: str
    system: str
    replay_end_lsn: str


BACKUP = PhysicalBackup(
    'base-20261120T073234Z',
    'sentinel-backup-20261120T073234Z-579766',
    'ee407cd2f0ba8ebd166c6e95dbfbef92a9f6cc9df5bd99b7f527ba96e95b3013',
    '7691913275518591014',
    '4E/E5000000',
)


class Witness(shared.Witness):
    schema_version: Literal['sentinel.acquisition-guard-coverage-witness/1']
    replay_end_lsn: str


def _sign(value):
    return _receipt_hmac({'purpose': SCHEMA, 'witness': value})


def _system(conn):
    return conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]


def _sources(conn):
    return shared._sources(conn) | EXTRA_SOURCES


def snapshot(conn, *, backup, marker, metadata_sha256):
    """Read the pinned predecessor at its physical, paused recovery endpoint."""
    operational_schema.require_idle_connection(conn)
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    conn.execute('SET LOCAL search_path = pg_catalog, public')
    _require(conn.execute('SELECT pg_is_in_recovery()').fetchone()[0] is True
             and conn.execute('SELECT pg_get_wal_replay_pause_state()').fetchone()[0] == 'paused',
             'witness requires a paused isolated physical restore')
    replay_end = conn.execute('SELECT pg_last_wal_replay_lsn()::text').fetchone()[0]
    system = _system(conn)
    _require(PhysicalBackup(backup, marker, metadata_sha256, system, replay_end) == BACKUP,
             'restore differs from the selected pre-acquisition-migration backup or replay point')
    _require(conn.execute('SELECT 1 FROM sentinel_backup_recovery_markers WHERE marker=%s',
                          (marker,)).fetchone() == (1,), 'restore marker is absent')
    schema.require_runtime_schema(conn)
    operational_schema.require_schema(conn)
    guards.require_predecessor(conn)
    deployment_fence.require(conn)
    ddl = operational_ddl_epoch.current(conn)
    _require(ddl[1] == BEFORE_EPOCH, 'restore has the wrong predecessor DDL epoch')
    prefixes = {}
    heads = {}
    for domain in DOMAINS:
        prefix = coverage.require_current(conn, domain)
        heads[domain] = coverage.head(conn, domain)
        _require(heads[domain][2] == 0, 'tracking has been reset')
        prefixes[domain] = shared._prefix_digest(prefix)
    body = Witness(schema_version=SCHEMA, backup=backup, marker=marker, metadata_sha256=metadata_sha256,
                   system=system, binding=coverage.binding(conn), ddl=ddl, replay_end_lsn=replay_end,
                   heads=heads, prefixes=prefixes, sources=_source_digests(conn, _sources(conn))
                   ).model_dump(mode='json')
    return {'witness': body, 'hmac_sha256': _sign(body)}


def validate(document):
    _require(isinstance(document, dict) and set(document) == {'witness', 'hmac_sha256'},
             'witness envelope is malformed')
    value = Witness.model_validate(document['witness']).model_dump(mode='json')
    _require(hmac.compare_digest(str(document['hmac_sha256']), _sign(value)),
             'witness authentication failed')
    _require(PhysicalBackup(value['backup'], value['marker'], value['metadata_sha256'],
                            value['system'], value['replay_end_lsn']) == BACKUP,
             'witness differs from the selected pre-acquisition-migration backup or replay point')
    _require(value['ddl'][1] == BEFORE_EPOCH, 'witness has the wrong predecessor DDL epoch')
    _require(set(value['heads']) == set(DOMAINS) == set(value['prefixes']), 'witness domains differ')
    required = shared._mandatory_sources() | EXTRA_SOURCES
    _require(required <= set(value['sources']) <= (shared._source_candidates() | EXTRA_SOURCES),
             'witness source relations differ')
    return value


def apply(conn, document, *, expected_backup, expected_account, expected_deployment):
    """Change only the inventory of the two fully proven, locked prefixes."""
    value = validate(document)
    _require(value['backup'] == expected_backup, 'backup confirmation differs')
    _require(value['binding'][:3] == [expected_deployment, 'alpaca', expected_account],
             'account confirmation differs')
    operational_schema.require_idle_connection(conn)
    with journal.writer_lock(conn, recovery_only=True):
        conn.execute('SET LOCAL search_path = pg_catalog, public')
        conn.execute("SET LOCAL lock_timeout='2000ms'")
        watched = _sources(conn)
        _require(watched == set(value['sources']), 'source relation set changed')
        locked = watched | evidence_schema.extension_tables | operational_ddl_epoch.extension_tables | {
            'sentinel_automation_control', 'sentinel_automation_lease',
        }
        conn.execute(sql.SQL('LOCK TABLE {} IN SHARE MODE').format(
            sql.SQL(',').join(sql.Identifier('public', name) for name in sorted(locked))))
        schema.require_runtime_schema(conn)
        operational_schema.require_schema(conn)
        guards.require_successor(conn)
        deployment_fence.require(conn)
        control = automation_store.load_control(conn)
        _require(not control.enabled and control.kill_switch_engaged, 'disabled+killed control is required')
        _require(_system(conn) == value['system'] and coverage.binding(conn) == value['binding'],
                 'physical/account binding changed')
        ddl = operational_ddl_epoch.current(conn)
        _require(ddl == (value['ddl'][0], AFTER_EPOCH), 'DDL advance is not the exact #613 installation')
        old = {}
        for domain in DOMAINS:
            head = coverage.head(conn, domain, lock=True)
            _require(list(head) == value['heads'][domain] and head[2] == 0, 'tracking head changed')
            payload = coverage._authenticated(conn, domain)
            _require(payload is not None and shared._prefix_digest(payload) == value['prefixes'][domain],
                     'old authenticated prefix changed')
            _require(payload['body'].get('stage') == 'COMPLETE' and payload['binding'] == value['binding']
                     and (payload['incarnation'], payload['through'], payload['reset_generation']) == head,
                     'old prefix coordinates changed')
            # Rebuild the *old* signed inventory on this physical database. A
            # changed contract, relation OID, filenode or database fails here.
            material = coverage._inventory_material(conn, domain)
            material[-1] = value['ddl']
            _require(coverage.digest(material) == payload['inventory'], 'source relation inventory changed')
            old[domain] = payload
        observed = _source_digests(conn, watched)
        changed = sorted(name for name in watched if observed[name] != value['sources'][name])
        _require(not changed, 'watched source rows changed in ' + ', '.join(changed))
        _require(operational_ddl_epoch.current(conn) == ddl, 'DDL changed during source verification')
        result = {}
        for domain, payload in old.items():
            updated = coverage.write(conn, domain, through=payload['through'], body=payload['body'])
            _require(updated == dict(payload, inventory=updated['inventory'])
                     and updated['inventory'] != payload['inventory'], 'invalid prefix transfer')
            result[domain] = shared._prefix_digest(coverage.require_current(conn, domain))
        conn.commit()
    return {'schema': RESULT_SCHEMA, 'witness_content_sha256': coverage.digest(document),
            'backup': expected_backup, 'prefixes': result, 'broker_contacted': False,
            'operational_ready': False}


def main(argv=None):
    from sentinel.coverage_recovery_cli import run
    return run(__doc__, snapshot, apply, argv)


if __name__ == '__main__':
    raise SystemExit(main())
