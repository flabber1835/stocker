"""Source-bound name continuity and distinct stock-merger identities."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from math import isfinite
import re

from pydantic import Field, model_validator

from sentinel.feed import calendar
from sentinel.feed.alpaca_observation import action_participants, structural_action_date
from sentinel.feed.alpaca_transport import AlpacaTransportRefused
from sentinel.feed.rolling_contract import Contract, Digest, digest


class NameChange(Contract):
    id: str = Field(min_length=1, max_length=128)
    old_symbol: str = Field(min_length=1, max_length=32)
    new_symbol: str = Field(min_length=1, max_length=32)
    old_cusip: str = Field(pattern=r'^[A-Z0-9]{9}$')
    new_cusip: str = Field(pattern=r'^[A-Z0-9]{9}$')
    process_date: date


class IdentityBinding(Contract):
    security_id: str = Field(min_length=1, max_length=128)
    provider_asset_id: str = Field(min_length=1, max_length=128)
    prior_provider_asset_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    origin_snapshot_id: Digest
    event: NameChange


def _positive_rate(value) -> Decimal:
    if isinstance(value, bool):
        raise AlpacaTransportRefused('stock merger rate is invalid')
    try:
        result = Decimal(str(value))
        number = float(result)
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        raise AlpacaTransportRefused('stock merger rate is invalid') from None
    if not result.is_finite() or result <= 0 or not isfinite(number) or number <= 0:
        raise AlpacaTransportRefused('stock merger rate is not finite and positive')
    return result


def _exact_ratio(record: dict) -> str:
    """The existing terminal contract accepts exact decimal ratios only."""
    old = _positive_rate(record.get('acquiree_rate'))
    new = _positive_rate(record.get('acquirer_rate'))
    value = Fraction(new) / Fraction(old)
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise AlpacaTransportRefused('stock merger ratio is not an exact decimal')
    scale = max(twos, fives)
    if scale > 100:
        raise AlpacaTransportRefused('stock merger ratio precision is unsupported')
    digits = str(value.numerator * 2 ** (scale - twos) * 5 ** (scale - fives))
    padded = digits.zfill(scale + 1)
    result = (digits if scale == 0 else padded[:-scale] + '.' + padded[-scale:])
    result = result.rstrip('0').rstrip('.') if '.' in result else result
    if not isfinite(float(result)) or float(result) <= 0:
        raise AlpacaTransportRefused('stock merger ratio is not finite and positive')
    return result


def _merger_record(record: dict) -> tuple[str, str]:
    """Validate the complete source roles before projecting any conversion."""
    if not isinstance(record, dict):
        raise AlpacaTransportRefused('stock merger record is malformed')
    for field in ('id', 'acquiree_symbol', 'acquirer_symbol'):
        value = record.get(field)
        if (not isinstance(value, str) or not value.strip()
                or len(value) > (128 if field == 'id' else 32)
                or value != value.strip()
                or (field != 'id' and value != value.upper())):
            raise AlpacaTransportRefused('stock merger identity is missing or ambiguous')
    for field in ('acquiree_cusip', 'acquirer_cusip'):
        value = record.get(field)
        if not isinstance(value, str) or re.fullmatch(r'[A-Z0-9]{9}', value) is None:
            raise AlpacaTransportRefused('stock merger CUSIP is missing or invalid')
    if record['acquiree_cusip'] == record['acquirer_cusip']:
        raise AlpacaTransportRefused('stock merger CUSIPs are not distinct')
    for field in ('process_date', 'effective_date'):
        value = record.get(field)
        try:
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except ValueError:
            raise AlpacaTransportRefused('stock merger date is missing or invalid') from None
    if record.get('cash_rate') is not None or record.get('stock_movements') is not None:
        raise AlpacaTransportRefused('stock merger has conflicting consideration')
    return calendar.session_on_or_after(record['effective_date']), _exact_ratio(record)


class MergerConversion(Contract):
    old_security_id: str = Field(min_length=1, max_length=128)
    old_provider_asset_id: str = Field(min_length=1, max_length=128)
    successor_security_id: str = Field(min_length=1, max_length=128)
    successor_provider_asset_id: str = Field(min_length=1, max_length=128)
    old_symbol: str = Field(min_length=1, max_length=32)
    successor_symbol: str = Field(min_length=1, max_length=32)
    old_cusip: str = Field(pattern=r'^[A-Z0-9]{9}$')
    successor_cusip: str = Field(pattern=r'^[A-Z0-9]{9}$')
    effective_session: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    exchange_ratio: str = Field(min_length=1, max_length=128)
    origin_snapshot_id: Digest
    record_id: str = Field(min_length=1, max_length=128)
    terms_sha256: Digest
    raw_record: dict

    @model_validator(mode='after')
    def bound_terms(self):
        record = self.raw_record
        effective, ratio = _merger_record(record)
        if (self.old_security_id == self.successor_security_id
                or self.old_provider_asset_id == self.successor_provider_asset_id
                or self.old_cusip != record['acquiree_cusip']
                or self.successor_cusip != record['acquirer_cusip']
                or self.old_symbol != record['acquiree_symbol']
                or self.successor_symbol != record['acquirer_symbol']
                or self.record_id != record['id']
                or str(self.effective_session) != effective
                or self.exchange_ratio != ratio
                or self.terms_sha256 != digest(record)):
            raise ValueError('stock merger source/identity binding changed')
        return self


def conversions(raw):
    """Validate immutable source-bound mergers independently of the controller."""
    if not isinstance(raw, list):
        raise AlpacaTransportRefused('invalid stock merger conversion inventory')
    values = [MergerConversion.model_validate(value) for value in raw]
    for field in ('old_security_id', 'old_provider_asset_id', 'record_id'):
        if len({getattr(value, field) for value in values}) != len(values):
            raise AlpacaTransportRefused('duplicate stock merger conversion: ' + field)
    return values


def merger_conversions(*, selected, previous_identity, bindings_raw, records,
                       target_session):
    """Project complete current-session terms; unsupported terms stay unconverted."""
    if previous_identity is None:
        return []
    prior_bindings = {value.provider_asset_id: value for value in
                      bindings(previous_identity['previous_bindings'])}
    prior = {item['ticker']: item for item in previous_identity['previous_selected']}
    current = {item['ticker']: item for item in canonical_assets(selected, bindings_raw)}
    provider = {item['ticker']: item for item in selected}
    by_old = {}
    for kind, record in records:
        if kind != 'stock_mergers' or not isinstance(record, dict) or record.get('acquiree_symbol') not in prior:
            continue
        day = structural_action_date(kind, record)
        if day is None or calendar.session_on_or_after(day) != target_session:
            continue
        by_old.setdefault(record['acquiree_symbol'], []).append(record)
    result = []
    for old_symbol, events in sorted(by_old.items()):
        supported = []
        for record in events:
            try:
                effective, ratio = _merger_record(record)
            except AlpacaTransportRefused:
                continue
            new_symbol = record['acquirer_symbol']
            predecessor, successor = prior[old_symbol], current.get(new_symbol)
            native_successor = provider.get(new_symbol)
            if successor is None or native_successor is None:
                continue
            if old_symbol != new_symbol and old_symbol in provider:
                # A still-active distinct acquiree listing has not ended.
                continue
            old_provider = predecessor['asset_id']
            inherited = prior_bindings.get(old_provider)
            old_sid = inherited.security_id if inherited else old_provider
            if old_sid == successor['asset_id'] or old_provider == native_successor['asset_id']:
                continue
            supported.append((record, effective, ratio, predecessor, successor,
                              native_successor, old_provider, old_sid))
        if not supported:
            continue
        if len(events) != 1 or len(supported) != 1:
            raise AlpacaTransportRefused('ambiguous stock merger conversion')
        (record, effective, ratio, predecessor, successor,
         native_successor, old_provider, old_sid) = supported[0]
        old_symbol, new_symbol = record['acquiree_symbol'], record['acquirer_symbol']
        for other_kind, other in records:
            if other is record:
                continue
            source_symbols = (frozenset((other.get('acquiree_symbol'),))
                              if other_kind == 'stock_mergers' else action_sources(other_kind, other))
            if old_symbol not in source_symbols:
                continue
            day = structural_action_date(other_kind, other)
            if day is None or (previous_identity['previous_session'] < day <= target_session):
                raise AlpacaTransportRefused('stock merger acquiree has conflicting action')
        value = MergerConversion(old_security_id=old_sid,
            old_provider_asset_id=old_provider,
            successor_security_id=successor['asset_id'],
            successor_provider_asset_id=native_successor['asset_id'],
            old_symbol=old_symbol, successor_symbol=new_symbol,
            old_cusip=record['acquiree_cusip'], successor_cusip=record['acquirer_cusip'],
            effective_session=effective, exchange_ratio=ratio,
            origin_snapshot_id=previous_identity['previous_snapshot_id'],
            record_id=record['id'], terms_sha256=digest(record), raw_record=deepcopy(record))
        result.append(value.model_dump(mode='json'))
    conversions(result)
    for symbol in {value['successor_symbol'] for value in result}:
        cusips = {value['successor_cusip'] for value in result if value['successor_symbol'] == symbol}
        if len(cusips) != 1:
            raise AlpacaTransportRefused('stock merger successor CUSIP conflicts')
    return sorted(result, key=lambda item: (item['old_security_id'], item['record_id']))


def bindings(raw):
    """Validate one-to-one immutable bindings before resolving any identity."""
    if not isinstance(raw, list):
        raise AlpacaTransportRefused('invalid Alpaca identity binding inventory')
    values = [IdentityBinding.model_validate(value) for value in raw]
    for field in ('security_id', 'provider_asset_id', 'ticker'):
        if len({getattr(value, field) for value in values}) != len(values):
            raise AlpacaTransportRefused('duplicate Alpaca identity binding: ' + field)
    for value in values:
        event = value.event
        if (event.old_symbol != value.ticker or event.new_symbol != value.ticker
                or event.old_cusip == event.new_cusip
                or value.provider_asset_id == value.prior_provider_asset_id):
            raise AlpacaTransportRefused('unproven Alpaca same-symbol identity binding')
    return values


def published_assets(reference, source):
    """Project prior provider IDs from authenticated, durable published identity."""
    version = source.get('schema')
    reference_schema = reference.get('schema')
    expected = {
        'sentinel.alpaca-openfigi-operational-source/1': 'sentinel.rolling-alpaca-openfigi-references/2',
        'sentinel.alpaca-openfigi-operational-source/2': 'sentinel.rolling-alpaca-openfigi-references/3',
        'sentinel.alpaca-openfigi-operational-source/3': 'sentinel.rolling-alpaca-openfigi-references/3',
        'sentinel.alpaca-openfigi-operational-source/4': 'sentinel.rolling-alpaca-openfigi-references/4',
    }
    modern = reference_schema in ('sentinel.rolling-alpaca-openfigi-references/3',
                                  'sentinel.rolling-alpaca-openfigi-references/4')
    if (source.get('provider') != 'ALPACA_OPENFIGI'
            or expected.get(version) != reference_schema):
        raise AlpacaTransportRefused('unbound published Alpaca identity source')
    raw = reference.get('identity_bindings', [])
    if (modern and digest(raw) != source.get('identity_bindings_sha256')) or (not modern and raw):
        raise AlpacaTransportRefused('published Alpaca identity binding digest mismatch')
    if reference_schema == 'sentinel.rolling-alpaca-openfigi-references/4':
        merger_raw = reference.get('merger_conversions')
        if digest(merger_raw) != source.get('merger_conversions_sha256'):
            raise AlpacaTransportRefused('published Alpaca merger digest mismatch')
        conversions(merger_raw)
    inherited = {value.ticker: value for value in bindings(raw)}
    tickers = reference.get('tickers')
    if not isinstance(tickers, list) or not tickers:
        raise AlpacaTransportRefused('published Alpaca identity references unavailable')
    result, canonical, seen = [], set(), set()
    for row in tickers:
        if not isinstance(row, dict):
            raise AlpacaTransportRefused('published Alpaca identity references invalid')
        ticker, sid = row.get('ticker'), row.get('permaticker')
        if (row.get('table') != 'SEP' or not isinstance(ticker, str) or not 1 <= len(ticker) <= 32
                or not isinstance(sid, str) or not 1 <= len(sid) <= 128
                or ticker in seen or sid in canonical):
            raise AlpacaTransportRefused('published Alpaca identity references ambiguous')
        value = inherited.get(ticker)
        if value is not None and value.security_id != sid:
            raise AlpacaTransportRefused('published Alpaca canonical identity mismatch')
        result.append(dict(ticker=ticker, asset_id=value.provider_asset_id if value else sid))
        seen.add(ticker);canonical.add(sid)
    for ticker, value in inherited.items():
        if ticker not in seen:
            if value.security_id in canonical:
                raise AlpacaTransportRefused('published Alpaca canonical identity collision')
            result.append(dict(ticker=ticker, asset_id=value.provider_asset_id))
            canonical.add(value.security_id)
    if len({row['asset_id'] for row in result}) != len(result):
        raise AlpacaTransportRefused('published Alpaca provider identity collision')
    return sorted(result, key=lambda row: row['ticker'])


def action_sources(kind, record):
    """A unit delivers common/warrants; it does not split existing recipients."""
    if kind == 'unit_splits':
        old = record.get('old_symbol')
        if (isinstance(old, str) and old.strip()
                and isinstance(record.get('old_cusip'), str)
                and isinstance(record.get('new_cusip'), str)
                and record['old_cusip'] != record['new_cusip']):
            return frozenset((old.strip().upper(),))
    return action_participants(record)


def bind(*, selected, previous_selected, previous_bindings, records,
         previous_session, target_session, previous_snapshot_id):
    """No price, holdings or broker input participates in continuity admission."""
    old = {item['ticker']: item for item in previous_selected}
    previous = {value.provider_asset_id: value for value in bindings(previous_bindings)}
    result = []
    for asset in selected:
        ticker, provider_id = asset['ticker'], asset['asset_id']
        prior = old.get(ticker)
        if prior is None:
            continue
        inherited = previous.get(prior['asset_id'])
        if inherited is not None and inherited.ticker != ticker:
            raise AlpacaTransportRefused('retained Alpaca identity listing changed')
        if inherited is not None and str(inherited.event.process_date) > previous_session:
            raise AlpacaTransportRefused('retained Alpaca identity event is in the future')
        if provider_id == prior['asset_id']:
            if inherited is not None:
                result.append(inherited.model_dump(mode='json'))
            continue
        events = [record for kind, record in records if kind == 'name_changes'
                  and ticker in action_participants(record)
                  and previous_session < record.get('process_date', '') <= target_session]
        if not events:
            # A genuinely new candidate keeps its new identity. A protected
            # missing identity still fails the ordinary economic-input guard.
            continue
        if len(events) != 1:
            raise AlpacaTransportRefused('ambiguous Alpaca name-change continuity')
        event = NameChange.model_validate(events[0])
        if (event.old_symbol != ticker or event.new_symbol != ticker
                or event.old_cusip == event.new_cusip):
            raise AlpacaTransportRefused('unsupported Alpaca name-change continuity')
        for kind, record in records:
            if kind != 'name_changes' and ticker in action_sources(kind, record):
                from sentinel.feed.alpaca_observation import structural_action_date
                day = structural_action_date(kind, record)
                if day is None or previous_session < day <= target_session:
                    raise AlpacaTransportRefused('economic action conflicts with Alpaca identity continuity')
        value = IdentityBinding(security_id=inherited.security_id if inherited else prior['asset_id'],
            provider_asset_id=provider_id, prior_provider_asset_id=prior['asset_id'],
            ticker=ticker, origin_snapshot_id=previous_snapshot_id, event=event)
        result.append(value.model_dump(mode='json'))
    bindings(result)
    return sorted(result, key=lambda value: value['security_id'])


def canonical_assets(selected, raw_bindings):
    values = {value.provider_asset_id: value for value in bindings(raw_bindings)}
    assets = []
    for asset in selected:
        binding = values.get(asset['asset_id'])
        if binding is not None and binding.ticker != asset['ticker']:
            raise AlpacaTransportRefused('Alpaca identity binding symbol mismatch')
        assets.append({**asset, 'asset_id': binding.security_id if binding else asset['asset_id']})
    if len({asset['asset_id'] for asset in assets}) != len(assets):
        raise AlpacaTransportRefused('Alpaca canonical identities collide')
    return assets
