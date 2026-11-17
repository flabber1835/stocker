"""Falsifiers for the installed-but-killed PAPER reconciliation gateway."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import psycopg
import pytest

from sentinel import runtime_admission
from sentinel.automation import store as automation_store
from sentinel.automation.model import ControlBinding
from sentinel.config import SentinelConfig
from sentinel.execution import authority_gate, broker_cash, fenced_paper_recovery as fenced, journal
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerExactOrderLookup, BrokerFill, BrokerInstrument, BrokerObservation,
    BrokerOrder, Side,
)
from sentinel.execution.guarded import (
    BrokerAuthorityRefused, BrokerOperation, ExecutionBrokerGuard,
    FencedPaperRecoveryGrant, GuardedExecutionBroker,
    PreTransportAuthorityRefused,
)
from sentinel.execution.simulator import SimulatedBroker
from sentinel.execution.states import CommandState
from tests.sentinel.test_fractional_native_settlement import (
    database, fractional_recovery_case, pg,
)
from tests.sentinel.test_fractional_flow import fractional_environment


NOW = datetime(2026, 11, 17, 20, tzinfo=timezone.utc)
KEY = "sntl-owned-key"


def grant() -> FencedPaperRecoveryGrant:
    return FencedPaperRecoveryGrant(
        expected_account="PAPER-1", deployment_id="deployed",
        takeover_epoch=1, certificate_sha256="a" * 64,
        control_generation=7, installation_sha256="b" * 64,
        command_keys=(KEY,), command_order_ids=((KEY, "owned-order"),),
        git_commit="c" * 40,
        runtime_image_digest="sha256:" + "d" * 64)


def _broker(inner=None, *, after=None):
    inner = inner or SimulatedBroker()
    async def ok(*_args):
        return None
    return GuardedExecutionBroker(
        inner=inner, grant=grant(), guard=ExecutionBrokerGuard(
            before_read=ok, after_read=after or ok, before_mutation=ok))


def test_fenced_grant_limits_exact_get_before_transport():
    inner = SimulatedBroker()
    broker = _broker(inner)
    called = []
    async def exact(key):
        called.append(key)
        raise AssertionError("transport should not be called")
    inner.find_by_client_key = exact
    with pytest.raises(BrokerAuthorityRefused, match="not retained"):
        asyncio.run(broker.find_by_client_key("sntl-foreign"))
    assert called == []


def test_fenced_grant_rejects_exact_lookup_order_id_drift():
    inner = SimulatedBroker()
    broker = _broker(inner)
    identity = BrokerAccountIdentity("alpaca", "PAPER-1")
    order = BrokerOrder(
        broker_order_id="foreign-order", client_key=KEY,
        instrument=BrokerInstrument("SEC-CRL", "CRL", "asset-crl"),
        side=Side.BUY, state=CommandState.FILLED,
        quantity=Decimal(1), filled_quantity=Decimal(1),
        filled_average_price=Decimal("335.82"), submitted_at=NOW)
    async def exact(_key):
        return BrokerExactOrderLookup(
            KEY, NOW, NOW, identity, identity, order)
    inner.find_by_client_key = exact
    with pytest.raises(BrokerAuthorityRefused, match="durable order ID"):
        asyncio.run(broker.find_by_client_key(KEY))


def test_fenced_grant_blocks_submit_and_cancel_before_transport():
    inner = SimulatedBroker()
    broker = _broker(inner)
    calls = []
    async def transport(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("broker mutation reached")
    inner.submit = transport
    inner.cancel = transport
    with pytest.raises(PreTransportAuthorityRefused):
        asyncio.run(broker.cancel("native-order"))
    with pytest.raises(PreTransportAuthorityRefused):
        asyncio.run(broker.submit(client_key=KEY, instrument=BrokerInstrument(
            security_id="SEC-CRL", symbol="CRL", broker_id="asset-crl"),
            side=Side.BUY, quantity=Decimal(1)))
    assert calls == []


def test_fenced_grant_limits_owned_native_fill_get_before_transport(monkeypatch):
    inner = SimulatedBroker()
    broker = _broker(inner)
    monkeypatch.setattr(GuardedExecutionBroker, "supports_owned_order_fills", property(lambda _self: True))
    called = []
    async def fills(**_kwargs):
        called.append(True)
        return ()
    inner.owned_order_fills = fills
    order = BrokerOrder(
        broker_order_id="foreign-order", client_key="sntl-foreign",
        instrument=BrokerInstrument("SEC-CRL", "CRL", "asset-crl"),
        side=Side.BUY, state=CommandState.FILLED,
        quantity=Decimal(1), filled_quantity=Decimal(1),
        filled_average_price=Decimal("335.82"), submitted_at=NOW)
    with pytest.raises(BrokerAuthorityRefused, match="not exact-owned"):
        asyncio.run(broker.owned_order_fills(
            orders=(order,), identity=BrokerAccountIdentity("alpaca", "PAPER-1"),
            through=NOW))
    assert called == []


def test_fenced_grant_rejects_foreign_order_id_under_owned_key_before_transport(monkeypatch):
    inner = SimulatedBroker()
    broker = _broker(inner)
    monkeypatch.setattr(GuardedExecutionBroker, "supports_owned_order_fills",
                        property(lambda _self: True))
    called = []
    async def fills(**_kwargs):
        called.append(True)
        return ()
    inner.owned_order_fills = fills
    order = BrokerOrder(
        broker_order_id="foreign-order", client_key=KEY,
        instrument=BrokerInstrument("SEC-CRL", "CRL", "asset-crl"),
        side=Side.BUY, state=CommandState.FILLED,
        quantity=Decimal(1), filled_quantity=Decimal(1),
        filled_average_price=Decimal("335.82"), submitted_at=NOW)
    with pytest.raises(BrokerAuthorityRefused, match="not exact-owned"):
        asyncio.run(broker.owned_order_fills(
            orders=(order,), identity=BrokerAccountIdentity("alpaca", "PAPER-1"),
            through=NOW))
    assert called == []


def test_fenced_grant_rejects_foreign_account_native_fill_get_before_transport(monkeypatch):
    inner = SimulatedBroker()
    broker = _broker(inner)
    monkeypatch.setattr(GuardedExecutionBroker, "supports_owned_order_fills",
                        property(lambda _self: True))
    called = []
    async def fills(**_kwargs):
        called.append(True)
        return ()
    inner.owned_order_fills = fills
    order = BrokerOrder(
        broker_order_id="owned-order", client_key=KEY,
        instrument=BrokerInstrument("SEC-CRL", "CRL", "asset-crl"),
        side=Side.BUY, state=CommandState.FILLED,
        quantity=Decimal(1), filled_quantity=Decimal(1),
        filled_average_price=Decimal("335.82"), submitted_at=NOW)
    with pytest.raises(BrokerAuthorityRefused, match="not exact-owned"):
        asyncio.run(broker.owned_order_fills(
            orders=(order,), identity=BrokerAccountIdentity("alpaca", "FOREIGN"),
            through=NOW))
    assert called == []


def test_fenced_grant_rejects_foreign_native_fill_after_get(monkeypatch):
    inner = SimulatedBroker()
    broker = _broker(inner)
    monkeypatch.setattr(GuardedExecutionBroker, "supports_owned_order_fills", property(lambda _self: True))
    async def fills(**_kwargs):
        return (BrokerFill(KEY, "foreign-order", Decimal(1), Decimal(1), NOW),)
    inner.owned_order_fills = fills
    order = BrokerOrder(
        broker_order_id="owned-order", client_key=KEY,
        instrument=BrokerInstrument("SEC-CRL", "CRL", "asset-crl"),
        side=Side.BUY, state=CommandState.FILLED,
        quantity=Decimal(1), filled_quantity=Decimal(1),
        filled_average_price=Decimal("335.82"), submitted_at=NOW)
    with pytest.raises(BrokerAuthorityRefused, match="unrelated native fill"):
        asyncio.run(broker.owned_order_fills(
            orders=(order,), identity=BrokerAccountIdentity("alpaca", "PAPER-1"),
            through=NOW))


def test_fence_flip_during_observe_refuses_after_read():
    inner = SimulatedBroker()
    async def observe():
        return BrokerObservation(observed_at=NOW)
    inner.observe = observe
    observed = []
    async def after(_grant, operation, _result):
        observed.append(operation)
        raise BrokerAuthorityRefused("kill generation changed after GET")
    broker = _broker(inner, after=after)
    with pytest.raises(BrokerAuthorityRefused, match="generation changed"):
        asyncio.run(broker.observe())
    assert observed == [BrokerOperation.OBSERVE]


def test_signed_safety_read_is_the_only_grant_operation():
    recovery = grant()
    assert authority_gate._authority_operation(
        recovery, BrokerOperation.OBSERVE) == "SAFETY_READ"
    for operation in (BrokerOperation.SUBMIT, BrokerOperation.CANCEL,
                      BrokerOperation.ACCOUNT_SNAPSHOT):
        with pytest.raises(Exception, match="cannot mutate or expand"):
            authority_gate._authority_operation(recovery, operation)


def test_observed_unknown_sentinel_key_refuses_before_journal(monkeypatch):
    monkeypatch.setattr(fenced, "_fence", lambda *_args, **_kwargs: (None, None))
    monkeypatch.setattr(fenced, "load_rollout_state", lambda _conn: SimpleNamespace(mode="CONTROLLER"))
    monkeypatch.setattr(fenced, "require_observation_safety_authority",
                        lambda *_args, **_kwargs: SimpleNamespace(certificate_sha256="a" * 64))
    monkeypatch.setenv("SENTINEL_GIT_COMMIT", "c" * 40)
    monkeypatch.setenv("SENTINEL_IMAGE_SOURCE_REVISION", "c" * 40)
    monkeypatch.setenv("SENTINEL_RUNTIME_IMAGE_DIGEST", "sha256:" + "d" * 64)
    order = BrokerOrder(
        broker_order_id="foreign-order", client_key="sntl-foreign",
        instrument=BrokerInstrument("SEC-CRL", "CRL", "asset-crl"),
        side=Side.BUY, state=CommandState.FILLED,
        quantity=Decimal(1), filled_quantity=Decimal(1),
        filled_average_price=Decimal("335.82"), submitted_at=NOW)
    observation = BrokerObservation(observed_at=NOW, orders=(order,))
    with pytest.raises(fenced.FencedPaperRecoveryRefused, match="unowned Sentinel key"):
        fenced._validate_read(None, grant(),
            BrokerOperation.OBSERVE, observation,
            account="PAPER-1", deployment="deployed", generation=7,
            base_url="https://paper-api.alpaca.markets")


def test_receipt_requires_exact_installed_image_and_fenced_state(tmp_path, monkeypatch):
    monkeypatch.setattr(fenced, "_AUTHORITY_ROOT", tmp_path)
    monkeypatch.setattr(fenced.identity, "rehearsal_identity", lambda: {
        "certification": {"certified": True},
        "deployment_artifacts": {"git_commit": "c" * 40,
                                 "runtime_image_digest": "sha256:" + "d" * 64}})
    monkeypatch.setenv("SENTINEL_IMAGE_SOURCE_REVISION", "c" * 40)
    image = "example/sentinel@sha256:" + "d" * 64
    receipt = dict(schema="sentinel.installation-receipt/1",
                   installation_state="INSTALLED", activation_state="FENCED",
                   automation_enabled=False, kill_switch_engaged=True,
                   operational_ready=False, requested_mode="fenced",
                   git_commit="c" * 40, runtime_image=image,
                   deployment_id="deployed", paper_account_id="PAPER-1")
    path = tmp_path / "installation-receipt.json"
    path.write_text(json.dumps(receipt))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    kwargs = dict(path=str(path), sha256=sha, account="PAPER-1",
                  deployment="deployed", commit="c" * 40, image=image)
    assert fenced.installation_receipt(**kwargs) == receipt
    with pytest.raises(fenced.FencedPaperRecoveryRefused):
        fenced.installation_receipt(**{**kwargs, "account": "OTHER"})
    with pytest.raises(fenced.FencedPaperRecoveryRefused):
        fenced.installation_receipt(**{**kwargs, "sha256": "0" * 64})


def test_fenced_route_settles_ack_zero_three_native_fills_then_go_admits(
        database, pg, fractional_recovery_case, monkeypatch):
    """The retained CRL failure is recoverable without a second order POST."""
    f = fractional_recovery_case
    command = replace(f.command, notional=Decimal("1337.66"))
    asset_id = command.instrument.broker_id
    f.venue.by_id[asset_id]["price"] = Decimal("335.82")
    quantities = ("1", "1.983235066", "1")
    posted_cash = ("-335.82", "-666.01", "-335.82")
    cumulative = ("1", "2.983235066", "3.983235066")
    remaining = ("2.983235066", "1", "0")
    with journal.writer_lock(database, recovery_only=True):
        broker_cash.record_plan_baseline(database,
            plan_id=f.plan.plan_id, decision_session=f.plan.decision_session,
            activity_state=asyncio.run(f.activity()))
        journal.save_command(database, command)
        order = f.venue.post("https://paper-api.alpaca.markets/v2/orders", dict(
            type="market", time_in_force="day", side="buy", symbol=asset_id,
            notional="1337.66", client_order_id=command.client_key,
            order_class="simple", extended_hours=False)).payload
        prototype = f.venue.unpublished.pop()
        order["filled_qty"] = "3.983235066"
        order["filled_avg_price"] = "335.82"
        f.venue.positions[asset_id] = Decimal("3.983235066")
        f.venue.cash = Decimal("20000") - Decimal("1337.65")
        observed_at = f.clock.now()
        times = (observed_at, observed_at + timedelta(seconds=3, milliseconds=3),
                 observed_at + timedelta(seconds=3, milliseconds=2))
        order["filled_at"] = times[-1].isoformat()
        order["updated_at"] = order["filled_at"]
        for index, (qty, cash, cum, leaves) in enumerate(
                zip(quantities, posted_cash, cumulative, remaining, strict=True), 1):
            f.venue.events.append(dict(prototype,
                event_id=f"01J5R00000000000000000{index:03d}",
                ref_id=str(UUID(int=100 + index)), qty=qty, net_amount=cash,
                at=times[index - 1].isoformat(),
                executed_at=times[index - 1].isoformat(),
                details=dict(prototype["details"],
                    execution_type="fill" if index == 3 else "partial_fill",
                    order_status="filled" if index == 3 else "partially_filled",
                    cum_qty=cum, leaves_qty=leaves)))
    f.clock.instant += timedelta(seconds=4)
    assert journal.load_commands(database, f.bound.identity)[0].filled_quantity == 0
    with pytest.raises(runtime_admission.Refused,
                       match="RETAINED_ADMISSION_REQUIRES_COMMAND_RECONCILIATION"):
        runtime_admission._fence(database)

    certificate_sha = "a" * 64
    commit = "c" * 40
    image_digest = "sha256:" + "d" * 64
    monkeypatch.setenv("SENTINEL_GIT_COMMIT", commit)
    monkeypatch.setenv("SENTINEL_IMAGE_SOURCE_REVISION", commit)
    monkeypatch.setenv("SENTINEL_RUNTIME_IMAGE_DIGEST", image_digest)
    binding = ControlBinding(
        deployment_id=f.bound.deployment_id, broker="alpaca",
        broker_account_id=f.bound.broker_account_id, takeover_epoch=1,
        certificate_sha256=certificate_sha, rollout_mode="PINNED_1_00",
        rollout_version=1, config_sha256="e" * 64)
    automation_store.activate(database, binding=binding, actor="test", reason="test")
    control = automation_store.deactivate(database, actor="test", reason="test")
    monkeypatch.setattr(fenced, "load_rollout_state",
                        lambda _conn: SimpleNamespace(mode="PINNED_1_00"))
    monkeypatch.setattr(fenced, "require_observation_safety_authority",
                        lambda *_args, **_kwargs: SimpleNamespace(
                            certificate_sha256=certificate_sha))
    monkeypatch.setattr(fenced, "build_execution_broker",
                        lambda *_args, **_kwargs: f.broker)
    # The deterministic venue fixture predates composition-issued identities;
    # certification is independently pinned by the broker composition tests.
    monkeypatch.setattr(fenced, "_require_certified_paper_broker",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(fenced, "_action_lookup", lambda *_args: None)

    def guard(**_kwargs):
        async def check(grant, operation, result=None):
            with psycopg.connect(pg.sync_dsn) as fresh:
                fenced._validate_read(
                    fresh, grant, operation, result,
                    account=f.bound.broker_account_id,
                    deployment=f.bound.deployment_id,
                    generation=control.generation,
                    base_url="https://paper-api.alpaca.markets")
        async def no_mutation(*_args):
            raise AssertionError("recovery attempted a broker mutation")
        return ExecutionBrokerGuard(
            before_read=check, after_read=check, before_mutation=no_mutation)

    monkeypatch.setattr(fenced, "build_fresh_execution_guard", guard)
    cfg = SentinelConfig("fixture", "fixture", "https://paper-api.alpaca.markets",
                         Path("/tmp/sentinel-test"), 1, 1, pg.sync_dsn)
    kwargs = dict(config=cfg, installation_sha256="b" * 64,
                  account=f.bound.broker_account_id,
                  deployment=f.bound.deployment_id,
                  generation=control.generation,
                  image="example/sentinel@" + image_digest)
    result = asyncio.run(fenced.recover(**kwargs))
    assert result["status"] == "RECONCILED"
    assert result["in_flight_commands"] == 0
    assert result["broker_mutations"] is False
    assert result["observation_id"] > 0
    settled, = journal.load_commands(database, f.bound.identity)
    assert settled.state is CommandState.FILLED
    assert settled.filled_quantity == Decimal("3.983235066")
    rows = database.execute(
        "SELECT fill_key,quantity,price FROM sentinel_fills ORDER BY fill_key").fetchall()
    assert len(rows) == 3 and all(len(row[0]) == 64 for row in rows)
    assert sorted((qty, price) for _, qty, price in rows) == sorted(
        (Decimal(qty), Decimal("335.82")) for qty in quantities)
    assert f.venue.requests["POST /v2/orders"] == 1
    runtime_admission._fence(database)
    replay = asyncio.run(fenced.recover(**kwargs))
    assert replay["status"] == "SKIPPED_CLEAN"
    assert replay["observation_id"] is None
    assert database.execute("SELECT COUNT(*) FROM sentinel_fills").fetchone()[0] == 3
    assert f.venue.requests["POST /v2/orders"] == 1
    # Legacy synthetic fingerprints can match cumulative economics yet must
    # never stand in for this current-plan native execution history.
    monkeypatch.setattr(fenced.fill_integrity, "exact_fill_economics",
                        lambda *_args, **_kwargs: None)
    database.execute("UPDATE sentinel_fills SET fill_key=left(fill_key,24)"
                     " WHERE client_key=%s AND fill_key=(SELECT MIN(fill_key)"
                     " FROM sentinel_fills WHERE client_key=%s)",
                     (command.client_key, command.client_key))
    with pytest.raises(fenced.FencedPaperRecoveryRefused,
                       match="broker-native fill identities"):
        fenced._native_coverage(database,
            journal.load_commands(database, f.bound.identity),
            native_plan_id=f.plan.plan_id)
    database.rollback()
