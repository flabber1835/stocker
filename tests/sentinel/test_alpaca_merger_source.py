"""Authenticated Alpaca merger terms across distinct permanent identities."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from sentinel.feed import alpaca_identity as identity
from sentinel.feed.alpaca_transport import AlpacaTransportRefused
from sentinel.feed.alpaca_pending import AlpacaSourcePending
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_alpaca_daily_formation import provider, OBS  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401


DAY = '2026-09-15'
PRIOR = '2026-09-14'


@pytest.fixture
def synthetic_feed_authority(monkeypatch, tmp_path):
    """Bind this module's synthetic provider to a test-only publication key."""
    from sentinel import backup_runtime_authority, identity as runtime_identity

    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'test-only-receipt-key-' * 4)
    monkeypatch.setattr(backup_runtime_authority, 'POLICY_MARKER',
                        tmp_path / 'absent-production-backup-policy')
    assert not backup_runtime_authority.enabled()
    monkeypatch.setattr(runtime_identity, 'require_feed_producer_identity', lambda: {
        'schema': 'sentinel.feed-producer/1',
        'git_commit': 'a' * 40,
        'runtime_image_digest': 'sha256:' + 'b' * 64,
        'image_source_revision': 'a' * 40,
    })


def merger(old, new='AAA', *, id, old_cusip='111111111', new_cusip='999999999',
           old_rate='1', new_rate='1'):
    # Alpaca's published stock-merger fields use acquirer_rate/acquiree_rate.
    # https://docs.alpaca.markets/us/reference/corporateactions-1
    return dict(id=id, acquiree_symbol=old, acquirer_symbol=new,
        acquiree_cusip=old_cusip, acquirer_cusip=new_cusip,
        acquiree_rate=old_rate, acquirer_rate=new_rate,
        process_date=DAY, effective_date=DAY)


def inputs(records):
    return dict(selected=[dict(ticker='AAA', asset_id='new-aaa')],
        previous_identity=dict(previous_selected=[
            dict(ticker='AAA', asset_id='old-aaa'),
            dict(ticker='BBB', asset_id='old-bbb')],
            previous_bindings=[], previous_session=PRIOR,
            previous_snapshot_id=digest('prior published source')),
        bindings_raw=[], records=[('stock_mergers', record) for record in records],
        target_session=DAY)


def test_two_acquirees_to_one_successor_keep_distinct_identities_and_exact_ratio():
    same = merger('AAA', id='same-symbol', old_cusip='111111111')
    gone = merger('BBB', id='vanished', old_cusip='222222222',
                  old_rate='2', new_rate='3')
    rows = identity.merger_conversions(**inputs([same, gone]))
    assert [(row['old_security_id'], row['successor_security_id'], row['exchange_ratio'])
            for row in rows] == [('old-aaa', 'new-aaa', '1'),
                                ('old-bbb', 'new-aaa', '1.5')]
    assert {row['origin_snapshot_id'] for row in rows} == {digest('prior published source')}
    assert all(row['raw_record']['id'] == row['record_id']
               and digest(row['raw_record']) == row['terms_sha256'] for row in rows)
    assert {value.old_security_id for value in identity.conversions(rows)} == {'old-aaa', 'old-bbb'}
    assert identity.action_sources('stock_mergers', gone) == {'AAA', 'BBB'}


@pytest.mark.parametrize('change', [
    {'acquirer_rate': None}, {'acquirer_rate': 'NaN'},
    {'acquiree_rate': 0}, {'acquirer_cusip': '111111111'},
    {'effective_date': '2026-09-16'}, {'acquirer_symbol': 'MISSING'},
    {'acquirer_rate': '1', 'acquiree_rate': '3'},
])
def test_unsupported_merger_omits_conversion_without_blocking_other_source(change):
    record = merger('AAA', id='unsupported') | change
    assert identity.merger_conversions(**inputs([record])) == []


