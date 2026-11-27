"""GET-only URL-selected account evidence for the operator panel.

No execution grant, journal transition or financial reconciliation is issued.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from fractions import Fraction

from sentinel import local_paper, operational_evidence
from sentinel.execution import journal, native_activity
from sentinel.execution.contract import Side
from sentinel.execution.numeric import decimal_text, exact_decimal
from sentinel.execution.states import CommandState
from sentinel.paper.inspection import _inspection_account_or_refuse

POLL_SECONDS = 60
DEADLINE_SECONDS = 8
PUBLICATION_SECONDS = 10
RESERVATION_RECHECK = 'RESERVATION_RECHECK'
SAMPLE_SUPERSEDED = 'SAMPLE_SUPERSEDED'
RESERVATION_RECHECK_SECONDS = 2
RESERVATION_SCHEMA = "sentinel.operator-account-reservation/1"
MARKET_WORKING_SCHEMA = "sentinel.operator-market-order/1"
RESERVATION_FLAG = "operator_order_reservation"


class AccountStatusRefused(ValueError):
    pass


class AccountEvidenceBusy(AccountStatusRefused):
    """A bounded evidence INSERT could not acquire its database lock."""

    def __init__(self, reason, *, dependency, lock_timeouts, lock_probe=None):
        super().__init__(reason)
        self.dependency = dependency
        self.lock_timeouts = lock_timeouts
        self.blocker = lock_probe.result() if lock_probe is not None and lock_probe.done() else None


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
    fact = dict(client_key=order.client_key, broker_order_id=order.broker_order_id,
        asset_id=order.instrument.broker_id, side=order.side.value,
        state=order.state.value, quantity=(None if order.quantity is None else decimal_text(order.quantity)),
        filled_quantity=decimal_text(order.filled_quantity), terms=order.order_terms.to_dict())
    if order.order_terms.order_type == "market":
        fact["filled_average_price"] = (decimal_text(order.filled_average_price)
            if order.filled_average_price is not None else None)
    if order.notional is not None:
        fact["notional"] = decimal_text(order.notional)
    if order.side is Side.SELL:
        fact["symbol"] = order.instrument.symbol
    return fact


def _commands(conn, bound, *, plan_id=None):
    from sentinel.execution.identity import DeploymentIdentity
    commands = journal.in_flight_commands(conn, DeploymentIdentity(*bound))
    facts = []
    market_plans = set()
    for c in commands:
        t = c.order_terms
        if (c.state not in {CommandState.ACKNOWLEDGED, CommandState.PARTIALLY_FILLED}
                or not c.broker_order_id
                or not c.instrument.broker_id
                or (c.quantity is not None and (not c.remaining.is_finite() or c.remaining <= 0))
                or t.time_in_force != "day" or t.order_class != "simple" or t.extended_hours
                or (plan_id is not None and c.identity.plan_id != plan_id)):
            return None
        if t.order_type == "market":
            market_plans.add(c.identity.plan_id)
            from sentinel.execution.market_buy_policy import MarketBuyPolicy
            if ((c.side is Side.BUY and (MarketBuyPolicy.from_env() is None
                         or (c.quantity is not None and c.quantity != c.quantity.to_integral_value())))
                    or (c.side is Side.SELL and (c.quantity is None or c.notional is not None))
                    or (c.state is CommandState.ACKNOWLEDGED and c.filled_quantity != 0)
                    or (c.state is CommandState.PARTIALLY_FILLED
                        and (c.filled_quantity <= 0 or c.filled_average_price is None))):
                return None
        elif (c.side is not Side.BUY or t.order_type != "limit" or t.limit_price is None
                or not t.limit_price.is_finite() or t.limit_price <= 0):
            return None
        fact = _fact(c)
        if c.side is Side.SELL:
            fact["security_id"] = c.security_id
        facts.append(fact)
    if market_plans and (len(market_plans) != 1 or not _market_working(facts)
            or len({f["asset_id"] for f in facts}) != len(facts)
            or len({f["broker_order_id"] for f in facts}) != len(facts)):
        return None
    if {c.side for c in commands} == {Side.BUY, Side.SELL}:
        from sentinel.core.decision import DEFENSIVE_SECURITY_ID
        from sentinel.execution import market_reservation_record
        from sentinel.paper.market_reservations import member
        purchases = [c for c in commands if c.side is Side.BUY]
        if (len(purchases) != 1 or purchases[0].security_id != DEFENSIVE_SECURITY_ID
                or purchases[0].notional is None or len(market_plans) != 1):
            return None
        basis = market_reservation_record.read(conn, purchases[0].identity.plan_id)
        if (not basis or basis["deployment"] != purchases[0].identity.deployment.to_dict()
                or basis["members"] != {purchases[0].client_key: member(purchases[0])}
                or not {c.client_key for c in commands if c.side is Side.SELL} <= set(basis["sales"])):
            return None
    return sorted(facts, key=lambda f: f["client_key"])


def _market_working(facts):
    return bool(facts and all(f["terms"]["order_type"] == "market" for f in facts))


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
    # The display reader has no strategy identifier resolver. Native asset ID,
    # ticker, client key and economics must match before retaining the journal ID.
    expected = [{k: v for k, v in command.items() if k != "security_id"} for command in commands]
    return commands if native == expected else None


def _recorded_order_proof(conn, *, account, now, schema, plan_id=None):
    from sentinel.feed import calendar
    from zoneinfo import ZoneInfo
    bound = _bound(conn)
    if bound is None or not account or account.get("account_id") != bound[2]:
        return None
    proof = (account.get("flags") or {}).get(RESERVATION_FLAG)
    observed = account.get("observed_at")
    if (not isinstance(proof, dict) or proof.get("schema") != schema
            or proof.get("binding") != list(bound) or observed is None or observed > now):
        return None
    session = observed.astimezone(ZoneInfo(calendar.EXCHANGE_TZ)).date()
    opened, closed = calendar.session_window(session)
    if not opened <= observed <= now <= closed:
        return None
    commands = _commands(conn, bound, plan_id=plan_id)
    if not commands or commands != proof.get("native_orders"):
        return None
    return commands, closed


def recorded_reservation(conn, *, account, now):
    """Recheck native display facts against current ownership, never grant trade authority."""
    proof = _recorded_order_proof(conn, account=account, now=now, schema=RESERVATION_SCHEMA)
    if proof is None or _market_working(proof[0]):
        return None
    commands, closed = proof
    hold = _reserved(commands)
    cash, power = Decimal(str(account["cash"])), Decimal(str(account["buying_power"]))
    if (not cash.is_finite() or not power.is_finite() or not 0 <= power < cash
            or abs(Fraction(cash)-Fraction(power)-Fraction(hold)) > 1):
        return None
    return {"reserved_cash": decimal_text(hold), "valid_until": closed.isoformat(),
            "order_count": len(commands)}


def recorded_market_working(conn, *, account, now, plan_id):
    """Match the current plan's working market orders without valuing sale proceeds."""
    if not plan_id:
        return None
    proof = _recorded_order_proof(conn, account=account, now=now,
                                  schema=MARKET_WORKING_SCHEMA, plan_id=plan_id)
    if proof is None or not _market_working(proof[0]):
        return None
    commands, closed = proof
    native = account["flags"][RESERVATION_FLAG]
    cash, power = Decimal(str(account["cash"])), Decimal(str(account["buying_power"]))
    if (not cash.is_finite() or not power.is_finite() or not 0 <= power <= cash
            or native.get("cash") != decimal_text(cash)
            or native.get("buying_power") != decimal_text(power)):
        return None
    if cash - power > 1 and all(o["side"] == "BUY" and o.get("notional") for o in commands):
        # A fixed-dollar basket can be valued exactly. Only the funded-basket
        # receipt can attribute its hold; generic working orders cannot.
        return None
    if any(o["side"] == "SELL" for o in commands):
        # A sale cannot explain a buying-power hold. In a mixed sleeve sweep
        # only the BIL order's unfilled dollars can explain a discrepancy.
        unfilled = sum((Fraction(o["notional"]) - Fraction(o["filled_quantity"])
                        * Fraction(o["filled_average_price"] or "0")
                        for o in commands if o["side"] == "BUY"), Fraction(0))
        if Fraction(cash) - Fraction(power) > max(0, unfilled) + 1:
            return None
    return {"orders": commands, "valid_until": closed}


