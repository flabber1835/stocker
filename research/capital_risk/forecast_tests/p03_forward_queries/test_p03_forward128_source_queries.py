"""Exact first128 source-query DATA; no financial runtime or source capture."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P03_FORWARD_QUERY_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
import system_campaign_p03_forward_source_queries as data
import prepare_p03_forward128_DATA as prep

@pytest.fixture(scope='module')
def actual():
    from system_campaign_financial_partial import root_spec
    spec=root_spec('P03',prep.ROOT)
    r=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial324-source-snapshot/capture-P03-13476494369-001')
    def read(p):return Path(chr(92)*2+'?'+chr(92)+str(Path(p).resolve())).read_bytes()
    manifest=json.loads(read(r/'authenticated-manifest.json'))['members']
    def member(n):
        raw=read(r/'verified-output'/n);prep.need(dict(bytes=len(raw),sha256=prep.sha(raw))==manifest[n],'TEST_AUTHENTICATED_MEMBER');return raw
    raw=member(spec['selected_checkpoint']);assert dict(bytes=len(raw),sha256=prep.sha(raw))==spec['selected_file']
    parent=json.loads(gzip.decompress(raw))
    inventory=Path('C:/GitHub/stocker/.codex-tmp/remaining-action-inventory-20261105/final/remaining-action-inventory.jsonl').read_bytes()
    catalog,proof,records=prep.prepare(parent,spec,member,inventory)
    return dict(spec=spec,parent=parent,member=member,inventory=inventory,catalog=catalog,proof=proof,records=records)

def test_actual_admitted503_and_complete_first128_selection(actual):
    query,=data.registry().queries;scope=query.scope.model_dump();proof=actual['proof']
    assert data.registry().model_dump(by_alias=True)==actual['catalog']
    assert proof['query_catalog_sha256']==data.CATALOG_SHA and proof['total_uncovered_acquisition_native_records']==1179
    assert proof['selected_records']==128 and proof['remaining_records']==1051 and proof['current_held_queries']==[]
    assert (query.root_admission_sha256,query.parent_completed,query.parent_input_count)==(prep.ROOT,503,16)
    assert scope['terms'][0]['ticker']=='WAIR' and scope['terms'][-1]['ticker']=='EIDX'
    assert all(t['parent_positions']==[] for t in scope['terms'])
    thor,=[t for t in scope['terms'] if t['security_id']=='731910459224080858']
    assert (thor['ticker'],thor['session'],thor['native_session'])==('THOR2','2020-01-22','2020-01-23')
    covered,resources=prep.covered_inputs(actual['parent'],actual['member']);assert len(resources)==16
    assert all((t['native_session'],t['security_id']) not in covered for t in scope['terms'])
    assert data.selected_scopes({'unselected':'preserved'},['P03'],enabled=True,root_lookup=lambda arm:actual['spec'])=={'unselected':'preserved','P03':scope}
    assert data.selected_scopes({'unselected':'preserved'},['P03'],enabled=False,root_lookup=lambda arm:pytest.fail('DISABLED_LOOKUP'))=={'unselected':'preserved'}

def test_whole_original_query_module_AST_undo_at_only_three_sites():
    import system_campaign_forward_source_queries as old
    raw=Path(old.__file__).read_bytes();assert prep.sha(raw)==prep.OLD_MODULE_SHA
    before=ast.parse(raw);after=ast.parse(Path(data.__file__).read_bytes())
    for name in ('CATALOG','CATALOG_SHA'):
        original=next(n for n in before.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])==name)
        changed=next(n for n in after.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])==name);changed.value=deepcopy(original.value)
    query=next(n for n in after.body if isinstance(n,ast.ClassDef) and n.name=='Query')
    arm=next(n for n in query.body if isinstance(n,ast.AnnAssign) and ast.unparse(n.target)=='arm')
    assert ast.unparse(arm.annotation)=="Literal['P03']";arm.annotation=ast.parse("Literal['P05']",mode='eval').body
    assert ast.dump(before,include_attributes=False)==ast.dump(after,include_attributes=False)
    assert old.CATALOG_SHA=='8c42192d198c63d74c81d11afbe60c0c383d6d9595cd8bb3e9c73e2889e60115'
    assert old.sha((old.HERE/old.CATALOG).read_bytes())==old.CATALOG_SHA

@pytest.mark.parametrize('change',['authority','adopted','cash','settlement','too_many','duplicate','past_identity','consumed_native','additional',
    'bool_quantity','zero_quantity','duplicate_slot','future_entry','bool_completed','bool_inputs'])
def test_query_cannot_grant_money_or_predict_roles_or_exceed128(change):
    value=data.registry().model_dump(by_alias=True);q=value['queries'][0];scope=q['scope'];term=scope['terms'][0]
    p=dict(slot_id=1,ticker=term['ticker'],quantity=1,entry_date='2019-01-01')
    if change=='authority':value['financial_authority']=True
    elif change=='adopted':value['input_adopted']=True
    elif change=='cash':term['cash_per_share']=100.
    elif change=='settlement':q['settlement_authorized']=True
    elif change=='too_many':scope['terms']=scope['terms']+[deepcopy(term)]
    elif change=='duplicate':scope['terms'][1]=deepcopy(term)
    elif change=='past_identity':term['session']=scope['parent_cursor']
    elif change=='consumed_native':term['native_session']=scope['parent_cursor']
    elif change=='additional':scope['additional_rows']=[{'NONCANONICAL':True}]
    elif change=='bool_quantity':p['quantity']=True;term['parent_positions']=[p]
    elif change=='zero_quantity':p['quantity']=0;term['parent_positions']=[p]
    elif change=='duplicate_slot':term['parent_positions']=[p,deepcopy(p)]
    elif change=='future_entry':p['entry_date']='2020-01-01';term['parent_positions']=[p]
    elif change=='bool_completed':q['parent_completed']=True
    else:q['parent_input_count']=True
    with pytest.raises(ValueError):data.Registry.model_validate(value)

@pytest.mark.parametrize('change',['outer','cursor','count','inputs','authority','arm'])
def test_wrong_or_stale_current_root_refuses(actual,change):
    root=deepcopy(actual['spec'])
    if change=='outer':root['outer_sha256']='0'*64
    elif change=='cursor':root['selected_session']='2019-12-30'
    elif change=='count':root['measured_closes']=502
    elif change=='inputs':root['repairs']=root['repairs'][:-1]
    elif change=='authority':root['financial_authority']=True
    else:root['arm']='P05'
    with pytest.raises(ValueError):data.selected_scopes({},['P03'],enabled=True,root_lookup=lambda arm:root)

def payload_fixture(actual):
    import system_campaign_financial_future as future
    assert prep.sha(Path(future.__file__).read_bytes())=='54ebe4e7da0ecd090f5d9dc87a0dd80bb3571b34d2433127a12b35b1a102775c'
    query,=data.registry().queries;scope=query.scope.model_dump();spec=actual['spec']
    # Source-query protocol DTO only: no financial schema/journals/state hashes,
    # no quotes/volumes/valuation, no canonical book or serialization.
    dto=dict(NONCANONICAL_SOURCE_QUERY_METADATA_DTO=True,sha256=scope['parent_outer_sha256'],source_cursor=scope['parent_cursor'],
        base=spec['base'],run={'state':{'wealth_core':{'episodes':{}}}})
    natives=[deepcopy(record['native']) for record in actual['records']]
    rows=[dict(deepcopy(record['anchors']['before']['identity']),NONCANONICAL_SOURCE_QUERY_METADATA_DTO=True) for record in actual['records']]
    return future,dto,scope,spec,natives,rows

def test_entire_original_payload_and_validator_accept128_noncanonical_query_DTOs(actual):
    future,dto,scope,spec,natives,rows=payload_fixture(actual);before=deepcopy(dto)
    payload=future.witness_payload(dto,'P03',scope,natives,rows,[])
    assert dto==before and len(payload['terms'])==128 and payload['schema']=='research.own-parent-frozen-source-witnesses/1'
    assert payload['financial_authority'] is payload['input_adopted'] is False and payload['financial_sessions_advanced']==0
    assert all(t['source_row']['NONCANONICAL_SOURCE_QUERY_METADATA_DTO'] is True for t in payload['terms'])
    assert future.validate_witness_capture(payload,spec,scope)==payload
    false_roles=deepcopy(scope);false_roles['terms'][0]['parent_positions']=[dict(slot_id=0,ticker=scope['terms'][0]['ticker'],quantity=1,entry_date='2019-01-01')]
    with pytest.raises(ValueError,match='PARENT_POSITION_SCOPE'):future.witness_payload(dto,'P03',false_roles,natives,rows,[])

@pytest.mark.parametrize('change',['authority','adopted','native_price','ticker','roles','producer','missing_term','epoch'])
def test_whole_original_capture_validation_refuses_payload_changes(actual,change):
    future,dto,scope,spec,natives,rows=payload_fixture(actual);payload=future.witness_payload(dto,'P03',scope,natives,rows,[])
    if change=='authority':payload['financial_authority']=True
    elif change=='adopted':payload['input_adopted']=True
    elif change=='native_price':payload['terms'][0]['native_term']['cash_per_share']=100.
    elif change=='ticker':payload['terms'][0]['source_row']['ticker']='FOREIGN'
    elif change=='roles':payload['terms'][0]['parent_positions']=[dict(slot_id=0,ticker='FOREIGN',quantity=1,entry_date='2019-01-01')]
    elif change=='producer':payload['producer_sha256']='0'*64
    elif change=='missing_term':payload['terms'].pop()
    else:payload['archive_sha256']='0'*64
    with pytest.raises(ValueError):future.validate_witness_capture(payload,spec,scope)

def removed(module,class_name,name,label):
    tree=ast.parse(Path(module.__file__).read_bytes());nodes=tree.body
    if class_name:nodes=next(n for n in nodes if isinstance(n,ast.ClassDef) and n.name==class_name).body
    fn=next(n for n in nodes if isinstance(n,ast.FunctionDef) and n.name==name);fn.decorator_list=[]
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value==label for a in node.value.args):self.count+=1;return None
            return self.generic_visit(node)
    change=Remove();fn=ast.fix_missing_locations(change.visit(fn));assert change.count==1
    scope=dict(vars(module));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<one-removed-source-query-DATA-guard>','exec'),scope)
    return scope[name]

def test_meaningful_exact_root_guard_removal_accepts_foreign_root(actual):
    root=deepcopy(actual['spec']);root['outer_sha256']='0'*64
    with pytest.raises(ValueError):data.selected_scopes({},['P03'],enabled=True,root_lookup=lambda arm:root)
    fn=removed(data,None,'selected_scopes','FORWARD_SOURCE_EXACT_CURRENT_ROOT_AXIS_FULL_INPUT_COUNT_AND_AUTHORITY')
    assert 'P03' in fn({},['P03'],enabled=True,root_lookup=lambda arm:root)

def test_meaningful_authority_guard_removal_accepts_financial_claim():
    value=data.registry().model_copy(update={'financial_authority':True})
    with pytest.raises(ValueError):data.Registry.source_only(value)
    assert removed(data,'Registry','source_only','FORWARD_SOURCE_NO_INPUT_OR_FINANCIAL_AUTHORITY')(value) is value

@pytest.mark.parametrize('kind,label',[('clock','FORWARD_SOURCE_UNIQUE_FUTURE_NATIVE_IDENTITIES'),('roles','FORWARD_SOURCE_EXACT_CURRENT_POSITIONS_NOT_FUTURE_PREDICTIONS')])
def test_meaningful_clock_and_role_guard_removals(kind,label):
    query,=data.registry().queries;scope=query.scope;terms=list(scope.terms)
    if kind=='clock':terms[0]=terms[0].model_copy(update={'session':scope.parent_cursor})
    else:
        p=data.Position.model_construct(slot_id=0,ticker=terms[0].ticker,quantity=1,entry_date='2099-01-01')
        terms[0]=terms[0].model_copy(update={'parent_positions':[p]})
    value=scope.model_copy(update={'terms':terms})
    with pytest.raises(ValueError):data.Scope.exact_future_native_and_current_roles(value)
    assert removed(data,'Scope','exact_future_native_and_current_roles',label)(value) is value

def test_meaningful_whole_inventory_guard_removal_accepts_unpinned_bytes(actual):
    covered,_=prep.covered_inputs(actual['parent'],actual['member']);raw=actual['inventory']+b'\n'
    with pytest.raises(ValueError,match='WHOLE_ORIGINAL_INVENTORY'):prep.selection(actual['parent'],raw,covered)
    fn=removed(prep,None,'selection','WHOLE_ORIGINAL_INVENTORY_BEFORE_PARSE')
    terms,selected,all_records=fn(actual['parent'],raw,covered)
    assert len(terms)==128 and len(all_records)==1179

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
