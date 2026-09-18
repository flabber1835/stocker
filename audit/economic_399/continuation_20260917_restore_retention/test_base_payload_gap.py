"""Audit #399: physical base payload is outside the runtime durability proof."""
import json
import subprocess

import psycopg
import pytest

from sentinel import backup_runtime_authority as authority
from sentinel.execution.journal import writer_lock
from tests.internal_state.physical import PhysicalCluster
from tests.support.postgres import _as_pg_user


def verify(cluster, base):
    return subprocess.run(
        _as_pg_user([cluster.binaries['pg_verifybackup'],
                     '--ignore=sentinel-recovery-marker',
                     '--ignore=sentinel-pitr-base-identity', str(base)]),
        capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize('damage', ['missing_control', 'same_size_version_corruption'])
def test_actual_physical_base_damage_is_missed_by_runtime_writer_gate(damage):
    cluster = PhysicalCluster()
    try:
        cluster.start()
        cluster.sql('CREATE TABLE audit399_durability_probe(note text NOT NULL)')
        checkpoint = cluster.checkpoint('economic_baseline')
        base = checkpoint['base']
        initial = verify(cluster, base)
        assert initial.returncode == 0, initial.stderr
        with cluster.runtime(), psycopg.connect(cluster.dsn) as conn:
            healthy = authority.require(conn, operation='audit399 intact base control')
            assert healthy['enabled'] is True
            assert healthy['base_backup'] == base.name
            conn.rollback()
            if damage == 'missing_control':
                (base / 'global/pg_control').unlink()
            else:
                version = base / 'PG_VERSION'
                original = version.read_bytes()
                assert len(original) == 3
                version.write_bytes(b'99\n')
                assert version.stat().st_size == len(original)
            broken = verify(cluster, base)
            assert broken.returncode != 0
            assert ('pg_control' if damage == 'missing_control' else 'PG_VERSION') in broken.stderr
            # Requiring a fresh complete WAL scrub must still not supply the
            # omitted physical-base-payload verification.
            authority._PROOF_CACHE.clear()
            after = authority.require(conn, operation='audit399 damaged base')
            assert after['enabled'] is True
            assert after['base_backup'] == base.name
            assert after['integrity_full_scrub'] is True
            conn.rollback()
            with writer_lock(conn):
                conn.execute('INSERT INTO audit399_durability_probe VALUES (%s)', (damage,))
                conn.commit()
            assert conn.execute('SELECT note FROM audit399_durability_probe').fetchone() == (damage,)
            conn.rollback()
            print(json.dumps({'damage': damage,
                'physical_verifier_before': initial.returncode,
                'physical_verifier_after': broken.returncode,
                'physical_verifier_error': broken.stderr.strip(),
                'runtime_proof_after': after,
                'protected_writer_commit_after_damage': True}, sort_keys=True))
    finally:
        cluster.close()
