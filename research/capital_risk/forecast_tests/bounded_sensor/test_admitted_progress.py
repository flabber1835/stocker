"""Exact historical input scopes and newly admitted P05 prefix, DATA only."""
from system_campaign_financial_partial import root_spec,validate_root_spec
import system_campaign_explicit_source_queries as queries

def test_current_p05_june_root_has_full15_inputs_and_independent_six_cash_proof():
    spec=root_spec('P05');validate_root_spec(spec)
    old=root_spec('P05','402b9ce10942fca4dcaac829303c6426a83a6a894ecf35d9cf472c4d84a8bb8d')
    assert (spec['measured_closes'],spec['selected_session'])==(1132,'2022-06-30')
    assert len(spec['repairs'])==15 and spec['repairs'][:-1]==old['repairs']
    a=spec['root_admission'];p=a['source_input_proof']
    assert a['parent_root_admission_sha256']==old['root_admission_sha256']
    assert (a['new_daily_records'],a['independent_accounting_snapshots'],a['new_monthly_reports'])==(21,42,1)
    assert p['passed'] and p['retained_observer_terms']==26 and len(p['actual_cash_events'])==6
    assert p['July_failed_canonical_state_excluded']

def test_old_may_MSP_query_does_not_activate_for_new_june_root():
    original={'P05':{'unselected_original':True}}
    scope=queries.selected_scopes(original,['P05'],enabled=True,root_lookup=root_spec)['P05']
    assert scope['parent_cursor']=='2022-06-30' and scope['terms'][0]['ticker']=='SRRA'
    assert scope['terms'][0]['pending_at_parent']['pending_sessions']==0
    assert next(q for q in queries.registry().queries if q.arm=='P05').scope.parent_cursor=='2022-05-31'

def test_p03_DOVA_preparation_query_has_exact_native_and_event_quote_only():
    scope=queries.selected_scopes({},['P03'],enabled=True,root_lookup=root_spec)['P03']
    assert scope['parent_cursor']=='2019-10-31'
    assert len(scope['terms'])==len(scope['additional_rows'])==1
    assert scope['terms'][0]['ticker']=='DOVA' and scope['terms'][0]['session']=='2019-11-11'
    assert scope['terms'][0]['native_session']==scope['additional_rows'][0]['session']=='2019-11-12'
