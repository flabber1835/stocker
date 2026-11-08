"""Financial replay origin, unchanged bodies, exact bounds and role refusals."""
from copy import deepcopy
import importlib
from pathlib import Path

import pytest

import core_volatility_control_replay as replay
from core_volatility_job import require_continuation_stage
from research.capital_risk.forecast_tests.test_core_volatility import test_constructor_and_actual_inspector_on_inert_docker_dto as constructor_canary


def parent():
    return {'sha256': replay.PARENT, 'completed': 21, 'source_cursor': '2018-01-31',
            'run': {'state': {'wealth_core': {'episodes': {}}, 'pending': []}}}


def test_replay_reuses_exact_source_function_bodies_with_financial_own_scope():
    for model in replay.MODELS:
        original = importlib.import_module(replay.SOURCES[model][0])
        prepare, observe = replay.entrypoints(model)
        assert prepare.__code__.co_code == original.prepare.__code__.co_code
        assert observe.__code__.co_code == original.observer.__code__.co_code
        guard = prepare.__globals__[replay.SOURCES[model][2]]
        assert guard(parent(), 'CONTROL') == []
        with pytest.raises(ValueError):
            guard(parent(), 'VOL075')


@pytest.mark.parametrize('field', ('outer', 'count', 'date', 'owned', 'pending'))
@pytest.mark.parametrize('model', replay.MODELS)
def test_wrong_or_foreign_replay_predecessor_refuses(model, field):
    cp = parent()
    if field == 'outer': cp['sha256'] = '0'*64
    elif field == 'count': cp['completed'] = 29
    elif field == 'date': cp['source_cursor'] = '2018-02-12'
    elif field == 'owned': cp['run']['state']['wealth_core']['episodes']['0'] = {'security_id': replay.SOURCES[model][3]}
    else: cp['run']['state']['pending'] = [{'security_id': replay.SOURCES[model][3]}]
    with pytest.raises(ValueError):
        replay.own_scope(cp, 'CONTROL', model)


@pytest.mark.parametrize('review', (False, True))
def test_actual_control_replay_entrypoint_is_inspected(monkeypatch, review):
    constructor_canary(monkeypatch, 'CONTROL', review, True, False, control_replay=True, maximum=1621)


def test_final_positive_bound_requires_complete_exact_axis():
    request = {'maximum': 514, 'parents': {'CONTROL': {'completed': 1642}}}
    receipt = {'worker': {'exit_code': 0}, 'reviewer': {'exit_code': 0}, 'status': 'COMPLETE_ARM_REVIEWED_PENDING_ARTIFACT_ADMISSION'}
    outcome = {'completed': 2156, 'complete': True, 'session': '2026-07-31'}
    require_continuation_stage(request, receipt, outcome, 'CONTROL')
    for field, value in (('completed', 2155), ('complete', False), ('session', '2026-07-30')):
        with pytest.raises(ValueError):
            require_continuation_stage(request, receipt, dict(outcome, **{field: value}), 'CONTROL')
    with pytest.raises(ValueError):
        require_continuation_stage(request, dict(receipt, status='PARTIAL_ARM_REVIEWED_PENDING_ARTIFACT_ADMISSION'), outcome, 'CONTROL')


def test_replay_count_origin_is_own_selected_history_not_later_reference():
    request = {'stage': 'OWN_CONTROL_INPUT_REPLAY', 'maximum': 1621, 'parents': {'CONTROL': {'completed': 1642}},
               'selected_history': {'completed': 21, 'outer_sha256': replay.PARENT}}
    receipt = {'worker': {'exit_code': 0}, 'reviewer': {'exit_code': 0}, 'status': 'PARTIAL_ARM_REVIEWED_PENDING_ARTIFACT_ADMISSION'}
    outcome = {'completed': 1642, 'complete': False, 'session': '2024-07-12', 'input_alignment_replay': True,
               'selected_financial_parent_sha256': replay.PARENT, 'common_models': list(replay.MODELS), 'diagnostic_book_authority_used': False}
    require_continuation_stage(request, receipt, outcome, 'CONTROL')
    with pytest.raises(ValueError):
        require_continuation_stage(request, receipt, dict(outcome, completed=3263), 'CONTROL')
    with pytest.raises(ValueError, match='EXACT_SHARED_INPUT_FINANCIAL_REPLAY'):
        require_continuation_stage(request, receipt, dict(outcome, diagnostic_book_authority_used=True), 'CONTROL')


def test_replay_financial_calls_stay_hosted(monkeypatch):
    monkeypatch.setenv('FULL_SYSTEM_HOSTED', '1')
    with pytest.raises(ValueError, match='HOSTED_CORE_ONLY'):
        replay.run(Path('/previous'), 'CONTROL', 1621)
