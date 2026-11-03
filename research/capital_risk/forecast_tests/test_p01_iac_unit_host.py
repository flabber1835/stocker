"""New native host/crypto/UNKNOWN contracts, all stubs or synthetic payloads."""
import ast
from copy import deepcopy
import json
import io
import tarfile
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace

import pytest
import yaml

HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import p01_iac_unit_job as job
import p01_iac_unit_export as export
import p01_iac_unit_parent as parent


def proof():
    return dict(status='OWN628_IAC_UNIT_INPUT_AND_TWO_SESSION_FAST_REFERENCE_QUALIFIED',financial_authority=False,
        financial_predecessor_authorized=False,component_transitions=2,qualified_through='2020-07-02',
        epoch_zero_outer_sha256=export.OUTER,input_zero_outer_sha256='d'*64,
        input_document_sha256='a'*64,successor_input_sha256='b'*64,original_inputs=11,successor_inputs=12,
        input_adoptions=1,actual_fast_reference_full_components_equal=True,actual_role_and_full_state_checks=2,
        source_epoch_boundary_reemitted=False,unit_normalization_qualified=True,
        unit_target_independence_qualified=True,source_scope_falsifiers_qualified=True)


def test_actual_admitted628_outer_binding_and_no_wrong_parent_imports():
    actual='da8f0ef0e04f70f1f388ee68ee1bb70d923dcb35b41f53e4d39b3e1e4b81f0ee'
    assert parent.ROOT_ADMISSION=='06157fd8d37a92bd5e623081374e00b2b8253b6750fa761234b19a467c798ef6'
    assert parent.OUTER==export.OUTER==actual
    good=proof();good['epoch_zero_outer_sha256']=actual;export.qualification(good)
    for name in ('parent','epoch','job','export','probe'):
        tree=ast.parse((HERE/('p01_iac_unit_'+name+'.py')).read_bytes())
        assert not any(isinstance(n,ast.ImportFrom) and n.module=='p01_native_resume_parent'
            for n in ast.walk(tree))


def test_actual628_epoch_outer_predicate_removal_falsifier():
    actual='da8f0ef0e04f70f1f388ee68ee1bb70d923dcb35b41f53e4d39b3e1e4b81f0ee'
    old='0ea1fbdbc50c17c53af5380c18e734f97512df859d22a4f3e6600c56cba5ae19'
    good=proof();good['epoch_zero_outer_sha256']=actual;export.qualification(good)
    bad=deepcopy(good);bad['epoch_zero_outer_sha256']=old
    with pytest.raises(ValueError):export.qualification(bad)
    tree=ast.parse(Path(export.__file__).read_bytes())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='qualification')
    target=next(n for n in ast.walk(fn) if isinstance(n,ast.Compare)
        and ast.unparse(n.left)=="proof['epoch_zero_outer_sha256']")
    target.left=ast.Constant(True);target.comparators=[ast.Constant(True)]
    ns=dict(vars(export));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<actual628-epoch-outer-predicate-removal>','exec'),ns)
    ns['qualification'](bad)


def test_actual_new_input_document_is_bound_to_admitted628_and_declared_axis():
    from p01_iac_unit_contract import specification,document,encoded,INPUT,END,MAXIMUM,FIRST
    spec=specification();value=document()
    assert spec['root_admission_descriptor_sha256']=='06157fd8d37a92bd5e623081374e00b2b8253b6750fa761234b19a467c798ef6'
    assert value['financial_parent']['outer_sha256']==parent.OUTER
    assert value['predecessor_checkpoint_sha256']==parent.INNER
    assert value['predecessor_state_sha256']==parent.STATE and value['predecessor_input_sha256']==parent.INPUT
    assert (HERE/INPUT).read_bytes()==encoded(value)
    assert END=='2021-06-29' and MAXIMUM==251 and FIRST==('2020-07-01','2020-07-02')
    prior=json.loads((HERE/parent.PRIOR).read_bytes())['sources']
    assert len(prior)==468 and set(job.SOURCES)==set(prior)|{parent.PRIOR}|set(job.NEW)


def receipt():
    return dict(schema=export.RECEIPT_SCHEMA,arm='P01',stage=export.STAGE,run_id='123',head='a'*40,
        request_sha256='b'*64,protocol_sha256='c'*64,strict_parent_outer_sha256='d'*64,
        status='BEFORE_EXPORT_PROBE',production_contacted=False,qualification_exported=False)


