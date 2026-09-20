"""Structural restore consumes the authenticated rolling book and current tape."""
import json
import psycopg
import pytest

from sentinel import restore_validation, rolling_checkpoint
from sentinel.feed import rolling_store
from tests.sentinel.test_rolling_initialization import ready, start
from tests.sentinel.test_operational_snapshot import operational_source
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source


@pytest.mark.parametrize('damage', ['checkpoint', 'snapshot', 'missing-origin'])
def test_restore_refuses_corrupt_current_rolling_dependencies(conn, ready, damage, monkeypatch):
    from sentinel.feed import runtime_schema
    monkeypatch.setattr(restore_validation.feed_store, 'require_feed_schema', runtime_schema.require_feed_schema)
    start(conn)
    conn.commit()
    with psycopg.connect(conn.info.dsn) as restored:
        report = restore_validation.validate_restored_database(restored)
        assert report['restart_state_present'] and report['transaction_read_only']
    if damage == 'checkpoint':
        conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{hmac_sha256}',%s::jsonb) WHERE cursor_name=%s",
                     (json.dumps('f'*64), rolling_checkpoint.CURSOR))
        error, reason = rolling_checkpoint.RollingColdStartRefused, 'AUTHENTICATION_FAILED'
    elif damage == 'snapshot':
        conn.execute('SET LOCAL session_replication_role=replica')
        conn.execute('UPDATE sentinel_snapshot_bars SET close_unadjusted=1 WHERE candidate_id=%s AND session=%s',
                     (ready['candidate_id'], '2026-09-14'))
        error, reason = rolling_store.SnapshotStorageRefused, 'manifest'
    else:
        conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s', (rolling_checkpoint.CURSOR,))
        error, reason = restore_validation.RestoreValidationRefused, 'lineage without rolling origin'
    conn.commit()
    with psycopg.connect(conn.info.dsn) as restored:
        with pytest.raises(error, match=reason):
            restore_validation.validate_restored_database(restored)

__all__ = ['conn', 'operational_source', 'pg', 'ready', 'source']


def test_uninitialized_rolling_publication_is_a_valid_empty_restore(conn, ready, monkeypatch):
    from sentinel.feed import runtime_schema
    # The legacy-test autouse fixture replaces this read-only guard with DDL.
    monkeypatch.setattr(restore_validation.feed_store, 'require_feed_schema', runtime_schema.require_feed_schema)
    conn.commit()
    with psycopg.connect(conn.info.dsn) as restored:
        report = restore_validation.validate_restored_database(restored)
        assert report['rolling'] == {'state_present': False, 'publication_version': ready['data_version']}
        assert not report['restart_state_present']
        assert report['transaction_read_only']


@pytest.fixture
def restore_ready(operational_source, request, monkeypatch):
    operational_source['TICKERS'][0]['relatedtickers'] = 'AAA BBB'
    width = getattr(request, 'param', 25)
    if width > 25:
        from sentinel.feed import operational_snapshot
        original = operational_snapshot.prepare
        def expanded(*args, **kwargs):
            data = operational_source
            if len(data['TICKERS']) == 25:
                template = data['TICKERS'][0]
                prices = [row for row in data['SEP'] if row['ticker'] == 'AAA']
                for index in range(26, width + 1):
                    symbol = f'WIDE{index}'
                    data['TICKERS'].append({**template, 'ticker': symbol, 'permaticker': str(index)})
                    data['SEP'].extend({**row, 'ticker': symbol} for row in prices)
            return original(*args, **kwargs)
        monkeypatch.setattr(operational_snapshot, 'prepare', expanded)
    return request.getfixturevalue('ready')


@pytest.mark.parametrize('restore_ready', [25, 129], indirect=True, ids=['inline', 'compressed'])
def test_populated_physical_restore_preserves_book_and_advances_next_session(
        conn, restore_ready, operational_source, monkeypatch):
    """Copy real PG pages, verify them, boot independently, then resume production."""
    from copy import deepcopy
    import os
    from pathlib import Path
    import shutil
    from sentinel.feed import runtime_schema, store
    from sentinel import rolling_runtime
    from tests.support.postgres import (
        _EphemeralPostgres, _find_pg_bin, _run, _as_pg_user)
    from tests.sentinel.test_rolling_daily import refresh, resume
    from tests.sentinel.test_rolling_initialization import OBS
    monkeypatch.setattr(restore_validation.feed_store, 'require_feed_schema', runtime_schema.require_feed_schema)
    rolling_runtime.advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=100_000)
    refresh(conn, operational_source, monkeypatch)
    second = rolling_runtime.advance(conn, through='2026-09-15', observation_id=OBS, starting_cash=100_000)
    book = deepcopy(second.state.wealth_core)
    assert book['episodes'] and 0 < book['cash'] < 100_000
    conn.commit()

    restored_pg = _EphemeralPostgres()
    try:
        if os.geteuid() == 0:
            shutil.chown(restored_pg.datadir, user='postgres', group='postgres')
        backup = _run(_as_pg_user([
            _find_pg_bin('pg_basebackup'), '-d', conn.info.dsn,
            '-D', restored_pg.datadir, '-X', 'stream', '-c', 'fast']))
        assert backup.returncode == 0, backup.stderr
        verified = _run(_as_pg_user([
            _find_pg_bin('pg_verifybackup'), restored_pg.datadir]))
        assert verified.returncode == 0, verified.stderr
        boot = _run(_as_pg_user([
            _find_pg_bin('pg_ctl'), '-D', restored_pg.datadir,
            '-o', f'-p {restored_pg.port} -h 127.0.0.1 -k {restored_pg.datadir}',
            '-l', str(Path(restored_pg.datadir)/'restored.log'), '-w', 'start']))
        assert boot.returncode == 0, boot.stderr
        restored_pg._started = True
        dsn = restored_pg.sync_dsn.rsplit('/', 1)[0] + '/' + conn.info.dbname
        with store.connect(dsn) as restored:
            report = restore_validation.validate_restored_database(restored)
            assert report['transaction_read_only'] and report['restart_state_present']
            assert report['rolling']['session'] == second.session
        # A fresh writable runtime connection advances only the restored cluster.
        with store.connect(dsn) as restored:
            assert resume(restored).state.wealth_core == book
            refresh(restored, operational_source, monkeypatch)
            third = rolling_runtime.advance(restored, through='2026-09-16', observation_id=OBS, starting_cash=100_000)
            assert third.session == '2026-09-16'
            # This tape repeats yesterday's raw marks, with no actions or exit
            # triggers. The held shares and cash must not change on restart.
            assert third.state.wealth_core['cash'] == book['cash']
            old_shares = {slot: (e['security_id'], e['current_shares']) for slot, e in book['episodes'].items()}
            new_shares = {slot: (e['security_id'], e['current_shares']) for slot, e in third.state.wealth_core['episodes'].items()}
            assert new_shares == old_shares
            restored.commit()
        with store.connect(dsn) as reopened:
            assert resume(reopened).state.state_hash == third.state.state_hash
        # The original database was not advanced through the restored handle.
        assert resume(conn).state.state_hash == second.state.state_hash
    finally:
        restored_pg.stop()
