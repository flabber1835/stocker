"""Host metadata, synthetic crypto and orchestration stubs only."""
import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest
import yaml

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import p01_factual_batch_job as job
import p01_factual_batch_export as export


def test_proven_stop_helper_reused_with_durable_final_inspection():
    import alpaca_fit_job
    assert job.stopped_run is alpaca_fit_job.stopped_run
    fn,=[n for n in ast.parse(Path(alpaca_fit_job.__file__).read_bytes()).body
          if isinstance(n,ast.FunctionDef) and n.name=='stopped_run']
    guarded=next(n for n in fn.body if isinstance(n,ast.Try) and n.finalbody)
    assert any(isinstance(n,ast.Call) and ast.unparse(n.func)=='os.fsync' for n in ast.walk(guarded))
    returned=next(n for n in fn.body if isinstance(n,ast.Return))
    assert 'wait_error' in [k.value for k in returned.value.keys]


def receipt():
    return dict(schema=export.RECEIPT_SCHEMA,arm='P01',stage=export.STAGE,run_id='123',head='a'*40,
        request_sha256='b'*64,protocol_sha256='c'*64,strict_parent_outer_sha256='d'*64,
        status='BEFORE_EXPORT_PROBE',production_contacted=False,qualification_exported=False)


def test_real_synthetic_marker_new_scope(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    request=tmp_path/'request.json';request.write_text(json.dumps(dict(protocol_sha256='c'*64)))
    proof=export.qualify_export(tmp_path/'probe',request)
    assert proof['status']=='P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED'
    assert proof['source_adapter_sha256']==job.sha256_file(Path(export.__file__))
    assert proof['synthetic_marker_only'] is True and proof['market_or_financial_state_processed'] is False


def test_public_receipt_rejects_financial_payload(tmp_path):
    value=receipt();value['shares']=1
    with pytest.raises(ValueError):export.write_receipt(tmp_path/'public.json',value)
    value=receipt();value['qualification_worker']=dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None,secret='x')
    with pytest.raises(ValueError):export.write_receipt(tmp_path/'public.json',value)


def test_unknown_writer_does_not_seal_mutable_output(tmp_path,monkeypatch):
    value=receipt();value['status']='ACTIVE_WRITER_STOP_UNKNOWN_NO_MUTABLE_SNAPSHOT'
    monkeypatch.setattr(export,'sealed',lambda *args,**kwargs:pytest.fail('must not seal unknown writer'))
    export.finish(value,tmp_path,tmp_path/'public.json',None,tmp_path/'request.json',known=False)
    assert value['encrypted_output_exported'] is False
    with pytest.raises(ValueError):export.finish(value,tmp_path,tmp_path/'public.json',None,tmp_path/'request.json',known=True)


def test_unknown_snapshot_guard_removal_falsifier(tmp_path,monkeypatch):
    source=Path(export.__file__).read_bytes();fn,=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='finish']
    conditional,=[n for n in fn.body if isinstance(n,ast.If)]
    assert ast.unparse(conditional.body[0].value.func)=='need'
    conditional.body=conditional.body[1:]
    monkeypatch.setattr(export,'sealed',lambda *a,**kw:dict(name='x',bytes=1,sha256='a'*64,manifest_sha256='b'*64,compression='TAR_GZIP_V1'))
    namespace=dict(vars(export));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<unknown-snapshot-guard-removal-falsifier>','exec'),namespace)
    value=receipt();value['status']='ACTIVE_WRITER_STOP_UNKNOWN_NO_MUTABLE_SNAPSHOT'
    namespace['finish'](value,tmp_path,tmp_path/'public.json',None,tmp_path/'request.json',known=True)
    assert value['encrypted_output_exported'] is True


