"""Permanent operator monitoring, recoverability, and Web Push contracts."""
from __future__ import annotations

import asyncio
import importlib
import inspect
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi.testclient import TestClient

from sentinel import operational_evidence, schema, shadow_supervisor
from sentinel import alert_service
from sentinel.automation import outbox
from sentinel.automation_runtime import ProductionAutomation
from sentinel.feed import store as feed_store
from sentinel.operational_status import FAIL, OK, PENDING, UNKNOWN, WARN
from sentinel.operational_status import RecoveryEvidence
from sentinel.panel import model, sources
from sentinel.panel.pwa import MANIFEST, SERVICE_WORKER
from sentinel.panel.render import PUSH_SCRIPT, render
from sentinel.web_push import (
    VapidCredentials,
    WebPushAlertAdapter,
    WebPushDeliveryFailure,
    b64url_decode,
    b64url_encode,
    encrypt,
    notification_payload,
    subscription_id,
)
from tests.support.postgres import _EphemeralPostgres


NOW = datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc)


def recovery(
        *, attempt: int = 1, maximum: int = 8,
        wake: datetime | None = None,
        deadline: datetime | None = None) -> RecoveryEvidence:
    return RecoveryEvidence(
        phase="TEST_RECOVERY", automatic=True, attempt=attempt,
        maximum_attempts=maximum,
        next_attempt_at=wake or NOW + timedelta(minutes=1),
        deadline=deadline)


def test_shadow_source_wait_is_amber_then_distinct_red_at_following_open(
        monkeypatch) -> None:
    alerts = []
    deadline = NOW + timedelta(hours=1)
    monkeypatch.setattr(
        shadow_supervisor.calendar, "latest_closed_session",
        lambda _now: "2026-09-11")
    monkeypatch.setattr(
        shadow_supervisor.calendar, "next_session",
        lambda _session: "2026-09-14")
    monkeypatch.setattr(
        shadow_supervisor.calendar, "session_window",
        lambda _session: (deadline, deadline + timedelta(hours=6)))
    monkeypatch.setattr(
        shadow_supervisor, "_enqueue_alert",
        lambda **kwargs: alerts.append(kwargs))

    shadow_supervisor._source_recovery_alert(now=NOW)
    shadow_supervisor._source_recovery_alert(now=deadline)

    assert [item["idempotency_key"] for item in alerts] == [
        "shadow-source:2026-09-11:not-ready",
        "shadow-source:2026-09-11:deadline-missed",
    ]
    assert [item["severity"] for item in alerts] == ["WARN", "CRITICAL"]
    assert alerts[0]["event_type"] == "SHADOW_SOURCE_RECOVERY_PENDING"
    assert alerts[1]["event_type"] == "SHADOW_SOURCE_DEADLINE_MISSED"


def test_shadow_semantic_retries_coalesce_per_decision_session(
        monkeypatch) -> None:
    alerts = []
    monkeypatch.setattr(
        shadow_supervisor.calendar, "latest_closed_session",
        lambda _now: "2026-09-11")
    monkeypatch.setattr(
        shadow_supervisor, "_enqueue_alert",
        lambda **kwargs: alerts.append(kwargs))

    shadow_supervisor._semantic_retry_alert(now=NOW)
    shadow_supervisor._semantic_retry_alert(now=NOW + timedelta(minutes=5))

    assert len(alerts) == 2
    assert alerts[0] == alerts[1]
    assert alerts[0]["idempotency_key"] == \
        "shadow-semantic:2026-09-11:retrying"
    assert alerts[0]["severity"] == "WARN"


def test_central_recoverability_policy_has_only_one_way_to_earn_amber() -> None:
    stale = NOW - timedelta(minutes=20)
    base = dict(
        key="required", label="Required fact", value="last known good",
        status=OK, as_of=stale, freshness=timedelta(minutes=10),
        required_current=True)

    assert model.Row(**base).effective_status(NOW) == FAIL
    assert model.Row(**base, recovery=recovery()).effective_status(NOW) == WARN
    assert model.Row(
        **base, recovery=recovery(attempt=8, maximum=8)
    ).effective_status(NOW) == FAIL
    assert model.Row(
        **base, recovery=recovery(deadline=NOW - timedelta(seconds=1))
    ).effective_status(NOW) == FAIL
    assert model.Row(
        "history", "History", "old", OK, as_of=stale,
        freshness=timedelta(minutes=10), required_current=False,
    ).effective_status(NOW) == WARN
    assert model.Row(
        "future", "Future", "impossible", OK,
        as_of=NOW + timedelta(minutes=1), required_current=True,
    ).effective_status(NOW) == FAIL
    required_pending = model.Row(
        "required-pending", "Required pending", "missing", PENDING,
        required_current=True)
    assert required_pending.effective_status(NOW) == FAIL
    assert model.Panel(rows=[required_pending], now=NOW).operational == FAIL
    assert model.Panel(
        rows=[model.Row("optional", "Optional", "not installed", PENDING)],
        now=NOW).operational == OK


