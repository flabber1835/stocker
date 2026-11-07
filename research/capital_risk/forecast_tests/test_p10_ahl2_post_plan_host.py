"""Actual flattened entrypoint and source-pinned host APIs, with canonical APIs stubbed."""
import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import system_campaign_p10_ahl2_post_plan as context
import system_campaign_p10_ahl2_post_plan_job as job
from system_campaign_p10_ahl2_contract import sha


def request():
    return context.host_expected_request(HERE.parents[1]/'.github/workflows'/context.WORKFLOW)


def test_full_new_source_closure_preserves_all450_and_original_economic_scope():
    value,old = request(),context.prior_request()
    assert all(value['sources'][n] == h for n,h in old['sources'].items())
    assert len(value['sources']) == 461
    assert {k for k in value if value.get(k) != old.get(k)} == {
        'schema','workflow','workflow_sha256','sources','budgets','request_context','retained_qualification'}
    assert value['source_physical_files'] == 516 and value['source_canonical_files'] == 224
    assert value['native_horizon'] == 21 and value['expected_successor_input_sha256'] == old['expected_successor_input_sha256']
    assert value['retained_qualification']['new_full_canonical_restores'] == 20


@pytest.fixture
def flat(tmp_path,monkeypatch):
    value = request();driver = tmp_path/'driver';driver.mkdir()
    for name in value['sources']:shutil.copyfile(HERE/name,driver/name)
    raw = (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    (driver/context.REQUEST).write_bytes(raw)
    monkeypatch.setattr(context,'HERE',driver)
    return driver,value


def test_full_worker_request_api_has_no_workflow_or_repo_layout_dependency(flat,monkeypatch):
    driver,value = flat
    original = Path.read_bytes
    def read(path):
        assert path.suffix != '.yml'
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',read)
    assert context.worker_expected_request() == value
    assert context.worker_raw_request(driver/context.REQUEST) == value


@pytest.mark.parametrize('bad',['source','retained_descriptor','raw_copy','request_model','missing_provenance'])
def test_flat_raw_request_source_and_cached_descriptor_mutations_refuse(flat,tmp_path,bad):
    driver,value = flat
    out = tmp_path/'request.json';shutil.copyfile(driver/context.REQUEST,out)
    if bad == 'source':(driver/'system_campaign_p10_ahl2_post_plan_observe.py').write_bytes(b'wrong')
    elif bad == 'retained_descriptor':(driver/context.RETAINED).write_bytes(b'{}')
    elif bad == 'raw_copy':out.write_bytes(json.dumps(value).encode())
    else:
        value = deepcopy(value)
        if bad == 'request_model':value['native_horizon'] = 1
        else:value.pop('retained_qualification')
        raw = json.dumps(value).encode();out.write_bytes(raw);(driver/context.REQUEST).write_bytes(raw)
    with pytest.raises(ValueError):context.worker_raw_request(out)


def test_host_actual_workflow_and_mechanical_nested_budgets():
    raw = (HERE.parents[1]/'.github/workflows'/context.WORKFLOW).read_bytes()
    assert sha(raw) == context.WORKFLOW_SHA
    value = context.workflow_budget_valid(raw)
    assert value['internal_envelope_seconds'] == 285*60
    assert value['outer_headroom_minutes'] == 18 and value['orchestration_headroom_minutes'] == 15
    assert context.BUDGET['admission'] == 1800 and context.BUDGET['discovery'] == 6300
    assert raw.index(b'ephemeral_runner_capacity.py') < raw.index(b'/stage.py')


@pytest.mark.parametrize('old,new',[(b'timeout-minutes: 355',b'timeout-minutes: 337'),
    (b'timeout-minutes: 300',b'timeout-minutes: 285'),(b'timeout-minutes: 12',b'timeout-minutes: 2')])
def test_actual_workflow_budget_loss_refuses(old,new):
    raw = (HERE.parents[1]/'.github/workflows'/context.WORKFLOW).read_bytes()
    with pytest.raises(ValueError):context.workflow_budget_valid(raw.replace(old,new))


def test_new_host_main_and_unknown_lifecycle_are_exact_old_AST_with_new_bindings(monkeypatch):
    import builtins
    import system_campaign_p10_ahl2_job as old
    captured = [];compiler = builtins.compile
    def compile_(source,filename,*a,**kw):
        if filename == '<p10-post-plan-same-stopped-host-lifecycle>':
            captured.extend(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name == 'main')
        return compiler(source,filename,*a,**kw)
    monkeypatch.setattr(builtins,'compile',compile_)
    scope = job.job_namespace()
    raw = context.prior_request()['sources']['system_campaign_p10_ahl2_job.py']
    assert sha((HERE/'system_campaign_p10_ahl2_job.py').read_bytes()) == raw
    fn, = [n for n in ast.parse((HERE/'system_campaign_p10_ahl2_job.py').read_bytes()).body
            if isinstance(n,ast.FunctionDef) and n.name == 'main']
    assert ast.dump(captured[0],include_attributes=False) == ast.dump(fn,include_attributes=False)
    assert scope['BUDGET'] is context.BUDGET and scope['admit_own'] is job.admit_capsule
    assert scope['qualification_valid'] is job.qualification_valid and scope['retain_qualification'] is job.retain_qualification
    assert scope['entrypoint'] is context.entrypoint and old.entrypoint is not context.entrypoint
    calls = [n for n in ast.walk(fn) if isinstance(n,ast.Call)]
    one = lambda name:next(n.lineno for n in calls if ast.unparse(n.func) == name)
    qseal, = [n for n in calls if ast.unparse(n.func) == 'preserve' and any(k.arg == 'qualification' and ast.literal_eval(k.value) is True for k in n.keywords)]
    worker, = [n for n in calls if ast.unparse(n.func) == 'worker_command' and ast.literal_eval(n.args[1]) == 'worker']
    assert one('qualify_export') < one('admit_strict') < one('admit_own')
    assert qseal.lineno < one('qualified_for_suffix') < worker.lineno
    assert 'unknown_preservation(active_role, known)' in ast.unparse(fn)


@pytest.mark.parametrize('role',['qualify','worker','review'])
def test_new_exact_worker_mounts_composite_capsule_and_cli_without_new_mount(tmp_path,monkeypatch,role):
    monkeypatch.setattr(os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(os,'getgid',lambda:1001,raising=False)
    capsule = tmp_path/'capsule';(capsule/'own1').mkdir(parents=True);(capsule/'capsule.json').write_bytes(b'{}')
    value = job.worker_command('SYNTHETIC',role,'/source','/frozen','/out','/old',capsule/'own1',evidence='/evidence')
    assert value[value.index('-B'):] == context.entrypoint(role)
    assert f'type=bind,source={capsule},target=/previous,readonly' in value
    assert not any('target=/retained' in x for x in value)
    assert ('type=bind,source=/evidence,target=/evidence,readonly' in value) == (role == 'review')
    assert value[value.index('--network')+1] == 'none'
    assert value[value.index('--memory')+1] == value[value.index('--memory-swap')+1] == '8g'


@pytest.mark.parametrize('bad',['root','duplicate','old_entrypoint','running'])
def test_new_actual_inspection_rejects_root_duplicate_old_Cmd_and_running(bad):
    from test_p10_ahl2_context import inspect_record
    value = inspect_record();value['Config']['Cmd'] = context.entrypoint('worker')
    if bad == 'root':value['Config']['User'] = '0:0'
    elif bad == 'duplicate':value['Mounts'].append(deepcopy(value['Mounts'][0]))
    elif bad == 'old_entrypoint':value['Config']['Cmd'][2] = '/driver/system_campaign_p10_ahl2_context_run.py'
    else:value['State']['Running'] = True
    with pytest.raises(ValueError):job.stopped_record(value,dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None),'worker','123')


def test_complete_retained_qualification_bytes_are_copied_only_as_proof(tmp_path):
    source,target = tmp_path/'source',tmp_path/'retained'
    names = ['retained-parent-evidence/fast/discovery-events.jsonl','retained-parent-evidence/old-refusal/actual-runtime-path/failed.json.gz',
             'fast/diagnostic-book/pre-event/2019-02-15.json.gz','qualification-summary.json']
    for name in names:
        path = source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(name.encode())
    job.retain_qualification(source,target)
    assert {p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()} == set(names)
    assert all((source/name).read_bytes() == (target/name).read_bytes() for name in names)


def test_real_synthetic_marker_binds_new_complete_request_without_financial_data(tmp_path,monkeypatch):
    from system_campaign_p10_ahl2_export import qualify_export
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    path = tmp_path/'request.json';path.write_bytes((json.dumps(request(),sort_keys=True,indent=2)+'\n').encode())
    value = qualify_export(tmp_path/'marker',path)
    assert value['status'] == 'P10_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED'
    assert value['synthetic_marker_only'] is True and value['market_or_financial_state_processed'] is False


def test_actual_flat_worker_entrypoint_reaches_only_declared_existing_API(flat,tmp_path):
    driver,value = flat
    out = tmp_path/'out';out.mkdir()
    shutil.copyfile(driver/context.REQUEST,out/'request.json')
    shutil.copyfile(driver/'system-campaign-p10-ahl2-predecessor-001.json',out/'spec.json')
    capsule = tmp_path/'capsule';(capsule/'own1').mkdir(parents=True);(capsule/'retained-qualification').mkdir()
    (capsule/'own1/source-bindings.json').write_bytes(b'{}')
    script = r'''
import importlib.abc,json,sys
from pathlib import Path
from types import SimpleNamespace,ModuleType
driver,out,capsule=map(Path,sys.argv[1:]);sys.path.insert(0,str(driver))
class Fence(importlib.abc.MetaPathFinder):
 def find_spec(self,name,path=None,target=None):
  if name.startswith(('sentinel','stock_strategy_shared','research.pooled_','numpy','pandas')):raise AssertionError('CANONICAL_IMPORT_FORBIDDEN:'+name)
sys.meta_path.insert(0,Fence())
import system_campaign_p10_ahl2_post_plan_run as entry
import system_campaign_p10_ahl2_post_plan_gate as gate
calls=[];core=ModuleType('full_system_core');core.hosted=lambda:calls.append('HOSTED');sys.modules['full_system_core']=core
real=Path
entry.Path=lambda p:{'/out':out,'/old':out.parent/'old','/previous':capsule}.get(str(p),real(p))
entry.validate_capsule=lambda p,s:calls.append(('CAPSULE',str(p))) or (p/'own1',p/'retained-qualification')
entry.physical_tree=lambda *a:calls.append('PHYSICAL_SOURCE_API_STUBBED')
gate.qualify=lambda root,previous,output,spec,**kw:calls.append(('QUALIFY',previous.name,kw['retained'].name)) or {'stub':True}
assert entry.main(SimpleNamespace(mode='qualify',spec=out/'spec.json',request=out/'request.json'))=={'stub':True}
assert calls==['HOSTED',('CAPSULE',str(capsule)),'PHYSICAL_SOURCE_API_STUBBED',('QUALIFY','own1','retained-qualification')]
assert not any(n.startswith(('sentinel','stock_strategy_shared','research.pooled_')) for n in sys.modules)
print(json.dumps({'actual_entrypoint_passed':True,'canonical_execution':False}))
'''
    value = subprocess.run([sys.executable,'-B','-c',script,str(driver),str(out),str(capsule)],capture_output=True,text=True,check=True)
    assert json.loads(value.stdout)['actual_entrypoint_passed'] is True
