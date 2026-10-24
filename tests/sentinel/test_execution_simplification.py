"""Structural reuse cannot become cached financial readiness or new authority."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from fractions import Fraction
import inspect
from types import SimpleNamespace

import pytest

from sentinel import binding, local_paper, observation_authority, standing_observation_authority as standing
from sentinel.authority import (AuthorityRefused, PAPER_OBSERVATION_ONLY, PAPER_SCOPE,
    RolloutMode, canonical_sha256, execution_config_identity)
from sentinel.execution import account_status, fill_notifications
from sentinel.execution import protected_funding as funding, protected_limits as limits
from sentinel.execution import target_reprojection as units
from sentinel.execution.contract import MalformedBrokerEvidence
from sentinel.execution.contract import (BrokerAccountIdentity, BrokerAccountSnapshot,
    BrokerInstrument, BrokerObservation, BrokerOrder, Side)
from sentinel.execution.commands import Command
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.reconcile import ReconciliationResult
from sentinel.execution.states import CommandState, RuntimeState
from tests.sentinel.test_limit_day_funding import DEPLOYMENT, account, available, command
from tests.sentinel.test_limit_day_sizing import protected_case


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setenv(local_paper.MODE_ENV, local_paper.MODE)
    monkeypatch.setenv(local_paper.ACCOUNT_ENV, "PAfixture")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("SENTINEL_GIT_COMMIT", "a" * 40)
    monkeypatch.setenv("SENTINEL_IMAGE_SOURCE_REVISION", "a" * 40)
    monkeypatch.setenv("SENTINEL_RUNTIME_IMAGE_DIGEST", "sha256:" + "b" * 64)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", limits.PROTECTED_MODE)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", "100")
    monkeypatch.delenv("SENTINEL_PAPER_DEBUG_WINDOW", raising=False)
    value = binding.AccountBinding(deployment_id="local", broker="alpaca",
        broker_account_id="PAfixture", takeover_epoch=1)
    calls = []
    monkeypatch.setattr(binding, "require", lambda conn: calls.append(conn) or value)
    return value, calls


def runtime():
    return {"deployment_artifacts": {"schema": "sentinel.runtime-artifacts/1",
        "git_commit": "a" * 40, "runtime_image_digest": "sha256:" + "b" * 64,
        "test_image_digest": "sha256:" + "b" * 64}}


def policy_hash():
    return canonical_sha256(execution_config_identity(
        paper_base_url="https://paper-api.alpaca.markets"))


def test_boolean_binding_guard_stays_boolean_and_binding_helper_returns_checked_fact(local):
    owner, calls = local
    conn = object()
    assert local_paper.require_bound_account(conn) is True
    assert local_paper.bound_account(conn) is owner
    assert calls == [conn, conn]


@pytest.mark.parametrize("read", [account_status._bound, fill_notifications._binding])
def test_display_and_notification_readers_use_one_fresh_binding_each(local, read):
    owner, calls = local
    conn = object()
    expected = (owner.deployment_id, owner.broker, owner.broker_account_id, owner.takeover_epoch)
    assert read(conn) == expected
    assert read(conn) == expected
    assert calls == [conn, conn]


def test_combined_guard_loads_own_binding_and_never_reuses_a_prior_result(local, monkeypatch):
    owner, calls = local
    conn = object()
    options = dict(runtime_identity=runtime(), configuration_sha256=policy_hash())
    assert local_paper.runtime_and_execution_config(conn, **options) is owner
    assert calls == [conn]
    monkeypatch.setattr(binding, "require", lambda conn: replace(owner, broker_account_id="PAforeign"))
    with pytest.raises(RuntimeError, match="durable binding"):
        local_paper.runtime_and_execution_config(conn, **options)
    # Supplying a previously checked binding cannot bypass a fresh read.
    with pytest.raises(TypeError):
        local_paper.runtime_and_execution_config(conn, bound=owner, **options)


@pytest.mark.parametrize("damage,match", [("image", "actual local commit"),
                                        ("config", "differs from actual policy")])
def test_combined_guard_retains_runtime_and_policy_refusals(local, monkeypatch, damage, match):
    identity, config = runtime(), policy_hash()
    if damage == "image":
        monkeypatch.setenv("SENTINEL_IMAGE_SOURCE_REVISION", "c" * 40)
    else:
        config = "0" * 64
    with pytest.raises(RuntimeError, match=match):
        local_paper.runtime_and_execution_config(object(), runtime_identity=identity,
            configuration_sha256=config)


def test_disabled_mode_never_reads_a_binding_or_grants_mandatory_authority(monkeypatch):
    monkeypatch.delenv(local_paper.MODE_ENV, raising=False)
    monkeypatch.setattr(binding, "require", lambda conn: pytest.fail("disabled local binding read"))
    assert local_paper.bound_account(object()) is None
    assert local_paper.require_bound_account(object()) is False
    assert local_paper.runtime_and_execution_config(object(),
        runtime_identity={}, configuration_sha256="0" * 64) is None
    with pytest.raises(RuntimeError, match="not authorized"):
        local_paper.require_runtime(object(), {})


def test_standing_local_authority_reads_once_without_changing_subject_failure_priority(local, monkeypatch):
    owner, calls = local
    strategy = {"strategy": "fixture"}
    subject = dict(deployment_id=owner.deployment_id, broker=owner.broker,
        broker_account_id=owner.broker_account_id, takeover_epoch=owner.takeover_epoch,
        environment=PAPER_SCOPE, paper_base_url="https://paper-api.alpaca.markets")
    document = SimpleNamespace(authorization_mode=PAPER_OBSERVATION_ONLY,
        allows=lambda mode: mode is RolloutMode.CONTROLLER,
        subject=subject, certificate_sha256="c" * 64, unattended_automation=True,
        rollout={"to_mode": "CONTROLLER", "to_version": 1},
        claims={"permitted_operations": ["AUTOMATION"], "bindings": {
            "strategy_identity_sha256": canonical_sha256(strategy),
            "publication_policy": {"implementation_sha256": "a", "chain_root_sha256": "b"},
            "current_corpus": {"data_version": 1},
            "current_metadata_snapshot": {"snapshot_date": "2026-10-22"}}})
    monkeypatch.setattr(standing, "load_active_signed_certificate", lambda *args, **kwargs: document)
    monkeypatch.setattr(standing, "load_rollout_state", lambda conn: SimpleNamespace(
        mode=RolloutMode.CONTROLLER, certificate_sha256=document.certificate_sha256, version=1))
    monkeypatch.setattr(observation_authority, "current_metadata_snapshot_identity", lambda conn:
        {"snapshot_date": "2026-10-23"})
    conn = object()
    options = dict(runtime_identity=runtime(), strategy_identity=strategy,
        required_mode=RolloutMode.CONTROLLER, required_operation="AUTOMATION",
        execution_config_sha256=policy_hash(), publication_policy_implementation_sha256="a",
        publication_chain_root_sha256="b", current_publication_version=6)
    assert standing.require_standing_observation_authority(conn, **options) is document
    assert calls == [conn]
    document.subject = dict(subject, broker_account_id="PAforeign")
    monkeypatch.setenv("SENTINEL_IMAGE_SOURCE_REVISION", "c" * 40)
    with pytest.raises(AuthorityRefused, match="subject does not match"):
        standing.require_standing_observation_authority(conn, **options)
    assert calls == [conn, conn]


@pytest.mark.parametrize("changes,error,message", [
    ({"status": "ACCOUNT_CLOSED"}, funding.ProtectedFundingNotReady, "unavailable"),
    ({"trading_blocked": True}, funding.ProtectedFundingNotReady, "unavailable"),
    ({"buying_power": D("1001.01")}, funding.ProtectedFundingRefused, "margin"),
    ({"buying_power": None}, MalformedBrokerEvidence, "unusable"),
    ({"multiplier": D(2)}, MalformedBrokerEvidence, "unusable"),
    ({"trading_blocked": "false"}, MalformedBrokerEvidence, "malformed"),
])
def test_shared_account_checks_keep_refusal_classification(changes, error, message):
    snapshot = replace(account(), **changes)
    candidate = command()
    with pytest.raises(error, match=message):
        funding.available_for_purchase(basis_cash=D(1000), account=snapshot,
            commands=(candidate,), candidate=candidate, deployment=DEPLOYMENT, plan_id="p")
    with pytest.raises(error, match=message):
        funding._assert_funding_account(basis=object(), account=snapshot,
            deployment=DEPLOYMENT, activity_state=None, broker=None)


def test_equity_requirement_stays_specific_to_continuation_and_margin_tolerance_is_exact():
    funding._assert_available_account(replace(account(), equity=D(0)), DEPLOYMENT)
    with pytest.raises(funding.ProtectedFundingRefused, match="equity"):
        funding._assert_available_account(replace(account(), equity=D(0)), DEPLOYMENT,
            require_equity=True)
    assert available(command(), bp="1001") == D(1000)


@pytest.mark.parametrize("error,message", [
    (funding.ProtectedFundingRefused, "native cash activity changed or is incomplete after the funding basis"),
    (funding.ProtectedFundingNotReady, "native cash-activity evidence changed or is incomplete"),
])
def test_shared_evidence_keeps_boundary_specific_exception_and_message(error, message):
    basis = SimpleNamespace(observed_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
        cash_activity_sha256="not-the-current-identity")
    for activity in (None, SimpleNamespace(processed_through=basis.observed_at - timedelta(seconds=1))):
        with pytest.raises(error) as rejected:
            funding._assert_current_evidence(basis=basis, account=account(),
                activity_state=activity, composition=None, activity_error=error,
                activity_message=message)
        assert type(rejected.value) is error
        assert str(rejected.value) == message


def protected(monkeypatch):
    state, plan, projection, references = protected_case()
    policy = limits.ProtectedLimitPolicy(100)
    projection = limits.resolve_protected(state, plan, projection, references, policy)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", limits.PROTECTED_MODE)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", "100")
    monkeypatch.delenv("SENTINEL_PAPER_DEBUG_WINDOW", raising=False)
    monkeypatch.setattr(limits, "build_references", lambda *args, **kwargs: references)
    return plan, projection, references


@pytest.mark.parametrize("operation", ["references", "allocation", "submission", "terms"])
def test_each_public_operation_independently_verifies_the_basket_once(monkeypatch, operation):
    plan, projection, references = protected(monkeypatch)
    calls = []
    original = limits._validate_allocation
    def independent(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(limits, "_validate_allocation", independent)
    monkeypatch.setattr(limits, "resolve_protected", lambda *args, **kwargs:
        pytest.fail("the allocation verifier reused its constructor"))
    if operation == "references":
        assert limits.revalidate_references(object(), plan=plan, projection=projection) == references
    elif operation == "allocation":
        limits.validate_allocation(projection, plan=plan,
            canonical_shadow_equity=D(projection.opening_sizing["shadow_equity"]))
    elif operation == "submission":
        actual, terms = limits.submission_protection(object(), plan=plan,
            projection=projection)
        assert actual == references and terms.for_security("SEC-AAA").limit_price > 0
    else:
        assert limits.order_terms_for(projection, "SEC-AAA").limit_price > 0
    assert len(calls) == 1


def test_submission_results_are_not_a_cache_for_next_source_or_projection_check(monkeypatch):
    plan, projection, references = protected(monkeypatch)
    options = dict(plan=plan, projection=projection)
    limits.submission_protection(object(), **options)
    monkeypatch.setattr(limits, "build_references", lambda *args, **kwargs:
        replace(references, prices={**references.prices, "SEC-AAA": D(101)}))
    with pytest.raises(units.TargetProjectionRefused, match="source references changed"):
        limits.submission_protection(object(), **options)
    evidence = deepcopy(projection.opening_sizing)
    evidence["limits"]["SEC-AAA"] = "10000"
    with pytest.raises(units.TargetProjectionRefused, match="allocation is inconsistent"):
        limits.submission_protection(object(), **dict(options,
            projection=replace(projection, opening_sizing=evidence)))


def test_detached_terms_are_immutable_facts_and_each_new_operation_checks_policy(monkeypatch):
    plan, projection, _ = protected(monkeypatch)
    _, terms = limits.submission_protection(object(), plan=plan, projection=projection)
    with pytest.raises(TypeError):
        terms.limits["SEC-AAA"] = terms.for_security("SEC-AAA")
    monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", "99")
    with pytest.raises(units.TargetProjectionRefused, match="current configuration"):
        limits.order_terms(projection)
    with pytest.raises(TypeError):
        limits.submission_protection(object(), plan=plan, projection=projection,
            validated_terms=terms)


def _prove_two_legs(monkeypatch):
    plan, projection, _ = protected(monkeypatch)
    owner = DeploymentIdentity(plan.deployment_id, plan.broker, plan.broker_account_id, plan.takeover_epoch)
    observed_at = datetime.combine(plan.effective_session, datetime.min.time(), timezone.utc).replace(hour=13, minute=32)
    terms = limits.order_terms(projection)
    first, second = plan.opening_intents[:2]
    def leg(intent, state):
        instrument = BrokerInstrument(intent.security_id, intent.security_id.removeprefix("SEC-"),
            "native-" + intent.security_id)
        return Command(CommandIdentity(owner, plan.plan_id, intent.security_id), instrument,
            Side.BUY, projection.target_basket[intent.security_id], state=state,
            broker_order_id="working-order" if state is CommandState.ACKNOWLEDGED else None,
            order_terms=terms.for_security(intent.security_id))
    acknowledged, planned = leg(first, CommandState.ACKNOWLEDGED), leg(second, CommandState.PLANNED)
    account = BrokerAccountSnapshot(BrokerAccountIdentity(owner.broker, owner.broker_account_id),
        D(100000), D(100000), buying_power=D(90000), multiplier=D(1), status="ACTIVE")
    basis = funding.PlanCashFundingBasis(deployment=funding._deployment(owner), plan_id=plan.plan_id,
        plan_fingerprint=plan.fingerprint(), projection_fingerprint=projection.fingerprint(),
        policy_sha256=limits.ProtectedLimitPolicy(100).fingerprint(), effective_session=plan.effective_session,
        paper_base_url="https://paper-api.alpaca.markets", observed_at=observed_at-timedelta(minutes=1),
        observation_id=1, observation_sha256="a"*64, cash="100000", buying_power="100000",
        broker_composition_sha256="c"*64, plan_cash_ceiling="100000")
    order = BrokerOrder(acknowledged.broker_order_id, acknowledged.client_key, acknowledged.instrument,
        Side.BUY, CommandState.ACKNOWLEDGED, acknowledged.quantity, order_terms=acknowledged.order_terms)
    observation = BrokerObservation(observed_at, orders=(order,), account_identity=account.identity)
    reconciliation = ReconciliationResult(RuntimeState.RUNNING, observation=observation, observation_id=2)
    monkeypatch.setattr(funding, "_require_writer", lambda conn: None)
    monkeypatch.setattr(funding, "load_basis", lambda *args, **kwargs: basis)
    monkeypatch.setattr(funding.journal, "latest_plan", lambda conn: plan)
    monkeypatch.setattr(funding.journal, "load_commands", lambda *args, **kwargs: [acknowledged, planned])
    monkeypatch.setattr(funding, "_plan_cash_composition", lambda broker: "c"*64)
    # Durable row identity has separate PostgreSQL coverage. This case counts
    # the continuation operation's own allocation verification, not that gate.
    monkeypatch.setattr(funding.target_reprojection, "assert_projection", lambda *args, **kwargs: None)
    calls = []
    original = limits._validate_allocation
    def independent(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(limits, "_validate_allocation", independent)
    result = funding.prove_cohort_continuation(object(), plan=plan, projection=projection,
        deployment=owner, reconciliation=reconciliation, account=account, activity_state=None,
        broker=object(), paper_base_url=basis.paper_base_url, evaluated_at=observed_at)
    assert len(result.commands) == 1
    assert len(calls) == 1


def test_two_eligible_cohort_commands_verify_basket_once(monkeypatch):
    _prove_two_legs(monkeypatch)


def test_repeated_cohort_basket_work_falsifier_is_detected(monkeypatch):
    source = inspect.getsource(funding.prove_cohort_continuation)
    needle = "if protected_terms is None:"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, "if True:"), "repeated-cohort-verification", "exec"),
         vars(funding), namespace)
    monkeypatch.setattr(funding, "prove_cohort_continuation", namespace["prove_cohort_continuation"])
    with pytest.raises(AssertionError):
        _prove_two_legs(monkeypatch)


def test_plan_and_canonical_equity_mismatches_remain_refusals(monkeypatch):
    plan, projection, _ = protected(monkeypatch)
    with pytest.raises(units.TargetProjectionRefused, match="allocation is inconsistent"):
        limits.validate_allocation(projection, plan=replace(plan, account_nav=plan.account_nav + 1),
            canonical_shadow_equity=D(projection.opening_sizing["shadow_equity"]) + 1)
    with pytest.raises(units.TargetProjectionRefused, match="canonical shadow equity"):
        limits.validate_allocation(projection, plan=plan,
            canonical_shadow_equity=D(projection.opening_sizing["shadow_equity"]) + 1)


def test_public_share_factor_preserves_exact_rational_and_authenticated_source_identity():
    evidence = dict(security_id="SEC", source_row_id="split-30", canonical_multiplier="0.03333333333333333",
        value="0.03333333333333333", canonical_numerator="1", canonical_denominator="30")
    options = dict(security_id="SEC", multiplier=D(evidence["value"]), evidence=(evidence,))
    assert units.share_action_factor(**options) == Fraction(1, 30)
    with pytest.raises(units.TargetProjectionRefused, match="source identity"):
        units.share_action_factor(**dict(options, evidence=({**evidence, "source_row_id": None},)))
    with pytest.raises(units.TargetProjectionRefused, match="differs from projection"):
        units.share_action_factor(**dict(options, multiplier=D(2)))
    with pytest.raises(units.TargetProjectionRefused, match="durable action evidence"):
        units.share_action_factor(security_id="SEC", multiplier=D(2), evidence=())
