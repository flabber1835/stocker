"""Durable broker cash evidence and immutable-plan cash baselines.

Issue #183 deliberately reuses two already-authoritative stores rather than
creating a runtime table that the behavioral-schema fingerprint does not know
about:

* ``sentinel_cash_flows`` retains recognized nonzero broker-native cash activities;
  a reserved flow-id/detail encoding distinguishes external capital from
  internal strategy cash without changing the table's physical schema.
* ``sentinel_processed_sessions`` also retains zero-valued native identities and
  is a keyed durable cursor store. Its existing
  Wealth Core row remains ``catchup``; namespaced broker/activity and plan
  baseline rows keep their own validated JSON state and cannot collide with it.

The important separation is ECONOMIC, not storage.  A deposit is external
capital and must be removed from strategy P&L.  A dividend, fee or interest
payment also moves cash, but removing it from P&L would manufacture performance.
Both explain broker cash; only the first class is external capital.
"""
from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import wraps
from itertools import batched
from fractions import Fraction
from collections.abc import Collection, Mapping as MappingView
from typing import Mapping, Optional

from sentinel.execution.contract import Completeness
from sentinel.execution.alpaca_trade_amendments import TradeAmendment
from sentinel.execution.numeric import exact_decimal


FLOW_PREFIX = "broker-cash:v1:"
DETAIL_PREFIX = "broker-cash/v1;"
ACTIVITY_CURSOR_PREFIX = "broker-cash-activity:v1:"
PLAN_BASELINE_PREFIX = "broker-cash-plan:v1:"
ACTIVITY_OVERLAP = timedelta(minutes=5)
# This scheme is earned only by the accepted Alpaca Activity-SSE traversal:
# full owned-account bootstrap, monotonic event cursor, immutable native ref_id,
# and explicit correction/bust refusal.  A timestamp-paged REST activity reader
# does not have equivalent negative-space authority.
ACTIVITY_IDENTITY_SCHEME = "alpaca-activity-sse-cash-ref/v1"
# Compatibility sentinel only.  An append-only identity detects a changed event
# set after publication but can never, by global scheme promotion, prove that a
# particular plan/session interval has finished publishing.  This set is kept
# empty so old state cannot become retroactively authoritative; a future source
# must add immutable plan/session-bound finality evidence, not add a string here.
CLOSE_FINALITY_IDENTITY_SCHEMES: frozenset[str] = frozenset()

# These are capital crossing the owned account boundary rather than strategy
# income or expense. Inter-account cash journals are external to this strategy
# account even when both accounts share a firm owner; their sign carries the
# inbound/outbound direction.
EXTERNAL_ACTIVITY_TYPES = frozenset({
    "CSD", "CSW", "ACATC", "MEM", "JNL", "JNLC"})
INTERNAL_ACTIVITY_TYPES = frozenset({
    "DIV", "SPLIT", "SPIN", "MA", "NC", "REO", "REORG", "VOF", "FIMAT",
    "CIL", "DIVNRA", "DIVWH", "OPCA", "OPASN", "OPEXC", "OPEXP", "OPTRD", "OPCSH",
    "FEE", "INT", "WH",
    "CFEE", "INTNRA", "INTTW", "DIVCGL", "DIVCGS", "DIVFEE",
    "DIVFT", "DIVROC", "DIVTW", "DIVTXEX", "CGD", "PTC", "PTR",
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
    last_event_id: Optional[str] = None
    trade_amendments: tuple[TradeAmendment, ...] = ()
    trade_history: tuple[dict, ...] = ()

    def __post_init__(self) -> None:
        if self.processed_through.tzinfo is None:
            raise ValueError("broker cash activity upper boundary must be timezone-aware")
        if self.last_activity_id is not None and not self.last_activity_id.strip():
            raise ValueError("last_activity_id must be non-empty when present")
        if self.last_event_id is not None and not self.last_event_id.strip():
            raise ValueError("last_event_id must be non-empty when present")


@dataclass(frozen=True)
class CashActivityState:
    broker: str
    account_id: str
    processed_through: datetime
    last_activity_id: Optional[str]
    balance_total: Decimal
    last_event_id: Optional[str] = None
    activity_identity_scheme: Optional[str] = None
    posting_kinds: tuple[tuple[str, str], ...] | None = None
    membership_root: str | None = None
    trade_amendments_applied: bool = False
    trade_amendment_commitment: str | None = None


@dataclass(frozen=True)
class PlanCashBaseline:
    plan_id: str
    broker: str
    account_id: str
    decision_session: date
    processed_through: datetime
    balance_total: Decimal
    # A cumulative total is not an event-set identity: +X followed by -X has
    # the same total while still crossing an unassignable close boundary.  New
    # baselines therefore retain the last recognized non-zero cash activity id
    # as the append-only set witness and the certified producer scheme that
    # gives that id its meaning. Legacy rows deliberately load with no scheme
    # and cannot certify close cash.
    last_activity_id: Optional[str] = None
    activity_identity_scheme: Optional[str] = None
    # v4 is captured once with the plan, never reconstructed for a legacy row.
    # Native reference IDs have no sortable append order; exact membership is
    # needed to distinguish a fee-only suffix from offsetting or revised cash.
    activity_membership: Optional[Collection[tuple[str, str]]] = None

    pending_postings: tuple[str, ...] = ()
    posting_source: tuple[str, str] | None = None

    @property
    def activity_identity_authoritative(self) -> bool:
        return (self.broker == "alpaca"
                and self.activity_identity_scheme == ACTIVITY_IDENTITY_SCHEME)

    @property
    def close_cash_finality_authoritative(self) -> bool:
        # There is deliberately no production shortcut from a cursor scheme to
        # interval finality.  Tests may replace this property to exercise
        # downstream arithmetic with a hypothetical accepted source, but a
        # production implementation needs a separately retained finality
        # witness bound to this plan and its exact close session.
        return False


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


MEMBERSHIP_PREFIX = ACTIVITY_CURSOR_PREFIX + "membership:v1:"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("ascii")).hexdigest()


def _valid_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _member_commitment(flow_id, session, amount, detail):
    exact = Fraction(amount)
    return _digest([flow_id, str(session), exact.numerator, exact.denominator, detail])


def _append_members(conn, state, parent, members):
    if parent is not None and not members:
        return parent
    # Keep the head bounded even on the first lifetime backfill. The cursor witness
    # is in the head so a new plan without carry can stamp it in constant work.
    members = dict(members)
    if state.last_activity_id is not None:
        last = broker_flow_id(broker=state.broker, account_id=state.account_id, activity_id=state.last_activity_id)
        if last not in members:
            raise BrokerCashAuthorityRefused("native membership extension omitted its last activity")
        members[last] = members.pop(last)
    for chunk in batched(members.items(), 128):
        parent = _write_membership_node(conn, state, parent, dict(chunk))
    return parent if parent is not None else _write_membership_node(conn, state, None, {})


def _write_membership_node(conn, state, parent, members):
    node = {"kind": "cash-membership/v1", "broker": state.broker, "account": state.account_id,
            "parent": parent, "members": members}
    root = _digest(node)
    name = MEMBERSHIP_PREFIX + root
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_processed_sessions (cursor_name,session,state)"
                    " VALUES (%s,%s,%s::jsonb) ON CONFLICT (cursor_name) DO NOTHING RETURNING 1",
                    (name, state.processed_through.date(), json.dumps(node)))
        if cur.fetchone() is None:
            cur.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s", (name,))
            row = cur.fetchone()
            if row is None or _read_json_state(row[0], where=name) != node:
                raise BrokerCashAuthorityRefused("immutable native membership node changed")
    return root