def test_feed_ready_while_behind_is_never_green() -> None:
    repairing = model.feed_row(
        frontier="2026-09-10", sessions_behind=1, ready=True,
        checks_passed=12, checks_total=12, as_of=NOW,
        checked_at=NOW, ingest_running=True, ingest_updated_at=NOW)
    abandoned = model.feed_row(
        frontier="2026-09-10", sessions_behind=1, ready=True,
        checks_passed=12, checks_total=12, as_of=NOW,
        checked_at=NOW, ingest_running=False)
    expired = model.feed_row(
        frontier="2026-09-10", sessions_behind=1, ready=True,
        checks_passed=12, checks_total=12, as_of=NOW,
        checked_at=NOW, ingest_running=True,
        ingest_updated_at=NOW - timedelta(minutes=16))
    ahead = model.feed_row(
        frontier="2026-09-14", sessions_behind=0, ready=True,
        checks_passed=12, checks_total=12, as_of=NOW,
        checked_at=NOW, frontier_ahead=True)

    assert repairing.effective_status(NOW) == WARN
    assert abandoned.effective_status(NOW) == FAIL
    assert expired.effective_status(NOW) == FAIL
    assert ahead.effective_status(NOW) == FAIL


def test_transient_broker_and_account_reads_are_amber_only_with_bounds() -> None:
    bounded = recovery()
    broker_retry = model.broker_row(
        available=None, error="Alpaca timed out", as_of=NOW,
        recovery=bounded)
    account_retry = model.alpaca_account_row(
        available=None, error="account endpoint timed out", observed_at=NOW,
        recovery=bounded)

    assert broker_retry.effective_status(NOW) == WARN
    assert account_retry.effective_status(NOW) == WARN
    assert model.broker_row(
        available=None, error="Alpaca timed out", as_of=NOW,
    ).effective_status(NOW) == UNKNOWN
    assert model.alpaca_account_row(
        available=None, error="account endpoint timed out", observed_at=NOW,
    ).effective_status(NOW) == UNKNOWN


def test_alpaca_account_exposes_identity_flags_and_cash_only_contract() -> None:
    healthy = model.alpaca_account_row(
        available=True, broker="alpaca", account_id="paper-1",
        expected_account_id="paper-1", status="ACTIVE", flags={},
        equity="100000", cash="100000", buying_power="100000",
        multiplier="1", observed_at=NOW)
    blocked = model.alpaca_account_row(
        available=True, broker="alpaca", account_id="paper-1",
        expected_account_id="paper-1", status="ACTIVE",
        flags={"trading_blocked": True}, equity="100000", cash="100000",
        buying_power="100000", multiplier="1", observed_at=NOW)
    margin = model.alpaca_account_row(
        available=True, broker="alpaca", account_id="paper-1",
        expected_account_id="paper-1", status="ACTIVE", flags={},
        equity="100000", cash="50000", buying_power="200000",
        multiplier="4", observed_at=NOW)
    wrong = model.alpaca_account_row(
        available=True, broker="alpaca", account_id="paper-wrong",
        expected_account_id="paper-1", status="ACTIVE", flags={},
        equity="100000", cash="100000", buying_power="100000",
        multiplier="1", observed_at=NOW)

    assert healthy.effective_status(NOW) == OK
    assert blocked.effective_status(NOW) == FAIL
    assert "trading_blocked" in blocked.detail
    assert margin.effective_status(NOW) == FAIL
    assert "multiplier is not cash-only 1" in margin.detail
    assert wrong.effective_status(NOW) == FAIL


def _backup_proofs() -> tuple[dict, dict, dict]:
    base = {
        "base_backup": "base-20260913", "marker": "marker-1",
        "marker_lsn": "0/500", "marker_wal": "000000010000000000000005",
        "system_identifier": "system-1",
    }
    restore = {
        "base_backup": "base-20260913", "marker": "marker-1",
        "target_lsn": "0/600", "system_identifier": "system-1",
        "physical_only": False,
    }
    runtime = {
        "enabled": True, "wal_integrity": "sha256-sidecar-v1",
        "recoverable_from_wal": "000000010000000000000005",
        "recoverable_through_wal": "000000010000000000000006",
        "wal_segments": 2, "base_backup": "base-20260913",
        "system_identifier": "system-1",
    }
    return base, restore, runtime


def test_backup_lag_is_amber_only_while_restore_authority_remains_valid() -> None:
    base, restore, runtime = _backup_proofs()
    common = dict(
        base_at=NOW - timedelta(hours=27),
        restore_at=NOW - timedelta(days=1),
        runtime_at=NOW - timedelta(minutes=1), base_proof=base,
        restore_proof=restore, runtime_proof=runtime, now=NOW,
        runtime_valid_until=NOW + timedelta(hours=1))

    assert model.backup_restore_row(
        **common, recovery=recovery()).effective_status(NOW) == WARN
    assert model.backup_restore_row(**common).effective_status(NOW) == FAIL
    broken = {**runtime, "wal_segments": 0}
    assert model.backup_restore_row(
        **{**common, "runtime_proof": broken}, recovery=recovery()
    ).effective_status(NOW) == FAIL


def test_monthly_restore_proof_survives_newer_daily_base_generations() -> None:
    base, restore, runtime = _backup_proofs()
    restore = {**restore, "base_backup": "base-20260831"}

    row = model.backup_restore_row(
        base_at=NOW - timedelta(hours=1),
        restore_at=NOW - timedelta(days=13),
        runtime_at=NOW - timedelta(minutes=2),
        base_proof=base, restore_proof=restore, runtime_proof=runtime,
        runtime_valid_until=NOW + timedelta(hours=1), now=NOW)

    assert row.effective_status(NOW) == OK


