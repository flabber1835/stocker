"""Pure resolved-parent admission; never initialize or run a controller locally."""
import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest

import system_campaign_spring2023_sensor as sensor


def fixture():
    seed = [dict(session='2023-03-30', math={'retained': 1}),
            dict(session='2023-03-31', math={'retained': 2})]
    tail = dict(session='2023-04-03', math={'uncommitted': 3})
    raw = b''.join((json.dumps(r) + '\n').encode() for r in [*seed, tail])
    cp = dict(sha256='1' * 64, source_cursor='2023-03-31')
    proof = dict(checkpoint_sha256=cp['sha256'], through=cp['source_cursor'], rows=2,
        every_actual_comparison_invariant=True, every_committed_watch_and_financial_row_bound=True,
        every_discrete_controller_state_equal=True, every_new_abiomed_before_and_after_position_and_intent_checked=True,
        abiomed_event_resolution={'actual': 'retained'})
    proofraw = json.dumps(proof).encode()
    spec = dict(interval_review_sha256=sensor.sha(proofraw), outer_sha256=cp['sha256'],
                selected_session=cp['source_cursor'], parent_certificate_rows=2)
    return seed, cp, raw, proofraw, spec


def test_exact_committed_seed_admits_and_keeps_unsent_tail_separate():
    seed, cp, raw, proof, spec = fixture()
    before = deepcopy(seed)
    result = sensor.require_committed_parent(seed, cp, raw, proof, spec)
    assert result['rows'] == 2 and result['through'] == '2023-03-31'
    assert seed == before and result['full_parent_certificate_sha256'] == sensor.sha(raw)


@pytest.mark.parametrize('change', ['seed_math', 'unsent_row', 'drop_row', 'different_cp', 'different_proof', 'date_before_event'])
def test_seed_or_parent_mismatch_refuses(change):
    seed, cp, raw, proof, spec = fixture()
    if change == 'seed_math': seed[-1]['math']['retained'] = 99
    elif change == 'unsent_row': seed.append(json.loads(raw.splitlines()[-1]))
    elif change == 'drop_row': seed.pop(0)
    elif change == 'different_cp': cp['sha256'] = '2' * 64
    elif change == 'different_proof': proof += b' '
    else: cp['source_cursor'] = '2022-11-30'
    with pytest.raises(ValueError, match='SPRING2023'):
        sensor.require_committed_parent(seed, cp, raw, proof, spec)


def test_no_numerical_witness_recovery_position_or_journal_method_is_overridden():
    for name in ('__enter__', 'witness', 'values', 'recover', 'advance', 'relevant', 'append'):
        assert getattr(sensor.SensorCertificate, name) is getattr(sensor.original.SensorCertificate, name)
    assert set(sensor.SensorCertificate.__dict__) - {'__module__', '__doc__'} == {'__init__'}


def test_actual_seed_guard_removal_falsifier():
    seed, cp, raw, proof, spec = fixture()
    seed[0]['math']['retained'] = 999
    tree = ast.parse(Path(sensor.__file__).read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'require_committed_parent']
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant) and a.value == 'SPRING2023_EXACT_COMPLETE_COMMITTED_PARENT_SEED_NO_UNSENT_ROWS'
                      for a in n.value.args)]
    fn.body.remove(guard)
    namespace = dict(vars(sensor))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-exact-parent-seed-guard-removed>', 'exec'), namespace)
    with pytest.raises(ValueError):
        sensor.require_committed_parent(seed, cp, raw, proof, spec)
    assert namespace['require_committed_parent'](seed, cp, raw, proof, spec)['rows'] == 2
