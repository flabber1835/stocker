"""NONCANONICAL filesystem fixtures; real evidence is read only by a separate reader."""
import ast,copy,hashlib,importlib,importlib.abc,io,json,os,sys,tarfile,types
from pathlib import Path
import pytest
P=Path(__file__).resolve().parents[2];sys.path.insert(0,str(P))
import system_campaign_p07_lossless_export as m
import system_campaign_p07_lossless_export_host as host

@pytest.fixture
def f(tmp_path):
    root=tmp_path/'output';root.mkdir();template={}
    for name,raw in [('resources/alpha.bin',b'NONCANONICAL ALPHA RESOURCE\n'),('resources/beta.bin',b'NONCANONICAL BETA RESOURCE\n')]:
        for target in [root/name,*[root/(prefix+name) for prefix in m.PREFIXES]]:
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        template[name]=dict(m.pin(root/name),retained_relative=name)
    stops=[]
    for role,name in [('preflight','parent-preflight/worker-inspect.json'),('economic','worker-inspect.json'),('review','stopped-review/worker-inspect.json')]:
        inspection=dict(State=dict(Running=False,ExitCode=1 if role!='preflight' else 0,OOMKilled=False))
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(m.encoded(inspection))
        stops.append(dict(role=role,returned=True,result=dict(stopped=True,exit_code=inspection['State']['ExitCode'],oom_killed=False,wait_error=None),inspection=inspection,inspection_sha256=m.digest(inspection)))
    for name in ('worker.log','stopped-review/worker.log','stopped-review/core-review.json','driver-failure.txt','book/daily.jsonl','book/checkpoint.json.gz'):
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(('NONCANONICAL UNIQUE FAILURE EVIDENCE '+name).encode())
    return types.SimpleNamespace(root=root,template=template,stops=stops,before=m.inventory(root)[0])
def snapshot(root):return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
def seal_capture(root,*args,**kwargs):return snapshot(root)
def assert_restored(f):
    assert m.inventory(f.root)[0]==f.before
    assert not (f.root/m.RECEIPT).exists()
    assert not list(f.root.parent.glob('p07-lossless-export-rollback-*'))
def test_failure_evidence_and_canonical_named_fixtures_survive_exact_roundtrip(f):
    payload=m.seal_represented(f.root,seal_capture,(),{},f.stops,template_files=f.template)
    assert_restored(f);assert m.RECEIPT in payload
    manifest={k:dict(bytes=len(v),sha256=m.sha(v)) for k,v in payload.items()}
    logical=m.logical_members(payload.__getitem__,manifest,template_files=f.template)
    for name,pin in f.before.items():assert dict(bytes=len(logical(name)),sha256=m.sha(logical(name)))==pin
    assert len(logical.names)==len(f.before)+1
    assert payload['worker.log']==(f.root/'worker.log').read_bytes()
    assert 'stopped-review/core-review.json' in payload and 'book/checkpoint.json.gz' in payload
@pytest.mark.parametrize('role',['economic','review'])
def test_exit1_is_known_stop_not_permission_to_delete_unique_evidence(f,role):
    assert f.stops[['preflight','economic','review'].index(role)]['result']['exit_code']==1
    result=m.seal_represented(f.root,seal_capture,(),{},f.stops,template_files=f.template)
    assert 'driver-failure.txt' in result and 'stopped-review/worker.log' in result;assert_restored(f)
@pytest.mark.parametrize('mutation',range(8))
def test_unknown_active_mismatched_or_missing_writer_refuses_without_mutation(f,mutation):
    record=f.stops[-1]
    if mutation==0:record['returned']=False
    elif mutation==1:record['result']['stopped']=False
    elif mutation==2:record['inspection']['State']['Running']=True;record['inspection_sha256']=m.digest(record['inspection'])
    elif mutation==3:record['result']['exit_code']=True
    elif mutation==4:record['result']['oom_killed']=True
    elif mutation==5:record['inspection_sha256']='f'*64
    elif mutation==6:f.stops.append(copy.deepcopy(record))
    else:(f.root/'stopped-review/worker-inspect.json').unlink();f.before=m.inventory(f.root)[0]
    with pytest.raises(ValueError):m.seal_represented(f.root,seal_capture,(),{},f.stops,template_files=f.template)
    assert_restored(f)
