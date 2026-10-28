"""Original worker incident clocks and recipient-bound recovery Web Push."""
from datetime import datetime, timezone
import inspect
import json
import re
import textwrap
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from sentinel import web_push
from sentinel.automation import outbox
from sentinel.feed import store
from tests.sentinel.test_operator_monitoring import (
    _add_subscription, _subscription_material, _vapid, db, issue369_pg,
)


NOW = datetime(2026, 10, 23, 20, 7, tzinfo=timezone.utc)
OBSERVED = "2026-10-23T20:01:00+00:00"


def _alert(event="SHADOW_DEPENDENCY_UNAVAILABLE", severity="WARN", **payload):
    return SimpleNamespace(alert_id="a" * 64, event_type=event,
                           severity=severity, created_at=NOW, payload=payload)


@pytest.mark.parametrize("code,phrase", [
    ("CORPUS_LOCK_BUSY", "Market-data publication lock is busy"),
    ("WRITER_LOCK_BUSY", "Strategy writer lock is busy"),
    ("DATABASE_UNAVAILABLE", "Database temporarily unavailable"),
    ("WORKER_BUDGET_EXHAUSTED", "worker time budget"),
    ("BACKUP_WRITE_FENCED", "Backup write permission is fenced"),
])
def test_dependency_copy_names_only_the_actual_typed_cause_and_original_time(code, phrase):
    value = web_push.notification_payload(_alert(
        cause_code=code, operation_stage="ACQUISITION_LOCK", observed_at=OBSERVED,
        detail="private exception text must never escape", exception_type="private.Type"))
    assert value["title"] == "Strategy update retrying"
    assert phrase in value["body"]
    assert "acquiring the data-update lock" in value["body"]
    assert "will retry" in value["body"]
    assert "Oct 23, 2026 at 1:01 PM PDT (Pacific)" in value["body"]
    assert "1:07 PM" not in value["body"]
    assert "private" not in json.dumps(value)
    assert "worker stopped" not in value["body"]
    if code != "BACKUP_WRITE_FENCED":
        assert "backup" not in value["body"].lower()


@pytest.mark.parametrize("code,stage", [(None, None), ("UNKNOWN", "secret-stage"),
                                       ([], {}), ("DEPENDENCY_UNAVAILABLE", "SHADOW_ADVANCE")])
def test_legacy_or_malformed_cause_remains_unknown_without_generic_speculation(code, stage):
    value = web_push.notification_payload(_alert(
        cause_code=code, operation_stage=stage, detail="lock, database, backup or budget"))
    assert "exact cause was not recorded" in value["body"]
    assert "event time unavailable; notification recorded" in value["body"]
    assert "Oct 23, 2026 at 1:07 PM PDT (Pacific)" in value["body"]
    assert "secret-stage" not in value["body"]
    assert "backup" not in value["body"].lower()


@pytest.mark.parametrize("clock", [None, "not a clock", "2026-10-23T20:01:00",
                                    1792785660, "x" * 100, "2026-10-23T20:07:06Z",
                                    "0001-01-01T00:00:00Z", "9999-12-31T23:59:59-12:00"])
def test_invalid_original_clock_does_not_claim_a_failure_time(clock):
    value = web_push.notification_payload(_alert(observed_at=clock))
    assert "event time unavailable; notification recorded" in value["body"]
    assert "1:07 PM PDT (Pacific)" in value["body"]


def test_clock_display_includes_calendar_day_and_winter_zone():
    alert = _alert(observed_at="2026-12-02T07:01:00Z")
    alert.created_at = datetime(2026, 12, 2, 7, 2, tzinfo=timezone.utc)
    value = web_push.notification_payload(alert)
    assert "Dec 1, 2026 at 11:01 PM PST (Pacific)" in value["body"]


def test_missing_legacy_event_and_recording_clocks_remain_explicit():
    alert = _alert()
    alert.created_at = NOW.replace(tzinfo=None)
    assert web_push.notification_payload(alert)["body"].endswith("event time unavailable")


def test_recovery_copy_distinguishes_warning_and_verified_update_from_trading_plan():
    value = web_push.notification_payload(_alert("SHADOW_DEPENDENCY_RECOVERED", "INFO",
        warning_alert_id="b" * 64, warning_observed_at=OBSERVED,
        recovered_at="2026-10-23T20:06:00Z"))
    assert value["title"] == "Strategy update verified"
    assert "Dependency warning: Oct 23, 2026 at 1:01 PM PDT (Pacific)" in value["body"]
    assert "Update verified: Oct 23, 2026 at 1:06 PM PDT (Pacific)" in value["body"]
    assert "See dashboard for trading-plan status" in value["body"]


