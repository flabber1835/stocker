"""LIVE risk reduction retains the exact plan when only whole shares can sell."""
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import automation_runtime
from sentinel.execution import alpaca, executor, fractional_orders, journal, reconcile, target_reprojection
from sentinel.execution.commands import compute_delta
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerAssetRules, BrokerCapabilities, BrokerInstrument,
    BrokerObservation, BrokerPosition, CommandOutcome, Side,
)
from sentinel.execution.guarded import BrokerAuthorityRefused, OrderEvidenceNotReady
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.states import IN_FLIGHT, CommandState, RuntimeState
from tests.sentinel.live_order_fixtures import DAY, NOW, REFERENCE_SESSION


EXIT = BrokerInstrument("SEC-EXIT", "EXIT", "native-exit")
OTHER = BrokerInstrument("SEC-OTHER", "OTHER", "native-other")
BIL = BrokerInstrument("SENTINEL:BIL", "BIL", "native-bil")
INCREMENT = Decimal("0.000000001")
DEPLOYMENT = DeploymentIdentity("offline-fallback", "alpaca-live", "offline-live-account", 1)
ACCOUNT = BrokerAccountIdentity(DEPLOYMENT.broker, DEPLOYMENT.broker_account_id)


class OfflineBroker:
    capabilities = BrokerCapabilities(stable_client_key=True, single_order_cancel=True,
        fractional_quantities=True, minimum_quantity_increment=INCREMENT)

    def __init__(self):
        self.positions = {EXIT: Decimal("12.345"), OTHER: Decimal("2")}
        self.sent = []
        self.rule_reads = []
        self.fractionable = False

    async def identify_account(self):
        return ACCOUNT

    async def asset_rules(self, *, instrument):
        self.rule_reads.append(instrument)
        return BrokerAssetRules(instrument, datetime.now(timezone.utc), self.fractionable)

    def observation(self):
        return BrokerObservation(NOW, account_identity=ACCOUNT, positions=tuple(
            BrokerPosition(instrument, amount)
            for instrument, amount in self.positions.items() if amount))

    async def submit(self, *, client_key, instrument, side, quantity):
        assert side is Side.SELL
        assert quantity <= self.positions[instrument]
        self.sent.append((client_key, instrument, quantity))
        return CommandOutcome(CommandState.ACKNOWLEDGED, broker_order_id=f"order-{len(self.sent)}")


@pytest.fixture
def execution(monkeypatch):
    monkeypatch.delenv("SENTINEL_PAPER_BUY_POLICY", raising=False)
    conn = object()
    broker = OfflineBroker()
    plan = ExecutionPlan("zero-exposure", REFERENCE_SESSION, DAY, Decimal(0),
        deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
        broker_account_id=DEPLOYMENT.broker_account_id, takeover_epoch=DEPLOYMENT.takeover_epoch,
        target_basket={EXIT.security_id: Decimal(0), OTHER.security_id: Decimal(0),
                       BIL.security_id: Decimal(1)})
    projection = target_reprojection.project_target(plan, through_session=DAY,
        action_multipliers={}, minimum_quantity_increment=INCREMENT)
    saved_plan = plan.to_dict()
    saved_projection = projection.payload()
    saved = {}

    def reload_plan():
        return replace(plan, target_basket={sid: Decimal(quantity)
                                          for sid, quantity in saved_plan["target_basket"].items()})

    def reload_projection(_conn, *, plan_id):
        assert plan_id == plan.plan_id
        return target_reprojection._decode(saved_projection, plan_id=plan_id, session=DAY)

    async def observe(**_kwargs):
        return reconcile.ReconciliationResult(RuntimeState.RUNNING, observation=broker.observation())

    def save(_conn, command, *, previous=None):
        assert previous == (saved[command.client_key].state if command.client_key in saved else None)
        saved[command.client_key] = command

    def fill(order):
        recorded = saved[order.client_key]
        assert recorded.state is CommandState.ACKNOWLEDGED
        broker.positions[order.instrument] -= order.quantity
        save(conn, recorded.transition(CommandState.FILLED, filled_quantity=order.quantity,
                                     filled_average_price=Decimal(10)), previous=recorded.state)

    async def run(**kwargs):
        return await executor.execute_session(conn=conn, broker=broker, deployment=DEPLOYMENT,
            plan=reload_plan(), target_projection=reload_projection(conn, plan_id=plan.plan_id), today=DAY,
            min_increment=INCREMENT, instruments={item.security_id: item for item in (EXIT, OTHER, BIL)},
            **kwargs)

    monkeypatch.setattr(journal, "writer_lock", lambda _conn: nullcontext())
    monkeypatch.setattr(journal, "latest_plan", lambda _conn: reload_plan())
    monkeypatch.setattr(target_reprojection, "load_projection", reload_projection)
    monkeypatch.setattr(executor, "_binding", lambda _conn: DEPLOYMENT)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: tuple(
        command for command in saved.values() if command.state in IN_FLIGHT))
    monkeypatch.setattr(journal, "load_commands", lambda *_args, plan_id, security_id=None, states=None: tuple(
        row for row in saved.values() if row.identity.plan_id == plan_id
        and (security_id is None or row.security_id == security_id)
        and (states is None or row.state in states)))
    monkeypatch.setattr(journal, "save_command", save)
    monkeypatch.setattr(reconcile, "reconcile", observe)
    monkeypatch.setattr(alpaca, "upgrade_restore_reason", lambda _conn: "")
    monkeypatch.setattr(alpaca, "execution_increase_fence_reason", lambda **_kwargs: "")
    monkeypatch.setattr(executor, "_settle_reductions",
                        lambda **_kwargs: pytest.fail("remaining exposure cannot fund increases"))
    return SimpleNamespace(broker=broker, plan=plan, run=run, conn=conn,
                           fill=fill, saved=saved, reload_plan=reload_plan)


