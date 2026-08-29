"""Broker-cash evidence, account economics, and paper cash authority."""

from __future__ import annotations

import json

from datetime import date, datetime, timedelta

from decimal import Decimal, InvalidOperation

from typing import Mapping, Optional

from sentinel.execution import broker_cash, executor, journal

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
        "quantity": str(item.quantity),
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
        "quantity": str(item.quantity),
        "filled_quantity": str(item.filled_quantity),
        "filled_average_price": (
            None if item.filled_average_price is None
            else str(item.filled_average_price)),
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
        "cash": str(snapshot.cash),
        "multiplier": (None if snapshot.multiplier is None
                       else str(snapshot.multiplier)),
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
        "quantity": str(command.quantity),
        "filled_quantity": str(command.filled_quantity),
        "filled_average_price": (
            None if command.filled_average_price is None
            else str(command.filled_average_price)),
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
        "expected_cash": str(expected_cash),
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
    try:
        return await broker_cash.ingest_account_cash(
            conn, broker_adapter=broker, broker=binding.broker,
            account_id=binding.broker_account_id, through=through)
    except BrokerAuthorityRefused:
        raise
    except broker_cash.BrokerCashAuthorityRefused as exc:
        raise PaperActivationRefused(
            f"broker cash authority is inconsistent: {exc}") from exc
    except Exception as exc:                                  # noqa: BLE001
        raise PaperRetryableRefused(
            "broker cash activity evidence is temporarily unavailable: "
            f"{type(exc).__name__}: {exc}") from exc

def _cash_authority_or_refuse(
        conn, *, plan: ExecutionPlan, deployment,
        account: BrokerAccountSnapshot, observation: BrokerObservation,
        activity_state: broker_cash.CashActivityState | None = None,
        permit_new_activity: bool = False,
        endpoint_lag_observed_at: datetime | None = None) -> None:
    """Reconcile immutable plan cash to fills plus durable broker activities.

    The account balance is never its own explanation.  Native Account Activity
    rows explain cash movement; the immutable plan records which cumulative
    activity total already existed when it was sized.  A later recognized cash
    event may authorize the *next* decision to use the fresh balance, but never
    rewrites a same-session plan or an execution already in flight.
    """
    expected_without_activity = plan.account_cash
    for command in journal.load_commands(
            conn, deployment, plan_id=plan.plan_id):
        if command.filled_quantity == 0:
            continue
        if command.filled_average_price is None:
            raise PaperActivationRefused(
                f"cannot reconcile account cash for filled command "
                f"{command.client_key}: its durable broker fill has no "
                "average price")
        notional = command.filled_quantity * command.filled_average_price
        expected_without_activity += (
            notional if command.side.value == "SELL" else -notional)

    activity_delta = Decimal(0)
    activity_identity_changed = False
    if activity_state is not None:
        if (activity_state.broker != plan.broker
                or activity_state.account_id != plan.broker_account_id):
            raise PaperActivationRefused(
                "broker cash activity state belongs to another account")
        baseline = broker_cash.load_plan_baseline(
            conn, plan_id=plan.plan_id)
        if baseline is None:
            # Never stamp current activity history retroactively onto an old
            # immutable plan. Offsetting post-plan events can leave cash
            # numerically unchanged while changing the native event set, so a
            # current equality cannot reconstruct the plan-time boundary.
            raise PaperActivationRefused(
                f"plan {plan.plan_id} has no immutable broker cash baseline. "
                "It cannot be backfilled from current cash or activity state; "
                "resolve the legacy plan explicitly and prepare a fresh plan")
        if (baseline.activity_identity_authoritative
                and activity_state.activity_identity_scheme
                != baseline.activity_identity_scheme):
            raise PaperActivationRefused(
                "broker cash activity state does not carry the same accepted "
                "activity identity scheme as the authoritative plan baseline")
        activity_delta = activity_state.balance_total - baseline.balance_total
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

    expected = expected_without_activity + activity_delta
    if abs(account.cash - expected) > Decimal("1.00"):
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
    if (activity_delta != 0 or activity_identity_changed) \
            and not permit_new_activity:
        raise PaperActivationRefused(
            "broker-native cash activity changed after plan "
            f"{plan.plan_id} was prepared (net={activity_delta}, "
            f"last_activity_id={activity_state.last_activity_id!r}). The "
            "event set is durably explained, but this immutable plan will not "
            "be re-sized or netted in place; prepare the next closed decision "
            "session")
