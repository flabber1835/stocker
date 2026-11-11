"""The real pass fence protects the one service through crash and rollback."""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import importlib
import json
import multiprocessing
import os
from pathlib import Path
import pwd
import subprocess
import sys

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0,str(ROOT/'scripts'))
import sentinel_maintenance_reader_handover as module
from sentinel_local_delivery.model import DeliveryRefused, canonical

OLD = 'a'*40
NEW = 'b'*40
IMAGE = 'sha256:'+'c'*64
OLD_IMAGE = 'sha256:'+'d'*64
KEY = 'private-test-key-only-'*3
LINEAGE_TESTS = ('tests/scripts/test_sentinel_backed_local_patch.py','tests/scripts/test_sentinel_backed_predecessor.py',
    'tests/scripts/test_sentinel_maintenance_reader_handover.py')
LINEAGE_DELTA = frozenset({*LINEAGE_TESTS,'docs/local-paper-delivery.md',
    'scripts/sentinel_backed_local_patch.py','scripts/sentinel_maintenance_reader_handover.py'})


class PowerLoss(BaseException):
    pass


def dump(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(canonical(value)+b'\n')


def write_env(path, values):
    path.write_text(''.join(k+'='+v+'\n' for k,v in sorted(values.items())))


class FakeSystemd(module.Native):
    """Only systemd/Docker/Git are fake; journal/files/HMAC/flock are real."""
    def __init__(self, root, monkeypatch):
        self.old, self.new, self.deployment = (root/name for name in ('old','new','application'))
        for source in (self.old,self.new,self.deployment):
            (source/'scripts').mkdir(parents=True)
            (source/'scripts/sentinel_backup_maintenance.py').write_text('# frozen '+source.name+'\n')
        (self.new/'scripts/sentinel_maintenance_reader_handover.py').write_text('# unchanged installed tool\n')
        self.host_source = root/'host'
        (self.host_source/'scripts').mkdir(parents=True)
        (self.host_source/module.TOOL_PATH).write_bytes(Path(module.__file__).read_bytes())
        self.host_qualification = root/'host-qualification.json'
        dump(self.host_qualification,dict(source_files={module.TOOL_PATH:module.file_sha(self.host_source/module.TOOL_PATH)}))
        self.dropin = root/'user-unit.d'/module.DROPIN
        self.home = root
        self.root, self.pid, self.ticks = str(self.old), 123, 555
        self.calls, self.fail_start = [], False
        self.argv = ['/usr/bin/env','-i','HOME=/home/test','USER=test','LOGNAME=test',
            'LANG=C.UTF-8','PATH=/usr/sbin:/usr/bin:/sbin:/bin','WSL_DISTRO_NAME=Ubuntu',
            '/bin/bash','scripts/sentinel-backup-maintenance.sh','--loop']
        self.static = {str(root/'unit.service'):'original-unit-sha'}
        backup = root/'backup'; backup.mkdir()
        self.env = dict(ALPACA_BASE_URL='https://paper-api.alpaca.markets',
            SENTINEL_LOCAL_PAPER_MODE='OWNER_AUTHORIZED_FUNCTION_FIRST_V1',
            SENTINEL_LOCAL_PAPER_ACCOUNT_ID='PAFICTIONAL',SENTINEL_LOCAL_PAPER_BACKUP_POLICY='REQUIRED_V1',
            SENTINEL_PUBLICATION_RECEIPT_KEY=KEY,SENTINEL_POSTGRES_PASSWORD='private-test-password',
            SENTINEL_BACKUP_DIR=str(backup),SENTINEL_BACKUP_OUTAGE_POLICY='BOUNDED_30H_V1',
            SENTINEL_GIT_COMMIT=OLD,SENTINEL_RUNTIME_IMAGE_REF=OLD_IMAGE,
            SENTINEL_RUNTIME_IMAGE_DIGEST=OLD_IMAGE,SENTINEL_TEST_IMAGE_DIGEST=OLD_IMAGE,
            SENTINEL_LOCAL_PAPER_IMAGE=OLD_IMAGE,SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256='old-source',
            SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256='same-config',SENTINEL_IMAGE_SOURCE_REVISION=OLD)
        new = dict(self.env,**{k:IMAGE for k in ('SENTINEL_RUNTIME_IMAGE_REF',
            'SENTINEL_RUNTIME_IMAGE_DIGEST','SENTINEL_TEST_IMAGE_DIGEST','SENTINEL_LOCAL_PAPER_IMAGE')},
            SENTINEL_GIT_COMMIT=NEW,SENTINEL_IMAGE_SOURCE_REVISION=NEW,
            SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256='new-source',SENTINEL_BACKUP_SHARED_INTEGRITY='REQUIRED_V1')
        write_env(self.old/'.env',self.env); write_env(self.new/'.env',new); write_env(self.deployment/'.env',new)
        self.lock = root/'locks/pass.lock'
        self.lock.parent.mkdir(mode=0o700)
        self.lock.touch(mode=0o600)
        monkeypatch.setattr(module,'_lock_path',lambda values:self.lock)
        def git(source,*args):
            if args == ('rev-parse','HEAD'): return OLD if Path(source) == self.old else NEW
            if args[:2] == ('status','--porcelain'): return ''
            raise AssertionError(args)
        monkeypatch.setattr(module.qualification,'git',git)
        monkeypatch.setattr(module.environment,'selected_reader',lambda *args:(self.old,(self.old/'.env','sha')))
        self.qualification = root/'qualification.json'
        dump(self.qualification,dict(schema=module.qualification.OPERATIONAL_SCHEMA,
            source_scope=module.qualification.OPERATIONAL_SCOPE,commit=NEW,predecessor_commit=OLD,
            source_files={p:'f'*64 for p in ('scripts/sentinel_maintenance_reader_handover.py',
                'scripts/sentinel_backup_maintenance.py','scripts/sentinel_backup_shared_integrity.py',
                'scripts/sentinel_backup_integrity_report.py','sentinel/backup_maintenance_integrity.py')}))
        self.validations = []
        def validate(path,sha,source,commit,predecessor):
            self.validations.append((str(source),commit,predecessor))
            report = module.read_json(path)
            module.require(module.file_sha(path) == sha and report['commit'] == commit
                and predecessor == OLD,'QUALIFICATION_REPORT_CHANGED')
        monkeypatch.setattr(module.qualification,'validate_report',validate)
        self.receipt = root/'app-operation/receipt.json'
        dump(self.receipt,dict(stage='VERIFIED'))
        dump(self.receipt.parent/'request.json',dict(deployment=str(self.deployment),
            candidate=dict(source_identity=dict(source='new-source',shadow_config='same-config'))))
        self.pg = dict(container='pg-id',image='pg-image',started='unchanged',volume='sentinel_sentinel_pgdata',
            source='/private/pgdata',command=['postgres','-c','archive_mode=on'])
        self.witness = dict(git_commit=NEW,runtime_image=IMAGE,postgres=deepcopy(self.pg),system='1234567')
        backed = importlib.import_module('sentinel_backed_local_patch')
        monkeypatch.setattr(backed,'predecessor_witness',lambda *args,**kwargs:deepcopy(self.witness))
        self.loop_valid = True
        monkeypatch.setattr(module,'owns_loop_lock',lambda reader,path:self.loop_valid)
        selected = dict(schema='sentinel.native-maintenance-reader/1',deployment=str(self.deployment),
            source=str(self.old),commit=OLD,script_sha256=module.file_sha(self.old/'scripts/sentinel_backup_maintenance.py'),
            environment_sha256=module.file_sha(self.old/'.env'))
        self.host_selector = self.deployment.parent/module.environment.HOST_READER_SELECTION
        self.deployment_selector = self.deployment/module.environment.READER_SELECTION
        for path,binding in ((self.host_selector,self.deployment.parent),(self.deployment_selector,self.deployment)):
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(module.selection_raw(selected,binding,KEY))
        self.operation = module.Handover(root/'operation',self)

    def inspect_image(self, image):
        return dict(Id=image,Config=dict(Labels={'org.opencontainers.image.revision':
            NEW if image == IMAGE else OLD}))

    def host_tool(self,commit,path,sha):
        assert commit == NEW
        module.require(module.file_sha(path) == sha,'QUALIFICATION_REPORT_CHANGED')
        executable_sha = module.file_sha(self.host_source/module.TOOL_PATH)
        module.require(module.read_json(path)['source_files'][module.TOOL_PATH] == executable_sha,
            'READER_HOST_EXECUTABLE_UNQUALIFIED')
        return dict(source=str(self.host_source),commit='e'*40,executable_sha256=executable_sha,
            qualification=str(path),qualification_sha256=sha)

    def runtime_facts(self,image,*,require_healthy=True):
        assert image == IMAGE
        return dict(postgres=deepcopy(self.pg),system='1234567',
            application_containers=[dict(id='app-'+str(i),started='same') for i in range(6)])

    def unit(self):
        return dict(pid=self.pid,active='active' if self.pid else 'inactive',sub='running' if self.pid else 'dead',
            root=self.root,argv=list(self.argv),static=dict(self.static),
            stable=self.dropin.read_text() if self.dropin.exists() else None)

    def reader(self,deployment,root,*,required):
        if self.pid and self.root == root:
            return dict(pid=self.pid,start_ticks=self.ticks,uid=os.getuid(),gid=os.getgid(),
                groups=sorted(os.getgroups()),root=root)
        module.require(not required,'ENVIRONMENT_NATIVE_READER_UNAVAILABLE')
        return None

    def control(self,verb):
        self.calls.append(verb)
        if verb == 'stop':
            # The fake daemon refuses a stop unless the REAL target pass fence is held.
            with self.lock.open('r+') as stream:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.pid = 0
        elif verb == 'daemon-reload':
            self.root = (next(line.split('=',1)[1] for line in self.dropin.read_text().splitlines()
                if line.startswith('WorkingDirectory=')) if self.dropin.exists() else str(self.old))
        elif verb == 'start':
            if self.fail_start and self.root == str(self.new):
                raise DeliveryRefused('INJECTED_START_FAILURE')
            assert self.pid == 0
            self.pid = 124 if self.root == str(self.new) else 125
            self.ticks += 100

    def ready(self,request,root,*,previous=None):
        result = self.reader(request['deployment'],root,required=True)
        module.require(result != previous and self.loop_valid,'READER_START_NOT_READY')
        return result

    def prepare(self):
        return self.operation.prepare(deployment=self.deployment,source=self.new,image=IMAGE,
            qualification_path=self.qualification,qualification_sha256=module.file_sha(self.qualification),
            application_receipt=self.receipt,operation_id='qualified-test',
            host_qualification_path=self.host_qualification,
            host_qualification_sha256=module.file_sha(self.host_qualification))


@pytest.fixture
def lab(tmp_path,monkeypatch):
    return FakeSystemd(tmp_path,monkeypatch)


def test_success_selects_source_then_starts_immediate_normal_loop(lab):
    old_bytes = (lab.old/'.env').read_bytes()
    initial = lab.prepare()
    assert not lab.calls and initial['phase'] == 'PREPARED'
    assert initial['request']['host_tool']['source'] == str(lab.host_source)
    assert (lab.new/module.TOOL_PATH).read_bytes() != (lab.host_source/module.TOOL_PATH).read_bytes()
    result = lab.operation.resume()
    assert result['phase'] == 'VERIFIED' and result['reader']['pid'] == 124
    assert lab.calls == ['stop','daemon-reload','start']
    assert (lab.old/'.env').read_bytes() == old_bytes
    assert [v['phase'] for v in result['history']] == list(module.PHASES[:9])
    assert module.selection(lab.host_selector,lab.deployment.parent,KEY)['source'] == str(lab.new)
    assert module.selection(lab.deployment_selector,lab.deployment,KEY)['source'] == str(lab.new)
    assert lab.operation.resume()['reader'] == result['reader']
    with pytest.raises(DeliveryRefused,match='COMPLETED_ROLLBACK'):
        lab.operation.rollback()


def held_child(path,started,release):
    with open(path,'r+') as stream:
        fcntl.flock(stream.fileno(),fcntl.LOCK_EX)
        started.set(); release.wait(15)


def test_active_backup_child_prevents_stop_or_selection(lab):
    lab.prepare()
    context = multiprocessing.get_context('fork')
    started, release = context.Event(), context.Event()
    child = context.Process(target=held_child,args=(lab.lock,started,release))
    child.start()
    try:
        assert started.wait(3)
        with pytest.raises(DeliveryRefused,match='PASS_BUSY'): lab.operation.resume()
        assert lab.calls == [] and lab.pid == 123
        assert lab.operation.read()['phase'] == 'PREPARED'
        assert module.selection(lab.host_selector,lab.deployment.parent,KEY)['source'] == str(lab.old)
    finally:
        release.set(); child.join(3)
        if child.is_alive(): child.terminate(); child.join()
    assert child.exitcode == 0
    assert lab.operation.resume()['phase'] == 'VERIFIED'


@pytest.mark.parametrize('phase',module.PHASES[1:9])
def test_power_loss_after_each_forward_receipt_resumes_once(lab,monkeypatch,phase):
    lab.prepare()
    original = lab.operation.advance
    def advance(value,next_phase,**kwargs):
        original(value,next_phase,**kwargs)
        if next_phase == phase: raise PowerLoss()
    monkeypatch.setattr(lab.operation,'advance',advance)
    with pytest.raises(PowerLoss): lab.operation.resume()
    assert lab.operation.read()['phase'] == phase
    monkeypatch.setattr(lab.operation,'advance',original)
    assert lab.operation.resume()['phase'] == 'VERIFIED'
    assert lab.calls.count('stop') == 1 and lab.calls.count('start') == 1


@pytest.mark.parametrize('target',('dropin','host_selector','deployment_selector'))
def test_power_loss_after_replace_before_receipt_recovers_exact_bytes(lab,monkeypatch,target):
    lab.prepare()
    original = module.replace_exact
    fired = False
    def replace(path,old,new):
        nonlocal fired
        original(path,old,new)
        if Path(path) == getattr(lab,target) and not fired:
            fired = True
            raise PowerLoss()
    monkeypatch.setattr(module,'replace_exact',replace)
    with pytest.raises(PowerLoss): lab.operation.resume()
    monkeypatch.setattr(module,'replace_exact',original)
    assert lab.operation.resume()['phase'] == 'VERIFIED'
    assert lab.calls.count('stop') == 1 and lab.calls.count('start') == 1


@pytest.mark.parametrize('verb',('stop','start','daemon-reload'))
def test_power_loss_after_systemd_action_before_receipt_recovers(lab,monkeypatch,verb):
    lab.prepare()
    original = lab.control
    fired = False
    def control(action):
        nonlocal fired
        original(action)
        if action == verb and not fired:
            fired = True
            raise PowerLoss()
    monkeypatch.setattr(lab,'control',control)
    with pytest.raises(PowerLoss): lab.operation.resume()
    monkeypatch.setattr(lab,'control',original)
    assert lab.operation.resume()['phase'] == 'VERIFIED'
    assert lab.calls.count('stop') == 1 and lab.calls.count('start') == 1


def test_failed_start_restores_unchanged_predecessor_and_signed_selectors(lab):
    before = {p:p.read_bytes() for p in (lab.old/'.env',lab.host_selector,lab.deployment_selector)}
    lab.prepare(); lab.fail_start = True
    with pytest.raises(DeliveryRefused,match='INJECTED_START_FAILURE'): lab.operation.resume()
    assert lab.operation.read()['phase'] == 'ROLLED_BACK' and lab.pid == 125
    assert not lab.dropin.exists() and lab.root == str(lab.old)
    assert all(p.read_bytes() == raw for p,raw in before.items())
    assert lab.operation.resume()['phase'] == 'ROLLED_BACK'


def test_existing_stable_qualified_predecessor_dropin_is_restored(lab):
    lab.dropin.parent.mkdir(parents=True)
    old = module.render_dropin(str(lab.old),lab.argv)
    lab.dropin.write_text(old)
    lab.prepare(); lab.fail_start = True
    with pytest.raises(DeliveryRefused,match='INJECTED_START_FAILURE'): lab.operation.resume()
    assert lab.operation.read()['phase'] == 'ROLLED_BACK'
    assert lab.dropin.read_text() == old and lab.root == str(lab.old)


@pytest.mark.parametrize('phase',module.PHASES[9:])
def test_power_loss_after_each_rollback_receipt_resumes(lab,monkeypatch,phase):
    lab.prepare(); lab.fail_start = True
    original = lab.operation.advance
    def advance(value,next_phase,**kwargs):
        original(value,next_phase,**kwargs)
        if next_phase == phase: raise PowerLoss()
    monkeypatch.setattr(lab.operation,'advance',advance)
    with pytest.raises(PowerLoss): lab.operation.resume()
    monkeypatch.setattr(lab.operation,'advance',original)
    assert lab.operation.resume()['phase'] == 'ROLLED_BACK'
    assert lab.pid == 125 and not lab.dropin.exists()


@pytest.mark.parametrize('target',('dropin','host_selector','deployment_selector'))
def test_power_loss_after_rollback_replace_before_receipt_is_idempotent(lab,monkeypatch,target):
    lab.prepare(); lab.fail_start = True
    original = module.replace_exact
    fired = False
    def replace(path,old,new):
        nonlocal fired
        original(path,old,new)
        if (Path(path) == getattr(lab,target) and not fired
            and lab.operation.read()['phase'] == 'ROLLBACK_REQUESTED'):
            fired = True
            raise PowerLoss()
    monkeypatch.setattr(module,'replace_exact',replace)
    with pytest.raises(PowerLoss): lab.operation.resume()
    monkeypatch.setattr(module,'replace_exact',original)
    assert lab.operation.resume()['phase'] == 'ROLLED_BACK'
    assert lab.calls.count('stop') == 1 and lab.pid == 125


def test_failed_start_with_active_successor_pass_cannot_stop_it_for_rollback(lab,monkeypatch):
    lab.prepare()
    context = multiprocessing.get_context('fork')
    started, release = context.Event(), context.Event()
    child = context.Process(target=held_child,args=(lab.lock,started,release))
    original = lab.control
    def control(verb):
        original(verb)
        if verb == 'start' and lab.root == str(lab.new):
            child.start(); assert started.wait(3)
            raise DeliveryRefused('INJECTED_AFTER_PROCESS_START')
    monkeypatch.setattr(lab,'control',control)
    try:
        with pytest.raises(DeliveryRefused,match='PASS_BUSY'): lab.operation.resume()
        assert lab.calls.count('stop') == 1 and lab.pid == 124
        assert lab.operation.read()['phase'] == 'ROLLBACK_REQUESTED'
    finally:
        release.set()
        if child.pid:
            child.join(3)
            if child.is_alive(): child.terminate(); child.join()
    monkeypatch.setattr(lab,'control',original)
    assert lab.operation.resume()['phase'] == 'ROLLED_BACK'
    assert lab.calls.count('stop') == 2 and lab.pid == 125


@pytest.mark.parametrize('change,reason',[
    ('pid','CURRENT_PROCESS_CHANGED'),('ticks','CURRENT_PROCESS_CHANGED'),('root','UNIT_DRIFT'),
    ('unit','UNIT_DRIFT'),('env','ENV_POLICY_CHANGED'),('selector','SELECTOR_DRIFT'),
    ('journal','JOURNAL_SIGNATURE'),('pointer','RUNTIME_POINTER_CHANGED'),('qualification','QUALIFICATION_REPORT_CHANGED'),
    ('host_report','QUALIFICATION_REPORT_CHANGED'),('host_executable','HOST_EXECUTABLE_UNQUALIFIED')])
def test_drift_refuses_before_stop(lab,change,reason):
    lab.prepare()
    if change == 'pid': lab.pid += 1
    elif change == 'ticks': lab.ticks += 1
    elif change == 'root': lab.root = '/unknown/source'
    elif change == 'unit': lab.static['injected.conf'] = 'foreign'
    elif change == 'env':
        values = module.sentinel_env.load(lab.new/'.env'); values['SENTINEL_BACKUP_DIR'] += '-other'
        write_env(lab.new/'.env',values)
    elif change == 'selector': lab.host_selector.write_text('{}\n')
    elif change == 'journal':
        value = json.loads(lab.operation.path.read_text()); value['value']['request']['image'] = OLD_IMAGE
        dump(lab.operation.path,value)
    elif change == 'pointer':
        path = lab.new/'artifacts/sentinel/deployment/validated-runtime.env'
        path.parent.mkdir(parents=True); path.write_text('SENTINEL_RUNTIME_IMAGE_REF='+OLD_IMAGE+'\n')
    elif change == 'host_report': lab.host_qualification.write_text(lab.host_qualification.read_text()+' ')
    elif change == 'host_executable':
        path = lab.host_source/module.TOOL_PATH
        path.write_text(path.read_text()+'# changed after prepare\n')
    else: lab.qualification.write_text(lab.qualification.read_text()+' ')
    with pytest.raises(DeliveryRefused,match=reason): lab.operation.resume()
    assert lab.calls == []


@pytest.mark.parametrize('change,reason',[
    ('signature','SELECTION_SIGNATURE'),('selectors_disagree','SELECTORS_DISAGREE'),
    ('policy','ENV_POLICY_CHANGED'),('extra_env','ENV_POLICY_CHANGED'),('image','IMAGE_REVISION_CHANGED'),
    ('app_stage','VERIFIED_APPLICATION_REQUIRED'),('app_image','VERIFIED_APPLICATION_REQUIRED'),
    ('app_source','APPLICATION_SOURCE_IDENTITY_CHANGED'),('qualification_scope','QUALIFICATION_SCOPE_REQUIRED'),
    ('qualification_inputs','QUALIFICATION_INPUTS_MISSING'),('qualification_commit','QUALIFICATION_REPORT_CHANGED'),
    ('head','RUNTIME_CHANGED'),
    ('loop','CURRENT_OWNER_UNPROVEN')])
def test_prepare_authenticates_policy_runtime_qualification_and_both_selectors(lab,monkeypatch,change,reason):
    if change in {'signature','selectors_disagree'}:
        value = json.loads(lab.host_selector.read_text())
        if change == 'signature': value['signature'] = '0'*64
        else:
            value['value']['commit'] = 'e'*40
            value['signature'] = module.environment.reader_signature(value['value'],KEY)
        dump(lab.host_selector,value)
    elif change in {'policy','extra_env'}:
        values = module.sentinel_env.load(lab.new/'.env')
        values['SENTINEL_BACKUP_OUTAGE_POLICY' if change == 'policy' else 'SENTINEL_UNREVIEWED'] = 'changed'
        write_env(lab.new/'.env',values)
    elif change == 'image':
        original = lab.inspect_image
        monkeypatch.setattr(lab,'inspect_image',lambda image:dict(original(image),
            Config=dict(Labels={'org.opencontainers.image.revision':OLD})))
    elif change == 'app_stage': dump(lab.receipt,dict(stage='APPLICATIONS_STARTED'))
    elif change == 'app_image': lab.witness['runtime_image'] = OLD_IMAGE
    elif change == 'app_source':
        value = module.read_json(lab.receipt.parent/'request.json')
        value['candidate']['source_identity']['source'] = 'different'
        dump(lab.receipt.parent/'request.json',value)
    elif change == 'head':
        original = module.qualification.git
        monkeypatch.setattr(module.qualification,'git',lambda source,*args:
            'e'*40 if Path(source) == lab.new and args == ('rev-parse','HEAD') else original(source,*args))
    elif change.startswith('qualification'):
        value = module.read_json(lab.qualification)
        if change == 'qualification_scope': value['source_scope'] = 'narrower'
        elif change == 'qualification_commit': value['commit'] = OLD
        else: del value['source_files']['scripts/sentinel_backup_shared_integrity.py']
        dump(lab.qualification,value)
    else: lab.loop_valid = False
    with pytest.raises(DeliveryRefused,match=reason): lab.prepare()
    assert lab.calls == [] and not lab.operation.path.exists()


def test_removed_hmac_and_pid_guards_are_executed_falsifiers(lab,monkeypatch):
    lab.prepare()
    lab.ticks += 1
    with pytest.raises(DeliveryRefused,match='CURRENT_PROCESS_CHANGED'): lab.operation.resume()
    # Removing just the exact PID-incarnation observation admits the changed daemon.
    original = lab.reader
    expected = lab.operation.read()['request']['old_reader']
    def broken_reader(deployment,root,*,required):
        result = original(deployment,root,required=required)
        return expected if result and root == str(lab.old) else result
    monkeypatch.setattr(lab,'reader',broken_reader)
    assert lab.operation.resume()['phase'] == 'VERIFIED'
    value = json.loads(lab.operation.path.read_text()); value['signature'] = '0'*64
    dump(lab.operation.path,value)
    with pytest.raises(DeliveryRefused,match='JOURNAL_SIGNATURE'): lab.operation.read()
    monkeypatch.setattr(module.hmac,'compare_digest',lambda *args:True)
    assert lab.operation.read()['phase'] == 'VERIFIED'


def test_removed_pass_fence_is_executed_falsifier(lab,monkeypatch):
    lab.prepare()
    real_fence = module.pass_fence
    @contextmanager
    def broken_fence(path,seconds):
        if Path(path) == lab.lock: yield
        else:
            with real_fence(path,seconds): yield
    monkeypatch.setattr(module,'pass_fence',broken_fence)
    # The service boundary asserts the actual independent descriptor is blocked.
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        lab.operation.resume()
    assert lab.pid == 123 and lab.operation.read()['phase'] == 'STOP_REQUESTED'


def test_terminal_success_cannot_have_resigned_rollback_history(lab):
    lab.prepare(); value = lab.operation.resume()
    value['history'].append(dict(phase='ROLLBACK_REQUESTED',previous=module.digest(value['history'][-1])))
    value['phase'] = 'ROLLBACK_REQUESTED'
    lab.operation.write(value)
    with pytest.raises(DeliveryRefused,match='JOURNAL_TRANSITION'): lab.operation.read()


def test_unknown_resigned_host_provenance_member_refuses(lab):
    value = lab.prepare()
    value['request']['host_tool']['unchecked_authority'] = True
    value['history'][0]['previous'] = module.digest(value['request'])
    lab.operation.write(value)
    with pytest.raises(DeliveryRefused,match='JOURNAL_SIGNATURE'): lab.operation.read()


def test_unknown_successor_incarnation_cannot_be_stopped_for_rollback(lab,monkeypatch):
    lab.prepare()
    original = lab.operation.advance
    def advance(value,phase,**kwargs):
        original(value,phase,**kwargs)
        if phase == 'STARTED':
            lab.pid += 1; lab.ticks += 1
    monkeypatch.setattr(lab.operation,'advance',advance)
    with pytest.raises(DeliveryRefused,match='ROLLBACK_PROCESS_CHANGED'): lab.operation.resume()
    assert lab.calls.count('stop') == 1 and lab.pid == 125
    assert lab.operation.read()['phase'] == 'ROLLBACK_REQUESTED'
    assert module.selection(lab.host_selector,lab.deployment.parent,KEY)['source'] == str(lab.new)


@pytest.mark.parametrize('change,reason',[
    ('command','UNIT_COMMAND_INVALID'),('environment','UNIT_POLICY_CHANGED'),
    ('kill_mode','UNIT_POLICY_CHANGED'),('restart','UNIT_POLICY_CHANGED'),
    ('fragment','UNIT_OWNER_CHANGED'),('dropin','UNIT_DROPINS_INVALID')])
def test_native_unit_refuses_arbitrary_command_environment_or_owner(tmp_path,change,reason):
    native = module.Native.__new__(module.Native)
    native.home = tmp_path
    native.dropin = tmp_path/'.config/systemd/user'/f'{module.UNIT}.d'/module.DROPIN
    fragment = tmp_path/'.config/systemd/user'/module.UNIT
    fragment.parent.mkdir(parents=True); fragment.write_text('[Service]\n')
    user = pwd.getpwuid(os.getuid()).pw_name
    argv = '/usr/bin/env -i HOME='+str(tmp_path)+' USER='+user+' LOGNAME='+user+\
        ' LANG=C.UTF-8 PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash scripts/sentinel-backup-maintenance.sh --loop'
    fields = dict(MainPID='123',ActiveState='active',SubState='running',WorkingDirectory=str(tmp_path/'old'),
        ExecStart='{ path=/usr/bin/env ; argv[]='+argv+' ; ignore_errors=no ; }',
        Restart='on-failure',KillMode='control-group',FragmentPath=str(fragment),DropInPaths='')
    if change == 'command': fields['ExecStart'] = fields['ExecStart'].replace('--loop','--loop arbitrary')
    elif change == 'environment': fields['ExecStart'] = fields['ExecStart'].replace(' -i ',' -i LD_PRELOAD=/foreign ')
    elif change == 'kill_mode': fields['KillMode'] = 'process'
    elif change == 'restart': fields['Restart'] = 'always'
    elif change == 'fragment': fields['FragmentPath'] += '.foreign'
    else: fields['DropInPaths'] = '/foreign/override.conf'
    native.run = lambda *args,**kwargs:'\n'.join(k+'='+v for k,v in fields.items())
    with pytest.raises(DeliveryRefused,match=reason): native.unit()


def test_loop_proof_requires_actual_exclusive_flock_not_open_inode(tmp_path):
    # Execute the production fdinfo reader in a real child, independently of fake systemd.
    context = multiprocessing.get_context('fork')
    path = tmp_path/'loop'; path.touch()
    started, release = context.Event(),context.Event()
    child = context.Process(target=held_child,args=(path,started,release)); child.start()
    try:
        assert started.wait(3)
        ticks = int((Path('/proc')/str(child.pid)/'stat').read_bytes().rpartition(b')')[2].split()[19])
        reader = dict(pid=child.pid,start_ticks=ticks)
        assert module.owns_loop_lock(reader,path)
        assert not module.owns_loop_lock(dict(reader,start_ticks=ticks+1),path)
        with path.open('r+') as unlocked:
            own_ticks = int((Path('/proc')/str(os.getpid())/'stat').read_bytes().rpartition(b')')[2].split()[19])
            assert not module.owns_loop_lock(dict(pid=os.getpid(),start_ticks=own_ticks),path)
    finally:
        release.set(); child.join(3)
        if child.is_alive(): child.terminate(); child.join()
    assert child.exitcode == 0


def test_start_readiness_wait_is_bounded_with_no_probe_storm(monkeypatch):
    native = module.Native.__new__(module.Native)
    elapsed, calls = [0.0], []
    monkeypatch.setattr(module.time,'monotonic',lambda:elapsed[0])
    monkeypatch.setattr(module.time,'sleep',lambda seconds:elapsed.__setitem__(0,elapsed[0]+seconds))
    def unit():
        calls.append(elapsed[0])
        return dict(pid=0,active='inactive',sub='dead',root='/fictional')
    native.unit = unit
    native.reader = lambda *args,**kwargs:None
    with pytest.raises(DeliveryRefused,match='START_NOT_READY'):
        native.ready(dict(deployment='/fictional',pass_lock='/fictional/pass.lock'),'/fictional')
    assert elapsed[0] == 15 and len(calls) <= 20


def resign_old_environment(lab):
    for path in (lab.host_selector,lab.deployment_selector):
        record = module.read_json(path)
        record['value']['environment_sha256'] = module.file_sha(lab.old/'.env')
        record['signature'] = module.environment.reader_signature(record['value'],KEY)
        dump(path,record)


@pytest.mark.parametrize('omit',('maintenance','all','application'))
def test_native_assets_uses_literal_paper_default_with_legacy_omitted_endpoint(lab,omit):
    selected = (lab.old,lab.new) if omit == 'maintenance' else (
        (lab.old,lab.new,lab.deployment) if omit == 'all' else (lab.deployment,))
    for source in selected:
        values = module.sentinel_env.load(source/'.env')
        del values['ALPACA_BASE_URL']; write_env(source/'.env',values)
    resign_old_environment(lab)
    # prepare executes the real Native.assets method, not just the pure policy helper.
    value = lab.prepare()
    assert value['phase'] == 'PREPARED' and lab.calls == []
    assert lab.operation.resume()['phase'] == 'VERIFIED'


@pytest.mark.parametrize('endpoint',('', 'https://api.alpaca.markets',
    'https://paper-api.alpaca.markets/', ' https://paper-api.alpaca.markets', 'https://foreign.invalid'))
def test_explicit_noncanonical_endpoint_remains_forbidden(lab,endpoint):
    values = module.sentinel_env.load(lab.deployment/'.env')
    # Quote the leading whitespace case so literal ingestion retains it.
    if endpoint.startswith(' '):
        values['ALPACA_BASE_URL'] = '"'+endpoint+'"'
    else: values['ALPACA_BASE_URL'] = endpoint
    write_env(lab.deployment/'.env',values)
    with pytest.raises(DeliveryRefused,match='PAPER_POLICY_CHANGED'): lab.prepare()
    assert lab.calls == [] and not lab.operation.path.exists()


class RealHostPackage:
    """Private Git history and the production v2 qualification validator."""
    def __init__(self,tmp_path,*,delta=module.HOST_DELTA,command=('pytest','private-fixture')):
        self.source = tmp_path/'host-source'; self.source.mkdir()
        self.report = tmp_path/'host-report.json'; self.log = tmp_path/'host-tests.log'
        self.git('init','--initial-branch=codex/private-host-test')
        self.git('config','user.name','Private fixture')
        self.git('config','user.email','fixture@example.invalid')
        contents = {name:'# baseline '+name+'\n' for name in delta}
        contents.update({'sentinel/anchor.py':'# immutable runtime\n',
            'sentinel/other.py':'# another immutable runtime input\n',
            'scripts/sentinel_local_delivery/__init__.py':'# immutable imported helper\n',
            'scripts/sentinel_backed_local_patch.py':'# immutable backed helper\n'})
        for name,text in contents.items():
            path = self.source/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(text)
        self.commit('private application baseline')
        self.base = self.git('rev-parse','HEAD')
        for name in delta:
            path = self.source/name; path.write_text(path.read_text()+'# reviewed host correction\n')
        self.commit('private host correction')
        self.log.write_text('1 passed in 0.01s\n')
        self.seal(command)

    def git(self,*args):
        result = subprocess.run(['git','-c','commit.gpgsign=false','-c','core.autocrlf=false',*args],
            cwd=self.source,check=True,capture_output=True,text=True,
            env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG'}} | {'GIT_CONFIG_GLOBAL':'/dev/null'})
        return result.stdout.strip()

    def commit(self,message):
        self.git('add','-A'); self.git('commit','-m',message)

    def seal(self,command=('pytest','private-fixture')):
        commit = self.git('rev-parse','HEAD')
        dump(self.report,dict(schema=module.qualification.OPERATIONAL_SCHEMA,
            source_scope=module.qualification.OPERATIONAL_SCOPE,commit=commit,predecessor_commit=self.base,
            at='2031-01-01T00:00:00+00:00',source_files=module.qualification.source_files(self.source,
                scope=module.qualification.OPERATIONAL_SCOPE,predecessor_commit=self.base),
            source_files_unchanged=True,final=True,results=[dict(name='private-fixture-result',
                exit_code=0,passed=1,skipped=0,deselected=0,log=str(self.log),
                log_sha256=module.qualification.sha256_file(self.log),command=list(command))]))
        self.sha = module.qualification.sha256_file(self.report)

    def validate(self,**kwargs):
        return module.qualified_host(kwargs.get('executable',self.source/module.TOOL_PATH),
            self.report,kwargs.get('sha',self.sha),kwargs.get('base',self.base))


@pytest.fixture
def real_host(tmp_path):
    return RealHostPackage(tmp_path)


def test_real_host_git_and_complete_qualification_bind_independent_program(real_host):
    result = real_host.validate()
    assert result == dict(source=str(real_host.source),commit=real_host.git('rev-parse','HEAD'),
        executable_sha256=module.qualification.sha256_file(real_host.source/module.TOOL_PATH),
        qualification=str(real_host.report),qualification_sha256=real_host.sha)
    assert result['commit'] != real_host.base


def test_lineage_host_qualifies_exact_six_file_delta_with_all_affected_tests(tmp_path):
    package = RealHostPackage(tmp_path,delta=LINEAGE_DELTA,command=('pytest',*LINEAGE_TESTS))
    result = package.validate()
    assert result['commit'] == package.git('rev-parse','HEAD')
    assert result['qualification_sha256'] == package.sha
    assert result['executable_sha256'] == module.file_sha(package.source/module.TOOL_PATH)
    assert module.read_json(package.report)['predecessor_commit'] == package.base


@pytest.mark.parametrize('missing_test',LINEAGE_TESTS)
def test_lineage_host_requires_all_complete_test_modules(tmp_path,monkeypatch,missing_test):
    covered_tests = tuple(path for path in LINEAGE_TESTS if path != missing_test)
    package = RealHostPackage(tmp_path,delta=LINEAGE_DELTA,
        command=('pytest',*covered_tests,missing_test+'::one_case'))
    with pytest.raises(DeliveryRefused,match='HOST_LINEAGE_TESTS_MISSING'):
        package.validate()
    require = module.require

    def without_test_coverage_guard(condition,reason):
        if reason != 'READER_HOST_LINEAGE_TESTS_MISSING':
            require(condition,reason)

    monkeypatch.setattr(module,'require',without_test_coverage_guard)
    assert package.validate()['commit'] == package.git('rev-parse','HEAD')


@pytest.mark.parametrize('delta',[
    LINEAGE_DELTA | {'sentinel/anchor.py'},
    LINEAGE_DELTA | {'docs/operation-owned-integrity-work.md'},
    LINEAGE_DELTA - {'tests/scripts/test_sentinel_backed_local_patch.py'},
],ids=['extra-runtime','extra-legacy','missing-backed-test'])
def test_lineage_host_refuses_inexact_delta(tmp_path,delta):
    package = RealHostPackage(tmp_path,delta=delta,command=('pytest',*LINEAGE_TESTS))
    with pytest.raises(DeliveryRefused,match='HOST_DELTA_REFUSED'):
        package.validate()


@pytest.mark.parametrize('mutation,reason',[
    ('dirty','QUALIFICATION_SOURCE_NOT_CLEAN'),('unknown_runtime','HOST_DELTA_REFUSED'),
    ('unknown_helper','HOST_DELTA_REFUSED'),('added_file','HOST_DELTA_REFUSED'),
    ('deleted_file','HOST_DELTA_REFUSED'),('report','QUALIFICATION_REPORT_CHANGED'),
    ('log','QUALIFICATION_LOG_CHANGED'),('self_map','QUALIFIED_SOURCE_BYTES_CHANGED'),
    ('substituted_executable','HOST_EXECUTABLE_SUBSTITUTED'),('foreign_base','QUALIFICATION_RUNTIME_CHANGED')])
def test_real_host_unknown_dirty_tampered_or_substituted_package_refuses(real_host,mutation,reason):
    package = real_host
    kwargs = {}
    if mutation == 'dirty':
        path = package.source/module.TOOL_PATH; path.write_text(path.read_text()+'# dirty\n')
    elif mutation in {'unknown_runtime','unknown_helper','added_file','deleted_file'}:
        if mutation == 'unknown_runtime': path = package.source/'sentinel/anchor.py'
        elif mutation == 'unknown_helper': path = package.source/'scripts/sentinel_local_delivery/__init__.py'
        elif mutation == 'added_file': path = package.source/'scripts/unreviewed.py'
        else: path = package.source/'sentinel/anchor.py'
        if mutation == 'deleted_file': path.unlink()
        else: path.write_text('# unreviewed host delta\n')
        package.commit('private negative mutation'); package.seal()
    elif mutation == 'report': package.report.write_text(package.report.read_text()+' ')
    elif mutation == 'log': package.log.write_text('1 passed in 0.02s\n')
    elif mutation == 'self_map':
        report = module.read_json(package.report); report['source_files'][module.TOOL_PATH] = '0'*64
        dump(package.report,report); package.sha = module.qualification.sha256_file(package.report)
    elif mutation == 'substituted_executable':
        path = package.source/'scripts/substituted.py'; path.write_text('# not the qualified executable\n')
        kwargs['executable'] = path
    else: kwargs['base'] = 'f'*40
    with pytest.raises(DeliveryRefused,match=reason): package.validate(**kwargs)


def test_real_host_delta_guard_removal_is_an_executed_falsifier(real_host,monkeypatch):
    path = real_host.source/'sentinel/anchor.py'
    path.write_text('# changed financial runtime must not borrow host authority\n')
    real_host.commit('private runtime falsifier'); real_host.seal()
    with pytest.raises(DeliveryRefused,match='HOST_DELTA_REFUSED'): real_host.validate()
    real_git = module.qualification.git
    def without_delta_guard(source,*args):
        if args[:3] == ('diff','--name-status','--no-renames'):
            return '\n'.join('M\t'+name for name in sorted(module.HOST_DELTA))
        return real_git(source,*args)
    monkeypatch.setattr(module.qualification,'git',without_delta_guard)
    assert real_host.validate()['commit'] == real_host.git('rev-parse','HEAD')


def test_same_candidate_host_uses_complete_app_report_without_host_only_delta(real_host):
    report = module.read_json(real_host.report)
    report['results'][0]['command'] = ['pytest',module.TOOL_TEST]
    dump(real_host.report,report); real_host.sha = module.qualification.sha256_file(real_host.report)
    commit = real_host.git('rev-parse','HEAD')
    assert real_host.validate(base=commit)['commit'] == commit


def test_same_candidate_host_still_requires_executed_direct_test_coverage(real_host):
    with pytest.raises(DeliveryRefused,match='APPLICATION_TOOL_TEST_MISSING'):
        real_host.validate(base=real_host.git('rev-parse','HEAD'))


@pytest.mark.parametrize('wrong_app_report',(False,True))
def test_native_assets_same_candidate_route_requires_exact_completed_app_report(lab,monkeypatch,wrong_app_report):
    (lab.new/module.TOOL_PATH).write_bytes((lab.host_source/module.TOOL_PATH).read_bytes())
    report = module.read_json(lab.qualification)
    report['source_files'][module.TOOL_PATH] = module.file_sha(lab.host_source/module.TOOL_PATH)
    dump(lab.qualification,report)
    lab.host_qualification = lab.qualification
    original = lab.host_tool
    monkeypatch.setattr(lab,'host_tool',lambda *args:dict(original(*args),commit=NEW))
    request = module.read_json(lab.receipt.parent/'request.json')
    request['qualification'] = dict(report_sha256='0'*64 if wrong_app_report else module.file_sha(lab.qualification))
    dump(lab.receipt.parent/'request.json',request)
    if wrong_app_report:
        with pytest.raises(DeliveryRefused,match='APPLICATION_TOOL_REPORT_CHANGED'): lab.prepare()
        assert lab.calls == []
    else:
        assert lab.prepare()['request']['host_tool']['commit'] == NEW
        assert lab.operation.resume()['phase'] == 'VERIFIED'


@pytest.mark.parametrize('seconds',(-1,3661,True))
def test_wait_is_bounded_before_lock(tmp_path,seconds):
    with pytest.raises(DeliveryRefused,match='WAIT_INVALID'):
        with module.pass_fence(tmp_path/'pass.lock',seconds): pass