def test_public_asset_and_error_values_are_only_declared_scalar_metadata(tmp_path):
    asset=dict(name='p01-iac-unit-qualification.tar.crseal',bytes=100,sha256='a'*64,manifest_sha256='b'*64,compression='TAR_GZIP_V1')
    good=dict(receipt(),qualification_encrypted_output=asset,export_error=dict(type='ValueError',code='EXPORT_OPERATION_FAILED'))
    export.write_receipt(tmp_path/'good.json',good)
    assert json.loads((tmp_path/'good.json').read_bytes())==good
    for key,bad in [('name',{'opaque':'payload'}),('name','../private'),('bytes',True),('bytes',0),('bytes',{'value':100}),
        ('sha256',['opaque']),('manifest_sha256','wrong'),('compression',{'opaque':'payload'}),('compression','unknown')]:
        wrong=deepcopy(good);wrong['qualification_encrypted_output'][key]=bad
        with pytest.raises((ValueError,TypeError)):export.write_receipt(tmp_path/'bad.json',wrong)
        assert not (tmp_path/'bad.json').exists()
    for key,bad in [('type',{'opaque':'payload'}),('type','private payload text'),('code',{'opaque':'payload'}),('code','raw error payload')]:
        wrong=deepcopy(good);wrong['export_error'][key]=bad
        with pytest.raises((ValueError,TypeError)):export.write_receipt(tmp_path/'bad.json',wrong)


def test_actual_component_flags_required_before_fresh_finance():
    q=proof();request=dict(input_document_sha256='a'*64,successor_input_sha256='b'*64,original_inputs=11,
        successor_inputs=12,qualified_full_runtime_sessions=2,qualified_through='2020-07-02')
    spec={'outer_sha256':export.OUTER};job.check_qualification(q,request,spec)
    for key in ('unit_normalization_qualified','unit_target_independence_qualified','source_scope_falsifiers_qualified'):
        for mode in ('false','missing'):
            wrong=deepcopy(q)
            if mode=='false':wrong[key]=False
            else:del wrong[key]
            with pytest.raises((ValueError,KeyError)):job.check_qualification(wrong,request,spec)
    tree=ast.parse(Path(job.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='check_qualification')
    target=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='all')
    target.func=ast.Name(id='removed_guard',ctx=ast.Load());ns=dict(vars(job),removed_guard=lambda *args:True)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-component-flags>','exec'),ns)
    bad=deepcopy(q);bad['unit_normalization_qualified']=False
    ns['check_qualification'](bad,request,spec)


def qualification_failure_fixture(tmp_path):
    root=tmp_path/'financial-output';root.mkdir();qual=tmp_path/'p01-iac-unit-qualification-output';qual.mkdir()
    files={'spec.json':b'{}','source-map.json':b'{}','worker-inspect.json':b'{"known":"stopped"}',
        'worker.log':b'actual partial failure log','proof/unit-normalization-component.inflight':b'partial gzip',
        'reference/book/checkpoint.json.gz':b'raw partial checkpoint',
        'reference/book/daily.jsonl':b'{"closed":1}\n{"partial":',
        'reference/book/checkpoint.json.gz.tmp-abc':b'inflight checkpoint',
        'reference/lineage/original-checkpoints/book/checkpoint.json.gz':b'all ancestry retained',
        'reference/contexts/discovery-fnf-hydration.json':b'{}',
        'fast/book/watch.jsonl':b'{"partial attempt":'}
    for name,raw in files.items():
        p=qual/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    for name in ('spec.json','request.json','source-map.json','source-bindings.json'):(root/name).write_bytes(b'{}')
    stop=dict(stopped=True,exit_code=1,oom_killed=False,wait_error=None)
    return root,qual,files,stop


