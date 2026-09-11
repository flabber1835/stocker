"""A ticker rename cannot redirect or strand an opening entry/funding exit."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import httpx
import pytest

from sentinel.execution import opening_sizing, target_reprojection as projections
from sentinel.execution.alpaca import AlpacaExecutionBroker, MalformedBrokerPayload
from sentinel.execution.contract import BrokerInstrument, BrokerPosition
from sentinel.execution.opening_prices import (
    OpeningPrices, OpeningPriceUnavailable, OpeningPriceUnavailability, parse_bars)
from sentinel.feed import calendar, universe
from sentinel.paper import targets
from tests.sentinel.test_production_decision import _observation
from tests.v5.test_opening import base, case, prices


def test_reverse_identity_refuses_two_symbols_and_recycled_ticker():
    resolver = universe.IdentityResolver([
        universe.Listing('SID', 'ONE'), universe.Listing('SID', 'TWO')])
    assert resolver.ticker_for_security('SID', '2026-08-12') is None
    resolver = universe.IdentityResolver([
        universe.Listing('SID', 'ONE'), universe.Listing('OTHER', 'ONE')])
    assert resolver.ticker_for_security('SID', '2026-08-12') is None


def rename_broker(monkeypatch, env, plan, *, alias=False, wrong_security=False):
    monkeypatch.setattr(opening_sizing, 'load_projection', lambda *a, **k: None)
    required = opening_sizing.required_prices(env, plan)
    old_symbols = {'SEC-AAA': 'AAA', 'SEC-X': 'X'}
    current = {sid: 'NEW' if sid == 'SEC-AAA' else 'NEWX' for sid in required}
    listings = [universe.Listing(sid, old_symbols[sid], '2000-01-01',
                                plan.decision_session.isoformat()) for sid in required]
    listings += [universe.Listing(sid, symbol, plan.effective_session.isoformat())
                 for sid, symbol in current.items()]
    resolver = universe.IdentityResolver(listings)
    monkeypatch.setattr(universe, 'load_resolver', lambda *a, **k: resolver)
    opened, _ = calendar.session_window(plan.effective_session)
    requested = []
    broker = AlpacaExecutionBroker(api_key='test', secret_key='test',
        base_url='https://paper-api.alpaca.markets',
        resolve_security_id=lambda symbol: ('WRONG' if wrong_security else
            resolver.resolve(symbol, plan.effective_session.isoformat())))

    async def get(path, params=None):
        symbol = path.rsplit('/', 1)[-1]
        requested.append(symbol)
        sid = next((sid for sid in required if current[sid] == symbol or
                    alias and old_symbols[sid] == symbol), None)
        if sid is None:
            httpx.Response(404, request=httpx.Request('GET', broker.base_url + path)).raise_for_status()
        return {'symbol': current[sid], 'id': 'asset-' + sid,
                'status': 'active', 'tradable': True}

    async def opening_prices(*, session, instruments):
        payload = {'bars': {item.symbol: [{'t': opened.isoformat(), 'o': '100', 'v': 10}]
                             for item in instruments.values()}, 'next_page_token': None}
        return parse_bars(payload, session=session, instruments=instruments,
                          observed_at=opened + timedelta(minutes=1))

    monkeypatch.setattr(broker, '_get', get)
    monkeypatch.setattr(broker, 'opening_prices', opening_prices)
    return broker, requested, current


@pytest.mark.parametrize('sale', [False, True])
@pytest.mark.parametrize('alias', [False, True])
def test_renamed_entry_and_pending_exit_complete_sizing(monkeypatch, sale, alias):
    env, plan = case(cash=100. if sale else 100000., sale=sale)
    before = env.to_dict()
    broker, requested, current = rename_broker(monkeypatch, env, plan, alias=alias)
    evidence = asyncio.run(opening_sizing.prices_for_plan(None, state=env, plan=plan, broker=broker))
    projection = opening_sizing.resolve(env, plan, base(env, plan), evidence)
    assert requested == [current[sid] for sid in sorted(current)]
    assert projection.target_basket['SEC-AAA'] == (10 if sale else 49)
    if sale:
        assert projection.target_basket['SEC-X'] == 0
        assert D(projection.opening_sizing['sales'][0]['proceeds']) == 999
    assert env.to_dict() == before
    assert OpeningPrices.from_dict(evidence.to_dict()) == evidence
    monkeypatch.setattr(opening_sizing, 'load_projection', lambda *a, **k: projection)
    retained = asyncio.run(opening_sizing.prices_for_plan(None, state=env, plan=plan, broker=object()))
    assert opening_sizing.resolve(env, plan, base(env, plan), retained) == projection


def test_adapter_rejects_recycled_symbol_for_other_security(monkeypatch):
    env, plan = case()
    broker, _, _ = rename_broker(monkeypatch, env, plan, alias=True, wrong_security=True)
    with pytest.raises(MalformedBrokerPayload, match='permanent security'):
        asyncio.run(opening_sizing.prices_for_plan(None, state=env, plan=plan, broker=broker))


@pytest.mark.parametrize('sale', [False, True])
def test_submission_uses_retained_renamed_instrument(monkeypatch, sale):
    env, plan = case(cash=100. if sale else 100000., sale=sale)
    broker, requested, current = rename_broker(monkeypatch, env, plan, alias=True)
    evidence = asyncio.run(opening_sizing.prices_for_plan(None, state=env, plan=plan, broker=broker))
    projection = opening_sizing.resolve(env, plan, base(env, plan), evidence)
    monkeypatch.setattr(projections, 'load_projection', lambda *a, **k: projection)
    monkeypatch.setattr(targets, 'load_meta', lambda *a, **k: {})
    observed = _observation(positions=(BrokerPosition(
        BrokerInstrument('SEC-X', 'NEWX', 'asset-SEC-X'), D(10)),) if sale else ())
    requested.clear()
    instruments = asyncio.run(targets._instrument_map(None, broker, env, plan, observed,
                                                      target_basket=projection.target_basket))
    assert instruments['SEC-AAA'] == BrokerInstrument('SEC-AAA', 'NEW', 'asset-SEC-AAA')
    assert requested == ['NEW']
    if sale:
        assert instruments['SEC-X'] == BrokerInstrument('SEC-X', 'NEWX', 'asset-SEC-X')


@pytest.mark.parametrize('fault', ['gap', 'ambiguous', 'reused'])
def test_effective_listing_must_be_unique_and_reversible(monkeypatch, fault):
    env, plan = case()
    broker, requested, _ = rename_broker(monkeypatch, env, plan)
    listings = [universe.Listing('SEC-AAA', 'OLD', '2000-01-01', plan.decision_session.isoformat())]
    if fault != 'gap':
        listings += [universe.Listing('SEC-AAA', 'NEW', plan.effective_session.isoformat())]
        listings += [universe.Listing('SEC-AAA' if fault == 'ambiguous' else 'OTHER',
                                     'OTHER' if fault == 'ambiguous' else 'NEW',
                                     plan.effective_session.isoformat())]
    resolver = universe.IdentityResolver(listings)
    monkeypatch.setattr(universe, 'load_resolver', lambda *a, **k: resolver)
    evidence = asyncio.run(opening_sizing.prices_for_plan(
        None, state=env, plan=plan, broker=broker))
    assert isinstance(evidence, OpeningPriceUnavailability)
    assert 'unique effective-session' in evidence.reason
    projection = opening_sizing.resolve(env, plan, base(env, plan), evidence)
    assert projection.target_basket['SEC-AAA'] == 0
    assert projection.opening_sizing['mode'] == opening_sizing.UNAVAILABLE_MODE
    assert requested == []


@pytest.mark.parametrize('fault', ['wrong_security', 'missing_asset', 'wrong_symbol'])
def test_opening_resolution_independently_checks_instrument_identity(monkeypatch, fault):
    env, plan = case()
    broker, _, _ = rename_broker(monkeypatch, env, plan)
    async def resolve(**kwargs):
        return BrokerInstrument('OTHER' if fault == 'wrong_security' else 'SEC-AAA',
                                'OTHER' if fault == 'wrong_symbol' else 'NEW',
                                None if fault == 'missing_asset' else 'asset-SEC-AAA')
    monkeypatch.setattr(broker, 'resolve_instrument', resolve)
    with pytest.raises(projections.TargetProjectionRefused, match='permanent security identity'):
        asyncio.run(opening_sizing.prices_for_plan(None, state=env, plan=plan, broker=broker))


@pytest.mark.parametrize('fault', ['symbol', 'asset', 'security'])
def test_opening_price_response_must_match_resolved_instruments(monkeypatch, fault):
    env, plan = case()
    broker, _, _ = rename_broker(monkeypatch, env, plan)
    original = broker.opening_prices
    async def swapped(**kwargs):
        evidence = await original(**kwargs)
        if fault == 'symbol':
            return replace(evidence, symbols={'SEC-AAA': 'OTHER'})
        if fault == 'asset':
            return replace(evidence, broker_ids={'SEC-AAA': 'other-asset'})
        return replace(evidence, prices={'OTHER': D(100)}, symbols={'OTHER': 'NEW'},
                       broker_ids={'OTHER': 'asset-SEC-AAA'})
    monkeypatch.setattr(broker, 'opening_prices', swapped)
    with pytest.raises(projections.TargetProjectionRefused, match='resolved instrument identities'):
        asyncio.run(opening_sizing.prices_for_plan(None, state=env, plan=plan, broker=broker))


@pytest.mark.parametrize('fault', ['missing', 'blank', 'duplicate'])
def test_opening_asset_ids_are_complete_unique_and_durable(fault):
    env, plan = case(sale=True)
    evidence = prices(env, plan)
    ids = dict(evidence.broker_ids)
    if fault == 'missing':
        del ids['SEC-X']
    elif fault == 'blank':
        ids['SEC-X'] = ' '
    else:
        ids['SEC-X'] = ids['SEC-AAA']
    with pytest.raises(OpeningPriceUnavailable, match='stable broker asset'):
        replace(evidence, broker_ids=ids)


@pytest.mark.parametrize('sale', [False, True])
def test_submission_refuses_asset_id_change_since_opening(monkeypatch, sale):
    env, plan = case(cash=100. if sale else 100000., sale=sale)
    broker, _, _ = rename_broker(monkeypatch, env, plan)
    evidence = asyncio.run(opening_sizing.prices_for_plan(None, state=env, plan=plan, broker=broker))
    projection = opening_sizing.resolve(env, plan, base(env, plan), evidence)
    monkeypatch.setattr(projections, 'load_projection', lambda *a, **k: projection)
    monkeypatch.setattr(targets, 'load_meta', lambda *a, **k: {})
    observed = _observation(positions=(BrokerPosition(
        BrokerInstrument('SEC-X', 'NEWX', 'different-asset'), D(10)),) if sale else ())
    if not sale:
        async def changed(**kwargs):
            return BrokerInstrument('SEC-AAA', 'NEW', 'different-asset')
        monkeypatch.setattr(broker, 'resolve_instrument', changed)
    with pytest.raises(targets.PaperActivationRefused, match='opening broker asset identity'):
        asyncio.run(targets._instrument_map(None, broker, env, plan, observed,
                                            target_basket=projection.target_basket))
