"""GET-only local PAPER account evidence for the operator panel.

No execution grant, journal transition or financial reconciliation is issued.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from fractions import Fraction

from sentinel import binding, local_paper, operational_evidence
from sentinel.execution import journal, native_activity
from sentinel.execution.numeric import decimal_text, exact_decimal
from sentinel.execution.states import IN_FLIGHT, CommandState
from sentinel.paper.inspection import _inspection_account_or_refuse

POLL_SECONDS = 60
DEADLINE_SECONDS = 8
RESERVATION_SCHEMA = "sentinel.operator-account-reservation/1"
RESERVATION_FLAG = "operator_order_reservation"


class AccountStatusRefused(ValueError):
    pass


def _bound(conn):
    if not local_paper.require_bound_account(conn):
        return None
    owner = binding.require(conn)
    return (owner.deployment_id, owner.broker, owner.broker_account_id,
            owner.takeover_epoch)


def _fact(order):
    return dict(client_key=order.client_key, broker_order_id=order.broker_order_id,
        asset_id=order.instrument.broker_id, side=order.side.value,
        state=order.state.value, quantity=decimal_text(order.quantity),
        filled_quantity=decimal_text(order.filled_quantity), terms=order.order_terms.to_dict())


def _commands(conn, bound):
    from sentinel.execution.identity import DeploymentIdentity
    commands = journal.load_commands(conn, DeploymentIdentity(*bound))
    facts = []
    for c in commands:
        if c.state not in IN_FLIGHT:
            continue
        t = c.order_terms
        if (c.state not in {CommandState.ACKNOWLEDGED, CommandState.PARTIALLY_FILLED}
                or c.side.value != "BUY" or not c.broker_order_id
                or not c.instrument.broker_id or not c.remaining.is_finite() or c.remaining <= 0
                or t.order_type != "limit" or t.time_in_force != "day"
                or t.order_class != "simple" or t.extended_hours
                or t.limit_price is None or not t.limit_price.is_finite() or t.limit_price <= 0):
            return None
        facts.append(_fact(c))
    return sorted(facts, key=lambda f: f["client_key"])


def _reserved(facts):
    return exact_decimal(sum(((Fraction(Decimal(f["quantity"])) - Fraction(Decimal(f["filled_quantity"])))
        * Fraction(Decimal(f["terms"]["limit_price"])) for f in facts), Fraction(0)))


async def _native_orders(reader, commands):
    rows = await reader._get("/v2/orders", {"status": "open", "limit": 500, "nested": True})
    if (not isinstance(rows, list) or len(rows) >= 500 or len(rows) != len(commands)
            or any(not isinstance(raw, dict) or raw.get("legs") for raw in rows)):
        return None
    orders = [reader._to_order(raw) for raw in rows]
    if any(o.external_replacement for o in orders):
        return None
    native = sorted((_fact(o) for o in orders), key=lambda f: f["client_key"] or "")
    return native if native == commands else None


def recorded_reservation(conn, *, account, now):
    """Recheck native display facts against current ownership, never grant trade authority."""
    from sentinel.feed import calendar
    from zoneinfo import ZoneInfo
    bound = _bound(conn)
    if bound is None or not account or account.get("account_id") != bound[2]:
        return None
    proof = (account.get("flags") or {}).get(RESERVATION_FLAG)
    observed = account.get("observed_at")
    if (not isinstance(proof, dict) or proof.get("schema") != RESERVATION_SCHEMA
            or proof.get("binding") != list(bound) or observed is None or observed > now):
        return None
    session = observed.astimezone(ZoneInfo(calendar.EXCHANGE_TZ)).date()
    opened, closed = calendar.session_window(session)
    if not opened <= observed <= now <= closed:
        return None
    commands = _commands(conn, bound)
    if not commands or commands != proof.get("native_orders"):
        return None
    hold = _reserved(commands)
    cash, power = Decimal(str(account["cash"])), Decimal(str(account["buying_power"]))
    if (not cash.is_finite() or not power.is_finite() or not 0 <= power < cash
            or abs(Fraction(cash)-Fraction(power)-Fraction(hold)) > 1):
        return None
    return {"reserved_cash": decimal_text(hold), "valid_until": closed.isoformat()}


async def _collect(conn, *, reader, bound, commands):
    conn.commit()  # Never retain a database transaction over provider I/O.
    snapshot = await reader.account_snapshot()
    _inspection_account_or_refuse(snapshot, bound[2])
    first = snapshot.identity
    native = native_activity._uuid(first.raw.get("id"), "NATIVE_ACCOUNT_ID_REQUIRED")
    if first.broker != bound[1] or first.raw.get("currency") != "USD":
        raise AccountStatusRefused("ACCOUNT_IDENTITY_OR_CURRENCY_CHANGED")
    native_orders = None
    if commands and snapshot.cash > snapshot.buying_power:
        native_orders = await _native_orders(reader, commands)
    last = await reader.account_snapshot()
    _inspection_account_or_refuse(last, bound[2])
    if ((last.identity.broker, last.identity.account_id, last.identity.raw.get("id"))
            != (first.broker, first.account_id, native)
            or last.identity.raw.get("currency") != "USD"):
        raise AccountStatusRefused("ACCOUNT_IDENTITY_OR_CURRENCY_CHANGED")
    if _bound(conn) != bound:
        raise AccountStatusRefused("DURABLE_BINDING_CHANGED")
    proof = None
    if (native_orders and commands == _commands(conn, bound)
            and snapshot.cash == last.cash and snapshot.buying_power == last.buying_power
            and abs(Fraction(last.cash)-Fraction(last.buying_power)-Fraction(_reserved(commands))) <= 1):
        proof = dict(schema=RESERVATION_SCHEMA, binding=list(bound), native_orders=native_orders)
    operational_evidence.record_account_snapshot(conn, last, display_reservation=proof)
    conn.commit()
    return True


async def collect(conn, *, config, reader=None):
    """Publish authenticated display evidence only, including blocked accounts."""
    config.assert_paper()
    bound = _bound(conn)
    if bound is None:
        return False
    commands = _commands(conn, bound)
    if reader is None:
        from sentinel.execution.alpaca import AlpacaExecutionBroker
        reader = AlpacaExecutionBroker(api_key=config.alpaca_key,
            secret_key=config.alpaca_secret, base_url=config.base_url)
    return await asyncio.wait_for(
        _collect(conn, reader=reader, bound=bound, commands=commands), DEADLINE_SECONDS)
