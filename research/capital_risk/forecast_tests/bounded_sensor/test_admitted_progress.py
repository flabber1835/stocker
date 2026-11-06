"""Exact historical input scopes and newly admitted P05 prefix, DATA only."""
from system_campaign_financial_partial import root_spec,validate_root_spec
import system_campaign_explicit_source_queries as queries

def test_current_p05_july_root_has_full16_inputs_and_independent_eight_cash_proof():
    spec=root_spec('P05');validate_root_spec(spec)
    old=root_spec('P05','fbc6821ce4ae8beb5e24805d8f2b10a2b5f0941b6f9c15e21c1ae7b3ce121add')
    assert (spec['measured_closes'],spec['selected_session'])==(1152,'2022-07-29')
    assert len(spec['repairs'])==16 and spec['repairs'][:-1]==old['repairs']
    a=spec['root_admission'];p=a['source_input_proof']
    assert a['parent_root_admission_sha256']==old['root_admission_sha256']
    assert (a['new_daily_records'],a['independent_accounting_snapshots'],a['new_monthly_reports'])==(20,40,1)
    assert p['passed'] and p['total_observer_terms']==28 and len(p['actual_cash_events'])==8
    assert p['August_tails_and_failed_canonical_state_excluded']

def test_historical_may_and_june_queries_do_not_replace_current_forward_batch():
    original={'P05':{'unselected_original':True}}
    scope=queries.selected_scopes(original,['P05'],enabled=True,root_lookup=root_spec)['P05']
    assert scope['parent_cursor']=='2022-07-29' and len(scope['terms'])==102
    held=[t for t in scope['terms'] if t['parent_positions']]
    assert len(held)==1 and held[0]['ticker']=='ACC' and held[0]['parent_positions'][0]['quantity']==29
    assert not any('pending_at_parent' in t for t in scope['terms'])
    assert next(q for q in queries.registry().queries if q.arm=='P05').scope.parent_cursor=='2022-05-31'

def test_p03_DOVA_preparation_query_has_exact_native_and_event_quote_only():
    scope=queries.selected_scopes({},['P03'],enabled=True,root_lookup=lambda arm:root_spec(arm,'2dfc5b30f486d40f97ab4f93c21ae75862714f0d0b410bd56228b137370329d0'))['P03']
    assert scope['parent_cursor']=='2019-10-31'
    assert len(scope['terms'])==len(scope['additional_rows'])==1
    assert scope['terms'][0]['ticker']=='DOVA' and scope['terms'][0]['session']=='2019-11-11'
    assert scope['terms'][0]['native_session']==scope['additional_rows'][0]['session']=='2019-11-12'

def test_current_p03_december503_root_retains_full16_inputs_and_49_actual_proofs():
    spec=root_spec('P03');validate_root_spec(spec)
    old=root_spec('P03','2dfc5b30f486d40f97ab4f93c21ae75862714f0d0b410bd56228b137370329d0')
    assert (spec['measured_closes'],spec['selected_session'])==(503,'2019-12-31')
    assert len(spec['repairs'])==16 and spec['repairs'][:15]==old['repairs']
    proof=spec['root_admission']['branch_uncertainty_proof']
    assert (proof['rows'],proof['retained_rows'])==(41,8)
    source=spec['root_admission']['source_input_proof']
    assert source['all_financial_observer_terms']==18 and source['January_tails_and_failed_state_excluded']
    scope=queries.selected_scopes({},['P03'],enabled=True,root_lookup=root_spec)['P03']
    assert len(scope['terms'])==128 and scope['parent_cursor']=='2019-12-31'
    assert all(term['parent_positions']==[] for term in scope['terms'])
