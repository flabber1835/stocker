"""Pure binary64/source/composition falsifiers; no financial replay or restore."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_campaign_point_growth as g
import system_campaign_financial_uncertainty as u
import system_campaign_financial_partial as p
import system_campaign_financial_resume as launcher
from system_campaign_uncertainty_math import Interval, RollingWitnessBounds, growth


def without_guard(name, code):
    fn = next(n for n in ast.parse(Path(g.__file__).read_bytes()).body
              if isinstance(n, ast.FunctionDef) and n.name == name)
    guard = next(n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and any(isinstance(v, ast.Constant) and v.value == code for v in n.value.args))
    fn.body.remove(guard)
    scope = dict(vars(g))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<removed-point-proof-guard>', 'exec'), scope)
    return scope[name]


def test_builtin_sum_differs_from_left_sum_and_matches_the_original_factor():
    values = [Interval.point(v) for v in (1e16, 1., -1e16)]
    assert growth(values).pair() == [1., 1.]
    assert g.point_growth(values).pair() == [1 + 1 / 3] * 2
    assert g.point_growth(()).pair() == [1., 1.]


def test_nonpoint_input_refuses_and_guard_removal_would_discard_uncertainty():
    values = [Interval(.1, .2)]
    with pytest.raises(ValueError, match='POINT_INPUTS_ONLY'):
        g.point_growth(values)
    assert without_guard('point_growth', 'POINT_GROWTH_POINT_INPUTS_ONLY')(values).lo == 1.1


def test_interpreter_mismatch_refuses_and_guard_removal_accepts_it(monkeypatch):
    monkeypatch.setattr(g.sys, 'version_info', (3, 11, 0))
    with pytest.raises(ValueError, match='SAME_CPYTHON312'):
        g.point_growth(())
    assert without_guard('point_growth', 'POINT_GROWTH_SAME_CPYTHON312')(()).lo == 1.


@pytest.mark.parametrize('value', [-1., 1e-310, -1e20])
def test_nonpositive_or_unsafe_factor_still_refuses(value):
    # -1 returns zero; the tiny final factor is exercised separately below.
    if value == 1e-310:
        with pytest.raises(ValueError, match='POSITIVE_NORMAL_SAFE_RANGE'):
            Interval.point(value).normal_positive()
    else:
        with pytest.raises(ValueError, match='POSITIVE_NORMAL_SAFE_RANGE'):
            g.point_growth([Interval.point(value)])


def test_absolute_nav_guard_and_frozen_math_source_remain_effective():
    bounds = RollingWitnessBounds([1.] * 41)
    with pytest.raises(ValueError, match='ACTUAL_NAV_WITHIN_BOUNDS'):
        bounds.advance(g.point_growth([Interval.point(0.)]), 1.0001)
    prior = json.loads((p.HERE / 'system-campaign-parallel-discovery-request-001.json').read_bytes())['sources']
    for name in ('system_campaign_uncertainty_math.py', 'system_campaign_uncertainty_context.py'):
        assert hashlib.sha256((p.HERE / name).read_bytes()).hexdigest() == prior[name]
    assert hashlib.sha256((p.HERE / 'system_campaign_financial_branches.py').read_bytes()).hexdigest() == u.BRANCH_SHA


@pytest.mark.parametrize('fails', [False, True])
def test_scope_changes_only_proof_growth_and_restores_on_every_exit(fails):
    import system_campaign_uncertainty_context as context
    import system_campaign_financial_branches as branches
    before = (context.growth, branches.growth, context.RollingWitnessBounds, branches.cloud)
    raw = b'synthetic exact source'
    try:
        with g.point_growth_scope(raw, hashlib.sha256(raw).hexdigest()):
            assert context.growth is branches.growth is g.point_growth
            assert (context.RollingWitnessBounds, branches.cloud) == before[2:]
            if fails:
                raise RuntimeError('synthetic failure')
    except RuntimeError:
        assert fails
    assert (context.growth, branches.growth, context.RollingWitnessBounds, branches.cloud) == before


def test_source_mismatch_refuses_before_composition():
    import system_campaign_uncertainty_context as context
    original = context.growth
    with pytest.raises(ValueError, match='EXACT_WITNESS_SOURCE'):
        with g.point_growth_scope(b'changed source', '0' * 64):
            pytest.fail('mismatched source installed')
    assert context.growth is original


def test_source_guard_removal_falsifier():
    weakened = without_guard('point_growth_scope', 'POINT_GROWTH_EXACT_WITNESS_SOURCE')
    with weakened(b'changed source', '0' * 64):
        pass


def parent():
    spec = p.root_spec('P07')
    cp = dict(sha256=spec['outer_sha256'], completed=spec['measured_closes'],
              source_cursor=spec['selected_session'], base=deepcopy(spec['base']),
              repairs=deepcopy(spec['repairs']), run=dict(input_sha256=spec['input_sha256']))
    return cp, spec


def without_integration_guard(name, code):
    fn = next(n for n in ast.parse(Path(u.__file__).read_bytes()).body
              if isinstance(n, ast.FunctionDef) and n.name == name)
    guard = next(n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and any(isinstance(v, ast.Constant) and v.value == code for v in n.value.args))
    fn.body.remove(guard)
    scope = dict(vars(u))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<removed-point-integration-guard>', 'exec'), scope)
    return scope[name]


def test_registered_phase_guard_removal_falsifier():
    cp, spec = parent()
    other = dict(spec, root_admission_sha256='0' * 64)
    with pytest.raises(ValueError, match='EXACT_REGISTERED_PHASE'):
        u.unchanged_input_receipt(cp, other)
    assert without_integration_guard('unchanged_input_receipt', 'FINANCIAL_NO_NEW_INPUT_EXACT_REGISTERED_PHASE')(cp, other)['new_factual_overlay'] is False


def test_inherited_input_guard_removal_falsifier(tmp_path):
    cp, spec = parent()
    current = deepcopy(cp)
    current['run']['input_sha256'] = '0' * 64
    destination = tmp_path / u.UNCHANGED_INPUT
    destination.parent.mkdir()
    destination.write_bytes((json.dumps(u.unchanged_input_receipt(cp, spec), sort_keys=True, indent=2) + '\n').encode())
    with pytest.raises(ValueError, match='EXACT_UNCHANGED_INPUT'):
        u.review_unchanged_input(cp, current, tmp_path, spec)
    without_integration_guard('review_unchanged_input', 'FINANCIAL_RETAINED_PROOF_EXACT_UNCHANGED_INPUT')(cp, current, tmp_path, spec)


def test_checkpoint_witness_guard_removal_falsifier(tmp_path, monkeypatch):
    raw = b'synthetic frozen witness'
    expected = hashlib.sha256(raw).hexdigest()
    path = tmp_path / 'sentinel/controller/median5.py'
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    cp, spec = parent()
    cp['base']['sources']['sentinel/controller/median5.py'] = '0' * 64
    monkeypatch.setattr(u, 'POINT_WITNESS_SHA', expected)
    monkeypatch.setattr(u, 'Path', lambda value: tmp_path)
    weakened = without_integration_guard('proof_scope', 'FINANCIAL_POINT_PROOF_SAME_FROZEN_WITNESS')
    with pytest.raises(ValueError, match='SAME_FROZEN_WITNESS'):
        u.proof_scope(cp, spec)
    with weakened(cp, spec):
        pass


def test_only_current_registered_root_uses_point_returns_and_no_new_input():
    cp, spec = parent()
    assert u.point_return_phase(spec) and not launcher.factual_overlay_needed(spec)
    assert cp['base']['sources']['sentinel/controller/median5.py'] == u.POINT_WITNESS_SHA
    old = p.root_spec('P07', '2293655ea9e4c520c66e016a33c9d33b78f12ceb09c50a371bc84b76c0eef543')
    assert not u.point_return_phase(old) and launcher.factual_overlay_needed(old)
    with pytest.raises(ValueError, match='EXACT_REGISTERED_PHASE'):
        u.unchanged_input_receipt(cp, old)


@pytest.mark.parametrize('change', [None, 'receipt', 'input', 'repairs', 'base', 'adoption', 'overlay'])
def test_unchanged_input_review_refuses_any_changed_input_or_new_adoption(tmp_path, change):
    cp, spec = parent()
    current = deepcopy(cp)
    receipt = u.unchanged_input_receipt(cp, spec)
    if change == 'receipt':
        receipt['new_factual_overlay'] = True
    elif change == 'input':
        current['run']['input_sha256'] = '0' * 64
    elif change == 'repairs':
        current['repairs'] = []
    elif change == 'base':
        current['base']['capital'] = '50001'
    elif change == 'adoption':
        (tmp_path / u.MODEL_ADOPTION).mkdir()
    elif change == 'overlay':
        (tmp_path / 'future-financial-overlay.json').write_bytes(b'{}')
    destination = tmp_path / u.UNCHANGED_INPUT
    destination.parent.mkdir(exist_ok=True)
    destination.write_bytes((json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode())
    if change is None:
        u.review_unchanged_input(cp, current, tmp_path, spec)
    else:
        with pytest.raises(ValueError, match='EXACT_UNCHANGED_INPUT'):
            u.review_unchanged_input(cp, current, tmp_path, spec)


def test_four_real_new_certificate_counterexamples_use_builtin_semantics():
    path = Path('C:/Users/mbron/.codex/visualizations/2026/11/03/01a1a1b6-c8b7-7800-b947-f49191928329/p07-point-growth-analysis-20261104-148/analysis.json')
    if not path.exists():
        pytest.skip('authenticated DATA arithmetic fixture is local-only')
    facts = json.loads(path.read_bytes())
    assert len(facts['counterexamples']) == 4
    assert facts['exact_frozen_witness_sha256'] == u.POINT_WITNESS_SHA
    for row in facts['counterexamples']:
        values = [Interval.point(v) for v in row['rounded_returns']]
        assert g.point_growth(values).pair() == [row['python312_builtin_factor']] * 2
        assert growth(values).lo == row['left_factor'] != row['python312_builtin_factor']
