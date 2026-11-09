"""One restricted helper replaces repeated exec probes without late admission."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import json
import subprocess
import time
from types import SimpleNamespace

import pytest

from tests.scripts.test_sentinel_local_delivery_coordinator import host_module as hosts, model
from tests.scripts.test_sentinel_local_delivery_evidence import (
    cooperative_drain_host, evidence, model as evidence_model)

OLD='1'*40
OLD_IMAGE='sha256:'+'2'*64
NEW_IMAGE='sha256:'+'3'*64


def helper_host():
    host=object.__new__(hosts.Host)
    host.request={'predecessor':{'commit':OLD},'candidate':{'image':NEW_IMAGE}}
    environment={'SENTINEL_GIT_COMMIT':OLD,'SENTINEL_RUNTIME_IMAGE_DIGEST':OLD_IMAGE,
        'SENTINEL_SHADOW_OBSERVATION_ID':'primary','SENTINEL_DATABASE_URL':'private-database-fixture',
        'SENTINEL_PUBLICATION_RECEIPT_KEY':'private-authentication-fixture-'+'x'*32,
        'ALPACA_API_KEY':'must-never-enter-helper','SENTINEL_AUTHORITY_ISSUER':'must-never-enter-helper'}
    target={'container':'exact-shadow','image':OLD_IMAGE}
    container={'Id':target['container'],'Image':target['image'],
        'Config':{'Env':[key+'='+value for key,value in environment.items()]},
        'Mounts':[{'Destination':'/var/lib/sentinel','Type':'volume','Name':'sentinel_sentinel_state'}]}
    host.environments=[];host.runs=[];request={'canonical':'exact-request'}
    @contextmanager
    def private(values):host.environments.append(deepcopy(values));yield '/private/environment'
    def run(argv,**kwargs):
        host.runs.append((argv,kwargs))
        return SimpleNamespace(stdout=json.dumps({'request':request}).encode())
    host.private_environment=private;host.run=run
    return host,target,container,request


def invoke(host,target,container,request):
    start=model.utcnow()
    return host.observe_drain(target,container,request,started_at=start,
        accept_until=start+timedelta(seconds=180),deadline=time.monotonic()+180)


def test_one_owned_observer_uses_only_exact_readonly_volume_and_required_binding_environment():
    host,target,container,request=helper_host()
    assert invoke(host,target,container,request)=={'request':request}
    assert len(host.runs)==len(host.environments)==1
    argv,kwargs=host.runs[0]
    assert argv[:3]==['docker','run','--rm'] and '-i' in argv
    assert argv[argv.index('--network')+1]=='none'
    assert argv[argv.index('--mount')+1]=='type=volume,src=sentinel_sentinel_state,dst=/var/lib/sentinel,readonly'
    assert '--read-only' in argv and '--cap-drop' in argv and '--pids-limit' in argv
    assert NEW_IMAGE in argv and 'sentinel.shadow_drain_observer' in argv
    assert argv[argv.index('--user')+1]=='0'
    assert kwargs['cleanup_image']==NEW_IMAGE and 0<kwargs['timeout']<=180
    assert json.loads(kwargs['data'])==request
    assert set(host.environments[0])=={'SENTINEL_GIT_COMMIT','SENTINEL_RUNTIME_IMAGE_DIGEST',
        'SENTINEL_SHADOW_OBSERVATION_ID','SENTINEL_DATABASE_URL','SENTINEL_PUBLICATION_RECEIPT_KEY',
        'SENTINEL_STATE_DIR'}
    assert not any('must-never-enter-helper' in str(item) for item in (argv,kwargs,host.environments))


def test_observer_keeps_exact_predecessor_user_for_private_0600_state():
    host,target,container,request=helper_host();container['Config']['User']='10001:10001'
    invoke(host,target,container,request)
    argv,_kwargs=host.runs[0]
    assert argv[argv.index('--user')+1]=='10001:10001'


@pytest.mark.parametrize('fault',['container','image','volume','mount','missing-env','duplicate-env','commit','candidate-tag'])
def test_helper_rejects_foreign_or_ambiguous_input_before_launch(fault):
    host,target,container,request=helper_host()
    if fault=='container':container['Id']='foreign'
    elif fault=='image':container['Image']='foreign'
    elif fault=='volume':container['Mounts'][0]['Name']='foreign'
    elif fault=='mount':container['Mounts'].append(deepcopy(container['Mounts'][0]))
    elif fault=='missing-env':container['Config']['Env']=container['Config']['Env'][1:]
    elif fault=='duplicate-env':container['Config']['Env'].append('SENTINEL_GIT_COMMIT='+OLD)
    elif fault=='commit':container['Config']['Env'][0]='SENTINEL_GIT_COMMIT='+'f'*40
    else:host.request['candidate']['image']='mutable:latest'
    with pytest.raises(model.DeliveryRefused):invoke(host,target,container,request)
    assert not host.runs


def test_helper_launch_consumes_existing_wait_instead_of_resetting_it():
    host,target,container,request=helper_host();start=model.utcnow()
    with pytest.raises(model.DeliveryRefused,match='DEADLINE'):
        host.observe_drain(target,container,request,started_at=start,
            accept_until=start+timedelta(seconds=180),deadline=time.monotonic()-1)
    assert not host.runs


def test_request_drain_uses_one_observer_and_no_ack_exec_loop():
    host,_item,target,proof,calls=cooperative_drain_host()
    observers=[];original=host.observe_drain
    def observed(*args,**kwargs):observers.append(kwargs);return original(*args,**kwargs)
    host.observe_drain=observed
    assert evidence.request_drain(host,{},target)==proof and len(observers)==1
    assert not any('acknowledged' in argv for argv in calls)
    assert observers[0]['accept_until']-observers[0]['started_at']==timedelta(seconds=180)


def test_late_observer_response_refuses_without_renewing_request(monkeypatch):
    host,_item,target,_proof,calls=cooperative_drain_host();clock=[0.]
    original=host.observe_drain
    def late(*args,**kwargs):clock[0]=180;return original(*args,**kwargs)
    host.observe_drain=late
    monkeypatch.setattr(evidence.time,'monotonic',lambda:clock[0])
    with pytest.raises(evidence_model.DeliveryRefused,match='DEADLINE'):
        evidence.request_drain(host,{},target)
    assert sum('request' in argv for argv in calls)==1


def test_unknown_observer_failure_does_not_fall_back_to_polling():
    host,_item,target,_proof,calls=cooperative_drain_host()
    def refused(*args,**kwargs):raise evidence_model.DeliveryRefused('OBSERVER_FAILED')
    host.observe_drain=refused
    with pytest.raises(evidence_model.DeliveryRefused,match='OBSERVER_FAILED'):
        evidence.request_drain(host,{},target)
    assert not any('acknowledged' in argv for argv in calls)


def test_owned_observer_timeout_keeps_original_cleanup_bounds_and_exact_image(monkeypatch):
    host=object.__new__(hosts.Host);host.request={'owner':'fixture'};host.clean={};calls=[]
    def subprocess_run(argv,**kwargs):
        calls.append((argv,kwargs))
        if argv[:2]==['docker','run']:
            host.owned_name=argv[argv.index('--name')+1]
            raise subprocess.TimeoutExpired(argv,kwargs['timeout'])
        assert argv[:2]==['docker','inspect']
        return SimpleNamespace(returncode=0,stdout=json.dumps([{'Image':NEW_IMAGE,
            'Id':'f'*64,'Name':'/'+host.owned_name,
            'Config':{'Labels':{'sentinel.local-delivery.request':hosts.digest(host.request)}}}]).encode())
    monkeypatch.setattr(hosts.subprocess,'run',subprocess_run)
    removed=[];original=host.run
    def run(argv,**kwargs):
        if argv[:3]==['docker','rm','-f']:removed.append((argv,kwargs));return SimpleNamespace()
        return original(argv,**kwargs)
    host.run=run
    with pytest.raises(model.DeliveryRefused,match='TIMED_OUT'):
        host.run(['docker','run','--rm',NEW_IMAGE],timeout=.01,cleanup_image=NEW_IMAGE)
    assert len(calls)==2 and calls[-1][1]['timeout']==15
    assert len(removed)==1 and removed[0][1]['timeout']==20
    assert removed[0][0][-1]=='f'*64


def test_observer_cleanup_refuses_foreign_image_even_with_a_matching_owner_label(monkeypatch):
    host=object.__new__(hosts.Host);host.request={'owner':'fixture'};host.clean={}
    monkeypatch.setattr(hosts.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=0,
        stdout=json.dumps([{'Image':OLD_IMAGE,'Id':'f'*64,'Name':'/exact-owned-name','Config':{'Labels':{
            'sentinel.local-delivery.request':hosts.digest(host.request)}}}]).encode()))
    host.run=lambda *args,**kwargs:pytest.fail('foreign helper removed')
    with pytest.raises(model.DeliveryRefused,match='IMAGE_CHANGED'):
        host._cleanup_owned('exact-owned-name',image=NEW_IMAGE)


def test_cleanup_image_guard_has_a_foreign_removal_falsifier(monkeypatch):
    original=hosts.require
    monkeypatch.setattr(hosts,'require',lambda value,reason:
        None if reason=='PROOF_CLEANUP_IMAGE_CHANGED' else original(value,reason))
    with pytest.raises(pytest.fail.Exception,match='foreign helper removed'):
        test_observer_cleanup_refuses_foreign_image_even_with_a_matching_owner_label(monkeypatch)


def test_failed_cleanup_observation_is_unknown_never_assumed_absence(monkeypatch):
    host=object.__new__(hosts.Host);host.clean={}
    monkeypatch.setattr(hosts.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=1))
    host.run=lambda *args,**kwargs:pytest.fail('unknown container removed')
    with pytest.raises(model.DeliveryRefused,match='OUTCOME_UNKNOWN'):
        host._cleanup_owned('exact-owned-name',image=NEW_IMAGE)


def test_nonzero_observer_cli_cleans_live_exact_helper_before_refusing(tmp_path,monkeypatch):
    host=object.__new__(hosts.Host);host.request={'owner':'fixture'};host.clean={};host.operation_dir=tmp_path
    calls=[]
    def run(argv,**kwargs):
        calls.append((argv,kwargs))
        if argv[:2]==['docker','run']:
            host.name=argv[argv.index('--name')+1]
            return SimpleNamespace(returncode=1,stdout=b'private-child-output',stderr=b'private-error')
        if argv[:2]==['docker','inspect']:
            return SimpleNamespace(returncode=0,stdout=json.dumps([{'Id':'f'*64,'Name':'/'+host.name,
                'Image':NEW_IMAGE,'Config':{'Labels':{'sentinel.local-delivery.request':hosts.digest(host.request)}}}]).encode())
        assert argv==['docker','rm','-f','f'*64]
        return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
    monkeypatch.setattr(hosts.subprocess,'run',run)
    with pytest.raises(model.DeliveryRefused,match='CHILD_OPERATION_REFUSED'):
        host.run(['docker','run','--rm',NEW_IMAGE],timeout=1,cleanup_image=NEW_IMAGE)
    assert len(calls)==3 and calls[-1][1]['timeout']==20
    assert next(tmp_path.glob('private-command-error-*')).read_bytes()==b'private-child-output\nprivate-error'


def test_cleanup_unknown_preserves_primary_nonzero_child_diagnostic(tmp_path,monkeypatch):
    host=object.__new__(hosts.Host);host.request={'owner':'fixture'};host.clean={};host.operation_dir=tmp_path
    monkeypatch.setattr(hosts.subprocess,'run',lambda argv,**kwargs:SimpleNamespace(
        returncode=1,stdout=b'private-canary',stderr=b'private-canary'))
    with pytest.raises(model.DeliveryRefused,match='CLEANUP_OUTCOME_UNKNOWN') as error:
        host.run(['docker','run','--rm',NEW_IMAGE],timeout=1,cleanup_image=NEW_IMAGE)
    assert isinstance(error.value.__cause__,model.DeliveryRefused)
    assert str(error.value.__cause__).startswith('CHILD_OPERATION_REFUSED: private-command-error-')
    assert 'private-canary' not in str(error.value)+str(error.value.__cause__)


def test_positive_absence_proof_uses_only_remaining_original_cleanup_budget(monkeypatch):
    host=object.__new__(hosts.Host);host.clean={};calls=[];clock=[0.]
    def run(argv,**kwargs):
        calls.append((argv,kwargs));clock[0]=4
        return SimpleNamespace(returncode=1 if argv[:2]==['docker','inspect'] else 0,stdout=b'')
    monkeypatch.setattr(hosts.subprocess,'run',run)
    monkeypatch.setattr(hosts.time,'monotonic',lambda:clock[0])
    host._cleanup_owned('exact-owned-name',image=NEW_IMAGE)
    assert [kwargs['timeout'] for argv,kwargs in calls]==[15,11]
    assert calls[-1][0][-1]=='name=^/exact\\-owned\\-name$'
