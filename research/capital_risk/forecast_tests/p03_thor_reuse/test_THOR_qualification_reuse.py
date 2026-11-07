import ast,inspect,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
D=Path('C:/GitHub/stocker/.codex-tmp/p03-fin337-thor-qualified-reuse-20261106');C=Path(__file__).parents[2];sys.path[:0]=[str(C)]
class Fence:
    def find_spec(self,name,path=None,target=None):
        if name.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('THOR_REUSE_DATA_ONLY:'+name)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_thor_qualification_reuse as reuse
from forecast_tests.p03_thor_reuse import review_FIN337_DATA as actual
from forecast_tests.p03_thor_reuse.audit_downstream_writers import audit
@pytest.fixture(scope='module')
def files():
    root,members,member,spec,parent,neutral,seed,qualified,boundary=actual.read()
    oldcap=actual.R/'financial324-source-snapshot/capture-P03-13476494369-001';old=actual.long(oldcap/'verified-output')
    manifest=json.loads((oldcap/'authenticated-manifest.json').read_bytes())['members']
    for n,pin in manifest.items():
        raw=(old/n).read_bytes();assert dict(bytes=len(raw),sha256=reuse.sha(raw))==pin
    return root,old,spec,parent,neutral,seed,qualified,json.loads(qualified)['exact_controller_sources']
def test_complete_real337_and_original324_boundary_seed_qualification_contract(files):
    out,old,spec,parent,neutral,seed,qualified,hashes=files
    result=reuse.qualification_contract(out,neutral,spec,old,seed,hashes,qualified)
    assert result['passed'] and result['unadmitted_tail_rows_seeded']==0 and result['financial_sessions_advanced']==0
    assert reuse.qualification_present(out,neutral,spec,old,seed,hashes,qualified) is True
def test_all_downstream_writers_and_latent_constructor_blocker_audited():
    result=audit()
    assert len(result['subsequent_new_resource_names_absent'])==7 and result['all324_original_members_hashed']==166
    assert result['known_retained_constructor_blocker']['original_predicate'] is False
@pytest.mark.parametrize('change',['missing_row','unadmitted_tail','state','input','neutral'])
def test_wrong_retained_seed_or_full_current_identity_refuses(files,change):
    _,_,spec,_,current,rows,_,_=files;rows=deepcopy(rows);current=deepcopy(current)
    if change=='missing_row':rows.pop()
    elif change=='unadmitted_tail':rows.append(deepcopy(rows[-1]))
    elif change=='state':current['run']['state_sha256']='0'*64
    elif change=='input':current['run']['input_sha256']='0'*64
    else:current['sha256']='0'*64
    with pytest.raises(ValueError):reuse.seed_contract(rows,current,spec)
def test_seed_guard_has_meaningful_removal_falsifier(files,monkeypatch):
    _,_,spec,_,current,rows,_,_=files;bad=deepcopy(rows);bad[0]['chain_sha256']='0'*64
    with pytest.raises(ValueError):reuse.seed_contract(bad,current,spec)
    need=reuse.need;monkeypatch.setattr(reuse,'need',lambda value,label:None if label=='THOR_REUSE_ONLY_REAL_NEUTRAL17_AND_BYTE_EXACT49_ADMITTED_SEED' else need(value,label))
    assert reuse.seed_contract(bad,current,spec)['rows']==49
def test_changed_qualified_bytes_refuse_without_touching_actual_file(files):
    out,old,spec,_,current,rows,qualified,hashes=files;before=(out/'branch-controller-qualification.json').read_bytes()
    with pytest.raises(ValueError):reuse.qualification_contract(out,current,spec,old,rows,hashes,qualified+b'corrupt DATA falsifier')
    assert (out/'branch-controller-qualification.json').read_bytes()==before
def test_wrong_six_source_map_refuses(files):
    out,old,spec,_,current,rows,qualified,hashes=files;bad=deepcopy(hashes);bad[next(iter(bad))]='0'*64
    with pytest.raises(ValueError):reuse.qualification_contract(out,current,spec,old,rows,bad,qualified)
