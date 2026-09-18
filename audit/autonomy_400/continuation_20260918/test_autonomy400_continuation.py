"""Audit witnesses against unchanged aff4461d source.

Dependency fakes supply database rows, network statuses and time. Assertions
record baseline behavior, including defects; green is reproduction, not repair.
No database server, container, network endpoint or broker is contacted.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from sentinel import automation_supervisor as supervisor
from sentinel import web_push
from sentinel.automation import outbox
from sentinel.automation.model import AlertRecord, AlertState, AckState


class EndProbe(BaseException):
    """Terminate the synthetic supervisor after its first observed kill."""


def test_watchdog_kills_new_same_phase_callback_at_old_deadline(monkeypatch):
    # Real deployed loop and watchdog; each invocation is 300 seconds long,
    # below the deployed 900-second deadline. A two-second observer misses
    # the brief transition between consecutive invocation heartbeats.
    virtual = SimpleNamespace(now=0.0)
    observed = []
    killed = []
    child = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(supervisor, "SentinelConfig", SimpleNamespace(
        from_env=lambda: SimpleNamespace(database_url="controlled-row-fixture")))
    monkeypatch.setattr(supervisor, "config_from_env", lambda: SimpleNamespace(
        callback_deadline_seconds=900, lease_seconds=12))
    monkeypatch.setattr(supervisor, "signal", SimpleNamespace(
        SIGTERM=15, SIGINT=2, signal=lambda *_: None))
    monkeypatch.setattr(supervisor, "_holder_id", lambda: "audit-owner")
    monkeypatch.setattr(supervisor, "_spawn", lambda _holder: child)
    monkeypatch.setattr(supervisor, "time", SimpleNamespace(
        monotonic=lambda: virtual.now,
        sleep=lambda amount: setattr(virtual, "now", virtual.now + amount)))
    monkeypatch.setenv("SENTINEL_AUTOMATION_SUPERVISOR_POLL_SECONDS", "2")
    monkeypatch.setenv("SENTINEL_AUTOMATION_SUPERVISOR_STARTUP_GRACE_SECONDS", "20")

    def snapshot(_dsn, _holder):
        age = virtual.now % 300 + 0.25
        observed.append((virtual.now, age))
        return "RECOVER_CALLBACK", age

    def terminate(_child):
        killed.append((virtual.now, observed[-1][1]))
        raise EndProbe()

    monkeypatch.setattr(supervisor, "_snapshot", snapshot)
    monkeypatch.setattr(supervisor, "_terminate", terminate)
    with pytest.raises(EndProbe):
        supervisor.main()
    assert killed == [(900.0, 0.25)]
    assert len(observed) == 451
    assert max(age for _, age in observed) < 300


def test_watchdog_control_one_truly_overdue_callback_expires():
    watch = supervisor.CallbackWatch()
    assert not supervisor._callback_deadline_expired(
        watch, state="RECOVER_CALLBACK", now_monotonic=0,
        deadline_seconds=900, state_age_seconds=0)
    assert not supervisor._callback_deadline_expired(
        watch, state="RECOVER_CALLBACK", now_monotonic=900,
        deadline_seconds=900, state_age_seconds=900)
    assert supervisor._callback_deadline_expired(
        watch, state="RECOVER_CALLBACK", now_monotonic=902,
        deadline_seconds=900, state_age_seconds=902)


def test_watchdog_control_observed_intermediate_state_resets():
    watch = supervisor.CallbackWatch()
    assert not supervisor._callback_deadline_expired(
        watch, state="RECOVER_CALLBACK", now_monotonic=0,
        deadline_seconds=900, state_age_seconds=0)
    assert not supervisor._callback_deadline_expired(
        watch, state="RETRY_SCHEDULED", now_monotonic=899,
        deadline_seconds=900, state_age_seconds=0)
    assert not supervisor._callback_deadline_expired(
        watch, state="RECOVER_CALLBACK", now_monotonic=902,
        deadline_seconds=900, state_age_seconds=0.25)


class OutboxRows:
    """Minimal row emulator for actual mark_failed() SQL, not a PostgreSQL test."""
    def __init__(self, alert):
        self.alert = alert
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        if sql.startswith("UPDATE sentinel_alert_outbox SET state="):
            new_state = AlertState(params[0])
            error = params[1] if new_state is AlertState.DEAD_LETTER else params[2]
            self.alert = self.alert.model_copy(update={
                "state": new_state, "last_error": error,
                "delivery_holder": None, "delivery_expires_at": None})

    def fetchone(self):
        return self.alert.attempt_count, self.alert.max_attempts

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _alert():
    now = datetime(2026, 9, 17, tzinfo=timezone.utc)
    return AlertRecord(
        alert_id="audit-fill", idempotency_key="audit-fill-key",
        schema_version=1, event_type="BROKER_FILL", severity="TRADE",
        payload={"side": "BUY", "ticker": "SYNTH", "quantity": "1",
                 "price": "10", "filled_at": now.isoformat()},
        state=AlertState.PENDING, attempt_count=0, max_attempts=8,
        next_attempt_at=now, ack_state=AckState.UNACKNOWLEDGED,
        created_at=now, updated_at=now)


@pytest.mark.parametrize("statuses,expected", [
    ((403, 503), AlertState.DEAD_LETTER),
    ((400, 429), AlertState.DEAD_LETTER),
    ((503, 503), AlertState.PENDING),
    ((410, 503), AlertState.PENDING),
    ((201, 503), AlertState.PENDING),
])
def test_mixed_recipient_failure_controls_whole_outbox_claim(
        monkeypatch, statuses, expected):
    # Use WARN to exercise operational failure notifications.
    alert = _alert().model_copy(update={
        "event_type": "AUTOMATION_RETRY", "severity": "WARN"})
    rows = OutboxRows(alert)
    deliveries = {"device-a": "PENDING", "device-b": "PENDING"}
    responses = dict(zip(deliveries, statuses))
    sender_calls = []

    def sender(endpoint, *_):
        sub = endpoint.rsplit("/", 1)[-1]
        sender_calls.append(sub)
        return responses[sub]

    adapter = web_push.WebPushAlertAdapter(
        connection_factory=lambda: pytest.fail("unexpected database access"),
        credentials=None, sender=sender)
    monkeypatch.setattr(adapter, "_initialize_fanout", lambda _a: (2, True))
    monkeypatch.setattr(adapter, "_recipients", lambda _id: [
        (sub, f"https://push.invalid/{sub}", "fixture-key", "fixture-auth", None)
        for sub, state in deliveries.items() if state == "PENDING"])
    monkeypatch.setattr(adapter, "_record", lambda **kw: deliveries.__setitem__(
        kw["sub_id"], kw["state"]))
    monkeypatch.setattr(adapter, "_fanout_counts", lambda _id: {
        state: list(deliveries.values()).count(state)
        for state in set(deliveries.values())})
    monkeypatch.setattr(web_push, "request_parts", lambda **_: (b"fixture", {}))

    def claim(conn, **_):
        if conn.alert.state is not AlertState.PENDING:
            return None
        conn.alert = conn.alert.model_copy(update={
            "state": AlertState.DELIVERING,
            "attempt_count": conn.alert.attempt_count + 1,
            "delivery_holder": "audit-dispatcher"})
        return conn.alert

    monkeypatch.setattr(outbox, "claim_next", claim)
    monkeypatch.setattr(outbox, "load_alert", lambda conn, *_: conn.alert)
    monkeypatch.setattr(outbox, "_append_event", lambda *_, **__: None)
    def delivered(conn, **_):
        conn.alert = conn.alert.model_copy(update={"state": AlertState.DELIVERED})
        return conn.alert
    monkeypatch.setattr(outbox, "mark_delivered", delivered)

    result = asyncio.run(outbox.dispatch_once(
        rows, adapter=adapter, holder_id="audit-dispatcher"))
    assert result.alert.state is expected
    assert rows.alert.attempt_count == 1
    assert deliveries["device-b"] == "PENDING"
    assert rows.commits == 1
    assert rows.rollbacks == 0
    assert any(sql.startswith("UPDATE sentinel_alert_outbox SET state=")
               for sql, _ in rows.statements)

    # All endpoints subsequently recover. Baseline dead letters are excluded
    # by the claim seam; retained PENDING rows deliver only outstanding devices.
    responses.update({"device-a": 201, "device-b": 201})
    followup = asyncio.run(outbox.dispatch_once(
        rows, adapter=adapter, holder_id="audit-dispatcher"))
    if expected is AlertState.DEAD_LETTER:
        assert followup.alert is None
        assert deliveries["device-b"] == "PENDING"
        assert sender_calls == ["device-a", "device-b"]
    else:
        assert followup.delivered
        assert deliveries["device-b"] == "DELIVERED"
        if statuses[0] in (201, 410):
            assert sender_calls.count("device-a") == 1
        assert sender_calls.count("device-b") == 2


def test_real_service_loop_can_leave_no_pollable_gap_between_callbacks(monkeypatch):
    from sentinel.automation.service import AutomationService
    from sentinel.automation import store
    from sentinel.automation.model import TickAction, TickResult

    base = datetime(2026, 9, 17, tzinfo=timezone.utc)
    virtual = SimpleNamespace(now=base)
    sleeps = []
    states = []
    ticks_started = []
    conn = SimpleNamespace(close=lambda: None)

    async def tick(_conn, **_):
        ticks_started.append(virtual.now)
        virtual.now += timedelta(seconds=300)
        return TickResult(action=TickAction.RETRY_SCHEDULED, reason="retry")

    async def sleep(seconds):
        sleeps.append(seconds)
        virtual.now += timedelta(seconds=seconds)

    service = SimpleNamespace(
        tick=tick, terminal=None, notify=None, holder_id="audit-owner",
        config=SimpleNamespace(heartbeat_seconds=3, control_poll_seconds=3))
    monkeypatch.setattr(store, "register_instance", lambda _conn, **kw:
                        states.append((virtual.now, kw)))
    count = asyncio.run(AutomationService.run(
        service, lambda: conn, stop=asyncio.Event(),
        clock=lambda: virtual.now, sleep=sleep, max_ticks=3))
    assert count == 3
    assert sleeps == [0.0, 0.0]
    assert ticks_started == [base + timedelta(seconds=s) for s in (0, 300, 600)]
    assert all(state["state"] == "RETRY_SCHEDULED" for _, state in states)
    assert all(state["next_wake_at"] < moment for moment, state in states)


@pytest.mark.parametrize("second_cycle_id,expected_incidents", [
    ("same-cycle", 1), ("new-cycle", 2),
])
def test_health_alarm_recurrence_after_observed_recovery(
        monkeypatch, second_cycle_id, expected_incidents):
    from sentinel import alert_service
    from sentinel.automation.health import AutomationHealth
    from sentinel.automation.model import DispatchResult

    common = dict(healthy=True, installed=True, enabled=True,
                  kill_switch_engaged=False, control_generation=7,
                  latest_cycle_state="SUCCEEDED", broker_outcome_unresolved=0)
    sequence = iter([
        AutomationHealth(**common, operational_ready=False,
                         policy_state="SCHEDULER_STALLED",
                         latest_cycle_id="same-cycle"),
        AutomationHealth(**common, operational_ready=True,
                         policy_state="READY", latest_cycle_id="same-cycle"),
        AutomationHealth(**common, operational_ready=False,
                         policy_state="SCHEDULER_STALLED",
                         latest_cycle_id=second_cycle_id),
    ])
    enqueued = []
    sleeps = []
    conn = SimpleNamespace(close=lambda: None, rollback=lambda: None)
    monkeypatch.setattr(alert_service, "SentinelConfig", SimpleNamespace(
        from_env=lambda: SimpleNamespace(database_url="controlled-row-fixture")))
    monkeypatch.setattr(alert_service, "config_from_env", lambda: SimpleNamespace(
        alert_max_attempts=8, alert_claim_seconds=60,
        retry_base_seconds=5, retry_max_seconds=900))
    monkeypatch.setattr(alert_service.feed_store, "connect", lambda _: conn)
    monkeypatch.setattr(alert_service, "read_health", lambda _: next(sequence))
    monkeypatch.setattr(alert_service, "signal", SimpleNamespace())
    monkeypatch.setattr(alert_service, "WebhookAlertAdapter", lambda *_, **__:
                        SimpleNamespace(deliver_dispatcher_probe=lambda *_: None))
    for name in ("register", "heartbeat", "record_success", "record_failure"):
        monkeypatch.setattr(alert_service.alert_health, name, lambda *_, **__: None)
    monkeypatch.setenv("SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL", "https://fixture.invalid")
    for name in ("PRIVATE_KEY", "PUBLIC_KEY", "SUBJECT"):
        monkeypatch.delenv("SENTINEL_WEB_PUSH_VAPID_" + name, raising=False)
    monkeypatch.setattr(alert_service.outbox, "enqueue", lambda _conn, **kw:
                        enqueued.append(kw) or SimpleNamespace())

    async def dispatch(*_, **__):
        return DispatchResult(alert=None)

    async def sleep_or_stop(stop, seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            stop.set()

    monkeypatch.setattr(alert_service.outbox, "dispatch_once", dispatch)
    monkeypatch.setattr(alert_service, "_sleep_or_stop", sleep_or_stop)
    assert asyncio.run(alert_service.run()) == 0
    assert len(sleeps) == 3
    assert len(enqueued) == expected_incidents
    assert all(e["event_type"] == "AUTOMATION_OPERATIONAL_RED" for e in enqueued)
    assert all(e["severity"] == "CRITICAL" for e in enqueued)
    if expected_incidents == 2:
        assert enqueued[0]["idempotency_key"] != enqueued[1]["idempotency_key"]


def test_health_incident_key_does_not_include_recovered_episode(monkeypatch):
    from sentinel import alert_service
    from sentinel.automation.health import AutomationHealth
    observed = []
    monkeypatch.setattr(alert_service.outbox, "enqueue", lambda _conn, **kw:
                        observed.append(kw) or SimpleNamespace())
    base = dict(healthy=True, installed=True, operational_ready=False,
                enabled=True, kill_switch_engaged=False, control_generation=7,
                policy_state="SCHEDULER_STALLED", latest_cycle_id="same-cycle",
                latest_cycle_state="SUCCEEDED")
    for hours in (0, 12):
        health = AutomationHealth(**base, database_now=(
            datetime(2026, 9, 17, tzinfo=timezone.utc) + timedelta(hours=hours)))
        alert_service._enqueue_health_incident(None, health=health, max_attempts=8)
    assert len(observed) == 2
    assert observed[0]["idempotency_key"] == observed[1]["idempotency_key"]


class HealthEnqueueRows:
    """Emulate INSERT ... ON CONFLICT retention for real enqueue validation."""
    def __init__(self):
        self.rows = {}
        self.commits = 0
        self.rollbacks = 0
    def cursor(self):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def execute(self, sql, params):
        assert "INSERT INTO sentinel_alert_outbox" in sql
        assert "ON CONFLICT (idempotency_key) DO NOTHING" in sql
        import json
        (alert_id, key, version, event, severity, payload, maximum, wake) = params
        self.rows.setdefault(alert_id, _alert().model_copy(update={
            "alert_id": alert_id, "idempotency_key": key,
            "schema_version": version, "event_type": event,
            "severity": severity, "payload": json.loads(payload),
            "max_attempts": maximum}))
    def commit(self):
        self.commits += 1
    def rollback(self):
        self.rollbacks += 1
    def close(self):
        pass


def test_old_health_identity_with_new_leader_blocks_dispatcher(monkeypatch):
    from sentinel import alert_service
    from sentinel.automation.health import AutomationHealth
    from sentinel.automation.model import DispatchResult, ImmutableAlertChanged
    rows = HealthEnqueueRows()
    monkeypatch.setattr(outbox, "load_alert", lambda conn, alert_id: conn.rows[alert_id])
    common = dict(healthy=True, installed=True, operational_ready=False,
                  enabled=True, kill_switch_engaged=False, control_generation=7,
                  policy_state="SCHEDULER_STALLED", latest_cycle_id="same-cycle",
                  latest_cycle_state="SUCCEEDED")
    first = AutomationHealth(**common, leader_holder="owner-before-restart")
    alert_service._enqueue_health_incident(rows, health=first, max_attempts=8)
    # Unchanged evidence is correctly idempotent.
    alert_service._enqueue_health_incident(rows, health=first, max_attempts=8)
    assert len(rows.rows) == 1
    current = AutomationHealth(**common, leader_holder="owner-after-restart")
    with pytest.raises(ImmutableAlertChanged):
        alert_service._enqueue_health_incident(rows, health=current, max_attempts=8)

    monkeypatch.setattr(alert_service, "SentinelConfig", SimpleNamespace(
        from_env=lambda: SimpleNamespace(database_url="controlled-row-fixture")))
    monkeypatch.setattr(alert_service, "config_from_env", lambda: SimpleNamespace(
        alert_max_attempts=8, alert_claim_seconds=60,
        retry_base_seconds=5, retry_max_seconds=900))
    monkeypatch.setattr(alert_service.feed_store, "connect", lambda _: rows)
    monkeypatch.setattr(alert_service, "read_health", lambda _: current)
    monkeypatch.setattr(alert_service, "signal", SimpleNamespace())
    database_reports = []
    monkeypatch.setattr(alert_service, "WebhookAlertAdapter", lambda *_, **__:
        SimpleNamespace(deliver_dispatcher_probe=lambda *_: None,
                        deliver_database_failure=lambda *args: database_reports.append(args)))
    for name in ("register", "heartbeat", "record_success", "record_failure"):
        monkeypatch.setattr(alert_service.alert_health, name, lambda *_, **__: None)
    monkeypatch.setenv("SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL", "https://fixture.invalid")
    for name in ("PRIVATE_KEY", "PUBLIC_KEY", "SUBJECT"):
        monkeypatch.delenv("SENTINEL_WEB_PUSH_VAPID_" + name, raising=False)
    dispatches = []
    sleeps = []
    async def dispatch(*_, **__):
        dispatches.append(True)
        return DispatchResult(alert=None)
    async def sleep_or_stop(stop, seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            stop.set()
    monkeypatch.setattr(alert_service.outbox, "dispatch_once", dispatch)
    monkeypatch.setattr(alert_service, "_sleep_or_stop", sleep_or_stop)
    assert asyncio.run(alert_service.run()) == 0
    assert len(sleeps) == 3
    assert dispatches == []
    assert len(database_reports) == 1
    assert "ImmutableAlertChanged" in database_reports[0][0]
    assert len(rows.rows) == 1
