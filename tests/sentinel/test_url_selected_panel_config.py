"""URL selection is visible and cannot recycle another environment's receipt."""
from pathlib import Path

import pytest
import yaml

from sentinel.panel import model, overview, read_projection, sources


@pytest.mark.parametrize('url,label', [
    ('https://paper-api.alpaca.markets', 'PAPER · simulation'),
    ('https://api.alpaca.markets', 'LIVE · real money'),
    ('https://api.alpaca.markets.evil.example', 'UNCONFIGURED'),
])
def test_selection_is_explicit_and_does_not_claim_trading_authority(url, label):
    row = sources.trading_environment_row(url)
    html = overview.overview_html(model.Panel(rows=[row]))
    assert 'Selected trading environment:' not in html
    assert row.value == label
    assert row.key == 'trading_environment'
    assert row.paper_plan is None and row.paper_account is None


def test_url_changes_only_invalidate_account_scope(monkeypatch):
    class Connection:
        def execute(self, *_args):
            return self

        def fetchone(self):
            return ('incarnation', 1, 'xmin')

    facts = (('cluster', 'db'), {'installation_id': 'install'}, 'epoch', {})
    monkeypatch.setattr(read_projection, '_shadow_inventory',
                        lambda _conn: [('unchanged canonical content',), [], []])
    conn = Connection()
    def keys():
        return tuple(read_projection._subject(conn, 'dsn', scope, facts=facts)
                     for scope in ('PAPER', 'SHADOW'))
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
    paper = keys()
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://api.alpaca.markets')
    live = keys()
    assert paper[0] != live[0]
    assert paper[1] == live[1]
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://API.ALPACA.MARKETS:443/')
    assert keys() == live


def test_compose_forwards_one_url_and_public_authority_without_sender_credentials():
    root = Path(__file__).resolve().parents[2]
    services = yaml.safe_load((root/'docker-compose.sentinel-automation.yml').read_text())['services']
    roles = ('sentinel-authorized-cli', 'sentinel-automation', 'sentinel-execution-collector')
    public_names = {'SENTINEL_LIVE_CERTIFICATE_PATH', 'SENTINEL_LIVE_TRUST_ROOTS_PATH',
                    'SENTINEL_LIVE_PROVISIONING_CERTIFICATE_PATH', 'SENTINEL_LIVE_FUNDING_CERTIFICATE_PATH'}
    for role in roles:
        config = services[role]
        assert config['environment']['ALPACA_BASE_URL'] == '${ALPACA_BASE_URL:-https://paper-api.alpaca.markets}'
        assert public_names <= config['environment'].keys()
        mount = next(item for item in config['volumes'] if isinstance(item, dict)
                     and item['target'] == '/var/lib/sentinel-authority')
        assert mount['read_only'] is True
    sender = services['sentinel-alert-dispatcher']['environment']
    assert sender['ALPACA_BASE_URL'] == services[roles[0]]['environment']['ALPACA_BASE_URL']
    assert sender['ALPACA_API_KEY'] == sender['ALPACA_SECRET_KEY'] == ''
    assert not public_names & sender.keys()
