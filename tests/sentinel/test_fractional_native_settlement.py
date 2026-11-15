"""Two ordinary PAPER orders through the selected Alpaca adapter and cash guard."""
import asyncio
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D, ROUND_DOWN
from types import SimpleNamespace
from uuid import UUID

import pytest

from sentinel import automation_runtime, binding, schema
from sentinel.execution import (
    alpaca, broker_cash, executor, fill_integrity, fractional_sizing, journal,
    reconcile, target_reprojection)
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.guarded import (
    ExecutionBrokerGuard, GuardedExecutionBroker, ManualExecutionGrant, OrderEvidenceNotReady)
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.market_buy_policy import FRACTIONAL_MODE, MarketBuyPolicy
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.simulator import SimulatedBroker
from sentinel.execution.states import CommandState, RuntimeState
from sentinel.feed import calendar
from sentinel.paper.cash import _cash_authority_or_refuse
from sentinel.paper.model import PaperRetryableRefused
from sentinel.paper.reconciliation_evidence import _dual_mutation_observation_or_refuse
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
        if path == "/v2/account":
            self.requests["GET " + path] += 1
            equity = self.cash + sum((qty * self.by_id[asset_id]["price"]
                                      for asset_id, qty in self.positions.items()), D(0))
            reserved = sum((D(order["notional"]) for order in self.orders.values()
                            if order["status"] in {"new", "partially_filled"}), D(0))
            return Response(dict(id=self.account_uuid, account_number=self.account, currency="USD",
                created_at="2026-02-12T00:00:00Z", cash=str(self.cash), equity=str(equity),
                last_equity=str(equity), buying_power=str(max(D(0), self.cash - reserved)),
                multiplier="1", status="ACTIVE", trading_blocked=False, account_blocked=False,
                trade_suspended_by_user=False))
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

    def publish_partial(self, order, *parts):
        fill = self.unpublished.pop()
        price = D(fill["price"])
        quantity = sum(parts, D(0))
        order.update(status="partially_filled", filled_qty=str(quantity), filled_at=None)
        self.cash += D(order["notional"]) - price * quantity
        self.positions[order["asset_id"]] = quantity
        for index, part in enumerate(parts, 1):
            # Distinct native nanosecond clocks can serialize to the same Python/Postgres clock.
            raw_time = fill["executed_at"].replace("+00:00", f".00000000{index}Z")
            self.events.append(dict(fill, event_id=f"01J5R00000000000000000{index:03d}",
                ref_id=str(UUID(int=100+index)), qty=str(part), net_amount=str(-part*price),
                executed_at=raw_time))


@pytest.fixture
def fractional_recovery_case(database, monkeypatch, fractional_environment):
    schema.ensure_schema(database)
    bound = binding.bind(database, deployment_id="fractional-native", broker="alpaca",
                         broker_account_id="PA-fractional-fixture")
    database.execute("UPDATE sentinel_account_binding SET established_at='2026-02-12T00:00:00Z'")
    database.commit()
    sid = "SEC-AAA"
    plan = ExecutionPlan("native-fill-recovery", date(2026, 8, 11), date(2026, 8, 12), D(1),
        {sid: D(0)}, **bound.identity.to_dict(), account_nav=D(20000), account_cash=D(20000))
    projection = target_reprojection.TargetProjection(plan.plan_id, plan.fingerprint(),
        plan.effective_session, {}, (), {}, plan.target_basket, opening_sizing={"mode": FRACTIONAL_MODE})
    journal.save_plan(database, plan)
    target_reprojection.record_projection(database, projection)
    window = calendar.session_window(plan.effective_session)
    clock = BusinessClock(window[0] + timedelta(seconds=61))
    clock.install(monkeypatch)
    instrument = BrokerInstrument(sid, sid.removeprefix("SEC-"), "asset-" + sid)
    assets = {instrument.symbol: {"id": instrument.broker_id, "symbol": instrument.symbol,
                                 "price": D("30.07")}}
    venue = FractionalVenue(account=bound.broker_account_id, cash="20000", assets=assets,
                            window=lambda: window)
    broker = AssetIdAlpacaExecutionBroker(api_key="fixture", secret_key="fixture",
        base_url="https://paper-api.alpaca.markets", http_provider=lambda: venue,
        resolve_security_id=lambda symbol, *_: sid if symbol == "RENAMED" else "SEC-" + symbol)

    async def poll():
        return await reconcile.reconcile(broker=broker, conn=database, binding=bound,
            deployment=bound.identity, informational_current_book=True)

    async def activity():
        return await broker_cash.ingest_account_cash(database, broker_adapter=broker,
            broker=bound.broker, account_id=bound.broker_account_id, through=clock.now())

    command = Command(CommandIdentity(bound.identity, plan.plan_id, sid), instrument, Side.BUY,
        None, notional=D("999"), state=CommandState.ACKNOWLEDGED, broker_order_id=str(UUID(int=1)))

    def buy(durable=command):
        journal.save_command(database, durable)
        return venue.post("https://paper-api.alpaca.markets/v2/orders", dict(type="market",
            time_in_force="day", side="buy", symbol=instrument.broker_id, notional="999",
            client_order_id=command.client_key, order_class="simple", extended_hours=False)).payload

    return SimpleNamespace(venue=venue, clock=clock, command=command, plan=plan, bound=bound,
                           broker=broker, poll=poll, activity=activity, buy=buy)


