"""DATA/AST qualification only; every state-like DTO below is noncanonical."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest

class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P06_LIFECYCLE_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
C=Path(__file__).resolve().parents[2];P=C;D=C
sys.path[:0]=[str(P),str(D),str(C)]
import system_campaign_p06_abmd_lifecycle_data as data
import system_campaign_p06_abmd_lifecycle as lifecycle
import system_campaign_p06_abmd_gateway as gateway
from system_campaign_bounded_sensor_input import sha,digest
from system_campaign_abmd_bounded_catalog import encoded,document

@pytest.fixture
def catalog():return json.loads((D/data.CATALOG).read_bytes())

def function(raw,name):return next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name)

def test_entire_original_pause_body_changes_only_one_explicit_filename_map():
    raw=(C/'system_campaign_financial_uncertainty.py').read_bytes()
    original=function(raw,'paused_own_adoption');new=data.adoption_tree(raw)
    mapping=next(n.value for n in new.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names')
    assert ast.literal_eval(mapping.keys.pop())==data.BOUND_DIRECTORY
    assert ast.literal_eval(mapping.values.pop())==data.BOUND_DOCUMENT
    assert ast.dump(new,include_attributes=False)==ast.dump(original,include_attributes=False)

def test_original_initial_induction_and_current_guard_retained_without_iterator_offset():
    raw=(C/'system_campaign_financial_branches.py').read_bytes();old=function(raw,'review')
    loop=next(n for n in old.body if isinstance(n,ast.For) and ast.unparse(n.target)=='(index, row)')
    current=next(n for n in old.body if isinstance(n,ast.Expr) and 'BRANCH_EXACT_CURRENT_REPRESENTATIVE_STATE' in ast.unparse(n))
    expected=ast.Module(body=[loop,current],type_ignores=[]);actual=data.initial_review_tree(raw)
    first=next(n for n in loop.body if isinstance(n,ast.If) and ast.unparse(n.test)=='index == 0')
    first.body=ast.parse('qualified_initial_event(row,before)').body
    assert ast.dump(actual,include_attributes=False)==ast.dump(expected,include_attributes=False)
    assert ast.unparse(actual.body[0].iter)=='enumerate(rows)'
    text=ast.unparse(actual)
    for guard in ('BRANCH_ONLY_DECLARED_EVENT_MAY_VARY','BRANCH_EVERY_ROUNDING_AWARE_MATH_CONTINUATION',
                  'BRANCH_INDEPENDENT_EXHAUSTIVE_STATES_AND_DECISIONS','BRANCH_EXACT_ACTUAL_FINANCIAL_CONTROLLER_DECISION'):
        assert guard in text

@pytest.mark.parametrize('which',['pause','induction'])
def test_whole_original_source_mutations_refused(which):
    name='system_campaign_financial_uncertainty.py' if which=='pause' else 'system_campaign_financial_branches.py'
    helper=data.adoption_tree if which=='pause' else data.initial_review_tree
    with pytest.raises(ValueError,match='ORIGINAL'):
        helper((C/name).read_bytes()+b'\n# changed source\n')

def test_complete_original_resource_plan_and_forward_term_are_authenticated():
    plan=data.plan();assert len(plan['old_descriptors'])==8
    root=Path('C:/Users/mbron/.codex/visualizations/2026/11/03/01a1a1b6-c8b7-7800-b947-f49191928329/financial-runs-20261104-281/capture-P06-13413225228-001/verified-output')
    resources=data.checked_resources(Path('\\\\?\\'+str(root.resolve())),plan)
    assert len(resources)==18 and sum(name.startswith('actual-future-event-') for name in resources)==8
    assert json.loads(resources['source-bindings.json']) and sha(resources['source-bindings.json'])==plan['source_binding_sha256']
    forward=data.forward_terms(plan);assert len(forward)==1
    assert forward[0]['ticker']=='MYOV' and forward[0]['added']==plan['forward_terms'][0]['added']

def test_resource_guard_has_a_meaningful_falsifier(tmp_path):
    plan=data.plan()
    tiny=dict(old_resources={'one.json':dict(bytes=1,sha256=sha(b'a'))})
    (tmp_path/'one.json').write_bytes(b'b')
    with pytest.raises(ValueError,match='ALL_OLD_SOURCE_AND_EVENT_BYTES'):data.checked_resources(tmp_path,tiny)
    raw=Path(data.__file__).read_bytes();fn=function(raw,'checked_resources')
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,node):
            if 'P06_LIFECYCLE_ALL_OLD_SOURCE_AND_EVENT_BYTES' in ast.unparse(node):self.hits+=1;return None
            if 'P06_LIFECYCLE_COMPLETE_ORIGINAL_RESOURCE_SET' in ast.unparse(node):return None
            return self.generic_visit(node)
    remove=Remove();fn=ast.fix_missing_locations(remove.visit(fn));assert remove.hits==1
    namespace=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-resource-identity-guard>','exec'),namespace)
    assert namespace['checked_resources'](tmp_path,tiny)=={'one.json':b'b'}

@pytest.mark.parametrize('change',['missing','cash','descriptor','sid'])
def test_only_exact_already_adopted_forward_MYOV_is_observed(change):
    plan=deepcopy(data.plan())
    if change=='missing':plan['forward_terms']=[]
    elif change=='cash':plan['forward_terms'][0]['added']['cash_per_share']=28.
    elif change=='sid':plan['forward_terms'][0]['added']['security_id']='1'
    else:plan['forward_terms'][0]['descriptor']['sha256']='0'*64
    with pytest.raises(ValueError):data.forward_terms(plan)

def test_preparation_requires_every_exact_receipt_and_source_byte(tmp_path,catalog):
    hashes={'controller/'+str(i):str(i)*64 for i in range(6)}
    receipt=data.expected_preparation(catalog,hashes)
    cloud=dict(passed=True,exact_controller_sources=hashes,ambiguous_comparisons_exhaustively_partitioned=True,
        all_possible_counters_retained_and_later_merged=True,actual_divergent_decisions_refused=True,historical_financial_sessions_advanced=0)
    (tmp_path/'abmd-synthetic-cloud').mkdir()
    files={'abmd-zero-transition-preparation.json':encoded(receipt),'abmd-preparation-input.json':encoded(document(catalog)),
        'abmd-preparation-event-source.json':encoded(catalog['market_source']),
        'abmd-synthetic-cloud/branch-controller-qualification.json':encoded(cloud)}
    for name,raw in files.items():(tmp_path/name).write_bytes(raw)
    lifecycle.require_preparation(tmp_path,catalog,hashes)
    for name,raw in files.items():
        (tmp_path/name).write_bytes(raw+b' ')
        with pytest.raises(ValueError):lifecycle.require_preparation(tmp_path,catalog,hashes)
        (tmp_path/name).write_bytes(raw)

def test_gateway_stream_accepts_whole_original_fsync_and_memory_stream_falsifier(tmp_path):
    from io import BytesIO,UnsupportedOperation
    from tempfile import TemporaryFile
    import system_campaign_financial_branches as branches
    from system_campaign_bounded_sensor_binding import bind_function
    append=bind_function(branches.Certificate.append,DAY='2022-12-22')
    record=dict(session='2022-12-22',input_sha256='a'*64,state_sha256='c'*64)
    def synthetic(stream):
        calls=[]
        obj=SimpleNamespace(not_canonical_certificate=True,pending=dict(schema=branches.SCHEMA,session='2022-12-22',
            input_sha256='a'*64,next_state_sha256='c'*64,synthetic_only=True),last_session=None,
            chain=branches.digest(branches.SCHEMA),stream=stream,rows=0,
            original_append=lambda journal,name,row:calls.append((name,row)))
        return obj,calls
    with TemporaryFile(mode='w+b',dir=tmp_path) as stream:
        obj,calls=synthetic(stream);append(obj,object(),'daily',record)
        stream.seek(0);proof=json.loads(stream.read())
        assert obj.rows==1 and obj.pending is None and proof['synthetic_only'] is True
        assert [name for name,row in calls]==['watch','daily']
        assert calls[0][1]['certificate_chain_sha256']==proof['chain_sha256']
    obj,calls=synthetic(BytesIO())
    with pytest.raises(UnsupportedOperation):append(obj,object(),'daily',record)
    assert calls==[]
    tree=ast.parse(Path(gateway.__file__).read_bytes())
    assert any(isinstance(n,ast.With) and any('TemporaryFile' in ast.unparse(item.context_expr) for item in n.items) for n in ast.walk(tree))

def synthetic_induction(catalog,selected):
    """Noncanonical DTO proof, using real interval/cloud arithmetic and a toy recovery."""
    import system_campaign_financial_branches as branch
    from system_campaign_uncertainty_math import Interval,RollingWitnessBounds,growth
    from system_campaign_bounded_sensor_event_review import event_basis
    sid=catalog['event']['security_id'];day='2022-12-22'
    discrete=dict(version=2,episode=False,latched=False,full_streak=0,recent_positive_streak=0,
        previous_native=1.,previous_desired=1.,effective_native=1.,champion_audit=dict(episodes=0,concordance_releases=0))
    names=([sid] if selected else [])+['SYNTHETIC_OTHER']
    nav=[1.02**n for n in range(41)]
    state=dict(discrete,last_session='2022-12-21',selected=names,
        selected_closes={name:381.02 if name==sid else 100. for name in names},witness_nav=nav)
    before=dict(not_canonical_state=True,wealth_core=dict(episodes={}),pending=[],last_processed_session='2022-12-21',median5=state,
        feed=dict(series={sid:dict(signal_basis_anchor=['2022-12-21',381.02,381.02])}))
    material=[dict(security_id=name,prior=state['selected_closes'][name],current=[380.,415.] if name==sid else [102.,102.]) for name in names]
    returns=[Interval(*item['current']).div(Interval.point(item['prior'])).sub(Interval.point(1.)) for item in material]
    factor=growth(returns);actual_nav=nav[-1]*factor.lo;math=RollingWitnessBounds(nav);math.advance(factor,actual_nav)
    after_nav=(nav+[actual_nav])[-41:];observed={f'recent_r{n}':actual_nav/after_nav[-n-1]-1 for n in (20,40)}
    bounds={f'recent_r{n}':math.period(n) for n in (20,40)}
    basis=dict(session=day,security_id=sid,selected=selected,event_contract_sha256=digest(catalog['event']),
        source_term_sha256=digest(dict(catalog['native'],session=day)),source_event_sha256=digest(catalog['market_source']))
    if selected:basis.update(prior_session='2022-12-21',raw_anchor='381.02',signal_anchor='381.02',split='1',signal_consideration_interval=[380.,415.])
    toy=lambda **kw:(deepcopy(kw['state']),dict(desired_allocation=1.,reason='SYNTHETIC_ONLY'))
    fresh=lambda **kw:deepcopy(discrete)
    kwargs=dict(state=dict(discrete,last_session=day),native=1.,wc_drawdown=-.05,spy_r20=.02,wc_r20=.01,**observed)
    (after,decision),following,leaves=branch.cloud(toy,kwargs,bounds,[discrete])
    row=dict(session=day,before=discrete,after=branch.discrete(after),possible_before=[discrete],possible_after=following,
        every_reachable_canonical_decision_identical=True,representative_is_not_a_valuation=True,owned_position=False,pending_order=False,
        event_basis=basis,bounded_event_basis=basis,material=dict(rows=material,factor=factor.pair(),representative_nav=actual_nav,observed=observed),
        math=math.snapshot(),intervals={k:v.pair() for k,v in bounds.items()},scalar_inputs={k:v for k,v in kwargs.items() if k!='state'},
        branches=leaves,decision=decision)
    callback=lambda r,b:event_basis(r,b,catalog)
    namespace=dict(vars(branch),rows=[row],before=before,cp=dict(run=dict(state=dict(median5=dict(discrete,witness_nav=after_nav)))),
        DAY=day,SID=sid,math_state=RollingWitnessBounds(nav),possible=[deepcopy(discrete)],representative=deepcopy(discrete),
        median5=SimpleNamespace(fresh=fresh),champion_config=SimpleNamespace(recover=toy),total=0,maximum=1,
        financial={day:dict(decision=dict(ldrc=decision,native_target_core_exposure=1.))},qualified_initial_event=callback)
    return namespace

@pytest.mark.parametrize('selected',[True,False])
def test_whole_original_initial_induction_accepts_qualified_synthetic_selected_and_point_cases(catalog,selected):
    scope=synthetic_induction(catalog,selected)
    exec(compile(data.initial_review_tree((C/'system_campaign_financial_branches.py').read_bytes()),'<synthetic-initial-induction-only>','exec'),scope)
    assert scope['total']==1 and scope['maximum']==1 and scope['math_state'].steps==1

@pytest.mark.parametrize('change',['range','before','factor','math','decision','possible','current','owned'])
def test_original_loop_and_independent_ABMD_preimage_refuse_corruption(catalog,change):
    scope=synthetic_induction(catalog,True);row=scope['rows'][0]
    if change=='range':row['material']['rows'][0]['current']=[380.,414.]
    elif change=='before':row['before']=dict(row['before'],full_streak=9)
    elif change=='factor':row['material']['factor'][0]=.1
    elif change=='math':row['math']['steps']=9
    elif change=='decision':row['decision']=dict(desired_allocation=0.,reason='BAD')
    elif change=='possible':row['possible_after']=[]
    elif change=='current':scope['cp']['run']['state']['median5']['full_streak']=4
    else:scope['before']['wealth_core']['episodes']['0']=dict(security_id=catalog['event']['security_id'])
    with pytest.raises(ValueError):
        exec(compile(data.initial_review_tree((C/'system_campaign_financial_branches.py').read_bytes()),'<synthetic-corruption-only>','exec'),scope)

def test_initial_preimage_guard_removal_is_detected_by_real_falsifier(catalog):
    scope=synthetic_induction(catalog,True);scope['before']['wealth_core']['episodes']['0']=dict(security_id=catalog['event']['security_id'])
    tree=data.initial_review_tree((C/'system_campaign_financial_branches.py').read_bytes())
    with pytest.raises(ValueError):exec(compile(tree,'<intact-first-event-guard>','exec'),scope)
    scope=synthetic_induction(catalog,True);scope['before']['wealth_core']['episodes']['0']=dict(security_id=catalog['event']['security_id'])
    first=next(n for n in tree.body[0].body if isinstance(n,ast.If) and ast.unparse(n.test)=='index == 0')
    first.body=[ast.Pass()];tree=ast.fix_missing_locations(tree)
    exec(compile(tree,'<removed-first-event-guard>','exec'),scope)
    assert scope['total']==1

@pytest.mark.parametrize('name',['run','review','preflight_entry','entry_context','gateway'])
def test_hosted_entry_refuses_before_any_financial_import(monkeypatch,name):
    import full_system_core
    def refuse():raise ValueError('NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='NOT_HOSTED'):
        if name=='run':lifecycle.run({},None,None,None,None,None)
        elif name=='review':lifecycle.review({},None,None)
        elif name=='preflight_entry':lifecycle.preflight_entry(None,None,{},None)
        elif name=='entry_context':
            with lifecycle.entry_context({}):pass
        else:gateway.qualify(None,None,None,None,None,inherited_root=None)