def test_zero_review_attempts_can_use_actual_two_stopped_writers(f):
    f.stops.pop()
    # Existing failure records remain physical even though no review was tracked.
    payload=m.seal_represented(f.root,seal_capture,(),{},f.stops,template_files=f.template)
    assert 'stopped-review/worker.log' in payload;assert_restored(f)
def test_changed_known_copy_fails_closed(f):
    path=f.root/(m.PREFIXES[0]+'resources/alpha.bin');path.write_bytes(b'NONCANONICAL CHANGED COPY');f.before=m.inventory(f.root)[0]
    with pytest.raises(ValueError,match='PINNED_PHYSICAL_ORIGINAL'):m.plan(f.root,f.stops,f.template)
    assert_restored(f)
def test_unknown_and_new_resource_copies_remain_physical(f):
    name=m.PREFIXES[1]+'new25.resource';(f.root/name).write_bytes(b'NONCANONICAL NEW25 RESOURCE');f.before=m.inventory(f.root)[0]
    payload=m.seal_represented(f.root,seal_capture,(),{},f.stops,template_files=f.template)
    assert payload[name]==b'NONCANONICAL NEW25 RESOURCE';assert_restored(f)
@pytest.mark.parametrize('point',range(8))
def test_every_move_failure_before_or_after_move_restores_full_tree(f,point):
    calls=[]
    def move(src,dst):
        index=len(calls);calls.append(index)
        if point==index*2:raise OSError('NONCANONICAL BEFORE MOVE')
        os.replace(src,dst)
        if point==index*2+1:raise OSError('NONCANONICAL AFTER MOVE')
    with pytest.raises(OSError):m.seal_represented(f.root,seal_capture,(),{},f.stops,template_files=f.template,move=move)
    assert_restored(f)
def test_original_seal_failure_restores_all_failure_temporary_bytes(f):
    def fail(root,*a,**k):assert m.RECEIPT in snapshot(root);raise ValueError('ORIGINAL GUARD FAILURE')
    with pytest.raises(ValueError,match='ORIGINAL GUARD'):m.seal_represented(f.root,fail,(),{},f.stops,template_files=f.template)
    assert_restored(f)
def test_observer_failure_restores_all_bytes(f):
    def observe(value):raise RuntimeError('NONCANONICAL OBSERVER')
    with pytest.raises(RuntimeError):m.seal_represented(f.root,seal_capture,(),{},f.stops,template_files=f.template,observe=observe)
    assert_restored(f)
def test_receipt_write_failure_restores_all_bytes(f,monkeypatch):
    def fail(value):raise OSError('NONCANONICAL RECEIPT FAILURE')
    monkeypatch.setattr(m,'encoded',fail)
    with pytest.raises(OSError):m.seal_represented(f.root,seal_capture,(),{},f.stops,template_files=f.template)
    assert_restored(f)
def test_rollback_failure_keeps_every_moved_copy_in_owned_backup_and_unique_records(f,monkeypatch):
    real=os.replace
    def fail_restore(src,dst):
        if 'p07-lossless-export-rollback-' in str(src):raise OSError('NONCANONICAL ROLLBACK FAILURE')
        return real(src,dst)
    monkeypatch.setattr(m.os,'replace',fail_restore)
    def seal_failure(root,*a,**k):raise ValueError('NONCANONICAL ORIGINAL SEAL FAILURE')
    with pytest.raises(ValueError,match='ROLLBACK_FAILED_BACKUPS_PRESERVED'):
        m.seal_represented(f.root,seal_failure,(),{},f.stops,template_files=f.template)
    backups=list(f.root.parent.glob('p07-lossless-export-rollback-*'));assert len(backups)==1
    assert len(list(backups[0].iterdir()))==4 and (f.root/'driver-failure.txt').is_file()
    assert (f.root/'resources/alpha.bin').read_bytes()==b'NONCANONICAL ALPHA RESOURCE\n'
