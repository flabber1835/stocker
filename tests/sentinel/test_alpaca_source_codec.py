"""Production factory and adapter round trips; only native HTTP is a fixture."""
import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import config
from sentinel.execution import feed_inputs
from sentinel.execution.alpaca import MalformedBrokerPayload
from sentinel.feed import alpaca_identity
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_issue_183_alpaca_hardening import Httpx, Response


class EvidenceConnection:
    def __init__(self, payloads):
        self.rows = {digest(value): value for value in payloads}
        self.reads = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params):
        assert sql == (
            "SELECT payload,canonical_payload FROM sentinel_snapshot_evidence "
            "WHERE evidence_sha256=%s")
        self.reads.append(params[0])
        self.row = (self.rows[params[0]], None) if params[0] in self.rows else None

    def fetchone(self):
        return self.row


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
    binding = alpaca_identity.IdentityBinding(
        security_id='permanent-listing', provider_asset_id='native-asset',
        prior_provider_asset_id='permanent-listing', ticker=symbol,
        origin_snapshot_id='a' * 64,
        event=alpaca_identity.NameChange(
            id='same-symbol-recreation', old_symbol=symbol, new_symbol=symbol,
            old_cusip='000000001', new_cusip='000000002', process_date=date(2026, 10, 15)),
    ).model_dump(mode='json')
    reference = {
        'schema': 'sentinel.rolling-alpaca-openfigi-references/3',
        'tickers': [{'table': 'SEP', 'ticker': symbol, 'permaticker': 'permanent-listing'}],
        'identity_bindings': [binding],
    }
    source = {
        'schema': 'sentinel.alpaca-openfigi-operational-source/3',
        'provider': 'ALPACA_OPENFIGI', 'identity_bindings_sha256': digest([binding]),
    }
    conn = EvidenceConnection([reference, source])
    refs = SimpleNamespace(manifest=SimpleNamespace(
        provider=provider, reference_sha256=digest(reference),
        source_evidence_sha256=digest(source)), resolver=authority)
    monkeypatch.setattr(feed_inputs, '_snapshot_identity_authorities',
        lambda *a, **k: (refs, '2026-10-16', '2026-10-15', authority))
    resolver = feed_inputs.resolver(conn, None, session='2026-10-16')
    assert conn.reads == ([digest(reference), digest(source)] if provider == 'ALPACA_OPENFIGI' else [])
    assert resolver.provider_asset_ids == ({'permanent-listing': 'native-asset'}
                                          if provider == 'ALPACA_OPENFIGI' else {})
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
