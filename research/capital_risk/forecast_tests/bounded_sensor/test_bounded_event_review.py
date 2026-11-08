"""Source-bound event preimage DTOs and complete B19 induction AST undo."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('BOUNDED_EVENT_REVIEW_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
import system_campaign_bounded_sensor_event_review as data

def fixture(selected=True):
    v=json.loads((Path(data.__file__).parent/'P03-own462-DOVA-source-bound-input-catalog-v1.json').read_bytes())
    e=v['event'];sid=e['security_id'];members=[sid,'100'] if selected else ['100']
    anchor=[e['prior_session'],float(v['market_source']['raw_prior_row']['raw_close']),float(v['market_source']['raw_prior_row']['signal_close'])]
    before=dict(synthetic_metadata_only=True,last_processed_session=e['prior_session'],wealth_core=dict(episodes={}),pending=[],
        median5=dict(selected=members,selected_closes={n:anchor[2] for n in members}),
        feed=dict(series={sid:dict(signal_basis_anchor=anchor)}))
    basis=dict(session=e['effective_session'],security_id=sid,selected=selected,event_contract_sha256=data.digest(e),
        source_term_sha256=data.digest(dict(v['native'],session=e['effective_session'])),source_event_sha256=data.digest(v['market_source']))
    if selected:basis.update(prior_session=e['prior_session'],raw_anchor=str(anchor[1]),signal_anchor=str(anchor[2]),split='1',signal_consideration_interval=[27.5,29.])
    row=dict(session=e['effective_session'],material=dict(rows=[dict(security_id=n,prior=anchor[2],current=[27.5,29.] if n==sid else [anchor[2]]*2) for n in members]),bounded_event_basis=basis)
    return v,before,row

@pytest.mark.parametrize('selected',[True,False])
def test_actual_legal_and_raw_sources_bound_to_explicit_synthetic_preimage(selected):
    v,before,row=fixture(selected)
    assert data.event_basis(row,before,v)==(('2019-11-12',v['event']['security_id'],[27.5,29.]) if selected else None)

@pytest.mark.parametrize('change',['held','ordered','prior_day','event_day','selected','missing_member','duplicate_member','wrong_prior',
    'raw_anchor','signal_anchor','source_term','source_fact','right_range','material_range','foreign_basis','wrong_split'])
def test_wrong_preimage_source_ownership_or_legal_permission_refuses(change):
    v,before,row=fixture();sid=v['event']['security_id'];basis=row['bounded_event_basis']
    if change=='held':before['wealth_core']['episodes']['0']=dict(security_id=sid)
    elif change=='ordered':before['pending']=[dict(security_id=sid)]
    elif change=='prior_day':before['last_processed_session']='2019-11-08'
    elif change=='event_day':row['session']='2019-11-13'
    elif change=='selected':basis['selected']=False
    elif change=='missing_member':row['material']['rows'].pop()
    elif change=='duplicate_member':row['material']['rows'].append(deepcopy(row['material']['rows'][0]))
    elif change=='wrong_prior':row['material']['rows'][0]['prior']=1.
    elif change=='raw_anchor':before['feed']['series'][sid]['signal_basis_anchor'][1]=1.
    elif change=='signal_anchor':before['feed']['series'][sid]['signal_basis_anchor'][2]=1.
    elif change=='source_term':basis['source_term_sha256']='0'*64
    elif change=='source_fact':basis['source_event_sha256']='0'*64
    elif change=='right_range':basis['signal_consideration_interval']=[27.5,30.]
    elif change=='material_range':row['material']['rows'][0]['current']=[27.5,30.]
    elif change=='foreign_basis':basis['price_selected']=True
    else:basis['split']='2'
    with pytest.raises(ValueError):data.event_basis(row,before,v)

def removed(label):
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='event_basis')
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value==label for v in node.value.args):self.hits+=1;return None
            return self.generic_visit(node)
    remove=Remove();fn=ast.fix_missing_locations(remove.visit(fn));assert remove.hits==1
    scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-bounded-event-guard-DATA-only>','exec'),scope)
    return scope['event_basis']

@pytest.mark.parametrize('label,change',[('BOUNDED_REVIEW_ENTIRE_EXACT_LEGAL_ENDPOINT_RANGE','material'),
    ('BOUNDED_REVIEW_EXACT_ONE_EVENT_SOURCE_AND_LEGAL_BASIS','basis')])
def test_removing_guard_really_admits_wrong_material_or_source_basis(label,change):
    v,before,row=fixture()
    if change=='material':row['material']['rows'][0]['current']=[27.5,30.]
    else:row['bounded_event_basis']['source_term_sha256']='0'*64
    with pytest.raises(ValueError):data.event_basis(row,before,v)
    assert removed(label)(row,before,v)==('2019-11-12',v['event']['security_id'],[27.5,29.])

def test_whole_B19_induction_AST_restored_by_undoing_only_iterator_and_one_permission():
    import system_campaign_financial_additional_sensor as original
    tree=data.original_suffix_tree();loop,current=tree.body
    assert ast.unparse(loop.iter)=='enumerate(rows, start=retained_count)'
    loop.iter=ast.parse('enumerate(rows)',mode='eval').body
    guard=next(n for n in ast.walk(loop) if isinstance(n,ast.Call) and len(n.args)==2
        and isinstance(n.args[1],ast.Constant) and n.args[1].value=='BRANCH_ONLY_DECLARED_EVENT_MAY_VARY')
    assert isinstance(guard.args[0],ast.BoolOp) and len(guard.args[0].values)==2
    assert ast.unparse(guard.args[0].values[1])=='additional_event_allows(row, item)'
    guard.args[0]=guard.args[0].values[0]
    fn=original.function(original.source('system_campaign_financial_branches.py'),'review')
    old_loop=next(n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.target)=='(index, row)')
    old_current=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='BRANCH_EXACT_CURRENT_REPRESENTATIVE_STATE' for v in n.value.args))
    assert ast.dump(loop,include_attributes=False)==ast.dump(old_loop,include_attributes=False)
    assert ast.dump(current,include_attributes=False)==ast.dump(old_current,include_attributes=False)

def test_event_proof_is_required_only_when_committed_not_from_a_tail(tmp_path):
    v,_,_=fixture()
    assert data.permissions(tmp_path,[],v,through='2019-11-11',input_descriptors=[])==({},[])
    with pytest.raises(ValueError,match='REQUIRED_COMMITTED_EVENT_PROOF'):
        data.permissions(tmp_path,[],v,through='2019-11-12',input_descriptors=[])

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_runtime_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