def test_existing_output_guard_has_meaningful_removal_falsifier(tmp_path,monkeypatch):
    # Isolated qualification metadata only, no checkpoint or financial state.
    raw=b'explicit wrong noncanonical qualification DTO';(tmp_path/'branch-controller-qualification.json').write_bytes(raw)
    monkeypatch.setattr(reuse,'qualification_contract',lambda *a:None)
    with pytest.raises(ValueError):reuse.qualification_present(tmp_path,None,None,None,None,None,b'expected DATA')
    need=reuse.need;monkeypatch.setattr(reuse,'need',lambda value,label:None if label=='THOR_REUSE_EXISTING_OUTPUT_ONLY_IDENTICAL_QUALIFIED_DATA' else need(value,label))
    assert reuse.qualification_present(tmp_path,None,None,None,None,None,b'expected DATA') is True
def test_one_whole_run_body_targeted_undo_and_all_later_operations_remain():
    tree=reuse.run_tree();old=reuse.thor.typed.body_tree('run_retained')
    for name in ('Certificate','preserve','backtest.main'):
        assert sum(ast.unparse(n.func)==name for n in ast.walk(tree) if isinstance(n,ast.Call))==sum(ast.unparse(n.func)==name for n in ast.walk(old) if isinstance(n,ast.Call))
    assert sum('branch-controller-qualification.json' in ast.unparse(n.items[0].context_expr) for n in ast.walk(tree) if isinstance(n,ast.With))==1
def data_writer():
    fn=reuse.run_tree();assign,branch,post=[n for n in fn.body if (isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='qualification_was_present')
        or (isinstance(n,ast.If) and ast.unparse(n.test)=='not qualification_was_present')
        or (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='qualification_postcondition')]
    function=ast.parse('def write(out,qualified):\n    cp=spec=old=rows=hashes=None\n').body[0]
    function.body.extend([assign,branch,post]);return ast.fix_missing_locations(function)
@pytest.mark.parametrize('present',[True,False])
def test_isolated_DATA_dispatch_keeps_original_exclusive_writer_and_exact_existing_bytes(tmp_path,present):
    raw=b'explicit noncanonical qualification DATA DTO only';p=tmp_path/'branch-controller-qualification.json';created=[]
    if present:p.write_bytes(raw)
    def existing(out,*a):
        path=out/'branch-controller-qualification.json'
        if path.exists():assert path.read_bytes()==raw;return True
        return False
    def after(out,*args):created.append(args[-1]);assert (out/'branch-controller-qualification.json').read_bytes()==raw
    ns=dict(qualification_present=existing,qualification_postcondition=after)
    exec(compile(ast.Module(body=[data_writer()],type_ignores=[]),'<whole-original-exclusive-writer-isolated-DATA-dispatch>','exec'),ns)
    ns['write'](tmp_path,raw)
    assert p.read_bytes()==raw and created==[present]
def constructor_DTO():
    source=ast.parse(Path(reuse.binding.__file__).read_bytes())
    ctor,=[n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name=='__init__']
    factory=ast.parse('def factory(event):\n    class Target(Base):\n        pass\n    return Target\n').body[0]
    factory.body[0].body=[deepcopy(ctor)]
    class Base:
        def __init__(self,*a,seed=(),**k):self.seed=list(seed)
    namespace=dict(Base=Base,need=reuse.need)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[factory],type_ignores=[])),'<whole-original-constructor-body-noncanonical-seed-DTO-only>','exec'),namespace)
    return namespace['factory']
def test_original_constructor_body_keeps_code_and_closure_for_exact_real49_seed(files):
    _,_,spec,_,current,seed,_,_=files;event=reuse.thor.typed.catalog()['event'];factory=constructor_DTO()
    Original=factory(event);fn=Original.__init__
    with pytest.raises(ValueError,match='PRIOR_COMMITTED_B19_SEED'):Original(seed=seed)
    Bound=reuse.bind_constructor(Original,event,current,spec)
    assert Bound.__init__.__code__ is fn.__code__ and Bound.__init__.__closure__ is fn.__closure__
    value=Bound(seed=seed);assert value.seed==seed and value.bounded_basis is None
