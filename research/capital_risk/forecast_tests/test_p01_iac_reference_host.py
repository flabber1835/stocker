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
import p01_iac_reference_job as job
import p01_iac_reference_export as export
import p01_iac_reference_evidence as evidence
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
        fixture_component_sha256=export.APPROVED[export.COMPONENT]['sha256'],fixture_expected_case_ids=list(export.FIXTURE_CASE_IDS),
        reference_evidence_reused=True,reference_reuse_admission_sha256=export.ADMISSION,
        reference_recorded_origin={k:export.ORIGIN[k] for k in ('run_id','head','artifact_id','request_sha256')},
        original_reference_compiler_logs_available=False,source_compiler_check_qualified=True,source_preparations=2,
        reference_report_rechecked=True,reference_report_financial_transitions=0,
        reference_report_origin='NEW_READONLY_CANONICAL_REPORT_ON_RESTORED_OLD_STATE',
        source_compiler_financial_transitions=0,reference_financial_transitions_reexecuted=0,old_reference_runtime_records_restored=2,
        old_synthetic_wires_restored=18,reference_evidence_sha256='a'*64)


def populate_q15(root):
    root.mkdir(parents=True,exist_ok=True);q=root/'qualification';q.mkdir(exist_ok=True)
    for name in ('spec.json','request.json','source-map.json','source-bindings.json'):
        if not (root/name).exists():(root/name).write_bytes(b'{}')
    for name in (*export.QUALIFICATION_FILES,'worker-inspect.json','worker.log'):
        if not (q/name).exists():(q/name).write_bytes(b'{}')


@pytest.fixture
def flat(tmp_path,monkeypatch):
    folder=tmp_path/'driver';folder.mkdir()
    for name in job.SOURCES:(folder/name).write_bytes((HERE/name).read_bytes())
    (folder/'system-campaign-search-protocol.json').write_bytes((HERE/'system-campaign-search-protocol.json').read_bytes())
    monkeypatch.setattr(job,'HERE',folder);monkeypatch.setattr(job.previous,'HERE',folder);monkeypatch.setattr(job.predecessor,'HERE',folder);monkeypatch.setattr(job.predecessor.predecessor,'HERE',folder);monkeypatch.setattr(evidence,'HERE',folder)
    monkeypatch.setattr(contract,'HERE',folder)
    value=job.expected_request();(folder/job.REQUEST).write_bytes(job.encoded_request(value))
    return folder,value


def test_actual_flat_driver_new_and_old_request_closures_no_workflow_lookup(flat):
    folder,value=flat
    assert not (folder.parents[1]/'.github/workflows').exists()
    assert len(value['sources'])==len(job.SOURCES) and len(json.loads((folder/job.PRIOR_REQUEST).read_bytes())['sources'])==497
    assert set(value['sources'])==set(json.loads((folder/job.PRIOR_REQUEST).read_bytes())['sources'])|{job.PRIOR_REQUEST}|set(job.NEW)
    assert value['prior_request_sha256']==job.PRIOR_SHA and value['prior_driver_sources']==497
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
    if kind=='new_source':(folder/'p01_iac_reference_source.py').write_bytes(b'changed')
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
        assert job.entrypoint(mode)==['-B','-u','/driver/p01_iac_reference_run.py','--mode',mode,'--spec','/out/spec.json']
        name='capital-system-p01-iac-reference-'+('worker' if mode=='economic' else mode)+'-123-1'
        command=job.worker_command(name,mode,Path('/source'),Path('/frozen'),Path('/out'),Path('/old'),Path('/capsule'),Path('/evidence'))
        assert command[command.index('-B'):]==job.entrypoint(mode)
        assert command[command.index('--network')+1]=='none' and '--cpus' in command and command[command.index('--cpus')+1]=='2'
        assert command[command.index('--memory')+1]==command[command.index('--memory-swap')+1]=='8g'
        mounts=[command[i+1] for i,v in enumerate(command) if v=='--mount']
        for target in ('/variant','/frozen','/driver','/old','/celg-input','/celg-input-descriptor.json'):
            assert any('target='+target+',' in m and m.endswith('readonly') for m in mounts)
        assert any('target=/out' in m and 'readonly' not in m for m in mounts)
        assert any('target=/evidence,readonly' in m for m in mounts)
    tree=ast.parse(Path(job.previous.__file__).read_bytes())
    assert '/evidence' in ast.unparse(ast.parse(Path(job.__file__).read_bytes()))


