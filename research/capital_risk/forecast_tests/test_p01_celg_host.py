"""Pure metadata/fence and real tiny-marker tests; no canonical finance imports."""
import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
from system_campaign_parallel_discovery_probe import Fence
import p01_celg_export as export
import p01_celg_job as job
import p01_celg_accounting as accounting
import p01_celg_component as component
import ephemeral_runner_capacity as capacity

@pytest.fixture
def env(monkeypatch,tmp_path):
    for k,v in dict(GITHUB_RUN_ID='123',GITHUB_SHA='1'*40,RUNNER_TEMP=str(tmp_path)).items():monkeypatch.setenv(k,v)
    monkeypatch.setattr(os,'getuid',lambda:1001,raising=False);monkeypatch.setattr(os,'getgid',lambda:1001,raising=False)
    return tmp_path

def request(tmp_path):
    path=tmp_path/'request.json';path.write_text(json.dumps(dict(protocol_sha256='2'*64)))
    return path

def receipt():
    return dict(schema='research.p01-celg-synthetic-component-receipt/1',arm='P01',stage=export.STAGE,
        authority=export.AUTHORITY,financial_authority=False,production_contacted=False,
        run_id='123',head='1'*40,status='STOPPED_SYNTHETIC_COMPONENT_REFUSAL_PRESERVED')

def test_actual_new_scope_marker_encrypt_authenticate_and_decrypt(env):
    proof=export.qualify_export(env/'marker',request(env))
    assert proof['status']=='CELG_COMPONENT_ACTUAL_NEW_SCOPE_MARKER_ROUNDTRIP_PASSED'
    assert proof['synthetic_marker_only'] and not proof['market_or_financial_state_processed']
    assert proof['stage']==export.STAGE and not proof['financial_or_canonical_state_processed']

def scoped_seal(*,remove_guard=False):
    fn=export.pinned(export.seal_source,'seal')
    replacements={'campaign-factual-suffix':export.STAGE,'P02':'P01',
        'RETAINED_EXPORT_EXACT_P02_RESEARCH_SCOPE':'CELG_COMPONENT_EXACT_NEW_SYNTHETIC_EXPORT_SCOPE'}
    for node in ast.walk(fn):
        if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value in replacements:node.value=replacements[node.value]
    if remove_guard:fn.body.pop(0)
    return job.compile_body(fn,vars(export.seal_source))

@pytest.mark.parametrize('arm,stage',[('P02',export.STAGE),('P01','campaign-factual-suffix')])
def test_actual_new_scope_seal_refuses_old_arm_or_scope(env,arm,stage):
    root=env/'root';root.mkdir();(root/'marker').write_text('synthetic')
    with pytest.raises(ValueError,match='CELG_COMPONENT_EXACT_NEW_SYNTHETIC_EXPORT_SCOPE'):
        scoped_seal()(root,env/'cipher',b'0'*32,request(env),arm,stage=stage,protocol_sha256='2'*64)

def test_actual_scope_guard_removal_falsifier(env):
    root=env/'root';root.mkdir();(root/'marker').write_text('synthetic')
    with pytest.raises(ValueError,match='CELG_COMPONENT_EXACT_NEW_SYNTHETIC_EXPORT_SCOPE'):
        scoped_seal()(root,env/'rejected',b'0'*32,request(env),'P02',stage='campaign-factual-suffix',protocol_sha256='2'*64)
    value=scoped_seal(remove_guard=True)(root,env/'guard-removed',b'0'*32,request(env),'P02',
        stage='campaign-factual-suffix',protocol_sha256='2'*64)
    assert value['bytes']>0

def test_unknown_stop_never_reads_private_output_or_encrypts(env,monkeypatch):
    monkeypatch.setattr(export,'sealed',lambda *a:pytest.fail('UNKNOWN_PRIVATE_SNAPSHOT'))
    value=receipt();value['status']='SYNTHETIC_COMPONENT_STOP_UNKNOWN_NO_SNAPSHOT'
    export.finish(value,env/'not-even-created',env/'receipt.json',None,request(env),known=False)
    assert json.loads((env/'receipt.json').read_bytes())==value and not value['encrypted_output_exported']

