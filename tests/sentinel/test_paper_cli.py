"""Focused wiring tests for the paper preparation and execution commands."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel.cli import main as cli
from sentinel import authority, paper, schema
from sentinel.cli import _shared as cli_shared
from sentinel.cli import authority as authority_cli
from sentinel.cli import automation as automation_cli
from sentinel.cli import paper as paper_cli
from sentinel.config import DEFAULT_BASE_URL, SentinelConfig
from sentinel.controller import frozen_rule
from sentinel.execution import alpaca, contract, executor, journal
from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerInstrument,
    BrokerObservation,
    BrokerOrder,
    BrokerPosition,
    Side,
)
from sentinel.execution.states import CommandState, RuntimeState
from sentinel.feed import store as feed_store
from sentinel import guarded_administration


@pytest.fixture(autouse=True)
def _authorized_runtime_surface(monkeypatch, tmp_path):
    marker = tmp_path / "authorized-runtime-v1"
    marker.write_bytes(cli_shared.AUTHORIZED_RUNTIME_MARKER_BYTES)
    monkeypatch.setattr(cli_shared, "AUTHORIZED_RUNTIME_MARKER", marker)
    monkeypatch.setenv(
        cli_shared.AUTHORIZED_RUNTIME_ENV, cli_shared.AUTHORIZED_RUNTIME_VALUE)


class _Connection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _config() -> SentinelConfig:
    return SentinelConfig(
        alpaca_key="PKTESTKEY1234", alpaca_secret="secret",
        base_url=DEFAULT_BASE_URL, state_dir=Path("/tmp/sentinel-test"),
        max_cycles=1, poll_seconds=0, database_url="postgresql://test/db")


def _wire_database(monkeypatch, calls):
    conn = _Connection()
    monkeypatch.setattr(
        feed_store, "connect",
        lambda url: calls.append(("connect", url)) or conn)
    monkeypatch.setattr(
        feed_store, "require_feed_schema",
        lambda actual: calls.append(("feed_schema", actual)))
    monkeypatch.setattr(
        schema, "ensure_schema",
        lambda actual: calls.append(("behavior_schema", actual)))
    return conn


def _execution_args():
    return SimpleNamespace(
        confirm_paper_account="paper-123", confirm_plan_id="plan-456",
        confirm_effective_session="2026-08-13",
        confirm_submit_paper_orders=True)


def _execution_result(session):
    return paper.ExecutionResult(
        plan=SimpleNamespace(to_dict=lambda: {"plan_id": "plan-456"}),
        preflight=SimpleNamespace(to_dict=lambda: {"clean": True}),
        session=session)


def _wire_administrative_inspection(monkeypatch):
    grant = object()
    guard = object()
    monkeypatch.setattr(authority_cli, "_administrative_epoch", lambda *a, **k: 1)
    monkeypatch.setattr(
        authority_cli, "_authorized_administrative_access",
        lambda *a, **k: (grant, guard))
    monkeypatch.setattr(
        guarded_administration, "GuardedAdministrativeExecutionBroker",
        lambda *, inner, grant, guard: (
            "guarded-admin", inner, grant, guard))
    return grant, guard


def _inspection_result():
    account = BrokerAccountSnapshot(
        identity=BrokerAccountIdentity("alpaca", "paper-123"),
        equity=Decimal("12345.67"), cash=Decimal("2345.67"),
        buying_power=Decimal("2345.67"), multiplier=Decimal(1),
        status="ACTIVE")
    instrument = BrokerInstrument(
        security_id="SEC-AAA", symbol="AAA", broker_id="asset-aaa")
    observation = BrokerObservation(
        observed_at=dt.datetime(2026, 8, 12, 20, tzinfo=dt.timezone.utc),
        positions=(BrokerPosition(instrument, Decimal("5.25")),),
        orders=(BrokerOrder(
            broker_order_id="order-1", client_key=None,
            instrument=instrument, side=Side.SELL,
            state=CommandState.ACKNOWLEDGED, quantity=Decimal(2)),))
    return paper.PaperAccountInspection(
        endpoint=DEFAULT_BASE_URL, expected_account="paper-123",
        account=account, observation=observation, binding=None)


def test_inspect_builds_typed_adapter_and_prints_complete_read_only_book(
        monkeypatch, capsys):
    calls = []
    conn = _Connection()
    monkeypatch.setattr(
        feed_store, "connect",
        lambda url: calls.append(("connect", url)) or conn)
    resolver = object()
    broker = object()
    monkeypatch.setattr(
        paper, "build_security_resolver",
        lambda actual, session: calls.append(
            ("resolver", actual, session)) or resolver)
    monkeypatch.setattr(
        paper_cli, "build_execution_broker",
        lambda config, *, resolve_security_id: calls.append(
            ("broker", config, resolve_security_id)) or broker)

    async def inspect(**kwargs):
        calls.append(("inspect", kwargs))
        return _inspection_result()

    monkeypatch.setattr(paper, "inspect_paper_account", inspect)
    grant, guard = _wire_administrative_inspection(monkeypatch)

    assert asyncio.run(paper_cli._inspect_paper_account(
        _config(), SimpleNamespace(
            deployment_id="nas-01", expect_account="paper-123"))) == cli.EXIT_OK

    output = json.loads(capsys.readouterr().out)
    assert output["endpoint"] == DEFAULT_BASE_URL
    assert output["account"] == {
        "broker": "alpaca", "account_id": "paper-123", "status": "ACTIVE",
        "trading_blocked": False, "account_blocked": False,
        "trade_suspended_by_user": False, "multiplier": "1",
        "equity": "12345.67", "cash": "2345.67",
        "buying_power": "2345.67"}
    assert output["observation_complete"] is True
    assert output["binding_state"] == "UNBOUND"
    assert output["broker_mutations_permitted"] is False
    assert output["positions"][0]["quantity"] == "5.25"
    assert output["working_open_orders"][0]["remaining_quantity"] == "2"
    assert calls[-1][1] == {
        "conn": conn,
        "broker": ("guarded-admin", broker, grant, guard),
        "base_url": DEFAULT_BASE_URL,
        "expected_account": "paper-123"}
    assert conn.closed


def test_inspect_does_not_ensure_or_write_database_schemas(monkeypatch):
    conn = _Connection()
    monkeypatch.setattr(feed_store, "connect", lambda _url: conn)
    monkeypatch.setattr(
        feed_store, "require_feed_schema",
        lambda _conn: (_ for _ in ()).throw(
            AssertionError("inspection wrote feed schema")))
    monkeypatch.setattr(
        schema, "ensure_schema",
        lambda _conn: (_ for _ in ()).throw(
            AssertionError("inspection wrote behavioral schema")))
    monkeypatch.setattr(
        paper, "build_security_resolver", lambda _conn, _session: object())
    monkeypatch.setattr(
        paper_cli, "build_execution_broker",
        lambda _config, *, resolve_security_id: object())
    monkeypatch.setattr(
        paper, "inspect_paper_account",
        lambda **_kwargs: (_ for _ in ()).throw(
            paper.PaperActivationRefused("stop after read-only wiring")))
    _wire_administrative_inspection(monkeypatch)

    assert asyncio.run(paper_cli._inspect_paper_account(
        _config(), SimpleNamespace(
            deployment_id="nas-01", expect_account="paper-123"))) \
        == cli.EXIT_NOT_ESTABLISHED
    assert conn.closed


def test_prepare_builds_resolver_after_schemas_and_prints_json(
        monkeypatch, capsys):
    calls = []
    conn = _wire_database(monkeypatch, calls)
    resolver = object()
    broker = object()

    def build_resolver(actual, session):
        calls.append(("resolver", actual, session))
        return resolver

    def build_broker(config, *, resolve_security_id):
        calls.append(("broker", config, resolve_security_id))
        return broker

    async def prepare(**kwargs):
        calls.append(("prepare", kwargs))
        return SimpleNamespace(to_dict=lambda: {"dry_run": True})

    monkeypatch.setattr(paper, "build_security_resolver", build_resolver)
    monkeypatch.setattr(paper_cli, "build_execution_broker", build_broker)
    monkeypatch.setattr(paper, "prepare_paper_plan", prepare)
    args = SimpleNamespace(
        through="2026-08-12", warmup_sessions=252,
        expect_account="paper-123")

    assert asyncio.run(paper_cli._prepare_paper_plan(_config(), args)) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out) == {"dry_run": True}
    assert [call[0] for call in calls] == [
        "connect", "feed_schema", "behavior_schema", "resolver", "broker",
        "prepare"]
    assert calls[-1][1] == {
        "conn": conn,
        "broker": broker,
        "base_url": DEFAULT_BASE_URL,
        "through": "2026-08-12",
        "expected_account": "paper-123",
        "warmup_sessions": 252,
    }
    assert conn.closed


def test_current_plan_never_constructs_a_broker(monkeypatch, capsys):
    calls = []
    conn = _wire_database(monkeypatch, calls)
    monkeypatch.setattr(
        paper_cli, "build_execution_broker",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("current-paper-plan contacted a broker")))
    monkeypatch.setattr(
        paper, "current_paper_plan",
        lambda actual, **_kwargs: {
            "plan": "current", "broker_contacted": False})

    assert asyncio.run(paper_cli._current_paper_plan(_config())) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out) == {
        "plan": "current", "broker_contacted": False}
    assert [call[0] for call in calls] == [
        "connect", "feed_schema", "behavior_schema"]
    assert conn.closed


def test_current_plan_uses_reviewed_shadow_in_dual_without_catchup(
        monkeypatch, capsys):
    calls = []
    conn = _wire_database(monkeypatch, calls)
    monkeypatch.setenv("SENTINEL_REVIEWED_DEPLOYMENT_MODE", "dual")
    monkeypatch.setenv("SENTINEL_SHADOW_OBSERVATION_ENABLED", "1")
    monkeypatch.setenv("SENTINEL_SHADOW_OBSERVATION_ID", "year-end")
    monkeypatch.setenv("SENTINEL_SHADOW_STARTING_CASH", "123456.78")

    def inspect(actual, **kwargs):
        calls.append(("current", actual, kwargs))
        return {
            "mode": "INFORMATIONAL_PAPER_MIRROR",
            "database_authorities_match": True,
            "broker_contacted": False,
        }

    monkeypatch.setattr(paper, "current_paper_plan", inspect)

    assert asyncio.run(paper_cli._current_paper_plan(_config())) == cli.EXIT_OK
    assert calls[-1] == (
        "current", conn,
        {"base_url": DEFAULT_BASE_URL,
         "dual_shadow_observation_id": "year-end",
         "dual_shadow_starting_cash": Decimal("123456.78")})
    assert json.loads(capsys.readouterr().out)["mode"] \
        == "INFORMATIONAL_PAPER_MIRROR"
    assert conn.closed


@pytest.mark.parametrize(
    "command", ["prepare", "current", "execute"])
def test_schema_migration_refusal_stops_paper_startup_before_broker(
        monkeypatch, capsys, command):
    calls = []
    conn = _wire_database(monkeypatch, calls)

    def refuse_schema(actual):
        calls.append(("behavior_schema", actual))
        raise schema.SchemaMigrationRefused(
            "behavioral migration authority is missing")

    def forbidden(*_args, **_kwargs):
        raise AssertionError(
            f"{command} continued past behavioral schema refusal")

    monkeypatch.setattr(schema, "ensure_schema", refuse_schema)
    monkeypatch.setattr(paper, "build_security_resolver", forbidden)
    monkeypatch.setattr(paper_cli, "build_execution_broker", forbidden)
    monkeypatch.setattr(paper, "prepare_paper_plan", forbidden)
    monkeypatch.setattr(paper, "current_paper_plan", forbidden)
    monkeypatch.setattr(paper, "execute_paper_plan", forbidden)

    if command == "prepare":
        args = SimpleNamespace(
            through="2026-08-12", warmup_sessions=252,
            expect_account="paper-123")
        result = asyncio.run(paper_cli._prepare_paper_plan(_config(), args))
    elif command == "current":
        result = asyncio.run(paper_cli._current_paper_plan(_config()))
    else:
        result = asyncio.run(
            paper_cli._execute_paper_plan(_config(), _execution_args()))

    assert result == cli.EXIT_NOT_ESTABLISHED
    assert capsys.readouterr().err == (
        "REFUSED: behavioral migration authority is missing\n")
    assert [call[0] for call in calls] == [
        "connect", "feed_schema", "behavior_schema"]
    assert conn.closed


def test_execute_passes_every_explicit_confirmation(monkeypatch, capsys):
    calls = []
    conn = _wire_database(monkeypatch, calls)
    resolver = object()
    broker = object()
    monkeypatch.setattr(
        paper, "build_security_resolver",
        lambda actual, session: calls.append(
            ("resolver", actual, session)) or resolver)
    monkeypatch.setattr(
        paper_cli, "build_execution_broker",
        lambda config, *, resolve_security_id: calls.append(
            ("broker", resolve_security_id)) or broker)

    async def execute(**kwargs):
        calls.append(("execute", kwargs))
        return SimpleNamespace(
            needs_attention=False,
            to_dict=lambda: {"paper_submission_authorized": True})

    monkeypatch.setattr(paper, "execute_paper_plan", execute)
    args = _execution_args()

    assert asyncio.run(paper_cli._execute_paper_plan(_config(), args)) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out) == {
        "paper_submission_authorized": True}
    assert calls[-1][1] == {
        "conn": conn,
        "broker": broker,
        "base_url": DEFAULT_BASE_URL,
        "confirm_account": "paper-123",
        "confirm_plan_id": "plan-456",
        "confirm_effective_session": "2026-08-13",
        "confirm_submit": True,
    }
    assert conn.closed


@pytest.mark.parametrize(
    ("session", "expected_exit", "authorized"),
    [
        (executor.SessionResult(
            runtime_state=RuntimeState.RUNNING, deferred=("sid-1",)),
         cli.EXIT_NOT_ESTABLISHED, False),
        (executor.SessionResult(
            runtime_state=RuntimeState.RUNNING,
            refused={"sid-1": "increase withheld"}),
         cli.EXIT_NOT_ESTABLISHED, False),
        (executor.SessionResult(runtime_state=RuntimeState.BROKER_DEGRADED),
         cli.EXIT_NOT_ESTABLISHED, False),
        (executor.SessionResult(
            runtime_state=RuntimeState.RUNNING,
            submitted=(SimpleNamespace(
                state=CommandState.UNKNOWN, client_key="command-1"),)),
         cli.EXIT_NOT_ESTABLISHED, False),
        (executor.SessionResult(
            runtime_state=RuntimeState.RUNNING,
            submitted=(SimpleNamespace(
                state=CommandState.CANCELLED, client_key="command-2"),)),
         cli.EXIT_NOT_ESTABLISHED, False),
        (executor.SessionResult(runtime_state=RuntimeState.RUNNING),
         cli.EXIT_OK, True),
    ],
    ids=["deferred", "refused", "non-running", "unknown", "cancelled",
         "clean-running"])
def test_execute_exit_and_authorization_reflect_operator_attention(
        monkeypatch, capsys, session, expected_exit, authorized):
    calls = []
    _wire_database(monkeypatch, calls)
    monkeypatch.setattr(
        paper, "build_security_resolver", lambda conn, session: object())
    monkeypatch.setattr(
        paper_cli, "build_execution_broker",
        lambda config, *, resolve_security_id: object())

    async def execute(**kwargs):
        return _execution_result(session)

    monkeypatch.setattr(paper, "execute_paper_plan", execute)

    assert asyncio.run(paper_cli._execute_paper_plan(
        _config(), _execution_args())) == expected_exit
    output = json.loads(capsys.readouterr().out)
    assert output["paper_submission_authorized"] is authorized
    assert output["operator_attention_required"] is (not authorized)


def test_activation_refusal_is_an_operator_checkpoint(monkeypatch, capsys):
    calls = []
    _wire_database(monkeypatch, calls)
    monkeypatch.setattr(
        paper, "build_security_resolver", lambda conn, session: object())
    monkeypatch.setattr(
        paper_cli, "build_execution_broker",
        lambda config, *, resolve_security_id: object())

    async def refuse(**kwargs):
        raise paper.PaperActivationRefused("ownership is not established")

    monkeypatch.setattr(paper, "prepare_paper_plan", refuse)
    args = SimpleNamespace(
        through="2026-08-12", warmup_sessions=252,
        expect_account="paper-123")

    assert asyncio.run(paper_cli._prepare_paper_plan(_config(), args)) \
        == cli.EXIT_NOT_ESTABLISHED
    assert "REFUSED: ownership is not established" in capsys.readouterr().err


@pytest.mark.parametrize(
    "refusal_type", [journal.WriterLockUnavailable,
                     alpaca.MalformedBrokerPayload])
def test_operational_refusals_are_caught_as_attention_exit(
        monkeypatch, capsys, refusal_type):
    calls = []
    conn = _wire_database(monkeypatch, calls)
    monkeypatch.setattr(
        paper, "build_security_resolver", lambda actual, session: object())
    monkeypatch.setattr(
        paper_cli, "build_execution_broker",
        lambda config, *, resolve_security_id: object())

    async def refuse(**kwargs):
        raise refusal_type("operator attention required")

    monkeypatch.setattr(paper, "execute_paper_plan", refuse)

    assert asyncio.run(paper_cli._execute_paper_plan(
        _config(), _execution_args())) == cli.EXIT_NOT_ESTABLISHED
    assert "REFUSED: operator attention required" in capsys.readouterr().err
    assert conn.closed


def test_certificate_install_requires_confirmation_before_file_or_database(
        monkeypatch, capsys):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("reserved certificate command touched external state")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(feed_store, "connect", forbidden)
    result = authority_cli._install_system_certificate(
        _config(), SimpleNamespace(
            certificate="operator-authored.json",
            confirm_certificate_sha256="a" * 64,
            reason="reviewed", confirm_install_alpaca_paper_execution_certificate=False))

    assert result == cli.EXIT_CONFIG
    assert "explicit paper-certificate" in capsys.readouterr().err


def _rollout_args(mode: str, *, confirm_controller: bool = False,
                  confirm_pinned_risk: bool = False):
    return SimpleNamespace(
        mode=mode, reason="reviewed transition",
        confirm_controller_rollout=confirm_controller,
        confirm_pinned_rollout_may_increase_exposure=confirm_pinned_risk)


def test_pinned_rollout_does_not_load_broken_controller_and_warns_of_risk(
        monkeypatch, capsys):
    calls = []
    conn = _Connection()
    monkeypatch.setattr(feed_store, "connect", lambda _url: conn)
    monkeypatch.setattr(schema, "ensure_schema", lambda actual: None)

    @contextmanager
    def locked(actual):
        calls.append(("lock", actual))
        yield

    monkeypatch.setattr(journal, "writer_lock", locked)
    before = authority.RolloutState(
        authority.RolloutMode.CONTROLLER, 4, "a" * 64)
    after = authority.RolloutState(
        authority.RolloutMode.PINNED_1_00, 5, None)
    monkeypatch.setattr(authority, "load_rollout_state", lambda actual: before)

    def set_mode(actual, **kwargs):
        calls.append(("set", actual, kwargs))
        return after

    monkeypatch.setattr(authority, "set_rollout_mode", set_mode)
    monkeypatch.setattr(
        authority_cli, "_current_system_identities",
        lambda: (_ for _ in ()).throw(
            AssertionError("pinned transition loaded broken controller")))

    assert authority_cli._set_paper_rollout_mode(
        _config(), _rollout_args(
            "PINNED_1_00", confirm_pinned_risk=True)) == cli.EXIT_OK

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["changed"] is True
    assert output["rollout"]["mode"] == "PINNED_1_00"
    assert output["risk_warning"] == cli_shared.PINNED_ROLLOUT_RISK_WARNING
    assert "may increase exposure and risk" in captured.err
    set_call = next(call for call in calls if call[0] == "set")
    assert set_call[2]["runtime_identity"] == {}
    assert set_call[2]["strategy_identity"] == {}
    assert conn.closed


@pytest.mark.parametrize("kill", [True, False])
def test_emergency_automation_fencing_bypasses_execution_writer_lock(
        monkeypatch, kill):
    from sentinel.automation import store

    conn = _Connection()
    calls = []
    monkeypatch.setattr(feed_store, "connect", lambda _url: conn)
    monkeypatch.setattr(schema, "ensure_schema", lambda actual: None)

    @contextmanager
    def unavailable(_actual):
        raise AssertionError(
            "emergency fencing waited for the execution writer lock")
        yield

    monkeypatch.setattr(journal, "writer_lock", unavailable)
    control = SimpleNamespace(
        enabled=not kill, kill_switch_engaged=True, generation=9)
    monkeypatch.setattr(
        store, "engage_kill",
        lambda actual, **kwargs: calls.append(
            ("kill", actual, kwargs)) or control)
    monkeypatch.setattr(
        store, "deactivate",
        lambda actual, **kwargs: calls.append(
            ("deactivate", actual, kwargs)) or control)

    result = automation_cli._remove_automation_authority(
        _config(), SimpleNamespace(actor="operator", reason="emergency"),
        kill=kill)

    assert result == cli.EXIT_OK
    assert calls == [(
        "kill" if kill else "deactivate", conn,
        {"actor": "operator", "reason": "emergency"})]
    assert conn.closed


@pytest.mark.parametrize(
    ("command", "function_name", "args", "expected_kwargs"),
    [
        (
            "certificate", "revoke_system_certificate",
            SimpleNamespace(
                confirm_revoke_system_certificate=True,
                certificate_sha256="a" * 64, reason="emergency"),
            {"certificate_sha256": "a" * 64,
             "reason": "emergency", "commit": True},
        ),
        (
            "key", "revoke_signed_key",
            SimpleNamespace(
                confirm_revoke_system_key=True,
                key_id="ed25519-sha256:" + "b" * 64,
                reason="emergency"),
            {"key_id": "ed25519-sha256:" + "b" * 64,
             "reason": "emergency", "commit": True},
        ),
    ],
)
def test_execution_authority_revocation_bypasses_writer_lock(
        monkeypatch, command, function_name, args, expected_kwargs):
    conn = _Connection()
    calls = []
    monkeypatch.setattr(feed_store, "connect", lambda _url: conn)
    monkeypatch.setattr(schema, "ensure_schema", lambda actual: None)

    @contextmanager
    def unavailable(_actual):
        raise AssertionError(
            "emergency authority revocation waited for the writer lock")
        yield

    monkeypatch.setattr(journal, "writer_lock", unavailable)
    monkeypatch.setattr(
        authority, function_name,
        lambda actual, **kwargs: calls.append((actual, kwargs)))

    result = (
        authority_cli._revoke_system_certificate(_config(), args)
        if command == "certificate"
        else authority_cli._revoke_system_key(_config(), args)
    )

    assert result == cli.EXIT_OK
    assert calls == [(conn, expected_kwargs)]
    assert conn.closed


def test_administrative_authority_revocation_bypasses_writer_lock(monkeypatch):
    from sentinel import administrative_authority

    conn = _Connection()
    calls = []
    monkeypatch.setattr(feed_store, "connect", lambda _url: conn)
    monkeypatch.setattr(schema, "ensure_schema", lambda actual: None)

    @contextmanager
    def unavailable(_actual):
        raise AssertionError(
            "administrative revocation waited for migration broker I/O")
        yield

    monkeypatch.setattr(journal, "writer_lock", unavailable)
    monkeypatch.setattr(
        administrative_authority, "revoke_administrative_certificate",
        lambda actual, **kwargs: calls.append((actual, kwargs)))
    args = SimpleNamespace(
        confirm_revoke_administrative_certificate=True,
        certificate_sha256="c" * 64, reason="migration aborted")

    assert authority_cli._revoke_administrative_certificate(
        _config(), args) == cli.EXIT_OK
    assert calls == [(conn, {
        "certificate_sha256": "c" * 64,
        "reason": "migration aborted",
        "commit": True,
    })]
    assert conn.closed


def test_pinned_rollout_requires_literal_exposure_increase_acknowledgement(
        monkeypatch, capsys):
    monkeypatch.setattr(
        feed_store, "connect",
        lambda _url: (_ for _ in ()).throw(
            AssertionError("missing confirmation opened database")))

    assert authority_cli._set_paper_rollout_mode(
        _config(), _rollout_args("PINNED_1_00")) == cli.EXIT_CONFIG
    refusal = capsys.readouterr().err
    assert "--confirm-pinned-rollout-may-increase-exposure" in refusal
    assert "forces 100% Wealth Core exposure" in refusal


def test_generic_controller_rollout_refuses_before_identity_or_database(
        monkeypatch, capsys):
    monkeypatch.setattr(
        authority_cli, "_current_system_identities",
        lambda: (_ for _ in ()).throw(
            frozen_rule.FrozenRuleTampered("controller digest mismatch")))
    monkeypatch.setattr(
        feed_store, "connect",
        lambda _url: (_ for _ in ()).throw(
            AssertionError("failed identity opened database")))

    assert authority_cli._set_paper_rollout_mode(
        _config(), _rollout_args(
            "CONTROLLER", confirm_controller=True)) == cli.EXIT_CONFIG
    assert "only by staging and activating" in capsys.readouterr().err


def test_rollout_help_names_pinned_exposure_increase_risk(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["set-paper-rollout-mode", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "forces 100% Wealth Core exposure" in help_text
    assert "--confirm-pinned-rollout-may-increase-exposure" in help_text


def test_broker_command_refuses_before_configuration_without_authorized_image(
        monkeypatch, tmp_path, capsys):
    monkeypatch.delenv(cli_shared.AUTHORIZED_RUNTIME_ENV, raising=False)
    monkeypatch.setattr(
        cli_shared, "AUTHORIZED_RUNTIME_MARKER", tmp_path / "missing-marker")
    monkeypatch.setattr(
        cli.SentinelConfig, "from_env",
        classmethod(lambda cls: (_ for _ in ()).throw(
            AssertionError("configuration was read before the image gate"))))

    assert cli.main([
        "prepare-paper-plan", "--through", "2026-08-12",
        "--expect-account", "paper-123",
    ]) == cli.EXIT_CONFIG
    error = capsys.readouterr().err
    assert "marker-bearing, digest-qualified" in error
    assert "sentinel-authorized-cli.sh" in error


def test_emergency_fencing_does_not_depend_on_authorized_image(monkeypatch):
    monkeypatch.delenv(cli_shared.AUTHORIZED_RUNTIME_ENV, raising=False)
    monkeypatch.setattr(
        cli_shared, "AUTHORIZED_RUNTIME_MARKER", Path("/definitely/missing"))

    assert cli_shared.require_authorized_runtime(
        "engage-paper-automation-kill-switch") is None
    assert cli_shared.require_authorized_runtime(
        "deactivate-paper-automation") is None
    assert cli_shared.require_authorized_runtime(
        "revoke-system-certificate") is None


@pytest.mark.parametrize(
    "refusal_type", [
        alpaca.MalformedBrokerPayload,
        contract.IncompleteObservation,
        paper.PaperActivationRefused,
    ])
def test_inspection_refusals_are_caught_without_a_traceback(
        monkeypatch, capsys, refusal_type):
    conn = _Connection()
    monkeypatch.setattr(feed_store, "connect", lambda _url: conn)
    monkeypatch.setattr(
        paper, "build_security_resolver", lambda _conn, _session: object())
    monkeypatch.setattr(
        paper_cli, "build_execution_broker",
        lambda _config, *, resolve_security_id: object())

    async def refuse(**_kwargs):
        raise refusal_type("inspection evidence is incomplete or malformed")

    monkeypatch.setattr(paper, "inspect_paper_account", refuse)
    _wire_administrative_inspection(monkeypatch)

    assert asyncio.run(paper_cli._inspect_paper_account(
        _config(), SimpleNamespace(
            deployment_id="nas-01", expect_account="paper-123"))) \
        == cli.EXIT_NOT_ESTABLISHED
    assert "REFUSED: inspection evidence is incomplete or malformed" \
        in capsys.readouterr().err
    assert conn.closed


def test_command_parser_preserves_required_confirmations_and_warmup_default(
        monkeypatch):
    config = _config()
    seen = {}
    monkeypatch.setattr(
        cli.SentinelConfig, "from_env", classmethod(lambda cls: config))

    async def prepare(actual_config, args):
        seen["prepare"] = (actual_config, vars(args))
        return cli.EXIT_OK

    async def inspect(actual_config, args):
        seen["inspect"] = (actual_config, vars(args))
        return cli.EXIT_OK

    async def inspect_empty(actual_config, args):
        seen["inspect_empty"] = (actual_config, vars(args))
        return cli.EXIT_OK

    async def bind_empty(actual_config, args):
        seen["bind_empty"] = (actual_config, vars(args))
        return cli.EXIT_OK

    def empty_candidate(actual_config, args):
        seen["empty_candidate"] = (actual_config, vars(args))
        return cli.EXIT_OK

    async def execute(actual_config, args):
        seen["execute"] = (actual_config, vars(args))
        return cli.EXIT_OK

    def install_certificate(actual_config, args):
        seen["install_certificate"] = (actual_config, vars(args))
        return cli.EXIT_OK

    def revoke_certificate(actual_config, args):
        seen["revoke_certificate"] = (actual_config, vars(args))
        return cli.EXIT_OK

    def activate_certificate(actual_config, args):
        seen["activate_certificate"] = (actual_config, vars(args))
        return cli.EXIT_OK

    def set_rollout(actual_config, args):
        seen["rollout"] = (actual_config, vars(args))
        return cli.EXIT_OK

    for command, handler in {
        "prepare-paper-plan": prepare,
        "inspect-paper-account": inspect,
        "inspect-empty-paper-account": inspect_empty,
        "bind-empty-paper-account": bind_empty,
        "create-empty-paper-binding-candidate": empty_candidate,
        "execute-paper-plan": execute,
        "install-system-certificate": install_certificate,
        "revoke-system-certificate": revoke_certificate,
        "activate-system-certificate": activate_certificate,
        "rotate-system-certificate": activate_certificate,
        "set-paper-rollout-mode": set_rollout,
    }.items():
        monkeypatch.setitem(cli.ROUTES, command, handler)

    assert cli.main([
        "inspect-paper-account", "--deployment-id", "nas-01",
        "--expect-account", "paper-123",
    ]) == cli.EXIT_OK
    assert seen["inspect"][1]["expect_account"] == "paper-123"
    assert cli.main([
        "create-empty-paper-binding-candidate",
        "--certificate-id", "empty-paper-binding-0001",
        "--issuer-generation", "7", "--deployment-id", "nas-01",
        "--expect-account", "paper-123",
        "--not-before", "2026-08-16T12:00:00Z",
        "--reviewer", "reviewer", "--ticket", "ticket-1",
    ]) == cli.EXIT_OK
    assert seen["empty_candidate"][1]["issuer_generation"] == 7
    assert cli.main([
        "inspect-empty-paper-account", "--deployment-id", "nas-01",
        "--expect-account", "paper-123",
    ]) == cli.EXIT_OK
    assert seen["inspect_empty"][1]["expect_account"] == "paper-123"
    assert cli.main([
        "bind-empty-paper-account", "--deployment-id", "nas-01",
        "--expect-account", "paper-123", "--notes", "ticket-1",
    ]) == cli.EXIT_OK
    assert seen["bind_empty"][1]["notes"] == "ticket-1"
    assert cli.main([
        "prepare-paper-plan", "--through", "2026-08-12",
        "--expect-account", "paper-123"]) == cli.EXIT_OK
    assert seen["prepare"][1]["warmup_sessions"] == 252
    assert cli.main([
        "execute-paper-plan",
        "--confirm-paper-account", "paper-123",
        "--confirm-plan-id", "plan-456",
        "--confirm-effective-session", "2026-08-13",
        "--confirm-submit-paper-orders"]) == cli.EXIT_OK
    assert seen["execute"][1]["confirm_submit_paper_orders"] is True
    assert cli.main([
        "install-system-certificate", "--certificate", "certificate.json",
        "--confirm-certificate-sha256", "a" * 64, "--reason", "reviewed",
        "--confirm-install-alpaca-paper-execution-certificate"]) == cli.EXIT_OK
    assert seen["install_certificate"][1][
        "confirm_install_alpaca_paper_execution_certificate"] is True
    assert cli.main([
        "activate-system-certificate", "--certificate-sha256", "a" * 64,
        "--confirm-paper-account", "paper-123",
        "--confirm-deployment-id", "nas-01", "--reason", "reviewed",
        "--confirm-controller-rollout",
        "--confirm-activate-alpaca-paper-execution-certificate"]) == cli.EXIT_OK
    assert seen["activate_certificate"][1][
        "confirm_activate_alpaca_paper_execution_certificate"] is True
    assert seen["activate_certificate"][1]["confirm_controller_rollout"] is True
    assert cli.main([
        "rotate-system-certificate", "--certificate-sha256", "b" * 64,
        "--confirm-supersedes-certificate-sha256", "a" * 64,
        "--confirm-paper-account", "paper-123",
        "--confirm-deployment-id", "nas-01", "--reason", "rotate",
        "--confirm-pinned-rollout-may-increase-exposure",
        "--confirm-rotate-alpaca-paper-execution-certificate"]) == cli.EXIT_OK
    assert seen["activate_certificate"][1][
        "confirm_rotate_alpaca_paper_execution_certificate"] is True
    assert seen["activate_certificate"][1][
        "confirm_pinned_rollout_may_increase_exposure"] is True
    assert cli.main([
        "revoke-system-certificate", "--certificate-sha256", "a" * 64,
        "--reason", "operator kill switch",
        "--confirm-revoke-system-certificate"]) == cli.EXIT_OK
    assert seen["revoke_certificate"][1][
        "confirm_revoke_system_certificate"] is True
    assert cli.main([
        "set-paper-rollout-mode", "--mode", "CONTROLLER",
        "--reason", "reviewed transition",
        "--confirm-controller-rollout"]) == cli.EXIT_OK
    assert seen["rollout"][1]["mode"] == "CONTROLLER"
    assert seen["rollout"][1]["confirm_controller_rollout"] is True
