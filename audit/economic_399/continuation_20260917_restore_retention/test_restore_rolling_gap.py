"""Audit #399: restore validator must consume current rolling restart authority."""
import json
import psycopg
import pytest
from sentinel import restore_validation, rolling_checkpoint as cp
from sentinel.feed import rolling_store
from tests.conftest import isolated_image_backup_policy, isolated_source_cache
from tests.sentinel.test_rolling_initialization import ready, start, OBS
from tests.sentinel.test_operational_snapshot import operational_source
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source


def validate_fresh(dsn):
    with psycopg.connect(dsn) as fresh:
        return restore_validation.validate_restored_database(fresh)


@pytest.mark.parametrize('damage', ['checkpoint_authentication', 'current_snapshot_payload'])
def test_actual_rolling_corruption_is_missed_by_restore_semantic_validator(
        conn, ready, damage, monkeypatch, capsys):
    result = start(conn)
    assert cp.read(conn).state_sha256 == result.state.state_hash
    conn.commit()
    before = validate_fresh(conn.info.dsn)
    assert before['restart_state_present'] is False
    assert before['transaction_read_only'] is True
    if damage == 'checkpoint_authentication':
        # Fault injection into a disposable restored-state model, not a write
        # reachable through normal signed-checkpoint production APIs.
        conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{hmac_sha256}',%s::jsonb) WHERE cursor_name=%s",
                     (json.dumps('f'*64), cp.CURSOR))
        conn.commit()
        with pytest.raises(cp.RollingColdStartRefused, match='AUTHENTICATION_FAILED'):
            cp.read(conn)
        conn.rollback()
    else:
        # Controlled storage-corruption injection, matching existing snapshot
        # integrity tests. Real immutable-payload protections remain unchanged.
        conn.execute('SET LOCAL session_replication_role=replica')
        conn.execute('UPDATE sentinel_snapshot_bars SET close_unadjusted=1 WHERE candidate_id=%s AND session=%s',
                     (ready['candidate_id'], '2026-09-14'))
        conn.commit()
        with pytest.raises(rolling_store.SnapshotStorageRefused, match='manifest'):
            rolling_store.verify_content(conn, ready['candidate_id'])
        conn.rollback()
    # The real read-only restore validator still returns its success object.
    after = validate_fresh(conn.info.dsn)
    assert after == before
    monkeypatch.setenv('SENTINEL_DATABASE_URL', conn.info.dsn)
    exit_code = restore_validation.main()
    assert exit_code == 0
    output = capsys.readouterr().out
    emitted = [line for line in output.splitlines() if line.startswith('restored_database_semantics_ready:true ')]
    assert len(emitted) == 1
    assert json.loads(emitted[0].split(' ', 1)[1]) == before
    print(json.dumps({'damage': damage, 'state_hash': result.state.state_hash,
                      'restore_result': after, 'actual_main_exit': exit_code,
                      'actual_main_emitted': emitted[0]}, sort_keys=True))
