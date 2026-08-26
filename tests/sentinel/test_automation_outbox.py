from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from sentinel import alert_health, schema
from sentinel.automation import outbox
from sentinel.automation.model import (
    AckState,
    AlertState,
    AutomationRefused,
    ImmutableAlertChanged,
)
from sentinel.feed import store as feed_store
from tests.support.postgres import _EphemeralPostgres


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:                                  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    connection = feed_store.connect(pg.sync_dsn)
    with connection.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    connection.commit()
    schema.ensure_schema(connection)
    yield connection
    connection.close()


def test_enqueue_is_idempotent_and_content_immutable(conn) -> None:
    first = outbox.enqueue(
        conn, idempotency_key="cycle-a:kill", event_type="KILL_ENGAGED",
        severity="CRITICAL", payload={"generation": 7})
    duplicate = outbox.enqueue(
        conn, idempotency_key="cycle-a:kill", event_type="KILL_ENGAGED",
        severity="CRITICAL", payload={"generation": 7})

    assert duplicate == first
    with pytest.raises(ImmutableAlertChanged):
        outbox.enqueue(
            conn, idempotency_key="cycle-a:kill", event_type="KILL_ENGAGED",
            severity="CRITICAL", payload={"generation": 8})
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_alert_outbox")
        assert cur.fetchone()[0] == 1


def test_alert_adapters_come_from_an_explicit_registry() -> None:
    adapter = outbox.LogAlertAdapter()
    registry = outbox.AlertAdapterRegistry({"log": adapter})

    assert registry.get("log") is adapter
    with pytest.raises(AutomationRefused, match="explicit registry"):
        registry.get("environment.import.path")


def test_retry_backoff_dead_letter_and_ack_are_durable(conn) -> None:
    alert = outbox.enqueue(
        conn, idempotency_key="retry-me", event_type="BROKER_UNKNOWN",
        severity="CRITICAL", payload={"client_key": "k"}, max_attempts=2)
    first = outbox.claim_next(conn, holder_id="alerter", claim_seconds=30)
    assert first is not None
    assert first.alert_id == alert.alert_id
    assert first.state is AlertState.DELIVERING
    assert first.attempt_count == 1

    retry = outbox.mark_failed(
        conn, alert_id=alert.alert_id, holder_id="alerter",
        error="temporary adapter outage", retry_base_seconds=10,
        retry_max_seconds=60)
    assert retry.state is AlertState.PENDING
    with conn.cursor() as cur:
        cur.execute(
            "SELECT next_attempt_at > clock_timestamp()+INTERVAL '9 seconds'"
            " FROM sentinel_alert_outbox WHERE alert_id=%s", (alert.alert_id,))
        assert cur.fetchone()[0] is True
        cur.execute(
            "UPDATE sentinel_alert_outbox SET"
            " next_attempt_at=clock_timestamp()-INTERVAL '1 second'"
            " WHERE alert_id=%s", (alert.alert_id,))
    conn.commit()

    second = outbox.claim_next(conn, holder_id="alerter", claim_seconds=30)
    assert second is not None and second.attempt_count == 2
    dead = outbox.mark_failed(
        conn, alert_id=alert.alert_id, holder_id="alerter",
        error="still unavailable", retry_base_seconds=10,
        retry_max_seconds=60)
    assert dead.state is AlertState.DEAD_LETTER

    acknowledged = outbox.acknowledge(
        conn, alert_id=alert.alert_id, actor="operator",
        acknowledgement="investigating adapter")
    assert acknowledged.ack_state is AckState.ACKNOWLEDGED
    assert outbox.acknowledge(
        conn, alert_id=alert.alert_id, actor="operator",
        acknowledgement="investigating adapter") == acknowledged

    with conn.cursor() as cur:
        cur.execute(
            "SELECT action FROM sentinel_alert_delivery_events"
            " WHERE alert_id=%s ORDER BY seq", (alert.alert_id,))
        assert [row[0] for row in cur.fetchall()] == [
            "CLAIMED", "RETRY_SCHEDULED", "CLAIMED", "DEAD_LETTERED"]


