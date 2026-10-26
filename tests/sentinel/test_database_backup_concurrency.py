"""Actual libpq connection loss while a private PG physical backup is active.

No broker/provider is constructed. The fixture owns a disposable PG cluster;
real socket timeouts reproduce the incident before fresh clock authority.
"""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time

import psycopg
from psycopg.conninfo import conninfo_to_dict
import pytest

from sentinel.feed import store as feed_store
from tests.sentinel.test_automation_service import conn, pg, config, enable, service_for, recovery_success


@pytest.mark.asyncio
async def test_real_connection_timeouts_recover_during_private_base_backup(conn,pg,tmp_path):
    assert conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0] != '7691913275518591014'
    conn.rollback()
    cfg=config(); enable(conn,cfg)
    params=conninfo_to_dict(pg.sync_dsn)
    assert params.get('host') in {'127.0.0.1','localhost'}
    verify=shutil.which('pg_verifybackup')
    if verify is None:
        programs=sorted(Path('/usr/lib/postgresql').glob('*/bin/pg_verifybackup'))
        assert programs
        verify=str(programs[-1])
    assert shutil.which('pg_basebackup')
    base=tmp_path/'base'; log=tmp_path/'backup.log'
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(.2)
    stopped=threading.Event(); accepted=[]
    def sink():
        while not stopped.is_set():
            try:
                peer,_=listener.accept();accepted.append(peer)
            except socket.timeout:pass
            except OSError:break
    thread=threading.Thread(target=sink,daemon=True);thread.start()
    backup=None
    try:
        with log.open('wb') as output:
            backup=subprocess.Popen(['pg_basebackup','--host',params['host'],'--port',params['port'],
                '--username',params.get('user','postgres'),'--pgdata',str(base),'--wal-method','stream',
                '--checkpoint','fast','--max-rate','1024','--no-password'],stdout=output,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+15
            while not conn.execute('SELECT count(*) FROM pg_stat_progress_basebackup').fetchone()[0]:
                conn.rollback()
                assert backup.poll() is None,log.read_text()
                assert time.monotonic()<deadline
                await asyncio.sleep(.05)
            conn.rollback()
            connections=[]; sleeps=[]; recovered=tmp_path/'recovered.txt'
            def connect():
                connections.append(True)
                if len(connections) in {2,4}:
                    # A real TCP peer accepts but never completes the PG handshake.
                    return psycopg.connect(host='127.0.0.1',port=listener.getsockname()[1],
                        user='postgres',dbname='private-timeout-probe',connect_timeout=2)
                return feed_store.connect(pg.sync_dsn)
            async def recover(context):
                recovered.write_text('fresh clock recovered')
                return recovery_success(context)
            async def unexpected(context):raise AssertionError('provider/broker callback before valid sample')
            service=service_for(cfg,recover=recover,refresh=unexpected,prepare=unexpected,execute=unexpected)
            async def pause(seconds):
                sleeps.append(seconds)
                assert not recovered.exists() and backup.poll() is None
                assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0]==0
                assert conn.execute('SELECT holder_id FROM sentinel_automation_lease WHERE id=1').fetchone()[0] is None
                assert conn.execute('SELECT count(*) FROM sentinel_automation_cycles').fetchone()[0]==0
                conn.rollback()
                await asyncio.sleep(.05)
            assert await service.run(connect,stop=asyncio.Event(),clock=lambda:datetime.now(timezone.utc),
                sleep=pause,max_ticks=3)==3
            assert len(accepted)==2 and len(sleeps)==2
            assert all(0<delay<=cfg.heartbeat_seconds for delay in sleeps)
            assert recovered.read_text()=='fresh clock recovered' and backup.poll() is None
            assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0]==0
            conn.rollback()
            assert backup.wait(timeout=90)==0,log.read_text()
        # The qualification client package may differ from the owned PG16
        # server. Verify manifest/data here; exact-PG16 WAL replay is a separate
        # mandatory current-image deployment gate, not claimed by this test.
        checked=subprocess.run([verify,'--no-parse-wal',str(base)],capture_output=True,text=True,timeout=30)
        assert checked.returncode==0,checked.stdout+checked.stderr
        print('PRIVATE_BACKUP_CONCURRENCY_PASS: real libpq timeouts=2; no pre-clock lease/cycle/order; backup manifest verified')
    finally:
        stopped.set();listener.close()
        for peer in accepted:peer.close()
        thread.join(timeout=1)
        if backup is not None and backup.poll() is None:
            backup.terminate();backup.wait(timeout=5)


__all__=['conn','pg']
