"""Small falsifiers for candidate isolation and input ownership boundaries."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sentinel.core.history import CurrentWindowProof, require_history_compatible
from sentinel.core.window_features import Signal, WindowFeatures, install
from sentinel.feed import calendar, source_authority
from sentinel.feed.source_wait import SourceCoveragePending
from stock_strategy_shared.wealth_core.feed import Feed, SecurityMeta, SecuritySeries, VendorBar
from stock_strategy_shared.wealth_core.window_signals import feature


DAY = '2026-09-14'


def coverage(missing, *, current_window=True):
    rows = [dict(table='SEP', permaticker=str(i), ticker=f'T{i}', category='Domestic Common Stock',
                 firstpricedate=DAY, lastpricedate=DAY) for i in range(100)]
    projection = source_authority.SeedListingProjection(rows, source_digest='a'*64)
    accumulator = source_authority.SeedCoverageAccumulator(projection, lambda t, d: t[1:], exceptions={})
    try:
        for row in rows[missing:]:
            accumulator.add(dict(ticker=row['ticker'], date=DAY, open=10., close=10., volume=1e6))
        return accumulator.require_complete(date_from=DAY, date_to=DAY, current_window=current_window)
    finally:
        accumulator.close()


def test_isolated_omission_needs_no_reviewed_ticker_exception():
    result = coverage(1)
    assert result['missing_eligible_total'] == 1
    assert result['reviewed_exceptions_applied_total'] == 0


@pytest.mark.parametrize('missing,current', [(2, True), (100, True), (1, False)])
def test_partial_export_and_legacy_gaps_refuse(missing, current):
    with pytest.raises(SourceCoveragePending):
        coverage(missing, current_window=current)


def test_gap_excludes_candidate_until_127_consecutive_closes_return():
    series = SecuritySeries('1', 'ABC', 'SID:1')
    meta = SecurityMeta('1', 'ABC', 'Domestic Common Stock', '1', first_session='2025-01-01')
    days = calendar.previous_sessions(DAY, 300)
    for i, day in enumerate(days):
        if i == 170:
            continue
        series.append(VendorBar(day, '1', 'ABC', 100.+i, 100.+i, 1e6, signal_close=100.+i),
                      i, published_signal=True)
        if i == 296:
            assert not feature(series, meta, index=i, session=day).eligible
        if i == 297:
            assert feature(series, meta, index=i, session=day).eligible


def input_pair():
    axis = calendar.previous_sessions(DAY, 300)
    prior = SimpleNamespace(state_hash='a'*64, last_processed_session=axis[-2],
        wealth_core={}, pending=[], median5={})
    row = VendorBar(DAY, '1', 'ABC', 100., 100., 1e6, signal_close=50.)
    signal = Signal(security_id='1', ticker='ABC', issuer_id='SID:1', closes=(50.,), raw_close=100.,
        eligible=False, eligibility_reason='SNAPSHOT_INPUT_UNAVAILABLE', certified_signals=None)
    material = WindowFeatures(snapshot_sha256='b'*64, prior_state_sha256=prior.state_hash,
        publication_version=2, sessions=tuple(axis), signals=(signal,), histories={})
    proof = CurrentWindowProof(prior_version=1, publication_version=2, prior_session=axis[-2],
        session=DAY, prior_state_sha256=prior.state_hash, snapshot_sha256='b'*64,
        features_sha256=material.sha256, protected_economics_sha256='c'*64).model_dump(by_alias=True)
    published = SimpleNamespace(window_features=material.model_dump(mode='json', by_alias=True),
        data_version=2, session=DAY, history_proof=proof, bars=(row,), signal_basis_anchors={})
    return prior, published


@pytest.mark.parametrize('fault', ['state', 'features', 'snapshot', 'keys', 'price'])
def test_window_install_refuses_unbound_or_inconsistent_inputs(fault):
    prior, published = input_pair()
    feed = Feed({})
    feed._session_index = 298
    if fault == 'state':
        prior.state_hash = 'd'*64
    elif fault == 'features':
        published.window_features['signals'][0]['eligible'] = True
    elif fault == 'snapshot':
        published.history_proof['snapshot_sha256'] = 'd'*64
    elif fault == 'keys':
        published.bars = ()
    else:
        published.bars = (replace(published.bars[0], raw_close=101.),)
    with pytest.raises(ValueError, match='CURRENT_WINDOW_'):
        install(feed, prior=prior, published=published)


def test_window_continuity_cannot_skip_or_replace_prior_state():
    prior, published = input_pair()
    args = dict(prior_version=1, last_processed_session=prior.last_processed_session,
        version=2, proof=published.history_proof, prior_state_sha256=prior.state_hash, session=DAY)
    require_history_compatible(**args)
    for change in ({'prior_state_sha256': 'd'*64}, {'version': 3}, {'session': calendar.next_session(DAY)}):
        with pytest.raises(ValueError, match='BINDING_CHANGED'):
            require_history_compatible(**{**args, **change})


def test_late_cash_is_forward_input_while_structural_history_still_refuses():
    from sentinel.core.window_continuity import protected_economics
    conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchall=lambda: []))
    resolver = SimpleNamespace(resolve=lambda ticker, day: '1' if ticker == 'ABC' else None)
    previous = SimpleNamespace(actions=[], resolver=resolver, candidate_id='old')
    current = SimpleNamespace(actions=[('source', {'ticker': 'ABC', 'date': DAY,
        'action': 'dividend', 'value': 1}, None)], resolver=resolver, candidate_id='new')
    # The same correction is immaterial to an unheld candidate.
    protected_economics(conn, previous=previous, current=current, live=set(), start=DAY, cursor=DAY)
    protected_economics(conn, previous=previous, current=current, live={'1'}, start=DAY, cursor=DAY)
    current.actions[0][1]['action'] = 'split'
    with pytest.raises(RuntimeError, match='RETAINED_ECONOMIC_EVENT_CHANGED'):
        protected_economics(conn, previous=previous, current=current, live={'1'}, start=DAY, cursor=DAY)


def test_snapshot_feature_override_cannot_skip_an_index():
    from stock_strategy_shared.wealth_core.median5 import fresh
    _, published = input_pair()
    feed = Feed({'1': SecurityMeta('1', 'ABC', 'Domestic Common Stock', '1', first_session=DAY)})
    feed.median5_state = fresh()
    feed._session_index = 8
    feed.snapshot_security_bars = {'1': Signal.model_validate(published.window_features['signals'][0]).bar()}
    with pytest.raises(ValueError, match='adjacent strategy index'):
        feed.advance(DAY, published.bars)


@pytest.mark.parametrize('fault', [None, 'old_schema', 'warmup_count', 'formed', 'first_session', 'controller'])
def test_observation_authority_requires_selected_fresh_window(fault):
    from unittest.mock import patch
    from sentinel import observation_startup
    from sentinel.authority import AuthorityRefused, canonical_sha256
    from sentinel.strategy import production_strategy
    config, strategy = production_strategy()
    strategy = {k:v for k,v in strategy.items() if k != 'startup_policy'}
    proof = dict(schema=observation_startup.WINDOW_SCHEMA, warmup_sessions=299,
        measured_sessions=300, decision_session=DAY,
        first_session=calendar.previous_sessions(DAY, 300)[0])
    controller = config.digest
    if fault == 'old_schema':
        proof['schema'] = observation_startup.COLD_SCHEMA
    elif fault == 'warmup_count':
        proof['warmup_sessions'] = 252
    elif fault == 'formed':
        proof['formation'] = {'sessions': 126}
    elif fault == 'first_session':
        proof['first_session'] = DAY
    elif fault == 'controller':
        controller = '0'*64
    args = dict(strategy_sha256=canonical_sha256(strategy), controller_sha256=controller)
    # The mutation campaign calls this witness directly, outside pytest fixtures.
    with patch('sentinel.strategy.production_strategy', return_value=(config, strategy)):
        if fault is None:
            observation_startup.require(proof, **args)
        else:
            with pytest.raises(AuthorityRefused):
                observation_startup.require(proof, **args)
