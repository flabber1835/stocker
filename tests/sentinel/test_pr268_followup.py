from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import automation_liveness, automation_recovery, backup_guard
from sentinel.automation.model import NonRetryableCallbackRefused
from sentinel.feed import outage_recovery
from sentinel import shadow_worker
from sentinel.panel import app as panel_app


class _Cursor:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, *_args, **_kwargs):
        return None

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, row=None):
        self.row = row

    def cursor(self):
        return _Cursor(self.row)

    def rollback(self):
        return None

    def close(self):
        return None


def test_automation_liveness_refuses_healthy_but_not_operational(monkeypatch):
    now = datetime.now(timezone.utc)
    health = SimpleNamespace(
        enabled=True,
        kill_switch_engaged=False,
        leader_holder="worker-1",
        scheduler_overdue=False,
        healthy=True,
        operational_ready=False,
        model_dump=lambda **_kwargs: {
            "healthy": True,
            "operational_ready": False,
        },
    )
    monkeypatch.setattr(
        automation_liveness.SentinelConfig, "from_env",
        lambda: SimpleNamespace(database_url="postgresql://test"))
    monkeypatch.setattr(
        automation_liveness, "config_from_env",
        lambda: SimpleNamespace(lease_seconds=60))
    monkeypatch.setattr(automation_liveness, "read_health", lambda _conn: health)
    monkeypatch.setattr(
        automation_liveness.feed_store, "connect",
        lambda _dsn: _Conn((now, now)))
    monkeypatch.setattr(
        automation_liveness, "HOLDER_FILE",
        SimpleNamespace(read_text=lambda **_kwargs: "worker-1"))

    assert automation_liveness.main() == 1


def test_automation_liveness_preserves_intentional_disabled_semantics(monkeypatch):
    health = SimpleNamespace(
        enabled=False,
        kill_switch_engaged=False,
        healthy=True,
        operational_ready=False,
        model_dump=lambda **_kwargs: {"healthy": True, "enabled": False},
    )
    monkeypatch.setattr(
        automation_liveness.SentinelConfig, "from_env",
        lambda: SimpleNamespace(database_url="postgresql://test"))
    monkeypatch.setattr(
        automation_liveness, "config_from_env",
        lambda: SimpleNamespace(lease_seconds=60))
    monkeypatch.setattr(automation_liveness, "read_health", lambda _conn: health)
    monkeypatch.setattr(
        automation_liveness.feed_store, "connect", lambda _dsn: _Conn())

    assert automation_liveness.main() == 0


def test_outage_current_frontier_does_not_skip_incoherence_repair(monkeypatch):
    conn = object()
    calls = []
    monkeypatch.setattr(
        outage_recovery.store, "latest_visible_session", lambda _conn: "2026-08-25")
    monkeypatch.setattr(
        outage_recovery.publication, "coherence",
        lambda _conn: SimpleNamespace(coherent=False))
    monkeypatch.setattr(
        outage_recovery.publication, "chain_gaps", lambda _conn: [])
    monkeypatch.setattr(
        outage_recovery.backup_guard, "require_writes_permitted",
        lambda _conn, *, operation: calls.append(("backup", operation)))
    monkeypatch.setattr(
        outage_recovery.ingest, "daily",
        lambda _conn, *, today: calls.append(("daily", today)))
    monkeypatch.setattr(
        outage_recovery.publication, "assert_coherent", lambda _conn: None)

    result = outage_recovery.catch_up(conn, target_session="2026-08-25")

    assert result.mode == "DAILY"
    assert ("daily", "2026-08-25") in calls


def test_outage_current_coherent_frontier_remains_read_only(monkeypatch):
    conn = object()
    monkeypatch.setattr(
        outage_recovery.store, "latest_visible_session", lambda _conn: "2026-08-25")
    monkeypatch.setattr(
        outage_recovery.publication, "coherence",
        lambda _conn: SimpleNamespace(coherent=True))
    monkeypatch.setattr(
        outage_recovery.publication, "chain_gaps", lambda _conn: [])
    monkeypatch.setattr(
        outage_recovery.backup_guard, "require_writes_permitted",
        lambda *_args, **_kwargs: pytest.fail("clean ALREADY_CURRENT must not mutate"))

    result = outage_recovery.catch_up(conn, target_session="2026-08-25")
    assert result.mode == "ALREADY_CURRENT"


def test_backup_archive_mode_misconfiguration_is_not_retryable(monkeypatch):
    result = backup_guard.BackupGuardStatus(
        state="FENCED", archive_mode="off", last_success_age_seconds=None,
        unresolved_failure=False, failed_count=0)
    monkeypatch.setattr(
        backup_guard, "_resolved_for_mutation", lambda *_args, **_kwargs: result)

    with pytest.raises(backup_guard.BackupConfigurationRefused):
        backup_guard.require_writes_permitted(object(), operation="test")


def test_backup_target_outage_remains_retryable(monkeypatch):
    result = backup_guard.BackupGuardStatus(
        state="FENCED", archive_mode="on", last_success_age_seconds=200000,
        unresolved_failure=True, failed_count=2)
    monkeypatch.setattr(
        backup_guard, "_resolved_for_mutation", lambda *_args, **_kwargs: result)

    with pytest.raises(backup_guard.BackupUnavailable):
        backup_guard.require_writes_permitted(object(), operation="test")


def test_shadow_worker_only_calls_transient_backup_failure_availability():
    assert shadow_worker._availability_failure(
        backup_guard.BackupUnavailable("target offline"))
    assert shadow_worker._availability_failure(
        backup_guard.BackupWriteFenced("legacy transient fence"))
    assert not shadow_worker._availability_failure(
        backup_guard.BackupConfigurationRefused("archive_mode=off"))


def test_automation_latches_backup_configuration_refusal(monkeypatch):
    runtime = object.__new__(automation_recovery.ProductionAutomation)
    monkeypatch.setattr(runtime, "connect", lambda: _Conn())

    def refuse(_conn, *, operation):
        raise backup_guard.BackupConfigurationRefused(
            f"{operation}: archive_mode=off")

    monkeypatch.setattr(
        automation_recovery.backup_guard, "require_writes_permitted", refuse)
    with pytest.raises(NonRetryableCallbackRefused):
        runtime._require_backup_for_new_mutation("automation plan preparation")


def test_segment_panel_says_marker_is_not_sufficient():
    text = Path(panel_app.__file__).read_text()
    assert "approval is necessary" in text
    assert "but NOT sufficient" in text
    assert "fresh COMPLETE/RUNNING flat" in text
    assert "no working orders or durable in-flight" in text
