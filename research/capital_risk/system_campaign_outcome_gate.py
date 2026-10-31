"""Hosted canonical proof qualification; no financial session is advanced."""
from copy import deepcopy
import json
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import need, save
from seal import sha256_file
from system_campaign_uncertainty_math import Interval
from system_campaign_uncertainty_gate import certified_recovery as strict_recovery
import system_campaign_outcome_proof as outcome


def must_refuse(call, code):
    try:
        call()
    except ValueError as error:
        need(code in str(error), 'OUTCOME_GATE_EXPECTED_REFUSAL_' + code)
        return str(error)
    raise ValueError('REFUSED_OUTCOME_GATE_MISSING_REFUSAL_' + code)


def qualify(out, old, spec, request):
    hosted()
    from sentinel.controller import champion_config, median5
    for name, expected in request['canonical_controller_sources'].items():
        need(sha256_file(Path('/variant') / name) == expected,
             'OUTCOME_GATE_EXACT_CANONICAL_SOURCE')
    raw = (old / 'uncertainty-refusal.json').read_bytes()
    need(sha256_file(old / 'uncertainty-refusal.json') == request['actual_refusal_sha256'],
         'OUTCOME_GATE_EXACT_AUTHENTICATED_REFUSAL')
    failure = json.loads(raw)
    need(failure['session'] == '2023-08-23'
         and failure['failure'] == 'REFUSED_UNCERTAINTY_AMBIGUOUS_CONTROLLER_COMPARISON_le'
         and failure['scalar_inputs']['spy_r20'] < 0,
         'OUTCOME_GATE_ACTUAL_REFUSAL_SCOPE')
    state = median5.fresh(champion=True)
    state.update(deepcopy(failure['before']), last_session=failure['session'])
    kwargs = dict(failure['scalar_inputs'], state=state)
    bounds = {name: Interval(*pair) if pair is not None else None
              for name, pair in failure['intervals'].items()}
    original = outcome.commitment(kwargs)
    must_refuse(lambda: strict_recovery(champion_config.recover, kwargs, bounds),
                'AMBIGUOUS_CONTROLLER_COMPARISON_le')
    ordinary, proof = outcome.certified_recovery(champion_config.recover, kwargs, bounds)
    need(len(proof['leaves']) == 2 and not proof['all_individual_comparisons_invariant']
         and proof['all_complete_results_equal']
         and ordinary[0]['latched'] is False
         and ordinary[1]['desired_allocation'] == 1.0,
         'OUTCOME_GATE_ACTUAL_COMPLETE_MASKED_RESULT')
    need(outcome.commitment(kwargs) == original, 'OUTCOME_GATE_ACTUAL_INPUTS_UNCHANGED')
    save(out / 'actual-refusal-outcome-proof.json', dict(
        original_refusal_sha256=request['actual_refusal_sha256'],
        logical_state_and_scalar_inputs=kwargs, complete_canonical_result=ordinary,
        proof=proof, constructed_component_state_is_not_a_financial_checkpoint=True))

    # Controlled component counterexample: a positive SPY condition makes the
    # formerly masked comparison economically relevant. This is not market data.
    positive = deepcopy(kwargs)
    positive['spy_r20'] = 0.03
    exposure_refusal = must_refuse(lambda: outcome.certified_recovery(
        champion_config.recover, positive, bounds), 'COMPLETE_CANONICAL_RECOVERY_DIFFERS')
    guard = outcome.same_result
    try:
        outcome.same_result = lambda left, right: True
        _, removed = outcome.certified_recovery(champion_config.recover, positive, bounds)
    finally:
        outcome.same_result = guard
    need(len({leaf['complete_result_sha256'] for leaf in removed['leaves']}) == 2,
         'OUTCOME_GATE_ACTUAL_COMPLETE_RESULT_GUARD_REMOVAL_FALSIFIER')

    # Same current target is insufficient when the hidden recovery counter can
    # differ. Use the unchanged controller on an explicitly synthetic episode.
    latent = deepcopy(kwargs)
    latent['state'].update(episode=True, latched=False, full_streak=0,
                           recent_positive_streak=0, previous_native=1.0,
                           previous_desired=0.0, effective_native=1.0)
    latent.update(wc_drawdown=-0.05, recent_r20=-0.01, recent_r40=0.01,
                  spy_r20=-0.03, wc_r20=-0.02)
    latent_bounds = dict(recent_r20=Interval(-0.01, 0.01), recent_r40=Interval.point(0.01))
    latent_refusal = must_refuse(lambda: outcome.certified_recovery(
        champion_config.recover, latent, latent_bounds), 'COMPLETE_CANONICAL_RECOVERY_DIFFERS')
    endpoints = []
    for value in (-0.01, 0.01):
        endpoint = deepcopy(latent)
        endpoint['recent_r20'] = value
        endpoints.append(champion_config.recover(**endpoint))
    need(endpoints[0][1]['desired_allocation'] == endpoints[1][1]['desired_allocation']
         and not outcome.same_result(endpoints[0], endpoints[1]),
         'OUTCOME_GATE_ACTUAL_LATENT_STATE_DIFFERENCE_AT_EQUAL_TARGET')
    budget_refusal = must_refuse(lambda: outcome.certified_recovery(
        champion_config.recover, kwargs, bounds, max_nodes=1), 'BRANCH_EXPLORATION_LIMIT')
    save(out / 'canonical-outcome-qualification.json', dict(
        status='ACTUAL_CANONICAL_COMPLETE_OUTCOME_GATE_PASSED',
        actual_original_refusal_reproduced=True, actual_masked_complete_result_proved=True,
        actual_exposure_counterexample_refused=exposure_refusal,
        actual_equal_target_latent_counterexample_refused=latent_refusal,
        actual_complete_result_guard_removal_falsifier=True,
        actual_unexplored_branch_budget_refused=budget_refusal,
        actual_masked_leaf_count=len(proof['leaves']),
        complete_result_sha256=proof['ordinary_result_sha256'],
        financial_sessions_advanced=0, new_input_adopted=False,
        source_or_policy_conversion=False, point_valuation_selected=False,
        production_contacted=False))


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--spec', type=Path, required=True)
    p.add_argument('--request', type=Path, required=True)
    args = p.parse_args()
    qualify(Path('/out'), Path('/old'), json.loads(args.spec.read_bytes()),
            json.loads(args.request.read_bytes()))