def test_hardlink_refused_before_any_mutation(f):
    os.link(f.root/'resources/alpha.bin',f.root/'alias-hardlink.bin');f.before={}
    with pytest.raises(ValueError,match='HARDLINK'):m.plan(f.root,f.stops,f.template)
    assert (f.root/'resources/alpha.bin').read_bytes()==b'NONCANONICAL ALPHA RESOURCE\n'
@pytest.mark.parametrize('name',['../outside','a/../b','/absolute','a\\b','C:/secret','.','a//b'])
def test_unsafe_names_refused(name):
    with pytest.raises(ValueError):m.safe_name(name)
@pytest.mark.parametrize('field',['source','bytes','name','before_inventory','writer_stops','retained_source_path'])
def test_logical_reader_rejects_rehashed_malformed_representation(f,field):
    payload=m.seal_represented(f.root,seal_capture,(),{},f.stops,template_files=f.template);r=json.loads(payload[m.RECEIPT])
    if field=='source':r['copies'][0]['source']='book/daily.jsonl'
    elif field=='bytes':r['copies'][0]['bytes']+=1
    elif field=='name':r['copies'][0]['name']='unknown/prefix.bin'
    elif field=='writer_stops':r['writer_stops'][1]['result']['stopped']=False
    elif field=='retained_source_path':r['copies'][0]['retained_source_path']='/invented/not-the-real-original'
    else:r['before_inventory'].pop('worker.log')
    payload[m.RECEIPT]=m.encoded(r);manifest={k:dict(bytes=len(v),sha256=m.sha(v)) for k,v in payload.items()}
    with pytest.raises(ValueError):m.logical_members(payload.__getitem__,manifest,template_files=f.template)
def test_no_unrecorded_prefix_omission(f):
    payload=m.seal_represented(f.root,seal_capture,(),{},f.stops,template_files=f.template);payload.pop('stopped-review/worker.log')
    manifest={k:dict(bytes=len(v),sha256=m.sha(v)) for k,v in payload.items()}
    with pytest.raises(ValueError,match='NO_PREFIX_EXEMPTION'):m.logical_members(payload.__getitem__,manifest,template_files=f.template)
def test_every_source_reauthenticated_at_logical_read(f):
    payload=m.seal_represented(f.root,seal_capture,(),{},f.stops,template_files=f.template);manifest={k:dict(bytes=len(v),sha256=m.sha(v)) for k,v in payload.items()}
    logical=m.logical_members(payload.__getitem__,manifest,template_files=f.template);payload['resources/alpha.bin']=b'NONCANONICAL MUTATED AFTER VALIDATION'
    with pytest.raises(ValueError):logical(m.PREFIXES[0]+'resources/alpha.bin')
def test_safe_diagnostics_and_atomic_public_update(f):
    value=m.diagnostics(f.root);path=f.root.parent/'public.json';original=dict(arm='P07',performance_admitted=False,status='ORIGINAL FAILURE STATUS',worker=dict(exit_code=1))
    path.write_bytes(m.encoded(original));host.publish(path,[value]);result=json.loads(path.read_bytes())
    assert {k:v for k,v in result.items() if k!='p07_export_diagnostics'}==original
    text=json.dumps(result['p07_export_diagnostics']);assert 'resources/' not in text and str(f.root) not in text and 'NONCANONICAL' not in text
    assert value['byte_bound_passed'] and value['member_bound_passed'] and value['symlink_bound_passed']
