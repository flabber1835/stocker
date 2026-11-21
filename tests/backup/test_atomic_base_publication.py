"""Read actual PostgreSQL at producer and consumer commit boundaries."""
from datetime import timedelta
import json
import time

import psycopg
import pytest
from psycopg.types.json import Jsonb

from sentinel.panel import model, presentation, sources
from scripts.sentinel_backup_publication import base_transition_sql
from tests.backup.test_progress_phase_contract import database  # noqa: F401
from tests.backup.test_recurring_maintenance import boundary, coordinator, SYSTEM

OLD = 'base-20261120T223403Z'
NEW = 'base-20261121T103626Z'


def physical(name=NEW):
    return dict(schema='sentinel.verified-base/1', physical_verified=True,
        metadata_sha256='a'*64, base_backup=name,
        marker='sentinel-backup-20261121T103626Z-42', marker_lsn='0/D000000',
        marker_wal='00000001000000000000000D', system_identifier=SYSTEM,
        xid8_before='1000', xid8_after='1001')


def append(conn, kind, proof, at=None):
    conn.execute("INSERT INTO sentinel_backup_evidence(kind,evidence_sha256,proof,observed_at) "
        "SELECT %s,encode(sha256(convert_to(%s::jsonb::text,'UTF8')),'hex'),%s,"
        "COALESCE(%s,clock_timestamp())", (kind, Jsonb(proof), Jsonb(proof), at))


def prepare(conn):
    now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    progress = dict(schema='sentinel.backup-maintenance-progress/1', attempt='a'*32,
        started_at=int(now.timestamp())-20, deadline=int(now.timestamp())+3580,
        system_identifier=SYSTEM, image='sha256:'+'d'*64,
        predecessor_base=OLD, base_backup=OLD, phase='BASE_BACKUP')
    runtime = dict(enabled=True, base_backup=OLD, system_identifier=SYSTEM,
        wal_integrity='sha256-sidecar-v1', wal_segments=3,
        recoverable_from_wal='00000001000000000000000A',
        recoverable_through_wal='00000001000000000000000D')
    append(conn, 'BASE_BACKUP', physical(OLD), now-timedelta(hours=1))
    append(conn, 'RESTORE_DRILL', dict(base_backup=OLD, system_identifier=SYSTEM,
        physical_only=False, marker='old-marker', target_lsn='0/D000000'), now-timedelta(hours=2))
    append(conn, 'RUNTIME_CHAIN', runtime, now-timedelta(seconds=10))
    append(conn, 'MAINTENANCE_PROGRESS', progress)
    conn.commit()
    return progress, runtime


def row(evidence):
    b,d,r,m = (evidence[k] for k in ('BASE_BACKUP','RESTORE_DRILL','RUNTIME_CHAIN','MAINTENANCE_PROGRESS'))
    now = max(e['observed_at'] for e in evidence.values() if e)+timedelta(milliseconds=1)
    return model.backup_restore_row(base_at=b['observed_at'], base_proof=b['proof'],
        restore_at=d['observed_at'], restore_proof=d['proof'],
        runtime_at=r['observed_at'], runtime_proof=r['proof'],
        runtime_valid_until=r['observed_at']+timedelta(minutes=10),
        maintenance_at=m['observed_at'], maintenance_proof=m['proof'], now=now)


def normal(evidence):
    value = row(evidence)
    assert value.status in {model.OK,model.WARN}, value.detail
    assert presentation.health_facts(model.Panel(rows=[value],now=value.as_of)) == {
        'active':[], 'warnings':[]}
    return value


def test_atomic_transition_is_invisible_until_both_records_commit(database):
    original,runtime = prepare(database)
    with psycopg.connect(database.info.dsn,autocommit=True) as reader:
        normal(sources._backup_evidence_snapshot(reader))
        database.execute(base_transition_sql(original,physical())).fetchone()
        before = sources._backup_evidence_snapshot(reader)
        assert before['BASE_BACKUP']['proof']['base_backup'] == OLD
        assert before['MAINTENANCE_PROGRESS']['proof'] == original
        normal(before)
        database.commit()
        after = sources._backup_evidence_snapshot(reader)
        assert after['BASE_BACKUP']['proof'] == physical()
        assert after['BASE_BACKUP']['observed_at'] <= after['MAINTENANCE_PROGRESS']['observed_at']
        successor = dict(original,base_backup=NEW,phase='VERIFY_CHAIN')
        assert after['MAINTENANCE_PROGRESS']['proof'] == successor
        value = normal(after)
        assert value.recovery.phase == 'BACKUP_MAINTENANCE'
        assert value.valid_until.timestamp() == original['deadline']
        append(database,'RUNTIME_CHAIN',dict(runtime,base_backup=NEW));database.commit()
        assert normal(sources._backup_evidence_snapshot(reader)).status == model.OK


def test_guard_failure_rolls_back_base_and_split_publication_falsifier(database):
    original,_ = prepare(database)
    changed = dict(original,deadline=original['deadline']-1)
    with pytest.raises(psycopg.errors.RaiseException):
        database.execute(base_transition_sql(changed,physical()))
    database.rollback()
    assert database.execute("SELECT count(*) FROM sentinel_backup_evidence WHERE proof->>'base_backup'=%s",(NEW,)).fetchone() == (0,)
    normal(sources._backup_evidence_snapshot(database))
    database.rollback()
    # Reintroduce the former separate base commit, then fail its progress write.
    append(database,'BASE_BACKUP',physical());database.commit()
    with pytest.raises(psycopg.errors.RaiseException):
        database.execute(base_transition_sql(changed,physical()))
    database.rollback()
    with pytest.raises(AssertionError,match='runtime chain disagrees'):
        normal(sources._backup_evidence_snapshot(database))