@pytest.mark.parametrize("expires", [True, False])
@pytest.mark.parametrize("state", [CommandState.ACKNOWLEDGED, CommandState.SEND_PENDING, CommandState.UNKNOWN])
def test_notional_position_lead_only_waits_for_agreeing_native_fills(
        database, fractional_recovery_case, expires, state):
    f = fractional_recovery_case
    order_id = f.command.broker_order_id
    asset_id = f.command.instrument.broker_id

    async def run():
        with journal.writer_lock(database, recovery_only=True):
            durable = f.command if state is CommandState.ACKNOWLEDGED else replace(
                f.command, state=state, broker_order_id=None)
            filled = f.buy(durable)
            f.venue.orders[order_id] = dict(filled, status="new", filled_qty="0",
                                          filled_avg_price=None, filled_at=None)
            f.venue.publish()
            pending = await f.poll()
            assert pending.runtime_state is RuntimeState.RECONCILING
            assert not pending.foreign_positions and not pending.transport_ready
            assert not pending.expected
            assert f.venue.requests["GET /v2beta1/events/activities"] > 0
            assert database.execute("SELECT count(*) FROM sentinel_fills").fetchone()[0] == 0
            with pytest.raises(PaperRetryableRefused):
                _dual_mutation_observation_or_refuse(pending)
            if expires:
                f.clock.instant += reconcile.POSITION_LAG_GRACE / 2
                f.venue.positions[asset_id] -= D(1)
                assert (await f.poll()).runtime_state is RuntimeState.RECONCILING
                f.clock.instant += reconcile.POSITION_LAG_GRACE / 2 + timedelta(seconds=1)
                expired = await f.poll()
                assert expired.runtime_state is RuntimeState.FOREIGN_ACTIVITY
                assert expired.foreign_positions == (f.command.security_id,)
                return
            f.venue.orders[order_id] = filled
            reconciled = await f.poll()
            assert reconciled.transport_ready and reconciled.expected == reconciled.observed
            assert database.execute("SELECT count(*) FROM sentinel_fills").fetchone()[0] == 1
    asyncio.run(run())


def test_durable_replay_preserves_identical_economics_under_distinct_native_ids(database, fractional_recovery_case):
    f = fractional_recovery_case

    async def run():
        with journal.writer_lock(database, recovery_only=True):
            order = f.buy()
            f.venue.publish_partial(order, D(4), D(4))
            first = await f.poll()
            assert first.transport_ready
            fills = first.observation.fills
            assert len(fills) == 2 and fills[0].activity_id != fills[1].activity_id
            assert fills[0].filled_at == fills[1].filled_at
            reads = f.venue.requests["GET /v2beta1/events/activities"]

            f.clock.instant += timedelta(seconds=1)
            replay = await f.poll()
            assert replay.transport_ready
            assert f.venue.requests["GET /v2beta1/events/activities"] == reads
            assert database.execute("SELECT count(*) FROM sentinel_fills").fetchone()[0] == 2
    asyncio.run(run())


