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


@pytest.mark.parametrize('funding_seconds,approval_delays,expected_approvals', [
    (31, [1], 1), (29, [2, 1], 2),
])
def test_reserved_purchase_renews_only_expired_rules_and_final_authority(
        monkeypatch, funding_seconds, approval_delays, expected_approvals):
    from sentinel.execution import submission_group
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity

    inner = DollarBroker(cash=D(1000))
    set_clock(inner, 60)
    instrument = market_instruments()['SEC-AAA']
    order = Command(CommandIdentity(DEPLOYMENT, 'group', instrument.security_id), instrument,
                    Side.BUY, None, notional=D(100))
    reads, approvals = [], []
    async def rules(*, instrument):
        reads.append(inner.now)
        return BrokerAssetRules(instrument, inner.now, True)
    async def funding(**_):
        inner.now += timedelta(seconds=funding_seconds)
    async def approval(*_):
        approvals.append(inner.now)
        inner.now += timedelta(seconds=approval_delays[len(approvals)-1])
    monkeypatch.setattr(inner, 'asset_rules', rules)
    broker = wrapper(inner, funding=funding, before_mutation=approval)
    with submission_group.independent_dispatch_scope((order,)):
        outcome = asyncio.run(broker.submit(client_key=order.client_key, instrument=instrument,
            side=Side.BUY, quantity=None, notional=order.notional))
    assert outcome.state is S.ACKNOWLEDGED and inner.dollars == {order.client_key: order.notional}
    assert len(reads) == 2 and len(approvals) == expected_approvals
    assert approvals[-1] >= reads[-1]


def test_expired_purchase_retains_same_key_and_an_independent_purchase_can_trade(database):
    from contextvars import ContextVar
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity

    schema.ensure_schema(database)
    inner = DollarBroker(cash=D(2000))
    set_clock(inner, 60)
    commands = [Command(CommandIdentity(DEPLOYMENT, 'group', sid), market_instruments()[sid],
                        Side.BUY, None, notional=D(100)) for sid in ('SEC-AAA', 'SEC-BBB')]
    journal.reserve_planned_commands(database, commands)
    database.commit()
    delayed, independent = commands
    current = ContextVar('current_purchase')
    approvals = []
    async def funding(*, client_key, **_):
        current.set(client_key)
    async def approve(*_):
        approvals.append(current.get())
        if current.get() == delayed.client_key:
            inner.now += timedelta(seconds=31)
    broker = wrapper(inner, funding=funding, before_mutation=approve)
    result = asyncio.run(executor._dispatch_independent(database, broker,
        [(order, True, None, False) for order in commands], reserved=True))
    assert isinstance(result[0], executor._ProvenUnsentPurchaseDeferral)
    assert result[1].state is S.ACKNOWLEDGED
    assert approvals.count(delayed.client_key) == 2
    assert inner.dollars == {independent.client_key: D(100)}
    stored = {row.client_key: row for row in journal.load_commands(database, DEPLOYMENT)}
    assert set(stored) == {order.client_key for order in commands}
    assert stored[delayed.client_key].state is S.PLANNED
    outcome, = asyncio.run(executor._dispatch_independent(database, wrapper(inner),
        [(stored[delayed.client_key], True, None, False)], reserved=True))
    assert outcome.state is S.ACKNOWLEDGED and outcome.client_key == delayed.client_key
    assert set(inner.dollars) == set(stored)