def test_expired_original_attempt_cannot_publish_a_new_generation(database):
    original,_ = prepare(database)
    expired=dict(original,started_at=original['started_at']-3600,deadline=original['deadline']-3600)
    assert database.execute(base_transition_sql(expired,physical())).fetchone() is None
    database.commit()
    assert sources._backup_evidence_snapshot(database)['BASE_BACKUP']['proof']['base_backup'] == OLD


class Interleaving:
    def __init__(self, reader, commit):
        self.reader,self.commit,self.fired=reader,commit,False

    def cursor(self):
        real=self.reader.cursor();owner=self
        class Cursor:
            def __enter__(self):return self
            def __exit__(self,*args):real.close()
            def execute(self,*args):
                real.execute(*args)
                if not owner.fired:
                    owner.fired=True;owner.commit()
            def fetchall(self):return real.fetchall()
            def fetchone(self):return real.fetchone()
        return Cursor()


def legacy_read(conn):
    return {k:sources._latest_backup_evidence(conn,k) for k in (
        'BASE_BACKUP','RESTORE_DRILL','RUNTIME_CHAIN','MAINTENANCE_PROGRESS')}


@pytest.mark.parametrize('legacy',[False,True])
def test_consumer_statement_snapshot_and_executed_split_read_falsifier(database,legacy):
    original,runtime=prepare(database)
    def commit():
        database.execute(base_transition_sql(original,physical())).fetchone()
        append(database,'RUNTIME_CHAIN',dict(runtime,base_backup=NEW));database.commit()
    with psycopg.connect(database.info.dsn,autocommit=True) as reader:
        observed=(legacy_read if legacy else sources._backup_evidence_snapshot)(Interleaving(reader,commit))
        if legacy:
            with pytest.raises(AssertionError,match='runtime chain disagrees'):normal(observed)
        else:
            normal(observed)
            assert observed['BASE_BACKUP']['proof']['base_backup'] == OLD
        assert normal(sources._backup_evidence_snapshot(reader)).status == model.OK


@pytest.mark.parametrize('fault',['invalid_chain','foreign_cluster','invalid_base','failed_progress'])
def test_new_negative_evidence_never_falls_back_to_the_previous_positive(database,fault):
    original,runtime=prepare(database)
    if fault=='invalid_chain':append(database,'RUNTIME_CHAIN',dict(runtime,wal_segments=0))
    elif fault=='foreign_cluster':append(database,'RUNTIME_CHAIN',dict(runtime,system_identifier='123'))
    elif fault=='invalid_base':append(database,'BASE_BACKUP',dict(physical(OLD),marker=''))
    else:append(database,'MAINTENANCE_PROGRESS',dict(original,phase='FAILED'))
    database.commit()
    assert row(sources._backup_evidence_snapshot(database)).status == model.FAIL


def run_lost_reply(database,boundary,monkeypatch,*,legacy=False):
    import tests.backup.test_recurring_maintenance as harness
    monkeypatch.setattr(harness,'NOW',int(time.time()))
    before,after=OLD,boundary.name
    boundary.name,boundary.old=before,True
    copies=[]
    def runner(argv,**kwargs):
        if argv[:2]==['bash','scripts/sentinel-base-backup.sh']:
            copies.append(argv);boundary.name=after
            original=json.loads(argv[argv.index('--maintenance-progress')+1])
            proof=physical(after)
            database.execute(base_transition_sql(original,proof)).fetchone();database.commit()
            raise coordinator.Refused('injected response lost after commit')
        if 'psql' in argv and ("SELECT 'MAINTENANCE_PROGRESS'" in argv[-1] or "WHERE kind='MAINTENANCE_PROGRESS'" in argv[-1]):
            result=database.execute(argv[-1]).fetchone();database.commit()
            return json.dumps(result[0]) if isinstance(result[0],dict) else str(result[0])
        return boundary(argv,**kwargs)
    if legacy:
        monkeypatch.setattr(coordinator,'_failed_progress',lambda progress,runner:
            coordinator.publish_progress(dict(progress,phase='FAILED'),runner))
    with pytest.raises(coordinator.Refused,match='response lost after commit'):
        coordinator.tick('/media',runner)
    records=database.execute("SELECT proof FROM sentinel_backup_evidence WHERE kind='MAINTENANCE_PROGRESS' ORDER BY seq").fetchall()
    assert [r[0]['phase'] for r in records] == ['BASE_BACKUP','VERIFY_CHAIN','FAILED']
    assert [r[0]['base_backup'] for r in records] == [before,after,after]
    assert len({(r[0]['attempt'],r[0]['started_at'],r[0]['deadline']) for r in records})==1
    assert len(copies)==1


def test_lost_reply_records_failure_against_the_actual_committed_successor(database,boundary,monkeypatch):
    run_lost_reply(database,boundary,monkeypatch)


def test_executed_lost_reply_falsifier_cannot_report_the_old_generation(database,boundary,monkeypatch):
    with pytest.raises(AssertionError):run_lost_reply(database,boundary,monkeypatch,legacy=True)


@pytest.mark.parametrize('field,value',[('attempt','bad'),('phase','COMPLETE'),('deadline',True),
    ('image','mutable'),('system_identifier','123'),('predecessor_base','foreign')])
def test_invalid_transition_identity_is_refused_before_publication(database,field,value):
    original,_=prepare(database);original[field]=value
    with pytest.raises(ValueError):base_transition_sql(original,physical())
