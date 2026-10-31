"""Typed current-cycle preparation copy retains the original recovery bounds."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import inspect
from types import SimpleNamespace

import pytest

from sentinel.automation import closing_data_notifications
from sentinel.feed import calendar
from sentinel.panel import model, postclose_feed_wait, retry_status, sources
from sentinel.panel.render import _row_html, render
from tests.sentinel.test_panel_availability_retry import CycleRows, NOW, OPEN, WAKE, projections
from tests.sentinel.test_panel_postclose_feed_wait import facts


PUBLISHER_DEADLINE = NOW+timedelta(hours=1)


def closing_cycle(*, publisher_deadline=PUBLISHER_DEADLINE):
    opened, ended = calendar.session_window('2026-10-23')
    closed = calendar.session_window('2026-10-22')[1]
    schedule = SimpleNamespace(decision_session='2026-10-22', effective_session='2026-10-23',
        decision_close_at=closed, prepare_at=closed, execution_open_at=opened,
        execute_at=opened+timedelta(seconds=1), execution_close_at=ended)
    marker = closing_data_notifications.marker(cycle=schedule, observed_at=NOW,
        next_retry_at=WAKE, publisher_deadline_at=publisher_deadline)
    assert marker is not None
    return CycleRows(diagnostic=dict(
        exception_type=closing_data_notifications.EXCEPTION_TYPE,
        notifier_action='RETRY_SCHEDULED', next_retry_at=WAKE.isoformat(),
        latest_failure_at=NOW.isoformat(), closing_data_wait=marker),
        row=dict(failure_code='ClosingDataPending', prepare_at=closed,
                 execution_close_at=ended))


def test_sql_summary_step_and_source_share_typed_preparation_and_original_deadline():
    connection = closing_cycle()
    cycle, summary, steps, exposure = projections(connection)
    current = steps[1]
    assert cycle['diagnostic']['closing_data_wait']['schema'] == closing_data_notifications.SCHEMA
    assert summary.recovery == current.recovery == exposure.recovery
    assert summary.recovery.phase == 'AUTOMATION_CLOSING_DATA'
    assert summary.recovery.deadline == PUBLISHER_DEADLINE-timedelta(microseconds=1)
    assert summary.recovery.next_attempt_at == WAKE
    for row in (summary, current):
        assert row.valid_until == row.recovery.deadline
        assert row.effective_status(NOW) == model.WARN
        assert '<div class="value">Preparing closing data</div>' in _row_html(row, NOW)
        assert 'Original preparation deadline: 2026-10-22 at 04:00 PM Pacific.' in _row_html(row, NOW)
        assert row.effective_status(PUBLISHER_DEADLINE) == model.FAIL
        assert 'Preparing closing data' not in _row_html(row, PUBLISHER_DEADLINE)
        assert row.value == 'WAITING FOR INPUTS · ATTEMPT 9'
    assert projections(closing_cycle())[1].recovery == summary.recovery
    assert all('SELECT ' in sql and 'UPDATE ' not in sql for sql, _ in connection.queries)
    assert len(connection.queries) == 1
    assert projections(closing_cycle(publisher_deadline=None))[1].recovery.deadline == OPEN-timedelta(microseconds=1)


@pytest.mark.parametrize('invalid', [
    'missing_marker', 'freeform_marker', 'wrong_schema', 'wrong_exception',
    'wrong_failure', 'wrong_session', 'wrong_prepare', 'wrong_execute',
    'changed_wake', 'wrong_observation', 'changed_deadline', 'wrong_notifier', 'wrong_phase',
])
def test_unbound_or_untyped_marker_keeps_generic_availability_warning(invalid):
    connection = closing_cycle()
    cycle = sources._latest_automation_cycle(connection)
    cycle = deepcopy(cycle)
    diagnostic = cycle['diagnostic']
    marker = diagnostic['closing_data_wait']
    if invalid == 'missing_marker': diagnostic.pop('closing_data_wait')
    elif invalid == 'freeform_marker': diagnostic['closing_data_wait'] = 'closing data pending'
    elif invalid == 'wrong_schema': marker['schema'] = 'other/1'
    elif invalid == 'wrong_exception': diagnostic['exception_type'] = 'builtins.RuntimeError'
    elif invalid == 'wrong_failure': cycle['failure_code'] = 'SourceDataPending'
    elif invalid == 'wrong_session': marker['decision_session'] = '2026-10-21'
    elif invalid == 'wrong_prepare': cycle['prepare_at'] += timedelta(seconds=1)
    elif invalid == 'wrong_execute': cycle['execute_at'] += timedelta(seconds=1)
    elif invalid == 'changed_wake': cycle['next_wake_at'] += timedelta(seconds=1)
    elif invalid == 'wrong_observation': diagnostic['latest_failure_at'] = (NOW-timedelta(seconds=1)).isoformat()
    elif invalid == 'changed_deadline': marker['publisher_deadline_at'] = WAKE.isoformat()
    elif invalid == 'wrong_notifier': diagnostic['notifier_action'] = 'TERMINAL'
    elif invalid == 'wrong_phase': cycle['retry_phase'] = 'PREPARE'
    evidence = retry_status.availability_recovery(cycle)
    assert evidence.phase == f'AUTOMATION_{cycle["retry_phase"]}_AVAILABILITY', 'unproved marker earned preparation phase'
    assert evidence.deadline == OPEN-timedelta(microseconds=1)


def test_typed_cycle_and_proof_backed_authority_support_only_current_source_headline():
    _, summary, steps, _ = projections(closing_cycle())
    financial, worker = facts(now=NOW, frontier='2026-10-21', deadline=OPEN)
    authority = model.Row('authority', 'Authority', 'PASS', model.OK, 'previous saved check',
        NOW-timedelta(hours=1), required_current=True, valid_until=NOW-timedelta(seconds=1))
    control = model.Row('automation', 'Automation', 'ENABLED', model.OK)
    _, automation = postclose_feed_wait.project_progress([], [control, summary, authority],
        financial, worker, now=NOW)
    projected = next(row for row in automation if row.key == 'authority')
    assert projected.recovery.phase == 'AUTHORITY_RECHECK_AFTER_DATA'
    assert projected.recovery.deadline == summary.recovery.deadline
    page = model.Panel(rows=[*financial, worker, *automation, *steps], now=NOW)
    assert page.operational == model.WARN
    assert '>Healthy · Waiting for closing data</span>' in render(page)
    assert 'Previous PASS is not current execution authority' in render(page)
    assert '>Healthy' not in render(replace(page, now=PUBLISHER_DEADLINE))
    # A cycle marker alone cannot explain the independent source/portfolio state.
    assert '>Healthy' not in render(model.Panel(rows=automation, now=NOW))
    generic = replace(summary, recovery=replace(summary.recovery,
        phase='AUTOMATION_REFRESH_AVAILABILITY'))
    assert '>Healthy' not in render(replace(page,
        rows=[generic if row.key == 'automation_cycle' else row for row in page.rows]))


def test_removing_positive_diagnostic_validation_is_detected(monkeypatch):
    source = inspect.getsource(retry_status._closing_data_recovery)
    guard = "if not quiet_event(cycle, state=cycle.get('state')):"
    assert source.count(guard) == 1
    namespace = dict(vars(retry_status))
    exec(compile(source.replace(guard, 'if False:'), '<closing-phase-falsifier>', 'exec'), namespace)
    monkeypatch.setattr(retry_status, '_closing_data_recovery', namespace['_closing_data_recovery'])
    with pytest.raises(AssertionError, match='unproved marker'):
        test_unbound_or_untyped_marker_keeps_generic_availability_warning('wrong_notifier')
