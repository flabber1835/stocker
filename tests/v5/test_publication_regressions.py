"""Production publication and real-adapter falsifiers from review 5162301745."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import json
from types import SimpleNamespace

import httpx
import pytest

from sentinel.core.kernel import advance_session
from sentinel.core.session import PublishedSession, SessionState, _feed_to_dict
from sentinel.execution.alpaca import AlpacaExecutionBroker
from sentinel.execution import opening_sizing
from sentinel.execution.opening_prices import ENDPOINT, OpeningPrices, OpeningPriceUnavailable
from sentinel.feed import calendar, universe
from sentinel.paper.inspection import build_security_resolver
from sentinel.strategy import production_strategy
from stock_strategy_shared.wealth_core import median5
from stock_strategy_shared.wealth_core.feed import Feed, FeedError, SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from tests.v5.test_opening import case, base
from tests.v5.test_v5 import canonical


def prior_book():
    env = canonical()
    axis = calendar.previous_sessions('2026-08-12', 142)
    meta = {'A': SecurityMeta('A', 'A', 'Domestic Common Stock', 'A', first_session=axis[0])}
    feed = Feed(meta)
    feed.restart_sessions = 260
    feed.median5_state = median5.fresh()
    for day in axis[:-1]:
        feed.advance(day, [VendorBar(day, 'A', 'A', 100., 100., 1e6, signal_close=100.)])
    book = PortfolioState.from_dict(env.wealth_core)
    book.median5 = feed.median5_state
    book.cash = 99000.
    book.episodes[0] = HoldingEpisode('A', 'A', 'SID:A', 0, axis[-43], axis[-42],
        100., 100., 10., 10., episode_peak_split_adjusted_close=100., market_sessions_held=40)
    book.slots[0].occupied_by = 'A'
    env.wealth_core = book.to_dict()
    env.feed = _feed_to_dict(feed, {'A'})
    env.last_known = {'A': 100.}
    env.data_version = 1
    env.last_processed_session = axis[-2]
    env.shadow_nav_history = [100000.]*41
    env.shadow_peak_nav = 100000.
    env.median5.update(selected=['A'], selected_closes={'A': 100.},
                       witness_nav=[1.]*41, last_session=axis[-2])
    tail = axis[-41:]
    published = PublishedSession(axis[-1], 2,
        [VendorBar(axis[-1], 'A', 'A', 50., 50., 2e6, split_ratio=2., signal_close=50.)],
        meta, {}, [100.]*41, spy_sessions=tail, spy_expected_sessions=tail,
        signal_basis_anchors={'A': VendorBar(axis[-2], 'A', 'A', 100., None, None, signal_close=50.)})
    return SessionState.from_dict(json.loads(json.dumps(env.to_dict()))), published


def step(env, published):
    config, identity = production_strategy()
    return advance_session(env, published, controller_config=config, strategy_identity=identity)


@pytest.mark.parametrize('split', [2., .5, 5.])
def test_daily_publication_split_preserves_book_features_and_witness_after_restart(split):
    prior, pub = prior_book()
    pub = replace(pub, bars=[replace(pub.bars[0], raw_close=100/split,
        raw_open=100/split, signal_close=100/split, split_ratio=split)],
        signal_basis_anchors={'A': replace(pub.signal_basis_anchors['A'], signal_close=100/split)})
    original = prior.to_dict()
    expected = step(prior, replace(pub, data_version=1,
                                  bars=[replace(pub.bars[0], signal_close=100.)]))
    actual = step(prior, pub)
    assert prior.to_dict() == original
    assert actual.wealth_core == expected.wealth_core
    assert actual.pending == expected.pending == []
    assert actual.median5 == expected.median5
    assert actual.last_decision == expected.last_decision
    assert actual.last_evidence['recent_leadership'] == {'recent_r20': 0., 'recent_r40': 0.}
    assert actual.shadow_nav_history[-1] == 100000.
    assert actual.feed['series']['A']['signal_closes'][-1] == 100.
    assert actual.wealth_core['episodes']['0']['current_shares'] == 10*split
    restored = SessionState.from_dict(json.loads(json.dumps(actual.to_dict())))
    day = calendar.next_session(pub.session)
    second = replace(pub, session=day, bars=[replace(pub.bars[0], session=day,
        raw_close=102/split, raw_open=100/split, signal_close=102/split, split_ratio=1.)],
        spy_sessions=tuple(pub.spy_sessions[1:])+(day,),
        spy_expected_sessions=tuple(pub.spy_expected_sessions[1:])+(day,))
    after = step(restored, second)
    assert after.feed['series']['A']['signal_closes'][-1] == 102.
    assert after.wealth_core['episodes']['0']['episode_peak_split_adjusted_close'] == 102.


def test_repeated_publications_compose_source_bridges_and_preserve_real_stop():
    prior, pub = prior_book()
    actual = step(prior, pub)
    day = calendar.next_session(pub.session)
    pub = replace(pub, session=day, data_version=3,
        bars=[replace(pub.bars[0], session=day, raw_close=10., raw_open=25.,
                      signal_close=10., split_ratio=2.)],
        signal_basis_anchors={'A': replace(pub.signal_basis_anchors['A'], session=actual.last_processed_session,
                                          raw_close=50., signal_close=25.)},
        spy_sessions=tuple(pub.spy_sessions[1:])+(day,),
        spy_expected_sessions=tuple(pub.spy_expected_sessions[1:])+(day,))
    result = step(SessionState.from_dict(json.loads(json.dumps(actual.to_dict()))), pub)
    assert result.feed['series']['A']['signal_basis_multiplier'] == 4.
    assert result.feed['series']['A']['signal_closes'][-1] == 40.
    assert result.pending[0]['reason'] == 'EXIT_TRAILING_STOP'
    assert result.pending[0]['shares'] == 40.


@pytest.mark.parametrize('fault', ['missing', 'security', 'session', 'raw_revision', 'zero', 'nan'])
def test_publication_anchor_is_required_and_identity_bound(fault):
    prior, pub = prior_book()
    anchor = pub.signal_basis_anchors['A']
    changes = {'security': {'security_id': 'OTHER'}, 'session': {'session': '2000-01-01'},
               'raw_revision': {'raw_close': 99.}, 'zero': {'signal_close': 0.},
               'nan': {'signal_close': float('nan')}}
    pub = replace(pub, signal_basis_anchors={} if fault == 'missing' else {'A': replace(anchor, **changes[fault])})
    original = prior.to_dict()
    with pytest.raises(FeedError, match='publication signal anchor'):
        step(prior, pub)
    assert prior.to_dict() == original


def test_signal_anchor_survives_protected_history_eviction():
    from sentinel.core.session import _feed_from_dict
    from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
    prior, pub = prior_book()
    feed = _feed_from_dict(prior.feed, pub.meta, EligibilityConfig())
    feed._session_index += 261
    compact = _feed_to_dict(feed, {'A'})
    assert compact['series']['A']['signal_closes'] == []
    restored = _feed_from_dict(json.loads(json.dumps(compact)), pub.meta, EligibilityConfig())
    restored.series['A'].reconcile_signal_basis(pub.signal_basis_anchors['A'])
    assert restored.series['A'].signal_basis_multiplier == 2.


class MetadataConnection:
    """Execute the actual loader's SQL in an in-memory relational engine."""
    def __init__(self, rows):
        import sqlite3
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE feed_universe_current (permaticker TEXT, ticker TEXT, '
            'first_price_date TEXT, last_price_date TEXT, is_delisted BOOLEAN, '
            'is_delisted_snapshot_date TEXT, snapshot_date TEXT)')
        self.db.executemany('INSERT INTO feed_universe_current VALUES (?,?,?,?,?,?,?)', rows)
    def cursor(self):
        conn = self
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def execute(self, sql, params=()):
                self.result = conn.db.execute(sql.replace('%s::date', '?').replace('%s', '?'), params)
            def fetchall(self): return self.result.fetchall()
        return Cursor()


