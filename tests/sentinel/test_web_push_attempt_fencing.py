"""Claim loss during HTTP cannot publish a stale per-device result."""
import pytest

from sentinel.automation import outbox
from sentinel.automation.model import AutomationRefused, AlertState
from sentinel.feed import store
from sentinel.web_push import WebPushAlertAdapter
from tests.sentinel.test_operator_monitoring import _add_subscription, _vapid, db, issue369_pg


def test_push_response_after_takeover_cannot_complete_successor(db, issue369_pg):
    _add_subscription(db, 'fenced-device')
    outbox.enqueue(db, idempotency_key='push-attempt', event_type='AUTOMATION_RETRY',
                   severity='WARN', payload={'reason': 'local fixture'})
    first = outbox.claim_next(db, holder_id='same-pid', claim_seconds=60)
    successor = []

    def sender(*_):
        db.execute("UPDATE sentinel_alert_outbox SET delivery_expires_at=clock_timestamp()-interval '1 second'")
        db.commit()
        successor.append(outbox.claim_next(db, holder_id='same-pid', claim_seconds=60))
        return 201

    adapter = WebPushAlertAdapter(connection_factory=lambda: store.connect(issue369_pg.sync_dsn),
        credentials=_vapid(), sender=sender)
    with pytest.raises(AutomationRefused, match='claim'):
        adapter.deliver_fenced(first, first.idempotency_key, claim_seconds=60)
    assert db.execute('SELECT state,last_status_code FROM sentinel_web_push_deliveries').fetchall() == [('PENDING', None)]
    assert outbox.load_alert(db, first.alert_id).state is AlertState.DELIVERING
    assert successor[0].attempt_count == first.attempt_count + 1
    db.commit()
    adapter = WebPushAlertAdapter(connection_factory=lambda: store.connect(issue369_pg.sync_dsn),
        credentials=_vapid(), sender=lambda *_: 201)
    second = successor[0]
    adapter.deliver_fenced(second, second.idempotency_key, claim_seconds=60)
    outbox.mark_delivered(db, alert_id=second.alert_id, holder_id=second.delivery_holder,
                          attempt=second.attempt_count)
    assert db.execute('SELECT state,last_status_code FROM sentinel_web_push_deliveries').fetchall() == [('DELIVERED', 201)]
    assert outbox.load_alert(db, second.alert_id).state is AlertState.DELIVERED


__all__ = ['db', 'issue369_pg']
