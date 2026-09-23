"""Canonical formation, independent sizing, and source-bound continuation."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
import math
from types import SimpleNamespace

import pytest

from sentinel.core.formation import Formation, FormationPlan, FormationRefused
from sentinel.core.kernel import advance_session
from sentinel.core.session import DefensiveBar, PublishedSession, SessionState
from sentinel.execution.projection import project
from sentinel.feed.rolling_contract import digest
from sentinel.strategy import production_strategy
from stock_strategy_shared.wealth_core.feed import (
    DecisionMetadataTimelineBuilder, SecurityMeta, VendorBar)


@pytest.fixture(scope='module')
def material():
    cfg, identity = production_strategy()
    plan = FormationPlan(end='2026-07-31', strategy=identity, source_sha256=digest('synthetic-v1'))
    axis = plan.axis
    timeline = DecisionMetadataTimelineBuilder(axis[:252])
    prices = {f'S{i:02}': 40. + i for i in range(30)}
    spy, stream = [], []
    for day, session in enumerate(axis):
        bars, meta = [], {}
        spy.append(100 * math.exp(day * .0003 + .003 * math.sin(day / 13)))
        for i, sid in enumerate(prices):
            symbol = 'RENAMED' if sid == 'S00' and day >= 290 else sid
            split = 2. if sid == 'S00' and day == 300 else 1.
            old = prices[sid] / split
            prices[sid] = old * (1.001 + .0015 * math.sin(day / 9 + i))
            scale = 2. if sid == 'S00' and day >= 300 else 1.
            meta[sid] = SecurityMeta(sid, symbol, 'Domestic Common Stock', sid, first_session=axis[0])
            bars.append(VendorBar(session, sid, symbol, prices[sid], old, 2e6,
                split_ratio=split, signal_close=prices[sid] * scale,
                dividend_per_share=.2 if sid == 'S00' and day == 310 else 0.))
        if day < 252:
            timeline.add_snapshot(session, meta)
        lo = max(0, day - 253)
        stream.append(PublishedSession(session, 1, tuple(bars), meta, {sid: 'TECH' for sid in meta},
            spy_closeadj=spy[lo:day + 1], spy_sessions=axis[lo:day + 1],
            spy_expected_sessions=axis[lo:day + 1],
            defensive_bar=DefensiveBar(session, 'SENTINEL:BIL', 'BIL', 100., 100., 100., 100.),
            defensive_previous_bar=(DefensiveBar(axis[day-1], 'SENTINEL:BIL', 'BIL', 100., 100., 100., 100.)
                                    if day else None)))
    window = SimpleNamespace(sessions=axis[:252],
        bars_by_session={p.session: p.bars for p in stream[:252]}, meta=stream[251].meta,
        metadata_timeline=timeline.finish(), median5_spy_closes=dict(zip(axis[:252], spy[:252])),
        median5_terminals={})
    return plan, window, stream[252:]


@pytest.fixture(scope='module')
def run(material):
    plan, window, stream = material
    formed = Formation(plan, window, data_version=1)
    checkpoints = [formed.checkpoint()]
    rows = []
    for i, published in enumerate(stream, 1):
        formed.advance(published)
        rows.append(formed.state)
        if i in (1, 47, 63, 125, 126):
            checkpoints.append(formed.checkpoint())
    return formed, checkpoints, rows


def test_exact_frozen_axis_and_independent_replay(material, run):
    plan, window, stream = material
    formed, checkpoints, rows = run
    assert plan.capital == '50000'
    assert (plan.axis[0], plan.axis[251], plan.axis[252], plan.axis[-1]) == (
        '2025-01-29', '2026-01-29', '2026-01-30', '2026-07-31')
    state = SessionState.from_dict(checkpoints[0]['state'])
    for published, expected in zip(stream, rows):
        state = advance_session(state, published, controller_config=formed.controller,
                                strategy_identity=plan.strategy)
        assert state.state_hash == expected.state_hash
    assert formed.complete and len(state.wealth_core['episodes']) > 0
    assert state.wealth_core['cash'] != 50000
    assert formed.checkpoint()['status'] == 'NOT_ADMITTED'
    assert len(state.feed['seen_sessions']) <= 300
    assert all(len(row['session_indices']) <= 300 for row in state.feed['series'].values())


def test_resume_across_rollover_split_and_dividend_is_identical(material, run):
    plan, _, stream = material
    formed, checkpoints, _ = run
    for raw in checkpoints:
        resumed = Formation.resume(json.loads(json.dumps(raw)), plan=plan)
        for p in stream[raw['count']:]:
            resumed.advance(p)
        assert resumed.checkpoint() == formed.checkpoint()


def test_owned_split_and_dividend_have_independent_economic_effects(material, run):
    rows = run[2]
    def day(index):
        return rows[index - 252]
    def owned(index):
        return next(e for e in day(index).wealth_core['episodes'].values()
                    if e['security_id'] == 'S00')
    before, after = owned(299), owned(300)
    assert before['current_shares'] > 0
    assert after['current_shares'] == 2 * before['current_shares']
    assert after['ticker'] == 'RENAMED'
    assert after['entry_date'] == before['entry_date']
    assert day(300).wealth_core['cash'] == day(299).wealth_core['cash']
    # The dividend is owed to an actually held security, then becomes spendable
    # one session later. Replay equality alone cannot establish either fact.
    owed = Decimal(str(owned(309)['current_shares'])) * Decimal('.2')
    assert owed > 0
    assert day(310).wealth_core['cash'] == day(309).wealth_core['cash']
    claims = day(310).ledger['receivables']
    assert len(claims) == 1 and claims[0]['security_id'] == 'S00'
    assert Decimal(str(claims[0]['amount'])) == owed
    assert day(311).ledger['receivables'] == []
    assert day(311).wealth_core['cash'] == pytest.approx(
        day(309).wealth_core['cash'] + float(owed), abs=1e-9)


def test_daily_cash_and_shares_reconcile_from_event_movements(run):
    for state in run[2]:
        cash = Decimal('50000')
        shares = {}
        for event in state.ledger['events']:
            cash += Decimal(str(event['cash_delta']))
            sid = event['security_id']
            shares[sid] = shares.get(sid, Decimal(0)) + Decimal(str(event['shares_delta']))
        assert float(cash) == pytest.approx(state.wealth_core['cash'], abs=1e-8)
        assert {sid: q for sid, q in shares.items() if q} == {
            e['security_id']: Decimal(str(e['current_shares']))
            for e in state.wealth_core['episodes'].values()}


def test_rejected_input_does_not_advance_candidate(material):
    plan, window, stream = material
    formed = Formation(plan, window, data_version=1)
    before = formed.checkpoint()
    with pytest.raises(FormationRefused, match='GAP_OR_DUPLICATE'):
        formed.advance(stream[1])
    assert formed.checkpoint() == before
    with pytest.raises(ValueError):
        formed.advance(replace(stream[0], data_version=0))
    assert formed.checkpoint() == before
    formed.advance(stream[0])
    with pytest.raises(FormationRefused, match='GAP_OR_DUPLICATE'):
        formed.advance(stream[0])
    before = formed.checkpoint()
    # Fills and strategy calculations precede this validation in the kernel.
    # A late failure must not leak a partly advanced book into the candidate.
    with pytest.raises(ValueError, match='current dated SPY'):
        formed.advance(replace(stream[1], spy_sessions=stream[0].spy_sessions))
    assert formed.checkpoint() == before
    formed.advance(stream[1])
    assert formed.state.wealth_core['episodes']


def test_missing_historical_metadata_cannot_use_current_metadata(material):
    plan, window, _ = material
    missing = deepcopy(window)
    missing.metadata_timeline = None
    with pytest.raises(FormationRefused, match='CAUSAL_METADATA_REQUIRED'):
        Formation(plan, missing, data_version=1)


@pytest.mark.parametrize('field,value', [('count', True), ('count', 127),
    ('status', 'VERIFIED'), ('chain', '0' * 64), ('state_sha256', '0' * 64)])
def test_checkpoint_tampering_refuses(material, run, field, value):
    raw = deepcopy(run[1][2]); raw[field] = value
    with pytest.raises(FormationRefused):
        Formation.resume(raw, plan=material[0])


@pytest.mark.parametrize('change', [dict(capital='100000'), dict(source_sha256='0' * 64),
    dict(end='2026-07-30')])
def test_resume_cannot_rebase_capital_or_change_source_period(material, run, change):
    plan = FormationPlan.model_validate(material[0].model_dump(by_alias=True) | change)
    with pytest.raises(FormationRefused, match='BINDING_CHANGED'):
        Formation.resume(run[1][2], plan=plan)


def test_complete_formation_cannot_advance_again(material, run):
    with pytest.raises(FormationRefused, match='ALREADY_COMPLETE'):
        run[0].advance(material[2][-1])


def test_fifty_thousand_scaling_does_not_import_historical_profit():
    # Independent hand calculation: 50k * .55 * .30 / 101 = 81 whole shares;
    # 50k * .55 * .20 / 77 = 71. Defensive 22,500 / 91 = 247.
    D = Decimal
    basket = project(shadow_weights={'A': D('.30'), 'B': D('.20')}, exposure=D('.55'),
        nav=D('50000'), marks={'A': D('101'), 'B': D('77'), 'BIL': D('91')},
        defensive_security='BIL', defensive_weight=D('.45'))
    assert basket.quantities == {'A': D(81), 'B': D(71)}
    assert basket.defensive_quantity == 247
    assert basket.cash_residual == 13875  # Core's uninvested half and rounding.
    assert basket.nav == 50000
    assert basket.invested_notional + 247 * 91 + basket.cash_residual == 50000


def test_active_owned_cause_reaches_final_kernel_target(material, run):
    plan, _, stream = material
    state = SessionState.from_dict(run[1][2]['state'])
    state.owned_impairment.update(active=True, entry_streak=0, recovery_streak=0)
    result = advance_session(state, stream[47], controller_config=run[0].controller,
                             strategy_identity=plan.strategy)
    assert result.last_decision['champion_target_core_exposure'] == 1.
    assert result.last_decision['target_core_exposure'] == .55


def test_current_controller_uses_correlation_peers_not_sector_labels(material, run):
    from sentinel.breadth.classifier import Holding, session_breadth
    plan, _, stream = material
    prior = SessionState.from_dict(run[1][4]['state'])
    published = stream[125]
    # Half the owned names are red; the rest are neutral with -1% r21.
    # Sector grouping would materially change their damage classification.
    ids = sorted(e['security_id'] for e in prior.wealth_core['episodes'].values())
    severe = set(ids[:len(ids)//2])
    earlier = {b.security_id: b for b in stream[104].bars}
    bars = []
    for bar in published.bars:
        factor = (.80 if bar.security_id in severe else
                  earlier[bar.security_id].signal_close * .99 / bar.signal_close)
        bars.append(replace(bar, raw_close=bar.raw_close * factor,
                            signal_close=bar.signal_close * factor))
    published = replace(published, bars=tuple(bars))
    outcomes = []
    for sectors in ({}, {sid: 'ONE_SECTOR' for sid in published.meta},
                    {sid: sid for sid in published.meta}):
        outcomes.append(advance_session(prior, replace(published, sectors=sectors),
            controller_config=run[0].controller, strategy_identity=plan.strategy))
    assert len({state.state_hash for state in outcomes}) == 1
    held = [Holding(**h) for h in outcomes[0].last_evidence['breadth']['holdings']]
    grouped = session_breadth([replace(h, sector='ONE') for h in held])
    separate = session_breadth([replace(h, sector=h.ticker) for h in held])
    assert grouped.damaged_breadth > separate.damaged_breadth


def test_current_eligibility_ignores_exchange_but_requires_first_session(material, run):
    plan, _, stream = material
    prior = SessionState.from_dict(run[1][0]['state'])
    published = stream[0]
    def transition(meta):
        return advance_session(prior, replace(published, meta=meta),
            controller_config=run[0].controller, strategy_identity=plan.strategy)
    outcomes = []
    for exchange in ('NYSE', 'OTC', None):
        meta = {sid: replace(m, exchange=exchange, exchange_authoritative=True)
                for sid, m in published.meta.items()}
        outcomes.append(transition(meta))
    assert len({state.state_hash for state in outcomes}) == 1
    assert outcomes[0].pending  # Positive admission, not an empty-book equality.
    future = {sid: replace(m, first_session=plan.end) for sid, m in published.meta.items()}
    assert transition(future).pending == []
    unknown = {sid: replace(m, category=None) for sid, m in published.meta.items()}
    assert transition(unknown).pending == []
