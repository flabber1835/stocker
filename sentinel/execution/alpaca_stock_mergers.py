"""Raw account evidence and restricted accounting for exact Alpaca share receipts."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
import re
from uuid import UUID

from sentinel.feed.rolling_contract import canonical_json, digest


PREFIX = 'alpaca-stock-merger-leg:v1:'
SCHEMA = 'sentinel.alpaca-stock-merger-leg/1'
_ULID = re.compile(r'[0-7][0-9A-HJKMNP-TV-Z]{25}')
_CUSIP = re.compile(r'[A-Z0-9]{9}')
_MAX_LEGS = 4096


class StockMergerEvidenceRefused(RuntimeError):
    pass


def _uuid(value):
    return isinstance(value, str) and bool(value) and str(UUID(value)) == value and UUID(value).int != 0


def _scope(broker, account_id):
    return PREFIX + digest([broker, account_id]) + ':'


def _candidate(raw):
    return raw.get('activity_type') in {'MA', 'CIL'} or (
        raw.get('activity_type') == 'DIV' and raw.get('activity_subtype') == 'SDIV')


def _check_raw(raw, *, native, key):
    try:
        valid = (isinstance(raw, dict) and _candidate(raw)
                 and _uuid(key) and _uuid(native) and raw.get('ref_id') == key
                 and isinstance(raw.get('event_id'), str) and _ULID.fullmatch(raw['event_id'])
                 and raw.get('account_id', native) == native)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise StockMergerEvidenceRefused('Alpaca merger activity identity is malformed')


def _load(conn, *, broker, account_id, proof, prefix):
    rows = conn.execute(
        'SELECT cursor_name, state FROM sentinel_processed_sessions'
        ' WHERE cursor_name LIKE %s ORDER BY cursor_name LIMIT %s',
        (prefix + '%', _MAX_LEGS + 1)).fetchall()
    if len(rows) > _MAX_LEGS:
        raise StockMergerEvidenceRefused('Alpaca merger activity inventory exceeds its bound')
    if proof is None:
        if rows:
            raise StockMergerEvidenceRefused('Alpaca merger activities exist without their committed cursor')
        return {}
    try:
        valid = (isinstance(proof, dict) and set(proof) == {'native_account_id', 'sha256'}
                 and _uuid(proof['native_account_id']) and isinstance(proof['sha256'], str)
                 and re.fullmatch(r'[0-9a-f]{64}', proof['sha256']))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise StockMergerEvidenceRefused('Alpaca merger activity commitment is malformed')
    retained = {}
    native = proof['native_account_id']
    for name, state in rows:
        ref_id = name.removeprefix(prefix)
        if (not isinstance(state, dict) or set(state) != {'schema', 'scope', 'raw'}
                or state['schema'] != SCHEMA or state['scope'] != [broker, account_id, native]):
            raise StockMergerEvidenceRefused('Alpaca merger activity row changed scope')
        _check_raw(state['raw'], native=native, key=ref_id)
        retained[ref_id] = state['raw']
    if digest(retained) != proof['sha256']:
        raise StockMergerEvidenceRefused('Alpaca merger activity inventory differs from its commitment')
    if len({row['event_id'] for row in retained.values()}) != len(retained):
        raise StockMergerEvidenceRefused('Alpaca merger activities repeat a publication identity')
    return retained


def record(conn, *, broker, account_id, prior, native_account, activities):
    """Append raw activities and return the new cash-cursor commitment."""
    prefix = _scope(broker, account_id)
    retained = _load(conn, broker=broker, account_id=account_id, proof=prior, prefix=prefix)
    if not isinstance(native_account, tuple) or len(native_account) != 3:
        raise StockMergerEvidenceRefused('Alpaca merger activities lack native account provenance')
    actual_broker, actual_account, native = native_account
    try:
        valid = (actual_broker, actual_account) == (broker, account_id) and _uuid(native)
    except (ValueError, TypeError):
        valid = False
    if not valid or (prior is not None and prior['native_account_id'] != native):
        raise StockMergerEvidenceRefused('Alpaca merger activity native account changed')
    seen = {row['event_id'] for row in retained.values()}
    for activity in activities:
        raw = activity.raw
        if not _candidate(raw):
            continue
        ref_id = activity.activity_id
        _check_raw(raw, native=native, key=ref_id)
        if ref_id in retained:
            if retained[ref_id] != raw:
                raise StockMergerEvidenceRefused('Alpaca merger activity changed under its native identity')
            continue
        if raw['event_id'] in seen or len(retained) >= _MAX_LEGS:
            raise StockMergerEvidenceRefused('Alpaca merger activity publication conflicts or exceeds bound')
        state = dict(schema=SCHEMA, scope=[broker, account_id, native], raw=raw)
        conn.execute('INSERT INTO sentinel_processed_sessions (cursor_name,session,state)'
                     ' VALUES (%s,%s,%s::jsonb)',
                     (prefix + ref_id, activity.activity_date, canonical_json(state)))
        retained[ref_id] = raw
        seen.add(raw['event_id'])
    return dict(native_account_id=native, sha256=digest(retained))


def verify_restored(conn, *, state):
    prefix = _scope(state.broker, state.account_id) if state is not None else None
    orphans = conn.execute(
        'SELECT EXISTS (SELECT 1 FROM sentinel_processed_sessions'
        ' WHERE cursor_name LIKE %s AND (%s::text IS NULL OR cursor_name NOT LIKE %s))',
        (PREFIX + '%', prefix, None if prefix is None else prefix + '%')).fetchone()
    if orphans[0]:
        raise StockMergerEvidenceRefused('restored Alpaca merger activities have no bound cursor')
    if state is not None:
        _load(conn, broker=state.broker, account_id=state.account_id,
              proof=state.stock_merger_proof, prefix=prefix)


def _money_or_qty(value):
    if not isinstance(value, str) or not re.fullmatch(r'-?[0-9]{1,24}(?:\.[0-9]{1,12})?', value):
        raise ValueError('invalid decimal')
    return Fraction(Decimal(value))


def _day(value):
    day = date.fromisoformat(value)
    if day.isoformat() != value:
        raise ValueError('invalid date')
    return day


@dataclass(frozen=True)
class Movement:
    group: tuple[str, str]
    old_asset: str
    new_asset: str
    old_quantity: Fraction
    new_quantity: Fraction
    position_date: date
    effective_date: date


def _posted(raw, *, observed_at):
    executed = datetime.fromisoformat(raw['executed_at'].replace('Z', '+00:00'))
    return (raw.get('status') == 'executed' and raw.get('currency') == 'USD'
            and not raw.get('previous_id') and not _money_or_qty(raw['net_amount'])
            and executed.utcoffset() is not None and executed <= observed_at
            and _day(raw['settle_date']) <= observed_at.date())


def _movement(group, rows, *, observed_at):
    if len(rows) != 2:
        return None
    try:
        quantities = []
        for raw in rows:
            if (raw.get('activity_type') != 'MA' or raw.get('activity_subtype') != 'SMA'
                    or not _posted(raw, observed_at=observed_at)):
                return None
            quantities.append((_money_or_qty(raw['qty']), raw))
        quantities.sort(key=lambda item: item[0])
        (removed, old), (received, new) = quantities
        detail = old['details']
        fields = ('position_date', 'effective_date', 'acquiree_qty', 'acquirer_qty',
                  'acquirer_rate', 'acquiree_rate', 'acquiree_cusip', 'acquirer_cusip')
        if any(detail[key] != new['details'][key] for key in fields):
            return None
        position, effective = _day(detail['position_date']), _day(detail['effective_date'])
        old_qty, new_qty = (_money_or_qty(detail[key]) for key in ('acquiree_qty', 'acquirer_qty'))
        old_rate, new_rate = (_money_or_qty(detail[key]) for key in ('acquiree_rate', 'acquirer_rate'))
        old_asset, new_asset = old['asset'], new['asset']
        if (position > effective or effective > observed_at.date() or min(old_qty, new_qty, old_rate, new_rate) <= 0
                or removed != -old_qty or received != new_qty or new_qty * old_rate != old_qty * new_rate
                or any(raw['details'].get(field) is not None for raw in rows
                       for field in ('cash_rate', 'cash_payout', 'cash_in_lieu'))
                or not _uuid(old_asset['id']) or not _uuid(new_asset['id']) or old_asset['id'] == new_asset['id']
                or any(not _CUSIP.fullmatch(detail[key]) or leg.get('cusip') != detail[key]
                       for key, leg in (('acquiree_cusip', old_asset), ('acquirer_cusip', new_asset)))
                or old_asset['cusip'] == new_asset['cusip']):
            return None
        return Movement(group, old_asset['id'], new_asset['id'], old_qty, new_qty, position, effective)
    except (KeyError, ValueError, TypeError, AttributeError, ArithmeticError):
        return None


def _stock_dividend(group, rows, *, observed_at):
    if len(rows) != 1:
        return None
    raw, = rows
    try:
        if ((raw.get('activity_type'), raw.get('activity_subtype')) != ('DIV', 'SDIV')
                or not _posted(raw, observed_at=observed_at)):
            return None
        detail = raw['details']
        old, paid, new = (_money_or_qty(detail[key]) for key in ('entitled_qty', 'paid_qty', 'new_qty'))
        asset = raw['asset']['id']
        position, effective = _day(detail['position_date']), _day(detail['ex_date'])
        if (not _uuid(asset) or min(old, paid) <= 0 or old + paid != new
                or _money_or_qty(raw['qty']) != paid or _money_or_qty(detail['rate']) <= 0
                or position > effective or effective > observed_at.date()
                or any(detail.get(key) is not None for key in ('cash_payout', 'cash_in_lieu'))):
            return None
        return Movement(group, asset, asset, old, paid, position, effective)
    except (KeyError, ValueError, TypeError, AttributeError, ArithmeticError):
        return None


def movements(raw_events, *, observed_at):
    """Recognize positively provable stock-only groups."""
    groups = defaultdict(list)
    assets = defaultdict(set)
    for row in raw_events:
        details = row.get('details')
        if not isinstance(details, dict):
            continue
        group = details.get('ca_id'), details.get('group_id')
        if all(isinstance(value, str) and 0 < len(value) <= 128 and value == value.strip()
               for value in group):
            groups[group].append(row)
            asset = row.get('asset')
            if isinstance(asset, dict) and isinstance(asset.get('id'), str):
                assets[asset['id']].add(group)
    recognized = []
    for group, rows in sorted(groups.items()):
        item = (_movement(group, rows, observed_at=observed_at)
                or _stock_dividend(group, rows, observed_at=observed_at))
        if item is not None:
            recognized.append(item)
    # A later compound asset movement needs date-ordered ownership replay.
    return tuple(item for item in recognized
                 if assets[item.old_asset] == assets[item.new_asset] == {item.group})


def explain(*, movements, commands, expected, observation, eligible):
    """Return scoped restrictions; never alter the command book or allocation."""
    from sentinel.execution.states import IN_FLIGHT

    positions = defaultdict(list)
    for position in observation.positions:
        positions[position.instrument.broker_id].append(position)
    restrictions = {}
    for item in movements:
        old_ids = {c.security_id for c in commands if c.instrument.broker_id == item.old_asset}
        successors = positions.get(item.new_asset, ())
        same_asset = item.old_asset == item.new_asset
        if (len(old_ids) != 1 or len(successors) != 1
                or (not same_asset and item.old_asset in positions)):
            continue
        successor, = successors
        old, = old_ids
        new = successor.instrument.security_id
        if ((old == new) != same_asset or old in restrictions or new in restrictions
                or (not same_asset and any(p.instrument.security_id == old for p in observation.positions))
                or Fraction(expected.get(old, 0)) != item.old_quantity
                or Fraction(successor.quantity) - Fraction(expected.get(new, 0)) != item.new_quantity):
            continue
        pair = {old: item.old_asset, new: item.new_asset}
        intersect = tuple(c for c in commands
            if c.security_id in pair or c.instrument.broker_id in pair.values())
        if (any(c.state in IN_FLIGHT or pair.get(c.security_id) != c.instrument.broker_id for c in intersect)
                or any(o.is_working and (o.instrument.security_id in pair
                       or o.instrument.broker_id in pair.values()) for o in observation.orders)
                or not eligible(item, intersect, pair)):
            continue
        reason = 'CORPORATE_ACTION_RECEIPT_RESTRICTED: ' + ':'.join(item.group)
        restrictions.update({old: reason, new: reason})
    return restrictions


def reconciled_restrictions(conn, *, state, deployment, actions, commands, expected, observation):
    from sentinel.execution import journal
    from sentinel.feed import calendar

    identity = observation.account_identity
    if (not observation.is_complete or not deployment.matches_account(identity)
            or (state is not None and not deployment.matches_account(
                {'broker': state.broker, 'account_id': state.account_id}))):
        return {}
    if (state is None or state.stock_merger_proof is None
            or identity.raw.get('id') != state.stock_merger_proof.get('native_account_id')
            or not (observation.observed_at - timedelta(seconds=60)
                    <= state.processed_through <= observation.observed_at)):
        return {}
    retained = _load(conn, broker=state.broker, account_id=state.account_id,
        proof=state.stock_merger_proof, prefix=_scope(state.broker, state.account_id))
    candidates = movements(retained.values(), observed_at=observation.observed_at)
    material = getattr(actions, 'material_events_for', None)
    scalar = getattr(actions, 'scalar_evidence_for', None)
    if not candidates or not callable(material) or not callable(scalar):
        return {}

    def eligible(item, affected, pair):
        from sentinel.execution.commands import is_legacy_migration

        if calendar.previous_sessions(item.position_date, 1) != [item.position_date.isoformat()]:
            return False
        _, close = calendar.session_window(item.position_date)
        security_ids = set(pair)
        symbols = {c.instrument.symbol for c in affected}
        symbols.update(p.instrument.symbol for p in observation.positions
                       if p.instrument.security_id in pair)
        if (any(event.session >= item.position_date
                for event in tuple(material(security_ids=security_ids, symbols=symbols))
                + tuple(scalar(security_ids)))
                or any(c.created_at is None or c.created_at > close or is_legacy_migration(c)
                       for c in affected)):
            return False
        wanted = {c.client_key: Fraction(c.filled_quantity) for c in affected if c.filled_quantity}
        observed = defaultdict(Fraction)
        # Allow the exact active-fill relation introduced with trade amendments.
        table = getattr(journal, 'ACTIVE_FILLS', 'sentinel_fills')
        rows = conn.execute(f'SELECT client_key,quantity,filled_at FROM {table} active'
                            ' WHERE client_key=ANY(%s)', (sorted(wanted),)).fetchall()
        for client_key, quantity, filled_at in rows:
            if filled_at is None or filled_at > close:
                return False
            observed[client_key] += Fraction(quantity)
        return observed == wanted

    return explain(movements=candidates, commands=commands, expected=expected,
                   observation=observation, eligible=eligible)
