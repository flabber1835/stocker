from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import backup_guard, backup_runtime_authority
from sentinel.automation import store as automation_store
from sentinel.automation.model import (
    AutomationConfig,
    CallbackDeadlineExceeded,
    CycleState,
    NonRetryableCallbackRefused,
    TickAction,
    TransientInfrastructureFailure,
)
from sentinel.automation_resilience import RecoveryAutomationService
from sentinel.automation_recovery import ProductionAutomation


ROOT = Path(__file__).resolve().parents[2]


async def _noop(_context):
    return None


def _service(**config_overrides):
    config = AutomationConfig(**config_overrides)
    return RecoveryAutomationService(
        config=config,
        holder_id="recovery-test",
        refresh=_noop,
        prepare=_noop,
        recover=_noop,
        execute=_noop,
    )


def test_transient_outage_never_exhausts_activation_generation():
    service = _service(
        refresh_max_attempts=2,
        retry_base_seconds=1,
        retry_max_seconds=10,
    )
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    cycle = SimpleNamespace(diagnostic={
        "retry_phase": "REFRESH",
        "phase_attempt_count": 1000,
        "first_failure_at": (now - timedelta(days=7)).isoformat(),
    })
    terminal, diagnostic = service._failure_diagnostic(
        cycle=cycle,
        phase="REFRESH",
        exc=TransientInfrastructureFailure("provider unavailable"),
        now=now,
    )
    assert terminal is False
    assert diagnostic["callback_failure"] == "TRANSIENT_INFRASTRUCTURE"
    assert diagnostic["availability_retry_unbounded"] is True
    assert diagnostic["phase_attempt_count"] == 1001


def test_long_data_callback_restarts_after_deadline_without_blocking():
    service = _service(refresh_max_attempts=1)
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    cycle = SimpleNamespace(diagnostic={
        "retry_phase": "REFRESH", "phase_attempt_count": 40})
    terminal, diagnostic = service._failure_diagnostic(
        cycle=cycle,
        phase="REFRESH",
        exc=CallbackDeadlineExceeded("bounded refresh runtime reached"),
        now=now,
    )
    assert terminal is False
    assert diagnostic["callback_failure"] == "BOUNDED_CALLBACK_RESTART"
    assert diagnostic["bounded_checkpoint_restart"] is True


def test_execution_callback_deadline_routes_to_read_only_recovery(monkeypatch):
    service = _service(execute_max_attempts=100)
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    cycle = SimpleNamespace(cycle_id="cycle-1")
    permit = SimpleNamespace()
    captured = {}
    reconciled = SimpleNamespace(state=CycleState.RECONCILING)

    def transition(_conn, **kwargs):
        captured.update(kwargs)
        return reconciled

    monkeypatch.setattr(automation_store, "transition_cycle", transition)
    result = service._handle_callback_failure(
        object(), now=now, cycle=cycle, permit=permit,
        phase="EXECUTE",
        exc=CallbackDeadlineExceeded("execution transport boundary timed out"),
    )
    assert result.action is TickAction.RETRY_SCHEDULED
    assert result.cycle is reconciled
    assert captured["to_state"] is CycleState.RECONCILING
    assert captured["next_wake_at"] == now
    assert captured["diagnostic"]["retry_phase"] == "RECOVER"
    assert captured["diagnostic"]["direct_execution_retry_permitted"] is False


def test_unbounded_retry_backoff_saturates_without_huge_integer_growth():
    service = _service(retry_base_seconds=5, retry_max_seconds=900)
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    assert service._retry_at(now, 1_000_000) == now + timedelta(seconds=900)


class _Conn:
    def __init__(self):
        self.rollbacks = 0
        self.closed = False

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_temporary_backup_loss_is_typed_transient(monkeypatch):
    runtime = object.__new__(ProductionAutomation)
    conn = _Conn()
    runtime.connect = lambda: conn
    monkeypatch.setattr(
        backup_runtime_authority, "require", lambda *_a, **_k: None)
    monkeypatch.setattr(
        backup_guard, "require_writes_permitted",
        lambda *_a, **_k: (_ for _ in ()).throw(
            backup_guard.BackupUnavailable("mount offline")),
    )
    with pytest.raises(TransientInfrastructureFailure, match="temporarily"):
        runtime._require_backup_for_new_mutation("test mutation")
    assert conn.rollbacks == 1
    assert conn.closed is True


def test_backup_integrity_refusal_remains_terminal(monkeypatch):
    runtime = object.__new__(ProductionAutomation)
    conn = _Conn()
    runtime.connect = lambda: conn
    monkeypatch.setattr(
        backup_runtime_authority, "require",
        lambda *_a, **_k: (_ for _ in ()).throw(
            backup_runtime_authority.BackupRuntimeRefused("bad marker")),
    )
    with pytest.raises(NonRetryableCallbackRefused, match="integrity"):
        runtime._require_backup_for_new_mutation("test mutation")


def test_wal_restore_horizon_crosses_log_boundary_contiguously():
    result = backup_runtime_authority._expected_wals(
        "0000000100000000000000FE",
        "000000010000000100000001",
        segment_size=16 * 1024 * 1024,
    )
    assert result == (
        "0000000100000000000000FE",
        "0000000100000000000000FF",
        "000000010000000100000000",
        "000000010000000100000001",
    )


def test_wal_restore_horizon_refuses_timeline_gap():
    with pytest.raises(backup_runtime_authority.BackupRuntimeRefused,
                       match="different timelines"):
        backup_runtime_authority._expected_wals(
            "000000010000000000000001",
            "000000020000000000000002",
            segment_size=16 * 1024 * 1024,
        )


def test_cold_boot_backup_mount_marker_is_enforced_in_archive_and_health():
    archive = (ROOT / "scripts" / "sentinel-archive-wal.sh").read_text(
        encoding="utf-8")
    overlay = (ROOT / "docker-compose.sentinel-backup.yml").read_text(
        encoding="utf-8")
    helper = (ROOT / "scripts" / "sentinel-backup-lib.sh").read_text(
        encoding="utf-8")
    marker = ".sentinel-independent-durable-target-v1"
    assert marker in archive
    assert "independent durable-target marker is missing" in archive
    assert marker in overlay
    assert "/sentinel-backup/wal" in overlay
    assert "/sentinel-backup/base" in overlay
    assert marker in helper
    assert "only AFTER the host/device" in helper


def test_unattended_services_enable_runtime_restore_horizon():
    compose = (ROOT / "docker-compose.sentinel-automation.yml").read_text(
        encoding="utf-8")
    assert compose.count("SENTINEL_RUNTIME_BACKUP_AUTHORITY: REQUIRED_V1") >= 2
    assert "SENTINEL_AUTOMATION_ALERT_MAX_ATTEMPTS:-1000000" in compose


def test_shadow_timeout_is_restartable_not_terminal_latch():
    text = (ROOT / "sentinel" / "shadow_supervisor.py").read_text(
        encoding="utf-8")
    assert "if code == EXIT_RETRY:" in text
    assert "code in {EXIT_RETRY, 124}" not in text
    assert '"7200"' in text