def test_conflicting_record_refuses_admissible_conversion():
    good = merger('AAA', id='complete')
    incomplete = merger('AAA', id='other') | {'acquirer_rate': None}
    with pytest.raises(AlpacaTransportRefused, match='ambiguous stock merger'):
        identity.merger_conversions(**inputs([good, incomplete]))
    conflicting = merger('BBB', id='different-cusip', old_cusip='222222222',
                         new_cusip='888888888')
    with pytest.raises(AlpacaTransportRefused, match='successor CUSIP conflicts'):
        identity.merger_conversions(**inputs([good, conflicting]))


def test_tampered_projection_and_raw_terms_refuse():
    rows = identity.merger_conversions(**inputs([merger('AAA', id='source')]))
    for tamper in (
        lambda row: row.update(exchange_ratio='2'),
        lambda row: row.update(successor_security_id='old-aaa'),
        lambda row: row['raw_record'].update(acquirer_rate='2'),
        lambda row: row.update(terms_sha256='f' * 64),
    ):
        altered = deepcopy(rows)
        tamper(altered[0])
        with pytest.raises((ValueError, AlpacaTransportRefused)):
            identity.conversions(altered)


def test_vanished_acquiree_preserves_unchanged_acquirer_history():
    from sentinel.feed.alpaca_source import AlpacaSource
    from sentinel.feed.alpaca_transport import ACTION_URL
    from sentinel.feed.rolling_contract import PriceWindow

    record = merger('BBB', id='vanished', old_cusip='222222222')

    class Pages:
        def pages(self, endpoint, params, *, key):
            assert endpoint == ACTION_URL
            yield {'stock_mergers': [record]}, {'observed_at': DAY + 'T23:00:00+00:00'}

    source = object.__new__(AlpacaSource)
    source.window = PriceWindow.through(DAY)
    source.selected = [dict(ticker='AAA', asset_id='old-aaa')]
    source.client = Pages()
    prior = inputs([])['previous_identity']
    source._previous_identity = lambda: prior
    payload, *_ = source._action_rows()
    assert payload['reset_after'] == {}
    assert payload['affected'] == []
    assert [(row['old_security_id'], row['successor_security_id'])
            for row in payload['merger_conversions']] == [('old-bbb', 'old-aaa')]


@pytest.mark.parametrize('record', [None,
    merger('AAA', id='early-partial') | {'acquirer_rate': None}])
def test_unbound_same_symbol_uuid_change_quarantines_candidate(record):
    from sentinel.feed.alpaca_source import AlpacaSource
    from sentinel.feed.alpaca_transport import ACTION_URL
    from sentinel.feed.rolling_contract import PriceWindow

    class Pages:
        def pages(self, endpoint, params, *, key):
            assert endpoint == ACTION_URL
            yield {'stock_mergers': [] if record is None else [record]}, {
                'observed_at': DAY + 'T23:00:00+00:00'}

    source = object.__new__(AlpacaSource)
    source.window = PriceWindow.through(DAY)
    source.selected = [dict(ticker='AAA', asset_id='new-aaa')]
    source.client = Pages()
    source._previous_identity = lambda: inputs([])['previous_identity']
    payload, *_ = source._action_rows()
    assert payload['reset_after']['AAA'] == DAY
    assert [(row['ticker'], row['old_provider_asset_id'],
             row['new_provider_asset_id'], row['split'])
            for row in payload['identity_breaks']] == [('AAA', 'old-aaa', 'new-aaa', None)]


def test_same_session_action_reobservation_waits_for_new_conversion():
    from sentinel.feed.alpaca_source import AlpacaSource
    from sentinel.feed.alpaca_transport import ACTION_URL
    from sentinel.feed.rolling_contract import PriceWindow

    record = merger('AAA', id='same-symbol')

    class Pages:
        def pages(self, endpoint, params, *, key):
            assert endpoint == ACTION_URL
            yield {'stock_mergers': [record]}, {'observed_at': DAY + 'T23:00:00+00:00'}

    source = object.__new__(AlpacaSource)
    source.window = PriceWindow.through(DAY)
    source.selected = [dict(ticker='AAA', asset_id='new-aaa')]
    source.client = Pages()
    source._previous_identity = lambda: inputs([])['previous_identity']
    source.same_session_conversions = identity.merger_conversions(**inputs([record]))
    with pytest.raises(AlpacaSourcePending, match='ALPACA_ACTION_REOBSERVATION_PENDING'):
        source._action_rows()

    source.same_session_conversions = []
    payload, *_ = source._action_rows()
    assert len(payload['merger_conversions']) == 1