def test_actual_synthetic_new_marker_crypto_and_namespace(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    request=tmp_path/'request.json';request.write_text(json.dumps(dict(protocol_sha256='c'*64)))
    value=export.qualify_export(tmp_path/'probe',request)
    assert value['status']=='P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED'
    assert value['source_adapter_sha256']==job.sha256_file(Path(export.__file__))
    assert value['synthetic_marker_only'] and not value['market_or_financial_state_processed']
    scope=export._scope()
    assert scope['STAGE']==export.STAGE=='campaign-p01-iac-reference-financial'
    assert scope['QUALIFICATION_STAGE']=='campaign-p01-iac-reference-qualification'
    assert 'p01-iac-reference-qualification-output' in ast.unparse(ast.parse(Path(export.previous.__file__).read_bytes())).replace('p01-iac-unit','p01-iac-reference')


def test_workflow_only_new_trigger_exact_host_workflow_hash_and_capped_budget():
    raw=(HERE.parents[1]/'.github/workflows'/job.WORKFLOW).read_bytes();assert job.sha256_file(HERE.parents[1]/'.github/workflows'/job.WORKFLOW)==job.WORKFLOW_SHA
    value=yaml.safe_load(raw);trigger=value.get('on',value.get(True))
    assert trigger['push']['paths']==['research/capital_risk/'+job.REQUEST] and value['concurrency']['cancel-in-progress'] is False
    steps=value['jobs']['iac-reference']['steps'];assert [s['timeout-minutes'] for s in steps]==[3,3,4,2,8,210,5]
    assert sum(s['timeout-minutes'] for s in steps)<=value['jobs']['iac-reference']['timeout-minutes']-5
    assert '.github/workflows' in steps[0]['with']['sparse-checkout']
    assert steps[-1]['if']=='always()' and steps[-1]['with']['retention-days']==7
    wrong=deepcopy(value);del wrong['jobs']['iac-reference']['steps'][-1]['timeout-minutes']
    with pytest.raises(KeyError):sum(s['timeout-minutes'] for s in wrong['jobs']['iac-reference']['steps'])


@pytest.mark.parametrize('failure',['none','qualify_unknown','qualify_refused','finance_unknown','review_unknown','wrong_qualifier_count','wrong_finance_input'])
def test_same_proven_source_bound_main_ordering_in_new_namespace(tmp_path,monkeypatch,failure):
    spec=importlib.util.spec_from_file_location('frozen_484_host_fixtures',HERE/'forecast_tests/test_p01_iac_unit_host.py')
    fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
    raw=(HERE/'forecast_tests/test_p01_iac_unit_host.py').read_bytes()
    node=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)
        and n.name=='test_source_bound_main_marker_before_parent_and_cipher_before_fresh_finance')
    class Namespace(ast.NodeTransformer):
        def visit_Constant(self,item):
            if type(item.value) is str:item.value=item.value.replace('p01-iac-unit','p01-iac-reference')
            return item
    node=Namespace().visit(node);values=dict(vars(fixtures),job=job,export=export,proof=proof)
    for i,item in enumerate(node.body):
        if isinstance(item,ast.Expr) and isinstance(item.value,ast.Call) and ast.unparse(item.value.func)=='monkeypatch.setattr' and any(isinstance(x,ast.Constant) and x.value=='admit' for x in ast.walk(item)):
            node.body[i+1:i+1]=ast.parse("def admitted_reference(root,key,spec):\n    events.append('reference')\n    root.mkdir()\n    return root\nmonkeypatch.setattr(job,'admit_reference',admitted_reference)").body
            break
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
            if type(item.value) is str:item.value=item.value.replace('p01-iac-unit','p01-iac-reference')
            return item
        def visit_If(self,item):
            if ast.unparse(item.test)=="role != 'qualify'":item.test=ast.Constant(True)
            return self.generic_visit(item)
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
    root=tmp_path/'out';q=root/'qualification';q.mkdir(parents=True);populate_q15(root)
    component=q/'unit-normalization-component.json.gz';component.write_bytes(b'opaque synthetic component')
    monkeypatch.setattr(export,'APPROVED',{export.COMPONENT:{'sha256':job.sha256_file(component)}})
    value=proof();value['fixture_component_sha256']=job.sha256_file(component)
    (q/'qualification-summary.json').write_text(json.dumps(value))
    provenance=dict(schema=evidence.PROVENANCE_SCHEMA,specification=evidence.reference_spec(),all_old_driver_sources_authenticated=True,full_qualification_inventory_authenticated=True,original_qualification_worker_exit_code=1,financial_worker_started=False,financial_authority=False,qualification_state_adopted=False,original_raw_request_utf8=(HERE/evidence.ORIGIN['request_file']).read_text())
    (q/'reference-evidence.json').write_text(json.dumps(provenance))
    value['reference_evidence_sha256']=job.sha256_file(q/'reference-evidence.json');(q/'qualification-summary.json').write_text(json.dumps(value))
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
    q=tmp_path/'qualification';q.mkdir();populate_q15(tmp_path);(q/'unit-normalization-component.json.gz').write_bytes(b'changed component')
    value=proof();monkeypatch.setattr(export,'APPROVED',{export.COMPONENT:{'sha256':value['fixture_component_sha256']}})
    provenance=dict(schema=evidence.PROVENANCE_SCHEMA,specification=evidence.reference_spec(),all_old_driver_sources_authenticated=True,full_qualification_inventory_authenticated=True,original_qualification_worker_exit_code=1,financial_worker_started=False,financial_authority=False,qualification_state_adopted=False,original_raw_request_utf8=(HERE/evidence.ORIGIN['request_file']).read_text())
    (q/'reference-evidence.json').write_text(json.dumps(provenance));value['reference_evidence_sha256']=job.sha256_file(q/'reference-evidence.json')
    (q/'qualification-summary.json').write_text(json.dumps(value))
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