def test_actual_stop_is_durable_before_export_failure_and_error_value_is_private(env,monkeypatch):
    path=env/'receipt.json';value=receipt();value['worker']=dict(stopped=True,exit_code=2,oom_killed=False,wait_error=None)
    def fail(*a):
        saved=json.loads(path.read_bytes())
        assert saved['worker']['stopped'] and saved['pre_export_status']==value['status']
        raise ValueError('private NAV=999 source price=2.30')
    monkeypatch.setattr(export,'sealed',fail)
    export.finish(value,env/'root',path,b'0'*32,request(env),known=True)
    assert value['status']=='KNOWN_STOP_EXPORT_FAILED_NO_PLAINTEXT_FALLBACK'
    assert value['export_error']==dict(type='ValueError',code='EXPORT_OPERATION_FAILED')
    assert 'NAV' not in path.read_text()

@pytest.mark.parametrize('addition',[{'strategy_nav':1000},{'worker':{'stopped':False}}, {'error':{'message':'private'}}])
def test_public_receipt_refuses_undeclared_financial_or_stop_payload(env,addition):
    with pytest.raises(ValueError):export.write_receipt(env/'receipt.json',dict(receipt(),**addition))

def test_phase_keeps_locations_without_exception_values(env,monkeypatch):
    monkeypatch.setattr(job,'memory_bytes',lambda:dict(MemAvailable=11*1024**3))
    try:raise RuntimeError('PRIVATE positions qty=13')
    except RuntimeError as error:job.note(env/'phase.json','FAILURE',error)
    value=json.loads((env/'phase.json').read_bytes())
    assert value['exception_class']=='RuntimeError' and value['code_locations']
    assert 'PRIVATE' not in (env/'phase.json').read_text() and not value['exception_values_included']

def inspection(name):
    return dict(Name='/'+name,Image=job.EXECUTION_IMAGE,Id='f'*64,
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
            PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
        Config=dict(Cmd=job.entrypoint(),WorkingDir='/variant',User='1001:1001',
            Labels={'research.study':'full-system-search-20261029','research.role':'worker'},Env=[]),
        Mounts=[dict(Type='bind',Destination=n,RW=n=='/out') for n in ('/variant','/frozen','/driver','/out')])

@pytest.mark.parametrize('change',[None,'old-mount','writable-source','wrong-entrypoint','network','credential'])
def test_actual_worker_command_and_inspection_fences(env,monkeypatch,change):
    name='capital-system-p01-celg-component-worker-123-1'
    argv=job.worker_command(name,Path('/source'),Path('/frozen-source'),Path('/output'))
    assert argv[argv.index('-B'):]==job.entrypoint() and argv.count('--mount')==4
    assert 'target=/old' not in ' '.join(argv) and '--memory-swap' in argv and '--network' in argv
    value=inspection(name)
    if change=='old-mount':value['Mounts'].append(dict(Type='bind',Destination='/old',RW=False))
    if change=='writable-source':value['Mounts'][0]['RW']=True
    if change=='wrong-entrypoint':value['Config']['Cmd']=['-B','/driver/full_system_core.py']
    if change=='network':value['HostConfig']['NetworkMode']='bridge'
    if change=='credential':value['Config']['Env']=['GH_TOKEN=private']
    monkeypatch.setattr(job.fence_source.subprocess,'run',lambda *a,**kw:SimpleNamespace(stdout=json.dumps([value]).encode()))
    if change:
        with pytest.raises(ValueError):job.inspect(name,'f'*64)
    else:assert job.inspect(name,'f'*64)==value

