"""Broker-cash evidence, account economics, and paper cash authority."""

from __future__ import annotations

import json

from datetime import date, datetime, timedelta

from decimal import Decimal, InvalidOperation
from fractions import Fraction

from typing import Mapping, Optional

from sentinel.execution import broker_cash, executor, journal
from sentinel.execution.numeric import decimal_text, exact_decimal as _cash_decimal

from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerInstrument,
    BrokerObservation,
    ExecutionBroker,
    MalformedBrokerEvidence,
)

from sentinel.execution.guarded import (
    AutomationExecutionGrant,
    BrokerAuthorityRefused,
    BrokerOperation,
    GuardedExecutionBroker,
    ManualExecutionGrant,
    PaperPreparationGrant,
)

from sentinel.execution.plan import ExecutionPlan

from .model import (
    NativeFeePostingPending,
    PaperActivationRefused,
    PaperRetryableRefused,
)

from .validation import _hash

ACCOUNT_ENDPOINT_LAG_GRACE = timedelta(seconds=120)

_ACCOUNT_ENDPOINT_LAG_SCHEMA = "sentinel.broker-account-lag/1"

_ACCOUNT_ENDPOINT_LAG_PREFIX = "broker-account-lag:v1:"


def _observation_economics(observation: BrokerObservation) -> dict:
    """Canonical broker book facts, excluding transport timestamps."""
    positions = [{
        "security_id": item.instrument.security_id,
        "broker_id": item.instrument.broker_id,
        "quantity": None if item.quantity is None else decimal_text(item.quantity),
    } for item in observation.positions]
    positions.sort(key=lambda item: (
        item["security_id"], item["broker_id"] or "", item["quantity"]))
    orders = [{
        "broker_order_id": item.broker_order_id,
        "client_key": item.client_key,
        "security_id": item.instrument.security_id,
        "broker_id": item.instrument.broker_id,
        "side": item.side.value,
        "state": item.state.value,
        "quantity": None if item.quantity is None else decimal_text(item.quantity),
        **({"notional": decimal_text(item.notional)} if item.notional is not None else {}),
        "filled_quantity": decimal_text(item.filled_quantity),
        "filled_average_price": (
            None if item.filled_average_price is None
            else decimal_text(item.filled_average_price)),
        "external_replacement": bool(item.external_replacement),
    } for item in observation.orders if item.is_working]
    orders.sort(key=lambda item: (
        item["broker_order_id"], item["client_key"] or ""))
    return {
        "completeness": observation.completeness.value,
        "account": (
            None if observation.account_identity is None else {
                "broker": observation.account_identity.broker,
                "account_id": observation.account_identity.account_id,
            }),
        "positions": positions,
        "orders": orders,
    }

def _account_economics(snapshot: BrokerAccountSnapshot) -> dict:
    """Facts that must remain stable around a settled cash observation.

    Equity is mark-to-market and can tick with no broker activity. Buying power
    can be recomputed from those marks as well; each endpoint payload is still
    validated as cash-only by ``_account_or_refuse``, but neither value is a
    stable cross-request identity. Cash and the account's permission/status
    fields are the relevant evidence for cash certification.
    """
    return {
        "broker": snapshot.identity.broker,
        "account_id": snapshot.identity.account_id,
        "cash": decimal_text(snapshot.cash),
        "multiplier": (None if snapshot.multiplier is None
                       else decimal_text(snapshot.multiplier)),
        "status": snapshot.status,
        "trading_blocked": snapshot.trading_blocked,
        "account_blocked": snapshot.account_blocked,
        "trade_suspended_by_user": snapshot.trade_suspended_by_user,
    }

