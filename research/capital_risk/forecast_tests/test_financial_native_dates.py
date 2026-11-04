"""Bounded native discovery is DATA-only and never chooses economic authority."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
import system_campaign_financial_partial as p
from research.capital_risk.forecast_tests.test_financial_source_close import removed_guard


def fixture():
    scope=deepcopy(f.NATIVE_DATE_WITNESS_SCOPES['P11']);term,=scope['terms']
    root=p.root_spec('P11')
    cp=dict(sha256=root['outer_sha256'],source_cursor=root['selected_session'],base=deepcopy(root['base']),
            run=dict(state=dict(wealth_core=dict(episodes={}))))
    row=dict(session=term['session'],security_id=term['security_id'],ticker=term['ticker'],
             issuer_id='SOURCE:unchanged',listing_first_session='2010-01-04',security_type_eligible='0',raw_close='32.50')
    native=dict(session='2022-06-29',security_id=term['security_id'],kind='UNRESOLVED_TERMINAL',
                reference='Exact frozen input',cash_per_share=None,delivered_security_id=None,
                delivered_ticker=None,delivered_issuer_id=None,exchange_ratio=None,
                cash_in_lieu_price_per_delivered_share=None,entitlement_aggregation='HOLDER')
    return scope,cp,[row],native


@pytest.mark.parametrize('count,status',[(0,'NO_NATIVE_IN_WINDOW'),(1,'UNIQUE_NATIVE_CAPTURED'),(2,'MULTIPLE_NATIVES_IN_WINDOW')])
def test_every_match_status_is_explicit_and_never_financial_authority(count,status):
    scope,cp,rows,native=fixture();natives=[]
    for i in range(count):
        item=deepcopy(native);item['session']=f'2022-06-{29+i}';natives.append(item)
    before=deepcopy((scope,cp,rows,natives));payload=f.witness_payload(cp,'P11',scope,natives,rows)
    spec=dict(arm='P11',outer_sha256=cp['sha256'],selected_session=cp['source_cursor'],base=cp['base'])
    assert f.validate_witness_capture(payload,spec,scope)==payload
    assert payload['match_status']==status and len(payload['native_candidates'])==count
    assert payload['financial_authority']is payload['input_adopted']is payload['production_contacted']is False
    assert payload['financial_sessions_advanced']==0 and payload['terms'][0]['source_row']==rows[0]
    assert (scope,cp,rows,natives)==before


def test_actual_candidate_selection_covers_all_kinds_and_does_not_modify_source():
    scope,_,_,native=fixture();other=deepcopy(native);other.update(session='2022-07-01',kind='CASH_PLUS_STOCK')
    ignored=deepcopy(native);ignored['security_id']='OTHER'
    outside=deepcopy(native);outside['session']='2022-07-18'
    source={'2022-06-29':[native,ignored],'2022-07-01':[other],'2022-07-18':[outside]};before=deepcopy(source)
    assert f.native_date_candidates(source,scope)==[native,other] and source==before


@pytest.mark.parametrize('arm,days',[('P03',169),('P11',1111)])
def test_current_scopes_use_exact_own_admitted_roots_and_actual_empty_positions(arm,days):
    scope=f.WITNESS_SCOPES[arm];root=p.root_spec(arm)
    assert root['measured_closes']==days and root['outer_sha256']==scope['parent_outer_sha256']
    assert root['selected_session']==scope['parent_cursor'] and scope['terms'][0]['parent_positions']==[]
    assert f.source_schema(scope)==f.SOURCE_WITNESS_DATE_QUERY_SCHEMA
    assert scope==f.registered_scope(f.digest(scope))


def test_query_scope_guard_removal_accepts_an_undeclared_lookup():
    scope,_,_,_=fixture();scope['undeclared']='OTHER_SOURCE'
    with pytest.raises(ValueError,match='ONE_DECLARED_SECURITY'):f.native_date_query(scope)
    assert removed_guard('native_date_query','SOURCE_NATIVE_DATE_ONE_DECLARED_SECURITY')(scope)


def test_bounded_query_guard_removal_accepts_an_unbounded_search():
    scope,_,_,_=fixture();scope['native_date_query']['session_to']='2022-09-01'
    with pytest.raises(ValueError,match='EXACT_BOUNDED_QUERY'):f.native_date_query(scope)
    assert removed_guard('native_date_query','SOURCE_NATIVE_DATE_EXACT_BOUNDED_QUERY')(scope)


@pytest.mark.parametrize('change',['identity','position'])
def test_actual_source_role_guard_removal_accepts_wrong_identity_or_parent_role(change):
    scope,_,rows,_=fixture();positions=[]
    if change=='identity':rows[0]['ticker']='OTHER'
    else:positions=[dict(slot_id=1,ticker='TVTY',quantity=134,entry_date='2022-06-23')]
    with pytest.raises(ValueError,match='FULL_IDENTITY_AND_ACTUAL_ROLE'):f.native_date_material(scope,[],rows,positions)
    assert removed_guard('native_date_material','SOURCE_NATIVE_DATE_FULL_IDENTITY_AND_ACTUAL_ROLE')(scope,[],rows,positions)


@pytest.mark.parametrize('change',['outside','sid','overflow'])
def test_candidate_guard_removal_accepts_unbounded_or_undeclared_results(change):
    scope,_,rows,native=fixture();natives=[native]
    if change=='outside':native['session']='2022-07-18'
    elif change=='sid':native['security_id']='OTHER'
    else:
        natives=[dict(native,reference='Distinct source '+str(i)) for i in range(17)]
    with pytest.raises(ValueError,match='ALL_CANDIDATES_WITHOUT_TRUNCATION'):f.native_date_material(scope,natives,rows,[])
    result=removed_guard('native_date_material','SOURCE_NATIVE_DATE_ALL_CANDIDATES_WITHOUT_TRUNCATION')(scope,natives,rows,[])
    assert len(result['native_candidates'])==len(natives)


@pytest.mark.parametrize('change',['authority','root','row','candidate_hash','counter_type','flag_type'])
def test_reconstruction_guard_removal_accepts_changed_capture(change):
    scope,cp,rows,native=fixture();payload=f.witness_payload(cp,'P11',scope,[native],rows)
    spec=dict(arm='P11',outer_sha256=cp['sha256'],selected_session=cp['source_cursor'],base=cp['base'])
    if change=='authority':payload['financial_authority']=True
    elif change=='root':spec['outer_sha256']='0'*64
    elif change=='row':payload['terms'][0]['source_row']['raw_close']='32.51'
    elif change=='counter_type':payload['financial_sessions_advanced']=False
    elif change=='flag_type':payload['financial_authority']=0
    else:payload['native_candidates'][0]['native_term_sha256']='0'*64
    with pytest.raises(ValueError,match='EXACT_SOURCE_ONLY_RECONSTRUCTION'):f.validate_witness_capture(payload,spec,scope)
    assert removed_guard('validate_witness_capture','SOURCE_NATIVE_DATE_EXACT_SOURCE_ONLY_RECONSTRUCTION')(payload,spec,scope)
