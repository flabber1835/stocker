"""Durable broker cash evidence and immutable-plan cash baselines.

Issue #183 deliberately reuses two already-authoritative stores rather than
creating a runtime table that the behavioral-schema fingerprint does not know
about:

* ``sentinel_cash_flows`` retains every recognized broker-native cash activity;
  a reserved flow-id/detail encoding distinguishes external capital from
  internal strategy cash without changing the table's physical schema.
* ``sentinel_processed_sessions`` is a keyed durable cursor store.  Its existing
  Wealth Core row remains ``catchup``; namespaced broker/activity and plan
  baseline rows keep their own validated JSON state and cannot collide with it.

The important separation is ECONOMIC, not storage.  A deposit is external
capital and must be removed from strategy P&L.  A dividend, fee or interest
payment also moves cash, but removing it from P&L would manufacture performance.
Both explain broker cash; only the first class is external capital.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Mapping, Optional

from sentinel.execution.contract import Completeness


FLOW_PREFIX = "broker-cash:v1:"
DETAIL_PREFIX = "broker-cash/v1;"
ACTIVITY_CURSOR_PREFIX = "broker-cash-activity:v1:"
PLAN_BASELINE_PREFIX = "broker-cash-plan:v1:"
ACTIVITY_OVERLAP = timedelta(minutes=5)

# These are capital crossing the account boundary rather than strategy income or
# expense.  Cash journals stay INTERNAL: the broker says that cash moved, but a
# journal label alone does not prove that new investor capital entered.
EXTERNAL_ACTIVITY_TYPES = frozenset({"CSD", "CSW", "ACATC"})
INTERNAL_ACTIVITY_TYPES = frozenset({
    "FEE", "CFEE",
    "INT", "INTNRA", "INTTW",
    "JNL", "JNLC",
    "DIV", "DIVCGL", "DIVCGS", "DIVFEE", "DIVFT", "DIVNRA", "DIVROC",
    "DIVTW", "DIVTXEX", "CGD",
    "PTC", "PTR",
})
RECOGNIZED_ACTIVITY_TYPES = EXTERNAL_ACTIVITY_TYPES | INTERNAL_ACTIVITY_TYPES


class BrokerCashAuthorityRefused(RuntimeError):
    """Broker cash history is incomplete, contradictory, or lacks a baseline."""


@dataclass(frozen=True)
class BrokerCashActivity:
    activity_id: str
    activity_type: str
    activity_date: date
    net_amount: Decimal
    raw: Mapping

    def __post_init__(self) -> None:
        if not self.activity_id.strip():
            raise ValueError("broker cash activity id must be non-empty")
        if self.activity_type not in RECOGNIZED_ACTIVITY_TYPES:
            raise ValueError(
                f"unrecognized broker cash activity type {self.activity_type!r}")
        if not isinstance(self.net_amount, Decimal) or not self.net_amount.is_finite():
            raise TypeError("broker cash activity net_amount must be finite Decimal")

    @property
    def classification(self) -> str:
        return ("EXTERNAL" if self.activity_type in EXTERNAL_ACTIVITY_TYPES
                else "INTERNAL")


@dataclass(frozen=True)
class BrokerCashActivityBatch:
    activities: tuple[BrokerCashActivity, ...]
    processed_through: datetime
    completeness: Completeness
    last_activity_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.processed_through.tzinfo is None:
            raise ValueError("broker cash activity upper boundary must be timezone-aware")
        if self.last_activity_id is not None and not self.last_activity_id.strip():
            raise ValueError("last_activity_id must be non-empty when present")


@dataclass(frozen=True)
class CashActivityState:
    broker: str
    account_id: str
    processed_through: datetime
    last_activity_id: Optional[str]
    balance_total: Decimal


@dataclass(frozen=True)
class PlanCashBaseline:
    plan_id: str
    broker: str
    account_id: str
    decision_session: date
    processed_through: datetime
    balance_total: Decimal


def _activity_cursor_name(broker: str, account_id: str) -> str:
    return f"{ACTIVITY_CURSOR_PREFIX}{broker}:{account_id}"


def _plan_cursor_name(plan_id: str) -> str:
    return f"{PLAN_BASELINE_PREFIX}{plan_id}"


def broker_flow_id(*, broker: str, account_id: str, activity_id: str) -> str:
    # Native id is the idempotency authority; broker/account scope prevents a
    # restored database pointed at another account from aliasing the same id.
    return f"{FLOW_PREFIX}{broker}:{account_id}:{activity_id}"


def is_broker_flow(flow_id: str) -> bool:
    return str(flow_id).startswith(FLOW_PREFIX)


def broker_flow_is_external(flow_id: str, detail: str) -> bool:
    """Return the economic class encoded by a reserved broker flow row.

    Malformed reserved rows are corruption, not ordinary operator flows.  This
    function is called by ``cashflow.net_external`` so a damaged classification
    can never silently change reported strategy P&L.
    """
    if not is_broker_flow(flow_id):
        return True
    prefix = DETAIL_PREFIX + "class="
    if not str(detail).startswith(prefix):
        raise BrokerCashAuthorityRefused(
            f"reserved broker cash flow {flow_id!r} has malformed detail")
    classification = str(detail)[len(prefix):].split(";", 1)[0]
    if classification not in {"EXTERNAL", "INTERNAL"}:
        raise BrokerCashAuthorityRefused(
            f"reserved broker cash flow {flow_id!r} has unknown class "
            f"{classification!r}")
    return classification == "EXTERNAL"


def _detail(activity: BrokerCashActivity) -> str:
    return (
        f"{DETAIL_PREFIX}class={activity.classification};"
        f"type={activity.activity_type};id={activity.activity_id}")


def _read_json_state(raw, *, where: str) -> dict:
    if isinstance(raw, dict):
        state = raw
    else:
        try:
            state = json.loads(str(raw))
        except (TypeError, ValueError) as exc:
            raise BrokerCashAuthorityRefused(
                f"{where} is not valid JSON") from exc
    if not isinstance(state, dict):
        raise BrokerCashAuthorityRefused(f"{where} must be a JSON object")
    return state


def _aware(value, *, where: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise BrokerCashAuthorityRefused(
            f"{where} is not a timezone-aware timestamp") from exc
    if parsed.tzinfo is None:
        raise BrokerCashAuthorityRefused(
            f"{where} is not a timezone-aware timestamp")
    return parsed.astimezone(timezone.utc)


def _finite_decimal(value, *, where: str) -> Decimal:
    try:
        out = Decimal(str(value))
    except Exception as exc:  # Decimal exposes several parse subclasses.
        raise BrokerCashAuthorityRefused(f"{where} is not Decimal") from exc
    if not out.is_finite():
        raise BrokerCashAuthorityRefused(f"{where} is not finite")
    return out


def load_activity_state(conn, *, broker: str,
                        account_id: str) -> Optional[CashActivityState]:
    name = _activity_cursor_name(broker, account_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s",
            (name,))
        row = cur.fetchone()
    if row is None:
        return None
    state = _read_json_state(row[0], where=f"cash activity cursor {name}")
    expected = {"kind", "broker", "account_id", "processed_through",
                "last_activity_id", "balance_total"}
    if set(state) != expected or state.get("kind") != "broker-cash-activity/v1":
        raise BrokerCashAuthorityRefused(
            f"cash activity cursor {name} has an unknown state shape")
    if state["broker"] != broker or state["account_id"] != account_id:
        raise BrokerCashAuthorityRefused(
            f"cash activity cursor {name} is bound to another account")
    last_id = state["last_activity_id"]
    if last_id is not None and (not isinstance(last_id, str) or not last_id.strip()):
        raise BrokerCashAuthorityRefused(
            f"cash activity cursor {name} has an invalid native id")
    return CashActivityState(
        broker=broker, account_id=account_id,
        processed_through=_aware(
            state["processed_through"], where=f"cash activity cursor {name}"),
        last_activity_id=last_id,
        balance_total=_finite_decimal(
            state["balance_total"], where=f"cash activity cursor {name} total"))


def _binding_established_at(conn, *, broker: str, account_id: str) -> datetime:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT broker,broker_account_id,established_at"
            " FROM sentinel_account_binding WHERE id=1")
        row = cur.fetchone()
    if row is None:
        raise BrokerCashAuthorityRefused(
            "broker cash ingestion requires the durable account binding")
    if str(row[0]) != broker or str(row[1]) != account_id:
        raise BrokerCashAuthorityRefused(
            "broker cash ingestion account does not match durable binding")
    established = row[2]
    if not isinstance(established, datetime) or established.tzinfo is None:
        raise BrokerCashAuthorityRefused(
            "durable account binding has no timezone-aware established_at")
    return established.astimezone(timezone.utc)


def _insert_activity(conn, *, broker: str, account_id: str,
                     activity: BrokerCashActivity) -> bool:
    """Insert once; a replay under the native id must be byte-economic equal."""
    if activity.net_amount == 0:
        return False
    flow_id = broker_flow_id(
        broker=broker, account_id=account_id,
        activity_id=activity.activity_id)
    detail = _detail(activity)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_cash_flows"
            " (flow_id,session,amount,detail) VALUES (%s,%s,%s,%s)"
            " ON CONFLICT (flow_id) DO NOTHING RETURNING flow_id",
            (flow_id, activity.activity_date.isoformat(),
             str(activity.net_amount), detail))
        inserted = cur.fetchone() is not None
        if inserted:
            return True
        cur.execute(
            "SELECT session,amount,detail FROM sentinel_cash_flows"
            " WHERE flow_id=%s", (flow_id,))
        row = cur.fetchone()
    if row is None:  # pragma: no cover - same transaction, defensive only.
        raise BrokerCashAuthorityRefused(
            f"broker activity {activity.activity_id} disappeared during replay")
    observed = (str(row[0]), Decimal(str(row[1])), str(row[2]))
    expected = (activity.activity_date.isoformat(), activity.net_amount, detail)
    if observed != expected:
        raise BrokerCashAuthorityRefused(
            f"broker activity id {activity.activity_id!r} changed economics: "
            f"stored={observed}, replay={expected}")
    return False


async def ingest_account_cash(
        conn, *, broker_adapter, broker: str, account_id: str,
        through: Optional[datetime] = None) -> CashActivityState:
    """Fetch one complete bounded interval and advance its cursor atomically.

    No row is written until the adapter has proved that the whole paginated
    interval completed.  The caller holds Sentinel's session writer lock; its
    commit/rollback therefore covers events and cursor together.
    """
    prior = load_activity_state(conn, broker=broker, account_id=account_id)
    upper = through or datetime.now(timezone.utc)
    if upper.tzinfo is None:
        raise BrokerCashAuthorityRefused(
            "broker cash ingestion upper boundary must be timezone-aware")
    upper = upper.astimezone(timezone.utc)
    established = _binding_established_at(
        conn, broker=broker, account_id=account_id)
    if prior is not None:
        if upper < prior.processed_through:
            raise BrokerCashAuthorityRefused(
                "broker cash ingestion clock moved behind its durable cursor")
        if upper == prior.processed_through:
            return prior
        after = max(established, prior.processed_through - ACTIVITY_OVERLAP)
        running_total = prior.balance_total
    else:
        after = established
        running_total = Decimal(0)
        # A cursor without its event ledger would be a partial restore.  The
        # inverse is equally ambiguous: retained reserved rows with no cursor
        # cannot establish which page boundary had actually been processed.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM sentinel_cash_flows"
                " WHERE flow_id LIKE %s", (f"{FLOW_PREFIX}{broker}:{account_id}:%",))
            if int(cur.fetchone()[0]) != 0:
                raise BrokerCashAuthorityRefused(
                    "broker cash activity rows exist without their durable "
                    "cursor; restore the complete behavioral state")

    batch = await broker_adapter.account_cash_activities(
        after=after, through=upper)
    if not isinstance(batch, BrokerCashActivityBatch):
        raise BrokerCashAuthorityRefused(
            "broker cash adapter returned an untyped activity batch")
    if batch.completeness is not Completeness.COMPLETE:
        raise BrokerCashAuthorityRefused(
            f"broker cash activity history is {batch.completeness.value}; "
            "cursor not advanced")
    if batch.processed_through.astimezone(timezone.utc) != upper:
        raise BrokerCashAuthorityRefused(
            "broker cash activity batch changed its requested upper boundary")

    seen: set[str] = set()
    last_id = prior.last_activity_id if prior else None
    for activity in batch.activities:
        if activity.activity_id in seen:
            raise BrokerCashAuthorityRefused(
                f"broker cash batch repeats native id {activity.activity_id}")
        seen.add(activity.activity_id)
        if _insert_activity(
                conn, broker=broker, account_id=account_id,
                activity=activity):
            running_total += activity.net_amount
        last_id = activity.activity_id
    if batch.last_activity_id is not None:
        if batch.activities and batch.last_activity_id != batch.activities[-1].activity_id:
            raise BrokerCashAuthorityRefused(
                "broker cash batch last native id does not match final activity")
        last_id = batch.last_activity_id

    state = CashActivityState(
        broker=broker, account_id=account_id, processed_through=upper,
        last_activity_id=last_id, balance_total=running_total)
    payload = {
        "kind": "broker-cash-activity/v1",
        "broker": broker,
        "account_id": account_id,
        "processed_through": upper.isoformat(),
        "last_activity_id": last_id,
        "balance_total": str(running_total),
    }
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
            " ON CONFLICT (cursor_name) DO UPDATE SET"
            " session=EXCLUDED.session,state=EXCLUDED.state,updated_at=NOW()",
            (_activity_cursor_name(broker, account_id), upper.date().isoformat(),
             json.dumps(payload, sort_keys=True)))
    return state


def load_plan_baseline(conn, *, plan_id: str) -> Optional[PlanCashBaseline]:
    name = _plan_cursor_name(plan_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s", (name,))
        row = cur.fetchone()
    if row is None:
        return None
    session = row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0]))
    state = _read_json_state(row[1], where=f"plan cash baseline {plan_id}")
    expected = {"kind", "plan_id", "broker", "account_id",
                "processed_through", "balance_total"}
    if set(state) != expected or state.get("kind") != "broker-cash-plan/v1":
        raise BrokerCashAuthorityRefused(
            f"plan cash baseline {plan_id} has an unknown state shape")
    if state["plan_id"] != plan_id:
        raise BrokerCashAuthorityRefused(
            f"plan cash baseline {plan_id} names another plan")
    return PlanCashBaseline(
        plan_id=plan_id, broker=str(state["broker"]),
        account_id=str(state["account_id"]), decision_session=session,
        processed_through=_aware(
            state["processed_through"], where=f"plan cash baseline {plan_id}"),
        balance_total=_finite_decimal(
            state["balance_total"], where=f"plan cash baseline {plan_id} total"))


def record_plan_baseline(conn, *, plan_id: str, decision_session: date,
                         activity_state: CashActivityState) -> PlanCashBaseline:
    """Stamp the cash-activity total under which an immutable plan was sized."""
    existing = load_plan_baseline(conn, plan_id=plan_id)
    candidate = PlanCashBaseline(
        plan_id=plan_id, broker=activity_state.broker,
        account_id=activity_state.account_id,
        decision_session=decision_session,
        processed_through=activity_state.processed_through,
        balance_total=activity_state.balance_total)
    if existing is not None:
        if existing != candidate:
            raise BrokerCashAuthorityRefused(
                f"plan {plan_id} cash baseline is immutable: "
                f"stored={existing}, attempted={candidate}")
        return existing
    payload = {
        "kind": "broker-cash-plan/v1",
        "plan_id": plan_id,
        "broker": activity_state.broker,
        "account_id": activity_state.account_id,
        "processed_through": activity_state.processed_through.isoformat(),
        "balance_total": str(activity_state.balance_total),
    }
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)",
            (_plan_cursor_name(plan_id), decision_session.isoformat(),
             json.dumps(payload, sort_keys=True)))
    return candidate


def activity_delta_for_plan(
        conn, *, plan_id: str, activity_state: CashActivityState) -> Decimal:
    baseline = load_plan_baseline(conn, plan_id=plan_id)
    if baseline is None:
        raise BrokerCashAuthorityRefused(
            f"plan {plan_id} has no broker cash-activity baseline. It predates "
            "the durable account-activity authority and cannot be guessed into "
            "one; prepare a fresh plan after explicitly resolving account cash")
    if (baseline.broker != activity_state.broker
            or baseline.account_id != activity_state.account_id):
        raise BrokerCashAuthorityRefused(
            f"plan {plan_id} cash baseline belongs to another broker account")
    return activity_state.balance_total - baseline.balance_total


__all__ = [
    "ACTIVITY_OVERLAP", "BrokerCashActivity", "BrokerCashActivityBatch",
    "BrokerCashAuthorityRefused", "CashActivityState",
    "EXTERNAL_ACTIVITY_TYPES", "FLOW_PREFIX", "INTERNAL_ACTIVITY_TYPES",
    "PlanCashBaseline", "RECOGNIZED_ACTIVITY_TYPES",
    "activity_delta_for_plan", "broker_flow_id", "broker_flow_is_external",
    "ingest_account_cash", "is_broker_flow", "load_activity_state",
    "load_plan_baseline", "record_plan_baseline",
]
