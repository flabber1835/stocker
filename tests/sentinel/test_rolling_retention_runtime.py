"""Current checkpoint pins, unattended retry, and database restore after GC."""
import subprocess
import uuid
import pytest

from sentinel import rolling_runtime as runtime
from sentinel.feed import retention, rolling_store, runtime_schema
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_initialization import OBS
from tests.sentinel.test_rolling_daily import refresh
from tests.support.postgres import _find_pg_bin

__all__ = ['conn', 'pg', 'source', 'operational_source', 'issuer_source', 'published', 'ready']


@pytest.mark.parametrize('instant,expected',[
    ('2026-10-15T13:14:59+00:00',False),('2026-10-15T13:15:00+00:00',True),
    ('2026-10-15T13:39:59+00:00',True),('2026-10-15T13:40:00+00:00',False),
    ('2026-11-16T14:20:00+00:00',True),('2026-10-17T13:30:00+00:00',False)])
def test_retention_opening_deferral_follows_actual_xnys(instant,expected):
    from datetime import datetime
    assert retention.opening_execution_due(datetime.fromisoformat(instant)) is expected


def test_opening_deferral_precedes_writer_and_has_a_removal_falsifier(monkeypatch):
    from types import SimpleNamespace
    from contextlib import contextmanager
    from sentinel.execution import journal
    from datetime import datetime
    class Clock:
        @staticmethod
        def now(*_):return datetime.fromisoformat('2026-10-15T13:31:00+00:00')
    monkeypatch.setattr(retention,'datetime',Clock)
    monkeypatch.setattr(retention,'_possible_work',lambda _:True)
    conn=SimpleNamespace(info=SimpleNamespace(transaction_status=SimpleNamespace(value=0)),
        execute=lambda *_a,**_k:None,commit=lambda:None,rollback=lambda:None)
    acquired=[]
    @contextmanager
    def writer(_):
        acquired.append(True)
        raise RuntimeError('writer acquisition detected')
        yield
    monkeypatch.setattr(journal,'writer_lock',writer)
    assert retention.maintain(conn)['status']=='DEFERRED'
    assert not acquired
    monkeypatch.setattr(retention,'opening_execution_due',lambda _:False)
    assert retention.maintain(conn)['status']=='RETRY'
    assert acquired==[True]


def test_checkpoint_handoff_releases_origin_prices_and_restore_keeps_current_closure(
        conn, published, operational_source, monkeypatch, tmp_path, pg):
    import psycopg
    from psycopg import sql
    monkeypatch.setattr(retention, 'opening_execution_due', lambda _: False)
    first = runtime.advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=100000)
    original = published['candidate_id']
    second_pub = refresh(conn, operational_source, monkeypatch)
    # Publication changed, but the old snapshot is still required for overlap.
    assert not rolling_store.retired(conn, original)
    assert conn.execute('SELECT sentinel_snapshot_pins(%s)', (original,)).fetchone()[0] == ['RESTART_CHECKPOINT']
    conn.commit()
    second = runtime.service_advance(conn, through='2026-09-15', observation_id=OBS, starting_cash=100000)
    assert second.state.state_hash != first.state.state_hash
    # Production-sized fixture exceeds one batch. Idle passes finish cleanup
    # independently of the ordinary verified-state poll.
    for _ in range(3):
        retention.idle_pass(conn.info.dsn)
    again = runtime.service_advance(conn, through='2026-09-15', observation_id=OBS, starting_cash=100000)
    assert again.state.state_hash == second.state.state_hash
    assert rolling_store.retired(conn, original)
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_bars WHERE candidate_id=%s', (original,)).fetchone()[0] == 0
    assert not rolling_store.retired(conn, second_pub['candidate_id'])
    conn.commit()
    dump = tmp_path / 'after-cleanup.dump'
    subprocess.run([_find_pg_bin('pg_dump'), '--dbname', conn.info.dsn, '-Fc', '-f', str(dump)], check=True, capture_output=True)
    restored_name = 'restored_' + uuid.uuid4().hex
    with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(restored_name)))
    restored_dsn = pg.sync_dsn.rsplit('/', 1)[0] + '/' + restored_name
    try:
        subprocess.run([_find_pg_bin('pg_restore'), '--dbname', restored_dsn, '--exit-on-error', str(dump)],
                       check=True, capture_output=True)
        with psycopg.connect(restored_dsn) as restored:
            runtime_schema.require_feed_schema(restored)
            restored.rollback()
            result = runtime.status(restored, observation_id=OBS, starting_cash=100000)
            assert result.state.state_hash == second.state.state_hash
            assert rolling_store.retired(restored, original)
    finally:
        with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(restored_name)))


def test_service_keeps_valid_trading_state_when_cleanup_fails(conn, published, monkeypatch):
    monkeypatch.setattr(retention, 'opening_execution_due', lambda _: False)
    runtime.advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=100000)
    def fail(*args, **kwargs):
        raise OSError('disposable cleanup failure')
    monkeypatch.setattr(retention, '_pass', fail)
    monkeypatch.setattr(retention, '_possible_work', lambda _: True)
    result = runtime.service_advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=100000)
    assert result.verification == 'VERIFIED'
    assert retention.idle_pass(conn.info.dsn) is False
    assert conn.execute('SELECT diagnostic FROM sentinel_snapshot_maintenance').fetchone()[0]['status'] == 'RETRY'


def test_idle_retention_defers_for_exact_current_close_work(conn):
    conn.execute("""CREATE TEMP TABLE sentinel_automation_control (
        id int,generation int,config_sha256 text,certificate_sha256 text,
        enabled bool,kill_switch_engaged bool)""")
    conn.execute("""CREATE TEMP TABLE sentinel_account_binding (
        id int,deployment_id text,broker text,broker_account_id text,takeover_epoch int)""")
    conn.execute("""CREATE TEMP TABLE sentinel_automation_cycles (
        control_generation int,config_sha256 text,certificate_sha256 text,deployment_id text,
        broker text,broker_account_id text,takeover_epoch int,prepare_at timestamptz,
        execution_open_at timestamptz,state text,diagnostic jsonb)""")
    conn.execute("INSERT INTO sentinel_automation_control VALUES (1,5,'config','cert',true,false)")
    conn.execute("INSERT INTO sentinel_account_binding VALUES (1,'d','alpaca','paper',2)")
    conn.execute("""INSERT INTO sentinel_automation_cycles VALUES (
        5,'config','cert','d','alpaca','paper',2,now()-interval '1 hour',now()+interval '1 hour',
        'RETRY_WAIT','{"retry_phase":"PREPARE"}')""")
    assert retention._closing_plan_pending(conn)
    for update in (
        "UPDATE sentinel_automation_cycles SET control_generation=4",
        "UPDATE sentinel_automation_cycles SET state='WAITING_OPEN'",
        """UPDATE sentinel_automation_cycles SET diagnostic='{"retry_phase":"RECOVER"}'""",
        "UPDATE sentinel_automation_cycles SET execution_open_at=now()-interval '1 hour'",
    ):
        with conn.transaction(force_rollback=True):
            conn.execute(update)
            assert not retention._closing_plan_pending(conn)
