"""A recovering scheduler is one incident until observed stable leadership."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from sentinel import alert_service
from sentinel.automation import outbox
from sentinel.automation.health import AutomationHealth
from sentinel.automation.model import AckState, AutomationRefused
from sentinel.feed import store
from tests.sentinel.test_automation_outbox import conn, pg


@pytest.fixture
def observed_clock(monkeypatch):
    # Keep real PostgreSQL row locks, commits and restart reads; only advance
    # the sampled database clock, without sleeping for the recovery interval.
    now = [datetime(2026, 10, 17, 23, 0, tzinfo=timezone.utc)]
    original = alert_service._health_cursor

    def cursor(connection):
        raw, occurrence, _database_now = original(connection)
        return raw, occurrence, now[0]

    monkeypatch.setattr(alert_service, "_health_cursor", cursor)
    return now


def _red(**updates):
    return AutomationHealth(
        healthy=True, installed=True, operational_ready=False,
        enabled=True, kill_switch_engaged=False, control_generation=7,
        policy_state="SCHEDULER_STALLED").model_copy(update=updates)


def _green(**updates):
    return _red(
        operational_ready=True, policy_state="LEADER_ACTIVE", leader_active=True,
        service_heartbeat_fresh=True, leader_holder="current-worker",
        fencing_token=13).model_copy(update=updates)


def _observe(connection, health, **kwargs):
    if health.policy_state == "LEADER_ACTIVE" and health.database_now is None:
        now = alert_service._health_cursor(connection)[2]
        health = health.model_copy(update={
            "database_now": now, "leader_expires_at": now + timedelta(seconds=12)})
    return alert_service._observe_health(
        connection, health=health, max_attempts=8, **kwargs)


def _cursor(connection):
    row = connection.execute(
        "SELECT active_identity,occurrence FROM sentinel_alert_health_cursor WHERE id=1").fetchone()
    connection.rollback()
    return (json.loads(row[0]) if row[0] else None), row[1]


def _recover_for(connection, clock, seconds, health=None, **kwargs):
    health = health or _green()
    _observe(connection, health, **kwargs)
    for _ in range(seconds // 10):
        clock[0] += timedelta(seconds=10)
        _observe(connection, health, **kwargs)


@pytest.mark.parametrize("first_reason", ["SCHEDULER_STALLED", "WAITING_FOR_LEADER"])
def test_symptom_cycle_and_holder_churn_reuse_first_immutable_alert(
        conn, pg, observed_clock, first_reason):
    first_health = _red(policy_state=first_reason, latest_cycle_id="first-cycle",
                        latest_cycle_state="WAITING_OPEN")
    first = _observe(conn, first_health)
    for index in range(4):
        with store.connect(pg.sync_dsn) as restarted:
            changed = first_health.model_copy(update={
                "policy_state": "WAITING_FOR_LEADER" if index % 2 else "SCHEDULER_STALLED",
                "latest_cycle_id": f"cycle-{index}", "latest_cycle_state": "PREPARING",
                "leader_holder": f"replacement-{index}", "fencing_token": index + 20,
            })
            observed_clock[0] += timedelta(seconds=2)
            repeated = _observe(restarted, changed)
            assert repeated.alert_id == first.alert_id
            assert repeated.payload == first.payload
            assert repeated.payload["reason"] == first_reason
            assert repeated.ack_state is AckState.UNACKNOWLEDGED
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox").fetchone()[0] == 1


def test_brief_recovery_and_unknown_observation_do_not_rearm(
        conn, observed_clock):
    first = _observe(conn, _red())
    _recover_for(conn, observed_clock, 50)
    observed_clock[0] += timedelta(seconds=2)
    _observe(conn, _red(healthy=False, policy_state="NOT_INSTALLED"))
    assert _cursor(conn)[0]["recovery"] is None
    _recover_for(conn, observed_clock, 50)
    assert _observe(conn, _red(policy_state="WAITING_FOR_LEADER")).alert_id == first.alert_id
    assert _cursor(conn)[0]["recovery"] is None


def test_sixty_seconds_of_same_fresh_leader_rearms_without_acknowledgement(
        conn, pg, observed_clock):
    first = _observe(conn, _red())
    _recover_for(conn, observed_clock, 50)
    observed_clock[0] += timedelta(seconds=9, microseconds=999999)
    _observe(conn, _green())
    assert _cursor(conn)[0] is not None  # 59.999999 seconds is still recovering.
    with store.connect(pg.sync_dsn) as restarted:
        observed_clock[0] += timedelta(microseconds=1)
        _observe(restarted, _green())
        assert _cursor(restarted)[0] is None
        recurrence = _observe(restarted, _red(policy_state="WAITING_FOR_LEADER"))
    assert recurrence.alert_id != first.alert_id
    assert outbox.load_alert(conn, first.alert_id).ack_state is AckState.UNACKNOWLEDGED
    assert recurrence.ack_state is AckState.UNACKNOWLEDGED
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox").fetchone()[0] == 2


@pytest.mark.parametrize("interruption", [
    "gap", "rollback", "holder", "fence", "not_ready", "no_lease",
    "stale_heartbeat", "read_failure", "unknown",
])
def test_recovery_requires_continuous_current_holder_evidence(
        conn, observed_clock, interruption):
    first = _observe(conn, _red())
    _recover_for(conn, observed_clock, 50)
    green = _green()
    kwargs = {}
    if interruption == "gap":
        observed_clock[0] += timedelta(seconds=11)
    elif interruption == "rollback":
        observed_clock[0] -= timedelta(seconds=1)
    else:
        observed_clock[0] += timedelta(seconds=1)
    if interruption == "holder":
        green = _green(leader_holder="different-worker")
    elif interruption == "fence":
        green = _green(fencing_token=14)
    elif interruption == "not_ready":
        green = _green(operational_ready=False)
    elif interruption == "no_lease":
        green = _green(leader_active=False)
    elif interruption == "stale_heartbeat":
        green = _green(service_heartbeat_fresh=False)
    elif interruption == "read_failure":
        kwargs["observation_interrupted"] = True
    elif interruption == "unknown":
        green = _green(healthy=False, policy_state="NOT_INSTALLED")
    _observe(conn, green, **kwargs)
    recovered = green if interruption in {"holder", "fence"} else _green()
    observed_clock[0] += timedelta(seconds=10)
    _observe(conn, recovered)
    observed_clock[0] += timedelta(seconds=1)
    _observe(conn, recovered)
    assert _cursor(conn)[0] is not None
    assert _observe(conn, _red()).alert_id == first.alert_id


def test_configured_slow_poll_has_bounded_recovery_gap(conn, observed_clock):
    _observe(conn, _red())
    _observe(conn, _green(), maximum_observation_gap_seconds=120)
    observed_clock[0] += timedelta(seconds=60)
    _observe(conn, _green(), maximum_observation_gap_seconds=120)
    assert _cursor(conn)[0] is None


def test_lock_delay_cannot_turn_expired_health_into_recovery(conn, observed_clock):
    first = _observe(conn, _red())
    _recover_for(conn, observed_clock, 50)
    health_time = observed_clock[0] + timedelta(seconds=10)
    observed_clock[0] = health_time + timedelta(seconds=13)
    stale = _green(database_now=health_time,
                   leader_expires_at=health_time + timedelta(seconds=12))
    _observe(conn, stale)
    assert _cursor(conn)[0]["recovery"] is None
    assert _observe(conn, _red()).alert_id == first.alert_id


def test_recovery_uses_original_health_time_not_later_lock_time(conn, observed_clock):
    _observe(conn, _red())
    original = observed_clock[0]
    observed_clock[0] += timedelta(seconds=4)
    fresh = _green(database_now=original,
                   leader_expires_at=original + timedelta(seconds=12))
    _observe(conn, fresh)
    recovery = _cursor(conn)[0]["recovery"]
    assert datetime.fromisoformat(recovery["started_at"]) == original


@pytest.mark.asyncio
async def test_dispatcher_start_preserves_episode_but_resets_recovery(
        conn, pg, observed_clock, monkeypatch):
    first = _observe(conn, _red())
    _recover_for(conn, observed_clock, 50)
    observed_clock[0] += timedelta(seconds=10)
    healthy = _green(database_now=observed_clock[0],
                     leader_expires_at=observed_clock[0] + timedelta(seconds=12))

    class Adapter:
        def __init__(self, *_args, **_kwargs):
            pass

        def deliver_dispatcher_probe(self, *_args):
            pass

    async def no_delivery(*_args, **_kwargs):
        return SimpleNamespace(error=None, delivered=False, alert=None)

    async def finish(stop, _seconds):
        stop.set()

    connect = store.connect
    monkeypatch.setenv("SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL",
                       "https://alerts.example.test/isolated")
    for name in ("SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY",
                 "SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY",
                 "SENTINEL_WEB_PUSH_VAPID_SUBJECT", "SENTINEL_ALERT_PROGRESS_FD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(alert_service.SentinelConfig, "from_env",
                        lambda: SimpleNamespace(database_url=pg.sync_dsn))
    monkeypatch.setattr(alert_service, "config_from_env", lambda: SimpleNamespace(
        alert_max_attempts=8, alert_claim_seconds=30,
        retry_base_seconds=1, retry_max_seconds=60))
    monkeypatch.setattr(alert_service.feed_store, "connect",
                        lambda *_args, **_kwargs: connect(pg.sync_dsn))
    monkeypatch.setattr(alert_service, "read_health", lambda _conn: healthy)
    monkeypatch.setattr(alert_service, "WebhookAlertAdapter", Adapter)
    monkeypatch.setattr(outbox, "dispatch_once", no_delivery)
    monkeypatch.setattr(alert_service, "_sleep_or_stop", finish)

    assert await alert_service.run() == 0
    episode, occurrence = _cursor(conn)
    assert episode is not None and episode["recovery"] is None
    assert occurrence == 1
    assert outbox.load_alert(conn, first.alert_id).ack_state is AckState.UNACKNOWLEDGED


@pytest.mark.parametrize("changed", [
    {"control_generation": 8}, {"broker_outcome_unresolved": 1},
    {"policy_state": "AUTHORITY_FAILED"}, {"policy_state": "AUTHORITY_INVALID"},
    {"policy_state": "SCHEDULER_OVERDUE"}, {"policy_state": "CORRUPT", "healthy": False},
    {"policy_state": "UNCERTIFIABLE_OBSERVATIONS", "healthy": False},
])
def test_independent_authority_integrity_and_broker_failures_still_notify(
        conn, observed_clock, changed):
    first = _observe(conn, _red())
    distinct = _observe(conn, _red(**changed))
    assert distinct.alert_id != first.alert_id
    assert distinct.severity == "CRITICAL"
    assert distinct.payload["reason"] == changed.get("policy_state", "SCHEDULER_STALLED")
    assert outbox.load_alert(conn, first.alert_id).ack_state is AckState.UNACKNOWLEDGED


@pytest.mark.parametrize("independent", [
    {"policy_state": "AUTHORITY_FAILED"},
    {"policy_state": "CORRUPT", "healthy": False},
    {"policy_state": "SCHEDULER_OVERDUE"},
], ids=["authority", "integrity", "overdue"])
def test_independent_failure_is_a_new_boundary_before_returning_leadership(
        conn, observed_clock, independent):
    first = _observe(conn, _red())
    observed_clock[0] += timedelta(seconds=2)
    separate = _observe(conn, _red(**independent))
    assert _observe(conn, _red(**independent)).alert_id == separate.alert_id
    observed_clock[0] += timedelta(seconds=2)
    returning = _observe(conn, _red())

    assert len({first.alert_id, separate.alert_id, returning.alert_id}) == 3
    repeated = _observe(conn, _red(policy_state="WAITING_FOR_LEADER"))
    assert repeated.alert_id == returning.alert_id
    assert repeated.payload == returning.payload
    assert repeated.payload["reason"] == "SCHEDULER_STALLED"
    for original in (first, separate, returning):
        retained = outbox.load_alert(conn, original.alert_id)
        assert retained == original
        assert retained.ack_state is AckState.UNACKNOWLEDGED
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox").fetchone()[0] == 3
    assert _cursor(conn)[1] == 3


def test_existing_cursor_reuses_existing_immutable_alert(conn, observed_clock):
    health = _red(latest_cycle_id="retained-cycle", latest_cycle_state="WAITING_OPEN")
    first = _observe(conn, health)
    legacy = outbox._json({"identity": (
        health.policy_state, health.control_generation, health.latest_cycle_id,
        health.latest_cycle_state, health.broker_outcome_unresolved)})
    conn.execute("UPDATE sentinel_alert_health_cursor SET active_identity=%s WHERE id=1",
                 (legacy,))
    conn.commit()
    repeated = _observe(conn, _red(policy_state="WAITING_FOR_LEADER"))
    assert repeated == first
    assert _cursor(conn)[1] == 1
    assert _cursor(conn)[0]["schema"] == alert_service._LEADERSHIP_EPISODE_SCHEMA


def test_malformed_recovery_cannot_erase_or_rearm_history(conn, observed_clock):
    first = _observe(conn, _red())
    state, _ = _cursor(conn)
    state["recovery"] = {"started_at": "bad-clock"}
    conn.execute("UPDATE sentinel_alert_health_cursor SET active_identity=%s WHERE id=1",
                 (outbox._json(state),))
    conn.commit()
    with pytest.raises(AutomationRefused, match="cursor is malformed"):
        _observe(conn, _green())
    assert outbox.load_alert(conn, first.alert_id).ack_state is AckState.UNACKNOWLEDGED
    assert _cursor(conn)[1] == 1


__all__ = ["conn", "pg"]