def _account_endpoint_lag_is_live(
        conn, *, plan: ExecutionPlan, deployment,
        account: BrokerAccountSnapshot, expected_cash: Decimal,
        observation: BrokerObservation, observed_at: datetime) -> bool:
    """Create/read one non-renewable grace for a stable cash mismatch."""
    if observed_at.tzinfo is None:
        raise PaperActivationRefused(
            "account endpoint evidence time must be timezone-aware")
    durable_commands = [{
        "client_key": command.client_key,
        "security_id": command.security_id,
        "broker_order_id": command.broker_order_id,
        "side": command.side.value,
        "state": command.state.value,
        "quantity": None if command.quantity is None else decimal_text(command.quantity),
        **({"notional": decimal_text(command.notional)} if command.notional is not None else {}),
        "filled_quantity": decimal_text(command.filled_quantity),
        "filled_average_price": (
            None if command.filled_average_price is None
            else decimal_text(command.filled_average_price)),
    } for command in journal.load_commands(
        conn, deployment, plan_id=plan.plan_id)]
    durable_commands.sort(key=lambda item: item["client_key"])
    observation_value = _observation_economics(observation)
    settled_book_identity = {
        # Terminal order rows may age out of the next recovery window after the
        # first retry. The durable command journal is their stable authority;
        # working orders cannot reach this quiescent evidence path at all.
        "durable_commands": durable_commands,
        "positions": observation_value["positions"],
        "account": observation_value["account"],
    }
    identity = {
        "schema": _ACCOUNT_ENDPOINT_LAG_SCHEMA,
        "deployment": deployment.to_dict(),
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.fingerprint(),
        "expected_cash": decimal_text(expected_cash),
        "settled_book_sha256": _hash(settled_book_identity),
    }
    cursor = _ACCOUNT_ENDPOINT_LAG_PREFIX + _hash(identity)
    candidate = dict(
        identity, first_observed_cash=str(account.cash),
        first_observed_at=observed_at.isoformat())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
            " ON CONFLICT (cursor_name) DO NOTHING",
            (cursor, observed_at.date(), json.dumps(
                candidate, sort_keys=True, separators=(",", ":"))))
        cur.execute(
            "SELECT state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s", (cursor,))
        row = cur.fetchone()
    if row is None:
        raise PaperActivationRefused(
            "account endpoint-lag evidence was not retained")
    stored = row[0] if isinstance(row[0], Mapping) else json.loads(str(row[0]))
    if (set(stored) != set(identity) | {
            "first_observed_cash", "first_observed_at"}
            or any(stored.get(key) != value
                   for key, value in identity.items())):
        raise PaperActivationRefused(
            "account endpoint-lag evidence identity changed")
    try:
        first = datetime.fromisoformat(str(stored["first_observed_at"]))
        first_cash = Decimal(str(stored["first_observed_cash"]))
    except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
        raise PaperActivationRefused(
            "account endpoint-lag evidence time is malformed") from exc
    if first.tzinfo is None or not first_cash.is_finite():
        raise PaperActivationRefused(
            "account endpoint-lag evidence value is invalid")
    # The surrounding writer lock rolls back on the retryable refusal this
    # function intentionally triggers.  Commit the immutable first-seen clock
    # now so a restart/retry cannot manufacture a fresh 120-second grace
    # forever.  Reconciliation writes preceding this point are also positive
    # broker evidence and are safe (and necessary) to retain.
    conn.commit()
    age = observed_at - first
    return timedelta(0) <= age <= ACCOUNT_ENDPOINT_LAG_GRACE

async def _broker_cash_state_or_refuse(
        conn, *, broker: ExecutionBroker, binding,
        through: datetime) -> broker_cash.CashActivityState | None:
    """Ingest one complete broker-cash interval under the caller's writer lock."""
    if not getattr(broker, "supports_account_cash_activities", False):
        return None
    from sentinel.execution.alpaca import ActivityCorrectionRequiresRecovery
    try:
        return await broker_cash.ingest_account_cash(
            conn, broker_adapter=broker, broker=binding.broker,
            account_id=binding.broker_account_id, through=through)
    except BrokerAuthorityRefused:
        raise
    except (broker_cash.BrokerCashAuthorityRefused, MalformedBrokerEvidence,
            ActivityCorrectionRequiresRecovery) as exc:
        raise PaperActivationRefused(
            f"broker cash authority is inconsistent: {exc}") from exc
    except Exception as exc:                                  # noqa: BLE001
        raise PaperRetryableRefused(
            "broker cash activity evidence is temporarily unavailable: "
            f"{type(exc).__name__}: {exc}") from exc

def _plan_fill_cash(conn, *, plan: ExecutionPlan, deployment, commands=None) -> Fraction:
    """The one immutable-plan plus durable-fill cash equation."""
    expected_without_activity = Fraction(plan.account_cash)
    if commands is None:
        commands = journal.load_commands(conn, deployment, plan_id=plan.plan_id)
    for command in commands:
        if command.identity.plan_id != plan.plan_id:
            continue
        if command.filled_quantity == 0:
            continue
        if command.filled_average_price is None:
            raise PaperActivationRefused(
                f"cannot reconcile account cash for filled command "
                f"{command.client_key}: its durable broker fill has no "
                "average price")
        notional = Fraction(command.filled_quantity) * Fraction(command.filled_average_price)
        expected_without_activity += (
            notional if command.side.value == "SELL" else -notional)
    return expected_without_activity