@pytest.mark.parametrize("raw_status", ["pending_cancel", "partially_filled", "done_for_day", "calculated"])
def test_notional_fill_advances_without_releasing_a_pending_cancel(database, fractional_recovery_case, raw_status):
    f = fractional_recovery_case

    async def run():
        with journal.writer_lock(database, recovery_only=True):
            order = f.buy(replace(f.command, state=CommandState.CANCEL_PENDING))
            f.venue.publish_partial(order, D(8))
            order["status"] = raw_status
            result = await f.poll()
            assert result.transport_ready and result.expected == result.observed == {f.command.security_id: D(8)}
            saved, = journal.in_flight_commands(database, f.bound.identity)
            assert saved.state is CommandState.CANCEL_PENDING and saved.filled_quantity == D(8)
            assert database.execute("SELECT count(*) FROM sentinel_fills").fetchone()[0] == 1
            before = result.observation.by_client_key(saved.client_key)
            assert before.state is (CommandState.CANCEL_PENDING if raw_status == "pending_cancel"
                                    else CommandState.PARTIALLY_FILLED)

            get = f.venue.get

            def terminal_get(url, params):
                if f.venue.path(url) == "/v2/orders" and params.get("status") == "open":
                    return Response([])
                return get(url, params)

            order["status"] = "canceled"
            f.venue.get = terminal_get
            f.clock.instant += timedelta(seconds=1)
            terminal = await f.poll()
            assert terminal.transport_ready and terminal.expected == result.expected
            settled, = journal.load_commands(database, f.bound.identity)
            assert settled.state is CommandState.CANCELLED and settled.filled_quantity == D(8)
            assert not journal.in_flight_commands(database, f.bound.identity)
    asyncio.run(run())


@pytest.mark.parametrize("retry_blocked_before_transport", [True, False])
def test_later_refusal_cannot_mark_a_throttled_fractional_sale_unsent(
        database, fractional_recovery_case, retry_blocked_before_transport):
    f = fractional_recovery_case
    posts = []
    preparations = []

    def post(url, body):
        assert f.venue.path(url) == "/v2/orders"
        posts.append(body["client_order_id"])
        if len(posts) == 1:
            response = Response(status=429, text="rate limited")
            response.headers = {"Retry-After": "0"}
            return response
        response = Response(status=422, text="sale refused on retry")
        response.headers = {"X-Request-ID": "native-retry-422"}
        return response

    async def read(*_args):
        pass

    async def authorize(*args):
        preparations.append(args)
        if len(preparations) == 2 and retry_blocked_before_transport:
            raise OrderEvidenceNotReady("second sale preparation was refused")

    f.venue.post = post
    broker = GuardedExecutionBroker(inner=f.broker,
        grant=ManualExecutionGrant(f.bound.broker_account_id, f.plan.plan_id, f.plan.effective_session, True),
        guard=ExecutionBrokerGuard(read, read, authorize))
    sale = replace(f.command, side=Side.SELL, quantity=D("0.5"), notional=None,
                   state=CommandState.PLANNED, broker_order_id=None)

    async def run():
        with journal.writer_lock(database, recovery_only=True):
            result = await executor._persist_and_send(database, broker, sale)
            assert result.state is CommandState.UNKNOWN and "HTTP 429" in result.detail
            assert len(preparations) == 2
            assert posts == [sale.client_key] * (1 if retry_blocked_before_transport else 2)
            assert [entry["to"] for entry in journal.command_history(database, sale.client_key)] == [
                "PLANNED", "SEND_PENDING", "UNKNOWN"]
    asyncio.run(run())


