"""Complete financial transports grant only recorded-report review; DATA only."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_partial as p
import system_campaign_financial_resume as m


def target():
    return deepcopy(json.loads((m.HERE / m.PARTIALS).read_bytes())['arms']['P10'])


def checkpoint(spec):
    return dict(schema='research.pooled-vacancy-backtest/1', sha256=spec['outer_sha256'],
        source_cursor=spec['selected_session'], completed=spec['measured_closes'],
        base=deepcopy(spec['base']), journals=deepcopy(spec['journals']), repairs=deepcopy(spec['repairs']),
        run=dict(checkpoint_sha256=spec['inner_sha256'], state_sha256=spec['state_sha256'],
                 input_sha256=spec['input_sha256']))


def mutated_function(module, name, label):
    fn = next(n for n in ast.parse(Path(module.__file__).read_bytes()).body
              if isinstance(n, ast.FunctionDef) and n.name == name)
    sites = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
             and any(isinstance(a, ast.Constant) and a.value == label for a in n.value.args)]
    assert len(sites) == 1
    fn.body.remove(sites[0])
    ns = dict(vars(module))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<removed-complete-reporting-guard>', 'exec'), ns)
    return ns[name]


def test_exact_complete_target_uses_own_current_seed_and_reporting_boundary(monkeypatch):
    monkeypatch.setattr(m, 'EXECUTION_MODE', 'READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION')
    monkeypatch.setattr(m, 'SELECTED_ARMS', ('P10',))
    monkeypatch.setattr(m, 'COMPLETED_ADMISSIONS', {})
    spec = target(); cp = checkpoint(spec)
    assert p.full_target(spec) is True
    assert p.reporting_seed(spec)['root_admission_sha256'] == p.ADMISSIONS['P10']
    assert m.strict_parent(cp, spec) is cp
    assert m.following_session(cp, spec, ['2026-07-30', '2026-07-31']) == '2026-08-03'
    request = m.expected_request()
    assert request['maximum_parallel_financial_workers'] == 0
    assert request['readonly_partial_review'] is True
    assert request['arms'] == ['P10']


@pytest.mark.parametrize('change', ['marker', 'count', 'date', 'format', 'status', 'authority',
                                   'stopped', 'exit', 'bool_exit', 'oom'])
def test_complete_target_wrong_axis_authority_or_stop_refuses(change):
    spec = target()
    if change == 'marker': spec['readonly_full_financial_target'] = 1
    elif change == 'count': spec['measured_closes'] = 2155
    elif change == 'date': spec['selected_session'] = '2026-07-30'
    elif change == 'format': spec['archive_format'] = p.FRESH_FORMAT
    elif change == 'status': spec['receipt_status'] = 'PARTIAL_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT'
    elif change == 'authority': spec['financial_authority'] = True
    elif change == 'stopped': spec['prior_stops']['worker']['stopped'] = False
    elif change == 'exit': spec['prior_stops']['worker']['exit_code'] = 1
    elif change == 'bool_exit': spec['prior_stops']['reviewer']['exit_code'] = False
    else: spec['prior_stops']['preflight']['oom_killed'] = True
    with pytest.raises(ValueError, match='EXPLICIT_SUCCESSFUL_COMPLETE_READONLY_TARGET'):
        p.full_target(spec)


def test_complete_target_guard_removal_accepts_failed_economic_stop():
    spec = target(); spec['prior_stops']['worker']['exit_code'] = 1
    with pytest.raises(ValueError): p.full_target(spec)
    broken = mutated_function(p, 'full_target', 'PARTIAL_ONLY_EXPLICIT_SUCCESSFUL_COMPLETE_READONLY_TARGET')
    assert broken(spec) is True


@pytest.mark.parametrize('mode', ['OWN_ADMITTED_FINANCIAL_CONTINUATION', 'READONLY_FROZEN_SOURCE_WITNESSES'])
def test_complete_target_refuses_other_execution_modes(monkeypatch, mode):
    monkeypatch.setattr(m, 'EXECUTION_MODE', mode)
    spec = target(); cp = checkpoint(spec)
    with pytest.raises(ValueError): m.strict_parent(cp, spec)
    with pytest.raises(ValueError): m.following_session(cp, spec, ['2026-07-31'])


def test_reporting_boundary_cannot_skip_a_real_session_or_extend_partial():
    spec = target(); cp = checkpoint(spec)
    with pytest.raises(ValueError): m.following_session(cp, spec, ['2026-07-31', '2026-08-03'])
    spec.pop('readonly_full_financial_target')
    with pytest.raises(ValueError): m.strict_parent(cp, spec)
    with pytest.raises(ValueError): m.following_session(cp, spec, ['2026-07-31'])


def test_economic_entry_refuses_readonly_before_reading_or_restoring_financial_state(monkeypatch):
    monkeypatch.setattr(m, 'hosted', lambda: None)
    class CrossedBoundary(Exception): pass
    class ForbiddenPath:
        def __truediv__(self, name): raise CrossedBoundary(name)
    spec = target()
    with pytest.raises(ValueError, match='ECONOMIC_ENTRY_REQUIRES_UNFINISHED_FINANCIAL_MODE'):
        m.economic(ForbiddenPath(), ForbiddenPath(), spec)
    broken = mutated_function(m, 'economic', 'RESUME_ECONOMIC_ENTRY_REQUIRES_UNFINISHED_FINANCIAL_MODE')
    with pytest.raises(CrossedBoundary): broken(ForbiddenPath(), ForbiddenPath(), spec)
