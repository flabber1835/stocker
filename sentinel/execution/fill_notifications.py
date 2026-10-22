"""Account-bound native fill receipts for local PAPER notifications only.

No financial ledger writes, completeness claims, or broker mutations live here.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction

from sentinel.automation import outbox
from sentinel.execution import fill_integrity, journal, native_activity


SINCE_ENV = "SENTINEL_FILL_NOTIFICATIONS_SINCE"
DEADLINE_SECONDS = 18
POLL_SECONDS = 30


class FillNotificationRefused(ValueError):
    pass


def _binding(conn):
    from sentinel import binding, local_paper
    if not local_paper.require_bound_account(conn):
        raise FillNotificationRefused("LOCAL_PAPER_REQUIRED")
    value = binding.require(conn)
    return (value.deployment_id, value.broker, value.broker_account_id,
            value.takeover_epoch)


def _existing(conn):
    rows = conn.execute(
        "SELECT payload FROM sentinel_alert_outbox WHERE event_type='BROKER_FILL'").fetchall()
    return [row[0] for row in rows]


def _covered(payloads, client_key):
    return sum((Fraction(Decimal(p["quantity"])) for p in payloads
                if p.get("client_key") == client_key), Fraction(0))


def _candidates(conn, bound, since):
    rows = conn.execute(
        "SELECT client_key,broker_order_id,broker_instrument_id,symbol,security_id,side,"
        " quantity,filled_quantity,order_terms FROM sentinel_commands"
        " WHERE broker=%s AND broker_account_id=%s AND deployment_id=%s"
        " AND takeover_epoch=%s AND created_at>=%s AND filled_quantity>0"
        " AND broker_order_id IS NOT NULL ORDER BY updated_at DESC",
        (bound[1], bound[2], bound[0], bound[3], since)).fetchall()
    existing = _existing(conn)
    return [dict(zip(("client_key", "broker_order_id", "broker_id", "symbol",
                     "security_id", "side", "quantity", "filled_quantity",
                     "order_terms"), row, strict=True)) for row in rows
            if _covered(existing, row[0]) < Fraction(row[7])][:3]


def _check_order(command, order):
    from sentinel.execution.contract import OrderTerms
    if not isinstance(order, dict):
        raise FillNotificationRefused("EXACT_ORDER_REQUIRED")
    expected = {"id": command["broker_order_id"],
                "client_order_id": command["client_key"],
                "asset_id": command["broker_id"],
                "side": command["side"].lower()}
    if any(order.get(k) != v for k, v in expected.items()):
        raise FillNotificationRefused("COMMAND_ORDER_IDENTITY_CHANGED")
    if (native_activity._decimal(order.get("qty"), positive=True) != command["quantity"]
            or native_activity._decimal(order.get("filled_qty"), positive=True)
            < command["filled_quantity"]
            or order.get("replaces") or order.get("replaced_by")):
        raise FillNotificationRefused("COMMAND_ORDER_ECONOMICS_CHANGED")
    terms = OrderTerms(order["type"], order["time_in_force"],
                       None if order.get("limit_price") is None else Decimal(order["limit_price"]),
                       order_class=order.get("order_class") or "simple",
                       extended_hours=order.get("extended_hours", False))
    if terms.to_dict() != command["order_terms"]:
        raise FillNotificationRefused("COMMAND_ORDER_TERMS_CHANGED")


async def _activities(reader, order_id):
    items, seen, token = [], set(), None
    for _ in range(10):
        params = {"order_id": order_id, "direction": "asc", "page_size": 100}
        if token:
            params["page_token"] = token
        page = await reader._get("/v2/account/activities/FILL", params)
        if not isinstance(page, list) or len(page) > 100:
            raise FillNotificationRefused("MALFORMED_FILL_PAGE")
        for item in page:
            native_id = item.get("id") if isinstance(item, dict) else None
            if not native_id or native_id in seen:
                raise FillNotificationRefused("REPEATED_OR_MISSING_FILL_ID")
            seen.add(native_id)
            items.append(item)
        if len(page) < 100:
            return items
        token = page[-1]["id"]
    raise FillNotificationRefused("FILL_PAGE_LIMIT")


async def _collect(conn, *, reader, since, now):
    bound = _binding(conn)
    candidates = _candidates(conn, bound, since)
    conn.commit()  # No transaction or execution-writer lock spans network I/O.
    if not candidates:
        return 0
    first = await reader.identify_account()
    native = native_activity._uuid(first.raw.get("id"), "NATIVE_ACCOUNT_ID_REQUIRED")
    if first.account_id != bound[2] or first.broker != bound[1] or not native:
        raise FillNotificationRefused("BROKER_ACCOUNT_CHANGED")
    subject = hashlib.sha256(outbox._json({"binding": bound, "native": native}).encode()).hexdigest()
    alerts = []
    for command in candidates:
        order = await reader._get("/v2/orders/" + command["broker_order_id"])
        _check_order(command, order)
        activities = await _activities(reader, command["broker_order_id"])
        fills = []
        for raw in activities:
            result = native_activity.normalize_activity(
                raw, subject_sha256=subject, account_id=native, order=order)
            if result.disposition == "QUARANTINED" or result.fill is None:
                raise FillNotificationRefused(result.reason_code or "NATIVE_FILL_REQUIRED")
            fill = result.fill
            if fill.executed_at > now:
                raise FillNotificationRefused("FUTURE_FILL")
            if (command["side"] == "BUY" and order.get("limit_price") is not None
                    and fill.price > Decimal(order["limit_price"])):
                raise FillNotificationRefused("FILL_EXCEEDS_LIMIT")
            fills.append(fill.as_broker_fill())
            if fill.executed_at < since:
                continue
            key = journal.fill_fingerprint(fills[-1])
            alert = outbox._fill_alert((fill.broker_order_id, key, fill.client_key,
                command["client_key"], fill.quantity, fill.price, fill.executed_at,
                command["side"], command["security_id"], command["symbol"], 1))
            if alert["event_type"] != "BROKER_FILL":
                raise FillNotificationRefused("NATIVE_COMMAND_IDENTITY_INVALID")
            alert["payload"].pop("reconstructed_from_durable_fill", None)
            alert["payload"].update(notification_only=True,
                source="ALPACA_ORDER_ACTIVITIES_V1", native_activity=raw,
                native_account_id=native, binding=list(bound))
            alerts.append(alert)
        # Reuse actual adapter normalization and the existing exact arithmetic
        # checks, without claiming that account-wide history is complete.
        broker_order = reader._to_order(order)
        from sentinel.execution.contract import BrokerObservation
        fill_integrity.validate(BrokerObservation(now, orders=(broker_order,),
            fills=tuple(fills)), {broker_order.broker_order_id: broker_order})
    last = await reader.identify_account()
    if (last.account_id, last.broker, last.raw.get("id")) != (first.account_id, first.broker, native):
        raise FillNotificationRefused("BROKER_ACCOUNT_CHANGED")
    if _binding(conn) != bound:
        raise FillNotificationRefused("DURABLE_BINDING_CHANGED")
    existing = _existing(conn)
    for alert in alerts:
        payload = alert["payload"]
        for prior in existing:
            if prior.get("fill_key") == payload["fill_key"]:
                fields = ("client_key", "broker_order_id", "ticker", "security_id",
                          "side", "quantity", "price", "filled_at")
                if any(prior.get(k) != payload.get(k) for k in fields):
                    raise FillNotificationRefused("NATIVE_FILL_ID_REUSED")
                if prior.get("native_activity", payload["native_activity"]) != payload["native_activity"]:
                    raise FillNotificationRefused("NATIVE_FILL_CHANGED")
        # Each receipt is independently durable. A crash replays this exact key.
        if not any(p.get("fill_key") == payload["fill_key"] for p in existing):
            outbox.enqueue(conn, **alert)
            existing.append(payload)
    conn.commit()
    return len(alerts)


async def collect(conn, *, config, reader=None, now=None):
    """Collect positive native facts; never infer a fill from an order average."""
    raw = os.environ.get(SINCE_ENV, "")
    if not raw:
        return 0
    since = native_activity.aware_time(raw)
    activated = conn.execute(
        "SELECT web_push_activated_at FROM sentinel_notification_policy WHERE id=1").fetchone()
    if activated is None:
        raise FillNotificationRefused("NOTIFICATION_POLICY_MISSING")
    since = max(since, activated[0])
    now = now or datetime.now(timezone.utc)
    if since > now:
        raise FillNotificationRefused("FUTURE_NOTIFICATION_BOUNDARY")
    config.assert_paper()
    if reader is None:
        from sentinel.execution.alpaca import AlpacaExecutionBroker
        reader = AlpacaExecutionBroker(api_key=config.alpaca_key,
            secret_key=config.alpaca_secret, base_url=config.base_url)
    return await asyncio.wait_for(
        _collect(conn, reader=reader, since=since, now=now), DEADLINE_SECONDS)
