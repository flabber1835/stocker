"""A typed refused pin plus a real atomic writer earns only unavailable/amber."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import inspect
from pathlib import Path
import textwrap
from types import SimpleNamespace
import uuid

import psycopg
import pytest

from sentinel.feed.publication import CORPUS_LOCK_KEY, CorpusLockUnavailable
from sentinel.feed.rolling_contract import PriceWindow, digest
from sentinel.feed.rolling_jobs import PreparationRequest
from sentinel.panel import app, model, observer_codec, read_projection, verification_service
from sentinel.panel import postclose_feed_wait as feed_wait, publication_wait as waiting
from tests.sentinel.test_panel_postclose_feed_wait import facts
from tests.support.postgres import _EphemeralPostgres


NOW=datetime(2026,10,26,20,50,tzinfo=timezone.utc)
END=NOW+timedelta(hours=1)


@pytest.fixture
def record():
    request=PreparationRequest(window=PriceWindow.through('2026-10-26'),
        strategy_sha256='a'*64,dependencies_sha256='b'*64).model_dump(mode='json')
    return [request,digest(request),'ACQUIRING',NOW-timedelta(minutes=40),END,
            NOW-timedelta(minutes=15),NOW-timedelta(minutes=25),'active',NOW]


def test_atomic_work_may_outlive_the_visible_committed_lease_without_reviving_it(record):
    assert record[5]<NOW
    assert waiting.deadline_from_record(record,now=NOW)==END-timedelta(microseconds=1)
    assert waiting.deadline_from_record(record,now=NOW+timedelta(seconds=1))==END-timedelta(microseconds=1)


@pytest.mark.parametrize('fault',['failed','aborted','published','unowned_backend','future',
    'expired','before_close','clock_skew','missing_lease','late_transaction','hash','foreign_target'])
def test_invalid_or_expired_work_cannot_explain_unavailability(record,fault):
    if fault in {'failed','aborted','published'}:record[2]={'failed':'REFUSED','aborted':'ABORTED','published':'PUBLISHED'}[fault]
    elif fault=='unowned_backend':record[7]='idle'
    elif fault=='future':record[3]=NOW+timedelta(seconds=1)
    elif fault=='expired':record[4]=NOW
    elif fault=='before_close':record[3]=NOW-timedelta(hours=2)
    elif fault=='clock_skew':record[8]=NOW+timedelta(seconds=6)
    elif fault=='missing_lease':record[5]=None
    elif fault=='late_transaction':record[6]=record[5]+timedelta(seconds=1)
    elif fault=='hash':record[1]='0'*64
    else:
        record[0]['window']=PriceWindow.through('2026-10-23').model_dump(mode='json')
        record[1]=digest(record[0])
    assert waiting.deadline_from_record(record,now=NOW) is None, 'invalid job earned publication wait'


def observed(monkeypatch,record,*,include_paper=False,subjects=None):
    state={'closed':False,'rolled_back':False}
    class Connection:
        def execute(self,query,args=None):
            if query==waiting.PROOF_SQL:
                assert args==(CORPUS_LOCK_KEY,)
            return self
        def fetchall(self):return [record]
        def rollback(self):state['rolled_back']=True
        def close(self):state['closed']=True
    monkeypatch.setattr(waiting.store,'connect',lambda *a,**kw:Connection())
    monkeypatch.setattr(waiting,'datetime',SimpleNamespace(now=lambda *a:NOW))
    subjects=iter(subjects or ['a'*64,'a'*64])
    monkeypatch.setattr(read_projection,'subject_for',lambda *a:next(subjects))
    value=waiting.observe('postgresql://isolated.invalid/private',include_paper,'a'*64)
    assert state['closed'] and state['rolled_back']
    return value


@pytest.mark.parametrize('paper',[False,True])
def test_publication_result_is_authenticated_unavailable_and_never_go(monkeypatch,record,paper):
    value=observed(monkeypatch,record,include_paper=paper)
    keys=read_projection.PAPER_KEYS if paper else read_projection.SHADOW_KEYS
    observer_codec.validate_envelope(value,keys)
    rows=[observer_codec.row_from_observation(row) for row in value['rows']]
    assert value['errors']==[] and all(row.status==model.WARN for row in rows)
    assert all(row.shadow_book is None and row.paper_alignment is None for row in rows)
    assert all(row.recovery.phase=='SOURCE_PUBLICATION' and row.valid_until==END-timedelta(microseconds=1) for row in rows)
    assert all(row.effective_status(END+timedelta(microseconds=1))==model.FAIL for row in rows)
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','private-unit-signing-key-'*4)
    envelope,signature=read_projection.make('PAPER' if paper else 'SHADOW','a'*64,
        rows,[],observed_at=NOW)
    decoded=read_projection.decode(envelope,signature,current_subject='a'*64,
        scope='PAPER' if paper else 'SHADOW',now=NOW)
    assert decoded is not None


@pytest.mark.parametrize('subjects',[['foreign'],['a'*64,'foreign']])
def test_changed_scope_subject_refuses(monkeypatch,record,subjects):
    with pytest.raises(ValueError,match='subject changed'):
        observed(monkeypatch,record,subjects=subjects)


def test_only_actual_corpus_lock_type_gets_publication_fallback(monkeypatch):
    answer=object();calls=[]
    monkeypatch.setattr(verification_service.financial,'retry_corpus_lock',lambda operation:operation())
    def unavailable(*a):raise CorpusLockUnavailable('busy')
    monkeypatch.setattr(verification_service,'_observe_once',unavailable)
    monkeypatch.setattr(waiting,'observe',lambda *a:calls.append(a) or answer)
    assert verification_service.observe('private',False,'key') is answer
    assert len(calls)==1
    for error in [RuntimeError('CorpusLockUnavailable'),ValueError('corrupt evidence')]:
        monkeypatch.setattr(verification_service,'_observe_once',lambda *a,exc=error:(_ for _ in ()).throw(exc))
        with pytest.raises(type(error)):verification_service.observe('private',False,'key')
    assert len(calls)==1
    monkeypatch.setattr(verification_service,'_observe_once',unavailable)
    monkeypatch.setattr(waiting,'observe',lambda *a:None)
    with pytest.raises(CorpusLockUnavailable):verification_service.observe('private',False,'key')


def test_publication_styling_preserves_failures_and_withdraws_old_pass(monkeypatch,record):
    value=observed(monkeypatch,record)
    rows=[observer_codec.row_from_observation(raw) for raw in value['rows']]
    _,worker=facts(now=NOW)
    old=NOW-timedelta(minutes=20)
    ingest=model.ingest_row(kind='OPERATIONAL',status='running',chunks_done=0,chunks_total=0,
        rows_written=100,current_chunk='ACQUIRING',updated_at=old)
    authority=model.Row('authority','Authority','PASS',model.OK,as_of=old,
        required_current=True,freshness=timedelta(minutes=5))
    cycle=model.Row('automation_cycle','Cycle','REFRESHING_DATA',model.WARN,required_current=True,
        recovery=model.RecoveryEvidence(phase='AUTOMATION_REFRESHING_DATA',automatic=True,deadline=END))
    auto=[authority,model.Row('automation','Automation','ENABLED'),cycle]
    feed,auto=feed_wait.project_progress([ingest],auto,rows,worker,now=NOW)
    assert feed[0].effective_status(NOW)==model.WARN
    assert auto[0].value=='RECHECK PENDING AFTER DATA' and auto[0].effective_status(NOW)==model.WARN
    assert auto[0].as_of==old and auto[0].valid_until==END-timedelta(microseconds=1)
    assert all(row.shadow_book is None for row in rows)
    page=model.Panel(rows=[*rows,worker,*feed,*auto],now=NOW)
    monkeypatch.setattr(app,'_config',lambda:(Path('/synthetic'),''))
    monkeypatch.setattr(app,'build_panel',lambda **kw:page)
    assert json.loads(app.panel_json().body)['color']=='amber'
    assert json.loads(app.operational_health().body)['red_rows']==[]
    for bad in [replace(ingest,status=model.FAIL),replace(ingest,status=model.UNKNOWN)]:
        out,_=feed_wait.project_progress([bad],auto,rows,worker,now=NOW)
        assert out[0] is bad
    for bad in [replace(authority,status=model.FAIL),replace(authority,status=model.UNKNOWN)]:
        _,out=feed_wait.project_progress([ingest],[bad,*auto[1:]],rows,worker,now=NOW)
        assert out[0] is bad
    feed,auto=feed_wait.project_progress([ingest],[authority,*auto[1:]],rows,
        replace(worker,status=model.FAIL),now=NOW)
    assert feed[0].effective_status(NOW)==model.FAIL and auto[0].effective_status(NOW)==model.FAIL


@pytest.fixture(scope='module')
def private_pg():
    server=_EphemeralPostgres();server.start()
    try:yield server
    finally:server.stop()


@pytest.mark.parametrize('fault',['none','no_update','no_lock','foreign_lock','no_scope','no_owner'])
def test_real_mvcc_writer_and_exact_lock_are_both_required(private_pg,record,fault):
    job,owner=str(uuid.uuid4()),str(uuid.uuid4())
    writer=psycopg.connect(private_pg.sync_dsn)
    reader=psycopg.connect(private_pg.sync_dsn)
    try:
        writer.execute('CREATE TABLE IF NOT EXISTS sentinel_snapshot_jobs(job_id uuid PRIMARY KEY,request jsonb,request_sha256 text,state text,created_at timestamptz,deadline timestamptz,lease_until timestamptz,owner uuid,fence bigint)')
        writer.execute('CREATE TABLE IF NOT EXISTS sentinel_operational_snapshot_jobs(job_id uuid PRIMARY KEY)')
        writer.execute('CREATE TABLE IF NOT EXISTS sentinel_snapshot_workers(owner uuid PRIMARY KEY,job_id uuid)')
        writer.execute('INSERT INTO sentinel_snapshot_jobs VALUES(%s,%s::jsonb,%s,%s,clock_timestamp(),clock_timestamp()+interval \'1 hour\',clock_timestamp()+interval \'10 minutes\',%s,1)',
            (job,json.dumps(record[0]),record[1],'ACQUIRING',owner))
        if fault!='no_scope':writer.execute('INSERT INTO sentinel_operational_snapshot_jobs VALUES(%s)',(job,))
        if fault!='no_owner':writer.execute('INSERT INTO sentinel_snapshot_workers VALUES(%s,%s)',(owner,job))
        writer.commit()
        if fault!='no_lock':writer.execute('SELECT pg_advisory_lock(%s)',(CORPUS_LOCK_KEY+(1 if fault=='foreign_lock' else 0),))
        if fault!='no_update':writer.execute('UPDATE sentinel_snapshot_jobs SET lease_until=clock_timestamp()+interval \'10 minutes\' WHERE job_id=%s',(job,))
        records=reader.execute(waiting.PROOF_SQL,(CORPUS_LOCK_KEY,)).fetchall()
        assert bool(records)==(fault=='none'), 'unowned transaction earned publication proof'
        writer.rollback()
        reader.rollback()
        assert reader.execute(waiting.PROOF_SQL,(CORPUS_LOCK_KEY,)).fetchall()==[]
    finally:
        reader.close();writer.close()


def test_removing_mvcc_owner_guard_is_detected(private_pg,record,monkeypatch):
    changed=waiting.PROOF_SQL.replace('a.backend_xid::text=j.xmax::text','TRUE').replace("AND j.xmax::text<>'0'",'')
    assert changed!=waiting.PROOF_SQL
    monkeypatch.setattr(waiting,'PROOF_SQL',changed)
    with pytest.raises(AssertionError,match='unowned transaction earned publication proof'):
        test_real_mvcc_writer_and_exact_lock_are_both_required(private_pg,record,'no_update')


def test_broad_exception_downgrade_is_detected(monkeypatch):
    source=textwrap.dedent(inspect.getsource(verification_service.observe))
    assert source.count('except CorpusLockUnavailable:')==1
    namespace={}
    exec(compile(source.replace('except CorpusLockUnavailable:','except Exception:'),
        '<publication-exception-falsifier>','exec'),verification_service.__dict__,namespace)
    monkeypatch.setattr(verification_service,'observe',namespace['observe'])
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_only_actual_corpus_lock_type_gets_publication_fallback(monkeypatch)
