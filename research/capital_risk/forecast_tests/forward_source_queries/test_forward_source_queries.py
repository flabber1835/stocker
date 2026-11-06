"""Current own1152 source scope only; no financial runtime or new input."""
import ast
from copy import deepcopy
import json,sys
from pathlib import Path
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('FORWARD_SOURCE_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
import system_campaign_forward_source_queries as data

def root():
    from system_campaign_financial_partial import root_spec
    return root_spec('P05')

def test_exact102_source_identities_and_only_actual_ACC_held_role():
    q,=data.registry().queries;s=q.scope.model_dump()
    assert len(s['terms'])==102 and s['additional_rows']==[]
    held=[t for t in s['terms'] if t['parent_positions']];t,=held
    assert t['ticker']=='ACC' and t['parent_positions']==[dict(slot_id=16,ticker='ACC',quantity=29,entry_date='2022-06-30')]
    assert data.selected_scopes({},['P05'],enabled=True,root_lookup=lambda a:root())=={'P05':s}
    assert data.selected_scopes({'old':'preserved'},['P05'],enabled=False,root_lookup=lambda a:None)=={'old':'preserved'}

@pytest.mark.parametrize('change',['authority','adopted','cash','settlement','too_many','duplicate','past_identity','consumed_native','additional',
    'bool_quantity','zero_quantity','duplicate_slot','future_entry','bool_completed','bool_inputs'])
def test_monetary_authority_wrong_future_clock_or_current_role_refuses(change):
    v=data.registry().model_dump(by_alias=True);q=v['queries'][0];s=q['scope'];t=s['terms'][0]
    held=next(t for t in s['terms'] if t['parent_positions']);p=held['parent_positions'][0]
    if change=='authority':v['financial_authority']=True
    elif change=='adopted':v['input_adopted']=True
    elif change=='cash':t['cash_per_share']=65.47
    elif change=='settlement':q['settlement_authorized']=True
    elif change=='too_many':s['terms']=s['terms']*2
    elif change=='duplicate':s['terms'].append(deepcopy(t))
    elif change=='past_identity':t['session']=s['parent_cursor']
    elif change=='consumed_native':t['native_session']=s['parent_cursor']
    elif change=='additional':s['additional_rows']=[dict(session='2022-08-09')]
    elif change=='bool_quantity':p['quantity']=True
    elif change=='zero_quantity':p['quantity']=0
    elif change=='duplicate_slot':held['parent_positions'].append(deepcopy(p))
    elif change=='future_entry':p['entry_date']='2022-08-01'
    elif change=='bool_completed':q['parent_completed']=True
    else:q['parent_input_count']=True
    with pytest.raises(ValueError):data.Registry.model_validate(v)

@pytest.mark.parametrize('change',['outer','cursor','count','inputs','authority','arm'])
def test_foreign_or_stale_current_root_refuses(change):
    r=deepcopy(root())
    if change=='outer':r['outer_sha256']='0'*64
    elif change=='cursor':r['selected_session']='2022-06-30'
    elif change=='count':r['measured_closes']=1151
    elif change=='inputs':r['repairs']=r['repairs'][:-1]
    elif change=='authority':r['financial_authority']=True
    else:r['arm']='P07'
    with pytest.raises(ValueError):data.selected_scopes({},['P05'],enabled=True,root_lookup=lambda a:r)

def test_old_unheld_and_pending_query_catalogs_remain_unchanged():
    import system_campaign_explicit_source_queries as old
    import system_campaign_pending_native_source_queries_v2 as pending
    assert len(old.registry().queries)==3 and len(pending.registry().queries)==1
    assert data.sha((old.HERE/old.CATALOG).read_bytes())==old.CATALOG_SHA
    assert data.sha((pending.HERE/pending.CATALOG).read_bytes())==pending.CATALOG_SHA

def test_entire_original_payload_and_reconstruction_accept_all102_source_query_DTOs():
    import system_campaign_financial_future as future
    from system_campaign_financial_partial import HERE
    catalog=json.loads((HERE/'system-campaign-p05-own1070-supported-cash-inputs.json').read_bytes())
    old={t['native_term']['security_id']:t for t in catalog['source_data']['payload']['terms']}
    q,=data.registry().queries;scope=q.scope.model_dump();spec=root();episodes={}
    for term in scope['terms']:
        for p in term['parent_positions']:
            episodes[str(p['slot_id'])]=dict(slot_id=p['slot_id'],ticker=p['ticker'],security_id=term['security_id'],
                current_shares=p['quantity'],entry_date=p['entry_date'])
    # Source-query metadata only: no schema/journals/checkpoint/state hashes,
    # portfolio book or financial serialization. It never enters a runtime.
    dto=dict(not_canonical_checkpoint=True,sha256=scope['parent_outer_sha256'],source_cursor=scope['parent_cursor'],
        base=spec['base'],run=dict(state=dict(wealth_core=dict(episodes=episodes))))
    natives=[old[t['security_id']]['native_term'] for t in scope['terms']]
    rows=[old[t['security_id']]['source_row'] for t in scope['terms']]
    payload=future.witness_payload(dto,'P05',scope,natives,rows,[])
    assert payload['schema']=='research.own-parent-frozen-source-witnesses/1' and len(payload['terms'])==102
    assert payload.get('additional_rows',[])==[] and payload['financial_authority'] is payload['input_adopted'] is False
    assert future.validate_witness_capture(payload,spec,scope)==payload

def removed(class_name,name,label):
    tree=ast.parse(Path(data.__file__).read_bytes())
    nodes=tree.body if class_name is None else next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==class_name).body
    fn=next(n for n in nodes if isinstance(n,ast.FunctionDef) and n.name==name);fn.decorator_list=[]
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value==label for v in node.value.args):
                self.count+=1;return None
            return self.generic_visit(node)
    remove=Remove();fn=ast.fix_missing_locations(remove.visit(fn));assert remove.count==1
    scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<one-removed-forward-source-guard-DATA-only>','exec'),scope)
    return scope[name]

