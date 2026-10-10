"""Health hints stay bounded, freshly bound, and outside financial admission."""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from sentinel import schema, shadow_health_projection as health, shadow_service, shadow_runtime
from sentinel.feed import store, calendar
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401
from tests.sentinel.test_alpaca_daily_formation import provider, OBS


@pytest.fixture
def projection(conn, tmp_path, monkeypatch):
    schema.ensure_schema(conn)
    monkeypatch.setenv('SENTINEL_STATE_DIR', str(tmp_path))
    config = shadow_service.ShadowServiceConfig(conn.info.dsn, 'bounded-health', Decimal(50000),
        shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY, 300, True)
    # Explicit simulated verifier output. No financial verdict is obtained from
    # this fixture; the real worker test below creates the actual projection.
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
                 "VALUES ('rolling-cold-start:v1','2026-09-14',%s::jsonb)",
                 (json.dumps({'large_retained_origin':'x' * 2_000_000}),))
    conn.commit()
    inventory, present = health._inventory(conn)
    assert present
    conn.rollback()
    payload = health.Projection(schema_id=health.SCHEMA, config_sha256=health._config(config),
        inventory_sha256=inventory, session='2026-09-14', record_sha256='a'*64,
        runtime_authority_sha256='b'*64).model_dump()
    health._write({'projection':payload, 'hmac_sha256':health._signature(payload)},health.path())
    monkeypatch.setattr(calendar,'latest_closed_session',lambda _: '2026-09-14')
    return config


def forbidden(_):
    pytest.fail('health reentered full retained-book verification')


def test_large_retained_origin_is_not_decoded_by_health(projection, monkeypatch):
    actual_connect = store.connect
    queries = []
    class Guard:
        def __init__(self, conn): self.conn = conn
        def execute(self, query, *args):
            queries.append(query)
            assert 'state' not in query.lower(), 'probe selected a financial payload'
            return self.conn.execute(query, *args)
        def rollback(self): self.conn.rollback()
        def close(self): self.conn.close()
    monkeypatch.setattr(store,'connect',lambda *a,**kw:Guard(actual_connect(*a,**kw)))
    started = time.monotonic()
    assert health.health(projection,fallback=forbidden)['service_health']=='HEALTHY_ATTESTED'
    assert time.monotonic()-started < 2
    assert len(queries)==4


@pytest.mark.parametrize('damage',['missing','truncated','oversize','hmac','field','config',
    'environment','row','foreign_row','publication','origin_deleted'])
def test_changed_health_binding_refuses(projection, conn, damage, monkeypatch, request):
    target = health.path()
    wrapped = json.loads(target.read_text())
    if damage=='missing': target.unlink()
    elif damage=='truncated': target.write_text('{')
    elif damage=='oversize': target.write_bytes(b'x'*(health.MAX_BYTES+1))
    elif damage=='hmac':
        wrapped['hmac_sha256']='0'*64; target.write_text(json.dumps(wrapped))
    elif damage=='field':
        wrapped['projection']['session']='2026-09-15'; target.write_text(json.dumps(wrapped))
    elif damage=='config': projection=replace(projection,starting_cash=Decimal(49000))
    elif damage=='environment': monkeypatch.setenv('SENTINEL_GIT_COMMIT','changed-runtime')
    elif damage=='row':
        conn.execute("UPDATE sentinel_processed_sessions SET state=state WHERE cursor_name='rolling-cold-start:v1'"); conn.commit()
    elif damage=='foreign_row':
        conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES ('shadow-foreign','2026-09-14','{}')"); conn.commit()
    elif damage=='publication':
        # Change publication through its real validated publisher. Never
        # disable the append-only or durable validation-receipt guards.
        _prices, publish = request.getfixturevalue('provider')
        publish()
    elif damage=='origin_deleted':
        conn.execute("DELETE FROM sentinel_processed_sessions"); conn.commit()
    with pytest.raises((ValueError,OSError)):
        health.health(projection,fallback=forbidden)


def test_causal_session_age_is_reobserved(projection, monkeypatch):
    monkeypatch.setattr(calendar,'latest_closed_session',lambda _: '2026-09-15')
    assert health.health(projection,fallback=forbidden,
        now=datetime(2026,9,16,12,tzinfo=timezone.utc))['service_health']=='HEALTHY_WAITING'
    with pytest.raises(ValueError,match='causal'):
        health.health(projection,fallback=forbidden,now=datetime(2026,9,16,15,tzinfo=timezone.utc))
    monkeypatch.setattr(calendar,'latest_closed_session',lambda _: '2026-09-17')
    with pytest.raises(ValueError,match='causal'):
        health.health(projection,fallback=forbidden)


