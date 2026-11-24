"""A replaced Alpaca UUID cannot borrow an earlier security's price history."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from sentinel.feed import alpaca_identity as identity, calendar
from sentinel.feed.alpaca_pending import AlpacaSourcePending
from sentinel.feed.alpaca_source import AlpacaSource
from sentinel.feed.alpaca_transport import ACTION_URL, ASSETS, BAR_URL, AlpacaTransportRefused
from sentinel.feed.rolling_contract import CurrentFormationWindow, PriceWindow, digest
from tests.sentinel.test_alpaca_daily_formation import OBS, provider  # noqa: F401
from tests.sentinel.test_alpaca_merger_source import synthetic_feed_authority  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401


DAY = '2026-09-15'
NEXT = '2026-09-16'
OLD = 'old-provider'
NEW = 'new-provider'


def split(*, day=DAY, record_id='split-proof', old_cusip='111111111',
          new_cusip='222222222', old_rate=5, new_rate=1):
    return dict(id=record_id, symbol='AAA', process_date=day, ex_date=day,
                old_cusip=old_cusip, new_cusip=new_cusip,
                old_rate=old_rate, new_rate=new_rate)


def previous(*, breaks=()):
    return dict(previous_selected=[dict(ticker='AAA', asset_id=OLD)],
                previous_bindings=[], previous_session='2026-09-14',
                previous_snapshot_id=digest('authenticated predecessor'),
                identity_breaks=list(breaks))


def action_source(records, *, prior=None, target=DAY, current=NEW):
    class Pages:
        def pages(self, endpoint, params, *, key):
            assert endpoint == ACTION_URL and key == 'corporate_actions'
            yield {'reverse_splits': deepcopy(records)}, {
                'observed_at': target + 'T23:00:00+00:00'}

    source = object.__new__(AlpacaSource)
    source.window = PriceWindow.through(target)
    source.client = Pages()
    source.selected = [dict(ticker='AAA', asset_id=current)]
    source.assets = list(source.selected)
    source._previous_identity = lambda: previous() if prior is None else prior
    return source


def test_complete_reverse_split_records_an_independent_uuid_break_and_floor():
    row = split()
    payload, *_ = action_source([row])._action_rows()
    assert payload['reset_after']['AAA'] == DAY
    assert payload['affected'] == []
    assert len(payload['identity_breaks']) == 1
    br = payload['identity_breaks'][0]
    assert (br['ticker'], br['old_provider_asset_id'], br['new_provider_asset_id']) == (
        'AAA', OLD, NEW)
    assert br['origin_snapshot_id'] == previous()['previous_snapshot_id']
    assert br['floor_session'] == DAY
    assert br['split']['record_id'] == row['id']
    assert br['split']['terms_sha256'] == digest(row)
    assert br['split']['economic_session'] == DAY
    assert br['split']['old_rate'] == '5' and br['split']['new_rate'] == '1'
    assert identity.canonical_assets(action_source([row]).selected, []) == [
        dict(ticker='AAA', asset_id=NEW)]


@pytest.mark.parametrize('records', [
    [],
    [split() | {'ex_date': NEXT}],
    [split(old_cusip='111111111', new_cusip='111111111')],
    [split(old_rate=0)],
    [split(), split(record_id='contradictory', new_cusip='333333333')],
])
def test_missing_future_or_conflicting_split_keeps_candidate_quarantined(records):
    payload, *_ = action_source(records)._action_rows()
    assert payload['reset_after']['AAA'] == DAY
    assert len(payload['identity_breaks']) == 1
    assert payload['identity_breaks'][0]['split'] is None
    assert not payload['identity_bindings']
    assert not payload['merger_conversions']


def _replace_provider(prices, ticker, prior_id, *, action=split()):
    original_get, original_pages = prices.get, prices.pages
    event = {**action, 'symbol': ticker}
    ny = ZoneInfo('America/New_York')

    def get(endpoint, params):
        assert endpoint == ASSETS
        assets, proof = original_get(endpoint, params)
        return [({**asset, 'id': NEW} if asset['symbol'] == ticker else asset)
                for asset in assets], proof

    def pages(endpoint, params, *, key):
        if endpoint == ACTION_URL:
            yield {'reverse_splits': [event]}, {'observed_at': DAY + 'T23:00:00+00:00'}
            return
        assert endpoint == BAR_URL
        for page, proof in original_pages(endpoint, params, key=key):
            page = deepcopy(page)
            for bar in page.get(ticker, []):
                day = datetime.fromisoformat(bar['t']).astimezone(ny).date().isoformat()
                if (params['adjustment'] == 'split' and day < DAY) or day >= DAY:
                    bar['o'] *= 5
                    bar['c'] *= 5
            yield page, proof

    prices.get, prices.pages = get, pages
    return event


def _source_evidence(conn, binding):
    from sentinel.feed import rolling_store
    manifest = rolling_store.manifest(conn, binding['candidate_id'])
    return (rolling_store.load_evidence(conn, manifest.source_evidence_sha256),
            rolling_store.load_evidence(conn, manifest.reference_sha256))


def _bar_rows(conn, binding, ticker):
    from sentinel.feed.normalized_layout import candidate_query
    return conn.execute(candidate_query(conn,
        'SELECT session,security_id,close_signal,close_unadjusted FROM sentinel_snapshot_bars '
        'WHERE candidate_id=%s AND ticker=%s ORDER BY session'),
        (binding['candidate_id'], ticker)).fetchall()


def test_split_uuid_break_excludes_old_and_event_day_prices_then_carries_fresh_tail(
        conn, provider, synthetic_feed_authority):
    from sentinel.feed import operational_snapshot, rolling_store

    prices, publish = provider
    publish()
    old_id, ticker = 'uuid-00', 'T00'
    prices.window = CurrentFormationWindow.through(DAY)
    event = _replace_provider(prices, ticker, old_id)

    first = publish()
    source, reference = _source_evidence(conn, first)
    assert source['selected_count'] == 25
    assert source['admitted_count'] == 24  # 24/25 passes; 23/25 would fail 95%.
    assert not any(row['ticker'] == ticker for row in reference['tickers'])
    assert _bar_rows(conn, first, ticker) == []
    br = source['identity_breaks'][0]
    assert br['ticker'] == ticker and br['floor_session'] == DAY
    assert br['split']['terms_sha256'] == digest(event)
    assert br['old_provider_asset_id'] == old_id and br['new_provider_asset_id'] == NEW

    conn.commit()
    assert operational_snapshot._current(conn).version == first['data_version']
    assert _source_evidence(conn, first)[0]['identity_breaks'] == [br]

    prices.window = CurrentFormationWindow.through(NEXT)
    second = publish()
    next_source, next_reference = _source_evidence(conn, second)
    assert next_source['identity_breaks'] == source['identity_breaks']
    admitted = [row for row in next_reference['tickers'] if row['ticker'] == ticker]
    assert len(admitted) == 1
    assert admitted[0]['permaticker'] == NEW
    assert admitted[0]['firstpricedate'] == NEXT
    rows = _bar_rows(conn, second, ticker)
    assert [(str(day), sid) for day, sid, *_ in rows] == [(NEXT, NEW)]
    assert rows[0][2] > 0 and rows[0][3] > 0
    assert not any(row.get('ticker') == ticker for row in next_reference['actions'])
    assert next_source['selected_count'] == 25
    assert next_source['admitted_count'] == 25
    assert rolling_store.manifest(conn, second['candidate_id']).window.end.isoformat() == NEXT


def test_two_quarantined_uuid_breaks_still_count_against_population_denominator(
        conn, provider, synthetic_feed_authority):
    prices, publish = provider
    origin = publish()
    prices.window = CurrentFormationWindow.through(DAY)
    original_get, original_pages = prices.get, prices.pages

    def get(endpoint, params):
        assert endpoint == ASSETS
        rows, proof = original_get(endpoint, params)
        return [({**row, 'id': NEW + '-' + row['symbol']}
                 if row['symbol'] in ('T00', 'T01') else row)
                for row in rows], proof

    def pages(endpoint, params, *, key):
        if endpoint == ACTION_URL:
            yield {'reverse_splits': []}, {'observed_at': DAY + 'T23:00:00+00:00'}
        else:
            yield from original_pages(endpoint, params, key=key)

    prices.get, prices.pages = get, pages
    with pytest.raises(ValueError, match='below 95% of selected candidates'):
        publish()
    from sentinel.feed import operational_snapshot
    assert operational_snapshot._current(conn).version == origin['data_version']


def test_selected_witness_with_unresolved_uuid_break_preserves_checkpoint(
        conn, provider, synthetic_feed_authority):
    from sentinel import rolling_daily, rolling_daily_checkpoint, rolling_initialization
    from sentinel.core.session import _path_dependent_security_ids
    from sentinel.core.window_continuity import MergerActionPending

    prices, publish = provider
    publish()
    before = rolling_initialization.initialize(conn, observation_id=OBS,
                                                 starting_cash=50_000)
    protected = _path_dependent_security_ids(before.state.wealth_core,
                                             before.state.pending)
    sid = next(sid for sid in before.state.median5['selected'] if sid not in protected)
    assert sid not in protected
    ticker = before.state.feed['series'][sid]['ticker']
    prices.window = CurrentFormationWindow.through(DAY)
    _replace_provider(prices, ticker, sid)
    publish()
    with pytest.raises(MergerActionPending) as caught:
        rolling_daily.advance(conn, observation_id=OBS, starting_cash=50_000)
    assert str(caught.value) == 'SELECTED_IDENTITY_ACTION_PENDING:' + DAY + ':' + sid
    conn.rollback()
    _, _, restored = rolling_daily_checkpoint.load(
        conn, rolling_initialization._context(OBS, 50_000))
    assert restored.state.state_hash == before.state.state_hash
    for table in ('sentinel_execution_plans', 'sentinel_commands', 'sentinel_fills'):
        assert conn.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0


def test_identity_break_source_validation_rejects_tampered_split_and_collision():
    from sentinel.feed import alpaca_source

    row = action_source([split()])._action_rows()[0]['identity_breaks'][0]
    source = {'schema': alpaca_source.SOURCE,
              'provider': 'ALPACA_OPENFIGI',
              'identity_break_policy': alpaca_source.IDENTITY_BREAK_POLICY,
              'identity_breaks': [row]}
    assert len(alpaca_source.source_breaks(source)) == 1
    tampered = deepcopy(source)
    tampered['identity_breaks'][0]['split']['raw_record']['new_rate'] = 2
    with pytest.raises((AlpacaTransportRefused, ValueError)):
        alpaca_source.source_breaks(tampered)
    collision = deepcopy(source)
    collision['identity_breaks'].append(deepcopy(row))
    with pytest.raises((AlpacaTransportRefused, ValueError)):
        alpaca_source.source_breaks(collision)


def test_reference_cannot_reintroduce_new_uuid_on_or_before_break_floor():
    row = action_source([split()])._action_rows()[0]['identity_breaks'][0]
    source = object.__new__(AlpacaSource)
    source.identity_breaks = [row]
    source.window = PriceWindow.through(DAY)
    source.tickers = [dict(ticker='AAA', permaticker=NEW, firstpricedate=DAY)]
    source.dividend_totals = lambda _admitted: {}
    source.splits = []
    source.identity_bindings = []
    source.merger_conversions = []
    source.dividends = []
    source.pending_cash = []
    with pytest.raises(AlpacaTransportRefused, match='identity-break reference crossed price floor'):
        source.reference_payload()
    source.tickers[0]['firstpricedate'] = NEXT
    source.tickers[0]['permaticker'] = OLD
    with pytest.raises(AlpacaTransportRefused, match='identity-break reference crossed price floor'):
        source.reference_payload()


def test_same_session_tip_carries_proved_split_when_reobservation_omits_it():
    from tests.sentinel.test_alpaca_merger_source import merger

    proved = action_source([split()])._action_rows()[0]['identity_breaks'][0]
    prior = previous() | {'previous_selected': [
        dict(ticker='AAA', asset_id=OLD),
        dict(ticker='BBB', asset_id='old-bbb'),
        dict(ticker='CCC', asset_id='ccc-id')]}
    source = action_source([], prior=prior)
    source.selected = [dict(ticker='AAA', asset_id=NEW),
                       dict(ticker='CCC', asset_id='ccc-id')]
    source.same_session_breaks = [proved]
    source.same_session_conversions = []
    other_action = merger('BBB', 'CCC', id='other-merger')

    class Pages:
        def pages(self, endpoint, params, *, key):
            assert endpoint == ACTION_URL
            yield {'stock_mergers': [other_action]}, {
                'observed_at': DAY + 'T23:00:00+00:00'}

    source.client = Pages()
    result, *_ = source._action_rows()
    assert result['identity_breaks'] == [proved]
    assert [(row['old_symbol'], row['successor_symbol'])
            for row in result['merger_conversions']] == [('BBB', 'CCC')]

    # A later provider omission may not clear the old proof, but a different
    # observed record cannot silently replace its signed terms.
    changed = action_source([split(new_rate=2)], prior=prior)
    changed.same_session_breaks = [proved]
    changed.selected = list(source.selected)
    with pytest.raises(AlpacaTransportRefused, match='identity-break|split'):
        changed._action_rows()
    shifted = action_source([split() | {'ex_date': NEXT}], prior=prior)
    shifted.same_session_breaks = [proved]
    shifted.selected = list(source.selected)
    with pytest.raises(AlpacaTransportRefused, match='published identity-break split changed'):
        shifted._action_rows()


def test_weekend_month_end_does_not_request_prices_with_inverted_bounds():
    source = object.__new__(AlpacaSource)
    source.window = PriceWindow.through('2026-06-02')
    source.months = [('2026-05-01', '2026-05-31'),
                     ('2026-06-01', '2026-06-02')]
    source.selected = [dict(ticker='AAA', asset_id=NEW),
                       dict(ticker='BBB', asset_id='other')]
    source.action_affected = frozenset()
    source.reset_after = {'AAA': '2026-05-29'}  # Friday, then Sunday month end.
    source.splits = []
    source.identity_bindings = []
    source.merger_conversions = []
    source.identity_breaks = []
    source.pair_absent = set()
    source.lease = SimpleNamespace(job_id='test-month-boundary')
    calls = []

    def bars(symbols, first, last, adjustment):
        assert first <= last
        calls.append((frozenset(symbols), first, last, adjustment))
        return {symbol: [] for symbol in symbols}, []

    source._bars = bars
    source._part = lambda _component, _generation, acquire, _checkpoint: acquire()[0]
    source._acquire_prices(lambda *_a: None, lambda: None)
    assert all('AAA' not in symbols for symbols, _first, last, _adjustment in calls
               if last == '2026-05-31')
    assert any('AAA' in symbols and first == '2026-06-01'
               for symbols, first, _last, _adjustment in calls)


def test_same_session_correction_uses_retained_predecessor_without_retired_older_payload(
        monkeypatch):
    from sentinel.feed import operational_snapshot, publication, rolling_store
    from sentinel.feed.rolling_store import SnapshotStorageRefused

    target = '2026-11-23'
    previous_day = '2026-11-20'
    queries = []
    loaded = []
    validated = []

    class Row:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

    def publication_row(version, day):
        return (version, version - 1, None, '2025-09-15', day,
                {'rolling_snapshot': {'candidate_id': 'v' + str(version)}})

    class Conn:
        def execute(self, sql, params):
            queries.append((sql, params))
            if 'window_end <= %s' in sql:
                assert params == (target,)
                return Row(publication_row(27, target))
            if 'window_end < %s' in sql and params == (target,):
                return Row(publication_row(26, previous_day))
            if 'window_end < %s' in sql and params == (previous_day,):
                return Row(publication_row(25, '2026-11-19'))
            raise AssertionError((sql, params))

    references = {
        'r27': {'schema': 'sentinel.rolling-alpaca-openfigi-references/3',
                'identity_bindings': [], 'tickers': [
                    {'table': 'SEP', 'ticker': 'AAA', 'permaticker': NEW}]},
        'r26': {'schema': 'sentinel.rolling-alpaca-openfigi-references/3',
                'identity_bindings': [], 'tickers': [
                    {'table': 'SEP', 'ticker': 'AAA', 'permaticker': OLD}]},
        's26': {'schema': 'sentinel.alpaca-openfigi-operational-source/3',
                'provider': 'ALPACA_OPENFIGI',
                'identity_bindings_sha256': digest([])},
    }

    monkeypatch.setattr(publication, '_validate_publication',
                        lambda _conn, pub, **_kw: validated.append(pub.version))
    monkeypatch.setattr(operational_snapshot, '_bound',
                        lambda _conn, pub: {'candidate_id': pub.evidence['rolling_snapshot']['candidate_id']})
    monkeypatch.setattr(rolling_store, 'manifest', lambda _conn, cid: SimpleNamespace(
        provider='ALPACA_OPENFIGI', reference_sha256='r' + cid[-2:],
        source_evidence_sha256='s' + cid[-2:], snapshot_id=digest(cid)))

    def load(_conn, key):
        loaded.append(key)
        if key not in references:
            raise SnapshotStorageRefused('retired predecessor evidence: ' + key)
        return references[key]

    monkeypatch.setattr(rolling_store, 'load_evidence', load)
    source = object.__new__(AlpacaSource)
    source.conn = Conn()
    source.window = PriceWindow.through(target)
    source.previous_identity = None
    result = source._previous_identity()
    assert result['previous_session'] == previous_day
    assert result['previous_selected'] == [{'ticker': 'AAA', 'asset_id': OLD}]
    assert validated == [27, 26]
    assert loaded == ['r27', 'r26', 's26']
    assert len(queries) == 2


def test_legacy_same_symbol_uuid_splice_cannot_be_used_as_next_day_predecessor(
        monkeypatch):
    from sentinel.feed import alpaca_source, operational_snapshot, publication, rolling_store

    class Row:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

    class Conn:
        def execute(self, sql, params):
            if 'window_end < %s' in sql:
                return Row((26, 25, None, '2025-09-15', '2026-11-20',
                            {'rolling_snapshot': {'candidate_id': 'v26'}}))
            return Row((27, 26, None, '2025-09-16', '2026-11-23',
                        {'rolling_snapshot': {'candidate_id': 'v27'}}))

    refs = {
        'r26': {'schema': 'sentinel.rolling-alpaca-openfigi-references/3',
                'identity_bindings': [], 'tickers': [
                    {'table': 'SEP', 'ticker': 'AAA', 'permaticker': OLD}]},
        'r27': {'schema': 'sentinel.rolling-alpaca-openfigi-references/3',
                'identity_bindings': [], 'tickers': [
                    {'table': 'SEP', 'ticker': 'AAA', 'permaticker': NEW}]},
    }
    sources = {
        's26': {'schema': 'sentinel.alpaca-openfigi-operational-source/3',
                'provider': 'ALPACA_OPENFIGI',
                'identity_bindings_sha256': digest([])},
        's27': {'schema': 'sentinel.alpaca-openfigi-operational-source/3',
                'provider': 'ALPACA_OPENFIGI',
                'identity_bindings_sha256': digest([])},
    }
    monkeypatch.setattr(publication, '_validate_publication', lambda *_a, **_k: None)
    monkeypatch.setattr(operational_snapshot, '_bound',
                        lambda _conn, pub: {'candidate_id': pub.evidence['rolling_snapshot']['candidate_id']})
    monkeypatch.setattr(rolling_store, 'manifest', lambda _conn, cid: SimpleNamespace(
        provider='ALPACA_OPENFIGI', reference_sha256='r' + cid[-2:],
        source_evidence_sha256='s' + cid[-2:], snapshot_id=digest(cid)))
    monkeypatch.setattr(rolling_store, 'load_evidence',
                        lambda _conn, key: (refs | sources)[key])

    source = object.__new__(AlpacaSource)
    source.conn = Conn()
    source.window = PriceWindow.through('2026-11-24')
    source.previous_identity = None
    with pytest.raises(AlpacaSourcePending, match='ALPACA_IDENTITY_ACTION_PENDING:AAA'):
        source._previous_identity()

    # A corrected /4 tip excludes the unproven old history and carries its
    # authenticated break; it can be used as the next-day source predecessor.
    proved = action_source([split()])._action_rows()[0]['identity_breaks'][0]
    refs['r27'] = {'schema': alpaca_source.REFERENCE,
                   'identity_bindings': [], 'merger_conversions': [],
                   'tickers': [{'table': 'SEP', 'ticker': 'BBB',
                                'permaticker': 'unrelated-bbb'}]}
    sources['s27'] = {'schema': alpaca_source.SOURCE,
                      'provider': 'ALPACA_OPENFIGI',
                      'identity_bindings_sha256': digest([]),
                      'merger_conversions_sha256': digest([]),
                      'identity_break_policy': alpaca_source.IDENTITY_BREAK_POLICY,
                      'identity_breaks': [proved]}
    source.previous_identity = None
    result = source._previous_identity()
    assert result['identity_breaks'] == [proved]
    assert result['previous_selected'] == [
        dict(ticker='BBB', asset_id='unrelated-bbb')]