def _healthy_cash_snapshot(snapshot):
    return (str(snapshot.status).upper() == "ACTIVE" and snapshot.multiplier == 1
            and not (snapshot.trading_blocked or snapshot.account_blocked
                     or snapshot.trade_suspended_by_user)
            and snapshot.equity > 0 and 0 <= snapshot.buying_power <= snapshot.cash)


async def _observation(conn, *, reader, bound, commands, config):
    from sentinel.execution import observed_dollar_hold
    conn.commit()  # Never retain a database transaction over provider I/O.
    snapshot = await reader.account_snapshot()
    _inspection_account_or_refuse(snapshot, bound[2])
    first = snapshot.identity
    native = native_activity._uuid(first.raw.get("id"), "NATIVE_ACCOUNT_ID_REQUIRED")
    if first.broker != bound[1] or first.raw.get("currency") != "USD":
        raise AccountStatusRefused("ACCOUNT_IDENTITY_OR_CURRENCY_CHANGED")
    native_orders = None
    dollar_basket = dollar_proof = None
    market = _market_working(commands)
    if config is None and _healthy_cash_snapshot(snapshot) and snapshot.cash - snapshot.buying_power > 1:
        dollar_basket = observed_dollar_hold.basket(conn, bound)
        conn.commit()
    if dollar_basket:
        dollar_proof = await observed_dollar_hold.capture(reader, dollar_basket, snapshot)
    elif (market and _healthy_cash_snapshot(snapshot)
            or commands and not market and snapshot.cash > snapshot.buying_power):
        native_orders = await _native_orders(reader, commands)
    last = await reader.account_snapshot()
    observed_at = conn.execute('SELECT clock_timestamp()').fetchone()[0]
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
    balances_stable = snapshot.cash == last.cash and snapshot.buying_power == last.buying_power
    if dollar_proof and balances_stable and _healthy_cash_snapshot(last):
        if observed_dollar_hold.verify(conn, bound, dollar_proof, last.cash, last.buying_power, observed_at, observed_at):
            proof = dollar_proof
    elif native_orders and commands == current_commands and balances_stable:
        if market and _healthy_cash_snapshot(snapshot) and _healthy_cash_snapshot(last):
            proof = dict(schema=MARKET_WORKING_SCHEMA, binding=list(bound), native_orders=native_orders,
                         cash=decimal_text(last.cash), buying_power=decimal_text(last.buying_power))
        elif not market and abs(
                Fraction(last.cash)-Fraction(last.buying_power)-Fraction(_reserved(commands))) <= 1:
            proof = dict(schema=RESERVATION_SCHEMA, binding=list(bound), native_orders=native_orders)
    unsettled = (
        proof is None and bool(current_commands) and not _market_working(current_commands)
        and str(last.status).upper() == 'ACTIVE' and last.multiplier == 1
        and not (last.trading_blocked or last.account_blocked or last.trade_suspended_by_user)
        and last.equity > 0 and last.buying_power >= 0
        and 1 < last.cash - last.buying_power <= _reserved(current_commands) + 1
    )
    if dollar_basket and not balances_stable and _healthy_cash_snapshot(last) and last.cash - last.buying_power > 1:
        unsettled = True
    return last, proof, unsettled, current_commands, observed_at


