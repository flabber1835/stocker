"""A stale endpoint, partial fill, or crash never creates another cash dollar."""
import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import inspect
import json
from types import SimpleNamespace

import pytest

from sentinel.execution import protected_funding as funding
from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerAccountSnapshot, CommandOutcome, OrderTerms, Side)
from sentinel.execution.guarded import GuardedExecutionBroker, PreTransportAuthorityRefused
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import CommandState as S
from sentinel.feed import calendar
from tests.sentinel.test_opening_submit_freshness_boundary import ClockedBroker, instrument, wrap


DEPLOYMENT = DeploymentIdentity("protected-test", "sim", "SIM-ACCOUNT", 1)


def account(cash="1000", bp=None):
    return BrokerAccountSnapshot(
        BrokerAccountIdentity("sim", "SIM-ACCOUNT"), D(cash), D(cash),
        buying_power=D(cash if bp is None else bp), multiplier=D(1), status="ACTIVE")


def command(name="a", *, price="99", quantity="1", state=S.SEND_PENDING, plan="p"):
    return Command(CommandIdentity(DEPLOYMENT, plan, "SEC-" + name),
        replace(instrument(), security_id="SEC-" + name), Side.BUY, D(quantity),
        state=state, order_terms=OrderTerms(order_type="limit", limit_price=D(price)))


def available(candidate, others=(), *, cash="1000", bp=None, basis="1000", implementation=None,
              deployment=DEPLOYMENT):
    return (implementation or funding.available_for_purchase)(
        basis_cash=D(basis), account=account(cash, bp), commands=(*others, candidate),
        candidate=candidate, deployment=deployment, plan_id="p")


def test_stale_native_buying_power_cannot_fund_second_overcommitted_buy():
    first, second = command("a"), command("b")
    with pytest.raises(funding.ProtectedFundingNotReady):
        available(second, (first,), cash="150", bp="150", basis="150")


def test_broker_hold_is_not_subtracted_twice_from_buying_power():
    first, second = command("a", price="399", state=S.ACKNOWLEDGED), command("b", price="599")
    assert available(second, (first,), bp="600") == D("600")


@pytest.mark.parametrize("state", [S.SEND_PENDING, S.UNKNOWN, S.CANCEL_PENDING,
                                  S.ACKNOWLEDGED, S.PARTIALLY_FILLED, S.PLANNED])
def test_every_potentially_live_promise_keeps_its_allowance(state):
    first = command("a", price="29", state=state)
    second = command("b", price="59")
    with pytest.raises(funding.ProtectedFundingNotReady):
        available(second, (first,), cash="70", bp="70", basis="100")


def test_reconciled_fill_removes_live_hold_but_never_recycles_its_savings():
    first = replace(command("a", price="399", state=S.FILLED),
                    filled_quantity=D(1), filled_average_price=D("350"))
    assert available(command("b", price="599"), (first,), cash="650") == D("600")
    with pytest.raises(funding.ProtectedFundingNotReady):
        available(command("b", price="600"), (first,), cash="650")


@pytest.mark.parametrize("state", [S.CANCELLED, S.REJECTED])
def test_terminal_unused_allowance_is_not_recycled_within_the_plan(state):
    with pytest.raises(funding.ProtectedFundingNotReady):
        available(command("b", price="699"), (command("a", price="399", state=state),))


def test_partial_fill_and_lagging_cash_do_not_release_original_ceiling():
    first = replace(command("a", price="10", quantity="10", state=S.PARTIALLY_FILLED),
                    filled_quantity=D(4), filled_average_price=D(8))
    with pytest.raises(funding.ProtectedFundingNotReady):
        available(command("b", price="99"), (first,), cash="200", basis="200")


def test_proven_unsent_supersession_releases_only_that_untransported_allowance():
    assert available(command("b", price="999"),
                     (command("a", state=S.SUPERSEDED),)) == D(1000)


def test_other_plan_unknown_cannot_be_filtered_out_of_funding():
    with pytest.raises(funding.ProtectedFundingNotReady, match="another plan"):
        available(command("b"), (command("a", state=S.UNKNOWN, plan="old"),))


@pytest.mark.parametrize("state", [S.FILLED, S.CANCELLED, S.REJECTED, S.SUPERSEDED])
def test_prior_epoch_terminal_other_plan_does_not_block_new_quiescent_cohort(state):
    current = replace(DEPLOYMENT, takeover_epoch=2)
    candidate = command("b")
    candidate = replace(candidate, identity=replace(candidate.identity, deployment=current))
    old = replace(command("a", plan="old", state=state), order_terms=OrderTerms())
    if state is S.FILLED:
        old = replace(old, filled_quantity=old.quantity, filled_average_price=D(99))
    assert available(candidate, (old,), deployment=current) == D(1000)


