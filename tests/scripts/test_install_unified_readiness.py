"""Execute the one-budget startup gate and its actual read-only child."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from email.message import Message
import importlib
import io
import json
import sys
import time
import urllib.error
import urllib.request

import pytest

from tests.scripts.test_sentinel_local_delivery_coordinator import coordinator,host_module,model,operation
from tests.scripts.test_sentinel_local_delivery_operator_review import scheduled_page,keyed
from tests.scripts.test_sentinel_local_delivery_evidence import checks
from tests.scripts.test_install_health_wakeups import unix_engine,event,chunk,EVENT_HEADERS

readiness=importlib.import_module(coordinator.__package__+'.readiness')
health=importlib.import_module(coordinator.__package__+'.docker_health')


def run_child(monkeypatch,pages,expected,*,seconds=20,audit=None):
    audit={} if audit is None else audit
    clock=[0.0];calls=[];out=io.StringIO();err=io.StringIO()
    audit.update(calls=calls,out=out,err=err)
    def get(url,*,timeout):
        assert url=='http://127.0.0.1:8000/panel.json' and 0<timeout<=25
        calls.append(timeout)
        value=pages.pop(0) if len(pages)>1 else pages[0]
        if isinstance(value,Exception):raise value
        response=io.BytesIO(json.dumps(value).encode())
        response.headers=Message()
        response.headers['x-sentinel-panel-status']=(
            'PARTIAL' if value.get('observation',{}).get('current') is False else 'CURRENT')
        return response
    monkeypatch.setattr(urllib.request,'urlopen',get)
    monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(time,'sleep',lambda duration:clock.__setitem__(0,clock[0]+duration))
    monkeypatch.setattr(sys,'argv',['reader',json.dumps(expected),readiness.panel_validator(checks.PANEL),
        (datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat()])
    with redirect_stdout(out),redirect_stderr(err):
        exec(compile(readiness.PANEL_WAIT,'actual readiness child','exec'),{})
    return json.loads(out.getvalue()),calls,err.getvalue(),clock[0]


def starting(page,key='alert_dispatcher'):
    page=deepcopy(page)
    keyed(page,key).update(status='unknown',color='red',value='STARTING')
    page['operator_review'].update(status='FAILED',active=[key])
    page['dashboard_health'].update(status='fail',color='red',active_conditions=[key])
    return page


@pytest.mark.parametrize('key',['alert_dispatcher','automation_leader'])
def test_known_startup_settles_then_exact_existing_validator_runs_on_same_response(monkeypatch,key):
    page,expected=scheduled_page(clean=True)
    result,calls,diagnostic,elapsed=run_child(monkeypatch,[starting(page,key),page],expected)
    assert result['color']=='green' and result['readiness_observations']==2
    assert len(calls)==2 and elapsed==5
    assert diagnostic.count('PENDING')==1 and key in diagnostic
    assert result['readiness_transitions']==[{'conditions':[key],'elapsed_ms':0}]
    assert datetime.fromisoformat(result['installation_panel_valid_until'])==min(
        datetime.fromisoformat(page['observation']['valid_until']),
        datetime.fromisoformat(page['dashboard_health']['valid_until']))


def test_recovered_history_is_never_automatically_acknowledged(monkeypatch):
    page,expected=scheduled_page(recovered=True)
    original=deepcopy(page)
    result,calls,_,_=run_child(monkeypatch,[page],expected)
    assert len(calls)==1 and result['dashboard_health']['color']=='amber'
    assert result['operator_review']['head']>result['operator_review']['reviewed_head']
    assert page==original


def test_expired_eligible_publication_waits_without_extending_any_fact(monkeypatch):
    page,expected=scheduled_page(clean=True)
    expired=deepcopy(page)
    expired['dashboard_health']['valid_until']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    original=deepcopy(expired)
    result,calls,_,elapsed=run_child(monkeypatch,[expired,page],expected)
    assert len(calls)==2 and elapsed==5 and expired==original
    assert result['readiness_transitions'][0]['conditions']==['dashboard_publication_expired']


def test_validator_dependencies_load_before_http_acquisition(monkeypatch):
    import builtins
    imports=[]
    actual=builtins.__import__
    def importing(name,*args,**kwargs):
        if name in {'sentinel.panel.review_model','sentinel.panel.presentation'}:
            imports.append(name)
        return actual(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',importing)
    page,expected=scheduled_page(clean=True)
    # run_child owns the URL stub; its returned page serialization is the first
    # json.dumps of a dictionary with this exact page subject.
    dumps=json.dumps
    observed=[]
    def serializing(value,*args,**kwargs):
        if value is page: observed.append(list(imports))
        return dumps(value,*args,**kwargs)
    monkeypatch.setattr(json,'dumps',serializing)
    run_child(monkeypatch,[page],expected)
    assert observed and {'sentinel.panel.review_model','sentinel.panel.presentation'}<=set(observed[0])


def checking(page):
    page=deepcopy(page)
    until=(datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat()
    keys=['shadow_verification','book','exposure','terminals']
    for key in keys:
        keyed(page,key).update(status='warn',color='amber',value='CHECK IN PROGRESS',valid_until=until,
            recovery=dict(phase='FINANCIAL_VERIFICATION',automatic=True,operator_required=False,deadline=until))
    page['operator_review'].update(status='REVIEW',warnings=keys)
    page['dashboard_health'].update(status='warn',color='amber',review_conditions=keys)
    return page


def test_typed_initial_financial_check_waits_for_actual_proof(monkeypatch):
    page,expected=scheduled_page(clean=True)
    result,calls,_,_=run_child(monkeypatch,[checking(page),page],expected)
    assert result['readiness_observations']==2 and len(calls)==2
    assert result['readiness_transitions'][0]['conditions']==['book','exposure','shadow_verification','terminals']


def test_financial_check_preserves_the_existing_typed_scheduled_workflow_wait(monkeypatch):
    page,expected=scheduled_page(clean=True);pending=checking(page)
    for key in ('automation_cycle','automation_step_open'):
        pending['operator_review']['warnings'].append(key)
        pending['dashboard_health']['review_conditions'].append(key)
    result,calls,_,_=run_child(monkeypatch,[pending,page],expected)
    assert len(calls)==2 and result['readiness_observations']==2


def test_untyped_workflow_cannot_hide_behind_a_financial_check(monkeypatch):
    page,expected=scheduled_page(clean=True);page=checking(page)
    page['operator_review']['warnings'].append('automation_cycle')
    keyed(page,'automation_cycle')['recovery']['phase']='AUTOMATION_RETRY_WAIT'
    audit={}
    with pytest.raises(AssertionError):run_child(monkeypatch,[page],expected,audit=audit)
    assert len(audit['calls'])==1


@pytest.mark.parametrize('fault',['expired','indefinite','untyped','manual','negative','source_error'])
def test_financial_wait_cannot_waive_failure_or_extend_authority(monkeypatch,fault):
    page,expected=scheduled_page(clean=True);page=checking(page)
    row=keyed(page,'shadow_verification')
    if fault=='expired':row['recovery']['deadline']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    elif fault=='indefinite':row['recovery']['deadline']=(datetime.now(timezone.utc)+timedelta(seconds=601)).isoformat()
    elif fault=='untyped':row['recovery']=None
    elif fault=='manual':row['recovery']['operator_required']=True
    elif fault=='negative':row.update(status='fail',color='red')
    else:page['source_errors']=['unavailable']
    audit={}
    with pytest.raises(AssertionError):run_child(monkeypatch,[page],expected,audit=audit)
    assert len(audit['calls'])==1


@pytest.mark.parametrize('fault',['plan','source','authority','broker','shadow_verification','review',
    'duplicate','missing_review','strict_expired','strict_leader','strict_scope'])
def test_nonstartup_or_strict_failures_are_not_retried(monkeypatch,fault):
    page,expected=scheduled_page(clean=True)
    page=starting(page)
    if fault=='plan':keyed(page,'paper_plan')['paper_plan']['plan_id']='foreign'
    elif fault=='source':page['source_errors']=['unavailable']
    elif fault in {'authority','broker','shadow_verification'}:
        keyed(page,fault).update(status='fail',color='red')
    elif fault=='review':page['operator_review']['warnings']=['authority']
    elif fault=='duplicate':page['rows'].append(deepcopy(page['rows'][0]))
    elif fault=='missing_review':page.pop('operator_review')
    elif fault=='strict_expired':
        page,_=scheduled_page(clean=True)
        page['observation']['valid_until']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    elif fault=='strict_leader':
        page,_=scheduled_page()
        keyed(page,'automation_leader')['valid_until']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    else:
        page,_=scheduled_page(clean=True)
        # A changed scope is not accepted as CURRENT by the strict validator.
        page['observation']['changed_scopes']=['PAPER']
    audit={}
    with pytest.raises((AssertionError,KeyError,ValueError)):
        run_child(monkeypatch,[page],expected,audit=audit)
    assert len(audit['calls'])==1 and audit['out'].getvalue()==''


@pytest.mark.parametrize('first',[
    urllib.error.HTTPError('local',503,'Unavailable',{},io.BytesIO()),
    urllib.error.URLError(ConnectionRefusedError()),
])
def test_only_explicit_startup_transport_absence_gets_a_bounded_retry(monkeypatch,first):
    page,expected=scheduled_page(clean=True)
    result,calls,_,elapsed=run_child(monkeypatch,[first,page],expected)
    assert result['color']=='green' and len(calls)==2 and elapsed==5


@pytest.mark.parametrize('first',[
    urllib.error.HTTPError('local',500,'Error',{},io.BytesIO()),
    urllib.error.URLError(TimeoutError()),ValueError('malformed'),
])
def test_unexpected_transport_or_decode_failure_does_not_retry(monkeypatch,first):
    page,expected=scheduled_page(clean=True)
    with pytest.raises(type(first)):
        run_child(monkeypatch,[first,page],expected)


def test_repeated_pending_page_reaches_original_deadline_without_success_or_log_spam(monkeypatch,capsys):
    page,expected=scheduled_page(clean=True)
    audit={}
    with pytest.raises(AssertionError,match='APPLICATION_READINESS_DEADLINE'):
        run_child(monkeypatch,[starting(page)],expected,seconds=10,audit=audit)
    assert audit['out'].getvalue()=='' and audit['err'].getvalue().count('PENDING')==1
    assert len(audit['calls'])==2


def test_nonstartup_classifier_has_an_executed_removed_guard_falsifier(monkeypatch):
    guard=" assert conditions<=startup|checking|workflows and negatives<=startup,'NONSTARTUP_READINESS_FAILURE'\n"
    assert readiness.PANEL_WAIT.count(guard)==1
    monkeypatch.setattr(readiness,'PANEL_WAIT',readiness.PANEL_WAIT.replace(guard,''))
    with pytest.raises(AssertionError):
        test_nonstartup_or_strict_failures_are_not_retried(monkeypatch,'shadow_verification')


def receipt(now,*,start_age=0,proof_age=0):
    return dict(history=[dict(stage='START_REQUESTED',at=(now-timedelta(seconds=start_age)).isoformat())],
        artifacts={'successor_verified_at':(now-timedelta(seconds=proof_age)).isoformat()})


@pytest.mark.parametrize('start_age,proof_age,remaining',[(0,0,230),(200,0,30),(0,890,10)])
def test_cutoff_uses_original_journal_and_proof_times(start_age,proof_age,remaining):
    now=datetime.now(timezone.utc)
    saved=receipt(now,start_age=start_age,proof_age=proof_age)
    assert readiness.cutoff(saved,now=now)==now+timedelta(seconds=remaining)
    later=now+timedelta(seconds=5)
    assert readiness.cutoff(saved,now=later)==now+timedelta(seconds=remaining)


@pytest.mark.parametrize('start_age,proof_age',[(230,0),(0,900)])
def test_expired_readiness_never_gets_a_resume_allowance(start_age,proof_age):
    now=datetime.now(timezone.utc)
    with pytest.raises(model.DeliveryRefused,match='APPLICATION_READINESS_DEADLINE'):
        readiness.cutoff(receipt(now,start_age=start_age,proof_age=proof_age),now=now)


def test_original_deadline_guard_has_an_executed_falsifier(monkeypatch):
    original=readiness.require
    monkeypatch.setattr(readiness,'require',lambda ok,reason:
        None if reason=='APPLICATION_READINESS_DEADLINE' else original(ok,reason))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_expired_readiness_never_gets_a_resume_allowance(230,0)


NAMES=('sentinel-sentinel-shadow-1','sentinel-sentinel-panel-1')
IMAGE='sha256:'+'a'*64
def group(status='starting'):
    return {name:dict(Id=str(i+1)*64,Name='/'+name,Image=IMAGE,RestartCount=0,
        State=dict(Running=True,OOMKilled=False,Restarting=False,StartedAt='original',
            Health={'Status':status})) for i,name in enumerate(NAMES)}


class GroupEngine:
    def __init__(self,groups,*,race=False):
        self.groups=groups;self.index=0;self.reads=[];self.subscriptions=[];self.closed=False;self.clock=0
        self.race=race
    def inspect(self,identity,deadline):
        self.reads.append(identity)
        selected=list(self.groups[min(self.index,len(self.groups)-1)].values())[(len(self.reads)-1)%len(NAMES)]
        return deepcopy(selected)
    @contextmanager
    def wakeups(self,identities,deadline):
        self.subscriptions.append(identities)
        if self.race:self.index+=1
        engine=self
        class Wakeups:
            def wait(self,deadline):
                engine.index+=1
                engine.clock+=1
                return True
        try:yield Wakeups()
        finally:self.closed=True


def wait_group(engine):
    return health.wait_many(engine,NAMES,IMAGE,180,clock=lambda:engine.clock)


def test_all_roles_share_one_subscription_and_post_subscription_fresh_observation():
    engine=GroupEngine([group(),group('healthy')],race=True)
    result=wait_group(engine)
    assert all(i['State']['Health']['Status']=='healthy' for i in result.values())
    assert len(engine.subscriptions)==1 and len(engine.reads)==4 and engine.closed


def test_ready_roles_do_not_subscribe_or_sleep():
    engine=GroupEngine([group('healthy')])
    assert wait_group(engine)==group('healthy')
    assert len(engine.reads)==2 and engine.subscriptions==[]


@pytest.mark.parametrize('fault',['id','image','start','restart_count','running','oom','restarting','unhealthy'])
def test_events_cannot_admit_replaced_restarted_or_failed_roles(fault):
    after=group('healthy');item=after[NAMES[1]]
    if fault=='id':item['Id']='f'*64
    elif fault=='image':item['Image']='sha256:'+'f'*64
    elif fault=='start':item['State']['StartedAt']='changed'
    elif fault=='restart_count':item['RestartCount']=1
    elif fault=='unhealthy':item['State']['Health']['Status']='unhealthy'
    else:item['State'][{'running':'Running','oom':'OOMKilled','restarting':'Restarting'}[fault]]=fault!='running'
    engine=GroupEngine([group(),after],race=True)
    with pytest.raises(model.DeliveryRefused):wait_group(engine)
    assert engine.closed


def test_group_incarnation_guard_has_an_executed_falsifier(monkeypatch):
    original=health.require
    monkeypatch.setattr(health,'require',lambda ok,reason:
        None if reason=='APPLICATION_STARTUP_PROCESS_CHANGED' else original(ok,reason))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_events_cannot_admit_replaced_restarted_or_failed_roles('start')


def test_persisted_incarnation_detects_a_restart_before_the_first_resumed_read():
    prior=group('healthy');after=deepcopy(prior)
    after[NAMES[1]]['RestartCount']=1
    engine=GroupEngine([after])
    with pytest.raises(model.DeliveryRefused,match='PROCESS_CHANGED'):
        health.wait_many(engine,NAMES,IMAGE,180,clock=lambda:engine.clock,expected=prior)
    assert engine.subscriptions==[]


def test_native_event_filter_accepts_wakeups_for_each_exact_role(unix_engine):
    ids=('1'*64,'2'*64)
    def serve(conn,request,stop):
        assert b'container' in request and all(identity.encode() in request for identity in ids)
        conn.sendall(EVENT_HEADERS+chunk(event(identity=ids[1])))
        stop.wait(.5)
    engine,_=unix_engine(serve)
    with engine.wakeups(ids,time.monotonic()+1) as wakeups:
        assert wakeups.wait(time.monotonic()+.5)


def advance_to(operation,stage):
    host,journal,delivery=operation
    while journal.read()['stage']!=stage:delivery.step()
    return host,journal,delivery


def test_start_uses_no_compose_wait_and_one_gate_owns_all_roles(operation):
    host,journal,delivery=advance_to(operation,'START_REQUESTED')
    delivery.step()
    starts=[c for c in host.calls if isinstance(c,tuple) and c[0]=='up']
    assert all('--wait' not in c and '--wait-timeout' not in c for c in starts)
    assert journal.read()['stage']=='APPLICATIONS_STARTED'
    assert delivery.step()['stage']=='VERIFIED'


def test_initial_leader_absence_can_settle_without_restarting_services(operation,monkeypatch):
    host,journal,delivery=advance_to(operation,'APPLICATIONS_STARTED')
    original=coordinator.evidence.leader;calls=[]
    def leader(h):
        calls.append(1)
        return dict(current=False,holder=None) if len(calls)<3 else original(h)
    monkeypatch.setattr(coordinator.evidence,'leader',leader)
    before=list(host.calls)
    assert delivery.step()['stage']=='VERIFIED'
    assert host.calls==before+['verify-candidate']


def test_health_and_leader_time_reduce_the_same_panel_allowance(operation,monkeypatch):
    host,journal,delivery=advance_to(operation,'APPLICATIONS_STARTED')
    health_wait=host.wait_applications_health;panel=coordinator.evidence.panel;bounds=[]
    def wait(**kwargs):
        assert kwargs['deadline']<=host.clock+120
        result=health_wait(**kwargs);host.clock+=100
        return result
    def observe(*args,**kwargs):
        bounds.append((kwargs['wait_until']-model.utcnow()).total_seconds())
        return panel(*args,**kwargs)
    monkeypatch.setattr(host,'wait_applications_health',wait)
    monkeypatch.setattr(coordinator.evidence,'panel',observe)
    assert delivery.step()['stage']=='VERIFIED'
    assert 0<bounds[0]<=127


def test_resume_does_not_reset_readiness_or_restart_services(operation,monkeypatch):
    host,journal,delivery=advance_to(operation,'APPLICATIONS_STARTED')
    end=model.utcnow()+timedelta(seconds=231)
    monkeypatch.setattr(coordinator,'utcnow',lambda:end)
    before=list(host.calls)
    with pytest.raises(model.DeliveryRefused,match='READINESS_DEADLINE'):delivery.step()
    assert host.calls==before+['verify-candidate']
    assert journal.read()['stage']=='APPLICATIONS_STARTED'


def test_started_process_binding_catches_an_interstage_restart(operation):
    host,journal,delivery=advance_to(operation,'APPLICATIONS_STARTED')
    assert set(journal.read()['artifacts']['started_applications'])==set(host_module.SERVICES)
    host.items['sentinel-panel']['RestartCount']+=1
    with pytest.raises(model.DeliveryRefused,match='PROCESS_CHANGED'):delivery.step()


@pytest.mark.parametrize('fault',['process','fence','expired_panel','deadline'])
def test_final_gate_rejects_changes_and_expiry_during_publication_wait(operation,monkeypatch,fault):
    host,journal,delivery=advance_to(operation,'APPLICATIONS_STARTED')
    original=coordinator.evidence.panel
    def panel(*args,**kwargs):
        value=original(*args,**kwargs)
        if fault=='process':host.items['sentinel-panel']['State']['StartedAt']='restarted'
        elif fault=='fence':
            read=coordinator.evidence.leader
            monkeypatch.setattr(coordinator.evidence,'leader',lambda h:dict(read(h),fence=900))
        elif fault=='expired_panel':value['installation_panel_valid_until']=(model.utcnow()-timedelta(seconds=1)).isoformat()
        else:host.clock+=231
        return value
    monkeypatch.setattr(coordinator.evidence,'panel',panel)
    with pytest.raises(model.DeliveryRefused):delivery.step()
    assert journal.read()['stage']=='APPLICATIONS_STARTED'


def test_original_panel_expiry_guard_has_an_executed_falsifier(operation,monkeypatch):
    original=coordinator.require
    monkeypatch.setattr(coordinator,'require',lambda ok,reason:
        None if reason=='INSTALLATION_PANEL_EXPIRED' else original(ok,reason))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_final_gate_rejects_changes_and_expiry_during_publication_wait(operation,monkeypatch,'expired_panel')
