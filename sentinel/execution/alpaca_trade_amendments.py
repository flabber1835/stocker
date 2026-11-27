"""Exact predecessor evidence for Alpaca Activity SSE trade amendments."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime
from fractions import Fraction
from typing import TYPE_CHECKING
from uuid import UUID

from sentinel.execution.contract import Side

if TYPE_CHECKING:
    from sentinel.execution.alpaca import NativeBrokerFill


PREFIX = "broker-trade-amendment:v1:"
_EFFECTS = frozenset({"trade_correct", "trade_bust"})
_PUBLICATION_ID = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}\Z")


class TradeAmendmentRefused(ValueError):
    """The native event has not yet been reconciled with the owned order."""


class TradeAmendmentPending(RuntimeError):
    """The native event arrived ahead of its independent exact-order proof."""


@dataclass(frozen=True)
class TradeAmendment:
    event_id: str
    activity_id: str
    previous_activity_id: str
    account_uuid: str
    broker_order_id: str
    broker_asset_id: str
    client_key: str | None
    side: Side
    executed_at: datetime
    native_json: str
    replacement: NativeBrokerFill | None


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("canonical Alpaca trade UUID required")
    return value


def asset_id(event, details):
    from sentinel.execution.alpaca import MalformedBrokerPayload

    detail_id = details.get("asset_id")
    asset = event.get("asset")
    envelope_id = asset.get("id") if isinstance(asset, dict) else None
    if detail_id and envelope_id and detail_id != envelope_id:
        raise MalformedBrokerPayload("trade activity has contradictory asset IDs", raw_event=event)
    return detail_id or envelope_id


def parse(event, *, account_uuid: str) -> TradeAmendment:
    """Interpret only the documented trade correction/bust relationships."""
    from sentinel.execution.alpaca import (
        AlpacaExecutionBroker, MalformedBrokerPayload, _required_aware_ts)

    try:
        account_uuid = _uuid(account_uuid)
        if "account_id" in event and event["account_id"] != account_uuid:
            raise ValueError("trade amendment changed the bound account")
        details = event["details"]
        kind = details["execution_type"]
        if (event["activity_type"] != "TRD" or kind not in _EFFECTS
                or event["status"] != "executed" or event["currency"] != "USD"):
            raise ValueError("expected an executed USD trade correction or bust")
        event_id = event["event_id"]
        # This is the documented publication clock, not the business date.
        if not isinstance(event_id, str) or not _PUBLICATION_ID.fullmatch(event_id):
            raise ValueError("trade amendment omitted its publication ULID")
        activity_id = _uuid(event["ref_id"])
        previous_id = _uuid(event["previous_id"])
        if activity_id == previous_id:
            raise ValueError("trade amendment references itself")
        order_id = _uuid(details["order_id"])
        native_asset_id = _uuid(asset_id(event, details))
        side = Side(details["side"].upper())
        if side not in (Side.BUY, Side.SELL):
            raise ValueError("trade amendment side cannot be converted")
        client_key = details.get("client_order_id")
        if client_key is not None and (not isinstance(client_key, str) or not client_key.strip()):
            raise ValueError("trade amendment has invalid client key")
        executed_at = _required_aware_ts(event["executed_at"], where="trade amendment execution time")
        native_json = json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False)
        replacement = (AlpacaExecutionBroker._activity_execution_fill(event, amendment=True)
                       if kind == "trade_correct" else None)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise MalformedBrokerPayload(f"invalid Alpaca trade amendment: {exc}", raw_event=event) from exc
    return TradeAmendment(event_id, activity_id, previous_id, account_uuid, order_id,
                          native_asset_id, client_key, side, executed_at, native_json, replacement)


def active_native_fills(events, *, account_uuid, decode_fill):
    """Project an owned order's bounded Activity SSE read in publication order."""
    from sentinel.execution.alpaca import MalformedBrokerPayload

    active = {}
    seen = set()
    for raw in events:
        if raw.get("previous_id") or raw["details"].get("execution_type") in _EFFECTS:
            event = parse(raw, account_uuid=account_uuid)
            old = active.pop(event.previous_activity_id, None)
            if (old is None or (old.broker_order_id, old.asset_id, old.side) !=
                    (event.broker_order_id, event.broker_asset_id, event.side)
                    or old.client_key is not None and event.client_key not in (None, old.client_key)):
                raise MalformedBrokerPayload(
                    "trade amendment does not match an active owned execution", raw_event=raw)
            ref = event.activity_id
            fill = event.replacement
        else:
            fill = decode_fill(raw)
            ref = fill.activity_id
        if ref in seen:
            raise MalformedBrokerPayload("trade activity ref_id repeated in replay", raw_event=raw)
        seen.add(ref)
        if fill is not None:
            active[ref] = fill
    return tuple(active.values())