def test_runtime_identity_needs_observed_reviewed_and_current_proof() -> None:
    git_sha = "a" * 40
    image = "sha256:" + "b" * 64
    common = dict(
        runtime_git=git_sha, runtime_image=image, reviewed_git=git_sha,
        reviewed_image=image, certificate_sha256="c" * 64,
        lifecycle_current=True, authority_verdict="PASS", checked_at=NOW)

    assert model.runtime_identity_row(**common).effective_status(NOW) == OK
    assert model.runtime_identity_row(
        **{**common, "runtime_git": "d" * 40}
    ).effective_status(NOW) == FAIL
    assert model.runtime_identity_row(
        **{**common, "checked_at": None}
    ).effective_status(NOW) == FAIL
    assert model.runtime_identity_row(
        **{**common, "checked_at": NOW - timedelta(minutes=6)}
    ).effective_status(NOW) == FAIL


def test_completed_runtime_evidence_lives_until_next_session_obligation() -> None:
    from sentinel.automation import schedule
    from sentinel.automation.model import AutomationConfig
    from sentinel.feed import calendar

    fact_at = datetime(2026, 9, 14, 14, 0, tzinfo=timezone.utc)
    cycle = {
        "state": "SUCCEEDED", "decision_session": "2026-09-11",
        "next_wake_at": None,
    }
    expected = schedule.for_decision_session(
        calendar.next_session("2026-09-11"), AutomationConfig()).prepare_at

    assert sources._runtime_valid_until(cycle, fact_at) == expected  # noqa: SLF001
    assert expected > fact_at + timedelta(minutes=10)


def test_degraded_dispatcher_is_amber_only_with_durable_delivery_retry() -> None:
    dispatcher = [{
        "dispatcher_id": "primary", "state": "DEGRADED",
        "heartbeat_at": NOW, "heartbeat_age_seconds": 1,
        "last_success_at": None, "consecutive_failures": 1,
        "last_error": "temporary push refusal",
    }]
    bounded = model.alert_dispatcher_row(
        installed=True, dispatchers=dispatcher, retry_attempt=1,
        retry_max_attempts=8, next_attempt_at=NOW + timedelta(seconds=5))
    unbounded = model.alert_dispatcher_row(
        installed=True, dispatchers=dispatcher)

    assert bounded.effective_status(NOW) == WARN
    assert unbounded.effective_status(NOW) == FAIL


def _cycle(state: str, **overrides) -> dict:
    value = {
        "cycle_id": "cycle-20260913", "state": state,
        "decision_session": "2026-09-13",
        "effective_session": "2026-09-14",
        "prepare_at": NOW - timedelta(minutes=4),
        "execution_open_at": NOW + timedelta(minutes=4),
        "execute_at": NOW + timedelta(minutes=5),
        "execution_close_at": NOW + timedelta(hours=5),
        "next_wake_at": NOW + timedelta(minutes=1),
        "attempt_count": 1, "phase_attempt_count": 1,
        "phase_max_attempts": 8, "updated_at": NOW,
        "created_at": NOW - timedelta(minutes=5),
    }
    value.update(overrides)
    return value


def test_dashboard_expands_every_durable_automation_step() -> None:
    events = [
        {"from_state": None, "to_state": "DISCOVERED", "at": NOW},
        {"from_state": "DISCOVERED", "to_state": "REFRESHING_DATA",
         "at": NOW},
        {"from_state": "REFRESHING_DATA", "to_state": "PREPARING",
         "at": NOW},
    ]
    rows = model.automation_step_rows(
        installed=True, enabled=True, cycle=_cycle("PREPARING"),
        events=events)

    assert [row.key for row in rows] == [
        "automation_step_discovery", "automation_step_data",
        "automation_step_prepare", "automation_step_open",
        "automation_step_transport", "automation_step_reconcile",
        "automation_step_complete",
    ]
    assert [row.effective_status(NOW) for row in rows] == [
        OK, OK, WARN, PENDING, PENDING, PENDING, PENDING]


def test_automation_steps_escalate_retry_and_require_clean_completion() -> None:
    retrying = model.automation_step_rows(
        installed=True, enabled=True,
        cycle=_cycle(
            "RETRY_WAIT", retry_phase="EXECUTE", phase_attempt_count=6))
    exhausted = model.automation_step_rows(
        installed=True, enabled=True,
        cycle=_cycle(
            "RETRY_WAIT", retry_phase="EXECUTE", phase_attempt_count=8))
    succeeded = model.automation_step_rows(
        installed=True, enabled=True,
        cycle=_cycle(
            "SUCCEEDED", clean_reconciliation_id="reconciliation-1",
            completed_at=NOW))
    false_success = model.automation_step_rows(
        installed=True, enabled=True,
        cycle=_cycle("SUCCEEDED", completed_at=NOW))

    assert retrying[4].value == "RETRY 6/8"
    assert retrying[4].effective_status(NOW) == WARN
    assert exhausted[4].effective_status(NOW) == FAIL
    assert all(row.effective_status(NOW) == OK for row in succeeded)
    assert false_success[-1].effective_status(NOW) == FAIL
    assert model.automation_cycle_row(
        installed=True, enabled=True, **_cycle("SUCCEEDED")
    ).effective_status(NOW) == FAIL


@pytest.mark.parametrize(
    ("row", "headline"),
    [
        (model.Row("healthy", "Healthy", "CURRENT", OK),
         "OPERATIONAL GREEN — HEALTHY AND CURRENT"),
        (model.Row(
            "repair", "Repair", "RETRY 1/8", WARN,
            required_current=True, recovery=recovery()),
         "OPERATIONAL AMBER — NO ACTION REQUIRED YET"),
        (model.Row("blocked", "Blocked", "ACTION REQUIRED", FAIL),
         "OPERATIONAL RED — OPERATOR ACTION REQUIRED"),
    ],
)
def test_headline_uses_the_same_recoverability_verdict(row, headline) -> None:
    panel = model.Panel(rows=[row], now=NOW)
    assert headline in render(panel)


