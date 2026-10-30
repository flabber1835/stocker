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


def _renewal_row(**changes):
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 10, 30, 8, tzinfo=timezone.utc)
    proof = dict(schema="sentinel.backup-maintenance-progress/1", attempt="a" * 32,
                 started_at=int(now.timestamp()) - 60, deadline=int(now.timestamp()) + 3540,
                 system_identifier="7691913275518591014", image="sha256:" + "d" * 64,
                 predecessor_base="base-20261029T072734Z", base_backup="base-20261029T072734Z",
                 phase="FAILED")
    proof.update(changes)
    return [proof, now, True, "7691913275518591014", now - timedelta(days=1),
            now + timedelta(seconds=1), None, None, False]


def test_backup_renewal_warning_deduplicates_the_base_not_five_minute_retry():
    first = outbox._backup_renewal_warning(_renewal_row())
    retry = outbox._backup_renewal_warning(_renewal_row(attempt="b" * 32))
    assert first["idempotency_key"] == retry["idempotency_key"]
    assert first["event_type"] == "BACKUP_RENEWAL_FAILED" and first["severity"] == "WARN"
    assert "journal" in first["payload"]["reason"]
    assert first["payload"]["attempt"] != retry["payload"]["attempt"]


@pytest.mark.parametrize("field,value", [
    ("schema", "future-schema"), ("attempt", "not-an-attempt"),
    ("phase", "BASE_BACKUP"), ("phase", "COMPLETE"),
    ("system_identifier", "7777777777777777777"), ("system_identifier", None),
    ("image", "mutable:latest"), ("predecessor_base", "../foreign"),
    ("base_backup", False), ("started_at", True), ("started_at", "1"),
    ("deadline", False), ("deadline", 0), ("deadline", 2**63),
])
def test_backup_warning_rejects_untyped_or_foreign_progress(field, value):
    assert outbox._backup_renewal_warning(_renewal_row(**{field: value})) is None


@pytest.mark.parametrize("fault", ["digest", "before-policy", "future", "extra-field", "missing-field",
                                   "no-policy", "naive-time", "not-a-document"])
def test_backup_warning_requires_authentic_current_policy_observation(fault):
    from datetime import timedelta
    row = _renewal_row()
    if fault == "digest": row[2] = False
    elif fault == "before-policy": row[4] = row[1] + timedelta(seconds=1)
    elif fault == "future": row[5] = row[1] - timedelta(seconds=1)
    elif fault == "extra-field": row[0]["unreviewed"] = True
    elif fault == "missing-field": row[0].pop("attempt")
    elif fault == "no-policy": row[4] = None
    elif fault == "naive-time": row[1] = row[1].replace(tzinfo=None)
    else: row[0] = []
    assert outbox._backup_renewal_warning(row) is None


def _verified_successor(system):
    return dict(schema="sentinel.verified-base/1", physical_verified=True,
                metadata_sha256="c" * 64, base_backup="base-20261030T080000Z",
                marker="sentinel-backup-20261030T080000Z-123", marker_lsn="0/1000000",
                marker_wal="000000010000000000000001", system_identifier=system,
                xid8_before="100", xid8_after="101")


@pytest.mark.parametrize("fault", [None, "digest", "foreign", "unverified", "untyped", "older",
                                   "incomplete", "bad-marker", "regressed-xid"])
def test_only_actual_later_verified_successor_suppresses_old_failure(fault):
    from datetime import timedelta
    row = _renewal_row()
    row[6], row[7], row[8] = _verified_successor(row[3]), row[1], True
    if fault == "digest": row[8] = False
    elif fault == "foreign": row[6]["system_identifier"] = "7777777777777777777"
    elif fault == "unverified": row[6]["physical_verified"] = False
    elif fault == "untyped": row[6]["physical_verified"] = 1
    elif fault == "older": row[7] = row[1] - timedelta(seconds=1)
    elif fault == "incomplete": row[6].pop("metadata_sha256")
    elif fault == "bad-marker": row[6]["marker"] = "unknown"
    elif fault == "regressed-xid": row[6]["xid8_after"] = "99"
    assert (outbox._backup_renewal_warning(row) is None) is (fault is None)


def test_backup_warning_foreign_system_guard_falsifier():
    import inspect
    source = inspect.getsource(outbox._backup_renewal_warning)
    guard = 'proof.get("system_identifier") != system'
    assert guard in source
    namespace = dict(vars(outbox))
    exec(compile(source.replace(guard, "False"), "removed-current-system-guard", "exec"), namespace)
    mutant = namespace["_backup_renewal_warning"]
    foreign = _renewal_row(system_identifier="7777777777777777777")
    assert outbox._backup_renewal_warning(foreign) is None
    with pytest.raises(AssertionError):
        assert mutant(foreign) is None


