from __future__ import annotations

from types import SimpleNamespace

import pytest

from sentinel import restore_validation


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, _params=None):
        self.conn.statements.append(statement)
        if statement == "SHOW transaction_read_only":
            self.rows = [("on",)]
        elif statement == "SELECT COUNT(*) FROM sentinel_commands":
            self.rows = [(2,)]
        elif statement.startswith("SELECT cycle_id"):
            self.rows = [("cycle-a",), ("cycle-b",)]
        elif statement.startswith("SELECT plan_id,decision_session"):
            self.rows = [("plan-current", "2026-08-25", "alpaca",
                          "paper-account")]
        elif statement.startswith("SELECT cursor_name"):
            self.rows = [("broker-cash-plan:v1:plan-current",)]
        else:
            self.rows = []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _Connection:
    def __init__(self):
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_restore_validator_reconstructs_every_durable_chain(monkeypatch):
    account = SimpleNamespace(
        identity="deployment", takeover_epoch=4, broker="alpaca",
        broker_account_id="paper-account")
    rollout = SimpleNamespace(
        mode=SimpleNamespace(value="CONTROLLER"), version=9)
    control = SimpleNamespace(
        enabled=False, kill_switch_engaged=True, generation=12)
    cycles = []

    monkeypatch.setattr(
        restore_validation.schema, "require_runtime_schema", lambda _c: None)
    monkeypatch.setattr(
        restore_validation.feed_store, "require_feed_schema", lambda _c: None)
    monkeypatch.setattr(
        restore_validation.authority, "load_rollout_state", lambda _c: rollout)
    monkeypatch.setattr(
        restore_validation.authority, "load_active_certificate", lambda _c: None)
    monkeypatch.setattr(
        restore_validation.administrative_authority,
        "administrative_authority_status", lambda _c: {"generation": 3})
    monkeypatch.setattr(
        restore_validation.binding, "load", lambda _c: account)
    monkeypatch.setattr(
        restore_validation.automation_store, "load_control", lambda _c: control)
    monkeypatch.setattr(
        restore_validation.journal, "latest_plan",
        lambda _c: SimpleNamespace(plan_id="plan-current"))
    monkeypatch.setattr(
        restore_validation.catchup, "resume_state", lambda _c: {"version": 5})
    monkeypatch.setattr(
        restore_validation.trial, "load_verifications", lambda _c: [{}, {}])
    monkeypatch.setattr(
        restore_validation.journal, "load_commands",
        lambda _c, _identity: (object(), object()))
    monkeypatch.setattr(
        restore_validation.journal, "terminal_recovery_checkpoint",
        lambda _c: SimpleNamespace(isoformat=lambda: "2026-08-25T12:00:00+00:00"))
    monkeypatch.setattr(
        restore_validation.broker_cash, "load_activity_state",
        lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        restore_validation.broker_cash, "load_plan_baseline",
        lambda *_args, **_kwargs: SimpleNamespace(
            decision_session="2026-08-25", broker="alpaca",
            account_id="paper-account"))
    monkeypatch.setattr(
        restore_validation.automation_store, "load_cycle",
        lambda _c, cycle_id: cycle_id)
    monkeypatch.setattr(
        restore_validation.automation_integrity, "validate_cycle_lineage",
        lambda _c, cycle: cycles.append(cycle))

    conn = _Connection()
    result = restore_validation.validate_restored_database(conn)

    assert result["transaction_read_only"] is True
    assert result["command_count"] == 2
    assert result["plan_count"] == 1
    assert result["cycle_count"] == 2
    assert result["trial_verification_count"] == 2
    assert result["cash_baseline_count"] == 1
    assert cycles == ["cycle-a", "cycle-b"]
    assert "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY" in (
        conn.statements)


def test_restore_validator_rejects_commands_without_account(monkeypatch):
    monkeypatch.setattr(
        restore_validation.schema, "require_runtime_schema", lambda _c: None)
    monkeypatch.setattr(
        restore_validation.feed_store, "require_feed_schema", lambda _c: None)
    monkeypatch.setattr(
        restore_validation.authority, "load_rollout_state",
        lambda _c: SimpleNamespace(
            mode=SimpleNamespace(value="PINNED_1_00"), version=1))
    monkeypatch.setattr(
        restore_validation.authority, "load_active_certificate", lambda _c: None)
    monkeypatch.setattr(
        restore_validation.administrative_authority,
        "administrative_authority_status", lambda _c: {"generation": 0})
    monkeypatch.setattr(restore_validation.binding, "load", lambda _c: None)
    monkeypatch.setattr(
        restore_validation.automation_store, "load_control",
        lambda _c: SimpleNamespace(
            enabled=False, kill_switch_engaged=True, generation=1))
    monkeypatch.setattr(
        restore_validation.journal, "latest_plan", lambda _c: None)
    monkeypatch.setattr(
        restore_validation.catchup, "resume_state", lambda _c: None)
    monkeypatch.setattr(
        restore_validation.trial, "load_verifications", lambda _c: [])

    with pytest.raises(
            restore_validation.RestoreValidationRefused,
            match="without a durable account binding"):
        restore_validation.validate_restored_database(_Connection())


def test_restore_database_url_escapes_password(monkeypatch):
    monkeypatch.delenv("SENTINEL_DATABASE_URL", raising=False)
    monkeypatch.setenv("SENTINEL_RESTORE_DATABASE_HOST", "restored-postgres")
    monkeypatch.setenv("SENTINEL_RESTORE_DATABASE_PASSWORD", "p@ss:/ word")

    assert restore_validation._database_url() == (  # noqa: SLF001
        "postgresql://sentinel:p%40ss%3A%2F%20word@"
        "restored-postgres:5432/sentinel")
