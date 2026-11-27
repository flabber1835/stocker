"""Canonical book and controller continuity across source-proven Alpaca mergers."""
from copy import deepcopy
from datetime import date
from fractions import Fraction
from types import SimpleNamespace

import pytest

from sentinel.controller import median5, terminal_returns
from sentinel.core import rolling_continuity, window_continuity, window_material
from sentinel.feed import calendar, rolling_store
from stock_strategy_shared.wealth_core.feed import Feed, SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.live import plan_session
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState


CURSOR = '2026-11-20'
SESSION = '2026-11-23'
OLD = 'old-provider-identity'
NEW = 'successor-identity'
SNAPSHOT = 'a' * 64


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def execute(self, query, args):
        self.queries.append((query, args))
        return _Result(self.rows)


def _case(*, held=False, anchor=None, source_row=None):
    conversion = SimpleNamespace(
        old_security_id=OLD, old_provider_asset_id=OLD,
        successor_security_id=NEW, successor_provider_asset_id='new-provider-uuid',
        old_symbol='AAA', successor_symbol='BBB', effective_session=SESSION,
        origin_snapshot_id=SNAPSHOT, exchange_ratio='1.5',
        record_id='merger-action', terms_sha256='b' * 64)
    previous = SimpleNamespace(
        candidate_id='previous-candidate',
        manifest=SimpleNamespace(provider='ALPACA_OPENFIGI',
            window=SimpleNamespace(end=CURSOR), snapshot_id=SNAPSHOT),
        resolver=SimpleNamespace(resolve=lambda symbol, day: OLD if (symbol, day) == ('AAA', CURSOR) else None))
    current = SimpleNamespace(
        merger_conversions=(conversion,),
        resolver=SimpleNamespace(resolve=lambda symbol, day: NEW if (symbol, day) == ('BBB', SESSION) else None))
    prior = SimpleNamespace(
        last_processed_session=CURSOR,
        median5={'selected': [OLD], 'selected_closes': {OLD: 100.}},
        wealth_core={'episodes': {'episode': {'security_id': OLD, 'current_shares': 2}}} if held else {},
        pending=[],
        feed={'series': {OLD: {'signal_basis_anchor': anchor or [CURSOR, 50., 100.],
                              'signal_basis_multiplier': 2.}}})
    conn = _Connection([source_row or (CURSOR, OLD, 'AAA', 50., 50., 50., 1000., 1., 0.)])
    return conn, prior, previous, current, conversion


def _bound_source(monkeypatch, previous, current, *, old_provider=OLD,
                  successor_admitted=True):
    monkeypatch.setattr(rolling_store, 'verify_content', lambda *_args: None)
    monkeypatch.setattr(window_continuity, 'candidate_query', lambda _conn, sql: sql)
    monkeypatch.setattr(window_continuity, '_provider_assets',
        lambda _conn, refs: {'AAA': old_provider} if refs is previous else
        {'BBB': 'new-provider-uuid'} if successor_admitted else {})


@pytest.mark.parametrize('current_symbol', [None, 'AAA'])
@pytest.mark.parametrize('dependent', ['selected', 'held', 'pending', 'reserved'])
def test_identity_discontinuity_waits_for_new_action(current_symbol, dependent):
    prior = SimpleNamespace(median5={'selected': [OLD]}, wealth_core={}, pending=[])
    if dependent != 'selected':
        prior.median5['selected'] = []
    if dependent == 'held':
        prior.wealth_core['episodes'] = {'1': {'security_id': OLD}}
    if dependent == 'pending':
        prior.pending = [{'security_id': OLD}]
    if dependent == 'reserved':
        prior.wealth_core['slots'] = {'1': {'reserved_for': OLD}}
    previous = SimpleNamespace(manifest=SimpleNamespace(provider='ALPACA_OPENFIGI'),
        resolver=SimpleNamespace(
            ticker_for_security=lambda sid, day: 'AAA' if (sid, day) == (OLD, CURSOR) else None,
            resolve=lambda symbol, day: OLD if (symbol, day) == ('AAA', CURSOR) else None))
    current = SimpleNamespace(manifest=SimpleNamespace(provider='ALPACA_OPENFIGI'),
        merger_conversions=(), resolver=SimpleNamespace(
            ticker_for_security=lambda _sid, _day: None,
            resolve=lambda symbol, day: NEW if (symbol, day) == (current_symbol, SESSION) else None))
    retained = deepcopy(prior.__dict__)
    reason = 'SELECTED' if dependent == 'selected' else 'HELD'
    with pytest.raises(window_continuity.MergerActionPending,
                       match=reason + '_IDENTITY_ACTION_PENDING:' + SESSION + ':' + OLD):
        window_continuity._pending_merger_action(
            prior=prior, previous=previous, current=current, cursor=CURSOR, session=SESSION)
    assert prior.__dict__ == retained


