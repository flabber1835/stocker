from dataclasses import replace

import pytest

from sentinel.trading_environment import (
    TradingEndpoint, TradingEndpointRefused, TradingEnvironment,
)


@pytest.mark.parametrize('url,mode,origin', [
    ('https://paper-api.alpaca.markets', TradingEnvironment.PAPER,
     'https://paper-api.alpaca.markets'),
    ('https://API.ALPACA.MARKETS:443/', TradingEnvironment.LIVE,
     'https://api.alpaca.markets'),
])
def test_exact_endpoint_selects_normalized_environment(url, mode, origin):
    endpoint = TradingEndpoint.parse(url)
    assert endpoint.environment is mode
    assert endpoint.base_url == origin
    assert endpoint.assets_url == origin + '/v2/assets'


@pytest.mark.parametrize('url', [
    '', ' https://api.alpaca.markets', 'https://api.alpaca.markets ',
    'http://api.alpaca.markets', 'https://api.alpaca.markets.evil.test',
    'https://api.alpaca.markets@evil.test', 'https://user@api.alpaca.markets',
    'https://user:secret@api.alpaca.markets', 'https://api.alpaca.markets:444',
    'https://api.alpaca.markets:invalid', 'https://api.alpaca.markets/v2',
    'https://api.alpaca.markets/../', 'https://api.alpaca.markets?',
    'https://api.alpaca.markets#', 'https://api.alpaca.markets?mode=paper',
    'https://api.alpaca.markets/#paper', 'https://api.alpaca.markets.',
    'https://api.alpaca.markets\\@evil.test', 'https://api.alpaca.markets\n',
    'https://api.alpaca.markets/\t', 'https://[api.alpaca.markets',
])
def test_unrecognized_or_ambiguous_origins_refuse(url):
    with pytest.raises(TradingEndpointRefused):
        TradingEndpoint.parse(url)


@pytest.mark.parametrize('suffix', [':444', '/v2', '?routing=other', '#paper', '.'])
def test_existing_paper_gate_uses_exact_origin_parser(suffix):
    from sentinel.config import is_paper_url, assert_paper_url, LiveEndpointRefused
    url = 'https://paper-api.alpaca.markets' + suffix
    assert is_paper_url(url) is False
    with pytest.raises(LiveEndpointRefused):
        assert_paper_url(url)


def test_prepared_live_mode_does_not_grant_order_authority():
    from sentinel.config import SentinelConfig, LiveEndpointRefused
    from sentinel.execution.alpaca import AlpacaExecutionBroker
    assert TradingEndpoint.parse('https://api.alpaca.markets').environment is TradingEnvironment.LIVE
    with pytest.raises(LiveEndpointRefused):
        SentinelConfig.from_env({'ALPACA_BASE_URL': 'https://api.alpaca.markets'})
    with pytest.raises(LiveEndpointRefused):
        AlpacaExecutionBroker(api_key='test', secret_key='test',
                              base_url='https://api.alpaca.markets')


def test_environment_cannot_be_relabelled_by_constructor_or_copy():
    paper = TradingEndpoint.parse('https://paper-api.alpaca.markets')
    with pytest.raises(TradingEndpointRefused):
        replace(paper, environment=TradingEnvironment.LIVE)
    with pytest.raises(TradingEndpointRefused):
        TradingEndpoint(environment=TradingEnvironment.LIVE,
                        base_url='https://paper-api.alpaca.markets')
    with pytest.raises(TradingEndpointRefused):
        TradingEndpoint(environment='ALPACA_LIVE', base_url='https://api.alpaca.markets')


def test_paper_and_live_recovery_subjects_are_disjoint_for_same_account():
    paper = TradingEndpoint.parse('https://paper-api.alpaca.markets')
    live = TradingEndpoint.parse('https://api.alpaca.markets')
    first = paper.subject(account_id='same-account', takeover_epoch=1)
    second = live.subject(account_id='same-account', takeover_epoch=1)
    assert first != second
    assert first['environment'] == 'ALPACA_PAPER'
    assert second['environment'] == 'ALPACA_LIVE'
    assert second['base_url'] == live.base_url


@pytest.mark.parametrize('account,epoch', [('', 1), (' account', 1),
    ('account', 0), ('account', True), ('account', 1.0)])
def test_recovery_subject_requires_explicit_account_epoch(account, epoch):
    endpoint = TradingEndpoint.parse('https://api.alpaca.markets')
    with pytest.raises(TradingEndpointRefused):
        endpoint.subject(account_id=account, takeover_epoch=epoch)
