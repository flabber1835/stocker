"""Unselected retained runtime DATA/AST tests; no future root or book is created."""
import ast,json,sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest

class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P06_RETAINED_RUNTIME_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
P=Path(__file__).resolve().parents[2];D=P;C=P
sys.path[:0]=[str(P),str(D),str(C)]
import system_campaign_p06_abmd_retained_data as data
import system_campaign_p06_abmd_retained as runtime
import system_campaign_p06_abmd_retained_suffix as suffix
from forecast_tests.p06_reporting_bridge.test_p06_reporting_bridge import raw_target

@pytest.fixture
def synthetic_authority(monkeypatch,raw_target):
    """Explicitly noncanonical authority DTO; never serialized or registered."""
    import system_campaign_financial_partial as partial
    calls=[]
    def validator(value):
        assert value['root_admission_sha256']=='SYNTHETIC_AUTHORITY_DTO_NOT_A_SHA256'
        calls.append('ORIGINAL_AUTHORITY_SEAM_CALLED')
    monkeypatch.setattr(partial,'validate_root_spec',validator)
    target=deepcopy(raw_target)
    target.update(retained_uncertainty_model=data.reporting.TAG,root_admission_sha256='SYNTHETIC_AUTHORITY_DTO_NOT_A_SHA256',
        root_admission=dict(branch_uncertainty_proof=dict(passed=True,rows=6,retained_rows=0,
            all_comparisons_and_state_sets_verified=True,all_math_watch_financial_chains_verified=True)))
    return target,calls

def request(target):
    return dict(execution_mode=data.MODE,financial_resume_authorized=True,readonly_partial_review=False,
        readonly_source_witnesses=False,**{data.FIELD:{'P06':data.declaration(target)}})

def test_actual_unadmitted1259_target_is_not_selected_or_registered(raw_target):
    assert data.candidate(raw_target) is True
    assert data.selected(raw_target,{}) is False and data.selected(raw_target) is False
    with pytest.raises(ValueError,match='ACTUAL_NEW1259_ROOT_ADMISSION_REQUIRED'):data.declaration(raw_target)
    assert 'root_admission' not in raw_target

def test_real_root_validator_rejects_noncanonical_authority_DTO(raw_target):
    target=deepcopy(raw_target);target.update(root_admission={},root_admission_sha256='EXPLICIT_NONCANONICAL_DTO')
    with pytest.raises((ValueError,KeyError,TypeError)):data.admitted(target)

def test_selection_requires_authority_seam_and_exact_explicit_request(synthetic_authority):
    target,calls=synthetic_authority;decl=data.declaration(target)
    assert calls and decl['committed_seed_rows']==6 and decl['new_input_adoption'] is False
    assert data.selected(target) is False
    assert data.selected(target,request(target)) is True
    r=request(target);r['financial_resume_authorized']=False;assert data.selected(target,r) is False
    r=request(target);r[data.FIELD]['P06']['committed_seed_rows']=18;assert data.selected(target,r) is False

@pytest.mark.parametrize('change',['six_rows','tail_seed','proof_flag','tag','input','descriptor','old_initial_root','cursor'])
def test_observed_admission_metadata_and_six_literal_scope_refuse_mutations(synthetic_authority,change):
    target,calls=synthetic_authority
    if change=='six_rows':target['root_admission']['branch_uncertainty_proof']['rows']=7
    elif change=='tail_seed':target['root_admission']['branch_uncertainty_proof']['retained_rows']=12
    elif change=='proof_flag':target['root_admission']['branch_uncertainty_proof']['all_math_watch_financial_chains_verified']=False
    elif change=='tag':target.pop('retained_uncertainty_model')
    elif change=='input':target['input_sha256']='0'*64
    elif change=='descriptor':target['repairs'][9]['sha256']='0'*64
    elif change=='old_initial_root':target['root_admission_sha256']=data.initial.ROOT
    else:target['selected_session']='2023-01-19'
    with pytest.raises(ValueError):data.admitted(target)