def test_known_negative_qualifier_preserves_all_raw_failure_branches_in_qstage_only(tmp_path,monkeypatch):
    root,qual,files,stop=qualification_failure_fixture(tmp_path);value=dict(receipt(),qualification_worker=stop)
    seen=[]
    def sealed(source,target,key,request,*,stage):
        seen.append(stage);assert stage==export.QUALIFICATION_STAGE
        scope=json.loads((source/'qualification-failure/export-scope.json').read_bytes())
        assert set(scope['preserved_members'])==set(files) and scope['ancestry_excluded']==[]
        assert not scope['financial_authority'] and not scope['financial_worker_launched'] and not scope['incomplete_files_parsed']
        for name,raw in files.items():assert (source/'qualification-failure'/name).read_bytes()==raw
        return dict(name=target.name,bytes=123,sha256='a'*64,manifest_sha256='b'*64,compression='TAR_GZIP_V1')
    monkeypatch.setattr(export,'sealed',sealed)
    path=tmp_path/'public/receipt.json';export.finish(value,root,path,b'x'*32,tmp_path/'request.json',known=True)
    assert seen==[export.QUALIFICATION_STAGE]
    assert value['status']=='QUALIFICATION_ONLY_KNOWN_STOP_REFUSAL_PRESERVED'
    assert value['qualification_exported'] and not value['encrypted_output_exported']
    assert 'worker' not in value and 'encrypted_output' not in value


def test_already_sealed_successful_q_is_not_resealed_on_prefinance_refusal(tmp_path,monkeypatch):
    root,qual,files,stop=qualification_failure_fixture(tmp_path);stop['exit_code']=0
    asset=dict(name='p01-iac-unit-qualification.tar.crseal',bytes=123,sha256='a'*64,manifest_sha256='b'*64,compression='TAR_GZIP_V1')
    value=dict(receipt(),qualification_worker=stop,qualification_exported=True,qualification_encrypted_output=asset)
    monkeypatch.setattr(export,'sealed',lambda *args,**kw:pytest.fail('already sealed Q must not be changed'))
    export.finish(value,root,tmp_path/'public/receipt.json',b'x'*32,tmp_path/'request.json',known=True)
    assert value['qualification_encrypted_output']==asset and not (root/'qualification-failure').exists()


@pytest.mark.parametrize('kind',['unknown','opaque_path','disk_reserve'])
def test_qualification_failure_requires_known_stop_allowlisted_paths_and_reserve(tmp_path,monkeypatch,kind):
    root,qual,files,stop=qualification_failure_fixture(tmp_path)
    if kind=='unknown':stop['stopped']=False
    if kind=='opaque_path':(qual/'opaque-secret.bin').write_bytes(b'not allowed')
    if kind=='disk_reserve':monkeypatch.setattr(export.shutil,'disk_usage',lambda path:SimpleNamespace(free=0))
    with pytest.raises(ValueError):export.preserve_qualification_failure(root,qual,stop)
    assert not (root/'qualification-failure').exists()


def test_qualification_unknown_never_copies_or_seals_mutable_qstate(tmp_path,monkeypatch):
    root,qual,files,stop=qualification_failure_fixture(tmp_path);value=dict(receipt(),qualification_worker=stop)
    monkeypatch.setattr(export,'preserve_qualification_failure',lambda *a:pytest.fail('UNKNOWN qstate copy'))
    monkeypatch.setattr(export,'sealed',lambda *a,**kw:pytest.fail('UNKNOWN qstate seal'))
    export.finish(value,root,tmp_path/'public/receipt.json',b'x'*32,tmp_path/'request.json',known=False)
    assert not value['encrypted_output_exported'] and 'encrypted_output' not in value


def test_known_qstop_guard_removal_falsifier(tmp_path):
    root,qual,files,stop=qualification_failure_fixture(tmp_path);stop['stopped']=False
    with pytest.raises(ValueError):export.preserve_qualification_failure(root,qual,stop)
    tree=ast.parse(Path(export.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='preserve_qualification_failure')
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and any(isinstance(v,ast.Constant)
        and v.value=='P01_IAC_ONLY_ACTUAL_KNOWN_STOPPED_QUALIFIER_FAILURE_STATE' for v in ast.walk(n)))
    guard.args[0]=ast.Constant(True);ns=dict(vars(export))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-qualifier-stop>','exec'),ns)
    assert ns['preserve_qualification_failure'](root,qual,stop)['qualifier_stop']['stopped'] is False