@pytest.mark.parametrize('field,bad',[('reference_evidence_reused',False),('original_reference_compiler_logs_available',True),
    ('source_compiler_check_qualified',False),('source_preparations',True),('source_compiler_financial_transitions',1),
    ('reference_financial_transitions_reexecuted',1),('old_reference_runtime_records_restored',0),('old_synthetic_wires_restored',17),
    ('reference_report_rechecked',False),('reference_report_financial_transitions',False),('reference_report_financial_transitions',1),
    ('reference_report_origin','OLD_RUNTIME_REPORT'),
    ('reference_reuse_admission_sha256','0'*64),('reference_evidence_sha256','bad')])
def test_new_q15_reference_compiler_no_advance_and_restore_fields_required(field,bad):
    good=proof();export.qualification(good);good[field]=bad
    with pytest.raises(ValueError):export.qualification(good)
    del good[field]
    with pytest.raises(ValueError):export.qualification(good)


def test_new_failure_paths_are_explicit_and_normal_q15_excludes_compiler_inflight():
    assert len(export.QUALIFICATION_FILES)==9 and 'reference-evidence.json' in export.QUALIFICATION_FILES
    for name in ('proof/source-compiler-check.inflight','source-check/contexts/native/hydrated.json',
        'reference-report/contexts/quote/quote.json.gz','source-check/contexts/a.json.tmp-abc'):
        assert export.failure_member(name)
    for name in ('source-check/book/checkpoint.json.gz','reference-report/private.key','source-check/contexts/../secret.json'):
        assert not export.failure_member(name)
    assert 'source-compiler-check.inflight' not in export.QUALIFICATION_FILES


def test_failure_compiler_inflight_omission_predicate_removal_falsifier(tmp_path):
    root=tmp_path/'out';q=root/'qualification';q.mkdir(parents=True);populate_q15(root)
    (q/'source-compiler-check.inflight').write_bytes(b'known-stopped opaque preparation progress')
    export.qualification_only_inventory(root)
    # Old frozen source refuses the same new path, proving the explicit versioned delta is required.
    with pytest.raises(ValueError):export.previous.qualification_only_inventory(root)



def successful_snapshot_fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(export,'memory_bytes',lambda:dict(MemAvailable=20*1024**3))
    monkeypatch.setattr(export.shutil,'disk_usage',lambda path:SimpleNamespace(free=20*1024**3))
    root=tmp_path/'out';populate_q15(root);q=root/'qualification';component=q/'unit-normalization-component.json.gz'
    component.write_bytes(b'SYNTHETIC_OPAQUE_COMPONENT');monkeypatch.setattr(export,'APPROVED',{export.COMPONENT:{'sha256':job.sha256_file(component)}})
    value=proof();provenance=dict(schema=evidence.PROVENANCE_SCHEMA,specification=evidence.reference_spec(),
        all_old_driver_sources_authenticated=True,full_qualification_inventory_authenticated=True,original_qualification_worker_exit_code=1,
        financial_worker_started=False,financial_authority=False,qualification_state_adopted=False,
        original_raw_request_utf8=(HERE/evidence.ORIGIN['request_file']).read_text())
    (q/'reference-evidence.json').write_text(json.dumps(provenance));value['reference_evidence_sha256']=job.sha256_file(q/'reference-evidence.json')
    value['fixture_component_sha256']=job.sha256_file(component);(q/'qualification-summary.json').write_text(json.dumps(value))
    checked=dict(origin='NEW_HOSTED_SOURCE_COMPILER_CHECK',source_preparations=2,financial_transitions=0,actual_logs=['synthetic'])
    (q/'source-compiler-check.inflight').write_text(json.dumps(checked))
    (q/'unit-normalization-source-proof.json').write_text(json.dumps(dict(source_compiler_check=checked)))
    request=tmp_path/'new-request.json';request.write_text(json.dumps(dict(protocol_sha256='c'*64)))
    receipt=dict(schema=export.RECEIPT_SCHEMA,arm='P01',stage=export.STAGE,run_id='123',head='a'*40,
        request_sha256=job.sha256_file(request),protocol_sha256='c'*64,strict_parent_outer_sha256=export.OUTER,
        status='SYNTHETIC_STOPPED_Q15',production_contacted=False,qualification_exported=False,
        qualification_worker=dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None))
    return root,receipt,request


