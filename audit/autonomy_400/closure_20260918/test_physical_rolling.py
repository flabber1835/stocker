"""Audit-only compound rolling-history physical restore and native backup proof."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

import psycopg
from psycopg import sql

from sentinel import rolling_runtime as runtime
from sentinel.feed import rolling_store, runtime_schema
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_initialization import OBS
from tests.sentinel.test_rolling_daily import refresh
from tests.support.postgres import _EphemeralPostgres, _find_pg_bin, _as_pg_user, _run


def fingerprints(connection):
    tables = [r[0] for r in connection.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()]
    result = {}
    for table in tables:
        rows = [r[0] for r in connection.execute(sql.SQL(
            'SELECT to_jsonb(t)::text FROM {} t ORDER BY to_jsonb(t)::text').format(sql.Identifier(table))).fetchall()]
        result[table] = {'rows': len(rows), 'sha256': hashlib.sha256(
            json.dumps(rows, separators=(',', ':')).encode()).hexdigest()}
    connection.commit()
    return result


def require(cmd):
    r = _run(cmd)
    assert r.returncode == 0, (cmd, r.returncode, r.stdout, r.stderr)
    return {'command': cmd, 'returncode': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr}


def test_cleanup_crash_physical_restore_promote_next_publication_converges(
        conn, pg, published, operational_source, monkeypatch):
    out = Path('/audit400/evidence/physical-rolling')
    out.mkdir(parents=True, exist_ok=True)
    commands = []
    first = runtime.advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=100000)
    old = published['candidate_id']
    second_pub = refresh(conn, operational_source, monkeypatch)
    assert not rolling_store.retired(conn, old)
    assert conn.execute('SELECT sentinel_snapshot_pins(%s)', (old,)).fetchone()[0] == ['RESTART_CHECKPOINT']
    conn.commit()
    second = runtime.service_advance(conn, through='2026-09-15', observation_id=OBS, starting_cash=100000)
    for _ in range(3):
        retry = runtime.service_advance(conn, through='2026-09-15', observation_id=OBS, starting_cash=100000)
        assert retry.state.state_hash == second.state.state_hash
    assert second.state.state_hash != first.state.state_hash
    assert rolling_store.retired(conn, old)
    assert not rolling_store.retired(conn, second_pub['candidate_id'])
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_bars WHERE candidate_id=%s', (old,)).fetchone()[0] == 0
    relation = conn.execute("SELECT pg_relation_filepath('sentinel_snapshot_bars')").fetchone()[0]
    conn.commit()
    before = fingerprints(conn)
    assert before['sentinel_action_history']['rows'] > 0
    assert before['sentinel_action_coverage']['rows'] > 0

    restored = _EphemeralPostgres()
    restored.dbname = conn.info.dbname
    if os.geteuid() == 0:
        shutil.chown(restored.datadir, user='postgres', group='postgres')
    data = Path(restored.datadir)
    try:
        commands.append(require(_as_pg_user([
            _find_pg_bin('pg_basebackup'), '--dbname', pg.sync_dsn,
            '--pgdata', restored.datadir, '--wal-method=stream', '--checkpoint=fast', '-R'])))
        commands.append(require(_as_pg_user([_find_pg_bin('pg_verifybackup'), restored.datadir])))

        # Native verification refuses each independently damaged copied backup.
        damage_results = []
        for damage in ('wal-gap', 'current-payload-byte'):
            damaged = Path(restored.datadir + '-' + damage)
            shutil.copytree(data, damaged)
            try:
                if damage == 'wal-gap':
                    files = sorted(p for p in (damaged/'pg_wal').iterdir()
                                   if p.is_file() and len(p.name) == 24)
                    assert files
                    files[0].unlink()
                else:
                    target = damaged/relation
                    assert target.is_file() and target.stat().st_size > 0
                    with target.open('r+b') as handle:
                        old_byte = handle.read(1)
                        handle.seek(0)
                        handle.write(bytes([old_byte[0] ^ 1]))
                r = _run([_find_pg_bin('pg_verifybackup'), str(damaged)])
                assert r.returncode != 0, damage
                damage_results.append({'damage': damage, 'returncode': r.returncode,
                                       'stdout': r.stdout, 'stderr': r.stderr})
            finally:
                shutil.rmtree(damaged)

        # An uncommitted diagnostic mutation dies with the source server.
        conn.execute("UPDATE sentinel_snapshot_maintenance SET diagnostic=diagnostic || "
                     "'{\"audit_uncommitted\":true}'::jsonb")
        commands.append(require(_as_pg_user([_find_pg_bin('pg_ctl'), '-D', pg.datadir,
                                              '-m', 'immediate', '-w', '-t', '30', 'stop'])))
        pg._started = False
        conn.close()
        options = f'-p {restored.port} -h 127.0.0.1 -k {restored.datadir}'
        commands.append(require(_as_pg_user([_find_pg_bin('pg_ctl'), '-D', restored.datadir,
                                              '-o', options, '-l', str(data/'server.log'),
                                              '-w', '-t', '30', 'start'])))
        restored._started = True
        with psycopg.connect(restored.sync_dsn) as check:
            assert check.execute('SELECT pg_is_in_recovery()').fetchone()[0]
        commands.append(require(_as_pg_user([_find_pg_bin('pg_ctl'), '-D', restored.datadir,
                                              '-w', '-t', '30', 'promote'])))
        with psycopg.connect(restored.sync_dsn) as recovered:
            assert recovered.execute('SELECT pg_is_in_recovery()').fetchone()[0] is False
            recovered.commit()
            after = fingerprints(recovered)
            assert after == before
            runtime_schema.require_feed_schema(recovered)
            recovered.rollback()
            state = runtime.status(recovered, observation_id=OBS, starting_cash=100000)
            assert state.state.state_hash == second.state.state_hash
            assert state.verification == 'VERIFIED'
            assert rolling_store.retired(recovered, old)
            recovered.commit()
            third_pub = refresh(recovered, operational_source, monkeypatch)
            third = runtime.service_advance(recovered, through='2026-09-16', observation_id=OBS, starting_cash=100000)
            again = runtime.service_advance(recovered, through='2026-09-16', observation_id=OBS, starting_cash=100000)
            assert third.verification == again.verification == 'VERIFIED'
            assert third.state.state_hash == again.state.state_hash != second.state.state_hash
            recovered.commit()
            report = {'tables': before, 'table_count': len(before), 'fingerprints_equal_after_promotion': True,
                      'origin_retired': old, 'current_publication': second_pub,
                      'next_publication': third_pub, 'restored_state_hash': state.state.state_hash,
                      'next_state_hash': third.state.state_hash, 'damage_results': damage_results,
                      'commands': commands}
            (out/'measurements.json').write_text(json.dumps(report, indent=2, default=str))
    finally:
        if (data/'server.log').exists():
            shutil.copyfile(data/'server.log', out/'restored-postgres.log')
        restored.stop()
        # Restore the test-owned source only so its existing fixture can drop
        # its private database during teardown. It stays stopped throughout
        # the entire restore/promotion/runtime-continuation assertion chain.
        if not pg._started:
            recovery = _run(_as_pg_user([_find_pg_bin('pg_ctl'), '-D', pg.datadir,
                '-l', str(Path(pg.datadir)/'server.log'),
                '-o', f'-p {pg.port} -h 127.0.0.1 -k {pg.datadir}', '-w', '-t', '30', 'start']))
            pg._started = recovery.returncode == 0
            assert pg._started, recovery.stderr
