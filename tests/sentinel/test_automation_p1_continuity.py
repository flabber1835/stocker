from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.alert_service import WebhookAlertAdapter
from sentinel.shadow_worker import EXIT_REFUSED, EXIT_RETRY, EXIT_WAITING


def test_unattended_alert_transport_requires_https():
    with pytest.raises(ValueError):
        WebhookAlertAdapter("http://example.com/hook")
    with pytest.raises(ValueError):
        WebhookAlertAdapter("https://user:pass@example.com/hook")
    WebhookAlertAdapter("https://example.com/hook")


def test_shadow_worker_exit_classes_are_distinct():
    assert len({EXIT_REFUSED, EXIT_RETRY, EXIT_WAITING}) == 3
    assert EXIT_REFUSED == 2


def test_primary_compose_supervises_shadow_and_externalizes_alerts():
    text = Path("docker-compose.sentinel-automation.yml").read_text()
    assert 'entrypoint: ["python", "-m", "sentinel.shadow_supervisor"]' in text
    assert "SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS" in text
    assert 'sentinel.shadow_supervisor", "--health"' in text
    assert "sentinel-alert-dispatcher:" in text
    assert 'entrypoint: ["python", "-m", "sentinel.alert_service"]' in text
    assert "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL" in text


def test_off_host_stack_contains_independent_silence_monitor():
    text = Path("docker-compose.sentinel-automation-standby.yml").read_text()
    assert "sentinel-alert-dispatcher-standby:" in text
    assert "SENTINEL_DATABASE_URL: ${SENTINEL_DATABASE_URL:?set shared HA PostgreSQL DSN}" in text
    assert "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL" in text


def test_trading_worker_does_not_consume_its_own_alert_outbox():
    text = Path("sentinel/automation_worker.py").read_text()
    assert "alert_wake=None" in text
    assert "control_wake=runtime.control_wake" in text


def test_health_surfaces_unresolved_broker_outcomes_after_kill():
    text = Path("sentinel/automation/health.py").read_text()
    assert "broker_outcome_unresolved" in text
    assert "KILLED_BROKER_OUTCOME_UNRESOLVED" in text
    assert "DISABLED_BROKER_OUTCOME_UNRESOLVED" in text
    for state in (
        "SEND_PENDING", "ACKNOWLEDGED", "UNKNOWN",
        "PARTIALLY_FILLED", "CANCEL_PENDING",
    ):
        assert state in text


def test_alert_service_has_direct_database_and_scheduler_silence_paths():
    text = Path("sentinel/alert_service.py").read_text()
    assert "ALERT_DISPATCHER_DATABASE_UNREACHABLE" in text
    assert "AUTOMATION_EXTERNAL_HEALTH_FAILURE" in text
    assert "SCHEDULER_STALLED" in text
    assert "SCHEDULER_OVERDUE" in text
    assert "WAITING_FOR_LEADER" in text
