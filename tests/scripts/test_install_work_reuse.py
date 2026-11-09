"""Immutable facts may be reused; mutable installation boundaries stay fresh."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tests.scripts.test_sentinel_local_delivery_coordinator import (
    coordinator, host_module as hosts, model, operation)
from tests.scripts.test_sentinel_local_delivery_cli import (
    inputs, qualification, model as qualification_model)

OLD, NEW = '1'*40, '2'*40
IMAGE = 'sha256:'+'3'*64
IDENTITY = dict(source='a'*64,shadow_config='b'*64,wealth='c'*64)


def probe_host():
    host=object.__new__(hosts.Host)
    host.config={'SENTINEL_SHADOW_OBSERVATION_ID':'primary',
        'SENTINEL_SHADOW_STARTING_CASH':'50000',
        'SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY':'qualified-policy'}
    host.loads=[];host.renders=[];host.runs=[]
    def load():host.loads.append(1);return {'fresh':'value'}
    def compose(values,*args):
        host.renders.append(deepcopy(host.config))
        return SimpleNamespace(stdout=json.dumps({'services':{'sentinel-shadow':{
            'environment':host.config}}}).encode())
    def run(argv,**kwargs):
        host.runs.append((argv,kwargs))
        return SimpleNamespace(stdout=json.dumps(IDENTITY).encode())
    host.load_values=load;host.compose=compose;host.run=run
    return host


def test_probe_reuses_only_immutable_result_after_fresh_configuration_render():
    host=probe_host()
    first=host.probe(NEW,IMAGE);first['source']='modified-return'
    assert host.probe(NEW,IMAGE)==IDENTITY
    assert len(host.runs)==1 and len(host.loads)==len(host.renders)==2
    assert hosts.Host.probe(probe_host(),NEW,IMAGE)==IDENTITY


@pytest.mark.parametrize('change',['image','commit','config'])
def test_probe_subject_or_explicit_configuration_changes_do_not_reuse(change):
    host=probe_host();host.probe(NEW,IMAGE)
    commit,image=NEW,IMAGE
    if change=='image':image='sha256:'+'4'*64
    elif change=='commit':commit=OLD
    else:host.config['SENTINEL_SHADOW_STARTING_CASH']='50001'
    assert host.probe(commit,image)==IDENTITY and len(host.runs)==2


@pytest.mark.parametrize('fault',['failed','malformed'])
def test_failed_and_malformed_identity_probes_are_not_admitted(fault):
    host=probe_host();original=host.run
    def invalid(*args,**kwargs):
        if fault=='failed':raise model.DeliveryRefused('PRIVATE_PROBE_FAILURE')
        return SimpleNamespace(stdout=b'{"source":"unqualified"}')
    host.run=invalid
    with pytest.raises(model.DeliveryRefused):host.probe(NEW,IMAGE)
    host.run=original
    assert host.probe(NEW,IMAGE)==IDENTITY and len(host.runs)==1


@pytest.mark.parametrize('commit,image', [('HEAD',IMAGE),(NEW,'mutable:latest'),
    (NEW,'repository@'+IMAGE)])
def test_identity_cache_never_accepts_mutable_or_unresolved_subjects(commit,image):
    host=probe_host()
    with pytest.raises(model.DeliveryRefused,match='SUBJECT_INVALID'):host.probe(commit,image)
    assert host.loads==host.runs==[]


def git_host(tmp_path):
    host=object.__new__(hosts.Host);host.source=tmp_path
    (tmp_path/'.git').mkdir(exist_ok=True)
    host.calls=[]
    def run(argv):
        host.calls.append(argv)
        return SimpleNamespace(stdout=str(len(host.calls)).encode())
    host.run=run
    return host


@pytest.mark.parametrize('args', [('merge-base',OLD,NEW),
    ('diff','--name-only',OLD,NEW),('diff','--name-only','-z',OLD,NEW),
    ('ls-tree','-r','--name-only','-z',NEW),('show',OLD+':'+hosts.COMPOSE[0])])
def test_exact_git_object_queries_reuse_one_result_without_replacement_refs(tmp_path,args):
    host=git_host(tmp_path)
    assert host.git(*args)==host.git(*args)=='1'
    assert len(host.calls)==1 and '--no-replace-objects' in host.calls[0]
    another=git_host(tmp_path)
    another.git(*args)
    assert len(another.calls)==1


@pytest.mark.parametrize('args', [('rev-parse','HEAD'),('status','--porcelain'),
    ('branch','--show-current'),('ls-files','-z'),('merge-base','HEAD',NEW),
    ('diff','--name-only',OLD,'HEAD'),('show','main:'+hosts.COMPOSE[0]),
    ('show',OLD+':sentinel/unreviewed.py')])
def test_mutable_or_out_of_scope_git_reads_are_never_cached(tmp_path,args):
    host=git_host(tmp_path)
    assert host.git(*args)=='1' and host.git(*args)=='2'
    assert all('--no-replace-objects' not in argv for argv in host.calls)


def test_closed_git_query_whitelist_has_a_removed_guard_falsifier(tmp_path,monkeypatch):
    monkeypatch.setattr(hosts,'_immutable_git',lambda args:True)
    with pytest.raises(AssertionError):
        test_mutable_or_out_of_scope_git_reads_are_never_cached(tmp_path,('rev-parse','HEAD'))


@pytest.mark.parametrize('common',[False,True])
def test_graft_absence_is_checked_again_before_each_cached_object_use(tmp_path,common):
    host=git_host(tmp_path);metadata=tmp_path/'.git'
    if common:
        shared=tmp_path/'shared';shared.mkdir()
        (metadata/'commondir').write_text('../shared')
        metadata=shared
    assert host.git('merge-base',OLD,NEW)=='1'
    (metadata/'info').mkdir()
    (metadata/'info/grafts').write_text('mutable-history')
    with pytest.raises(model.DeliveryRefused,match='GRAFTS_REFUSED'):
        host.git('merge-base',OLD,NEW)
    assert len(host.calls)==1


@pytest.mark.parametrize('fault',['head','branch','status','bytes','log'])
def test_git_fact_reuse_keeps_mutable_qualification_checks_fresh(inputs,fault):
    calls=[];facts={};damage=[False]
    def read(*args):
        if damage[0]:
            if fault=='head' and args==('rev-parse','HEAD'):return 'f'*40
            if fault=='branch' and args==('branch','--show-current'):return 'main'
            if fault=='status' and args==('status','--porcelain'):return ' M sentinel/module.py'
        if hosts._immutable_git(args) and args in facts:return facts[args]
        calls.append(args);result=inputs.git(inputs.source,*args)
        if hosts._immutable_git(args):facts[args]=result
        return result
    def validate():
        return qualification.validate_report(inputs.report_path,inputs.report_sha,inputs.source,
            inputs.report['commit'],inputs.report['predecessor_commit'],git_reader=read)
    assert validate()==validate()==inputs.report
    assert calls.count(('rev-parse','HEAD'))==2
    assert calls.count(('status','--porcelain'))==2
    assert calls.count(('branch','--show-current'))==2
    assert calls.count(('merge-base',inputs.report['predecessor_commit'],inputs.report['commit']))==1
    assert calls.count(('ls-tree','-r','--name-only','-z',inputs.report['commit']))==1
    damage[0]=True
    if fault=='bytes':(inputs.source/'sentinel/module.py').write_text('forged=1\n')
    elif fault=='log':inputs.log.write_text('99 passed in 0.1s\n')
    with pytest.raises(qualification_model.DeliveryRefused):validate()


def application(service, *, image=IMAGE):
    return dict(Id=('a' if service==hosts.SERVICES[0] else 'b')*64,
        Name='/sentinel-'+service+'-1',Image=image,
        Config={'Labels':{'com.docker.compose.project':'sentinel',
            'com.docker.compose.service':service,'com.docker.compose.config-hash':'c'*64}},
        State={'Running':True,'Health':{'Status':'healthy'},'Restarting':False,'OOMKilled':False})


def observation_host(items):
    host=object.__new__(hosts.Host);host.calls=[]
    def run(argv):
        host.calls.append(argv)
        if argv[:3]==['docker','container','ls']:
            raw='\n'.join(json.dumps(dict(ID=item['Id'],Names=item['Name'][1:])) for item in items)
        else:raw=json.dumps(items)
        return SimpleNamespace(stdout=raw.encode())
    host.run=run
    return host


def test_required_six_role_observation_is_one_fresh_process_each_time():
    items=[application(name) for name in hosts.SERVICES];host=observation_host(items)
    first=host.containers(hosts.SERVICES)
    assert len(host.calls)==1 and len(first)==6
    items[0]['State']['Running']=False
    second=host.containers(hosts.SERVICES)
    assert len(host.calls)==2 and first[hosts.SERVICES[0]]['State']['Running'] is True
    assert second[hosts.SERVICES[0]]['State']['Running'] is False


def test_optional_role_absence_is_explicit_and_discovered_ids_are_inspected_once():
    items=[application(hosts.SERVICES[0])];host=observation_host(items)
    observed=host.containers(hosts.SERVICES,missing_ok=True)
    assert len(host.calls)==2 and host.calls[-1][-1]==items[0]['Id']
    assert observed[hosts.SERVICES[0]]==items[0]
    assert all(observed[name] is None for name in hosts.SERVICES[1:])


@pytest.mark.parametrize('fault',['missing','duplicate','foreign','malformed','replaced'])
def test_batch_observation_refuses_ambiguous_or_changed_results(fault):
    items=[application(name) for name in hosts.SERVICES];host=observation_host(items)
    if fault=='missing':items.pop()
    elif fault=='duplicate':items[-1]=deepcopy(items[0])
    elif fault=='foreign':items[-1]['Name']='/foreign-name'
    elif fault=='malformed':items[-1]['State']=None
    else:
        original=host.run
        def changed(argv):
            if argv[:3]==['docker','container','inspect']:items[0]['Id']='changed-id'
            return original(argv)
        host.run=changed
    with pytest.raises(model.DeliveryRefused):
        host.containers(hosts.SERVICES,missing_ok=fault=='replaced')


def ready_host():
    host=object.__new__(hosts.Host);host.request={'candidate':{'image':IMAGE}}
    items={name:application(name) for name in hosts.SERVICES}
    return host,items,{name:'c'*64 for name in hosts.SERVICES}


@pytest.mark.parametrize('fault',[None,'missing','image','running','health','oom','restarting',
    'project','service','hash','missing-hash','malformed-state','malformed-config'])
def test_noop_start_requires_every_role_image_health_and_current_config_hash(fault):
    host,items,hashes=ready_host();name=hosts.SERVICES[-1];item=items[name]
    if fault=='missing':items.pop(name)
    elif fault=='image':item['Image']='foreign'
    elif fault=='running':item['State']['Running']=False
    elif fault=='health':item['State']['Health']['Status']='unhealthy'
    elif fault=='oom':item['State']['OOMKilled']=True
    elif fault=='restarting':item['State']['Restarting']=True
    elif fault in {'project','service','hash'}:
        key={'project':'project','service':'service','hash':'config-hash'}[fault]
        item['Config']['Labels']['com.docker.compose.'+key]='foreign'
    elif fault=='missing-hash':hashes.pop(name)
    elif fault=='malformed-state':item['State']=None
    elif fault=='malformed-config':item['Config']=None
    assert host.candidate_apps_ready(hashes,items) is (fault is None)


@pytest.mark.parametrize('fault',[None,'missing','duplicate','malformed','failed'])
def test_expected_config_hashes_use_bounded_current_compose_and_fail_closed(fault):
    host,_,hashes=ready_host();calls=[]
    def compose(values,*args,**kwargs):
        calls.append((values,args,kwargs))
        if fault=='failed':raise model.DeliveryRefused('UNSUPPORTED_HASH_OPERATION')
        lines=[name+' '+digest for name,digest in hashes.items()]
        if fault=='missing':lines.pop()
        elif fault=='duplicate':lines.append(lines[0])
        elif fault=='malformed':lines[-1]='not-a-service-hash'
        return SimpleNamespace(stdout=('\n'.join(lines)+'\n').encode())
    host.compose=compose
    assert host.candidate_config_hashes({'fresh':'config'})==(hashes if fault is None else None)
    assert calls==[({'fresh':'config'},('config','--hash','*'),{'timeout':90})]


def at_start(operation):
    host,journal,delivery=operation
    while journal.read()['stage']!='START_REQUESTED':delivery.step()
    return host,journal,delivery


def test_lost_start_ack_resume_skips_only_completed_exact_candidate_start(operation):
    host,journal,delivery=at_start(operation)
    candidate=host.candidate_values(host.values)
    host.compose(candidate,'up','--no-deps','--no-build','--pull','never',*hosts.SERVICES[1:])
    before=list(host.calls)
    assert delivery.step()['stage']=='APPLICATIONS_STARTED'
    assert host.calls==before+['verify-candidate'] and host.config_renders==1


def test_configuration_render_precedes_the_fresh_resume_observation(operation):
    host,journal,delivery=at_start(operation)
    candidate=host.candidate_values(host.values)
    host.compose(candidate,'up','--no-deps','--no-build','--pull','never',*hosts.SERVICES[1:])
    original=host.candidate_config_hashes
    def change(values):
        result=original(values)
        host.items[hosts.SERVICES[-1]]['Config']['Labels']['com.docker.compose.config-hash']='foreign'
        return result
    host.candidate_config_hashes=change
    before=len(host.calls)
    assert delivery.step()['stage']=='APPLICATIONS_STARTED'
    assert any(isinstance(call,tuple) and call[0]=='up' for call in host.calls[before:])


@pytest.mark.parametrize('fault',['missing','image','running','health','oom','restarting'])
def test_changed_shadow_after_wait_refuses_before_starting_other_roles(operation,fault):
    host,journal,delivery=at_start(operation);original=host.candidate_config_hashes
    def change(values):
        result=original(values);item=host.items['sentinel-shadow']
        if fault=='missing':host.items.pop('sentinel-shadow')
        elif fault=='image':item['Image']='foreign'
        elif fault=='running':item['State']['Running']=False
        elif fault=='health':item['State']['Health']['Status']='unhealthy'
        elif fault=='oom':item['State']['OOMKilled']=True
        else:item['State']['Restarting']=True
        return result
    host.candidate_config_hashes=change;before=len(host.calls)
    with pytest.raises(model.DeliveryRefused,match='SUCCESSOR_SHADOW_CHANGED'):delivery.step()
    assert journal.read()['stage']=='START_REQUESTED'
    assert not any(isinstance(call,tuple) and call[0]=='up' for call in host.calls[before:])


def test_changed_shadow_guard_has_a_removed_guard_falsifier(operation,monkeypatch):
    monkeypatch.setattr(coordinator,'application_healthy',lambda *args:True)
    with pytest.raises(AssertionError):
        test_changed_shadow_after_wait_refuses_before_starting_other_roles(operation,'image')


def test_real_start_requires_a_separate_fresh_post_mutation_batch(operation):
    host,journal,delivery=at_start(operation);observations=[];original=host.containers
    def observe(*args,**kwargs):
        result=original(*args,**kwargs);observations.append(deepcopy(result));return result
    host.containers=observe
    assert delivery.step()['stage']=='APPLICATIONS_STARTED'
    assert len(observations)==2
    assert observations[0][hosts.SERVICES[-1]]['State']['Running'] is False
    assert observations[1][hosts.SERVICES[-1]]['State']['Running'] is True


def test_noop_configuration_guard_has_a_removed_guard_falsifier(monkeypatch):
    original=hosts.Host.candidate_apps_ready
    monkeypatch.setattr(hosts.Host,'candidate_apps_ready',lambda *args:True)
    with pytest.raises(AssertionError):
        test_noop_start_requires_every_role_image_health_and_current_config_hash('hash')
    monkeypatch.setattr(hosts.Host,'candidate_apps_ready',original)
