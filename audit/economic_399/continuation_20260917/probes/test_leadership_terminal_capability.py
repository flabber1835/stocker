"""Audit-only: exact terminal terms do not settle the leadership price sensor."""
import json
from datetime import date
from decimal import Decimal
import pytest
from test_rounded_nav import canonical_two_days
from sentinel.core.session import PublishedSession, SessionState, _feed_from_dict
from sentinel.core.kernel import advance_session
from sentinel.strategy import production_strategy
from sentinel.feed import calendar
from stock_strategy_shared.wealth_core.feed import VendorBar
from stock_strategy_shared.wealth_core.state import PortfolioState
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.live import plan_session
from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core import v5
from stock_strategy_shared.wealth_core.terminal import TerminalTerms, TerminalKind

@pytest.mark.parametrize('sid,held', [('0',True),('5',False)])
def test_complete_cash_terminal_has_no_supported_leadership_return(sid, held):
    env, meta, _stages = canonical_two_days(0.)
    assert sid in env.median5['selected']
    assert any(ep['security_id']==sid for ep in env.wealth_core['episodes'].values()) is held
    session='2026-08-13'
    all_days=calendar.previous_sessions('2026-08-11',253)[:-1]+['2026-08-11','2026-08-12',session]
    spy={d:100+i*.05 for i,d in enumerate(all_days)}
    days=calendar.previous_sessions(session,210)
    term=TerminalTerms(session,sid,TerminalKind.CASH_MERGER,cash_per_share=110.,reference='audit-complete-cash-deal')
    assert term.completeness(10 if held else 0)==(True,'')
    bars=[VendorBar(session=session,security_id=k,ticker=m.ticker,raw_open=100.,raw_close=100.,volume=1e6,signal_close=100.)
          for k,m in meta.items() if k!=sid]
    published=PublishedSession(session,7,bars,meta,{k:'Sector' for k in meta},[spy[d] for d in days],
        spy_sessions=days,spy_expected_sessions=days,terminal_events=(term,))
    # Independent invocation of the same canonical book transition used by the kernel.
    portfolio=PortfolioState.from_dict(env.wealth_core)
    ledger=Ledger.from_dict(env.ledger)
    pending=[PendingOrder.from_dict(p) for p in env.pending]
    plan=plan_session(session=session,bars=bars,meta=meta,state=portfolio,pending=pending,ledger=ledger,
        last_known=dict(env.last_known),feed=_feed_from_dict(env.feed,meta,EligibilityConfig()),
        cfg=v5.config(),terminal_events=(term,))
    assert not plan.blocked
    assert portfolio.cash==(1100. if held else 0.)
    assert len(portfolio.episodes)==(19 if held else 20)
    assert plan.estimated_equity==(20100. if held else 20000.)
    cfg, identity=production_strategy()
    before=json.loads(json.dumps(env.to_dict()))
    for _ in range(2):
        restored=SessionState.from_dict(json.loads(json.dumps(before)))
        with pytest.raises(ValueError,match=f'unresolved recent-leadership return: {session} {sid}'):
            advance_session(restored,published,controller_config=cfg,strategy_identity=identity)
        assert restored.to_dict()==before
    print('TERMINAL SENSOR', {'security':sid,'held':held,'canonical_book_cash':portfolio.cash,
        'canonical_book_nav':plan.estimated_equity,'full_kernel':'unresolved recent-leadership return',
        'restart':'same refusal; prior state unchanged'})
