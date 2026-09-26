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


def cnqr():
    return json.loads(Path(__file__).with_name('cnqr-supplement.json').read_text())


def yoku():
    return json.loads(Path(__file__).with_name('yoku-supplement.json').read_text())


def lvnta_2016():
    return [json.loads(Path(__file__).with_name(name).read_text()) for name in
            ('lvnta-2016-chuba-supplement.json', 'lvnta-2016-chubk-supplement.json')]


def test_retained_records_unchanged_and_new_output_cannot_overwrite(tmp_path, monkeypatch):
    original = [dict(id='other-event', security_id='other-security', cash_per_share='12.34')]
    base, output = tmp_path/'base.json', tmp_path/'new.json'
    base.write_text(json.dumps(original))
    monkeypatch.setattr(prepare_supplements, 'BASE_SHA256', hashlib.sha256(base.read_bytes()).hexdigest())
    prepare_supplements.prepare(base, output)
    assert json.loads(output.read_text()) == original + [itc()]
    assert json.loads(base.read_text()) == original
    with pytest.raises(FileExistsError):
        prepare_supplements.prepare(base, output)
    base.write_text('[]')
    with pytest.raises(ValueError, match='retained supplement bytes changed'):
        prepare_supplements.prepare(base, tmp_path/'another.json')