def test_missing_action_quarantines_one_candidate_without_stopping_publication(
        conn, provider, synthetic_feed_authority):
    from sentinel import rolling_initialization
    from sentinel.feed import calendar, operational_snapshot as op, rolling_jobs as jobs, rolling_store
    from sentinel.feed.alpaca_transport import ACTION_URL, ASSETS
    from sentinel.feed.rolling_contract import PriceWindow
    from sentinel.strategy import production_strategy

    prices, publish = provider
    origin = publish()
    rolling_initialization.initialize(conn, observation_id=OBS, starting_cash=50_000)
    day = calendar.next_session(str(prices.window.end))
    prices.window = PriceWindow.through(day)
    original_get, original_pages = prices.get, prices.pages
    asset_observations = []

    def changed_asset(endpoint, params):
        assets, proof = original_get(endpoint, params)
        assert endpoint == ASSETS
        asset_observations.append(True)
        return [({**item, 'id': 'new-uuid-00'} if item['symbol'] == 'T00' else item)
                for item in assets], proof

    records = []

    def late_actions(endpoint, params, *, key):
        if endpoint == ACTION_URL:
            yield {'stock_mergers': records}, {'observed_at': day + 'T23:00:00+00:00'}
        else:
            yield from original_pages(endpoint, params, key=key)

    prices.get, prices.pages = changed_asset, late_actions
    _, strategy = production_strategy()
    job = op.enqueue(conn, strategy_sha256=digest(strategy),
                     dependencies_sha256=digest('late-action-fixture'), budget_seconds=900)
    conn.commit()
    deadline = jobs.status(conn, job)['deadline']
    binding = op.prepare(conn, job)
    state = jobs.status(conn, job)
    assert state['state'] == 'PUBLISHED' and state['deadline'] == deadline
    assert op._current(conn).version > origin['data_version']
    assert jobs.status(conn, job)['deadline'] == deadline
    manifest = rolling_store.manifest(conn, binding['candidate_id'])
    reference = rolling_store.load_evidence(conn, manifest.reference_sha256)
    source = rolling_store.load_evidence(conn, manifest.source_evidence_sha256)
    assert source['selected_count'] == 25 and source['admitted_count'] == 24
    assert not any(row['ticker'] == 'T00' for row in reference['tickers'])
    assert [(row['old_provider_asset_id'], row['new_provider_asset_id'], row['split'])
            for row in source['identity_breaks']] == [('uuid-00', 'new-uuid-00', None)]
    assert len(asset_observations) >= 2


@pytest.mark.parametrize('gap,symbol,latest_closed', [
    ('latest', 'SPY', DAY),
    ('historical', 'SPY', DAY),
    ('stale', 'SPY', '2026-09-16'),
    ('latest', 'BIL', DAY),
    ('stale', 'BIL', '2026-09-16'),
])
def test_benchmark_gap_waits_only_for_just_closed_session(
        gap, symbol, latest_closed, monkeypatch):
    from sentinel.feed import calendar
    from sentinel.feed.alpaca_source import AlpacaSource, _bounds
    from sentinel.feed.rolling_contract import PriceWindow

    monkeypatch.setattr(calendar, 'latest_closed_session', lambda now=None: latest_closed)
    source = object.__new__(AlpacaSource)
    source.window = PriceWindow.through(DAY)
    source.action_affected = frozenset()
    source.reset_after = {}
    source.splits = []
    sessions = list(map(str, source.window.sessions))
    missing = sessions[-2] if gap == 'historical' else sessions[-1]

    def bars(symbols, first, last, adjustment):
        result = {}
        for ticker in symbols:
            result[ticker] = [dict(t=datetime.fromisoformat(_bounds(day, day)[0])
                .astimezone(timezone.utc).isoformat(), o=100.0, c=100.0, v=1000)
            for day in sessions if not (ticker == symbol and day == missing
                    and adjustment == 'raw')]
        return result, []

    source._bars = bars
    if gap == 'latest':
        with pytest.raises(AlpacaSourcePending, match='ALPACA_BENCHMARK_CLOSE_PENDING'):
            source._benchmark_rows()
    elif symbol == 'BIL':
        with pytest.raises(AlpacaTransportRefused, match='BIL split-only/raw prices lack corroborated coverage'):
            source._benchmark_rows()
    else:
        with pytest.raises(AlpacaTransportRefused, match='SPY/BIL lack exact paired daily coverage'):
            source._benchmark_rows()