def test_prior_epoch_unknown_blocks_and_current_plan_epoch_must_be_exact():
    current = replace(DEPLOYMENT, takeover_epoch=2)
    candidate = command("b")
    candidate = replace(candidate, identity=replace(candidate.identity, deployment=current))
    with pytest.raises(funding.ProtectedFundingNotReady, match="another plan"):
        available(candidate, (command("a", plan="old", state=S.UNKNOWN),), deployment=current)
    with pytest.raises(funding.ProtectedFundingRefused, match="takeover epoch"):
        available(candidate, (command("a", state=S.FILLED),), deployment=current)


@pytest.mark.parametrize("owner", [replace(DEPLOYMENT, takeover_epoch=3),
                                  replace(DEPLOYMENT, broker_account_id="OTHER")])
def test_future_or_other_account_history_is_never_ignored(owner):
    prior = command("a", plan="old", state=S.SUPERSEDED)
    prior = replace(prior, identity=replace(prior.identity, deployment=owner))
    with pytest.raises(funding.ProtectedFundingRefused, match="another deployment"):
        available(command("b"), (prior,))


def test_unbounded_legacy_buy_and_fill_above_limit_refuse():
    for prior in (replace(command("a"), order_terms=OrderTerms()),
                  replace(command("a"), filled_quantity=D(1), filled_average_price=D(100))):
        with pytest.raises(funding.ProtectedFundingRefused):
            available(command("b"), (prior,))
    with pytest.raises(funding.ProtectedFundingRefused, match="whole-share"):
        available(command(quantity="0.5"))


def test_funding_requires_exact_durable_candidate_and_subject():
    candidate = command()
    with pytest.raises(funding.ProtectedFundingRefused, match="durably reserved"):
        funding.available_for_purchase(basis_cash=D(1000), account=account(), commands=(),
            candidate=candidate, deployment=DEPLOYMENT, plan_id="p")
    with pytest.raises(funding.ProtectedFundingRefused, match="subject"):
        funding.available_for_purchase(basis_cash=D(1000),
            account=replace(account(), identity=BrokerAccountIdentity("sim", "other")),
            commands=(candidate,), candidate=candidate, deployment=DEPLOYMENT, plan_id="p")


@pytest.mark.parametrize("guard", ["gross", "live"])
def test_removing_either_monetary_ceiling_is_detected(guard):
    source = inspect.getsource(funding.available_for_purchase)
    if guard == "gross":
        before = "ceiling = max(Fraction(0), Fraction(basis_cash) - other)"
        after = "ceiling = Fraction(basis_cash)"
        prior = replace(command("a", price="99", state=S.FILLED),
                        filled_quantity=D(1), filled_average_price=D("99"))
        kwargs = dict(cash="150", basis="150")  # Deliberately lagging cash endpoint.
    else:
        before = "Fraction(account.cash) - live_other"
        after = "Fraction(account.cash)"
        prior = command("a", price="29", state=S.UNKNOWN)
        kwargs = dict(cash="70", basis="100")
    mutated = source.replace(before, after)
    assert mutated != source
    namespace = dict(vars(funding))
    exec(mutated, namespace)
    candidate = command("b", price="99" if guard == "gross" else "59")
    with pytest.raises(funding.ProtectedFundingNotReady):
        available(candidate, (prior,), **kwargs)
    assert available(candidate, (prior,), implementation=namespace["available_for_purchase"], **kwargs) > 0


class ProtectedBroker(ClockedBroker):
    def __init__(self):
        super().__init__()
        self.capabilities = replace(self.capabilities, protected_limit_day=True,
                                    regular_session_quote_prices=True)
        self.terms_sent = []

    async def opening_prices(self, **kwargs):
        raise AssertionError("protected BUY must not request quotes")

    async def submit(self, *, client_key, instrument, side, quantity, order_terms=OrderTerms()):
        self.calls.append("submit:" + client_key)
        self.terms_sent.append(order_terms)
        return CommandOutcome(S.ACKNOWLEDGED, "protected-order")


def membrane(inner, funding_callback):
    legacy = wrap(inner)
    return GuardedExecutionBroker(inner=inner, grant=legacy.grant,
        guard=legacy.guard, protected_funding=funding_callback)


