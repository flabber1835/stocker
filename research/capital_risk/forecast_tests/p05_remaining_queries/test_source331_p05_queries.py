"""Whole source2 constructor and strict metadata only; no canonical runtime."""
import ast,gzip,json,sys
from pathlib import Path
from copy import deepcopy
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('SOURCE331_QUERY_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
P=Path(__file__).parent;C=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(P),str(C)]
import system_campaign_p05_remaining_source_queries as data
import system_campaign_explicit_source_queries as original_scope
import system_campaign_forward_source_queries as original_registry
import system_campaign_financial_future as future
from system_campaign_financial_partial import root_spec
R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8')
def read(p):return (Path(p) if str(p).startswith('\\\\?\\') else Path('\\\\?\\'+str(Path(p).resolve()))).read_bytes()

@pytest.fixture(scope='module')
def actual():
    spec=root_spec('P05');assert spec['root_admission_sha256']=='baabf01e4e070faea5c03fb0055fa715ac075a0175d5bdcc24b356a922cb1026'
    cap=R/'financial326-source-snapshot/capture-P05-13479382405-001';pins=json.loads(read(cap/'authenticated-manifest.json'))['members']
    raw=read(cap/'verified-output/book/checkpoint.json.gz');assert dict(bytes=len(raw),sha256=data.sha(raw))==pins['book/checkpoint.json.gz']
    cp=json.loads(gzip.decompress(raw));assert cp['sha256']==spec['outer_sha256']
    source=R/'source322-source-snapshot/capture-P05-13474058928-001';pins=json.loads(read(source/'authenticated-manifest.json'))['members']
    raw=read(source/'verified-output/source-witnesses.json');assert dict(bytes=len(raw),sha256=data.sha(raw))==pins['source-witnesses.json']
    payload=json.loads(raw);terms={v['native_term']['security_id']:v for v in payload['terms']}
    query,=data.registry().queries;scope=query.scope.model_dump()
    dto=dict(NONCANONICAL_SOURCE_ROLE_DTO=True,sha256=cp['sha256'],source_cursor=cp['source_cursor'],
        base={k:cp['base'][k] for k in ('archive_sha256','bundle_sha256')},
        run=dict(state=dict(wealth_core=dict(episodes=deepcopy(cp['run']['state']['wealth_core']['episodes'])))))
    native=[terms[t['security_id']]['native_term'] for t in scope['terms']]
    rows=[terms[t['security_id']]['source_row'] for t in scope['terms']]
    extra=json.loads((P/'SOURCE331-preparation-DATA.json').read_bytes())['additional_CTXS_raw_discovery']
    return spec,dto,scope,native,rows,extra

def test_original_unheld_validator_and_whole_registry_reader_are_retained():
    assert data.Scope.exact_bounded_future_identities is original_scope.Scope.exact_bounded_future_identities
    assert data.Scope.model_fields['additional_rows'].metadata==original_scope.Scope.model_fields['additional_rows'].metadata
    before=ast.parse(Path(original_registry.__file__).read_bytes());after=ast.parse(Path(data.__file__).read_bytes())
    for name in ('registry','selected_scopes','source_names'):
        a=next(n for n in before.body if isinstance(n,ast.FunctionDef) and n.name==name)
        b=next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name==name)
        assert ast.dump(a)==ast.dump(b)

def test_actual_current_root_full19_remaining36_and_one_additional_raw_row(actual):
    spec,dto,scope,native,rows,extra=actual
    result=data.selected_scopes({},['P05'],enabled=True,root_lookup=lambda arm:spec)
    assert result=={'P05':scope} and len(scope['terms'])==36 and len(scope['additional_rows'])==1
    assert scope['terms'][0]['ticker']=='CTXS' and scope['terms'][-1]['ticker']=='ORLA'
    assert all(v['parent_positions']==[] for v in scope['terms'])
    assert future.digest(extra)==scope['additional_rows'][0]['source_observation_sha256'] and extra['tradeable']=='1'