@pytest.mark.parametrize('withdraw,reason', [
    ('identity', 'another instrument'), ('future', 'future dated'),
    ('eligibility', 'not currently fractionable'), ('authority', 'withdrawn'), ('cutoff', 'final next-open freshness'),
    ('foreign-expiry', 'unrelated approval'), ('adapter-expiry', 'unrelated adapter'),
])
def test_reserved_purchase_renewal_cannot_override_current_authority(monkeypatch, withdraw, reason):
    from sentinel.execution import submission_group
    from sentinel.execution.commands import Command
    from sentinel.execution.contract import BrokerAssetRulesExpired
    from sentinel.execution.guarded import BrokerAuthorityRefused, PurchaseRulesExpired
    from sentinel.execution.identity import CommandIdentity

    inner = DollarBroker(cash=D(1000))
    set_clock(inner, 568 if withdraw == 'cutoff' else 60)
    instrument = market_instruments()['SEC-AAA']
    order = Command(CommandIdentity(DEPLOYMENT, 'group', instrument.security_id), instrument,
                    Side.BUY, None, notional=D(100))
    reads, approvals = [], []
    async def rules(*, instrument):
        reads.append(inner.now)
        renewed = len(reads) == 2
        if renewed and withdraw == 'adapter-expiry':
            raise BrokerAssetRulesExpired('unrelated adapter')
        return BrokerAssetRules(market_instruments()['SEC-BBB'] if renewed and withdraw == 'identity' else instrument,
            inner.now + timedelta(seconds=int(renewed and withdraw == 'future')),
            not (renewed and withdraw == 'eligibility'))
    async def approve(*_):
        approvals.append(inner.now)
        inner.now += timedelta(seconds=31 if len(approvals) == 1 else 1)
        if len(approvals) == 2 and withdraw == 'authority':
            raise BrokerAuthorityRefused('withdrawn')
        if len(approvals) == 2 and withdraw == 'foreign-expiry':
            raise BrokerAssetRulesExpired('unrelated approval')
    monkeypatch.setattr(inner, 'asset_rules', rules)
    broker = wrapper(inner, before_mutation=approve)
    with submission_group.independent_dispatch_scope((order,)):
        with pytest.raises(PreTransportAuthorityRefused, match=reason) as blocked:
            asyncio.run(broker.submit(client_key=order.client_key, instrument=instrument,
                side=Side.BUY, quantity=None, notional=order.notional))
    assert not isinstance(blocked.value, PurchaseRulesExpired)
    broker.consume_not_transported(blocked.value, order)
    assert not inner.dollars


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


def test_final_posting_limited_order_requires_exact_fresh_ceiling(database, monkeypatch):
    from sentinel import dual_plan_authority
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity
    from sentinel.paper.model import PaperActivationRefused
    from sentinel.paper.validation import _market_buy_candidate_or_refuse

    schema.ensure_schema(database)
    binding.bind(database, deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
                 broker_account_id=DEPLOYMENT.broker_account_id)
    state, original = case()
    plan = replace(original, deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
                   broker_account_id=DEPLOYMENT.broker_account_id, takeover_epoch=DEPLOYMENT.takeover_epoch)
    plan = replace(plan, plan_id="sentinel-" + plan.fingerprint())
    raw = base(state, plan)
    projection = fractional_sizing.resolve(state, plan, raw, references(plan, raw), MarketBuyPolicy(True),
        baseline={"through_event_seq": 0, "commands": [], "holdings": {}}, retained_targets={})
    journal.save_plan(database, plan)
    target_reprojection.record_projection(database, projection)
    monkeypatch.setattr(dual_plan_authority, "require_current_buy_policy", lambda *_args, **_kwargs: None)
    sid = "SEC-AAA"
    candidate = Command(CommandIdentity(DEPLOYMENT, plan.plan_id, sid), market_instruments()[sid],
                        Side.BUY, quantity=None, notional=D("698.99"))
    observation = asyncio.run(DollarBroker().observe())
    with journal.writer_lock(database, recovery_only=True):
        journal.save_command(database, candidate)
        journal.save_command(database, recovery.prepare_send(candidate), previous=S.PLANNED)
        def verify(ceiling):
            _market_buy_candidate_or_refuse(database, plan=plan, projection=projection, deployment=DEPLOYMENT,
                observation=observation, client_key=candidate.client_key, instrument=candidate.instrument,
                quantity=None, notional=candidate.notional, order_terms=candidate.order_terms,
                estimate=D("699.99"), session=plan.effective_session, cash_ceiling=ceiling)
        verify(D("699.99"))
        for changed in (None, D("699.98"), D("700.00")):
            with pytest.raises(PaperActivationRefused, match="immutable remaining allocation"):
                verify(changed)


@pytest.mark.parametrize("change,expected", [
    ("", "CASH_POSTING_WAIT"), ("cutoff", "ACTIONABLE_DELTA_REMAINS"),
    ("other_delta", "ACTIONABLE_DELTA_REMAINS"), ("insufficient_credit", "ACTIONABLE_DELTA_REMAINS"),
    ("forged_ceiling", "ACTIONABLE_DELTA_REMAINS")])