def test_actual_negative_q_cipher_full_gcm_and_inventory_before_refusal_payload(tmp_path,monkeypatch):
    from seal import decrypt
    root,qual,files,stop=qualification_failure_fixture(tmp_path);value=dict(receipt(),qualification_worker=stop)
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    request=tmp_path/'request.json';request.write_text(json.dumps(dict(protocol_sha256='c'*64)))
    path=tmp_path/'public/receipt.json';path.parent.mkdir();key=b'x'*32
    export.finish(value,root,path,key,request,known=True)
    asset=value['qualification_encrypted_output'];encrypted=path.parent/asset['name']
    assert export.sha256_file(encrypted)==asset['sha256'] and encrypted.stat().st_size==asset['bytes']
    plain=tmp_path/'authenticated.tar.gz';decrypt(encrypted,plain,key,asset['sha256'])
    with tarfile.open(fileobj=io.BytesIO(plain.read_bytes()),mode='r:gz') as tar:
        manifest_raw=tar.extractfile('manifest.json').read();manifest=json.loads(manifest_raw)
        assert __import__('hashlib').sha256(manifest_raw).hexdigest()==asset['manifest_sha256']
        assert manifest['stage']==export.QUALIFICATION_STAGE and not any(n.startswith('book/') for n in manifest['members'])
        for name,entry in manifest['members'].items():
            raw=tar.extractfile(name).read();assert len(raw)==entry['bytes'] and __import__('hashlib').sha256(raw).hexdigest()==entry['sha256']
        scope=json.loads(tar.extractfile('qualification-failure/export-scope.json').read())
        assert scope['qualifier_stop']==stop and scope['financial_snapshot_or_predecessor_admitted'] is False
    (root/'book').mkdir();(root/'book/checkpoint.json.gz').write_bytes(b'wrong financial namespace')
    with pytest.raises(ValueError):export.qualification_only_inventory(root)


def test_proven_stopped_run_and_durable_inspection_unchanged():
    import alpaca_fit_job
    assert job.stopped_run is alpaca_fit_job.stopped_run
    tree=ast.parse(Path(alpaca_fit_job.__file__).read_bytes())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='stopped_run')
    guarded=next(n for n in fn.body if isinstance(n,ast.Try) and n.finalbody)
    assert any(isinstance(n,ast.Call) and ast.unparse(n.func)=='os.fsync' for n in ast.walk(guarded))
    assert 'wait_error' in ast.unparse(fn)


