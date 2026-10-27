"""Exercise actual durable handoff transitions and interrupted mutations."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import hashlib
import importlib
import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path
import sys

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
PACKAGE = ROOT/'scripts/sentinel_local_delivery'
SPEC = importlib.util.spec_from_file_location('delivery_coordinator_fixture', PACKAGE/'__init__.py',
    submodule_search_locations=[str(PACKAGE)])
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
model = importlib.import_module(SPEC.name+'.model')
coordinator = importlib.import_module(SPEC.name+'.coordinator')
host_module = importlib.import_module(SPEC.name+'.host')


def request(tmp_path):
    return dict(schema=model.SCHEMA, handoff_mode='PRE_OPEN',operation_id='fictional-delivery', source=str(tmp_path),
        deployment=str(tmp_path), predecessor=dict(commit='1'*40,image='sha256:'+'1'*64,
            postgres={'system':'unchanged'},system='123456789'),
        candidate=dict(commit='2'*40,image='sha256:'+'2'*64,
            source_identity={'source':'2'*64,'wealth':'3'*64,'shadow_config':'4'*64}),
        qualification=dict(report_path=str(tmp_path/'qualification.json'),report_sha256='5'*64,
            commit='2'*40,passed=True,source_files={'sentinel/example.py':'6'*64}),
        allowed_delta=['sentinel/example.py'],created_at=model.utcnow().isoformat())


def test_previous_requests_keep_preopen_semantics_and_cannot_inject_posttrade(tmp_path):
    value=request(tmp_path);value['schema']=model.PREVIOUS_SCHEMA;value.pop('handoff_mode')
    assert model.handoff_mode(model.validate_request(value))=='PRE_OPEN'
    model.write_new(tmp_path/'request.json',value)
    journal=model.Journal(tmp_path)
    assert journal.read()['schema']==model.PREVIOUS_SCHEMA
    assert journal.advance('NEW','PREFLIGHT_PASS')['stage']=='PREFLIGHT_PASS'
    value['handoff_mode']='POST_TRADE'
    with pytest.raises(model.DeliveryRefused,match='REQUEST_SHAPE'):model.validate_request(value)


def test_plain_archive_off_adapter_cannot_acquire_posttrade_permission(tmp_path):
    selected=request(tmp_path);selected['handoff_mode']='POST_TRADE'
    from types import SimpleNamespace
    with pytest.raises(model.DeliveryRefused,match='BACKED_ADAPTER_REQUIRED'):
        host_module.Host.verify_candidate(SimpleNamespace(request=selected))


class Host:
    def __init__(self, selected):
        self.request=selected
        self.values={key:selected['predecessor']['image'] for key in host_module.RUNTIME_KEYS}
        self.values.update(SENTINEL_GIT_COMMIT=selected['predecessor']['commit'],
            SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256='a'*64,
            SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256='b'*64,SECRET='private-value')
        self.state={'control':{'generation':77},'plan':'immutable-plan','commands':'unchanged'}
        self.native={'native-id':'17'};self.notifications={'old':'immutable-payload'}
        self.calls=[];self.busy=False;self.canonical_count=0;self.clock=0;self.heartbeat=0
        self.items={name:self.item(selected['predecessor']['image'],True) for name in host_module.SERVICES}
        self.fail_after=None
        self.drain_current=True;self.schema_complete=True;self.migration_count=0
    def item(self,image,running):
        return dict(Image=image,State=dict(Running=running,Health={'Status':'healthy'},
            OOMKilled=False,Restarting=False))
    def load_values(self): return dict(self.values)
    def candidate_values(self,old):
        new=dict(old)
        for key in host_module.RUNTIME_KEYS: new[key]=self.request['candidate']['image']
        new.update(SENTINEL_GIT_COMMIT=self.request['candidate']['commit'],
            SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256='2'*64,
            SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256='4'*64)
        return new
    def probe(self,*args,**kwargs): return {'source':'a'*64,'shadow_config':'b'*64}
    def verify_candidate(self): self.calls.append('verify-candidate')
    def container(self,name,missing_ok=False):
        if missing_ok and name not in self.items:return None
        return deepcopy(self.items[name])
    def predecessor_services(self):return host_module.SERVICES
    def verify_compose(self,role):self.calls.append('verify-compose-'+role)
    def install_compose(self):
        self.calls.append('install-compose')
        if self.fail_after=='compose':
            self.fail_after=None;raise model.DeliveryRefused('LOST_ACK')
    def postgres(self): return deepcopy(self.request['predecessor']['postgres'])
    def install_values(self,current,new):
        assert current==self.values
        self.values=dict(new);self.calls.append('install-runtime')
        if self.fail_after=='install':
            self.fail_after=None;raise model.DeliveryRefused('LOST_ACK')
    def compose(self,values,*args,**kwargs):
        self.calls.append(args)
        if args[0]=='stop':
            assert set(args[3:])==set(self.predecessor_services())
            for item in self.items.values():item['State']['Running']=False
            name='stop'
        else:
            names=[v for v in args if v in host_module.SERVICES]
            assert names and '--no-deps' in args and '--no-build' in args and 'never' in args
            for service in names:self.items[service]=self.item(self.request['candidate']['image'],True)
            name='shadow' if names==['sentinel-shadow'] else 'apps'
        if self.fail_after==name:
            self.fail_after=None;raise model.DeliveryRefused('LOST_ACK')
    @contextmanager
    def owned(self):
        assert not self.busy;self.busy=True
        try:yield
        finally:self.busy=False
    def sleep(self,seconds):self.clock+=seconds;self.heartbeat+=1


@pytest.fixture
def operation(tmp_path,monkeypatch):
    selected=request(tmp_path)
    model.write_new(tmp_path/'request.json',selected)
    journal=model.Journal(tmp_path);host=Host(selected)
    evidence=coordinator.evidence
    monkeypatch.setattr(evidence,'snapshot',lambda h:deepcopy(h.state))
    monkeypatch.setattr(evidence,'notification_history',lambda h:deepcopy(h.notifications))
    def unchanged(h,old):
        model.require(all(h.notifications.get(k)==v for k,v in old.items()),'HISTORY_CHANGED')
        return {'appended':len(h.notifications)-len(old)}
    monkeypatch.setattr(evidence,'check_notification_history',unchanged)
    monkeypatch.setattr(evidence,'native_positions',lambda h,v:deepcopy(h.native))
    monkeypatch.setattr(evidence,'compare_configuration',lambda *args:None)
    def canonical(h,*args):h.canonical_count+=1;return {'book':'same','proof':'same'}
    monkeypatch.setattr(evidence,'canonical_check',canonical)
    def idle(h,*args):model.require(not h.busy_worker,'WORKER_ACTIVE')
    host.busy_worker=False
    monkeypatch.setattr(evidence,'idle',idle)
    monkeypatch.setattr(evidence,'drain_target',lambda h:{'target':'exact-original-container'})
    def request_drain(h,*args):
        model.require(not h.busy_worker,'WORKER_ACTIVE')
        return {'method':'COOPERATIVE','acknowledgement':{'immutable':'incarnation-bound'}}
    monkeypatch.setattr(evidence,'request_drain',request_drain)
    def check_drain(h,*args):model.require(h.drain_current,'DRAIN_ACK_EXPIRED_OR_REPLACED')
    monkeypatch.setattr(evidence,'check_drain',check_drain)
    def migrate(h,*args):
        h.migration_count+=1
        return {'installation':{'installation_id':'immutable-current-schema'},'complete':h.schema_complete}
    monkeypatch.setattr(evidence,'migrate_operational_schema',migrate)
    monkeypatch.setattr(evidence,'leader',lambda h:dict(current=True,holder='owner',generation=77,
        fence=8,heartbeat=h.heartbeat))
    monkeypatch.setattr(evidence,'panel',lambda *args:{'fresh':True,'green':True})
    delivery=coordinator.Delivery(host,journal,monotonic=lambda:host.clock,sleep=host.sleep)
    return host,journal,delivery


def test_complete_actual_coordinator_reuses_preflight_and_preserves_history(operation):
    host,journal,delivery=operation
    receipt=delivery.advance()
    assert receipt['stage']=='VERIFIED' and host.canonical_count==3
    assert len(receipt['history'])==len(model.STAGES)-1 and host.heartbeat>0
    assert host.notifications=={'old':'immutable-payload'}
    assert 'private-value' not in json.dumps(receipt)
    mutations=[c for c in host.calls if isinstance(c,tuple)]
    assert len(mutations)==3 and mutations[0][0]=='stop'
    assert mutations[1][-1]=='sentinel-shadow'
    assert not any('postgres' in str(c) or 'backup' in str(c) for c in mutations)
    assert delivery.advance()==receipt and host.canonical_count==3


def test_full_source_checks_run_at_mutation_boundaries_not_journal_intents(operation):
    host,journal,delivery=operation
    checked=[]
    host.verify_candidate=lambda:checked.append(journal.read()['stage'])
    delivery.advance()
    assert checked==['NEW','DRAIN_REQUESTED','STOP_REQUESTED','SCHEMA_INSTALL_REQUESTED',
        'COMPOSE_INSTALL_REQUESTED','COMPOSE_INSTALLED','START_REQUESTED','APPLICATIONS_STARTED']
    delivery.advance()
    assert len(checked)==8


@pytest.mark.parametrize('stage', ['DRAIN_REQUESTED','STOP_REQUESTED','SCHEMA_INSTALL_REQUESTED',
    'COMPOSE_INSTALL_REQUESTED','COMPOSE_INSTALLED','START_REQUESTED','APPLICATIONS_STARTED'])
def test_changed_source_is_refused_before_each_installation_mutation(operation,stage):
    host,journal,delivery=operation
    while journal.read()['stage']!=stage:delivery.step()
    before=list(host.calls)
    def changed():raise model.DeliveryRefused('QUALIFIED_SOURCE_BYTES_CHANGED')
    host.verify_candidate=changed
    with pytest.raises(model.DeliveryRefused,match='QUALIFIED_SOURCE_BYTES_CHANGED'):
        delivery.step()
    assert host.calls==before and journal.read()['stage']==stage


@pytest.mark.parametrize('stage', ['DRAIN_REQUESTED','STOP_REQUESTED','COMPOSE_INSTALLED',
                                 'START_REQUESTED','APPLICATIONS_STARTED'])
@pytest.mark.parametrize('kind', ['state','book','native','history'])
def test_live_preservation_changes_refuse_at_each_operational_boundary(operation,stage,kind):
    host,journal,delivery=operation
    while journal.read()['stage']!=stage:delivery.step()
    if kind=='state':host.state['commands']='changed'
    elif kind=='book':host.state['book_cursors_md5']='changed'
    elif kind=='native':host.native['native-id']='18'
    else:host.notifications['old']='changed'
    mutations=[c for c in host.calls if isinstance(c,tuple)]
    with pytest.raises(model.DeliveryRefused):delivery.step()
    assert journal.read()['stage']==stage
    assert [c for c in host.calls if isinstance(c,tuple)]==mutations


def test_missing_mutation_source_check_has_a_falsifier(operation,monkeypatch):
    monkeypatch.setattr(coordinator,'SOURCE_CHECK_STAGES',
        coordinator.SOURCE_CHECK_STAGES-{'STOP_REQUESTED'})
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_changed_source_is_refused_before_each_installation_mutation(operation,'STOP_REQUESTED')


def test_missing_native_boundary_comparison_has_a_falsifier(operation,monkeypatch):
    host,journal,delivery=operation
    original=delivery._unchanged
    monkeypatch.setattr(delivery,'_unchanged',lambda artifacts,**kwargs:
        original(artifacts,native=False,allow_restart=kwargs.get('allow_restart',False)))
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_live_preservation_changes_refuse_at_each_operational_boundary(operation,'STOP_REQUESTED','native')


def test_native_comparisons_are_six_operational_observations_not_every_journal_step(operation,monkeypatch):
    host,journal,delivery=operation
    calls=[]
    original=coordinator.evidence.native_positions
    def observed(*args):
        calls.append(journal.read()['stage'])
        return original(*args)
    monkeypatch.setattr(coordinator.evidence,'native_positions',observed)
    delivery.advance()
    assert calls==['NEW','DRAIN_REQUESTED','STOP_REQUESTED','COMPOSE_INSTALLED',
                   'START_REQUESTED','APPLICATIONS_STARTED']


def test_restart_observation_is_used_only_after_all_candidate_services_started(operation):
    host,journal,delivery=operation
    calls=[]
    original=host.postgres
    def observe(expected):
        assert journal.read()['stage']=='APPLICATIONS_STARTED'
        assert expected==original()
        calls.append(True)
        return dict(expected,started='current-process')
    host.postgres_after_restart=observe
    receipt=delivery.advance()
    assert receipt['stage']=='VERIFIED' and len(calls)==2
    assert receipt['artifacts']['verified_postgres']['started']=='current-process'
    assert receipt['artifacts']['postgres']==host.request['predecessor']['postgres']


def test_restart_during_final_observation_refuses_completion(operation):
    host,journal,delivery=operation
    calls=[]
    def observe(expected):
        calls.append(True)
        return dict(expected,started=str(len(calls)))
    host.postgres_after_restart=observe
    with pytest.raises(model.DeliveryRefused,match='CHANGED_DURING_FINAL_OBSERVATION'):
        delivery.advance()
    assert journal.read()['stage']=='APPLICATIONS_STARTED'


@pytest.mark.parametrize('changed', [False, True])
def test_posttrade_native_positions_must_match_settled_reconciliation(operation, monkeypatch, changed):
    host, journal, delivery = operation
    selected = dict(host.request, handoff_mode='POST_TRADE')
    model.atomic_json(journal.folder/'request.json', selected)
    host.request = selected
    delivery.journal = model.Journal(journal.folder)
    settled = dict(host.native)
    if changed:
        settled['native-id'] = '18'
    monkeypatch.setattr(coordinator.evidence, 'canonical_check',
        lambda *_args: {'settled_native_positions': settled})
    if changed:
        with pytest.raises(model.DeliveryRefused, match='POST_TRADE_NATIVE_RECONCILIATION_CHANGED'):
            delivery.step()
        assert delivery.journal.read()['stage'] == 'NEW'
        assert not any(isinstance(call, tuple) for call in host.calls)
    else:
        assert delivery.step()['stage'] == 'PREFLIGHT_PASS'


def test_removing_posttrade_native_comparison_has_a_falsifier(operation, monkeypatch):
    original = coordinator.require
    monkeypatch.setattr(coordinator, 'require', lambda value, reason:
        None if reason == 'POST_TRADE_NATIVE_RECONCILIATION_CHANGED' else original(value, reason))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_posttrade_native_positions_must_match_settled_reconciliation(operation, monkeypatch, True)


@pytest.mark.parametrize('lost_ack',['stop','compose','install','shadow','apps'])
def test_lost_ack_resumes_only_exact_current_stage(operation,lost_ack):
    host,journal,delivery=operation;host.fail_after=lost_ack
    with pytest.raises(model.DeliveryRefused,match='LOST_ACK'):delivery.advance()
    assert journal.read()['stage'] in {'STOP_REQUESTED','COMPOSE_INSTALL_REQUESTED','COMPOSE_INSTALLED','START_REQUESTED'}
    assert delivery.advance()['stage']=='VERIFIED' and host.canonical_count==3


@pytest.mark.parametrize('kind',['state','native','history','configuration'])
def test_changed_preserved_state_refuses_before_application_stop(operation,kind):
    host,journal,delivery=operation;delivery.step();delivery.step()
    if kind=='state':host.state['commands']='changed'
    elif kind=='native':host.native['native-id']='18'
    elif kind=='history':host.notifications['old']='changed'
    else:host.values['SECRET']='changed'
    with pytest.raises(model.DeliveryRefused):delivery.step()
    assert journal.read()['stage']=='DRAIN_REQUESTED'
    assert not any(isinstance(c,tuple) for c in host.calls)


def test_active_worker_cannot_acknowledge_or_stop_applications(operation):
    host,journal,delivery=operation;delivery.step();delivery.step();host.busy_worker=True
    with pytest.raises(model.DeliveryRefused,match='WORKER_ACTIVE'):delivery.step()
    assert journal.read()['stage']=='DRAIN_REQUESTED'
    assert not any(isinstance(c,tuple) for c in host.calls)


def test_expired_or_replaced_drain_never_reaches_stop(operation):
    host,journal,delivery=operation
    while journal.read()['stage']!='STOP_REQUESTED':delivery.step()
    host.drain_current=False
    with pytest.raises(model.DeliveryRefused,match='DRAIN_ACK'):
        delivery.step()
    assert journal.read()['stage']=='STOP_REQUESTED'
    assert not any(isinstance(c,tuple) for c in host.calls)


def test_pending_bootstrap_retains_same_stage_and_resumes_pages_without_repreflight(operation):
    host,journal,delivery=operation
    host.schema_complete=False
    first=delivery.advance()
    assert first['stage']=='SCHEMA_INSTALL_REQUESTED' and host.migration_count==1
    assert host.canonical_count==2 and all(not item['State']['Running'] for item in host.items.values())
    host.schema_complete=True
    assert delivery.advance()['stage']=='VERIFIED' and host.migration_count==2
    assert host.canonical_count==3


def test_first_four_to_six_role_handoff_does_not_require_nonexistent_old_containers(operation):
    host,journal,delivery=operation
    host.predecessor_services=lambda:host_module.LEGACY_SERVICES
    for name in host_module.SERVICES[4:]:host.items.pop(name)
    assert delivery.advance()['stage']=='VERIFIED'
    assert set(host.items)==set(host_module.SERVICES)
    assert all(item['Image']==host.request['candidate']['image'] for item in host.items.values())


def assert_compose_power_loss_recovery(operation,tmp_path,monkeypatch):
    host,journal,delivery=operation
    source,installed=tmp_path/'candidate-compose',tmp_path/'installed-compose'
    source.mkdir();installed.mkdir()
    original={name:('predecessor '+name).encode() for name in host_module.COMPOSE}
    candidate={name:('qualified candidate '+name).encode() for name in host_module.COMPOSE}
    for name in host_module.COMPOSE:
        (source/name).write_bytes(candidate[name]);(installed/name).write_bytes(original[name])
    actual=object.__new__(host_module.Host)
    actual.source,actual.deployment=source,installed
    actual.request={'predecessor':{'commit':'1'*40},'qualification':{'source_files':{
        name:hashlib.sha256(value).hexdigest() for name,value in candidate.items()}}}
    actual.git_bytes=lambda _show,subject:original[subject.split(':',1)[1]]
    host.install_compose=actual.install_compose
    while journal.read()['stage']!='COMPOSE_INSTALL_REQUESTED':delivery.step()
    real_fsync=os.fsync
    state={'lose_power':True,'directory_synced':False}
    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            assert all((installed/name).read_bytes()==raw for name,raw in candidate.items())
            if state['lose_power']:
                # Emulate one rename lost at power failure. Its journal intent
                # must remain reusable with a mixed exact old/new file set.
                name=host_module.COMPOSE[0]
                (installed/name).write_bytes(original[name])
                raise OSError('SIMULATED_POWER_LOSS_BEFORE_DIRECTORY_SYNC')
            state['directory_synced']=True
        return real_fsync(fd)
    monkeypatch.setattr(host_module.os,'fsync',fsync)
    with pytest.raises(OSError,match='SIMULATED_POWER_LOSS'):
        delivery.step()
    assert journal.read()['stage']=='COMPOSE_INSTALL_REQUESTED', 'Compose receipt advanced before directory durability'
    assert not state['directory_synced']
    state['lose_power']=False
    assert delivery.step()['stage']=='COMPOSE_INSTALLED'
    assert state['directory_synced']
    assert all((installed/name).read_bytes()==raw for name,raw in candidate.items())


def test_compose_directory_sync_precedes_durable_stage_and_survives_power_loss(operation,tmp_path,monkeypatch):
    assert_compose_power_loss_recovery(operation,tmp_path,monkeypatch)


def test_removing_compose_directory_sync_has_a_power_loss_falsifier(operation,tmp_path,monkeypatch):
    import inspect
    import textwrap
    source=textwrap.dedent(inspect.getsource(host_module.Host.install_compose))
    source=source.replace('        os.fsync(directory)','        pass  # removed directory durability guard')
    scope=dict(vars(host_module))
    exec(compile(source,'Compose durability falsifier','exec'),scope)
    monkeypatch.setattr(host_module.Host,'install_compose',scope['install_compose'])
    with pytest.raises((AssertionError,pytest.fail.Exception),
                       match='Compose receipt advanced before directory durability|DID NOT RAISE'):
        assert_compose_power_loss_recovery(operation,tmp_path,monkeypatch)


@pytest.mark.parametrize('stage',['SCHEMA_INSTALL_REQUESTED','COMPOSE_INSTALL_REQUESTED'])
def test_new_mutation_stages_preserve_original_preflight_expiry(operation,monkeypatch,stage):
    host,journal,delivery=operation
    while journal.read()['stage']!=stage:delivery.step()
    before=host.migration_count if stage=='SCHEMA_INSTALL_REQUESTED' else host.calls.count('install-compose')
    monkeypatch.setattr(coordinator,'utcnow',lambda:model.utcnow()+timedelta(minutes=16))
    with pytest.raises(model.DeliveryRefused,match='INTERVAL_EXPIRED'):delivery.step()
    assert (host.migration_count if stage=='SCHEMA_INSTALL_REQUESTED' else host.calls.count('install-compose'))==before


def test_historical_verified_receipt_keeps_its_original_finite_stage_contract(tmp_path):
    selected=request(tmp_path);selected['schema']=model.LEGACY_SCHEMA;selected.pop('handoff_mode')
    model.write_new(tmp_path/'request.json',selected)
    subject=model.digest(selected);artifacts={'historical_scope':'unchanged'};previous=subject;history=[]
    for stage in model.LEGACY_STAGES[1:]:
        event=dict(stage=stage,at=model.utcnow().isoformat(),previous=previous,artifacts_sha256=model.digest(artifacts))
        event['sha256']=model.digest(event);previous=event['sha256'];history.append(event)
    receipt=dict(schema=model.LEGACY_SCHEMA,operation_id=selected['operation_id'],request_sha256=subject,
                 stage='VERIFIED',history=history,artifacts=artifacts)
    model.write_new(tmp_path/'receipt.json',receipt)
    journal=model.Journal(tmp_path)
    assert journal.read()==receipt
    with pytest.raises(model.DeliveryRefused,match='LEGACY_DELIVERY_CANNOT_RESUME'):
        journal.advance('VERIFIED','NEW')


@pytest.mark.parametrize('stage',['STOP_REQUESTED','START_REQUESTED'])
def test_stale_durable_intent_cannot_mutate_applications(operation,monkeypatch,stage):
    host,journal,delivery=operation
    while journal.read()['stage']!=stage:delivery.step()
    now=model.utcnow()+timedelta(minutes=16)
    monkeypatch.setattr(coordinator,'utcnow',lambda:now)
    before=len(host.calls)
    with pytest.raises(model.DeliveryRefused,match='INTERVAL_EXPIRED'):delivery.step()
    assert all(not isinstance(c,tuple) for c in host.calls[before:])
    # Falsifier: removing the original-clock check permits the rejected mutation.
    monkeypatch.setattr(delivery,'_fresh',lambda _:None)
    delivery.step()
    assert any(isinstance(c,tuple) for c in host.calls[before:])


def test_request_and_linked_receipt_tampering_fail_closed(operation,tmp_path):
    host,journal,delivery=operation;delivery.step()
    raw=model.read_json(tmp_path/'receipt.json');raw['artifacts']['preserved']['commands']='forged'
    model.atomic_json(tmp_path/'receipt.json',raw)
    with pytest.raises(model.DeliveryRefused,match='ARTIFACTS_CHANGED'):journal.read()


def test_duplicate_json_and_unsafe_request_never_reach_subprocess(tmp_path):
    path=tmp_path/'record.json';path.write_text('{"schema":1,"schema":2}')
    with pytest.raises(model.DeliveryRefused,match='DUPLICATE_KEY'):model.read_json(path)
    selected=request(tmp_path);selected['allowed_delta']=['sentinel/../.env']
    with pytest.raises(model.DeliveryRefused,match='DELTA_PATH'):model.validate_request(selected)


def test_nonblocking_real_host_lock_rejects_another_delivery(tmp_path):
    first=host_module.Host.__new__(host_module.Host);first.deployment=tmp_path
    second=host_module.Host.__new__(host_module.Host);second.deployment=tmp_path
    with first.owned():
        with pytest.raises(model.DeliveryRefused,match='ANOTHER_DELIVERY'):
            with second.owned():raise AssertionError('concurrent owner entered')
    with second.owned():pass


def test_timed_out_oneoff_cleanup_is_scoped_to_this_request(tmp_path,monkeypatch):
    host=host_module.Host.__new__(host_module.Host)
    host.request=request(tmp_path);host.deployment=tmp_path;host.clean={}
    host.compose_paths=lambda values:tuple(tmp_path/name for name in host_module.COMPOSE)
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        if argv[0:2]==['docker','compose']:
            raise subprocess.TimeoutExpired(argv,1)
        return None
    host.run=run
    def inspect(argv,**kwargs):
        assert argv[:2]==['docker','inspect']
        assert argv[2]==calls[0][calls[0].index('--name')+1]
        item={'Config':{'Labels':{'sentinel.local-delivery.request':model.digest(host.request)}}}
        return subprocess.CompletedProcess(argv,0,stdout=json.dumps([item]).encode())
    monkeypatch.setattr(host_module.subprocess,'run',inspect)
    with pytest.raises(model.DeliveryRefused,match='TIMED_OUT'):
        host.compose({},'run','--rm','sentinel-authorized-cli','python')
    assert calls[1]==['docker','rm','-f',calls[0][calls[0].index('--name')+1]]
    assert 'postgres' not in str(calls) and 'sentinel-shadow-1' not in str(calls)


@pytest.mark.parametrize('foreign',[False,True])
def test_direct_offline_image_timeout_has_owned_cleanup_guard(tmp_path,monkeypatch,foreign):
    host=host_module.Host.__new__(host_module.Host)
    host.request=request(tmp_path);host.clean={};host.operation_dir=tmp_path
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        if argv[:2]==['docker','run']:raise subprocess.TimeoutExpired(argv,1)
        if argv[:2]==['docker','inspect']:
            labels={'sentinel.local-delivery.request': 'foreign' if foreign else model.digest(host.request)}
            return subprocess.CompletedProcess(argv,0,stdout=json.dumps([{'Config':{'Labels':labels}}]).encode())
        return subprocess.CompletedProcess(argv,0,stdout=b'',stderr=b'')
    monkeypatch.setattr(host_module.subprocess,'run',run)
    reason='OWNERSHIP_CHANGED' if foreign else 'TIMED_OUT'
    with pytest.raises(model.DeliveryRefused,match=reason):
        host.run(['docker','run','--rm','--network','none','exact-image'])
    removals=[c for c in calls if c[:3]==['docker','rm','-f']]
    assert len(removals)==(0 if foreign else 1)


def test_failed_commands_keep_distinct_private_evidence_without_printing_secrets(tmp_path,monkeypatch):
    host=host_module.Host.__new__(host_module.Host)
    host.request=request(tmp_path);host.clean={};host.operation_dir=tmp_path
    def fail(argv,**kwargs):
        return subprocess.CompletedProcess(argv,1,stdout=b'private-result',stderr=b'private-secret')
    monkeypatch.setattr(host_module.subprocess,'run',fail)
    for _ in range(2):
        with pytest.raises(model.DeliveryRefused,match='CHILD_OPERATION_REFUSED') as error:
            host.run(['read-only-program'])
        assert 'private-secret' not in str(error.value)
    files=list(tmp_path.glob('private-command-error-*.log'))
    assert len(files)==2 and all(path.read_bytes()==b'private-result\nprivate-secret' for path in files)
    assert all(path.stat().st_mode&0o077==0 for path in files)