def test_automation_classifies_only_the_current_cash_funded_wait(monkeypatch, change, expected):
    from types import SimpleNamespace
    from sentinel import automation_runtime, paper
    from sentinel.execution.states import RuntimeState
    from tests.sentinel import test_automation_runtime as t

    cfg = t.config()
    plan = replace(t.plan(), broker="alpaca")
    plan = replace(plan, plan_id="sentinel-" + plan.fingerprint())
    ctx = t.context(cfg, plan=plan)
    ctx = ctx.model_copy(update={"cycle": ctx.cycle.model_copy(update={"broker": plan.broker})})
    sid = t.INSTRUMENT.security_id
    runtime = t.production(cfg)
    runtime._dual_run_enabled = True
    broker = DollarBroker()
    t.install_runtime_seams(monkeypatch, runtime, t.FakeConnection(), ctx, broker)
    monkeypatch.setattr(automation_runtime, "require_observation_integrity", lambda _: None)
    monkeypatch.setattr(automation_runtime.schema, "require_runtime_schema", lambda _: None)
    monkeypatch.setattr(journal, "latest_plan", lambda _: plan)
    monkeypatch.setattr(journal, "in_flight_commands", lambda *_args: ())
    monkeypatch.setattr(runtime, "_actionable_current_plan_deltas", lambda *_args, **_kwargs:
        (SimpleNamespace(security_id="another" if change == "other_delta" else sid, is_increase=True),))
    deadline = min(ctx.cycle.execution_close_at, ctx.cycle.execution_open_at + timedelta(minutes=10),
                   ctx.cycle.execute_at + timedelta(seconds=cfg.maximum_execution_lateness_seconds))
    monkeypatch.setattr(automation_runtime, "_now_utc", lambda: deadline if change == "cutoff" else ctx.cycle.execute_at)
    async def pending(**kwargs):
        rec = t.reconciliation(await broker.observe())
        funds = fractional_progress.PostingFunds(D(1), D(1), D("0.01") if change == "insufficient_credit"
                                                 else D(309), D("0.01")).to_dict()
        if change == "forged_ceiling":
            funds["cash_ceiling"] = "2"
        session = executor.SessionResult(runtime_state=RuntimeState.RUNNING, reconciliation=rec,
            deferred=(sid,), posting_deferred=(sid,), posting_funds=funds)
        return paper.ExecutionResult(plan=plan, preflight=rec, session=session)
    monkeypatch.setattr(paper, "execute_automated_paper_plan", pending)
    result = asyncio.run(runtime.execute(ctx))
    assert result.disposition is t.ExecuteDisposition.RECONCILE
    assert result.failure_code == expected
    assert result.diagnostic.get("original_execution_deadline_at") == (
        deadline.isoformat() if expected == "CASH_POSTING_WAIT" else None)


def test_ordinary_shortage_mislabeled_as_native_posting_falsifier(monkeypatch):
    monkeypatch.setattr(fractional_progress.PostingFunds, "credit_can_fund_order", lambda self: True)
    with pytest.raises(AssertionError, match="CASH_POSTING_WAIT"):
        test_automation_classifies_only_the_current_cash_funded_wait(
            monkeypatch, "insufficient_credit", "ACTIONABLE_DELTA_REMAINS")


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


