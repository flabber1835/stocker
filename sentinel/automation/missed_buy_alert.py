"""Positive, saved evidence for a clean opening that missed only BUY transport.

This is a one-time notifier read at the fenced terminal transition. It neither
grants execution authority nor refreshes the broker; ambiguity returns None.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from time import monotonic


_ACTIVE = (
    "PLANNED", "SEND_PENDING", "ACKNOWLEDGED", "UNKNOWN",
    "PARTIALLY_FILLED", "CANCEL_PENDING",
)
_TERMINAL = frozenset({"FILLED", "CANCELLED", "REJECTED", "SUPERSEDED"})


def _positive_decimal(value) -> Decimal | None:
    if not isinstance(value, str):
        return None
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result > 0 else None


def _positions(payload) -> dict[str, Decimal] | None:
    rows = payload.get("positions")
    if not isinstance(rows, list) or len(rows) > 100:
        return None
    result = {}
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("security_id"), str):
            return None
        sid = row["security_id"]
        if not sid or sid in result:
            return None
        try:
            qty = Decimal(str(row["quantity"]))
        except (KeyError, InvalidOperation, TypeError, ValueError):
            return None
        if not qty.is_finite() or qty < 0:
            return None
        result[sid] = qty
    return {sid: qty for sid, qty in result.items() if qty}


def _no_transport_events(conn, command, *, execute_at, as_of, deadline) -> bool:
    """Allow only the canonical restored checkpoint chain, never a send outcome."""
    if monotonic() >= deadline:
        return False
    events = conn.execute(
        "SELECT from_state,to_state,filled_quantity,detail,at "
        "FROM sentinel_command_events WHERE client_key=%s ORDER BY seq LIMIT 101",
        (command.client_key,)).fetchall()
    if not events or len(events) > 100:
        return False
    first = events[0]
    if (first[0] is not None or first[1] != "PLANNED" or first[2] != 0
            or not isinstance(first[4], datetime)
            or not execute_at <= first[4] <= as_of):
        return False
    pending, previous_at = False, first[4]
    for source, target, filled, detail, at in events[1:]:
        if (filled != 0 or not isinstance(at, datetime)
                or not previous_at <= at <= as_of):
            return False
        if not pending and (source, target) == ("PLANNED", "SEND_PENDING"):
            pending = True
        elif (pending and (source, target) == ("SEND_PENDING", "PLANNED")
              and isinstance(detail, str)
              and detail.startswith("PRE_TRANSPORT_CHECKPOINT_RESTORED: ")):
            pending = False
        else:
            return False
        previous_at = at
    return not pending


def _observation(conn, seq, *, cycle, expected, as_of, planned_keys,
                 current_plan_keys, no_command_buy_ids, deadline):
    from sentinel.execution import journal

    if monotonic() >= deadline:
        return None
    row = conn.execute(
        "SELECT observed_at,runtime_state,completeness FROM sentinel_observations "
        "WHERE seq=%s", (seq,)).fetchone()
    if monotonic() >= deadline:
        return None
    if (row is None or row[1:] != ("RUNNING", "COMPLETE")
            or not isinstance(row[0], datetime)
            or not cycle.execute_at <= row[0] <= as_of):
        return None
    payload = journal.load_observation_payload(conn, seq)
    if monotonic() >= deadline:
        return None
    if (payload.get("completeness") != "COMPLETE"
            or (payload.get("broker"), payload.get("account_id"))
                != (cycle.broker, cycle.broker_account_id)
            or _positions(payload) != expected):
        return None
    orders, exact = payload.get("orders"), payload.get("exact_evidence")
    if (not isinstance(orders, list) or len(orders) > 100
            or not isinstance(exact, list) or len(exact) > 100):
        return None
    native = list(orders)
    for item in exact:
        if (not isinstance(item, Mapping)
                or not isinstance(item.get("client_key"), str)):
            return None
        order = item.get("order")
        if order is None:
            continue
        if item["client_key"] in planned_keys or not isinstance(order, Mapping):
            return None
        native.append(order)
    by_key = {}
    for order in native:
        if (not isinstance(order, Mapping)
                or not isinstance(order.get("client_key"), str)
                or not order["client_key"]
                or order["client_key"] in planned_keys
                or not isinstance(order.get("security_id"), str)
                or order.get("state") not in _TERMINAL):
            return None
        key = order["client_key"]
        previous = by_key.setdefault(key, order)
        if (previous["state"], previous["security_id"]) != (
                order["state"], order["security_id"]):
            return None
    keys = set(by_key)
    if monotonic() >= deadline:
        return None
    known = conn.execute(
        "SELECT client_key,plan_id,deployment_id,broker,broker_account_id,"
        "takeover_epoch,security_id FROM sentinel_commands "
        "WHERE client_key=ANY(%s)", (sorted(keys),)).fetchall() if keys else []
    if monotonic() >= deadline:
        return None
    if len(known) != len(keys):
        return None
    for key, plan_id, deployment, broker, account, epoch, sid in known:
        if ((deployment, broker, account, epoch) != (
                cycle.deployment_id, cycle.broker, cycle.broker_account_id,
                cycle.takeover_epoch)
                or (plan_id == cycle.plan_id and key not in current_plan_keys)
                or (plan_id == cycle.plan_id and sid in no_command_buy_ids)
                or (sid in no_command_buy_ids and plan_id != cycle.plan_id
                    and by_key[key]['state'] != 'FILLED')):
            return None
    return row[0]


def prove(conn, cycle, control, *, diagnostic, clean_id) -> dict | None:
    """Return a narrow immutable-event witness, or None for any uncertainty."""
    from sentinel.dual_plan_authority import load_authority
    from sentinel.execution import journal, target_reprojection
    from sentinel.execution.identity import DeploymentIdentity
    from sentinel.paper_plan_preview import project_original_intent

    deadline = monotonic() + 4.0
    if (cycle.historical_state_only or cycle.attempt_count <= 0 or not cycle.plan_id
            or not cycle.plan_fingerprint or control.binding is None
            or cycle.control_generation != control.generation
            or (cycle.deployment_id, cycle.broker, cycle.broker_account_id,
                cycle.takeover_epoch, cycle.config_sha256)
                != (control.binding.deployment_id, control.binding.broker,
                    control.binding.broker_account_id, control.binding.takeover_epoch,
                    control.config_sha256)
            or not isinstance(diagnostic, Mapping)
            or diagnostic.get("clean") is not True
            or diagnostic.get("runtime_state") != "RUNNING"
            or diagnostic.get("terminal_reason") is not None
            or any(diagnostic.get(key) != [] for key in (
                "unresolved", "foreign_orders", "foreign_positions"))
            or diagnostic.get("restricted_securities") != {}
            or not isinstance(diagnostic.get("expected"), dict)
            or diagnostic["expected"] != diagnostic.get("observed")
            or not isinstance(clean_id, (str, int)) or isinstance(clean_id, bool)
            or not str(clean_id).isdigit() or not 0 < int(clean_id) < 2**63
            or diagnostic.get("observation_id") != int(clean_id)):
        return None
    expected = {}
    for sid, raw in diagnostic["expected"].items():
        if not isinstance(sid, str) or not sid or not isinstance(raw, str):
            return None
        try:
            qty = Decimal(raw)
        except (InvalidOperation, ValueError):
            return None
        if not qty.is_finite() or qty < 0:
            return None
        if qty:
            expected[sid] = qty

    plan = journal.load_plan(conn, cycle.plan_id)
    if monotonic() >= deadline:
        return None
    if (plan is None or plan.fingerprint() != cycle.plan_fingerprint
            or (plan.decision_session, plan.effective_session,
                plan.deployment_id, plan.broker, plan.broker_account_id,
                plan.takeover_epoch) != (
                    cycle.decision_session, cycle.effective_session,
                    cycle.deployment_id, cycle.broker, cycle.broker_account_id,
                    cycle.takeover_epoch)):
        return None
    projection = target_reprojection.load_projection(conn, plan_id=plan.plan_id)
    if monotonic() >= deadline:
        return None
    if (projection is None or projection.plan_fingerprint != cycle.plan_fingerprint
            or projection.through_session != cycle.effective_session):
        return None
    target_reprojection.assert_projection(
        conn, plan=plan, projection=projection,
        through_session=cycle.effective_session)
    if monotonic() >= deadline:
        return None
    created = conn.execute(
        "SELECT created_at FROM sentinel_execution_plans WHERE plan_id=%s",
        (plan.plan_id,)).fetchone()
    if created is None or not isinstance(created[0], datetime):
        return None
    authority = load_authority(conn, plan_id=plan.plan_id)
    if monotonic() >= deadline:
        return None
    if authority is None:
        return None
    preview = project_original_intent({
        "cycle_id": cycle.cycle_id, "plan_id": plan.plan_id,
        "plan_fingerprint": cycle.plan_fingerprint,
        "decision_session": plan.decision_session,
        "effective_session": plan.effective_session,
        "execute_at": cycle.execute_at,
        "execution_open_at": cycle.execution_open_at,
        "created_at": created[0], "broker": plan.broker,
        "broker_account_id": plan.broker_account_id,
        "target_basket": dict(plan.target_basket),
        "target_exposure": plan.target_exposure,
        "account_nav": plan.account_nav,
        "opening_intents": [item.to_dict() for item in plan.opening_intents],
    }, authority)
    if monotonic() >= deadline:
        return None
    legs = {leg.security_id: leg for leg in preview.legs}
    if not legs or len(legs) > 100:
        return None
    commands = journal.load_commands(conn, DeploymentIdentity(
        cycle.deployment_id, cycle.broker, cycle.broker_account_id,
        cycle.takeover_epoch), plan_id=plan.plan_id)
    if monotonic() >= deadline:
        return None
    if len(commands) > 100 or len({c.client_key for c in commands}) != len(commands):
        return None
    by_sid = {}
    for command in commands:
        if command.security_id not in legs or command.side.value != legs[command.security_id].action:
            return None
        by_sid.setdefault(command.security_id, []).append(command)

    filled_sells = []
    for leg in preview.legs:
        if leg.action != "SELL":
            continue
        sales = by_sid.get(leg.security_id, [])
        if (leg.change_quantity is None or leg.change_quantity >= 0 or not sales
                or any(c.state.value != "FILLED" or c.quantity is None
                       or c.broker_order_id is None
                       or c.filled_quantity != c.quantity for c in sales)
                or sum((c.filled_quantity for c in sales), Decimal(0))
                    != -leg.change_quantity):
            return None
        filled_sells.extend(c.client_key for c in sales)

    raw = diagnostic.get("actionable_deltas")
    if not isinstance(raw, list) or not 0 < len(raw) <= 20:
        return None
    remaining = {}
    for item in raw:
        if (not isinstance(item, Mapping) or not isinstance(item.get("security_id"), str)
                or item.get("side") != "BUY"):
            return None
        sid = item["security_id"]
        if sid in remaining or sid not in legs or legs[sid].action != "BUY":
            return None
        if set(item) != {"security_id", "remaining", "side", "remaining_notional"}:
            return None
        if item["remaining_notional"] is None:
            quantity, notional = _positive_decimal(item["remaining"]), None
            if quantity is None:
                return None
        else:
            quantity, notional = None, _positive_decimal(item["remaining_notional"])
            if item["remaining"] != "0" or notional is None:
                return None
        remaining[sid] = (quantity, notional)

    as_of = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    if not isinstance(as_of, datetime) or monotonic() >= deadline:
        return None
    planned = {}
    for command in commands:
        state = command.state.value
        if state == "PLANNED":
            sid = command.security_id
            if (command.side.value != "BUY" or sid not in remaining
                    or sid in planned or command.filled_quantity != 0
                    or command.broker_order_id is not None
                    or (command.quantity, command.notional) != remaining[sid]
                    or not _no_transport_events(
                        conn, command, execute_at=cycle.execute_at,
                        as_of=as_of, deadline=deadline)):
                return None
            planned[sid] = command.client_key
        elif state != "FILLED" or command.broker_order_id is None:
            # CANCELLED/REJECTED purchases are not clean unsent purchases.
            return None
    no_command_buy_ids = set(remaining) - set(planned)
    planned_keys = set(planned.values())
    if monotonic() >= deadline:
        return None
    active = conn.execute(
        "SELECT client_key,state FROM sentinel_commands "
        "WHERE state=ANY(%s) ORDER BY client_key LIMIT 101",
        (list(_ACTIVE),)).fetchall()
    if (monotonic() >= deadline or len(active) != len(planned_keys)
            or {key for key, state in active if state == "PLANNED"} != planned_keys):
        return None
    saved_id = int(clean_id)
    saved_at = _observation(conn, saved_id, cycle=cycle, expected=expected,
                            as_of=as_of, planned_keys=planned_keys,
                            current_plan_keys={c.client_key for c in commands},
                            no_command_buy_ids=no_command_buy_ids,
                            deadline=deadline)
    latest = conn.execute(
        "SELECT seq,observed_at FROM sentinel_observations "
        "ORDER BY seq DESC LIMIT 1").fetchone()
    if (monotonic() >= deadline or saved_at is None or latest is None or latest[0] < saved_id
            or not isinstance(latest[1], datetime) or latest[1] < saved_at):
        return None
    if (latest[0] != saved_id
            and _observation(conn, latest[0], cycle=cycle, expected=expected,
                             as_of=as_of, planned_keys=planned_keys,
                             current_plan_keys={c.client_key for c in commands},
                             no_command_buy_ids=no_command_buy_ids,
                             deadline=deadline) is None):
        return None
    if monotonic() >= deadline:
        return None
    return {
        "schema": "sentinel.missed-window-buy-only/1",
        "cycle_id": cycle.cycle_id,
        "plan_id": plan.plan_id,
        "plan_fingerprint": cycle.plan_fingerprint,
        "from_state": cycle.state.value,
        "attempt_count": cycle.attempt_count,
        "observation_id": saved_id,
        "latest_observation_id": latest[0],
        "remaining_buy_security_ids": sorted(remaining),
        "unsent_buy_keys": sorted(planned_keys),
        "filled_sell_keys": sorted(filled_sells),
        "journal": "RESTORED_PRETRANSPORT_ONLY",
    }
