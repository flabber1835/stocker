from copy import deepcopy
from decimal import Decimal as D
import gzip
import json
from types import SimpleNamespace

import pytest

from sentinel.controller.machine import Controller
from sentinel.core.formation import FormationPlan
from sentinel.core.session import SessionState
from sentinel.feed.rolling_contract import digest
from sentinel.strategy import production_strategy
from .inputs import TARGETS
from .run import FormedAccount, assert_unreachable, checkpoint, restore, verify_economics


def state(day='2006-08-01', target='.55', close='10000'):
    return SimpleNamespace(last_processed_session=day,
        shadow_nav_history=[float(close)],
        last_evidence={'wealth_core': dict(session=day, blocked=False,
            resolved_equity=close, estimated_equity=close, resolved_open_equity='10000',
            open_unresolved_security_ids=[], candidates=[]), 'observation':{'shadow_nav':float(close)}},
        last_decision={'target_core_exposure':target}, median5={'selected':[]},
        wealth_core={'cash':5000, 'episodes':{'0':dict(security_id='A',current_shares=50)}},
        ledger={'events':[]})


def prices(previous='2006-07-31'):
    return dict(bil_open_signal='1',bil_close_signal='1',bil_close_adjusted='1',
        bil_close_unadjusted='1',bil_previous_close_adjusted='1',bil_previous_session=previous)


def prior():
    return dict(strategy_nav='50000',last_session='2006-07-31',pending_allocation='.55',held_allocation=None)


def test_requested_252_plus_126_axis():
    _, identity = production_strategy()
    plan=FormationPlan(end='2006-07-28',strategy=identity,source_sha256='a'*64)
    assert [plan.axis[i] for i in (0,251,252,377)] == [
        '2005-01-28','2006-01-27','2006-01-30','2006-07-28']
    assert plan.capital == '50000'


def test_first_close_does_not_earn_historical_book_appreciation():
    s=state('2006-07-31',close='20000')
    initial=dict(strategy_nav='50000',last_session=None,pending_allocation=None,held_allocation=None)
    result=FormedAccount().advance(previous=initial,state=s,strategy_prices=prices('2006-07-28'))
    assert D(result['strategy_nav']) == 50000
    assert result['held_allocation'] is None and D(result['pending_allocation']) == D('.55')


def test_new_funded_entry_cost_and_next_allocation_cost_are_hand_calculated():
    account=FormedAccount()
    s=state(target='.2')
    before=deepcopy(s.wealth_core)
    result=account.advance(previous=prior(),state=s,strategy_prices=prices(),formed_startup_marks={'A':'100'})
    # 55% Core with half its capital in stock: 27.5% stock + 45% BIL.
    # $50,000 * 0.725 * 0.001 = $36.25 in entry costs, no price movement.
    assert D(result['strategy_nav']) == D('49963.75')
    assert s.wealth_core == before
    pub=SimpleNamespace(bars=[SimpleNamespace(security_id='A',raw_open=100)])
    verify_economics(prior(),result,s,pub)
    next_state=state('2006-08-02',target='.2')
    next_result=account.advance(previous=result,state=next_state,strategy_prices=prices('2006-08-01'))
    # A 35 percentage-point allocation change costs 3.5 bp, charged once.
    assert D(next_result['strategy_nav']) == D('49946.2626875')
    verify_economics(result,next_result,next_state,pub)


def test_lost_formed_entry_mode_is_detected_by_independent_oracle():
    account=FormedAccount()
    account.warmup_input_identity={}
    s=state()
    wrong=account.advance(previous=prior(),state=s,strategy_prices=prices())
    assert D(wrong['strategy_nav']) == D('49977.5')
    pub=SimpleNamespace(bars=[SimpleNamespace(security_id='A',raw_open=100)])
    with pytest.raises(ValueError,match='independent funded accounting'):
        verify_economics(prior(),wrong,s,pub)


@pytest.mark.parametrize('path',['held','witness','scored'])
def test_any_economic_reachability_refuses(path):
    s=state()
    assert_unreachable(s)
    sid=next(iter(TARGETS))
    if path == 'held':
        s.wealth_core['episodes']['1']=dict(security_id=sid,current_shares=1)
    elif path == 'witness':
        s.median5['selected']=[sid]
    else:
        s.last_evidence['wealth_core']['candidates']=[dict(security_id=sid,score=1)]
    with pytest.raises(ValueError,match='economic reachability'):
        assert_unreachable(s)


def test_checkpoint_roundtrip_and_source_change_refusal(tmp_path):
    config, identity=production_strategy()
    s=SessionState.fresh(starting_cash=50000,controller=Controller(config),strategy_identity=identity)
    binding={'source':'a'*64}
    packet=dict(binding=binding,state=s.to_dict(),state_sha256=s.state_hash)
    checkpoint(tmp_path,packet)
    actual, restored=restore(tmp_path/'latest-checkpoint.json',binding)
    assert actual == packet and restored.state_hash == s.state_hash
    with pytest.raises(ValueError,match='binding'):
        restore(tmp_path/'latest-checkpoint.json',{'source':'b'*64})
    pointer=json.loads((tmp_path/'latest-checkpoint.json').read_text())
    with (tmp_path/pointer['path']).open('ab') as f:
        f.write(b'corrupted')
    with pytest.raises(ValueError,match='bytes changed'):
        restore(tmp_path/'latest-checkpoint.json',binding)
