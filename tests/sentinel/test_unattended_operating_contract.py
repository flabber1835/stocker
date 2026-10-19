"""Falsifiers for installation clocks, scoped staging and sparse free prices."""
from datetime import timedelta
from decimal import Decimal as D
import json
from types import SimpleNamespace

import pytest

from sentinel import backup_runtime_authority as backup, rolling_initialization as initial
from sentinel import shadow_observation as shadow
from sentinel.execution.contract import BrokerInstrument
from sentinel.execution.opening_prices import (
    LEGACY_QUOTE_SOURCE, QUOTE_SOURCE, SIP_QUOTE_SOURCE, OpeningPrices, OpeningPriceUnavailable,
    OpeningPriceNotReady, RegularQuotes, parse_quotes)
from sentinel.execution import opening_sizing
from sentinel.feed import calendar
from sentinel.strategy import production_strategy
from tests.v5.test_opening import case, base


def quote_payload(session, symbols=('AAA',), *, age=0):
    opened, _ = calendar.session_window(session)
    now = opened + timedelta(minutes=3)
    return {'quotes':{symbol:{'t':(now-timedelta(seconds=age)).isoformat(),
        'ap':100,'bp':99,'as':10,'bs':10} for symbol in symbols}}, now


def quotes(state, plan, *, available=None, age=0):
    target = opening_sizing.required_prices(state, plan)
    instruments = {sid:BrokerInstrument(sid, sid.removeprefix('SEC-'), 'asset-'+sid) for sid in target}
    symbols = {sid:item.symbol for sid,item in instruments.items()}
    payload, now = quote_payload(plan.effective_session,
        tuple(symbols[sid] for sid in target if available is None or sid in available), age=age)
    return parse_quotes(payload, session=plan.effective_session, instruments=instruments,
                        observed_at=now, broker_symbols=symbols)


def test_quote_roundtrip_binds_raw_sides_and_session():
    state, plan = case(entries=2, sale=True)
    evidence = quotes(state, plan)
    assert evidence.source == QUOTE_SOURCE == 'ALPACA_IEX_RAW_REGULAR_QUOTES_V2'
    assert OpeningPrices.from_dict(json.loads(json.dumps(evidence.to_dict()))) == evidence
    assert evidence.prices['SEC-AAA'] == 100 and evidence.bids['SEC-X'] == 99
    raw = evidence.to_dict()
    raw['bids']['SEC-X'] = '101'
    with pytest.raises(OpeningPriceUnavailable, match='crossed'):
        OpeningPrices.from_dict(raw)


@pytest.mark.parametrize('source', [LEGACY_QUOTE_SOURCE, SIP_QUOTE_SOURCE])
def test_historical_quote_roundtrip_preserves_source_and_typed_validation(source):
    state, plan = case()
    raw = quotes(state, plan).to_dict()
    raw['source'] = source
    evidence = OpeningPrices.from_dict(json.loads(json.dumps(raw)))
    assert isinstance(evidence, RegularQuotes)
    assert evidence.source == source
    assert evidence.to_dict() == raw
    raw['bids']['SEC-AAA'] = '101'
    with pytest.raises(OpeningPriceUnavailable, match='crossed'):
        OpeningPrices.from_dict(raw)


@pytest.mark.parametrize('source', [QUOTE_SOURCE, SIP_QUOTE_SOURCE])
def test_quote_sources_cannot_forge_bar_only_evidence(source):
    state, plan = case()
    raw = quotes(state, plan).to_dict()
    raw['source'] = source
    del raw['bids'], raw['quoted_at']
    with pytest.raises(OpeningPriceUnavailable, match='shape'):
        OpeningPrices.from_dict(raw)
    with pytest.raises(OpeningPriceUnavailable, match='authenticated sides'):
        OpeningPrices(session=plan.effective_session,
            opening_at=calendar.session_window(plan.effective_session)[0],
            observed_at=calendar.session_window(plan.effective_session)[0]+timedelta(minutes=3),
            prices={'SEC-AAA':D(100)}, symbols={'SEC-AAA':'AAA'},
            broker_ids={'SEC-AAA':'asset-SEC-AAA'}, source=source)


@pytest.mark.parametrize('source', ['ALPACA_DELAYED_SIP_RAW_REGULAR_QUOTES_V1', [], {}, None])
def test_unrecognized_quote_source_is_never_accepted_as_regular_quotes(source):
    state, plan = case()
    raw = quotes(state, plan).to_dict()
    raw['source'] = source
    with pytest.raises(OpeningPriceUnavailable):
        OpeningPrices.from_dict(raw)
    with pytest.raises(OpeningPriceUnavailable):
        RegularQuotes.from_dict(raw)


@pytest.mark.asyncio
async def test_iex_authority_denial_refuses_without_another_feed_or_request():
    import httpx
    from sentinel.execution.alpaca import AlpacaCredentialsRefused, AlpacaExecutionBroker
    state, plan = case()
    _payload, now = quote_payload(plan.effective_session)
    calls = []
    def response(request):
        calls.append(request)
        return httpx.Response(403, json={'message':'market data authority denied'})
    client = httpx.AsyncClient
    provider = SimpleNamespace(AsyncClient=lambda **kw:client(
        transport=httpx.MockTransport(response), **kw))
    broker = AlpacaExecutionBroker(api_key='synthetic-paper-key', secret_key='synthetic-paper-secret',
        base_url='https://paper-api.alpaca.markets', http_provider=lambda:provider,
        clock_provider=lambda:now)
    with pytest.raises(AlpacaCredentialsRefused, match='HTTP 403'):
        await broker.opening_prices(session=plan.effective_session,
            instruments={'SEC-AAA':BrokerInstrument('SEC-AAA', 'AAA', 'asset-SEC-AAA')})
    assert len(calls) == 1
    assert calls[0].url.host == 'data.alpaca.markets'
    assert calls[0].url.path == '/v2/stocks/quotes/latest'
    assert dict(calls[0].url.params) == {'symbols':'AAA', 'feed':'iex'}
    assert calls[0].headers['APCA-API-KEY-ID'] == 'synthetic-paper-key'


