"""Production paper transport admission precedes its one guarded composition."""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import binding, config, paper
from sentinel.execution import certification, journal
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.guarded import (
    AutomationExecutionGrant, BrokerAuthorityRefused, ExecutionBrokerGuard,
    GuardedExecutionBroker, PaperPreparationGrant,
)
from sentinel.paper import execution, inspection, preparation, recovery, validation
from tests.sentinel.test_issue_183_alpaca_hardening import Httpx, Response


def transport():
    cfg = config.SentinelConfig(
        alpaca_key="fixture", alpaca_secret="fixture",
        base_url=config.DEFAULT_BASE_URL, state_dir=Path("/fixture"),
        max_cycles=1, poll_seconds=0)
    broker = config.build_execution_broker(
        cfg, resolve_security_id=lambda symbol, *_: "SEC-" + symbol)
    http = Httpx(routes={"/v2/account": Response({
        "id": "native-account", "account_number": "SIM-PAPER",
        "equity": "1000", "cash": "1000", "buying_power": "1000",
        "multiplier": "1", "status": "ACTIVE", "trading_blocked": False,
        "account_blocked": False, "trade_suspended_by_user": False,
    })})
    broker._http_provider = lambda: http
    return broker, http


def automation_grant(scope):
    return AutomationExecutionGrant(
        scope, "fixture-cycle", 1, "fixture-holder", 1, "SIM-PAPER", 1,
        "CONTROLLER", 2, "a" * 64)


class SchemaReached(Exception):
    pass


@pytest.mark.parametrize("gateway", ["prepare", "execute", "recover"])
@pytest.mark.parametrize("kind", ["bare", "wrapped", "unissued", "forged"])
def test_public_gateways_admit_only_the_issued_bare_transport(
        monkeypatch, gateway, kind):
    broker, http = transport()
    if kind == "wrapped":
        async def unused(*_args):
            raise AssertionError("no broker call allowed before schema")
        broker = GuardedExecutionBroker(
            inner=broker,
            grant=PaperPreparationGrant("SIM-PAPER", date(2026, 8, 11)),
            guard=ExecutionBrokerGuard(unused, unused, unused))
    elif kind == "unissued":
        from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
        broker = AssetIdAlpacaExecutionBroker(
            api_key="fixture", secret_key="fixture",
            base_url=config.DEFAULT_BASE_URL)
    elif kind == "forged":
        broker = SimpleNamespace(certified_adapter_identity=
                                 certification.require_certified_adapter(broker))

    def stop(_conn):
        raise SchemaReached
    monkeypatch.setattr(preparation, "_require_mutation_backup", lambda *a, **k: None)
    monkeypatch.setattr(preparation.schema, "require_runtime_schema", stop)
    common = dict(conn=object(), broker=broker, base_url=config.DEFAULT_BASE_URL)
    if gateway == "prepare":
        call = preparation.prepare_paper_plan(
            **common, through="2026-08-11", expected_account="SIM-PAPER")
    elif gateway == "execute":
        call = execution._execute_current_paper_plan(
            **common, grant=automation_grant("EXECUTE"))
    else:
        call = recovery.recover_automated_paper_cycle(
            **common, grant=automation_grant("RECOVER"),
            automation_config_sha256="b" * 64)
    with pytest.raises(SchemaReached if kind == "bare" else paper.PaperActivationRefused):
        asyncio.run(call)
    assert http.calls == []


@pytest.mark.parametrize("scope", ["PREPARE", "RECOVER", "EXECUTE"])
def test_shared_composition_checks_seal_and_retains_fresh_read_guards(monkeypatch, scope):
    broker, http = transport()
    calls = []
    async def before(grant, operation):
        calls.append(("before", operation))
    async def after(grant, operation, result):
        calls.append(("after", operation))
    async def mutate(*_args):
        calls.append(("mutation", None))
        raise BrokerAuthorityRefused("fixture revoked mutation")
    monkeypatch.setattr(validation, "build_fresh_execution_guard",
                        lambda **kwargs: ExecutionBrokerGuard(before, after, mutate))
    wrapped = validation._guard_broker(
        conn=SimpleNamespace(info=SimpleNamespace(dsn="dbname=fixture")),
        broker=broker,
        grant=(PaperPreparationGrant("SIM-PAPER", date(2026, 8, 11))
               if scope == "PREPARE" else automation_grant(scope)),
        base_url=config.DEFAULT_BASE_URL,
        now_provider=lambda: None, strategy_provider=lambda: {})
    inspection._require_certified_paper_broker(wrapped)
    account = asyncio.run(wrapped.account_snapshot())
    assert account.identity.account_id == "SIM-PAPER"
    assert [call[0] for call in calls] == ["before", "after"]
    assert len(http.calls) == 1 and http.calls[0][0] == "GET"
    with pytest.raises(BrokerAuthorityRefused):
        if scope == "EXECUTE":
            asyncio.run(wrapped.cancel("forbidden"))
        else:
            asyncio.run(wrapped.submit(client_key="forbidden", side=Side.BUY,
                instrument=BrokerInstrument("SEC-AAA", "AAA", "asset-aaa"),
                quantity=Decimal(1)))
    assert len(http.calls) == 1
    assert (calls[-1][0] == "mutation") is (scope == "EXECUTE")
    wrapped._guard = ExecutionBrokerGuard(before, after, mutate)
    with pytest.raises(paper.PaperActivationRefused):
        inspection._require_certified_paper_broker(wrapped)


def test_composition_refuses_a_constructor_that_returns_the_bare_transport(monkeypatch):
    broker, http = transport()
    async def no_op(*_args):
        pass
    monkeypatch.setattr(validation, "build_fresh_execution_guard", lambda **kwargs:
                        ExecutionBrokerGuard(no_op, no_op, no_op))
    monkeypatch.setattr(validation, "GuardedExecutionBroker", lambda **kwargs: kwargs["inner"])
    with pytest.raises(paper.PaperActivationRefused):
        validation._guard_broker(
            conn=SimpleNamespace(info=SimpleNamespace(dsn="dbname=fixture")),
            broker=broker, grant=PaperPreparationGrant("SIM-PAPER", date(2026, 8, 11)),
            base_url=config.DEFAULT_BASE_URL,
            now_provider=lambda: None, strategy_provider=lambda: {})
    assert http.calls == []


# Real PostgreSQL orchestration fixtures retain their explicit deterministic
# strategy/authority boundary. Transport, guard sealing, plan adoption and
# broker HTTP parsing below are production implementations.
from tests.sentinel.test_paper_activation import (  # noqa: E402,F401
    pg, conn, simulator_is_certified, DECISION, PRIOR, _publish, _persist_state,
    _state, _ready, _advance_stub, _prepare,
)


def test_strict_postgres_preparation_retains_unaccepted_history_refusal(conn, monkeypatch):
    binding.bind(conn, deployment_id="paper-composition-fixture", broker="alpaca",
                 broker_account_id="SIM-PAPER")
    pinned = _publish(conn)
    _persist_state(conn, _state(session=PRIOR, data_version=pinned.version))
    _ready(monkeypatch)
    monkeypatch.setattr(preparation, "advance_and_persist", _advance_stub)
    broker, http = transport()
    with pytest.raises(paper.PaperRetryableRefused, match="observation is PARTIAL"):
        _prepare(conn, broker)
    assert journal.latest_plan(conn) is None
    assert http.calls and all(call[0] == "GET" for call in http.calls)
    assert not journal.load_commands(conn, binding.load(conn).identity)
