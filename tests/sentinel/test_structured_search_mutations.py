"""Observe the research falsifiers fail under isolated in-memory faults."""
from pathlib import Path
import runpy

import numpy as np
import pytest
from _pytest.outcomes import Failed

from research.structured_search import audit, data as D, engine, models, policies, protocol

CHECKS=runpy.run_path(str(Path(__file__).with_name('test_structured_search.py')))


@pytest.mark.parametrize('fault',[
    'same_close_execution','new_exposure_owns_gap','future_label','global_scaler',
    'drawdown_cap_removed','selection_unfrozen','native_zero_removed',
    'warning_never_expires','confirmation_removed','account_feedback','training_boundary_removed'])
def test_each_fault_is_detected_by_its_behavioral_falsifier(fault,monkeypatch,tmp_path):
    args=[]
    if fault=='same_close_execution':
        monkeypatch.setattr(D,'apply',lambda decision,days:D.action_indices(decision[1:]))
        test='test_next_open_alignment_and_first_funding_are_fixed'
    elif fault=='new_exposure_owns_gap':
        monkeypatch.setattr(D,'returns',lambda matrix,actions,initial:matrix[np.arange(len(matrix)),actions,actions])
        test='test_return_owns_old_overnight_and_preserves_fold_continuity'
    elif fault=='future_label':
        original=D.labels
        monkeypatch.setattr(D,'labels',lambda *a:(original(*a)[0]+1,original(*a)[1]))
        test='test_labels_exclude_first_overnight_and_purge_every_future_outcome'
    elif fault=='global_scaler':
        original=models.fit
        def broken(x,days,p,cutoff):
            result=original(x,days,p,cutoff)
            result['xmean']=x[D.WARMUP:,result['columns']].mean(axis=0).tolist()
            return result
        monkeypatch.setattr(models,'fit',broken)
        test='test_fitted_models_use_only_purged_training_rows_and_reproduce_json'; args=['ridge']
    elif fault=='drawdown_cap_removed':
        monkeypatch.setattr(protocol,'choose',lambda records,base,family=None:max([base,*records],key=lambda r:r['metrics']['cagr']))
        test='test_selection_rejects_high_cagr_above_drawdown_cap_and_keeps_fallback'
    elif fault=='selection_unfrozen':
        monkeypatch.setattr(engine,'assert_frozen',lambda *a:None)
        test='test_outer_selection_file_mutation_is_detected'; args=[tmp_path]
    elif fault=='native_zero_removed':
        original=policies.state_path
        def broken(x,baseline,p):
            result=original(x,baseline,p); result[x[:,D.FEATURES.index('native_target')]==0]=1.
            return result
        monkeypatch.setattr(policies,'state_path',broken)
        test='test_state_family_native_zero_overrides_positive_recovery_signals'
    elif fault=='warning_never_expires':
        original=policies.state_path
        monkeypatch.setattr(policies,'state_path',lambda x,b,p:original(x,b,{**p,'expiry':0}))
        test='test_warning_expiration_clears_sticky_defense_without_future_health'
    elif fault=='confirmation_removed':
        original=policies.smooth
        monkeypatch.setattr(policies,'smooth',lambda r,b,down,up,hold:original(r,b,1,1,1))
        test='test_confirmation_and_minimum_state_duration_avoid_single_close_reversal'
    elif fault=='account_feedback':
        original=D.features
        def broken(rows):
            result=original(rows)
            result[:,0]+=np.array([float(r.get('strategy',{}).get('nav',0)) for r in rows])
            return result
        monkeypatch.setattr(D,'features',broken)
        test='test_features_are_prefix_causal_and_ignore_account_and_broker'
    else:
        monkeypatch.setattr(audit,'check_model',lambda *a:None)
        test='test_fitted_models_use_only_purged_training_rows_and_reproduce_json'; args=['ridge']
    with pytest.raises((AssertionError,Failed)):
        CHECKS[test](*args)
