"""The new basis may change only the declared ordinary cash facts."""
from copy import deepcopy
import ast
from pathlib import Path

import pytest

from system_campaign_spring2023_basis import require_exact_delta, digest
import system_campaign_spring2023_basis as basis


def fixture():
    fact = dict(suppress=[], add=[], declared_fact_compilers={'old': '1' * 64}, other='retained')
    before = dict(schema='retained-four-model-schema', factual_semantics=fact,
                  factual_semantics_sha256=digest(fact), model_semantics=[{'id': str(n)} for n in range(4)],
                  price_or_probability_estimate_selected=False, independent_uncertainty_assumption=False)
    term = dict(security_id='NEW', native_session='2023-04-27', native_term_sha256='2' * 64,
                added=dict(session='2023-04-28', security_id='NEW', cash_per_share=20.))
    cat = dict(terms=[term], commitment_group={'reference_stem': 'new/'})
    refs = {'new/' + k: str(i) * 64 for i, k in enumerate(('catalog', 'loader', 'private'), 3)}
    after = deepcopy(before)
    after['factual_semantics']['suppress'] = [dict(session='2023-04-27', security_id='NEW', term_sha256='2' * 64)]
    after['factual_semantics']['add'] = [deepcopy(term['added'])]
    after['factual_semantics']['declared_fact_compilers'].update(refs)
    after['factual_semantics_sha256'] = digest(after['factual_semantics'])
    return before, after, cat, refs


def test_exact_declared_delta_passes_without_mutating_the_parent():
    before, after, cat, refs = fixture()
    original = deepcopy(before)
    assert require_exact_delta(before, after, cat, refs)
    assert before == original


@pytest.mark.parametrize('change', ['cash', 'date', 'model', 'old_fact', 'probability', 'missing_private'])
def test_economic_model_or_evidence_changes_are_not_normalized_away(change):
    before, after, cat, refs = fixture()
    if change == 'cash': after['factual_semantics']['add'][0]['cash_per_share'] += .01
    elif change == 'date': after['factual_semantics']['add'][0]['session'] = '2023-05-01'
    elif change == 'model': after['model_semantics'][3]['id'] = 'different'
    elif change == 'old_fact': after['factual_semantics']['other'] = 'changed'
    elif change == 'probability': after['price_or_probability_estimate_selected'] = True
    else: refs.pop('new/private')
    with pytest.raises(ValueError, match='EXACT_FACTUAL_DELTA|THREE_NEW_UNREDEFINED'):
        require_exact_delta(before, after, cat, refs)


def test_actual_exact_delta_guard_removal_falsifier():
    before, after, cat, refs = fixture()
    after['factual_semantics']['add'][0]['cash_per_share'] += .01
    tree = ast.parse(Path(basis.__file__).read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'require_exact_delta']
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant) and a.value == 'SPRING2023_EXACT_FACTUAL_DELTA_ALL_FOUR_MODEL_SEMANTICS_UNCHANGED'
                      for a in n.value.args)]
    fn.body.remove(guard)
    namespace = dict(vars(basis))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-economic-delta-guard-removed>', 'exec'), namespace)
    with pytest.raises(ValueError):
        require_exact_delta(before, after, cat, refs)
    assert namespace['require_exact_delta'](before, after, cat, refs)
