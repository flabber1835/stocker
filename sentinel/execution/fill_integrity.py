"""Validate native execution history before it becomes economic authority."""
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import json

from sentinel.execution.identity import ALPACA_PAPER_BROKER, is_sentinel_key
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerFill, Side
from sentinel.execution.states import CommandState, is_terminal


class FillHistoryIncomplete(ValueError):
    pass


class PostedFillCashIncomplete(FillHistoryIncomplete):
    pass


_CENT = Fraction("0.01")
_SHARE_INCREMENT = Fraction("0.000000001")
NOTIONAL_POSITION_LEAD_PREFIX = "broker-cash-activity:v1:notional-position-lead:v1:"


def live_notional_position_lead(conn, *, deployment, order, observed_at, grace) -> bool:
    """Retain the first mismatch clock without acquiring any share authority."""
    from sentinel.execution.journal import JournalUnitOfWork

    subject = {"deployment": deployment.to_dict(), "security_id": order.instrument.security_id,
               "broker_order_id": order.broker_order_id, "client_key": order.client_key}
    encoded = json.dumps(subject, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key = NOTIONAL_POSITION_LEAD_PREFIX + hashlib.sha256(encoded).hexdigest()
    with JournalUnitOfWork(conn):
        conn.execute(
            "INSERT INTO sentinel_processed_sessions(cursor_name,session,state)"
            " VALUES (%s,%s,%s::jsonb) ON CONFLICT (cursor_name) DO NOTHING",
            (key, observed_at.date(), json.dumps(dict(
                subject, first_observed_at=observed_at.isoformat()))))
        saved = conn.execute(
            "SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s", (key,)).fetchone()[0]
        if not isinstance(saved, dict) or {k: v for k, v in saved.items() if k != "first_observed_at"} != subject:
            raise RuntimeError("notional position lead changed its durable order subject")
        first_observed_at = datetime.fromisoformat(saved["first_observed_at"])
        if first_observed_at.tzinfo is None or first_observed_at > observed_at:
            raise RuntimeError("notional position lead clock is invalid")
    return observed_at - first_observed_at <= grace


def _signed_gross(side, gross):
    if side is Side.BUY:
        return -gross
    if side is Side.SELL:
        return gross
    raise ValueError("fill cash impact is missing its native side")


def validate_posted_cash(side, qty, price, cash_amount):
    price = Fraction(price)
    reported = Fraction(cash_amount)
    signed = _signed_gross(side, Fraction(qty) * price)
    if reported * signed < 0 or abs(reported - signed) > _CENT / 2 + _SHARE_INCREMENT * price:
        raise ValueError("posted trade cash contradicts its native shares, side or price")


def _validate_notional(notional, *, gross, prices, complete):
    if notional is None:
        return
    tolerance = _CENT + _SHARE_INCREMENT * sum((Fraction(price) for price in prices), Fraction(0))
    requested = Fraction(notional)
    if gross > requested + tolerance or (complete and gross < requested - tolerance):
        raise ValueError("native executions contradict the requested order notional")


@dataclass(frozen=True)
class FillEconomics:
    gross: Fraction
    cash: Fraction


@dataclass(frozen=True)
class OwnedFillCoverage:
    command: Command
    quantity: Decimal
    cash_missing: bool


def owned_fill_coverage(conn, commands):
    """Find current fractional orders whose fill facts are needed by plan cash."""
    from sentinel.execution import fractional_progress, journal, target_reprojection
    if not commands:
        return {}
    plan = journal.latest_plan(conn)
    if plan is None:
        return {}
    owned = {c.client_key: c for c in commands if c.identity.plan_id == plan.plan_id
             and c.state not in {CommandState.PLANNED, CommandState.SUPERSEDED}}
    if not owned or not fractional_progress.is_fractional(
            target_reprojection.load_projection(conn, plan_id=plan.plan_id)):
        return {}
    rows = conn.execute(
        "SELECT f.client_key,SUM(f.quantity),"
        " BOOL_OR(LENGTH(f.fill_key)=64 AND cash.cursor_name IS NULL) FROM sentinel_fills f"
        " JOIN sentinel_commands c ON c.client_key=f.client_key AND c.broker_order_id=f.broker_order_id"
        " LEFT JOIN sentinel_processed_sessions cash ON cash.cursor_name=%s || f.fill_key"
        " WHERE f.client_key=ANY(%s) GROUP BY f.client_key",
        (journal.FILL_CASH_PREFIX, list(owned))).fetchall()
    covered = {key: (quantity, missing) for key, quantity, missing in rows}
    return {key: OwnedFillCoverage(command, *covered.get(key, (Decimal(0), False)))
            for key, command in owned.items()}


def _serialized_average_gross_interval(quantity, average):
    quantity = Fraction(quantity)
    average = Decimal(average)
    if not average.is_finite() or average <= 0 or quantity < 0:
        return None
    expected = quantity * Fraction(average)
    exponent = average.as_tuple().exponent
    tolerance = (quantity * Fraction(10) ** exponent / 2
                 if exponent < 0 else Fraction(0))
    return expected - tolerance, expected + tolerance


def gross_matches_serialized_average(quantity, gross, average):
    interval = _serialized_average_gross_interval(quantity, average)
    return interval is not None and interval[0] <= Fraction(gross) <= interval[1]


def _posted_cash(state, *, order_id, client_key, side, qty, price):
    if (not isinstance(state, dict) or set(state) != {"order_id", "client_key", "amount"}
            or state["order_id"] != order_id or state["client_key"] != client_key):
        raise ValueError("posted trade cash is not bound to the owned fill")
    try:
        amount = Decimal(state["amount"])
        if not amount.is_finite():
            raise InvalidOperation
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("posted trade cash must be a finite decimal") from exc
    validate_posted_cash(side, qty, price, amount)
    return amount


def _nearest_usd(signed):
    cents = signed / _CENT
    if cents % 1 == Fraction(1, 2):
        raise PostedFillCashIncomplete("Alpaca USD posting at a half cent requires native cash evidence")
    return round(cents) * _CENT


def _native_cash_with_omissions(command, *, gross, known, missing):
    # The Alpaca customer agreement specifies cent rounding on sales. Confirm
    # that rounding per execution and rounding the order give the same amount.
    # A completed dollar BUY also has an exact cent-denominated request, and
    # that request must agree with both calculations before deriving cash.
    if not is_terminal(command.state):
        raise PostedFillCashIncomplete("working order has unconfirmed sub-cent native cash")
    rounded = known + sum((_nearest_usd(value) for value in missing), Fraction(0))
    if rounded != _nearest_usd(_signed_gross(command.side, gross)):
        raise PostedFillCashIncomplete("Alpaca USD posting differs by rounding boundary")
    if command.side is Side.BUY and (command.notional is None
            or command.state is not CommandState.FILLED or rounded != -Fraction(command.notional)):
        raise PostedFillCashIncomplete("buy with unconfirmed sub-cent native cash")
    return rounded


def exact_fill_economics(conn, command, *, verify_notional=True, require_cash=True) -> FillEconomics:
    """Verify executed principal and signed cash from the same owned fill set."""
    from sentinel.execution.journal import FILL_CASH_PREFIX
    if command.filled_quantity == 0:
        return FillEconomics(Fraction(0), Fraction(0))
    if not command.broker_order_id:
        raise ValueError("filled command has no native order identity")
    rows = conn.execute(
        "SELECT f.fill_key,f.quantity,f.price,cash.state FROM sentinel_fills f"
        " LEFT JOIN sentinel_processed_sessions cash ON cash.cursor_name=%s || f.fill_key"
        " WHERE f.client_key=%s AND f.broker_order_id=%s",
        (FILL_CASH_PREFIX, command.client_key, command.broker_order_id)).fetchall()
    quantity, gross, cash = Fraction(0), Fraction(0), Fraction(0)
    missing = []
    for key, qty, price, posted in rows:
        principal = Fraction(qty) * Fraction(price)
        quantity += Fraction(qty)
        gross += principal
        if posted is None:
            signed = _signed_gross(command.side, principal)
            # Native activity hashes use the full SHA-256 digest. Legacy
            # price/quantity fingerprints use a 24-character prefix.
            if require_cash and command.identity.deployment.broker == ALPACA_PAPER_BROKER and len(key) == 64:
                missing.append(signed)
            else:
                cash += signed
        else:
            cash += Fraction(_posted_cash(posted, order_id=command.broker_order_id,
                client_key=command.client_key, side=command.side, qty=qty, price=price))
    expected = command.filled_quantity
    average = command.filled_average_price
    if (average is None or quantity > expected or gross < 0
            or (quantity > 0 and gross == 0)):
        raise ValueError("native fill principal contradicts the durable command")
    complete = quantity == expected
    if verify_notional and command.notional is not None:
        prices = [price for _, _, price, _ in rows]
        _validate_notional(command.notional, gross=gross, prices=prices,
                           complete=complete and command.state is CommandState.FILLED)
    if not complete:
        if not partial_gross_leaves_positive_notional(expected, gross, average):
            raise ValueError("native fills leave no positive principal for missing shares")
        raise FillHistoryIncomplete("exact native fill coverage is required")
    if not gross_matches_serialized_average(expected, gross, average):
        raise ValueError("native fill principal contradicts the durable order average")
    if any(value % _CENT for value in missing):
        cash = _native_cash_with_omissions(command, gross=gross, known=cash, missing=missing)
    else:
        cash += sum(missing, Fraction(0))
    if verify_notional and command.notional is not None:
        _validate_notional(command.notional, gross=-cash, prices=prices, complete=False)
    return FillEconomics(gross, cash)


def partial_gross_leaves_positive_notional(quantity, gross, average):
    interval = _serialized_average_gross_interval(quantity, average)
    return interval is not None and Fraction(gross) < interval[1]


def validate(observation, orders, *, position_leading_order_ids=()):
    totals, gross, prices, posted_debits, seen = {}, {}, {}, {}, set()
    for fill in observation.fills:
        order = orders.get(fill.broker_order_id)
        if order is None:
            raise ValueError('native fill omitted exact order')
        if not is_sentinel_key(order.client_key):
            continue
        native = getattr(fill, 'activity_id', None)
        if native:
            if native in seen:
                raise ValueError('duplicate native execution identity')
            seen.add(native)
            if (getattr(fill, 'asset_id', None) != order.instrument.broker_id
                    or getattr(fill, 'side', None) is not order.side):
                raise ValueError('native fill asset or side contradicts order')
        if fill.client_key not in (None, order.client_key):
            raise ValueError('native fill client key contradicts order')
        if (fill.filled_at is None or order.submitted_at is None
                or fill.filled_at < order.submitted_at
                or fill.filled_at > observation.observed_at):
            raise ValueError('native fill time is outside order observation lifetime')
        # Sentinel issues ordinary DAY orders. Publication may be late; the
        # execution itself cannot move into a later session.
        from zoneinfo import ZoneInfo
        from sentinel.feed import calendar
        day = order.submitted_at.astimezone(ZoneInfo(calendar.EXCHANGE_TZ)).date()
        _, closed = calendar.session_window(day)
        if fill.filled_at > closed:
            raise ValueError('native fill executes after the DAY order session')
        key = order.broker_order_id
        principal = Fraction(fill.quantity) * Fraction(fill.price)
        posted = getattr(fill, 'cash_amount', None)
        if posted is not None:
            validate_posted_cash(order.side, fill.quantity, fill.price, posted)
        totals[key] = totals.get(key, Fraction(0)) + Fraction(fill.quantity)
        gross[key] = gross.get(key, Fraction(0)) + principal
        prices.setdefault(key, []).append(fill.price)
        posted_debits[key] = posted_debits.get(key, Fraction(0)) + (
            principal if posted is None else -Fraction(posted))
    ahead = set()
    for key, quantity in totals.items():
        order = orders[key]
        _validate_notional(order.notional, gross=gross[key], prices=prices[key],
                           complete=quantity == order.filled_quantity and order.state is CommandState.FILLED)
        _validate_notional(order.notional, gross=posted_debits[key], prices=prices[key], complete=False)
        if quantity > order.filled_quantity:
            if key not in position_leading_order_ids:
                raise ValueError('native fill quantity exceeds cumulative order fills')
            ahead.add(key)
        if (quantity < Fraction(order.filled_quantity)
                and not partial_gross_leaves_positive_notional(
                    order.filled_quantity, gross[key], order.filled_average_price)):
            raise ValueError('native partial fill gross leaves no positive notional for missing fills')
        if quantity == Fraction(order.filled_quantity):
            if not gross_matches_serialized_average(
                    quantity, gross[key], order.filled_average_price):
                raise ValueError('native fill gross notional contradicts cumulative order')
    if observation.fill_history_complete:
        for key, order in orders.items():
            if is_sentinel_key(order.client_key) and totals.get(key, 0) != Fraction(order.filled_quantity):
                raise FillHistoryIncomplete('native fill history does not cover cumulative order fills')
    return ahead


def retain_refusal(conn, observation, reason):
    payload = {'schema': 'sentinel.native-fill-refusal/1', 'reason': str(reason),
               'observation': asdict(observation)}
    _retain(conn, payload, observation.observed_at.date())


@dataclass(frozen=True)
class _DurableCashFill(BrokerFill):
    cash_amount: Decimal | None = None


def validate_durable(conn, observation, orders, *, position_leading_order_ids=()):
    """Validate the immutable union, including across producer reads/restarts.

    Reconciliation holds the account's single-writer lock until publication.
    Rows from a previous accepted read cannot disappear or acquire a second ID.
    """
    from sentinel.execution.journal import FILL_CASH_PREFIX, fill_fingerprint

    incoming = {fill_fingerprint(f): f for f in observation.fills}
    merged = dict(incoming)
    rows = conn.execute(
        'SELECT f.fill_key,f.broker_order_id,f.client_key,f.quantity,f.price,f.filled_at,cash.state '
        'FROM sentinel_fills f LEFT JOIN sentinel_processed_sessions cash '
        'ON cash.cursor_name=%s || f.fill_key WHERE f.broker_order_id=ANY(%s) OR f.fill_key=ANY(%s)',
        (FILL_CASH_PREFIX, list(orders), list(incoming))).fetchall()
    for key, order_id, client_key, quantity, price, filled_at, state in rows:
        current = incoming.get(key)
        order = orders.get(order_id)
        posted = None if state is None or order is None else _posted_cash(state, order_id=order_id,
            client_key=order.client_key, side=order.side, qty=quantity, price=price)
        if current is not None:
            if (order_id != current.broker_order_id or order is None
                    or client_key not in (None, order.client_key)
                    or quantity != current.quantity or price != current.price
                    or filled_at != current.filled_at):
                raise ValueError('native fill contradicts immutable durable execution')
            if posted is not None:
                incoming_cash = getattr(current, 'cash_amount', None)
                if incoming_cash is not None and incoming_cash != posted:
                    raise ValueError('native fill contradicts immutable durable cash impact')
                if incoming_cash is None:
                    merged[key] = replace(current, cash_amount=posted)
        elif observation.fill_history_complete:
            raise FillHistoryIncomplete('complete native history omitted durable execution identity')
        else:
            merged[key] = _DurableCashFill(broker_order_id=order_id, client_key=client_key,
                quantity=quantity, price=price, filled_at=filled_at, cash_amount=posted)
    return validate(replace(observation, fills=tuple(merged.values())), orders,
                    position_leading_order_ids=position_leading_order_ids)


def retain_native_refusal(conn, identity, reason):
    from datetime import datetime, timezone
    payload = {'schema': 'sentinel.native-fill-refusal/1', 'reason': str(reason),
               'account_identity': asdict(identity), 'raw_event': reason.raw_event}
    _retain(conn, payload, datetime.now(timezone.utc).date())


def _retain(conn, payload, session):
    from sentinel.execution.journal import JournalUnitOfWork
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
    key = 'native-fill-refusal:' + hashlib.sha256(encoded.encode()).hexdigest()
    with JournalUnitOfWork(conn):
        conn.execute('INSERT INTO sentinel_processed_sessions (cursor_name,session,state) '
                     'VALUES (%s,%s,%s::jsonb) ON CONFLICT (cursor_name) DO NOTHING',
                     (key, session, encoded))


def require_durable_coverage(conn, binding, *, allow_incomplete=False):
    """A partial/absent cached history cannot freeze a dividend entitlement."""
    from sentinel.trial import TrialEvidenceRefused
    complete = True
    with conn.cursor() as cur:
        cur.execute(
            'SELECT c.client_key,c.state,c.filled_quantity,c.filled_average_price,'
            'COALESCE(SUM(f.quantity),0),COALESCE(SUM(f.quantity*f.price),0) '
            'FROM sentinel_commands c LEFT JOIN sentinel_fills f '
            'ON f.client_key=c.client_key AND f.broker_order_id=c.broker_order_id '
            'WHERE c.broker=%s AND c.broker_account_id=%s '
            'GROUP BY c.client_key,c.state,c.filled_quantity,c.filled_average_price',
            (binding['broker'], binding['broker_account_id']))
        for key, state, quantity, average, filled, gross in cur.fetchall():
            from sentinel.execution.states import IN_FLIGHT, CommandState
            if CommandState(state) in IN_FLIGHT:
                raise TrialEvidenceRefused('paper dividend ownership has unresolved commands: ' + key)
            quantity, filled, gross = map(Decimal, (quantity, filled, gross))
            if allow_incomplete and filled < quantity:
                if (not all(value.is_finite() for value in (quantity, filled, gross))
                        or filled < 0 or gross < 0 or average is None
                        or not Decimal(average).is_finite() or Decimal(average) <= 0
                        or (filled == 0 and gross != 0)
                        or (filled > 0 and gross <= 0)
                        or not partial_gross_leaves_positive_notional(
                            quantity, gross, average)):
                    raise TrialEvidenceRefused('paper dividend ownership has contradictory native fills: ' + key)
                complete = False
                continue
            if (quantity != filled or (quantity and
                    (average is None or not gross_matches_serialized_average(
                        quantity, gross, average)))):
                raise TrialEvidenceRefused('paper dividend ownership lacks complete native fills: ' + key)
    return complete