def test_exact_sources_and_only_synthetic_quote_scope():
    value=job.expected_request();old=json.loads((HERE/export.PRIOR).read_bytes())
    assert len(value['sources'])==429 and len(old['sources'])==418
    assert all(value['sources'][n]==h for n,h in old['sources'].items())
    assert not set(value['sources'])&{'p01_celg_multileg_quote.json.gz','p01_celg_multileg_quote_capture.json','p01_celg_multileg_qualification_plan.json'}
    assert not value['actual_own_book_restored'] and not value['retained_right_quote_authenticated']
    assert value['all_positions_and_prices_explicitly_synthetic']
    assert accounting.Quote.model_validate(component.quote()).observed_market_data is False
    with pytest.raises(ValueError):accounting.Quote.model_validate(dict(component.quote(),feed='sip',raw_sha256='1'*64))

def test_marker_precedes_parentfetch_and_only_worker_and_capacity_precedes_staging():
    tree=ast.parse(Path(job.__file__).read_bytes());main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    calls={name:[n.lineno for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id==name]
           for name in ('qualify_export','admit','stopped_run','validate_prepared_receipt')}
    assert all(len(rows)==1 for rows in calls.values())
    assert calls['validate_prepared_receipt'][0]<calls['qualify_export'][0]<calls['admit'][0]<calls['stopped_run'][0]
    raw=(HERE.parents[1]/'.github/workflows/capital-system-p01-celg-component.yml').read_text()
    assert raw.index('/ephemeral_runner_capacity.py')<raw.index('/stage.py')<raw.index('/p01_celg_job.py')
    assert 'workflow_dispatch' not in raw and 'timeout-minutes: 65' in raw and 'timeout-minutes: 35' in raw and 'retention-days: 7' in raw
    assert 'timeout-minutes: 5' in raw and 'timeout-minutes: 8' in raw
    value=job.expected_request()
    assert value['job_timeout_minutes']==65 and value['capacity_step_timeout_minutes']==5
    assert value['orchestration_timeout_minutes']==35 and value['staging_timeout_minutes']==8
    assert value['worker_wait_seconds']==900 and value['initial_min_disk_bytes']==12*1024**3
    assert value['preworker_min_disk_bytes']==value['preworker_min_memory_bytes']==10*1024**3

@pytest.mark.parametrize('field,value',[('manifest_sha256','3'*64),('source_commit','2'*40),
    ('authenticated_before_parsing',False),('replay_started',True)])
def test_original_frozen_stage_identity_and_authentication_remain_mandatory(env,field,value):
    stage=dict(status='STAGING_PASSED',run_id='123',source_commit='1'*40,protocol_sha256=job.PROTOCOL,
        runtime_image=job.IMAGE,execution_image=job.EXECUTION_IMAGE,source_files_verified=514,members_verified=591,
        manifest_sha256='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a',
        authenticated_before_parsing=True,offline_image_source_verified=True,
        runtime_index_config_layer_chain_verified=True,replay_started=False)
    job.stage_valid(stage);stage[field]=value
    with pytest.raises(ValueError):job.stage_valid(stage)

@pytest.mark.parametrize('field,value',[('head','2'*40),('run_id','124'),('source_sha256','3'*64),('target_removed',False)])
def test_shared_prepared_receipt_consumed_exactly_without_cleanup(field,value):
    sha=job.expected_request()['capacity_source_sha256']
    receipt=dict(schema=capacity.SCHEMA,authority=capacity.AUTHORITY,head='1'*40,run_id='123',ref=capacity.REF,
        source_sha256=sha,target=capacity.TARGET,phase='PREPARED',phase_history=['VALIDATING','REMOVAL_ATTEMPTED','PREPARED'],
        removal_attempted=True,target_removed=True,error_code=None,free_before_bytes=0,free_after_bytes=12*1024**3,
        production_contacted=False,financial_or_market_payload_included=False)
    capacity.validate_prepared_receipt(receipt,head='1'*40,run_id='123',source_sha256=sha)
    receipt[field]=value
    with pytest.raises(ValueError):capacity.validate_prepared_receipt(receipt,head='1'*40,run_id='123',source_sha256=sha)