def test_sizing_groups_native_asset_reads_and_submit_uses_current_rules(monkeypatch):
    from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
    from sentinel.execution.guarded import BrokerOperation, ExecutionBrokerGuard, ManualExecutionGrant
    from tests.sentinel.test_limit_day_transport import broker_for

    opened, _ = calendar.session_window(date(2026, 8, 18))
    names = list("ABCDE")
    routes = {"/v2/assets/" + symbol: dict(id="asset-" + symbol, symbol=symbol, status="active",
              tradable=True, fractionable=True) for symbol in names}
    # A later call by stable ID sees newly withdrawn fractional eligibility.
    routes.update({"/v2/assets/asset-" + s: {**routes["/v2/assets/" + s], "fractionable": False} for s in names})
    inner, http = broker_for(AssetIdAlpacaExecutionBroker, routes=routes)
    monkeypatch.setattr(inner, "_now", lambda: opened)
    checks = []
    async def check(grant, operation, result=None):
        checks.append(operation)
    broker = GuardedExecutionBroker(inner=inner, grant=ManualExecutionGrant("TEST", "plan", opened.date(), True),
        guard=ExecutionBrokerGuard(check, check, check))
    instruments = asyncio.run(broker.resolve_sizing_instruments({"SEC-" + s: s for s in names}))
    for s in names:
        instrument = instruments["SEC-" + s]
        assert instrument.broker_id == "asset-" + s
        assert asyncio.run(broker.sizing_asset_rules(instrument)).fractionable
    assert [call[1] for call in http.calls] == ["/v2/assets/" + s for s in names]
    assert checks == [BrokerOperation.RESOLVE_INSTRUMENT] * 4
    assert not asyncio.run(broker.asset_rules(instrument=instruments["SEC-A"])).fractionable
    assert http.calls[-1][1] == "/v2/assets/asset-A"


def test_unavailable_fractional_purchase_needs_only_its_exact_asset_rules(monkeypatch):
    from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
    from sentinel.execution.guarded import PurchaseInstrumentUnavailable
    from tests.sentinel.test_issue_183_alpaca_hardening import INSTRUMENT
    from tests.sentinel.test_limit_day_transport import broker_for
    opened, closed = calendar.session_window(date(2026, 8, 18))
    now = opened + timedelta(minutes=2)
    asset_route = f"/v2/assets/{INSTRUMENT.broker_id}"
    inner, http = broker_for(AssetIdAlpacaExecutionBroker, payload={}, routes={
        "/v2/clock": {"timestamp": now.isoformat(), "is_open": True,
                      "next_open": (opened + timedelta(days=1)).isoformat(), "next_close": closed.isoformat()},
        asset_route: {"id": INSTRUMENT.broker_id, "symbol": INSTRUMENT.symbol,
                      "status": "inactive", "tradable": False}})
    monkeypatch.setattr(inner, "now", now, raising=False)
    monkeypatch.setattr(inner, "_now", lambda: now)
    with pytest.raises(PurchaseInstrumentUnavailable):
        asyncio.run(wrapper(inner).submit(client_key="key", instrument=INSTRUMENT, side=Side.BUY,
                                          quantity=None, notional=D(10)))
    assert [item[1] for item in http.calls] == ["/v2/clock", asset_route]


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


def test_two_proven_unsent_attempts_keep_independent_single_use_proofs():
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity
    inner = DollarBroker(cash=D(1))
    set_clock(inner, 60)
    broker = wrapper(inner)
    orders = [Command(CommandIdentity(DEPLOYMENT, "group", sid), market_instruments()[sid],
                      Side.BUY, None, notional=D(100)) for sid in ("SEC-AAA", "SEC-BBB")]

    async def run():
        errors = await asyncio.gather(*(broker.submit(client_key=c.client_key, instrument=c.instrument,
            side=c.side, quantity=c.quantity, notional=c.notional) for c in orders), return_exceptions=True)
        for c, error in zip(reversed(orders), reversed(errors)):
            assert isinstance(error, OrderEvidenceNotReady)
            broker.consume_not_transported(error, c)
            with pytest.raises(ValueError, match="unused"):
                broker.consume_not_transported(error, c)
    asyncio.run(run())
    assert not inner.dollars