def test_action_pending_after_part_commit_requires_fresh_revision_successor():
    from sentinel.feed.acquisition_parts import SourceRevision
    from sentinel.feed.alpaca_source import AlpacaSource

    source = object.__new__(AlpacaSource)
    source.assets = []
    source.merger_conversions = []
    source._inventory = lambda: ({'assets': []}, None, None, 0)

    def pending():
        raise AlpacaSourcePending('ALPACA_IDENTITY_ACTION_PENDING', symbol='AAA')

    source._action_rows = pending
    with pytest.raises(SourceRevision) as caught:
        source.corroborate()
    assert caught.value.component == 'ACTIONS'


def test_published_same_symbol_and_vanished_acquiree_earn_current_return(
        conn, provider, synthetic_feed_authority):
    from sentinel import rolling_daily, rolling_initialization
    from sentinel.core.window_material import protected
    from sentinel.core.session import _path_dependent_security_ids
    from sentinel.feed import calendar, rolling_store
    from sentinel.feed.alpaca_transport import ACTION_URL, ASSETS
    from sentinel.feed.normalized_layout import candidate_query
    from sentinel.feed.rolling_contract import PriceWindow

    prices, publish = provider
    origin = publish()
    before = rolling_initialization.initialize(conn, observation_id=OBS, starting_cash=50_000)
    held = {item['security_id'] for item in before.state.wealth_core['episodes'].values()}
    owned = _path_dependent_security_ids(before.state.wealth_core, before.state.pending)
    selected_only = [sid for sid in before.state.median5['selected'] if sid not in owned]
    assert len(selected_only) >= 2
    old_a, old_b = selected_only[:2]
    ticker_a = before.state.feed['series'][old_a]['ticker']
    ticker_b = before.state.feed['series'][old_b]['ticker']
    day = calendar.next_session(before.state.last_processed_session)
    prices.window = PriceWindow.through(day)
    old_get, old_pages = prices.get, prices.pages

    def get(endpoint, params):
        assets, proof = old_get(endpoint, params)
        assert endpoint == ASSETS
        return [({**asset, 'id': 'successor-aaa'} if asset['symbol'] == ticker_a else asset)
                for asset in assets if asset['symbol'] != ticker_b], proof

    records = [merger(ticker_a, ticker_a, id='same-symbol', old_cusip='111111111'),
               merger(ticker_b, ticker_a, id='vanished', old_cusip='222222222',
                      old_rate='2', new_rate='3')]

    def pages(endpoint, params, *, key):
        if endpoint == ACTION_URL:
            yield {'stock_mergers': records}, {'observed_at': day + 'T23:00:00+00:00'}
        else:
            yield from old_pages(endpoint, params, key=key)

    prices.get, prices.pages = get, pages
    binding = publish()
    manifest = rolling_store.manifest(conn, binding['candidate_id'])
    reference = rolling_store.load_evidence(conn, manifest.reference_sha256)
    source = rolling_store.load_evidence(conn, manifest.source_evidence_sha256)
    conversions = identity.conversions(reference['merger_conversions'])
    assert source['merger_conversions_sha256'] == digest(reference['merger_conversions'])
    assert {(row.old_security_id, row.successor_security_id) for row in conversions} == {
        (old_a, 'successor-aaa'), (old_b, 'successor-aaa')}
    assert {row.origin_snapshot_id for row in conversions} == {origin['snapshot_id']}

    bars = conn.execute(candidate_query(conn,
        'SELECT security_id,session,close_unadjusted,close_signal FROM sentinel_snapshot_bars '
        'WHERE candidate_id=%s AND security_id=ANY(%s) ORDER BY security_id,session'),
        (binding['candidate_id'], [old_a, old_b, 'successor-aaa'])).fetchall()
    assert [(str(session), sid) for sid, session, _raw, _signal in bars] == [(day, 'successor-aaa')]
    raw = float(bars[0][2])
    current_closes = dict(conn.execute(candidate_query(conn,
        'SELECT security_id,close_signal FROM sentinel_snapshot_bars '
        'WHERE candidate_id=%s AND session=%s'),
        (binding['candidate_id'], day)).fetchall())
    prior = before.state.median5
    total = 0.0
    for sid in prior['selected']:
        if sid in (old_a, old_b):
            anchor = before.state.feed['series'][sid]['signal_basis_anchor']
            ratio = 1.0 if sid == old_a else 1.5
            now = ratio * raw * anchor[2] / anchor[1]
        else:
            now = current_closes[sid]
        total += now / prior['selected_closes'][sid] - 1
    expected_nav = prior['witness_nav'][-1] * (1 + total / len(prior['selected']))

    after = rolling_daily.advance(conn, observation_id=OBS, starting_cash=50_000)
    assert after.state.median5['witness_nav'][-1] == pytest.approx(expected_nav, rel=1e-12)
    assert old_a not in after.state.median5['selected']
    assert old_b not in after.state.median5['selected']
    assert old_a not in protected(after.state) and old_b not in protected(after.state)
    assert old_a not in held and old_b not in held
    conn.commit()
    assert rolling_daily.resume(conn, observation_id=OBS,
        starting_cash=50_000).state.state_hash == after.state.state_hash