def test_complete_original_source2_constructor_and_reconstruction(actual):
    spec,dto,scope,native,rows,extra=actual
    result=future.witness_payload(dto,'P05',scope,native,rows,[extra])
    assert result['schema']==future.SOURCE_WITNESS_PENDING_SCHEMA and len(result['terms'])==36
    assert result['additional_rows'][0]['source_row']==extra
    assert result['financial_sessions_advanced']==0 and result['financial_authority'] is result['input_adopted'] is False
    future.validate_witness_capture(result,spec,scope)

@pytest.mark.parametrize('change',['authority','adopted','money','too_many','duplicate','past','roles','extra_roles','foreign_extra','extra_hash','bool_count'])
def test_reject_authority_money_stale_scope_or_foreign_roles(change):
    v=data.registry().model_dump(by_alias=True);q=v['queries'][0];s=q['scope'];t=s['terms'][0]
    if change=='authority':v['financial_authority']=True
    elif change=='adopted':v['input_adopted']=True
    elif change=='money':t['cash_per_share']=104.
    elif change=='too_many':s['terms']=[deepcopy(t) for _ in range(129)]
    elif change=='duplicate':s['terms'][1]=deepcopy(t)
    elif change=='past':t['session']=s['parent_cursor']
    elif change=='roles':t['parent_positions']=[dict(slot_id=0,ticker='CTXS',quantity=1,entry_date='2022-01-01')]
    elif change=='extra_roles':s['additional_rows'][0]['parent_positions']=[{}]
    elif change=='foreign_extra':s['additional_rows'][0]['security_id']='1'
    elif change=='extra_hash':s['additional_rows'][0]['source_observation_sha256']='bad'
    else:q['parent_completed']=True
    with pytest.raises(ValueError):data.Registry.model_validate(v)

@pytest.mark.parametrize('change',['native','source','roles','additional','money','authority','missing'])
def test_whole_source2_reader_rejects_corrupted_data(actual,change):
    spec,dto,scope,native,rows,extra=deepcopy(actual)
    if change=='native':native[0]['cash_per_share']=104.
    elif change=='source':rows[0]['ticker']='FOREIGN'
    elif change=='roles':dto['run']['state']['wealth_core']['episodes']['99']=dict(slot_id=99,ticker='CTXS',security_id=scope['terms'][0]['security_id'],current_shares=1,entry_date='2022-01-01')
    elif change=='additional':extra['raw_close']='1'
    elif change=='missing':rows.pop()
    if change in ('money','authority'):
        result=future.witness_payload(dto,'P05',scope,native,rows,[extra])
        if change=='money':result['terms'][0]['native_term']['cash_per_share']=104.
        else:result['financial_authority']=True
        with pytest.raises(ValueError):future.validate_witness_capture(result,spec,scope)
    else:
        with pytest.raises(ValueError):future.witness_payload(dto,'P05',scope,native,rows,[extra])

def removed(name,label):
    tree=ast.parse(Path(data.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    hits=[n for n in fn.body if isinstance(n,ast.For)]
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(x,ast.Constant) and x.value==label for x in node.value.args):self.count+=1;return None
            return self.generic_visit(node)
    mutation=Remove();fn=ast.fix_missing_locations(mutation.visit(fn));assert mutation.count==1
    ns=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-source-only-root-guard>','exec'),ns);return ns[name]

def test_exact_current_root_guard_removal_really_accepts_foreign_authority(actual):
    spec=deepcopy(actual[0]);spec['outer_sha256']='0'*64
    with pytest.raises(ValueError):data.selected_scopes({},['P05'],enabled=True,root_lookup=lambda arm:spec)
    broken=removed('selected_scopes','FORWARD_SOURCE_EXACT_CURRENT_ROOT_AXIS_FULL_INPUT_COUNT_AND_AUTHORITY')
    assert 'P05' in broken({},['P05'],enabled=True,root_lookup=lambda arm:spec)

@pytest.mark.parametrize('name',['research.pooled_bad','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
    with pytest.raises(ImportError):__import__(name)
