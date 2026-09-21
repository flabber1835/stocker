"""Independent arithmetic and production transition checks for the study."""
import copy
from dataclasses import replace
import json
import gzip
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel.core.kernel import advance_session
from sentinel.core.session import SessionState
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState

from research.impedance.pipeline import assert_split_neutral, make_origin
from research.impedance.pipeline_diagnostics import assert_nav, attribution, measure


def tiny_state():
    book = PortfolioState.fresh(17., 2)
    for i, shares in enumerate((3, 5)):
        sid = f'S{i}'
        book.slots[i].occupied_by = sid
        book.episodes[i] = HoldingEpisode(sid, sid, sid, i, '2020-01-01',
            '2020-01-02', 10., 10., shares, shares)
    return SimpleNamespace(wealth_core=book.to_dict(), ledger=Ledger().to_dict(),
        last_evidence={'observation': {'shadow_nav': 120.}})


def test_nav_uses_owned_quantity_times_current_raw_marks():
    # 17 cash + 3 * 11 + 5 * 14 = 120, independently specified.
    state = tiny_state()
    assert assert_nav(state, {'S0': 11., 'S1': 14.}) == 120.
    assert state.last_evidence['observation']['shadow_nav'] == 120.


def test_nav_rejects_wrong_current_mark():
    with pytest.raises(AssertionError):
        assert_nav(tiny_state(), {'S0': 12., 'S1': 14.})


def test_damage_attribution_keeps_sold_losses_and_denominator_separate():
    # Two damaged names among three become one among two. The continuing
    # damaged survivor heals (-1/3); an exit removes 1/3, an entry adds 1/3, and the new
    # denominator contributes 1/6. Net: -1/6.
    result = attribution({'A': True, 'B': True, 'C': False},
                         {'B': False, 'D': True})
    assert result == pytest.approx(dict(continuing_label_change=-1/3,
        entries=1/3, exits=-1/3, denominator=1/6, observed_change=-1/6))
    assert attribution({'A': True}, {})['exits'] == -1.
    assert attribution({}, {'A': True})['entries'] == 1.
    assert attribution({}, {})['observed_change'] == 0.


@pytest.fixture(scope='module')
def origin():
    return make_origin()


def test_production_formed_book_restart_order_and_observer(origin):
    config, identity, state, market, formation = origin
    assert len(state.wealth_core['episodes']) == 20
    before = state.state_hash
    p = copy.deepcopy(market).advance('synchronized_shock', 0)
    direct = advance_session(state, p, controller_config=config, strategy_identity=identity)
    restored = SessionState.from_dict(json.loads(json.dumps(state.to_dict())))
    repeated = advance_session(restored, replace(p, bars=tuple(reversed(p.bars))),
                               controller_config=config, strategy_identity=identity)
    assert direct.state_hash == repeated.state_hash
    assert state.state_hash == before
    diagnostic_before = direct.state_hash
    row = measure(direct, p, formation[-1]['labels'])
    assert direct.state_hash == diagnostic_before
    assert row['nav'] < formation[-1]['nav']
    assert row['observation']['damaged_breadth'] == 1.


def test_nav_falsifier_also_catches_production_formed_book(origin):
    _, _, state, market, _ = origin
    marks = dict(market.prices)
    assert_nav(state, marks)
    sid = next(iter(state.wealth_core['episodes'].values()))['security_id']
    marks[sid] += 1.
    with pytest.raises(AssertionError):
        assert_nav(state, marks)


@pytest.mark.parametrize('corruption', ['nav', 'decision', 'observation', 'missing_split', 'truncation'])
def test_split_equivalence_rejects_corruption(corruption):
    # These retained real pipeline rows are inputs to the *evidence validator*.
    # This is not a replacement for executing the canonical pipeline.
    path = Path(__file__).resolve().parents[2] / 'audit/impedance/pipeline-results.json.gz'
    cases = json.loads(gzip.decompress(path.read_bytes()))['cases']
    healthy, split = cases['healthy'], cases['healthy_split']
    assert_split_neutral(healthy, split)
    row = split['records'][20]
    if corruption == 'nav':
        row['nav'] += 1.
    elif corruption == 'decision':
        row['core_multiplier'] = 0.
    elif corruption == 'observation':
        row['observation']['shadow_r20'] += .1
    elif corruption == 'missing_split':
        row['events'] = []
    else:
        split['records'].pop()
    with pytest.raises(AssertionError):
        assert_split_neutral(healthy, split)
