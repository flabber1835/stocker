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
