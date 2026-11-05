"""New native host/crypto/UNKNOWN contracts, all stubs or synthetic payloads."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace

import pytest
import yaml

HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import p01_native_resume_job as job
import p01_native_resume_export as export


def proof():
    return dict(status='OWN627_NATIVE_EPOCH_AND_ONE_SESSION_QUALIFIED',financial_authority=False,
        financial_predecessor_authorized=False,component_transitions=1,qualified_through='2020-06-30',epoch_zero_outer_sha256=export.OUTER,
        original_input_sha256=export.INPUT,original_inputs=11,source_epoch_boundary_reemitted=False,input_boundary_reemitted=False)


def receipt():
    return dict(schema=export.RECEIPT_SCHEMA,arm='P01',stage=export.STAGE,run_id='123',head='a'*40,
        request_sha256='b'*64,protocol_sha256='c'*64,strict_parent_outer_sha256='d'*64,
        status='BEFORE_EXPORT_PROBE',production_contacted=False,qualification_exported=False)


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


@pytest.mark.parametrize('field,value',[('component_transitions',0),('component_transitions',2),
    ('component_transitions',True),('component_transitions',1.0),('original_inputs',10),
    ('qualified_through','2020-07-01'),('status','OWN627_NATIVE_EPOCH_AND_THREE_SESSIONS_QUALIFIED'),
    ('input_boundary_reemitted',True),('source_epoch_boundary_reemitted',True),('original_input_sha256','0'*64)])
def test_native_gate_requires_actual_one_day_same_input_and_no_boundary(field,value):
    good=proof();export.qualification(good);bad=deepcopy(good);bad[field]=value
    with pytest.raises(ValueError):export.qualification(bad)


def test_one_session_gate_guard_removal_falsifier():
    bad=proof();bad['component_transitions']=2
    with pytest.raises(ValueError):export.qualification(bad)
    fn=next(n for n in ast.parse(Path(export.__file__).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name=='qualification')
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need')
    guard.args[0]=ast.Constant(True);namespace=dict(vars(export))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<one-session-gate-removal-falsifier>','exec'),namespace)
    namespace['qualification'](bad)
    missing=proof();del missing['qualified_through']
    with pytest.raises(KeyError):export.qualification(missing)
    namespace['qualification'](missing)


def test_one_session_gate_requires_endpoint_and_declared_request_scope():
    good=proof();request=dict(original_input_sha256=export.INPUT,original_inputs=11,
        qualified_full_runtime_sessions=1,processing_endpoint='2020-06-30',
        maximum_financial_transitions=1,expected_completed=628)
    job.check_qualification(good,request,dict(outer_sha256=export.OUTER))
    missing=deepcopy(good);del missing['qualified_through']
    with pytest.raises(KeyError):export.qualification(missing)
    for field,value in [('qualified_full_runtime_sessions',3),('processing_endpoint','2021-06-29'),
                        ('maximum_financial_transitions',252),('expected_completed',879)]:
        wrong=deepcopy(request);wrong[field]=value
        with pytest.raises(ValueError):job.check_qualification(good,wrong,dict(outer_sha256=export.OUTER))


def test_public_receipt_and_unknown_writer_no_snapshot(tmp_path,monkeypatch):
    value=receipt();value['shares']=1
    with pytest.raises(ValueError):export.write_receipt(tmp_path/'public.json',value)
    monkeypatch.setattr(export,'sealed',lambda *a,**kw:pytest.fail('UNKNOWN may not snapshot'))
    value=receipt();value['status']='ACTIVE_WRITER_STOP_UNKNOWN_NO_MUTABLE_SNAPSHOT'
    export.finish(value,tmp_path,tmp_path/'public.json',None,tmp_path/'request.json',known=False)
    assert value['encrypted_output_exported'] is False
    with pytest.raises(ValueError):export.finish(value,tmp_path,tmp_path/'public.json',None,tmp_path/'request.json',known=True)


@pytest.mark.parametrize('logs',['normal','failed_only','partial_failed'])
def test_exact_twelve_member_qualifier_proofs_not_book(tmp_path,monkeypatch,logs):
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


def test_exact_native_worker_entrypoint_and_quote_mounts(tmp_path,monkeypatch):
    import full_system_benchmark as source
    monkeypatch.setattr(source.os,'getuid',lambda:1001,raising=False);monkeypatch.setattr(source.os,'getgid',lambda:1001,raising=False)
    for mode in ('qualify','economic','review'):
        args=job.worker_command('capital-system-p01-native-resume-worker-123-1',mode,
            tmp_path/'source',tmp_path/'frozen',tmp_path/'out',tmp_path/'old',tmp_path/'quote',
            None if mode=='qualify' else tmp_path/'evidence')
        assert args[args.index('-B'):]==job.entrypoint(mode) and 'none' in args and '--read-only' in args
        assert any('target=/celg-input,readonly' in v for v in args)
        assert any('target=/evidence,readonly' in v for v in args)==(mode!='qualify')


@pytest.mark.parametrize('role',['qualify','worker','review'])
def test_actual_inspector_new_namespace_cli_and_readonly_quotes(tmp_path,monkeypatch,role):
    name='capital-system-p01-native-resume-'+role+'-123-1'
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
    value=yaml.safe_load((HERE.parents[1]/'.github/workflows/p01_native_resume_financial.yml').read_text())
    trigger=value.get('on',value.get(True));assert trigger['push']['paths']==['research/capital_risk/p01_native_resume_request.json']
    assert value['concurrency']['cancel-in-progress'] is False
    def check(v):
        worker=v['jobs']['native-resume'];steps=worker['steps']
        assert worker['timeout-minutes']==240 and len(steps)==7
        assert [s['timeout-minutes'] for s in steps]==[3,3,4,2,8,210,5]
        assert sum(s['timeout-minutes'] for s in steps)<=worker['timeout-minutes']-5
        assert 210*60-(2400+5400+1800+270)==2730
        assert steps[-1]['if']=='always()' and steps[-1]['with']['retention-days']==7
        assert len(steps[-1]['with']['path'].splitlines())==7
    check(value);wrong=deepcopy(value);del wrong['jobs']['native-resume']['steps'][-1]['timeout-minutes']
    with pytest.raises(KeyError):check(wrong)


@pytest.mark.parametrize('failure',['none','qualify_unknown','qualify_refused','finance_unknown','review_unknown',
    'log_failure','wait_error','repeated_input','wrong_original_input','wrong_qualifier_count','missing_qualifier_endpoint'])
def test_source_bound_main_marker_before_parent_and_cipher_before_fresh_finance(tmp_path,monkeypatch,failure):
    events=[];finishes=[];contract=ModuleType('p01_native_resume_contract')
    contract.SPEC='spec.json';contract.specification=lambda:dict(outer_sha256=export.OUTER)
    monkeypatch.setitem(sys.modules,'p01_native_resume_contract',contract)
    here=tmp_path/'driver';here.mkdir();(here/'spec.json').write_text('{}');monkeypatch.setattr(job,'HERE',here)
    request=dict(capacity_source_sha256='c'*64,protocol_sha256='d'*64,initial_min_disk_bytes=1,
        qualification_wait_seconds=2400,financial_wait_seconds=5400,review_wait_seconds=1800,quote_descriptor={},
        original_input_sha256=export.INPUT,original_inputs=11,qualified_full_runtime_sessions=1,
        processing_endpoint='2020-06-30',maximum_financial_transitions=1,expected_completed=628)
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
        if mode=='economic':assert command['evidence']==tmp_path/'p01-native-resume-qualification-output'
        if failure==dict(qualify='qualify_unknown',economic='finance_unknown',review='review_unknown')[mode]:raise job.StopUnknown('UNKNOWN')
        out.mkdir(exist_ok=True);(out/'worker-inspect.json').write_text('{}')
        if failure=='log_failure':(out/'log-copy-failure.json').write_text('{"type":"OSError"}')
        else:(out/'worker.log').write_text('synthetic')
        if mode=='qualify':
            (out/'proof').mkdir()
            for n in export.QUALIFICATION_FILES:(out/'proof'/n).write_text('{}')
            q=proof();q['input_boundary_reemitted']=failure=='repeated_input'
            if failure=='wrong_original_input':q['original_input_sha256']='0'*64
            if failure=='wrong_qualifier_count':q['component_transitions']=2
            if failure=='missing_qualifier_endpoint':del q['qualified_through']
            (out/'proof/qualification-summary.json').write_text(json.dumps(q))
        if mode=='economic':
            assert (out/'request.json').read_bytes()==raw
            (out/'native-resume-outcome.json').write_text(json.dumps(dict(status='COMPLETE_NATIVE_RESUME_SEGMENT_PENDING_REVIEW',
                original_input_sha256=export.INPUT,original_inputs=11,source_epoch_boundary_reemitted=False,input_boundary_reemitted=False)))
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
    if failure in ('qualify_unknown','qualify_refused','repeated_input','wrong_original_input','wrong_qualifier_count','missing_qualifier_endpoint'):
        assert 'economic' not in events and not value['qualification_exported'] and known==(failure!='qualify_unknown')
    else:assert events.index('qual_cipher')<events.index('economic') and known==(failure!='finance_unknown')
    if failure=='review_unknown':assert value['review_stop_unknown'] and not (out/'stopped-review').exists()
    if failure in ('none','wait_error','log_failure'):assert value['status']=='FINANCIAL_SUFFIX_HOSTED_REVIEW_PASSED_PENDING_CLIENT'
