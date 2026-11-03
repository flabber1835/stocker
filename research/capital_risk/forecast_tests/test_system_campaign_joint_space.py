"""Finite search coverage and immutable identities only; no market histories."""
from system_campaign_joint_space import joint_profiles,correlations,DEFAULT_CORRELATION


def test_joint_class_covers_all_marginals_and_declared_interactions():
    v=joint_profiles();rows=v['joint_profiles'];pairs={(r['controller_index'],r['correlation_index']) for r in rows}
    assert len(rows)==len(pairs)==4096 and len(v['controllers'])==256 and len(v['correlations'])==2916
    assert all((i,0) in pairs for i in range(256)) and all((0,i) in pairs for i in range(2916))
    assert sum(i>0 and j>0 for i,j in pairs)==925 and pairs!={(i,j) for i in range(256) for j in range(2916)}
    assert v['baseline_id']==rows[0]['id'] and v['correlations'][0]['parameters']==DEFAULT_CORRELATION
    assert joint_profiles()==v
