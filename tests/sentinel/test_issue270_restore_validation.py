from __future__ import annotations

from types import SimpleNamespace

import pytest

from sentinel import restore_validation
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg


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
        elif statement.startswith("SELECT cursor_name,state"):
            self.rows = []  # No prospective cash-retirement rows in this legacy fixture.
        elif statement.startswith("SELECT cursor_name,session,state"):
            assert _params == (["broker-cash-plan:v1:plan-current"],)
            self.rows = [("broker-cash-plan:v1:plan-current", "2026-08-25", {})]
        elif statement.startswith("SELECT cursor_name"):
            self.rows = [("broker-cash-plan:v1:plan-current",)]
            if self.conn.retirement_present:
                self.rows += [("broker-cash-plan:v1:retirement:legacy",),
                              ("broker-cash-plan:v1:retirement:native:claim",)]
        else:
            self.rows = []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _Connection:
    def __init__(self, *, retirement_present=False):
        self.statements = []
        self.commits = 0
        self.rollbacks = 0
        self.retirement_present = retirement_present

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


@pytest.mark.parametrize('retirement_present', [False, True])
def test_restore_validator_reconstructs_every_durable_chain(monkeypatch, retirement_present):
    from sentinel.paper import cash_retirement, policy_replacement
    account = SimpleNamespace(
        identity="deployment", takeover_epoch=4, broker="alpaca",
        broker_account_id="paper-account")
    rollout = SimpleNamespace(
        mode=SimpleNamespace(value="CONTROLLER"), version=9)
    control = SimpleNamespace(
        enabled=False, kill_switch_engaged=True, generation=12)
    cycles = []
    validated_retirements = []
    validated_replacements = []
    monkeypatch.setattr(cash_retirement, 'verify_retirements',
        lambda connection: validated_retirements.append(connection))
    monkeypatch.setattr(policy_replacement, 'verify_receipts',
        lambda connection: validated_replacements.append(connection))

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
    # This orchestration test models the legacy corpus. Real rolling closure
    # and tamper refusal are exercised in test_rolling_restore_integrity.py.
    monkeypatch.setattr(restore_validation, "_rolling_closure", lambda _c: None)
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
        lambda *_args, **_kwargs: SimpleNamespace(membership_root=None))
    monkeypatch.setattr(
        restore_validation.broker_cash, "decode_plan_baseline",
        lambda *_args, **_kwargs: SimpleNamespace(
            decision_session="2026-08-25", broker="alpaca",
            account_id="paper-account", pending_postings=()))
    monkeypatch.setattr(
        restore_validation.automation_store, "load_cycle_batch",
        lambda _c, cycle_ids: cycle_ids)
    monkeypatch.setattr(
        restore_validation.automation_integrity, "verify_restored_cycle_batch",
        lambda _c, batch, validated: cycles.extend(batch))

    conn = _Connection(retirement_present=retirement_present)
    result = restore_validation.validate_restored_database(conn)

    assert result["transaction_read_only"] is True
    assert result["command_count"] == 2
    assert result["plan_count"] == 1
    assert result["cycle_count"] == 2
    assert result["trial_verification_count"] == 2
    assert result["cash_baseline_count"] == 1
    assert validated_retirements == [conn]
    assert validated_replacements == [conn]
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
    monkeypatch.setattr(restore_validation, "_rolling_closure", lambda _c: None)
    monkeypatch.setattr(
        restore_validation.trial, "load_verifications", lambda _c: [])

    with pytest.raises(
            restore_validation.RestoreValidationRefused,
            match="without a durable account binding"):
        restore_validation.validate_restored_database(_Connection())


