"""Delivery obligations survive outages without weakening attempt ownership."""
import asyncio
import json
import threading
from uuid import uuid4

import pytest

from sentinel.automation import outbox
from sentinel.automation.model import AlertState
from sentinel.feed import store
from sentinel.web_push import WebPushAlertAdapter
from tests.sentinel.test_operator_monitoring import (
    _add_subscription, _subscription_material, _vapid, db, issue369_pg)


def due(db, alert_id):
    db.execute("UPDATE sentinel_alert_outbox SET next_attempt_at=clock_timestamp()-interval '1 second' "
               "WHERE alert_id=%s", (alert_id,))
    db.commit()


def test_long_outage_and_repeated_worker_death_preserve_delivery_identity(db, issue369_pg):
    alert = outbox.enqueue(db, idempotency_key='prolonged-outage', event_type='AUTOMATION_RETRY',
                           severity='WARN', payload={}, max_attempts=2)
    for count in range(1, 7):
        # New connection models dispatcher restart: no in-memory retry state.
        with store.connect(issue369_pg.sync_dsn) as connection:
            claimed = outbox.claim_next(connection, holder_id='replacement', claim_seconds=60)
            assert claimed and claimed.attempt_count == count
            assert claimed.idempotency_key == alert.idempotency_key
            if count % 2:
                failed = outbox.mark_failed(connection, alert_id=alert.alert_id,
                    holder_id=claimed.delivery_holder, attempt=count, error='timeout')
                assert failed.state is AlertState.PENDING
                due(connection, alert.alert_id)
            else:
                connection.execute("UPDATE sentinel_alert_outbox SET delivery_expires_at="
                                   "clock_timestamp()-interval '1 second' WHERE alert_id=%s",
                                   (alert.alert_id,))
                connection.commit()
    final = outbox.claim_next(db, holder_id='recovered', claim_seconds=60)
    assert final and final.attempt_count == 7
    result = outbox.mark_delivered(db, alert_id=alert.alert_id,
                                 holder_id='recovered', attempt=7)
    assert result.state is AlertState.DELIVERED
    assert db.execute('SELECT COUNT(*) FROM sentinel_alert_outbox').fetchone()[0] == 1


def test_permanent_peer_cannot_discard_temporary_recipient(db, issue369_pg):
    permanent = _add_subscription(db, 'permanent-peer', material=11)
    temporary = _add_subscription(db, 'temporary-peer', material=17)
    alert = outbox.enqueue(db, idempotency_key='mixed-peer', event_type='AUTOMATION_RETRY',
                           severity='WARN', payload={}, max_attempts=1)
    calls = []
    recovered = False
    def send(endpoint, *_):
        calls.append(endpoint)
        return 403 if endpoint == permanent else 201 if recovered else 503
    adapter = WebPushAlertAdapter(connection_factory=lambda: store.connect(issue369_pg.sync_dsn),
                                  credentials=_vapid(), sender=send)
    first = asyncio.run(outbox.dispatch_once(db, adapter=adapter, holder_id='first'))
    assert first.alert.state is AlertState.PENDING
    due(db, alert.alert_id)
    recovered = True
    second = asyncio.run(outbox.dispatch_once(db, adapter=adapter, holder_id='second'))
    assert calls.count(temporary) == 2
    assert db.execute("SELECT state FROM sentinel_web_push_deliveries d JOIN "
                      "sentinel_web_push_subscriptions s USING(subscription_id) WHERE s.endpoint=%s",
                      (temporary,)).fetchone()[0] == 'DELIVERED'
    # Successful delivery to one peer does not hide the permanent failure.
    assert second.dead_lettered


@pytest.mark.parametrize('state', ['CORRUPT', 'UNCERTIFIABLE_OBSERVATIONS'])
def test_missing_authority_flags_cannot_silence_integrity_alarm(db, state):
    from sentinel import alert_service
    from sentinel.automation.health import AutomationHealth
    health = AutomationHealth(healthy=False, installed=True, operational_ready=False,
                              policy_state=state)
    assert alert_service._active_incident(health)
    alert = alert_service._enqueue_health_incident(db, health=health, max_attempts=8)
    assert alert.severity == 'CRITICAL' and alert.payload['reason'] == state
    assert not alert_service._active_incident(health.model_copy(update={
        'policy_state': 'NOT_INSTALLED', 'installed': False}))


