from __future__ import annotations

from pathlib import Path

from sentinel.automation_supervisor import (
    CallbackWatch,
    _callback_deadline_expired,
    _restart_for_health,
)


def test_callback_deadline_is_process_supervised():
    watch = CallbackWatch()
    assert not _callback_deadline_expired(
        watch, state="EXECUTE_CALLBACK", now_monotonic=100.0,
        deadline_seconds=30.0)
    assert not _callback_deadline_expired(
        watch, state="EXECUTE_CALLBACK", now_monotonic=130.0,
        deadline_seconds=30.0)
    assert _callback_deadline_expired(
        watch, state="EXECUTE_CALLBACK", now_monotonic=130.001,
        deadline_seconds=30.0)


def test_callback_watch_resets_between_phases():
    watch = CallbackWatch()
    _callback_deadline_expired(
        watch, state="PREPARE_CALLBACK", now_monotonic=10.0,
        deadline_seconds=30.0)
    assert not _callback_deadline_expired(
        watch, state="RUNNING", now_monotonic=50.0,
        deadline_seconds=30.0)
    assert not _callback_deadline_expired(
        watch, state="EXECUTE_CALLBACK", now_monotonic=100.0,
        deadline_seconds=30.0)


def test_enabled_stalled_or_overdue_scheduler_requires_restart():
    for policy in ("SCHEDULER_STALLED", "SCHEDULER_OVERDUE",
                   "WAITING_FOR_LEADER"):
        assert _restart_for_health(
            enabled=True, killed=False, operational_ready=False,
            policy_state=policy, startup_grace_elapsed=True)


def test_fail_closed_policy_states_do_not_restart_loop():
    for policy in ("DISABLED", "KILLED", "AUTHORITY_FAILED", "BLOCKED"):
        assert not _restart_for_health(
            enabled=(policy not in {"DISABLED"}),
            killed=(policy == "KILLED"), operational_ready=False,
            policy_state=policy, startup_grace_elapsed=True)


def test_compose_uses_strict_liveness_and_bounded_failover_budget():
    text = Path("docker-compose.sentinel-automation.yml").read_text()
    assert "sentinel.automation_supervisor" in text
    assert "sentinel.automation_liveness" in text
    assert "SENTINEL_AUTOMATION_LEASE_SECONDS:-12" in text
    assert "SENTINEL_AUTOMATION_HEARTBEAT_SECONDS:-3" in text
    assert "SENTINEL_AUTOMATION_CONTROL_POLL_SECONDS:-3" in text
    assert "SENTINEL_AUTOMATION_RETRY_BASE_SECONDS:-5" in text
    assert "interval: 5s" in text
    assert "retries: 2" in text


def test_off_host_standby_requires_shared_database_and_same_fencing_runtime():
    text = Path("docker-compose.sentinel-automation-standby.yml").read_text()
    assert "sentinel-automation-standby:" in text
    assert "SENTINEL_DATABASE_URL: ${SENTINEL_DATABASE_URL:?set shared HA PostgreSQL DSN}" in text
    assert "sentinel.automation_supervisor" in text
    assert "sentinel.automation_liveness" in text
    assert "depends_on:" not in text
    assert "SENTINEL_AUTOMATION_LEASE_SECONDS:-12" in text
