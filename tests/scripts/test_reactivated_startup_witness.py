"""A recovered cold-start interval can be proved only before the first acquisition."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
from types import SimpleNamespace

import pytest

from tests.scripts.test_sentinel_local_delivery_coordinator import SPEC, model

startup = importlib.import_module(SPEC.name+'.reactivated_startup')
SERVICES = startup.SERVICES


def stamp(seconds):
    return (datetime(2026,11,18,20,tzinfo=timezone.utc)+timedelta(seconds=seconds)).isoformat()


def witness():
    history = {g:{'previous':'unchanged'} for g in
               ('alerts','delivered_alerts','events','fanouts','recipients','delivered_recipients')}
    original = {'0'*64:{'severity':'CRITICAL'}}
    baseline = dict(control={'generation':214},inflight=0,other_active=0,retained_incidents=original,
                    reactivation={'unsettled_alerts':0,'successor_commands':0})
    request = dict(schema=model.REACTIVATED_SCHEMA,handoff_mode='POST_TRADE_REACTIVATED',
                   candidate={'image':'sha256:'+'a'*64})
    apps = {role:dict(Id=('%064x'%(index+1))[::-1],State=dict(Running=True,StartedAt=stamp(8),
            Restarting=False,OOMKilled=False,Health={'Status':'healthy'}),Image=request['candidate']['image'],
            RestartCount=0) for index,role in enumerate(SERVICES)}
    process = {role:dict(Id=item['Id'],RestartCount=0,State={'StartedAt':stamp(8)}) for role,item in apps.items()}
    stages = dict(STOP_REQUESTED=-80,APPLICATIONS_STOPPED=-66,START_REQUESTED=2,APPLICATIONS_STARTED=10)
    receipt = dict(schema=model.REACTIVATED_SCHEMA,stage='APPLICATIONS_STARTED',
                   request_sha256=model.digest(request),history=[dict(stage=k,at=stamp(v)) for k,v in stages.items()],
                   artifacts=dict(preserved=baseline,started_applications=process,notification_history=history))
    generation, occurrence = 214,96
    prior = 'previous-worker'
    holder = 'sentinel-'+process['sentinel-automation']['Id'][:12]+'-43ad4023-78c8-457e-aa22-eb0019ef6c74'
    diagnostic = dict(schema='sentinel.scheduler-diagnostic/1',policy_state='WAITING_FOR_LEADER',
                      predicate='LEASE_EXPIRED',control_generation=generation,holder=prior,holder_present=True,
                      holder_matches=True,leader_active=False,service_heartbeat_fresh=False,
                      callback_current=False,scheduler_overdue=False,callback_started_at=None,callback_deadline_at=None,
                      sampled_at=stamp(13),lease_expires_at=stamp(-61),lease_heartbeat_at=stamp(-73),
                      instance_heartbeat_at=stamp(-73),instance_state='WAITING',fence=465,
                      heartbeat_age_seconds=86.0,heartbeat_window_seconds=12.0,read_elapsed_seconds=.025)
    key = 'automation-health-occurrence:'+str(occurrence)
    alert_id = hashlib.sha256(('sentinel.alert/1\0'+key).encode()).hexdigest()
    alert = dict(event_type='AUTOMATION_OPERATIONAL_RED',severity='CRITICAL',ack_state='UNACKNOWLEDGED',
                 created_at=stamp(13.25),payload=dict(reason='WAITING_FOR_LEADER',control_generation=generation,
                 broker_outcome_unresolved=0,latest_cycle_id=None,latest_cycle_state=None,scheduler_diagnostic=diagnostic))
    current = deepcopy(baseline)
    current['retained_incidents'][alert_id] = alert
    events = [dict(action=act,alert_id=alert_id,at=stamp(at),seq=seq,attempt=1,error=None,holder_id='dispatcher')
              for at,act,seq in [(13.4,'CLAIMED',1025),(14.7,'DELIVERED',1026)]]
    after = deepcopy(history)
    for g in ('alerts','delivered_alerts','fanouts'):
        after[g][alert_id]='new'
    for g in ('recipients','delivered_recipients'):
        after[g][alert_id+':recipient']='new'
    after['events'].update({'1025':'claim','1026':'delivery'})
    f = dict(alert=deepcopy(alert),key=key,schema=1,state='DELIVERED',attempts=1,ack_empty=True,
             delivered_at=stamp(14.65),events=events,generation=generation,enabled=True,killed=False,authority='PASS',
             lease_generation=generation,holder=holder,fence=466,acquired=stamp(14.38),heartbeat=stamp(121),
             expires=stamp(133),registered=stamp(11),service_heartbeat=stamp(121),service_state='WAITING',
             candidate_workers=1,previous_holder=prior,previous_registered=stamp(-7200),
             previous_heartbeat=stamp(-73),previous_state='WAITING',occurrence=occurrence,cleared=True,
             now=stamp(125),history=after)
    return dict(alert_id=alert_id,request=request,apps=apps,receipt=receipt,current=current,facts=f,
                holder=holder,log=deepcopy(diagnostic),at=stamp(13.1))


def run(case):
    def sql(query):
        assert 'SELECT' in query and 'FOR UPDATE' not in query and '@' not in query
        assert 'sentinel_alert_outbox' in query and case['alert_id'] in query
        return case['facts']
    def command(argv, *, timeout):
        assert timeout <= 5
        if argv[:2] == ['docker','exec']:
            assert argv[2:] == [case['apps']['sentinel-automation']['Id'],'cat','/tmp/sentinel-automation-holder-id']
            return SimpleNamespace(stdout=case['holder'].encode())
        assert argv[:4] == ['docker','logs','--timestamps','--tail']
        assert argv[-1] == case['apps']['sentinel-alert-dispatcher']['Id']
        message = {'schema':'sentinel.scheduler-incident/1','diagnostic':case['log']}
        data = (case['at']+' '+json.dumps(message)+'\n').encode()
        return SimpleNamespace(stdout=b'',stderr=data*case.get('log_count',1))
    host=SimpleNamespace(request=case['request'],containers=lambda names:case['apps'],sql=sql,run=command)
    return startup.observe_startup_append(host,case['receipt'],case['current'])


def test_actual_call_path_stable_under_advancing_healthy_owner():
    c = witness()
    proof = run(c)
    assert proof['alert_id']==c['alert_id'] and proof['claim_seq']==1025 and proof['delivery_seq']==1026
    assert proof['first_acquired_at']==stamp(14.38) and proof['fence']==466
    c['facts'].update(heartbeat=stamp(130),service_heartbeat=stamp(130),expires=stamp(142),now=stamp(135))
    assert run(c)==proof


@pytest.mark.parametrize('key,value',[
    ('key','automation-health-occurrence:97'),('schema',True),('state','DLQ'),('attempts',2),('ack_empty',False),
    ('cleared',False),('generation',215),('lease_generation',213),('enabled',False),('killed',True),
    ('authority','FAIL'),('candidate_workers',2),('fence',468),('fence',465),('fence',True),
    ('registered',stamp(13.4)),('acquired',stamp(13.1)),('acquired',stamp(39)),('previous_registered',stamp(-10)),
    ('previous_heartbeat',stamp(-79)),('previous_state','ERROR'),('service_state','PREFLIGHT_RECOVER_CALLBACK'),
    ('expires',stamp(125)),('service_heartbeat',stamp(120)),('heartbeat',stamp(160)),('now',stamp(74)),
    ('occurrence',95),('delivered_at',stamp(39)),('previous_holder','someone-else'),('holder','wrong'),
])
def test_unproved_native_facts_refuse(key,value):
    c=witness()
    c['facts'][key]=value
    with pytest.raises(model.DeliveryRefused): run(c)


@pytest.mark.parametrize('key,value',[
    ('predicate','INSTANCE_MISSING'),('policy_state','SCHEDULER_STALLED'),('holder_present',False),
    ('holder_matches',False),('leader_active',True),('service_heartbeat_fresh',True),('callback_current',True),
    ('scheduler_overdue',True),('control_generation',215),('sampled_at',stamp(13.5)),
    ('callback_started_at',stamp(3)),('callback_deadline_at',stamp(13)),('instance_state','ACTIVE'),
    ('instance_heartbeat_at',stamp(-80)),('fence',464),('lease_expires_at',stamp(-81)),
    ('lease_expires_at',stamp(6)),('holder','other'),('schema','sentinel.scheduler-diagnostic/2'),
    ('new_field',0),('heartbeat_age_seconds',85.99),('heartbeat_window_seconds',11.99),
    ('read_elapsed_seconds',False)])
def test_concordant_forged_log_and_payload_still_refuse(key,value):
    c=witness()
    for d in (c['log'],c['facts']['alert']['payload']['scheduler_diagnostic'],
              c['current']['retained_incidents'][c['alert_id']]['payload']['scheduler_diagnostic']):
        d[key]=value
    with pytest.raises(model.DeliveryRefused): run(c)


@pytest.mark.parametrize('mutation',[
    'ack','second','unresolved','numeric_bool','wrongcycle','payload_mismatch','extra_field','new_other_info',
    'old_alert_ack','different_notify','wrong_recipient','changed_source','fake_log','missing_log','log_twice',
    'log_after_insert','wrong_holder_file','restarted','stopped','different_id','different_start','bad_image','bad_stage',
    'unowned_request','late_alert','delivery_order','other_delivery','wrong_claimant','extra_event','missed_event',
    'different_mode','unknown_outcome',
])
def test_append_and_ownership_falsifiers(mutation):
    c=witness()
    a=c['current']['retained_incidents'][c['alert_id']]
    facts=c['facts']
    if mutation=='ack': del c['current']['retained_incidents']['0'*64]
    elif mutation=='second': c['current']['retained_incidents']['1'*64]=a
    elif mutation in {'unresolved','numeric_bool','wrongcycle','extra_field','late_alert'}:
        if mutation=='late_alert': a['created_at']=stamp(14.38)
        elif mutation=='wrongcycle': a['payload']['latest_cycle_id']='active-cycle'
        elif mutation=='extra_field': a['payload']['unknown_new_field']='ignored?'
        else: a['payload']['broker_outcome_unresolved']=False if mutation=='numeric_bool' else 1
        facts['alert']=deepcopy(a)
    elif mutation=='payload_mismatch': facts['alert']['payload']['control_generation']=210
    elif mutation=='new_other_info': facts['history']['alerts']['a'*64]='other'
    elif mutation=='old_alert_ack': facts['history']['alerts']['previous']='changed'
    elif mutation=='different_notify': facts['history']['events']['9999']='unrelated'
    elif mutation=='wrong_recipient': facts['history']['recipients']['d'*64+':x']='unrelated'
    elif mutation=='changed_source': c['current']['changed']=True
    elif mutation=='fake_log': c['log']['holder']='forged'
    elif mutation=='missing_log': c['log_count']=0
    elif mutation=='log_twice': c['log_count']=2
    elif mutation=='log_after_insert': c['at']=stamp(13.5)
    elif mutation=='wrong_holder_file': c['holder']+='0'
    elif mutation=='restarted': c['apps']['sentinel-shadow']['RestartCount']=1
    elif mutation=='stopped': c['apps']['sentinel-panel']['State']['Running']=False
    elif mutation=='different_id': c['apps']['sentinel-automation']['Id']='4'*64
    elif mutation=='different_start': c['apps']['sentinel-automation']['State']['StartedAt']=stamp(9)
    elif mutation=='bad_image': c['apps']['sentinel-alert-dispatcher']['Image']='another'
    elif mutation=='bad_stage': c['receipt']['stage']='PREFLIGHT_PASS'
    elif mutation=='unowned_request': c['receipt']['request_sha256']='different'
    elif mutation=='delivery_order': facts['events'][1]['at']=stamp(12)
    elif mutation=='other_delivery': facts['events'][0]['alert_id']='different'
    elif mutation=='wrong_claimant': facts['events'][1]['holder_id']='other'
    elif mutation=='extra_event': facts['events'].append(deepcopy(facts['events'][0]))
    elif mutation=='missed_event': del facts['history']['events']['1025']
    elif mutation=='different_mode': c['request']['handoff_mode']='PRE_OPEN'
    elif mutation=='unknown_outcome':
        c['receipt']['artifacts']['preserved']['inflight']=c['current']['inflight']=1
    with pytest.raises(model.DeliveryRefused): run(c)