def bind_fixture(f,monkeypatch,*,seal_error=False,stop_error=False):
    expected=f.root.parent/'financial-resume-output-P07';f.root.rename(expected);f.root=expected
    monkeypatch.setenv('RUNNER_TEMP',str(f.root.parent));monkeypatch.setenv('GITHUB_RUN_ID','123')
    declaration=dict(NONCANONICAL='FINITE DECLARATION')
    request=dict(execution_mode='OWN_ADMITTED_FINANCIAL_CONTINUATION',financial_resume_authorized=True,readonly_partial_review=False,
                 **{m.FIELD:declaration})
    req=f.root.parent/'NONCANONICAL-request.json';req.write_bytes(m.encoded(request))
    public=f.root.parent/'public.json';public.write_bytes(m.encoded(dict(arm='P07',performance_admitted=False,status='ORIGINAL FAILURE')))
    args=types.SimpleNamespace(arm='P07',request=req,output=public)
    module=types.SimpleNamespace(root_spec=lambda arm:dict(root_admission_sha256=m.ROOT,outer_sha256='1e1e4dbce5a3b13c329bfb2c16a99e6f6043bcc8628a9852971f7100d9295a3a',measured_closes=1259,repairs=[None]*24))
    def stopped(*a,**kw):
        if stop_error:raise RuntimeError('NONCANONICAL UNKNOWN STOP')
        role='economic' if '-worker-' in a[1] else 'review' if '-review-' in a[1] else 'preflight'
        return next(v['result'] for v in f.stops if v['role']==role)
    def seal(root,*a,**kw):
        if seal_error:raise ValueError('NONCANONICAL ORIGINAL SEAL FAILURE')
        return snapshot(root)
    def launch(a):
        for role,output in [('preflight',f.root/'parent-preflight'),('worker',f.root),('review',f.root/'stopped-review')]:
            try:module.stopped_run(['NONCANONICAL'],f'capital-system-resume-p07-{role}-123-1',output,deadline=1)
            except RuntimeError:break
        result=module.seal(f.root,'NONCANONICAL-TARGET',b'NONCANONICAL-KEY',req,'P07',stage='campaign-factual-suffix')
        # Simulate whole original launch's final public() replacing earlier diagnostics.
        public.write_bytes(m.encoded(dict(arm='P07',performance_admitted=False,status='ORIGINAL FINAL FAILURE')))
        return result
    module.seal=seal;module.stopped_run=stopped;module.launch=launch
    monkeypatch.setattr(host,'declaration',lambda:declaration)
    monkeypatch.setattr(host,'bound_sources',lambda mm,rr:(seal,stopped))
    monkeypatch.setattr(m,'template',lambda:f.template)
    return module,args,seal,stopped
def test_whole_host_seam_tracks_failed_workers_restores_bindings_and_final_public(f,monkeypatch):
    module,args,seal,stop=bind_fixture(f,monkeypatch)
    payload=host.bind_launch(module)(args)
    assert m.RECEIPT in payload and module.seal is seal and module.stopped_run is stop
    public=json.loads(args.output.read_bytes());assert public['status']=='ORIGINAL FINAL FAILURE'
    assert [v['phase'] for v in public['p07_export_diagnostics']]==['BEFORE','PHYSICAL_REPRESENTATION','RESTORED']
    assert_restored(f)
def test_host_original_seal_failure_keeps_original_error_and_safe_diagnostics(f,monkeypatch):
    module,args,seal,stop=bind_fixture(f,monkeypatch,seal_error=True)
    with pytest.raises(ValueError,match='ORIGINAL SEAL FAILURE'):host.bind_launch(module)(args)
    assert module.seal is seal and module.stopped_run is stop and json.loads(args.output.read_bytes())['p07_export_diagnostics']
    assert_restored(f)
