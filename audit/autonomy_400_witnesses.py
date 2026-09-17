"""Audit witnesses asserting observed defects in aff4461d, not acceptance fixes.
Production source is checked out separately by the evidence workflow. PostgreSQL
cases use disposable local clusters. No provider credentials or broker calls.
"""
from types import SimpleNamespace
import threading
import time
import pytest
from sentinel import automation_supervisor as sup, shadow_supervisor as ss
from sentinel import shadow_worker as sw, shadow_service as base
from sentinel import rolling_runtime as rolling
from sentinel.feed import rolling_jobs as jobs
from tests.support.postgres import _EphemeralPostgres

@pytest.fixture
def pg():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


def test_a1_actual_postgres_lock_blocks_supervisor_snapshot(pg):
    import psycopg
    with psycopg.connect(pg.sync_dsn, autocommit=True) as setup:
        setup.execute('CREATE TABLE sentinel_automation_service_instances (instance_id TEXT PRIMARY KEY,state TEXT,heartbeat_at TIMESTAMPTZ)')
    result, errors = [], []
    with psycopg.connect(pg.sync_dsn) as blocker:
        blocker.execute('LOCK TABLE sentinel_automation_service_instances IN ACCESS EXCLUSIVE MODE')
        def snapshot():
            try: result.append(sup._snapshot(pg.sync_dsn,'audit'))
            except Exception as exc: errors.append(repr(exc))
        thread = threading.Thread(target=snapshot, daemon=True)
        thread.start()
        try:
            waiting = False
            with psycopg.connect(pg.sync_dsn, autocommit=True) as observer:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    waiting = observer.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE 'SELECT state,heartbeat_at,clock_timestamp()%')").fetchone()[0]
                    if waiting: break
                    time.sleep(.01)
            assert waiting
            time.sleep(.2)
            assert thread.is_alive() and result == [] and errors == []
        finally:
            blocker.rollback()
            thread.join(5)
    assert not thread.is_alive() and errors == [] and result == [(None,None)]


def test_a2_actual_rolling_path_refuses_gap(monkeypatch):
    monkeypatch.setattr(rolling,'classify',lambda *a,**k:{'status':'ATTESTED_STRUCTURAL','latest_session':'2026-09-14'})
    with pytest.raises(rolling.Refused,match='ROLLING_RUNTIME_SESSION_GAP'):
        rolling.service_advance(object(),through='2026-09-16',observation_id='primary',starting_cash=100000)


def test_a3_real_database_connection_loss_escapes_worker(pg,monkeypatch):
    import psycopg
    dsn = pg.sync_dsn
    pg.stop()
    monkeypatch.setattr(sw.ShadowServiceConfig,'from_env',lambda:SimpleNamespace(database_url=dsn,observation_id='primary',starting_cash=100000))
    with pytest.raises(psycopg.OperationalError):
        sw.main()


@pytest.mark.parametrize('condition',['retry_wait','owned','expired'])
def test_a4_actual_claim_rejects_expected_unavailability(pg,condition):
    import psycopg
    from uuid import uuid4
    job, owner = str(uuid4()), str(uuid4())
    with psycopg.connect(pg.sync_dsn) as conn:
        conn.execute('CREATE TABLE sentinel_snapshot_jobs (job_id UUID PRIMARY KEY, owner UUID, fence INT NOT NULL DEFAULT 0, lease_until TIMESTAMPTZ, deadline TIMESTAMPTZ, state TEXT, resume_state TEXT, reason TEXT, updated_at TIMESTAMPTZ, next_retry TIMESTAMPTZ)')
        conn.execute('CREATE TABLE sentinel_snapshot_comparisons (job_id UUID)')
        conn.execute('CREATE TABLE sentinel_snapshot_workers (owner UUID PRIMARY KEY,job_id UUID)')
        conn.execute("INSERT INTO sentinel_snapshot_jobs(job_id,deadline,state,resume_state) VALUES(%s,clock_timestamp()+interval '1 hour','ACQUIRING','ACQUIRING')",(job,))
        if condition == 'retry_wait':
            conn.execute("UPDATE sentinel_snapshot_jobs SET state='RETRY_WAIT',next_retry=clock_timestamp()+interval '10 minutes'")
        elif condition == 'owned':
            conn.execute("UPDATE sentinel_snapshot_jobs SET owner=%s,lease_until=clock_timestamp()+interval '10 minutes'",(owner,))
        else:
            conn.execute("UPDATE sentinel_snapshot_jobs SET deadline=clock_timestamp()-interval '1 second'")
        conn.commit()
        with pytest.raises(jobs.JobRefused,match='owned, waiting, expired or terminal'):
            jobs.claim(conn,job,lease_seconds=600)
        conn.rollback()
        conn.execute("UPDATE sentinel_snapshot_jobs SET owner=NULL,lease_until=NULL,next_retry=NULL,deadline=clock_timestamp()+interval '1 hour'")
        lease=jobs.claim(conn,job,lease_seconds=600)
        assert lease.job_id==job


