"""Exercise actual durable handoff transitions and interrupted mutations."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import importlib
import importlib.util
import json
import os
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
    return dict(schema=model.SCHEMA, operation_id='fictional-delivery', source=str(tmp_path),
        deployment=str(tmp_path), predecessor=dict(commit='1'*40,image='sha256:'+'1'*64,
            postgres={'system':'unchanged'},system='123456789'),
        candidate=dict(commit='2'*40,image='sha256:'+'2'*64,
            source_identity={'source':'2'*64,'wealth':'3'*64,'shadow_config':'4'*64}),
        qualification=dict(report_path=str(tmp_path/'qualification.json'),report_sha256='5'*64,
            commit='2'*40,passed=True,source_files={'sentinel/example.py':'6'*64}),
        allowed_delta=['sentinel/example.py'],created_at=model.utcnow().isoformat())


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
    def container(self,name): return deepcopy(self.items[name])
    def postgres(self): return deepcopy(self.request['predecessor']['postgres'])
    def install_values(self,current,new):
        assert current==self.values
        self.values=dict(new);self.calls.append('install-runtime')
        if self.fail_after=='install':
            self.fail_after=None;raise model.DeliveryRefused('LOST_ACK')
    def compose(self,values,*args,**kwargs):
        self.calls.append(args)
        if args[0]=='stop':
            assert set(args[3:])==set(host_module.SERVICES)
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
    monkeypatch.setattr(evidence,'leader',lambda h:dict(current=True,holder='owner',generation=77,
        fence=8,heartbeat=h.heartbeat))
    monkeypatch.setattr(evidence,'panel',lambda *args:{'fresh':True,'green':True})
    delivery=coordinator.Delivery(host,journal,monotonic=lambda:host.clock,sleep=host.sleep)
    return host,journal,delivery


def test_complete_actual_coordinator_reuses_preflight_and_preserves_history(operation):
    host,journal,delivery=operation
    receipt=delivery.advance()
    assert receipt['stage']=='VERIFIED' and host.canonical_count==3
    assert len(receipt['history'])==8 and host.heartbeat>0
    assert host.notifications=={'old':'immutable-payload'}
    assert 'private-value' not in json.dumps(receipt)
    mutations=[c for c in host.calls if isinstance(c,tuple)]
    assert len(mutations)==3 and mutations[0][0]=='stop'
    assert mutations[1][-1]=='sentinel-shadow'
    assert not any('postgres' in str(c) or 'backup' in str(c) for c in mutations)
    assert delivery.advance()==receipt and host.canonical_count==3


@pytest.mark.parametrize('lost_ack',['stop','install','shadow','apps'])
def test_lost_ack_resumes_only_exact_current_stage(operation,lost_ack):
    host,journal,delivery=operation;host.fail_after=lost_ack
    with pytest.raises(model.DeliveryRefused,match='LOST_ACK'):delivery.advance()
    assert journal.read()['stage'] in {'STOP_REQUESTED','APPLICATIONS_STOPPED','START_REQUESTED'}
    assert delivery.advance()['stage']=='VERIFIED' and host.canonical_count==3


@pytest.mark.parametrize('kind',['state','native','history','configuration'])
def test_changed_preserved_state_refuses_before_application_stop(operation,kind):
    host,journal,delivery=operation;delivery.step()
    if kind=='state':host.state['commands']='changed'
    elif kind=='native':host.native['native-id']='18'
    elif kind=='history':host.notifications['old']='changed'
    else:host.values['SECRET']='changed'
    with pytest.raises(model.DeliveryRefused):delivery.step()
    assert journal.read()['stage']=='PREFLIGHT_PASS'
    assert not any(isinstance(c,tuple) for c in host.calls)


def test_active_worker_refuses_and_does_not_consume_preflight(operation):
    host,journal,delivery=operation;delivery.step();host.busy_worker=True
    with pytest.raises(model.DeliveryRefused,match='WORKER_ACTIVE'):delivery.step()
    assert journal.read()['stage']=='PREFLIGHT_PASS'


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
