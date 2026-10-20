"""Only positively observed, already funded protected cohorts may continue."""
from dataclasses import replace
import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import inspect
from types import SimpleNamespace

import pytest

from sentinel.execution import protected_funding as funding, protected_limits
from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerAccountSnapshot, BrokerInstrument, BrokerObservation,
    BrokerOrder, OrderTerms, Side)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.reconcile import ReconciliationResult
from sentinel.execution.states import CommandState as S, RuntimeState


NOW = datetime(2026, 10, 20, 13, 32, tzinfo=timezone.utc)
OWNER = DeploymentIdentity("cohort", "alpaca", "private-paper", 1)
TERMS = OrderTerms(order_type="limit", limit_price=D(100))
PAPER = "https://paper-api.alpaca.markets"


@pytest.fixture
def cohort(monkeypatch):
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", protected_limits.PROTECTED_MODE)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", "100")
    plan = ExecutionPlan("p", date(2026, 10, 19), NOW.date(), D(1),
        {"SEC-A": D(2), "SEC-B": D(1)}, deployment_id=OWNER.deployment_id,
        broker=OWNER.broker, broker_account_id=OWNER.broker_account_id,
        takeover_epoch=1, account_cash=D(1000), account_nav=D(1000))
    projection = SimpleNamespace(target_basket=plan.target_basket, fingerprint=lambda: "b" * 64)
    basis = funding.PlanCashFundingBasis(deployment=funding._deployment(OWNER), plan_id="p",
        plan_fingerprint=plan.fingerprint(), projection_fingerprint=projection.fingerprint(),
        policy_sha256=protected_limits.ProtectedLimitPolicy(100).fingerprint(),
        effective_session=NOW.date(), paper_base_url=PAPER, observed_at=NOW-timedelta(minutes=1),
        observation_id=1, observation_sha256="a" * 64, cash="1000", buying_power="1000",
        broker_composition_sha256="c" * 64, plan_cash_ceiling="1000")
    instrument = BrokerInstrument("SEC-A", "AAA", "native-a")
    command = Command(CommandIdentity(OWNER, "p", instrument.security_id), instrument,
        Side.BUY, D(2), state=S.ACKNOWLEDGED, broker_order_id="order-a", order_terms=TERMS)
    planned = Command(CommandIdentity(OWNER, "p", "SEC-B"),
        BrokerInstrument("SEC-B", "BBB", "native-b"), Side.BUY, D(1), order_terms=TERMS)
    order = BrokerOrder("order-a", command.client_key, instrument, Side.BUY,
        S.ACKNOWLEDGED, D(2), order_terms=TERMS)
    account = BrokerAccountSnapshot(BrokerAccountIdentity("alpaca", "private-paper"),
        D(1000), D(1000), buying_power=D(800), multiplier=D(1), status="ACTIVE")
    value = SimpleNamespace(plan=plan, projection=projection, basis=basis,
        commands=[command, planned], order=order, account=account, now=NOW)
    monkeypatch.setattr(funding, "_require_writer", lambda _conn: None)
    monkeypatch.setattr(funding, "load_basis", lambda *_args, **_kwargs: value.basis)
    monkeypatch.setattr(funding.journal, "latest_plan", lambda _conn: value.plan)
    monkeypatch.setattr(funding.journal, "load_commands", lambda *_args, **_kwargs: value.commands)
    monkeypatch.setattr(funding.target_reprojection, "assert_projection", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(protected_limits, "order_terms_for", lambda *_args: TERMS)
    monkeypatch.setattr(funding, "_plan_cash_composition", lambda _broker: "c" * 64)
    return value


def prove(cohort, *, implementation=None, observation=None, **changes):
    observation = observation or BrokerObservation(
        NOW, orders=(cohort.order,), account_identity=cohort.account.identity)
    rec = ReconciliationResult(RuntimeState.RUNNING, observation=observation, observation_id=2)
    kwargs = dict(plan=cohort.plan, projection=cohort.projection, deployment=OWNER,
        reconciliation=rec, account=cohort.account, activity_state=None,
        broker=object(), paper_base_url=PAPER, evaluated_at=cohort.now)
    kwargs.update(changes)
    return (implementation or funding.prove_cohort_continuation)(object(), **kwargs)


def test_owned_working_day_buy_can_continue_same_fixed_cohort(cohort):
    before = cohort.basis.model_dump()
    evidence = prove(cohort)
    assert evidence.reserved_cash == D(200)
    assert evidence.commands[0]["client_key"] == cohort.commands[0].client_key
    assert evidence.commands[0]["remaining_quantity"] == "2"
    assert evidence.observation_id == 2 and evidence.observed_at == NOW
    assert cohort.basis.model_dump() == before


@pytest.mark.parametrize("state", [S.UNKNOWN, S.SEND_PENDING, S.CANCEL_PENDING])
def test_uncertain_commands_never_earn_continuation(cohort, state):
    cohort.commands[0] = replace(cohort.commands[0], state=state)
    with pytest.raises(funding.ProtectedFundingRefused, match="uncertain"):
        prove(cohort)


@pytest.mark.parametrize("damage", ["foreign", "native-id", "quantity", "terms", "replacement",
    "missing", "filled-counter", "sell", "other-plan", "basis", "composition", "endpoint",
    "planned-quantity", "margin", "deposit", "blocked", "equity"])
def test_changed_or_missing_cohort_evidence_refuses(cohort, damage, monkeypatch):
    if damage == "foreign":
        cohort.order = replace(cohort.order, client_key="foreign")
    elif damage == "native-id":
        cohort.order = replace(cohort.order, broker_order_id="other")
    elif damage == "quantity":
        cohort.order = replace(cohort.order, quantity=D(3))
    elif damage == "terms":
        cohort.order = replace(cohort.order, order_terms=replace(TERMS, limit_price=D(101)))
    elif damage == "replacement":
        cohort.order = replace(cohort.order, external_replacement=True)
    elif damage == "missing":
        observation = BrokerObservation(NOW, account_identity=cohort.account.identity)
        with pytest.raises(funding.ProtectedFundingRefused, match="positive"):
            prove(cohort, observation=observation)
        return
    elif damage == "filled-counter":
        cohort.order = replace(cohort.order, filled_quantity=D(1), filled_average_price=D(100))
    elif damage == "sell":
        cohort.commands[0] = replace(cohort.commands[0], side=Side.SELL, order_terms=OrderTerms())
    elif damage == "other-plan":
        cohort.commands[0] = replace(cohort.commands[0],
            identity=replace(cohort.commands[0].identity, plan_id="another"))
    elif damage == "basis":
        cohort.basis = cohort.basis.model_copy(update={"policy_sha256": "d" * 64})
    elif damage == "composition":
        monkeypatch.setattr(funding, "_plan_cash_composition", lambda _broker: "d" * 64)
    elif damage == "endpoint":
        cohort.basis = cohort.basis.model_copy(update={"paper_base_url": "https://paper-other.invalid"})
    elif damage == "planned-quantity":
        cohort.commands[1] = replace(cohort.commands[1], quantity=D(2))
    elif damage == "margin":
        cohort.account = replace(cohort.account, buying_power=D(1002))
    elif damage == "deposit":
        cohort.account = replace(cohort.account, cash=D(1002))
    elif damage == "blocked":
        cohort.account = replace(cohort.account, trading_blocked=True)
    elif damage == "equity":
        cohort.account = replace(cohort.account, equity=D(0))
    with pytest.raises(funding.ProtectedFundingRefused):
        prove(cohort)


@pytest.mark.parametrize("offset", [-1, 61])
def test_future_or_stale_observation_refuses(cohort, offset):
    cohort.now = NOW + timedelta(seconds=offset)
    with pytest.raises(funding.ProtectedFundingNotReady, match="stale or future"):
        prove(cohort)


def test_partial_fill_releases_only_positively_reported_remainder(cohort):
    from sentinel.execution.contract import BrokerPosition
    cohort.commands[0] = replace(cohort.commands[0], state=S.PARTIALLY_FILLED,
        filled_quantity=D(1), filled_average_price=D(100))
    cohort.order = replace(cohort.order, state=S.PARTIALLY_FILLED,
        filled_quantity=D(1), filled_average_price=D(100))
    cohort.account = replace(cohort.account, cash=D(900), buying_power=D(800))
    observation = BrokerObservation(NOW, orders=(cohort.order,),
        positions=(BrokerPosition(cohort.order.instrument, D(1)),),
        account_identity=cohort.account.identity)
    assert prove(cohort, observation=observation).reserved_cash == D(100)
    assert funding.maximum_cost(cohort.commands[0]) == D(201)


@pytest.mark.parametrize("guard", ["basis", "identity", "age", "writer"])
def test_continuation_guard_falsifiers(cohort, monkeypatch, guard):
    source = inspect.getsource(funding.prove_cohort_continuation)
    if guard == "basis":
        cohort.basis = cohort.basis.model_copy(update={"policy_sha256": "d" * 64})
        before = "_assert_basis(basis, plan=plan, projection=projection, deployment=deployment, policy=policy)"
        after = "pass"
    elif guard == "identity":
        cohort.order = replace(cohort.order, broker_order_id="wrong-native-id")
        before = "or order.broker_order_id != command.broker_order_id"
        after = "or False"
    elif guard == "age":
        cohort.now = NOW + timedelta(seconds=61)
        before = "if age < timedelta(0) or age > timedelta(seconds=60):"
        after = "if False:"
    else:
        def unowned(_conn):
            raise funding.ProtectedFundingRefused("writer lock is absent")
        monkeypatch.setattr(funding, "_require_writer", unowned)
        before = "_require_writer(conn)"
        after = "pass"
    with pytest.raises(funding.ProtectedFundingRefused):
        prove(cohort)
    assert source.count(before) == 1
    local = {}
    exec(compile(source.replace(before, after), "<private-cohort-falsifier>", "exec"), vars(funding), local)
    # Removing the guard makes precisely the previously rejected case pass.
    assert prove(cohort, implementation=local["prove_cohort_continuation"]).plan_id == "p"


def test_first_protected_funding_deferral_returns_promptly_to_recovery(cohort, monkeypatch):
    from sentinel.execution import executor
    from sentinel.execution.contract import BrokerCapabilities
    observation = BrokerObservation(NOW, account_identity=cohort.account.identity)
    rec = ReconciliationResult(RuntimeState.RUNNING, observation=observation, observation_id=2)
    async def reconcile(**_kwargs):
        return rec
    async def identify():
        return cohort.account.identity
    monkeypatch.setattr(executor.R, "reconcile", reconcile)
    monkeypatch.setattr(executor.journal, "in_flight_commands", lambda *_args: ())
    monkeypatch.setattr(executor, "_binding", lambda _conn: OWNER)
    instruments = {command.security_id: command.instrument for command in cohort.commands}
    def build(**kwargs):
        delta = kwargs["delta"]
        return Command(CommandIdentity(OWNER, "p", delta.security_id),
            instruments[delta.security_id], Side.BUY, delta.quantity, order_terms=TERMS), False
    sent = []
    async def defer(_conn, _broker, command, **_kwargs):
        sent.append(command.client_key)
        return replace(command, detail="fixed BUY maximum exceeds its reserved paper cash")
    monkeypatch.setattr(executor, "_command_for_delta", build)
    monkeypatch.setattr(executor, "_persist_and_send", defer)
    projection = SimpleNamespace(target_basket=cohort.plan.target_basket,
        opening_sizing={"mode": protected_limits.PROTECTED_MODE})
    monkeypatch.setattr(protected_limits, "unavailable_opening_intents", lambda _projection: {})
    result = asyncio.run(executor._execute_session_locked(
        broker=SimpleNamespace(capabilities=BrokerCapabilities(
            stable_client_key=True, single_order_cancel=True), identify_account=identify),
        conn=object(), deployment=OWNER, plan=cohort.plan, instruments=instruments,
        today=NOW.date(), actions=None, target_projection=projection, min_increment=D(1)))
    assert len(sent) == 1
    assert set(result.deferred) == {"SEC-A", "SEC-B"}
    assert not result.submitted


def test_removing_prompt_recovery_is_detected(cohort, monkeypatch):
    from sentinel.execution import executor
    test_first_protected_funding_deferral_returns_promptly_to_recovery(cohort, monkeypatch)
    source = inspect.getsource(executor._execute_session_locked)
    before = 'if delta.is_increase and order_terms.order_type == "limit":'
    assert source.count(before) == 1
    local = {}
    exec(compile(source.replace(before, "if False:"), "<private-prompt-recovery>", "exec"),
         vars(executor), local)
    monkeypatch.setattr(executor, "_execute_session_locked", local["_execute_session_locked"])
    with pytest.raises(AssertionError):
        test_first_protected_funding_deferral_returns_promptly_to_recovery(cohort, monkeypatch)


@pytest.mark.parametrize("inside,actionable,proved,expected", [
    (True, True, True, "READY_TO_EXECUTE"),
    (True, False, True, "RECONCILE"),
    (False, True, True, "RECONCILE"),
    (True, True, False, "RECONCILE"),
])
def test_recovery_routes_only_proved_unsent_cohort_inside_original_cutoff(
        monkeypatch, inside, actionable, proved, expected):
    from sentinel import automation_runtime, paper
    from sentinel.execution.simulator import SimulatedBroker
    from tests.sentinel import test_automation_runtime as runtime_tests
    cfg = runtime_tests.config()
    plan = runtime_tests.plan()
    ctx = runtime_tests.context(cfg, plan=plan)
    conn = runtime_tests.FakeConnection()
    broker = SimulatedBroker()
    runtime = runtime_tests.production(cfg)
    runtime_tests.install_runtime_seams(monkeypatch, runtime, conn, ctx, broker)
    monkeypatch.setattr(automation_runtime.schema, "require_runtime_schema", lambda _conn: None)
    monkeypatch.setattr(automation_runtime, "require_observation_integrity", lambda _conn: None)
    now = runtime_tests.NOW + (timedelta(seconds=1) if inside else timedelta(minutes=10))
    monkeypatch.setattr(automation_runtime, "_now_utc", lambda: now)
    command = replace(runtime_tests.command(plan.plan_id), order_terms=TERMS)
    observation = BrokerObservation(now, account_identity=BrokerAccountIdentity("sim", "SIM-ACCOUNT"))
    rec = runtime_tests.reconciliation(observation)
    if proved:
        rec.protected_cohort = funding.ProtectedCohortContinuation(
            deployment=funding._deployment(command.identity.deployment), plan_id=plan.plan_id,
            effective_session=plan.effective_session, projection_fingerprint="a" * 64,
            policy_sha256="b" * 64, basis_sha256="c" * 64,
            observation_id=11, observed_at=now, reserved_cash="100",
            commands=({"client_key": command.client_key, "broker_order_id": command.broker_order_id,
                "security_id": command.security_id, "state": "ACKNOWLEDGED", "side": "BUY",
                "remaining_quantity": "1", "limit_price": "100", "order_terms": TERMS.to_dict()},))
    async def recovered(**_kwargs):
        return rec
    monkeypatch.setattr(paper, "recover_automated_paper_cycle", recovered)
    monkeypatch.setattr(automation_runtime.journal, "in_flight_commands", lambda *_args: (command,))
    monkeypatch.setattr(automation_runtime.journal, "load_commands", lambda *_args, **_kwargs: (command,))
    monkeypatch.setattr(automation_runtime.journal, "latest_plan", lambda _conn: plan)
    runtime._actionable_current_plan_deltas = lambda *_args, **_kwargs: (
        (SimpleNamespace(security_id="SEC-B", remaining=D(1), is_increase=True),) if actionable else ())
    result = asyncio.run(runtime.recover(ctx))
    assert result.disposition.value == expected
    if proved and (not inside or not actionable):
        assert result.failure_code == "PROTECTED_DAY_ORDERS_WORKING"
        assert result.diagnostic["protected_day_wait"]["reserved_cash"] == "100"
    elif not proved:
        assert result.failure_code == "COMMANDS_IN_FLIGHT"
    else:
        assert result.failure_code == "PROTECTED_COHORT_READY"
