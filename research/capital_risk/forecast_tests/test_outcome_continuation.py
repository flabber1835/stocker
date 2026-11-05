"""Metadata, dependency and visitor checks; no controller or financial execution."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import system_campaign_outcome_archive as archive
import system_campaign_outcome_basis as basis
import system_campaign_outcome_frame as frame
import system_campaign_outcome_review as review
import system_campaign_outcome_sensor as sensor


def parent_fixture(refined=False):
    rows = [dict(session='2023-07-28', retained=1), dict(session='2023-07-31', retained=2)]
    raw = b''.join((json.dumps(r) + '\n').encode() for r in [*rows, dict(session='2023-08-01', unsent=True)])
    cp = dict(sha256='1' * 64, source_cursor='2023-07-31')
    proof = dict(schema='research.joint-leadership-uncertainty-independent-review/' + ('2' if refined else '1'),
        checkpoint_sha256=cp['sha256'], through=cp['source_cursor'], rows=2,
        every_actual_comparison_invariant=not refined,
        every_committed_watch_and_financial_row_bound=True, every_discrete_controller_state_equal=True,
        every_new_abiomed_before_and_after_position_and_intent_checked=True,
        every_new_chinook_before_and_after_position_and_intent_checked=True,
        no_owned_cvr_accounting_supported=True,
        abiomed_event_resolution={'retained': True})
    model = None
    if refined:
        model = SimpleNamespace(sha256='2' * 64, source_evidence=[SimpleNamespace(
            reference='research:system-optimization-002/controller-outcome/certificate-adapter/1',
            sha256=sensor.sha(Path(sensor.__file__).read_bytes()))])
        proof.update(every_complete_controller_result_equal=True, proof_mode=sensor.MODE,
                     proof_input_sha256=model.sha256)
    spec = dict(outer_sha256=cp['sha256'], selected_session=cp['source_cursor'], parent_certificate_rows=2)
    return rows, cp, raw, proof, spec, model


def admit(parts):
    rows, cp, raw, proof, spec, model = parts
    proofraw = json.dumps(proof).encode()
    spec = {**spec, 'interval_review_sha256': sensor.sha(proofraw)}
    return sensor.require_parent(rows, cp, raw, proofraw, spec, model)


def test_original_parent_and_typed_outcome_parent_keep_truthful_distinct_claims():
    first = admit(parent_fixture())
    second = admit(parent_fixture(True))
    assert first['every_actual_parent_comparison_invariant'] is True
    assert second['every_actual_parent_comparison_invariant'] is False
    assert second['parent_proof_mode'] == 'EXPLICIT_COMPLETE_OUTCOME_PROOF'
    assert first['rows'] == second['rows'] == 2


@pytest.mark.parametrize('change', ['missing_model', 'false_result', 'owned_scope', 'wrong_input', 'wrong_source',
                                  'wrong_cp', 'unsent_seed', 'dropped_seed'])
def test_refined_parent_requires_every_exact_binding(change):
    parts = parent_fixture(True)
    rows, cp, raw, proof, spec, model = parts
    if change == 'missing_model': parts = (*parts[:-1], None)
    elif change == 'false_result': proof['every_complete_controller_result_equal'] = False
    elif change == 'owned_scope': proof['no_owned_cvr_accounting_supported'] = False
    elif change == 'wrong_input': proof['proof_input_sha256'] = '3' * 64
    elif change == 'wrong_source': model.source_evidence[0].sha256 = '3' * 64
    elif change == 'wrong_cp': cp['sha256'] = '3' * 64
    elif change == 'unsent_seed': rows.append(json.loads(raw.splitlines()[-1]))
    else: rows.pop(0)
    with pytest.raises(ValueError, match='OUTCOME'):
        admit(parts)


def test_actual_exact_seed_guard_removal_falsifier():
    parts = parent_fixture()
    parts[0][0]['retained'] = 999
    rows, cp, raw, proof, spec, _ = parts
    proofraw = json.dumps(proof).encode()
    spec['interval_review_sha256'] = sensor.sha(proofraw)
    tree = ast.parse(Path(sensor.__file__).read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'require_parent']
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant)
                      and a.value == 'OUTCOME_EXACT_COMPLETE_PARENT_SEED_WITHOUT_UNSENT_TAIL'
                      for a in n.value.args)]
    fn.body.remove(guard)
    namespace = dict(vars(sensor))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-parent-seed-guard-removal>', 'exec'), namespace)
    with pytest.raises(ValueError):
        sensor.require_parent(rows, cp, raw, proofraw, spec)
    assert namespace['require_parent'](rows, cp, raw, proofraw, spec)['rows'] == 2


def test_schema_two_requires_model_and_never_relabels_original_rows():
    model = SimpleNamespace(sha256='1' * 64, first_affected_session='2023-08-01')
    row = dict(schema=archive.SCHEMA, session='2023-08-01', proof_mode=sensor.MODE,
        proof_input_sha256=model.sha256, complete_recovery_inputs={}, comparisons=dict(
            schema='research.complete-controller-outcome-proof/1', all_complete_results_equal=True))
    assert archive.row_schema(row, model)
    with pytest.raises(ValueError): archive.row_schema(row, None)
    changed = {**row, 'schema': archive.original.SCHEMA}
    with pytest.raises(ValueError, match='NOT_RELABELED'): archive.row_schema(changed, model)


def test_actual_frame_dependency_parser_refuses_a_new_history_read():
    contract = json.loads((Path(frame.__file__).parent / 'system-campaign-outcome-refinement-contract.json').read_bytes())
    source = Path(__file__).resolve().parents[3] / 'sentinel/controller/champion.py'
    raw = source.read_bytes()
    assert frame.recover_dependencies(raw) == contract['frame_dependencies']
    changed = raw.replace(b'result = deepcopy(validate(state))',
                          b"history_read = state['witness_nav'][-1]\n    result = deepcopy(validate(state))")
    assert changed != raw
    with pytest.raises(ValueError, match='DECLARED_LOGICAL_FIELDS'):
        frame.recover_dependencies(changed)


def test_frame_copy_refuses_unchanged_target_with_changed_history():
    before = dict(version=2, episode=False, last_session='2023-08-01', witness_nav=[1., 2.])
    after = {**before, 'episode': True}
    assert frame.frame_copy(before, after)
    after['witness_nav'] = [1., 3.]
    with pytest.raises(ValueError, match='FRAME_FIELDS_COPIED'):
        frame.frame_copy(before, after)


def test_reviewer_compiles_only_declared_sites_without_executing_controller():
    model = SimpleNamespace(sha256='1' * 64)
    compiled = review.compile_review(model, {'declared': 'metadata-only'})
    names = set(compiled.__code__.co_names)
    assert {'parent_admitted', 'recovery_inputs', 'comparison_count', 'comparison_invariance'} <= names
    assert 'fresh' not in names
    # The old certificate chain seed is unchanged even when the row schema changes.
    assert archive.original.SCHEMA == 'research.leadership-uncertainty-certificate/1'


def test_only_exact_lineage_removed_from_new_common_model():
    value = dict(predecessor_checkpoint_sha256='1' * 64, parent_outer_sha256='2' * 64,
        parent_file_sha256='3' * 64, parent_input_sha256='4' * 64, first_affected_session='2023-08-01',
        schema='research.controller-outcome-refinement-input/1', max_nodes=127, proof_mode=sensor.MODE)
    model = SimpleNamespace(model_dump=lambda **_: deepcopy(value))
    before = dict(schema='old', factual_semantics={'unchanged': True}, model_semantics=[{'old': 'retained'}])
    after = deepcopy(before)
    after['schema'] = 'research.system-campaign-common-controller-outcome-basis/1'
    after['model_semantics'].append({k: v for k, v in value.items() if k not in basis.common_semantics.__globals__['LINEAGE_FIELDS']})
    assert basis.require_exact_delta(before, after, model)
    after['model_semantics'][0]['old'] = 'changed'
    with pytest.raises(ValueError, match='FIVE_EVENT_SEMANTICS_UNCHANGED'):
        basis.require_exact_delta(before, after, model)
