"""Source-preserving dispatch, no-advance receipts, readonly lifetime and restart DATA."""
import ast,builtins,copy,gzip,json,sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from test_additional_sensor import C,DEP,data,runtime,env,fixture,fence


def registered_retained(env,monkeypatch,index):
    """Synthetic metadata only; no future real root or canonical state is created."""
    catalog=env.u.own_policy_catalog()
    closed=dict(env.u.OWN_POLICY_CLOSED_GENERATIONS)
    closed[env.u.OWN_POLICY_SHA]=tuple(catalog['phases'])
    p=copy.deepcopy(env.p)
    p.update(root_admission_sha256=str(index)*64,outer_sha256=str(index+2)*64,
        source_cursor=('2022-03-31' if index==1 else '2022-04-29'),completed=1047+index,
        adoption_mode='RETAINED',ordinary_input_mode='UNCHANGED',proof_rows=593+index,
        proof_new_rows=1,proof_retained_rows=592+index,origin_record_sha256=data.sha(data.encoded(env.p)))
    catalog['phases'][p['root_admission_sha256']]=p
    raw=data.encoded(catalog)
    (env.overlay/env.u.OWN_POLICY_CATALOG).write_bytes(raw)
    monkeypatch.setattr(env.u,'OWN_POLICY_SHA',data.sha(raw))
    monkeypatch.setattr(env.u,'OWN_POLICY_CLOSED_GENERATIONS',closed)
    spec=dict(arm=p['arm'],root_admission_sha256=p['root_admission_sha256'],outer_sha256=p['outer_sha256'],
        selected_session=p['source_cursor'],measured_closes=p['completed'])
    return p,spec


def current_request(env,p):
    return dict(execution_mode='OWN_ADMITTED_FINANCIAL_CONTINUATION',financial_resume_authorized=True,
        financial_source_changed=False,selected_research_models={'P07':data.declaration(p,env.u.OWN_POLICY_SHA)},
        sources={env.u.OWN_POLICY_CATALOG:env.u.OWN_POLICY_SHA},admitted_checkpoints={'P07':p['outer_sha256']})


def test_two_registered_restarts_keep_initial_provenance_and_distinct_current_authority(env,monkeypatch):
    import system_campaign_financial_partial as partial
    initial=data.declaration(env.p,env.u.OWN_POLICY_SHA)
    previous=None
    for index in (1,2):
        p,spec=registered_retained(env,monkeypatch,index)
        spec['retained_additional_sensor']=copy.deepcopy(initial)
        assert data.selected_declaration(env.root,env.cp,spec)==p
        request=current_request(env,p)
        monkeypatch.setattr(partial,'root_spec',lambda arm,root:copy.deepcopy(spec))
        assert data.report_declaration(request,'P07')['retained_additional_sensor']==initial
        assert request['selected_research_models']['P07']['root_admission_sha256']==p['root_admission_sha256']
        exact=dict(spec,retained_additional_sensor=copy.deepcopy(request['selected_research_models']['P07']))
        assert data.selected_declaration(env.root,env.cp,exact)==p
        if previous is not None:
            with pytest.raises(ValueError,match='DECLARATION_EXACT'):
                data.selected_declaration(env.root,env.cp,dict(spec,retained_additional_sensor=previous))
        bad=copy.deepcopy(request);bad['selected_research_models']['P07']=copy.deepcopy(initial)
        with pytest.raises(ValueError,match='REPORT_EXACT_ORIGINAL_DECLARATION'):data.report_declaration(bad,'P07')
        previous=copy.deepcopy(request['selected_research_models']['P07'])
        assert spec['retained_additional_sensor']==initial


@pytest.mark.parametrize('bad',['root','generation','origin','source','model','prefix'])
def test_stored_initial_declaration_rejects_unknown_or_changed_provenance(env,monkeypatch,bad):
    initial=data.declaration(env.p,env.u.OWN_POLICY_SHA)
    p,spec=registered_retained(env,monkeypatch,1)
    spec['retained_additional_sensor']=initial
    if bad=='root':spec['root_admission_sha256']='f'*64
    if bad=='generation':initial['policy_catalog_sha256']='0'*64
    if bad=='origin':initial['origin_root_admission_sha256']='0'*64
    if bad=='source':initial['source_payload_sha256']='0'*64
    if bad=='model':initial['original_branch_descriptor']['predecessor_checkpoint_sha256']='0'*64
    if bad=='prefix':initial['retained_prefix_sha256']='0'*64
    with pytest.raises(ValueError):data.selected_declaration(env.root,env.cp,spec)