def test_host_unknown_writer_falls_back_to_original_unchanged_export(f,monkeypatch):
    module,args,seal,stop=bind_fixture(f,monkeypatch,stop_error=True)
    payload=host.bind_launch(module)(args)
    assert m.RECEIPT not in payload and set(payload)==set(f.before)
    public=json.loads(args.output.read_bytes());assert public['p07_export_diagnostics'][-1]['representation_status']=='REFUSED'
    assert_restored(f)
def test_unselected_host_route_is_whole_inert(tmp_path):
    p=tmp_path/'request.json';p.write_text('{}');marker=object()
    module=types.SimpleNamespace(launch=lambda args:marker)
    assert host.bind_launch(module)(types.SimpleNamespace(arm='P07',request=p)) is marker
def test_public_diagnostic_failure_never_masks_original_seal_error(f,monkeypatch,capsys):
    module,args,seal,stop=bind_fixture(f,monkeypatch,seal_error=True)
    def fail(*a,**kw):raise OSError('NONCANONICAL SECRET-LOOKING PATH MUST NOT PRINT')
    monkeypatch.setattr(host,'publish',fail)
    with pytest.raises(ValueError,match='ORIGINAL SEAL FAILURE'):host.bind_launch(module)(args)
    text=capsys.readouterr().out
    assert 'p07_export_diagnostics_write_failed' in text and 'SECRET-LOOKING' not in text
    assert_restored(f)
def test_tracker_inspection_observation_failure_preserves_original_result(tmp_path):
    value=dict(stopped=True,exit_code=1,oom_killed=False,wait_error=None)
    tracker=host.Tracker(lambda *a,**kw:value,'123')
    assert tracker([], 'capital-system-resume-p07-worker-123-1',tmp_path) is value
    assert tracker.records[0]['inspection'] is None
def test_public_diagnostic_must_stay_outside_financial_tree(f):
    path=f.root/'NONCANONICAL-public.json';raw=m.encoded(dict(arm='P07',performance_admitted=False));path.write_bytes(raw)
    with pytest.raises(ValueError,match='OUTSIDE_FINANCIAL'):host.publish(path,[m.diagnostics(f.root)],f.root)
    assert path.read_bytes()==raw
def test_safe_diagnostic_never_follows_link_targets(f,monkeypatch):
    real=m.linked
    monkeypatch.setattr(m,'linked',lambda path,info=None:Path(path).name=='resources' or real(path,info))
    value=m.diagnostics(f.root)
    assert value['symlink_or_reparse_count']==3 and value['unsafe_link_target_stats_read'] is False
    assert value['byte_bound_passed'] is value['member_bound_passed'] is None and value['symlink_bound_passed'] is False
@pytest.mark.parametrize('mode',['READONLY_SOURCE_WITNESSES','OWN_ADMITTED_FINANCIAL_CONTINUATION'])
def test_request_binding_selected_only_for_original_financial_d9(f,monkeypatch,mode):
    base=dict(arms=['P07'],execution_mode=mode,financial_resume_authorized=True,sources={},selected_p07_vivo_ordinary25={'P07':dict(root_admission_sha256=m.ROOT)})
    monkeypatch.setattr(host,'declaration',lambda:dict(NONCANONICAL='DECLARATION'))
    monkeypatch.setattr(host,'source_names',lambda:())
    actual=host.bind_expected_request(lambda:base)()
    assert (m.FIELD in actual)==(mode=='OWN_ADMITTED_FINANCIAL_CONTINUATION')
    assert m.FIELD not in base
