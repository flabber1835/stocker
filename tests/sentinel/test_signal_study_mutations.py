"""Deliberately break boundaries and prove the behavior tests catch them."""
import inspect
import textwrap

import pytest

from research.signal_study import extract, features, opportunities, probes, review
from research.signal_study.guard import CoreGuard
from tests.sentinel import test_signal_study as checks


def mutated(function, before, after):
    source=textwrap.dedent(inspect.getsource(function))
    assert source.count(before)==1
    namespace=dict(function.__globals__)
    exec(compile(source.replace(before,after),'<injected-signal-study-fault>','exec'),namespace)
    return namespace[function.__name__]


FAULTS = [
    (extract,'validate',"if filename!='checkpoint-'+inputs.sha(blob)+'.json.gz':",'if False:',
     checks.test_checkpoint_authentication_requires_file_state_prefix_and_cursor,()),
    (extract,'validate',"if digest(state)!=packet['state_sha256']:",'if False:',
     checks.test_checkpoint_authentication_requires_file_state_prefix_and_cursor,()),
    (extract,'validate',"if packet['outputs'].get('daily.jsonl')!=expected_prefix[cursor]:",'if False:',
     checks.test_checkpoint_authentication_requires_file_state_prefix_and_cursor,()),
    (extract,'recover',"if j>=0 and not math.isclose(float(rows[j]['core']['nav']),float(value),rel_tol=1e-12,abs_tol=1e-8):",'if False:',
     checks.test_recovery_rejects_misalignment_and_conflicts,('core',)),
    (extract,'put','if value is None: return','if value is None: value=0.',
     checks.test_recovery_maps_dates_without_backfilling_terminal_values,()),
    (extract,'put',"if key in cell and not math.isclose(cell[key],value,rel_tol=1e-12,abs_tol=1e-12):",'if False:',
     checks.test_recovery_rejects_misalignment_and_conflicts,('overlap',)),
    (features,'build','w = witness[i-40:i+1]','w = np.roll(witness,-1)[i-40:i+1]',
     checks.test_feature_prefix_causality_and_exclusion_of_account_state,()),
    (opportunities,'local_labels','override = np.r_[np.full(h, action), actions[t+h]]',
     'override = np.r_[np.full(h, action), action]',
     checks.test_local_labels_own_intraday_then_rejoin_overnight_and_both_costs,()),
    (opportunities,'decompose','math.log(float(gross/(gap*intraday)))','0.',
     checks.test_attribution_residual_reconciles_unchanged_partial_convention,()),
    (probes,'fit','scaler = StandardScaler().fit(x)','scaler = StandardScaler().fit(x+1.)',
     checks.test_frozen_models_reproduce_and_scaler_only_uses_supplied_training,('logistic',)),
    (review,'check_scalers',"if not np.allclose(scale,m['scale'],rtol=1e-10,atol=1e-12):",'if False:',
     checks.test_review_scaler_falsifier_rejects_changed_scale,()),
]


@pytest.mark.parametrize('module,name,before,after,falsifier,args',FAULTS,
                         ids=['file-hash','state-hash','prefix','history-date','missing-zero',
                              'overlap-conflict','future-feature','rejoin','allocation-residual','scaler','scale-audit'])
def test_behavior_test_detects_injected_fault(monkeypatch,module,name,before,after,falsifier,args):
    falsifier(*args)
    monkeypatch.setattr(module,name,mutated(getattr(module,name),before,after))
    with pytest.raises((AssertionError,pytest.fail.Exception)):
        falsifier(*args)


def test_core_guard_falsifier_detects_removed_guard(monkeypatch):
    checks.test_core_guard_blocks_a_transition_before_its_body(monkeypatch)
    monkeypatch.setattr(CoreGuard,'watch',lambda *args:None)
    with pytest.raises(pytest.fail.Exception):
        checks.test_core_guard_blocks_a_transition_before_its_body(monkeypatch)
