"""A late worker cannot report the outcome of a reclaimed delivery attempt."""
from types import SimpleNamespace

import pytest

from sentinel import alert_service
from sentinel.automation import outbox
from sentinel.automation.model import AutomationRefused, AlertState
from tests.sentinel.test_automation_outbox import conn, pg


@pytest.mark.parametrize('result', ['success', 'failure'])
def test_old_attempt_cannot_finish_successor_even_with_same_holder(conn, result):
    outbox.enqueue(conn, idempotency_key='attempt-fence', event_type='TEST',
                   severity='CRITICAL', payload={}, max_attempts=3)
    first = outbox.claim_next(conn, holder_id='same-pid')
    conn.execute("UPDATE sentinel_alert_outbox SET delivery_expires_at=clock_timestamp()-interval '1 second'")
    conn.commit()
    second = outbox.claim_next(conn, holder_id='same-pid')
    assert second.attempt_count == first.attempt_count + 1
    with pytest.raises(AutomationRefused, match='active claim'):
        if result == 'success':
            outbox.mark_delivered(conn, alert_id=first.alert_id, holder_id='same-pid',
                                  attempt=first.attempt_count)
        else:
            outbox.mark_failed(conn, alert_id=first.alert_id, holder_id='same-pid',
                               attempt=first.attempt_count, error='late', retryable=False)
    assert outbox.load_alert(conn, first.alert_id).state is AlertState.DELIVERING
    done = outbox.mark_delivered(conn, alert_id=second.alert_id, holder_id='same-pid',
                                attempt=second.attempt_count)
    assert done.state is AlertState.DELIVERED


def test_health_incident_survives_leader_replacement(conn):
    health = SimpleNamespace(policy_state='SCHEDULER_STALLED', control_generation=1,
                             latest_cycle_id=None, latest_cycle_state=None,
                             broker_outcome_unresolved=False, leader_holder='host-a')
    first = alert_service._enqueue_health_incident(conn, health=health, max_attempts=3)
    health.leader_holder = 'host-b'
    second = alert_service._enqueue_health_incident(conn, health=health, max_attempts=3)
    assert first.alert_id == second.alert_id

__all__ = ['conn', 'pg']
