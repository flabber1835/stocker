"""Independent dollar oracles and timing checks for the synthetic comparison."""
import copy
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel.core.kernel import advance_session
from sentinel.strategy import owned_impairment_strategy
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from research.impedance.account import Account, BILL, dec
from research.impedance.pipeline import make_origin


def single_stock():
    book=PortfolioState.fresh(0.,1)
    book.slots[0].occupied_by='S'
    book.episodes[0]=HoldingEpisode('S','S','S',0,'2020-01-01','2020-01-02',10.,10.,100,100)
    return SimpleNamespace(wealth_core=book.to_dict(),ledger=Ledger().to_dict())


def test_whole_share_affordability_and_fees_have_independent_oracle():
    account=Account(cash=Decimal(1000))
    core=single_stock();marks={'S':Decimal(10),BILL:Decimal(100)}
    row=account.rebalance(core,marks,1.)
    assert account.shares=={'S':Decimal(99)}
    assert account.cash==Decimal('9.01')
    assert account.fees==Decimal('.99')
    assert account.nav(marks)==Decimal('999.01')
    assert row['target']==1.
    # Selling 99 shares realizes 990 minus .99; 9 bills cost 900 plus .90.
    account.rebalance(core,marks,0.)
    assert account.shares=={BILL:Decimal(9)}
    assert account.cash==Decimal('97.12')
    assert account.nav(marks)==Decimal('997.12')
    assert Account.restore(account.snapshot()).snapshot()==account.snapshot()


@pytest.fixture(scope='module')
def origin():
    return make_origin(owned_impairment_strategy)


def test_current_close_cannot_change_same_open_account_targets(origin):
    cfg,identity,prior,market,_=origin
    published=copy.deepcopy(market).advance()
    # Same opens/actions, drastically different closes. The kernel can change
    # today's decision and tomorrow's pending intents, not opening ownership.
    changed=replace(published,bars=[replace(b,raw_close=b.raw_close*.8,
                    signal_close=b.signal_close*.8) for b in published.bars])
    states=[advance_session(prior,p,controller_config=cfg,strategy_identity=identity)
            for p in (published,changed)]
    marks={b.security_id:dec(b.raw_open) for b in published.bars} | {BILL:dec(100)}
    accounts=[Account(),Account()]
    for a,s in zip(accounts,states):
        a.rebalance(s,marks,prior.last_decision['target_core_exposure'])
    assert accounts[0].snapshot()==accounts[1].snapshot()
    assert states[0].last_evidence['observation'] != states[1].last_evidence['observation']


def test_broken_current_close_target_would_change_the_timing_test(origin):
    cfg,identity,prior,market,_=origin
    p=copy.deepcopy(market).advance('synchronized_shock',0)
    next_state=advance_session(prior,p,controller_config=cfg,strategy_identity=identity)
    assert next_state.last_decision['target_core_exposure']==0.
    marks={b.security_id:dec(b.raw_open) for b in p.bars} | {BILL:dec(100)}
    proper,lookahead=Account(),Account()
    proper.rebalance(next_state,marks,prior.last_decision['target_core_exposure'])
    lookahead.rebalance(next_state,marks,next_state.last_decision['target_core_exposure'])
    assert proper.snapshot()!=lookahead.snapshot()