def test_withdrawn_shadow_verification_turns_operational_headline_red() -> None:
    shadow = model.shadow_verification_row(
        verdict="SHADOW_GO", verification="WITHDRAWN",
        session="2026-09-12", error="integrity proof changed")
    panel = model.Panel(rows=[shadow], now=NOW)

    assert panel.operational == FAIL
    assert "OPERATIONAL RED — OPERATOR ACTION REQUIRED" in render(panel)


def test_operational_health_uses_exact_panel_status(monkeypatch) -> None:
    app_module = importlib.import_module("sentinel.panel.app")
    red = model.Panel(
        rows=[model.Row("account", "Account", "BLOCKED", FAIL)], now=NOW)
    monkeypatch.setattr(app_module, "build_panel", lambda **_kwargs: red)
    monkeypatch.setattr(
        app_module, "_shadow_segment_disclosure", lambda panel, _dsn: panel)

    response = app_module.operational_health()
    body = json.loads(response.body)
    assert response.status_code == 503
    assert body["status"] == FAIL
    assert body["color"] == "red"
    assert body["red_rows"] == ["account"]

    amber = model.Panel(rows=[model.Row(
        "retry", "Retry", "1/8", WARN, required_current=True,
        recovery=recovery())], now=NOW)
    monkeypatch.setattr(app_module, "build_panel", lambda **_kwargs: amber)
    response = app_module.operational_health()
    assert response.status_code == 200
    assert json.loads(response.body)["color"] == "amber"


def test_home_screen_heartbeat_and_service_worker_fail_closed() -> None:
    html = render(model.Panel(
        rows=[model.Row("healthy", "Healthy", "CURRENT", OK)], now=NOW))

    assert "DASHBOARD HEARTBEAT · UPDATED 0s AGO" in html
    assert "DASHBOARD HEARTBEAT LOST · STATUS STALE" in html
    assert 'window.addEventListener("offline"' in html
    assert "if (wentOffline){ invalidate(false); }" in html
    assert "if (wentOffline){ invalidate(true); }" in html
    assert 'window.addEventListener("pageshow"' in html
    assert 'document.addEventListener("visibilitychange"' in html
    assert "only the server can earn it again" in html
    assert "caches.delete" in SERVICE_WORKER
    assert "caches.open" not in SERVICE_WORKER
    assert "showNotification" in SERVICE_WORKER
    assert "clients.openWindow" in SERVICE_WORKER
    assert "OPERATIONAL RED — OFFLINE" in SERVICE_WORKER


def test_notification_permission_is_requested_only_inside_button_gesture() -> None:
    before_click, click_handler = PUSH_SCRIPT.split(
        'enable.addEventListener("click"', 1)

    assert "Notification.requestPermission" not in before_click
    assert click_handler.count("Notification.requestPermission") == 1
    assert "PushManager" in before_click
    assert 'method: "POST"' in click_handler
    assert MANIFEST["display"] == "standalone"
    assert {icon["sizes"] for icon in MANIFEST["icons"]} == {
        "192x192", "512x512"}


def test_success_paths_have_no_routine_or_recovery_to_green_alert() -> None:
    source = inspect.getsource(ProductionAutomation._fenced_data_wake)
    assert "AUTOMATION_FENCED_DATA_READY" not in source
    assert "SHADOW_OBSERVATION_VERIFIED" not in source


def test_retry_incident_is_coalesced_and_red_escalation_is_distinct() -> None:
    first_detail = {
        "notifier_action": "RETRY_SCHEDULED", "retry_phase": "EXECUTE",
        "phase_attempt_count": 1, "phase_max_attempts": 8,
        "failure_code": "BROKER_TIMEOUT", "first_failure_at": "t0",
        "exception_fingerprint": "same-failure",
    }
    sixth_detail = {**first_detail, "phase_attempt_count": 6}
    first = outbox._cycle_event_alert(  # noqa: SLF001
        (1, "cycle-a", "RETRY_WAIT", 7, 11, first_detail))
    sixth = outbox._cycle_event_alert(  # noqa: SLF001
        (2, "cycle-a", "RETRY_WAIT", 7, 11, sixth_detail))
    red = outbox._cycle_event_alert(  # noqa: SLF001
        (3, "cycle-a", "BLOCKED", 7, 11,
         {"failure_code": "BROKER_TIMEOUT"}))

    assert first == sixth
    assert first["severity"] == "WARN"
    assert red["severity"] == "CRITICAL"
    assert red["idempotency_key"] != first["idempotency_key"]


def test_fact_recovery_uses_durable_retry_phase_not_error_words() -> None:
    refresh = _cycle(
        "RETRY_WAIT", retry_phase="REFRESH",
        failure_detail="text happens to mention broker")
    execute = _cycle(
        "RETRY_WAIT", retry_phase="EXECUTE",
        failure_detail="opaque transport refusal")

    assert sources._observation_recovery(refresh) is None  # noqa: SLF001
    assert sources._observation_recovery(execute) is not None  # noqa: SLF001


