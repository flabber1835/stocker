"""Validate native execution history before it becomes economic authority."""
from dataclasses import asdict, replace
from decimal import Decimal
from fractions import Fraction
import hashlib
import json

from sentinel.execution.identity import is_sentinel_key


class FillHistoryIncomplete(ValueError):
    pass


def validate(observation, orders):
    totals, gross, seen = {}, {}, set()
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
        totals[key] = totals.get(key, Fraction(0)) + Fraction(fill.quantity)
        gross[key] = gross.get(key, Fraction(0)) + Fraction(fill.quantity) * Fraction(fill.price)
        if totals[key] > Fraction(order.filled_quantity):
            raise ValueError('native fill quantity exceeds cumulative order fills')
    for key, quantity in totals.items():
        order = orders[key]
        expected = Fraction(order.filled_quantity) * Fraction(order.filled_average_price)
        if quantity < Fraction(order.filled_quantity) and gross[key] >= expected:
            raise ValueError('native partial fill gross leaves no positive notional for missing fills')
        if quantity == Fraction(order.filled_quantity):
            if gross[key] != expected:
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


def require_durable_coverage(conn, binding):
    """A partial/absent cached history cannot freeze a dividend entitlement."""
    from sentinel.trial import TrialEvidenceRefused
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
            if (quantity != filled or (quantity and
                    (average is None or Fraction(gross) != Fraction(quantity) * Fraction(average)))):
                raise TrialEvidenceRefused('paper dividend ownership lacks complete native fills: ' + key)