def test_expired_delivery_claim_is_recovered_with_same_idempotency_key(conn) -> None:
    alert = outbox.enqueue(
        conn, idempotency_key="stable-remote-key", event_type="LEASE_LOST",
        severity="ERROR", payload={"fence": 4})
    first = outbox.claim_next(conn, holder_id="dead-worker", claim_seconds=30)
    assert first is not None
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_alert_outbox SET"
            " delivery_expires_at=clock_timestamp()-INTERVAL '1 second'"
            " WHERE alert_id=%s", (alert.alert_id,))
    conn.commit()

    recovered = outbox.claim_next(
        conn, holder_id="replacement", claim_seconds=30)

    assert recovered is not None
    assert recovered.idempotency_key == "stable-remote-key"
    assert recovered.attempt_count == 2
    assert recovered.delivery_holder == "replacement"


def test_repeated_crash_after_claim_dead_letters_at_max_attempts(conn) -> None:
    alert = outbox.enqueue(
        conn, idempotency_key="crash-after-every-claim",
        event_type="AUTOMATION_BLOCKED", severity="CRITICAL", payload={},
        max_attempts=2)

    first = outbox.claim_next(
        conn, holder_id="crashed-first", claim_seconds=30)
    assert first is not None and first.attempt_count == 1
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_alert_outbox SET"
            " delivery_expires_at=clock_timestamp()-INTERVAL '1 second'"
            " WHERE alert_id=%s", (alert.alert_id,))
    conn.commit()

    second = outbox.claim_next(
        conn, holder_id="crashed-second", claim_seconds=30)
    assert second is not None and second.attempt_count == 2
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_alert_outbox SET"
            " delivery_expires_at=clock_timestamp()-INTERVAL '1 second'"
            " WHERE alert_id=%s", (alert.alert_id,))
    conn.commit()

    assert outbox.claim_next(
        conn, holder_id="must-not-receive-third", claim_seconds=30) is None
    exhausted = outbox.load_alert(conn, alert.alert_id)
    assert exhausted.state is AlertState.DEAD_LETTER
    assert exhausted.attempt_count == 2
    assert exhausted.delivery_holder is None
    assert exhausted.last_error == "delivery claim expired at maximum attempts"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT action FROM sentinel_alert_delivery_events"
            " WHERE alert_id=%s ORDER BY seq", (alert.alert_id,))
        assert [row[0] for row in cur.fetchall()] == [
            "CLAIMED", "RETRY_SCHEDULED", "CLAIMED", "DEAD_LETTERED"]


def test_concurrent_claimers_receive_distinct_alerts(conn, pg) -> None:
    for key in ("concurrent-a", "concurrent-b"):
        outbox.enqueue(
            conn, idempotency_key=key, event_type="TEST", severity="INFO",
            payload={"key": key})
    start = threading.Barrier(2)

    def claim(holder):
        worker = feed_store.connect(pg.sync_dsn)
        try:
            start.wait(timeout=10)
            claimed = outbox.claim_next(
                worker, holder_id=holder, claim_seconds=30)
            assert claimed is not None
            return claimed.alert_id
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = {
            future.result(timeout=30)
            for future in [
                pool.submit(claim, "alerter-a"),
                pool.submit(claim, "alerter-b"),
            ]
        }
    assert len(claimed) == 2


@pytest.mark.asyncio
async def test_dispatch_operates_while_fresh_automation_is_killed(conn) -> None:
    delivered = []

    class MemoryAdapter:
        async def deliver(self, alert, idempotency_key):
            delivered.append((alert.event_type, idempotency_key))

    alert = outbox.enqueue(
        conn, idempotency_key="disabled-alert", event_type="CERT_EXPIRED",
        severity="CRITICAL", payload={"certificate": "x"})

    result = await outbox.dispatch_once(
        conn, adapter=MemoryAdapter(), holder_id="alert-worker")

    assert result.delivered
    assert result.alert is not None
    assert result.alert.state is AlertState.DELIVERED
    assert delivered == [("CERT_EXPIRED", alert.idempotency_key)]


