"""A quiescent paper cash basis and conservative journal-derived BUY ceilings.

There is no mutable balance to recover and no inferred release. Every promise
charges its original maximum for the lifetime of its plan, even after a fill or
cancellation. A later plan must earn an ordinary quiescent cash proof anew.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, field_validator

from sentinel.execution import journal, target_reprojection
from sentinel.execution.contract import BrokerAccountSnapshot, OrderTerms, Side
from sentinel.execution.numeric import decimal_text, exact_decimal
from sentinel.execution.states import CommandState, IN_FLIGHT


PREFIX = "protected-buy-funding:v1:"
HEADROOM = Decimal("1.00")


class ProtectedFundingRefused(ValueError):
    """The durable monetary authority is missing or contradictory."""


class ProtectedFundingNotReady(ProtectedFundingRefused):
    """The fixed promise does not currently fit its conservative allowance."""


class FundingBasis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema: Literal["sentinel.protected-buy-funding/1"] = "sentinel.protected-buy-funding/1"
    deployment: tuple[str, str, str, StrictInt]
    plan_id: str
    plan_fingerprint: str
    projection_fingerprint: str
    policy_sha256: str
    effective_session: date
    paper_base_url: str
    observed_at: AwareDatetime
    observation_id: StrictInt = Field(gt=0)
    observation_sha256: str
    cash_activity_sha256: str
    cash: Decimal
    buying_power: Decimal
    multiplier: Decimal = Decimal("1")

    @field_validator("cash", "buying_power", mode="before")
    @classmethod
    def exact_nonnegative(cls, value):
        if not isinstance(value, (str, Decimal)):
            raise ValueError("funding cash requires decimal strings or Decimal")
        result = Decimal(value)
        if not result.is_finite() or result < 0:
            raise ValueError("funding cash must be finite and nonnegative")
        return result

    @field_validator("multiplier", mode="before")
    @classmethod
    def unlevered(cls, value):
        if not isinstance(value, (str, Decimal)) or Decimal(value) != Decimal(1):
            raise ValueError("protected funding requires a 1x paper account")
        return Decimal(1)

    @field_validator("plan_fingerprint", "projection_fingerprint", "policy_sha256",
                     "observation_sha256", "cash_activity_sha256")
    @classmethod
    def digest(cls, value):
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("funding evidence requires an exact SHA256")
        return value


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _deployment(identity) -> tuple:
    return (identity.deployment_id, identity.broker,
            identity.broker_account_id, identity.takeover_epoch)


def _activity_identity(state):
    if state is None:
        return None
    return {"broker": state.broker, "account_id": state.account_id,
            "last_activity_id": state.last_activity_id,
            "balance_total": decimal_text(state.balance_total),
            "activity_identity_scheme": state.activity_identity_scheme}


def _require_writer(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid()"
            " AND locktype='advisory' AND classid=0 AND objid=%s"
            " AND objsubid=1 AND mode='ExclusiveLock' AND granted)",
            (journal.WRITER_LOCK_KEY,))
        owned = cur.fetchone()[0]
    if owned is not True:
        raise ProtectedFundingRefused("protected funding requires the execution writer lock")


def load_basis(conn, *, plan_id: str) -> FundingBasis | None:
    with conn.cursor() as cur:
        cur.execute("SELECT session,state FROM sentinel_processed_sessions"
                    " WHERE cursor_name=%s", (PREFIX + plan_id,))
        row = cur.fetchone()
    if row is None:
        return None
    try:
        value = row[1] if isinstance(row[1], dict) else json.loads(str(row[1]))
        unsigned = dict(value)
        digest = unsigned.pop("funding_sha256")
        if digest != _sha(unsigned):
            raise ValueError("funding fingerprint changed")
        basis = FundingBasis.model_validate(unsigned)
        if basis.plan_id != plan_id or basis.effective_session != row[0]:
            raise ValueError("funding basis key/session changed")
        from sentinel.config import assert_paper_url
        assert_paper_url(basis.paper_base_url)
        return basis
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise ProtectedFundingRefused("protected funding basis is corrupt") from exc


def _assert_basis(basis, *, plan, projection, deployment, policy) -> None:
    if (basis.deployment != _deployment(deployment)
            or basis.plan_id != plan.plan_id
            or basis.plan_fingerprint != plan.fingerprint()
            or basis.projection_fingerprint != projection.fingerprint()
            or basis.policy_sha256 != policy.fingerprint()
            or basis.effective_session != plan.effective_session):
        raise ProtectedFundingRefused("funding basis differs from current immutable authority")


def record_quiescent_basis(conn, *, plan, projection, binding, reconciliation,
                           account, activity_state, observed_at: datetime,
                           paper_base_url: str) -> FundingBasis:
    """Earn once through the existing strict account and cash contract."""
    from sentinel.config import assert_paper_url
    from sentinel.execution.protected_limits import ProtectedLimitPolicy
    from sentinel.paper.inspection import _account_evidence_is_quiescent, _account_or_refuse
    from sentinel.paper.cash import _cash_authority_or_refuse

    _require_writer(conn)
    assert_paper_url(paper_base_url)
    policy = ProtectedLimitPolicy.from_env()
    if policy is None:
        raise ProtectedFundingRefused("protected policy is not selected")
    target_reprojection.assert_projection(
        conn, plan=plan, projection=projection, through_session=plan.effective_session)
    existing = load_basis(conn, plan_id=plan.plan_id)
    if existing is not None:
        _assert_basis(existing, plan=plan, projection=projection,
                      deployment=binding.identity, policy=policy)
        if existing.paper_base_url != paper_base_url:
            raise ProtectedFundingRefused("funding endpoint changed")
        return existing
    observation = reconciliation.observation
    if (not reconciliation.transport_ready or reconciliation.observation_id is None
            or not _account_evidence_is_quiescent(
                conn, deployment=binding.identity, observation=observation)):
        raise ProtectedFundingNotReady("a clean quiescent cash observation is required")
    commands = journal.load_commands(conn, binding.identity, plan_id=plan.plan_id)
    if any(command.side is Side.BUY and command.state is not CommandState.SUPERSEDED
           for command in commands):
        raise ProtectedFundingRefused("a BUY promise predates the funding basis")
    _account_or_refuse(account, binding, binding.broker_account_id)
    _cash_authority_or_refuse(
        conn, plan=plan, deployment=binding.identity, account=account,
        observation=observation, activity_state=activity_state,
        endpoint_lag_observed_at=observed_at)
    if activity_state is None or activity_state.processed_through < observed_at:
        raise ProtectedFundingNotReady("complete native cash-activity evidence is required")
    payload = journal.load_observation_payload(conn, reconciliation.observation_id)
    activity = _activity_identity(activity_state)
    basis = FundingBasis(
        deployment=_deployment(binding.identity), plan_id=plan.plan_id,
        plan_fingerprint=plan.fingerprint(), projection_fingerprint=projection.fingerprint(),
        policy_sha256=policy.fingerprint(), effective_session=plan.effective_session,
        paper_base_url=paper_base_url, observed_at=observed_at,
        observation_id=reconciliation.observation_id,
        observation_sha256=_sha(payload), cash_activity_sha256=_sha(activity),
        cash=account.cash, buying_power=account.buying_power, multiplier=account.multiplier)
    value = basis.model_dump(mode="json")
    value["funding_sha256"] = _sha(value)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state)"
                    " VALUES (%s,%s,%s::jsonb) ON CONFLICT (cursor_name) DO NOTHING",
                    (PREFIX + plan.plan_id, plan.effective_session, _canonical(value)))
    if load_basis(conn, plan_id=plan.plan_id) != basis:
        raise ProtectedFundingRefused("concurrent funding basis differs")
    conn.commit()
    return basis


def maximum_cost(command) -> Decimal:
    if command.quantity != command.quantity.to_integral_value():
        raise ProtectedFundingRefused("protected BUY requires whole-share quantity")
    terms = command.order_terms
    if (not isinstance(terms, OrderTerms) or terms.order_type != "limit"
            or terms.time_in_force != "day" or terms.limit_price is None
            or terms.order_class != "simple" or terms.extended_hours is not False
            or command.side is not Side.BUY):
        raise ProtectedFundingRefused("BUY obligation has no certified fixed maximum")
    terms.require_owned_submission(command.side)
    if (command.filled_average_price is not None
            and command.filled_average_price > terms.limit_price):
        raise ProtectedFundingRefused("reported BUY fill exceeds its immutable limit")
    return exact_decimal(Fraction(command.quantity) * Fraction(terms.limit_price)
                         + Fraction(HEADROOM))


def available_for_purchase(*, basis_cash: Decimal, account: BrokerAccountSnapshot,
                           commands, candidate, deployment, plan_id: str) -> Decimal:
    """Pure gross-ceiling arithmetic; terminal savings are never recycled."""
    from sentinel.execution.contract import available_purchase_cash

    if not deployment.matches_account(account.identity):
        raise ProtectedFundingRefused("fresh account differs from the funding subject")
    available_purchase_cash(account)  # Typed amounts, 1x multiplier, active flags.
    if (account.status.upper() != "ACTIVE" or account.trading_blocked
            or account.account_blocked or account.trade_suspended_by_user):
        raise ProtectedFundingNotReady("paper account is unavailable")
    if account.buying_power - account.cash > Decimal("1.00"):
        raise ProtectedFundingRefused("buying power above cash exposes margin")
    if candidate.identity.deployment != deployment or candidate.identity.plan_id != plan_id:
        raise ProtectedFundingRefused("candidate differs from the funding cohort")
    other = Fraction(0)
    live_other = Fraction(0)
    found = False
    for command in commands:
        owner = command.identity.deployment
        if ((owner.deployment_id, owner.broker, owner.broker_account_id)
                != (deployment.deployment_id, deployment.broker, deployment.broker_account_id)
                or owner.takeover_epoch > deployment.takeover_epoch):
            raise ProtectedFundingRefused("journal command has another deployment")
        if command.identity.plan_id != plan_id:
            if command.state in IN_FLIGHT:
                raise ProtectedFundingNotReady("another plan still has an in-flight obligation")
            continue
        if owner != deployment:
            raise ProtectedFundingRefused("current-plan promise belongs to another takeover epoch")
        if command.side is not Side.BUY or command.state is CommandState.SUPERSEDED:
            continue
        cost = maximum_cost(command)
        if command.client_key == candidate.client_key:
            if command != candidate or found:
                raise ProtectedFundingRefused("candidate key has contradictory durable economics")
            found = True
        else:
            other += Fraction(cost)
            if command.state in IN_FLIGHT or command.state is CommandState.PLANNED:
                live_other += (Fraction(command.remaining) * Fraction(command.order_terms.limit_price)
                               + Fraction(HEADROOM))
    if not found:
        raise ProtectedFundingRefused("candidate was not durably reserved before transport")
    ceiling = max(Fraction(0), Fraction(basis_cash) - other)
    available = min(max(Fraction(0), Fraction(account.cash) - live_other),
                    Fraction(account.buying_power), ceiling)
    if Fraction(maximum_cost(candidate)) > available:
        raise ProtectedFundingNotReady("fixed BUY maximum exceeds its reserved paper cash")
    return exact_decimal(available)


def validate_submission(conn, *, client_key, instrument, quantity, order_terms,
                        account: BrokerAccountSnapshot, activity_state) -> None:
    """Canonical membrane callback; no caller-supplied funding proof is accepted."""
    from sentinel import binding as binding_mod
    from sentinel.execution import protected_limits

    _require_writer(conn)
    binding = binding_mod.require(conn)
    plan = journal.latest_plan(conn)
    if plan is None:
        raise ProtectedFundingRefused("there is no current execution plan")
    projection = target_reprojection.load_projection(conn, plan_id=plan.plan_id)
    basis = load_basis(conn, plan_id=plan.plan_id)
    policy = protected_limits.ProtectedLimitPolicy.from_env()
    if projection is None or basis is None or policy is None:
        raise ProtectedFundingRefused("protected projection, policy or funding basis is absent")
    _assert_basis(basis, plan=plan, projection=projection,
                  deployment=binding.identity, policy=policy)
    if (activity_state is None or activity_state.processed_through < basis.observed_at
            or _sha(_activity_identity(activity_state)) != basis.cash_activity_sha256):
        raise ProtectedFundingRefused("native cash activity changed or is incomplete after the funding basis")
    references = protected_limits.revalidate_references(conn, plan=plan, projection=projection)
    if references.symbols.get(instrument.security_id) != instrument.symbol:
        raise ProtectedFundingRefused("BUY symbol differs from its authenticated source identity")
    if (references.source_provider == "ALPACA_OPENFIGI"
            and instrument.security_id != "SENTINEL:BIL"
            and references.provider_asset_ids.get(instrument.security_id) != instrument.broker_id):
        raise ProtectedFundingRefused("BUY native asset differs from its authenticated source identity")
    target_reprojection.assert_projection(
        conn, plan=plan, projection=projection, through_session=plan.effective_session)
    commands = journal.load_commands(conn, binding.identity)
    candidates = [command for command in commands if command.client_key == client_key]
    if len(candidates) != 1:
        raise ProtectedFundingRefused("exact durable candidate is absent or duplicated")
    candidate = candidates[0]
    if (candidate.state is not CommandState.SEND_PENDING
            or candidate.filled_quantity != 0 or candidate.broker_order_id is not None
            or candidate.instrument != instrument or candidate.quantity != quantity
            or candidate.order_terms != order_terms
            or candidate.order_terms != protected_limits.order_terms_for(
                projection, candidate.security_id)):
        raise ProtectedFundingRefused("pre-transport command differs from its immutable protection")
    available_for_purchase(
        basis_cash=basis.cash, account=account, commands=commands, candidate=candidate,
        deployment=binding.identity, plan_id=plan.plan_id)