def test_backup_recovery_requires_durable_typed_failure_domain() -> None:
    typed = _cycle(
        "RETRY_WAIT", retry_phase="PREPARE", failure_domain="BACKUP",
        failure_detail="opaque dependency refusal")
    prose_only = _cycle(
        "RETRY_WAIT", retry_phase="PREPARE",
        failure_detail="text happens to mention backup")
    unrelated = _cycle(
        "RETRY_WAIT", retry_phase="PREPARE", failure_domain="SHARADAR",
        failure_detail="backup appears only in prose")

    assert sources._cycle_recovery(  # noqa: SLF001
        typed, failure_domains=("BACKUP",)) is not None
    assert sources._cycle_recovery(  # noqa: SLF001
        prose_only, failure_domains=("BACKUP",)) is None
    assert sources._cycle_recovery(  # noqa: SLF001
        unrelated, failure_domains=("BACKUP",)) is None


def test_health_alarm_reuses_terminal_cycle_alert_identity(monkeypatch) -> None:
    calls = []
    connection = object()
    health = SimpleNamespace(
        policy_state="BLOCKED", control_generation=7,
        latest_cycle_id="cycle-a", latest_cycle_state="BLOCKED",
        broker_outcome_unresolved=False, leader_holder="leader-a")
    monkeypatch.setattr(
        outbox, "enqueue_cycle_transition_alert",
        lambda conn, **kwargs: calls.append((conn, kwargs)) or "alert")
    monkeypatch.setattr(
        outbox, "enqueue",
        lambda *_args, **_kwargs: pytest.fail("duplicate health alert"))

    result = alert_service._enqueue_health_incident(  # noqa: SLF001
        connection, health=health, max_attempts=8)

    assert result == "alert"
    assert calls == [(connection, {
        "cycle_id": "cycle-a", "state": "BLOCKED"})]


def test_red_scheduler_alarm_does_not_collapse_into_amber_retry(monkeypatch) -> None:
    connection = object()
    health = SimpleNamespace(
        policy_state="SCHEDULER_STALLED", control_generation=7,
        latest_cycle_id="cycle-a", latest_cycle_state="RETRY_WAIT",
        broker_outcome_unresolved=False, leader_holder="leader-a")
    monkeypatch.setattr(
        outbox, "enqueue_cycle_transition_alert",
        lambda *_args, **_kwargs: pytest.fail("red alarm reused amber alert"))
    calls = []
    monkeypatch.setattr(
        outbox, "enqueue",
        lambda conn, **kwargs: calls.append((conn, kwargs)) or "red-alert")

    result = alert_service._enqueue_health_incident(  # noqa: SLF001
        connection, health=health, max_attempts=8)

    assert result == "red-alert"
    assert calls[0][1]["severity"] == "CRITICAL"
    assert calls[0][1]["event_type"] == "AUTOMATION_OPERATIONAL_RED"


def test_secondary_webhook_cannot_probe_or_clear_primary_web_push_health() -> None:
    source = inspect.getsource(alert_service.run)

    assert "web_push_configured = all(vapid_values)" in source
    assert "webhook_adapter is not None and not web_push_configured" in source


@pytest.mark.asyncio
async def test_contiguous_database_outage_retries_one_external_incident(
        monkeypatch) -> None:
    adapters = []
    connect_attempts = 0

    class Adapter:
        def __init__(self, _url, *, timeout_seconds):
            assert timeout_seconds == 10
            self.calls = []
            adapters.append(self)

        def deliver_database_failure(self, detail, bucket):
            self.calls.append((detail, bucket))
            if len(self.calls) < 3:
                raise alert_service.AlertTransportFailure(
                    "synthetic independent transport outage")

    def unavailable(_dsn):
        nonlocal connect_attempts
        connect_attempts += 1
        raise ConnectionError(f"database unavailable attempt {connect_attempts}")

    async def finite_sleep(stop: asyncio.Event, _seconds: float) -> None:
        if connect_attempts >= 4:
            stop.set()

    monkeypatch.setenv(
        "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL",
        "https://alerts.example.test/sentinel")
    for name in (
            "SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY",
            "SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY",
            "SENTINEL_WEB_PUSH_VAPID_SUBJECT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        alert_service.SentinelConfig, "from_env",
        lambda: SimpleNamespace(database_url="postgresql://unavailable"))
    monkeypatch.setattr(
        alert_service, "config_from_env",
        lambda: SimpleNamespace(alert_max_attempts=8))
    monkeypatch.setattr(alert_service, "WebhookAlertAdapter", Adapter)
    monkeypatch.setattr(alert_service.feed_store, "connect", unavailable)
    monkeypatch.setattr(alert_service, "_sleep_or_stop", finite_sleep)
    monkeypatch.setattr(
        alert_service.time, "time", lambda: 60 * (1000 + connect_attempts))

    assert await alert_service.run() == 0

    assert connect_attempts == 4
    assert len(adapters) == 1
    assert len(adapters[0].calls) == 3
    assert {bucket for _detail, bucket in adapters[0].calls} == {1001}
    assert {detail for detail, _bucket in adapters[0].calls} == {
        "ConnectionError: database unavailable attempt 1"}


def _private_key(value: int) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(value, ec.SECP256R1())


def _public_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)


def _vapid() -> VapidCredentials:
    private = _private_key(7)
    return VapidCredentials.from_base64url(
        private_key=b64url_encode((7).to_bytes(32, "big")),
        public_key=b64url_encode(_public_bytes(private)),
        subject="mailto:sentinel@example.test")


def _subscription_material(value: int = 11) -> tuple[str, str]:
    return (
        b64url_encode(_public_bytes(_private_key(value))),
        b64url_encode(bytes(range(16))))