def test_protected_membrane_preserves_terms_without_quote_get():
    inner = ProtectedBroker()
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened + timedelta(seconds=61)
    terms = OrderTerms(order_type="limit", limit_price=D(100))
    seen = []
    async def validate(**kwargs):
        seen.append(kwargs)
    result = asyncio.run(membrane(inner, validate).submit(client_key="protected",
        instrument=instrument(), side=Side.BUY, quantity=D(1), order_terms=terms))
    assert result.state is S.ACKNOWLEDGED and inner.terms_sent == [terms]
    assert seen[0]["order_terms"] == terms and seen[0]["account"].identity.account_id == "SIM-ACCOUNT"


@pytest.mark.parametrize("seconds", [59, 600, 601])
def test_protected_buys_keep_both_schedule_edges(seconds):
    inner = ProtectedBroker()
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened + timedelta(seconds=seconds)
    async def validate(**kwargs):
        return None
    with pytest.raises(PreTransportAuthorityRefused, match="freshness"):
        asyncio.run(membrane(inner, validate).submit(client_key="late",
            instrument=instrument(), side=Side.BUY, quantity=D(1),
            order_terms=OrderTerms(order_type="limit", limit_price=D(100))))
    assert not inner.terms_sent




def test_protected_unsent_proof_is_single_use_and_bound_to_exact_terms():
    from sentinel.execution.guarded import OrderEvidenceNotReady
    inner = ProtectedBroker()
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened + timedelta(seconds=61)
    pending = Command(CommandIdentity(DEPLOYMENT, "p", instrument().security_id),
        instrument(), Side.BUY, D(1), state=S.SEND_PENDING,
        order_terms=OrderTerms(order_type="limit", limit_price=D(100)))
    async def unavailable(**kwargs):
        raise funding.ProtectedFundingNotReady("native allowance is not ready")
    broker = membrane(inner, unavailable)
    def attempt():
        with pytest.raises(OrderEvidenceNotReady) as caught:
            asyncio.run(broker.submit(client_key=pending.client_key, instrument=pending.instrument,
                side=pending.side, quantity=pending.quantity, order_terms=pending.order_terms))
        return caught.value
    first = attempt()
    with pytest.raises(ValueError, match="matching unused"):
        broker.consume_not_transported(first,
            replace(pending, order_terms=replace(pending.order_terms, limit_price=D(101))))
    second = attempt()
    broker.consume_not_transported(second, pending)
    with pytest.raises(ValueError, match="matching unused"):
        broker.consume_not_transported(second, pending)
    assert inner.terms_sent == []


def test_protected_funding_wait_cannot_cross_final_submission_cutoff():
    inner = ProtectedBroker()
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened + timedelta(seconds=599)
    async def delayed(**kwargs):
        inner.now = opened + timedelta(seconds=600)
    with pytest.raises(PreTransportAuthorityRefused, match="freshness"):
        asyncio.run(membrane(inner, delayed).submit(client_key="cutoff",
            instrument=instrument(), side=Side.BUY, quantity=D(1),
            order_terms=OrderTerms(order_type="limit", limit_price=D(100))))
    assert inner.terms_sent == []



def test_canonical_callback_retries_fresh_native_cash_without_quote_fallback(monkeypatch):
    from sentinel import structural_verification
    from sentinel.execution import protected_funding
    from sentinel.execution.guarded import OrderEvidenceNotReady
    from sentinel.paper import cash, inspection, validation
    from sentinel.paper.model import PaperRetryableRefused
    inner = ProtectedBroker()
    opened, _ = calendar.session_window(inner.now.date())
    inner.now = opened + timedelta(seconds=61)
    legacy = wrap(inner)
    connection = object()
    owner = SimpleNamespace(identity=DEPLOYMENT)
    # Isolate composition authority; exercise the actual canonical cash callback.
    monkeypatch.setattr(structural_verification, "owned", lambda _conn: None)
    monkeypatch.setattr(structural_verification, "Scope", lambda _conn: object())
    monkeypatch.setattr(validation, "_fresh_connection_factory", lambda _conn: None)
    monkeypatch.setattr(validation, "build_fresh_execution_guard", lambda **kwargs: legacy.guard)
    monkeypatch.setattr(inspection, "_require_certified_paper_broker", lambda _broker: None)
    monkeypatch.setattr(validation.binding_mod, "require", lambda _conn: owner)
    attempts, proofs = [], []
    activity = object()
    async def fresh_cash(conn, **kwargs):
        assert conn is connection and kwargs["through"] == inner.now
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise PaperRetryableRefused("temporary native cash GET outage")
        return activity
    monkeypatch.setattr(cash, "_broker_cash_state_or_refuse", fresh_cash)
    monkeypatch.setattr(protected_funding, "validate_submission",
        lambda conn, **kwargs: proofs.append((conn, kwargs)))
    broker = validation._guard_broker(conn=connection, broker=inner, grant=legacy.grant,
        base_url="https://paper-api.alpaca.markets",
        now_provider=lambda: inner.now, strategy_provider=lambda: {})
    kwargs = dict(client_key="cash-retry", instrument=instrument(), side=Side.BUY,
        quantity=D(1), order_terms=OrderTerms(order_type="limit", limit_price=D(100)))
    with pytest.raises(OrderEvidenceNotReady, match="native cash GET outage"):
        asyncio.run(broker.submit(**kwargs))
    assert inner.terms_sent == [] and proofs == []
    assert asyncio.run(broker.submit(**kwargs)).state is S.ACKNOWLEDGED
    assert len(attempts) == 2 and all(item["broker"] is broker for item in attempts)
    assert len(proofs) == 1 and proofs[0][1]["activity_state"] is activity