def test_whole_physical_source_function_gate_accepts_actual_compiled_seal_and_stop_without_imports(monkeypatch):
    cap=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial339-P07-source-snapshot/producer/research/capital_risk')
    def compile_original(path,name):
        module=compile(path.read_bytes(),str(path),'exec',dont_inherit=True)
        code,=[v for v in module.co_consts if isinstance(v,types.CodeType) and v.co_name==name]
        scope={};function=types.FunctionType(code,scope,name);scope[name]=function
        return function
    seal=compile_original(cap/'full_system_trials_job.py','seal');stop=compile_original(cap/'alpaca_fit_job.py','stopped_run')
    module=types.SimpleNamespace(__file__=str(cap/'system_campaign_financial_resume.py'),seal=seal,stopped_run=stop)
    request=dict(sources={name:m.pin(cap/name)['sha256'] for name in ('full_system_trials_job.py','alpaca_fit_job.py','system_campaign_financial_resume.py')})
    assert host.bound_sources(module,request)==(seal,stop)
    original=seal.__code__;seal.__code__=(lambda *args:None).__code__
    # Same source filename alone is insufficient; restoring the filename still
    # leaves the real full-body equality guard able to reject the changed code.
    seal.__code__=seal.__code__.replace(co_filename=original.co_filename)
    with pytest.raises(ValueError,match='CODE_EQUALS'):host.bound_sources(module,request)
    previous=host.need
    def without(value,label):
        if label!='WHOLE_ORIGINAL_FUNCTION_CODE_EQUALS_PHYSICAL_SOURCE':previous(value,label)
    monkeypatch.setattr(host,'need',without)
    assert host.bound_sources(module,request)==(seal,stop)
@pytest.mark.parametrize('mutation',['passed','financial_runtime_executed','missing_file','changed_source'])
def test_exact_private_qualification_file_gate(tmp_path,monkeypatch,mutation):
    runtime={}
    for name in set(host.SOURCE_NAMES)-{host.QUALIFICATION}:
        target=tmp_path/name;target.write_bytes(('NONCANONICAL FILE '+name).encode());runtime[name]=m.pin(target)
    q=dict(passed=True,financial_runtime_executed=False,runtime_files=runtime)
    if mutation=='passed':q['passed']=False
    elif mutation=='financial_runtime_executed':q['financial_runtime_executed']=True
    elif mutation=='missing_file':q['runtime_files'].pop(next(iter(runtime)))
    else:(tmp_path/next(iter(runtime))).write_bytes(b'NONCANONICAL UNQUALIFIED SOURCE')
    (tmp_path/host.QUALIFICATION).write_bytes(m.encoded(q));monkeypatch.setattr(host,'HERE',tmp_path)
    with pytest.raises(ValueError):host.declaration()
    if mutation=='missing_file':
        original=host.need
        def without(value,label):
            if label!='COMPLETE_EXACT_THREE_RUNTIME_FILE_GATE':original(value,label)
        monkeypatch.setattr(host,'need',without)
        assert host.declaration()['per_file_copy_equivalence_required']
@pytest.mark.parametrize('phase',['BEFORE','PHYSICAL_REPRESENTATION','RESTORED'])
@pytest.mark.parametrize('seal_error',[False,True])
def test_all_host_traversal_failures_are_safe_UNKNOWN_and_preserve_original_outcome(f,monkeypatch,capsys,phase,seal_error):
    module,args,seal,stop=bind_fixture(f,monkeypatch,seal_error=seal_error)
    original=host.diagnostics;calls=[];failure_index=['BEFORE','PHYSICAL_REPRESENTATION','RESTORED'].index(phase)+1
    def diagnostic(root):
        calls.append(None)
        if len(calls)==failure_index:raise OSError('NONCANONICAL SECRET/PATH MUST NEVER LEAK')
        return original(root)
    monkeypatch.setattr(host,'diagnostics',diagnostic)
    if seal_error:
        with pytest.raises(ValueError,match='ORIGINAL SEAL FAILURE'):host.bind_launch(module)(args)
    else:assert m.RECEIPT in host.bind_launch(module)(args)
    record=next(v for v in json.loads(args.output.read_bytes())['p07_export_diagnostics'] if v['phase']==phase)
    assert record['diagnostic_status']=='UNKNOWN' and record['diagnostic_failure']=='TRAVERSAL_FAILED'
    assert all(record[k] is None for k in ('file_count','logical_bytes','member_bound_passed','byte_bound_passed','symlink_bound_passed'))
    assert 'SECRET/PATH' not in capsys.readouterr().out and 'SECRET/PATH' not in args.output.read_text()
    assert module.seal is seal and module.stopped_run is stop;assert_restored(f)