def test_restore_checks_legacy_and_current_posted_fill_cash(conn, monkeypatch):
    from dataclasses import replace
    from datetime import datetime, timezone
    from decimal import Decimal
    from uuid import UUID
    import psycopg
    from sentinel import authority, binding
    from sentinel.execution import journal, fill_integrity
    from sentinel.execution.alpaca import NativeBrokerFill
    from sentinel.execution.commands import Command
    from sentinel.execution.contract import BrokerInstrument, Side
    from sentinel.execution.identity import CommandIdentity
    from sentinel.execution.states import CommandState
    from sentinel.feed import runtime_schema
    from tests.sentinel.test_operational_read_projection import install_projection
    from tests.v5.test_opening import case

    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'offline-fill-cash-restore-key-' * 4)
    monkeypatch.setattr(restore_validation.feed_store, 'require_feed_schema', runtime_schema.require_feed_schema)
    install_projection(conn)
    bound = binding.bind(conn, deployment_id='restore-fill-cash', broker='alpaca',
                         broker_account_id='paper-fixture')
    _, plan = case(entries=1)
    rollout = authority.load_rollout_state(conn)
    plan = replace(plan, **bound.identity.to_dict(), rollout_mode=rollout.mode.value,
                   rollout_version=rollout.version, rollout_certificate_sha256=rollout.certificate_sha256)
    plan = replace(plan, plan_id='sentinel-' + plan.fingerprint())
    journal.save_plan(conn, plan)
    asset = BrokerInstrument('SEC-AAA', 'AAA', 'native-asset')
    command = Command(CommandIdentity(bound.identity, plan.plan_id, asset.security_id),
                      asset, Side.BUY, None, notional=Decimal(100), state=CommandState.FILLED,
                      broker_order_id=str(UUID(int=41)), filled_quantity=Decimal(1),
                      filled_average_price=Decimal(100))
    journal.save_command(conn, command)
    fill = NativeBrokerFill(broker_order_id=command.broker_order_id, client_key=command.client_key,
                            quantity=Decimal(1), price=Decimal(100), cash_amount=Decimal(-100),
                            filled_at=datetime(2026, 8, 13, 14, tzinfo=timezone.utc),
                            asset_id=asset.broker_id, side=Side.BUY, activity_id=str(UUID(int=42)), raw={})
    journal.record_fills(conn, (fill,))
    native = journal.fill_fingerprint(fill)
    current = journal.FILL_CASH_PREFIX + native
    legacy = journal.LEGACY_FILL_CASH_PREFIX + native

    def verify():
        with psycopg.connect(conn.info.dsn) as restored:
            return restore_validation.validate_restored_database(restored)

    assert verify()['transaction_read_only']
    conn.execute('UPDATE sentinel_processed_sessions SET cursor_name=%s WHERE cursor_name=%s', (legacy, current))
    conn.commit()
    assert journal.record_fills(conn, (fill,)) == 0
    assert conn.execute('SELECT cursor_name FROM sentinel_processed_sessions WHERE cursor_name IN (%s,%s)',
                        (current, legacy)).fetchall() == [(legacy,)]
    assert fill_integrity.exact_fill_economics(conn, command).cash == -100
    assert verify()['command_count'] == 1

    conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{amount}',to_jsonb('0.01'::text)) "
                 "WHERE cursor_name=%s", (legacy,))
    conn.commit()
    with pytest.raises(restore_validation.RestoreValidationRefused, match='posted fill cash.*contradicts'):
        verify()
    conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{amount}',to_jsonb('-100'::text)) "
                 "WHERE cursor_name=%s", (legacy,))
    conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) '
                 'SELECT %s,session,state FROM sentinel_processed_sessions WHERE cursor_name=%s', (current, legacy))
    conn.commit()
    with pytest.raises(restore_validation.RestoreValidationRefused, match='duplicate'):
        verify()
    with pytest.raises(ValueError, match='not bound to the owned fill'):
        fill_integrity.exact_fill_economics(conn, command)


def test_restore_database_url_escapes_password(monkeypatch):
    monkeypatch.delenv("SENTINEL_DATABASE_URL", raising=False)
    monkeypatch.setenv("SENTINEL_RESTORE_DATABASE_HOST", "restored-postgres")
    monkeypatch.setenv("SENTINEL_RESTORE_DATABASE_PASSWORD", "p@ss:/ word")

    assert restore_validation._database_url() == (  # noqa: SLF001
        "postgresql://sentinel:p%40ss%3A%2F%20word@"
        "restored-postgres:5432/sentinel")
