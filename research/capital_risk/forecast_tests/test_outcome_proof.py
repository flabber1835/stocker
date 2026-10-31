"""Pure callable proof fixtures; these do not execute a canonical controller."""
from copy import deepcopy
import math

import pytest

import system_campaign_outcome_proof as proof
from system_campaign_uncertainty_math import Interval


def inputs():
    return dict(state={'latched': False, 'count': 0}, recent_r20=-0.09,
                recent_r40=-0.02, spy=-0.03)


def bounds():
    return dict(recent_r20=Interval(-0.10, -0.07), recent_r40=Interval.point(-0.02))


def masked(*, state, recent_r20, recent_r40, spy):
    if recent_r20 <= -0.085 and spy >= 0:
        state['latched'] = True
    return state, {'target': 0.55 if state['latched'] else 1.0}


def test_later_false_condition_admits_both_paths_and_preserves_all_original_inputs():
    original = inputs()
    saved = deepcopy(original)
    result, evidence = proof.certified_recovery(masked, original, bounds())
    assert original == saved and result == (saved['state'], {'target': 1.0})
    assert len(evidence['leaves']) == 2 and evidence['nodes'] == 3
    assert not evidence['all_individual_comparisons_invariant']
    assert evidence['all_complete_results_equal'] and not evidence['point_valuation_selected']
    assert {tuple(v['choices']) for v in evidence['leaves']} == {(False,), (True,)}


def test_real_exposure_difference_refuses_and_full_result_guard_removal_falsifies(monkeypatch):
    original = inputs()
    original['spy'] = 0.03
    with pytest.raises(ValueError, match='COMPLETE_CANONICAL_RECOVERY_DIFFERS'):
        proof.certified_recovery(masked, original, bounds())
    monkeypatch.setattr(proof, 'same_result', lambda a, b: True)
    _, evidence = proof.certified_recovery(masked, original, bounds())
    assert len({v['complete_result_sha256'] for v in evidence['leaves']}) == 2


def test_latent_state_difference_refuses_even_when_current_target_is_equal():
    def latent(*, state, recent_r20, **other):
        state['count'] += int(recent_r20 <= -0.085)
        return state, {'target': 1.0}

    with pytest.raises(ValueError, match='COMPLETE_CANONICAL_RECOVERY_DIFFERS'):
        proof.certified_recovery(latent, inputs(), bounds())


@pytest.mark.parametrize('budgets', [{'max_leaves': 1}, {'max_nodes': 1}, {'max_depth': 0}])
def test_incomplete_exploration_refuses(budgets):
    with pytest.raises(ValueError, match='LIMIT'):
        proof.certified_recovery(masked, inputs(), bounds(), **budgets)


def test_short_circuit_paths_have_their_own_complete_choice_sequences():
    def multiple(*, state, recent_r20, recent_r40, **other):
        if recent_r20 <= -0.085 and recent_r40 <= -0.02:
            pass
        return state, {'target': 1.0}

    intervals = bounds()
    intervals['recent_r40'] = Interval(-0.04, 0.01)
    _, evidence = proof.certified_recovery(multiple, inputs(), intervals)
    assert {tuple(v['choices']) for v in evidence['leaves']} == {
        (False,), (True, False), (True, True)}
    assert evidence['all_complete_results_equal']


def test_invariant_comparison_has_one_leaf_and_preserves_finite_checks():
    def simple(*, state, recent_r20, **other):
        assert math.isfinite(recent_r20)
        return state, {'target': 1.0 if recent_r20 < 0.0 else 0.55}

    _, evidence = proof.certified_recovery(simple, inputs(), bounds())
    assert len(evidence['leaves']) == 1 and evidence['nodes'] == 1
    assert evidence['all_individual_comparisons_invariant']


@pytest.mark.parametrize('operation', [lambda x: x + 1.0, lambda x: 1.0 / x,
    lambda x: float(x), lambda x: bool(x), lambda x: abs(x), lambda x: x == 0.0])
def test_unhandled_scalar_operations_cannot_silently_use_the_representative(operation):
    def unsafe(*, state, recent_r20, **other):
        operation(recent_r20)
        return state, {'target': 1.0}

    with pytest.raises(ValueError, match='UNSUPPORTED_BOUNDED_SCALAR_OPERATION'):
        proof.certified_recovery(unsafe, inputs(), bounds())


def test_bounded_scalar_may_not_escape_in_an_apparently_equal_result():
    def escape(*, state, recent_r20, **other):
        return state, {'target': 1.0, 'unproven_numeric_field': recent_r20}

    with pytest.raises(ValueError, match='BOUNDED_SCALAR_ESCAPED_RESULT'):
        proof.certified_recovery(escape, inputs(), bounds())


def test_original_input_mutation_refuses_even_if_every_output_matches():
    original = inputs()

    def mutate(*, state, **other):
        original['state']['count'] += 1
        return state, {'target': 1.0}

    with pytest.raises(ValueError, match='ORIGINAL_INPUT_NOT_MUTATED'):
        proof.certified_recovery(mutate, original, bounds())


def test_complete_result_equality_preserves_types_and_float_bits():
    assert not proof.same_result({'count': 1}, {'count': True})
    assert not proof.same_result({'value': -0.0}, {'value': 0.0})
    assert not proof.same_result(([1],), [[1]])