@pytest.mark.parametrize('logs',['normal','failed_only','partial_failed'])
def test_qualification_export_only_named_proofs_and_explicit_logs(tmp_path,monkeypatch,logs):
    root=tmp_path/'root';(root/'qualification').mkdir(parents=True)
    for name in ('spec.json','request.json','source-bindings.json','source-map.json'):(root/name).write_text('{}')
    for name in (*export.QUALIFICATION_FILES,'worker-inspect.json'):(root/'qualification'/name).write_text('{}')
    proof=dict(status='OWN526_GROUPED_FACTUAL_INPUT_AND_RUNTIME_QUALIFIED',financial_authority=False,
        financial_predecessor_authorized=False,source_epoch_boundary_reemitted=False,component_transitions=2)
    (root/'qualification/qualification-summary.json').write_text(json.dumps(proof))
    if logs!='failed_only':(root/'qualification/worker.log').write_text('synthetic log')
    if logs!='normal':(root/'qualification/log-copy-failure.json').write_text('{"type":"OSError"}')
    value=receipt();value['qualification_worker']=dict(stopped=True,exit_code=0,oom_killed=False,wait_error='TimeoutExpired')
    value['qualification_log_copy_failed']=logs!='normal'
    sealed=[];monkeypatch.setattr(export,'sealed',lambda *args,**kw:sealed.append(kw['stage']) or
        dict(name='q',bytes=1,sha256='a'*64,manifest_sha256='b'*64,compression='TAR_GZIP_V1'))
    export.preserve_qualification(value,root,tmp_path/'public.json',b'x'*32,tmp_path/'request.json')
    assert sealed==[export.QUALIFICATION_STAGE] and value['qualification_exported'] is True
    (root/'book').mkdir();(root/'book/qualification-checkpoint.json').write_text('{}')
    with pytest.raises(ValueError):export.preserve_qualification(value,root,tmp_path/'public.json',b'x'*32,tmp_path/'request.json')


def test_command_exact_offline_mount_contract(tmp_path,monkeypatch):
    # The existing command builder is reused; only the exact new CLI and two RO quote mounts differ.
    import full_system_benchmark as command_source
    monkeypatch.setattr(command_source.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(command_source.os,'getgid',lambda:1001,raising=False)
    for mode in ('qualify','economic','review'):
        args=job.worker_command('capital-system-p01-factual-batch-worker-123-1',mode,
            tmp_path/'source',tmp_path/'frozen',tmp_path/'out',tmp_path/'old',tmp_path/'capsule',
            None if mode=='qualify' else tmp_path/'evidence')
        assert args[args.index('-B'):]==job.entrypoint(mode)
        assert 'none' in args and '--read-only' in args and '--memory-swap' in args
        assert any('target=/celg-input,readonly' in v for v in args)
        assert any('target=/celg-input-descriptor.json,readonly' in v for v in args)
        assert any('target=/evidence,readonly' in v for v in args)==(mode!='qualify')


@pytest.mark.parametrize('role',['qualify','worker','review'])
def test_actual_inspector_body_new_entrypoint_and_ro_fences(tmp_path,monkeypatch,role):
    name='capital-system-p01-factual-batch-'+role+'-123-1'
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
    value['Config']['Cmd'][2]='/driver/p01_celg_bridge_run.py'
    with pytest.raises(ValueError):job.inspect(name,'a'*64)
    if role=='worker':
        fn,=[n for n in ast.parse(Path(job.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='inspect']
        fn.body=[n for n in fn.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
            and any(isinstance(a,ast.Constant) and a.value=='P01_BATCH_EXACT_WORKER_ENTRYPOINT' for a in n.value.args))]
        namespace=dict(vars(job));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
            '<new-entrypoint-guard-removal-falsifier>','exec'),namespace)
        assert namespace['inspect'](name,'a'*64)==value
    value['Config']['Cmd']=job.entrypoint(dict(qualify='qualify',worker='economic',review='review')[role])
    next(x for x in value['Mounts'] if x['Destination']=='/celg-input')['RW']=True
    with pytest.raises(ValueError):job.inspect(name,'a'*64)


def test_reconstruction_uses_historical223_not_current224(tmp_path,monkeypatch):
    old=tmp_path/'old';old.mkdir();driver=tmp_path/'driver';driver.mkdir()
    binding=dict(parameters={'family':'retained'},all_sources={'old.py':'a'*64})
    mapping=dict(predecessor_financial_sources={'old.py':'a'*64},successor_financial_sources={'new.py':'b'*64})
    (old/'source-bindings.json').write_text(json.dumps(binding));(old/'source-map.json').write_text(json.dumps(mapping))
    (driver/job.SOURCE_MAP).write_text(json.dumps(mapping));monkeypatch.setattr(job,'HERE',driver)
    def build(frozen,destination,parameters):
        destination.mkdir();(destination/'old.py').write_text('synthetic source');assert parameters==binding['parameters'];return binding
    seen=[]
    def render(files,expected,destination,*,financial_sources):
        seen.append(financial_sources);destination.mkdir();return mapping
    monkeypatch.setattr(job,'build',build);monkeypatch.setattr(job,'write_disjoint',render)
    job.reconstruct(tmp_path/'frozen',old,tmp_path)
    assert seen==[mapping['predecessor_financial_sources']]