@pytest.mark.parametrize('seal_error',[False,True])
def test_core_observer_diagnostic_traversal_cannot_replace_original_outcome(f,monkeypatch,seal_error):
    module,args,seal,stop=bind_fixture(f,monkeypatch,seal_error=seal_error)
    def fail(root):raise OSError('NONCANONICAL CORE DIAGNOSTIC FAILURE')
    monkeypatch.setattr(m,'diagnostics',fail)
    if seal_error:
        with pytest.raises(ValueError,match='ORIGINAL SEAL FAILURE'):host.bind_launch(module)(args)
    else:assert m.RECEIPT in host.bind_launch(module)(args)
    assert_restored(f)
def test_real_imported_W_metadata_module_source_code_identity_without_execution():
    import subprocess
    result=subprocess.run([sys.executable,'-B',str('C:\\GitHub\\stocker\\.codex-tmp\\p07-lossless-export-v2-20261106\\smoke_actual_imported_sources.py')],capture_output=True,text=True,check=True)
    value=json.loads(result.stdout)
    assert value['passed'] and value['original_seal_code_exact'] and value['original_stop_code_exact']
    assert value['stale_actual_request_refused'] and value['meaningful_actual_host_source_owner_guard_removal']
    assert value['financial_runtime_executed'] is False
@pytest.mark.parametrize('scope',['host','core'])
def test_meaningful_safe_diagnostic_exception_fence_removal(f,monkeypatch,scope):
    module,args,seal,stop=bind_fixture(f,monkeypatch,seal_error=True)
    def fail(root):raise OSError('NONCANONICAL OBSERVATION FAILURE')
    if scope=='host':monkeypatch.setattr(host,'diagnostics',fail)
    else:monkeypatch.setattr(m,'diagnostics',fail)
    with pytest.raises(ValueError,match='ORIGINAL SEAL FAILURE'):host.bind_launch(module)(args)
    if scope=='host':monkeypatch.setattr(host,'safe_diagnostics',lambda root,reader=None:reader(root))
    else:monkeypatch.setattr(m,'safe_diagnostics',lambda root:m.diagnostics(root))
    with pytest.raises(OSError,match='OBSERVATION FAILURE'):host.bind_launch(module)(args)
@pytest.mark.parametrize('seal_error',[False,True])
def test_diagnostic_log_failure_cannot_replace_original_outcome_or_prevent_public_record(f,monkeypatch,seal_error):
    module,args,seal,stop=bind_fixture(f,monkeypatch,seal_error=seal_error)
    def fail(*a,**kw):raise OSError('NONCANONICAL LOG FAILURE')
    monkeypatch.setattr(host,'print',fail,raising=False)
    if seal_error:
        with pytest.raises(ValueError,match='ORIGINAL SEAL FAILURE'):host.bind_launch(module)(args)
    else:assert m.RECEIPT in host.bind_launch(module)(args)
    assert len(json.loads(args.output.read_bytes())['p07_export_diagnostics'])==3
    assert_restored(f)
def test_core_whole_AST_undo_changes_only_safe_observer_argument():
    old=ast.parse(Path('C:/GitHub/stocker/.codex-tmp/p07-lossless-export-20261106/system_campaign_p07_lossless_export.py').read_bytes())
    current=ast.parse((P/'system_campaign_p07_lossless_export.py').read_bytes())
    current.body=[n for n in current.body if not (isinstance(n,ast.FunctionDef) and n.name=='safe_diagnostics')]
    changed=[]
    for n in ast.walk(current):
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='safe_diagnostics':n.func.id='diagnostics';changed.append(n)
    assert len(changed)==1 and ast.dump(current,include_attributes=False)==ast.dump(old,include_attributes=False)