@pytest.mark.parametrize('expires', ['cutoff', 'asset'])
def test_http_connection_setup_cannot_carry_a_paper_buy_past_cutoff(monkeypatch, expires):
    import httpcore
    import httpx
    from httpcore._backends.mock import AsyncMockBackend, AsyncMockStream
    from types import SimpleNamespace
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity
    from tests.sentinel.test_issue_183_alpaca_hardening import INSTRUMENT, adapter

    opened, _ = calendar.session_window(date(2026, 8, 18))
    cutoff = opened + timedelta(minutes=10)
    clock = [cutoff - timedelta(seconds=1) if expires == 'cutoff' else opened + timedelta(minutes=2)]
    rules = (BrokerAssetRules(INSTRUMENT, clock[0] - timedelta(seconds=29), True)
             if expires == 'asset' else None)
    connected = clock[0] + timedelta(seconds=1 if expires == 'cutoff' else 2)
    writes = []

    class Wire(AsyncMockStream):
        async def write(self, buffer, timeout=None):
            writes.append(buffer)

    class DelayedConnect(AsyncMockBackend):
        async def connect_tcp(self, *args, **kwargs):
            clock[0] = connected
            return Wire([])

    raw, _ = adapter()
    transport = httpx.AsyncHTTPTransport()
    transport._pool = httpcore.AsyncConnectionPool(network_backend=DelayedConnect([]))
    raw._http_provider = lambda: SimpleNamespace(AsyncClient=lambda **opts: httpx.AsyncClient(
        transport=transport, trust_env=False, **opts))
    raw.now = clock[0]
    raw._clock_provider = lambda: clock[0]
    broker = wrapper(raw)

    async def before_submit(**_kwargs):
        return None, (opened + timedelta(minutes=1), cutoff), rules
    monkeypatch.setattr(broker, "_prepare_submit", before_submit)
    order = Command(CommandIdentity(DEPLOYMENT, "group", INSTRUMENT.security_id),
                    INSTRUMENT, Side.BUY, D(1))
    reason = 'opening window' if expires == 'cutoff' else 'asset trading rules are stale'
    with pytest.raises(OrderEvidenceNotReady, match=reason) as stopped:
        asyncio.run(broker.submit(client_key=order.client_key, instrument=INSTRUMENT,
                                  side=Side.BUY, quantity=D(1)))
    assert not writes and clock[0] == connected
    broker.consume_not_transported(stopped.value, order)


@pytest.mark.parametrize('expires', ['cutoff', 'asset'])
def test_http_header_deadline_guard_falsifier(monkeypatch, expires):
    from sentinel.execution import guarded
    monkeypatch.setattr(guarded, "recheck_paper_before_headers", lambda *_args, **_kwargs: None)
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_http_connection_setup_cannot_carry_a_paper_buy_past_cutoff(monkeypatch, expires)


def test_unknown_stops_a_sibling_in_tls_and_keeps_already_sent_receipt(database, monkeypatch):
    import httpcore
    import httpx
    import json
    from httpcore._backends.mock import AsyncMockBackend, AsyncMockStream
    from types import SimpleNamespace
    from sentinel.execution.commands import Command
    from sentinel.execution.contract import BrokerInstrument
    from sentinel.execution.identity import CommandIdentity
    from tests.sentinel.test_issue_183_alpaca_hardening import adapter, full_order

    schema.ensure_schema(database)
    opened, closed = calendar.session_window(date(2026, 8, 18))
    raw, _ = adapter()
    raw.now = opened + timedelta(minutes=1)
    raw._clock_provider = lambda: raw.now
    broker = wrapper(raw)
    commands = [Command(CommandIdentity(DEPLOYMENT, "group", "SEC-" + symbol),
        BrokerInstrument("SEC-" + symbol, symbol, "asset-" + symbol.lower()), Side.SELL, D(2))
        for symbol in ("DELAYED", "AMBIGUOUS", "ACCEPTED")]
    started = asyncio.Event()
    ambiguous_client_closing = asyncio.Event()
    delayed_client_closed = asyncio.Event()
    writes = [[], [], []]
    count = 0

    def client(**opts):
        nonlocal count
        index = count
        count += 1
        command = commands[index]
        body = json.dumps(full_order(client_order_id=command.client_key, symbol=command.instrument.symbol,
            asset_id=command.instrument.broker_id, side="sell")).encode()
        status = b"503 Service Unavailable" if index == 1 else b"201 Created"
        response = b"HTTP/1.1 " + status + b"\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body

        class Wire(AsyncMockStream):
            async def write(self, buffer, timeout=None):
                writes[index].append(buffer)
                if index == 2 and buffer:
                    started.set()

            async def read(self, max_bytes, timeout=None):
                if index == 1:
                    await started.wait()
                if index == 2:
                    await ambiguous_client_closing.wait()
                return await super().read(max_bytes, timeout)

        class Backend(AsyncMockBackend):
            async def connect_tcp(self, *args, **kwargs):
                if index == 0:
                    await ambiguous_client_closing.wait()
                return Wire([response])

        class Client(httpx.AsyncClient):
            async def __aexit__(self, *args):
                if index == 1:
                    ambiguous_client_closing.set()
                    await delayed_client_closed.wait()
                if index == 0:
                    delayed_client_closed.set()
                return await super().__aexit__(*args)
        transport = httpx.AsyncHTTPTransport()
        transport._pool = httpcore.AsyncConnectionPool(network_backend=Backend([]))
        return Client(transport=transport, trust_env=False, **opts)

    raw._http_provider = lambda: SimpleNamespace(AsyncClient=client)
    async def prepared(**_kwargs):
        return None, (opened, closed), None
    monkeypatch.setattr(broker, "_prepare_submit", prepared)
    async def run():
        async with asyncio.timeout(8):
            return await executor._dispatch_independent(database, broker,
                [(c, False, None, False) for c in commands], reserved=False)
    outcomes = asyncio.run(run())
    assert not writes[0] and writes[1] and writes[2], "late sibling crossed its write boundary"
    assert [o.state for o in outcomes] == [S.PLANNED, S.UNKNOWN, S.ACKNOWLEDGED]
    durable = {c.client_key: c for c in journal.load_commands(database, DEPLOYMENT)}
    assert [durable[c.client_key].state for c in commands] == [S.PLANNED, S.UNKNOWN, S.ACKNOWLEDGED]