def _membership_tip(conn, state):
    name = MEMBERSHIP_PREFIX + state.membership_root
    with conn.cursor() as cur:
        cur.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s", (name,))
        row = cur.fetchone()
    node = _read_json_state(row[0], where=name) if row else None
    if (not isinstance(node, dict) or _digest(node) != state.membership_root or
            node.get("kind") != "cash-membership/v1" or
            (node.get("broker"), node.get("account")) != (state.broker, state.account_id) or
            not isinstance(node.get("members"), dict)):
        raise BrokerCashAuthorityRefused("missing or altered immutable native membership head")
    tip = node["members"]
    last = state.last_activity_id
    if bool(tip) != bool(last) or last and broker_flow_id(
            broker=state.broker, account_id=state.account_id, activity_id=last) not in tip:
        raise BrokerCashAuthorityRefused("current cash cursor disagrees with its immutable membership head")
    return tip


class _MembershipPrefix(MappingView):
    """A read-only prefix of one authenticated chain, shared across restored plans."""

    def __init__(self, rows, start):
        self.rows = rows
        self.start = start

    def __len__(self):
        return len(self.rows) - self.start

    def __iter__(self):
        return (key for key, (index, _) in self.rows.items() if index >= self.start)

    def __getitem__(self, key):
        index, value = self.rows[key]
        if index < self.start:
            raise KeyError(key)
        return value


def membership_prefixes(conn, broker, account_id, root):
    if not _valid_digest(root):
        raise BrokerCashAuthorityRefused("invalid native membership root")
    with conn.cursor() as cur:
        # UNION (distinct) also bounds a corrupt cycle before digest verification.
        cur.execute("WITH RECURSIVE nodes(name,body) AS ("
                    " SELECT cursor_name,state FROM sentinel_processed_sessions WHERE cursor_name=%s"
                    " UNION SELECT s.cursor_name,s.state FROM sentinel_processed_sessions s"
                    " JOIN nodes n ON s.cursor_name=%s || (n.body->>'parent'))"
                    " SELECT name,body FROM nodes", (MEMBERSHIP_PREFIX + root, MEMBERSHIP_PREFIX))
        nodes = dict(cur.fetchall())
    members = {}
    prefixes = {}
    while root is not None:
        prefixes[root] = _MembershipPrefix(members, len(members))
        node = nodes.pop(MEMBERSHIP_PREFIX + root, None)
        if (not isinstance(node, dict) or _digest(node) != root or
                set(node) != {"kind", "broker", "account", "parent", "members"} or
                node["kind"] != "cash-membership/v1" or
                (node["broker"], node["account"]) != (broker, account_id) or
                not isinstance(node["members"], dict)):
            raise BrokerCashAuthorityRefused("missing or altered immutable native membership node")
        prefix = f"{FLOW_PREFIX}{broker}:{account_id}:"
        for key, value in node["members"].items():
            if (not key.startswith(prefix) or not key[len(prefix):].strip() or
                    not _valid_digest(value) or key in members):
                raise BrokerCashAuthorityRefused("invalid or repeated native membership commitment")
            members[key] = (len(members), value)
        root = node["parent"]
        if root is not None and not _valid_digest(root):
            raise BrokerCashAuthorityRefused("invalid native membership parent")
    return prefixes


