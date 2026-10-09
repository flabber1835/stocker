"""Health-check entry and database-clock freshness, without external services."""
from datetime import datetime, timezone
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from sentinel import alert_health, alert_liveness


AGE = "SENTINEL_AUTOMATION_ALERT_HEALTH_MAX_AGE_SECONDS"
GRACE = "SENTINEL_AUTOMATION_ALERT_STARTUP_GRACE_SECONDS"
IDENTITY = "SENTINEL_AUTOMATION_ALERT_DISPATCHER_ID"
NONFINITE = ["NaN", "inf", "-inf", "1e999"]


def health_row(*, state="HEALTHY", heartbeat_age=1, startup_age=1,
               dead_letters=0, identity="primary"):
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    return (identity, now, now, state, None, None, 0, "transport rejected", now,
            heartbeat_age, startup_age, dead_letters)


class ReadOnlyConnection:
    """Only the health SELECT is available; writes would fail the test."""
    def __init__(self, row):
        self.row = row
        self.queries = []
        self.rollbacks = 0
        self.closed = 0

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, parameters):
        assert sql.startswith("SELECT ")
        self.queries.append((sql, parameters))

    def fetchone(self):
        return self.row

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


@pytest.fixture
def entry(monkeypatch):
    for name in (AGE, GRACE, IDENTITY):
        monkeypatch.delenv(name, raising=False)
    config = SimpleNamespace(database_url="postgresql://private-health-fixture")
    connection = ReadOnlyConnection(health_row())
    contacts = []
    schemas = []
    monkeypatch.setattr(alert_liveness.SentinelConfig, "from_env", lambda: config)
    monkeypatch.setattr(alert_liveness.feed_store, "connect",
                        lambda url: contacts.append(url) or connection)
    monkeypatch.setattr(alert_liveness.schema, "require_runtime_schema",
                        lambda conn: schemas.append(conn))
    return config, connection, contacts, schemas


def test_missing_database_refuses_without_contact(entry, capsys):
    config, connection, contacts, schemas = entry
    config.database_url = ""
    assert alert_liveness.main() == 1
    assert "database URL is unset" in capsys.readouterr().err
    assert contacts == schemas == []
    assert connection.closed == 0


@pytest.mark.parametrize("name", [AGE, GRACE])
@pytest.mark.parametrize("value", NONFINITE + ["0", "-1", "", "invalid"])
def test_invalid_budget_refuses_before_database_contact(
        entry, monkeypatch, capsys, name, value):
    _, connection, contacts, schemas = entry
    monkeypatch.setenv(name, value)
    assert alert_liveness.main() == 1
    output = capsys.readouterr()
    assert "ALERT_DISPATCHER_UNHEALTHY" in output.err
    assert output.out == ""
    assert contacts == schemas == []
    assert connection.closed == 0


@pytest.mark.parametrize("state,age,start_age", [
    ("HEALTHY", 0, 0), ("HEALTHY", 30, 1000),
    ("STARTING", 1, 330), ("DEGRADED", 1, 1000)])
def test_default_boundary_uses_database_clock_and_closes_owned_connection(
        entry, capsys, state, age, start_age):
    config, connection, contacts, schemas = entry
    connection.row = health_row(state=state, heartbeat_age=age, startup_age=start_age)
    assert alert_liveness.main() == 0
    output = capsys.readouterr()
    assert output.out.strip() == (
        f"alert_dispatcher_healthy:true dispatcher=primary state={state}")
    assert output.err == ""
    assert contacts == [config.database_url]
    assert schemas == [connection]
    assert connection.rollbacks == connection.closed == 1
    assert connection.queries[0][1] == ("primary",)


def test_explicit_identity_and_valid_custom_budgets(entry, monkeypatch, capsys):
    _, connection, _, _ = entry
    monkeypatch.setenv(IDENTITY, "  alternate  ")
    monkeypatch.setenv(AGE, "45.5")
    monkeypatch.setenv(GRACE, "500.5")
    connection.row = health_row(state="STARTING", heartbeat_age=45.5,
                                startup_age=500.5, identity="alternate")
    assert alert_liveness.main() == 0
    assert "dispatcher=alternate state=STARTING" in capsys.readouterr().out
    assert connection.queries[0][1] == ("alternate",)
    assert connection.closed == 1


@pytest.mark.parametrize("row,reason", [
    (None, "no durable health row"),
    (health_row(heartbeat_age=30.001), "stale"),
    (health_row(heartbeat_age=-0.001), "stale"),
    (health_row(dead_letters=1), "dead-letter"),
    (health_row(state="FAILED"), "transport is failed"),
    (health_row(state="STARTING", startup_age=330.001), "startup grace")])
def test_unhealthy_database_fact_cannot_report_healthy(entry, capsys, row, reason):
    _, connection, _, _ = entry
    connection.row = row
    assert alert_liveness.main() == 1
    output = capsys.readouterr()
    assert reason in output.err
    assert output.out == ""
    assert connection.rollbacks == connection.closed == 1


@pytest.mark.parametrize("identity", [" ", "x" * 129])
def test_invalid_identity_is_not_substituted_with_primary(
        entry, monkeypatch, capsys, identity):
    _, connection, _, _ = entry
    monkeypatch.setenv(IDENTITY, identity)
    assert alert_liveness.main() == 1
    assert "identity" in capsys.readouterr().err
    assert connection.queries == []
    assert connection.closed == 1


@pytest.mark.parametrize("stage", ["connect", "schema", "read"])
def test_dependency_failure_reports_error_and_closes_only_owned_connection(
        entry, monkeypatch, capsys, stage):
    _, connection, _, _ = entry

    def fail(*args):
        raise OSError("private health dependency unavailable")

    if stage == "connect":
        monkeypatch.setattr(alert_liveness.feed_store, "connect", fail)
    elif stage == "schema":
        monkeypatch.setattr(alert_liveness.schema, "require_runtime_schema", fail)
    else:
        monkeypatch.setattr(connection, "execute", fail)
    assert alert_liveness.main() == 1
    output = capsys.readouterr()
    assert "OSError: private health dependency unavailable" in output.err
    assert output.out == ""
    assert connection.closed == int(stage != "connect")


@pytest.mark.parametrize("field", ["maximum_age_seconds", "startup_grace_seconds"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 0, -1])
def test_direct_health_reader_rejects_invalid_budget_before_read(field, value):
    connection = ReadOnlyConnection(health_row(state="STARTING",
        heartbeat_age=3600, startup_age=3600))
    budgets = {"maximum_age_seconds": 30, "startup_grace_seconds": 330}
    budgets[field] = value
    configuration_refusal = None
    try:
        alert_health.require_healthy(connection, dispatcher_id="primary", **budgets)
    except ValueError as exc:
        configuration_refusal = exc
    except alert_health.AlertDispatcherUnhealthy:
        pass  # A later stale-row refusal is not budget validation.
    assert configuration_refusal is not None
    assert "positive" in str(configuration_refusal)
    assert connection.queries == []
    assert connection.rollbacks == 0


@pytest.mark.parametrize("configured", [True, False])
def test_module_entry_reports_actual_exit_code(entry, capsys, configured):
    config, connection, contacts, _ = entry
    if not configured:
        config.database_url = ""
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(Path(alert_liveness.__file__)), run_name="__main__")
    assert stopped.value.code == (0 if configured else 1)
    output = capsys.readouterr()
    assert bool(output.out) is configured
    assert bool(output.err) is not configured
    assert bool(contacts) is configured
    assert connection.closed == int(configured)