NOW = datetime(2026, 10, 19, 13, 31, tzinfo=timezone.utc)


def funding_basis(**changes):
    fields = dict(deployment=funding._deployment(DEPLOYMENT), plan_id="p",
        plan_fingerprint="a" * 64, projection_fingerprint="b" * 64,
        policy_sha256="c" * 64, effective_session=NOW.date(),
        paper_base_url="https://paper-api.alpaca.markets", observed_at=NOW,
        observation_id=1, observation_sha256="d" * 64,
        cash_activity_sha256="e" * 64, cash=D("1000.00"), buying_power=D("1000.00"))
    return funding.FundingBasis(**{**fields, **changes})


def test_funding_basis_json_roundtrip_preserves_exact_ownership_and_decimal_cash():
    original = funding_basis()
    raw = json.loads(original.model_dump_json())
    assert raw["deployment"] == list(funding._deployment(DEPLOYMENT))
    assert raw["cash"] == "1000.00" and raw["observed_at"].endswith("Z")
    assert funding.FundingBasis.model_validate(raw) == original
    for changed in ({"cash": 1000.0}, {"buying_power": "NaN"},
                    {"multiplier": "2"}, {"deployment": [*raw["deployment"][:3], True]},
                    {"observation_id": False}, {"extra": "unreviewed"}):
        with pytest.raises((ValueError, TypeError, ArithmeticError)):
            funding.FundingBasis.model_validate({**raw, **changed})


def _store_basis(conn, basis):
    payload = basis.model_dump(mode="json")
    payload["funding_sha256"] = funding._sha(payload)
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state)"
                 " VALUES (%s,%s,%s::jsonb)",
                 (funding.PREFIX + basis.plan_id, basis.effective_session, json.dumps(payload)))
    conn.commit()


@pytest.fixture
def funding_case(conn, monkeypatch):
    """Real rows/lock; isolate only the separately tested publication proof."""
    from sentinel import binding
    from sentinel.execution import broker_cash, journal, protected_limits, target_reprojection
    from sentinel.execution.plan import ExecutionPlan

    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", protected_limits.PROTECTED_MODE)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", "100")
    owner = binding.bind(conn, deployment_id=DEPLOYMENT.deployment_id,
        broker=DEPLOYMENT.broker, broker_account_id=DEPLOYMENT.broker_account_id)
    candidate = command()
    plan = ExecutionPlan(plan_id="p", decision_session=date(2026, 10, 16),
        effective_session=NOW.date(), target_exposure=D(1), target_basket={candidate.security_id: D(1)},
        deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
        broker_account_id=DEPLOYMENT.broker_account_id, takeover_epoch=1,
        account_nav=D(1000), account_cash=D(1000))
    journal.save_plan(conn, plan)
    projection = target_reprojection.TargetProjection(plan.plan_id, plan.fingerprint(),
        plan.effective_session, {}, (), {}, plan.target_basket)
    target_reprojection.record_projection(conn, projection)
    policy = protected_limits.ProtectedLimitPolicy.from_env()
    activity = broker_cash.CashActivityState("sim", "SIM-ACCOUNT", NOW, "native-ref-1",
        D(1000), "native-event-1", "fixture-cash-ref/v1")
    basis = funding_basis(plan_fingerprint=plan.fingerprint(),
        projection_fingerprint=projection.fingerprint(), policy_sha256=policy.fingerprint(),
        cash_activity_sha256=funding._sha(funding._activity_identity(activity)))
    _store_basis(conn, basis)
    journal.save_command(conn, candidate)
    proof_calls = []
    references = SimpleNamespace(source_provider="ALPACA_OPENFIGI",
        symbols={candidate.security_id: candidate.instrument.symbol},
        provider_asset_ids={candidate.security_id: candidate.instrument.broker_id})
    def fresh_references(connection, **kwargs):
        proof_calls.append((connection, kwargs))
        return references
    monkeypatch.setattr(protected_limits, "revalidate_references", fresh_references)
    monkeypatch.setattr(protected_limits, "order_terms_for", lambda _projection, _sid: candidate.order_terms)
    return SimpleNamespace(owner=owner, candidate=candidate, plan=plan, projection=projection,
                           activity=activity, basis=basis, proof_calls=proof_calls, references=references)


