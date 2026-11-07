"""Actual prepared raw rows; full-scan counters and absence are explicit inputs."""
import json,sys
from copy import deepcopy
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parent))
import system_campaign_abmd_bounded_hydration as data

@pytest.fixture(scope='module')
def actual():return json.loads((Path(__file__).resolve().parents[2]/'P07-own1238-ABMD-bounded-catalog-v2.json').read_bytes())

def values(c):return dict(native=c['native'],rows=[c['market_source']['raw_identity_row'],c['market_source']['raw_prior_row']],scanned=2080223,security_rows=245,last_source_session='2022-12-21')

def test_actual_absent_completion_quote_with_exact_native_and_prior_rows(actual):
    result=data.witness(actual,**values(actual))
    assert result==actual['market_source'] and result['source_quote_present'] is False

@pytest.mark.parametrize('change',['quote','missing_identity','missing_prior','duplicate','prior_value','scanned','bool_scanned','sid_count','last','native'])
def test_incomplete_scan_changed_row_or_completion_quote_refuses(actual,change):
    v=deepcopy(values(actual))
    if change=='quote':v['rows'].append(dict(v['rows'][-1],session='2022-12-22'))
    elif change=='missing_identity':v['rows']=v['rows'][1:]
    elif change=='missing_prior':v['rows']=v['rows'][:1]
    elif change=='duplicate':v['rows'].append(deepcopy(v['rows'][-1]))
    elif change=='prior_value':v['rows'][-1]['raw_close']='1'
    elif change=='scanned':v['scanned']-=1
    elif change=='bool_scanned':v['scanned']=True
    elif change=='sid_count':v['security_rows']-=1
    elif change=='last':v['last_source_session']='2022-12-22'
    else:v['native']['cash_per_share']=380.
    with pytest.raises(ValueError):data.witness(actual,**v)

def test_hydrate_refuses_before_financial_import_when_not_hosted(monkeypatch):
    import full_system_core
    def refuse():raise ValueError('NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    with pytest.raises(ValueError,match='NOT_HOSTED'):data.hydrate({},None)
