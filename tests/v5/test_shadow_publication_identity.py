"""Routine rebases cross the complete shadow verification boundary."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sentinel import shadow_observation as SO, shadow_runtime as SR
from sentinel import dual_reconciliation
from sentinel.core.production import SessionState, warm_session_state
from sentinel.controller.machine import Controller
from sentinel.feed import calendar
from sentinel.strategy import production_strategy
from tests.sentinel.test_shadow_observation import (
    FIRST, FakePostgres, TEST_RUNTIME_IDENTITY, _activation, _fully_published,
    _install_runtime_gates, _preopen_clock, _warmup_window,
)


def warmup():
    axis, window = _warmup_window()
    window.median5_spy_closes = {day: 100. + i*.125 for i, day in enumerate(axis)}
    window.median5_terminals = {}
    for i, day in enumerate(axis):
        bar = window.bars_by_session[day][0]
        close = 10. + i*.125
        window.bars_by_session[day] = [replace(
            bar, raw_close=close, raw_open=close, signal_close=close)]
    return axis, window


def identity(window):
    return SR._warmup_input_identity(window, window.sessions, prospective_witness=True)


def rebase(window, *, stock=1., spy=1.):
    changed = deepcopy(window)
    changed.median5_spy_closes = {day: value*spy for day, value in window.median5_spy_closes.items()}
    for day, bars in window.bars_by_session.items():
        changed.bars_by_session[day] = [replace(bar, signal_close=bar.signal_close*stock) for bar in bars]
    return changed


def runtime_for_gate(window, changed):
    conn = FakePostgres()
    observer = SimpleNamespace(
        store=SO.PostgresShadowObservationStore(conn, observation_id='rebase'),
        first_session=FIRST, warmup_input_identity=identity(window))
    return SO.PostgresShadowRuntime(conn, observer=observer,
                                   warmup_input_loader=lambda: identity(changed))


@pytest.mark.parametrize('stock,spy', [(.5, 1.), (1., 2.), (.25, 10.)])
def test_warmup_rebases_pass_the_production_revision_gate(stock, spy):
    _, window = warmup()
    changed = rebase(window, stock=stock, spy=spy)
    assert runtime_for_gate(window, changed)._require_current_warmup_input() == identity(window)['warmup_input_sha256']


def test_warmup_basis_is_owned_per_permanent_security():
    _, window = warmup()
    window.meta['2'] = replace(window.meta['1'], security_id='2', ticker='BBB', permaticker='2')
    for bars in window.bars_by_session.values():
        bars.append(replace(bars[0], security_id='2', ticker='BBB',
                            signal_close=bars[0].signal_close*3.))
    changed = rebase(window, stock=.5, spy=2.)
    for day, bars in changed.bars_by_session.items():
        bars[1] = replace(bars[1], signal_close=window.bars_by_session[day][1].signal_close*.25)
    assert identity(changed) == identity(window)


@pytest.mark.parametrize('fault', ['signal', 'first_signal', 'spy', 'first_spy',
                                    'raw_close', 'volume', 'split', 'missing', 'terminal', 'metadata'])
def test_rebased_warmup_still_refuses_real_revisions(fault):
    axis, window = warmup()
    changed = rebase(window, stock=.5, spy=2.)
    day = axis[70]
    if fault in {'signal', 'first_signal'}:
        day = axis[0] if fault == 'first_signal' else day
        bar = changed.bars_by_session[day][0]
        changed.bars_by_session[day] = [replace(bar, signal_close=bar.signal_close+.001)]
    elif fault in {'spy', 'first_spy'}:
        changed.median5_spy_closes[axis[0] if fault == 'first_spy' else day] += .001
    elif fault in {'raw_close', 'volume', 'split'}:
        field = 'split_ratio' if fault == 'split' else fault
        bar = changed.bars_by_session[day][0]
        changed.bars_by_session[day] = [replace(bar, **{field: getattr(bar, field)+.001})]
    elif fault == 'missing':
        changed.bars_by_session[day] = []
    elif fault == 'terminal':
        changed.median5_terminals[day] = {'1'}
    else:
        changed.meta['1'] = replace(changed.meta['1'], category='Canadian Common Stock')
    with pytest.raises(SO.ShadowObservationRefused, match='warm-up'):
        runtime_for_gate(window, changed)._require_current_warmup_input()


def session_input(*, scale=1., version=7):
    original = _fully_published(FIRST, version=version)
    bar = replace(original.published.bars[0], signal_close=41.5*scale)
    predecessor = replace(bar, session=calendar.previous_sessions(FIRST, 2)[0],
                          signal_close=41.375*scale)
    return replace(original.published, bars=[bar], signal_basis_anchors={'1': predecessor})


def test_committed_session_rebase_preserves_ratios_and_anchor_identity(monkeypatch):
    old = session_input()
    new = session_input(scale=.5, version=8)
    assert SO._economic_input_identity(old) == SO._economic_input_identity(new)
    _, window = warmup()
    runtime = runtime_for_gate(window, window)
    config, strategy = production_strategy()
    seed = SessionState.fresh(starting_cash=100000., controller=Controller(config), strategy_identity=strategy)
    runtime.observer.initial_state = seed
    previous = _fully_published(FIRST)
    row = {'session': FIRST, 'input_sha256': SO.FullyPublishedSession(old, previous.publication).input_sha256,
           'economic_input_identity': SO._economic_input_identity(old), 'state': seed.to_dict()}
    current = _fully_published(FIRST, version=8)
    publication = SimpleNamespace(version=8, window_end=FIRST, to_dict=lambda: current.publication)
    monkeypatch.setattr(SO, 'load_published_session', lambda *a, **k: new)
    runtime._require_committed_economic_inputs([row], publication)
    corrected = replace(new, bars=[replace(new.bars[0], signal_close=20.751)])
    monkeypatch.setattr(SO, 'load_published_session', lambda *a, **k: corrected)
    with pytest.raises(SO.ShadowObservationRefused, match='committed shadow session'):
        runtime._require_committed_economic_inputs([row], publication)


@pytest.mark.parametrize('fault', ['missing', 'session', 'security', 'raw_close', 'signal_close'])
def test_daily_identity_binds_the_canonical_predecessor(fault):
    old = session_input()
    changed = session_input(scale=.5, version=8)
    anchor = changed.signal_basis_anchors['1']
    values = {'session': calendar.previous_sessions(FIRST, 3)[0], 'security': 'OTHER',
              'raw_close': 10.01, 'signal_close': 20.688}
    if fault == 'missing':
        changed = replace(changed, signal_basis_anchors={})
    else:
        field = 'security_id' if fault == 'security' else fault
        changed = replace(changed, signal_basis_anchors={'1': replace(anchor, **{field: values[fault]})})
    try:
        value = SO._economic_input_identity(changed)
    except SO.ShadowObservationRefused:
        return
    assert value != SO._economic_input_identity(old)


def test_champion_shadow_restart_and_dual_intent_continue_after_republication(monkeypatch):
    axis, window = warmup()
    # The canonical initial-construction gate requires 25 eligible securities.
    for i in range(2, 26):
        sid, ticker = str(i), f'S{i}'
        window.meta[sid] = replace(window.meta['1'], security_id=sid,
                                  ticker=ticker, permaticker=sid, related_tickers=(ticker,))
        for bars in window.bars_by_session.values():
            bars.append(replace(bars[0], security_id=sid, ticker=ticker))
    config, strategy = production_strategy()
    seed = SessionState.fresh(starting_cash=100000., controller=Controller(config),
                              strategy_identity=strategy)
    seed = warm_session_state(seed, window, publication_version=7,
                              prospective_concordance_witness=True)
    conn = FakePostgres()
    store = SO.PostgresShadowObservationStore(conn, observation_id='rebase')
    observer = SO.ShadowObserver(
        store=store, observation_id='rebase', starting_cash=100000., first_session=FIRST,
        initial_state=seed, controller_config=config, strategy_identity=strategy,
        runtime_identity=TEST_RUNTIME_IDENTITY, activation_timing=_activation(),
        warmup_input_identity=identity(window))

    def published(day, version, stock, spy):
        offset = 0 if day == FIRST else 1
        source = _fully_published(day, version=version).published
        dates = calendar.previous_sessions(day, 41)
        close, previous = 41.5+offset*.125, 41.375+offset*.125
        bars = [replace(source.bars[0], security_id=sid, ticker=meta.ticker,
                        raw_close=close, raw_open=close, signal_close=close*stock)
                for sid, meta in window.meta.items()]
        anchors = {bar.security_id: replace(bar, session=dates[-2], raw_close=previous,
                                           signal_close=previous*stock) for bar in bars}
        return replace(source, bars=bars, meta=window.meta,
                       signal_basis_anchors=anchors, spy_sessions=dates,
                       spy_expected_sessions=dates,
                       spy_closeadj=[(100.+(252+offset-40+i)*.125)*spy for i in range(41)])

    _install_runtime_gates(monkeypatch, conn)
    monkeypatch.setattr(SO, 'load_published_session',
                        lambda _conn, day, **kw: published(day, 7, 1., 1.))
    first = SO.PostgresShadowRuntime(
        conn, observer=observer, clock=lambda: _preopen_clock(),
        warmup_input_loader=lambda: identity(window)).advance_next()
    assert first.verification == SO.VERIFIED
    assert len(first.state.pending) == 20
    retained = deepcopy(store.records())
    restored = SO.ShadowObserver.resume(
        store=store, observation_id='rebase', starting_cash=100000., first_session=FIRST,
        controller_config=config, strategy_identity=strategy, runtime_identity=TEST_RUNTIME_IDENTITY)
    _install_runtime_gates(monkeypatch, conn, version=8)
    monkeypatch.setattr(SO, 'load_published_session',
                        lambda _conn, day, **kw: published(day, 8, .5, 2.))
    changed = rebase(window, stock=.5, spy=2.)
    runtime = SO.PostgresShadowRuntime(
        conn, observer=restored, clock=lambda: _preopen_clock(),
        warmup_input_loader=lambda: identity(changed))
    status = runtime.durable_status()
    assert status.verification == SO.VERIFIED
    assert status.record_sha256 == first.record_sha256
    assert store.records() == retained
    monkeypatch.setattr(SR, 'verified_shadow_status', lambda *a, **k: runtime.durable_status())
    monkeypatch.setattr(dual_reconciliation, '_require_regenesis_transport_approval',
                        lambda *a: SimpleNamespace(index=0))
    dual = dual_reconciliation.verified_shadow_intent(
        conn, decision_session=FIRST, observation_id='rebase', starting_cash=100000.)
    assert dual.state.state_hash == first.state.state_hash

    next_day = calendar.next_session(FIRST)
    _install_runtime_gates(monkeypatch, conn, session=next_day, version=8)
    monkeypatch.setattr(SO, 'load_published_session',
                        lambda _conn, day, **kw: published(day, 8, .5, 2.))
    runtime.clock = lambda: _preopen_clock(next_day)
    after = runtime.advance_next()
    expected = SO.advance_state(first.state, published(next_day, 7, 1., 1.),
                               controller_config=config, strategy_identity=strategy)
    assert after.verification == SO.VERIFIED
    assert len(after.state.wealth_core['episodes']) == 20
    assert after.state.wealth_core == expected.wealth_core
    assert after.state.pending == expected.pending
    assert after.state.last_decision == expected.last_decision
    assert after.state.feed['series']['1']['signal_closes'] == expected.feed['series']['1']['signal_closes']
    assert [row[2] for row in after.state.median5['spy_history']] == [row[2] for row in expected.median5['spy_history']]
