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


def browser(issue369_pg, monkeypatch):
    import importlib
    from starlette.testclient import TestClient
    monkeypatch.setenv('SENTINEL_DATABASE_URL', issue369_pg.sync_dsn)
    monkeypatch.setenv('SENTINEL_PUBLIC_ORIGIN', 'https://panel.example.test')
    client = TestClient(importlib.import_module('sentinel.panel.app').app)
    client.headers['Origin'] = 'https://panel.example.test'
    return client


def rotate(client, old, new, material=23):
    p256dh, auth = _subscription_material(material)
    return client.post('/push/subscriptions/refresh', json={
        'previous_endpoint': old,
        'subscription': {'endpoint': new, 'keys': {'p256dh': p256dh, 'auth': auth}}})


def push_adapter(issue369_pg, sender):
    return WebPushAlertAdapter(connection_factory=lambda: store.connect(issue369_pg.sync_dsn),
                               credentials=_vapid(), sender=sender)


@pytest.mark.parametrize('captured', [False, True])
@pytest.mark.parametrize('targeted', [False, True])
def test_pending_alert_follows_rotation_before_or_after_fanout(
        db, issue369_pg, monkeypatch, captured, targeted):
    from sentinel.web_push import subscription_id
    old = _add_subscription(db, 'rotating')
    peer = _add_subscription(db, 'peer')
    client = browser(issue369_pg, monkeypatch)
    alert = outbox.enqueue(db, idempotency_key='rotation',
        event_type='PUSH_ENROLLMENT_TEST' if targeted else 'AUTOMATION_RETRY',
        severity='INFO' if targeted else 'WARN',
        payload={'subscription_id': subscription_id(old)} if targeted else {})
    first = push_adapter(issue369_pg, lambda endpoint, *_: 503 if endpoint == old else 201)
    if captured:
        assert asyncio.run(outbox.dispatch_once(db, adapter=first, holder_id='first')).alert.state is AlertState.PENDING
        due(db, alert.alert_id)
    replacement = 'https://push.example.test/replaced'
    assert rotate(client, old, replacement).status_code == 200
    unrelated = _add_subscription(db, 'late-unrelated')
    calls = []
    result = asyncio.run(outbox.dispatch_once(db,
        adapter=push_adapter(issue369_pg, lambda endpoint, *_: calls.append(endpoint) or 201),
        holder_id='restarted'))
    assert result.delivered and result.alert.alert_id == alert.alert_id
    assert calls.count(replacement) == 1 and old not in calls and unrelated not in calls
    assert calls.count(peer) == int(not captured and not targeted)
    assert db.execute('SELECT COUNT(*) FROM sentinel_web_push_deliveries').fetchone()[0] == (1 if targeted else 2)


@pytest.mark.parametrize('status', [201, 410, 503])
@pytest.mark.parametrize('same_endpoint', [False, True])
def test_rotation_during_http_fences_old_result_and_retries_successor(
        db, issue369_pg, monkeypatch, status, same_endpoint):
    old = _add_subscription(db, 'in-flight')
    replacement = old if same_endpoint else 'https://push.example.test/in-flight-next'
    client = browser(issue369_pg, monkeypatch)
    alert = outbox.enqueue(db, idempotency_key='in-flight', event_type='AUTOMATION_RETRY',
                           severity='WARN', payload={})
    def sender(*_):
        assert rotate(client, old, replacement, material=31).status_code == 200
        return status
    result = asyncio.run(outbox.dispatch_once(db, adapter=push_adapter(issue369_pg, sender), holder_id='old'))
    assert result.alert.state is AlertState.PENDING
    assert db.execute('SELECT state,last_status_code,attempt_count FROM sentinel_web_push_deliveries').fetchall() == [('PENDING', None, 0)]
    assert db.execute('SELECT retired_at FROM sentinel_web_push_subscriptions WHERE endpoint=%s',
                      (replacement,)).fetchone() == (None,)
    db.commit()
    due(db, alert.alert_id)
    calls = []
    final = asyncio.run(outbox.dispatch_once(db,
        adapter=push_adapter(issue369_pg, lambda endpoint, *_: calls.append(endpoint) or 201),
        holder_id='new'))
    assert final.delivered and calls == [replacement]