def test_irrelevant_incomplete_merger_does_not_block_source_or_daily_book(
        conn, provider, synthetic_feed_authority):
    from sentinel import rolling_daily, rolling_initialization
    from sentinel.core.window_material import protected
    from sentinel.feed import calendar, rolling_store
    from sentinel.feed.alpaca_transport import ACTION_URL, ASSETS
    from sentinel.feed.rolling_contract import PriceWindow

    prices, publish = provider
    original_get, original_pages = prices.get, prices.pages

    def expanded_get(endpoint, params):
        assets, proof = original_get(endpoint, params)
        assert endpoint == ASSETS
        assets.extend({'id': f'uuid-{i:02}', 'symbol': f'T{i:02}',
            'name': f'Company {i}', 'class': 'us_equity', 'status': 'active',
            'tradable': True, 'exchange': 'NASDAQ'} for i in range(25, 50))
        return assets, proof

    prices.get = expanded_get
    origin = publish()
    before = rolling_initialization.initialize(conn, observation_id=OBS, starting_cash=50_000)
    manifest = rolling_store.manifest(conn, origin['candidate_id'])
    reference = rolling_store.load_evidence(conn, manifest.reference_sha256)
    protected_ids = protected(before.state)
    irrelevant = next(row for row in reference['tickers']
                      if row['permaticker'] not in protected_ids)
    old_symbol = irrelevant['ticker']
    day = calendar.next_session(before.state.last_processed_session)
    prices.window = PriceWindow.through(day)

    def current_get(endpoint, params):
        assets, proof = expanded_get(endpoint, params)
        return [asset for asset in assets if asset['symbol'] != old_symbol], proof

    incomplete = merger(old_symbol, 'MISSING', id='incomplete-unheld') | {'acquirer_rate': None}

    def pages(endpoint, params, *, key):
        if endpoint == ACTION_URL:
            yield {'stock_mergers': [incomplete]}, {'observed_at': day + 'T23:00:00+00:00'}
        else:
            yield from original_pages(endpoint, params, key=key)

    prices.get, prices.pages = current_get, pages
    binding = publish()
    source_manifest = rolling_store.manifest(conn, binding['candidate_id'])
    current = rolling_store.load_evidence(conn, source_manifest.reference_sha256)
    assert current['merger_conversions'] == []
    after = rolling_daily.advance(conn, observation_id=OBS, starting_cash=50_000)
    assert after.appended and after.state.last_processed_session == day