def test_legacy_recovery_does_not_invent_original_warning_time():
    body = web_push.notification_payload(_alert("SHADOW_DEPENDENCY_RECOVERED", "INFO"))["body"]
    assert "original warning time unavailable" in body
    assert "event time unavailable; notification recorded" in body


@pytest.mark.parametrize("warning,recovered", [
    ("2026-10-23T20:06:00Z", "2026-10-23T20:01:00Z"),
    (OBSERVED, "2026-10-23T20:07:06Z"),
    ("0001-01-01T00:00:00Z", "2026-10-23T20:06:00Z"),
    (OBSERVED, "9999-12-31T23:59:59-12:00"),
    (OBSERVED, "2026-10-23T20:06:00"),
])
def test_future_reversed_or_unsafe_recovery_clocks_remain_explicitly_unavailable(warning, recovered):
    body = web_push.notification_payload(_alert("SHADOW_DEPENDENCY_RECOVERED", "INFO",
        warning_observed_at=warning, recovered_at=recovered))["body"]
    assert "original warning time unavailable" in body
    assert "event time unavailable; notification recorded Oct 23, 2026 at 1:07 PM PDT" in body


def test_unsafe_recorded_clock_never_overflows_the_notification_renderer():
    alert = _alert(observed_at="0001-01-01T00:00:00Z")
    alert.created_at = datetime(1, 1, 1, tzinfo=timezone.utc)
    assert web_push.notification_payload(alert)["body"].endswith("event time unavailable")


def test_source_data_pending_refresh_names_the_actual_wait():
    value = web_push.notification_payload(_alert("AUTOMATION_RETRY_SCHEDULED", "WARN",
        reason="SourceDataPending", detail={"retry_phase": "REFRESH", "first_failure_at": OBSERVED}))
    assert value["title"] == "Closing data not ready"
    assert "preparation will retry" in value["body"]
    assert "Oct 23, 2026 at 1:01 PM PDT (Pacific)" in value["body"]


def test_unquiet_closing_data_wait_requests_review_without_inventing_a_cause():
    value = web_push.notification_payload(_alert("AUTOMATION_RETRY_SCHEDULED", "WARN",
        reason="ClosingDataPending", detail={"retry_phase": "REFRESH", "first_failure_at": OBSERVED}))
    assert value["title"] == "Closing-data preparation needs review"
    assert "see dashboard" in value["body"]
    assert "Oct 23, 2026 at 1:01 PM PDT (Pacific)" in value["body"]
    assert "deadline" not in value["body"].lower()
    assert "crash" not in value["body"].lower()
    assert "verified" not in value["body"].lower()


def test_later_unquiet_closing_wait_keeps_original_failure_clock():
    alert = _alert("AUTOMATION_RETRY_SCHEDULED", "WARN", reason="ClosingDataPending",
        detail={"retry_phase": "REFRESH", "first_failure_at": OBSERVED})
    original = web_push.notification_payload(alert)
    alert.created_at = datetime(2026, 10, 23, 21, 10, tzinfo=timezone.utc)
    assert web_push.notification_payload(alert) == original


def test_later_source_retry_keeps_original_failure_time_instead_of_delivery_time():
    alert = _alert("AUTOMATION_RETRY_SCHEDULED", "WARN", reason="SourceDataPending",
                   detail={"retry_phase": "REFRESH", "first_failure_at": OBSERVED})
    original = web_push.notification_payload(alert)
    alert.created_at = datetime(2026, 10, 23, 21, 10, tzinfo=timezone.utc)
    assert web_push.notification_payload(alert) == original


@pytest.mark.parametrize("clock", [None, "2026-10-23T20:01:00", "2026-10-23T20:07:06Z"])
def test_source_wait_with_missing_or_invalid_original_time_labels_recording_time(clock):
    value = web_push.notification_payload(_alert("AUTOMATION_RETRY_SCHEDULED", "WARN",
        reason="SourceDataPending", detail={"retry_phase": "REFRESH", "first_failure_at": clock}))
    assert value["title"] == "Closing data not ready"
    assert "event time unavailable; notification recorded Oct 23, 2026 at 1:07 PM PDT" in value["body"]


