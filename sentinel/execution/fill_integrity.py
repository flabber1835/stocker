"""Validate native execution history before it becomes economic authority."""
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import json

from sentinel.execution.identity import is_sentinel_key
from sentinel.execution.contract import Side
from sentinel.execution.states import CommandState


class FillHistoryIncomplete(ValueError):
    pass


_CENT = Fraction("0.01")
_SHARE_INCREMENT = Fraction("0.000000001")


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
        "SELECT f.client_key,SUM(f.quantity) FROM sentinel_fills f"
        " JOIN sentinel_commands c ON c.client_key=f.client_key AND c.broker_order_id=f.broker_order_id"
        " WHERE f.client_key=ANY(%s) GROUP BY f.client_key", (list(owned),)).fetchall()
    covered = dict(rows)
    return {key: (command, covered.get(key, Decimal(0))) for key, command in owned.items()}


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


def exact_fill_economics(conn, command, *, verify_notional=True) -> FillEconomics:
    """Verify executed principal and signed cash from the same owned fill set."""
    from sentinel.execution.journal import FILL_CASH_PREFIX
    if command.filled_quantity == 0:
        return FillEconomics(Fraction(0), Fraction(0))
    if not command.broker_order_id:
        raise ValueError("filled command has no native order identity")
    rows = conn.execute(
        "SELECT f.quantity,f.price,cash.state FROM sentinel_fills f"
        " LEFT JOIN sentinel_processed_sessions cash ON cash.cursor_name=%s || f.fill_key"
        " WHERE f.client_key=%s AND f.broker_order_id=%s",
        (FILL_CASH_PREFIX, command.client_key, command.broker_order_id)).fetchall()
    quantity, gross, cash = Fraction(0), Fraction(0), Fraction(0)
    for qty, price, posted in rows:
        principal = Fraction(qty) * Fraction(price)
        quantity += Fraction(qty)
        gross += principal
        if posted is None:
            cash += _signed_gross(command.side, principal)
        else:
            if (not isinstance(posted, dict) or set(posted) != {"order_id", "client_key", "amount"}
                    or posted["order_id"] != command.broker_order_id or posted["client_key"] != command.client_key):
                raise ValueError("posted trade cash is not bound to the owned fill")
            try:
                amount = Decimal(posted["amount"])
                if not amount.is_finite():
                    raise InvalidOperation
            except (InvalidOperation, TypeError) as exc:
                raise ValueError("posted trade cash must be a finite decimal") from exc
            validate_posted_cash(command.side, qty, price, amount)
            cash += Fraction(amount)
    expected = command.filled_quantity
    average = command.filled_average_price
    if (average is None or quantity > expected or gross < 0
            or (quantity > 0 and gross == 0)):
        raise ValueError("native fill principal contradicts the durable command")
    complete = quantity == expected
    if verify_notional and command.notional is not None:
        prices = [price for _, price, _ in rows]
        _validate_notional(command.notional, gross=gross, prices=prices,
                           complete=complete and command.state is CommandState.FILLED)
        _validate_notional(command.notional, gross=-cash, prices=prices, complete=False)
    if not complete:
        if not partial_gross_leaves_positive_notional(expected, gross, average):
            raise ValueError("native fills leave no positive principal for missing shares")
        raise FillHistoryIncomplete("exact native fill coverage is required")
    if not gross_matches_serialized_average(expected, gross, average):
        raise ValueError("native fill principal contradicts the durable order average")
    return FillEconomics(gross, cash)


def partial_gross_leaves_positive_notional(quantity, gross, average):
    interval = _serialized_average_gross_interval(quantity, average)
    return interval is not None and Fraction(gross) < interval[1]


def validate(observation, orders):
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
        if totals[key] > Fraction(order.filled_quantity):
            raise ValueError('native fill quantity exceeds cumulative order fills')
    for key, quantity in totals.items():
        order = orders[key]
        _validate_notional(order.notional, gross=gross[key], prices=prices[key],
                           complete=quantity == order.filled_quantity and order.state is CommandState.FILLED)
        _validate_notional(order.notional, gross=posted_debits[key], prices=prices[key], complete=False)
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


def retain_refusal(conn, observation, reason):
    payload = {'schema': 'sentinel.native-fill-refusal/1', 'reason': str(reason),
               'observation': asdict(observation)}
    _retain(conn, payload, observation.observed_at.date())


def validate_durable(conn, observation, orders):
    """Validate the immutable union, including across producer reads/restarts.

    Reconciliation holds the account's single-writer lock until publication.
    Rows from a previous accepted read cannot disappear or acquire a second ID.
    """
    from sentinel.execution.contract import BrokerFill
    from sentinel.execution.journal import fill_fingerprint

    incoming = {fill_fingerprint(f): f for f in observation.fills}
    merged = dict(incoming)
    rows = conn.execute(
        'SELECT fill_key,broker_order_id,client_key,quantity,price,filled_at '
        'FROM sentinel_fills WHERE broker_order_id=ANY(%s) OR fill_key=ANY(%s)',
        (list(orders), list(incoming))).fetchall()
    for key, order_id, client_key, quantity, price, filled_at in rows:
        current = incoming.get(key)
        if current is not None:
            order = orders.get(current.broker_order_id)
            if (order_id != current.broker_order_id or order is None
                    or client_key not in (None, order.client_key)
                    or quantity != current.quantity or price != current.price
                    or filled_at != current.filled_at):
                raise ValueError('native fill contradicts immutable durable execution')
        elif observation.fill_history_complete:
            raise FillHistoryIncomplete('complete native history omitted durable execution identity')
        else:
            merged[key] = BrokerFill(broker_order_id=order_id, client_key=client_key,
                quantity=quantity, price=price, filled_at=filled_at)
    validate(replace(observation, fills=tuple(merged.values())), orders)


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
