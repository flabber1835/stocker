"""Isolated DATA/synthetic proposal tests; canonical financial imports forbidden."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
import subprocess

import pytest

HERE=Path(__file__).resolve().parents[1]
C=HERE
sys.path.insert(0,str(HERE))
BASE='d466fc599fb631fbb18fb86421115534e1ce1eda'
def original(filename):
    return subprocess.check_output(['git','show',BASE+':research/capital_risk/'+filename])
import system_campaign_financial_future as f

def catalog():return json.loads((HERE/f.OWN_CASH_CATALOG).read_bytes())
def term(ticker='WLH'):return deepcopy(next(v for v in catalog()['terms'] if v['ticker']==ticker))
def without_guard(name,label):
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==name)
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(a,ast.Constant) and a.value==label for a in n.value.args))
    for node in ast.walk(fn):
        for field in ('body','orelse'):
            body=getattr(node,field,None)
            if isinstance(body,list) and guard in body:body[body.index(guard)]=ast.Pass()
    ns=dict(vars(f))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<synthetic-removed-guard>','exec'),ns)
    return ns[name]

def test_actual_wlh_uses_new_own_catalog_and_exact_mixed_assumption():
    t=term();before=deepcopy(t);selected=f.research_mixed_term(t)
    codec,name,terms=f.own_cash_selection('P05','2020-01-31')
    assert name==f.OWN_CASH_CATALOG and len(codec.catalog['terms'])==17
    assert codec.catalog_sha=='c93bb3e00a7990b25fe146ced63407ce582e1da9511c1b94c8039e8e04b90f89' and terms==[selected]
    assert selected['added']['cash_per_share']==2.5 and selected['added']['exchange_ratio']==.8
    assert t==before and t['research_assumption']['published_cash_is_approximate'] is False
    assert t['preserved_factual_record']['held_representation_scope']=='CANONICAL_EXACT_INTEGRAL_ONLY'
    assert selected['delivered_identity_witness']['issuer_id']=='SEC_CIK:1562476'
    assert selected['delivered_identity_witness']['security_type_eligible']=='1'
    assert selected['native_session']=='2020-02-05' and selected['added']['session']=='2020-02-06'
    f.completion_session(selected,['2020-02-04','2020-02-05','2020-02-06','2020-02-07'])

def test_actual_known_native_query_binds_exact_resolved_scope():
    t=term();query=f.registered_scope(t['source_capture']['query_scope_sha256'])
    scope=f.registered_scope(t['source_capture']['scope_sha256'])
    assert 'native_preimage_query' not in query and len(query['additional_row_queries'])==1
    assert f.selected_query_scope(t,query)==scope
    assert f.qualify_selected_query_resolution(t,query,scope) is None

def test_original_fmsa_version_and_query_behavior_remain():
    t=term('FMSA');selected=f.research_mixed_term(t)
    codec,_,terms=f.own_cash_selection('P03','2018-04-30')
    assert terms==[selected] and len(codec.catalog['terms'])==14
    assert selected['research_assumption']['published_cash_is_approximate'] is True
    assert selected['added']['cash_per_share']==.73 and selected['added']['exchange_ratio']==.2
    query=f.registered_scope(t['source_capture']['query_scope_sha256'])
    assert 'native_preimage_query' in query
    f.qualify_selected_query_resolution(t,query,f.registered_scope(t['source_capture']['scope_sha256']))

@pytest.mark.parametrize('ticker,change',[('FMSA',False),('FMSA',1),('WLH',True),('WLH',0),('WLH',1)])
def test_precision_flags_are_version_specific_and_strict(ticker,change):
    t=term(ticker);t['research_assumption']['published_cash_is_approximate']=change
    with pytest.raises(ValueError):f.research_mixed_term(t)

@pytest.mark.parametrize('change',['cash','ratio','precision','settlement','opening','date','identity','proxy','aggregation','cil','extra','schema'])
def test_new_exact_cash_mode_retains_mixed_guards(change):
    t=term()
    if change=='cash':t['added']['cash_per_share']=2.51
    elif change=='ratio':t['added']['exchange_ratio']='0.81'
    elif change=='precision':t['added']['exchange_ratio']='0.80000000000000000001'
    elif change=='settlement':t['research_assumption']['actual_settlement_claimed']=True
    elif change=='opening':t['research_assumption']['opening_availability_assumed']=False
    elif change=='date':t['added']['session']='2020-02-07'
    elif change=='identity':t['added']['delivered_security_id']='OTHER'
    elif change=='proxy':t['proxy']['source_observation_sha256']='0'*64
    elif change=='aggregation':t['added']['entitlement_aggregation']='LOT'
    elif change=='cil':t['added']['cash_in_lieu_price_per_delivered_share']=27.55
    elif change=='schema':t['research_assumption']['schema']='research.daily-mixed-consideration-assumption/3'
    else:t['research_assumption']['broker_authority']=True
    with pytest.raises(ValueError):f.research_mixed_term(t)

def test_new_exact_mode_amount_guard_removal_falsifier():
    t=term();t['added']['cash_per_share']=2.51
    with pytest.raises(ValueError):f.research_mixed_term(t)
    assert without_guard('research_mixed_term','OWN_INPUT_EXPLICIT_RESEARCH_MIXED_AMOUNT_RATIO_IDENTITY_AND_TIMING')(t)['added']['cash_per_share']==2.51

def test_exact_cash_boolean_guard_removal_falsifier():
    t=term();t['research_assumption']['published_cash_is_approximate']=0
    with pytest.raises(ValueError):f.research_mixed_term(t)
    assert without_guard('research_mixed_term','OWN_INPUT_EXPLICIT_RESEARCH_MIXED_AMOUNT_RATIO_IDENTITY_AND_TIMING')(t)['research_assumption']['published_cash_is_approximate']==0

@pytest.mark.parametrize('change',['native','parent','cursor','ticker','identity_day','native_day','native_sid','consumed','positions'])
def test_known_native_query_is_bound_before_row_resolution(change):
    t=term();q=f.registered_scope(t['source_capture']['query_scope_sha256']);s=f.registered_scope(t['source_capture']['scope_sha256'])
    if change=='native':t['native']['reference']='substituted'
    elif change=='parent':t['parent_outer_sha256']='0'*64
    elif change=='cursor':t['parent_cursor']='2020-01-30'
    elif change=='ticker':q['terms'][0]['ticker']='OTHER'
    elif change=='identity_day':t['identity_witness']['session']='2020-02-03'
    elif change=='native_day':t['native']['session']='2020-02-06'
    elif change=='native_sid':t['native']['security_id']='OTHER'
    elif change=='consumed':t['parent_cursor']=q['parent_cursor']='2020-02-05'
    else:t['parent_positions']=[{'quantity':1}]
    with pytest.raises(ValueError):f.qualify_selected_query_resolution(t,q,s)

def test_known_native_guard_removal_admits_substituted_body():
    t=term();q=f.registered_scope(t['source_capture']['query_scope_sha256']);s=f.registered_scope(t['source_capture']['scope_sha256'])
    t['native']['reference']='substituted'
    with pytest.raises(ValueError):f.qualify_selected_query_resolution(t,q,s)
    assert without_guard('qualify_selected_query_resolution','OWN_INPUT_KNOWN_NATIVE_EXACT_PREIMAGE_PARENT_AND_UNCONSUMED_SCOPE')(t,q,s) is None

def test_known_scope_shape_guard_removal_admits_extra_authority_field():
    t=term();q=f.registered_scope(t['source_capture']['query_scope_sha256']);s=f.registered_scope(t['source_capture']['scope_sha256'])
    q['financial_use_authorized']=s['financial_use_authorized']=True
    with pytest.raises(ValueError):f.qualify_selected_query_resolution(t,q,s)
    assert without_guard('qualify_selected_query_resolution','OWN_INPUT_KNOWN_NATIVE_SINGLE_DELIVERY_QUERY_SCOPE')(t,q,s) is None

def test_final_resolution_guard_removal_admits_changed_resolved_digest():
    t=term();q=f.registered_scope(t['source_capture']['query_scope_sha256']);s=f.registered_scope(t['source_capture']['scope_sha256'])
    s['additional_rows'][0]['source_observation_sha256']='0'*64
    with pytest.raises(ValueError):f.qualify_selected_query_resolution(t,q,s)
    assert without_guard('qualify_selected_query_resolution','OWN_CASH_EXACT_QUERY_RESOLUTION_NATIVE_PREIMAGE')(t,q,s) is None

def test_known_native_path_retains_delivery_identity_and_count_guards():
    t=term();q=f.registered_scope(t['source_capture']['query_scope_sha256']);s=f.registered_scope(t['source_capture']['scope_sha256'])
    q['additional_row_queries'][0]['ticker']='OTHER'
    with pytest.raises(ValueError):f.qualify_selected_query_resolution(t,q,s)
    q=f.registered_scope(t['source_capture']['query_scope_sha256']);q['additional_row_queries'].append(deepcopy(q['additional_row_queries'][0]))
    with pytest.raises(ValueError):f.qualify_selected_query_resolution(t,q,s)

def test_all_sixteen_prior_records_and_original_legal_policy_are_unchanged():
    before=json.loads(original(f.OWN_CASH_CATALOG));after=catalog()
    assert after['terms'][:16]==before['terms'] and len(after['terms'])==23
    after['terms']=after['terms'][:16]
    assert f.sha((json.dumps(after,sort_keys=True,indent=2,allow_nan=False)+'\n').encode())=='465c8a78287c5cb7864aa400e13290f07f278c31e2a34897018cf5403551070c'
    provenance=term()['preserved_factual_record'];raw=(C/provenance['filename']).read_bytes()
    legal,=[v for v in json.loads(raw)['records'] if v['action_id']=='WLH-2020-02-06']
    assert f.sha(raw)==provenance['sha256'] and f.digest(legal)==provenance['record_sha256']
    assert legal['fraction_policy']=='NO_COMMON_CIL_PRICE_PROVED_REFUSE_UNSUPPORTED_NONINTEGRAL'

def test_original_model_and_unrelated_validator_asts_unchanged():
    def nodes(raw):
        result={}
        for n in ast.parse(raw).body:
            if not isinstance(n,(ast.FunctionDef,ast.ClassDef)):continue
            while n.name=='selected_stock_term' and isinstance(n.body[1],ast.If) and any(mode in ast.unparse(n.body[1].test)for mode in ('PREOPEN_STOCK','PRIOR_STOCK')):
                del n.body[1]
            result[n.name]=ast.dump(n,include_attributes=False)
        return result
    old=nodes(original('system_campaign_financial_future.py'));new=nodes(Path(f.__file__).read_bytes())
    for name in ('ResearchMixedAssumption','source_terms','resolved_query_scope','selected_query_scope',
        'selected_stock_term','research_cash_term','research_tender_term','research_source_exit_term','source_cash_term','completion_cash_term'):
        assert old[name]==new[name],name
    before=next(n for n in ast.parse(original('system_campaign_financial_future.py')).body if isinstance(n,ast.FunctionDef)and n.name=='completion_session')
    after=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef)and n.name=='completion_session')
    for mode in ('PRIOR_STOCK','PREOPEN_STOCK'):
        assert isinstance(after.body[0],ast.If) and mode in ast.unparse(after.body[0].test)
        del after.body[0]
    # Only the final NEXT_COMPLETION predicate now permits a nontrading
    # completion date; all earlier recognition branches remain exact.
    assert ast.dump(ast.Module(body=before.body[:-1],type_ignores=[]),include_attributes=False)==ast.dump(ast.Module(body=after.body[:-2],type_ignores=[]),include_attributes=False)