def test_a4_claim_refusal_precedes_failure_handler_and_cleanup(monkeypatch):
    from sentinel.feed import rolling_publisher as pub, operational_snapshot as op
    conn=SimpleNamespace(commit=lambda:None,rollback=lambda:None)
    monkeypatch.setattr(pub.runtime_schema,'require_feed_schema',lambda c:None)
    monkeypatch.setattr(op,'registered',lambda *a:True)
    monkeypatch.setattr(op,'published',lambda *a:None)
    monkeypatch.setattr(pub.identity,'require_feed_producer_identity',lambda:{})
    def claim(*a,**k):raise jobs.JobRefused('job is owned, waiting, expired or terminal')
    monkeypatch.setattr(jobs,'claim',claim)
    monkeypatch.setattr(pub,'_record_failure',lambda *a,**k:pytest.fail('failure handler entered'))
    monkeypatch.setattr(pub.staging,'clear',lambda *a,**k:pytest.fail('cleanup finally entered'))
    with pytest.raises(jobs.JobRefused): pub._prepare(conn,'job',operational=True)


def test_a5_valid_65_segment_horizon_is_permanent_refusal(monkeypatch):
    from sentinel import backup_runtime_authority as backup
    size=16*1024*1024
    objects=backup._expected_wals('000000010000000000000000','000000010000000000000040',segment_size=size)
    metadata={name:(size,1,1,'sha256='+'0'*64,1,1) for name in objects}
    monkeypatch.setattr(backup,'_archive_metadata',lambda *a,**k:metadata)
    monkeypatch.setattr(backup,'_require_no_aliases',lambda *a,**k:None)
    monkeypatch.setattr(backup,'_hash_objects',lambda *a,**k:{x:'0'*64 for x in k['objects']})
    conn=SimpleNamespace(info=SimpleNamespace(dsn='unused'))
    args=dict(operation='audit',system_id='123',base='base-20260917T000000Z',wal_root='unused',history_object=None,segment_size=size,start=objects[0],end=objects[-1])
    backup._validate_archive_objects(conn,wal_objects=objects[:64],**args)
    with pytest.raises(backup.BackupRuntimeRefused,match='Create a fresh base backup'):
        backup._validate_archive_objects(conn,wal_objects=objects,**args)


def test_a6_retryable_transport_becomes_dead_letter(monkeypatch):
    from sentinel.automation import outbox
    seen=[]
    class Cur:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def execute(self,sql,args=None):seen.append((sql,args))
        def fetchone(self):return (8,8)
    conn=SimpleNamespace(cursor=lambda:Cur(),commit=lambda:None,rollback=lambda:None)
    monkeypatch.setattr(outbox,'_append_event',lambda *a,**k:None)
    monkeypatch.setattr(outbox,'load_alert',lambda *a,**k:None)
    outbox.mark_failed(conn,alert_id='a',holder_id='h',error='HTTP 503',retryable=True)
    assert seen[1][1][0]=='DEAD_LETTER'


def test_a7_deployed_idle_loop_omits_retention(monkeypatch,tmp_path):
    from sentinel.feed import retention
    clock=[0];handlers={};calls=[]
    monkeypatch.setattr(ss.ShadowServiceConfig,'from_env',lambda:SimpleNamespace(poll_seconds=300))
    monkeypatch.setattr(ss.signal,'signal',lambda sig,fn:handlers.setdefault(sig,fn))
    monkeypatch.setattr(ss,'LATCH_FILE',tmp_path/'latch')
    monkeypatch.setattr(ss,'HEARTBEAT_FILE',tmp_path/'heartbeat')
    monkeypatch.setattr(ss,'_touch',lambda:None)
    monkeypatch.setattr(ss.time,'monotonic',lambda:clock[0])
    def sleep(seconds):
        clock[0]+=seconds
        if clock[0]>=3:handlers[ss.signal.SIGTERM](None,None)
    monkeypatch.setattr(ss.time,'sleep',sleep)
    monkeypatch.setattr(ss.subprocess,'Popen',lambda *a,**k:SimpleNamespace(poll=lambda:0))
    monkeypatch.setattr(retention,'idle_pass',lambda *a:calls.append(1) or True)
    assert ss.run()==0 and clock[0]==3 and calls==[]
