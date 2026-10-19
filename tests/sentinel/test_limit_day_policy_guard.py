"""Selected protected policy and real grant branches fail closed before POST."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import inspect
import textwrap
from types import SimpleNamespace

import pytest

from sentinel import authority, dual_plan_authority, dual_reconciliation, structural_verification
from sentinel.authority import validation as authority_validation
from sentinel.core.decision import _shadow_equity
from sentinel.execution import protected_limits, target_reprojection
from sentinel.execution.certification import (
    AdapterNotCertified, certify_adapter, require_certified_adapter)
from sentinel.execution.commands import Command
from sentinel.execution.contract import OrderTerms, Side
from sentinel.execution.guarded import (
    AutomationExecutionGrant, BrokerOperation, GuardedExecutionBroker, ManualExecutionGrant,
    PreTransportAuthorityRefused)
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.simulator import SimulatedBroker
from sentinel.execution.states import CommandState as S
from sentinel.paper import validation
from tests.sentinel.test_opening_submit_freshness_boundary import instrument, wrap
from tests.sentinel.test_limit_day_funding import DEPLOYMENT, ProtectedBroker
from tests.sentinel.test_production_decision import (
    DECISION_SESSION, EFFECTIVE_SESSION, _account, _binding, _state)
from tests.sentinel.test_regular_quote_submission import QuoteBroker
from tests.sentinel import test_signed_authority as signed_fx


@pytest.fixture(autouse=True)
def legacy_environment(monkeypatch):
    monkeypatch.delenv("SENTINEL_PAPER_BUY_POLICY", raising=False)
    monkeypatch.delenv("SENTINEL_PAPER_BUY_CAP_BPS", raising=False)


def select(monkeypatch, cap="100"):
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", protected_limits.PROTECTED_MODE)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", cap)


def at_open(inner):
    from sentinel.feed import calendar
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened + timedelta(seconds=61)
    return inner


@pytest.mark.parametrize("omit", [True, False])
def test_selected_policy_cannot_drop_limit_terms_to_legacy_market(monkeypatch, omit):
    select(monkeypatch)
    inner = at_open(QuoteBroker())
    broker = wrap(inner)
    command = Command(CommandIdentity(DEPLOYMENT, "p", instrument().security_id),
        instrument(), Side.BUY, D(1), state=S.SEND_PENDING)
    kwargs = dict(client_key=command.client_key, instrument=command.instrument,
                  side=command.side, quantity=command.quantity)
    if not omit:
        kwargs["order_terms"] = OrderTerms()
    with pytest.raises(PreTransportAuthorityRefused, match="requires immutable LIMIT/DAY") as caught:
        asyncio.run(broker.submit(**kwargs))
    assert inner.calls == []
    broker.consume_not_transported(caught.value, command)
    with pytest.raises(ValueError, match="matching unused"):
        broker.consume_not_transported(caught.value, command)


def test_legacy_market_stays_available_when_policy_is_unset():
    inner = at_open(QuoteBroker())
    result = asyncio.run(wrap(inner).submit(client_key="legacy", instrument=instrument(),
                                           side=Side.BUY, quantity=D(1)))
    assert result.state is S.ACKNOWLEDGED and "quote-read" in inner.calls


def test_selected_policy_keeps_legacy_market_sell_terms(monkeypatch):
    select(monkeypatch)
    inner = at_open(QuoteBroker())
    inner.seed_position(instrument(), "1")
    result = asyncio.run(wrap(inner).submit(client_key="sell", instrument=instrument(),
                                           side=Side.SELL, quantity=D(1)))
    assert result.state is S.ACKNOWLEDGED
    assert "quote-read" not in inner.calls


@pytest.mark.parametrize("policy,cap", [
    ("UNREVIEWED", "100"), (protected_limits.PROTECTED_MODE, None),
    (protected_limits.PROTECTED_MODE, "1.5"), (None, "100"),
])
def test_invalid_policy_configuration_is_a_known_exact_unsent_refusal(monkeypatch, policy, cap):
    if policy is not None:
        monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", policy)
    if cap is not None:
        monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", cap)
    inner = at_open(QuoteBroker())
    broker = wrap(inner)
    command = Command(CommandIdentity(DEPLOYMENT, "p", instrument().security_id),
        instrument(), Side.BUY, D(1), state=S.SEND_PENDING)
    with pytest.raises(PreTransportAuthorityRefused, match="policy configuration") as caught:
        asyncio.run(broker.submit(client_key=command.client_key, instrument=command.instrument,
                                  side=command.side, quantity=command.quantity))
    assert inner.calls == []
    broker.consume_not_transported(caught.value, command)


def test_policy_selected_during_await_cannot_reach_market_transport(monkeypatch):
    inner = at_open(QuoteBroker())
    clock = inner.market_clock
    async def changed_clock():
        result = await clock()
        select(monkeypatch)
        return result
    monkeypatch.setattr(inner, "market_clock", changed_clock)
    with pytest.raises(PreTransportAuthorityRefused, match="requires immutable LIMIT/DAY"):
        asyncio.run(wrap(inner).submit(client_key="changed-policy", instrument=instrument(),
                                      side=Side.BUY, quantity=D(1)))
    assert "submit:changed-policy" not in inner.calls


@pytest.mark.parametrize("changed", [None, "cap", "unset"])
def test_changed_policy_or_cap_invalidates_signed_execution_configuration(monkeypatch, tmp_path, changed):
    select(monkeypatch)
    roots = tmp_path / "roots.json"
    roots.write_text('{"fixture":"independently observed trust-root bytes"}')
    def fresh_config():
        return authority.canonical_sha256(authority.execution_config_identity(
            paper_base_url="https://paper-api.alpaca.markets", trust_roots_path=roots))
    document = signed_fx.claims()
    document["bindings"]["execution_config_sha256"] = fresh_config()
    certificate = authority.verify_signed_certificate(signed_fx.signed(document),
        now=signed_fx.NOW, trust_roots=signed_fx.ROOTS)
    original_context = signed_fx.context(document)
    authority_validation._context_matches(certificate, original_context, rollout_phase="from")
    inner = at_open(ProtectedBroker())
    legacy = wrap(inner)
    async def current_authority(_grant, _operation):
        current = replace(original_context, bindings={
            **original_context.bindings, "execution_config_sha256": fresh_config()})
        authority_validation._context_matches(certificate, current, rollout_phase="from")
    async def funding(**kwargs):
        if changed == "cap":
            select(monkeypatch, "101")
        elif changed == "unset":
            monkeypatch.delenv("SENTINEL_PAPER_BUY_POLICY")
            monkeypatch.delenv("SENTINEL_PAPER_BUY_CAP_BPS")
    broker = GuardedExecutionBroker(inner=inner, grant=legacy.grant,
        guard=replace(legacy.guard, before_mutation=current_authority), protected_funding=funding)
    action = broker.submit(client_key="fixed-cap", instrument=instrument(), side=Side.BUY,
                           quantity=D(1), order_terms=OrderTerms(order_type="limit", limit_price=D(100)))
    if changed is None:
        assert asyncio.run(action).state is S.ACKNOWLEDGED
    else:
        with pytest.raises(PreTransportAuthorityRefused, match="runtime/configuration"):
            asyncio.run(action)
        assert inner.terms_sent == []


def test_funding_callback_cannot_be_swapped_after_adapter_certification():
    inner = SimulatedBroker()
    certify_adapter(inner, name="simulator", mode="SIMULATION")
    legacy = wrap(inner)
    async def funding(**kwargs):
        return None
    async def replacement(**kwargs):
        return None
    broker = GuardedExecutionBroker(inner=inner, grant=legacy.grant,
        guard=legacy.guard, protected_funding=funding)
    assert require_certified_adapter(broker).wrapper_kind == "generation-fenced-execution"
    broker._protected_funding = replacement
    with pytest.raises(AdapterNotCertified, match="guard configuration changed"):
        require_certified_adapter(broker)


def test_removing_selected_terms_guard_is_detected(monkeypatch):
    source = textwrap.dedent(inspect.getsource(GuardedExecutionBroker._require_selected_buy_terms))
    source = source.replace("@staticmethod\n", "")
    needle = 'if selected is not None and order_terms.order_type != "limit":'
    assert source.count(needle) == 1
    local = {}
    import sentinel.execution.guarded as guarded
    exec(compile(source.replace(needle, "if False:"), "<private-selected-buy-terms>", "exec"),
         vars(guarded), local)
    monkeypatch.setattr(GuardedExecutionBroker, "_require_selected_buy_terms",
                        staticmethod(local["_require_selected_buy_terms"]))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_selected_policy_cannot_drop_limit_terms_to_legacy_market(monkeypatch, True)


def test_removing_final_selected_terms_recheck_is_detected(monkeypatch):
    source = textwrap.dedent(inspect.getsource(GuardedExecutionBroker._prepare_submit))
    needle = "self._require_selected_buy_terms(side=side, order_terms=order_terms)"
    assert source.count(needle) == 2
    start, end = source.rsplit(needle, 1)
    local = {}
    import sentinel.execution.guarded as guarded
    exec(compile(start + "pass" + end, "<private-final-buy-policy>", "exec"),
         vars(guarded), local)
    monkeypatch.setattr(GuardedExecutionBroker, "_prepare_submit", local["_prepare_submit"])
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_policy_selected_during_await_cannot_reach_market_transport(monkeypatch)


@pytest.fixture
def grant_case(monkeypatch):
    select(monkeypatch)
    state, binding = _state(equity="2000"), _binding()
    plan = ExecutionPlan("actual-grant-plan", DECISION_SESSION, EFFECTIVE_SESSION, D(1),
        {"SEC-AAA": D(1)}, deployment_id=binding.deployment_id, broker=binding.broker,
        broker_account_id=binding.broker_account_id, takeover_epoch=binding.takeover_epoch)
    current, rollout = object(), object()
    calls = {"readiness": [], "window": [], "authorities": [], "allocation": []}
    projection = SimpleNamespace(opening_sizing={
        "shadow_equity": str(_shadow_equity(state)), "references": {}})
    monkeypatch.setattr("sentinel.handover.assert_no_legacy_path", lambda _conn: binding)
    monkeypatch.setattr(validation, "load_rollout_state", lambda _conn: rollout)
    monkeypatch.setattr(validation.feed_inputs, "require_current", lambda _conn: current)
    monkeypatch.setattr(validation.feed_inputs, "frontier", lambda _conn: DECISION_SESSION)
    monkeypatch.setattr(validation, "_state_and_plan_or_refuse", lambda _conn: (state, plan, DECISION_SESSION))
    monkeypatch.setattr(validation, "_latest_plan_or_refuse", lambda _conn: plan)
    monkeypatch.setattr(validation, "_validate_automation_grant", lambda *_: (None,
        SimpleNamespace(plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(),
                        decision_session=plan.decision_session)))
    monkeypatch.setattr(validation, "_readiness_or_refuse",
                        lambda *args, **kwargs: calls["readiness"].append(kwargs))
    monkeypatch.setattr(validation, "_execution_window_or_refuse",
                        lambda *args, **kwargs: calls["window"].append(args))
    monkeypatch.setattr(validation, "_assert_plan_authorities",
                        lambda *args, **kwargs: calls["authorities"].append(kwargs))
    monkeypatch.setattr(validation.binding_mod, "require", lambda _conn: binding)
    monkeypatch.setattr(validation.journal, "load_commands",
                        lambda *args, **kwargs: (SimpleNamespace(side=Side.BUY),))
    monkeypatch.setattr(target_reprojection, "load_projection", lambda *args, **kwargs: projection)
    monkeypatch.setattr(protected_limits, "validate_projection", lambda *args, **kwargs: None)
    monkeypatch.setattr(protected_limits.PriorCloseReferences, "from_dict",
                        classmethod(lambda cls, raw: object()))
    monkeypatch.setattr(protected_limits, "_validate_allocation",
                        lambda *args, **kwargs: calls["allocation"].append(kwargs))
    monkeypatch.setattr(structural_verification, "active", lambda: False)
    monkeypatch.setattr(dual_reconciliation, "verified_shadow_intent",
                        lambda *args, **kwargs: SimpleNamespace(state=state))
    monkeypatch.setattr(dual_plan_authority, "rederive_plan",
                        lambda *args, **kwargs: {"state_sha256": state.state_hash,
                                               "shadow_equity": str(_shadow_equity(state))})
    return SimpleNamespace(state=state, binding=binding, plan=plan, projection=projection, calls=calls)


def invoke_grant(case, kind, operation):
    if kind == "manual":
        grant = ManualExecutionGrant(case.binding.broker_account_id, case.plan.plan_id,
                                     case.plan.effective_session, True)
    else:
        grant = AutomationExecutionGrant("EXECUTE", "cycle", 1, "holder", 1,
            case.binding.broker_account_id, case.binding.takeover_epoch, "PINNED_1_00", 1, "a" * 64)
    result = (_account().identity if operation is BrokerOperation.IDENTIFY_ACCOUNT else
              _account() if operation is BrokerOperation.ACCOUNT_SNAPSHOT else None)
    options = ({"dual_shadow_observation_id": "shadow", "dual_shadow_starting_cash": D(2000)}
               if kind == "dual" else {})
    validation._validate_broker_grant(object(), grant, operation, result,
        now_provider=lambda: datetime(2026, 8, 12, 13, 31, tzinfo=timezone.utc),
        strategy_provider=lambda: case.state.strategy_identity, **options)


@pytest.mark.parametrize("kind", ["manual", "automation", "dual"])
@pytest.mark.parametrize("operation", [BrokerOperation.IDENTIFY_ACCOUNT,
                                      BrokerOperation.ACCOUNT_SNAPSHOT, BrokerOperation.SUBMIT])
def test_actual_execution_grant_branches_check_typed_operation(grant_case, kind, operation):
    invoke_grant(grant_case, kind, operation)
    assert len(grant_case.calls["readiness"]) == len(grant_case.calls["authorities"]) == 1
    assert len(grant_case.calls["allocation"]) == (operation is BrokerOperation.SUBMIT)


@pytest.mark.parametrize("kind", ["manual", "automation", "dual"])
def test_actual_submit_grant_refuses_noncanonical_allocation_denominator(grant_case, kind):
    grant_case.projection.opening_sizing["shadow_equity"] = str(_shadow_equity(grant_case.state) * 2)
    with pytest.raises(validation.PaperActivationRefused, match="canonical equity"):
        invoke_grant(grant_case, kind, BrokerOperation.SUBMIT)
    assert grant_case.calls["allocation"] == []


@pytest.mark.parametrize("kind", ["manual", "automation", "dual"])
def test_restoring_undefined_operation_defect_is_detected(grant_case, monkeypatch, kind):
    source = inspect.getsource(validation._validate_broker_grant)
    assert source.count("_operation is BrokerOperation.SUBMIT") == 2
    local = {}
    exec(compile(source.replace("_operation is BrokerOperation.SUBMIT",
                                "operation is BrokerOperation.SUBMIT"),
                 "<private-undefined-operation>", "exec"), vars(validation), local)
    monkeypatch.setattr(validation, "_validate_broker_grant", local["_validate_broker_grant"])
    with pytest.raises(NameError, match="operation"):
        test_actual_execution_grant_branches_check_typed_operation(
            grant_case, kind, BrokerOperation.IDENTIFY_ACCOUNT)


@pytest.mark.parametrize("kind", ["manual", "automation", "dual"])
def test_removing_canonical_equity_binding_is_detected(grant_case, monkeypatch, kind):
    source = inspect.getsource(validation._protected_allocation_or_refuse)
    needle = 'if Decimal(projection.opening_sizing["shadow_equity"]) != expected:'
    assert source.count(needle) == 1
    local = {}
    exec(compile(source.replace(needle, "if False:"), "<private-canonical-allocation>", "exec"),
         vars(validation), local)
    monkeypatch.setattr(validation, "_protected_allocation_or_refuse", local["_protected_allocation_or_refuse"])
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_actual_submit_grant_refuses_noncanonical_allocation_denominator(grant_case, kind)
