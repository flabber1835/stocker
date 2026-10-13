"""Source-bound economic identity across same-symbol CUSIP name changes."""
from datetime import date

from pydantic import Field

from sentinel.feed.alpaca_observation import action_participants
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
    modern = reference.get('schema') == 'sentinel.rolling-alpaca-openfigi-references/3'
    if (source.get('provider') != 'ALPACA_OPENFIGI'
            or version not in ('sentinel.alpaca-openfigi-operational-source/1',
                               'sentinel.alpaca-openfigi-operational-source/2',
                               'sentinel.alpaca-openfigi-operational-source/3')
            or reference.get('schema') not in ('sentinel.rolling-alpaca-openfigi-references/2',
                                              'sentinel.rolling-alpaca-openfigi-references/3')
            or (version != 'sentinel.alpaca-openfigi-operational-source/1') != modern):
        raise AlpacaTransportRefused('unbound published Alpaca identity source')
    raw = reference.get('identity_bindings', [])
    if (modern and digest(raw) != source.get('identity_bindings_sha256')) or (not modern and raw):
        raise AlpacaTransportRefused('published Alpaca identity binding digest mismatch')
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