@pytest.mark.parametrize('age', [-1, 61, 300])
def test_future_stale_or_preopen_quotes_cannot_size(age):
    state, plan = case()
    with pytest.raises(OpeningPriceNotReady):
        quotes(state, plan, age=age)


def test_regular_quote_freshness_boundary_remains_sixty_seconds():
    state, plan = case()
    evidence = quotes(state, plan, age=60)
    assert evidence.source == QUOTE_SOURCE
    assert evidence.observed_at-evidence.quoted_at['SEC-AAA'] == timedelta(seconds=60)


@pytest.mark.parametrize('damage', ['zero_ask_size', 'zero_bid_size', 'crossed', 'zero_ask'])
def test_regular_quote_requires_positive_raw_sides_and_sizes(damage):
    state, plan = case()
    payload, now = quote_payload(plan.effective_session)
    field, value = {'zero_ask_size':('as',0), 'zero_bid_size':('bs',0),
                    'crossed':('bp',101), 'zero_ask':('ap',0)}[damage]
    payload['quotes']['AAA'][field] = value
    with pytest.raises(OpeningPriceNotReady):
        parse_quotes(payload, session=plan.effective_session, observed_at=now,
            instruments={'SEC-AAA':BrokerInstrument('SEC-AAA','AAA','asset-SEC-AAA')},
            broker_symbols={'SEC-AAA':'AAA'})


def test_missing_entry_defers_only_that_security_and_preserves_priority_cash():
    state, plan = case(cash=6000, entries=2)
    evidence = quotes(state, plan, available={'SEC-BBB'})
    result = opening_sizing.resolve(state, plan, base(state, plan), evidence)
    assert result.target_basket['SEC-AAA'] == 0
    first, second = result.opening_sizing['entries']
    assert first['status'] == 'PRICE_PENDING' and D(first['reserved_cash']) == 5000
    assert D(second['core_cost']) <= 1000 and D(second['account_shares']) > 0
    assert state.pending[0]['intended_dollars'] == 5000  # Immutable strategy intent.


def test_missing_sale_never_funds_entry_and_bid_is_used_when_available():
    state, plan = case(cash=0, sale=True)
    missing = opening_sizing.resolve(state, plan, base(state, plan),
                                    quotes(state, plan, available={'SEC-AAA'}))
    assert missing.target_basket['SEC-AAA'] == 0
    assert missing.opening_sizing['sales'][0]['proceeds'] == '0'
    complete = opening_sizing.resolve(state, plan, base(state, plan), quotes(state, plan))
    assert D(complete.opening_sizing['sales'][0]['proceeds']) == D('989.01')


def test_late_formation_timing_is_never_prospective_authority(monkeypatch):
    day = '2026-10-05'
    opened, _ = calendar.session_window(calendar.next_session(day))
    monkeypatch.setattr(initial, '_now', lambda conn:opened+timedelta(minutes=20))
    value = initial._preparation_timing(None, day, production_strategy()[1])
    assert value['status'] == 'STATE_ONLY_AFTER_OPEN'
    assert shadow._timing_proof(value, decision_session=day, committed=False,
        where='state', allow_state_only=True) == value
    with pytest.raises(shadow.ShadowObservationRefused):
        shadow._timing_proof(value, decision_session=day, committed=False, where='authority')
    value['candidate_committed_at'] = value['observed_at']
    with pytest.raises(shadow.ShadowObservationRefused):
        shadow._timing_proof(value, decision_session=day, committed=True,
                            where='authority', allow_state_only=True)


def test_staging_still_requires_archive_and_both_durable_markers(monkeypatch):
    monkeypatch.setattr(backup, 'enabled', lambda:True)
    calls = []
    monkeypatch.setattr(backup.backup_guard, 'require_bulk_writes_permitted',
        lambda *a,**kw:SimpleNamespace(unresolved_failure=False))
    monkeypatch.setattr(backup, '_require_marker', lambda conn, root:calls.append(root))
    monkeypatch.setattr(backup, '_require', lambda *a,**kw:(_ for _ in ()).throw(
        backup.BackupHorizonExceeded('full admission remains refused')))
    assert backup.require_staging(None, operation='raw capture')['scope'] == 'NON_AUTHORITATIVE_STAGING'
    assert calls == [backup.WAL_ROOT, backup.BASE_ROOT]
    with pytest.raises(backup.BackupHorizonExceeded):
        backup.require(None, operation='publish')
    monkeypatch.setattr(backup.backup_guard, 'require_bulk_writes_permitted',
        lambda *a,**kw:SimpleNamespace(unresolved_failure=True))
    with pytest.raises(backup.BackupRuntimeUnavailable, match='archive failure'):
        backup.require_staging(None, operation='raw capture')


def test_missing_staging_media_does_not_become_unprotected_work(monkeypatch):
    monkeypatch.setattr(backup, 'enabled', lambda:True)
    monkeypatch.setattr(backup.backup_guard, 'require_bulk_writes_permitted',
        lambda *a,**kw:SimpleNamespace(unresolved_failure=False))
    monkeypatch.setattr(backup, '_require_marker', lambda *a:(_ for _ in ()).throw(
        backup.BackupRuntimeUnavailable('missing target')))
    with pytest.raises(backup.BackupRuntimeUnavailable):
        backup.require_staging(None, operation='raw capture')