def test_complete_conversion_or_source_proven_rename_resolves_action_wait():
    prior = SimpleNamespace(median5={'selected': [OLD]}, wealth_core={}, pending=[])
    previous = SimpleNamespace(manifest=SimpleNamespace(provider='ALPACA_OPENFIGI'),
        resolver=SimpleNamespace(ticker_for_security=lambda *_: 'AAA',
                                 resolve=lambda *_: OLD))
    current = SimpleNamespace(manifest=SimpleNamespace(provider='ALPACA_OPENFIGI'),
        merger_conversions=(SimpleNamespace(old_security_id=OLD),),
        resolver=SimpleNamespace(ticker_for_security=lambda *_: None,
                                 resolve=lambda *_: None))
    window_continuity._pending_merger_action(
        prior=prior, previous=previous, current=current, cursor=CURSOR, session=SESSION)


def test_selected_action_wait_precedes_price_read_and_book_transition(monkeypatch):
    _conn, prior, previous, current, _ = _case()
    previous.current_window = current.current_window = True
    current.candidate_id = 'current'
    previous.resolver.ticker_for_security = lambda *_: 'AAA'
    current.manifest = SimpleNamespace(provider='ALPACA_OPENFIGI',
        window=SimpleNamespace(end=SESSION), snapshot_id='c' * 64)
    current.merger_conversions = ()
    current.resolver.ticker_for_security = lambda *_: None
    monkeypatch.setattr(window_continuity, 'SnapshotReferences',
        lambda _conn, candidate_id, snapshot_id: previous if candidate_id == 'previous' else current)
    monkeypatch.setattr(window_continuity.rolling_store, 'verify_content', lambda *_: None)
    monkeypatch.setattr(window_continuity.window_features, 'protected', lambda _prior: {OLD})

    class NoPriceRead:
        def __init__(self, *_a, **_k):
            pass

        def require_checkpoint_window(self, _prior):
            pass

        def prices(self, **_kwargs):
            pytest.fail('price read happened before selected identity action wait')

    monkeypatch.setattr(window_continuity, 'RollingPriceReader', NoPriceRead)
    retained = deepcopy(prior.__dict__)
    with pytest.raises(window_continuity.MergerActionPending,
                       match='SELECTED_IDENTITY_ACTION_PENDING'):
        window_continuity.prepare(_conn, prior=prior,
            previous_binding={'candidate_id': 'previous', 'snapshot_id': SNAPSHOT},
            publication=SimpleNamespace(window_end=SESSION),
            binding={'candidate_id': 'current', 'snapshot_id': 'c' * 64})
    assert prior.__dict__ == retained
    current.merger_conversions = ()
    current.resolver.ticker_for_security = lambda *_: 'BBB'
    current.resolver.resolve = lambda symbol, day: OLD if (symbol, day) == ('BBB', SESSION) else None
    window_continuity._pending_merger_action(
        prior=prior, previous=previous, current=current, cursor=CURSOR, session=SESSION)


def test_selected_only_merger_uses_prior_published_anchor_and_fractional_return(monkeypatch):
    conn, prior, previous, current, _ = _case()
    _bound_source(monkeypatch, previous, current)
    bridges, conversions = window_continuity._merger_bridges(
        conn, prior=prior, previous=previous, current=current, cursor=CURSOR, session=SESSION)
    assert set(bridges) == {OLD}
    assert bridges[OLD].session == date.fromisoformat(CURSOR) and bridges[OLD].close_unadjusted == 50.
    assert bridges[OLD].close_signal == 50.
    assert conn.queries[0][1] == ('previous-candidate', OLD, CURSOR)
    prices = SimpleNamespace(bars=(VendorBar(SESSION, NEW, 'BBB', 40., 40., 1000.,
                                             signal_close=40.),))
    meta = {NEW: SecurityMeta(NEW, 'BBB', permaticker=NEW)}
    events = window_continuity._merger_terminals(
        conversions=conversions, prices=prices, metadata=meta, session=SESSION)
    assert len(events) == 1 and events[0].security_id == OLD
    assert events[0].delivered_security_id == NEW and events[0].exchange_ratio == '1.5'
    values = terminal_returns.values(prior=prior, published=SimpleNamespace(
        session=SESSION, bars=prices.bars, terminal_events=events))
    assert values == {OLD: 120.}
    state = {'last_session': CURSOR, 'selected': [OLD],
             'selected_closes': {OLD: 100.}, 'witness_nav': [1.]}
    after, _ = median5.witness(state, session=SESSION, candidates=(), closes={},
                               terminals={OLD}, terminal_values=values)
    assert after['selected'] == [] and after['witness_nav'] == pytest.approx([1., 1.2])
    assert prior.wealth_core == {} and prior.pending == []


