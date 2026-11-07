import ast,gzip,json,sys,os
from copy import deepcopy
from pathlib import Path
import pytest
D=Path('C:/GitHub/stocker/.codex-tmp/p05-ctxs-own1175-20261106');C=Path(__file__).parents[2];sys.path[:0]=[str(C)]
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('ORIGIN18_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
import system_campaign_p05_remaining_origin_data as origin
import system_campaign_retained_forward_cash as prior
@pytest.fixture(scope='module')
def actual():
    r=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial326-source-snapshot/capture-P05-13479382405-001')
    manifest=json.loads((r/'authenticated-manifest.json').read_bytes())['members'];root=r/'verified-output'
    if os.name=='nt' and not str(root).startswith('\\\\?\\'):root=Path('\\\\?\\'+str(root.resolve()))
    raw=(root/'book/checkpoint.json.gz').read_bytes()
    assert dict(bytes=len(raw),sha256=origin.sha(raw))==manifest['book/checkpoint.json.gz']
    cp=json.loads(gzip.decompress(raw));origin.data.own.parent_contract(cp)
    def member(n):
        value=(root/n).read_bytes()
        assert dict(bytes=len(value),sha256=origin.sha(value))==manifest[n]
        return value
    assert all((root/n).is_file() for n in manifest),'complete authenticated capture required; no missing-name fallback'
    return cp,manifest,member
def test_entire_original_bodies_restore_after_single_AST_branch_undo():
    a=origin.inventory_tree(Path(origin.old_materials.__file__).read_bytes())
    b=origin.batch_inventory_tree(Path(origin.old_batch.__file__).read_bytes())
    assert isinstance(a,ast.FunctionDef) and isinstance(b,ast.FunctionDef)
def test_full_actual19_inventory_matches_whole_old_inventory_exactly(actual):
    cp,names,member=actual;plan,=prior.plans()
    old=origin.old_batch.inventory(cp,plan,names,member)
    adapted=origin.inventory_function()(cp,plan,names,member)
    assert adapted==old and adapted['full_input_count']==19 and len(adapted['entries'])==5 and len(adapted['terms'])==68
def test_changed_actual_full_input_hash_is_still_refused_before_resource_reads(actual):
    cp,names,member=actual;cp=deepcopy(cp);cp['run']['input_sha256']='0'*64;reads=[]
    with pytest.raises(ValueError,match='FULL_CANONICAL_INPUT_HASH'):
        origin.inventory_function()(cp,prior.plans()[0],names,lambda n:reads.append(n))
    assert reads==[]
def test_original_full_input_guard_retained_and_meaningful(actual):
    cp,names,member=actual;changed=deepcopy(cp);changed['run']['input_sha256']='0'*64
    fn=origin.inventory_function()
    with pytest.raises(ValueError):fn(changed,prior.plans()[0],names,member)
    material_fn=fn.__globals__['ORIGINAL_INVENTORY'];need=material_fn.__globals__['need']
    material_fn.__globals__['need']=lambda v,label:None if label=='RETAINED_CASH_V2_FULL_CANONICAL_INPUT_HASH' else need(v,label)
    assert fn(changed,prior.plans()[0],names,member)['full_input_count']==19
def test_independent_material_reconstructs_every_term_and_original_delivery_CIL(actual):
    parent,_,_=actual;m=origin.material(parent)
    assert len(m['terms'])==18 and m['native_and_delivery_witnesses_verified']==21 and not m['consumed_native_preserved']
    by={t['ticker']:t for t in m['terms']}
    assert by['DRE']['added']['exchange_ratio']==.475 and by['DRE']['added']['cash_in_lieu_price_per_delivered_share']==103.5
    assert by['LSI']['added']['cash_in_lieu_price_per_delivered_share']==149.18000000000001
    assert by['MTTR']['added']['cash_in_lieu_price_per_delivered_share']==75.629999999999995
    assert by['CTXS']['added']['cash_per_share']==104. and by['CTXS']['portfolio_completion_authorized'] is False
def test_whole_original_overlay_and_source_scope_are_reconstructed_from_closed_DATA(actual):
    parent,_,_=actual;m=origin.material(parent);api=origin.api_module.api(parent);raw=origin.encoded(m)
    doc=api.document(parent,m,origin.sha(raw));scope=api.source_scopes(parent,m,origin.sha(origin.encoded(doc)),origin.sha(raw))
    assert len(doc['add'])==len(doc['suppress'])==18 and len(doc['source_evidence'])<=128
    assert len(scope)==1 and scope[0]['security_id']==origin.data.own.SID and scope[0]['portfolio_completion_authorized'] is False
def test_only_the_fourteen_exact_new_cash_terms_bypass_old_ACC_branch():
    terms=origin.data.terms();cash=[t for t in terms if origin.remaining_cash_from(t,terms)]
    assert len(cash)==14 and all(t['added']['kind']=='CASH_MERGER' for t in cash)
    assert not origin.remaining_cash(next(t for t in terms if t['ticker']=='CTXS'))
    assert not origin.remaining_cash(next(t for t in terms if t['ticker']=='DRE'))
def test_changed_cash_literal_guard_has_meaningful_removal_falsifier(monkeypatch):
    t=deepcopy(next(t for t in origin.data.terms() if t['ticker']=='CYBE'));t['added']['cash_per_share']=1.
    with pytest.raises(ValueError):origin.remaining_cash(t)
    old=origin.need;monkeypatch.setattr(origin,'need',lambda v,label:None if label=='P05_ORIGIN18_ONLY_FOURTEEN_BYTE_EXACT_RETAINED_NEXT_CASH_TERMS' else old(v,label))
    assert origin.remaining_cash(t)
@pytest.mark.parametrize('key,value',[('packet_checks',35),('financial_sessions_advanced',1),('financial_sessions_advanced',False),('passed',False),('wrong_native_and_delivery_witness_refused',False)])
def test_incomplete_original_packet_qualification_refuses(key,value):
    q=dict(passed=True,packet_checks=36,only_terminal_field_changed=True,complete_terms_and_canonical_notional_verified=True,
        original_incomplete_guard_retained=True,wrong_predecessor_and_consumed_date_refused=True,wrong_native_and_delivery_witness_refused=True,financial_sessions_advanced=0)
    origin.qualification(q);q[key]=value
    with pytest.raises(ValueError):origin.qualification(q)
def test_current19_cannot_claim_new20_descriptor_or_origin(actual):
    cp,names,member=actual
    with pytest.raises(ValueError,match='TWENTIETH_DESCRIPTOR'):origin.composite(cp,cp['repairs'][-1],names,member)
def test_origin_resource_set_excludes_no_required_new_resource():
    assert len(origin.required_resources())==10
    assert origin.PARENT in origin.required_resources() and origin.NEUTRAL in origin.required_resources()
    assert origin.api_module.original.SOURCE_SCOPES in origin.required_resources()
@pytest.mark.parametrize('prefix',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_all_financial_import_fences(prefix):
    with pytest.raises(ImportError):Fence().find_spec(prefix)
