"""Focused wiring tests for the paper preparation and execution commands."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import __main__ as cli
from sentinel import paper, schema
from sentinel.config import DEFAULT_BASE_URL, SentinelConfig
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
        feed_store, "ensure_schema",
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
        cli, "build_execution_broker",
        lambda config, *, resolve_security_id: calls.append(
            ("broker", config, resolve_security_id)) or broker)

    async def inspect(**kwargs):
        calls.append(("inspect", kwargs))
        return _inspection_result()

    monkeypatch.setattr(paper, "inspect_paper_account", inspect)

    assert asyncio.run(cli._inspect_paper_account(
        _config(), SimpleNamespace(expect_account="paper-123"))) == cli.EXIT_OK

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
        "conn": conn, "broker": broker, "base_url": DEFAULT_BASE_URL,
        "expected_account": "paper-123"}
    assert conn.closed


def test_inspect_does_not_ensure_or_write_database_schemas(monkeypatch):
    conn = _Connection()
    monkeypatch.setattr(feed_store, "connect", lambda _url: conn)
    monkeypatch.setattr(
        feed_store, "ensure_schema",
        lambda _conn: (_ for _ in ()).throw(
            AssertionError("inspection wrote feed schema")))
    monkeypatch.setattr(
        schema, "ensure_schema",
        lambda _conn: (_ for _ in ()).throw(
            AssertionError("inspection wrote behavioral schema")))
    monkeypatch.setattr(
        paper, "build_security_resolver", lambda _conn, _session: object())
    monkeypatch.setattr(
        cli, "build_execution_broker",
        lambda _config, *, resolve_security_id: object())
    monkeypatch.setattr(
        paper, "inspect_paper_account",
        lambda **_kwargs: (_ for _ in ()).throw(
            paper.PaperActivationRefused("stop after read-only wiring")))

    assert asyncio.run(cli._inspect_paper_account(
        _config(), SimpleNamespace(expect_account="paper-123"))) \
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
    monkeypatch.setattr(cli, "build_execution_broker", build_broker)
    monkeypatch.setattr(paper, "prepare_paper_plan", prepare)
    args = SimpleNamespace(
        through="2026-08-12", warmup_sessions=252,
        expect_account="paper-123")

    assert asyncio.run(cli._prepare_paper_plan(_config(), args)) == cli.EXIT_OK
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
        cli, "build_execution_broker",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("current-paper-plan contacted a broker")))
    monkeypatch.setattr(
        paper, "current_paper_plan",
        lambda actual: {"plan": "current", "broker_contacted": False})

    assert asyncio.run(cli._current_paper_plan(_config())) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out) == {
        "plan": "current", "broker_contacted": False}
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
        cli, "build_execution_broker",
        lambda config, *, resolve_security_id: calls.append(
            ("broker", resolve_security_id)) or broker)

    async def execute(**kwargs):
        calls.append(("execute", kwargs))
        return SimpleNamespace(
            needs_attention=False,
            to_dict=lambda: {"paper_submission_authorized": True})

    monkeypatch.setattr(paper, "execute_paper_plan", execute)
    args = _execution_args()

    assert asyncio.run(cli._execute_paper_plan(_config(), args)) == cli.EXIT_OK
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
        cli, "build_execution_broker",
        lambda config, *, resolve_security_id: object())

    async def execute(**kwargs):
        return _execution_result(session)

    monkeypatch.setattr(paper, "execute_paper_plan", execute)

    assert asyncio.run(cli._execute_paper_plan(
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
        cli, "build_execution_broker",
        lambda config, *, resolve_security_id: object())

    async def refuse(**kwargs):
        raise paper.PaperActivationRefused("ownership is not established")

    monkeypatch.setattr(paper, "prepare_paper_plan", refuse)
    args = SimpleNamespace(
        through="2026-08-12", warmup_sessions=252,
        expect_account="paper-123")

    assert asyncio.run(cli._prepare_paper_plan(_config(), args)) \
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
        cli, "build_execution_broker",
        lambda config, *, resolve_security_id: object())

    async def refuse(**kwargs):
        raise refusal_type("operator attention required")

    monkeypatch.setattr(paper, "execute_paper_plan", refuse)

    assert asyncio.run(cli._execute_paper_plan(
        _config(), _execution_args())) == cli.EXIT_NOT_ESTABLISHED
    assert "REFUSED: operator attention required" in capsys.readouterr().err
    assert conn.closed


def test_certificate_install_is_reserved_and_refuses_before_file_or_database(
        monkeypatch, capsys):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("reserved certificate command touched external state")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(feed_store, "connect", forbidden)
    result = cli._install_system_certificate(
        _config(), SimpleNamespace(
            manifest="operator-authored.json",
            confirm_manifest_sha256="a" * 64,
            confirm_paper_execution_authority=True))

    assert result == cli.EXIT_NOT_ESTABLISHED
    assert "trusted issuer/signature" in capsys.readouterr().err


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
        cli, "build_execution_broker",
        lambda _config, *, resolve_security_id: object())

    async def refuse(**_kwargs):
        raise refusal_type("inspection evidence is incomplete or malformed")

    monkeypatch.setattr(paper, "inspect_paper_account", refuse)

    assert asyncio.run(cli._inspect_paper_account(
        _config(), SimpleNamespace(expect_account="paper-123"))) \
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

    async def execute(actual_config, args):
        seen["execute"] = (actual_config, vars(args))
        return cli.EXIT_OK

    def install_certificate(actual_config, args):
        seen["install_certificate"] = (actual_config, vars(args))
        return cli.EXIT_OK

    def revoke_certificate(actual_config, args):
        seen["revoke_certificate"] = (actual_config, vars(args))
        return cli.EXIT_OK

    def set_rollout(actual_config, args):
        seen["rollout"] = (actual_config, vars(args))
        return cli.EXIT_OK

    monkeypatch.setattr(cli, "_prepare_paper_plan", prepare)
    monkeypatch.setattr(cli, "_inspect_paper_account", inspect)
    monkeypatch.setattr(cli, "_execute_paper_plan", execute)
    monkeypatch.setattr(
        cli, "_install_system_certificate", install_certificate)
    monkeypatch.setattr(
        cli, "_revoke_system_certificate", revoke_certificate)
    monkeypatch.setattr(cli, "_set_paper_rollout_mode", set_rollout)

    assert cli.main([
        "inspect-paper-account", "--expect-account", "paper-123",
    ]) == cli.EXIT_OK
    assert seen["inspect"][1]["expect_account"] == "paper-123"
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
        "install-system-certificate", "--manifest", "manifest.json",
        "--confirm-manifest-sha256", "a" * 64,
        "--confirm-paper-execution-authority"]) == cli.EXIT_OK
    assert seen["install_certificate"][1][
        "confirm_paper_execution_authority"] is True
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
