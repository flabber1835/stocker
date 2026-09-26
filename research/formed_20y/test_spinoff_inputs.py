from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
import json
from pathlib import Path

import pytest

from research.bounded_20y.run import vendor
from sentinel.core.spinoffs import (
    SpinoffDistribution, SpinoffTermsRequired, LIQUIDATE_CHILD_AT_OPEN,
    apply_supported_entitlements,
)
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from . import spinoff_inputs


def evidence():
    return json.loads(Path(__file__).with_name('spinoff-source-rows.json').read_text())


def event(row):
    _, parent, child_id, child, ratio = spinoff_inputs.REVIEWED[(row['session'], row['security_id'])]
    return SpinoffDistribution(row['session'], parent, row['security_id'], child,
        child_id, 'sourced-'+parent, None, child_shares_per_parent=ratio,
        policy=LIQUIDATE_CHILD_AT_OPEN)


@pytest.mark.parametrize('index', range(3))
def test_exact_in_kind_proxy_removed_without_changing_other_fields(index):
    row = evidence()['observations'][index]
    original = deepcopy(row)
    actions = [a for a in evidence()['actions'] if a['ticker'] == row['ticker']]
    assert {a['action'] for a in actions} == {'spinoff', 'spinoffdividend'}
    proxy = next(a for a in actions if a['action'] == 'spinoffdividend')
    assert D(row['dividend_per_share']) == D(proxy['canonical_value'])
    cash = {**row, 'security_id': 'independent-cash-payer', 'dividend_per_share': '0.5'}
    result, audit = spinoff_inputs.normalize([row, cash], [event(row)])
    assert row == original and result == [{**original, 'dividend_per_share': '0'}, cash]
    assert len(audit) == 1 and audit[0]['original_dividend_per_share'] == original['dividend_per_share']
    assert audit[0]['source_row_sha256'] != audit[0]['normalized_row_sha256']


def test_changed_source_or_child_terms_refuse():
    row = evidence()['observations'][0]
    with pytest.raises(ValueError, match='observation changed'):
        spinoff_inputs.normalize([{**row, 'dividend_per_share': '38'}], [event(row)])
    with pytest.raises(ValueError, match='child terms changed'):
        spinoff_inputs.normalize([row], [replace(event(row), child_shares_per_parent='2')])
    with pytest.raises(ValueError, match='child terms changed'):
        spinoff_inputs.normalize([row], [replace(event(row), child_security_id='wrong')])


def test_unknown_proxy_and_duplicate_or_missing_rows_refuse():
    row = evidence()['observations'][0]
    with pytest.raises(ValueError, match='unreviewed'):
        spinoff_inputs.normalize([{**row, 'security_id': 'unknown'}],
                                [replace(event(row), parent_security_id='unknown')])
    with pytest.raises(ValueError, match='duplicate supported'):
        spinoff_inputs.normalize([row], [event(row), event(row)])
    with pytest.raises(ValueError, match='duplicate spinoff observation'):
        spinoff_inputs.normalize([row, row], [event(row)])
    with pytest.raises(ValueError, match='observation missing'):
        spinoff_inputs.normalize([], [event(row)])


def test_lvnta_two_child_shares_no_additional_74_dollar_dividend():
    row = evidence()['observations'][0]
    terms = event(row)
    assert row['ticker'] == 'LVNTA'
    state, ledger = PortfolioState.fresh(1000), Ledger()
    state.slots[6].occupied_by = row['security_id']
    state.episodes[6] = HoldingEpisode(security_id=row['security_id'], ticker='LVNTA',
        issuer_id='SID:'+row['security_id'], slot_id=6, signal_date='2013-03-07',
        entry_date='2013-03-08', entry_raw_open=77.7, entry_split_adjusted_price=38.85,
        initial_shares=1, current_shares=2, episode_peak_split_adjusted_close=75.28)
    normalized, _ = spinoff_inputs.normalize([row], [terms])
    parent = vendor(normalized[0])
    child = replace(parent, security_id=terms.child_security_id, ticker='LTRPA',
                    raw_open=37.36, raw_close=36., signal_close=36.)
    original = deepcopy(state.to_dict())
    with pytest.raises(SpinoffTermsRequired, match='SPINOFF_CHILD_OWNERSHIP_REQUIRED'):
        apply_supported_entitlements(state, [replace(terms, policy='REQUIRE_REVIEWED_CHILD_OWNERSHIP')],
            bars=[parent, child], ledger=ledger, config=WealthCoreConfig())
    assert state.to_dict() == original and not ledger.events
    audit = apply_supported_entitlements(state, [terms], bars=[parent, child],
                                        ledger=ledger, config=WealthCoreConfig())
    assert abs(D(str(state.cash))-D('1074.64528')) < D('.00000001')
    assert audit[0]['whole_child_shares'] == 2 and audit[0]['fractional_child_shares'] == '0'
    assert state.episodes[6].current_shares == 2 and state.slots[6].occupied_by == row['security_id']
    assert [e.event_type.value for e in ledger.events] == ['SPINOFF_RECEIPT', 'SPINOFF_LIQUIDATION']
    assert parent.dividend_per_share == 0
    assert abs(D(str(ledger.events[1].fees))-D('.07472')) < D('.00000001')
