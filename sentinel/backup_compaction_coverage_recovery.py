"""One-time recovery of the authenticated prefixes invalidated on November 15."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import signal
from pathlib import Path
from typing import Literal

from psycopg import sql

from sentinel import chain_progress_recovery as shared
from sentinel import deployment_fence, operational_ddl_epoch, operational_schema, schema
from sentinel.automation import store as automation_store
from sentinel.execution import evidence_projection as coverage, evidence_schema, journal
from sentinel.feed import store

SCHEMA = 'sentinel.backup-compaction-coverage-witness/1'
RESULT_SCHEMA = 'sentinel.backup-compaction-coverage-transfer/1'
BEFORE_EPOCH = 142
AFTER_EPOCH = 475
PRE_COMPACTION_BASE = 'base-20261115T094526Z'
PRE_COMPACTION_REPLAY_END = '45/62381EA0'
PREDECESSOR_GUARD_SHA256 = 'b21613321e7ecc1f26c793adf88389566cefb771dcaa6fc016cf2a1d35825f9f'
DOMAINS = shared.DOMAINS
_require = shared._require
_prefix_digest = shared._prefix_digest
_source_digests = shared._source_digests
SOURCES = frozenset(shared._mandatory_sources() | {
    'sentinel_commands', 'sentinel_execution_evidence_changes', 'sentinel_execution_evidence_heads',
})


class Witness(shared.Witness):
    schema_version: Literal['sentinel.backup-compaction-coverage-witness/1']
    replay_end_lsn: str


def _sign(value):
    from sentinel.feed.publication import _receipt_hmac
    return _receipt_hmac({'purpose': SCHEMA, 'witness': value})


def _system(conn):
    return str(conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0])


def snapshot(conn, *, backup, marker, metadata_sha256):
    conn.execute('SET TRANSACTION READ ONLY')
    conn.execute("SET LOCAL search_path = pg_catalog, public")
    _require(conn.execute('SELECT pg_is_in_recovery()').fetchone()[0] is True
             and conn.execute('SELECT pg_get_wal_replay_pause_state()').fetchone()[0] == 'paused',
             'witness requires a paused isolated physical restore')
    replay_end = conn.execute('SELECT pg_last_wal_replay_lsn()::text').fetchone()[0]
    _require(backup == PRE_COMPACTION_BASE and replay_end == PRE_COMPACTION_REPLAY_END,
             'restore has the wrong compaction replay point')
    schema.require_runtime_schema(conn)
    operational_schema.require_schema(conn)
    ddl = operational_ddl_epoch.current(conn)
    _require(ddl[1] == BEFORE_EPOCH, 'restore must precede the exact compaction sequence')
    row = conn.execute(
        "SELECT prosrc FROM pg_proc WHERE oid="
        "to_regprocedure('public.sentinel_acquisition_price_delete_guard()')").fetchone()
    _require(row is not None and hashlib.sha256(' '.join(row[0].split()).encode()).hexdigest()
             == PREDECESSOR_GUARD_SHA256, 'restore has the wrong retention guard')
    _require(conn.execute('SELECT 1 FROM sentinel_backup_recovery_markers WHERE marker=%s',
                         (marker,)).fetchone(), 'restore marker is absent')
    heads = {}
    prefixes = {}
    for domain in DOMAINS:
        prefix = coverage.require_current(conn, domain)
        heads[domain] = coverage.head(conn, domain)
        _require(heads[domain][2] == 0, 'tracking has been reset')
        prefixes[domain] = _prefix_digest(prefix)
    value = Witness(schema_version=SCHEMA, backup=backup, marker=marker,
        metadata_sha256=metadata_sha256, system=_system(conn), binding=coverage.binding(conn),
        ddl=ddl, replay_end_lsn=replay_end, heads=heads, prefixes=prefixes,
        sources=_source_digests(conn, SOURCES))
    body = value.model_dump(mode='json')
    return {'witness': body, 'hmac_sha256': _sign(body)}


def validate(document):
    _require(isinstance(document, dict) and set(document) == {'witness', 'hmac_sha256'},
             'witness envelope is malformed')
    value = Witness.model_validate(document['witness']).model_dump(mode='json')
    _require(value['backup'] == PRE_COMPACTION_BASE
             and value['replay_end_lsn'] == PRE_COMPACTION_REPLAY_END,
             'witness has the wrong compaction replay point')
    _require(value['ddl'][1] == BEFORE_EPOCH, 'witness does not precede compaction')
    _require(set(value['heads']) == set(DOMAINS) == set(value['prefixes']), 'witness domains differ')
    _require(set(value['sources']) == SOURCES, 'witness source relations differ')
    _require(hmac.compare_digest(str(document['hmac_sha256']), _sign(value)),
             'witness authentication failed')
    return value


def apply(conn, document, *, expected_backup, expected_account, expected_deployment):
    value = validate(document)
    _require(value['backup'] == expected_backup, 'backup confirmation differs')
    _require(value['binding'][:3] == [expected_deployment, 'alpaca', expected_account],
             'account confirmation differs')
    operational_schema.require_idle_connection(conn)
    with journal.writer_lock(conn, recovery_only=True):
        conn.execute("SET LOCAL search_path = pg_catalog, public")
        conn.execute("SET LOCAL lock_timeout='2000ms'")
        conn.execute("SET LOCAL statement_timeout='15000ms'")
        locked = SOURCES | evidence_schema.extension_tables | operational_ddl_epoch.extension_tables | {
            'sentinel_automation_control', 'sentinel_automation_lease',
        }
        conn.execute(sql.SQL('LOCK TABLE {} IN SHARE MODE').format(
            sql.SQL(',').join(sql.Identifier('public', name) for name in sorted(locked))))
        schema.require_runtime_schema(conn)
        operational_schema.require_schema(conn)
        store.require_feed_schema(conn)
        deployment_fence.require(conn)
        control = automation_store.load_control(conn)
        _require(not control.enabled and control.kill_switch_engaged, 'disabled+killed control is required')
        _require(_system(conn) == value['system'] and coverage.binding(conn) == value['binding'],
                 'physical/account binding changed')
        ddl = operational_ddl_epoch.current(conn)
        _require(ddl == (value['ddl'][0], AFTER_EPOCH), 'DDL advance is not the exact compaction sequence')
        old = {}
        for domain in DOMAINS:
            head = coverage.head(conn, domain, lock=True)
            _require(list(head) == value['heads'][domain] and head[2] == 0, 'tracking head changed')
            payload = coverage._authenticated(conn, domain)
            _require(payload is not None and _prefix_digest(payload) == value['prefixes'][domain],
                     'old authenticated prefix changed')
            _require(payload['body'].get('stage') == 'COMPLETE'
                     and (payload['incarnation'], payload['through'], payload['reset_generation']) == head
                     and payload['binding'] == value['binding'], 'old prefix coordinates changed')
            material = coverage._inventory_material(conn, domain)
            material[-1] = value['ddl']
            _require(coverage.digest(material) == payload['inventory'], 'source relation inventory changed')
            old[domain] = payload
        _require(_source_digests(conn, SOURCES) == value['sources'], 'watched source rows changed')
        _require(operational_ddl_epoch.current(conn) == ddl, 'DDL changed during source verification')
        result = {}
        for domain, payload in old.items():
            updated = coverage.write(conn, domain, through=payload['through'], body=payload['body'])
            _require({key: item for key, item in updated.items() if key != 'inventory'}
                     == {key: item for key, item in payload.items() if key != 'inventory'},
                     'prefix content changed during transfer')
            result[domain] = _prefix_digest(coverage.require_current(conn, domain))
        conn.commit()
    return {'schema': RESULT_SCHEMA, 'witness_content_sha256': coverage.digest(document),
            'backup': expected_backup, 'prefixes': result, 'broker_contacted': False,
            'operational_ready': False}


def main(argv=None):
    from sentinel.restore_validation import _database_url

    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--snapshot', action='store_true')
    mode.add_argument('--apply', type=Path)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--marker')
    parser.add_argument('--metadata-sha256')
    parser.add_argument('--confirm-witness-sha256')
    parser.add_argument('--expect-account')
    parser.add_argument('--deployment-id')
    args = parser.parse_args(argv)
    try:
        signal.alarm(600)
        with store.connect(_database_url(), connect_timeout=3, statement_timeout_ms=15000) as conn:
            if args.snapshot:
                result = snapshot(conn, backup=args.backup, marker=args.marker,
                                  metadata_sha256=args.metadata_sha256)
                conn.rollback()
            else:
                raw = args.apply.read_bytes()
                _require(hashlib.sha256(raw).hexdigest() == args.confirm_witness_sha256,
                         'exact witness confirmation required')
                result = apply(conn, shared._document(raw), expected_backup=args.backup,
                               expected_account=args.expect_account,
                               expected_deployment=args.deployment_id)
        print(json.dumps(result, sort_keys=True, separators=(',', ':')))
        return 0
    except Exception as exc:
        print('REFUSED: ' + type(exc).__name__ + ': ' + str(exc))
        return 2
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    raise SystemExit(main())