def test_meaningful_current_root_guard_removal_accepts_foreign_parent():
    r=deepcopy(root());r['outer_sha256']='0'*64
    label='FORWARD_SOURCE_EXACT_CURRENT_ROOT_AXIS_FULL_INPUT_COUNT_AND_AUTHORITY'
    with pytest.raises(ValueError):data.selected_scopes({},['P05'],enabled=True,root_lookup=lambda a:r)
    assert 'P05' in removed(None,'selected_scopes',label)({},['P05'],enabled=True,root_lookup=lambda a:r)

def test_meaningful_source_authority_guard_removal_accepts_financial_claim():
    registry=data.registry().model_copy(update=dict(financial_authority=True))
    with pytest.raises(ValueError):data.Registry.source_only(registry)
    assert removed('Registry','source_only','FORWARD_SOURCE_NO_INPUT_OR_FINANCIAL_AUTHORITY')(registry) is registry

@pytest.mark.parametrize('change,label',[('clock','FORWARD_SOURCE_UNIQUE_FUTURE_NATIVE_IDENTITIES'),
    ('roles','FORWARD_SOURCE_EXACT_CURRENT_POSITIONS_NOT_FUTURE_PREDICTIONS')])
def test_meaningful_clock_and_role_guard_removals(change,label):
    q,=data.registry().queries;scope=q.scope;terms=list(scope.terms)
    if change=='clock':terms[0]=terms[0].model_copy(update=dict(session=scope.parent_cursor))
    else:
        i=next(i for i,t in enumerate(terms) if t.parent_positions);term=terms[i]
        terms[i]=term.model_copy(update=dict(parent_positions=term.parent_positions*2))
    scope=scope.model_copy(update=dict(terms=terms))
    with pytest.raises(ValueError):data.Scope.exact_future_native_and_current_roles(scope)
    assert removed('Scope','exact_future_native_and_current_roles',label)(scope) is scope

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