@pytest.mark.parametrize(
    "value", ["ab+c", "ab/c", "ab c", "ab=c", "AB", ""])
def test_web_push_rejects_noncanonical_base64url(value: str) -> None:
    with pytest.raises(ValueError, match="canonical URL-safe"):
        b64url_decode(value)


def test_rfc8291_payload_round_trip_uses_browser_keys() -> None:
    ua_private = _private_key(11)
    ua_public = _public_bytes(ua_private)
    p256dh = b64url_encode(ua_public)
    auth = bytes(range(16))
    ephemeral = _private_key(13)
    salt = bytes(range(16, 32))
    body = encrypt(
        b'{"alert":"amber"}', p256dh=p256dh,
        auth=b64url_encode(auth), ephemeral_private_key=ephemeral, salt=salt)

    assert body[:16] == salt
    assert int.from_bytes(body[16:20], "big") == 4096
    key_length = body[20]
    server_public = body[21:21 + key_length]
    ciphertext = body[21 + key_length:]
    shared = ua_private.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), server_public))
    ikm = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=auth,
        info=b"WebPush: info\x00" + ua_public + server_public,
    ).derive(shared)
    cek = HKDF(
        algorithm=hashes.SHA256(), length=16, salt=salt,
        info=b"Content-Encoding: aes128gcm\x00",
    ).derive(ikm)
    nonce = HKDF(
        algorithm=hashes.SHA256(), length=12, salt=salt,
        info=b"Content-Encoding: nonce\x00",
    ).derive(ikm)

    assert AESGCM(cek).decrypt(nonce, ciphertext, None) == (
        b'{"alert":"amber"}\x02')


@pytest.fixture(scope="module")
def issue369_pg():
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
def db(issue369_pg):
    conn = feed_store.connect(issue369_pg.sync_dsn)
    with conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    conn.commit()
    schema.ensure_schema(conn)
    yield conn
    conn.close()


def _add_subscription(conn, suffix: str, *, material: int = 11) -> str:
    endpoint = f"https://push.example.test/{suffix}"
    p256dh, auth = _subscription_material(material)
    sub_id = subscription_id(endpoint)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_web_push_subscriptions"
            " (subscription_id,endpoint,p256dh,auth,user_agent)"
            " VALUES (%s,%s,%s,%s,'pytest')",
            (sub_id, endpoint, p256dh, auth))
    conn.commit()
    return endpoint


def test_unchanged_backup_reobservation_appends_new_freshness_evidence(db) -> None:
    base, _restore, _runtime = _backup_proofs()

    first = operational_evidence.record_backup_proof(
        db, kind="BASE_BACKUP", proof=base)
    second = operational_evidence.record_backup_proof(
        db, kind="BASE_BACKUP", proof=base)
    db.commit()

    assert first == second
    with db.cursor() as cur:
        cur.execute(
            "SELECT evidence_sha256,COUNT(*),COUNT(DISTINCT seq)"
            " FROM sentinel_backup_evidence GROUP BY evidence_sha256")
        assert cur.fetchall() == [(first, 2, 2)]


def test_push_enrollment_is_same_origin_narrow_and_durable(
        db, issue369_pg, monkeypatch) -> None:
    app_module = importlib.import_module("sentinel.panel.app")
    origin = "https://caesars-palace.tailnet.example"
    p256dh, auth = _subscription_material(31)
    endpoint = "https://push.example.test/enrolled-device"
    monkeypatch.setenv("SENTINEL_DATABASE_URL", issue369_pg.sync_dsn)
    monkeypatch.setenv("SENTINEL_PUBLIC_ORIGIN", origin)
    monkeypatch.setenv(
        "SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY",
        b64url_encode(_vapid().public_key_bytes))
    client = TestClient(app_module.app)
    payload = {
        "endpoint": endpoint,
        "keys": {"p256dh": p256dh, "auth": auth},
        "test_id": "00000000-0000-4000-8000-000000000001",
    }

    denied = client.post(
        "/push/subscriptions", headers={"Origin": "https://wrong.test"},
        json=payload)
    accepted = client.post(
        "/push/subscriptions", headers={"Origin": origin}, json=payload)

    assert denied.status_code == 403
    assert accepted.status_code == 201
    assert accepted.headers["cache-control"] == "no-store"
    with db.cursor() as cur:
        cur.execute(
            "SELECT endpoint,retired_at FROM sentinel_web_push_subscriptions")
        assert cur.fetchall() == [(endpoint, None)]
        cur.execute("SELECT event_type,severity FROM sentinel_alert_outbox")
        assert cur.fetchall() == [("PUSH_ENROLLMENT_TEST", "INFO")]

    removed = client.post(
        "/push/subscriptions/remove", headers={"Origin": origin},
        json={"endpoint": endpoint})
    assert removed.status_code == 200
    with db.cursor() as cur:
        cur.execute(
            "SELECT retired_at,retire_reason FROM"
            " sentinel_web_push_subscriptions WHERE endpoint=%s", (endpoint,))
        retired_at, reason = cur.fetchone()
    assert retired_at is not None
    assert reason == "removed by device"


