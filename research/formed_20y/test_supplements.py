from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest

from research.bounded_20y.run import terminals
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import apply_terminal
from . import prepare_supplements


def trbs():
    return json.loads(Path(__file__).with_name('trbs-supplement.json').read_text())


def isln():
    return json.loads(Path(__file__).with_name('isln-supplement.json').read_text())


def lvnta():
    return json.loads(Path(__file__).with_name('lvnta-supplement.json').read_text())


def test_retained_records_unchanged_and_new_output_cannot_overwrite(tmp_path, monkeypatch):
    original = [dict(id='other-event', security_id='other-security', cash_per_share='12.34')]
    base, output = tmp_path/'base.json', tmp_path/'new.json'
    base.write_text(json.dumps(original))
    monkeypatch.setattr(prepare_supplements, 'BASE_SHA256', hashlib.sha256(base.read_bytes()).hexdigest())
    prepare_supplements.prepare(base, output)
    assert json.loads(output.read_text()) == original + [trbs(), isln(), lvnta()]
    assert json.loads(base.read_text()) == original
    with pytest.raises(FileExistsError):
        prepare_supplements.prepare(base, output)
    base.write_text('[]')
    with pytest.raises(ValueError, match='retained supplement bytes changed'):
        prepare_supplements.prepare(base, tmp_path/'another.json')


def test_existing_identity_cannot_be_silently_replaced(tmp_path, monkeypatch):
    base = tmp_path/'base.json'
    base.write_text(json.dumps([dict(id='another-id', security_id=trbs()['security_id'])]))
    monkeypatch.setattr(prepare_supplements, 'BASE_SHA256', hashlib.sha256(base.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match='already has supplemental terms'):
        prepare_supplements.prepare(base, tmp_path/'new.json')


@pytest.mark.parametrize('missing', [False, True])
def test_sourced_cash_terms_pay_57_shares_without_cancelled_dividend(missing):
    event = deepcopy(trbs())
    assert event['known_by'] == event['original_event_session'] == '2006-11-10'
    assert event['effective_session'] == '2006-11-13'
    if missing:
        event['cash_per_share'] = ''
    state, ledger = PortfolioState.fresh(1000), Ledger()
    sid = event['security_id']
    state.slots[2].occupied_by = sid
    state.episodes[2] = HoldingEpisode(security_id=sid, ticker='TRBS', issuer_id='SID:'+sid,
        slot_id=2, signal_date='2006-07-14', entry_date='2006-07-17', entry_raw_open=37.86,
        entry_split_adjusted_price=37.86, initial_shares=57, current_shares=57,
        episode_peak_split_adjusted_close=38.93, market_sessions_held=83)
    result = apply_terminal(state, terminals([event])['2006-11-13'][0], ledger=ledger,
                            session='2006-11-13', cfg=WealthCoreConfig())
    if missing:
        assert result['applied'] is False
        assert result['reason'] == 'MISSING_CASH_PER_SHARE'
        assert state.cash == 1000 and 2 in state.episodes and not ledger.events
    else:
        assert result['applied'] is True and 2 not in state.episodes
        assert abs(Decimal(str(state.cash)) - Decimal('3217.30')) < Decimal('0.00000001')
        assert len(ledger.events) == 1
        assert abs(Decimal(str(ledger.events[0].cash_delta)) - Decimal('2217.30')) < Decimal('0.00000001')
        assert ledger.events[0].shares_delta == -57


@pytest.mark.parametrize('missing', [False, True])
def test_sourced_isln_cash_terms_pay_109_shares(missing):
    event = deepcopy(isln())
    assert event['known_by'] == event['original_event_session'] == event['effective_session'] == '2010-12-21'
    if missing:
        event['cash_per_share'] = ''
    state, ledger = PortfolioState.fresh(1000), Ledger()
    sid = event['security_id']
    state.slots[12].occupied_by = sid
    state.episodes[12] = HoldingEpisode(security_id=sid, ticker='ISLN', issuer_id='SID:'+sid,
        slot_id=12, signal_date='2010-10-06', entry_date='2010-10-07', entry_raw_open=23.88,
        entry_split_adjusted_price=23.88, initial_shares=109, current_shares=109,
        episode_peak_split_adjusted_close=33.85, market_sessions_held=52)
    result = apply_terminal(state, terminals([event])['2010-12-21'][0], ledger=ledger,
                            session='2010-12-21', cfg=WealthCoreConfig())
    if missing:
        assert result['applied'] is False
        assert result['reason'] == 'MISSING_CASH_PER_SHARE'
        assert state.cash == 1000 and 12 in state.episodes and not ledger.events
    else:
        assert result['applied'] is True and 12 not in state.episodes
        assert abs(Decimal(str(state.cash)) - Decimal('4689.65')) < Decimal('0.00000001')
        assert len(ledger.events) == 1
        assert abs(Decimal(str(ledger.events[0].cash_delta)) - Decimal('3689.65')) < Decimal('0.00000001')
        assert ledger.events[0].shares_delta == -109
