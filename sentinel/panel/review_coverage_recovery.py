"""Exact dashboard DDL recovery from an isolated physical pre-DDL witness.

Ordinary readers never enter this operator-owned recovery. Shared streaming
source-byte proofs retain every progress-recovery source and scratch guard.
"""
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
from sentinel.panel import review_schema, review_migration

SCHEMA = 'sentinel.dashboard-ddl-coverage-witness/1'
DOMAINS = review_migration.DOMAINS
DDL_ADVANCE = review_migration.DDL_ADVANCE
RecoveryRefused = shared.RecoveryRefused
_require = shared._require
_prefix_digest = shared._prefix_digest
_mandatory_sources = shared._mandatory_sources
_source_candidates = shared._source_candidates
_sources = shared._sources
_source_digests = shared._source_digests
_document = shared._document


class Witness(shared.Witness):
    schema_version: Literal['sentinel.dashboard-ddl-coverage-witness/1']
    review_contract_sha256: str


def _sign(value):
    from sentinel.feed.publication import _receipt_hmac
    return _receipt_hmac({'purpose': SCHEMA, 'witness': value})


def _review_contract():
    return coverage.digest(review_schema.DDL)


def _validate_predecessor(conn):
    schema.require_runtime_schema(conn)
    operational_schema.require_schema(conn)
    _require(not review_schema.require_schema(conn, allow_absent=True),
             'dashboard witness requires the actual pre-DDL schema')


def _snapshot(conn, *, backup, marker, metadata_sha256):
    """Capture the already established prefix; callers enforce restore isolation."""
    _validate_predecessor(conn)
    _require(conn.execute('SELECT 1 FROM sentinel_backup_recovery_markers WHERE marker=%s',
                         (marker,)).fetchone(), 'restore marker is absent')
    deployment_fence.require(conn)
    heads = {}; prefixes = {}
    for domain in DOMAINS:
        payload = coverage.require_current(conn, domain)
        heads[domain] = coverage.head(conn, domain)
        _require(heads[domain][2] == 0, 'tracking has been reset')
        prefixes[domain] = _prefix_digest(payload)
    value = Witness(schema_version=SCHEMA, review_contract_sha256=_review_contract(), backup=backup, marker=marker,
        metadata_sha256=metadata_sha256,
        system=str(conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]),
        binding=coverage.binding(conn), ddl=operational_ddl_epoch.current(conn),
        heads=heads, prefixes=prefixes,sources=_source_digests(conn)).model_dump(mode='json')
    return {'witness': value, 'hmac_sha256': _sign(value)}


def snapshot(conn, **kwargs):
    """Only a paused physical recovery may issue a pre-migration witness."""
    conn.execute('SET TRANSACTION READ ONLY')
    restored=conn.execute('SELECT pg_is_in_recovery()').fetchone()[0]
    _require(restored is True and conn.execute('SELECT pg_get_wal_replay_pause_state()').fetchone()[0]=='paused',
             'witness requires a paused isolated physical restore')
    return _snapshot(conn, **kwargs)


def validate(document):
    _require(isinstance(document,dict) and set(document)=={'witness','hmac_sha256'},
             'witness envelope is malformed')
    value = Witness.model_validate(document['witness']).model_dump(mode='json')
    _require(value['review_contract_sha256']==_review_contract(), 'dashboard migration contract changed')
    _require(set(value['heads']) == set(DOMAINS) == set(value['prefixes']), 'witness domains differ')
    _require(_mandatory_sources()<=set(value['sources'])<=_source_candidates(), 'witness source relations differ')
    _require(value['ddl'][1] >= 0 and all(len(v)==64 and all(c in '0123456789abcdef' for c in v)
        for v in value['prefixes'].values()), 'witness coordinates are malformed')
    _require(hmac.compare_digest(str(document['hmac_sha256']),_sign(value)),
             'witness authentication failed')
    return value


