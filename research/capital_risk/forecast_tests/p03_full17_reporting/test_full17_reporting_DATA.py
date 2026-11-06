import ast,json,math,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from forecast_tests.p03_full17_reporting.prepare_target_DATA import C,D,Fence,sha
import system_campaign_p03_full17_reporting as report
from forecast_tests.p03_full17_reporting import review_FIN340_DATA as data

@pytest.fixture(scope='module')
def target():return json.loads((D/'P03-FIN340-full17-target.json').read_bytes())
@pytest.fixture(scope='module')
def actual():return data.actual()
def request(target):
    return dict(execution_mode=report.MODE,financial_resume_authorized=False,readonly_partial_review=True,
        readonly_source_witnesses=False,maximum_parallel_financial_workers=0,selected_p03_thor_qualification_reuse={},
        **{report.FIELD:{'P03':report.declaration(target)}})
def test_actual_target_and_separate_503_seed(target):
    qualified=report.qualify_target(target)
    assert report.validate_target(qualified)['total_committed_proof_rows']==70
    assert report.request_declaration(qualified,request(qualified))['full_inputs']==17
    assert qualified['monthly_seed_root_admission_sha256']==report.ROOT and qualified['measured_closes']==524
    assert 'root_admission' not in qualified and qualified['financial_authority'] is False
@pytest.mark.parametrize('change',['seed','input','count','clock','authority','root','journal','extra','marker'])
def test_target_changes_refused(target,change):
    v=deepcopy(target)
    if change=='seed':v['monthly_seed_root_admission_sha256']='0'*64
    elif change=='input':v['repairs'].pop()
    elif change=='count':v['measured_closes']=525
    elif change=='clock':v['selected_session']='2020-02-03'
    elif change=='authority':v['financial_authority']=True
    elif change=='root':v['root_admission']={}
    elif change=='journal':v['journals']['daily']['bytes']+=1
    elif change=='marker':v[report.MARKER]={}
    else:v['foreign']=True
    with pytest.raises(ValueError):report.qualify_target(v)
@pytest.mark.parametrize('change',['financial','workers','source','readonly','reuse','mode','declaration'])
def test_only_zero_financial_readonly_request(target,change):
    v=report.qualify_target(target);r=request(v)
    if change=='financial':r['financial_resume_authorized']=True
    elif change=='workers':r['maximum_parallel_financial_workers']=1
    elif change=='source':r['readonly_source_witnesses']=True
    elif change=='readonly':r['readonly_partial_review']=False
    elif change=='reuse':r['selected_p03_thor_qualification_reuse']={'P03':{}}
    elif change=='mode':r['execution_mode']='OWN_ADMITTED_FINANCIAL_CONTINUATION'
    else:r[report.FIELD]['P03']['full_inputs']=16
    with pytest.raises(ValueError):report.request_declaration(v,r)
def test_request_adds_pins_and_explicit_finite_declaration(target):
    v=report.qualify_target(target)
    got=report.expected_request(lambda:dict(sources={}),execution_mode=report.MODE,selected_arms=('P03','P05'),target_lookup=lambda a:v if a=='P03' else {'arm':'P05'})
    assert got[report.FIELD]=={'P03':report.declaration(v)} and set(got['sources'])==set(report.source_names())
    got=report.expected_request(lambda:dict(sources={}),execution_mode='OWN_ADMITTED_FINANCIAL_CONTINUATION',selected_arms=('P03',),target_lookup=lambda a:v)
    assert got[report.FIELD]=={}
def test_original_AST_and_frozen_sources(monkeypatch):
    fact=report.fact();monkeypatch.setattr(report,'fact',lambda:fact);monkeypatch.setattr(report,'HERE',C)
    report.source_contract(SimpleNamespace(__file__=str(C/'system_campaign_financial_resume.py')))
