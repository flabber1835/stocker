"""Never-held source exit is explicitly incapable of portfolio settlement."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
from research.capital_risk.forecast_tests.test_financial_source_close import absent, removed_guard

def term():return f.selected('P04',cursor='2025-10-31')[2][0]

def parent_and_material():
    t=term();w,p,l=absent()
    cp=dict(sha256=t['parent_outer_sha256'],source_cursor=t['parent_cursor'],run=dict(state=dict(wealth_core=w,pending=p,ledger=l)))
    material=dict(arm='P04',parent_outer_sha256=cp['sha256'],terms=[t])
    return cp,material

def test_source_exit_preserves_exact_quote_native_and_denies_settlement():
    c,_,ts=f.selected('P04',cursor='2025-10-31');t,=ts
    assert t['ticker']=='LNWO' and t['identity_witness']['security_type_eligible']=='1'
    assert t['parent_positions']==[] and t['source_capture']['run_id']==41858834037
    assert t['added']['cash_per_share']==85.6 and t['added']['session']==t['native_session']=='2025-11-14'
    assert t['retained_quote']['session']=='2025-11-13'
    assert t['research_assumption']['retained_quote_sha256']=='4dac7b2fbc872f09880871131fee7dbbdce97df5e1d4bb5a1fcc6e6c8285d3f0'
    assert t['mandatory_common_share_completion_confirmed'] is t['portfolio_completion_authorized'] is False
    assert t['research_assumption']['held_settlement_supported'] is t['research_assumption']['actual_settlement_claimed'] is False
    f.research_source_exit_term(t);f.completion_session(t,['2025-11-13','2025-11-14'])
    assert len(c.catalog['terms'])==12 and c.catalog_sha==f.OWN_CASH_SHA
    assert f.selected('P05',cursor='2018-01-31')[0].catalog_sha=='c2b3d070ba31bd94c947c057f667cca2452ee3ff4875fcd458164b947e5147a2'

@pytest.mark.parametrize('change',['cash','quote','digest','date','mandatory','preopen','held','portfolio','stock','reference','claim','execution','identity','scope','extra'])
def test_source_exit_cannot_become_a_cash_right_or_change_its_source(change):
    t=deepcopy(term())
    if change=='cash':t['added']['cash_per_share']=86.
    elif change=='quote':t['retained_quote']['raw_close']=86.
    elif change=='digest':t['research_assumption']['retained_quote_sha256']='0'*64
    elif change=='date':t['added']['session']='2025-11-17'
    elif change=='mandatory':t['mandatory_common_share_completion_confirmed']=True
    elif change=='preopen':t['preopen_completion_confirmed']=True
    elif change=='held':t['parent_positions']=[dict(quantity=1)]
    elif change=='portfolio':t['portfolio_completion_authorized']=True
    elif change=='stock':t['added']['exchange_ratio']=1.
    elif change=='reference':t['added']['reference']='actual statutory cash'
    elif change=='claim':t['research_assumption']['actual_settlement_claimed']=True
    elif change=='execution':t['research_assumption']['execution_price_claimed']=True
    elif change=='identity':t['research_assumption']['legal_identity_admitted']=True
    elif change=='scope':t['research_assumption']['scope']='CURRENTLY_UNHELD_ONLY'
    else:t['research_assumption']['broker_authority']=True
    with pytest.raises(ValueError):f.research_source_exit_term(t)

def test_model_guard_removal_accepts_changed_price():
    t=deepcopy(term());t['added']['cash_per_share']=86.
    with pytest.raises(ValueError):f.research_source_exit_term(t)
    assert removed_guard('research_source_exit_term','OWN_INPUT_EXPLICIT_UNHELD_SOURCE_EXIT_NO_SETTLEMENT')(t) is None

def test_quote_guard_removal_accepts_a_different_frozen_raw_close():
    t=term();row=dict(t['retained_quote'],raw_close='85.7')
    with pytest.raises(ValueError,match='EXACT_FROZEN_RAW_QUOTE'):f.source_exit_quote(t,row)
    assert removed_guard('source_exit_quote','OWN_INPUT_SOURCE_EXIT_EXACT_FROZEN_RAW_QUOTE')(t,row) is None

def test_axis_guard_removal_accepts_later_recognition():
    t=term();dates=['2025-11-13','2025-11-17']
    with pytest.raises(ValueError):f.completion_session(t,dates)
    assert removed_guard('completion_session','OWN_INPUT_SOURCE_EXIT_EXACT_NEXT_FROZEN_DAILY_BOUNDARY')(t,dates) is None

def test_new_scope_keeps_never_held_history_mandatory_on_the_parent():
    cp,m=parent_and_material();scope,=f.source_scopes(cp,m,'a'*64,'b'*64)
    assert scope['schema']=='research.never-held-source-exit-scope/1'
    assert scope['require_never_held'] is True and scope['portfolio_completion_authorized'] is False
    assert scope['source_ticker']=='LNWO'
    for change in ('require_never_held','portfolio_completion_authorized'):
        bad=deepcopy(scope);bad[change]=not bad[change]
        with pytest.raises(ValueError):f.NeverHeldSourceExitScope.model_validate(bad)
    cp['run']['state']['ledger']['events'].append(dict(detail=dict(source_ticker='LNWO')))
    with pytest.raises(ValueError,match='NO_HISTORICAL_OWNERSHIP'):f.source_scopes(cp,m,'a'*64,'b'*64)

def test_history_guard_removal_hides_prior_source_ownership():
    cp,m=parent_and_material();scope,=f.source_scopes(cp,m,'a'*64,'b'*64)
    state=cp['run']['state'];state['ledger']['events'].append(dict(security_id=scope['security_id'],event_type='BUY'))
    args=(state['wealth_core'],state['pending'],state['ledger'],scope)
    with pytest.raises(ValueError,match='NO_HISTORICAL_OWNERSHIP'):f.require_source_scope(*args)
    assert removed_guard('require_source_scope','FUTURE_SOURCE_EXIT_NO_HISTORICAL_OWNERSHIP')(*args) is None
