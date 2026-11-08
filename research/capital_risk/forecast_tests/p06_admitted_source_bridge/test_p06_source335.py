"""Root metadata/whole context tests only; canonical operations are forbidden."""
import ast,importlib,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('SOURCE335_TEST_METADATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
C=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(Path(__file__).parent),str(C),str(C.parents[1])]
import system_campaign_p06_admitted_source_bridge as bridge
import system_campaign_p06_forward_source_queries as query
import system_campaign_p03_forward_source_queries as old
from system_campaign_financial_partial import root_spec
def request(spec):
    return dict(explicitly_noncanonical_request_metadata_DTO=True,execution_mode=bridge.MODE,readonly_source_witnesses=True,
        financial_resume_authorized=False,readonly_partial_review=False,maximum_parallel_financial_workers=0,
        **{bridge.FIELD:{'P06':bridge.declaration(spec)}})
def test_actual_admitted1383_metadata_and_bound_entire_context_code():
    spec=root_spec('P06');decl=bridge.declaration(spec)
    assert (decl['completed'],decl['full_inputs'])==(1383,10) and not decl['financial_authority']
    result=bridge.bound_context();assert result.__wrapped__.__code__ is bridge.original.entry_context.__wrapped__.__code__
    assert bridge.request_declaration(spec,request(spec))==decl
    assert bridge.selected_request(spec,request(spec))
@pytest.mark.parametrize('change',['financial','reporting','source','mode','workers','missing','foreign'])
def test_source_bridge_never_authorizes_an_economic_or_undeclared_context(change):
    spec=root_spec('P06');value=request(spec)
    if change=='financial':value['financial_resume_authorized']=True
    elif change=='reporting':value['readonly_partial_review']=True
    elif change=='source':value['readonly_source_witnesses']=False
    elif change=='mode':value['execution_mode']='OWN_ADMITTED_FINANCIAL_CONTINUATION'
    elif change=='workers':value['maximum_parallel_financial_workers']=1
    elif change=='missing':value[bridge.FIELD]={}
    else:value[bridge.FIELD]['P06']['root_admission_sha256']='0'*64
    with pytest.raises(ValueError):bridge.request_declaration(spec,value)
def test_financial_request_guard_removal_has_a_meaningful_falsifier():
    spec=root_spec('P06');value=request(spec);value['financial_resume_authorized']=True
    with pytest.raises(ValueError):bridge.request_declaration(spec,value)
    fn=next(n for n in ast.parse(Path(bridge.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='request_declaration')
    guards=[n for n in fn.body if isinstance(n,ast.Expr) and 'P06_SOURCE_ONLY_EXPLICIT_ZERO_FINANCIAL_SOURCE_REQUEST' in ast.unparse(n)]
    assert len(guards)==1;fn.body.remove(guards[0]);scope=dict(vars(bridge))
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-new-source-only-gate>','exec'),scope)
    assert scope['request_declaration'](spec,value)['source_only']
def test_exact_whole_original_query_module_AST_undo():
    before=Path(old.__file__).read_text();after=Path(query.__file__).read_text()
    for a,b in [(query.CATALOG,old.CATALOG),(query.CATALOG_SHA,old.CATALOG_SHA),("arm:Literal['P06']","arm:Literal['P03']")]:
        assert after.count(a)==1;after=after.replace(a,b,1)
    assert ast.dump(ast.parse(before))==ast.dump(ast.parse(after))
def test_actual128_future_scope_includes_BBIG_without_claiming_cash_or_future_ownership():
    q,=query.registry().queries;spec=root_spec('P06')
    assert (q.parent_completed,q.parent_input_count)==(1383,10) and len(q.scope.terms)==128
    bbig,=[t for t in q.scope.terms if t.ticker=='BBIG']
    assert (bbig.session,bbig.native_session,bbig.parent_positions)==('2023-07-26','2023-07-27',[])
    selected=query.selected_scopes({},['P06'],enabled=True,root_lookup=lambda _:spec)
    assert selected['P06']==q.scope.model_dump() and q.scope.additional_rows==[]
    assert not query.registry().financial_authority and not query.registry().input_adopted
def test_context_restores_original_retention_hooks_on_abort(monkeypatch):
    import full_system_core as host
    import system_campaign_financial_partial as partial
    monkeypatch.setattr(host,'hosted',lambda:None)
    spec=root_spec('P06');before=(partial.retained_models,partial.model_context)
    with pytest.raises(RuntimeError,match='explicit test abort'):
        with bridge.entry_context(spec,old=Path('/explicit-noncanonical-test-input-path'),out=Path('/explicit-noncanonical-test-output-path'),request=request(spec)):
            assert partial.retained_models is not before[0] and partial.model_context is not before[1]
            raise RuntimeError('explicit test abort')
    assert (partial.retained_models,partial.model_context)==before
def test_context_rejects_wrong_root_before_hooks():
    import system_campaign_financial_partial as partial
    spec=root_spec('P06');value=request(spec);spec=deepcopy(spec);spec['root_admission_sha256']='0'*64
    before=(partial.retained_models,partial.model_context)
    with pytest.raises(ValueError):
        with bridge.entry_context(spec,old=Path('/metadata-only'),out=Path('/metadata-only'),request=value):pass
    assert (partial.retained_models,partial.model_context)==before
@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name,monkeypatch):
    monkeypatch.setattr(sys,'meta_path',[Fence(),*sys.meta_path])
    with pytest.raises(ImportError,match='SOURCE335_TEST_METADATA_ONLY'):
        importlib.import_module(name+'.explicitly_forbidden_probe')