@pytest.mark.parametrize('same_endpoint', [False, True])
def test_explicit_removal_and_new_enrollment_cannot_inherit_pending_alert(
        db, issue369_pg, monkeypatch, same_endpoint):
    old = _add_subscription(db, 'removed')
    client = browser(issue369_pg, monkeypatch)
    alert = outbox.enqueue(db, idempotency_key='removed', event_type='AUTOMATION_RETRY',
                           severity='WARN', payload={})
    first = asyncio.run(outbox.dispatch_once(db, adapter=push_adapter(issue369_pg, lambda *_: 503), holder_id='first'))
    assert first.alert.state is AlertState.PENDING
    assert client.post('/push/subscriptions/remove', json={'endpoint': old}).status_code == 200
    new = old if same_endpoint else 'https://push.example.test/unrelated-enrollment'
    assert rotate(client, old, new).status_code == 200
    due(db, alert.alert_id)
    final = asyncio.run(outbox.dispatch_once(db,
        adapter=push_adapter(issue369_pg, lambda *_: pytest.fail('removed obligation reached new enrollment')),
        holder_id='restarted'))
    assert final.dead_lettered


def test_rotation_chain_survives_restart_and_refuses_merging_devices(db, issue369_pg, monkeypatch):
    old = _add_subscription(db, 'chain-first')
    peer = _add_subscription(db, 'chain-peer')
    client = browser(issue369_pg, monkeypatch)
    alert = outbox.enqueue(db, idempotency_key='chain', event_type='AUTOMATION_RETRY', severity='WARN', payload={})
    first = asyncio.run(outbox.dispatch_once(db,
        adapter=push_adapter(issue369_pg, lambda endpoint, *_: 201 if endpoint == peer else 503), holder_id='first'))
    assert first.alert.state is AlertState.PENDING
    second, third = 'https://push.example.test/chain-second', 'https://push.example.test/chain-third'
    assert rotate(client, old, second).status_code == 200
    assert rotate(client, old, second).status_code == 200  # lost acknowledgement
    assert rotate(client, second, third).status_code == 200
    assert rotate(client, old, second).status_code == 503  # stale predecessor request
    assert rotate(client, third, peer).status_code == 503
    due(db, alert.alert_id)
    calls = []
    final = asyncio.run(outbox.dispatch_once(db,
        adapter=push_adapter(issue369_pg, lambda endpoint, *_: calls.append(endpoint) or 201), holder_id='restarted'))
    assert final.delivered and calls == [third]


def test_recipient_schema_migration_preserves_eligibility_and_pending_evidence(db):
    from sentinel import schema
    old = _add_subscription(db, 'legacy-subscription')
    db.execute('ALTER TABLE sentinel_web_push_subscriptions DROP COLUMN eligible_from, DROP COLUMN successor_id')
    db.commit()
    with pytest.raises(schema.SchemaMigrationRefused, match='missing migration columns'):
        schema.require_runtime_schema(db)
    db.rollback()
    schema.ensure_schema(db)
    row = db.execute('SELECT created_at,eligible_from,successor_id FROM sentinel_web_push_subscriptions WHERE endpoint=%s', (old,)).fetchone()
    assert row[0] == row[1] and row[2] is None
    db.commit()
    schema.ensure_schema(db)
    assert db.execute('SELECT created_at,eligible_from,successor_id FROM sentinel_web_push_subscriptions WHERE endpoint=%s', (old,)).fetchone() == row