def test_workflow_request_only_trigger_and_headroom():
    raw=(HERE.parents[1]/'.github/workflows/p01_factual_batch_financial.yml').read_text()
    value=yaml.safe_load(raw);trigger=value.get('on',value.get(True))
    assert trigger['push']['paths']==['research/capital_risk/p01_factual_batch_request.json']
    assert value['concurrency']['cancel-in-progress'] is False
    worker=value['jobs']['factual-batch'];assert worker['timeout-minutes']==240
    steps=worker['steps'];financial=next(s for s in steps if 'p01_factual_batch_job.py' in s.get('run',''))
    assert financial['timeout-minutes']==210 and 210*60-(2400+5400+1800+270)==2730
    assert 'ephemeral_runner_capacity.py' in steps[1]['run']
    assert next(s for s in steps if 'p01_factual_batch_probe.py' in s.get('run',''))['run'].endswith('ephemeral-runner-capacity.json')
    artifact=steps[-1];assert artifact['if']=='always()' and artifact['with']['retention-days']==7
    assert len(artifact['with']['path'].splitlines())==7


def test_bounded_workflow_budget_and_missing_upload_timeout_falsifier():
    value=yaml.safe_load((HERE.parents[1]/'.github/workflows/p01_factual_batch_financial.yml').read_text())
    def budget(workflow):
        worker=workflow['jobs']['factual-batch'];steps=worker['steps']
        assert len(steps)==7 and all(type(s.get('timeout-minutes')) is int for s in steps)
        assert [s['timeout-minutes'] for s in steps]==[3,3,4,2,8,210,5]
        assert sum(s['timeout-minutes'] for s in steps)<=worker['timeout-minutes']-5
    budget(value)
    removed=deepcopy(value);del removed['jobs']['factual-batch']['steps'][-1]['timeout-minutes']
    with pytest.raises(AssertionError):budget(removed)