def _insert_backup_notice_progress(conn, *, attempt="a" * 32, phases=("BASE_BACKUP", "FAILED"),
                                   authentic=True, observed=None, **changes):
    from psycopg.types.json import Jsonb
    now, system = conn.execute("SELECT clock_timestamp(),system_identifier::text "
                               "FROM pg_control_system()").fetchone()
    observed = now if observed is None else observed
    proof = _renewal_row()[0]
    proof.update(system_identifier=system, attempt=attempt,
                 started_at=int(observed.timestamp()) - 60, deadline=int(observed.timestamp()) + 3540)
    proof.update(changes)
    for phase in phases:
        proof["phase"] = phase
        conn.execute("WITH v AS (SELECT %s::jsonb AS proof) INSERT INTO sentinel_backup_evidence "
            "(kind,evidence_sha256,proof,observed_at) SELECT 'MAINTENANCE_PROGRESS',"
            "CASE WHEN %s THEN encode(sha256(convert_to(proof::text,'UTF8')),'hex') ELSE repeat('0',64) END,"
            "proof,%s FROM v", (Jsonb(proof), authentic, observed))
    conn.commit()
    return proof


def test_real_backup_renewal_failure_reconstructed_once_across_retries_and_restart(conn):
    first = _insert_backup_notice_progress(conn)
    outbox._reconstruct_missing_transition_alerts(conn)
    conn.commit()
    _insert_backup_notice_progress(conn, attempt="b" * 32)
    for _ in range(2):
        outbox._reconstruct_missing_transition_alerts(conn)
        conn.commit()
    rows = conn.execute("SELECT event_type,severity,payload FROM sentinel_alert_outbox").fetchall()
    assert len(rows) == 1 and rows[0][:2] == ("BACKUP_RENEWAL_FAILED", "WARN")
    assert rows[0][2]["attempt"] == first["attempt"]
    assert conn.execute("SELECT count(*) FROM sentinel_commands").fetchone()[0] == 0


@pytest.mark.parametrize("phases", [("BASE_BACKUP",), ("BASE_BACKUP", "VERIFY_CHAIN", "COMPLETE")])
def test_real_newer_maintenance_progress_never_reconstructs_old_failed_renewal(conn, phases):
    _insert_backup_notice_progress(conn)
    _insert_backup_notice_progress(conn, attempt="b" * 32, phases=phases)
    outbox._reconstruct_missing_transition_alerts(conn)
    conn.commit()
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox").fetchone()[0] == 0


@pytest.mark.parametrize("fault", ["digest", "foreign", "historical", "future", "untyped", "oversized"])
def test_real_bad_backup_notice_evidence_cannot_block_unrelated_critical_delivery(conn, fault):
    from datetime import timedelta
    kwargs = {}
    if fault == "digest": kwargs["authentic"] = False
    elif fault == "foreign": kwargs["system_identifier"] = "7777777777777777777"
    elif fault in {"historical", "future"}:
        now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        kwargs["observed"] = now + timedelta(hours=-1 if fault == "historical" else 1)
    elif fault == "untyped": kwargs["started_at"] = True
    else: kwargs["unreviewed"] = "x" * 9000
    _insert_backup_notice_progress(conn, **kwargs)
    critical = outbox.enqueue(conn, idempotency_key="unrelated-critical", event_type="CRITICAL_INCIDENT",
                              severity="CRITICAL", payload={"reason": "independent current incident"})
    claimed = outbox.claim_next(conn, holder_id="independent-dispatcher")
    assert claimed.alert_id == critical.alert_id
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox "
                        "WHERE event_type='BACKUP_RENEWAL_FAILED'").fetchone()[0] == 0


def test_real_verified_successor_suppresses_obsolete_failed_renewal(conn):
    from psycopg.types.json import Jsonb
    failed = _insert_backup_notice_progress(conn)
    successor = _verified_successor(failed["system_identifier"])
    conn.execute("WITH v AS (SELECT %s::jsonb AS proof) INSERT INTO sentinel_backup_evidence "
        "(kind,evidence_sha256,proof) SELECT 'BASE_BACKUP',"
        "encode(sha256(convert_to(proof::text,'UTF8')),'hex'),proof FROM v", (Jsonb(successor),))
    conn.commit()
    outbox._reconstruct_missing_transition_alerts(conn)
    conn.commit()
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox").fetchone()[0] == 0


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
        # This server belongs solely to this module's disposable fixture.
        # Current trigger functions must not survive a table-only reset.
        cur.execute('DROP SCHEMA public CASCADE')
        cur.execute('CREATE SCHEMA public')
    connection.commit()
    schema.ensure_schema(connection)
    feed_store.migrate_schema(connection)
    from sentinel.panel import operational_schema
    operational_schema.install(connection)
    connection.commit()
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