def test_rotation_cannot_cross_delivery_result_transaction(db, issue369_pg, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from sentinel import push_recipients
    old = _add_subscription(db, 'serialization')
    client = browser(issue369_pg, monkeypatch)
    alert = outbox.enqueue(db, idempotency_key='serialization', event_type='AUTOMATION_RETRY',
                           severity='WARN', payload={})
    entered, release, refresh_started = threading.Event(), threading.Event(), threading.Event()
    original = push_recipients.resolve
    calls = 0
    def resolve(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 2:  # after result revalidation, before durable result update
            entered.set()
            assert release.wait(2)
        return result
    monkeypatch.setattr(push_recipients, 'resolve', resolve)
    adapter = push_adapter(issue369_pg, lambda *_: 201)
    def refreshing():
        refresh_started.set()
        return rotate(client, old, 'https://push.example.test/serialized-next')
    with ThreadPoolExecutor(max_workers=2) as workers:
        delivery = workers.submit(adapter.deliver, alert, alert.idempotency_key)
        try:
            assert entered.wait(2)
            refreshed = workers.submit(refreshing)
            assert refresh_started.wait(2)
            import time
            time.sleep(.15)
            assert not refreshed.done(), 'rotation crossed an uncommitted delivery result'
        finally:
            release.set()
        delivery.result(timeout=2)
        assert refreshed.result(timeout=2).status_code == 200
    assert db.execute('SELECT state FROM sentinel_web_push_deliveries').fetchall() == [('DELIVERED',)]


def test_delivery_result_uses_enrollment_lock_order(db, issue369_pg, monkeypatch):
    import psycopg
    _add_subscription(db, 'lock-order')
    outbox.enqueue(db, idempotency_key='lock-order', event_type='AUTOMATION_RETRY',
                   severity='WARN', payload={})
    claim = outbox.claim_next(db, holder_id='dispatch', claim_seconds=60)
    original = outbox.renew_claim
    calls = 0
    def renew(connection, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:  # result commit, after the pre-HTTP renewal
            with store.connect(issue369_pg.sync_dsn) as contender:
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    contender.execute('SELECT id FROM sentinel_notification_policy WHERE id=1 FOR UPDATE NOWAIT')
                contender.rollback()
        return original(connection, **kwargs)
    monkeypatch.setattr(outbox, 'renew_claim', renew)
    push_adapter(issue369_pg, lambda *_: 201).deliver_fenced(claim, claim.idempotency_key, claim_seconds=60)
    assert calls == 2


def test_old_rotation_retry_cannot_reconnect_removed_successor(db, issue369_pg, monkeypatch):
    old = _add_subscription(db, 'old-incarnation')
    replacement = 'https://push.example.test/new-incarnation'
    client = browser(issue369_pg, monkeypatch)
    alert = outbox.enqueue(db, idempotency_key='old-incarnation', event_type='AUTOMATION_RETRY',
                           severity='WARN', payload={})
    first = asyncio.run(outbox.dispatch_once(db, adapter=push_adapter(issue369_pg, lambda *_: 503), holder_id='first'))
    assert first.alert.state is AlertState.PENDING
    assert rotate(client, old, replacement).status_code == 200
    assert client.post('/push/subscriptions/remove', json={'endpoint': replacement}).status_code == 200
    assert rotate(client, replacement, replacement, material=37).status_code == 200
    assert rotate(client, old, replacement).status_code == 503
    due(db, alert.alert_id)
    result = asyncio.run(outbox.dispatch_once(db,
        adapter=push_adapter(issue369_pg, lambda *_: pytest.fail('removed successor inherited old history')),
        holder_id='restarted'))
    assert result.dead_lettered


def test_removal_follows_current_successor_but_never_an_independent_reenrollment(
        db, issue369_pg, monkeypatch):
    old = _add_subscription(db, 'remove-root')
    middle, latest = 'https://push.example.test/remove-middle', 'https://push.example.test/remove-latest'
    client = browser(issue369_pg, monkeypatch)
    assert rotate(client, old, middle).status_code == 200
    assert rotate(client, middle, latest).status_code == 200
    assert client.post('/push/subscriptions/remove', json={'endpoint': old}).status_code == 200
    assert db.execute('SELECT retired_at IS NOT NULL FROM sentinel_web_push_subscriptions WHERE endpoint=%s', (latest,)).fetchone() == (True,)
    db.commit()
    assert rotate(client, latest, latest, material=41).status_code == 200
    assert client.post('/push/subscriptions/remove', json={'endpoint': middle}).status_code == 200
    assert db.execute('SELECT retired_at FROM sentinel_web_push_subscriptions WHERE endpoint=%s', (latest,)).fetchone() == (None,)
