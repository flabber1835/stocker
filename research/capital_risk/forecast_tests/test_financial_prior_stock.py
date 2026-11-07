"""Source-qualified prior-date stock right and calendar falsifiers; DATA only."""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
from research.capital_risk.forecast_tests.test_financial_native_preimage import without_guard

def term():return deepcopy(next(t for t in json.loads((f.HERE/f.OWN_CASH_CATALOG).read_bytes())['terms']if t['recognition_rule']==f.PRIOR_STOCK))

def test_holiday_completion_and_exact_prior22_generation():
    raw=term();selected=f.selected_stock_term(raw)
    assert raw['actual_completion_date']=='2021-01-01' and selected['added']['session']=='2021-01-04'
    assert selected['added']['cash_per_share']==0. and Fraction(str(selected['added']['exchange_ratio']))==Fraction(21,16)
    assert selected['proxy']['actual_settlement_rate_observed']is False
    f.completion_session(selected,['2020-12-30','2020-12-31','2021-01-04'])
    codec,_,terms=f.selected('P05',cursor='2020-11-30');assert terms==[selected]
    previous=dict(codec.catalog,terms=codec.catalog['terms'][:22])
    assert f.sha((json.dumps(previous,sort_keys=True,indent=2,allow_nan=False)+'\n').encode())=='f9f1ee6486767af7597a34be9425b22d6856bc26237255b1465055289494468e'
    import system_campaign_financial_resume as resume
    original=raw['retained_original_legal_record']
    assert original['proxy_authority_reused']is False
    assert resume.expected_request()['sources'][original['catalog_file']]==original['catalog_sha256']

@pytest.mark.parametrize('change',['cash','ratio','date','preopen','identity','settlement','extraction'])
def test_wrong_right_or_timing_claim_refuses(change):
    t=term()
    if change=='cash':t['added']['cash_per_share']=1.
    elif change=='ratio':t['added']['exchange_ratio']='1.312500000000000001'
    elif change=='date':t['actual_completion_date']=t['added']['session']
    elif change=='preopen':t['preopen_completion_confirmed']=True
    elif change=='identity':t['added']['delivered_security_id']='OTHER'
    elif change=='settlement':t['proxy']['actual_settlement_rate_observed']=True
    else:t['primary_extraction']['cash_per_ordinary_common_share']='1'
    with pytest.raises(ValueError):f.confirmed_prior_stock_term(t)

def test_zero_cash_guard_removal_falsifier():
    t=term();t['added']['cash_per_share']=1.
    with pytest.raises(ValueError):f.confirmed_prior_stock_term(t)
    assert without_guard('confirmed_prior_stock_term','OWN_INPUT_EXACT_CONFIRMED_PRIOR_ZERO_CASH_STOCK_RIGHT')(t)['added']['cash_per_share']==1.

def test_first_frozen_calendar_guard_removal_falsifier():
    t=term();dates=['2020-12-30','2020-12-31','2021-01-05']
    with pytest.raises(ValueError):f.completion_session(t,dates)
    assert without_guard('completion_session','OWN_INPUT_PRIOR_STOCK_FIRST_FROZEN_SESSION_AFTER_COMPLETION')(t,dates)is None
