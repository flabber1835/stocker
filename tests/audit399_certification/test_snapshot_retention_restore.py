"""Audit #399: real PostgreSQL exported snapshots across economic handoff + GC.

Production SHA aff4461d9af6d4a7367018768fda18d948958b49. All source, strategy,
and persistence operations are the pinned implementation. The external source,
producer attestation, clock and absent backup media use existing test fixtures.
Logical pg_dump/pg_restore is exercised, not physical PITR or deployed acceptance.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import uuid

import psycopg
from psycopg import sql
import pytest

from sentinel import rolling_runtime as runtime, rolling_initialization as initial
from sentinel import rolling_daily as daily, rolling_authority as authority
from sentinel.feed import retention, rolling_store, calendar
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_initialization import OBS
from tests.sentinel.test_rolling_daily import refresh
from tests.support.postgres import _find_pg_bin

KW = dict(observation_id=OBS, starting_cash=100000)
MAINTAIN = retention.maintain


def _manifest(c):
    """Independent complete PUBLIC-table row/count fingerprint, sorted by value."""
    tables = [r[0] for r in c.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
    out = {}
    for name in tables:
        count, checksum = c.execute(sql.SQL(
            "SELECT count(*), md5(COALESCE(string_agg(row_to_json(t)::text, E'\\n' "
            "ORDER BY row_to_json(t)::text),'')) FROM public.{} t"
        ).format(sql.Identifier(name))).fetchone()
        out[name] = {"rows": count, "md5_sorted_rows": checksum}
    return out


def _maintenance(c, batch):
    deleted = 0
    for _ in range(12):
        c.rollback()
        result = MAINTAIN(c, batch_rows=batch)
        assert result['status'] == 'COMPLETE', result
        deleted += result['deleted_rows']
        if not result['more_work']:
            return deleted
    pytest.fail('controlled two-generation cleanup did not converge in 12 passes')


@contextmanager
def _restored(pg, dump):
    name = 'audit399_restored_' + uuid.uuid4().hex
    with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    dsn = pg.sync_dsn.rsplit('/', 1)[0] + '/' + name
    try:
        result = subprocess.run([_find_pg_bin('pg_restore'), '--dbname', dsn,
            '--exit-on-error', '--no-owner', '--no-privileges', str(dump)],
            capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, (result.stdout, result.stderr)
        with psycopg.connect(dsn) as restored:
            yield restored
    finally:
        with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


@pytest.mark.parametrize('batch', [5000, 50000], ids=['bounded-batches','single-batch'])
@pytest.mark.parametrize('phase', ['before-publication','after-publication',
                                  'trailing-candidate','attested'])
def test_exported_snapshot_keeps_economic_closure_after_live_gc(
        conn, pg, published, operational_source, monkeypatch, tmp_path,
        record_property, batch, phase):
    runtime.advance(conn, through='2026-09-14', **KW)
    old_publication = refresh(conn, operational_source, monkeypatch)
    old = runtime.advance(conn, through='2026-09-15', **KW)
    assert old.state.wealth_core['episodes']
    assert 0 < old.state.wealth_core['cash'] < 100000
    _maintenance(conn, 50000)
    conn.rollback()

    new_publication = None
    live = None
    if phase != 'before-publication':
        new_publication = refresh(conn, operational_source, monkeypatch)
    if phase == 'trailing-candidate':
        original = authority.append
        def before_authority(*args, **kwargs):
            raise RuntimeError('AUDIT_TRAILING_CANDIDATE_BOUNDARY')
        monkeypatch.setattr(authority, 'append', before_authority)
        with pytest.raises(RuntimeError, match='AUDIT_TRAILING_CANDIDATE_BOUNDARY'):
            runtime.advance(conn, through='2026-09-16', **KW)
        monkeypatch.setattr(authority, 'append', original)
        assert runtime.classify(conn, structural_only=True, **KW)['status'] == 'RECOVERY_REQUIRED'
    elif phase == 'attested':
        live = runtime.advance(conn, through='2026-09-16', **KW)
    conn.rollback()

    with psycopg.connect(conn.info.dsn) as snapshot:
        snapshot.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        snapshot_id = snapshot.execute('SELECT pg_export_snapshot()').fetchone()[0]
        expected = _manifest(snapshot)
        old_rows = snapshot.execute('SELECT count(*) FROM sentinel_snapshot_bars WHERE candidate_id=%s',
                                   (old_publication['candidate_id'],)).fetchone()[0]
        assert old_rows == 7500
        # Work proceeds through a different connection while the snapshot lives.
        if phase == 'before-publication':
            new_publication = refresh(conn, operational_source, monkeypatch)
        if live is None:
            live = runtime.advance(conn, through='2026-09-16', **KW)
        assert live.state.wealth_core['episodes']
        deleted = _maintenance(conn, batch)
        assert deleted == 7800
        assert rolling_store.retired(conn, old_publication['candidate_id'])
        assert conn.execute('SELECT count(*) FROM sentinel_snapshot_bars WHERE candidate_id=%s',
                            (old_publication['candidate_id'],)).fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM sentinel_snapshot_bars WHERE candidate_id=%s',
                            (new_publication['candidate_id'],)).fetchone()[0] == 7500
        conn.commit()
        assert _manifest(snapshot) == expected  # Every table remains snapshot-consistent.
        dump = tmp_path / (phase + '.dump')
        result = subprocess.run([_find_pg_bin('pg_dump'), '--dbname', conn.info.dsn,
            '--format=custom', '--snapshot', snapshot_id, '--no-owner', '--no-privileges',
            '--file', str(dump)], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, (result.stdout, result.stderr)

    # Restore occurs after the exporter has released its transaction and after
    # the original live payload was actually deleted. Compare complete tables.
    with _restored(pg, dump) as restored:
        actual = _manifest(restored)
        assert actual == expected
        restored.rollback()
        classification = runtime.classify(restored, structural_only=True, **KW)
        context = initial._context(OBS, 100000)
        checkpoint, _, state, attested, _ = runtime._closure(restored, context)
        restored.rollback()
        if phase == 'before-publication':
            assert classification['status'] == 'ATTESTED_STRUCTURAL'
            assert state.state.state_hash == old.state.state_hash
            assert checkpoint.session == '2026-09-15'
        else:
            if phase == 'after-publication':
                assert classification['status'] == 'ATTESTED_STRUCTURAL'
                assert checkpoint.session == '2026-09-15'
                assert state.state.state_hash == old.state.state_hash
                result = runtime.advance(restored, through='2026-09-16', **KW)
            else:
                assert classification['status'] == ('RECOVERY_REQUIRED' if phase == 'trailing-candidate'
                                                     else 'ATTESTED_STRUCTURAL')
                def replay_forbidden(*args, **kwargs):
                    pytest.fail('committed economic transition replayed after restore')
                with monkeypatch.context() as m:
                    m.setattr(daily, 'advance', replay_forbidden)
                    m.setattr(initial, 'initialize', replay_forbidden)
                    result = runtime.advance(restored, through='2026-09-16', **KW)
            assert result.state.state_hash == live.state.state_hash
            assert result.state.wealth_core == live.state.wealth_core
            assert result.state.ledger == live.state.ledger
            assert result.state.controller == live.state.controller
        record_property('phase', phase)
        record_property('batch_rows', batch)
        record_property('live_deleted_rows', deleted)
        record_property('snapshot_public_tables', len(expected))
        record_property('snapshot_sha256', hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest())
        record_property('old_state_sha256', old.state.state_hash)
        record_property('advanced_state_sha256', live.state.state_hash)
        record_property('dump_sha256', hashlib.sha256(dump.read_bytes()).hexdigest())