def test_actual_synthetic_export_marker_in_new_scope(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    request=tmp_path/'request.json';request.write_text(json.dumps(dict(protocol_sha256='c'*64)))
    value=export.qualify_export(tmp_path/'probe',request)
    assert value['status']=='P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED'
    assert value['source_adapter_sha256']==job.sha256_file(Path(export.__file__))
    assert value['synthetic_marker_only'] and not value['market_or_financial_state_processed']


@pytest.mark.parametrize('field,value',[('component_transitions',0),('component_transitions',3),
    ('component_transitions',True),('component_transitions',2.0),('original_inputs',10),
    ('qualified_through','2020-07-01'),('status','OWN627_NATIVE_EPOCH_AND_THREE_SESSIONS_QUALIFIED'),
    ('input_adoptions',2),('source_epoch_boundary_reemitted',True),('input_document_sha256','not-a-hash')])
def test_native_gate_requires_actual_two_days_same_input_and_no_boundary(field,value):
    good=proof();export.qualification(good);bad=deepcopy(good);bad[field]=value
    with pytest.raises(ValueError):export.qualification(bad)


def test_two_session_gate_guard_removal_falsifier():
    bad=proof();bad['component_transitions']=1
    with pytest.raises(ValueError):export.qualification(bad)
    fn=next(n for n in ast.parse(Path(export.__file__).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name=='qualification')
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need')
    guard.args[0]=ast.Constant(True);namespace=dict(vars(export))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<two-session-gate-removal-falsifier>','exec'),namespace)
    namespace['qualification'](bad)
    missing=proof();del missing['qualified_through']
    with pytest.raises(KeyError):export.qualification(missing)
    namespace['qualification'](missing)


def test_two_session_gate_requires_endpoint_exact_input_and_reference():
    good=proof();request=dict(input_document_sha256='a'*64,successor_input_sha256='b'*64,
        original_inputs=11,successor_inputs=12,qualified_full_runtime_sessions=2,qualified_through='2020-07-02')
    job.check_qualification(good,request,dict(outer_sha256=export.OUTER))
    missing=deepcopy(good);del missing['qualified_through']
    with pytest.raises(KeyError):export.qualification(missing)
    for field,value in [('qualified_full_runtime_sessions',3),('qualified_through','2020-07-01'),
                        ('input_document_sha256','0'*64),('successor_inputs',11),('successor_input_sha256','0'*64)]:
        wrong=deepcopy(request);wrong[field]=value
        with pytest.raises(ValueError):job.check_qualification(good,wrong,dict(outer_sha256=export.OUTER))
    for field,value in [('actual_fast_reference_full_components_equal',False),('actual_role_and_full_state_checks',1),
                        ('successor_inputs',11),('input_adoptions',2),('input_zero_outer_sha256',export.OUTER)]:
        wrong=deepcopy(good);wrong[field]=value
        with pytest.raises(ValueError):export.qualification(wrong)


def test_actual_full_reference_predicate_removal_falsifier():
    bad=proof();bad['actual_fast_reference_full_components_equal']=False
    with pytest.raises(ValueError):export.qualification(bad)
    tree=ast.parse(Path(export.__file__).read_bytes())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='qualification')
    target=next(n for n in ast.walk(fn) if isinstance(n,ast.Compare)
        and ast.unparse(n.left)=="proof['actual_fast_reference_full_components_equal']")
    target.left=ast.Constant(True);target.comparators=[ast.Constant(True)]
    ns=dict(vars(export));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<full-reference-predicate-removal>','exec'),ns)
    ns['qualification'](bad)


@pytest.mark.parametrize('field,value',[('fresh_from_original628',False),('qualification_state_adopted',True),
    ('successor_input_sha256','0'*64),('source_epoch_boundary_reemitted',True),('input_adoptions',2),
    ('original_inputs',11.0),('successor_inputs',12.0),('maximum_transitions',251.0),
    ('processing_endpoint','2020-07-02'),('full_measurement_end','2021-06-29')])
def test_finance_gate_binds_fresh_parent_exact_input_and_scope(field,value):
    request=dict(input_document_sha256='a'*64,successor_input_sha256='b'*64,
        maximum_financial_transitions=251,processing_endpoint='2021-06-29',full_measurement_end='2026-07-31')
    outcome=dict(input_document_sha256='a'*64,successor_input_sha256='b'*64,original_inputs=11,successor_inputs=12,
        fresh_from_original628=True,qualification_state_adopted=False,source_epoch_boundary_reemitted=False,
        input_adoptions=1,maximum_transitions=251,processing_endpoint='2021-06-29',full_measurement_end='2026-07-31')
    job.check_financial_input(outcome,proof(),request)
    outcome[field]=value
    with pytest.raises(ValueError):job.check_financial_input(outcome,proof(),request)
    if field=='fresh_from_original628':
        tree=ast.parse(Path(job.__file__).read_bytes())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='check_financial_input')
        guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need')
        guard.args[0]=ast.Constant(True);ns=dict(vars(job))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
            '<fresh-finance-gate-removal>','exec'),ns)
        ns['check_financial_input'](outcome,proof(),request)


def test_public_receipt_and_unknown_writer_no_snapshot(tmp_path,monkeypatch):
    value=receipt();value['shares']=1
    with pytest.raises(ValueError):export.write_receipt(tmp_path/'public.json',value)
    monkeypatch.setattr(export,'sealed',lambda *a,**kw:pytest.fail('UNKNOWN may not snapshot'))
    value=receipt();value['status']='ACTIVE_WRITER_STOP_UNKNOWN_NO_MUTABLE_SNAPSHOT'
    export.finish(value,tmp_path,tmp_path/'public.json',None,tmp_path/'request.json',known=False)
    assert value['encrypted_output_exported'] is False
    with pytest.raises(ValueError):export.finish(value,tmp_path,tmp_path/'public.json',None,tmp_path/'request.json',known=True)