def test_changed_constructor_seed_remains_refused(files):
    _,_,spec,_,current,seed,_,_=files;event=reuse.thor.typed.catalog()['event'];Original=constructor_DTO()(event)
    Bound=reuse.bind_constructor(Original,event,current,spec)
    with pytest.raises(ValueError):Bound(seed=seed[:-1])
    # A different pre-native seed must not pass through the old True predicate.
    assert seed[0]['session']<event['native_session']
    with pytest.raises(ValueError):Bound(seed=seed[:1])
def test_only_exact_already_consumed_event_can_use_retained_constructor_scope(files):
    _,_,spec,_,current,seed,_,_=files;event=deepcopy(reuse.thor.typed.catalog()['event']);event['native_session']='2020-12-31'
    with pytest.raises(ValueError):reuse.constructor_seed(seed,event,current,spec)
def test_constructor_caller_guard_removal_is_meaningful_with_metadata_frame_DTO(files,monkeypatch):
    _,_,spec,_,current,seed,_,_=files;event=reuse.thor.typed.catalog()['event'];Original=constructor_DTO()(event)
    Bound=reuse.bind_constructor(Original,event,current,spec);instance=object.__new__(Bound);instance.seed=seed
    fn=Bound.__init__.__globals__['need'];frame=SimpleNamespace(f_code=(lambda:None).__code__,f_locals={'self':instance})
    with monkeypatch.context() as patch:
        patch.setattr(reuse.inspect,'currentframe',lambda:SimpleNamespace(f_back=frame))
        with pytest.raises(ValueError):fn(False,'PRIOR_COMMITTED_B19_SEED')
        need=reuse.need;patch.setattr(reuse,'need',lambda value,label:None if label=='THOR_REUSE_ONLY_REAL_ORIGINAL_CONSTRUCTOR_CALLER_AND_SELF' else need(value,label))
        assert fn(False,'PRIOR_COMMITTED_B19_SEED') is None
def test_failed337_does_not_gain_missing_certificate_review(files):
    out,_,spec,*_=files
    with pytest.raises(FileNotFoundError):reuse.review_receipt(out,spec)
def test_separate_corrective_request_required_and_future_restart_not_added(files):
    _,_,spec,*_=files;declaration=reuse.declaration(spec)
    request=dict(execution_mode=reuse.thor.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,
        **{reuse.thor.FIELD:{'P03':reuse.thor.declaration(spec)},reuse.FIELD:{'P03':declaration}})
    assert reuse.selected(spec,request)
    request[reuse.FIELD]['P03']['exact_duplicate_DATA_only']=False
    with pytest.raises(ValueError):reuse.selected(spec,request)
    assert declaration['future17_root_restart_selected'] is False
def test_no_blanket_IO_bypass_or_canonical_writer_added():
    tree=ast.parse(Path(reuse.__file__).read_bytes());calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
    assert not any(v.endswith(('.unlink','.replace','.chmod','.restore','.write_checkpoint','.main')) for v in calls)
    assert 'thor.boundary_relation' in calls and 'thor.exact' in calls
def test_whole_four_m_bodies_and_original_frozen_closure_match_actual337_source(files):
    _,_,_,_,_,_,_,_=files
    snapshot=(actual.F/'system_campaign_financial_resume.py').read_bytes();request=json.loads((actual.long(actual.CAP/'verified-output')/'request.json').read_bytes())
    assert reuse.sha(snapshot)==request['sources']['system_campaign_financial_resume.py']
    def bodies(raw):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(raw).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in ('preflight','economic','review','launch','AdoptionGate')}
    assert bodies(snapshot)==bodies((C/'system_campaign_financial_resume.py').read_bytes())
    tree=ast.parse(Path(reuse.__file__).read_bytes())
    fn,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='entry_context']
    assert any(isinstance(n,ast.If) and ast.unparse(n.test)=="request.get('execution_mode') != thor.MODE or not thor.selected(spec)" for n in fn.body)
@pytest.mark.parametrize('prefix',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_all_financial_import_fences(prefix):
    with pytest.raises(ImportError):Fence().find_spec(prefix)
