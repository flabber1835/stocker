"""Published ADS cash with explicit participation assumption; DATA only."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
from research.capital_risk.forecast_tests.test_financial_source_close import removed_guard

def term():return f.selected('P05',cursor='2018-01-31')[2][0]

@pytest.mark.parametrize('arm,quantity,artifact',[('P05',25,13338596091),('P06',17,13337926516),('P11',35,13337507034)])
def test_each_own_ads_book_uses_shared_disclosed_tender_model(arm,quantity,artifact):
    c,_,terms=f.selected(arm,cursor='2018-01-31');t,=terms
    assert t['ticker']=='AAAP1' and t['identity_witness']['security_type_eligible']=='0'
    assert t['parent_positions'][0]['quantity']==quantity and t['source_capture']['artifact_id']==artifact
    assert t['source_capture']['run_id']==41856244317
    assert t['added']['session']=='2018-02-01' and t['added']['cash_per_share']==82.
    assert t['native_session']=='2018-02-09' and t['actual_mandatory_exchange_session']=='2018-07-13'
    assert t['actual_mandatory_net_cash_per_ads']=='81.95'
    assert t['mandatory_common_share_completion_confirmed'] is t['preopen_completion_confirmed'] is False
    assert t['research_assumption']['tender_participation_assumed'] is True
    assert t['research_assumption']['actual_settlement_claimed'] is False
    assert len(c.catalog['terms'])==11 and c.catalog_sha=='c2b3d070ba31bd94c947c057f667cca2452ee3ff4875fcd458164b947e5147a2'
    f.research_tender_term(t);f.completion_session(t,['2018-01-31','2018-02-01','2018-02-09'])
    assert f.suppressions(dict(source_cursor='2018-01-31'),terms)==[dict(session='2018-02-09',security_id=t['security_id'],term_sha256=t['native_term_sha256'])]

@pytest.mark.parametrize('change',['cash','publication','deadline','date','native','mandatory','preopen','stock','identity','reference','participation','claim','unit','extra'])
def test_model_cannot_change_published_cash_or_assert_actual_settlement(change):
    t=deepcopy(term())
    if change=='cash':t['added']['cash_per_share']=81.95
    elif change=='publication':t['research_assumption']['published_cash_per_source_unit']='81.95'
    elif change=='deadline':t['research_assumption']['offer_deadline_session']='2018-01-30'
    elif change=='date':t['added']['session']='2018-02-02'
    elif change=='native':t['native_session']='2018-02-01'
    elif change=='mandatory':t['mandatory_common_share_completion_confirmed']=True
    elif change=='preopen':t['preopen_completion_confirmed']=True
    elif change=='stock':t['added']['exchange_ratio']=0.2
    elif change=='identity':t['identity_witness']['ticker']='OTHER'
    elif change=='reference':t['added']['reference']='unbound'
    elif change=='participation':t['research_assumption']['tender_participation_assumed']=False
    elif change=='claim':t['research_assumption']['actual_settlement_claimed']=True
    elif change=='unit':t['research_assumption']['source_unit']='ORDINARY_COMMON_SHARE'
    else:t['research_assumption']['broker_authority']=True
    with pytest.raises(ValueError):f.research_tender_term(t)

def test_tender_amount_guard_removal_accepts_wrong_cash():
    t=deepcopy(term());t['added']['cash_per_share']=81.95
    with pytest.raises(ValueError):f.research_tender_term(t)
    assert removed_guard('research_tender_term','OWN_INPUT_EXPLICIT_ASSUMED_TENDER_AND_PUBLISHED_CASH')(t) is None

def test_tender_daily_boundary_guard_removal_accepts_missing_recognition_date():
    t=term();dates=['2018-01-31','2018-02-02','2018-02-09']
    with pytest.raises(ValueError):f.completion_session(t,dates)
    assert removed_guard('completion_session','OWN_INPUT_TENDER_EXACT_NEXT_FROZEN_DAILY_BOUNDARY')(t,dates) is None