def test_prior_canonical_id_and_provider_uuid_remain_distinct(monkeypatch):
    conn, prior, previous, current, conversion = _case()
    conversion.old_provider_asset_id = 'prior-name-change-uuid'
    _bound_source(monkeypatch, previous, current, old_provider='prior-name-change-uuid')
    bridges, _ = window_continuity._merger_bridges(
        conn, prior=prior, previous=previous, current=current, cursor=CURSOR, session=SESSION)
    assert set(bridges) == {OLD}


def test_unadmitted_successor_names_missing_current_close(monkeypatch):
    conn, prior, previous, current, _ = _case()
    current.resolver.resolve = lambda *_args: None
    _bound_source(monkeypatch, previous, current, successor_admitted=False)
    with pytest.raises(rolling_continuity.RollingContinuityRefused,
                       match='MERGER_SUCCESSOR_CURRENT_CLOSE_REQUIRED'):
        window_continuity._merger_bridges(
            conn, prior=prior, previous=previous, current=current, cursor=CURSOR, session=SESSION)
    assert conn.queries == []


def test_held_merger_without_current_predecessor_history_uses_canonical_book(monkeypatch):
    conn, prior, previous, current, _ = _case(held=True)
    prior.median5['selected'] = []
    _bound_source(monkeypatch, previous, current)
    bridges, conversions = window_continuity._merger_bridges(
        conn, prior=prior, previous=previous, current=current, cursor=CURSOR, session=SESSION)
    assert OLD in bridges
    metadata = {sid: SecurityMeta(sid, ticker, permaticker=sid)
                for sid, ticker in ((OLD, 'AAA'), (NEW, 'BBB'))}
    current_bar = VendorBar(SESSION, NEW, 'BBB', 40., 40., 1000., signal_close=40.)
    signal = window_material.Signal(security_id=NEW, ticker='BBB', issuer_id=NEW,
        closes=(40.,), raw_close=40., eligible=False, eligibility_reason='NEW',
        certified_signals=None)
    features = window_material.WindowFeatures(snapshot_sha256=SNAPSHOT,
        prior_state_sha256=SNAPSHOT, publication_version=2,
        sessions=calendar.previous_sessions(SESSION, 300), signals=(signal,),
        histories={OLD: ()})
    prior.last_processed_session = CURSOR
    prior.state_hash = SNAPSHOT

    def run(material):
        feed = Feed(metadata)
        feed.warmup([CURSOR], {CURSOR: [
            VendorBar(CURSOR, OLD, 'AAA', 50., 50., 1000., split_ratio=2)]})
        feed.series[OLD].signal_basis_multiplier = 2.
        feed.median5_state = {'last_index': feed._session_index}
        published = SimpleNamespace(session=SESSION, data_version=2,
            window_features=material.model_dump(mode='json', by_alias=True),
            history_proof={'features_sha256': material.sha256, 'snapshot_sha256': SNAPSHOT},
            signal_basis_anchors={OLD: window_continuity.merger_anchor_bar(
                CURSOR, OLD, 'AAA', 50., 50.)}, bars=(current_bar,))
        window_material.install(feed, prior=prior, published=published)
        state = PortfolioState.fresh(1000.)
        state.initialized = True
        state.slots[0].occupied_by = OLD
        state.episodes[0] = HoldingEpisode(OLD, 'AAA', metadata[OLD].issuer_key()[0],
            0, '2026-11-10', '2026-11-10', 45., 90., 2., 2., 100.)
        terms = window_continuity._merger_terminals(conversions=conversions,
            prices=published, metadata=metadata, session=SESSION, held={OLD: Fraction(2)})
        plan = plan_session(session=SESSION, bars=published.bars, meta=metadata, state=state,
            pending=[], ledger=Ledger(), last_known={OLD: 50.}, feed=feed, terminal_events=terms)
        return state, plan

    rebuilt = window_continuity._merger_histories(features, bridges=bridges, held={OLD})
    state, plan = run(rebuilt)
    assert state.episodes[0].security_id == NEW
    assert state.episodes[0].current_shares == 3.
    assert state.episodes[0].entry_split_adjusted_price == pytest.approx(30.)
    assert state.episodes[0].entry_date == '2026-11-10'
    assert state.cash == 1000. and plan.resolved_equity == 1120.

    # The old implementation lost the prior basis when the new source omitted
    # every predecessor bar. The same fixture then fails to convert.
    without_bridge, unresolved = run(features)
    assert without_bridge.episodes[0].security_id == OLD
    assert unresolved.resolved_equity is None


