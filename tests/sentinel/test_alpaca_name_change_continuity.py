"""Provider object recreation preserves economic identity and leadership returns."""
from decimal import Decimal

import pytest

from sentinel.feed import alpaca_identity as identity, calendar
from sentinel.feed.alpaca_transport import ACTION_URL, AlpacaTransportRefused
from sentinel.feed.rolling_contract import PriceWindow, digest
from tests.sentinel.test_alpaca_daily_formation import provider, OBS  # noqa: F401
from tests.sentinel.test_alpaca_operational_snapshot import alpaca_path  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401


def event(ticker='AAA', day='2026-09-15'):
    return dict(id='rename-proof', old_symbol=ticker, new_symbol=ticker,
                old_cusip='123456789', new_cusip='987654321', process_date=day)


def inputs():
    return dict(selected=[dict(ticker='AAA',asset_id='new-provider')],
        previous_selected=[dict(ticker='AAA',asset_id='canonical-old')],
        previous_bindings=[], records=[('name_changes',event())],
        previous_session='2026-09-14',target_session='2026-09-15',
        previous_snapshot_id=digest('accepted predecessor'))


def test_source_bound_name_change_retains_identity_without_a_share_conversion():
    value=identity.bind(**inputs())
    assert value[0]['security_id']=='canonical-old'
    assert value[0]['provider_asset_id']=='new-provider'
    assert 'exchange_ratio' not in value[0]
    assert identity.canonical_assets(inputs()['selected'],value)==[
        dict(ticker='AAA',asset_id='canonical-old')]
    next_inputs=inputs() | dict(previous_selected=inputs()['selected'],previous_bindings=value,
        records=[],previous_session='2026-09-15',target_session='2026-09-16')
    assert identity.bind(**next_inputs)==value  # Preserve original evidence clock.


@pytest.mark.parametrize('kind',['absent','future','stale'])
def test_uuid_replacement_alone_cannot_invent_continuity(kind):
    args=inputs()
    args['records']=[] if kind=='absent' else [('name_changes',event(day=(
        '2026-09-16' if kind=='future' else '2026-09-14')))]
    assert identity.bind(**args)==[]
    assert identity.canonical_assets(args['selected'],[])==args['selected']


@pytest.mark.parametrize('kind',['duplicate','missing_cusip','same_cusip','symbol_changed','economic'])
def test_ambiguous_or_economic_replacement_refuses(kind):
    args=inputs()
    if kind=='duplicate': args['records'].append(('name_changes',event() | {'id':'second'}))
    elif kind=='missing_cusip': del args['records'][0][1]['old_cusip']
    elif kind=='same_cusip': args['records'][0][1]['new_cusip']='123456789'
    elif kind=='symbol_changed': args['records'][0][1]['old_symbol']='OTHER'
    else: args['records'].append(('stock_mergers',dict(id='economic',
        acquiree_symbol='AAA',acquirer_symbol='BBB',effective_date='2026-09-15')))
    with pytest.raises(ValueError if kind=='missing_cusip' else AlpacaTransportRefused):
        identity.bind(**args)


def test_unit_delivery_does_not_reset_a_common_stock_recipient():
    record=dict(id='units',old_symbol='AAAU',new_symbol='AAA',alternate_symbol='AAAW',
        old_cusip='111111111',new_cusip='987654321',alternate_cusip='333333333',
        old_rate=1,new_rate=1,alternate_rate=.5,effective_date='2026-09-15')
    assert identity.action_sources('unit_splits',record)==frozenset({'AAAU'})
    args=inputs();args['records'].append(('unit_splits',record))
    assert identity.bind(**args)[0]['security_id']=='canonical-old'
    del record['old_cusip']
    assert identity.action_sources('unit_splits',record)==frozenset({'AAAU','AAA','AAAW'})
    with pytest.raises(AlpacaTransportRefused,match='economic action'):
        identity.bind(**args)


def test_binding_collision_and_symbol_mismatch_refuse():
    value=identity.bind(**inputs())
    with pytest.raises(AlpacaTransportRefused,match='duplicate'):
        identity.bindings(value+value)
    with pytest.raises(AlpacaTransportRefused,match='symbol mismatch'):
        identity.canonical_assets([dict(ticker='BBB',asset_id='new-provider')],value)