@pytest.mark.parametrize('guard',['ALL_ATTEMPTED_WRITERS_POSITIVELY_STOPPED','EVERY_COPY_EQUALS_PINNED_PHYSICAL_ORIGINAL','NO_HARDLINKS'])
def test_meaningful_adapter_guard_removals(f,monkeypatch,guard):
    if guard=='ALL_ATTEMPTED_WRITERS_POSITIVELY_STOPPED':f.stops[1]['returned']=False
    elif guard=='EVERY_COPY_EQUALS_PINNED_PHYSICAL_ORIGINAL':f.template['resources/alpha.bin']['sha256']='f'*64
    else:os.link(f.root/'resources/alpha.bin',f.root/'NONCANONICAL-HARDLINK')
    with pytest.raises(ValueError):m.plan(f.root,f.stops,f.template)
    original=m.need
    def without(value,label):
        if label!=guard:original(value,label)
    monkeypatch.setattr(m,'need',without)
    assert m.plan(f.root,f.stops,f.template)['receipt']['copies']
def original_seal_fixture():
    path=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial339-P07-source-snapshot/producer/research/capital_risk/full_system_trials_job.py')
    raw=path.read_bytes();assert m.sha(raw)==m.SEAL_SHA
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='seal']
    return node
@pytest.mark.parametrize('kind',['members','bytes','symlink'])
def test_whole_original_seal_combined_guard_and_meaningful_removal(tmp_path,monkeypatch,kind):
    class Marker(Exception):pass
    class File:
        def __init__(self,index):self.index=index
        def is_file(self):return True
        def relative_to(self,root):return self
        def as_posix(self):return str(self.index)
        def stat(self):return types.SimpleNamespace(st_size=1024**3+1 if kind=='bytes' else 0)
        def is_symlink(self):return kind=='symlink'
        def __lt__(self,other):return self.index<other.index
    class Root:
        def rglob(self,pattern):return [File(i) for i in range(5000 if kind=='members' else 1)]
    def marker(*a,**k):raise Marker()
    scope=dict(need=m.need,re=__import__('re'),json=json,sha256_file=lambda p:'a'*64,os=os,EncryptWriter=marker)
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','b'*40)
    def compile_node(node):
        ns=dict(scope);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<WHOLE-ORIGINAL-SEAL-NONCANONICAL-FIXTURE>','exec'),ns);return ns['seal']
    node=original_seal_fixture();fn=compile_node(copy.deepcopy(node))
    with pytest.raises(ValueError,match='TRIAL_EXPORT_BOUND'):fn(Root(),tmp_path/'original',b'NONCANONICAL',tmp_path/'request','P07',protocol_sha256='a'*64)
    class Remove(ast.NodeTransformer):
        def visit_Expr(self,n):
            if isinstance(n.value,ast.Call) and n.value.args and isinstance(n.value.args[-1],ast.Constant) and n.value.args[-1].value=='TRIAL_EXPORT_BOUND':return ast.Pass()
            return self.generic_visit(n)
    mutant=compile_node(Remove().visit(node))
    with pytest.raises(Marker):mutant(Root(),tmp_path/'mutant',b'NONCANONICAL',tmp_path/'request','P07',protocol_sha256='a'*64)
@pytest.mark.parametrize('name',['research.pooled_input_support','stock_strategy_shared','sentinel','numpy','pandas'])
def test_import_fences(name):
    class Fence(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('LOSSLESS_DATA_ONLY')
    fence=Fence();sys.meta_path.insert(0,fence)
    try:
        with pytest.raises(ImportError):importlib.import_module(name)
    finally:sys.meta_path.remove(fence)