def test_whole_original_suffix_review_AST_undo_only_adds_explicit_growth_keyword():
    import system_campaign_financial_uncertainty as original
    raw=Path(original.__file__).read_bytes();new=suffix.review_tree(raw)
    old=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='review_new_rows')
    call=next(n.value for n in new.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='scope')
    growth=call.keywords.pop();assert growth.arg=='growth' and ast.unparse(growth.value)=='mixed_growth'
    assert ast.dump(new,include_attributes=False)==ast.dump(old,include_attributes=False)
    # The separate original suffix loop itself remains unchanged and starts at
    # the genuine retained count; no event predicate is extended.
    loop=original.suffix_review_tree().body[0]
    assert ast.unparse(loop.iter)=='enumerate(rows, start=retained_count)'
    text=ast.unparse(loop)
    assert 'additional_event_allows' not in text and 'BRANCH_ONLY_DECLARED_EVENT_MAY_VARY' in text
    with pytest.raises(ValueError):suffix.review_tree(raw+b'\n# source changed\n')

def test_whole_original_unchanged_input_review_AST_is_untouched():
    import system_campaign_financial_uncertainty as original
    raw=Path(original.__file__).read_bytes();fn=data.unchanged_review_tree(raw)
    old=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='review_unchanged_input')
    assert ast.dump(fn,include_attributes=False)==ast.dump(old,include_attributes=False)
    assert "'future-financial-overlay.json'" in ast.unparse(fn)

def test_removing_literal_six_scope_guard_really_accepts_bad_seed_metadata(synthetic_authority):
    target,_=synthetic_authority;target['root_admission']['branch_uncertainty_proof']['rows']=18
    with pytest.raises(ValueError,match='ONLY_ACTUAL_ADMITTED_SIX_ROW_PROOF_SCOPE'):data.admitted(target)
    tree=ast.parse(Path(data.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='admitted')
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value=='P06_RETAINED_ONLY_ACTUAL_ADMITTED_SIX_ROW_PROOF_SCOPE' for v in node.value.args):
                self.hits+=1;return None
            return self.generic_visit(node)
    remove=Remove();fn=ast.fix_missing_locations(remove.visit(fn));assert remove.hits==1
    scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-six-proof-admission-guard-only>','exec'),scope)
    assert scope['admitted'](target)['target']['measured_closes']==1259

def point_suffix_DTO():
    """Toy recovery and point material; no canonical transition or financial book."""
    import system_campaign_financial_branches as branch
    from system_campaign_uncertainty_math import Interval,RollingWitnessBounds,growth
    from system_campaign_point_growth import point_growth
    R=data.reporting.HERE.parent
    proof=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial324-source-snapshot/capture-P06-13478656632-001/verified-output/uncertainty-certificate.jsonl')
    raw=Path('\\\\?\\'+str(proof.resolve())).read_bytes();assert data.sha(raw)==data.FULL_SHA
    observed=next(json.loads(line) for line in raw.splitlines() if json.loads(line)['session']=='2022-12-28')
    material=deepcopy(observed['material']['rows'])
    values=[Interval(*item['current']).div(Interval.point(item['prior'])).sub(Interval.point(1.)) for item in material]
    factor=point_growth(values);assert factor.pair()!=growth(values).pair()
    discrete=dict(version=2,episode=False,latched=False,full_streak=0,recent_positive_streak=0,
        previous_native=1.,previous_desired=1.,effective_native=1.,champion_audit=dict(episodes=0,concordance_releases=0))
    math=RollingWitnessBounds([1.]*41)
    for _ in range(6):math.advance(Interval.point(1.),1.)
    retained=[dict(math=deepcopy(math.snapshot()),possible_after=[deepcopy(discrete)]) for _ in range(6)]
    nav=factor.lo;math.advance(factor,nav);bounds={f'recent_r{n}':math.period(n) for n in (20,40)}
    scalars=dict(native=1.,wc_drawdown=-.05,spy_r20=.02,wc_r20=.01,recent_r20=nav-1.,recent_r40=nav-1.)
    toy=lambda **kw:(deepcopy(kw['state']),dict(desired_allocation=1.,reason='EXPLICIT_SYNTHETIC_RECOVERY'))
    kwargs=dict(scalars,state=dict(discrete,last_session='2023-01-03'))
    (after,decision),following,leaves=branch.cloud(toy,kwargs,bounds,[discrete])
    row=dict(session='2023-01-03',material=dict(rows=material,factor=factor.pair(),representative_nav=nav,
        observed={k:scalars[k] for k in bounds}),math=math.snapshot(),intervals={k:v.pair() for k,v in bounds.items()},
        scalar_inputs=scalars,before=deepcopy(discrete),after=branch.discrete(after),possible_before=[deepcopy(discrete)],
        possible_after=following,branches=leaves,decision=decision,every_reachable_canonical_decision_identical=True,
        representative_is_not_a_valuation=True,owned_position=False,pending_order=False)
    parent=dict(not_canonical_checkpoint=True,completed=1259,source_cursor='2022-12-30',run=dict(state=dict(median5=dict(discrete,witness_nav=[1.]*41))))
    current=dict(not_canonical_checkpoint=True,completed=1260,source_cursor='2023-01-03',run=dict(state=dict(median5=dict(discrete,witness_nav=[1.]*40+[nav]))))
    financial={'2023-01-03':dict(decision=dict(ldrc=decision,native_target_core_exposure=1.))}
    return parent,current,retained,[row],financial,SimpleNamespace(fresh=lambda **kw:deepcopy(discrete)),SimpleNamespace(recover=toy)