def test_actual_frozen_q_inventory_refuses_progress_and_new_exact_snapshot_seals15(tmp_path,monkeypatch):
    import io,tarfile
    from seal import decrypt
    root,value,request=successful_snapshot_fixture(tmp_path,monkeypatch)
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    strict=tmp_path/'strict-out';__import__('shutil').copytree(root,strict)
    before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
    # The actual pinned legacy Q function (same compiled code) rejects the inflight extra.
    with pytest.raises(ValueError):export._scope()['preserve_qualification'](dict(value),strict,tmp_path/'strict-public.json',b'x'*32,request)
    out=tmp_path/'public/receipt.json';out.parent.mkdir()
    export.preserve_qualification(value,root,out,b'x'*32,request)
    assert {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}==before
    asset=value['qualification_encrypted_output'];plain=tmp_path/'new-q15.tar.gz'
    decrypt(out.parent/asset['name'],plain,b'x'*32,asset['sha256'])
    with tarfile.open(fileobj=io.BytesIO(plain.read_bytes()),mode='r:gz') as tar:
        manifest=json.loads(tar.extractfile('manifest.json').read())
        assert len(manifest['members'])==15 and 'qualification/source-compiler-check.inflight' not in manifest['members']
        for name,entry in manifest['members'].items():
            data=tar.extractfile(name).read();assert entry==dict(bytes=len(data),sha256=__import__('hashlib').sha256(data).hexdigest())
    assert (root/'qualification/source-compiler-check.inflight').exists()


@pytest.mark.parametrize('kind',['unknown','refused','wrong_extra','divergent_progress','changed_copy'])
def test_snapshot_unknown_extra_divergent_log_or_copy_failure_refuses(kind,tmp_path,monkeypatch):
    root,value,request=successful_snapshot_fixture(tmp_path,monkeypatch)
    if kind=='unknown':value['qualification_worker']['stopped']=False
    if kind=='refused':value['qualification_worker']['exit_code']=1
    if kind=='wrong_extra':(root/'qualification/opaque-extra.json').write_bytes(b'not allowed')
    if kind=='divergent_progress':(root/'qualification/source-compiler-check.inflight').write_bytes(b'{"changed":true}')
    if kind=='changed_copy':
        original=export.shutil.copyfile
        def copy(a,b):original(a,b);Path(b).write_bytes(b'changed copy')
        monkeypatch.setattr(export.shutil,'copyfile',copy)
    with pytest.raises(ValueError):export.preserve_qualification(value,root,tmp_path/'public.json',b'x'*32,request)
    assert (root/'qualification/source-compiler-check.inflight').exists() and not value['qualification_exported']