def metadata_row(sid, ticker, last='2026-08-11', active=False, observed='2026-08-11'):
    return (sid, ticker, '2000-01-01', last, active, observed, observed)


@pytest.mark.parametrize('sale', [False, True])
def test_normal_metadata_allows_next_open_and_pending_sale_funding(monkeypatch, sale):
    env, plan = case(cash=100. if sale else 100000., sale=sale)
    rows = [metadata_row('SEC-AAA', 'AAA')]
    if sale: rows.append(metadata_row('SEC-X', 'X'))
    conn = MetadataConnection(rows)
    resolver = build_security_resolver(conn, plan.effective_session.isoformat())
    assert resolver('AAA') == 'SEC-AAA'
    assert resolver('AAA', '2026-08-13') is None
    assert universe.load_resolver(conn).resolve('AAA', '2026-08-12') is None
    monkeypatch.setattr(opening_sizing, 'load_projection', lambda *a, **k: None)
    opened, _ = calendar.session_window(plan.effective_session)
    requests = []
    def transport(request):
        requests.append(request)
        if '/assets/' in request.url.path:
            symbol = request.url.path.rsplit('/', 1)[-1]
            return httpx.Response(200, json={'symbol': symbol, 'id': 'asset-'+symbol,
                                            'status': 'active', 'tradable': True})
        symbols = request.url.params['symbols'].split(',')
        return httpx.Response(200, json={'bars': {s: [{'t': opened.isoformat(), 'o': 100, 'v': 10}]
                                                        for s in symbols}, 'next_page_token': None})
    provider = lambda: SimpleNamespace(AsyncClient=lambda **k: httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    broker = AlpacaExecutionBroker(api_key='test', secret_key='test', base_url='https://paper-api.alpaca.markets',
        resolve_security_id=resolver, http_provider=provider, clock_provider=lambda: opened+timedelta(minutes=1))
    evidence = asyncio.run(opening_sizing.prices_for_plan(conn, state=env, plan=plan, broker=broker))
    result = opening_sizing.resolve(env, plan, base(env, plan), evidence)
    assert result.target_basket['SEC-AAA'] == (10 if sale else 49)
    if sale: assert D(result.opening_sizing['sales'][0]['proceeds']) == 999
    assert requests


@pytest.mark.parametrize('fault', ['delisted', 'unknown', 'stale', 'future', 'stale_active', 'reuse', 'ambiguous'])
def test_forward_execution_identity_requires_fresh_active_unique_authority(fault):
    rows = [list(metadata_row('SEC-AAA', 'AAA'))]
    if fault == 'delisted': rows[0][4] = True
    elif fault == 'unknown': rows[0][4] = None
    elif fault == 'stale': rows[0][3] = '2026-08-10'
    elif fault == 'future': rows[0][5] = rows[0][6] = '2026-08-13'
    elif fault == 'stale_active': rows[0][5] = '2026-08-10'
    elif fault == 'reuse': rows.append(metadata_row('OTHER', 'AAA'))
    elif fault == 'ambiguous': rows.append(metadata_row('SEC-AAA', 'OTHER'))
    resolver = universe.load_resolver(MetadataConnection(rows), execution_session='2026-08-12')
    assert resolver.ticker_for_security('SEC-AAA', '2026-08-12') is None


@pytest.mark.parametrize('custom', [False, True])
def test_actual_alpaca_class_share_request_and_response_conversion(custom):
    session = calendar.next_session('2026-08-11')
    from datetime import date
    session = date.fromisoformat(session)
    opened, _ = calendar.session_window(session)
    mapping = {'BRK-B': 'BRK/B' if custom else 'BRK.B', 'AAA': 'AAA'}
    requests = []
    def transport(request):
        requests.append(request)
        if '/assets/' in request.url.path:
            symbol = request.url.path.removeprefix('/v2/assets/')
            assert symbol in mapping.values()
            return httpx.Response(200, json={'symbol': symbol, 'id': 'asset-'+symbol,
                                            'status': 'active', 'tradable': True})
        assert str(request.url).startswith(ENDPOINT)
        assert set(request.url.params['symbols'].split(',')) == set(mapping.values())
        return httpx.Response(200, json={'bars': {s: [{'t': opened.isoformat(), 'o': 500.125, 'v': 30}]
                                                for s in mapping.values()}, 'next_page_token': None})
    provider = lambda: SimpleNamespace(AsyncClient=lambda **k: httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    broker = AlpacaExecutionBroker(api_key='test', secret_key='test', base_url='https://paper-api.alpaca.markets',
        http_provider=provider, clock_provider=lambda: opened+timedelta(minutes=1),
        resolve_security_id=lambda symbol: 'SEC-'+symbol,
        **({'to_broker_symbol': mapping.__getitem__,
            'from_broker_symbol': {v:k for k,v in mapping.items()}.__getitem__} if custom else {}))
    async def run():
        instruments = {('SEC-'+symbol): await broker.resolve_instrument(security_id='SEC-'+symbol, symbol=symbol)
                       for symbol in mapping}
        return await broker.opening_prices(session=session, instruments=instruments)
    result = asyncio.run(run())
    assert dict(result.symbols) == {'SEC-BRK-B': 'BRK-B', 'SEC-AAA': 'AAA'}
    assert result.prices['SEC-BRK-B'] == D('500.125')
    assert OpeningPrices.from_dict(json.loads(json.dumps(result.to_dict()))) == result
    assert len(requests) == 3


def test_declared_rename_wins_over_predecessor_forward_extension():
    rows = [metadata_row('SEC-AAA', 'OLD'),
            ('SEC-AAA', 'NEW', '2026-08-12', '2026-08-12', False, '2026-08-12', '2026-08-12')]
    conn = MetadataConnection(rows)
    resolver = universe.load_resolver(conn, execution_session='2026-08-12')
    assert resolver.ticker_for_security('SEC-AAA', '2026-08-12') == 'NEW'
    assert resolver.resolve('OLD', '2026-08-12') is None
    assert build_security_resolver(conn, '2026-08-12')('OLD', '2026-08-11') == 'SEC-AAA'


@pytest.mark.parametrize('fault', ['signal', 'raw', 'session', 'missing'])
def test_restart_validates_signal_anchor_against_retained_history(fault):
    prior, _ = prior_book()
    raw = prior.to_dict()
    series = raw['feed']['series']['A']
    if fault == 'missing':
        del series['signal_basis_anchor']
        series['signal_basis_multiplier'] = 2.
    else:
        series['signal_basis_anchor'][{'session': 0, 'raw': 1, 'signal': 2}[fault]] = (
            '2000-01-01' if fault == 'session' else 99.)
    with pytest.raises(ValueError, match='signal (anchor|basis)'):
        SessionState.from_dict(raw)


def test_changing_publications_preserve_nonflat_mixed_precision_features():
    """Independent fixed-publication stream agrees across rebases and restarts."""
    import math
    from sentinel.core.session import _feed_from_dict
    from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
    meta = {'A': SecurityMeta('A', 'A', 'Domestic Common Stock', 'A', first_session='0000')}
    feeds = [Feed(meta), Feed(meta)]
    for feed in feeds:
        feed.median5_state = median5.fresh()
        feed.restart_sessions = 260
    scale = 1.
    previous = None
    for index in range(310):
        day = f'{index:04}'
        signal = 100.*math.exp(.001*index+.04*math.sin(index*.4))
        split = 2. if index in (149, 209) else .5 if index == 270 else 1.
        scale *= split
        if previous is not None:
            feeds[1].series['A'].reconcile_signal_basis(
                replace(previous, signal_close=previous.signal_close/scale))
        bar = VendorBar(day, 'A', 'A', signal/scale, signal/scale, 1e6*scale,
                        split_ratio=split, signal_close=signal)
        reference = feeds[0].advance(day, [bar])
        changed = feeds[1].advance(day, [replace(bar, signal_close=signal/scale)])
        assert changed.security_bars == reference.security_bars
        assert feeds[1].median5_state == feeds[0].median5_state
        assert feeds[1].series['A'].signal_closes == feeds[0].series['A'].signal_closes
        previous = bar
        if index in (170, 220, 280):
            features = json.loads(json.dumps(feeds[1].median5_state))
            feeds[1] = _feed_from_dict(json.loads(json.dumps(_feed_to_dict(feeds[1], set()))),
                                      meta, EligibilityConfig())
            feeds[1].median5_state = features
            # Match only the bounded stored window after the restart.
            features = deepcopy(feeds[0].median5_state)
            feeds[0] = _feed_from_dict(_feed_to_dict(feeds[0], set()), meta, EligibilityConfig())
            feeds[0].median5_state = features