def test_explicit_point_growth_binding_works_and_removing_it_really_fails():
    import system_campaign_financial_uncertainty as original
    parent,current,retained,rows,financial,median5,champion=point_suffix_DTO()
    result=suffix.bind_review()(parent,current,retained,rows,financial,median5=median5,champion_config=champion)
    assert result['rows']==1 and result['every_reachable_decision_identical'] is True
    with pytest.raises(ValueError,match='BRANCH_INDEPENDENT_ACTUAL_OPERATION_ORDER'):
        original.review_new_rows(parent,current,retained,rows,financial,median5=median5,champion_config=champion)

@pytest.mark.parametrize('change',['factor','math','decision','possible','final','varying'])
def test_original_suffix_math_cloud_and_no_new_event_guards_remain(change):
    parent,current,retained,rows,financial,median5,champion=point_suffix_DTO();row=rows[0]
    if change=='factor':row['material']['factor'][0]=.1
    elif change=='math':row['math']['steps']=9
    elif change=='decision':row['decision']=dict(desired_allocation=0.,reason='BAD')
    elif change=='possible':row['possible_after']=[]
    elif change=='final':current['run']['state']['median5']['full_streak']=9
    else:row['material']['rows'][0]['current'][1]+=.1
    with pytest.raises(ValueError):suffix.bind_review()(parent,current,retained,rows,financial,median5=median5,champion_config=champion)

@pytest.mark.parametrize('mode',['preflight','economic'])
def test_only_ABMD_codec_full10_and_original_global_surfaces_restored(monkeypatch,tmp_path,synthetic_authority,mode):
    import full_system_core
    import system_campaign_financial_partial as partial
    import system_campaign_financial_uncertainty as legacy
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    target,_=synthetic_authority;calls=[];old_phase=legacy.uncertainty_phase
    # The frozen reporting selector intentionally identifies the same saved
    # metadata; the common dispatcher must exclude admitted roots from it.
    assert data.reporting.selected(target) is True
    def no_reporting_entry(*a,**k):raise AssertionError('ADMITTED_TARGET_MUST_NOT_ENTER_OLD_READONLY_BRIDGE')
    monkeypatch.setattr(data.reporting,'entry_context',no_reporting_entry)
    def old_models(*a):calls.append('OLD_MODELS');return True
    @contextmanager
    def old_context(*a):calls.append('OLD_CONTEXT');yield
    monkeypatch.setattr(partial,'retained_models',old_models);monkeypatch.setattr(partial,'model_context',old_context)
    monkeypatch.setattr(runtime,'full',lambda *a:calls.append('FULL10') or dict(full_inputs=10))
    monkeypatch.setattr(runtime.initial,'catalog',lambda:dict(event='EXPLICIT_SYNTHETIC_EVENT'))
    monkeypatch.setattr(runtime,'hydrate',lambda *a:('SYNTHETIC_NATIVE',{}));monkeypatch.setattr(runtime,'evidence_for',lambda value:[])
    class SyntheticCodec:
        def __init__(self,*a):calls.append('ONLY_ABMD_CODEC')
        def __enter__(self):calls.append('CODEC_ENTER')
        def __exit__(self,*a):calls.append('CODEC_EXIT')
    monkeypatch.setattr(runtime,'InputCodec',SyntheticCodec)
    module=SimpleNamespace(factual_overlay_needed=lambda t:True);old_overlay=module.factual_overlay_needed
    cp=dict(not_canonical_checkpoint=True,base=target['base'],repairs=target['repairs'],run=dict(input_sha256=target['input_sha256']))
    with runtime.entry_context(module,target,mode=mode,old=tmp_path,out=tmp_path,request=request(target)):
        assert partial.retained_models(tmp_path,cp,target) is True
        with partial.model_context(tmp_path,cp,target):pass
        assert module.factual_overlay_needed(target) is False and legacy.uncertainty_phase(target) is True
        assert partial.retained_models(tmp_path,cp,dict(arm='P03')) is True
    assert calls==['FULL10','ONLY_ABMD_CODEC','CODEC_ENTER','CODEC_EXIT','OLD_MODELS']
    assert partial.retained_models is old_models and partial.model_context is old_context
    assert legacy.uncertainty_phase is old_phase and module.factual_overlay_needed is old_overlay