def test_progress_whole_object_guard_removal_accepts_divergent_log_falsifier(tmp_path,monkeypatch):
    root,value,request=successful_snapshot_fixture(tmp_path,monkeypatch)
    (root/'qualification/source-compiler-check.inflight').write_text('{"changed":true}')
    calls=[];monkeypatch.setitem(export._scope(),'preserve_qualification',lambda *a:calls.append(a[1]))
    with pytest.raises(ValueError):export.preserve_qualification(value,root,tmp_path/'public.json',b'x'*32,request)
    node=next(n for n in ast.parse(Path(export.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='preserve_qualification')
    guard=next(n for n in ast.walk(node) if isinstance(n,ast.Call) and any(isinstance(x,ast.Constant)
        and x.value=='REFERENCE_ENTIRE_EARLY_COMPILER_PROGRESS_EQUALS_FINAL_TYPED_PROOF' for x in ast.walk(n)))
    guard.args[0]=ast.Constant(True);ns=dict(vars(export))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-full-progress-equivalence>','exec'),ns)
    ns['preserve_qualification'](value,root,tmp_path/'public.json',b'x'*32,request)
    assert calls and calls[0]!=root

@pytest.mark.parametrize('kind',['duplicate','root_uid','root_gid'])
def test_actual_inspector_rejects_duplicate_bind_and_root_with_guard_removal(kind,tmp_path,monkeypatch):
    name='capital-system-p01-iac-reference-worker-123-1'
    mounts={'/variant','/frozen','/driver','/out','/old','/celg-input','/celg-input-descriptor.json','/evidence'}
    user='0:1001' if kind=='root_uid' else '1001:0' if kind=='root_gid' else '1001:1001'
    uid,gid=map(int,user.split(':'))
    value=dict(Name='/'+name,Id='a'*64,Image=job.inspector_source.EXECUTION_IMAGE,
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
            PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
        Mounts=[dict(Type='bind',Destination=n,RW=n=='/out') for n in mounts],
        Config=dict(WorkingDir='/variant',User=user,Labels={'research.study':'full-system-search-20261029',
            'research.role':'worker'},Env=['FULL_SYSTEM_HOSTED=1'],Cmd=job.entrypoint('economic')))
    if kind=='duplicate':value['Mounts'].append(deepcopy(value['Mounts'][0]))
    monkeypatch.setattr(job.inspector_source,'os',SimpleNamespace(getuid=lambda:uid,getgid=lambda:gid))
    monkeypatch.setattr(job.inspector_source,'subprocess',SimpleNamespace(run=lambda *a,**kw:SimpleNamespace(stdout=json.dumps([value]).encode())))
    with pytest.raises(ValueError,match='EIGHT_UNIQUE_BIND'):job.inspect(name,'a'*64)
    monkeypatch.setattr(job,'inspection_bindings',lambda v:None)
    assert job.inspect(name,'a'*64)==value


def test_actual_marker_and_successful_snapshot_share_parent_without_collision(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    root,value,request=successful_snapshot_fixture(tmp_path,monkeypatch)
    original=export.preserve_qualification;calls=[]
    monkeypatch.setattr(export,'preserve_qualification',lambda *a,**k:pytest.fail('marker cannot enter Q snapshot'))
    marker=tmp_path/'p01-iac-reference-export-probe'
    export.qualify_export(marker,request)
    assert marker.is_dir() and not (tmp_path/'p01-iac-reference-qualification-seal-snapshot').exists()
    monkeypatch.setattr(export,'preserve_qualification',original)
    delegate=export._scope()['preserve_qualification']
    def counted(*args):calls.append(args[1]);return delegate(*args)
    monkeypatch.setitem(export._scope(),'preserve_qualification',counted)
    public=tmp_path/'public/receipt.json';public.parent.mkdir()
    export.preserve_qualification(value,root,public,b'x'*32,request)
    assert calls==[tmp_path/'p01-iac-reference-qualification-seal-snapshot']
    assert marker.is_dir() and (marker/'source/marker.txt').is_file()
    with pytest.raises(FileExistsError):export.preserve_qualification(value,root,public,b'x'*32,request)
    assert len(calls)==1


@pytest.mark.parametrize('kind',['duplicate_over_old_total','snapshot_over_bound','memory','disk'])
def test_snapshot_inherited_limit_duplicate_allowance_and_actual_copy_reserve(kind,tmp_path,monkeypatch):
    root,value,request=successful_snapshot_fixture(tmp_path,monkeypatch)
    progress=root/'qualification/source-compiler-check.inflight'
    total=sum(p.stat().st_size for p in root.rglob('*') if p.is_file());size=total-progress.stat().st_size
    calls=[];monkeypatch.setitem(export._scope(),'preserve_qualification',lambda *a:calls.append(a[1]))
    if kind=='duplicate_over_old_total':
        monkeypatch.setattr(export,'QUALIFICATION_LIMIT',size)
        assert size<total<=2*size
        export.preserve_qualification(value,root,None,None,None)
        assert len(calls)==1
    else:
        if kind=='snapshot_over_bound':monkeypatch.setattr(export,'QUALIFICATION_LIMIT',size-1)
        if kind=='memory':monkeypatch.setattr(export,'memory_bytes',lambda:dict(MemAvailable=0))
        if kind=='disk':monkeypatch.setattr(export.shutil,'disk_usage',lambda path:SimpleNamespace(free=10*1024**3))
        with pytest.raises(ValueError):export.preserve_qualification(value,root,None,None,None)
        assert calls==[] and progress.exists()
