from decimal import Decimal as D
from itertools import product
from types import SimpleNamespace

import numpy as np
import pytest

from research.exposure_oracle.accounting import Day
from research.exposure_oracle import target_search as search


def problem():
    grid=(D(0),D('.55'),D(1))
    days=[Day(str(i),D(str(g)),D(str(d)),D(str(g))*D(str(d)),D(1),D(1),D(1))
          for i,(g,d) in enumerate(((1,1.03),(.995,1.01),(1.005,.98),(1,1.025),(.99,1.015),(1.01,.99)))]
    return np.stack([d.matrix(grid) for d in days]),0,np.zeros(len(days),dtype=int)


def exhaustive(m,initial,actual):
    return [(list(p),search.path_metrics(m,initial,actual,list(p))) for p in product(range(3),repeat=len(m))]


def test_budget_dynamic_program_matches_exhaustive_max_growth_for_every_budget():
    m,initial,actual=problem()
    candidates=exhaustive(m,initial,actual)
    result=search.forward(m,initial,actual,len(m))
    for k in range(len(m)+1):
        expected=max(v['log_wealth'] for _,v in candidates if v['changed_days']==k)
        assert result.growth[-1,k].max()==pytest.approx(expected,abs=1e-12)
        recovered=search.path_metrics(m,initial,actual,result.path(k))
        assert recovered['changed_days']==k
        assert recovered['log_wealth']==pytest.approx(expected,abs=1e-12)


def test_growth_pruning_keeps_every_feasible_path_at_fixed_budget():
    m,initial,actual=problem()
    lower,upper,cap=.035,.09,.08
    candidates=[(p,v) for p,v in exhaustive(m,initial,actual) if search.admissible(v,lower,upper,cap)]
    budget=min(v['changed_days'] for _,v in candidates)
    allowed=search.prune(m,search.forward(m,initial,actual,budget),budget,lower)
    for path,v in candidates:
        if v['changed_days']!=budget: continue
        old=initial
        for t,new in enumerate(path):
            assert allowed[t,old,new]
            old=new
    assert allowed.sum()<allowed.size


def test_milp_matches_exhaustive_lexicographic_objective_and_drawdown():
    m,initial,actual=problem()
    lower,upper,cap=.035,.09,.015
    candidates=[(p,v) for p,v in exhaustive(m,initial,actual) if search.admissible(v,lower,upper,cap)]
    objective=lambda v:(v['changed_days'],v['deviation_points'],v['switches'])
    expected=min(objective(v) for _,v in candidates)
    budget=expected[0]
    allowed=search.prune(m,search.forward(m,initial,actual,budget),budget,lower)
    first=search.milp_path(m,initial,actual,budget,lower,upper,cap,allowed,time_limit=10)
    assert first['status']==0
    assert first['metrics']['deviation_points']==expected[1]
    final=search.milp_path(m,initial,actual,budget,lower,upper,cap,allowed,
        objective='switches',deviation=expected[1],incumbent=first['path'],time_limit=10)
    assert final['status']==0
    assert objective(final['metrics'])==expected
    assert search.admissible(final['metrics'],lower,upper,cap)


def test_fixed_deployment_and_initial_holding_cannot_be_changed():
    m,initial,actual=problem()
    m[0,:,1:]=-np.inf
    budgets=search.forward(m,initial,actual,3)
    for k in range(4):
        assert budgets.path(k)[0]==0
    assert not search.prune(m,budgets,2,.035)[0,:,1:].any()


def test_time_limit_without_incumbent_is_not_infeasibility(monkeypatch):
    from scipy import optimize
    m,initial,actual=problem()
    monkeypatch.setattr(optimize,'milp',lambda *a,**kw:SimpleNamespace(
        status=1,message='Time limit',x=None,fun=None))
    result=search.milp_path(m,initial,actual,2,.035,.09,.08,np.isfinite(m))
    assert result['status']==1 and result['path'] is None
    assert result['dual_bound'] is None


def test_solver_target_violation_cannot_be_reported_as_a_solution(monkeypatch):
    from scipy import optimize
    m,initial,actual=problem()
    def bad_solver(c,**kwargs):
        x=np.zeros(len(c))
        x[np.arange(len(m))*9]=1  # A connected zero-exposure path misses target.
        return SimpleNamespace(status=0,message='fake optimum',x=x,fun=0.)
    monkeypatch.setattr(optimize,'milp',bad_solver)
    with pytest.raises(ValueError,match='constraint replay'):
        search.milp_path(m,initial,actual,0,.035,.09,.08,np.isfinite(m))


def test_invalid_or_fractional_action_indices_refuse():
    m,initial,actual=problem()
    with pytest.raises(ValueError,match='exact grid'):
        search.forward(m,initial,[.5]*len(m),3)
    with pytest.raises(ValueError,match='budget problem'):
        search.forward(m,initial,actual,len(m)+1)


def test_turnover_and_deviation_are_different_objectives():
    m,initial,actual=problem()
    values=search.path_metrics(m,initial,actual,[0,1,1,0,0,0])
    assert values['changed_days']==2
    assert values['deviation_points']==110
    assert values['switches']==2


def test_target_boundary_is_not_tightened_excluding_a_closer_solution():
    m=np.array([[[0.,.04,.08]]*3])
    result=search.milp_path(m,0,[0],1,.04,.09,.01,np.isfinite(m))
    assert result['status']==0
    assert result['path']==[1]
    assert result['metrics']['deviation_points']==55
