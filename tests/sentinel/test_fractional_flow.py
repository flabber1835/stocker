"""Exercise the existing journal/reconciler/executor with native dollar orders."""
import asyncio
from dataclasses import replace
from datetime import date, timedelta, timezone
from decimal import Decimal as D
import inspect
import textwrap

import pytest

from sentinel import binding, schema
from sentinel.execution import executor, fractional_progress, fractional_sizing, issuer_admission, issuer_runtime, journal, recovery, target_reprojection
from sentinel.execution.contract import BrokerAssetRules, Side
from sentinel.execution.guarded import GuardedExecutionBroker, OrderEvidenceNotReady, PreTransportAuthorityRefused
from sentinel.execution.market_buy_policy import FRACTIONAL_MODE, MarketBuyPolicy
from sentinel.execution.simulator import FaultKind
from sentinel.execution.states import CommandState as S
from sentinel.feed import calendar
from tests.sentinel.test_order_terms_schema import pg, database, _compiled
from tests.sentinel.test_market_buy_policy import MARKET_ENV
from tests.sentinel.test_market_day_execution import MarketBroker, wrapper, set_clock, market_instruments, DEPLOYMENT
from tests.sentinel.test_limit_day_sizing import references
from tests.v5.test_opening import case, base


@pytest.fixture(autouse=True)
def fractional_environment(monkeypatch):
    for key, value in {**MARKET_ENV, "SENTINEL_PAPER_BUY_POLICY": FRACTIONAL_MODE}.items():
        monkeypatch.setenv(key, value)


class DollarBroker(MarketBroker):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.capabilities = replace(self.capabilities, notional_market_buys=True,
                                    minimum_quantity_increment=D("0.000000001"))
        self.fractionable = True
        self.dollars = {}

    async def asset_rules(self, *, instrument):
        return BrokerAssetRules(instrument, self.now, self.fractionable)

    def _native(self, order):
        if order is not None and order.client_key in self.dollars:
            return replace(order, quantity=None, notional=self.dollars[order.client_key])
        return order

    def _snapshot_orders(self):
        return (self._native(order) for order in super()._snapshot_orders())

    async def find_by_client_key(self, client_key):
        result = await super().find_by_client_key(client_key)
        return replace(result, order=self._native(result.order))

    async def submit(self, *, client_key, instrument, side, quantity, notional=None):
        if notional is not None:
            assert quantity is None
            self.dollars[client_key] = notional
            quantity = notional / D(100)  # deterministic private exchange fill price
        return await super().submit(client_key=client_key, instrument=instrument,
                                    side=side, quantity=quantity)


def test_guard_funds_dollars_without_requesting_a_quote():
    inner = DollarBroker(cash=D(1000))
    inner.missing_quote = True
    set_clock(inner, 60)
    result = asyncio.run(wrapper(inner).submit(client_key="dollar", instrument=market_instruments()["SEC-AAA"],
        side=Side.BUY, quantity=None, notional=D("999")))
    assert result.state is S.ACKNOWLEDGED and inner.dollars == {"dollar": D(999)}


@pytest.mark.parametrize("cash,power", [("999", "1000"), ("1000", "999")])
def test_notional_and_headroom_fit_both_native_cash_bounds(cash, power):
    inner = DollarBroker(cash=D(cash), buying_power=D(power))
    set_clock(inner, 60)
    with pytest.raises(OrderEvidenceNotReady, match="headroom exceeds"):
        asyncio.run(wrapper(inner).submit(client_key="dollar", instrument=market_instruments()["SEC-AAA"],
            side=Side.BUY, quantity=None, notional=D(999)))
    assert not inner.dollars