def _require_exact_fee_cash(*, account, exact_expected) -> None:
    if Fraction(account.cash) != exact_expected:
        raise PaperActivationRefused(
            "native fee continuation requires the exact fresh cash equation")


def _fee_cash_continuation(
        conn, *, baseline, account, activity_state, exact_expected,
        expected_without_activity, deployment, observation, allow_native_fee_wait) -> bool:
    try:
        debit_fees_only = broker_cash.plan_activity_is_debit_fees_only(
            conn, baseline=baseline, activity_state=activity_state)
    except broker_cash.BrokerCashAuthorityRefused as exc:
        raise PaperActivationRefused(
            f"native fee continuation evidence is inconsistent: {exc}") from exc
    if not debit_fees_only:
        return False
    if (allow_native_fee_wait
            and Fraction(account.cash) == expected_without_activity
            and deployment.matches_account(account.identity)
            and observation is not None and observation.account_identity is not None
            and deployment.matches_account(observation.account_identity)):
        from .inspection import _account_evidence_is_quiescent
        if _account_evidence_is_quiescent(conn, deployment=deployment, observation=observation):
            raise NativeFeePostingPending(
                "Alpaca account cash has not yet reflected the verified debit fees")
    _require_exact_fee_cash(account=account, exact_expected=exact_expected)
    return True


def load_native_fee_plan_baseline(conn, *, plan, deployment, account, activity_state):
    """Load the actual original plan boundary; this alone grants no permission."""
    try:
        baseline = broker_cash.load_plan_baseline(conn, plan_id=plan.plan_id)
    except broker_cash.BrokerCashAuthorityRefused as exc:
        raise PaperActivationRefused("immutable fee-plan cash baseline is inconsistent") from exc
    if baseline is None or baseline.activity_membership is None:
        return None
    if (baseline.broker != plan.broker or baseline.account_id != plan.broker_account_id
            or baseline.decision_session != plan.decision_session
            or not deployment.matches_account(account.identity)
            or activity_state.broker != plan.broker
            or activity_state.account_id != plan.broker_account_id):
        raise PaperActivationRefused("native fee-plan cash subject changed")
    return baseline


def require_exact_native_fee_cash(conn, *, plan, deployment, account,
                                   activity_state, baseline, commands=None) -> None:
    """The canonical exact cash equation, after the owner proves memberships."""
    exact_expected = _plan_fill_cash(conn, plan=plan, deployment=deployment, commands=commands)
    exact_expected += Fraction(activity_state.balance_total) - Fraction(baseline.balance_total)
    _require_exact_fee_cash(account=account, exact_expected=exact_expected)


def native_fee_plan_continuation(conn, *, plan, deployment, account,
                                  activity_state) -> bool:
    """Canonical plan-only proof, with no supplied exception or observation."""
    baseline = load_native_fee_plan_baseline(conn, plan=plan, deployment=deployment,
        account=account, activity_state=activity_state)
    if baseline is None:
        return False
    try:
        fees = broker_cash.plan_activity_is_debit_fees_only(
            conn, baseline=baseline, activity_state=activity_state)
    except broker_cash.BrokerCashAuthorityRefused as exc:
        raise PaperActivationRefused("native fee-plan membership is inconsistent") from exc
    if fees:
        require_exact_native_fee_cash(conn, plan=plan, deployment=deployment,
            account=account, activity_state=activity_state, baseline=baseline)
    return fees