def test_successive_provider_recreation_keeps_the_original_canonical_identity():
    value=identity.bind(**inputs())
    args=inputs() | dict(selected=[dict(ticker='AAA',asset_id='third-provider')],
        previous_selected=inputs()['selected'],previous_bindings=value,
        records=[('name_changes',event(day='2026-09-16') | dict(old_cusip='987654321',new_cusip='555555555',id='second-proof'))],
        previous_session='2026-09-15',target_session='2026-09-16',
        previous_snapshot_id=digest('next accepted predecessor'))
    result=identity.bind(**args)
    assert result[0]['security_id']=='canonical-old' and result[0]['provider_asset_id']=='third-provider'
    assert result[0]['prior_provider_asset_id']=='new-provider'


def test_reused_identity_event_cannot_be_in_the_future():
    value=identity.bind(**inputs())
    value[0]['event']['process_date']='2026-09-18'
    args=inputs() | dict(previous_selected=inputs()['selected'],previous_bindings=value,
        records=[],previous_session='2026-09-15',target_session='2026-09-16')
    with pytest.raises(AlpacaTransportRefused,match='event is in the future'):
        identity.bind(**args)


def change_provider(prices, *, ticker, previous_id, day, with_event=True):
    original_get, original_pages=prices.get,prices.pages
    def get(endpoint,params):
        assets,proof=original_get(endpoint,params)
        assets=[{**asset,'id':'replacement-provider'} if asset['id']==previous_id else asset for asset in assets]
        return assets,proof
    def pages(endpoint,params,*,key):
        if endpoint==ACTION_URL and with_event:
            yield {'name_changes':[event(ticker,day)],'unit_splits':[
                dict(id='units',old_symbol='UNITS',new_symbol=ticker,alternate_symbol='WARRANTS',
                    old_cusip='111111111',new_cusip='987654321',old_rate=1,new_rate=1,
                    alternate_rate=.5,effective_date=day,process_date=day)]}, {
                        'observed_at':day+'T23:00:00+00:00'}
        else:
            yield from original_pages(endpoint,params,key=key)
    prices.get,prices.pages=get,pages


@pytest.mark.parametrize('owned',[False,True])
def test_daily_name_change_preserves_held_or_leadership_economics_and_restart(conn,provider,owned):
    from sentinel import rolling_initialization as initial,rolling_daily as daily
    from sentinel.core import window_features
    from sentinel.feed import rolling_store
    from sentinel.feed.normalized_layout import candidate_query
    prices,publish=provider
    publish();before=initial.initialize(conn,observation_id=OBS,starting_cash=50_000)
    held={value['security_id']:value for value in before.state.wealth_core['episodes'].values()}
    protected=window_features.protected(before.state)
    sid=next(iter(held)) if owned else next(s for s in sorted(protected) if s not in held)
    ticker=before.state.feed['series'][sid]['ticker']
    old_shares=held[sid]['current_shares'] if owned else None
    before_nav=before.state.median5['witness_nav'][-1]
    prior_closes=before.state.median5['selected_closes']
    day=calendar.next_session(before.state.last_processed_session)
    prices.window=PriceWindow.through(day)
    change_provider(prices,ticker=ticker,previous_id=sid,day=day)
    binding=publish()
    manifest=rolling_store.manifest(conn,binding['candidate_id'])
    reference=rolling_store.load_evidence(conn,manifest.reference_sha256)
    proof=reference['identity_bindings'][0]
    assert proof['security_id']==sid and proof['provider_asset_id']=='replacement-provider'
    current=dict(conn.execute(candidate_query(conn, 'SELECT security_id,close_signal FROM sentinel_snapshot_bars '
        'WHERE candidate_id=%s AND session=%s'),(binding['candidate_id'],day)).fetchall())
    assert set(prior_closes).issubset(current)
    expected_return=sum(Decimal(str(current[key]))/Decimal(str(close))-1
        for key,close in prior_closes.items())/len(prior_closes)
    result=daily.advance(conn,observation_id=OBS,starting_cash=50_000)
    assert result.state.median5['witness_nav'][-1]==pytest.approx(before_nav*float(1+expected_return),rel=1e-12)
    if owned:
        after=next(value for value in result.state.wealth_core['episodes'].values() if value['security_id']==sid)
        assert after['current_shares']==old_shares
    assert 'replacement-provider' not in result.state.feed['series']
    conn.commit()
    assert daily.resume(conn,observation_id=OBS,starting_cash=50_000).state.state_hash==result.state.state_hash
    assert not daily.advance(conn,observation_id=OBS,starting_cash=50_000).appended
    # The next daily source retains the original identity/event proof.
    prices.window=PriceWindow.through(calendar.next_session(day));next_binding=publish()
    next_manifest=rolling_store.manifest(conn,next_binding['candidate_id'])
    assert rolling_store.load_evidence(conn,next_manifest.reference_sha256)['identity_bindings']==[proof]


