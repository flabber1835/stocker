"""Synthetic recurrence equivalence and future-prefix causality only."""
from copy import deepcopy
import numpy as np
import pytest
from full_system_controller_vector import targets
from full_system_controller_policy import profiles


def synthetic_rows(n):
    observation={'shadow_drawdown':-.13,'shadow_r5':-.06,'shadow_r10':-.10,'shadow_r20':-.05,'shadow_r40':-.05,
        'damaged_breadth':0.,'green_breadth':0.,'damaged_breadth_delta5':None,'spy_r20':-.02,
        'spy_vol_ratio':.10,'stops20':0,'shadow_nav':50000.}
    return [{'evidence':{'observation':dict(observation),'recent_leadership':{'recent_r20':-.10,'recent_r40':-.10}}} for _ in range(n)]


def test_profile_breadth_matrix_matches_separate_scalar_equations_and_is_causal():
    rows=synthetic_rows(30);p=profiles()[0];damage=np.asarray([[0.]*6+[1.]*24,[0.]*30])
    matrix=targets(rows,[p,p],damage=damage);separate=[]
    for d in damage:
        changed=deepcopy(rows)
        for i,row in enumerate(changed):
            row['evidence']['observation'].update(damaged_breadth=float(d[i]),damaged_breadth_delta5=float(d[i]-d[i-5]) if i>=5 else None)
        separate.append(targets(changed,[p])[0])
    assert np.array_equal(matrix,np.asarray(separate)) and np.any(matrix[0]!=matrix[1])
    assert np.array_equal(targets(rows[:12],[p,p],damage=damage[:,:12]),matrix[:,:12])
    with pytest.raises(ValueError,match='BREADTH_MATRIX'):targets(rows,[p],damage=damage)
    invalid=damage.copy();invalid[0,0]=float('nan')
    with pytest.raises(ValueError,match='BREADTH_MATRIX'):targets(rows,[p,p],damage=invalid)