@pytest.mark.parametrize("same_native_asset", [True, False])
def test_native_fill_replay_uses_permanent_identity_across_ticker_rename(
        database, fractional_recovery_case, same_native_asset):
    f = fractional_recovery_case

    async def run():
        with journal.writer_lock(database, recovery_only=True):
            order = f.buy()
            first = await f.poll()
            assert first.transport_ready
            old_symbol = f.command.instrument.symbol
            assert f.venue.unpublished[0]["details"]["symbol"] == old_symbol
            venue_asset = f.venue.by_id[f.command.instrument.broker_id]
            f.venue.assets["RENAMED"] = venue_asset
            venue_asset["symbol"] = "RENAMED"
            order["symbol"] = "RENAMED"
            if not same_native_asset:
                f.venue.unpublished[0]["details"]["asset_id"] = "unrelated-native-asset"
            f.venue.publish()
            observed = await f.poll()
            if not same_native_asset:
                assert observed.runtime_state is RuntimeState.RECONCILING
                assert "asset or side contradicts order" in observed.detail
                assert database.execute("SELECT count(*) FROM sentinel_fills").fetchone()[0] == 0
                return
            assert observed.transport_ready
            assert observed.observation.exact_by_client_key(f.command.client_key).order.instrument.symbol == "RENAMED"
            assert observed.observation.fills[0].raw["details"]["symbol"] == old_symbol
            assert database.execute("SELECT count(*) FROM sentinel_fills").fetchone()[0] == 1
    asyncio.run(run())


@pytest.mark.parametrize("at_half_cent", [True, False])
def test_missing_native_cash_derives_exact_cents_and_imports_later_posting(
        database, fractional_recovery_case, at_half_cent):
    f = fractional_recovery_case

    async def run():
        with journal.writer_lock(database, recovery_only=True):
            broker_cash.record_plan_baseline(database, plan_id=f.plan.plan_id,
                decision_session=f.plan.decision_session, activity_state=await f.activity())
            order = f.buy()
            fill, = f.venue.unpublished
            if at_half_cent:
                order.update(filled_qty="9.98995", filled_avg_price="100")
                fill.update(qty="9.98995", price="100")
                f.venue.positions[f.command.instrument.broker_id] = D("9.98995")
            fill.pop("net_amount")
            f.venue.publish()
            result = await f.poll()
            stored, = journal.load_commands(database, f.bound.identity, plan_id=f.plan.plan_id)
            if not at_half_cent:
                economics = fill_integrity.exact_fill_economics(database, stored)
                assert economics.gross != D("999") and economics.cash == D("-999")
            fee = dict(fill, activity_type="FEE", activity_subtype="CAT", details={},
                       event_id="01J5R00000000000000000002", ref_id=str(UUID(int=202)), net_amount="-0.01")
            fee.pop("qty")
            fee.pop("price")
            f.venue.events.append(fee)
            f.venue.cash -= D("0.01")
            f.clock.instant += timedelta(seconds=1)
            state = await f.activity()
            account = await f.broker.account_snapshot()

            def check_cash():
                return _cash_authority_or_refuse(database, plan=f.plan, deployment=f.bound.identity,
                    account=account, observation=result.observation, activity_state=state,
                    allow_native_fee_wait=True)

            if at_half_cent:
                with pytest.raises(PaperRetryableRefused, match="FILL_CASH_PENDING.*half cent"):
                    check_cash()
            else:
                assert check_cash() is False

            fill["net_amount"] = "-999"
            f.clock.instant += timedelta(seconds=1)
            enriched = await f.poll()
            assert check_cash() is False
            assert database.execute("SELECT count(*) FROM sentinel_fills").fetchone()[0] == 1
            posted, = database.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name LIKE %s",
                                       (journal.FILL_CASH_PREFIX + "%",)).fetchone()
            assert posted["amount"] == "-999"
            with pytest.raises(journal.FillEconomicsChanged, match="changed cash impact"):
                journal.record_fills(database, (replace(enriched.observation.fills[0], cash_amount=D("-998.999")),))
    asyncio.run(run())


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