def _retained(conn, cases):
    return dict(conn.execute(
        "SELECT cursor_name,state FROM sentinel_processed_sessions WHERE cursor_name=ANY(%s)",
        (list(cases),)).fetchall())


def _all_receipts(conn):
    return conn.execute(
        "SELECT cursor_name,state FROM sentinel_processed_sessions WHERE cursor_name LIKE %s ORDER BY cursor_name",
        (PREFIX + "%",)).fetchall()


def _commitment(rows):
    return (hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest() if rows else None)


def commitment(conn):
    return _commitment(_all_receipts(conn))


def verify_restored(conn, *, expected_commitment):
    """A table-selective restore must retain both sides of every amendment."""
    from sentinel.execution import journal

    rows = _all_receipts(conn)
    if _commitment(rows) != expected_commitment:
        raise TradeAmendmentRefused("restored trade amendments disagree with the activity cursor")
    native, published = {}, set()
    for key, receipt in rows:
        event = parse(receipt["native"], account_uuid=receipt["account_uuid"])
        bindings = conn.execute(
            "SELECT broker_instrument_id,side,broker,broker_account_id,deployment_id,takeover_epoch"
            " FROM sentinel_commands WHERE client_key=%s AND broker_order_id=%s",
            (receipt["client_key"], receipt["broker_order_id"])).fetchall()
        deployment = receipt["deployment"]
        expected_binding = (event.broker_asset_id, event.side.value, deployment["broker"],
            deployment["broker_account_id"], deployment["deployment_id"], deployment["takeover_epoch"])
        predecessor_key = journal.native_fill_key(event.previous_activity_id)
        if (receipt["schema"] != "sentinel.alpaca-trade-amendment/1"
                or event.broker_order_id != receipt["broker_order_id"]
                or event.client_key not in (None, receipt["client_key"])
                or bindings != [expected_binding] or key != PREFIX + predecessor_key
                or event.activity_id in native or event.event_id in published):
            raise TradeAmendmentRefused("restored trade amendment has divergent owned identity")
        keys = [predecessor_key, journal.native_fill_key(event.activity_id)]
        with conn.cursor() as cur:
            fills = journal._read_fills_by_key(cur, keys)
        before = fills.get(keys[0], [])
        after = fills.get(keys[1], [])
        replacement = event.replacement
        expected_after = ([] if replacement is None else [
            [event.broker_order_id, receipt["client_key"], replacement.quantity,
             replacement.price, replacement.filled_at]])
        if (len(before) != 1 or before[0][:2] != [event.broker_order_id, receipt["client_key"]]
                or after != expected_after):
            raise TradeAmendmentRefused("restored trade amendment lacks its original or replacement fill")
        native[event.activity_id] = event
        published.add(event.event_id)
    for event in native.values():
        prior = native.get(event.previous_activity_id)
        if prior is not None and (prior.replacement is None or prior.event_id >= event.event_id):
            raise TradeAmendmentRefused("restored amendment predecessor is not in publication order")


def _record(event, command):
    return {
        "schema": "sentinel.alpaca-trade-amendment/1",
        "broker_order_id": command.broker_order_id,
        "client_key": command.client_key,
        "deployment": command.identity.deployment.to_dict(),
        "account_uuid": event.account_uuid,
        "native": json.loads(event.native_json),
    }


