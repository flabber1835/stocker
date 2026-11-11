"""Whole-share PAPER market BUY transport, serial order admission and recovery."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import inspect
import textwrap
from types import SimpleNamespace

import pytest

from sentinel import binding
from sentinel.execution import executor, journal, market_buy_sizing, recovery, target_reprojection
from sentinel.execution.alpaca import RetryableCommandOutcome
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, OrderTerms, Side
from sentinel.execution.guarded import (
    ExecutionBrokerGuard, GuardedExecutionBroker, ManualExecutionGrant,
    OrderEvidenceNotReady, PreTransportAuthorityRefused,
)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.market_buy_policy import MarketBuyPolicy
from sentinel.execution.opening_prices import (
    OpeningPriceNotReady, QUOTE_SOURCE, RegularQuotes, SIP_QUOTE_SOURCE,
)
from sentinel.execution.reconcile import ReconciliationResult
from sentinel.execution.states import CommandState as S, RuntimeState
from sentinel.feed import calendar
from sentinel.paper.validation import _market_buy_candidate_or_refuse
from tests.sentinel.test_guarded_execution_broker import conn, pg  # noqa: F401
from tests.sentinel.test_market_buy_policy import MARKET_ENV
from tests.sentinel.test_market_day_sizing import _quotes
from tests.sentinel.test_opening_submit_freshness_boundary import ClockedBroker, instrument
from tests.v5.test_opening import base, case


DEPLOYMENT = DeploymentIdentity("market-execution", "sim", "SIM-ACCOUNT", 1)


@pytest.fixture(autouse=True)
def market_environment(monkeypatch):
    for key, value in MARKET_ENV.items():
        monkeypatch.setenv(key, value)


class MarketBroker(ClockedBroker):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.capabilities = replace(self.capabilities, regular_session_quote_prices=True,
            regular_session_open_prices=True, pre_submit_instrument_revalidation=True)
        self.ask = D(100)
        self.missing_quote = False
        self.quote_source = QUOTE_SOURCE

    async def opening_prices(self, *, session, instruments):
        if self.missing_quote:
            raise OpeningPriceNotReady("missing regular quote")
        sid, security = next(iter(instruments.items()))
        opened, _ = calendar.session_window(session)
        return RegularQuotes(
            session=session, opening_at=opened, observed_at=self.now,
            prices={sid: self.ask}, symbols={sid: security.symbol},
            broker_ids={sid: security.broker_id}, bids={sid: self.ask - D("0.01")},
            quoted_at={sid: self.now}, source=self.quote_source)


async def permit_read_or_mutation(*args):
    return None


async def permit_funding(**kwargs):
    return None


def wrapper(inner, *, before_mutation=permit_read_or_mutation, funding=permit_funding):
    return GuardedExecutionBroker(
        inner=inner, grant=ManualExecutionGrant(
            "SIM-ACCOUNT", "test-plan", inner.now.date(), True),
        guard=ExecutionBrokerGuard(permit_read_or_mutation, permit_read_or_mutation, before_mutation),
        issuer_admission_check=lambda **kwargs: SimpleNamespace(allowed=True),
        market_buy_funding=funding)


def set_clock(inner, seconds):
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened + timedelta(seconds=seconds)


def submit(broker, quantity=D(1)):
    return asyncio.run(broker.submit(
        client_key="market-key", instrument=instrument(), side=Side.BUY, quantity=quantity))


@pytest.mark.parametrize("seconds,accepted", [(59, False), (60, True), (599, True), (600, False)])
def test_market_buy_uses_original_strict_regular_session_window(seconds, accepted):
    inner = MarketBroker()
    set_clock(inner, seconds)
    broker = wrapper(inner)
    if accepted:
        assert submit(broker).state is S.ACKNOWLEDGED
        assert "submit:market-key" in inner.calls
    else:
        with pytest.raises(PreTransportAuthorityRefused, match="final next-open freshness"):
            submit(broker)
        assert "submit:market-key" not in inner.calls


def test_final_guard_rechecks_clock_after_fresh_authority():
    inner = MarketBroker()
    set_clock(inner, 599)

    async def cross_cutoff(*args):
        set_clock(inner, 600)

    with pytest.raises(PreTransportAuthorityRefused, match="final next-open freshness"):
        submit(wrapper(inner, before_mutation=cross_cutoff))
    assert "submit:market-key" not in inner.calls


@pytest.mark.parametrize("cash,buying_power", [("101", "105"), ("105", "101")])
def test_market_estimate_uses_the_smaller_native_cash_bound(cash, buying_power):
    inner = MarketBroker(cash=D(cash))
    inner.buying_power = D(buying_power)
    set_clock(inner, 60)
    with pytest.raises(OrderEvidenceNotReady, match="native cash or buying power"):
        submit(wrapper(inner))
    assert "submit:market-key" not in inner.calls


def test_market_missing_quote_and_fractional_quantity_are_proven_unsent():
    inner = MarketBroker()
    set_clock(inner, 60)
    broker = wrapper(inner)
    with pytest.raises(OrderEvidenceNotReady, match="whole-share quantity"):
        submit(broker, D("0.5"))
    inner.missing_quote = True
    with pytest.raises(OrderEvidenceNotReady, match="missing regular quote"):
        submit(broker)
    assert "submit:market-key" not in inner.calls


def test_market_guard_refuses_typed_quote_from_another_source():
    inner = MarketBroker()
    set_clock(inner, 60)
    inner.quote_source = SIP_QUOTE_SOURCE
    with pytest.raises(PreTransportAuthorityRefused, match="reviewed IEX source"):
        submit(wrapper(inner))
    assert "submit:market-key" not in inner.calls


class RateLimitedBroker(MarketBroker):
    async def submit(self, *, client_key, **kwargs):
        self.calls.append(f"submit:{client_key}")
        return RetryableCommandOutcome(S.UNKNOWN, retry_after_seconds=D(0))


def test_ambiguous_market_post_goes_to_unknown_without_inline_resubmit(conn):
    inner = RateLimitedBroker()
    set_clock(inner, 60)
    command = Command(CommandIdentity(DEPLOYMENT, "rate-limit-plan", "SEC-AAA", 0),
                      instrument(), Side.BUY, D(1))
    settled = asyncio.run(executor._persist_and_send(conn, wrapper(inner), command))
    assert settled.state is S.UNKNOWN
    assert inner.calls.count(f"submit:{command.client_key}") == 1
    assert f"find:{command.client_key}" not in inner.calls
    assert [row["to"] for row in journal.command_history(conn, command.client_key)] == [
        "PLANNED", "SEND_PENDING", "UNKNOWN"]


@pytest.fixture
def market_plan(conn):
    binding.bind(conn, deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
                 broker_account_id=DEPLOYMENT.broker_account_id)
    state, original = case(entries=2)
    plan = replace(original, deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
                   broker_account_id=DEPLOYMENT.broker_account_id, takeover_epoch=1)
    plan = replace(plan, plan_id=f"sentinel-{plan.fingerprint()}")
    projection = market_buy_sizing.resolve(state, plan, base(state, plan),
        _quotes(state, plan, ask="100"), MarketBuyPolicy(), retained_targets=None)
    journal.save_plan(conn, plan)
    target_reprojection.record_projection(conn, projection)
    return plan, projection


def market_instruments():
    return {sid: BrokerInstrument(sid, sid.removeprefix("SEC-"), f"sim-asset-{sid}")
            for sid in ("SEC-AAA", "SEC-BBB")}


async def execute_serial(conn, monkeypatch, market_plan):
    plan, projection = market_plan
    inner = MarketBroker()
    opened, _ = calendar.session_window(plan.effective_session)
    inner.now = opened + timedelta(seconds=60)

    async def reconcile(**kwargs):
        observation = await inner.observe()
        for command in journal.in_flight_commands(conn, DEPLOYMENT):
            revised = recovery.apply_observation(command, observation)
            if revised != command:
                journal.save_command(conn, revised, previous=command.state)
        return ReconciliationResult(runtime_state=RuntimeState.RUNNING, observation=observation,
                                    expected={}, observed={}, observation_id=1)

    monkeypatch.setattr(executor.R, "reconcile", reconcile)
    instruments = market_instruments()
    with journal.writer_lock(conn, recovery_only=True):
        async def tick():
            return await executor._execute_session_locked(
                broker=inner, conn=conn, deployment=DEPLOYMENT, plan=plan,
                instruments=instruments, today=plan.effective_session, actions=None,
                target_projection=projection, min_increment=D(1),
                buy_admission=lambda **kwargs: SimpleNamespace(allowed=True))

        first = await tick()
        assert [command.security_id for command in first.submitted] == ["SEC-AAA"], first.detail
        assert first.deferred == ("SEC-BBB",)
        key = first.submitted[0].client_key

        assert not (await tick()).submitted
        inner.fill(key, "1")
        assert not (await tick()).submitted
        assert journal.load_commands(conn, DEPLOYMENT, client_keys=(key,))[0].state is S.PARTIALLY_FILLED

        inner.fill(key)
        second = await tick()
        assert [command.security_id for command in second.submitted] == ["SEC-BBB"]
        assert second.submitted[0].order_terms == OrderTerms()
        assert inner.calls.count(f"submit:{key}") == 1


def test_market_executor_serializes_work_across_positive_partial_fill(conn, monkeypatch, market_plan):
    asyncio.run(execute_serial(conn, monkeypatch, market_plan))


def test_removing_the_one_market_buy_rule_is_detected(conn, monkeypatch, market_plan):
    source = inspect.getsource(executor._execute_session_locked)
    guard = "            if market and delta.is_increase:"
    assert source.count(guard) == 1
    local = {}
    exec(source.replace(guard, "            if False:"), vars(executor), local)
    monkeypatch.setattr(executor, "_execute_session_locked", local["_execute_session_locked"])
    with pytest.raises(AssertionError):
        asyncio.run(execute_serial(conn, monkeypatch, market_plan))


def test_final_market_candidate_matches_its_exact_plan_and_account_wide_inflight_set(
        conn, monkeypatch, market_plan):
    # Plan issuance and policy cutover have their own tests. Exercise the
    # final candidate checks with actual immutable plan/projection SQL rows.
    from sentinel import dual_plan_authority
    monkeypatch.setattr(dual_plan_authority, "require_current_buy_policy", lambda *args, **kwargs: None)
    plan, projection = market_plan
    inner = MarketBroker()
    observation = asyncio.run(inner.observe())
    pending = [Command(CommandIdentity(DEPLOYMENT, plan.plan_id, sid, 0), security,
        Side.BUY, projection.target_basket[sid])
        for sid, security in market_instruments().items()]
    with journal.writer_lock(conn, recovery_only=True):
        first, second = sorted(pending, key=lambda command: command.client_key)
        journal.save_command(conn, first)
        journal.save_command(conn, recovery.prepare_send(first), previous=S.PLANNED)

        def verify(estimate):
            _market_buy_candidate_or_refuse(
                conn, plan=plan, projection=projection, deployment=DEPLOYMENT,
                observation=observation, client_key=first.client_key, instrument=first.instrument,
                quantity=first.quantity, order_terms=OrderTerms(), estimate=D(estimate),
                session=plan.effective_session)

        verify("4990")
        with pytest.raises(OrderEvidenceNotReady, match="saved entry allocation"):
            verify("5001")
        journal.save_command(conn, second)
        journal.save_command(conn, recovery.prepare_send(second), previous=S.PLANNED)
        with pytest.raises(OrderEvidenceNotReady, match="only unresolved order"):
            verify("4990")


@pytest.mark.parametrize("guard,refusal", [
    ("if estimate > available:",
     lambda: test_market_estimate_uses_the_smaller_native_cash_bound("101", "105")),
    ("if quote.source != QUOTE_SOURCE:", test_market_guard_refuses_typed_quote_from_another_source),
    ("if not earliest <= now < latest:", test_final_guard_rechecks_clock_after_fresh_authority),
])
def test_removing_a_final_market_transport_guard_is_detected(monkeypatch, guard, refusal):
    source = textwrap.dedent(inspect.getsource(GuardedExecutionBroker._prepare_submit))
    assert source.count(guard) == 1
    import sentinel.execution.guarded as guarded
    local = {}
    exec(source.replace(guard, "if False:"), vars(guarded), local)
    monkeypatch.setattr(GuardedExecutionBroker, "_prepare_submit", local["_prepare_submit"])
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        refusal()
