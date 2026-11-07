"""Recovery namespace, flat driver metadata and stop contracts; no Core."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import yaml

HERE=Path(__file__).parents[1];sys.path.insert(0,str(HERE))
import p01_iac_unit_fixture_job as job
import p01_iac_unit_fixture_export as export
import p01_iac_unit_contract as contract


def proof():
    return dict(status='OWN628_IAC_UNIT_INPUT_AND_TWO_SESSION_FAST_REFERENCE_QUALIFIED',financial_authority=False,
        financial_predecessor_authorized=False,component_transitions=2,qualified_through='2020-07-02',
        epoch_zero_outer_sha256=export.OUTER,input_zero_outer_sha256='d'*64,
        input_document_sha256='a'*64,successor_input_sha256='b'*64,original_inputs=11,successor_inputs=12,
        input_adoptions=1,actual_fast_reference_full_components_equal=True,actual_role_and_full_state_checks=2,
        source_epoch_boundary_reemitted=False,unit_normalization_qualified=True,
        unit_target_independence_qualified=True,source_scope_falsifiers_qualified=True,
        fixture_aggregate_complete=True,fixture_aggregate_all_passed=True,fixture_expected_case_count=9,
        fixture_attempted_case_count=9,fixture_passed_case_count=9,fixture_failed_case_count=0,
        fixture_component_sha256='a'*64,fixture_expected_case_ids=list(export.FIXTURE_CASE_IDS))


@pytest.fixture
def flat(tmp_path,monkeypatch):
    folder=tmp_path/'driver';folder.mkdir()
    for name in job.SOURCES:(folder/name).write_bytes((HERE/name).read_bytes())
    (folder/'system-campaign-search-protocol.json').write_bytes((HERE/'system-campaign-search-protocol.json').read_bytes())
    monkeypatch.setattr(job,'HERE',folder);monkeypatch.setattr(job.previous,'HERE',folder);monkeypatch.setattr(job.predecessor,'HERE',folder)
    monkeypatch.setattr(contract,'HERE',folder)
    value=job.expected_request();(folder/job.REQUEST).write_bytes(job.encoded_request(value))
    return folder,value


def test_actual_flat_driver_new_and_old_request_closures_no_workflow_lookup(flat):
    folder,value=flat
    assert not (folder.parents[1]/'.github/workflows').exists()
    assert len(value['sources'])==len(job.SOURCES) and len(json.loads((folder/job.PRIOR_REQUEST).read_bytes())['sources'])==490
    assert set(value['sources'])==set(json.loads((folder/job.PRIOR_REQUEST).read_bytes())['sources'])|{job.PRIOR_REQUEST}|set(job.NEW)
    assert value['prior_request_sha256']==job.PRIOR_SHA and value['prior_driver_sources']==490
    assert job.validate_worker_request(folder/job.REQUEST,mode='qualify')==value
    prior=json.loads((folder/job.PRIOR_REQUEST).read_bytes())
    for key,item in prior.items():
        if key not in ('schema','stage','sources','prior_request_file','prior_request_sha256','prior_driver_sources',
            'actual_entrypoint','worker_namespace','workflow','owner_workflow_sha256','recovery_reason',
            'failed_qualification_run_id','failed_qualification_artifact_id'):assert value[key]==item
    assert value['input_document_sha256']=='0f1f4672e1a3ee3f64f8281d25f3348d9f53f28ea6146d71c4f71a8378d515b7'
    assert value['successor_input_sha256']=='ce0615156c89367169ac5da437c5418747b5d290c7634a79f52a415fb68262b8'


@pytest.mark.parametrize('kind',['new_source','old_source','old_request','new_request','crlf','wrong_path','rawcopy'])
def test_flat_request_refuses_wrong_epoch_source_model_and_copies(flat,monkeypatch,kind):
    folder,value=flat;path=folder/job.REQUEST
    if kind=='new_source':(folder/'p01_iac_unit_fixture_component.py').write_bytes(b'changed')
    if kind=='old_source':(folder/'p01_iac_unit_guard.py').write_bytes(b'changed')
    if kind=='old_request':(folder/job.PRIOR_REQUEST).write_bytes(b'{}\n')
    if kind=='new_request':
        bad=deepcopy(value);bad['new_request_before_any_old_runtime']=False;path.write_bytes(job.encoded_request(bad))
    if kind=='crlf':path.write_bytes(path.read_bytes().replace(b'\n',b'\r\n'))
    if kind=='wrong_path':
        path=folder/'wrong.json';path.write_bytes(job.encoded_request(value))
    if kind=='rawcopy':
        copy=folder/'out-request.json';copy.write_bytes(b'changed');monkeypatch.setattr(job,'_worker_copy',lambda mode:copy)
    with pytest.raises(ValueError):job.validate_worker_request(path,mode='economic' if kind=='rawcopy' else 'qualify')


def test_both_economic_and_review_require_whole_new_raw_copy(flat,monkeypatch):
    folder,value=flat;copy=folder/'copied.json';copy.write_bytes(job.encoded_request(value))
    seen=[];monkeypatch.setattr(job,'_worker_copy',lambda mode:seen.append(mode) or copy)
    for mode in ('economic','review'):assert job.validate_worker_request(folder/job.REQUEST,mode=mode)==value
    assert seen==['economic','review']


def test_new_request_whole_model_predicate_removal_falsifier(flat):
    folder,value=flat;bad=deepcopy(value);bad['new_request_before_any_old_runtime']=False
    path=folder/job.REQUEST;path.write_bytes(job.encoded_request(bad))
    with pytest.raises(ValueError):job.validate_worker_request(path,mode='qualify')
    tree=ast.parse(Path(job.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='validate_worker_request')
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and any(isinstance(v,ast.Constant)
        and v.value=='RECOVERY_ENTIRE_NEW_REQUEST_AND_ALL_SOURCE_BYTES_BEFORE_OLD_RUNTIME' for v in ast.walk(n)))
    guard.args[0]=ast.Constant(True);namespace=dict(vars(job))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-new-model>','exec'),namespace)
    assert namespace['validate_worker_request'](path,mode='qualify')==value


def test_exact_new_entrypoints_mounts_and_source_bound_inspector(monkeypatch):
    import full_system_benchmark as source
    monkeypatch.setattr(source.os,'getuid',lambda:1001,raising=False);monkeypatch.setattr(source.os,'getgid',lambda:1001,raising=False)
    for mode in ('qualify','economic','review'):
        assert job.entrypoint(mode)==['-B','-u','/driver/p01_iac_unit_fixture_run.py','--mode',mode,'--spec','/out/spec.json']
        name='capital-system-p01-iac-unit-fixture-'+('worker' if mode=='economic' else mode)+'-123-1'
        command=job.worker_command(name,mode,Path('/source'),Path('/frozen'),Path('/out'),Path('/old'),Path('/capsule'),Path('/evidence') if mode!='qualify' else None)
        assert command[command.index('-B'):]==job.entrypoint(mode)
        assert command[command.index('--network')+1]=='none' and '--cpus' in command and command[command.index('--cpus')+1]=='2'
        assert command[command.index('--memory')+1]==command[command.index('--memory-swap')+1]=='8g'
        mounts=[command[i+1] for i,v in enumerate(command) if v=='--mount']
        for target in ('/variant','/frozen','/driver','/old','/celg-input','/celg-input-descriptor.json'):
            assert any('target='+target+',' in m and m.endswith('readonly') for m in mounts)
        assert any('target=/out' in m and 'readonly' not in m for m in mounts)
        if mode!='qualify':assert any('target=/evidence,readonly' in m for m in mounts)
    tree=ast.parse(Path(job.previous.__file__).read_bytes())
    assert job._body('inspect').__globals__['entrypoint'] is job.entrypoint


def test_actual_synthetic_new_marker_crypto_and_namespace(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    request=tmp_path/'request.json';request.write_text(json.dumps(dict(protocol_sha256='c'*64)))
    value=export.qualify_export(tmp_path/'probe',request)
    assert value['status']=='P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED'
    assert value['source_adapter_sha256']==job.sha256_file(Path(export.__file__))
    assert value['synthetic_marker_only'] and not value['market_or_financial_state_processed']
    scope=export._scope()
    assert scope['STAGE']==export.STAGE=='campaign-p01-iac-unit-fixture-financial'
    assert scope['QUALIFICATION_STAGE']=='campaign-p01-iac-unit-fixture-qualification'
    assert 'p01-iac-unit-fixture-qualification-output' in ast.unparse(ast.parse(Path(export.previous.__file__).read_bytes())).replace('p01-iac-unit','p01-iac-unit-fixture')


def test_workflow_only_new_trigger_exact_host_workflow_hash_and_capped_budget():
    raw=(HERE.parents[1]/'.github/workflows'/job.WORKFLOW).read_bytes();assert job.sha256_file(HERE.parents[1]/'.github/workflows'/job.WORKFLOW)==job.WORKFLOW_SHA
    value=yaml.safe_load(raw);trigger=value.get('on',value.get(True))
    assert trigger['push']['paths']==['research/capital_risk/'+job.REQUEST] and value['concurrency']['cancel-in-progress'] is False
    steps=value['jobs']['iac-unit-fixture']['steps'];assert [s['timeout-minutes'] for s in steps]==[3,3,4,2,8,210,5]
    assert sum(s['timeout-minutes'] for s in steps)<=value['jobs']['iac-unit-fixture']['timeout-minutes']-5
    assert '.github/workflows' in steps[0]['with']['sparse-checkout']
    assert steps[-1]['if']=='always()' and steps[-1]['with']['retention-days']==7
    wrong=deepcopy(value);del wrong['jobs']['iac-unit-fixture']['steps'][-1]['timeout-minutes']
    with pytest.raises(KeyError):sum(s['timeout-minutes'] for s in wrong['jobs']['iac-unit-fixture']['steps'])


@pytest.mark.parametrize('failure',['none','qualify_unknown','qualify_refused','finance_unknown','review_unknown','wrong_qualifier_count','wrong_finance_input'])
def test_same_proven_source_bound_main_ordering_in_new_namespace(tmp_path,monkeypatch,failure):
    spec=importlib.util.spec_from_file_location('frozen_484_host_fixtures',HERE/'forecast_tests/test_p01_iac_unit_host.py')
    fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
    raw=(HERE/'forecast_tests/test_p01_iac_unit_host.py').read_bytes()
    node=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)
        and n.name=='test_source_bound_main_marker_before_parent_and_cipher_before_fresh_finance')
    class Namespace(ast.NodeTransformer):
        def visit_Constant(self,item):
            if type(item.value) is str:item.value=item.value.replace('p01-iac-unit','p01-iac-unit-fixture')
            return item
    node=Namespace().visit(node);values=dict(vars(fixtures),job=job,export=export,proof=proof)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<frozen-host-fixture-new-namespace-only>','exec'),values)
    values[node.name](tmp_path,monkeypatch,failure)


def old_fixture(names):
    path=HERE/'forecast_tests/test_p01_iac_unit_host.py'
    spec=importlib.util.spec_from_file_location('frozen_484_auxiliary_host_fixtures',path)
    fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
    nodes=[n for n in ast.parse(path.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name in names|{'receipt'}]
    class Namespace(ast.NodeTransformer):
        def visit_Constant(self,item):
            if type(item.value) is str:item.value=item.value.replace('p01-iac-unit','p01-iac-unit-fixture')
            return item
    tree=Namespace().visit(ast.Module(body=nodes,type_ignores=[]));values=dict(vars(fixtures),job=job,export=export,proof=proof)
    exec(compile(ast.fix_missing_locations(tree),'<frozen-484-stop-crypto-fixtures-new-namespace>','exec'),values)
    return values


@pytest.mark.parametrize('role',['qualify','worker','review'])
def test_actual_inspection_receipt_new_namespace_modes_and_ro_falsifiers(tmp_path,monkeypatch,role):
    name='test_actual_inspector_new_namespace_cli_and_readonly_quotes'
    old_fixture({name})[name](tmp_path,monkeypatch,role)


def test_actual_new_negative_q_cipher_gcm_full_failure_inventory_and_known_scope(tmp_path,monkeypatch):
    name='test_actual_negative_q_cipher_full_gcm_and_inventory_before_refusal_payload'
    old_fixture({name,'qualification_failure_fixture'})[name](tmp_path,monkeypatch)


def test_new_public_export_scalar_allowlist_conformance(tmp_path):
    name='test_public_asset_and_error_values_are_only_declared_scalar_metadata'
    old_fixture({name})[name](tmp_path)


@pytest.mark.parametrize('field,bad',[
    ('fixture_aggregate_complete',False),('fixture_aggregate_all_passed',1),
    ('fixture_expected_case_count',8),('fixture_attempted_case_count',8),('fixture_attempted_case_count',9.0),
    ('fixture_passed_case_count',True),('fixture_failed_case_count',1),('fixture_failed_case_count',False),
    ('fixture_component_sha256','not-a-hash'),('fixture_expected_case_ids',['POST_EVENT_SOURCE_BUY'])])
def test_complete_nine_fixture_gate_missing_wrong_scalar_or_count_refuses(field,bad):
    good=proof();export.qualification(good)
    wrong=deepcopy(good);wrong[field]=bad
    with pytest.raises(ValueError):export.qualification(wrong)
    del good[field]
    with pytest.raises(ValueError):export.qualification(good)


def test_aggregate_gate_removal_accepts_incomplete_fixture_falsifier():
    bad=proof();bad['fixture_attempted_case_count']=8
    with pytest.raises(ValueError):export.qualification(bad)
    fn=next(n for n in ast.parse(Path(export.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='qualification')
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need')
    guard.args[0]=ast.Constant(True);namespace=dict(vars(export))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-nine-fixture-gate>','exec'),namespace)
    namespace['qualification'](bad)


def test_successful_qualifier_seal_binds_actual_component_bytes_and_unknown_refuses(tmp_path,monkeypatch):
    root=tmp_path/'out';q=root/'qualification';q.mkdir(parents=True)
    component=q/'unit-normalization-component.json.gz';component.write_bytes(b'opaque synthetic component')
    value=proof();value['fixture_component_sha256']=job.sha256_file(component)
    (q/'qualification-summary.json').write_text(json.dumps(value))
    receipt=dict(qualification_worker=dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None))
    calls=[];monkeypatch.setitem(export._scope(),'preserve_qualification',lambda *a:calls.append('sealed'))
    export.preserve_qualification(receipt,root,tmp_path/'public.json',b'x'*32,tmp_path/'request.json')
    assert calls==['sealed'];calls.clear();component.write_bytes(b'changed component')
    with pytest.raises(ValueError,match='ACTUAL_COMPONENT_BYTES_EQUAL'):
        export.preserve_qualification(receipt,root,tmp_path/'public.json',b'x'*32,tmp_path/'request.json')
    assert not calls
    receipt['qualification_worker']['stopped']=False
    with pytest.raises(ValueError,match='KNOWN_SUCCESSFUL_QUALIFIER_STOP'):
        export.preserve_qualification(receipt,tmp_path/'never-read',None,None,None)


def test_hash_binding_removal_accepts_replaced_component_falsifier(tmp_path,monkeypatch):
    q=tmp_path/'qualification';q.mkdir();(q/'unit-normalization-component.json.gz').write_bytes(b'changed component')
    (q/'qualification-summary.json').write_text(json.dumps(proof()))
    receipt=dict(qualification_worker=dict(stopped=True,exit_code=0,oom_killed=False))
    calls=[];monkeypatch.setitem(export._scope(),'preserve_qualification',lambda *a:calls.append('sealed'))
    with pytest.raises(ValueError):export.preserve_qualification(receipt,tmp_path,None,None,None)
    fn=next(n for n in ast.parse(Path(export.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='preserve_qualification')
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and any(isinstance(n,ast.Constant)
        and n.value=='FIXTURE_ACTUAL_COMPONENT_BYTES_EQUAL_QUALIFIED_AGGREGATE_HASH' for n in ast.walk(n)))
    guard.args[0]=ast.Constant(True);namespace=dict(vars(export))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-component-hash>','exec'),namespace)
    namespace['preserve_qualification'](receipt,tmp_path,None,None,None)
    assert calls==['sealed']