def apply(conn, document, *, expected_backup, expected_account, expected_deployment):
    """Transfer both exact prefixes atomically while every watched source is locked."""
    value = validate(document)
    _require(value['backup']==expected_backup, 'backup confirmation differs')
    _require(value['binding'][0]==expected_deployment and value['binding'][1]=='alpaca'
        and value['binding'][2]==expected_account, 'account confirmation differs')
    operational_schema.require_idle_connection(conn)
    with journal.writer_lock(conn, recovery_only=True):
        conn.execute("SET LOCAL lock_timeout='2000ms'")
        conn.execute("SET LOCAL statement_timeout='15000ms'")
        watched = _sources(conn)
        _require(watched==set(value['sources']), 'source relation set changed')
        locked = watched | set(evidence_schema.extension_tables) | set(operational_ddl_epoch.extension_tables)
        conn.execute(sql.SQL('LOCK TABLE {} IN SHARE MODE').format(
            sql.SQL(',').join(sql.Identifier(name) for name in sorted(locked))))
        schema.require_runtime_schema(conn)
        operational_schema.require_schema(conn)
        review_schema.require_schema(conn)
        deployment_fence.require(conn)
        control = automation_store.load_control(conn)
        _require(not control.enabled and control.kill_switch_engaged, 'disabled+killed control is required')
        _require(str(conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0])
            == value['system'] and coverage.binding(conn)==value['binding'], 'physical/account binding changed')
        ddl = operational_ddl_epoch.current(conn)
        _require(ddl[0]==value['ddl'][0] and ddl[1]==value['ddl'][1]+DDL_ADVANCE,
                 'DDL advance is not the exact dashboard migration')
        old = {}
        for domain in DOMAINS:
            _require(list(coverage.head(conn,domain,lock=True))==value['heads'][domain], 'tracking head changed')
            payload = coverage._authenticated(conn,domain)
            _require(payload is not None and _prefix_digest(payload)==value['prefixes'][domain],
                     'old authenticated prefix changed')
            _require(payload['body'].get('stage')=='COMPLETE'
                and payload['through']==value['heads'][domain][1]
                and payload['incarnation']==value['heads'][domain][0]
                and payload['reset_generation']==value['heads'][domain][2]==0
                and payload['binding']==value['binding'], 'old prefix coordinates changed')
            material = coverage._inventory_material(conn,domain)
            material[-1] = value['ddl']
            _require(coverage.digest(material)==payload['inventory'], 'source relation inventory changed')
            old[domain] = payload
        _require(_source_digests(conn)==value['sources'], 'watched source rows changed')
        _require(operational_ddl_epoch.current(conn)==ddl, 'DDL changed during source verification')
        result = {}
        for domain, payload in old.items():
            new = coverage.write(conn,domain,through=payload['through'],body=payload['body'])
            _require({k:v for k,v in new.items() if k!='inventory'}
                == {k:v for k,v in payload.items() if k!='inventory'}, 'prefix content changed during transfer')
            result[domain] = _prefix_digest(coverage.require_current(conn,domain))
        conn.commit()
    return {'schema':'sentinel.dashboard-ddl-coverage-transfer/1',
        'witness_content_sha256':coverage.digest(document), 'backup':expected_backup,
        'prefixes':result, 'broker_contacted':False, 'operational_ready':False}


def main(argv=None):
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
    from sentinel.feed import store
    from sentinel.restore_validation import _database_url
    conn = None
    try:
        signal.alarm(600)
        conn = store.connect(_database_url(),connect_timeout=3,statement_timeout_ms=15000)
        if args.snapshot:
            result = snapshot(conn,backup=args.backup,marker=args.marker,metadata_sha256=args.metadata_sha256)
        else:
            raw=args.apply.read_bytes()
            document = _document(raw)
            _require(hashlib.sha256(raw).hexdigest()==args.confirm_witness_sha256,
                     'exact witness confirmation required')
            result = apply(conn,document,expected_backup=args.backup,expected_account=args.expect_account,
                           expected_deployment=args.deployment_id)
        print(json.dumps(result,sort_keys=True,separators=(',',':')))
        return 0
    except Exception as exc:
        print('REFUSED: '+type(exc).__name__+': '+str(exc))
        return 2
    finally:
        signal.alarm(0)
        if conn is not None:
            conn.rollback();conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
