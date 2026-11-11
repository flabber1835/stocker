"""GET-only URL-selected account evidence for the operator panel.

No execution grant, journal transition or financial reconciliation is issued.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from fractions import Fraction

from sentinel import local_paper, operational_evidence
from sentinel.execution import journal, native_activity
from sentinel.execution.numeric import decimal_text, exact_decimal
from sentinel.execution.states import IN_FLIGHT, CommandState
from sentinel.paper.inspection import _inspection_account_or_refuse

POLL_SECONDS = 60
DEADLINE_SECONDS = 8
RESERVATION_RECHECK = 'RESERVATION_RECHECK'
RESERVATION_RECHECK_SECONDS = 2
RESERVATION_SCHEMA = "sentinel.operator-account-reservation/1"
RESERVATION_FLAG = "operator_order_reservation"


class AccountStatusRefused(ValueError):
    pass


def _bound(conn, *, config=None):
    if config is not None:
        from sentinel.trading_environment import TradingEnvironment
        if config.environment is TradingEnvironment.LIVE:
            from sentinel.execution.trading_readonly import live_binding
            return live_binding(conn, config=config)
    owner = local_paper.bound_account(conn)
    if owner is None:
        return None
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
    return {"reserved_cash": decimal_text(hold), "valid_until": closed.isoformat(),
            "order_count": len(commands)}


async def _observation(conn, *, reader, bound, commands, config):
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
    current = _bound(conn) if config is None else _bound(conn, config=config)
    if current != bound:
        raise AccountStatusRefused("DURABLE_BINDING_CHANGED")
    current_commands = _commands(conn, bound) if commands is not None else None
    proof = None
    if (native_orders and commands == current_commands
            and snapshot.cash == last.cash and snapshot.buying_power == last.buying_power
            and abs(Fraction(last.cash)-Fraction(last.buying_power)-Fraction(_reserved(commands))) <= 1):
        proof = dict(schema=RESERVATION_SCHEMA, binding=list(bound), native_orders=native_orders)
    unsettled = (
        proof is None and bool(current_commands)
        and str(last.status).upper() == 'ACTIVE' and last.multiplier == 1
        and not (last.trading_blocked or last.account_blocked or last.trade_suspended_by_user)
        and last.equity > 0 and last.buying_power >= 0
        and 1 < last.cash - last.buying_power <= _reserved(current_commands) + 1
    )
    return last, proof, unsettled, current_commands


async def _collect(conn, *, reader, bound, commands, config=None):
    clock = asyncio.get_running_loop().time
    started = clock()
    last, proof, unsettled, current = await _observation(
        conn, reader=reader, bound=bound, commands=commands, config=config)
    remaining = min(3, DEADLINE_SECONDS - (clock() - started) - 0.5)
    if unsettled and remaining > 0:
        try:
            async with asyncio.timeout(remaining):
                last, proof, unsettled, _ = await _observation(
                    conn, reader=reader, bound=bound, commands=current, config=config)
        except TimeoutError:
            conn.rollback()
            if (_bound(conn) if config is None else _bound(conn, config=config)) != bound:
                raise AccountStatusRefused("DURABLE_BINDING_CHANGED")
    operational_evidence.record_account_snapshot(conn, last, display_reservation=proof)
    conn.commit()
    return RESERVATION_RECHECK if unsettled else True


async def collect(conn, *, config, reader=None, report_reservation_recheck=False):
    """Publish authenticated display evidence only, including blocked accounts."""
    from sentinel.trading_environment import TradingEnvironment
    live = config.environment is TradingEnvironment.LIVE
    if not live:
        config.assert_paper()
    bound = _bound(conn, config=config) if live else _bound(conn)
    if bound is None:
        return False
    commands = None if live else _commands(conn, bound)
    if live:
        from sentinel.execution.trading_readonly import live_monitoring_reader
        reader = live_monitoring_reader(config, reader)
    elif reader is None:
        from sentinel.execution.alpaca import AlpacaExecutionBroker
        reader = AlpacaExecutionBroker(api_key=config.alpaca_key,
            secret_key=config.alpaca_secret, base_url=config.base_url)
    result = await asyncio.wait_for(
        _collect(conn, reader=reader, bound=bound, commands=commands,
                 config=config if live else None), DEADLINE_SECONDS)
    return result if report_reservation_recheck else bool(result)