@pytest.mark.parametrize('logs',['normal','failed_only','partial_failed'])
def test_exact_fourteen_member_qualifier_proofs_not_book(tmp_path,monkeypatch,logs):
    root=tmp_path/'out';(root/'qualification').mkdir(parents=True)
    for n in ('spec.json','request.json','source-bindings.json','source-map.json'):(root/n).write_text('{}')
    for n in (*export.QUALIFICATION_FILES,'worker-inspect.json'):(root/'qualification'/n).write_text('{}')
    (root/'qualification/qualification-summary.json').write_text(json.dumps(proof()))
    if logs!='failed_only':(root/'qualification/worker.log').write_text('synthetic')
    if logs!='normal':(root/'qualification/log-copy-failure.json').write_text('{"type":"OSError"}')
    value=receipt();value['qualification_worker']=dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None)
    value['qualification_log_copy_failed']=logs!='normal';seen=[]
    monkeypatch.setattr(export,'sealed',lambda *a,**kw:seen.append(kw['stage']) or
        dict(name='q',bytes=1,sha256='a'*64,manifest_sha256='b'*64,compression='TAR_GZIP_V1'))
    export.preserve_qualification(value,root,tmp_path/'public.json',b'x'*32,tmp_path/'request.json')
    assert seen==[export.QUALIFICATION_STAGE] and value['qualification_exported']
    (root/'book').mkdir();(root/'book/checkpoint.json.gz').write_bytes(b'forbidden_disposable_state')
    with pytest.raises(ValueError):export.preserve_qualification(value,root,tmp_path/'public.json',b'x'*32,tmp_path/'request.json')


def test_exact_iac_worker_entrypoint_and_quote_mounts(tmp_path,monkeypatch):
    import full_system_benchmark as source
    monkeypatch.setattr(source.os,'getuid',lambda:1001,raising=False);monkeypatch.setattr(source.os,'getgid',lambda:1001,raising=False)
    for mode in ('qualify','economic','review'):
        args=job.worker_command('capital-system-p01-iac-unit-worker-123-1',mode,
            tmp_path/'source',tmp_path/'frozen',tmp_path/'out',tmp_path/'old',tmp_path/'quote',
            None if mode=='qualify' else tmp_path/'evidence')
        assert args[args.index('-B'):]==job.entrypoint(mode) and 'none' in args and '--read-only' in args
        assert any('target=/celg-input,readonly' in v for v in args)
        assert any('target=/evidence,readonly' in v for v in args)==(mode!='qualify')


@pytest.mark.parametrize('role',['qualify','worker','review'])
def test_actual_inspector_new_namespace_cli_and_readonly_quotes(tmp_path,monkeypatch,role):
    name='capital-system-p01-iac-unit-'+role+'-123-1'
    mounts={'/variant','/frozen','/driver','/out','/old','/celg-input','/celg-input-descriptor.json'}
    if role!='qualify':mounts.add('/evidence')
    value=dict(Name='/'+name,Id='a'*64,Image=job.inspector_source.EXECUTION_IMAGE,
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
            PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
        Mounts=[dict(Type='bind',Destination=n,RW=n=='/out') for n in mounts],
        Config=dict(WorkingDir='/variant',User='1001:1001',Labels={'research.study':'full-system-search-20261029',
            'research.role':'review' if role=='review' else 'worker'},Env=['FULL_SYSTEM_HOSTED=1'],
            Cmd=job.entrypoint(dict(qualify='qualify',worker='economic',review='review')[role])))
    monkeypatch.setattr(job.inspector_source,'os',SimpleNamespace(getuid=lambda:1001,getgid=lambda:1001))
    monkeypatch.setattr(job.inspector_source,'subprocess',SimpleNamespace(run=lambda *a,**kw:SimpleNamespace(stdout=json.dumps([value]).encode())))
    assert job.inspect(name,'a'*64)==value
    value['Config']['Cmd'][2]='/driver/p01_factual_batch_run.py'
    with pytest.raises(ValueError):job.inspect(name,'a'*64)
    value['Config']['Cmd']=job.entrypoint(dict(qualify='qualify',worker='economic',review='review')[role])
    next(v for v in value['Mounts'] if v['Destination']=='/celg-input')['RW']=True
    with pytest.raises(ValueError):job.inspect(name,'a'*64)