def test_unknown_header_stop_falsifier(database, monkeypatch):
    from sentinel.execution import guarded
    monkeypatch.setattr(guarded, "recheck_paper_before_headers", lambda *_args, **_kwargs: None)
    with pytest.raises(AssertionError, match="late sibling crossed"):
        test_unknown_stops_a_sibling_in_tls_and_keeps_already_sent_receipt(database, monkeypatch)


def test_unqualified_http_version_refuses_before_any_order_io(monkeypatch):
    import httpcore
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity
    from tests.sentinel.test_issue_183_alpaca_hardening import INSTRUMENT, adapter
    raw, http = adapter()
    raw.now = calendar.session_window(date(2026, 8, 18))[0] + timedelta(minutes=1)
    monkeypatch.setattr(httpcore, "__version__", "unqualified")
    broker = wrapper(raw)
    order = Command(CommandIdentity(DEPLOYMENT, "group", INSTRUMENT.security_id),
                    INSTRUMENT, Side.BUY, D(1))
    with pytest.raises(PreTransportAuthorityRefused, match="versions") as stopped:
        asyncio.run(broker.submit(client_key=order.client_key, instrument=INSTRUMENT, side=Side.BUY, quantity=D(1)))
    broker.consume_not_transported(stopped.value, order)
    assert not http.calls


def test_cancelling_dispatch_drains_checkpointed_requests_and_starts_no_more(monkeypatch):
    from sentinel.execution.commands import Command
    from sentinel.execution.contract import BrokerInstrument, CommandOutcome
    from sentinel.execution.identity import CommandIdentity
    states = {}
    started = asyncio.Event()
    release = asyncio.Event()
    class Delayed:
        async def submit(self, *, client_key, **_kwargs):
            assert states[client_key] is S.SEND_PENDING
            if len(states) == 4:
                started.set()
            await release.wait()
            return CommandOutcome(S.ACKNOWLEDGED, broker_order_id="native-" + client_key)
    def save(_conn, command, *, previous=None):
        assert states.get(command.client_key) is previous
        states[command.client_key] = command.state
    monkeypatch.setattr(journal, "save_command", save)
    commands = [Command(CommandIdentity(DEPLOYMENT, "group", f"S{i}"),
        BrokerInstrument(f"S{i}", f"S{i}", f"asset{i}"), Side.SELL, D(1)) for i in range(6)]

    async def run():
        dispatch = asyncio.create_task(executor._dispatch_independent(None, Delayed(),
            [(c, False, None, False) for c in commands], reserved=False))
        async with asyncio.timeout(5):
            await started.wait()
            dispatch.cancel()
            await asyncio.sleep(0)
            assert not dispatch.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await dispatch
    asyncio.run(run())
    assert states == {c.client_key: S.ACKNOWLEDGED for c in commands[:4]}