@pytest.mark.asyncio
async def test_dispatch_failure_is_committed_not_lost(conn) -> None:
    class BrokenAdapter:
        def deliver(self, alert, idempotency_key):
            raise TimeoutError("remote outcome unavailable")

    outbox.enqueue(
        conn, idempotency_key="one-shot", event_type="AUTOMATION_BLOCKED",
        severity="ERROR", payload={}, max_attempts=1)

    result = await outbox.dispatch_once(
        conn, adapter=BrokenAdapter(), holder_id="alert-worker")

    assert result.dead_lettered
    assert "TimeoutError" in result.error


@pytest.mark.asyncio
async def test_terminal_transport_failure_dead_letters_without_retry(conn) -> None:
    class TerminalFailure(RuntimeError):
        retryable = False

    class RejectedAdapter:
        def deliver(self, alert, idempotency_key):
            raise TerminalFailure("webhook credentials rejected")

    outbox.enqueue(
        conn, idempotency_key="terminal-webhook", event_type="TEST",
        severity="CRITICAL", payload={}, max_attempts=8)

    result = await outbox.dispatch_once(
        conn, adapter=RejectedAdapter(), holder_id="alert-worker")

    assert result.dead_lettered
    assert result.alert is not None
    assert result.alert.attempt_count == 1
    assert "webhook credentials rejected" in result.error


def test_dispatcher_health_transitions_and_recovers_durably(conn) -> None:
    starting = alert_health.register(conn, dispatcher_id="primary")
    assert starting.state == alert_health.STARTING

    healthy = alert_health.record_success(conn, dispatcher_id="primary")
    assert healthy.state == alert_health.HEALTHY
    assert healthy.consecutive_failures == 0

    degraded = alert_health.record_failure(
        conn, dispatcher_id="primary", error="timeout",
        maximum_failures=2)
    assert degraded.state == alert_health.DEGRADED
    failed = alert_health.record_failure(
        conn, dispatcher_id="primary", error="timeout again",
        maximum_failures=2)
    assert failed.state == alert_health.FAILED

    recovered = alert_health.record_success(conn, dispatcher_id="primary")
    assert recovered.state == alert_health.HEALTHY
    assert recovered.consecutive_failures == 0
    assert recovered.last_error is None


def test_dispatcher_health_fails_on_stale_heartbeat_and_dead_letter(conn) -> None:
    alert_health.register(conn, dispatcher_id="primary")
    alert_health.record_success(conn, dispatcher_id="primary")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_alert_dispatcher_health SET"
            " heartbeat_at=clock_timestamp()-INTERVAL '2 minutes'"
            " WHERE dispatcher_id='primary'")
    conn.commit()
    with pytest.raises(alert_health.AlertDispatcherUnhealthy, match="stale"):
        alert_health.require_healthy(
            conn, dispatcher_id="primary", maximum_age_seconds=30,
            startup_grace_seconds=300)

    alert_health.record_success(conn, dispatcher_id="primary")
    outbox.enqueue(
        conn, idempotency_key="dead-letter-health", event_type="TEST",
        severity="CRITICAL", payload={}, max_attempts=1)
    claimed = outbox.claim_next(
        conn, holder_id="alert-worker", claim_seconds=30)
    assert claimed is not None
    outbox.mark_failed(
        conn, alert_id=claimed.alert_id, holder_id="alert-worker",
        error="terminal", retryable=False)
    with pytest.raises(alert_health.AlertDispatcherUnhealthy,
                       match="dead-letter"):
        alert_health.require_healthy(
            conn, dispatcher_id="primary", maximum_age_seconds=30,
            startup_grace_seconds=300)