@pytest.mark.parametrize("event,severity,payload,title,body", [
    ("BROKER_FILL", "TRADE", {"side": "BUY", "ticker": "PANW", "quantity": "3",
       "price": "354.52", "filled_at": OBSERVED}, "BUY PANW filled", f"3 @ $354.52 · {OBSERVED}"),
    ("PUSH_ENROLLMENT_TEST", "INFO", {}, "Caesar's Palace notifications enabled",
       "Test notification requested from this device."),
    ("PAPER_PLAN_READY", "INFO", {"effective_session": "2026-10-26", "reason": "original plan"},
       "Paper trades planned for 2026-10-26", "original plan"),
    ("SHADOW_DEPENDENCY_UNAVAILABLE", "CRITICAL", {"reason": "original critical reason"},
       "Caesar's Palace — action required", "original critical reason"),
    ("AUTOMATION_RETRY_SCHEDULED", "CRITICAL", {"reason": "SourceDataPending",
       "detail": {"retry_phase": "REFRESH"}}, "Caesar's Palace — action required", "SourceDataPending"),
    ("AUTOMATION_RETRY_SCHEDULED", "WARN", {"reason": "SourceDataPending",
       "detail": {"retry_phase": "EXECUTE"}}, "Caesar's Palace — automatic recovery", "SourceDataPending"),
])
def test_existing_fill_enrollment_plan_and_critical_payloads_are_unchanged(event, severity, payload, title, body):
    value = web_push.notification_payload(_alert(event, severity, **payload))
    assert value == {"schema": "caesars-palace.web-push/1", "alert_id": "a" * 64,
        "title": title, "body": body, "tag": "a" * 64, "url": "/",
        "icon": "/static/caesars-palace-192.png", "badge": "/static/caesars-palace-192.png"}


def _adapter(pg, calls):
    return web_push.WebPushAlertAdapter(
        connection_factory=lambda: store.connect(pg.sync_dsn), credentials=_vapid(),
        sender=lambda endpoint, *_: calls.append(endpoint) or 201)


def _delivered_warning(conn, pg, *, suffix="warned", event="SHADOW_DEPENDENCY_UNAVAILABLE", severity="WARN"):
    endpoint = _add_subscription(conn, suffix)
    alert = outbox.enqueue(conn, idempotency_key="dependency-warning", event_type=event,
                           severity=severity, payload={"observed_at": OBSERVED})
    claimed = outbox.claim_next(conn, holder_id="warning-sender")
    calls = []
    _adapter(pg, calls).deliver(claimed, claimed.idempotency_key)
    outbox.mark_delivered(conn, alert_id=claimed.alert_id, holder_id=claimed.delivery_holder,
                          attempt=claimed.attempt_count)
    assert calls == [endpoint]
    return alert, endpoint


def _recovery(conn, warning):
    return outbox.enqueue(conn, idempotency_key="dependency-recovery:" + warning.alert_id,
        event_type="SHADOW_DEPENDENCY_RECOVERED", severity="INFO",
        payload={"warning_alert_id": warning.alert_id, "warning_observed_at": OBSERVED,
                 "recovered_at": NOW.isoformat()})


def test_recovery_adapter_pushes_only_to_devices_with_delivered_warning(db, issue369_pg):
    warning, endpoint = _delivered_warning(db, issue369_pg)
    unrelated = _add_subscription(db, "unwarned-before-recovery", material=17)
    recovery = _recovery(db, warning)
    calls = []
    adapter = _adapter(issue369_pg, calls)
    adapter.deliver(recovery, recovery.idempotency_key)
    adapter.deliver(recovery, recovery.idempotency_key)
    assert calls == [endpoint] and unrelated not in calls
    assert db.execute("SELECT recipient_count FROM sentinel_web_push_fanouts WHERE alert_id=%s",
                      (recovery.alert_id,)).fetchone() == (1,)
    assert db.execute("SELECT state FROM sentinel_web_push_deliveries WHERE alert_id=%s",
                      (recovery.alert_id,)).fetchall() == [("DELIVERED",)]


@pytest.mark.parametrize("damage", ["warning_not_delivered", "receipt_missing", "receipt_not_delivered",
                                    "wrong_event", "wrong_severity"])
def test_recovery_needs_original_warning_and_per_device_delivery_proof(db, issue369_pg, damage):
    warning, _ = _delivered_warning(db, issue369_pg)
    if damage == "warning_not_delivered":
        db.execute("UPDATE sentinel_alert_outbox SET state='PENDING' WHERE alert_id=%s", (warning.alert_id,))
    elif damage == "receipt_missing":
        db.execute("DELETE FROM sentinel_web_push_deliveries WHERE alert_id=%s", (warning.alert_id,))
    elif damage == "receipt_not_delivered":
        db.execute("UPDATE sentinel_web_push_deliveries SET state='PENDING',delivered_at=NULL WHERE alert_id=%s", (warning.alert_id,))
    elif damage == "wrong_event":
        db.execute("UPDATE sentinel_alert_outbox SET event_type='SYSTEM_RECOVERED' WHERE alert_id=%s", (warning.alert_id,))
    else:
        db.execute("UPDATE sentinel_alert_outbox SET severity='CRITICAL' WHERE alert_id=%s", (warning.alert_id,))
    db.commit()
    recovery = _recovery(db, warning)
    with pytest.raises(web_push.WebPushDeliveryFailure):
        _adapter(issue369_pg, []).deliver(recovery, recovery.idempotency_key)