def test_reconstruction_reuses_predecessor223_not_current224(tmp_path,monkeypatch):
    old=tmp_path/'old';old.mkdir();driver=tmp_path/'driver';driver.mkdir()
    binding=dict(parameters={'family':'original'},all_sources={'old.py':'a'*64})
    mapping=dict(predecessor_financial_sources={'old.py':'a'*64},successor_financial_sources={'new.py':'b'*64})
    for name,value in [('source-bindings.json',binding),('source-map.json',mapping)]:
        (old/name).write_text(json.dumps(value))
    (driver/job.SOURCE_MAP).write_text(json.dumps(mapping));monkeypatch.setattr(job,'HERE',driver)
    def build(frozen,destination,parameters):destination.mkdir();(destination/'old.py').write_text('source');return binding
    seen=[]
    def render(files,expected,destination,*,financial_sources):seen.append(financial_sources);destination.mkdir();return mapping
    monkeypatch.setattr(job,'build',build);monkeypatch.setattr(job,'write_disjoint',render)
    job.reconstruct(tmp_path/'frozen',old,tmp_path);assert seen==[mapping['predecessor_financial_sources']]


def test_capped_workflow_budget_trigger_and_upload_timeout_falsifier():
    value=yaml.safe_load((HERE.parents[1]/'.github/workflows/p01_iac_unit_financial.yml').read_text())
    trigger=value.get('on',value.get(True));assert trigger['push']['paths']==['research/capital_risk/p01_iac_unit_request.json']
    assert value['concurrency']['cancel-in-progress'] is False
    def check(v):
        worker=v['jobs']['iac-unit'];steps=worker['steps']
        assert worker['timeout-minutes']==240 and len(steps)==7
        assert [s['timeout-minutes'] for s in steps]==[3,3,4,2,8,210,5]
        assert sum(s['timeout-minutes'] for s in steps)<=worker['timeout-minutes']-5
        assert 210*60-(2400+5400+1800+270)==2730
        assert steps[-1]['if']=='always()' and steps[-1]['with']['retention-days']==7
        assert len(steps[-1]['with']['path'].splitlines())==7
    check(value);wrong=deepcopy(value);del wrong['jobs']['iac-unit']['steps'][-1]['timeout-minutes']
    with pytest.raises(KeyError):check(wrong)


@pytest.mark.parametrize('failure',['none','qualify_unknown','qualify_refused','finance_unknown','review_unknown',
    'log_failure','wait_error','repeated_input','wrong_original_input','wrong_qualifier_count','missing_qualifier_endpoint','wrong_reference','wrong_finance_input'])