_membership_observation = ContextVar("native_cash_membership_observation", default=None)


def share_membership_observation(function):
    """Reuse only actual durable cursors inside one synchronous cash decision."""
    @wraps(function)
    def observed(conn, *args, **kwargs):
        token = _membership_observation.set((conn, {}))
        try:
            return function(conn, *args, **kwargs)
        finally:
            _membership_observation.reset(token)
    return observed


def _membership_state(conn, broker, account_id):
    observation = _membership_observation.get()
    if observation is None or observation[0] is not conn:
        return load_activity_state(conn, broker=broker, account_id=account_id)
    states = observation[1]
    key = (broker, account_id)
    if key not in states:
        states[key] = load_activity_state(conn, broker=broker, account_id=account_id)
    return states[key]


def _read_members(conn, broker, account_id, root):
    return _members_at_root(conn, _membership_state(conn, broker, account_id), root)


def _members_at_root(conn, state, root):
    if state is None or state.membership_root is None:
        raise BrokerCashAuthorityRefused("plan membership has no anchored account cash cursor")
    prefixes = membership_prefixes(conn, state.broker, state.account_id, state.membership_root)
    if root not in prefixes:
        raise BrokerCashAuthorityRefused("plan membership is outside the account cash chain")
    return prefixes[root]


def _native_cash_ledger(conn, *, broker: str, account_id: str):
    """Return exact account-native rows; dates and insert clocks are not order."""
    prefix = f"{FLOW_PREFIX}{broker}:{account_id}:"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT flow_id,session,amount,detail FROM sentinel_cash_flows"
            " WHERE LEFT(flow_id,LENGTH(%s))=%s ORDER BY flow_id",
            (prefix, prefix))
        rows = cur.fetchall()
    result = {}
    for flow_id, session, amount, detail in rows:
        native_id = str(flow_id)[len(prefix):]
        parts = str(detail).split(";", 3)
        activity_type = (parts[2][5:] if len(parts) == 4
                         and parts[2].startswith("type=") else None)
        value = _finite_decimal(amount, where="native cash ledger amount")
        if (not native_id.strip() or activity_type not in RECOGNIZED_ACTIVITY_TYPES
                or value == 0):
            raise BrokerCashAuthorityRefused("native cash ledger row is malformed")
        activity = BrokerCashActivity(native_id, activity_type, session, value, {})
        if str(detail) != _detail(activity):
            raise BrokerCashAuthorityRefused("native cash ledger classification changed")
        exact = Fraction(value)
        commitment = _member_commitment(str(flow_id), session, exact, str(detail))
        result[str(flow_id)] = (commitment, exact, str(detail))
    return result


def _current_cash_ledger(conn, *, activity_state: CashActivityState):
    if (activity_state.broker != "alpaca"
            or activity_state.activity_identity_scheme != ACTIVITY_IDENTITY_SCHEME
            or _membership_state(conn, activity_state.broker, activity_state.account_id) != activity_state):
        raise BrokerCashAuthorityRefused(
            "native cash membership requires the actual current Activity-SSE cursor")
    rows = _native_cash_ledger(conn, broker=activity_state.broker,
                               account_id=activity_state.account_id)
    last = (None if activity_state.last_activity_id is None else broker_flow_id(
        broker=activity_state.broker, account_id=activity_state.account_id,
        activity_id=activity_state.last_activity_id))
    if (sum((row[1] for row in rows.values()), Fraction(0))
            != Fraction(activity_state.balance_total)
            or bool(rows) != (last is not None)
            or (last is not None and last not in rows)):
        raise BrokerCashAuthorityRefused(
            "native cash membership disagrees with its durable cursor")
    return rows


def _debit_fee_membership(*, baseline, activity_state, rows) -> bool:
    """Evaluate an original boundary against the owner's private current rows."""
    if baseline.activity_membership is None:
        return False  # No retroactive membership or legacy baseline promotion.
    if (not baseline.activity_identity_authoritative
            or baseline.broker != activity_state.broker
            or baseline.account_id != activity_state.account_id
            or activity_state.processed_through < baseline.processed_through):
        raise BrokerCashAuthorityRefused("native cash membership boundary changed")
    original = dict(baseline.activity_membership)
    if any(key not in rows or rows[key][0] != commitment
           for key, commitment in original.items()):
        raise BrokerCashAuthorityRefused("immutable plan native cash membership changed")
    if sum((rows[key][1] for key in original), Fraction(0)) != Fraction(baseline.balance_total):
        raise BrokerCashAuthorityRefused("immutable plan native cash total changed")
    added = {key: row for key, row in rows.items() if key not in original}
    prefix = f"{FLOW_PREFIX}{activity_state.broker}:{activity_state.account_id}:"
    if not added:
        if (activity_state.last_activity_id != baseline.last_activity_id
                or activity_state.balance_total != baseline.balance_total):
            raise BrokerCashAuthorityRefused("native cash cursor changed without new members")
        return False
    last = broker_flow_id(broker=activity_state.broker,
        account_id=activity_state.account_id, activity_id=activity_state.last_activity_id)
    if (last not in added
            or sum((row[1] for row in added.values()), Fraction(0))
            != Fraction(activity_state.balance_total) - Fraction(baseline.balance_total)):
        raise BrokerCashAuthorityRefused("new native fee membership is inconsistent")
    if any(row[1] >= 0 or row[2] != (
            f"{DETAIL_PREFIX}class=INTERNAL;type=FEE;id={key[len(prefix):]}")
           for key, row in added.items()):
        return False
    return True