def test_explicit_browser_successor_keeps_warning_obligation_but_new_enrollment_does_not(
        db, issue369_pg, monkeypatch):
    from sentinel.panel import app
    warning, old_endpoint = _delivered_warning(db, issue369_pg)
    origin = "https://caesars-palace.tailnet.example"
    new_endpoint = "https://push.example.test/authenticated-successor"
    p256dh, auth = _subscription_material(19)
    monkeypatch.setenv("SENTINEL_DATABASE_URL", issue369_pg.sync_dsn)
    monkeypatch.setenv("SENTINEL_PUBLIC_ORIGIN", origin)
    response = TestClient(app.app).post("/push/subscriptions/refresh", headers={"Origin": origin},
        json={"previous_endpoint": old_endpoint, "subscription": {"endpoint": new_endpoint,
               "keys": {"p256dh": p256dh, "auth": auth}}})
    assert response.status_code == 200
    _add_subscription(db, "unrelated-device", material=23)
    recovery = _recovery(db, warning)
    calls = []
    _adapter(issue369_pg, calls).deliver(recovery, recovery.idempotency_key)
    assert calls == [new_endpoint]


def test_ordinary_info_remains_quiet_while_fill_and_critical_still_fan_out(db, issue369_pg):
    endpoint = _add_subscription(db, "existing-device")
    calls = []
    adapter = _adapter(issue369_pg, calls)
    for event in ("SYSTEM_RECOVERED", "SHADOW_DEPENDENCY_HEARTBEAT", "SHADOW_DEPENDENCY_RECOVERED_OTHER"):
        quiet = outbox.enqueue(db, idempotency_key=event, event_type=event,
                               severity="INFO", payload={"reason": "ordinary information"})
        adapter.deliver(quiet, quiet.idempotency_key)
    assert not calls
    assert db.execute("SELECT COUNT(*) FROM sentinel_web_push_fanouts").fetchone() == (0,)
    for event, severity in (("BROKER_FILL", "TRADE"), ("AUTOMATION_BLOCKED", "CRITICAL")):
        alert = outbox.enqueue(db, idempotency_key=event, event_type=event,
                               severity=severity, payload={"reason": "existing alert"})
        adapter.deliver(alert, alert.idempotency_key)
    assert calls == [endpoint, endpoint]


def test_removed_recovery_info_exemption_is_caught_by_transport_regression(db, issue369_pg, monkeypatch):
    source = textwrap.dedent(inspect.getsource(web_push.WebPushAlertAdapter.deliver))
    changed, replacements = re.subn(r',\s*"SHADOW_DEPENDENCY_RECOVERED"(?=})', "", source)
    assert replacements == 1
    namespace = {}
    exec(compile(changed, "recovery-push-falsifier", "exec"),
         web_push.__dict__, namespace)
    monkeypatch.setattr(web_push.WebPushAlertAdapter, "deliver", namespace["deliver"])
    with pytest.raises(AssertionError):
        test_recovery_adapter_pushes_only_to_devices_with_delivered_warning(db, issue369_pg)


def test_removed_warning_receipt_guard_is_caught_by_transport_regression(db, issue369_pg, monkeypatch):
    source = textwrap.dedent(inspect.getsource(web_push.WebPushAlertAdapter._initialize_recovery_fanout))
    needle = '" WHERE alert_id=%s AND state=\'DELIVERED\'"'
    assert source.count(needle) == 1
    delivery_clock = '" AND delivered_at<=%s ORDER BY subscription_id"'
    assert source.count(delivery_clock) == 1
    changed = source.replace(needle, '" WHERE alert_id=%s"').replace(
        delivery_clock, '" AND (delivered_at<=%s OR delivered_at IS NULL) ORDER BY subscription_id"')
    namespace = {}
    exec(compile(changed, "warning-receipt-falsifier", "exec"),
         web_push.__dict__, namespace)
    monkeypatch.setattr(web_push.WebPushAlertAdapter, "_initialize_recovery_fanout",
                        namespace["_initialize_recovery_fanout"])
    with pytest.raises(pytest.fail.Exception):
        test_recovery_needs_original_warning_and_per_device_delivery_proof(
            db, issue369_pg, "receipt_not_delivered")


__all__ = ["db", "issue369_pg"]