@pytest.mark.parametrize("reconstruct", [False, True])
def test_real_retry_transition_survives_live_notification_and_reconstruction(conn, reconstruct):
    import asyncio
    from sentinel.automation.model import SourceDataPending, TickAction
    from sentinel.automation_resilience import RecoveryAutomationService
    from test_automation_service import (AFTER_WEDNESDAY_CLOSE, config, enable,
                                         prepare_result, recovery_success, execution_success)

    async def pending(_context):
        raise SourceDataPending("provider has not completed the source join")

    cfg = config()
    enable(conn, cfg)
    service = RecoveryAutomationService(
        config=cfg, holder_id="notification-writer", refresh=pending,
        prepare=prepare_result, recover=recovery_success, execute=execution_success)
    asyncio.run(service.tick(conn, now=AFTER_WEDNESDAY_CLOSE))
    result = asyncio.run(service.tick(conn, now=AFTER_WEDNESDAY_CLOSE))
    assert result.action is TickAction.RETRY_SCHEDULED
    for _ in range(2):
        if reconstruct:
            outbox._reconstruct_missing_transition_alerts(conn)
        else:
            outbox.enqueue_cycle_transition_alert(conn, cycle_id=result.cycle.cycle_id,
                                                 state="RETRY_WAIT")
    row = conn.execute("SELECT payload FROM sentinel_alert_outbox WHERE event_type='AUTOMATION_RETRY_SCHEDULED'").fetchall()
    assert len(row) == 1
    assert row[0][0]["detail"]["retry_phase"] == "REFRESH"


@pytest.mark.parametrize('reconstruct', [False, True])
@pytest.mark.parametrize('deadline_risk', [False, True])
def test_closing_frontier_wait_is_quiet_in_direct_and_reconstructed_outbox_unless_deadline_risk(
        conn, reconstruct, deadline_risk):
    import asyncio
    from datetime import timedelta
    from sentinel.automation.model import ClosingDataPending, TickAction
    from sentinel.automation_resilience import RecoveryAutomationService
    from tests.sentinel.test_automation_service import (
        AFTER_WEDNESDAY_CLOSE, config, enable, prepare_result, recovery_success, execution_success,
    )

    async def pending(_context):
        raise ClosingDataPending('the source-final closing frontier is not ready',
            publisher_deadline_at=(AFTER_WEDNESDAY_CLOSE + timedelta(seconds=5)
                if deadline_risk else None))

    cfg = config()
    enable(conn, cfg)
    worker = RecoveryAutomationService(config=cfg, holder_id='closing-notification-writer',
        refresh=pending, prepare=prepare_result, recover=recovery_success, execute=execution_success)
    asyncio.run(worker.tick(conn, now=AFTER_WEDNESDAY_CLOSE))
    result = asyncio.run(worker.tick(conn, now=AFTER_WEDNESDAY_CLOSE))
    assert result.action is TickAction.RETRY_SCHEDULED
    event_before = conn.execute('SELECT detail FROM sentinel_automation_cycle_events '
        "WHERE cycle_id=%s AND to_state='RETRY_WAIT' ORDER BY seq DESC LIMIT 1",
        (result.cycle.cycle_id,)).fetchone()[0]
    assert ('closing_data_wait' in event_before['diagnostic']) is (not deadline_risk)
    for _ in range(2):
        if reconstruct:
            outbox._reconstruct_missing_transition_alerts(conn)
        else:
            alert = outbox.enqueue_cycle_transition_alert(conn,
                cycle_id=result.cycle.cycle_id, state='RETRY_WAIT')
            assert (alert is not None) is deadline_risk
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox "
        "WHERE event_type='AUTOMATION_RETRY_SCHEDULED'").fetchone()[0] == int(deadline_risk)
    assert conn.execute('SELECT detail FROM sentinel_automation_cycle_events '
        "WHERE cycle_id=%s AND to_state='RETRY_WAIT' ORDER BY seq DESC LIMIT 1",
        (result.cycle.cycle_id,)).fetchone()[0] == event_before


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
        attempt=first.attempt_count,
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
        attempt=second.attempt_count,
        error="credentials explicitly rejected", retry_base_seconds=10,
        retry_max_seconds=60, retryable=False)
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


def test_repeated_crash_after_claim_remains_recoverable(conn) -> None:
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

    recovered = outbox.claim_next(
        conn, holder_id="third", claim_seconds=30)
    assert recovered.state is AlertState.DELIVERING
    assert recovered.attempt_count == 3
    assert recovered.delivery_holder == "third"
    assert recovered.idempotency_key == alert.idempotency_key
    with conn.cursor() as cur:
        cur.execute(
            "SELECT action FROM sentinel_alert_delivery_events"
            " WHERE alert_id=%s ORDER BY seq", (alert.alert_id,))
        assert [row[0] for row in cur.fetchall()] == [
            "CLAIMED", "RETRY_SCHEDULED", "CLAIMED", "RETRY_SCHEDULED", "CLAIMED"]


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

    assert not result.dead_lettered
    assert result.alert.state is AlertState.PENDING
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

    idle = alert_health.heartbeat(conn, dispatcher_id="primary")
    assert idle.state == alert_health.HEALTHY
    assert idle.last_success_at is None
    alert_health.require_healthy(
        conn, dispatcher_id="primary", maximum_age_seconds=30,
        startup_grace_seconds=300)

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
        attempt=claimed.attempt_count,
        error="terminal", retryable=False)
    with pytest.raises(alert_health.AlertDispatcherUnhealthy,
                       match="dead-letter"):
        alert_health.require_healthy(
            conn, dispatcher_id="primary", maximum_age_seconds=30,
            startup_grace_seconds=300)