def activity_boundaries_are_debit_fees_only(
        conn, *, baselines: tuple[PlanCashBaseline, ...],
        activity_state: CashActivityState) -> tuple[bool, ...]:
    """One fresh native read for multiple immutable boundaries in one admission."""
    rows = _current_cash_ledger(conn, activity_state=activity_state)
    return tuple(_debit_fee_membership(baseline=baseline, activity_state=activity_state,
        rows=rows) for baseline in baselines)


def plan_activity_is_debit_fees_only(
        conn, *, baseline: PlanCashBaseline, activity_state: CashActivityState) -> bool:
    """Earn only the named FEE exception, without changing an immutable plan."""
    if baseline.activity_membership is None:
        return False  # A legacy caller cannot acquire membership retrospectively.
    return activity_boundaries_are_debit_fees_only(
        conn, baselines=(baseline,), activity_state=activity_state)[0]


def capture_activity_membership(conn, *, activity_state: CashActivityState):
    """Capture a new immutable native boundary in the caller's writer scope."""
    return tuple((key, row[0]) for key, row in _current_cash_ledger(
        conn, activity_state=activity_state).items())


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
    v1 = {"kind", "broker", "account_id", "processed_through",
          "last_activity_id", "balance_total"}
    v2 = v1 | {"last_event_id"}
    v3 = v2 | {"activity_identity_scheme"}
    v4 = v3 | {'posting_kinds'}
    amendment_commitment = None
    if state.get("kind") == "broker-cash-activity/v6":
        from sentinel.execution.alpaca_trade_amendments import commitment
        state = dict(state)
        amendment_commitment = state.pop("trade_amendment_commitment", None)
        if not _valid_digest(amendment_commitment) or commitment(conn) != amendment_commitment:
            raise BrokerCashAuthorityRefused("trade amendment evidence disagrees with the cash cursor")
        state["kind"] = "broker-cash-activity/v5"
    root = state.get('membership_root')
    if state.get('kind') == 'broker-cash-activity/v5':
        if not _valid_digest(root):
            raise BrokerCashAuthorityRefused('invalid native cash cursor membership root')
        state = dict(state)
        del state['membership_root']
        state['kind'] = 'broker-cash-activity/v4' if 'posting_kinds' in state else 'broker-cash-activity/v3'
    state_keys = frozenset(state)
    if (state_keys not in {frozenset(v1), frozenset(v2), frozenset(v3), frozenset(v4)}
            or state.get("kind") not in {
                "broker-cash-activity/v1", "broker-cash-activity/v2",
                "broker-cash-activity/v3", "broker-cash-activity/v4"}):
        raise BrokerCashAuthorityRefused(
            f"cash activity cursor {name} has an unknown state shape")
    if ((state.get("kind") == "broker-cash-activity/v1" and set(state) != v1)
            or (state.get("kind") == "broker-cash-activity/v2"
                and set(state) != v2)
            or (state.get("kind") == "broker-cash-activity/v3"
                and set(state) != v3)
            or (state.get('kind') == 'broker-cash-activity/v4' and set(state) != v4)):
        raise BrokerCashAuthorityRefused(
            f"cash activity cursor {name} mixes incompatible schema fields")
    if state["broker"] != broker or state["account_id"] != account_id:
        raise BrokerCashAuthorityRefused(
            f"cash activity cursor {name} is bound to another account")
    last_id = state["last_activity_id"]
    if last_id is not None and (not isinstance(last_id, str) or not last_id.strip()):
        raise BrokerCashAuthorityRefused(
            f"cash activity cursor {name} has an invalid native id")
    last_event_id = state.get("last_event_id")
    if (last_event_id is not None
            and (not isinstance(last_event_id, str)
                 or not last_event_id.strip())):
        raise BrokerCashAuthorityRefused(
            f"cash activity cursor {name} has an invalid event cursor")
    identity_scheme = state.get("activity_identity_scheme")
    if (identity_scheme is not None
            and identity_scheme != ACTIVITY_IDENTITY_SCHEME):
        raise BrokerCashAuthorityRefused(
            f"cash activity cursor {name} has an unrecognized identity scheme")
    if identity_scheme is not None and broker not in {"alpaca", "alpaca-live"}:
        raise BrokerCashAuthorityRefused(
            f"cash activity cursor {name} applies the Alpaca Activity-SSE "
            "identity scheme to another broker")
    kinds = state.get('posting_kinds')
    if 'posting_kinds' in state and (identity_scheme != ACTIVITY_IDENTITY_SCHEME
            or not isinstance(kinds, dict) or any(not isinstance(k, str) or not k
                or v not in ('CDIV', 'FEE') for k, v in kinds.items())):
        raise BrokerCashAuthorityRefused('invalid cash posting classification')
    return CashActivityState(
        broker=broker, account_id=account_id,
        processed_through=_aware(
            state["processed_through"], where=f"cash activity cursor {name}"),
        last_activity_id=last_id,
        balance_total=_finite_decimal(
            state["balance_total"], where=f"cash activity cursor {name} total"),
        last_event_id=last_event_id,
        activity_identity_scheme=identity_scheme,
        posting_kinds=None if kinds is None else tuple(sorted(kinds.items())), membership_root=root,
        trade_amendment_commitment=amendment_commitment)


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
    flow_id = broker_flow_id(
        broker=broker, account_id=account_id,
        activity_id=activity.activity_id)
    detail = _detail(activity)
    zero_name = f"broker-cash-zero:v1:{broker}:{account_id}:{activity.activity_id}"
    zero_payload = {"kind": "broker-cash-zero/v1", "detail": detail}
    with conn.cursor() as cur:
        # A zero amount is not a cash flow, but its native identity must survive
        # restart. Both stores share the caller's writer lock and transaction.
        cur.execute(
            "SELECT session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s", (zero_name,))
        zero = cur.fetchone()
        if zero is not None:
            if (activity.net_amount != 0
                    or str(zero[0]) != activity.activity_date.isoformat()
                    or _read_json_state(zero[1], where=zero_name) != zero_payload):
                raise BrokerCashAuthorityRefused(
                    f"broker activity id {activity.activity_id!r} changed economics "
                    "from retained zero evidence")
            return False
        if activity.net_amount == 0:
            cur.execute(
                "SELECT session,amount,detail FROM sentinel_cash_flows"
                " WHERE flow_id=%s", (flow_id,))
            if cur.fetchone() is not None:
                raise BrokerCashAuthorityRefused(
                    f"broker activity id {activity.activity_id!r} changed economics "
                    "from a retained cash flow to zero")
            cur.execute(
                "INSERT INTO sentinel_processed_sessions"
                " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)",
                (zero_name, activity.activity_date.isoformat(),
                 json.dumps(zero_payload, sort_keys=True)))
            return False
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
        through: Optional[datetime] = None, qualify_postings: bool = False) -> CashActivityState:
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
    financial_sse = (
        getattr(broker_adapter, "financial_activity_sse", False) is True)
    if financial_sse and broker not in {"alpaca", "alpaca-live"}:
        raise BrokerCashAuthorityRefused(
            "the certified Activity-SSE cash identity scheme is Alpaca-only")
    if (prior is not None
            and prior.activity_identity_scheme == ACTIVITY_IDENTITY_SCHEME
            and not financial_sse):
        raise BrokerCashAuthorityRefused(
            "an authoritative Activity-SSE cash cursor cannot be downgraded "
            "to timestamp-paged activity ingestion")
    track_postings = financial_sse and (qualify_postings or (prior is not None and prior.posting_kinds is not None))
    replay_kinds = track_postings and prior is not None and prior.posting_kinds is None
    missing_last_flow = False
    if prior is not None:
        if prior.membership_root is not None:
            _membership_tip(conn, prior)
        # A cursor survives a table-selective restore independently of its
        # ledger. Reusing it would either forget prior cash or count replayed
        # activities twice. The total is immediate authority. A missing legacy
        # last-id is provisionally checked against the complete broker replay
        # below because zero-value activities intentionally have no cash row.
        prefix = f"{FLOW_PREFIX}{broker}:{account_id}:"
        last_flow = (broker_flow_id(broker=broker, account_id=account_id,
                                   activity_id=prior.last_activity_id)
                     if prior.last_activity_id is not None else None)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(amount),0),"
                " COALESCE(BOOL_OR(flow_id=%s),false)"
                " FROM sentinel_cash_flows"
                " WHERE LEFT(flow_id,LENGTH(%s))=%s",
                (last_flow, prefix, prefix))
            ledger_total, has_last = cur.fetchone()
        if Decimal(str(ledger_total)) != prior.balance_total:
            raise BrokerCashAuthorityRefused(
                "broker cash ledger disagrees with its durable cursor; "
                "restore the complete behavioral state")
        missing_last_flow = last_flow is not None and not has_last
        if upper < prior.processed_through:
            raise BrokerCashAuthorityRefused(
                "broker cash ingestion clock moved behind its durable cursor")
        if upper == prior.processed_through and not missing_last_flow and not replay_kinds:
            return prior
        # A v1 cursor is only a business-time boundary. It cannot resume the
        # Activity SSE without gaps because a backfill is published later with
        # its old ``at`` value. Replay from binding establishment until the
        # first durable event_id is earned. Once present, event_id is the sole
        # resumption authority; ``after`` remains a bounded bootstrap input.
        after = (established if (financial_sse and prior.last_event_id is None) else
                 max(established, prior.processed_through - ACTIVITY_OVERLAP))
        running_total = Fraction(prior.balance_total)
    else:
        after = established
        running_total = Fraction(0)
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

    if financial_sse or missing_last_flow:
        # Capturing the bounded upper event_id must cover the whole owned
        # account interval so a newly published event with old business time is
        # visible. A missing ledger witness also needs the owned interval:
        # its last zero-value activity may predate the normal overlap.
        after = established
    activity_kwargs = {"after": after, "through": upper}
    if (prior is not None and prior.last_event_id is not None and financial_sse
            and not missing_last_flow and not replay_kinds):
        activity_kwargs["since_event_id"] = prior.last_event_id
    batch = await broker_adapter.account_cash_activities(**activity_kwargs)
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
    if batch.trade_amendments and (not financial_sse or batch.last_event_id is None
            or batch.trade_amendments[-1].event_id > batch.last_event_id):
        raise BrokerCashAuthorityRefused("trade amendments require qualified bounded activity replay")
    from sentinel.execution import alpaca_trade_amendments
    try:
        amendments_applied = await alpaca_trade_amendments.apply(
            conn, broker_adapter=broker_adapter, broker=broker, account_id=account_id,
            amendments=batch.trade_amendments, trade_history=batch.trade_history)
    except alpaca_trade_amendments.TradeAmendmentRefused as exc:
        raise BrokerCashAuthorityRefused(str(exc)) from exc

    if missing_last_flow:
        prior_activity = next(
            (activity for activity in batch.activities
             if activity.activity_id == prior.last_activity_id), None)
        if prior_activity is None or prior_activity.net_amount != 0:
            raise BrokerCashAuthorityRefused(
                "broker cash ledger is missing its durable last activity and "
                "the complete replay does not prove it was a zero-value event; "
                "restore the complete behavioral state")

    posting_kinds = dict(prior.posting_kinds or ()) if prior else {}
    if replay_kinds:
        retained = _native_cash_ledger(conn, broker=broker, account_id=account_id)
        prefix = f"{FLOW_PREFIX}{broker}:{account_id}:"
        replayed = {prefix + item.activity_id for item in batch.activities if item.net_amount}
        if not retained.keys() <= replayed or (prior.last_event_id is not None
                and (batch.last_event_id is None or batch.last_event_id < prior.last_event_id)):
            raise BrokerCashAuthorityRefused("posting classification replay omitted retained evidence")
    seen: set[str] = set()
    # A proven zero-value legacy last-id was a traversal cursor, not a ledger
    # witness. Normalize it away. New state retains only an activity that has a
    # materialized nonzero cash row, keeping the restore invariant truthful.
    last_id = (None if missing_last_flow else
               (prior.last_activity_id if prior else None))
    additions = {}
    for activity in batch.activities:
        if activity.activity_id in seen:
            raise BrokerCashAuthorityRefused(
                f"broker cash batch repeats native id {activity.activity_id}")
        seen.add(activity.activity_id)
        inserted = _insert_activity(
            conn, broker=broker, account_id=account_id,
            activity=activity)
        if track_postings:
            raw = activity.raw
            kind = None
            if (raw.get("currency") == "USD" and raw.get("status") == "executed"
                    and raw.get("ref_id") == activity.activity_id and not raw.get("previous_id")):
                if (activity.activity_type == "DIV" and raw.get("activity_subtype") == "CDIV"
                        and activity.net_amount > 0):
                    kind = "CDIV"
                elif activity.activity_type == "FEE" and activity.net_amount < 0:
                    kind = "FEE"
            if not inserted and not replay_kinds and posting_kinds.get(activity.activity_id) != kind:
                raise BrokerCashAuthorityRefused("replayed cash posting classification changed")
            if kind is not None:
                posting_kinds[activity.activity_id] = kind
        if inserted:
            if financial_sse:
                key = broker_flow_id(broker=broker, account_id=account_id, activity_id=activity.activity_id)
                additions[key] = _member_commitment(key, activity.activity_date, activity.net_amount, _detail(activity))
            running_total += Fraction(activity.net_amount)
            last_id = activity.activity_id
    if batch.last_activity_id is not None:
        if batch.activities and batch.last_activity_id != batch.activities[-1].activity_id:
            raise BrokerCashAuthorityRefused(
                "broker cash batch last native id does not match final activity")
        # ``batch.last_activity_id`` is traversal evidence and may identify a
        # zero-value SPLIT/REORG. It is deliberately not promoted to the cash
        # ledger witness unless that event produced a materialized row above.

    last_event_id = prior.last_event_id if prior else None
    if batch.last_event_id is not None:
        if (last_event_id is not None
                and batch.last_event_id < last_event_id):
            raise BrokerCashAuthorityRefused(
                "broker cash activity event cursor regressed")
        last_event_id = batch.last_event_id

    balance_total = exact_decimal(running_total)
    amendment_commitment = (alpaca_trade_amendments.commitment(conn) if amendments_applied else
                            (prior.trade_amendment_commitment if prior is not None else None))
    state = CashActivityState(
        broker=broker, account_id=account_id, processed_through=upper,
        last_activity_id=last_id, balance_total=balance_total,
        last_event_id=last_event_id,
        activity_identity_scheme=(
            ACTIVITY_IDENTITY_SCHEME if financial_sse else None),
        posting_kinds=tuple(sorted(posting_kinds.items())) if track_postings else None,
        trade_amendments_applied=amendments_applied, trade_amendment_commitment=amendment_commitment)
    payload = {
        "kind": ("broker-cash-activity/v3" if financial_sse
                 else "broker-cash-activity/v2"),
        "broker": broker,
        "account_id": account_id,
        "processed_through": upper.isoformat(),
        "last_activity_id": last_id,
        "last_event_id": last_event_id,
        "balance_total": str(balance_total),
    }
    if track_postings:
        payload.update(kind="broker-cash-activity/v4", posting_kinds=posting_kinds)
    if financial_sse:
        parent = prior.membership_root if prior else None
        if prior is not None and parent is None:
            # First new-scheme ingestion on a legacy account commits its verified ledger once.
            ledger = _native_cash_ledger(conn, broker=broker, account_id=account_id)
            last = broker_flow_id(broker=broker, account_id=account_id, activity_id=last_id) if last_id else None
            if (sum((row[1] for row in ledger.values()), Fraction(0)) != running_total
                    or bool(ledger) != bool(last) or last and last not in ledger):
                raise BrokerCashAuthorityRefused("legacy native membership disagrees with durable cursor")
            additions = {key: row[0] for key, row in ledger.items()}
        state = replace(state, membership_root=_append_members(conn, state, parent, additions))
        payload.update(kind="broker-cash-activity/v5", membership_root=state.membership_root,
                       activity_identity_scheme=ACTIVITY_IDENTITY_SCHEME)
        if amendment_commitment is not None:
            payload.update(kind="broker-cash-activity/v6",
                           trade_amendment_commitment=amendment_commitment)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
            " ON CONFLICT (cursor_name) DO UPDATE SET"
            " session=EXCLUDED.session,state=EXCLUDED.state,updated_at=NOW()",
            (_activity_cursor_name(broker, account_id), upper.date().isoformat(),
             json.dumps(payload, sort_keys=True)))
    return state


