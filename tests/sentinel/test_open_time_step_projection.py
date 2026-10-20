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