def test_initial_mode_accepts_only_its_own_exact_declaration(env,monkeypatch):
    initial=data.declaration(env.p,env.u.OWN_POLICY_SHA)
    spec=dict(env.spec,retained_additional_sensor=initial)
    assert data.selected_declaration(env.root,env.cp,spec)==env.p
    registered_retained(env,monkeypatch,1)
    with pytest.raises(ValueError,match='DECLARATION_EXACT'):data.selected_declaration(env.root,env.cp,spec)


@pytest.mark.parametrize('field',['origin_record_sha256','event','ordinary_metadata','original_descriptors','policy_source_files'])
def test_retained_origin_cannot_change_any_original_binding(env,monkeypatch,field):
    p,_=registered_retained(env,monkeypatch,1)
    assert data.retained_origin(p)==env.p
    bad=copy.deepcopy(p)
    bad[field]='changed'
    with pytest.raises(ValueError):data.retained_origin(bad)


def test_retained_origin_binding_guard_removal_is_detected(env,monkeypatch):
    p,_=registered_retained(env,monkeypatch,1)
    p['event']=dict(p['event'],native_session='2022-03-03')
    with pytest.raises(ValueError,match='ALL_ORIGINAL_MODEL_SOURCE'):data.retained_origin(p)
    fn=data.function(Path(data.__file__).read_bytes(),'retained_origin')
    call,=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need'
        and isinstance(n.args[-1],ast.Constant) and n.args[-1].value=='ADDITIONAL_ALL_ORIGINAL_MODEL_SOURCE_AND_OBSERVER_BINDINGS_UNCHANGED']
    call.args[0]=ast.Constant(True);scope=dict(vars(data))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-retained-origin-binding>','exec'),scope)
    assert scope['retained_origin'](p)==env.p

def test_all_original383_and_b19_bytes_and_legacy_p07_helpers_preserved():
    request=json.loads((DEP/'system-campaign-parallel-discovery-request-001.json').read_bytes())
    assert len(request['sources'])==383
    for name,h in request['sources'].items():
        assert data.sha((DEP/name).read_bytes())==h
        if (C/name).exists():assert (C/name).read_bytes()==(DEP/name).read_bytes()
    assert data.sha((DEP/'system_campaign_financial_branches.py').read_bytes())==data.EXPECTED['system_campaign_financial_branches.py']
    old=(DEP/'system_campaign_financial_uncertainty.py').read_bytes();new=(C/'system_campaign_financial_uncertainty.py').read_bytes()
    for name in ('run_retained','retained_seed','active_codec','point_return_phase','proof_scope','review_retained','review_new_rows','suffix_review_tree'):
        assert ast.dump(data.function(old,name),include_attributes=False)==ast.dump(data.function(new,name),include_attributes=False)

def test_every_earlier_policy_and_source_generation_stays_identical(env):
    actual=json.loads((env.overlay/env.u.OWN_POLICY_CATALOG).read_bytes())
    before=json.loads((DEP/env.u.OWN_POLICY_CATALOG).read_bytes())
    prior_keys = env.u.OWN_POLICY_CLOSED_GENERATIONS['6a867f721b31cd5fb71d1b965820facf2b48939158ed8d35432257eabd0d0ff1']
    before['phases'] = {k:before['phases'][k] for k in prior_keys}
    assert data.sha(data.encoded(before))=='6a867f721b31cd5fb71d1b965820facf2b48939158ed8d35432257eabd0d0ff1'
    assert {k:actual['phases'][k] for k in prior_keys}==before['phases']
    assert all(actual[k]==v for k,v in before.items() if k!='phases')
    assert data.sha(data.encoded(before)) in env.u.OWN_POLICY_CLOSED_GENERATIONS
    sources=json.loads((env.overlay/env.u.OWN_SOURCE_CATALOG).read_bytes())
    prior=json.loads((DEP/env.u.OWN_SOURCE_CATALOG).read_bytes())
    prior['sources'].pop(env.p['source_payload_sha256'],None)
    assert data.sha(data.encoded(prior))=='1387cb501b145a77b74e31e28140a913c63cebf08f19ab293015c475574141ac'
    assert {k:v for k,v in sources['sources'].items() if k!=env.p['source_payload_sha256']}==prior['sources']