def test_unproven_controller_identity_replacement_retains_original_book(conn,provider):
    from sentinel import rolling_initialization as initial,rolling_daily as daily,rolling_daily_checkpoint
    from sentinel.rolling_reconstruction_evidence import InputsUnavailable
    prices,publish=provider
    publish();before=initial.initialize(conn,observation_id=OBS,starting_cash=50_000)
    sid=before.state.median5['selected'][0]
    ticker=before.state.feed['series'][sid]['ticker']
    day=calendar.next_session(before.state.last_processed_session)
    prices.window=PriceWindow.through(day)
    change_provider(prices,ticker=ticker,previous_id=sid,day=day,with_event=False)
    publish()
    with pytest.raises(InputsUnavailable,match='HELD_ECONOMIC_INPUT_PENDING'):
        daily.advance(conn,observation_id=OBS,starting_cash=50_000)
    conn.rollback()
    _,_,restored=rolling_daily_checkpoint.load(conn,initial._context(OBS,50_000))
    assert restored.state.state_hash==before.state.state_hash


@pytest.mark.parametrize('legacy_policy',['1','2'])
def test_old_source_policy_cannot_satisfy_fresh_readiness(conn,provider,monkeypatch,legacy_policy):
    from sentinel import rolling_initialization as initial
    from sentinel.feed import alpaca_source,rolling_go_inputs
    prices,publish=provider
    publish();before=initial.initialize(conn,observation_id=OBS,starting_cash=50_000)
    prices.window=PriceWindow.through(calendar.next_session(before.state.last_processed_session))
    current=alpaca_source.SOURCE
    original=alpaca_source.AlpacaSource.reference_payload
    def legacy_reference(self):
        value=original(self)
        if legacy_policy=='1':
            value.pop('identity_bindings')
            return value | dict(schema='sentinel.rolling-alpaca-openfigi-references/2')
        return value
    monkeypatch.setattr(alpaca_source,'SOURCE','sentinel.alpaca-openfigi-operational-source/'+legacy_policy)
    monkeypatch.setattr(alpaca_source.AlpacaSource,'reference_payload',legacy_reference)
    publish()
    monkeypatch.setattr(alpaca_source,'SOURCE',current)
    monkeypatch.setattr(alpaca_source.AlpacaSource,'reference_payload',original)
    def fresh_acquisition(*_args,**_kwargs):
        raise ConnectionError('fresh identity source required')
    monkeypatch.setattr(rolling_go_inputs.snapshots,'enqueue',fresh_acquisition)
    with pytest.raises(ConnectionError,match='fresh identity source required'):
        rolling_go_inputs._prepare(conn,target_session=str(prices.window.end))


@pytest.mark.parametrize('mismatch',['old_source_new_reference','new_source_old_reference','binding_digest',
                                  'unknown_source_old_reference'])
def test_source_and_identity_reference_must_agree(conn,alpaca_path,monkeypatch,mismatch):
    from sentinel.feed import operational_snapshot as op,rolling_store
    from sentinel.core.rolling_inputs import SnapshotReferences,RollingInputsRefused
    job=op.enqueue(conn,strategy_sha256=digest('identity-reader-fixture'),
        dependencies_sha256=digest('identity-reader-dependencies'),budget_seconds=240)
    conn.commit();binding=op.prepare(conn,job)
    manifest=rolling_store.manifest(conn,binding['candidate_id'])
    original=rolling_store.load_evidence
    def mixed(c,sha):
        value=original(c,sha)
        if sha==manifest.source_evidence_sha256:
            if mismatch=='unknown_source_old_reference':
                return value | dict(schema='sentinel.alpaca-openfigi-operational-source/unknown')
            if mismatch=='old_source_new_reference':
                return value | dict(schema='sentinel.alpaca-openfigi-operational-source/1')
            if mismatch=='binding_digest':return value | dict(identity_bindings_sha256='f'*64)
        if sha==manifest.reference_sha256 and mismatch in ('new_source_old_reference','unknown_source_old_reference'):
            return {key:item for key,item in value.items() if key!='identity_bindings'} | dict(
                schema='sentinel.rolling-alpaca-openfigi-references/2')
        return value
    monkeypatch.setattr(rolling_store,'load_evidence',mixed)
    with pytest.raises(RollingInputsRefused,match='UNBOUND_ALPACA_IDENTITY'):
        SnapshotReferences(conn,candidate_id=binding['candidate_id'],snapshot_id=binding['snapshot_id'])