def test_existing_identity_cannot_be_silently_replaced(tmp_path, monkeypatch):
    base = tmp_path/'base.json'
    base.write_text(json.dumps([itc()]))
    monkeypatch.setattr(prepare_supplements, 'BASE_SHA256', hashlib.sha256(base.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match='already exists'):
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


def apply_cnqr(event):
    state, ledger = PortfolioState.fresh(1000), Ledger()
    sid = event['security_id']
    state.slots[13].occupied_by = sid
    state.episodes[13] = HoldingEpisode(security_id=sid, ticker='CNQR', issuer_id='SID:'+sid,
        slot_id=13, signal_date='2014-11-12', entry_date='2014-11-13', entry_raw_open=128.36,
        entry_split_adjusted_price=128.36, initial_shares=45, current_shares=45,
        episode_peak_split_adjusted_close=128.87, market_sessions_held=14)
    result = apply_terminal(state, terminals([event])['2014-12-05'][0], ledger=ledger,
                            session='2014-12-05', cfg=WealthCoreConfig())
    return state, ledger, result


@pytest.mark.parametrize('missing', [False, True])
def test_sourced_cnqr_cash_terms_pay_45_shares(missing):
    event = deepcopy(cnqr())
    assert event['known_by'] == event['original_event_session'] == '2014-12-04'
    assert event['effective_session'] == '2014-12-05'
    if missing:
        event['cash_per_share'] = ''
    state, ledger, result = apply_cnqr(event)
    if missing:
        assert result['applied'] is False
        assert result['reason'] == 'MISSING_CASH_PER_SHARE'
        assert state.cash == 1000 and 13 in state.episodes and not ledger.events
    else:
        assert result['applied'] is True and 13 not in state.episodes
        assert abs(Decimal(str(state.cash)) - Decimal('6805.00')) < Decimal('0.00000001')
        assert len(ledger.events) == 1
        assert abs(Decimal(str(ledger.events[0].cash_delta)) - Decimal('5805.00')) < Decimal('0.00000001')
        assert ledger.events[0].shares_delta == -45


def test_cnqr_altered_consideration_fails_independent_payout_oracle():
    event = deepcopy(cnqr())
    event['cash_per_share'] = '128.99'
    _, ledger, result = apply_cnqr(event)
    assert result['applied'] is True
    with pytest.raises(AssertionError):
        assert Decimal(str(ledger.events[0].cash_delta)) == Decimal('5805.00')


def apply_yoku(event):
    state, ledger = PortfolioState.fresh(1000), Ledger()
    sid = event['security_id']
    state.slots[8].occupied_by = sid
    state.episodes[8] = HoldingEpisode(security_id=sid, ticker='YOKU', issuer_id='SID:'+sid,
        slot_id=8, signal_date='2016-02-23', entry_date='2016-02-24', entry_raw_open=27.35,
        entry_split_adjusted_price=27.35, initial_shares=231, current_shares=231,
        episode_peak_split_adjusted_close=27.54, market_sessions_held=28)
    result = apply_terminal(state, terminals([event])['2016-04-06'][0], ledger=ledger,
                            session='2016-04-06', cfg=WealthCoreConfig())
    return state, ledger, result


@pytest.mark.parametrize('missing', [False, True])
def test_sourced_yoku_gross_cash_terms_pay_231_ads(missing):
    event = deepcopy(yoku())
    assert event['known_by'] == event['original_event_session'] == '2016-04-05'
    assert event['effective_session'] == '2016-04-06'
    assert 'not claimed' in event['cash_finality_limitation']
    if missing:
        event['cash_per_share'] = ''
    state, ledger, result = apply_yoku(event)
    if missing:
        assert result['applied'] is False
        assert result['reason'] == 'MISSING_CASH_PER_SHARE'
        assert state.cash == 1000 and 8 in state.episodes and not ledger.events
    else:
        assert result['applied'] is True and 8 not in state.episodes
        assert Decimal(str(state.cash)) == Decimal('7375.60')
        assert len(ledger.events) == 1
        assert Decimal(str(ledger.events[0].cash_delta)) == Decimal('6375.60')
        assert ledger.events[0].shares_delta == -231


def test_yoku_altered_consideration_fails_independent_payout_oracle():
    event = deepcopy(yoku())
    event['cash_per_share'] = '27.59'
    _, ledger, result = apply_yoku(event)
    assert result['applied'] is True
    with pytest.raises(AssertionError):
        assert Decimal(str(ledger.events[0].cash_delta)) == Decimal('6375.60')


def itc():
    return json.loads(Path(__file__).with_name('itc-supplement.json').read_text())


def apply_itc(event):
    state, ledger = PortfolioState.fresh(1000), Ledger()
    sid = event['security_id']
    state.slots[3].occupied_by = sid
    state.episodes[3] = HoldingEpisode(security_id=sid, ticker='ITC', issuer_id='SID:'+sid,
        slot_id=3, signal_date='2016-05-02', entry_date='2016-05-03', entry_raw_open=44.46,
        entry_split_adjusted_price=44.46, initial_shares=153, current_shares=153,
        episode_peak_split_adjusted_close=47.22, market_sessions_held=114)
    result = apply_terminal(state, terminals([event])['2016-10-14'][0], ledger=ledger,
        session='2016-10-14', cfg=WealthCoreConfig(), source_signal_to_raw_scale=1.,
        delivered_signal_to_raw_scale=1., delivered_raw_open=31.03)
    return state, ledger, result


def check_itc_oracle(state, ledger):
    ep = state.episodes[3]
    assert ep.security_id == '900440039260292770' and ep.current_shares == 115
    assert ep.market_sessions_held == 114 and ep.entry_date == '2016-05-03'
    assert abs(Decimal(str(state.cash))-Decimal('4454.94768')) < Decimal('0.00000001')
    detail = ledger.events[0].detail
    assert Decimal(str(detail['cash_consideration'])) == Decimal('3453.21')
    assert Decimal(str(detail['cash_in_lieu'])) == Decimal('1.73768')
    package = Decimal('3454.94768') + Decimal(115)*Decimal('31.03')
    scale = Decimal(153)*Decimal('31.03')/package
    assert abs(Decimal(str(ep.episode_peak_split_adjusted_close))-Decimal('47.22')*scale) < Decimal('0.00000001')


def test_itc_sourced_mixed_terms_preserve_slot_age_and_package_references():
    state, ledger, result = apply_itc(itc())
    assert result['applied']
    check_itc_oracle(state, ledger)


@pytest.mark.parametrize('field', ['cash_per_share', 'exchange_ratio',
    'delivered_security_id', 'cash_in_lieu_price_per_delivered_share'])
def test_itc_missing_terms_refuse_without_economic_mutation(field):
    event = itc(); event[field] = ''
    state, ledger, result = apply_itc(event)
    assert not result['applied']
    assert state.cash == 1000 and state.episodes[3].current_shares == 153
    assert not ledger.events


@pytest.mark.parametrize('field,value', [('cash_per_share','22.56'),('exchange_ratio','0.7530')])
def test_itc_altered_terms_fail_independent_oracle(field,value):
    event = itc(); event[field] = value
    state, ledger, result = apply_itc(event)
    assert result['applied']
    with pytest.raises(AssertionError):
        check_itc_oracle(state,ledger)
