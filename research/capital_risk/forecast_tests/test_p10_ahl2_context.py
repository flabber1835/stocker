"""Actual flattened metadata/entrypoint tests; existing canonical APIs are stubbed."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path,PurePosixPath
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import system_campaign_p10_ahl2_context as context
import system_campaign_p10_ahl2_context_job as job
from system_campaign_p10_ahl2_contract import need

def request():return context.host_expected_request(HERE.parents[1]/'.github/workflows'/context.WORKFLOW)

def test_exact_old_actual_function_reproduces_driver_indexerror():
    old=__import__('system_campaign_p10_ahl2_job')
    raw=context.frozen_body('system_campaign_p10_ahl2_job.py')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='expected_request']
    namespace=dict(vars(old),HERE=PurePosixPath('/driver'),sha256_file=lambda p:context.prior_request()['sources'].get(p.name,'c'*64))
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<actual-old-driver-context>','exec'),namespace)
    with pytest.raises(IndexError):namespace['expected_request']()

def test_new_model_changes_only_declared_transport_and_keeps_all445():
    new=request();old=context.prior_request()
    changed={k for k in set(new)|set(old) if new.get(k)!=old.get(k)}
    assert changed=={'schema','workflow','workflow_sha256','sources','request_context'}
    assert all(new['sources'][n]==h for n,h in old['sources'].items())
    assert len(new['sources'])==450 and set(context.MODULES)<=set(new['sources'])
    assert new['sources'][context.PRIOR_REQUEST]==context.PRIOR_SHA
    assert new['request_context']['worker_workflow_file_required'] is False
    assert new['native_horizon']==21 and new['source_physical_files']==516 and new['source_canonical_files']==224

def test_actual_host_expected_request_requires_explicit_checkout_workflow(monkeypatch):
    monkeypatch.setenv('GITHUB_WORKSPACE',str(HERE.parents[1]))
    assert job.expected_request()==request()
    monkeypatch.delenv('GITHUB_WORKSPACE')
    with pytest.raises(KeyError):job.expected_request()

@pytest.mark.parametrize('bad',['bytes','basename','missing'])
def test_host_actual_wrong_workflow_refuses(tmp_path,bad):
    p=tmp_path/(context.WORKFLOW if bad!='basename' else 'other.yml')
    if bad!='missing':p.write_bytes(b'wrong' if bad=='bytes' else (HERE.parents[1]/'.github/workflows'/context.WORKFLOW).read_bytes())
    with pytest.raises((ValueError,FileNotFoundError)):context.host_expected_request(p)

@pytest.fixture
def flat(tmp_path,monkeypatch):
    value=request();driver=tmp_path/'driver';driver.mkdir()
    for name in value['sources']:shutil.copyfile(HERE/name,driver/name)
    shutil.copyfile(HERE/context.REQUEST,driver/context.REQUEST)
    monkeypatch.setattr(context,'HERE',driver)
    return driver,value

def test_entire_worker_api_passes_flat_capsule_without_workflow_or_ancestors(flat,monkeypatch):
    driver,value=flat
    original=Path.read_bytes
    def read(path):
        assert not str(path).endswith('.yml')
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',read)
    assert context.worker_expected_request()==value
    assert context.worker_raw_request(driver/context.REQUEST)==value
    assert not (driver/'.github').exists()

@pytest.mark.parametrize('bad',['source','old_request','raw_copy','native_horizon','workflow','workflow_sha','missing_field','extra_field'])
def test_flat_worker_full_source_model_raw_mutations_refuse(flat,tmp_path,bad):
    driver,value=flat;out=tmp_path/'request.json';shutil.copyfile(driver/context.REQUEST,out)
    if bad=='source':(driver/'system_campaign_p10_ahl2_contract.py').write_bytes(b'changed')
    elif bad=='old_request':(driver/context.PRIOR_REQUEST).write_bytes(b'{}')
    elif bad=='raw_copy':out.write_bytes(json.dumps(value).encode())
    else:
        value=deepcopy(value)
        if bad=='native_horizon':value['native_horizon']=1
        elif bad=='workflow':value['workflow']='old.yml'
        elif bad=='workflow_sha':value['workflow_sha256']='f'*64
        elif bad=='missing_field':value.pop('actual_old_refusal_and_full_changed_FAST_REFERENCE_required')
        else:value['unreviewed']=True
        raw=json.dumps(value).encode();out.write_bytes(raw);(driver/context.REQUEST).write_bytes(raw)
    with pytest.raises(ValueError):context.worker_raw_request(out)

@pytest.mark.parametrize('label',['P10_CONTEXT_ACTUAL_HOST_WORKFLOW_BYTES','P10_CONTEXT_OUT_REQUEST_EXACT_RAW_DRIVER_COPY','P10_CONTEXT_ENTIRE_WORKER_REQUEST_MODEL_AND_SOURCE_CLOSURE'])
def test_context_predicate_removal_falsifiers(flat,tmp_path,label):
    driver,value=flat;name='host_expected_request' if 'HOST_WORKFLOW' in label else 'worker_raw_request'
    fn,=[n for n in ast.parse((HERE/'system_campaign_p10_ahl2_context.py').read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==name]
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Expr(self,n):
            if isinstance(n.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value==label for a in n.value.args):
                self.count+=1;return None
            return self.generic_visit(n)
    remove=Remove();fn=remove.visit(fn);assert remove.count==1
    namespace=dict(vars(context));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<context-guard-removed>','exec'),namespace)
    if name=='host_expected_request':p=tmp_path/context.WORKFLOW;p.write_bytes(b'wrong')
    else:
        p=tmp_path/'request.json';shutil.copyfile(driver/context.REQUEST,p)
        if 'RAW_DRIVER_COPY' in label:p.write_bytes(json.dumps(value).encode())
        else:
            value['native_horizon']=1;raw=json.dumps(value).encode();p.write_bytes(raw);(driver/context.REQUEST).write_bytes(raw)
    with pytest.raises(ValueError):getattr(context,name)(p)
    assert namespace[name](p)==(value if 'ENTIRE_WORKER' in label else context.worker_expected_request())

def inspect_record(role='worker'):
    destinations=['/variant','/frozen','/driver','/out','/old','/previous']+(['/evidence'] if role=='review' else [])
    return dict(Name='/capital-system-p10-ahl2-'+role+'-123-1',Id='f'*64,
        Image='sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d',
        State=dict(Running=False,OOMKilled=False,ExitCode=0),
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,ReadonlyRootfs=True,
                        PidsLimit=64,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
        Config=dict(WorkingDir='/variant',User='1001:1001',Env=[],Cmd=context.entrypoint(role),
                    Labels={'research.study':'full-system-search-20261029','research.role':'review' if role=='review' else 'worker'}),
        Mounts=[dict(Type='bind',Destination=d,RW=d=='/out') for d in destinations])

@pytest.mark.parametrize('role',['qualify','worker','review'])
def test_actual_new_namespace_worker_command_and_stop_entrypoint(monkeypatch,role):
    import os
    monkeypatch.setattr(os,'getuid',lambda:1001,raising=False);monkeypatch.setattr(os,'getgid',lambda:1001,raising=False)
    command=job.worker_command('synthetic',role,'/source','/frozen','/out','/old','/previous',evidence='/evidence')
    assert command[command.index('-B'):]==context.entrypoint(role)
    assert command[command.index('--memory')+1]==command[command.index('--memory-swap')+1]=='8g'
    assert command[command.index('--network')+1]=='none'
    value=inspect_record(role);stop=dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None)
    assert job.stopped_record(value,stop,role,'123')==value

@pytest.mark.parametrize('bad',['old_entrypoint','root','duplicate','running','bool_exit'])
def test_new_stop_exact_actual_fences_refuse(bad):
    value=inspect_record();stop=dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None)
    if bad=='old_entrypoint':value['Config']['Cmd'][2]='/driver/system_campaign_p10_ahl2_run.py'
    elif bad=='root':value['Config']['User']='0:0'
    elif bad=='duplicate':value['Mounts'].append(deepcopy(value['Mounts'][0]))
    elif bad=='running':value['State']['Running']=True
    else:value['State']['ExitCode']=False
    with pytest.raises(ValueError):job.stopped_record(value,stop,'worker','123')

def test_new_host_main_is_exact_original_AST_with_isolated_globals(monkeypatch):
    import builtins
    old=__import__('system_campaign_p10_ahl2_job');before=old.entrypoint
    captured=[];original_compile=builtins.compile
    def compiler(source,filename,*args,**kwargs):
        if filename=='<p10-context-original-host-orchestration>':
            captured.extend(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        return original_compile(source,filename,*args,**kwargs)
    monkeypatch.setattr(builtins,'compile',compiler)
    namespace=job.job_namespace()
    original,=[n for n in ast.parse(context.frozen_body('system_campaign_p10_ahl2_job.py')).body if isinstance(n,ast.FunctionDef) and n.name=='main']
    assert len(captured)==1 and ast.dump(captured[0],include_attributes=False)==ast.dump(original,include_attributes=False)
    assert namespace['main'].__globals__ is namespace and old.entrypoint is before
    assert namespace['entrypoint'] is context.entrypoint and namespace['expected_request'] is job.expected_request

def test_actual_flat_entrypoint_reaches_only_existing_qualification_API_without_core(flat,tmp_path):
    driver,value=flat
    script=r'''
import importlib.abc,json,sys
from pathlib import Path
from types import SimpleNamespace,ModuleType
driver=Path(sys.argv[1]);out=Path(sys.argv[2]);previous=Path(sys.argv[3]);sys.path.insert(0,str(driver))
class Fence(importlib.abc.MetaPathFinder):
 def find_spec(self,name,path=None,target=None):
  if name.startswith(('sentinel','stock_strategy_shared','research.pooled_','numpy','pandas')):raise AssertionError('CANONICAL_IMPORT_FORBIDDEN:'+name)
sys.meta_path.insert(0,Fence())
import system_campaign_p10_ahl2_context_run as entry
import system_campaign_p10_ahl2_run as old
import system_campaign_p10_ahl2_gate as gate
assert callable(old.physical_tree) and callable(gate.qualify)
calls=[];core=ModuleType('full_system_core');core.hosted=lambda:calls.append('HOSTED');sys.modules['full_system_core']=core
real=Path
old.Path=lambda value: {'/out':out,'/old':out.parent/'old','/previous':previous}.get(str(value),real(value))
old.physical_tree=lambda *a:calls.append('PHYSICAL_SOURCE_GUARD_STUBBED')
gate.qualify=lambda *a:calls.append('ACTUAL_EXISTING_QUALIFY_API_STUBBED') or {'metadata_only':True}
result=entry.main(SimpleNamespace(mode='qualify',spec=out/'spec.json',request=out/'request.json'))
assert result=={'metadata_only':True} and calls==['HOSTED','PHYSICAL_SOURCE_GUARD_STUBBED','ACTUAL_EXISTING_QUALIFY_API_STUBBED']
assert not any(n.startswith(('sentinel','stock_strategy_shared','research.pooled_')) for n in sys.modules)
print(json.dumps({'actual_flat_entrypoint_metadata_passed':True,'canonical_execution':False,'calls':calls}))
'''
    out=tmp_path/'out';out.mkdir();previous=tmp_path/'previous';previous.mkdir()
    shutil.copyfile(driver/context.REQUEST,out/'request.json')
    shutil.copyfile(driver/'system-campaign-p10-ahl2-predecessor-001.json',out/'spec.json')
    (previous/'source-bindings.json').write_bytes(b'{}')
    result=subprocess.run([sys.executable,'-B','-c',script,str(driver),str(out),str(previous)],capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)['actual_flat_entrypoint_metadata_passed'] is True

def test_workflow_budgets_capacity_and_new_request_only_trigger():
    raw=(HERE.parents[1]/'.github/workflows'/context.WORKFLOW).read_bytes();assert context.sha(raw)==context.WORKFLOW_SHA
    text=raw.decode();timeouts=[int(line.partition(':')[2].strip()) for line in text.splitlines() if 'timeout-minutes:' in line]
    assert timeouts==[355,3,5,4,3,12,300,10]
    assert text.index('ephemeral_runner_capacity.py')<text.index('/stage.py')
    assert context.REQUEST in text and 'system-p10-ahl2-context-' in text and 'retention-days: 7' in text
    assert 'system-campaign-p10-ahl2-request-001.json' not in text