@pytest.mark.asyncio
async def test_zero_exposure_sale_retains_residual_across_restart_and_never_resells(execution):
    first = await execution.run()
    assert [(row.security_id, row.quantity) for row in first.submitted] == [
        (EXIT.security_id, Decimal(12)), (OTHER.security_id, Decimal(2))]
    assert first.restricted_securities == {EXIT.security_id: "FRACTIONAL_SELL_RESIDUAL: 0.345"}
    assert BIL.security_id in first.deferred
    assert execution.broker.rule_reads == [EXIT]
    for row in first.submitted:
        execution.fill(row)

    reloaded = execution.reload_plan()
    assert reloaded == execution.plan and reloaded.target_basket[EXIT.security_id] == 0
    actionable = automation_runtime._actionable_projection_deltas(execution.conn, plan=reloaded,
        effective_session=DAY, observation=execution.broker.observation(),
        minimum_quantity_increment=INCREMENT)
    assert [(row.side, row.quantity) for row in actionable if row.security_id == EXIT.security_id] == [
        (Side.SELL, Decimal("0.345"))]
    resumed = await execution.run()
    assert not resumed.submitted and len(execution.broker.sent) == 2
    assert resumed.restricted_securities == first.restricted_securities
    assert BIL.security_id in resumed.deferred

    execution.broker.fractionable = True
    recovered = await execution.run(reductions_only=True)
    row, = recovered.submitted
    assert row.quantity == Decimal("0.345") and row.identity.revision == 1
    assert row.client_key != first.submitted[0].client_key
    execution.fill(row)
    assert execution.broker.positions[EXIT] == 0
    assert all(item[1] != BIL for item in execution.broker.sent)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [CommandState.ACKNOWLEDGED, CommandState.UNKNOWN])
async def test_in_flight_sale_is_never_readmitted_by_whole_share_fallback(execution, state):
    first = await execution.run(reductions_only=True)
    order = first.submitted[0]
    retained = replace(execution.saved[order.client_key], state=state)
    execution.saved[order.client_key] = retained
    repost = await execution.run(reductions_only=True)
    assert not repost.submitted and len(execution.broker.sent) == 2
    assert execution.saved[order.client_key] == retained
    assert execution.broker.rule_reads == [EXIT]


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["stale", "future", "wrong-asset", "missing"])
async def test_live_reduction_fallback_requires_explicit_current_asset_rules(fault):
    delta = compute_delta(security_id=EXIT.security_id, desired=Decimal(0),
                          observation=OfflineBroker().observation(), min_increment=INCREMENT)
    age = timedelta(seconds={"stale": -31, "future": 1}.get(fault, -1))
    rules = BrokerAssetRules(OTHER if fault == "wrong-asset" else EXIT,
                             datetime.now(timezone.utc) + age, False)
    class Broker:
        async def asset_rules(self, **_kwargs):
            return None if fault == "missing" else rules
    with pytest.raises(OrderEvidenceNotReady, match="eligibility unavailable"):
        await fractional_orders.choose_live_sale(Broker(), delta=delta, instrument=EXIT)


@pytest.mark.asyncio
async def test_stale_rules_guard_removal_permits_an_unqualified_fallback(monkeypatch):
    monkeypatch.setattr(BrokerAssetRules, "require_current", lambda *_args: None)
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        await test_live_reduction_fallback_requires_explicit_current_asset_rules("stale")


@pytest.mark.asyncio
async def test_live_reduction_fallback_preserves_authority_refusal(monkeypatch, execution):
    async def revoked(**_kwargs):
        raise BrokerAuthorityRefused("scope revoked")
    monkeypatch.setattr(execution.broker, "asset_rules", revoked)
    with pytest.raises(BrokerAuthorityRefused, match="scope revoked"):
        await execution.run()
    assert not execution.broker.sent and not execution.saved