def _checked_command(command, order):
    from sentinel.execution.reconcile import _order_command_conflict
    from sentinel.execution.states import CommandState

    if order.state not in {
            CommandState.ACKNOWLEDGED, CommandState.PARTIALLY_FILLED,
            CommandState.FILLED, CommandState.CANCEL_PENDING, CommandState.CANCELLED}:
        raise TradeAmendmentRefused("amended execution has an unsupported order status")
    if (order.filled_quantity == 0) != (order.filled_average_price is None):
        raise TradeAmendmentRefused("amended cumulative fill and price disagree")
    # Validate immutable ownership using the proposed economics, then require
    # the amended fill set to independently corroborate those economics.
    projected = replace(command, state=order.state, filled_quantity=order.filled_quantity,
                        filled_average_price=order.filled_average_price,
                        detail="reconciled Alpaca execution correction or bust")
    conflict = _order_command_conflict(order, projected)
    if conflict:
        raise TradeAmendmentRefused(conflict)
    return projected


def _backfill_predecessors(*, active, order, command, event, trade_history, observed_at):
    """Prove the pre-amendment native fill set using the prior owned order."""
    from sentinel.execution.alpaca import AlpacaExecutionBroker
    from sentinel.execution import fill_integrity, journal

    history = tuple(row for row in trade_history
                    if row["details"].get("order_id") == event.broker_order_id)
    if [row for row in history if row["event_id"] == event.event_id] != [json.loads(event.native_json)]:
        raise TradeAmendmentRefused("bounded replay does not corroborate the current amendment")
    earlier = tuple(row for row in history if row["event_id"] < event.event_id)
    if any(not _PUBLICATION_ID.fullmatch(row["event_id"]) or not _uuid(row["ref_id"]) for row in earlier):
        raise TradeAmendmentRefused("owned predecessor does not have native publication identity")
    fills = active_native_fills(earlier, account_uuid=event.account_uuid,
                                 decode_fill=AlpacaExecutionBroker._activity_execution_fill)
    before = replace(order, state=command.state, filled_quantity=command.filled_quantity,
                     filled_average_price=command.filled_average_price)
    fill_integrity._validate_fill_set(fills, {order.broker_order_id: before},
        observed_at=observed_at, history_complete=True, position_leading_order_ids=())
    described = {journal.fill_fingerprint(fill): fill for fill in fills}
    if not active.keys() <= described.keys():
        raise TradeAmendmentRefused("predecessor replay omitted existing owned fill identity")
    found = []
    for key, fill in described.items():
        old = active.get(key)
        if old is None:
            owned = replace(fill, client_key=command.client_key)
            active[key] = owned
            found.append(owned)
        elif (old.quantity, old.price, old.filled_at) != (fill.quantity, fill.price, fill.filled_at):
            raise TradeAmendmentRefused("predecessor replay changed existing fill economics")
    return found