def test_source_bound_main_marker_before_parent_and_cipher_before_fresh_finance(tmp_path,monkeypatch,failure):
    events=[];finishes=[];contract=ModuleType('p01_iac_unit_contract')
    contract.SPEC='spec.json';contract.specification=lambda:dict(outer_sha256=export.OUTER)
    monkeypatch.setitem(sys.modules,'p01_iac_unit_contract',contract)
    here=tmp_path/'driver';here.mkdir();(here/'spec.json').write_text('{}');monkeypatch.setattr(job,'HERE',here)
    request=dict(capacity_source_sha256='c'*64,protocol_sha256='d'*64,initial_min_disk_bytes=1,
        qualification_wait_seconds=2400,financial_wait_seconds=5400,review_wait_seconds=1800,quote_descriptor={},
        input_document_sha256='a'*64,successor_input_sha256='b'*64,original_inputs=11,successor_inputs=12,
        qualified_full_runtime_sessions=2,qualified_through='2020-07-02',processing_endpoint='2021-06-29',
        maximum_financial_transitions=251,expected_completed=879,full_measurement_end='2026-07-31')
    path=tmp_path/'request.json';raw=(json.dumps(request,indent=2)+'\r\n').encode();path.write_bytes(raw)
    for name in ('capacity','staging'):(tmp_path/(name+'.json')).write_text('{}')
    monkeypatch.setattr(job,'expected_request',lambda:deepcopy(request));monkeypatch.setattr(job,'check_context',lambda *a:None)
    monkeypatch.setattr(job,'validate_prepared_receipt',lambda *a,**kw:events.append('capacity'))
    monkeypatch.setattr(job,'stage_valid',lambda *a:None);monkeypatch.setattr(job,'note',lambda *a:None)
    monkeypatch.setattr(job,'resources',lambda *a:None);monkeypatch.setattr(job,'freeze',lambda *a:None)
    monkeypatch.setenv('RUNNER_TEMP',str(tmp_path));monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1');monkeypatch.setenv(job.SECRET,'eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=')
    monkeypatch.setattr(job,'qualify_export',lambda *a:events.append('marker') or {'synthetic_marker_only':True})
    def admitted(*a):
        events.append('parent');old=tmp_path/'old';old.mkdir()
        for n in ('source-bindings.json','source-map.json'):(old/n).write_text('{}')
        return old
    monkeypatch.setattr(job,'admit',admitted);monkeypatch.setattr(job,'authenticate_capsule',lambda *a,**kw:events.append('quote'))
    def reconstruct(*a):
        x,y=tmp_path/'original',tmp_path/'source';x.mkdir();y.mkdir();return x,y
    monkeypatch.setattr(job,'reconstruct',reconstruct)
    monkeypatch.setattr(job,'worker_command',lambda name,mode,*a,**kw:dict(mode=mode,old=a[3],evidence=a[5] if len(a)>5 else None))
    def stopped(command,name,out,**kwargs):
        mode=command['mode'];events.append(mode);assert command['old']==tmp_path/'old'
        if mode=='economic':assert command['evidence']==tmp_path/'p01-iac-unit-qualification-output'
        if failure==dict(qualify='qualify_unknown',economic='finance_unknown',review='review_unknown')[mode]:raise job.StopUnknown('UNKNOWN')
        out.mkdir(exist_ok=True);(out/'worker-inspect.json').write_text('{}')
        if failure=='log_failure':(out/'log-copy-failure.json').write_text('{"type":"OSError"}')
        else:(out/'worker.log').write_text('synthetic')
        if mode=='qualify':
            (out/'proof').mkdir()
            for n in export.QUALIFICATION_FILES:(out/'proof'/n).write_text('{}')
            q=proof();q['input_adoptions']=2 if failure=='repeated_input' else 1
            if failure=='wrong_original_input':q['input_document_sha256']='0'*64
            if failure=='wrong_qualifier_count':q['component_transitions']=1
            if failure=='missing_qualifier_endpoint':del q['qualified_through']
            if failure=='wrong_reference':q['actual_fast_reference_full_components_equal']=False
            (out/'proof/qualification-summary.json').write_text(json.dumps(q))
        if mode=='economic':
            assert (out/'request.json').read_bytes()==raw
            (out/'iac-unit-outcome.json').write_text(json.dumps(dict(status='COMPLETE_IAC_UNIT_SEGMENT_PENDING_REVIEW',
                input_document_sha256='0'*64 if failure=='wrong_finance_input' else 'a'*64,successor_input_sha256='b'*64,
                original_inputs=11,successor_inputs=12,fresh_from_original628=True,qualification_state_adopted=False,
                source_epoch_boundary_reemitted=False,input_adoptions=1,maximum_transitions=251,
                processing_endpoint='2021-06-29',full_measurement_end='2026-07-31')))
        return dict(stopped=True,exit_code=1 if failure=='qualify_refused' and mode=='qualify' else 0,
            oom_killed=False,wait_error='TimeoutExpired' if failure=='wait_error' else None)
    monkeypatch.setattr(job,'stopped_run',stopped)
    def preserve(value,*a):events.append('qual_cipher');value['qualification_exported']=True
    monkeypatch.setattr(job,'preserve_qualification',preserve)
    monkeypatch.setattr(job,'finish',lambda value,root,path,key,request,known:finishes.append((deepcopy(value),known,Path(root))))
    args=SimpleNamespace(request=path,capacity=tmp_path/'capacity.json',staging=tmp_path/'staging.json',output=tmp_path/'public/receipt.json')
    with pytest.raises(SystemExit):job.main(args)
    assert events.index('marker')<events.index('parent')<events.index('quote')<events.index('qualify')
    value,known,out=finishes[0]
    if failure in ('qualify_unknown','qualify_refused','repeated_input','wrong_original_input','wrong_qualifier_count','missing_qualifier_endpoint','wrong_reference'):
        assert 'economic' not in events and not value['qualification_exported'] and known==(failure!='qualify_unknown')
    else:assert events.index('qual_cipher')<events.index('economic') and known==(failure!='finance_unknown')
    if failure=='wrong_finance_input':assert 'review' not in events
    if failure=='review_unknown':assert value['review_stop_unknown'] and not (out/'stopped-review').exists()
    if failure in ('none','wait_error','log_failure'):assert value['status']=='FINANCIAL_SUFFIX_HOSTED_REVIEW_PASSED_PENDING_CLIENT'