def test_failed_receipt_commit_stops_other_workers_before_coordinator_resumes(monkeypatch):
    from sentinel.execution import submission_group
    from sentinel.execution.commands import Command
    from sentinel.execution.contract import CommandOutcome
    from sentinel.execution.identity import CommandIdentity
    commands = [Command(CommandIdentity(DEPLOYMENT, "group", sid), market_instruments()[sid], Side.SELL, D(1))
                for sid in ("SEC-AAA", "SEC-BBB")]
    first, second = commands
    ready = asyncio.Event()
    failed_commit = asyncio.Event()
    saw_stop = []

    def save(_conn, command, **_kwargs):
        if command.client_key == first.client_key and command.state is S.ACKNOWLEDGED:
            failed_commit.set()
            raise RuntimeError("simulated receipt write failure")
    monkeypatch.setattr(journal, "save_command", save)

    class Broker:
        async def submit(self, *, client_key, **_kwargs):
            if client_key == first.client_key:
                await ready.wait()
            else:
                ready.set()
                await failed_commit.wait()
                saw_stop.append(submission_group.stopped(second.client_key))
            return CommandOutcome(S.ACKNOWLEDGED, broker_order_id="native-" + client_key)
    async def run():
        async with asyncio.timeout(5):
            with pytest.raises(RuntimeError, match="receipt write failure"):
                await executor._dispatch_independent(None, Broker(),
                    [(c, False, None, False) for c in commands], reserved=False)
    asyncio.run(run())
    assert saw_stop == [True]


