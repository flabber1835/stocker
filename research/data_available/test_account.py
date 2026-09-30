from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from functools import partial
from unittest.mock import patch
import pytest
from stock_strategy_shared.wealth_core.engine import SecurityBar
from stock_strategy_shared.wealth_core.feed import Feed
from research.data_available.account import Account, propose
from research.data_available.run import Arm
from research.data_available.policy import snapshot_bars
from research.data_available.test_policy import bars, meta, day


def snapshot(n=50):
    bs=[SecurityBar(str(i),'S'+str(i),'SID:'+str(i),[50.]*127,50.,True,'',
                    (.2,.1,.1,50.-i)) for i in range(n)]
    return bs,{b.security_id:[50.]*300 for b in bs}


def test_only_snapshot_and_account_determine_intents():
    bs,windows=snapshot()
    account=Account(cash=D(50_000),equity=D(50_000),positions={})
    sells,buys=propose(bs,windows,account)
    assert sells==[]
    assert [s for s,_ in buys]==[str(i) for i in range(20)]
    assert all(v==D(2500) for _,v in buys)
    assert sum(v for _,v in buys)==account.cash
    assert propose(list(reversed(bs)),windows,account)==(sells,buys)


def test_rank_retention_stop_and_outstanding_orders():
    bs,windows=snapshot()
    account=Account(cash=D(0),equity=D(50_000),positions={'30':D(10),'45':D(10),'46':D(10)},pending={'46'})
    assert propose(bs,windows,account)==(['45'],[])
    windows['30'][0]=100.
    assert propose(bs,windows,account)==(['30','45'],[])


def test_gap_defers_affected_holding_and_unknown_equity_blocks_buys():
    bs,windows=snapshot()
    bs[45]=replace(bs[45],eligible=False,certified_signals=None)
    account=Account(cash=D(50_000),equity=None,positions={'45':D(10)})
    assert propose(bs,windows,account)==([],[])


def test_no_spending_pending_sale_or_reserved_buy_cash():
    bs,windows=snapshot()
    account=Account(cash=D(1000),equity=D(50_000),positions={'45':D(10)},pending={'0'},reserved_cash=D(900))
    sells,buys=propose(bs,windows,account)
    assert sells==['45']
    assert buys==[('1',D(100))]
    assert sum(v for _,v in buys)<=account.cash-account.reserved_cash


def test_terminal_veto_and_stop_prevent_reentry():
    bs,windows=snapshot()
    windows['0'][0]=100.
    account=Account(cash=D(50_000),equity=D(50_000),positions={})
    _,buys=propose(bs,windows,account,{'1'})
    assert '0' not in dict(buys) and '1' not in dict(buys)
    windows['0']=[50.]*300
    assert '0' in dict(propose(bs,windows,account)[1])


def test_account_rule_ignores_episode_age_review_and_cooldown():
    arm=Arm('account300')
    feed=Feed(meta(30)); feed.median5_state=arm.state.median5
    for i in range(300):
        norm=feed.advance(day(i),bars(i,30))
    signals=snapshot_bars(feed,norm.security_bars)
    windows={s:series.signal_closes for s,series in feed.series.items()}
    row=arm.step(day(299),norm,signals,windows=windows)
    assert row['fills']==0 and row['queued']>0
    norm=feed.advance(day(300),bars(300,30))
    signals=snapshot_bars(feed,norm.security_bars)
    windows={s:series.signal_closes[-300:] for s,series in feed.series.items()}
    row=arm.step(day(300),norm,signals,windows=windows)
    assert row['fills']>0
    before=deepcopy(arm.state)
    for e in arm.state.episodes.values():
        e.market_sessions_held=1000
        e.review_completed=False
        e.episode_peak_split_adjusted_close=1e9
    arm.state.security_cooldowns={b.security_id:0 for b in signals}
    # Rule-level inputs deliberately do not include any of those fields.
    def view(state):
        return Account(cash=D(str(state.cash)),equity=D(str(row['equity'])),
            positions={e.security_id:D(str(e.current_shares)) for e in state.episodes.values()},
            pending={o.security_id for o in arm.pending})
    assert propose(signals,windows,view(arm.state))==propose(signals,windows,view(before))
