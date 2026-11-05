"""Explicit approximate daily mixed consideration; DATA and synthetic guards only."""
import ast
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
from research.capital_risk.forecast_tests.test_financial_native_preimage import without_guard


def term():
    catalog=json.loads((f.HERE/f.OWN_CASH_CATALOG).read_bytes())
    return deepcopy(next(t for t in catalog['terms'] if t['recognition_rule']==f.RESEARCH_MIXED))


def test_fmsa_model_preserves_approximation_real_source_and_literal_ratio():
    raw=term();before=deepcopy(raw);selected=f.research_mixed_term(raw)
    codec,name,terms=f.selected('P03',cursor='2018-04-30')
    assert terms==[selected] and raw==before and len(codec.catalog['terms'])==14
    assert selected['added']['cash_per_share']==.73 and selected['added']['exchange_ratio']==.2
    assert Fraction(raw['added']['exchange_ratio'])==Fraction(str(selected['added']['exchange_ratio']))==Fraction(1,5)
    assert raw['research_assumption']['published_cash_is_approximate']is True
    assert raw['research_assumption']['actual_settlement_claimed']is raw['preopen_completion_confirmed']is False
    assert selected['delivered_identity_witness']['ticker']=='CVIAQ'
    assert selected['delivered_identity_witness']['security_type_eligible']=='0'
    assert selected['added']['session']==selected['actual_completion_date']=='2018-06-01'
    f.completion_session(selected,['2018-05-30','2018-05-31','2018-06-01','2018-06-04'])
    resolved=f.registered_scope(raw['source_capture']['scope_sha256'])
    query=f.registered_scope(raw['source_capture']['query_scope_sha256'])
    assert f.selected_query_scope(raw,query)==resolved
    assert resolved['additional_rows'][0]['source_observation_sha256']==raw['proxy']['source_observation_sha256']
    assert f.suppressions(dict(source_cursor='2018-04-30'),terms)==[dict(session='2018-05-31',security_id=raw['security_id'],term_sha256=raw['native_term_sha256'])]


@pytest.mark.parametrize('change',['cash','ratio','precision','approximation','settlement','date','phase','identity','proxy','aggregation','cil','extra'])
def test_changed_terms_or_false_settlement_claims_refuse(change):
    t=term()
    if change=='cash':t['added']['cash_per_share']=.74
    elif change=='ratio':t['added']['exchange_ratio']='0.21'
    elif change=='precision':t['added']['exchange_ratio']='0.20000000000000000001'
    elif change=='approximation':t['research_assumption']['published_cash_is_approximate']=False
    elif change=='settlement':t['research_assumption']['actual_settlement_claimed']=True
    elif change=='date':t['added']['session']='2018-06-04'
    elif change=='phase':t['preopen_completion_confirmed']=True
    elif change=='identity':t['added']['delivered_security_id']='OTHER'
    elif change=='proxy':t['proxy']['source_observation_sha256']='0'*64
    elif change=='aggregation':t['added']['entitlement_aggregation']='LOT'
    elif change=='cil':t['added']['cash_in_lieu_price_per_delivered_share']=28.
    else:t['research_assumption']['broker_authority']=True
    with pytest.raises(ValueError):f.research_mixed_term(t)


def test_mixed_amount_guard_removal_falsifier():
    t=term();t['added']['cash_per_share']=.74
    with pytest.raises(ValueError):f.research_mixed_term(t)
    assert without_guard('research_mixed_term','OWN_INPUT_EXPLICIT_RESEARCH_MIXED_AMOUNT_RATIO_IDENTITY_AND_TIMING')(t)['added']['cash_per_share']==.74


def test_calendar_guard_removal_falsifier():
    t=f.research_mixed_term(term());dates=['2018-05-30','2018-06-01','2018-06-04']
    with pytest.raises(ValueError):f.completion_session(t,dates)
    assert without_guard('completion_session','OWN_INPUT_RESEARCH_MIXED_NEXT_FROZEN_DAILY_BOUNDARY')(t,dates)is None


def test_query_identity_and_count_guard_removal_falsifiers():
    t=term();q=f.registered_scope(t['source_capture']['query_scope_sha256'])
    q['additional_row_queries'][0]['ticker']='OTHER'
    with pytest.raises(ValueError):f.selected_query_scope(t,q)
    assert without_guard('selected_query_scope','OWN_INPUT_CAPTURED_DELIVERY_QUERY_IDENTITY_AND_ROW_DIGEST')(t,q)['additional_rows']
    q=f.registered_scope(t['source_capture']['query_scope_sha256']);q['additional_row_queries'].append(deepcopy(q['additional_row_queries'][0]))
    with pytest.raises(ValueError):f.selected_query_scope(t,q)
    assert without_guard('selected_query_scope','OWN_INPUT_ONE_CAPTURED_DELIVERY_QUERY')(t,q)['additional_rows']


def test_prior_cash_and_weekend_stock_validators_remain_ast_identical():
    old=subprocess.check_output(['git','show','1ba6755b4b0d9bb03a699e54fc7f61a13cc052f7:research/capital_risk/system_campaign_financial_future.py'])
    def functions(raw):
        result={}
        for n in ast.parse(raw).body:
            if not isinstance(n,ast.FunctionDef):continue
            while n.name=='selected_stock_term' and isinstance(n.body[1],ast.If) and any(mode in ast.unparse(n.body[1].test)for mode in ('PREOPEN_STOCK','PRIOR_STOCK')):
                del n.body[1]
            result[n.name]=ast.dump(n,include_attributes=False)
        return result
    before,after=functions(old),functions(Path(f.__file__).read_bytes())
    for name in ('selected_stock_term','research_cash_term','research_tender_term','research_source_exit_term','source_cash_term','completion_cash_term'):
        assert before[name]==after[name],name


def test_all_thirteen_prior_catalog_records_have_the_original_bytes():
    catalog=json.loads((f.HERE/f.OWN_CASH_CATALOG).read_bytes());catalog['terms']=catalog['terms'][:13]
    raw=(json.dumps(catalog,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    assert f.sha(raw)=='ddfb2f16b73dae3b1d4586e11ba3d8ec84365de260fcbc7e9cb9cf21b9481852'
    assert f.selected('P11',cursor='2018-08-31')[0].catalog_sha==f.sha(raw)
