"""Read-only status cannot turn an interrupted callback into completed transport."""
from datetime import datetime, timedelta, timezone

import pytest
from sentinel.panel import model

NOW = datetime(2026, 10, 12, 14, tzinfo=timezone.utc)
INTERRUPTED = {
    'from_state': 'EXECUTING', 'to_state': 'RECONCILING', 'at': NOW,
    'detail': {'failure_code': 'CallbackDeadlineExceeded',
               'failure_detail': 'EXECUTE callback exceeded bounded runtime 900s',
               'diagnostic': {'callback_failure': 'EXECUTE_TIMEOUT_REQUIRES_RECOVERY'}},
}


def transport(state, events):
    return next(row for row in model.automation_step_rows(
        installed=True, enabled=True,
        cycle={'cycle_id': 'missed', 'state': state, 'updated_at': NOW, 'clean_reconciliation_id': 24},
        events=events) if row.key == 'automation_step_transport')


@pytest.mark.parametrize('state', ['RECONCILING', 'SUPERSEDED', 'BLOCKED'])
def test_interrupted_callback_does_not_complete_order_transport(state):
    row = transport(state, [INTERRUPTED])
    assert row.status is model.FAIL
    assert row.value == 'INTERRUPTED · OUTCOME UNVERIFIED'
    assert 'CallbackDeadlineExceeded' in row.detail


def test_subsequent_successful_transport_supersedes_interruption():
    row = transport('RECONCILING', [INTERRUPTED, {
        'from_state': 'EXECUTING', 'to_state': 'RECONCILING', 'at': NOW,
        'detail': {'failure_code': None}}])
    assert row.status is model.OK and row.value == 'COMPLETE'


def test_clean_success_can_complete_transport_after_unknown_outcome():
    row = transport('SUCCEEDED', [INTERRUPTED])
    assert row.status is model.OK and row.value == 'COMPLETE'


def test_current_execution_retry_keeps_its_active_gate():
    opened = NOW.replace(hour=13, minute=30)
    observed = opened + timedelta(minutes=5)
    deadline = opened + timedelta(minutes=10)
    cycle = {'cycle_id': 'missed', 'state': 'RETRY_WAIT', 'retry_phase': 'EXECUTE',
        'updated_at': observed, 'next_wake_at': observed + timedelta(seconds=3),
        'execution_open_at': opened, 'execute_at': opened + timedelta(seconds=60),
        'execution_close_at': NOW.replace(hour=20, minute=0),
        'original_execution_deadline_at': deadline}
    row = next(row for row in model.automation_step_rows(
        installed=True, enabled=True, cycle=cycle,
        events=[{**INTERRUPTED, 'at': observed - timedelta(seconds=1)}])
        if row.key == 'automation_step_transport')
    assert row.status is model.WARN and row.value == 'READY TO CONTINUE'
    assert row.required_current and row.effective_status(observed) is model.WARN
    assert row.recovery.phase == 'CLEAN_RECOVERY_EXECUTION_WAKE'
    assert row.recovery.automatic and row.recovery.deadline == deadline
    assert row.recovery.next_attempt_at == cycle['next_wake_at']
    assert row.effective_status(deadline + timedelta(microseconds=1)) is model.FAIL
    for invalid in (None, cycle['execution_close_at']):
        unproved = next(row for row in model.automation_step_rows(
            installed=True, enabled=True, cycle={**cycle, 'original_execution_deadline_at': invalid})
            if row.key == 'automation_step_transport')
        assert unproved.required_current and unproved.effective_status(observed) is model.FAIL


