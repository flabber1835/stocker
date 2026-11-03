"""Analytic acquisition and strict chronological-input falsifiers, no backtest."""
import math
from copy import deepcopy
import pytest
from system_campaign_acquire import expected_improvement,choose
from system_campaign_space import DEFAULT,record

def test_expected_improvement_matches_normal_integral_at_zero_improvement():
    assert expected_improvement(.01,1.,0.)==pytest.approx(1/math.sqrt(2*math.pi),abs=1e-15)
    assert expected_improvement(-2.,0.,0.)==0.

def test_later_metrics_and_invented_result_fields_are_refused():
    first=record(DEFAULT);pool=[first]+[record({**DEFAULT,'slots':n,'review':review}) for n in (10,30) for review in (63,119,189)]
    row={'core_id':first['id'],'training_end':'2020-12-31','parameters':first['parameters'],
        'budgets':[{'relative_budget':b,'annual_log_growth':.1,'drawdown_magnitude':.1,'baseline_drawdown_magnitude':.2} for b in (.5,.75,1.)]}
    a=choose([row],pool,[first['id']],'2020-12-31');assert len({r['id'] for r in a['choices']})==4
    assert choose([row],pool,[first['id']],'2020-12-31')['choices']==a['choices']
    bad=deepcopy(row);bad['training_end']='2022-12-30'
    with pytest.raises(ValueError):choose([bad],pool,[first['id']],'2020-12-31')
    bad=deepcopy(row);bad['evaluation_result']=999
    with pytest.raises(ValueError):choose([bad],pool,[first['id']],'2020-12-31')