def test_browser_subscription_replacement_is_atomic_and_silent(
        db, issue369_pg, monkeypatch) -> None:
    app_module = importlib.import_module("sentinel.panel.app")
    origin = "https://caesars-palace.tailnet.example"
    previous = _add_subscription(db, "old-browser-device", material=37)
    endpoint = "https://push.example.test/replacement-browser-device"
    p256dh, auth = _subscription_material(41)
    monkeypatch.setenv("SENTINEL_DATABASE_URL", issue369_pg.sync_dsn)
    monkeypatch.setenv("SENTINEL_PUBLIC_ORIGIN", origin)
    client = TestClient(app_module.app)

    response = client.post(
        "/push/subscriptions/refresh", headers={"Origin": origin},
        json={
            "previous_endpoint": previous,
            "subscription": {
                "endpoint": endpoint,
                "keys": {"p256dh": p256dh, "auth": auth},
            },
        })

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    with db.cursor() as cur:
        cur.execute(
            "SELECT endpoint,retired_at,retire_reason"
            " FROM sentinel_web_push_subscriptions ORDER BY endpoint")
        rows = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM sentinel_alert_outbox")
        alert_count = cur.fetchone()[0]
    assert rows[0][0] == previous
    assert rows[0][1] is not None
    assert rows[0][2] == "replaced by browser"
    assert rows[1] == (endpoint, None, None)
    assert alert_count == 0


def test_service_worker_handles_subscription_rotation_without_test_push() -> None:
    assert 'addEventListener("pushsubscriptionchange"' in SERVICE_WORKER
    assert 'fetch("/push/subscriptions/refresh"' in SERVICE_WORKER
    assert "PUSH_ENROLLMENT_TEST" not in SERVICE_WORKER


@pytest.mark.asyncio
async def test_informational_green_outbox_rows_are_consumed_without_push(
        db, issue369_pg) -> None:
    alert = outbox.enqueue(
        db, idempotency_key="quiet-green", event_type="SYSTEM_RECOVERED",
        severity="INFO", payload={"state": "GREEN"})
    adapter = WebPushAlertAdapter(
        connection_factory=lambda: feed_store.connect(issue369_pg.sync_dsn),
        credentials=_vapid(),
        sender=lambda *_args: pytest.fail("green emitted Web Push"))

    result = await outbox.dispatch_once(
        db, adapter=adapter, holder_id="quiet-dispatcher")

    assert result.delivered is True
    assert result.alert.alert_id == alert.alert_id
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_web_push_fanouts")
        assert cur.fetchone()[0] == 0


def test_web_push_partial_fanout_retries_only_the_failed_device(
        db, issue369_pg) -> None:
    first = _add_subscription(db, "device-a", material=11)
    second = _add_subscription(db, "device-b", material=17)
    alert = outbox.enqueue(
        db, idempotency_key="amber-one", event_type="AUTOMATION_RETRY",
        severity="WARN", payload={"reason": "provider timeout"})
    calls = []

    def sender(endpoint, _body, _headers, _timeout):
        calls.append(endpoint)
        if endpoint == second and calls.count(second) == 1:
            return 503
        return 201

    adapter = WebPushAlertAdapter(
        connection_factory=lambda: feed_store.connect(issue369_pg.sync_dsn),
        credentials=_vapid(), sender=sender)
    with pytest.raises(WebPushDeliveryFailure) as failure:
        adapter.deliver(alert, alert.idempotency_key)
    assert failure.value.retryable is True

    late = _add_subscription(db, "device-added-later", material=19)
    adapter.deliver(alert, alert.idempotency_key)

    assert calls == [first, second, second]
    assert late not in calls
    with db.cursor() as cur:
        cur.execute(
            "SELECT recipient_count FROM sentinel_web_push_fanouts"
            " WHERE alert_id=%s", (alert.alert_id,))
        assert cur.fetchone()[0] == 2
        cur.execute(
            "SELECT state,COUNT(*) FROM sentinel_web_push_deliveries"
            " WHERE alert_id=%s GROUP BY state", (alert.alert_id,))
        assert dict(cur.fetchall()) == {"DELIVERED": 2}


def test_device_added_after_alert_never_receives_that_historical_alert(
        db, issue369_pg) -> None:
    alert = outbox.enqueue(
        db, idempotency_key="before-device", event_type="AUTOMATION_RETRY",
        severity="WARN", payload={"reason": "brief outage"})
    _add_subscription(db, "new-device", material=23)
    calls = []
    adapter = WebPushAlertAdapter(
        connection_factory=lambda: feed_store.connect(issue369_pg.sync_dsn),
        credentials=_vapid(), sender=lambda *args: calls.append(args) or 201)

    with pytest.raises(WebPushDeliveryFailure, match="no active"):
        adapter.deliver(alert, alert.idempotency_key)
    assert calls == []


def test_first_fanout_excludes_a_late_device_when_an_older_device_exists(
        db, issue369_pg) -> None:
    existing = _add_subscription(db, "existing-device", material=25)
    alert = outbox.enqueue(
        db, idempotency_key="between-devices", event_type="AUTOMATION_RETRY",
        severity="WARN", payload={"reason": "brief outage"})
    late = _add_subscription(db, "late-device", material=27)
    calls = []
    adapter = WebPushAlertAdapter(
        connection_factory=lambda: feed_store.connect(issue369_pg.sync_dsn),
        credentials=_vapid(), sender=lambda *args: calls.append(args[0]) or 201)

    adapter.deliver(alert, alert.idempotency_key)

    assert calls == [existing]
    assert late not in calls
    with db.cursor() as cur:
        cur.execute(
            "SELECT recipient_count FROM sentinel_web_push_fanouts"
            " WHERE alert_id=%s", (alert.alert_id,))
        assert cur.fetchone()[0] == 1
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_web_push_deliveries"
            " WHERE alert_id=%s", (alert.alert_id,))
        assert cur.fetchone()[0] == 1


