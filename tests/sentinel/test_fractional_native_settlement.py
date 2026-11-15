"""Two ordinary PAPER orders through the selected Alpaca adapter and cash guard."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D, ROUND_DOWN
from types import SimpleNamespace
from uuid import UUID

import pytest

from sentinel import automation_runtime, binding, schema
from sentinel.execution import alpaca, broker_cash, executor, fractional_sizing, journal, target_reprojection
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.contract import BrokerInstrument
from sentinel.execution.guarded import ExecutionBrokerGuard, GuardedExecutionBroker, ManualExecutionGrant
from sentinel.execution.market_buy_policy import MarketBuyPolicy
from sentinel.execution.simulator import SimulatedBroker
from sentinel.execution.states import CommandState
from sentinel.feed import calendar
from sentinel.paper.cash import _cash_authority_or_refuse
from sentinel.paper.model import PaperRetryableRefused
from tests.sentinel import test_automation_runtime as runtime_fixtures
from tests.sentinel.test_fractional_continuity import owned_plan
from tests.sentinel.test_fractional_execution import DEPLOY, dollars, native_fills, observation
from tests.sentinel.test_fractional_flow import fractional_environment
from tests.sentinel.test_limit_day_sizing import references
from tests.sentinel.test_order_terms_schema import database, pg
from tests.support.current_workflow_clock import BusinessClock
from tests.support.current_workflow_transport import NativeWorkflowAlpaca, Response
from tests.v5.test_opening import base, case


class FractionalVenue(NativeWorkflowAlpaca):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.unpublished = []

    def get(self, url, params):
        path = self.path(url)
        if path.startswith("/v2/assets/"):
            name = path.rsplit("/", 1)[-1]
            item = self.by_id[name] if name in self.by_id else self.assets[name]
            return Response(dict(id=item["id"], symbol=item["symbol"], tradable=True,
                                 status="active", fractionable=True))
        return super().get(url, params)

    def post(self, url, body):
        assert self.path(url) == "/v2/orders"
        assert body["type"] == "market" and body["time_in_force"] == "day" and body["side"] == "buy"
        assert "qty" not in body and "limit_price" not in body
        assert all(row["client_order_id"] != body["client_order_id"] for row in self.orders.values())
        self.requests["POST /v2/orders"] += 1
        index = len(self.orders) + 1
        native = self.by_id[body["symbol"]]
        price, dollars = native["price"], D(body["notional"])
        qty = (dollars / price).quantize(D("0.000000001"), rounding=ROUND_DOWN)
        stamp = self.window()[0] + timedelta(minutes=1)
        when = stamp.isoformat()
        order_id = str(UUID(int=index))
        order = dict(body, id=order_id, asset_id=native["id"], symbol=native["symbol"],
                     qty=None, status="filled", filled_qty=str(qty), filled_avg_price=str(price),
                     submitted_at=when, filled_at=when, created_at=when, updated_at=when)
        self.orders[order["id"]] = order
        self.positions[native["id"]] = qty
        self.cash -= dollars
        self.unpublished.append(dict(
            account_id=self.account_uuid, event_id=f"01J5R00000000000000000{index:03d}",
            ref_id=str(UUID(int=100+index)), activity_type="TRD", status="executed",
            at=when, executed_at=when, settle_date=stamp.date().isoformat(),
            qty=str(qty), price=str(price), currency="USD", net_amount=str(-dollars),
            details=dict(execution_type="fill", order_id=order_id, client_order_id=order["client_order_id"],
                         asset_id=native["id"], side="buy", symbol=native["symbol"])))
        return Response(order)

    def publish(self):
        self.events.extend(self.unpublished)
        self.unpublished.clear()


@pytest.mark.parametrize("owned_reader", [True, False])
def test_cohort_resumes_after_native_fill_publication(database, monkeypatch, fractional_environment, owned_reader):
    async def run():
        schema.ensure_schema(database)
        bound = binding.bind(database, deployment_id="fractional-native", broker="alpaca",
                             broker_account_id="PA-fractional-fixture")
        database.execute("UPDATE sentinel_account_binding SET established_at='2026-02-12T00:00:00Z'")
        database.commit()
        state, raw = case(entries=2)
        plan = replace(raw, **bound.identity.to_dict(), account_nav=D(20000), account_cash=D(20000))
        plan = replace(plan, plan_id="sentinel-" + plan.fingerprint())
        initial = base(state, plan)
        projection = fractional_sizing.resolve(state, plan, initial, references(plan, initial),
            MarketBuyPolicy(True), baseline={"through_event_seq": 0, "commands": [], "holdings": {}},
            retained_targets={})
        journal.save_plan(database, plan)
        target_reprojection.record_projection(database, projection)
        window = calendar.session_window(plan.effective_session)
        clock = BusinessClock(window[0] + timedelta(seconds=61))
        clock.install(monkeypatch)
        instruments = {sid: BrokerInstrument(sid, sid.removeprefix("SEC-"), "asset-" + sid)
                       for sid in projection.opening_sizing["purchases"]}
        assets = {i.symbol: {"id": i.broker_id, "symbol": i.symbol, "price": D("30.07")}
                  for i in instruments.values()}
        venue = FractionalVenue(account=bound.broker_account_id, cash="20000", assets=assets,
                                window=lambda: window)
        inner = AssetIdAlpacaExecutionBroker(api_key="fixture", secret_key="fixture",
            base_url="https://paper-api.alpaca.markets", http_provider=lambda: venue,
            resolve_security_id=lambda symbol, *_: "SEC-" + symbol)
        if not owned_reader:
            monkeypatch.setattr(alpaca.FinancialGradeAlpacaExecutionBroker,
                                "supports_owned_order_fills", property(lambda self: False))

        async def permit(*args, **kwargs):
            pass

        def issuer_permit(**kwargs):
            return SimpleNamespace(allowed=True)

        broker = GuardedExecutionBroker(inner=inner, grant=ManualExecutionGrant(
            bound.broker_account_id, plan.plan_id, plan.effective_session, True),
            guard=ExecutionBrokerGuard(permit, permit, permit), market_buy_funding=permit,
            issuer_admission_check=issuer_permit)

        async def activity():
            return await broker_cash.ingest_account_cash(database, broker_adapter=broker,
                broker=bound.broker, account_id=bound.broker_account_id, through=clock.now())

        async def cash_authority(rec):
            _cash_authority_or_refuse(database, plan=plan, deployment=bound.identity,
                account=await broker.account_snapshot(), observation=rec.observation,
                activity_state=await activity())

        async def tick():
            clock.instant += timedelta(seconds=1)
            return await executor._execute_session_locked(
                broker=broker, conn=database, deployment=bound.identity, plan=plan,
                instruments=instruments, today=plan.effective_session, actions=lambda *_: D(1),
                target_projection=projection, min_increment=D("0.000000001"),
                informational_current_book=True, increase_reconciliation_authority=cash_authority,
                buy_admission=issuer_permit)

        with journal.writer_lock(database, recovery_only=True):
            broker_cash.record_plan_baseline(database, plan_id=plan.plan_id,
                decision_session=plan.decision_session, activity_state=await activity())
            first = await tick()
            assert len(first.submitted) == 1, first.to_dict()
            with pytest.raises(PaperRetryableRefused, match="FILL_PRINCIPAL_PENDING"):
                await tick()
            assert venue.requests["POST /v2/orders"] == 1
            assert journal.load_commands(database, bound.identity)[0].state is CommandState.FILLED
            venue.publish()
            if not owned_reader:
                with pytest.raises(PaperRetryableRefused, match="FILL_PRINCIPAL_PENDING"):
                    await tick()
                assert venue.requests["POST /v2/orders"] == 1
                return
            second = await tick()
            assert len(second.submitted) == 1, second.to_dict()
            assert second.submitted[0].security_id != first.submitted[0].security_id
            venue.publish()
            settled = await tick()
            await cash_authority(settled.reconciliation)
            assert settled.reconciliation.clean and not settled.submitted
            assert venue.requests["POST /v2/orders"] == 2 and venue.cash == D("18002")
            assert database.execute("SELECT COUNT(*) FROM sentinel_fills").fetchone()[0] == 2
    asyncio.run(run())


@pytest.mark.parametrize("state,expected", [(CommandState.CANCELLED, ("598", "999")),
                                             (CommandState.REJECTED, ("999",))])
def test_recovery_routes_unaffected_purchases_inside_window(database, monkeypatch, state, expected):
    t = runtime_fixtures
    schema.ensure_schema(database)
    shadow, raw = case(entries=2)
    plan = owned_plan(raw, account_nav=D(20000))
    initial = base(shadow, plan)
    projection = fractional_sizing.resolve(shadow, plan, initial, references(plan, initial),
        MarketBuyPolicy(True), baseline={"through_event_seq": 0, "commands": [], "holdings": {}},
        retained_targets={})
    journal.save_plan(database, plan)
    target_reprojection.record_projection(database, projection)
    held = "4" if state is CommandState.CANCELLED else "0"
    command = dollars(filled=held, state=state)
    command = replace(command, identity=replace(command.identity, plan_id=plan.plan_id))
    journal.save_command(database, command)
    if state is CommandState.CANCELLED:
        native_fills(database, command)
    observed = observation(held)
    deltas = automation_runtime._actionable_projection_deltas(database, plan=plan,
        effective_session=plan.effective_session, observation=observed, minimum_quantity_increment=D("0.000000001"))
    assert tuple(str(item.notional) for item in deltas) == expected
    cfg = t.config()
    context = t.context(cfg, state=t.CycleState.RECONCILING, plan=plan)
    cycle = context.cycle.model_copy(update={
        **DEPLOY.to_dict(), "decision_session": plan.decision_session, "effective_session": plan.effective_session})
    context = context.model_copy(update={"cycle": cycle})
    runtime = t.production(cfg)
    t.install_runtime_seams(monkeypatch, runtime, database, context, SimulatedBroker())
    monkeypatch.setattr(automation_runtime, "require_observation_integrity", lambda _: None)
    monkeypatch.setattr(automation_runtime.schema, "require_runtime_schema", lambda _: None)
    monkeypatch.setattr(automation_runtime, "_now_utc", lambda: cycle.execute_at + timedelta(seconds=5))

    async def clean(**kwargs):
        return t.reconciliation(observed)

    monkeypatch.setattr(automation_runtime.paper, "recover_automated_paper_cycle", clean)
    result = asyncio.run(runtime.recover(context))
    assert result.disposition is t.ExecuteDisposition.READY_TO_EXECUTE
