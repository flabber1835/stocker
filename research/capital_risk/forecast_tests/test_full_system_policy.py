"""Pure proposal geometry and selection-leak tests; no financial replay."""
import importlib.util
from pathlib import Path
import pytest

P=Path(__file__).resolve().parents[1]/'full_system_controller_policy.py'
spec=importlib.util.spec_from_file_location('full_system_policy_pure',P)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def test_pool_is_deterministic_and_contains_exact_parent_and_owned_baseline():
    values=m.profiles();assert values==m.profiles() and len(values)==256
    assert values[0]['parent']==m.BASE_PARENT and values[0]['owned']==m.BASE_OWNED
    assert len({p['id'] for p in values})==256


def row(name,multiple,drawdown,turnover='1'):
    return {'id':name,'core_id':'synthetic-core','group':name,
        'metrics':{'multiple':multiple,'maximum_drawdown_magnitude':drawdown,
            'anchor':'2018-01-02','start':'2018-01-03','end':'2022-12-30','closes':1258},
        'turnover':turnover}


def test_selection_uses_exact_joint_objective_and_several_drawdown_budgets():
    values=[row('base','6/5','1/5'),row('growth','7/5','19/100'),row('balanced','13/10','1/10'),row('loss','1/2','1/100')]
    result=m.select(values,'base')
    assert result['selected']==['balanced','growth']
    assert result['training_joint_improvements']==2 and result['best_joint']=='growth'


def test_selection_refuses_evaluation_fields_and_mismatched_periods():
    bad=row('base','6/5','1/5');bad['evaluation_multiple']='999'
    with pytest.raises(ValueError,match='TRAINING_ONLY'):m.select([bad],'base')
    base=row('base','6/5','1/5');other=row('other','7/5','1/10');other['metrics']['end']='2026-07-31'
    with pytest.raises(ValueError,match='COMMON_TRAINING'):m.select([base,other],'base')