def _cash_authority_or_refuse(
        conn, *, plan: ExecutionPlan, deployment,
        account: BrokerAccountSnapshot, observation: BrokerObservation,
        activity_state: broker_cash.CashActivityState | None = None,
        permit_new_activity: bool = False,
        endpoint_lag_observed_at: datetime | None = None,
        allow_native_fee_wait: bool = False) -> bool:
    """Reconcile immutable plan cash to fills plus durable broker activities.

    The account balance is never its own explanation. Native activities explain
    movement; the immutable plan binds the prior set. Only exact membership-
    proved debit fees may continue its intent under fresh funding guards. The
    return value says whether changed activity still requires plan retirement.
    """
    expected_without_activity = _plan_fill_cash(conn, plan=plan, deployment=deployment)

    activity_delta = Fraction(0)
    activity_identity_changed = False
    if activity_state is not None:
        if (activity_state.broker != plan.broker
                or activity_state.account_id != plan.broker_account_id):
            raise PaperActivationRefused(
                "broker cash activity state belongs to another account")
        try:
            baseline = broker_cash.load_plan_baseline(
                conn, plan_id=plan.plan_id)
        except broker_cash.BrokerCashAuthorityRefused as exc:
            raise PaperActivationRefused(
                f"immutable plan cash baseline is inconsistent: {exc}") from exc
        if baseline is None:
            # Never stamp current activity history retroactively onto an old
            # immutable plan. Offsetting post-plan events can leave cash
            # numerically unchanged while changing the native event set, so a
            # current equality cannot reconstruct the plan-time boundary.
            raise PaperActivationRefused(
                f"plan {plan.plan_id} has no immutable broker cash baseline. "
                "It cannot be backfilled from current cash or activity state; "
                "resolve the legacy plan explicitly and prepare a fresh plan")
        if (baseline.broker != activity_state.broker
                or baseline.account_id != activity_state.account_id
                or baseline.decision_session != plan.decision_session):
            raise PaperActivationRefused(
                "immutable plan cash baseline belongs to another account or session")
        if (baseline.activity_identity_authoritative
                and activity_state.activity_identity_scheme
                != baseline.activity_identity_scheme):
            raise PaperActivationRefused(
                "broker cash activity state does not carry the same accepted "
                "activity identity scheme as the authoritative plan baseline")
        activity_delta = Fraction(activity_state.balance_total) - Fraction(baseline.balance_total)
        if not baseline.activity_identity_authoritative:
            if not permit_new_activity:
                raise PaperActivationRefused(
                    f"plan {plan.plan_id} has a legacy cash baseline without "
                    "native activity-set identity; execution is refused until "
                    "preparation adopts a fresh plan")
            activity_identity_changed = True
        else:
            activity_identity_changed = (
                activity_state.last_activity_id != baseline.last_activity_id)

    exact_expected = expected_without_activity + activity_delta
    actual_cash = Fraction(account.cash)
    discrepancy = abs(actual_cash - exact_expected)
    activity_changed = activity_delta != 0 or activity_identity_changed
    possible_unposted_fee = allow_native_fee_wait and actual_cash == expected_without_activity
    if (activity_state is not None and baseline.activity_membership is not None
            and (discrepancy <= 1 or possible_unposted_fee)):
        if _fee_cash_continuation(
                conn, baseline=baseline, account=account, activity_state=activity_state,
                exact_expected=exact_expected, expected_without_activity=expected_without_activity,
                deployment=deployment, observation=observation,
                allow_native_fee_wait=allow_native_fee_wait):
            # A fee grants no new money and never changes a target or baseline.
            # Every BUY still earns fresh actual-cash/reservation admission.
            return False
    expected = _cash_decimal(exact_expected)
    if discrepancy > 1:
        if (permit_new_activity and activity_state is not None
                and baseline.activity_identity_authoritative
                and activity_delta > 0
                and Fraction(account.cash) == expected_without_activity):
            # A native credit may be visible before the balance endpoint
            # reflects it. This read-only wait earns no cash/plan authority and
            # never renews the separate generic endpoint-lag clock.
            raise PaperRetryableRefused(
                'account cash is not yet coherent with known positive native '
                'cash activity; preparation/recovery must wait for the full '
                'cash equation before adopting a new plan or baseline')
        if (endpoint_lag_observed_at is not None
                and _account_endpoint_lag_is_live(
                    conn, plan=plan, deployment=deployment,
                    account=account, expected_cash=expected,
                    observation=observation,
                    observed_at=endpoint_lag_observed_at)):
            raise PaperRetryableRefused(
                "account cash endpoint is not yet coherent with the stable "
                "order/position bracket; no mutation is permitted during the "
                f"bounded {int(ACCOUNT_ENDPOINT_LAG_GRACE.total_seconds())}s "
                "re-observation window")
        raise PaperActivationRefused(
            f"fresh account cash {account.cash} is not explained by plan "
            f"baseline {plan.account_cash}, durable fills and broker-native "
            f"cash activities (expected {expected}). Cash movement is never "
            "inferred")
    if activity_changed and not permit_new_activity:
        raise PaperActivationRefused(
            "broker-native cash activity changed after plan "
            f"{plan.plan_id} was prepared (net={_cash_decimal(activity_delta)}, "
            f"last_activity_id={activity_state.last_activity_id!r}). The "
            "event set is durably explained, but this immutable plan will not "
            "be re-sized or netted in place; prepare the next closed decision "
            "session")
    return activity_changed
