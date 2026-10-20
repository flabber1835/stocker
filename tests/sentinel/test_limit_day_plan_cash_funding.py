"""An uncertified activity producer never earns credit in a paper cash cohort."""
import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import inspect
from types import SimpleNamespace

import pytest

from sentinel import binding
from sentinel.execution import journal, protected_funding as funding, protected_limits, target_reprojection
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.certification import certify_adapter, require_certified_adapter
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerAccountIdentity, BrokerAccountSnapshot, BrokerObservation, OrderTerms, Side
from sentinel.execution.guarded import GuardedExecutionBroker
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.reconcile import ReconciliationResult
from sentinel.execution.states import CommandState as S, RuntimeState
from sentinel.paper import cash, inspection, validation
from tests.sentinel.test_guarded_execution_broker import Recorder, conn, pg  # noqa: F401


from sentinel.execution.contract import BrokerInstrument, BrokerOrder
from sentinel.execution.identity import DeploymentIdentity

NOW = datetime(2026, 10, 19, 13, 31, tzinfo=timezone.utc)
PAPER = "https://paper-api.alpaca.markets"
ACCOUNT = "PAPER-CASH-FUNDING"


def native_wrapper(*, inner=None):
    if inner is None:
        inner = AssetIdAlpacaExecutionBroker(api_key="fixture", secret_key="fixture",
            base_url=PAPER, http_provider=lambda: pytest.fail("unexpected provider request"))
        certify_adapter(inner, name="alpaca", mode="ALPACA_PAPER")
    return Recorder().wrap(inner)


def account(value="1000", bp=None):
    return BrokerAccountSnapshot(BrokerAccountIdentity("alpaca", ACCOUNT), D(1000), D(value),
        buying_power=D(value if bp is None else bp), multiplier=D(1), status="ACTIVE")


def test_real_asset_id_composition_selects_no_activity_variant_across_restart():
    first, restarted = native_wrapper(), native_wrapper()
    assert first.capabilities.account_cash_activity_evidence is False
    assert first.supports_account_cash_activities is False
    assert first.financial_activity_sse is False
    assert require_certified_adapter(first).composition_sha256 != require_certified_adapter(restarted).composition_sha256
    assert funding._plan_cash_composition(first) == funding._plan_cash_composition(restarted)
    assert funding._plan_cash_composition(None) is None


@pytest.mark.parametrize("damage", ["fake", "simulator", "bare", "rewrapped", "callback", "inner-capability", "live-endpoint"])
def test_unissued_foreign_or_changed_composition_never_selects_plan_cash(damage):
    wrapped = native_wrapper()
    if damage == "fake":
        wrapped = SimpleNamespace(capabilities=wrapped.capabilities,
            supports_account_cash_activities=False, certified_adapter_identity=require_certified_adapter(wrapped))
    elif damage == "simulator":
        from sentinel.execution.simulator import SimulatedBroker
        inner = SimulatedBroker()
        certify_adapter(inner, name="simulator", mode="SIMULATION")
        wrapped = Recorder().wrap(inner)
    elif damage == "bare":
        assert funding._plan_cash_composition(wrapped._inner) is None
        return
    elif damage == "rewrapped":
        wrapped._inner = native_wrapper()._inner
    elif damage == "inner-capability":
        wrapped._inner.capabilities = replace(wrapped._inner.capabilities, account_cash_activity_evidence=True)
    elif damage == "live-endpoint":
        wrapped._inner.base_url = "https://api.alpaca.markets"
    else:
        wrapped._protected_funding = lambda **kwargs: None
    with pytest.raises(funding.ProtectedFundingRefused, match="certified Alpaca paper"):
        funding._plan_cash_composition(wrapped)