@pytest.mark.parametrize('label',['ADDITIONAL_CLOSED_IDENTITY_ONLY_QUALIFICATION_SCHEMA'])
def test_source_qualification_guard_removal_admits_authority_flag(env,label):
    q=json.loads((env.overlay/env.u.OWN_SOURCE_CATALOG).read_bytes())['sources'][env.p['source_payload_sha256']]['qualification']
    q['financial_authority']=True
    with pytest.raises(ValueError):data.qualified_source_identity_only(q)
    fn=data.function(Path(data.__file__).read_bytes(),'qualified_source_identity_only')
    call,=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need']
    call.args[0]=ast.Constant(True);scope=dict(vars(data))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-identity-only-guard>','exec'),scope)
    assert scope['qualified_source_identity_only'](q) is True

def test_zero_advance_receipt_rechecks_both_independent_boundaries_and_observations(env,monkeypatch,tmp_path):
    root=tmp_path/'gate-data';root.mkdir();p=env.p
    cp0=dict(sha256=p['origin_outer_sha256']);cp1=dict(sha256='1'*64,run=dict(checkpoint_sha256='2'*64))
    current=dict(sha256='3'*64,repairs=['synthetic22'],base=dict(synthetic=True),run=dict(input_sha256='4'*64))
    metadata=dict(cp1_outer_sha256=cp1['sha256'],cp1_inner_sha256=cp1['run']['checkpoint_sha256'],cp2_outer_sha256=current['sha256'],
        observation_seed_bytes=8,observation_seed_sha256=data.sha(b'seedrows'))
    (root/data.ORIGIN).write_bytes(data.encoded(metadata))
    (root/'material.json').write_bytes(data.encoded(dict(terms=[dict(native_session='2022-05-18')])))
    for directory in (env.u.ORDINARY_ADOPTION,data.ADOPTION):(root/(directory+'-correlation-inputs.jsonl.gz')).write_bytes(gzip.compress(b'seedrows'))
    cloud=root/'additional-sensor-cloud-qualification';cloud.mkdir();(cloud/'branch-controller-qualification.json').write_bytes(b'synthetic cloud proof DATA')
    proof=dict(schema='research.retained-additional-sensor-zero-advance/1',passed=True,root_admission_sha256=p['origin_root_admission_sha256'],
        origin_sha256=data.sha((root/data.ORIGIN).read_bytes()),parent_outer_sha256=cp0['sha256'],cp1_outer_sha256=cp1['sha256'],cp2_outer_sha256=current['sha256'],
        original593_prefix_sha256=p['retained_prefix_sha256'],actual_parser_packets_and_two_neutral_adoptions_qualified=True,
        financial_sessions_advanced=0,canonical_financial_source_changed=False,observer_binding_sha256=data.digest(['synthetic origins']),
        cloud_qualification_sha256=data.sha((cloud/'branch-controller-qualification.json').read_bytes()))
    (root/data.QUALIFICATION).write_bytes(data.encoded(proof))
    monkeypatch.setattr(runtime,'hosted',lambda:None)
    monkeypatch.setattr(runtime,'validate_origin',lambda root,cp,p:(metadata,cp0))
    monkeypatch.setattr(runtime,'ordinary_api',lambda p:dict(hydration_name=lambda cp:'material.json',OVERLAY='ordinary.json'))
    monkeypatch.setattr(runtime,'observer_bindings',lambda root,p:['synthetic origins'])
    calls=[]
    def boundary(root,directory,prior,path,earliest):
        calls.append((directory,prior,path,earliest))
        if directory==env.u.ORDINARY_ADOPTION:return cp1
        assert prior is cp1 and path=='zogenix-sensor-input.json' and earliest==p['event']['native_session']
        return current
    monkeypatch.setattr(env.u,'boundary',boundary)
    assert runtime.verify_qualification(root,current,p)==(metadata,cp0)
    assert [c[0] for c in calls]==[env.u.ORDINARY_ADOPTION,data.ADOPTION]
    # A changed neutral boundary must stop the worker before final finance.
    bad=copy.deepcopy(current);bad['repairs']=['changed']
    with pytest.raises(ValueError,match='BOTH_ACTUAL_CANONICAL_NEUTRAL_BOUNDARIES'):runtime.verify_qualification(root,bad,p)
    (root/(data.ADOPTION+'-correlation-inputs.jsonl.gz')).write_bytes(gzip.compress(b'seedrows-new-row'))
    with pytest.raises(ValueError,match='ZERO_NEW_OBSERVATIONS'):runtime.verify_qualification(root,current,p)