def test_held_fractional_entitlement_without_price_remains_pending():
    _, _, _, _, conversion = _case(held=True)
    prices = SimpleNamespace(bars=(VendorBar(SESSION, NEW, 'BBB', 40., 40., 1000.,
                                              signal_close=40.),))
    metadata = {NEW: SecurityMeta(NEW, 'BBB', permaticker=NEW)}
    with pytest.raises(window_continuity.MergerActionPending,
                       match='MISSING_CASH_IN_LIEU_PRICE:' + SESSION + ':' + OLD):
        window_continuity._merger_terminals(conversions=(conversion,), prices=prices,
            metadata=metadata, session=SESSION, held={OLD: Fraction(1)})


@pytest.mark.parametrize('damage', ['wrong-origin', 'wrong-provider', 'wrong-date',
                                     'wrong-successor-provider', 'wrong-successor-identity',
                                     'wrong-raw', 'wrong-signal-basis', 'missing-prior-bar'])
def test_merger_anchor_and_source_identity_must_agree(monkeypatch, damage):
    conn, prior, previous, current, conversion = _case()
    _bound_source(monkeypatch, previous, current)
    if damage == 'wrong-origin':
        conversion.origin_snapshot_id = 'c' * 64
    elif damage == 'wrong-provider':
        conversion.old_provider_asset_id = 'unrelated-uuid'
    elif damage == 'wrong-date':
        conversion.effective_session = '2026-11-24'
    elif damage == 'wrong-successor-provider':
        conversion.successor_provider_asset_id = 'unrelated-new-uuid'
    elif damage == 'wrong-successor-identity':
        conversion.successor_security_id = 'unrelated-new-id'
    elif damage == 'wrong-raw':
        conn.rows = [(CURSOR, OLD, 'AAA', 51., 50., 50., 1000., 1., 0.)]
    elif damage == 'wrong-signal-basis':
        prior.feed['series'][OLD]['signal_basis_multiplier'] = 1.
    else:
        conn.rows = []
    with pytest.raises(rolling_continuity.RollingContinuityRefused,
                       match='MERGER_(SOURCE_IDENTITY|PRIOR_)'):
        window_continuity._merger_bridges(
            conn, prior=prior, previous=previous, current=current, cursor=CURSOR, session=SESSION)


@pytest.mark.parametrize('damage', ['absent', 'stale', 'nonpositive', 'wrong-symbol'])
def test_merger_terminal_needs_current_successor_raw_close(damage):
    _, _, _, _, conversion = _case()
    bar = VendorBar(SESSION, NEW, 'BBB', 40., 40., 1000., signal_close=40.)
    if damage == 'absent':
        bars = ()
    elif damage == 'stale':
        bars = (VendorBar(CURSOR, NEW, 'BBB', 40., 40., 1000., signal_close=40.),)
    elif damage == 'nonpositive':
        bars = (VendorBar(SESSION, NEW, 'BBB', 0., 40., 1000., signal_close=40.),)
    else:
        bars = (VendorBar(SESSION, NEW, 'OTHER', 40., 40., 1000., signal_close=40.),)
    with pytest.raises(rolling_continuity.RollingContinuityRefused,
                       match='MERGER_SUCCESSOR_CURRENT_CLOSE_REQUIRED'):
        window_continuity._merger_terminals(
            conversions=(conversion,), prices=SimpleNamespace(bars=bars),
            metadata={NEW: SecurityMeta(NEW, 'BBB', permaticker=NEW)}, session=SESSION)