def test_cash_guard_falsifier(monkeypatch):
    monkeypatch.setattr(GuardedExecutionBroker, "_prepare_submit", _compiled(
        GuardedExecutionBroker._prepare_submit,
        "if estimate > spendable:", "if False:"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_notional_and_headroom_fit_both_native_cash_bounds("999", "1000")


@pytest.mark.parametrize("delay,automated,crosses,accepted", [
    (30, True, False, True),
    (30, True, True, False),
    (30, False, True, True),
    (60, True, True, False),
])
def test_signed_buy_cutoff_is_rechecked_after_fresh_authority(monkeypatch, delay, automated, crosses, accepted):
    from sentinel.automation_runtime import config_from_env
    from sentinel.execution.guarded import AutomationExecutionGrant

    monkeypatch.setenv("SENTINEL_AUTOMATION_EXECUTION_DELAY_SECONDS", str(delay))
    config = config_from_env()
    cutoff = delay + config.maximum_execution_lateness_seconds
    inner = DollarBroker(cash=D(1000))
    set_clock(inner, cutoff - 1)
    checks = []

    async def authority(*args):
        checks.append(inner.now)
        if crosses:
            set_clock(inner, cutoff)

    broker = wrapper(inner, before_mutation=authority)
    if automated:
        broker._grant = AutomationExecutionGrant(
            "EXECUTE", "cycle", 1, "holder", 1, "SIM-ACCOUNT", 1, "CONTROLLER", 1,
            "a" * 64, config_sha256=config.fingerprint)
    initial_clock = inner.now
    call = broker.submit(client_key="signed-cutoff", instrument=market_instruments()["SEC-AAA"],
                         side=Side.BUY, quantity=None, notional=D(100))
    if accepted:
        assert asyncio.run(call).state is S.ACKNOWLEDGED
        assert inner.dollars == {"signed-cutoff": D(100)}
    else:
        with pytest.raises(OrderEvidenceNotReady, match="final next-open freshness"):
            asyncio.run(call)
        assert not inner.dollars
    assert checks == [initial_clock]


def test_signed_buy_cutoff_falsifier(monkeypatch):
    monkeypatch.setattr(GuardedExecutionBroker, "_prepare_submit", _compiled(
        GuardedExecutionBroker._prepare_submit,
        "latest = min(latest, scheduled_cutoff)", "latest = latest"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_signed_buy_cutoff_is_rechecked_after_fresh_authority(monkeypatch, 30, True, True, False)


def test_reduction_scope_refuses_buy_at_transport_even_before_cutoff():
    from sentinel.execution.guarded import AutomationExecutionGrant

    inner = DollarBroker(cash=D(1000))
    set_clock(inner, 60)
    broker = wrapper(inner)
    broker._grant = AutomationExecutionGrant(
        "EXECUTE", "cycle", 1, "holder", 1, "SIM-ACCOUNT", 1, "CONTROLLER", 1,
        "a" * 64, reduction_only_reconciliation_id="fresh-book")
    with pytest.raises(PreTransportAuthorityRefused, match="reductions-only execution requires a SELL"):
        asyncio.run(broker.submit(client_key="dollar", instrument=market_instruments()["SEC-AAA"],
                                  side=Side.BUY, quantity=None, notional=D(999)))
    assert not inner.dollars


def test_reduction_scope_transport_guard_falsifier(monkeypatch):
    monkeypatch.setattr(GuardedExecutionBroker, "_prepare_submit", _compiled(
        GuardedExecutionBroker._prepare_submit,
        "and side is not Side.SELL):", "and False):"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_reduction_scope_refuses_buy_at_transport_even_before_cutoff()


@pytest.mark.parametrize("override", [{}, {"fractionable": False}, {"id": "other"},
                                      {"symbol": "OTHER"}, {"tradable": False}])
def test_native_fractional_sell_proves_final_asset_in_one_lookup(monkeypatch, override):
    from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
    from tests.sentinel.test_issue_183_alpaca_hardening import INSTRUMENT, full_order
    from tests.sentinel.test_limit_day_transport import broker_for

    opened, closed = calendar.session_window(date(2026, 8, 18))
    now = opened + timedelta(minutes=15)
    asset_route = f"/v2/assets/{INSTRUMENT.broker_id}"
    inner, http = broker_for(AssetIdAlpacaExecutionBroker,
        payload=full_order(side="sell", quantity="4.5"), routes={
            "/v2/clock": {"timestamp": now.isoformat(), "is_open": True,
                          "next_open": (opened + timedelta(days=1)).isoformat(),
                          "next_close": closed.isoformat()},
            asset_route: {"id": INSTRUMENT.broker_id, "symbol": INSTRUMENT.symbol,
                          "status": "active", "tradable": True, "fractionable": True, **override}})
    monkeypatch.setattr(inner, "now", now, raising=False)
    monkeypatch.setattr(inner, "_now", lambda: now)
    call = wrapper(inner).submit(client_key="key-1", instrument=INSTRUMENT,
                                 side=Side.SELL, quantity=D("4.5"))
    if override:
        with pytest.raises(OrderEvidenceNotReady):
            asyncio.run(call)
        assert [step[1] for step in http.calls] == ["/v2/clock", asset_route]
    else:
        assert asyncio.run(call).state is S.ACKNOWLEDGED
        assert [(step[0], step[1]) for step in http.calls] == [
            ("GET", "/v2/clock"), ("GET", asset_route), ("POST", inner.base_url + "/v2/orders")]
        assert http.calls[-1][2]["symbol"] == INSTRUMENT.broker_id


def test_native_fractional_sell_deduplication_falsifier(monkeypatch):
    monkeypatch.setattr(GuardedExecutionBroker, "_prepare_submit", _compiled(
        GuardedExecutionBroker._prepare_submit, "and not revalidate_by_asset_rules:", "and True:"))
    with pytest.raises(PreTransportAuthorityRefused, match="instrument identity"):
        test_native_fractional_sell_proves_final_asset_in_one_lookup(monkeypatch, {})


def test_eligibility_change_leaves_unsent_dollar_command_provable(database):
    schema.ensure_schema(database)
    inner = DollarBroker()
    inner.fractionable = False
    set_clock(inner, 60)
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity
    command = Command(CommandIdentity(DEPLOYMENT, "test", "SEC-AAA", 0),
        market_instruments()["SEC-AAA"], Side.BUY, None, notional=D(100))
    result = asyncio.run(executor._persist_and_send(database, wrapper(inner), command))
    assert result.state is S.PLANNED and not inner.dollars
    assert journal.load_commands(database, DEPLOYMENT)[0].state is S.PLANNED


def test_funding_read_failure_is_proven_unsent_and_can_resume(database):
    schema.ensure_schema(database)
    inner = DollarBroker()
    set_clock(inner, 60)
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity
    command = Command(CommandIdentity(DEPLOYMENT, "test", "SEC-AAA", 0),
        market_instruments()["SEC-AAA"], Side.BUY, None, notional=D(100))
    async def unavailable(**kwargs):
        raise TimeoutError("funding evidence temporarily unavailable")
    with pytest.raises(PreTransportAuthorityRefused, match="funding unavailable before transport"):
        asyncio.run(executor._persist_and_send(database, wrapper(inner, funding=unavailable), command))
    result, = journal.load_commands(database, DEPLOYMENT)
    assert result.state is S.PLANNED and not inner.dollars
    assert not any(call.startswith("submit:") for call in inner.calls)
    resumed = asyncio.run(executor._persist_and_send(database, wrapper(inner), result))
    assert resumed.state is S.ACKNOWLEDGED and inner.dollars == {command.client_key: D(100)}


def test_native_accept_then_timeout_stays_unknown_and_recovers_same_dollars(database):
    schema.ensure_schema(database)
    inner = DollarBroker()
    set_clock(inner, 60)
    inner.schedule_submit(FaultKind.ACCEPT_THEN_TIMEOUT)
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity
    command = Command(CommandIdentity(DEPLOYMENT, "test", "SEC-AAA", 0),
        market_instruments()["SEC-AAA"], Side.BUY, None, notional=D(100))
    broker = wrapper(inner)
    result = asyncio.run(executor._persist_and_send(database, broker, command))
    assert result.state is S.UNKNOWN
    resolved = asyncio.run(recovery.resolve_unknown(broker, result, asyncio.run(broker.observe())))
    assert resolved.state is S.ACKNOWLEDGED and resolved.notional == 100 and resolved.quantity is None
    assert inner.calls.count("submit:" + command.client_key) == 1


async def serial_flow(database, monkeypatch, *, continuation=None):
    schema.ensure_schema(database)
    binding.bind(database, deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
                 broker_account_id=DEPLOYMENT.broker_account_id)
    state, original = case(entries=2 if continuation is None else 3)
    plan = replace(original, deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
                   broker_account_id=DEPLOYMENT.broker_account_id, takeover_epoch=1)
    plan = replace(plan, plan_id="sentinel-" + plan.fingerprint())
    raw = base(state, plan)
    projection = fractional_sizing.resolve(state, plan, raw, references(plan, raw), MarketBuyPolicy(True),
        baseline={"through_event_seq": 0, "commands": [], "holdings": {}}, retained_targets={})
    journal.save_plan(database, plan)
    target_reprojection.record_projection(database, projection)
    inner = DollarBroker()
    opened, _ = calendar.session_window(plan.effective_session)
    inner.now = opened.astimezone(timezone.utc) + timedelta(seconds=60)
    observe_orders = inner.observe

    async def observe_fills():
        snapshot = await observe_orders()
        return replace(snapshot, fills=await inner.recent_fills(opened))

    monkeypatch.setattr(inner, "observe", observe_fills)
    database.execute("UPDATE sentinel_account_binding SET established_at=%s", (opened,))
    database.commit()
    from sentinel.execution import reconcile
    from sentinel.feed import issuer_reference
    instruments = market_instruments()
    if continuation is not None:
        from sentinel.execution.contract import BrokerInstrument
        instruments["SEC-CCC"] = BrokerInstrument("SEC-CCC", "CCC", "sim-asset-SEC-CCC")
    source = issuer_reference.IssuerReferenceSnapshot.create(observed_at_utc=inner.now,
        associations=[{'cik': str(i).zfill(10), 'ticker': asset.symbol, 'exchange': 'NYSE'}
                      for i, asset in enumerate(instruments.values(), 1)],
        coverage='PARTIAL', source_method='WEB_EXTRACTED_REPRESENTATION')
    descriptors = {sid: issuer_admission.Instrument(security_id=sid,
        provider_asset_id=asset.broker_id, symbol=asset.symbol, exchange='NYSE',
        security_type='Common Stock', security_type2='Common Stock')
        for sid, asset in instruments.items()}
    monkeypatch.setattr(issuer_reference, 'load_snapshot', lambda: source)
    monkeypatch.setattr(issuer_runtime, 'reference_instruments', lambda *_: descriptors)
    admission = issuer_runtime.PaperIssuerAdmission(conn=database, binding=DEPLOYMENT,
                                                    clock=lambda: inner.now)
    broker = wrapper(inner, issuer_check=admission.final_check)
    with journal.writer_lock(database, recovery_only=True):
        from sentinel.automation_runtime import _actionable_projection_deltas
        from sentinel import trial
        rec = await reconcile.reconcile(broker=broker, conn=database,
            binding=None, deployment=DEPLOYMENT)
        issuer_admission.enroll(database, binding=DEPLOYMENT, state=state,
            reconciliation=rec, snapshot=source, instruments=descriptors, now=inner.now)
        admission.prepare_for_transport(publication=object(), state=state, plan=plan,
            projection=projection, reconciliation=rec)
        assert admission.evidence is not None, admission.error
        if continuation is not None:
            from sentinel.paper.model import ExecutionResult
            native_submit = inner.submit
            checked_books = []

            async def submit(**kwargs):
                result = await native_submit(**kwargs)
                if continuation not in {"working", "unknown", "rejected"}:
                    inner.fill(kwargs["client_key"])
                if continuation == "new_reconciliation_required":
                    inner.schedule_observe(FaultKind.PARTIAL_OBSERVATION)
                return result

            async def fresh_cash(latest):
                assert not journal.in_flight_commands(database, DEPLOYMENT)
                assert not any(order.is_working for order in latest.observation.orders)
                assert latest.clean
                checked_books.append(latest.observation_id)
                if continuation == "cash" and len(checked_books) == 2:
                    raise RuntimeError("new account cash is unavailable")

            if continuation in {"unknown", "rejected"}:
                inner.schedule_submit(FaultKind.ACCEPT_THEN_TIMEOUT if continuation == "unknown"
                                      else FaultKind.REJECT)
            monkeypatch.setattr(inner, "submit", submit)
            async def invoke():
                return await executor._execute_session_locked(
                    broker=broker, conn=database, deployment=DEPLOYMENT,
                    plan=plan, instruments=instruments, today=plan.effective_session,
                    actions=lambda *args: D(1), target_projection=projection,
                    min_increment=D("0.000000001"), buy_admission=admission.check_buy,
                    informational_current_book=True,
                    increase_reconciliation_authority=fresh_cash,
                    market_buy_window_open=(None if continuation == "handoff"
                                            else lambda: continuation != "expired"))

            current = await invoke()
            if continuation == "immediate":
                assert [command.security_id for command in current.submitted] == [
                    "SEC-AAA", "SEC-BBB", "SEC-CCC"], current.to_dict()
                assert len(set(checked_books)) == 3 and all(checked_books)
                assert not current.deferred
            elif continuation == "handoff":
                second, third = await invoke(), await invoke()
                assert [tuple(command.security_id for command in result.submitted)
                        for result in (current, second, third)] == [("SEC-AAA",), ("SEC-BBB",), ("SEC-CCC",)]
                assert len(set(checked_books)) == 3 and all(checked_books)
            else:
                assert [command.security_id for command in current.submitted] == ["SEC-AAA"], current.to_dict()
                assert current.deferred == ("SEC-BBB", "SEC-CCC")
                assert current.settlement_deferred == (
                    ("SEC-BBB", "SEC-CCC") if continuation == "working" else ())
                assert ExecutionResult(plan, rec, current).needs_attention is (continuation != "working")
                if continuation == "cash":
                    assert len(checked_books) == 2 and "new account cash" in current.detail
            return
        async def tick():
            return await executor._execute_session_locked(broker=broker, conn=database,
                deployment=DEPLOYMENT, plan=plan, instruments=instruments,
                today=plan.effective_session, actions=lambda *args: D(1),
                target_projection=projection, min_increment=D("0.000000001"),
                buy_admission=admission.check_buy)
        first = await tick()
        assert len(first.submitted) == 1, first.to_dict()
        command = first.submitted[0]
        assert command.security_id == "SEC-AAA" and command.notional == 4999 and command.quantity is None
        inner.fill(command.client_key, "0.5")
        partial = await tick()
        assert not partial.submitted, partial.to_dict()
        current = journal.load_commands(database, DEPLOYMENT, client_keys=(command.client_key,))[0]
        assert current.filled_quantity == D("0.5") and current.state is S.PARTIALLY_FILLED
        inner.fill(command.client_key)
        second = await tick()
        assert len(second.submitted) == 1 and second.submitted[0].security_id == "SEC-BBB", second.to_dict()
        inner.fill(second.submitted[0].client_key)
        settled = await tick()
        assert not settled.submitted and not settled.deferred, settled.to_dict()
        result = fractional_progress.derive(database, projection=projection, deployment=DEPLOYMENT)
        assert result.targets["SEC-AAA"] == D("49.99") and not result.budgets
        effective, witness = trial._fulfilled_projection(database, projection=projection, deployment=DEPLOYMENT)
        assert effective == result.targets
        fractional_progress.require_completed(witness)
        assert not _actionable_projection_deltas(database, plan=plan,
            effective_session=plan.effective_session, observation=await broker.observe(),
            minimum_quantity_increment=D("0.000000001"))
        assert all(c.side is Side.BUY for c in journal.load_commands(database, DEPLOYMENT))


def test_real_reconciliation_keeps_partial_shares_and_serializes_two_dollar_buys(database, monkeypatch):
    asyncio.run(serial_flow(database, monkeypatch))


@pytest.mark.parametrize("outcome", ["immediate", "handoff", "working", "cash", "expired",
                                   "new_reconciliation_required", "unknown", "rejected"])
def test_guarded_market_buy_continuation_uses_fresh_settlement(database, monkeypatch, outcome):
    asyncio.run(serial_flow(database, monkeypatch, continuation=outcome))


def test_serial_buy_guard_falsifier(database, monkeypatch):
    monkeypatch.setattr(executor, "_execute_session_locked", _compiled(
        executor._execute_session_locked, "if market and delta.is_increase:", "if False:"))
    with pytest.raises(AssertionError):
        asyncio.run(serial_flow(database, monkeypatch))


def test_real_issuer_guard_falsifier(database, monkeypatch):
    monkeypatch.setattr(issuer_admission, "check_buy", _compiled(
        issuer_admission.check_buy, "or Decimal(purchases.get(sid, {}).get('budget', '0')) > 0", "or False"))
    with pytest.raises(AssertionError, match="ISSUER_POSITIVE_TARGET_REQUIRED"):
        asyncio.run(serial_flow(database, monkeypatch))


def test_twenty_fractional_reductions_need_one_basket_admission(database, monkeypatch):
    from sentinel.execution.commands import Command
    from sentinel.execution import feed_inputs
    from sentinel.execution.contract import BrokerInstrument
    from sentinel.execution.identity import CommandIdentity
    from sentinel.paper import targets

    async def run():
        schema.ensure_schema(database)
        binding.bind(database, deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
                     broker_account_id=DEPLOYMENT.broker_account_id)
        state, original = case(entries=1, exposure="0.55")
        instruments = {
            f"SEC-A{i:02d}": BrokerInstrument(f"SEC-A{i:02d}", f"A{i:02d}", f"sim-asset-SEC-A{i:02d}")
            for i in range(20)}
        plan = replace(original, deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
                       broker_account_id=DEPLOYMENT.broker_account_id, takeover_epoch=1,
                       target_basket={**dict.fromkeys(instruments, D("5.5")), "SEC-AAA": D(0)})
        plan = replace(plan, plan_id="sentinel-" + plan.fingerprint())
        raw = target_reprojection.project_target(
            plan, through_session=plan.effective_session, action_multipliers={},
            minimum_quantity_increment=D("0.000000001"))
        projection = fractional_sizing.resolve(state, plan, raw, references(plan, raw), MarketBuyPolicy(True),
            baseline={"through_event_seq": 0, "commands": [], "holdings": dict.fromkeys(instruments, "10")},
            retained_targets={})
        journal.save_plan(database, plan)
        target_reprojection.record_projection(database, projection)
        inner = DollarBroker()
        opened, _ = calendar.session_window(plan.effective_session)
        inner.now = opened + timedelta(minutes=15)
        database.execute("UPDATE sentinel_account_binding SET established_at=%s", (opened,))
        database.commit()
        for sid, instrument in instruments.items():
            inner.seed_position(instrument, "10")
            journal.save_command(database, Command(CommandIdentity(DEPLOYMENT, "prior", sid),
                instrument, Side.BUY, D(10), filled_quantity=D(10), filled_average_price=D(100),
                state=S.FILLED, broker_order_id=f"prior-{sid}"))
        admitted = []

        async def mutation_authority(latest):
            assert latest.clean
            admitted.append(latest.observation_id)

        native_resolve = inner.resolve_instrument

        async def resolve(*, security_id, symbol):
            assert security_id != "SEC-AAA", "a non-executable BUY requested asset evidence"
            return await native_resolve(security_id=security_id, symbol=symbol)

        monkeypatch.setattr(inner, "resolve_instrument", resolve)
        monkeypatch.setattr(feed_inputs, "metadata", lambda _conn: {})
        broker = wrapper(inner)
        with journal.writer_lock(database, recovery_only=True):
            mapped = await targets._instrument_map(database, broker, state, plan, await broker.observe(),
                target_basket=projection.target_basket, reductions_only=True)
            result = await executor._execute_session_locked(broker=broker, conn=database,
                deployment=DEPLOYMENT, plan=plan, instruments=mapped,
                today=plan.effective_session, actions=None, target_projection=projection,
                informational_current_book=True, mutation_authority=mutation_authority, reductions_only=True,
                min_increment=D("0.000000001"))
        assert len(admitted) == 1 and admitted[0]
        assert result.deferred == ("SEC-AAA",) and not result.refused, result.to_dict()
        assert [command.security_id for command in result.submitted] == list(instruments)
        assert len({command.client_key for command in result.submitted}) == 20
        assert all(command.side is Side.SELL and command.state is S.ACKNOWLEDGED
                   and command.quantity == D("4.5") for command in result.submitted)

    asyncio.run(run())


@pytest.mark.parametrize("fractionable", [False, True])
def test_sale_settlement_checks_the_original_share_target(database, fractionable):
    from sentinel.core.decision import DEFENSIVE_SECURITY_ID
    from sentinel.execution.commands import Command
    from sentinel.execution.contract import BrokerInstrument
    from sentinel.execution.identity import CommandIdentity

    class FillSales(DollarBroker):
        async def asset_rules(self, *, instrument):
            return BrokerAssetRules(instrument, self.now,
                self.fractionable or instrument.security_id == DEFENSIVE_SECURITY_ID)

        async def submit(self, **kwargs):
            outcome = await super().submit(**kwargs)
            if kwargs["side"] is Side.SELL:
                self.fill(kwargs["client_key"])
            return outcome

    async def run():
        schema.ensure_schema(database)
        binding.bind(database, deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
                     broker_account_id=DEPLOYMENT.broker_account_id)
        state, original = case(entries=0, sale=True)
        plan = replace(original, deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
                       broker_account_id=DEPLOYMENT.broker_account_id, takeover_epoch=1,
                       target_basket={"SEC-X": D(0), DEFENSIVE_SECURITY_ID: D(1)})
        plan = replace(plan, plan_id="sentinel-" + plan.fingerprint())
        raw = base(state, plan)
        sale = BrokerInstrument("SEC-X", "X", "sim-asset-SEC-X")
        sleeve = BrokerInstrument(DEFENSIVE_SECURITY_ID, "BIL", "sim-asset-" + DEFENSIVE_SECURITY_ID)
        projection = fractional_sizing.resolve(state, plan, raw, references(plan, raw), MarketBuyPolicy(True),
            baseline={"through_event_seq": 0, "commands": [], "holdings": {"SEC-X": "2.5"}},
            retained_targets={})
        journal.save_plan(database, plan)
        target_reprojection.record_projection(database, projection)
        journal.save_command(database, Command(CommandIdentity(DEPLOYMENT, "prior", sale.security_id),
            sale, Side.BUY, D("2.5"), filled_quantity=D("2.5"), filled_average_price=D(100),
            state=S.FILLED, broker_order_id="prior-buy"))
        inner = FillSales()
        opened, _ = calendar.session_window(plan.effective_session)
        inner.now = opened + timedelta(seconds=60)
        inner.fractionable = fractionable
        inner.seed_position(sale, "2.5")
        database.execute("UPDATE sentinel_account_binding SET established_at=%s", (opened,))
        database.commit()
        with journal.writer_lock(database, recovery_only=True):
            return await executor._execute_session_locked(broker=wrapper(inner), conn=database,
                deployment=DEPLOYMENT, plan=plan, instruments={sale.security_id: sale, sleeve.security_id: sleeve},
                today=plan.effective_session, actions=None, target_projection=projection,
                min_increment=D("0.000000001"))

    result = asyncio.run(run())
    if fractionable:
        assert [command.side for command in result.submitted] == [Side.SELL, Side.BUY]
        assert result.submitted[0].quantity == D("2.5")
    else:
        assert [command.side for command in result.submitted] == [Side.SELL]
        assert result.submitted[0].quantity == 2
        assert result.restricted_securities["SEC-X"].endswith("0.5")