def test_health_recurrence_survives_restart_without_duplicate_active_alert(db, issue369_pg):
    from sentinel import alert_service
    from sentinel.automation.health import AutomationHealth
    red = AutomationHealth(healthy=True, installed=True, operational_ready=False,
                           enabled=True, kill_switch_engaged=False, control_generation=7,
                           policy_state='SCHEDULER_STALLED')
    first = alert_service._observe_health(db, health=red, max_attempts=8)
    with store.connect(issue369_pg.sync_dsn) as restarted:
        repeated = alert_service._observe_health(restarted, health=red, max_attempts=8)
        assert repeated.alert_id == first.alert_id
        unknown = red.model_copy(update={'healthy': False, 'policy_state': 'NOT_INSTALLED'})
        alert_service._observe_health(restarted, health=unknown, max_attempts=8)
        assert alert_service._observe_health(restarted, health=red, max_attempts=8).alert_id == first.alert_id
        green = red.model_copy(update={'operational_ready': True, 'policy_state': 'LEADER_ACTIVE'})
        assert alert_service._observe_health(restarted, health=green, max_attempts=8) is None
    with store.connect(issue369_pg.sync_dsn) as restarted:
        recurrence = alert_service._observe_health(restarted, health=red, max_attempts=8)
        assert recurrence.alert_id != first.alert_id
        assert recurrence.payload == first.payload
        assert alert_service._observe_health(restarted, health=red, max_attempts=8).alert_id == recurrence.alert_id
    assert db.execute("SELECT count(*) FROM sentinel_alert_outbox WHERE event_type='AUTOMATION_OPERATIONAL_RED'").fetchone()[0] == 2


@pytest.mark.parametrize('committed', [False, True])
def test_health_occurrence_and_alert_recover_atomic_commit(db, monkeypatch, committed):
    from sentinel import alert_service
    from sentinel.automation.health import AutomationHealth
    red = AutomationHealth(healthy=False, installed=True, operational_ready=False, policy_state='CORRUPT')
    original = outbox.enqueue
    def interrupted(*args, **kwargs):
        if committed:
            original(*args, **kwargs)
        raise OSError('commit boundary')
    monkeypatch.setattr(outbox, 'enqueue', interrupted)
    with pytest.raises(OSError, match='commit boundary'):
        alert_service._observe_health(db, health=red, max_attempts=8)
    assert db.execute('SELECT occurrence FROM sentinel_alert_health_cursor WHERE id=1').fetchone()[0] == int(committed)
    db.rollback()
    monkeypatch.setattr(outbox, 'enqueue', original)
    alert = alert_service._observe_health(db, health=red, max_attempts=8)
    assert alert.idempotency_key == 'automation-health-occurrence:1'
    assert db.execute('SELECT count(*) FROM sentinel_alert_outbox').fetchone()[0] == 1


@pytest.mark.parametrize('damage', ['row', 'table'])
def test_notification_migration_does_not_reseed_lost_occurrence(db, damage):
    from sentinel import alert_service, schema
    from sentinel.automation.health import AutomationHealth
    red = AutomationHealth(healthy=False, installed=True, operational_ready=False, policy_state='CORRUPT')
    alert = alert_service._observe_health(db, health=red, max_attempts=8)
    db.execute('DELETE FROM sentinel_alert_health_cursor' if damage == 'row'
               else 'DROP TABLE sentinel_alert_health_cursor')
    db.commit()
    with pytest.raises(Exception, match='cursor|singleton'):
        schema.ensure_schema(db)
    db.rollback()
    assert outbox.load_alert(db, alert.alert_id).alert_id == alert.alert_id


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['enroll', 'refresh', 'remove'])
async def test_waiting_subscription_database_does_not_block_event_loop(monkeypatch, route):
    from starlette.requests import Request
    from fastapi import HTTPException
    from sentinel.panel import push_enrollment as panel
    endpoint = 'https://push.example.test/offline-database'
    p256dh, auth = _subscription_material(11)
    subscription = {'endpoint': endpoint, 'keys': {'p256dh': p256dh, 'auth': auth}}
    value = (dict(subscription, test_id=str(uuid4())) if route == 'enroll'
             else {'subscription': subscription} if route == 'refresh'
             else {'endpoint': endpoint})
    async def receive():
        return {'type': 'http.request', 'body': json.dumps(value).encode(), 'more_body': False}
    request = Request({'type': 'http', 'headers': [(b'origin', b'https://panel.example.test')]}, receive)
    monkeypatch.setenv('SENTINEL_PUBLIC_ORIGIN', 'https://panel.example.test')
    monkeypatch.setenv('SENTINEL_DATABASE_URL', 'postgresql://unused/local')
    entered, released = threading.Event(), threading.Event()
    def blocked(*_, **__):
        entered.set()
        released.wait(1)
        raise TimeoutError('local simulated database stall')
    monkeypatch.setattr(store, 'connect', blocked)
    call = asyncio.create_task(getattr(panel, route)(request))
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(.005)
        assert entered.is_set()
        # If SQL ran on the event loop, its timeout would already finish call.
        assert not call.done()
    finally:
        released.set()
        with pytest.raises(HTTPException) as failure:
            await call
        assert failure.value.status_code == 503


__all__ = ['db', 'issue369_pg']