def test_fresh_cohort_ready_persistence_keeps_both_panel_execution_deadlines(monkeypatch):
    from tests.sentinel.test_automation_service_fault_paths import (
        ready_cohort_recovery, run_resting_recovery,
    )

    case = ready_cohort_recovery(monkeypatch)
    record = run_resting_recovery(case).cycle
    deadline = case.service._latest_new_execution_at(case.cycle)
    assert deadline != case.completed + timedelta(minutes=10)
    cycle = {'cycle_id': record.cycle_id, 'state': record.state.value,
        'plan_id': record.plan_id, 'effective_session': str(record.effective_session),
        'updated_at': case.completed, 'next_wake_at': record.next_wake_at,
        'clean_reconciliation_id': record.last_clean_reconciliation_id,
        'failure_code': record.failure_code, 'failure_detail': record.failure_detail,
        'execution_open_at': record.execution_open_at, 'execute_at': record.execute_at,
        'execution_close_at': record.execution_close_at, **record.diagnostic}
    row = next(row for row in model.automation_step_rows(
        installed=True, enabled=True, cycle=cycle) if row.key == 'automation_step_transport')
    assert row.value == 'READY TO CONTINUE', 'fresh READY was projected as DAY observation'
    assert row.status is model.WARN and row.required_current
    assert row.recovery.phase == 'CLEAN_RECOVERY_EXECUTION_WAKE'
    assert row.recovery.automatic and row.recovery.deadline == deadline
    assert row.recovery.next_attempt_at == record.next_wake_at
    assert row.effective_status(case.completed) is model.WARN
    assert row.effective_status(deadline + timedelta(microseconds=1)) is model.FAIL

    cycle_row = model.automation_cycle_row(installed=True, enabled=True,
        cycle_id=record.cycle_id, state=record.state.value, plan_id=record.plan_id,
        effective_session=str(record.effective_session), next_wake_at=record.next_wake_at,
        clean_reconciliation_id=record.last_clean_reconciliation_id,
        failure_code=record.failure_code, failure_detail=record.failure_detail,
        retry_phase=cycle['retry_phase'], protected_day_wait=cycle.get('protected_day_wait'),
        original_execution_deadline_at=cycle['original_execution_deadline_at'],
        execution_open_at=record.execution_open_at, execute_at=record.execute_at,
        execution_close_at=record.execution_close_at, updated_at=case.completed)
    assert cycle_row.status is model.WARN and cycle_row.required_current
    assert cycle_row.recovery.phase == 'CLEAN_RECOVERY_EXECUTION_WAKE'
    assert cycle_row.recovery.automatic and cycle_row.recovery.deadline == deadline
    assert cycle_row.recovery.next_attempt_at == record.next_wake_at
    assert cycle_row.effective_status(case.completed) is model.WARN
    assert cycle_row.effective_status(deadline + timedelta(microseconds=1)) is model.FAIL
    assert 'protected_day_wait' not in record.diagnostic
    assert case.raw_ready.diagnostic['protected_day_wait'] == case.payload
    assert record.diagnostic['protected_cohort'] == case.cohort
    assert record.diagnostic['actionable_deltas'] == case.deltas


def test_removed_ready_wait_separation_is_detected_by_real_panel_projection(monkeypatch):
    import inspect
    import textwrap
    from sentinel.automation import service as service_module

    source = textwrap.dedent(inspect.getsource(service_module.AutomationService._run_recover))
    marker = 'ready_diagnostic.pop("protected_day_wait", None)'
    assert source.count(marker) == 1
    namespace = dict(vars(service_module))
    exec(compile(source.replace(marker, 'pass'), '<private-ready-wait-falsifier>', 'exec'), namespace)
    monkeypatch.setattr(service_module.AutomationService, '_run_recover', namespace['_run_recover'])
    with pytest.raises(AssertionError, match='fresh READY was projected as DAY observation'):
        test_fresh_cohort_ready_persistence_keeps_both_panel_execution_deadlines(monkeypatch)


def test_recovery_retry_does_not_complete_interrupted_transport():
    row = next(row for row in model.automation_step_rows(
        installed=True, enabled=True, cycle={
            'cycle_id': 'missed', 'state': 'RETRY_WAIT', 'retry_phase': 'RECOVER', 'updated_at': NOW},
        events=[INTERRUPTED]) if row.key == 'automation_step_transport')
    assert row.status is model.FAIL and row.value.startswith('INTERRUPTED')


def test_success_without_clean_reconciliation_cannot_clear_interruption():
    row = next(row for row in model.automation_step_rows(
        installed=True, enabled=True, cycle={
            'cycle_id': 'missed', 'state': 'SUCCEEDED', 'updated_at': NOW},
        events=[INTERRUPTED]) if row.key == 'automation_step_transport')
    assert row.status is model.FAIL and row.value.startswith('INTERRUPTED')