@pytest.mark.parametrize('bad',['authority','advance','origin','observer','cloud'])
def test_preparation_receipt_cannot_authorize_finance_with_wrong_fields(env,monkeypatch,tmp_path,bad):
    # Test source guard itself with the exact stored receipt expression; no financial function runs.
    fn=data.function(Path(runtime.__file__).read_bytes(),'verify_qualification')
    guard,=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and
        any(isinstance(a,ast.Constant) and a.value=='ADDITIONAL_EXACT_CLOSED_ZERO_FINANCIAL_PREPARATION_GATE' for a in n.value.args)]
    origin=dict(cp1_outer_sha256='1'*64,cp2_outer_sha256='2'*64)
    root=tmp_path;(root/data.ORIGIN).write_bytes(data.encoded(origin))
    p=env.p;cp0=dict(sha256='0'*64)
    q=dict(schema='research.retained-additional-sensor-zero-advance/1',passed=True,root_admission_sha256=p['origin_root_admission_sha256'],
        origin_sha256=data.sha((root/data.ORIGIN).read_bytes()),parent_outer_sha256=cp0['sha256'],cp1_outer_sha256=origin['cp1_outer_sha256'],cp2_outer_sha256=origin['cp2_outer_sha256'],
        original593_prefix_sha256=p['retained_prefix_sha256'],actual_parser_packets_and_two_neutral_adoptions_qualified=True,
        financial_sessions_advanced=0,canonical_financial_source_changed=False,observer_binding_sha256=data.digest([]))
    scope=dict(data=data,Path=Path,root=root,p=p,q=q,cp0=cp0,value=origin,observer_bindings=lambda root,p:[])
    program=compile(ast.fix_missing_locations(ast.Module(body=[guard],type_ignores=[])),'<actual-zero-advance-receipt-guard>','exec')
    exec(program,scope)
    if bad=='authority':q['canonical_financial_source_changed']=True
    elif bad=='advance':q['financial_sessions_advanced']=1
    elif bad=='origin':q['origin_sha256']='0'*64
    elif bad=='observer':q['observer_binding_sha256']='0'*64
    else:q['actual_parser_packets_and_two_neutral_adoptions_qualified']=False
    with pytest.raises(ValueError):exec(program,scope)

def restart_source(tmp_path,p):
    root=tmp_path/'old';out=tmp_path/'out';root.mkdir();out.mkdir()
    value=dict(input_files={'synthetic-input-data.txt':'ignored-by-stub'})
    names={data.ORIGIN,data.QUALIFICATION,runtime.ORIGIN_DIR+'/cp0.json.gz','synthetic-input-data.txt',
        runtime.ORIGIN_DIR+'/entire-prior-certificate.jsonl','additional-sensor-cloud-qualification/branch-controller-qualification.json'}
    for directory in ('ordinary-input-adoption',data.ADOPTION):
        names.update({directory+'/checkpoint.json.gz',directory+'/proof.json',directory+'-correlation-inputs.jsonl.gz'})
    for name in names:
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(('synthetic DATA only '+name).encode())
    return root,out,value,names

def test_restart_preserves_gate_both_neutral_proofs_event_archive_and_only_committed_observations(env,monkeypatch,tmp_path):
    p=env.p;root,out,value,names=restart_source(tmp_path,p)
    event=root/'book/pre-event'/('2022-03-07-'+'a'*64+'.json.gz');event.parent.mkdir(parents=True);event.write_bytes(b'synthetic event archive DATA')
    names.add(event.relative_to(root).as_posix())
    committed=root/'nested/actual-future-event-2022-03-11.json'
    committed.parent.mkdir(parents=True);committed.write_bytes(b'synthetic committed actual observation DATA')
    (root/'actual-future-event-2022-12-31.json').write_bytes(b'truncated uncommitted tail')
    monkeypatch.setattr(data,'selected_declaration',lambda *a:p)
    monkeypatch.setattr(data,'descriptors',lambda *a:[({},dict(schema=data.SCHEMA))])
    monkeypatch.setattr(runtime,'validate_origin',lambda *a:(value,None))
    runtime.preserve(root,dict(source_cursor='2022-06-30'),out,{})
    for name in names:assert (out/name).read_bytes()==(root/name).read_bytes()
    assert (out/committed.relative_to(root)).read_bytes()==committed.read_bytes()
    assert not(out/'actual-future-event-2022-12-31.json').exists()