async def apply(conn, *, broker_adapter, broker, account_id, amendments, trade_history=()):
    """Stage native rebooking in the cash cursor owner's transaction."""
    from sentinel import binding
    from sentinel.execution import fill_integrity, journal
    from sentinel.execution.contract import BrokerExactOrderLookup
    from sentinel.execution.states import CommandState

    if not amendments:
        return False
    owner = binding.require(conn)
    if (owner.broker, owner.broker_account_id) != (broker, account_id) or not owner.is_owned:
        raise TradeAmendmentRefused("trade amendment has no matching owned account")
    broker_order_ids = {event.broker_order_id for event in amendments}
    owned = tuple(command for command in journal.load_commands(conn, owner.identity)
                  if command.broker_order_id in broker_order_ids)
    commands = {command.broker_order_id: command for command in owned}
    if len(owned) != len(commands):
        raise TradeAmendmentRefused("amended broker order has more than one owned command")
    cases = {PREFIX + journal.native_fill_key(e.previous_activity_id): e for e in amendments}
    if (len(cases) != len(amendments)
            or len({e.activity_id for e in amendments}) != len(amendments)
            or any(a.event_id >= b.event_id for a, b in zip(amendments, amendments[1:]))):
        raise TradeAmendmentRefused("trade amendment stream diverged or regressed")
    retained = _retained(conn, cases)
    grouped = {}
    for key, event in cases.items():
        if event != parse(json.loads(event.native_json), account_uuid=event.account_uuid):
            raise TradeAmendmentRefused("trade amendment differs from its retained wire evidence")
        command = commands.get(event.broker_order_id)
        if (command is None or command.instrument.broker_id != event.broker_asset_id
                or command.state in {CommandState.PLANNED, CommandState.SUPERSEDED}
                or command.side is not event.side or event.client_key not in (None, command.client_key)):
            raise TradeAmendmentRefused("trade amendment lacks matching owned order, asset and side")
        record = _record(event, command)
        if key in retained:
            if record != retained[key]:
                raise TradeAmendmentRefused("retained predecessor has a different amendment")
            continue
        grouped.setdefault(event.broker_order_id, []).append((key, event, record))
    if not grouped:
        return False

    writes = []
    for order_id, group in grouped.items():
        command = commands[order_id]
        lookup = await broker_adapter.find_by_client_key(command.client_key)
        if not isinstance(lookup, BrokerExactOrderLookup) or lookup.order is None:
            raise TradeAmendmentPending("amended owned order is unavailable on exact lookup")
        identities = (lookup.stable_identity, lookup.identity_after)
        uuid = group[0][1].account_uuid
        if (any(not owner.identity.matches_account(identity) or identity.raw.get("id") != uuid
                for identity in identities) or any(e.account_uuid != uuid for _, e, _ in group)):
            raise TradeAmendmentRefused("amendment and exact order belong to different accounts")
        order = lookup.order
        projected = _checked_command(command, order)
        rows = conn.execute(
            "SELECT f.fill_key,f.client_key,f.quantity,f.price,f.filled_at,cash.state"
            f" FROM {journal.ACTIVE_FILLS} f" + journal.FILL_CASH_JOIN_SQL +
            " WHERE f.broker_order_id=%s",
            (*journal.FILL_CASH_PREFIXES, order_id)).fetchall()
        active = {}
        for key, client_key, qty, price, filled_at, state in rows:
            if client_key != command.client_key:
                raise TradeAmendmentRefused("durable fill belongs to another owned command")
            amount = None if state is None else fill_integrity._posted_cash(
                state, order_id=order_id, client_key=client_key,
                side=command.side, qty=qty, price=price)
            active[key] = fill_integrity._DurableCashFill(
                client_key, order_id, qty, price, filled_at, amount)
        first_key, first_event, _ = group[0]
        incomplete = (sum((Fraction(f.quantity) for f in active.values()), Fraction(0))
                      != Fraction(command.filled_quantity)
                      or first_key.removeprefix(PREFIX) not in active)
        if incomplete and not trade_history:
            raise TradeAmendmentRefused("owned order does not have a complete durable predecessor fill set")
        replacements = (_backfill_predecessors(active=active, order=order, command=command,
            event=first_event, trade_history=trade_history, observed_at=lookup.request_completed_at)
            if incomplete else [])
        before = replace(order, state=command.state, filled_quantity=command.filled_quantity,
                         filled_average_price=command.filled_average_price)
        fill_integrity._validate_fill_set(
            active.values(), {order_id: before}, observed_at=lookup.request_completed_at,
            history_complete=True, position_leading_order_ids=())
        for key, event, _ in group:
            previous = active.pop(key.removeprefix(PREFIX), None)
            if previous is None:
                raise TradeAmendmentRefused("amendment predecessor is missing or already reversed")
            replacement = event.replacement
            if replacement is not None:
                replacement = replace(replacement, client_key=command.client_key)
                replacement_key = journal.fill_fingerprint(replacement)
                if replacement_key in active:
                    raise TradeAmendmentRefused("replacement execution identity is already active")
                active[replacement_key] = replacement
                replacements.append(replacement)
        try:
            fill_integrity._validate_fill_set(
                active.values(), {order_id: order},
                observed_at=lookup.request_completed_at, history_complete=True,
                position_leading_order_ids=())
        except ValueError as exc:
            raise TradeAmendmentPending(f"amended executions await concordant exact order: {exc}") from exc
        writes.append((command, projected, group, replacements))

    with conn.cursor() as cur:
        for prior, projected, group, replacements in writes:
            journal._write_fills(cur, replacements)
            for key, event, record in group:
                cur.execute(
                    "INSERT INTO sentinel_processed_sessions(cursor_name,session,state)"
                    " VALUES (%s,%s,%s::jsonb)", (key, event.executed_at.date(), json.dumps(record)))
            journal.save_command(conn, projected, previous=prior.state, commit=False)
    return True