def test_terminal_push_response_retires_only_that_subscription(
        db, issue369_pg) -> None:
    endpoint = _add_subscription(db, "gone", material=29)
    alert = outbox.enqueue(
        db, idempotency_key="red-gone", event_type="AUTOMATION_BLOCKED",
        severity="CRITICAL", payload={"reason": "operator required"})
    adapter = WebPushAlertAdapter(
        connection_factory=lambda: feed_store.connect(issue369_pg.sync_dsn),
        credentials=_vapid(), sender=lambda *_args: 410)

    with pytest.raises(WebPushDeliveryFailure) as failure:
        adapter.deliver(alert, alert.idempotency_key)
    assert failure.value.retryable is False
    with db.cursor() as cur:
        cur.execute(
            "SELECT retired_at,retire_reason FROM"
            " sentinel_web_push_subscriptions WHERE endpoint=%s", (endpoint,))
        retired_at, reason = cur.fetchone()
        assert retired_at is not None
        assert "410" in reason
        cur.execute(
            "SELECT state FROM sentinel_web_push_deliveries"
            " WHERE alert_id=%s", (alert.alert_id,))
        assert cur.fetchone()[0] == "RETIRED"


def _insert_command(conn, *, broker_order_id: str = "order-1") -> str:
    client_key = "sentinel-v1-issue369-command"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_commands"
            " (client_key,plan_id,security_id,deployment_id,broker,"
            " broker_account_id,takeover_epoch,symbol,broker_instrument_id,"
            " side,quantity,state,broker_order_id,filled_quantity)"
            " VALUES (%s,'plan-1','security-1','deployment-1','alpaca',"
            " 'paper-1',1,'AAPL','asset-1','BUY',2,'FILLED',%s,2)",
            (client_key, broker_order_id))
    conn.commit()
    return client_key


def _insert_fill(
        conn, *, broker_order_id: str, fill_key: str,
        client_key: str | None, quantity: str, price: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_fills"
            " (broker_order_id,fill_key,client_key,quantity,price,filled_at)"
            " VALUES (%s,%s,%s,%s,%s,clock_timestamp())",
            (broker_order_id, fill_key, client_key, quantity, price))
    conn.commit()


def test_fill_commit_crash_reconstructs_one_alert_per_partial_fill(db) -> None:
    client_key = _insert_command(db)
    _insert_fill(
        db, broker_order_id="order-1", fill_key="native-fill-1",
        client_key=client_key, quantity="1", price="189.25")

    first = outbox.claim_next(db, holder_id="fill-dispatcher")
    assert first is not None
    assert first.event_type == "BROKER_FILL"
    assert first.idempotency_key == "fill:order-1:native-fill-1"
    assert dict(first.payload)["side"] == "BUY"
    assert dict(first.payload)["ticker"] == "AAPL"
    assert dict(first.payload)["quantity"] == "1"
    assert dict(first.payload)["price"] == "189.25"
    assert dict(first.payload)["filled_at"]
    outbox.mark_delivered(
        db, alert_id=first.alert_id, holder_id="fill-dispatcher", attempt=first.attempt_count)

    _insert_fill(
        db, broker_order_id="order-1", fill_key="native-fill-2",
        client_key=client_key, quantity="1", price="189.50")
    second = outbox.claim_next(db, holder_id="fill-dispatcher")
    assert second is not None
    assert second.idempotency_key == "fill:order-1:native-fill-2"
    outbox.mark_delivered(
        db, alert_id=second.alert_id, holder_id="fill-dispatcher", attempt=second.attempt_count)

    assert outbox.claim_next(db, holder_id="fill-dispatcher") is None
    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_alert_outbox"
            " WHERE event_type='BROKER_FILL'")
        assert cur.fetchone()[0] == 2


def test_unbound_fill_emits_red_integrity_alert_not_a_fabricated_trade(db) -> None:
    _insert_fill(
        db, broker_order_id="unknown-order", fill_key="native-orphan",
        client_key=None, quantity="1", price="10")

    alert = outbox.claim_next(db, holder_id="integrity-dispatcher")

    assert alert is not None
    assert alert.event_type == "FILL_NOTIFICATION_IDENTITY_INVALID"
    assert alert.severity == "CRITICAL"
    assert alert.idempotency_key == (
        "fill-integrity:unknown-order:native-orphan")
    assert "side" not in dict(alert.payload)


def test_contradictory_fill_command_identity_emits_red_integrity_alert(db) -> None:
    _insert_command(db, broker_order_id="bound-order")
    _insert_fill(
        db, broker_order_id="bound-order", fill_key="contradictory-fill",
        client_key="a-different-client-key", quantity="1", price="10")

    alert = outbox.claim_next(db, holder_id="integrity-dispatcher")

    assert alert is not None
    assert alert.event_type == "FILL_NOTIFICATION_IDENTITY_INVALID"
    assert alert.severity == "CRITICAL"
    assert "side" not in dict(alert.payload)


def test_fill_notification_payload_uses_durable_economics() -> None:
    alert = SimpleNamespace(
        alert_id="alert-1", event_type="BROKER_FILL", severity="TRADE",
        payload={
            "side": "BUY", "ticker": "AAPL", "quantity": "1",
            "price": "189.25", "filled_at": NOW.isoformat(),
            "broker_order_id": "order-1"})

    payload = notification_payload(alert)

    assert payload["title"] == "BUY AAPL filled"
    assert "1 @ $189.25" in payload["body"]
    assert payload["tag"] == "alert-1"