@pytest.fixture
def case(conn, monkeypatch):
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", protected_limits.PROTECTED_MODE)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", "100")
    owner = binding.bind(conn, deployment_id="plan-cash", broker="alpaca", broker_account_id=ACCOUNT)
    # The fixture's historical observation belongs after its actual account
    # binding; the real provenance loader correctly excludes pre-binding rows.
    conn.execute("UPDATE sentinel_account_binding SET established_at=%s WHERE id=1", (NOW - timedelta(days=1),))
    conn.commit()
    from sentinel.execution.contract import BrokerInstrument
    instrument = BrokerInstrument("SEC-A", "AAA", "native-aaa")
    candidate = Command(CommandIdentity(owner.identity, "p", instrument.security_id), instrument,
        Side.BUY, D(1), state=S.SEND_PENDING, order_terms=OrderTerms(order_type="limit", limit_price=D(99)))
    plan = ExecutionPlan("p", date(2026, 10, 16), NOW.date(), D(1), {instrument.security_id: D(1)},
        deployment_id=owner.deployment_id, broker=owner.broker, broker_account_id=ACCOUNT,
        takeover_epoch=owner.takeover_epoch, account_nav=D(1000), account_cash=D(1000))
    journal.save_plan(conn, plan)
    projection = target_reprojection.TargetProjection("p", plan.fingerprint(), NOW.date(), {}, (), {}, plan.target_basket)
    target_reprojection.record_projection(conn, projection)
    observed = BrokerObservation(NOW, started_at=NOW - timedelta(seconds=1), account_identity=account().identity)
    seq = journal.record_observation(conn, observed, RuntimeState.RUNNING.value)
    reconciliation = ReconciliationResult(RuntimeState.RUNNING, observation=observed, observation_id=seq)
    monkeypatch.setattr(protected_limits, "revalidate_references", lambda *_args, **_kwargs:
        SimpleNamespace(source_provider="ALPACA_OPENFIGI", symbols={instrument.security_id: instrument.symbol},
                        provider_asset_ids={instrument.security_id: instrument.broker_id}))
    monkeypatch.setattr(protected_limits, "order_terms_for", lambda *_args: candidate.order_terms)
    return SimpleNamespace(owner=owner, candidate=candidate, plan=plan, projection=projection,
        reconciliation=reconciliation, broker=native_wrapper())


def earn(conn, case, *, snapshot=None, activity=None, broker=None):
    return funding.record_quiescent_basis(conn, plan=case.plan, projection=case.projection,
        binding=case.owner, reconciliation=case.reconciliation, account=snapshot or account(),
        activity_state=activity, observed_at=NOW, paper_base_url=PAPER,
        broker=case.broker if broker is None else broker)


def submit(conn, case, *, snapshot=None, activity=None, broker=None):
    candidate = case.candidate
    return funding.validate_submission(conn, client_key=candidate.client_key,
        instrument=candidate.instrument, quantity=candidate.quantity, order_terms=candidate.order_terms,
        account=snapshot or account(), activity_state=activity,
        broker=case.broker if broker is None else broker)


def reserve(conn, case):
    journal.save_command(conn, case.candidate)


def test_real_certified_composition_earns_and_reloads_typed_no_activity_basis(conn, case):
    with journal.writer_lock(conn, recovery_only=True):
        basis = earn(conn, case)
        assert isinstance(basis, funding.PlanCashFundingBasis)
        assert basis.schema == "sentinel.protected-buy-funding/2"
        assert basis.cash == basis.plan_cash_ceiling == D(1000)
        assert "cash_activity_sha256" not in basis.model_dump()
        assert funding.load_basis(conn, plan_id="p") == basis
        reserve(conn, case)
        assert submit(conn, case, broker=native_wrapper()) is None
        with pytest.raises(funding.ProtectedFundingRefused, match="composition"):
            submit(conn, case, broker=object())


@pytest.mark.parametrize("advertised,supported", [(True, True), (True, False), (False, True)])
def test_activity_capable_missing_interval_never_falls_back(conn, case, advertised, supported):
    # The capability boundary alone is enough to rule out /2, before any
    # production-certified no-activity composition could be selected.
    capable = SimpleNamespace(capabilities=replace(case.broker.capabilities,
        account_cash_activity_evidence=advertised), supports_account_cash_activities=supported)
    with journal.writer_lock(conn, recovery_only=True):
        with pytest.raises(funding.ProtectedFundingNotReady, match="native cash-activity"):
            earn(conn, case, broker=capable)
    assert funding.load_basis(conn, plan_id="p") is None


def test_disabled_capability_cannot_smuggle_an_activity_identity(conn, case):
    with journal.writer_lock(conn, recovery_only=True):
        with pytest.raises(funding.ProtectedFundingRefused, match="disabled cash capability"):
            earn(conn, case, activity=object())