@pytest.mark.parametrize('cursor', [
    'broker-cash-activity:v1:alpaca:paper-account',
    'broker-cash-plan:v1:paper-plan',
    'dual-plan-sizing-authority:v1:paper-plan',
    'dual-regenesis-broker-handover:v2:paper-observation:00000001',
    'paper-informational-mirror:v1:paper-plan',
])
def test_execution_receipts_do_not_invalidate_broker_free_shadow_health(projection, conn, cursor):
    before = health._inventory(conn)
    conn.rollback()
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
                 "VALUES (%s,'2026-09-14','{}')", (cursor,))
    conn.commit()
    assert health._inventory(conn) == before
    conn.rollback()
    assert health.health(projection, fallback=forbidden)['service_health'] == 'HEALTHY_ATTESTED'
    conn.execute("UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s",
                 (json.dumps({'changed': True}), cursor))
    conn.commit()
    assert health.health(projection, fallback=forbidden)['service_health'] == 'HEALTHY_ATTESTED'


def test_new_database_uses_existing_reconstruction_check(conn, tmp_path, monkeypatch):
    schema.ensure_schema(conn)
    monkeypatch.setenv('SENTINEL_STATE_DIR',str(tmp_path))
    config=shadow_service.ShadowServiceConfig(conn.info.dsn,'new',Decimal(50000),
        shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY,300,True)
    assert health.health(config,fallback=lambda _: {'service_health':'RECONSTRUCTION_PENDING'})=={
        'service_health':'RECONSTRUCTION_PENDING'}


def test_canonical_worker_publishes_projection_and_io_failure_does_not_change_book(
        conn, provider, tmp_path, monkeypatch, capsys):
    from sentinel import rolling_runtime, shadow_worker, rolling_initialization as init, shadow_recovery
    prices,publish=provider
    publish()
    config=shadow_service.ShadowServiceConfig(conn.info.dsn,OBS,Decimal(50000),
        shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY,5,True)
    monkeypatch.setenv('SENTINEL_STATE_DIR',str(tmp_path))
    monkeypatch.setenv('SENTINEL_FEED_SERVICE_MODE','SHADOW')
    monkeypatch.setattr(shadow_service.ShadowServiceConfig,'from_env',lambda:config)
    actual=shadow_recovery.advance_once
    monkeypatch.setattr(shadow_worker,'advance_once',lambda value:actual(value,now=init._now(conn)))
    assert shadow_worker.main()==0
    assert health.health(config,fallback=forbidden)['service_health']=='HEALTHY_ATTESTED'
    before=rolling_runtime.status(conn,observation_id=OBS,starting_cash=50000).to_dict()
    conn.rollback()
    def io_failure(*_): raise OSError('projection store unavailable')
    monkeypatch.setattr(health,'_write',io_failure)
    assert shadow_worker.main()==0
    assert 'shadow health projection unavailable' in capsys.readouterr().err
    after=rolling_runtime.status(conn,observation_id=OBS,starting_cash=50000).to_dict()
    assert before==after
    conn.rollback()


def test_killed_probe_parent_cannot_leave_reader_running(tmp_path):
    script='''from pathlib import Path
import os,sys,time
from sentinel import supervisor_io
def reader():
 Path(sys.argv[1]).write_text(str(os.getpid()))
 time.sleep(60)
supervisor_io.run(reader,timeout=60)
'''
    target=tmp_path/'reader.pid'
    parent=subprocess.Popen([sys.executable,'-c',script,str(target)])
    pid=None
    try:
        end=time.monotonic()+5
        while not target.exists():
            assert parent.poll() is None and time.monotonic()<end
            time.sleep(.02)
        pid=int(target.read_text())
        parent.kill(); parent.wait(timeout=3)
        end=time.monotonic()+2
        while True:
            proc=Path(f'/proc/{pid}/stat')
            if not proc.exists() or proc.read_text().split(')')[-1].strip().split()[0]=='Z': break
            assert time.monotonic()<end, 'dependency reader survived its probe parent'
            time.sleep(.02)
    finally:
        if parent.poll() is None: parent.kill();parent.wait(timeout=3)
        if pid is not None:
            try: os.kill(pid,signal.SIGKILL)
            except ProcessLookupError: pass


def test_parent_identity_fork_race_fails_before_dependency():
    result=subprocess.run([sys.executable,'-c',
        'from sentinel import supervisor_io; supervisor_io._parent_death(-1); raise SystemExit(99)'],timeout=3)
    assert result.returncode == -signal.SIGKILL


__all__=['conn','pg','provider']
