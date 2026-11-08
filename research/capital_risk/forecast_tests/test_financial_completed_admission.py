"""Completed scoring authority cannot become continuation authority; JSON only."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_partial as p
import system_campaign_financial_resume as m


def entry():
    return deepcopy(json.loads((p.HERE/p.ROOTS).read_bytes())['completed_financial_roots']['P10'])


@pytest.mark.parametrize('arm,prior_count', [('P00',1883),('P04',1970),('P10',1592)])
def test_completed_result_is_scoring_only_and_old_continuation_root_is_preserved(arm,prior_count):
    value = p.completed_result(arm)
    assert value['full_financial_validation_completed'] is value['performance_scoring_authorized'] is True
    assert value['financial_continuation_authorized'] is False
    assert value['completed'] == 2156 and value['total_monthly_reports'] == 103
    assert p.root_spec(arm)['measured_closes'] == prior_count
    assert value['parent_root_admission_sha256'] == p.ADMISSIONS[arm]
    if arm == 'P00':
        assert value['initial_empty_origin_verified'] is True
        assert value['historical_p00_state_or_returns_reused'] is False
        assert value['initial_formation_records'] == 126


@pytest.mark.parametrize('arm', ['P00','P04','P10'])
@pytest.mark.parametrize('field', ['readonly_run_id','new_daily_records'])
def test_each_completed_result_requires_its_own_clock_and_suffix_counts(monkeypatch,arm,field):
    value=deepcopy(json.loads((p.HERE/p.ROOTS).read_bytes())['completed_financial_roots'][arm])
    value['admission'][field] += 1
    value['admission_sha256']=p.sha((json.dumps(value['admission'],indent=2,sort_keys=True)+'\n').encode())
    monkeypatch.setitem(p.COMPLETED_ADMISSIONS,arm,value['admission_sha256'])
    with pytest.raises(ValueError,match='COMPLETE_RESEARCH_SCORING_ONLY_SCOPE'):
        p.authorized_completion(value,arm)


@pytest.mark.parametrize('change', ['score', 'continue', 'count', 'root', 'gzip', 'source', 'cipher', 'tail', 'clock', 'transport_authority'])
def test_wrong_complete_result_or_transport_refuses(change):
    value = entry(); a, t = value['admission'], value['transport']
    if change == 'score': a['performance_scoring_authorized'] = False
    elif change == 'continue': a['financial_continuation_authorized'] = True
    elif change == 'count': t['measured_closes'] = 2155
    elif change == 'root': t['monthly_seed_root_admission_sha256'] = '0'*64
    elif change == 'gzip': t['selected_file']['sha256'] = '0'*64
    elif change == 'source': t['base']['sources'][next(iter(t['base']['sources']))] = '0'*64
    elif change == 'cipher': t['encrypted_output']['sha256'] = '0'*64
    elif change == 'tail': a['empty_uncommitted_tails_verified'] = False
    elif change == 'clock': a['readonly_run_id'] = 0
    else: t['financial_authority'] = True
    with pytest.raises(ValueError): p.authorized_completion(value, 'P10')


def test_actual_scoring_scope_guard_removal_accepts_forbidden_continuation(monkeypatch):
    value = entry(); a = value['admission']; a['financial_continuation_authorized'] = True
    value['admission_sha256'] = p.sha((json.dumps(a, indent=2, sort_keys=True, allow_nan=False)+'\n').encode())
    monkeypatch.setattr(p, 'COMPLETED_ADMISSIONS', {'P10': value['admission_sha256']})
    with pytest.raises(ValueError): p.authorized_completion(value, 'P10')
    fn = next(n for n in ast.parse(Path(p.__file__).read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name == 'authorized_completion')
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant) and a.value == 'FINANCIAL_COMPLETE_RESEARCH_SCORING_ONLY_SCOPE' for a in n.value.args)]
    fn.body.remove(guard); ns = dict(vars(p))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-complete-scoring-only-scope>', 'exec'), ns)
    assert ns['authorized_completion'](value, 'P10')['financial_continuation_authorized'] is True


@pytest.mark.parametrize('mode', ['OWN_ADMITTED_FINANCIAL_CONTINUATION', 'READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION', 'READONLY_FROZEN_SOURCE_WITNESSES'])
@pytest.mark.parametrize('arm',['P00','P04','P10'])
def test_completed_arm_cannot_launch_again_in_any_mode(monkeypatch, mode,arm):
    monkeypatch.setattr(m, 'SELECTED_ARMS', (arm,)); monkeypatch.setattr(m, 'EXECUTION_MODE', mode)
    with pytest.raises(ValueError, match='CLOSED_COMPLETE_ARM_CANNOT_BE_REEXECUTED'): m.expected_request()


def test_removed_completed_arm_guard_reopens_a_closed_reporting_job(monkeypatch):
    monkeypatch.setattr(m, 'SELECTED_ARMS', ('P10',))
    monkeypatch.setattr(m, 'EXECUTION_MODE', 'READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION')
    with pytest.raises(ValueError): m.expected_request()
    fn = next(n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name == 'expected_request')
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant) and a.value == 'RESUME_CLOSED_COMPLETE_ARM_CANNOT_BE_REEXECUTED' for a in n.value.args)]
    fn.body.remove(guard); ns = dict(vars(m))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-closed-completed-arm-guard>', 'exec'), ns)
    assert ns['expected_request']()['arms'] == ['P10']