@pytest.mark.parametrize("cash_value", ["999.50", "1000.50", "1001"])
def test_cash_equation_tolerance_is_never_added_to_ceiling(conn, case, cash_value):
    with journal.writer_lock(conn, recovery_only=True):
        basis = earn(conn, case, snapshot=account(cash_value))
    assert basis.cash == D(cash_value)
    assert basis.plan_cash_ceiling == min(D(cash_value), case.plan.account_cash)


def test_only_reported_durable_same_plan_sell_principal_can_fund_basis(conn, case):
    sell = replace(case.candidate, identity=replace(case.candidate.identity, security_id="SEC-SELL"),
        instrument=replace(case.candidate.instrument, security_id="SEC-SELL"), side=Side.SELL,
        quantity=D(2), filled_quantity=D(2), filled_average_price=D("12.345"),
        state=S.FILLED, order_terms=OrderTerms(), broker_order_id="positive-sell")
    journal.save_command(conn, sell)
    with journal.writer_lock(conn, recovery_only=True):
        basis = earn(conn, case, snapshot=account("1024.69"))
    assert basis.plan_cash_ceiling == D("1024.69")


def test_no_missing_average_or_prospective_sell_credit():
    plan = SimpleNamespace(account_cash=D("1000.000000000000000000000001"))
    sell = SimpleNamespace(side=Side.SELL, filled_quantity=D(0), filled_average_price=None)
    assert funding._plan_cash_ceiling(plan=plan, account=account("2000"), commands=(sell,)) == plan.account_cash
    sell.filled_quantity = D(1)
    with pytest.raises(funding.ProtectedFundingRefused, match="reported average"):
        funding._plan_cash_ceiling(plan=plan, account=account("2000"), commands=(sell,))


@pytest.mark.parametrize("cash_value,allowed", [("1001", True), ("1001.01", False), ("500", True), ("99", False)])
def test_deposit_refuses_and_withdrawal_only_restricts_fixed_budget(conn, case, cash_value, allowed):
    with journal.writer_lock(conn, recovery_only=True):
        earn(conn, case)
        reserve(conn, case)
        if allowed:
            submit(conn, case, snapshot=account(cash_value))
        else:
            with pytest.raises(funding.ProtectedFundingRefused):
                submit(conn, case, snapshot=account(cash_value))


@pytest.mark.parametrize("state", [S.PLANNED, S.SEND_PENDING, S.UNKNOWN, S.CANCEL_PENDING,
    S.ACKNOWLEDGED, S.PARTIALLY_FILLED, S.FILLED, S.CANCELLED, S.REJECTED])
def test_lag_restart_cancel_or_terminal_savings_never_release_gross_promise(conn, case, state):
    with journal.writer_lock(conn, recovery_only=True):
        earn(conn, case)
        prior = replace(case.candidate, identity=replace(case.candidate.identity, security_id="SEC-OTHER"),
            instrument=replace(case.candidate.instrument, security_id="SEC-OTHER"),
            state=state, order_terms=OrderTerms(order_type="limit", limit_price=D(950)))
        if state is S.FILLED:
            prior = replace(prior, filled_quantity=D(1), filled_average_price=D(900))
        if state is S.PARTIALLY_FILLED:
            prior = replace(prior, quantity=D(2), filled_quantity=D(1), filled_average_price=D(900))
        journal.save_command(conn, prior)
        reserve(conn, case)
        with pytest.raises(funding.ProtectedFundingNotReady, match="reserved paper cash"):
            submit(conn, case, broker=native_wrapper())


def test_existing_basis_is_not_renewed_with_deposit_or_later_sale(conn, case):
    with journal.writer_lock(conn, recovery_only=True):
        original = earn(conn, case)
        assert earn(conn, case, snapshot=account("2000"), broker=native_wrapper()) == original
        reserve(conn, case)
        with pytest.raises(funding.ProtectedFundingRefused, match="cash increased"):
            submit(conn, case, snapshot=account("2000"))


def test_existing_quiescence_and_strict_cash_checks_still_refuse(conn, case):
    with journal.writer_lock(conn, recovery_only=True):
        reserve(conn, case)
        with pytest.raises(funding.ProtectedFundingNotReady, match="quiescent"):
            earn(conn, case)
    assert funding.load_basis(conn, plan_id="p") is None