def test_funding_basis_persisted_json_roundtrip_and_tamper_refusal(conn, funding_case):
    assert funding.load_basis(conn, plan_id="p") == funding_case.basis
    conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{cash}','\"2000\"'::jsonb)"
                 " WHERE cursor_name=%s", (funding.PREFIX + "p",))
    conn.commit()
    with pytest.raises(funding.ProtectedFundingRefused, match="corrupt"):
        funding.load_basis(conn, plan_id="p")


@pytest.mark.parametrize("damage", [None, "writer", "quantity", "instrument", "terms", "planned",
                                    "activity-id", "activity-scheme", "activity-balance", "activity-stale",
                                    "source-symbol", "source-asset"])
def test_canonical_submission_rechecks_committed_rows_activity_and_writer(conn, funding_case, damage):
    from sentinel.execution import journal
    case = funding_case
    kwargs = dict(client_key=case.candidate.client_key, instrument=case.candidate.instrument,
        quantity=case.candidate.quantity, order_terms=case.candidate.order_terms,
        account=account(), activity_state=case.activity)
    if damage == "quantity": kwargs["quantity"] = D(2)
    if damage == "instrument": kwargs["instrument"] = replace(case.candidate.instrument, broker_id="wrong")
    if damage == "terms": kwargs["order_terms"] = replace(case.candidate.order_terms, limit_price=D(100))
    if damage == "planned":
        journal.save_command(conn, replace(case.candidate, state=S.PLANNED), previous=S.SEND_PENDING)
    if damage == "source-symbol": case.references.symbols[case.candidate.security_id] = "OTHER"
    if damage == "source-asset": case.references.provider_asset_ids[case.candidate.security_id] = "other-native"
    activity_changes = {"activity-id": {"last_activity_id": "native-ref-2"},
        "activity-scheme": {"activity_identity_scheme": "different-scheme"},
        "activity-balance": {"balance_total": D(999)},
        "activity-stale": {"processed_through": NOW - timedelta(seconds=1)}}
    if damage in activity_changes:
        kwargs["activity_state"] = replace(case.activity, **activity_changes[damage])
    if damage == "writer":
        with pytest.raises(funding.ProtectedFundingRefused, match="writer lock"):
            funding.validate_submission(conn, **kwargs)
        return
    with journal.writer_lock(conn, recovery_only=True):
        if damage is None:
            assert funding.validate_submission(conn, **kwargs) is None
            assert len(case.proof_calls) == 1
        else:
            with pytest.raises(funding.ProtectedFundingRefused):
                funding.validate_submission(conn, **kwargs)


# Reuse the canonical disposable PostgreSQL fixture only for the last cases.


@pytest.mark.parametrize("guard,damage,needle,replacement", [
    ("writer", "writer", "_require_writer(conn)", "pass"),
    ("activity", "activity-id", "if (activity_state is None or activity_state.processed_through < basis.observed_at\n"
     "            or _sha(_activity_identity(activity_state)) != basis.cash_activity_sha256):", "if False:"),
    ("source-symbol", "source-symbol",
     "if references.symbols.get(instrument.security_id) != instrument.symbol:", "if False:"),
    ("source-asset", "source-asset",
     'if (references.source_provider == "ALPACA_OPENFIGI"', "if (False"),
    ("quantity", "quantity", "candidate.quantity != quantity", "False"),
    ("terms", "terms", "candidate.order_terms != order_terms", "False"),
])
def test_removing_canonical_funding_guard_is_detected(
        conn, funding_case, monkeypatch, guard, damage, needle, replacement):
    # Establish the same genuine refusal before replacing only one guard.
    test_canonical_submission_rechecks_committed_rows_activity_and_writer(conn, funding_case, damage)
    source = inspect.getsource(funding.validate_submission)
    assert source.count(needle) == 1
    local = {}
    exec(compile(source.replace(needle, replacement), "<private-funding-" + guard + ">", "exec"),
         vars(funding), local)
    monkeypatch.setattr(funding, "validate_submission", local["validate_submission"])
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_canonical_submission_rechecks_committed_rows_activity_and_writer(conn, funding_case, damage)


from tests.sentinel.test_guarded_execution_broker import conn, pg  # noqa: E402,F401