@pytest.mark.parametrize('failure',['none','qualify_unknown','qualify_refused','finance_unknown','review_unknown','log_failure','wait_error','repeated_source','wrong_input_bytes'])
def test_host_order_known_stop_and_separate_fresh_finance(tmp_path,monkeypatch,failure):
    events=[];finishes=[];contract=ModuleType('p01_factual_batch_contract')
    contract.SPEC='spec.json';contract.specification=lambda:dict(outer_sha256='OWN526')
    monkeypatch.setitem(sys.modules,'p01_factual_batch_contract',contract)
    here=tmp_path/'driver';here.mkdir();(here/'spec.json').write_text('{}');monkeypatch.setattr(job,'HERE',here)
    request=dict(capacity_source_sha256='c'*64,protocol_sha256='d'*64,initial_min_disk_bytes=1,
        qualification_wait_seconds=2400,financial_wait_seconds=5400,review_wait_seconds=1800,quote_descriptor={},
        input_document_sha256='input')
    request_path=tmp_path/'request.json';request_raw=(json.dumps(request,indent=2)+'\r\n').encode();request_path.write_bytes(request_raw)
    for name in ('capacity','staging'):(tmp_path/(name+'.json')).write_text('{}')
    monkeypatch.setattr(job,'expected_request',lambda:deepcopy(request));monkeypatch.setattr(job,'check_context',lambda *args:None)
    monkeypatch.setattr(job,'validate_prepared_receipt',lambda *a,**kw:events.append('capacity'))
    monkeypatch.setattr(job,'stage_valid',lambda *args:events.append('staging'));monkeypatch.setattr(job,'note',lambda *args:None)
    monkeypatch.setattr(job,'resources',lambda *args:None);monkeypatch.setattr(job,'freeze',lambda p:events.append('freeze:'+Path(p).name))
    monkeypatch.setenv('RUNNER_TEMP',str(tmp_path));monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','a'*40)
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1');monkeypatch.setenv(job.SECRET,'eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=')
    monkeypatch.setattr(job,'qualify_export',lambda *args:events.append('marker') or {'synthetic_marker_only':True})
    def admit(*args):
        events.append('admit');old=tmp_path/'old';old.mkdir()
        for name in ('source-bindings.json','source-map.json'):(old/name).write_text('{}')
        return old
    monkeypatch.setattr(job,'admit',admit)
    monkeypatch.setattr(job,'authenticate_capsule',lambda *a,**kw:events.append('quote_auth'))
    def reconstruct(*args):
        a,b=tmp_path/'original',tmp_path/'source';a.mkdir();b.mkdir();return a,b
    monkeypatch.setattr(job,'reconstruct',reconstruct)
    monkeypatch.setattr(job,'worker_command',lambda name,mode,*a,**kw:dict(name=name,mode=mode,old=a[3],evidence=a[5] if len(a)>5 else None))
    def stopped(command,name,out,**kwargs):
        mode=command['mode'];events.append(mode)
        assert command['old']==tmp_path/'old'
        if mode=='economic':assert command['evidence']==tmp_path/'p01-factual-batch-qualification-output'
        if failure==dict(qualify='qualify_unknown',economic='finance_unknown',review='review_unknown')[mode]:raise job.StopUnknown('SYNTHETIC_UNKNOWN')
        out.mkdir(exist_ok=True);(out/'worker-inspect.json').write_text('{}')
        if failure=='log_failure':(out/'log-copy-failure.json').write_text('{"type":"OSError"}')
        else:(out/'worker.log').write_text('synthetic')
        if mode=='qualify':
            (out/'proof').mkdir()
            for n in export.QUALIFICATION_FILES:(out/'proof'/n).write_text('{}')
            proof=dict(status='OWN526_GROUPED_FACTUAL_INPUT_AND_RUNTIME_QUALIFIED',financial_authority=False,
                financial_predecessor_authorized=False,component_transitions=2,source_epoch_boundary_reemitted=failure=='repeated_source',
                epoch_zero_outer_sha256='OWN526',input_document_sha256='wrong' if failure=='wrong_input_bytes' else 'input')
            (out/'proof/qualification-summary.json').write_text(json.dumps(proof))
        if mode=='economic':
            assert (out/'request.json').read_bytes()==request_raw
            (out/'batch-outcome.json').write_text(json.dumps(dict(status='COMPLETE_FACTUAL_BATCH_SEGMENT_PENDING_REVIEW',input_document_sha256='input')))
        return dict(stopped=True,exit_code=1 if failure=='qualify_refused' and mode=='qualify' else 0,
            oom_killed=False,wait_error='TimeoutExpired' if failure=='wait_error' else None)
    monkeypatch.setattr(job,'stopped_run',stopped)
    def preserve(value,*args):
        events.append('qual_cipher');value['qualification_exported']=True
        value['qualification_encrypted_output']=dict(name='q',bytes=1,sha256='a'*64,manifest_sha256='b'*64,compression='TAR_GZIP_V1')
    monkeypatch.setattr(job,'preserve_qualification',preserve)
    monkeypatch.setattr(job,'finish',lambda value,root,path,key,request,known:finishes.append((deepcopy(value),known,Path(root))))
    args=SimpleNamespace(request=request_path,capacity=tmp_path/'capacity.json',staging=tmp_path/'staging.json',output=tmp_path/'public/receipt.json')
    with pytest.raises(SystemExit):job.main(args)
    assert events.index('marker')<events.index('admit')<events.index('quote_auth')<events.index('qualify')
    value,known,out=finishes[0]
    if failure in ('qualify_unknown','qualify_refused','repeated_source','wrong_input_bytes'):
        assert 'economic' not in events and not value['qualification_exported']
        assert known==(failure!='qualify_unknown')
    else:
        assert events.index('qual_cipher')<events.index('economic') and value['qualification_exported'] is True
        assert known==(failure!='finance_unknown')
    if failure=='review_unknown':assert value['review_stop_unknown'] is True and not (out/'stopped-review').exists()
    if failure=='log_failure':assert value['qualification_log_copy_failed'] and value['worker_log_copy_failed'] and value['review_log_copy_failed']
    if failure in ('none','wait_error','log_failure'):assert value['status']=='FINANCIAL_SUFFIX_HOSTED_REVIEW_PASSED_PENDING_CLIENT'
