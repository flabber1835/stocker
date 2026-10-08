"""Run reviewed input-policy mutations in memory; never edit production files."""
import inspect
import json
from textwrap import dedent
from types import FunctionType
from unittest.mock import patch

from _pytest.outcomes import Failed

from tests.sentinel import test_current_window_guards as checks
from sentinel.feed.source_authority.coverage import SeedCoverageAccumulator
from sentinel.core import window_continuity
from sentinel import observation_startup
from stock_strategy_shared.wealth_core.feed import Feed


def rewritten(function, old, new):
    source = dedent(inspect.getsource(function))
    if old not in source:
        raise ValueError('mutation seam disappeared')
    scope = dict(function.__globals__)
    exec(compile(source.replace(old, new, 1), '<current-window-mutant>', 'exec'), scope)
    mutant = FunctionType(scope[function.__name__].__code__, function.__globals__,
                          function.__name__, function.__defaults__)
    mutant.__kwdefaults__ = function.__kwdefaults__
    return mutant


def run():
    cases = [
        ('partial_export', SeedCoverageAccumulator, 'require_complete',
         'material_loss = current_window and len(observed) * 100 < len(expected) * 99',
         'material_loss = False', lambda: checks.test_partial_export_and_legacy_gaps_refuse(2, True)),
        ('state_binding', checks, 'install', 'material.prior_state_sha256 != prior.state_hash', 'False',
         lambda: checks.test_window_install_refuses_unbound_or_inconsistent_inputs('state')),
        ('feature_binding', checks, 'install', "proof.get('features_sha256') != material.sha256", 'False',
         lambda: checks.test_window_install_refuses_unbound_or_inconsistent_inputs('features')),
        ('history_owner', checks, 'require_history_compatible',
         'checked.prior_state_sha256 != prior_state_sha256', 'False',
         checks.test_window_continuity_cannot_skip_or_replace_prior_state),
        ('candidate_gap', checks, 'feature', 'valid = contiguous and all(positive(c) for c in closes)',
         'valid = all(positive(c) for c in closes)',
         checks.test_gap_excludes_candidate_until_127_consecutive_closes_return),
        ('retained_cash', window_continuity, 'protected_economics',
         "if evidence != {'actions': events(current), 'distributions': distributions(current)}:",
         'if False:', checks.test_late_cash_is_forward_input_while_structural_history_still_refuses),
        ('adjacent_index', Feed, 'advance', "if self.median5_state['last_index'] != idx - 1:",
         'if False:', checks.test_snapshot_feature_override_cannot_skip_an_index),
        ('fresh_startup', observation_startup, 'require',
         "or warmup.get('warmup_sessions') != feature_sessions(WINDOW_SCHEMA)", 'or False',
         lambda: checks.test_observation_authority_requires_selected_fresh_window('warmup_count')),
    ]
    results = []
    for name, owner, attribute, old, new, test in cases:
        test()
        with patch.object(owner, attribute, rewritten(getattr(owner, attribute), old, new)):
            try:
                test()
            except (AssertionError, Failed):
                caught = True
            else:
                caught = False
        results.append(dict(name=name, caught=caught))
        print(json.dumps(results[-1]), flush=True)
    return all(item['caught'] for item in results)


if __name__ == '__main__':
    raise SystemExit(0 if run() else 1)