def test_only_actual_existing_bounded_context_and_no_financial_reuse():
    import system_campaign_bounded_sensor_runtime_v2 as dova
    module=SimpleNamespace(financial_inputs=lambda *a:None,review=lambda *a:None,factual_overlay_needed=lambda *a:False)
    with pytest.raises(ValueError):report.active_bounded_context(module)
    with dova.entry_context(module,json.loads((D/'P03-FIN340-full17-target.json').read_bytes())):
        report.active_bounded_context(module)
        import system_campaign_financial_uncertainty as legacy
        saved=legacy.run
        try:
            legacy.run=lambda *a,**k:None
            with pytest.raises(ValueError):report.active_bounded_context(module)
        finally:legacy.run=saved
def test_actual_full70_proof_and21_accounting(actual):
    assert data.branch(actual)['rows']==21 and data.accounting(actual)['raw_accounting_snapshots']==42
    assert len(actual['rows'])==70 and len(actual['current']['repairs'])==17
def test_full17_typed_origin_all19_observer_terms(actual):
    proof=data.inputs_and_observers(actual)
    assert proof['full_inputs']==17 and proof['original_observers']['observation_terms']==19
    assert [v['ticker'] for v in proof['original_observers']['cash_events']]==['CBLK','MDCO','ARQL','THOR2']
def test_whole_observer_reader_three_site_undo():
    original=next(n for n in ast.parse(data.old_reader.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='ordinary_review')
    tree=data.ordinary_tree()
    class Undo(ast.NodeTransformer):
        count=merge=reported=0
        def visit_Compare(self,node):
            if ast.unparse(node)=="len(current['repairs']) == 17":self.count+=1;node.comparators[0]=ast.Constant(16)
            return self.generic_visit(node)
        def visit_Assign(self,node):
            if ast.unparse(node)=="terms = ordinary.merge(inventory['terms'], ordinary.tail_materials(root, current)[0])":self.merge+=1;node.value=ast.parse("inventory['terms']",mode='eval').body
            return self.generic_visit(node)
        def visit_keyword(self,node):
            if node.arg=='observation_terms' and ast.unparse(node.value)=='len(terms)':self.reported+=1;node.value=ast.Constant(18)
            return self.generic_visit(node)
    undo=Undo();tree=undo.visit(tree)
    assert undo.count==undo.merge==undo.reported==1 and ast.dump(tree.body[0],include_attributes=False)==ast.dump(original,include_attributes=False)
@pytest.mark.parametrize('change',['factor','foreign_interval','observed','leaf_coverage','state_set','financial_decision','final_endpoint','oracle_scope'])
def test_independent_new21_semantic_mutations(actual,change):
    rows=deepcopy(actual['rows'][49:]);financial=deepcopy(actual['financial']);current=deepcopy(actual['current']);oracle=deepcopy(actual['oracle']);row=rows[0]
    if change=='factor':row['material']['factor'][0]=math.nextafter(row['material']['factor'][0],-math.inf)
    elif change=='foreign_interval':row['material']['rows'][0]['current'][1]=math.nextafter(row['material']['rows'][0]['current'][1],math.inf)
    elif change=='observed':row['material']['observed']['recent_r20']=float('inf')
    elif change=='leaf_coverage':
        leaf=row['branches'][0];key=next(k for k,v in leaf['domains'].items() if v is not None);leaf['domains'][key][0]=math.nextafter(leaf['domains'][key][0],math.inf)
    elif change=='state_set':row['possible_after']=[]
    elif change=='financial_decision':financial[0]['decision']['ldrc']={'FOREIGN':True}
    elif change=='final_endpoint':current['run']['state']['median5']['full_streak']+=1
    else:oracle['exhaustive_leaves']+=1
    with pytest.raises((ValueError,KeyError)):data.branch(actual,rows=rows,financial=financial,current=current,oracle=oracle)
def test_accounting_mutation_refused(actual):
    rows=deepcopy(actual['financial']);rows[0]['economics']['parent_core_close_equity']='1'
    with pytest.raises(ValueError):data.accounting(actual,rows)
def test_whole_induction_undo():
    raw=data.data.read(data.data.INDEPENDENT);old=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='review')
    loop=next(n for n in old.body if isinstance(n,ast.For) and ast.unparse(n.target)=='(index, row)')
    guards=[n for n in old.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value in ('EXACT_CURRENT_STATE','EXACT_SEPARATE_TRANSITION_ORACLE_SCOPE') for a in n.value.args)]
    changed=data.data.induction_tree(raw);changed.body[0].iter=deepcopy(loop.iter)
    class Undo(ast.NodeTransformer):
        hits=0
        def visit_BoolOp(self,node):
            if ast.unparse(node)=='additional_event_allows(row, item) or bound.lo == bound.hi':
                self.hits+=1;return ast.copy_location(ast.parse("row['session'] == DAY and item['security_id'] == SID or bound.lo == bound.hi",mode='eval').body,node)
            return self.generic_visit(node)
    undo=Undo();changed=undo.visit(changed)
    assert undo.hits==1 and ast.dump(changed,include_attributes=False)==ast.dump(ast.Module(body=[loop,*guards],type_ignores=[]),include_attributes=False)