async def _collect(conn, *, reader, bound, commands, config=None):
    clock = asyncio.get_running_loop().time
    started = clock()
    last, proof, unsettled, current, observed_at = await _observation(
        conn, reader=reader, bound=bound, commands=commands, config=config)
    remaining = min(3, DEADLINE_SECONDS - (clock() - started) - 0.5)
    if unsettled and remaining > 0:
        try:
            async with asyncio.timeout(remaining):
                last, proof, unsettled, current, observed_at = await _observation(
                    conn, reader=reader, bound=bound, commands=current, config=config)
        except TimeoutError:
            conn.rollback()
            if (_bound(conn) if config is None else _bound(conn, config=config)) != bound:
                raise AccountStatusRefused("DURABLE_BINDING_CHANGED")
    return last, proof, unsettled, current, observed_at


async def _publish(conn, *, bound, config, sample, opening, report):
    from psycopg.errors import LockNotAvailable
    from sentinel import account_lock_observation
    from sentinel.execution import observed_dollar_hold, opening_display

    last, proof, unsettled, commands, observed_at = sample
    clock = asyncio.get_running_loop().time
    deadline = clock() + PUBLICATION_SECONDS
    lock_timeouts = 0
    lock_probe = None
    dependency = 'ACCOUNT_EVIDENCE'
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise AccountEvidenceBusy('ACCOUNT_EVIDENCE_LOCK_TIMEOUT', dependency=dependency,
                                      lock_timeouts=lock_timeouts, lock_probe=lock_probe)
        lock_ms = max(1, min(1000, int(remaining * 1000)))
        conn.execute("SELECT set_config('lock_timeout', least(coalesce(nullif(setting::int,0),%s),%s)::text,true)"
                     " FROM pg_settings WHERE name='lock_timeout'", (lock_ms, lock_ms))
        current_opening = opening_display.confirm(conn, bound, opening) if opening is not None else None
        try:
            operational_evidence.record_account_snapshot(conn, last, display_reservation=proof,
                opening_observation=current_opening, collector_observed_at=observed_at)
            # Never wait with a financial invalidation lock while upgrading
            # our relation lock. A simultaneous evidence writer can finish.
            conn.execute('LOCK TABLE sentinel_broker_account_evidence IN SHARE MODE NOWAIT')
        except LockNotAvailable as exc:
            # PostgreSQL guarantees this statement was cancelled. Retry only
            # after rollback. A commit with an unknown outcome is never replayed.
            conn.rollback()
            lock_timeouts += 1
            if 'sentinel_operational_account_insert_bump()' in (exc.diag.context or ''):
                dependency = 'PAPER_REVISION'
            if report and lock_timeouts == 1 and deadline-clock() > .25:
                try:
                    lock_probe = account_lock_observation.start(conn, observed_at=observed_at)
                except Exception:
                    pass  # The next financial transaction never waits for or depends on this probe.
            await asyncio.sleep(min(.05, max(0,deadline-clock())))
            continue
        if conn.execute('SELECT 1 FROM sentinel_broker_account_evidence WHERE observed_at>%s LIMIT 1',
                        (observed_at,)).fetchone():
            conn.rollback()
            return SAMPLE_SUPERSEDED
        current_bound = _bound(conn) if config is None else _bound(conn, config=config)
        if current_bound != bound:
            conn.rollback()
            raise AccountStatusRefused('DURABLE_BINDING_CHANGED')
        dollar = proof and proof.get("schema") == observed_dollar_hold.SCHEMA
        if ((dollar and not observed_dollar_hold.verify(conn, bound, proof, last.cash, last.buying_power,
                                                        observed_at, observed_at))
                or (proof and not dollar and _commands(conn, bound) != commands)
                or (current_opening and opening_display.confirm(conn, bound, opening) != current_opening)):
            conn.rollback()
            raise AccountStatusRefused('ACCOUNT_EVIDENCE_ORDER_CONTEXT_CHANGED')
        now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
        if not 0 <= (now-observed_at).total_seconds() <= PUBLICATION_SECONDS:
            conn.rollback()
            raise AccountEvidenceBusy('ACCOUNT_EVIDENCE_PUBLICATION_EXPIRED', dependency=dependency,
                                      lock_timeouts=lock_timeouts, lock_probe=lock_probe)
        conn.commit()
        if report:
            from sentinel import account_collection_incidents, supervisor_io
            try:
                account_collection_incidents.recover(conn, observed_at=observed_at)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                supervisor_io._pipe_report('account collector recovery diagnostic unavailable: '+type(exc).__name__)
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
    opening = None
    if live or (commands == [] and hasattr(reader, 'observe')):
        from sentinel.execution import opening_display
        opening = await opening_display.collect(conn, reader=reader, bound=bound)
    sample = await asyncio.wait_for(
        _collect(conn, reader=reader, bound=bound, commands=commands,
                 config=config if live else None), DEADLINE_SECONDS)
    result = await _publish(conn, bound=bound, config=config if live else None, sample=sample, opening=opening,
                            report=report_reservation_recheck)
    return result if report_reservation_recheck else result != SAMPLE_SUPERSEDED
