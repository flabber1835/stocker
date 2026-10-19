"""Exact protected order terms cross native transport and recovery unchanged."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from decimal import Decimal as D
import hashlib
import inspect
import json
import textwrap

import pytest

from sentinel.execution import alpaca
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.contract import BrokerOrder, OrderTerms, Side
from sentinel.execution.states import CommandState as S
from tests.sentinel.test_issue_183_alpaca_hardening import Httpx, INSTRUMENT, PAPER, Response, full_order, run


LIMIT = OrderTerms(order_type='limit', limit_price=D('102.25'))
ROUTES = [alpaca.OriginalAlpaca, alpaca.FinancialGradeAlpacaExecutionBroker,
          AssetIdAlpacaExecutionBroker]


def broker_for(cls, *, payload=None, post=None, routes=None):
    http = Httpx(post=Response(payload or full_order(), 200) if post is None else post,
                 routes=routes)
    broker = cls(api_key='fixture', secret_key='fixture', base_url=PAPER,
                 resolve_security_id=lambda symbol, _as_of=None: 'SEC-' + symbol,
                 http_provider=lambda: http)
    return broker, http


def limited(**changes):
    return full_order(type='limit', order_type='limit', limit_price='102.25', **changes)


def send(broker, terms=LIMIT, *, side=Side.BUY, quantity=D(2)):
    return run(broker.submit(client_key='key-1', instrument=INSTRUMENT,
                            side=side, quantity=quantity, order_terms=terms))


def test_order_terms_are_frozen_canonical_versioned_and_legacy_defaulted():
    assert OrderTerms().to_dict() == {'schema': 'sentinel.order-terms/1',
        'order_type': 'market', 'time_in_force': 'day', 'limit_price': None,
        'order_class': 'simple', 'extended_hours': False}
    assert OrderTerms.from_dict(LIMIT.to_dict()) == LIMIT
    assert replace(LIMIT, limit_price=D('102.250')).to_dict() == LIMIT.to_dict()
    with pytest.raises(FrozenInstanceError):
        LIMIT.limit_price = D(1)
    # Every historical positional field remains in its original position.
    order = BrokerOrder('id', 'key', INSTRUMENT, Side.BUY, S.ACKNOWLEDGED,
                        D(2), D(0), None, None, False, None, None, {'audit': 1})
    assert order.raw == {'audit': 1} and order.order_terms == OrderTerms()


@pytest.mark.parametrize('change', [
    {'schema': 'sentinel.order-terms/2'}, {'extra': 1},
    {'order_type': ''}, {'order_type': 2}, {'time_in_force': None},
    {'order_class': False}, {'extended_hours': 'false'},
    {'limit_price': 10.25}, {'limit_price': 'NaN'}, {'limit_price': '0'},
    {'limit_price': '-1'}, {'limit_price': '102.250'},
])
def test_order_terms_decoder_refuses_noncanonical_or_untyped_fields(change):
    with pytest.raises((ValueError, TypeError)):
        OrderTerms.from_dict({**LIMIT.to_dict(), **change})


def test_order_terms_decoder_never_defaults_missing_wire_economics():
    for key in LIMIT.to_dict():
        raw = LIMIT.to_dict()
        del raw[key]
        with pytest.raises(ValueError):
            OrderTerms.from_dict(raw)


@pytest.mark.parametrize('terms', [
    OrderTerms('stop', 'day'), OrderTerms('limit', 'ioc', D(10)),
    OrderTerms('limit', 'opg', D(10)), OrderTerms('limit', 'gtc', D(10)),
    OrderTerms('market', 'opg'), OrderTerms('market', 'day', D(10)),
    OrderTerms('limit', 'day'), OrderTerms('limit', 'day', D(10), 'bracket'),
    OrderTerms('limit', 'day', D(10), extended_hours=True),
    OrderTerms('limit', 'day', D('10.001')),
    OrderTerms('limit', 'day', D('0.12345')),
])
def test_unsupported_terms_remain_typed_but_cannot_authorize_owned_transport(terms):
    assert OrderTerms.from_dict(terms.to_dict()) == terms
    with pytest.raises(ValueError):
        terms.require_owned_submission(Side.BUY)


@pytest.mark.parametrize('cls', ROUTES)
def test_limit_day_buy_has_exact_wire_terms_and_one_post(cls):
    broker, http = broker_for(cls, payload=limited())
    assert send(broker).state is S.ACKNOWLEDGED
    assert http.calls == [('POST', PAPER + '/v2/orders', {
        'symbol': 'AAPL' if cls is alpaca.OriginalAlpaca else 'asset-aapl',
        'qty': '2', 'side': 'buy', 'type': 'limit', 'time_in_force': 'day',
        'client_order_id': 'key-1', 'order_class': 'simple',
        'extended_hours': False, 'limit_price': '102.25'})]


@pytest.mark.parametrize('cls', ROUTES)
def test_legacy_market_call_omits_new_keyword_and_keeps_old_wire_body(cls):
    broker, http = broker_for(cls)
    assert run(broker.submit(client_key='key-1', instrument=INSTRUMENT,
                            side=Side.BUY, quantity=D(2))).state is S.ACKNOWLEDGED
    assert http.calls[0][2]['type'] == 'market'
    assert 'limit_price' not in http.calls[0][2]


@pytest.mark.parametrize('cls', ROUTES)
@pytest.mark.parametrize('change', [
    {'type': 'market', 'order_type': 'market', 'limit_price': None},
    {'limit_price': '102.26'}, {'limit_price': None}, {'limit_price': 102.25},
    {'time_in_force': 'gtc'}, {'time_in_force': 'ioc'},
    {'order_class': 'bracket'}, {'order_class': ' '}, {'extended_hours': True},
    {'extended_hours': 'false'}, {'order_type': 'market'},
])
def test_contradictory_2xx_terms_are_unknown_and_never_retried(cls, change):
    broker, http = broker_for(cls, payload={**limited(), **change})
    outcome = send(broker)
    assert outcome.state is S.UNKNOWN and outcome.broker_order_id == 'order-1'
    assert len(http.calls) == 1


@pytest.mark.parametrize('cls', ROUTES)
@pytest.mark.parametrize('field', ['type', 'time_in_force', 'order_class', 'extended_hours', 'limit_price'])
def test_incomplete_limit_acknowledgement_does_not_guess_defaults(cls, field):
    payload = limited()
    del payload[field]
    broker, http = broker_for(cls, payload=payload)
    assert send(broker).state is S.UNKNOWN
    assert len(http.calls) == 1


@pytest.mark.parametrize('cls', ROUTES)
def test_only_native_empty_class_is_normalized_to_simple(cls):
    broker, _ = broker_for(cls, payload=limited(order_class=''))
    assert send(broker).state is S.ACKNOWLEDGED


@pytest.mark.parametrize('cls', ROUTES)
@pytest.mark.parametrize('status,filled', [('filled', '2'), ('partially_filled', '1')])
@pytest.mark.parametrize('price', ['102.24', '102.25', '102.26'])
def test_limit_fill_echo_must_respect_the_submitted_cap(cls, status, filled, price):
    broker, http = broker_for(cls, payload=limited(
        status=status, filled=filled, filled_avg_price=price))
    result = send(broker)
    assert result.state is (S.UNKNOWN if D(price) > LIMIT.limit_price else S.ACKNOWLEDGED)
    assert result.broker_order_id == 'order-1' and len(http.calls) == 1


@pytest.mark.parametrize('cls', ROUTES)
def test_unsupported_capability_and_sell_limit_refuse_before_post(cls):
    broker, http = broker_for(cls, payload=limited())
    with pytest.raises(ValueError):
        send(broker, side=Side.SELL)
    broker.capabilities = replace(broker.capabilities, protected_limit_day=False)
    with pytest.raises(Exception, match='protected_limit_day'):
        send(broker)
    assert http.calls == []


def test_fractional_limit_or_untyped_terms_refuse_without_transport():
    broker, http = broker_for(alpaca.FinancialGradeAlpacaExecutionBroker,
                             payload=limited(quantity='1.5'))
    with pytest.raises(ValueError, match='whole'):
        send(broker, quantity=D('1.5'))
    with pytest.raises(TypeError, match='OrderTerms'):
        send(broker, terms=LIMIT.to_dict())
    assert http.calls == []


def test_transport_typeerror_is_unknown_without_market_fallback():
    broker, http = broker_for(alpaca.FinancialGradeAlpacaExecutionBroker,
                             post=TypeError('transport rejected keyword'))
    assert send(broker).state is S.UNKNOWN
    assert len(http.calls) == 1 and http.calls[0][2]['type'] == 'limit'


def test_exact_native_recovery_retains_limit_and_does_not_assume_market():
    payload = limited(client_order_id='sntl-owned')
    broker, _ = broker_for(alpaca.FinancialGradeAlpacaExecutionBroker,
        routes={'/v2/account': {'account_number': 'PA-1'},
                '/v2/orders:by_client_order_id': payload})
    found = run(broker.find_by_client_key('sntl-owned')).order
    assert found.order_terms == LIMIT
    assert broker._to_order({**payload, 'order_class': ''}).order_terms == LIMIT
    for field in ('type', 'time_in_force', 'order_class', 'extended_hours', 'limit_price'):
        missing = dict(payload)
        del missing[field]
        with pytest.raises(alpaca.IncompleteBrokerPayload):
            broker._to_order(missing)


def test_unsupported_foreign_and_unreported_terms_remain_visible():
    broker, _ = broker_for(alpaca.FinancialGradeAlpacaExecutionBroker)
    foreign = limited(client_order_id='manual', time_in_force='opg', order_class='bracket')
    assert broker._to_order(foreign).order_terms == OrderTerms('limit', 'opg', D('102.25'), 'bracket')
    missing = dict(foreign)
    del missing['type']
    assert broker._to_order(missing).order_terms is None


def test_order_snapshot_stability_includes_each_wire_term():
    broker, _ = broker_for(alpaca.FinancialGradeAlpacaExecutionBroker)
    order = broker._to_order(limited())
    for terms in (replace(LIMIT, limit_price=D(103)), replace(LIMIT, time_in_force='gtc'),
                  replace(LIMIT, order_class='bracket'), replace(LIMIT, extended_hours=True), None):
        assert alpaca._fingerprint((order,)) != alpaca._fingerprint((replace(order, order_terms=terms),))


def _completion_fixture(monkeypatch, kind, *, durable=OrderTerms(), observed=OrderTerms()):
    now = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
    order = {'client_key': 'sntl-owned', 'security_id': 'SEC-AAPL', 'symbol': 'AAPL',
             'broker_id': 'asset-aapl', 'side': 'BUY', 'quantity': '2',
             'broker_order_id': 'order-1', 'state': 'FILLED', 'filled_quantity': '2'}
    if kind == 'broker-observation/v5':
        order['order_terms'] = None if observed is None else observed.to_dict()
    provenance = {'kind': kind, 'broker': 'alpaca', 'account_id': 'PA-1',
                  'terminal_recovery_through': now.isoformat(), 'completeness': 'COMPLETE', 'orders': [order]}
    row = ('SEC-AAPL', 'AAPL', 'asset-aapl', 'BUY', D(2), 'FILLED', 'order-1', D(2), D(100), durable.to_dict())

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, *args): pass
        def fetchall(self): return [(7, now)]
        def fetchone(self): return row

    conn = type('Connection', (), {'cursor': lambda self: Cursor()})()
    monkeypatch.setattr(alpaca.journal, '_terminal_recovery_binding', lambda conn: ('alpaca', 'PA-1', now))
    monkeypatch.setattr(alpaca, 'load_provenance', lambda conn, seq: provenance)
    return conn, now, provenance, order


def test_historical_completion_digest_is_unchanged_and_only_defaults_match(monkeypatch):
    conn, now, provenance, order = _completion_fixture(monkeypatch, 'broker-observation/v4')
    immutable = {k: order[k] for k in ('client_key', 'security_id', 'symbol', 'broker_id', 'side', 'quantity', 'broker_order_id')}
    prior = {'kind': 'terminal-recovery-completion/v3', 'observation_seq': 7,
             'observed_at': now.isoformat(), 'processed_through': now.isoformat(),
             'provenance': provenance, 'immutable_commands': [immutable]}
    digest = hashlib.sha256(json.dumps(prior, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()
    assert alpaca.completion_proof(conn, now) == (7, digest)
    conn, now, _, _ = _completion_fixture(monkeypatch, 'broker-observation/v4', durable=LIMIT)
    assert alpaca.completion_proof(conn, now) is None


@pytest.mark.parametrize('observed', [LIMIT, OrderTerms(), None])
def test_new_completion_requires_exact_typed_terms(monkeypatch, observed):
    conn, now, _, _ = _completion_fixture(monkeypatch, 'broker-observation/v5', durable=LIMIT, observed=observed)
    assert (alpaca.completion_proof(conn, now) is not None) == (observed == LIMIT)


def test_private_acknowledgement_term_guard_falsifier(monkeypatch):
    source = inspect.getsource(alpaca.OriginalAlpaca._validate_submit_response)
    assert source.count('if order.order_terms != order_terms:') == 1
    local = {}
    exec(compile(textwrap.dedent(source).replace('if order.order_terms != order_terms:', 'if False:'),
                 '<private-terms-echo-falsifier>', 'exec'), alpaca.__dict__, local)
    monkeypatch.setattr(alpaca.OriginalAlpaca, '_validate_submit_response', local['_validate_submit_response'])
    with pytest.raises(AssertionError):
        test_contradictory_2xx_terms_are_unknown_and_never_retried(
            alpaca.FinancialGradeAlpacaExecutionBroker, {'time_in_force': 'gtc'})


def test_private_native_required_terms_guard_falsifier(monkeypatch):
    source = inspect.getsource(alpaca.OriginalAlpaca._to_order)
    needle = "required=is_sentinel_key(payload.get('client_order_id'))"
    assert source.count(needle) == 1
    local = {}
    exec(compile(textwrap.dedent(source).replace(needle, 'required=False'),
                 '<private-native-terms-falsifier>', 'exec'), alpaca.__dict__, local)
    monkeypatch.setattr(alpaca.OriginalAlpaca, '_to_order', local['_to_order'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_exact_native_recovery_retains_limit_and_does_not_assume_market()


def test_private_limit_fill_price_guard_falsifier(monkeypatch):
    source = inspect.getsource(alpaca.OriginalAlpaca._validate_submit_response)
    needle = 'if (side is Side.BUY and order_terms.limit_price is not None'
    assert source.count(needle) == 1
    local = {}
    exec(compile(textwrap.dedent(source).replace(needle, 'if (False and order_terms.limit_price is not None'),
                 '<private-limit-fill-price-falsifier>', 'exec'), alpaca.__dict__, local)
    monkeypatch.setattr(alpaca.OriginalAlpaca, '_validate_submit_response', local['_validate_submit_response'])
    with pytest.raises(AssertionError):
        test_limit_fill_echo_must_respect_the_submitted_cap(
            alpaca.FinancialGradeAlpacaExecutionBroker, 'filled', '2', '102.26')


def test_private_limit_capability_guard_falsifier(monkeypatch):
    source = inspect.getsource(alpaca._submit_body)
    needle = "capabilities.require('protected_limit_day')"
    assert source.count(needle) == 1
    local = {}
    exec(compile(source.replace(needle, 'pass'), '<private-limit-capability-falsifier>', 'exec'),
         alpaca.__dict__, local)
    monkeypatch.setattr(alpaca, '_submit_body', local['_submit_body'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_unsupported_capability_and_sell_limit_refuse_before_post(
            alpaca.FinancialGradeAlpacaExecutionBroker)


def test_private_whole_quantity_guard_falsifier(monkeypatch):
    source = inspect.getsource(alpaca._submit_body)
    needle = 'if quantity != quantity.to_integral_value():'
    assert source.count(needle) == 1
    local = {}
    exec(compile(source.replace(needle, 'if False:'), '<private-limit-whole-quantity-falsifier>', 'exec'),
         alpaca.__dict__, local)
    monkeypatch.setattr(alpaca, '_submit_body', local['_submit_body'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_fractional_limit_or_untyped_terms_refuse_without_transport()
