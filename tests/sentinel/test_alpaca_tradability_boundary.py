"""Broker permissions cannot change listed inputs or corroboration identity."""
from copy import deepcopy

import pytest

from sentinel.feed import openfigi, calendar
from sentinel.feed.acquisition_parts import SourceRevision
from sentinel.feed.alpaca_source import AlpacaSource
from sentinel.feed.alpaca_transport import ASSETS, AlpacaTransportRefused
from sentinel.feed.rolling_contract import PriceWindow
from tests.sentinel.test_alpaca_operational_snapshot import alpaca_path, _publish  # noqa: F401
from tests.sentinel.test_alpaca_daily_formation import provider, OBS  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401


def asset(**changes):
    return dict(id='listed-id', symbol='AAA', name='Ordinary shares',
                exchange='NYSE', status='active', **{'class': 'us_equity'},
                tradable=True) | changes


@pytest.mark.parametrize('permission', [True, False, None, 'unavailable'])
def test_listing_capture_does_not_use_a_broker_permission(permission):
    assert openfigi.inventory([asset(tradable=permission)]) == [
        dict(asset_id='listed-id', ticker='AAA', name='Ordinary shares', exchange='NYSE')]
    raw=asset();raw.pop('tradable')
    assert openfigi.inventory([raw]) == openfigi.inventory([asset()])


@pytest.mark.parametrize('changes', [dict(status='inactive'), dict(exchange='OTC'), {'class':'crypto'}])
def test_real_listing_and_instrument_exclusions_remain(changes):
    assert openfigi.inventory([asset(tradable=False) | changes]) == []


@pytest.mark.parametrize('permission', [True, False])
def test_duplicate_identity_is_not_hidden_by_a_permission_flag(permission):
    with pytest.raises(AlpacaTransportRefused, match='duplicate'):
        openfigi.inventory([asset(), asset(symbol='OTHER', tradable=permission)])


def source_with_reobservation(raw):
    class Client:
        def get(self, endpoint, params):
            assert endpoint == ASSETS
            return [raw], {'observed_at':'2026-10-12T23:00:00+00:00'}
    source=AlpacaSource(None, None, None, client=Client())
    source.assets=openfigi.inventory([asset()])
    source._action_rows=lambda: (dict(affected=[], reset_after={}, dividends=[],
        pending_cash=[], splits=[], identity_bindings=[]), None, {}, 0)
    return source


def test_permission_only_reobservation_does_not_invent_a_source_revision():
    source_with_reobservation(asset(tradable=False)).corroborate()


@pytest.mark.parametrize('permission',[False,None,'true'])
def test_listed_data_does_not_grant_execution_permission(permission):
    from sentinel.execution.alpaca import MalformedBrokerPayload
    from tests.sentinel.test_issue_183_alpaca_hardening import adapter,run
    raw=asset(tradable=permission)
    assert openfigi.inventory([raw])
    broker,http=adapter(routes={'/v2/assets/AAA':raw})
    with pytest.raises(MalformedBrokerPayload,match='not tradable'):
        run(broker.resolve_instrument(security_id='SEC-AAA',symbol='AAA'))
    assert http.calls==[('GET','/v2/assets/AAA',{})]


@pytest.mark.parametrize('changes', [dict(id='new-id'), dict(symbol='OTHER'),
    dict(exchange='NASDAQ'), dict(status='inactive'), dict(exchange='OTC')])
def test_true_listing_reobservation_changes_still_refuse(changes):
    with pytest.raises(SourceRevision, match='source component \\*'):
        source_with_reobservation(asset() | changes).corroborate()


@pytest.mark.parametrize('initial_permission', [True, False])
def test_permission_flip_during_acquisition_still_publishes_complete_inputs(
        conn, alpaca_path, initial_permission):
    original=alpaca_path.get
    reads=[]
    def get(endpoint,params):
        values,proof=original(endpoint,params)
        if endpoint==ASSETS:
            permission=initial_permission if not reads else not initial_permission
            reads.append(permission)
            values=[value | dict(tradable=permission) for value in values]
        return values,proof
    alpaca_path.get=get
    binding=_publish(conn)
    assert reads==[initial_permission,not initial_permission]
    from sentinel.feed import rolling_store
    manifest=rolling_store.manifest(conn,binding['candidate_id'])
    reference=rolling_store.load_evidence(conn,manifest.reference_sha256)
    assert {row['ticker'] for row in reference['tickers']}=={'AAA','BBB'}
    assert all('tradable' not in row for row in reference['tickers'])
    assert len(list(rolling_store.read_bars(conn,binding['candidate_id'])))==600


def test_untradable_listing_supports_canonical_formation_daily_restart_without_broker(conn,provider):
    from sentinel import rolling_initialization as initial, rolling_daily as daily, rolling_checkpoint as origin
    prices,publish=provider
    original=prices.get
    permission=[False]
    def get(endpoint,params):
        values,proof=original(endpoint,params)
        if endpoint==ASSETS:values=[value | dict(tradable=permission[0]) for value in values]
        return values,proof
    prices.get=get
    publish()
    formed=initial.initialize(conn,observation_id=OBS,starting_cash=50_000)
    original_origin=deepcopy(origin.read(conn).model_dump(mode='json'))
    day=calendar.next_session(formed.state.last_processed_session)
    permission[0]=True
    prices.window=PriceWindow.through(day)
    publish()
    advanced=daily.advance(conn,observation_id=OBS,starting_cash=50_000)
    assert advanced.appended and advanced.state.last_processed_session==day
    conn.commit()
    assert origin.read(conn).model_dump(mode='json')==original_origin
    assert daily.resume(conn,observation_id=OBS,starting_cash=50_000).state.state_hash==advanced.state.state_hash
    assert not daily.advance(conn,observation_id=OBS,starting_cash=50_000).appended