def test_target_guard_removal_is_meaningful(target):
    tree=ast.parse(Path(report.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='validate_target')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='P03_REPORT_EVERY_EXACT_TRANSPORT_TARGET_FIELD' for a in n.value.args))
    fn.body.remove(guard);scope=dict(vars(report));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-exact-target-guard>','exec'),scope)
    v=deepcopy(target);v['measured_closes']=525
    with pytest.raises(ValueError):report.validate_target(v)
    assert scope['validate_target'](v)['target']['measured_closes']==524
def test_request_authority_guard_removal_is_meaningful(target):
    fn=next(n for n in ast.parse(Path(report.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='request_declaration')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='P03_REPORT_ONLY_EXPLICIT_READONLY_ZERO_FINANCIAL_REQUEST' for a in n.value.args))
    fn.body.remove(guard);scope=dict(vars(report));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-readonly-authority-guard>','exec'),scope)
    v=report.qualify_target(target);r=request(v);r['financial_resume_authorized']=True
    with pytest.raises(ValueError):report.request_declaration(v,r)
    assert scope['request_declaration'](v,r)['financial_resume_authorized'] is False
def test_source_AST_guard_removal_is_meaningful(tmp_path,monkeypatch):
    value=report.fact();names=set(value['frozen_sources'])|set(value['original_AST'])
    for name in names:(tmp_path/name).write_bytes((C/name).read_bytes())
    p=tmp_path/'system_campaign_financial_partial.py';raw=p.read_bytes();needle=b'def monthly_reproduction(evidence, out, spec, current):'
    assert raw.count(needle)==1;p.write_bytes(raw.replace(needle,needle+b'\n    FOREIGN = True',1))
    monkeypatch.setattr(report,'HERE',tmp_path);monkeypatch.setattr(report,'fact',lambda:value)
    module=SimpleNamespace(__file__=str(tmp_path/'system_campaign_financial_resume.py'))
    with pytest.raises(ValueError,match='WHOLE_ORIGINAL_DRIVER_RETENTION_AND_MONTHLY_AST'):report.source_contract(module)
    fn=next(n for n in ast.parse(Path(report.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='source_contract')
    loop=next(n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.iter)=="value['original_AST'].items()")
    guard=next(n for n in loop.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and 'P03_REPORT_WHOLE_ORIGINAL_DRIVER_RETENTION_AND_MONTHLY_AST' in ast.unparse(n))
    loop.body.remove(guard);scope=dict(vars(report));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-whole-original-reporting-AST-guard>','exec'),scope)
    scope['source_contract'](module)
@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_all_five_import_fences(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
