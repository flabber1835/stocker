"""A merger may close a controller witness without changing Wealth Core ownership."""
from types import SimpleNamespace

import pytest

from sentinel.controller import median5, terminal_returns
from sentinel.core import rolling_continuity, window_continuity
from sentinel.feed import rolling_store
from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar


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
        wealth_core={'episodes': {'episode': {'security_id': OLD}}} if held else {},
        pending=[],
        feed={'series': {OLD: {'signal_basis_anchor': anchor or [CURSOR, 50., 100.],
                              'signal_basis_multiplier': 2.}}})
    conn = _Connection([source_row or (CURSOR, OLD, 'AAA', 50., 50.)])
    return conn, prior, previous, current, conversion


def _bound_source(monkeypatch, previous, current, *, old_provider=OLD,
                  successor_admitted=True):
    monkeypatch.setattr(rolling_store, 'verify_content', lambda *_args: None)
    monkeypatch.setattr(window_continuity, 'candidate_query', lambda _conn, sql: sql)
    monkeypatch.setattr(window_continuity, '_provider_assets',
        lambda _conn, refs: {'AAA': old_provider} if refs is previous else
        {'BBB': 'new-provider-uuid'} if successor_admitted else {})


def test_selected_only_merger_uses_prior_published_anchor_and_fractional_return(monkeypatch):
    conn, prior, previous, current, _ = _case()
    _bound_source(monkeypatch, previous, current)
    bridges, conversions = window_continuity._merger_bridges(
        conn, prior=prior, previous=previous, current=current, cursor=CURSOR, session=SESSION)
    assert set(bridges) == {OLD}
    assert bridges[OLD].session == CURSOR and bridges[OLD].raw_close == 50.
    assert bridges[OLD].signal_close == 50.
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


def test_held_merger_refuses_before_reading_a_price(monkeypatch):
    conn, prior, previous, current, _ = _case(held=True)
    _bound_source(monkeypatch, previous, current)
    with pytest.raises(rolling_continuity.RollingContinuityRefused,
                       match='OWNED_MERGER_CONVERSION_UNSUPPORTED'):
        window_continuity._merger_bridges(
            conn, prior=prior, previous=previous, current=current, cursor=CURSOR, session=SESSION)
    assert conn.queries == []
    # Falsifier: disabling the ownership check would admit the exact same event.
    monkeypatch.setattr(window_continuity, '_path_dependent_security_ids', lambda *_args: set())
    bridges, _ = window_continuity._merger_bridges(
        conn, prior=prior, previous=previous, current=current, cursor=CURSOR, session=SESSION)
    assert OLD in bridges


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
        conn.rows = [(CURSOR, OLD, 'AAA', 51., 50.)]
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