def _plan_baseline_row(conn, plan_id):
    with conn.cursor() as cur:
        cur.execute("SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s",
                    (_plan_cursor_name(plan_id),))
        return cur.fetchone()


def load_plan_baseline(conn, *, plan_id: str) -> Optional[PlanCashBaseline]:
    row = _plan_baseline_row(conn, plan_id)
    if row is None:
        return None
    return decode_plan_baseline(plan_id, row, conn=conn)


def decode_plan_baseline(plan_id: str, row, *, conn=None, read_members=None) -> PlanCashBaseline:
    """Validate the stored (session, state) row against its exact plan key."""
    session = row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0]))
    state = _read_json_state(row[1], where=f"plan cash baseline {plan_id}")
    v1 = {"kind", "plan_id", "broker", "account_id",
          "processed_through", "balance_total"}
    v2 = v1 | {"last_activity_id"}
    v3 = v2 | {"activity_identity_scheme"}
    v4 = v3 | {"activity_membership"}
    carry = {"pending_postings", "posting_source"}
    v6 = v3 | {"membership_root"}
    shapes = {"broker-cash-plan/v1": (v1,), "broker-cash-plan/v2": (v2,),
              "broker-cash-plan/v3": (v3,), "broker-cash-plan/v4": (v4,),
              "broker-cash-plan/v5": (v4 | carry,), "broker-cash-plan/v6": (v6, v6 | carry)}
    if set(state) not in shapes.get(state.get("kind"), ()):
        raise BrokerCashAuthorityRefused(f"plan cash baseline {plan_id} has an unknown state shape")
    if state["plan_id"] != plan_id:
        raise BrokerCashAuthorityRefused(
            f"plan cash baseline {plan_id} names another plan")
    last_activity_id = state.get("last_activity_id")
    if (last_activity_id is not None
            and (not isinstance(last_activity_id, str)
                 or not last_activity_id.strip())):
        raise BrokerCashAuthorityRefused(
            f"plan cash baseline {plan_id} has an invalid activity identity")
    identity_scheme = state.get("activity_identity_scheme")
    if (identity_scheme is not None
            and identity_scheme != ACTIVITY_IDENTITY_SCHEME):
        raise BrokerCashAuthorityRefused(
            f"plan cash baseline {plan_id} has an unrecognized identity scheme")
    if identity_scheme is not None and state["broker"] != "alpaca":
        raise BrokerCashAuthorityRefused(
            f"plan cash baseline {plan_id} applies the Alpaca Activity-SSE "
            "identity scheme to another broker")
    membership = None
    raw_membership = {}
    prefix = f"{FLOW_PREFIX}{state['broker']}:{state['account_id']}:"
    if state["kind"] in {"broker-cash-plan/v4", "broker-cash-plan/v5"}:
        raw_membership = state["activity_membership"]
        if (identity_scheme != ACTIVITY_IDENTITY_SCHEME
                or not isinstance(raw_membership, dict)
                or any(not isinstance(key, str) or not key.startswith(prefix)
                       or not key[len(prefix):].strip()
                       or not isinstance(value, str) or len(value) != 64
                       or any(char not in "0123456789abcdef" for char in value)
                       for key, value in raw_membership.items())):
            raise BrokerCashAuthorityRefused("plan cash membership has an invalid shape")
    elif state["kind"] == "broker-cash-plan/v6":
        if identity_scheme != ACTIVITY_IDENTITY_SCHEME or not _valid_digest(state["membership_root"]):
            raise BrokerCashAuthorityRefused("invalid immutable cash membership authority")
        resolver = read_members or (lambda b, a, r: _read_members(conn, b, a, r))
        raw_membership = resolver(state["broker"], state["account_id"], state["membership_root"])
    if state["kind"] in {"broker-cash-plan/v4", "broker-cash-plan/v5", "broker-cash-plan/v6"}:
        last_flow = (None if last_activity_id is None else prefix + last_activity_id)
        if (bool(raw_membership) != (last_flow is not None)
                or (last_flow is not None and last_flow not in raw_membership)):
            raise BrokerCashAuthorityRefused("plan cash membership has no original last identity")
        membership = (raw_membership.items() if read_members else tuple(sorted(raw_membership.items())))
    pending = state.get("pending_postings", [])
    if (not isinstance(pending, list) or any(type(k) is not str for k in pending)
            or pending != sorted(set(pending)) or any(k not in raw_membership for k in pending)
            or ("pending_postings" in state and not pending)):
        raise BrokerCashAuthorityRefused("invalid immutable pending posting membership")
    source = state.get("posting_source")
    if pending and (not isinstance(source, list) or len(source) != 2
            or not isinstance(source[0], str) or not source[0] or source[0] == plan_id
            or not isinstance(source[1], str) or len(source[1]) != 64
            or any(char not in "0123456789abcdef" for char in source[1])):
        raise BrokerCashAuthorityRefused("invalid predecessor for immutable pending postings")
    return PlanCashBaseline(
        plan_id=plan_id, broker=str(state["broker"]),
        account_id=str(state["account_id"]), decision_session=session,
        processed_through=_aware(
            state["processed_through"], where=f"plan cash baseline {plan_id}"),
        balance_total=_finite_decimal(
            state["balance_total"], where=f"plan cash baseline {plan_id} total"),
        last_activity_id=last_activity_id,
        activity_identity_scheme=identity_scheme,
        activity_membership=membership, pending_postings=tuple(pending),
        posting_source=tuple(source) if source else None)


