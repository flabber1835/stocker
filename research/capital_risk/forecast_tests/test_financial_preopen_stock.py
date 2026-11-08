"""Qualified stock-only input guards; DATA and synthetic falsifiers only."""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
from research.capital_risk.forecast_tests.test_financial_native_preimage import without_guard

def term():
    return deepcopy(next(t for t in json.loads((f.HERE/f.OWN_CASH_CATALOG).read_bytes())['terms'] if t['recognition_rule']==f.PREOPEN_STOCK))

def test_stock_only_input_and_historical_generations():
    raw=term();selected=f.selected_stock_term(raw)
    assert raw['added']['exchange_ratio']=='0.485'
    assert selected['added']['cash_per_share']==0. and Fraction(str(selected['added']['exchange_ratio']))==Fraction(97,200)
    assert raw==term()
    codec,name,terms=f.selected('P03',cursor='2018-12-31')
    assert terms==[selected] and len(codec.catalog['terms'])==21
    old=dict(codec.catalog,terms=codec.catalog['terms'][:20])
    assert f.sha((json.dumps(old,sort_keys=True,indent=2,allow_nan=False)+'\n').encode())=='f7653bb52979ef4129741af32ae48bbd3463925dc26bd8f5f5aad60c1035e530'
    f.completion_session(selected,['2019-01-30','2019-01-31','2019-02-01'])

@pytest.mark.parametrize('change',['cash','ratio','phase','identity','proxy','settlement','extraction'])
def test_changed_input_refuses(change):
    t=term()
    if change=='cash':t['added']['cash_per_share']=1.
    elif change=='ratio':t['added']['exchange_ratio']='0.485000000000000001'
    elif change=='phase':t['preopen_completion_confirmed']=False
    elif change=='identity':t['added']['delivered_security_id']='OTHER'
    elif change=='proxy':t['proxy']['source_observation_sha256']='0'*64
    elif change=='settlement':t['proxy']['actual_settlement_rate_observed']=True
    else:t['primary_extraction']['cash_per_ordinary_common_share']='1'
    with pytest.raises(ValueError):f.confirmed_preopen_stock_term(t)

def test_zero_cash_guard_has_removal_falsifier():
    t=term();t['added']['cash_per_share']=1.
    with pytest.raises(ValueError):f.confirmed_preopen_stock_term(t)
    assert without_guard('confirmed_preopen_stock_term','OWN_INPUT_EXACT_CONFIRMED_PREOPEN_ZERO_CASH_STOCK_RIGHT')(t)['added']['cash_per_share']==1.

def test_calendar_guard_has_removal_falsifier():
    t=term();dates=['2019-01-30','2019-01-31','2019-02-04']
    with pytest.raises(ValueError):f.completion_session(t,dates)
    assert without_guard('completion_session','OWN_INPUT_PREOPEN_STOCK_EXACT_FROZEN_NEXT_SESSION')(t,dates)is None