@pytest.mark.parametrize('cursor,required',[('2022-03-04',False),('2022-03-07',True)])
def test_restart_event_archive_required_only_after_actual_committed_event(env,monkeypatch,tmp_path,cursor,required):
    root,out,value,names=restart_source(tmp_path,env.p)
    monkeypatch.setattr(data,'selected_declaration',lambda *a:env.p)
    monkeypatch.setattr(data,'descriptors',lambda *a:[({},dict(schema=data.SCHEMA))])
    monkeypatch.setattr(runtime,'validate_origin',lambda *a:(value,None))
    if required:
        with pytest.raises(ValueError,match='COMMITTED_EVENT_ARCHIVE_REQUIRED'):runtime.preserve(root,dict(source_cursor=cursor),out,{})
    else:runtime.preserve(root,dict(source_cursor=cursor),out,{})

def test_original_review_body_runs_with_full_codec_lifetime_through_readonly(env,monkeypatch,tmp_path):
    # Only synthetic metadata bytes and mocked API calls. No checkpoint is restored.
    old=tmp_path/'old-input-reference';evidence=tmp_path/'evidence';out=tmp_path/'review';old.mkdir();evidence.mkdir();out.mkdir()
    (old/'synthetic-parent.gz').write_bytes(gzip.compress(b'{"synthetic_original_parent":true}'))
    (evidence/'book').mkdir();(evidence/'book/checkpoint.json.gz').write_bytes(gzip.compress(b'{"synthetic_full22_input_metadata":true}'))
    (evidence/'resume-tail-preflight.json').write_bytes(b'{"synthetic_no_journals":true}')
    active={'value':False};log=[]
    @contextmanager
    def inputs(root,current,scratch,spec):
        assert current==dict(synthetic_full22_input_metadata=True)
        active['value']=True;log.append('codec-enter')
        try:yield
        finally:active['value']=False;log.append('codec-exit')
    def check(label):
        def call(*args,**kwargs):
            assert active['value'],'CODEC_LIFETIME_REQUIRED';log.append(label)
        return call
    u=SimpleNamespace(uncertainty_phase=lambda spec:True,review=check('uncertainty'))
    def imports(name,globals=None,locals=None,fromlist=(),level=0):
        if name=='system_campaign_financial_resume':return resume
        if name=='system_campaign_financial_partial':return SimpleNamespace(financial_inputs=inputs)
        if name=='system_campaign_financial_uncertainty':return u
        return builtins.__import__(name,globals,locals,fromlist,level)
    def old_path(path):return old if path=='/old' else Path(path)
    resume=SimpleNamespace(__file__=str(C/'system_campaign_financial_resume.py'),
        __builtins__=dict(vars(builtins),__import__=imports),hosted=lambda:None,Path=old_path,json=json,gzip=gzip,
        strict_parent=lambda value,spec:value,readonly_review=check('readonly'),verify_correlation=check('correlation'),
        preserve_tails=check('tails'),verify_originals=check('originals'),need=data.need,sha256_file=lambda path:'expected-file-hash')
    fn=data.function(Path(runtime.__file__).read_bytes(),'review_driver');scope=dict(vars(runtime),hosted=lambda:None,__builtins__=resume.__builtins__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<actual-review-lifetime-dispatch-with-synthetic-API>','exec'),scope)
    spec=dict(arm='P07',root_admission={},selected_checkpoint='synthetic-parent.gz',outer_sha256='x',selected_file=dict(sha256='expected-file-hash'))
    scope['review_driver'](evidence,out,spec)
    assert log==['codec-enter','uncertainty','readonly','correlation','tails','originals','codec-exit']
    assert active['value'] is False
    # Old body without the documented lifetime fails at the first qualified call.
    oldfn=data.function((DEP/'system_campaign_financial_resume.py').read_bytes(),'review')
    ns=dict(vars(resume));exec(compile(ast.fix_missing_locations(ast.Module(body=[oldfn],type_ignores=[])),'<legacy-body-without-new-scope>','exec'),ns)
    with pytest.raises(AssertionError,match='LIFETIME_REQUIRED'):ns['review'](evidence,out,spec)


def synthetic_pause(e,monkeypatch,tmp_path,*,bad=None):
    imports_original=builtins.__import__;log=[];current=dict(synthetic_input_successor=True)
    signals=SimpleNamespace(SIGINT=2,SIGTERM=15);handlers={2:object(),15:object()}
    signals.getsignal=lambda key:handlers[key]
    signals.signal=lambda key,value:handlers.__setitem__(key,value)
    runtime_api=SimpleNamespace(advance=lambda *a,**k:pytest.fail('synthetic baseline advance should remain unused'))
    backtest=SimpleNamespace(write_json=lambda *a,**k:None)
    gate_holder=[]
    class Gate:
        def __init__(self,cp,book,directory,h,earliest):self.accepted=False;gate_holder.append(self)
        def __enter__(self):return self
        def __exit__(self,*args):pass
    class Observation:
        def __init__(self,path,rows):self.path=path;self.rows=rows
        def __enter__(self):self.path.write_bytes(gzip.compress(b''.join(self.rows)));return self
        def __exit__(self,*args):pass
    def imports(name,globals=None,locals=None,fromlist=(),level=0):
        if name=='research.pooled_vacancy_funding':return SimpleNamespace(backtest=backtest,journal=SimpleNamespace(read_checkpoint=lambda path:current),runtime=runtime_api)
        if name=='system_campaign_financial_resume':return SimpleNamespace(AdoptionGate=Gate)
        if name=='system_campaign_uncertainty_integration':return SimpleNamespace(AdmissionPause=Pause)
        if name=='system_campaign_factual_run':return SimpleNamespace(SeededObservation=Observation)
        return imports_original(name,globals,locals,fromlist,level)
    owner,=[n for n in ast.parse((DEP/'system_campaign_uncertainty_integration.py').read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='AdmissionPause']
    scope=dict(__builtins__=dict(vars(builtins),__import__=imports),signal=signals,Path=Path,need=data.need)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[owner],type_ignores=[])),'<original-pause-on-synthetic-driver-API>','exec'),scope);Pause=scope['AdmissionPause']
    def main(args):
        log.append('input-startup')
        signals.signal(signals.SIGTERM,lambda *a:log.append('graceful-pause'))
        if bad=='advance':runtime_api.advance()
        if bad!='not-paused':backtest.write_json(tmp_path/'status.json',dict(status='RESUMED'))
        gate_holder[-1].accepted=bad!='gate'
        return 1 if bad=='exit' else 0
    backtest.main=main
    monkeypatch.setitem(e.u.__dict__,'__builtins__',dict(vars(builtins),__import__=imports))
    monkeypatch.setattr(e.u,'hosted',lambda:None)
    monkeypatch.setattr(e.u,'boundary',lambda *a:current)
    return log,backtest,runtime_api,signals