def test_review_lifetime_wraps_whole_original_financial_inputs_and_has_no_ALDR_or_B19_codec():
    tree=ast.parse(Path(runtime.__file__).read_bytes());text=ast.unparse(tree)
    assert 'system_campaign_alder_date_v2' not in text and 'idempotent_dispatch' not in text
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='entry_context')
    assert 'stack.enter_context(partial.financial_inputs(Path(evidence), current, scratch, spec))' in ast.unparse(fn)
    assert 'from system_campaign_financial_branches import Codec' not in text
    run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    calls=[n for n in ast.walk(run) if isinstance(n,ast.Call) and ast.unparse(n.func)=='backtest.main']
    assert len(calls)==1 and ast.unparse(calls[0])=='backtest.main(args)'

def test_request_hook_uses_actual_admission_and_declares_unchanged_segment(monkeypatch,synthetic_authority,raw_target):
    target,_=synthetic_authority;monkeypatch.setattr(data,'source_names',lambda:())
    def base():return dict(sources={},admitted_checkpoints={'P06':target['outer_sha256']},arm_inputs={'P06':dict(new_factual_overlay=True)})
    result=runtime.expected_request(base,execution_mode=data.MODE,selected_arms=['P06'],root_lookup=lambda arm:target)
    assert result[data.FIELD]=={'P06':data.declaration(target)} and result['arm_inputs']['P06']['new_factual_overlay'] is False
    with pytest.raises(ValueError,match='ACTUAL_NEW1259_ROOT_ADMISSION_REQUIRED'):
        runtime.expected_request(base,execution_mode=data.MODE,selected_arms=['P06'],root_lookup=lambda arm:raw_target)
    foreign=base();foreign['admitted_checkpoints']['P06']='WRONG_SEED'
    with pytest.raises(ValueError,match='REQUEST_ACTUAL_ADMITTED_FINANCIAL_SEED'):
        runtime.expected_request(lambda:foreign,execution_mode=data.MODE,selected_arms=['P06'],root_lookup=lambda arm:target)

@pytest.mark.parametrize('name',['run','review','seed','preserve','ordinary_observer','arithmetic','entry'])
def test_hosted_fence_precedes_all_local_canonical_imports(monkeypatch,name):
    import full_system_core
    def refuse():raise ValueError('NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='NOT_HOSTED'):
        if name=='run':runtime.run(None,None,None,None,None,None,spec=None,old=None,request=None)
        elif name=='review':runtime.review(None,None,None,spec=None,old=None,request=None)
        elif name=='seed':runtime.seed(None,None,None)
        elif name=='preserve':runtime.preserve(None,None,None,None,None)
        elif name=='ordinary_observer':runtime.ordinary_observer(None,None,None)
        elif name=='arithmetic':runtime.arithmetic()
        else:
            with runtime.entry_context(None,None,mode='review',old=None,out=None,request=None):pass

@pytest.mark.parametrize('prefix',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(prefix):
    with pytest.raises(ImportError):Fence().find_spec(prefix)

def test_actual_newly_published1259_root_is_authoritative_metadata_only():
    from system_campaign_financial_partial import root_spec
    target=root_spec('P06')
    assert target['root_admission_sha256']=='41520825b51f125272ed44bb01ca58905fe7b170005fc1a1c4a72856bf01263f'
    declared=data.declaration(target)
    assert declared['financial_seed_root_admission_sha256']==target['root_admission_sha256']
    assert declared['committed_seed_rows']==6 and declared['new_input_adoption'] is False
    assert data.selected(target,request(target)) is True
