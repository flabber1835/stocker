from __future__ import annotations

import os
from pathlib import Path

from sentinel.automation_supervisor import (
    CallbackWatch,
    _callback_deadline_expired,
    _instance_stalled,
)


ROOT = Path(os.environ.get(
    "SENTINEL_REPO_ROOT", Path(__file__).resolve().parents[2]))


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


def test_instance_stall_is_bounded_by_lease_after_startup_grace():
    assert not _instance_stalled(
        heartbeat_age_seconds=99.0, lease_seconds=12.0,
        startup_grace_elapsed=False)
    assert not _instance_stalled(
        heartbeat_age_seconds=12.0, lease_seconds=12.0,
        startup_grace_elapsed=True)
    assert _instance_stalled(
        heartbeat_age_seconds=12.001, lease_seconds=12.0,
        startup_grace_elapsed=True)


def test_missing_initial_instance_is_fatal_after_startup_grace():
    assert not _instance_stalled(
        heartbeat_age_seconds=None, lease_seconds=12.0,
        startup_grace_elapsed=False)
    assert _instance_stalled(
        heartbeat_age_seconds=None, lease_seconds=12.0,
        startup_grace_elapsed=True)


def test_compose_uses_strict_liveness_and_bounded_failover_budget():
    text = (ROOT / "docker-compose.sentinel-automation.yml").read_text(
        encoding="utf-8")
    assert "sentinel.automation_supervisor" in text
    assert "sentinel.automation_liveness" in text
    assert "SENTINEL_AUTOMATION_LEASE_SECONDS:-12" in text
    assert "SENTINEL_AUTOMATION_HEARTBEAT_SECONDS:-3" in text
    assert "SENTINEL_AUTOMATION_CONTROL_POLL_SECONDS:-3" in text
    assert "SENTINEL_AUTOMATION_RETRY_BASE_SECONDS:-5" in text
    assert "interval: 5s" in text
    assert "retries: 2" in text


def test_off_host_standby_requires_shared_database_and_same_fencing_runtime():
    text = (ROOT / "docker-compose.sentinel-automation-standby.yml").read_text(
        encoding="utf-8")
    assert "sentinel-automation-standby:" in text
    assert (
        "SENTINEL_DATABASE_URL: "
        "${SENTINEL_DATABASE_URL:?set shared HA PostgreSQL DSN}" in text)
    assert "sentinel.automation_supervisor" in text
    assert "sentinel.automation_liveness" in text
    assert "depends_on:" not in text
    assert "SENTINEL_AUTOMATION_LEASE_SECONDS:-12" in text


def test_secondary_worker_is_hot_passive_until_live_lease_expires():
    text = (ROOT / "sentinel" / "automation_worker.py").read_text(
        encoding="utf-8")
    assert 'state="STANDBY"' in text
    assert "leader != holder_id" in text
    assert "lease_generation == control_generation" in text
    assert "expires_at > database_now" in text


def test_global_health_is_bound_to_current_lease_holder_not_latest_instance():
    text = (ROOT / "sentinel" / "automation" / "health.py").read_text(
        encoding="utf-8")
    assert "WHERE i.instance_id=l.holder_id LIMIT 1" in text
    assert "ORDER BY heartbeat_at DESC LIMIT 1" not in text