def test_delayed_ack_cannot_regress_a_recovered_fill(database):
    from sentinel.execution.commands import Command
    from sentinel.execution.identity import CommandIdentity
    schema.ensure_schema(database)
    sid = "SEC-AAA"
    planned = Command(CommandIdentity(DEPLOYMENT, "group", sid), market_instruments()[sid], Side.SELL, D(2))
    pending = recovery.prepare_send(planned)
    ack = pending.transition(S.ACKNOWLEDGED, broker_order_id="native-1")
    filled = ack.transition(S.FILLED, filled_quantity=D(2), filled_average_price=D(100))
    for previous, current in ((None, planned), (S.PLANNED, pending), (S.SEND_PENDING, ack),
                              (S.ACKNOWLEDGED, filled)):
        journal.save_command(database, current, previous=previous)
    with pytest.raises(ValueError, match="newer order evidence"):
        journal.save_command(database, ack, previous=S.SEND_PENDING)
    database.rollback()
    actual, = journal.load_commands(database, DEPLOYMENT)
    assert actual.state is S.FILLED and actual.filled_quantity == D(2)


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
            started = set()
            all_posted = asyncio.Event()
            reservations = []

            async def submit(**kwargs):
                result = await native_submit(**kwargs)
                if continuation == "reserved":
                    started.add(kwargs["client_key"])
                    if len(started) == 3:
                        all_posted.set()
                    async with asyncio.timeout(5):
                        await all_posted.wait()
                elif continuation not in {"working", "unknown", "rejected"}:
                    inner.fill(kwargs["client_key"])
                if continuation == "expired":
                    inner.now = opened + timedelta(minutes=10)
                if continuation == "new_reconciliation_required":
                    inner.schedule_observe(FaultKind.PARTIAL_OBSERVATION)
                return result

            async def fresh_cash(latest):
                assert not journal.in_flight_commands(database, DEPLOYMENT)
                assert not any(order.is_working for order in latest.observation.orders)
                assert latest.clean
                checked_books.append(latest.observation_id)
                if continuation == "reserved":
                    return fractional_progress.PostingFunds(D(11000), D(11000), D(0), D(0))
                if continuation == "pending_posting":
                    # $0.01 is reserved on the first pass. The pending credit
                    # becomes available only to a subsequent reconciled tick.
                    if len(checked_books) == 1:
                        return fractional_progress.PostingFunds(D(700), D(700), D(309), D("0.01"))
                    if len(checked_books) == 2:
                        return fractional_progress.PostingFunds(D("1.01"), D("1.01"), D(309), D("0.01"))
                if continuation == "cash" and len(checked_books) == 2:
                    raise RuntimeError("new account cash is unavailable")

            if continuation in {"unknown", "rejected"}:
                inner.schedule_submit(FaultKind.ACCEPT_THEN_TIMEOUT if continuation == "unknown"
                                      else FaultKind.REJECT)
            monkeypatch.setattr(inner, "submit", submit)
            def reserve(commands, latest, funds):
                assert latest.clean and not started and not reservations
                assert sum(c.notional + D(1) for c in commands) <= funds.cash_ceiling
                rows = journal.load_commands(database, DEPLOYMENT, client_keys=tuple(c.client_key for c in commands))
                assert len(rows) == len(commands) and all(c.state is S.PLANNED for c in rows)
                reservations.extend(c.client_key for c in commands)

            async def invoke():
                return await executor._execute_session_locked(
                    broker=broker, conn=database, deployment=DEPLOYMENT,
                    plan=plan, instruments=instruments, today=plan.effective_session,
                    actions=lambda *args: D(1), target_projection=projection,
                    min_increment=D("0.000000001"), buy_admission=admission.check_buy,
                    informational_current_book=True,
                    increase_reconciliation_authority=fresh_cash,
                    reserve_market_buys=reserve if continuation == "reserved" else None,
                    market_buy_window_open=(None if continuation == "handoff"
                                            else lambda: inner.now < opened + timedelta(minutes=10)))

            current = await invoke()
            if continuation == "reserved":
                assert len(checked_books) == 1 and len(reservations) == len(started) == 3
                assert reservations == [c.client_key for c in current.submitted]
                assert all(c.state is S.ACKNOWLEDGED and c.filled_quantity == 0 for c in current.submitted)
                assert [c.notional for c in current.submitted] == [D(4999), D(4999), D(999)]
            elif continuation == "pending_posting":
                assert len(current.submitted) == 1, "expected only the funded purchase"
                first, = current.submitted
                assert first.notional == D("698.99") and first.security_id == "SEC-AAA"
                assert len(checked_books) == 2
                assert current.posting_deferred == ("SEC-AAA", "SEC-BBB", "SEC-CCC")
                assert current.deferred == current.posting_deferred
                assert not ExecutionResult(plan, rec, current).needs_attention
                resumed = await invoke()
                topup = resumed.submitted[0]
                assert topup.security_id == first.security_id
                assert topup.identity.revision == first.identity.revision + 1
                assert topup.notional + first.notional + D(2) == D(5000)
                assert inner.calls.count("submit:" + first.client_key) == 1
                assert not resumed.deferred
            elif continuation == "immediate":
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
                if continuation == "expired":
                    assert len(checked_books) == 1 and "outside the buy window" in current.detail
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


def test_reserved_purchases_overlap_before_first_receipt_and_share_one_cash_ceiling(database, monkeypatch):
    asyncio.run(serial_flow(database, monkeypatch, continuation="reserved"))


@pytest.mark.parametrize("outcome", ["immediate", "handoff", "working", "cash", "expired", "pending_posting",
                                   "new_reconciliation_required", "unknown", "rejected"])
def test_guarded_market_buy_continuation_uses_fresh_settlement(database, monkeypatch, outcome):
    asyncio.run(serial_flow(database, monkeypatch, continuation=outcome))


def test_unposted_debit_funding_limit_falsifier(database, monkeypatch):
    monkeypatch.setattr(fractional_progress, "funded_notional", lambda requested, ceiling: requested)
    with pytest.raises(AssertionError, match="expected only the funded purchase"):
        asyncio.run(serial_flow(database, monkeypatch, continuation="pending_posting"))


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
        native_submit = inner.submit
        active = peak = 0
        first_four = asyncio.Event()

        async def delayed_submit(**kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 4:
                first_four.set()
            try:
                async with asyncio.timeout(5):
                    await first_four.wait()
                return await native_submit(**kwargs)
            finally:
                active -= 1

        monkeypatch.setattr(inner, "submit", delayed_submit)

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
        assert peak == 4 and active == 0
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