@pytest.mark.parametrize("cash_value", ["998.99", "1001.01"])
def test_unexplained_cash_at_basis_is_not_normalized_into_a_flow(conn, case, cash_value):
    from sentinel.paper.model import PaperActivationRefused
    with journal.writer_lock(conn, recovery_only=True):
        with pytest.raises(PaperActivationRefused, match="not explained|not yet coherent"):
            earn(conn, case, snapshot=account(cash_value))
    assert funding.load_basis(conn, plan_id="p") is None


def test_variant_shape_is_strict_and_retained_activity_shape_is_unchanged():
    from tests.sentinel.test_limit_day_funding import funding_basis
    old = funding_basis()
    assert set(old.model_dump()) == {"schema", "deployment", "plan_id", "plan_fingerprint",
        "projection_fingerprint", "policy_sha256", "effective_session", "paper_base_url", "observed_at",
        "observation_id", "observation_sha256", "cash_activity_sha256", "cash", "buying_power", "multiplier"}
    new = {key: value for key, value in old.model_dump().items() if key != "cash_activity_sha256"}
    new.update(schema="sentinel.protected-buy-funding/2", broker_composition_sha256="f" * 64,
               plan_cash_ceiling=D(1000))
    assert funding.PlanCashFundingBasis.model_validate(new).plan_cash_ceiling == D(1000)
    with pytest.raises(ValueError):
        funding.FundingBasis.model_validate(new)
    with pytest.raises(ValueError):
        funding.PlanCashFundingBasis.model_validate({**new, "cash_activity_sha256": "e" * 64})


def test_real_production_guarded_callback_passes_actual_wrapper_and_never_calls_sse(conn, case, monkeypatch):
    from sentinel import structural_verification
    # Keep the real AssetId adapter, issued wrapper/callback seal, cash reader,
    # durable basis, source-symbol binding and funding arithmetic. Authority
    # issuance is a separate contract, so replace only its external guard here.
    guard = Recorder().wrap(case.broker._inner).guard
    monkeypatch.setattr(structural_verification, "owned", lambda _conn: None)
    monkeypatch.setattr(structural_verification, "Scope", lambda _conn: object())
    monkeypatch.setattr(validation, "_fresh_connection_factory", lambda _conn: None)
    monkeypatch.setattr(validation, "build_fresh_execution_guard", lambda **_kwargs: guard)
    wrapped = validation._guard_broker(conn=conn, broker=case.broker._inner, grant=case.broker.grant,
        base_url=PAPER, now_provider=lambda: NOW, strategy_provider=lambda: {})
    assert require_certified_adapter(wrapped).wrapper_kind == "generation-fenced-execution"
    case.broker = wrapped
    with journal.writer_lock(conn, recovery_only=True):
        state = asyncio.run(cash._broker_cash_state_or_refuse(conn, broker=wrapped, binding=case.owner, through=NOW))
        assert state is None
        earn(conn, case, activity=state)
        reserve(conn, case)
        asyncio.run(wrapped._protected_funding(client_key=case.candidate.client_key,
            instrument=case.candidate.instrument, quantity=case.candidate.quantity,
            order_terms=case.candidate.order_terms, account=account()))


@pytest.mark.parametrize("guard", ["composition", "no-credit", "deposit"])
def test_private_guard_removal_is_detected(conn, case, monkeypatch, guard):
    if guard == "composition":
        target = funding._plan_cash_composition
        needle = 'identity = require_certified_adapter(broker, expected="alpaca")'
        # A forged field must be rejected by actual issuance, not accepted as
        # an adapter's self-described certification identity.
        replacement = 'identity = broker.certified_adapter_identity'
        fake = SimpleNamespace(capabilities=case.broker.capabilities,
            supports_account_cash_activities=False, _inner=case.broker._inner,
            certified_adapter_identity=require_certified_adapter(case.broker))
        def rejected():
            with pytest.raises(funding.ProtectedFundingRefused):
                funding._plan_cash_composition(fake)
    elif guard == "no-credit":
        target = funding._plan_cash_ceiling
        needle = "min(Fraction(account.cash), expected)"
        replacement = "Fraction(account.cash)"
        def rejected():
            assert funding._plan_cash_ceiling(plan=case.plan, account=account("1000.50"), commands=()) == D(1000)
    else:
        target = funding.validate_submission
        needle = "if account.cash > basis.cash + HEADROOM:"
        replacement = "if False:"
        with journal.writer_lock(conn, recovery_only=True):
            earn(conn, case)
            reserve(conn, case)
        def rejected():
            with journal.writer_lock(conn, recovery_only=True):
                with pytest.raises(funding.ProtectedFundingRefused):
                    submit(conn, case, snapshot=account("2000"))
    rejected()
    source = inspect.getsource(target)
    assert source.count(needle) == 1
    local = {}
    exec(compile(source.replace(needle, replacement), "<private-plan-cash-" + guard + ">", "exec"), vars(funding), local)
    monkeypatch.setattr(funding, target.__name__, local[target.__name__])
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        rejected()

