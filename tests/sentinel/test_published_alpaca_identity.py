"""Published identity survives retention of predecessor acquisition scratch."""
from copy import deepcopy

import pytest

from sentinel.feed import alpaca_identity as identity, calendar, retention, rolling_store
from sentinel.feed.alpaca_transport import AlpacaTransportRefused
from sentinel.feed.rolling_contract import PriceWindow, digest
from tests.sentinel.test_alpaca_daily_formation import provider, OBS  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401
from tests.sentinel.test_alpaca_name_change_continuity import inputs, change_provider


def reference(*, modern=False, bindings=None):
    raw=bindings or []
    return dict(schema='sentinel.rolling-alpaca-openfigi-references/'+('3' if modern else '2'),
        tickers=[dict(table='SEP',ticker='AAA',permaticker='canonical-old')],
        **({'identity_bindings':raw} if modern else {}))


def source(version='1', bindings=None):
    return dict(schema='sentinel.alpaca-openfigi-operational-source/'+version,
        provider='ALPACA_OPENFIGI', identity_bindings_sha256=digest(bindings or []))


def test_legacy_published_identity_does_not_need_classification_scratch():
    assert identity.published_assets(reference(),source())==[dict(ticker='AAA',asset_id='canonical-old')]


@pytest.mark.parametrize('version',['2','3'])
def test_published_provider_mapping_keeps_original_identity_on_next_day(version):
    bound=identity.bind(**inputs())
    selected=identity.published_assets(reference(modern=True,bindings=bound),source(version,bound))
    assert selected==inputs()['selected']
    assert identity.bind(**(inputs() | dict(previous_selected=selected,previous_bindings=bound,
        records=[],previous_session='2026-09-15',target_session='2026-09-16')))==bound


def test_binding_without_admitted_prices_is_still_published_identity_evidence():
    bound=identity.bind(**inputs())
    refs=reference(modern=True,bindings=bound)
    refs['tickers']=[dict(table='SEP',ticker='BBB',permaticker='other-id')]
    assert identity.published_assets(refs,source('3',bound))==[
        dict(ticker='AAA',asset_id='new-provider'),dict(ticker='BBB',asset_id='other-id')]


@pytest.mark.parametrize('kind',['unknown_source','unknown_reference','old_source_new_reference',
    'modern_source_legacy_reference','digest','canonical','duplicate_ticker','duplicate_canonical',
    'provider_collision','missing_tickers','malformed_row'])
def test_unbound_or_ambiguous_published_identity_refuses(kind):
    bound=identity.bind(**inputs());refs=reference(modern=True,bindings=bound);src=source('3',bound)
    if kind=='unknown_source':src['schema']='unknown'
    elif kind=='unknown_reference':refs['schema']='unknown'
    elif kind=='old_source_new_reference':src=source()
    elif kind=='modern_source_legacy_reference':refs=reference()
    elif kind=='digest':src['identity_bindings_sha256']='f'*64
    elif kind=='canonical':refs['tickers'][0]['permaticker']='different-canonical'
    elif kind=='duplicate_ticker':refs['tickers'].append(dict(table='SEP',ticker='AAA',permaticker='other-id'))
    elif kind=='duplicate_canonical':refs['tickers'].append(dict(table='SEP',ticker='BBB',permaticker='canonical-old'))
    elif kind=='provider_collision':refs['tickers'].append(dict(table='SEP',ticker='BBB',permaticker='new-provider'))
    elif kind=='missing_tickers':refs['tickers']=[]
    elif kind=='malformed_row':refs['tickers']=[None]
    with pytest.raises(AlpacaTransportRefused):identity.published_assets(refs,src)


def test_retired_dated_legacy_aggregate_supports_same_day_recovery_and_restart(conn,provider,monkeypatch):
    from sentinel import rolling_initialization as initial,rolling_daily as daily,rolling_checkpoint
    from sentinel.feed import alpaca_source
    prices,publish=provider
    original=alpaca_source.AlpacaSource.reference_payload
    def legacy(self):
        result=original(self);result.pop('identity_bindings')
        return result | dict(schema='sentinel.rolling-alpaca-openfigi-references/2')
    with monkeypatch.context() as old:
        old.setattr(alpaca_source,'SOURCE','sentinel.alpaca-openfigi-operational-source/1')
        old.setattr(alpaca_source.AlpacaSource,'reference_payload',legacy)
        old.setattr(alpaca_source.AlpacaSource,'_previous_identity',lambda self:None)
        before_binding=publish()
        before=initial.initialize(conn,observation_id=OBS,starting_cash=50_000)
        origin=deepcopy(rolling_checkpoint.read(conn).model_dump(mode='json'))
        sid=before.state.median5['selected'][0]
        ticker=before.state.feed['series'][sid]['ticker']
        day=calendar.next_session(before.state.last_processed_session)
        prices.window=PriceWindow.through(day)
        change_provider(prices,ticker=ticker,previous_id=sid,day=day)
        publish()
    old_part=conn.execute("SELECT part_id FROM sentinel_acquisition_bindings WHERE job_id=%s AND component='TICKERS'",
        (before_binding['job_id'],)).fetchone()[0]
    for _ in range(100):
        if not conn.execute('SELECT 1 FROM sentinel_acquisition_parts WHERE part_id=%s',(old_part,)).fetchone():break
        conn.commit();result=retention.maintain(conn,batch_rows=50000)
        assert result['status']=='COMPLETE'
    else:pytest.fail('Canonical retention did not retire the unpinned predecessor aggregate')
    conn.commit()
    assert rolling_store.load_evidence(conn,rolling_store.manifest(conn,before_binding['candidate_id']).reference_sha256)['tickers']
    current=publish()
    manifest=rolling_store.manifest(conn,current['candidate_id'])
    bound=rolling_store.load_evidence(conn,manifest.reference_sha256)['identity_bindings']
    assert len(bound)==1 and bound[0]['security_id']==sid and bound[0]['provider_asset_id']=='replacement-provider'
    assert bound[0]['origin_snapshot_id']==before_binding['snapshot_id']
    advanced=daily.advance(conn,observation_id=OBS,starting_cash=50_000)
    assert advanced.appended and advanced.state.last_processed_session==day
    assert sid in advanced.state.feed['series'] and 'replacement-provider' not in advanced.state.feed['series']
    conn.commit()
    assert rolling_checkpoint.read(conn).model_dump(mode='json')==origin
    assert daily.resume(conn,observation_id=OBS,starting_cash=50_000).state.state_hash==advanced.state.state_hash
    assert not daily.advance(conn,observation_id=OBS,starting_cash=50_000).appended
