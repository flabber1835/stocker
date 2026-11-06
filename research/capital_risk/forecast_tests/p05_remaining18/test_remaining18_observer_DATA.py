import ast,gzip,json,os,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
D=Path('C:/GitHub/stocker/.codex-tmp/p05-ctxs-own1175-20261106');C=Path(__file__).parents[2];sys.path[:0]=[str(C)]
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('OBSERVER18_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
import system_campaign_p05_remaining_observer_data as review
import system_campaign_retained_cash_v2 as union
from system_campaign_uncertainty_review import committed_rows
from forecast_tests.p05_remaining18.test_remaining18_origin_inventory_DATA import actual as prior_actual
@pytest.fixture(scope='module')
def actual():
    cp,names,member=prior_actual.__wrapped__()
    root=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial326-source-snapshot/capture-P05-13479382405-001/verified-output')
    if os.name=='nt' and not str(root).startswith('\\\\?\\'):root=Path('\\\\?\\'+str(root.resolve()))
    plan,=review.cash.plans();_,_,old=review.cash.checked_resources(root,cp,plan)
    inventory=review.origin.old_batch.inventory(cp,plan,names,member)
    terms=union.union_terms(old,inventory['terms'],review.origin.material(cp)['terms'])
    old_terms=union.union_terms(old,inventory['terms'])
    observed={day:json.loads(raw) for day,raw in review.cash.committed_logs(root,cp,plan).items()}
    rows=committed_rows(root/'book',cp,'daily')
    material=review.origin.material(cp);api=review.origin.api_module.api(cp)
    doc=api.document(cp,material,review.sha(review.origin.encoded(material)))
    scopes=api.source_scopes(cp,material,review.sha(review.origin.encoded(doc)),review.sha(review.origin.encoded(material)))
    return cp,rows,observed,terms,scopes,old_terms
def test_complete_real19_predecessor_review_preserves_all94_old_terms_and112_total(actual):
    cp,rows,observed,terms,scopes,old_terms=actual
    result=review.review_data(cp,rows,observed,terms,scopes)
    old=review.cash.verify_records(rows,cp['run']['state']['ledger']['events'],observed,old_terms,cp['source_cursor'])
    assert len(old_terms)==94 and len(terms)==112 and result['ordinary_cash_terms']==108
    assert result['original_cash_events']==old and len(old)==9 and result['original_stock_events']==result['source_only_events']==[]
def test_source_projection_leaves_all_genuine_predecessor_records_byte_equivalent(actual):
    cp,rows,observed,terms,scopes,_=actual
    before=review.origin.encoded(observed)
    ordinary,projected,checked=review.source_projection(rows,cp['run']['state']['ledger']['events'],observed,terms,scopes,cp['source_cursor'])
    assert len(ordinary)==111 and not checked and review.origin.encoded(projected)==before and review.origin.encoded(observed)==before
@pytest.mark.parametrize('change',['missing_cash','duplicate_cash','unexpected_source','wrong_order','engine','risk'])
def test_any_changed_real_daily_call_set_refuses_before_projection(actual,change):
    cp,rows,observed,terms,scopes,_=actual;bad=deepcopy(observed);day=next(iter(bad));record=bad[day]
    if change=='missing_cash':record['cash'].pop()
    elif change=='duplicate_cash':record['cash'].append(deepcopy(record['cash'][0]))
    elif change=='unexpected_source':record['source']=[dict(security_id=review.origin.data.own.SID)]
    elif change=='wrong_order':record['order']=[]
    elif change=='engine':record['engine_calls']=1
    else:record['risk']=[['unexpected','unexpected']]
    with pytest.raises(ValueError):review.source_projection(rows,cp['run']['state']['ledger']['events'],bad,terms,scopes,cp['source_cursor'])
def test_missing_real_event_date_refuses(actual):
    cp,rows,observed,terms,scopes,_=actual;bad=deepcopy(observed);bad.pop(next(iter(bad)))
    with pytest.raises(ValueError):review.source_projection(rows,cp['run']['state']['ledger']['events'],bad,terms,scopes,cp['source_cursor'])
def test_whole_merge_AST_has_one_targeted_predicate_undo():
    assert isinstance(review.merge_tree(Path(review.cash.__file__).read_bytes()),ast.FunctionDef)
def test_single_observation_DTO_merges_old_cash_with_new18_without_engine(actual):
    _,_,_,terms,scopes,old=actual
    new=[t for t in terms if t not in old]
    event=SimpleNamespace(terms={(t['added']['session'],t['security_id']):deepcopy(t['added']) for t in new},scopes=deepcopy(scopes))
    merge=review.merge_function(lambda e:review.exact_scope(e,scopes))
    merge(event,old)
    assert len(event.terms)==112 and event.scopes==scopes
@pytest.mark.parametrize('change',['missing','portfolio','digest','phase','extra'])
def test_scope_omission_or_authority_change_refuses(actual,change):
    _,_,_,terms,scopes,_=actual
    event=SimpleNamespace(terms={(t['added']['session'],t['security_id']):deepcopy(t['added']) for t in terms},scopes=deepcopy(scopes))
    if change=='missing':event.scopes=[]
    elif change=='portfolio':event.scopes[0]['portfolio_completion_authorized']=True
    elif change=='digest':event.scopes[0]['terminal_sha256']='0'*64
    elif change=='phase':event.scopes[0]['source_valuation_phase']='OPEN'
    else:event.scopes.append(deepcopy(event.scopes[0]))
    with pytest.raises(ValueError):review.exact_scope(event,scopes)
def test_new_scope_guard_removal_is_meaningful(actual,monkeypatch):
    _,_,_,terms,scopes,_=actual
    event=SimpleNamespace(terms={(t['added']['session'],t['security_id']):deepcopy(t['added']) for t in terms},scopes=[])
    with pytest.raises(ValueError):review.exact_scope(event,scopes)
    original=review.need;monkeypatch.setattr(review,'need',lambda v,label:None if label=='P05_OBSERVER18_ONLY_COMPLETE_VALIDATED_CTXS_SCOPE_AND_EXACT_TERMINAL' else original(v,label))
    assert review.exact_scope(event,scopes)
@pytest.mark.parametrize('prefix',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_all_financial_import_fences(prefix):
    with pytest.raises(ImportError):Fence().find_spec(prefix)
