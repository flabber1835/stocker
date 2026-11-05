"""Published cash with disclosed daily timing approximation; DATA/synthetic only."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
from research.capital_risk.forecast_tests.test_financial_source_close import removed_guard


def term():return f.selected('P07',cursor='2020-06-30')[2][0]


def test_lm_published_consideration_is_an_explicit_research_timing_assumption():
    codec,_,terms=f.selected('P07',cursor='2020-06-30');t,=terms
    assert t['ticker']=='LM' and t['added']['cash_per_share']==50.
    assert t['added']['session']==t['actual_completion_date']=='2020-07-31'
    assert t['native_session']==t['last_trading_session']=='2020-07-30'
    assert t['preopen_completion_confirmed'] is False
    assert t['research_assumption']['opening_availability_assumed'] is True
    assert t['research_assumption']['actual_settlement_claimed'] is False
    assert t['parent_positions']==[dict(slot_id=20,ticker='LM',quantity=49,entry_date='2020-06-24')]
    assert t['source_capture']['run_id']==41827156321 and codec.catalog_sha=='1baf3f3938fa8fa6e31ddd1ca7c264f79f8eae8de8396c2828fdf831c2436915'
    f.research_cash_term(t);f.completion_session(t,['2020-07-29','2020-07-30','2020-07-31','2020-08-03'])
    assert f.suppressions(dict(source_cursor='2020-06-30'),terms)==[dict(session='2020-07-30',
        security_id=t['security_id'],term_sha256=t['native_term_sha256'])]
    old,_,_=f.selected('P00',cursor='2025-06-30')
    assert old.catalog_sha=='4467104fa7d591af78c7665895b453757c04431492c4a805fa6027ae24f27d84'
    assert len(old.catalog['terms'])==7 and len(codec.catalog['terms'])==8


def test_edr_uses_same_daily_cash_model_from_own169_without_identity_upgrade():
    codec,_,terms=f.selected('P11',cursor='2018-08-31');t,=terms
    assert codec.catalog_sha=='ddfb2f16b73dae3b1d4586e11ba3d8ec84365de260fcbc7e9cb9cf21b9481852'
    assert len(codec.catalog['terms'])==13
    assert t['parent_root_admission_sha256']=='33320498ba5db684738471b48b0ed3e66ebf78fe5b2b9dc24a34be047cdbf3ed'
    assert t['ticker']=='EDR1' and t['identity_witness']['security_type_eligible']=='0'
    assert t['parent_positions']==[dict(slot_id=4,ticker='EDR1',quantity=1,entry_date='2018-08-31')]
    assert t['source_capture']['artifact_id']==13345399053
    assert t['added']['cash_per_share']==41.5 and t['added']['session']==t['actual_completion_date']=='2018-09-20'
    assert t['native_session']==t['last_trading_session']=='2018-09-19'
    assert t['research_assumption']['opening_availability_assumed'] is True
    assert t['research_assumption']['actual_settlement_claimed'] is t['preopen_completion_confirmed'] is False
    f.research_cash_term(t);f.completion_session(t,['2018-09-18','2018-09-19','2018-09-20','2018-09-21'])
    assert f.suppressions(dict(source_cursor='2018-08-31'),terms)==[dict(session='2018-09-19',security_id=t['security_id'],term_sha256=t['native_term_sha256'])]
    previous,_,_=f.selected('P04',cursor='2025-10-31')
    assert previous.catalog_sha=='a312304df09aa19feabce82cce92adc1798a49e104333fc4d7d5cb7ce94af77f'


@pytest.mark.parametrize('change',['cash','publication','date','preopen','mandatory','stock','claim','extra'])
def test_research_approximation_cannot_change_published_cash_or_claim_settlement(change):
    t=deepcopy(term())
    if change=='cash':t['added']['cash_per_share']=49.99
    elif change=='publication':t['research_assumption']['published_cash_per_share']='49.99'
    elif change=='date':t['added']['session']='2020-07-30'
    elif change=='preopen':t['preopen_completion_confirmed']=True
    elif change=='mandatory':t['mandatory_common_share_completion_confirmed']=False
    elif change=='stock':t['added']['exchange_ratio']=0.1
    elif change=='claim':t['research_assumption']['actual_settlement_claimed']=True
    else:t['research_assumption']['broker_authority']=True
    with pytest.raises(ValueError):f.research_cash_term(t)


def test_research_cash_guard_removal_admits_a_changed_published_amount():
    t=deepcopy(term());t['added']['cash_per_share']=49.99
    with pytest.raises(ValueError):f.research_cash_term(t)
    assert removed_guard('research_cash_term','OWN_INPUT_EXPLICIT_RESEARCH_CASH_AMOUNT_AND_DAILY_RECOGNITION')(t) is None


def test_research_axis_guard_removal_admits_a_missing_daily_boundary():
    t=term();dates=['2020-07-29','2020-07-30','2020-08-03']
    with pytest.raises(ValueError):f.completion_session(t,dates)
    assert removed_guard('completion_session','OWN_INPUT_RESEARCH_EXACT_NEXT_FROZEN_DAILY_BOUNDARY')(t,dates) is None


def test_resolved_tvty_uses_the_same_cash_model_from_own1111_without_backdating_holdings():
    codec,_,terms=f.selected('P11',cursor='2022-05-31');t,=terms
    assert codec.catalog_sha=='465c8a78287c5cb7864aa400e13290f07f278c31e2a34897018cf5403551070c' and len(codec.catalog['terms'])==16
    assert t['parent_root_admission_sha256']=='524ad7d5c2ca46bd48d6fdd7066c788ba557e62116246a1fae9b00845a106e58'
    assert t['parent_positions']==[] and t['source_capture']['artifact_id']==13367285466
    assert t['identity_witness']['session']=='2022-06-24'
    assert t['identity_witness']['source_observation_sha256']=='977374e6361f5729f4bf403a1afc640a237ac62660f3f1055bffb4d3b7eb24ab'
    assert f.digest(t['native'])==t['native_term_sha256']=='aca7bf92b9c5faea11cf82b77b7e081e728242a3775f9ba2f435da3015236e95'
    assert t['native_session']==t['last_trading_session']=='2022-06-27'
    assert t['added']['cash_per_share']==32.5 and t['added']['session']=='2022-06-28'
    assert t['research_assumption']['actual_settlement_claimed'] is t['preopen_completion_confirmed'] is False
    f.research_cash_term(t);f.completion_session(t,['2022-06-24','2022-06-27','2022-06-28'])