def record_plan_baseline(conn, *, plan_id: str, decision_session: date,
                         activity_state: CashActivityState,
                         pending_postings: tuple[str, ...] = (),
                         posting_source: tuple[str, str] | None = None,
                         return_baseline: bool = True) -> PlanCashBaseline | None:
    """Stamp the cash-activity total under which an immutable plan was sized."""
    if (activity_state.broker != "alpaca"
            or activity_state.activity_identity_scheme
            != ACTIVITY_IDENTITY_SCHEME):
        raise BrokerCashAuthorityRefused(
            "plan cash baseline requires the certified append-only Activity "
            "SSE cash identity scheme; timestamp-paged activity state cannot "
            "prove an unchanged event set")
    stored = _plan_baseline_row(conn, plan_id)
    existing = None
    root = activity_state.membership_root
    if stored is not None:
        previous = _read_json_state(stored[1], where=f"plan cash baseline {plan_id}")
        bounded_members = None
        if previous.get("kind") == "broker-cash-plan/v6":
            if root is None or root != previous.get("membership_root"):
                raise BrokerCashAuthorityRefused(f"plan {plan_id} cash baseline is immutable")
            if not return_baseline and not pending_postings:
                current = load_activity_state(conn, broker=activity_state.broker, account_id=activity_state.account_id)
                if current != activity_state:
                    raise BrokerCashAuthorityRefused("native membership requires the actual current Activity-SSE cursor")
                tip = _membership_tip(conn, current)
                bounded_members = lambda *_: tip
        existing = decode_plan_baseline(plan_id, stored, conn=conn, read_members=bounded_members)
    if existing is not None:
        members = existing.activity_membership
    elif root is not None:
        if load_activity_state(conn, broker=activity_state.broker, account_id=activity_state.account_id) != activity_state:
            raise BrokerCashAuthorityRefused("native membership requires the actual current Activity-SSE cursor")
        if return_baseline or pending_postings:
            members = tuple(sorted(_members_at_root(conn, activity_state, root).items()))
        else:
            members = tuple(_membership_tip(conn, activity_state).items())
    else:
        members = capture_activity_membership(conn, activity_state=activity_state)
    candidate = PlanCashBaseline(
        plan_id=plan_id, broker=activity_state.broker,
        account_id=activity_state.account_id,
        decision_session=decision_session,
        processed_through=activity_state.processed_through,
        balance_total=activity_state.balance_total,
        last_activity_id=activity_state.last_activity_id,
        activity_identity_scheme=activity_state.activity_identity_scheme,
        pending_postings=pending_postings, posting_source=posting_source,
        activity_membership=members)
    if existing is not None:
        if existing != candidate:
            raise BrokerCashAuthorityRefused(
                f"plan {plan_id} cash baseline is immutable: "
                f"stored={existing}, attempted={candidate}")
        return existing if return_baseline else None
    payload = {
        "kind": "broker-cash-plan/v6",
        "plan_id": plan_id,
        "broker": activity_state.broker,
        "account_id": activity_state.account_id,
        "processed_through": activity_state.processed_through.isoformat(),
        "balance_total": str(activity_state.balance_total),
        "last_activity_id": activity_state.last_activity_id,
        "activity_identity_scheme": activity_state.activity_identity_scheme,
        "membership_root": root,
    }
    if root is None:
        del payload["membership_root"]
        payload.update(kind="broker-cash-plan/v5" if pending_postings else "broker-cash-plan/v4",
                       activity_membership=dict(members))
    if bool(pending_postings) != bool(posting_source):
        raise BrokerCashAuthorityRefused("pending posts must carry their predecessor observation")
    if pending_postings:
        if (pending_postings != tuple(sorted(set(pending_postings)))
                or not set(pending_postings) <= dict(candidate.activity_membership).keys()):
            raise BrokerCashAuthorityRefused("pending cash postings lack original native membership")
        payload.update(pending_postings=list(pending_postings),
                       posting_source=list(posting_source))
    decode_plan_baseline(plan_id, (decision_session, payload), read_members=lambda *_: dict(members))
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)",
            (_plan_cursor_name(plan_id), decision_session.isoformat(),
             json.dumps(payload, sort_keys=True)))
    return candidate if return_baseline else None


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
    return exact_decimal(Fraction(activity_state.balance_total) - Fraction(baseline.balance_total))


__all__ = [
    "ACTIVITY_IDENTITY_SCHEME", "ACTIVITY_OVERLAP",
    "CLOSE_FINALITY_IDENTITY_SCHEMES", "BrokerCashActivity",
    "BrokerCashActivityBatch",
    "BrokerCashAuthorityRefused", "CashActivityState",
    "EXTERNAL_ACTIVITY_TYPES", "FLOW_PREFIX", "INTERNAL_ACTIVITY_TYPES",
    "PlanCashBaseline", "RECOGNIZED_ACTIVITY_TYPES",
    "activity_delta_for_plan", "broker_flow_id", "broker_flow_is_external",
    "ingest_account_cash", "is_broker_flow", "load_activity_state",
    "load_plan_baseline", "record_plan_baseline",
]
