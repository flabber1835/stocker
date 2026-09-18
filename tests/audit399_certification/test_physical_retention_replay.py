"""Audit #399: physical WAL replay of actual rolling economic state and retention.

Uses the repository PhysicalCluster harness, production archive command, real
pg_basebackup/pg_verifybackup, and named replay targets in an isolated cluster.
External market/broker/deployment qualification remains a separate gate.
"""
import hashlib
import json
import uuid

import psycopg
import pytest

from sentinel import backup_runtime_authority, rolling_runtime as runtime
from sentinel import rolling_initialization as initial
from sentinel.feed import rolling_store, runtime_schema, store
from tests.internal_state.physical import PhysicalCluster
from tests.sentinel.test_rolling_snapshot_publisher import source  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_rolling_initialization import OBS
from tests.sentinel.test_rolling_daily import refresh
from tests.audit399_certification.test_snapshot_retention_restore import _manifest, _maintenance, KW


@pytest.fixture
def physical():
    cluster = PhysicalCluster()
    try:
        cluster.start()  # Missing binaries or archive failures are errors, never skips.
        backup_runtime_authority._PROOF_CACHE.clear()
        with cluster.runtime():
            yield cluster
    finally:
        backup_runtime_authority._PROOF_CACHE.clear()
        cluster.close()


@pytest.fixture
def conn(physical):
    c = store.connect(physical.dsn)
    runtime_schema.migrate_feed_schema(c)
    try:
        yield c
    finally:
        c.close()


@pytest.mark.parametrize('target', ['before-retirement', 'after-retirement'])
def test_real_physical_replay_preserves_rolling_book_and_retention_atomicity(
        physical, conn, published, operational_source, monkeypatch, record_property, target):
    conn.execute('CREATE TABLE audit399_recovery_control(note text NOT NULL)')
    conn.execute("INSERT INTO audit399_recovery_control VALUES('at-target')")
    conn.commit()
    runtime.advance(conn, through='2026-09-14', **KW)
    old_publication = refresh(conn, operational_source, monkeypatch)
    old = runtime.advance(conn, through='2026-09-15', **KW)
    assert old.state.wealth_core['episodes']
    _maintenance(conn, 50000)
    conn.rollback()
    # The base precedes the economic transition, action/publication receipt,
    # checkpoint/authority commits and the retirement being tested.
    base = physical.checkpoint('economic_baseline')
    manifest_sha = hashlib.sha256((base['base']/'backup_manifest').read_bytes()).hexdigest()
    new_publication = refresh(conn, operational_source, monkeypatch)
    advanced = runtime.advance(conn, through='2026-09-16', **KW)
    assert advanced.state.wealth_core['episodes']
    if target == 'after-retirement':
        assert _maintenance(conn, 5000) == 7800
    conn.rollback()
    point = 'audit399_' + target.replace('-', '_') + '_' + uuid.uuid4().hex
    lsn = physical.sql('SELECT pg_create_restore_point(%s)::text', (point,))[0]
    wal = physical.sql('SELECT pg_walfile_name(%s::pg_lsn)', (lsn,))[0]
    # Explicit audit target: same verified pre-transition base, later archived
    # named point. This does not replace any production backup marker metadata.
    physical.checkpoints['audit_target'] = dict(base, marker=point, wal=wal)
    expected = _manifest(conn)
    conn.rollback()
    if target == 'before-retirement':
        assert _maintenance(conn, 5000) == 7800
    conn.execute("UPDATE audit399_recovery_control SET note='after-target'")
    conn.commit()
    assert rolling_store.retired(conn, old_publication['candidate_id'])
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_bars WHERE candidate_id=%s',
                        (old_publication['candidate_id'],)).fetchone()[0] == 0
    conn.rollback()
    physical.sql('SELECT pg_switch_wal()')
    archived = physical.wait_archive(wal)
    assert archived.is_file() and archived.with_name(archived.name+'.sha256').is_file()
    assert _manifest(conn) != expected
    conn.close()

    physical.restore('audit_target')  # Stops the primary, copies the base, replays, promotes.
    with psycopg.connect(physical.dsn) as restored:
        assert restored.execute('SELECT pg_is_in_recovery()').fetchone() == (False,)
        assert restored.execute("SELECT note FROM audit399_recovery_control").fetchone() == ('at-target',)
        assert restored.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0] == base['system_id']
        assert _manifest(restored) == expected
        assert rolling_store.retired(restored, old_publication['candidate_id']) is (target == 'after-retirement')
        expected_old_rows = 0 if target == 'after-retirement' else 7500
        assert restored.execute('SELECT count(*) FROM sentinel_snapshot_bars WHERE candidate_id=%s',
                                (old_publication['candidate_id'],)).fetchone()[0] == expected_old_rows
        assert restored.execute('SELECT count(*) FROM sentinel_snapshot_bars WHERE candidate_id=%s',
                                (new_publication['candidate_id'],)).fetchone()[0] == 7500
        restored.rollback()
        classification = runtime.classify(restored, structural_only=True, **KW)
        assert classification == {'status':'ATTESTED_STRUCTURAL','latest_session':'2026-09-16'}
        checkpoint, _, result, attested, _ = runtime._closure(restored, initial._context(OBS, 100000))
        assert result.state.state_hash == advanced.state.state_hash
        assert result.state.wealth_core == advanced.state.wealth_core
        assert result.state.ledger == advanced.state.ledger
        assert result.state.controller == advanced.state.controller
        assert attested is not None and checkpoint.session == '2026-09-16'
        restored.rollback()
        backup_runtime_authority._PROOF_CACHE.clear()
        proof = backup_runtime_authority.require(restored, operation='audit399 physical restored closure')
        assert proof['enabled'] is True
        assert proof['base_backup'] == physical.checkpoints['after_restore']['base'].name
        record_property('replay_target', target)
        record_property('target_lsn', lsn)
        record_property('target_wal', wal)
        record_property('base_manifest_sha256', manifest_sha)
        record_property('snapshot_public_tables', len(expected))
        record_property('snapshot_sha256', hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest())
        record_property('state_sha256', advanced.state.state_hash)
        record_property('restored_old_price_rows', expected_old_rows)
        record_property('backup_proof', json.dumps(proof, sort_keys=True, default=str))
