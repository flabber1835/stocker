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
    assert t['source_capture']['run_id']==41827156321 and codec.catalog_sha==f.OWN_CASH_SHA
    f.research_cash_term(t);f.completion_session(t,['2020-07-29','2020-07-30','2020-07-31','2020-08-03'])
    assert f.suppressions(dict(source_cursor='2020-06-30'),terms)==[dict(session='2020-07-30',
        security_id=t['security_id'],term_sha256=t['native_term_sha256'])]
    old,_,_=f.selected('P00',cursor='2025-06-30')
    assert old.catalog_sha=='4467104fa7d591af78c7665895b453757c04431492c4a805fa6027ae24f27d84'
    assert len(old.catalog['terms'])==7 and len(codec.catalog['terms'])==8


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