# TestProtectedCohortContinuation owns the permanent continuation contract.
CONTINUATION_NOW = datetime(2026, 10, 20, 13, 32, tzinfo=timezone.utc)

CONTINUATION_OWNER = DeploymentIdentity("cohort", "alpaca", "private-paper", 1)

CONTINUATION_TERMS = OrderTerms(order_type="limit", limit_price=D(100))

CONTINUATION_PAPER = "https://paper-api.alpaca.markets"

@pytest.fixture
def continuation_cohort(monkeypatch):
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", protected_limits.PROTECTED_MODE)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", "100")
    plan = ExecutionPlan("p", date(2026, 10, 19), CONTINUATION_NOW.date(), D(1),
        {"SEC-A": D(2), "SEC-B": D(1)}, deployment_id=CONTINUATION_OWNER.deployment_id,
        broker=CONTINUATION_OWNER.broker, broker_account_id=CONTINUATION_OWNER.broker_account_id,
        takeover_epoch=1, account_cash=D(1000), account_nav=D(1000))
    projection = SimpleNamespace(target_basket=plan.target_basket, fingerprint=lambda: "b" * 64)
    basis = funding.PlanCashFundingBasis(deployment=funding._deployment(CONTINUATION_OWNER), plan_id="p",
        plan_fingerprint=plan.fingerprint(), projection_fingerprint=projection.fingerprint(),
        policy_sha256=protected_limits.ProtectedLimitPolicy(100).fingerprint(),
        effective_session=CONTINUATION_NOW.date(), paper_base_url=CONTINUATION_PAPER, observed_at=CONTINUATION_NOW-timedelta(minutes=1),
        observation_id=1, observation_sha256="a" * 64, cash="1000", buying_power="1000",
        broker_composition_sha256="c" * 64, plan_cash_ceiling="1000")
    instrument = BrokerInstrument("SEC-A", "AAA", "native-a")
    command = Command(CommandIdentity(CONTINUATION_OWNER, "p", instrument.security_id), instrument,
        Side.BUY, D(2), state=S.ACKNOWLEDGED, broker_order_id="order-a", order_terms=CONTINUATION_TERMS)
    planned = Command(CommandIdentity(CONTINUATION_OWNER, "p", "SEC-B"),
        BrokerInstrument("SEC-B", "BBB", "native-b"), Side.BUY, D(1), order_terms=CONTINUATION_TERMS)
    order = BrokerOrder("order-a", command.client_key, instrument, Side.BUY,
        S.ACKNOWLEDGED, D(2), order_terms=CONTINUATION_TERMS)
    account = BrokerAccountSnapshot(BrokerAccountIdentity("alpaca", "private-paper"),
        D(1000), D(1000), buying_power=D(800), multiplier=D(1), status="ACTIVE")
    value = SimpleNamespace(plan=plan, projection=projection, basis=basis,
        commands=[command, planned], order=order, account=account, now=CONTINUATION_NOW)
    monkeypatch.setattr(funding, "_require_writer", lambda _conn: None)
    monkeypatch.setattr(funding, "load_basis", lambda *_args, **_kwargs: value.basis)
    monkeypatch.setattr(funding.journal, "latest_plan", lambda _conn: value.plan)
    monkeypatch.setattr(funding.journal, "load_commands", lambda *_args, **_kwargs: value.commands)
    monkeypatch.setattr(funding.target_reprojection, "assert_projection", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(protected_limits, "order_terms_for", lambda *_args: CONTINUATION_TERMS)
    monkeypatch.setattr(funding, "_plan_cash_composition", lambda _broker: "c" * 64)
    return value

def continuation_prove(continuation_cohort, *, implementation=None, observation=None, **changes):
    observation = observation or BrokerObservation(
        CONTINUATION_NOW, orders=(continuation_cohort.order,), account_identity=continuation_cohort.account.identity)
    rec = ReconciliationResult(RuntimeState.RUNNING, observation=observation, observation_id=2)
    kwargs = dict(plan=continuation_cohort.plan, projection=continuation_cohort.projection, deployment=CONTINUATION_OWNER,
        reconciliation=rec, account=continuation_cohort.account, activity_state=None,
        broker=object(), paper_base_url=CONTINUATION_PAPER, evaluated_at=continuation_cohort.now)
    kwargs.update(changes)
    return (implementation or funding.prove_cohort_continuation)(object(), **kwargs)


class TestProtectedCohortContinuation:
    'Only positively observed, already funded protected cohorts may continue.'

    def test_owned_working_day_buy_can_continue_same_fixed_cohort(self, continuation_cohort):
        before = continuation_cohort.basis.model_dump()
        evidence = continuation_prove(continuation_cohort)
        assert evidence.reserved_cash == D(200)
        assert evidence.commands[0]["client_key"] == continuation_cohort.commands[0].client_key
        assert evidence.commands[0]["remaining_quantity"] == "2"
        assert evidence.observation_id == 2 and evidence.observed_at == CONTINUATION_NOW
        assert continuation_cohort.basis.model_dump() == before

    @pytest.mark.parametrize("state", [S.UNKNOWN, S.SEND_PENDING, S.CANCEL_PENDING])
    def test_uncertain_commands_never_earn_continuation(self, continuation_cohort, state):
        continuation_cohort.commands[0] = replace(continuation_cohort.commands[0], state=state)
        with pytest.raises(funding.ProtectedFundingRefused, match="uncertain"):
            continuation_prove(continuation_cohort)

    @pytest.mark.parametrize("damage", ["foreign", "native-id", "quantity", "terms", "replacement",
        "missing", "filled-counter", "sell", "other-plan", "basis", "composition", "endpoint",
        "planned-quantity", "margin", "deposit", "blocked", "equity"])
    def test_changed_or_missing_cohort_evidence_refuses(self, continuation_cohort, damage, monkeypatch):
        if damage == "foreign":
            continuation_cohort.order = replace(continuation_cohort.order, client_key="foreign")
        elif damage == "native-id":
            continuation_cohort.order = replace(continuation_cohort.order, broker_order_id="other")
        elif damage == "quantity":
            continuation_cohort.order = replace(continuation_cohort.order, quantity=D(3))
        elif damage == "terms":
            continuation_cohort.order = replace(continuation_cohort.order, order_terms=replace(CONTINUATION_TERMS, limit_price=D(101)))
        elif damage == "replacement":
            continuation_cohort.order = replace(continuation_cohort.order, external_replacement=True)
        elif damage == "missing":
            observation = BrokerObservation(CONTINUATION_NOW, account_identity=continuation_cohort.account.identity)
            with pytest.raises(funding.ProtectedFundingRefused, match="positive"):
                continuation_prove(continuation_cohort, observation=observation)
            return
        elif damage == "filled-counter":
            continuation_cohort.order = replace(continuation_cohort.order, filled_quantity=D(1), filled_average_price=D(100))
        elif damage == "sell":
            continuation_cohort.commands[0] = replace(continuation_cohort.commands[0], side=Side.SELL, order_terms=OrderTerms())
        elif damage == "other-plan":
            continuation_cohort.commands[0] = replace(continuation_cohort.commands[0],
                identity=replace(continuation_cohort.commands[0].identity, plan_id="another"))
        elif damage == "basis":
            continuation_cohort.basis = continuation_cohort.basis.model_copy(update={"policy_sha256": "d" * 64})
        elif damage == "composition":
            monkeypatch.setattr(funding, "_plan_cash_composition", lambda _broker: "d" * 64)
        elif damage == "endpoint":
            continuation_cohort.basis = continuation_cohort.basis.model_copy(update={"paper_base_url": "https://paper-other.invalid"})
        elif damage == "planned-quantity":
            continuation_cohort.commands[1] = replace(continuation_cohort.commands[1], quantity=D(2))
        elif damage == "margin":
            continuation_cohort.account = replace(continuation_cohort.account, buying_power=D(1002))
        elif damage == "deposit":
            continuation_cohort.account = replace(continuation_cohort.account, cash=D(1002))
        elif damage == "blocked":
            continuation_cohort.account = replace(continuation_cohort.account, trading_blocked=True)
        elif damage == "equity":
            continuation_cohort.account = replace(continuation_cohort.account, equity=D(0))
        with pytest.raises(funding.ProtectedFundingRefused):
            continuation_prove(continuation_cohort)

    @pytest.mark.parametrize("offset", [-1, 61])
    def test_future_or_stale_observation_refuses(self, continuation_cohort, offset):
        continuation_cohort.now = CONTINUATION_NOW + timedelta(seconds=offset)
        with pytest.raises(funding.ProtectedFundingNotReady, match="stale or future"):
            continuation_prove(continuation_cohort)

    def test_partial_fill_releases_only_positively_reported_remainder(self, continuation_cohort):
        from sentinel.execution.contract import BrokerPosition
        continuation_cohort.commands[0] = replace(continuation_cohort.commands[0], state=S.PARTIALLY_FILLED,
            filled_quantity=D(1), filled_average_price=D(100))
        continuation_cohort.order = replace(continuation_cohort.order, state=S.PARTIALLY_FILLED,
            filled_quantity=D(1), filled_average_price=D(100))
        continuation_cohort.account = replace(continuation_cohort.account, cash=D(900), buying_power=D(800))
        observation = BrokerObservation(CONTINUATION_NOW, orders=(continuation_cohort.order,),
            positions=(BrokerPosition(continuation_cohort.order.instrument, D(1)),),
            account_identity=continuation_cohort.account.identity)
        assert continuation_prove(continuation_cohort, observation=observation).reserved_cash == D(100)
        assert funding.maximum_cost(continuation_cohort.commands[0]) == D(201)

    @pytest.mark.parametrize("guard", ["basis", "identity", "age", "writer"])
    def test_continuation_guard_falsifiers(self, continuation_cohort, monkeypatch, guard):
        source = inspect.getsource(funding.prove_cohort_continuation)
        if guard == "basis":
            continuation_cohort.basis = continuation_cohort.basis.model_copy(update={"policy_sha256": "d" * 64})
            before = "_assert_basis(basis, plan=plan, projection=projection, deployment=deployment, policy=policy)"
            after = "pass"
        elif guard == "identity":
            continuation_cohort.order = replace(continuation_cohort.order, broker_order_id="wrong-native-id")
            before = "or order.broker_order_id != command.broker_order_id"
            after = "or False"
        elif guard == "age":
            continuation_cohort.now = CONTINUATION_NOW + timedelta(seconds=61)
            before = "if age < timedelta(0) or age > timedelta(seconds=60):"
            after = "if False:"
        else:
            def unowned(_conn):
                raise funding.ProtectedFundingRefused("writer lock is absent")
            monkeypatch.setattr(funding, "_require_writer", unowned)
            before = "_require_writer(conn)"
            after = "pass"
        with pytest.raises(funding.ProtectedFundingRefused):
            continuation_prove(continuation_cohort)
        assert source.count(before) == 1
        local = {}
        exec(compile(source.replace(before, after), "<private-cohort-falsifier>", "exec"), vars(funding), local)
        # Removing the guard makes precisely the previously rejected case pass.
        assert continuation_prove(continuation_cohort, implementation=local["prove_cohort_continuation"]).plan_id == "p"

    def test_first_protected_funding_deferral_returns_promptly_to_recovery(self, continuation_cohort, monkeypatch):
        from sentinel.execution import executor
        from sentinel.execution.contract import BrokerCapabilities
        observation = BrokerObservation(CONTINUATION_NOW, account_identity=continuation_cohort.account.identity)
        rec = ReconciliationResult(RuntimeState.RUNNING, observation=observation, observation_id=2)
        async def reconcile(**_kwargs):
            return rec
        async def identify():
            return continuation_cohort.account.identity
        monkeypatch.setattr(executor.R, "reconcile", reconcile)
        monkeypatch.setattr(executor.journal, "in_flight_commands", lambda *_args: ())
        monkeypatch.setattr(executor, "_binding", lambda _conn: CONTINUATION_OWNER)
        instruments = {command.security_id: command.instrument for command in continuation_cohort.commands}
        def build(**kwargs):
            delta = kwargs["delta"]
            return Command(CommandIdentity(CONTINUATION_OWNER, "p", delta.security_id),
                instruments[delta.security_id], Side.BUY, delta.quantity, order_terms=CONTINUATION_TERMS), False
        sent = []
        async def defer(_conn, _broker, command, **_kwargs):
            sent.append(command.client_key)
            return replace(command, detail="fixed BUY maximum exceeds its reserved paper cash")
        monkeypatch.setattr(executor, "_command_for_delta", build)
        monkeypatch.setattr(executor, "_persist_and_send", defer)
        projection = SimpleNamespace(target_basket=continuation_cohort.plan.target_basket,
            opening_sizing={"mode": protected_limits.PROTECTED_MODE})
        monkeypatch.setattr(protected_limits, "unavailable_opening_intents", lambda _projection: {})
        result = asyncio.run(executor._execute_session_locked(
            broker=SimpleNamespace(capabilities=BrokerCapabilities(
                stable_client_key=True, single_order_cancel=True), identify_account=identify),
            conn=object(), deployment=CONTINUATION_OWNER, plan=continuation_cohort.plan, instruments=instruments,
            today=CONTINUATION_NOW.date(), actions=None, target_projection=projection, min_increment=D(1)))
        assert len(sent) == 1
        assert set(result.deferred) == {"SEC-A", "SEC-B"}
        assert not result.submitted

    def test_removing_prompt_recovery_is_detected(self, continuation_cohort, monkeypatch):
        from sentinel.execution import executor
        self.test_first_protected_funding_deferral_returns_promptly_to_recovery(continuation_cohort, monkeypatch)
        source = inspect.getsource(executor._execute_session_locked)
        before = 'if delta.is_increase and order_terms.order_type == "limit":'
        assert source.count(before) == 1
        local = {}
        exec(compile(source.replace(before, "if False:"), "<private-prompt-recovery>", "exec"),
             vars(executor), local)
        monkeypatch.setattr(executor, "_execute_session_locked", local["_execute_session_locked"])
        with pytest.raises(AssertionError):
            self.test_first_protected_funding_deferral_returns_promptly_to_recovery(continuation_cohort, monkeypatch)

    @pytest.mark.parametrize("inside,actionable,proved,expected", [
        (True, True, True, "READY_TO_EXECUTE"),
        (True, False, True, "RECONCILE"),
        (False, True, True, "RECONCILE"),
        (True, True, False, "RECONCILE"),
    ])
    def test_recovery_routes_only_proved_unsent_cohort_inside_original_cutoff(self,
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
        command = replace(runtime_tests.command(plan.plan_id), order_terms=CONTINUATION_TERMS)
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
                    "remaining_quantity": "1", "limit_price": "100", "order_terms": CONTINUATION_TERMS.to_dict()},))
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
        if proved:
            from sentinel.automation.model import ProtectedDayWait
            from sentinel.feed import calendar
            wait = ProtectedDayWait.model_validate(result.diagnostic['protected_day_wait'])
            assert wait.plan_id == plan.plan_id and wait.effective_session == plan.effective_session
            assert wait.deployment == funding._deployment(command.identity.deployment)
            assert wait.observed_at == now
            assert wait.deadline == calendar.session_window(plan.effective_session)[1] + timedelta(minutes=10)
            assert wait.commands[0].broker_order_id == command.broker_order_id
            assert wait.commands[0].order_terms == CONTINUATION_TERMS.to_dict()
        else:
            assert 'protected_day_wait' not in result.diagnostic
        if proved and (not inside or not actionable):
            assert result.failure_code == "PROTECTED_DAY_ORDERS_WORKING"
            assert result.diagnostic["protected_day_wait"]["reserved_cash"] == "100"
        elif not proved:
            assert result.failure_code == "COMMANDS_IN_FLIGHT"
        else:
            assert result.failure_code == "PROTECTED_COHORT_READY"
