"""Exercise the existing journal/reconciler/executor with native dollar orders."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import inspect
import textwrap
from types import SimpleNamespace

import pytest

from sentinel import binding, schema
from sentinel.execution import executor, fractional_progress, fractional_sizing, journal, recovery, target_reprojection
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
        "if estimate > available_purchase_cash(account):", "if False:"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_notional_and_headroom_fit_both_native_cash_bounds("999", "1000")


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


async def serial_flow(database):
    schema.ensure_schema(database)
    binding.bind(database, deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
                 broker_account_id=DEPLOYMENT.broker_account_id)
    state, original = case(entries=2)
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
    inner.now = opened + timedelta(seconds=60)
    database.execute("UPDATE sentinel_account_binding SET established_at=%s", (opened,))
    database.commit()
    broker = wrapper(inner)
    with journal.writer_lock(database, recovery_only=True):
        from sentinel.automation_runtime import _actionable_projection_deltas
        from sentinel import trial
        async def tick():
            return await executor._execute_session_locked(broker=broker, conn=database,
                deployment=DEPLOYMENT, plan=plan, instruments=market_instruments(),
                today=plan.effective_session, actions=lambda *args: D(1),
                target_projection=projection, min_increment=D("0.000000001"),
                buy_admission=lambda **kwargs: SimpleNamespace(allowed=True))
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


def test_real_reconciliation_keeps_partial_shares_and_serializes_two_dollar_buys(database):
    asyncio.run(serial_flow(database))


def test_serial_buy_guard_falsifier(database, monkeypatch):
    monkeypatch.setattr(executor, "_execute_session_locked", _compiled(
        executor._execute_session_locked, "if market and delta.is_increase:", "if False:"))
    with pytest.raises(AssertionError):
        asyncio.run(serial_flow(database))
