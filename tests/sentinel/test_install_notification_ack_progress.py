"""Actual PostgreSQL acknowledgement proof preserves every retained alert field."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import importlib
import json
import sys
from types import SimpleNamespace

from psycopg.types.json import Jsonb
import pytest

from sentinel.feed import store
from sentinel.panel import review_store as review
from tests.sentinel.test_dashboard_review import conn,pg  # noqa: F401
from tests.scripts.test_sentinel_local_delivery_coordinator import (
    coordinator,host_module,model,request,Host,
)

progress=importlib.import_module(coordinator.__package__+'.notification_ack_progress')
ALERT='a'*64
ACTOR='private qualification operator'
ALERT_HASH="""SELECT md5(jsonb_build_array(a.alert_id,a.idempotency_key,a.schema_version,
 a.event_type,a.severity,a.payload,a.created_at,a.ack_state,a.acknowledged_by,
 a.acknowledged_at,a.acknowledgement)::text) FROM sentinel_alert_outbox a WHERE alert_id=%s"""


@pytest.fixture
def case_factory(conn,monkeypatch):
    used=[]
    def create(fault=None):
        assert not used;used.append(True)
        now=datetime.now(timezone.utc)
        created=now-timedelta(seconds=30);baseline=now-timedelta(seconds=20);acked=now-timedelta(seconds=5)
        conn.execute('INSERT INTO sentinel_alert_outbox '
            '(alert_id,idempotency_key,schema_version,event_type,severity,payload,state,max_attempts,created_at,delivered_at) '
            "VALUES(%s,'private-qualified-alert',1,'WAITING_FOR_LEADER','CRITICAL',%s,'DELIVERED',3,%s,%s)",
            (ALERT,Jsonb({'diagnostic':'synthetic resolved incident'}),created,created+timedelta(seconds=1)))
        before={ALERT:conn.execute(ALERT_HASH,(ALERT,)).fetchone()[0]}
        key=review.scope(conn);state=review.empty(created)
        conn.execute('INSERT INTO sentinel_dashboard_review_state(scope_sha256,payload,signature) VALUES(%s,%s,%s)',
            (key,Jsonb(state),review.signature(dict(scope=key,state=state),purpose=review.SCHEMA)))
        review.append(conn,key,state,kind='STARTED',event_key='private-qualified-start',
            details={'component':'dashboard'},now=created+timedelta(seconds=2))
        def append_ack(sequence):
            event=dict(schema=review.EVENT_SCHEMA,scope='f'*64 if fault=='scope' else key,
                sequence=sequence,kind='ACKNOWLEDGED',at=acked.isoformat(),
                details={'actor':ACTOR,'reviewed_head':sequence-1,'alert_ids':[ALERT]},
                previous='f'*64 if fault=='chain' else state['head_signature'])
            if fault=='inventory':event['details']['alert_ids']=[ALERT,'b'*64]
            if fault=='duplicate_inventory':event['details']['alert_ids']=[ALERT,ALERT]
            signed=('0'*64 if fault=='signature' else review.signature(event,purpose=review.EVENT_SCHEMA))
            conn.execute('INSERT INTO sentinel_dashboard_review_events '
                '(scope_sha256,sequence,event_key,kind,at,payload,signature) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                (key,sequence,'ack:'+str(sequence)*64,'ACKNOWLEDGED',acked,Jsonb(event),signed))
            state.update(head=sequence,head_signature=signed)
        if fault!='missing_event':append_ack(2)
        if fault=='ambiguous':append_ack(3)
        state.update(reviewed_head=state['head'],reviewed_at=acked.isoformat())
        review.save(conn,key,state,acked)
        conn.execute("UPDATE sentinel_alert_outbox SET ack_state='ACKNOWLEDGED',acknowledged_by=%s,"
            'acknowledged_at=%s,acknowledgement=%s,updated_at=%s WHERE alert_id=%s',
            (ACTOR,acked,progress.NOTE,acked,ALERT))
        if fault=='payload':conn.execute("UPDATE sentinel_alert_outbox SET payload='{}'::jsonb")
        elif fault=='identity':conn.execute("UPDATE sentinel_alert_outbox SET idempotency_key='changed-identity'")
        elif fault=='actor':conn.execute("UPDATE sentinel_alert_outbox SET acknowledged_by='different operator'")
        elif fault=='clock':conn.execute("UPDATE sentinel_alert_outbox SET acknowledged_at=acknowledged_at+interval '1 second'")
        elif fault=='note':conn.execute("UPDATE sentinel_alert_outbox SET acknowledgement='different note'")
        elif fault=='delivery':conn.execute("UPDATE sentinel_alert_outbox SET state='PENDING'")
        elif fault=='severity':conn.execute("UPDATE sentinel_alert_outbox SET severity='INFO'")
        elif fault=='delivery_clock':conn.execute("UPDATE sentinel_alert_outbox SET delivered_at=created_at-interval '1 second'")
        elif fault=='deleted':conn.execute('DELETE FROM sentinel_alert_outbox')
        elif fault=='reversed':
            before={ALERT:conn.execute(ALERT_HASH,(ALERT,)).fetchone()[0]}
            conn.execute("UPDATE sentinel_alert_outbox SET ack_state='UNACKNOWLEDGED',acknowledged_by=NULL,acknowledged_at=NULL,acknowledgement=NULL")
        elif fault=='reacknowledged':
            before={ALERT:conn.execute(ALERT_HASH,(ALERT,)).fetchone()[0]}
            conn.execute("UPDATE sentinel_alert_outbox SET payload=payload||'{\"edited\":true}'::jsonb")
        if fault=='before_baseline':baseline=acked+timedelta(seconds=1)
        conn.commit()
        current_row=conn.execute(ALERT_HASH,(ALERT,)).fetchone()
        current={} if current_row is None else {ALERT:current_row[0]}
        binding=conn.execute('SELECT deployment_id,broker,broker_account_id,takeover_epoch FROM sentinel_account_binding WHERE id=1').fetchone()
        conn.rollback()
        monkeypatch.setenv('SENTINEL_DATABASE_URL',conn.info.dsn)
        return SimpleNamespace(conn=conn,before=before,current=current,baseline=baseline,acked=acked,
            binding=dict(zip(('deployment_id','broker','broker_account_id','takeover_epoch'),binding)),scope=key)
    return create


def expected(case):
    return dict(schema=progress.SCHEMA,alerts={key:dict(before=old,current=case.current.get(key,''))
        for key,old in case.before.items()},binding=case.binding,not_before=case.baseline.isoformat())


def execute_program(case,monkeypatch,*,program=None,value=None):
    printed=[]
    with monkeypatch.context() as patch:
        patch.setattr(sys,'argv',['private-ack-proof',json.dumps(expected(case) if value is None else value)])
        exec(compile(progress.PROGRAM if program is None else program,'actual read-only acknowledgement proof','exec'),
            {'print':printed.append})
    assert len(printed)==1
    return json.loads(printed[0])


def test_real_signed_ack_reconstructs_original_digest_in_one_read_only_transaction(case_factory,monkeypatch):
    case=case_factory();connections=[];queries=[];connect=store.connect
    def connected(*args,**kwargs):
        c=connect(*args,**kwargs);connections.append(c)
        class Observed:
            def execute(self,statement,*a,**kw):
                queries.append(statement)
                assert statement.startswith(('SELECT ','BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
                return c.execute(statement,*a,**kw)
            def __getattr__(self,name):return getattr(c,name)
        return Observed()
    monkeypatch.setattr(store,'connect',connected)
    result=execute_program(case,monkeypatch)
    assert result==dict(schema=progress.SCHEMA,scope=case.scope,alerts={ALERT:dict(
        before=case.before[ALERT],current=case.current[ALERT],event_sequence=2)})
    assert len(connections)==1 and connections[0].closed
    assert queries[0]=='BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'
    assert case.conn.execute(ALERT_HASH,(ALERT,)).fetchone()[0]==case.current[ALERT]
    case.conn.rollback()


@pytest.mark.parametrize('fault',[
    'payload','identity','actor','clock','note','scope','signature','chain','missing_event',
    'ambiguous','before_baseline','delivery','severity','delivery_clock','deleted','reversed',
    'reacknowledged','inventory','duplicate_inventory',
])
def test_real_proof_refuses_changed_history_or_unbound_ack(case_factory,monkeypatch,fault):
    case=case_factory(fault)
    with pytest.raises((AssertionError,review.ReviewRefused,ValueError,KeyError)):
        execute_program(case,monkeypatch)


@pytest.mark.parametrize('fault',['binding','naive_baseline','future_baseline'])
def test_real_proof_requires_exact_account_and_finite_baseline(case_factory,monkeypatch,fault):
    case=case_factory();value=expected(case)
    if fault=='binding':value['binding']={**value['binding'],'takeover_epoch':999}
    elif fault=='naive_baseline':value['not_before']=case.baseline.replace(tzinfo=None).isoformat()
    else:value['not_before']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    with pytest.raises((AssertionError,ValueError)):
        execute_program(case,monkeypatch,value=value)


def baseline_host(case,tmp_path,monkeypatch):
    selected=request(tmp_path)
    selected['created_at']=(case.baseline-timedelta(seconds=1)).isoformat()
    model.write_new(tmp_path/'request.json',selected)
    journal=model.Journal(tmp_path)
    preserved={**case.binding,'ownership_state':'SENTINEL_OWNED'}
    with monkeypatch.context() as patch:
        patch.setattr(model,'utcnow',lambda:case.baseline)
        journal.advance('NEW','PREFLIGHT_PASS',notification_history={'alerts':case.before},
            preserved={'binding':preserved})
    host=Host(selected);host.operation_dir=tmp_path;host.supports_dashboard_ack_progress=True
    calls=[]
    def run(argv,**options):
        calls.append((argv,options))
        assert argv[:2]==['docker','exec'] and argv[3:6]==['python','-B','-c']
        assert argv[6]==progress.PROGRAM and options['timeout']==30
        output=execute_program(case,monkeypatch,value=json.loads(argv[7]))
        return SimpleNamespace(stdout=json.dumps(output).encode())
    host.run=run;host.calls=calls
    return host


def test_backed_wrapper_consumes_real_proof_without_changing_journal(case_factory,tmp_path,monkeypatch):
    case=case_factory();host=baseline_host(case,tmp_path,monkeypatch)
    original=(tmp_path/'receipt.json').read_bytes()
    assert progress.prove(host,case.before,case.current) is None
    assert len(host.calls)==1 and (tmp_path/'receipt.json').read_bytes()==original


def test_unfinished_build_uses_qualified_direct_predecessor_without_a_candidate_image(
        case_factory,tmp_path,monkeypatch):
    case=case_factory();host=baseline_host(case,tmp_path,monkeypatch)
    original=(tmp_path/'receipt.json').read_bytes()
    installed=host.request['candidate']['image']
    host.predecessor_receipt=tmp_path/'receipt.json'
    host.operation_dir=tmp_path/'unfinished-build'
    host.request={**host.request, 'operation_id':'private-unfinished-build',
        'predecessor':{'commit':'2'*40,'image':installed}, 'candidate':{'commit':'3'*40}}
    host.values['SENTINEL_RUNTIME_IMAGE_DIGEST']=installed
    host.items['sentinel-panel']['Image']=installed
    assert progress.prove(host,case.before,case.current) is None
    assert len(host.calls)==1 and (tmp_path/'receipt.json').read_bytes()==original


def test_unchanged_history_never_runs_the_exception_proof(case_factory,monkeypatch):
    case=case_factory()
    host=SimpleNamespace(run=lambda *_a,**_kw:pytest.fail('unchanged history launched a proof'))
    assert progress.prove(host,case.before,case.before) is None


@pytest.mark.parametrize('fault',['adapter','missing_baseline','wrong_baseline','foreign_image','unhealthy'])
def test_wrapper_refuses_unqualified_or_ambiguous_host_scope(case_factory,tmp_path,monkeypatch,fault):
    case=case_factory();host=baseline_host(case,tmp_path,monkeypatch)
    if fault=='adapter':host.supports_dashboard_ack_progress=False
    elif fault=='missing_baseline':host.operation_dir=tmp_path/'no-original-journal'
    elif fault=='wrong_baseline':case.before={ALERT:'0'*32}
    elif fault=='foreign_image':host.values['SENTINEL_RUNTIME_IMAGE_DIGEST']='sha256:'+'f'*64
    else:host.items['sentinel-panel']['State']['Health']['Status']='unhealthy'
    with pytest.raises(model.DeliveryRefused,match='Existing notification history changed: alerts'):
        progress.prove(host,case.before,case.current)
    assert host.calls==[]


@pytest.mark.parametrize('fault',['missing','changed_before','changed_current','unknown_event','unknown_scope'])
def test_wrapper_rejects_malformed_child_receipts(case_factory,tmp_path,monkeypatch,fault):
    case=case_factory();host=baseline_host(case,tmp_path,monkeypatch)
    result=dict(schema=progress.SCHEMA,scope=case.scope,alerts={ALERT:dict(
        before=case.before[ALERT],current=case.current[ALERT],event_sequence=2)})
    if fault=='missing':result['alerts']={}
    elif fault=='changed_before':result['alerts'][ALERT]['before']='0'*32
    elif fault=='changed_current':result['alerts'][ALERT]['current']='0'*32
    elif fault=='unknown_event':result['alerts'][ALERT]['event_sequence']=1
    else:result['scope']='not-a-scope'
    host.run=lambda *_args,**_kwargs:SimpleNamespace(stdout=json.dumps(result).encode())
    with pytest.raises(model.DeliveryRefused,match='Existing notification history changed: alerts'):
        progress.prove(host,case.before,case.current)


@pytest.mark.parametrize('group',['delivered_alerts','events','fanouts','recipients','delivered_recipients'])
def test_other_delivered_history_remains_exact_and_is_checked_before_ack(case_factory,tmp_path,monkeypatch,group):
    case=case_factory();host=baseline_host(case,tmp_path,monkeypatch)
    groups=('alerts','delivered_alerts','events','fanouts','recipients','delivered_recipients')
    before={key:({'retained':'1'*32} if key!='alerts' else case.before) for key in groups}
    current=deepcopy(before);current['alerts']=case.current;current[group]['retained']='2'*32
    host.sql=lambda *_args:current
    with pytest.raises(model.DeliveryRefused,match='Existing notification history changed: '+group):
        coordinator.evidence.check_notification_history(host,before)
    assert host.calls==[]


def test_original_digest_guard_has_an_executed_payload_mutation_falsifier(case_factory,monkeypatch):
    case=case_factory('payload')
    guard="  assert unacknowledged==alerts[key]['before'],'ORIGINAL_ALERT_DIGEST_CHANGED'\n"
    assert progress.PROGRAM.count(guard)==1
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        with pytest.raises((AssertionError,review.ReviewRefused)):
            execute_program(case,monkeypatch,program=progress.PROGRAM.replace(guard,''))


def test_event_authentication_guard_has_an_executed_signature_falsifier(case_factory,monkeypatch):
    case=case_factory('signature')
    monkeypatch.setattr(review,'authenticate',lambda *_args,**_kwargs:None)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        with pytest.raises((AssertionError,review.ReviewRefused)):
            execute_program(case,monkeypatch)