@pytest.mark.parametrize('directory,filename',[('ordinary-input-adoption','future-financial-overlay.json'),(data.ADOPTION,'zogenix-sensor-input.json')])
def test_original_admission_pause_zero_advance_cooperation_for_each_new_boundary(env,monkeypatch,tmp_path,directory,filename):
    log,backtest,engine,signals=synthetic_pause(env,monkeypatch,tmp_path)
    path=tmp_path/filename;path.write_bytes(b'{"synthetic_input_only":true}')
    original_advance=engine.advance;original_write=backtest.write_json;original_handlers=dict((key,signals.getsignal(key)) for key in (2,15))
    result=runtime.pause(dict(source_cursor='2022-02-28'),tmp_path,[],[b'seed\n'],path,'2022-03-04',directory)
    assert result==dict(synthetic_input_successor=True) and log==['input-startup','graceful-pause']
    assert engine.advance is original_advance and backtest.write_json is original_write
    assert all(signals.getsignal(key) is value for key,value in original_handlers.items())

@pytest.mark.parametrize('bad',['advance','not-paused','gate','exit'])
def test_original_pause_refusals_prevent_boundary_acceptance(env,monkeypatch,tmp_path,bad):
    log,backtest,engine,signals=synthetic_pause(env,monkeypatch,tmp_path,bad=bad)
    path=tmp_path/'zogenix-sensor-input.json';path.write_bytes(b'{"synthetic_input_only":true}')
    with pytest.raises(ValueError):runtime.pause(dict(source_cursor='2022-02-28'),tmp_path,[],[],path,'2022-03-04',data.ADOPTION)
