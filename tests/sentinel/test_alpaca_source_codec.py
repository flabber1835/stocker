"""Production factory and adapter round trips; only native HTTP is a fixture."""
import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import config
from sentinel.execution import feed_inputs
from sentinel.execution.alpaca import MalformedBrokerPayload
from tests.sentinel.test_issue_183_alpaca_hardening import Httpx, Response


@pytest.mark.parametrize('provider', ['ALPACA_OPENFIGI', 'ALPACA_NASDAQ', 'SHARADAR'])
def test_source_resolver_factory_and_native_instrument_roundtrip(monkeypatch, provider):
    native = provider != 'SHARADAR'
    symbol = 'PBR.A' if native else 'BRK-B'
    wire = 'PBR.A' if native else 'BRK.B'
    calls = []
    def lookup(value, day):
        calls.append((value, day))
        return 'permanent-listing' if value == symbol and day in {'2026-10-15', '2026-10-16'} else None
    authority = SimpleNamespace(resolve=lookup)
    refs = SimpleNamespace(manifest=SimpleNamespace(provider=provider), resolver=authority)
    monkeypatch.setattr(feed_inputs, '_snapshot_identity_authorities',
        lambda *a, **k: (refs, '2026-10-16', '2026-10-15', authority))
    resolver = feed_inputs.resolver(None, None, session='2026-10-16')
    cfg = config.SentinelConfig('fixture', 'fixture', config.DEFAULT_BASE_URL, Path('/fixture'), 1, 0)
    broker = config.build_execution_broker(cfg, resolve_security_id=resolver)
    http = Httpx(routes={'/v2/assets/' + wire: Response({
        'id': 'native-asset', 'symbol': wire, 'status': 'active',
        'tradable': True, 'class': 'us_equity', 'exchange': 'NYSE'})})
    broker._http_provider = lambda: http
    broker._clock_provider = lambda: datetime(2026, 10, 16, 14, tzinfo=timezone.utc)
    instrument = asyncio.run(broker.resolve_instrument(security_id='permanent-listing', symbol=symbol))
    assert (instrument.security_id, instrument.symbol, instrument.broker_id) == ('permanent-listing', symbol, 'native-asset')
    assert calls and all(value == symbol for value, day in calls)
    assert resolver(symbol, '2026-10-17') is None
    assert resolver('BIL') == 'SENTINEL:BIL'
    # The same codec is used by positions, orders, fills and exact-key recovery.
    assert broker._instrument(wire, 'native-asset', as_of=date(2026, 10, 16)) == instrument
    with pytest.raises(MalformedBrokerPayload, match='requested'):
        asyncio.run(broker.resolve_instrument(security_id='different-listing', symbol=symbol))
    http.routes['/v2/assets/' + wire] = Response({
        'id': 'native-asset', 'symbol': 'FOREIGN', 'status': 'active', 'tradable': True})
    with pytest.raises(MalformedBrokerPayload):
        asyncio.run(broker.resolve_instrument(security_id='permanent-listing', symbol=symbol))
    assert all(method == 'GET' for method, *_ in http.calls)


def test_unknown_source_domain_cannot_receive_a_broker():
    cfg = config.SentinelConfig('fixture', 'fixture', config.DEFAULT_BASE_URL, Path('/fixture'), 1, 0)
    resolver = feed_inputs.BrokerSecurityResolver('UNAUTHENTICATED', lambda *_: 'id')
    with pytest.raises(ValueError, match='unsupported source'):
        config.build_execution_broker(cfg, resolve_security_id=resolver)


def test_native_roundtrip_falsifier_reproduces_incident_if_conversion_returns(monkeypatch):
    factory = config.build_execution_broker
    def broken(*a, **k):
        broker = factory(*a, **k)
        broker._from_symbol = lambda value: value.replace('.', '-')
        return broker
    monkeypatch.setattr(config, 'build_execution_broker', broken)
    with pytest.raises(MalformedBrokerPayload, match='no permanent security identity'):
        test_source_resolver_factory_and_native_instrument_roundtrip(monkeypatch, 'ALPACA_OPENFIGI')
