"""Source-bound terminal consideration reaches the prior leadership witness."""
import json
import pytest
from tests.support.canonical_economic_book import canonical_two_days
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
def test_complete_cash_terminal_earns_return_before_leaving_sensor(sid, held):
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
        advanced = advance_session(restored,published,controller_config=cfg,strategy_identity=identity)
        assert sid not in advanced.median5['selected']
        assert len(advanced.wealth_core['episodes']) == (19 if held else 20)
        previous = env.median5['witness_nav'][-1]
        assert advanced.median5['witness_nav'][-1] / previous == pytest.approx(1 + .1/25)
        assert restored.to_dict() == before


@pytest.mark.parametrize('kind,expected', [
    (TerminalKind.WRITE_OFF, 0), (TerminalKind.CASH_MERGER, 220),
    (TerminalKind.CONVERSION, 100), (TerminalKind.CASH_PLUS_STOCK, 320)])
def test_terminal_consideration_uses_owned_signal_basis(kind, expected):
    from types import SimpleNamespace
    from sentinel.controller.terminal_returns import values
    prior = SimpleNamespace(median5={'selected':['A']}, last_processed_session='2026-08-12',
        feed={'series':{'A':{'signal_basis_anchor':['2026-08-12', 50, 100]}}})
    terms = TerminalTerms('2026-08-13', 'A', kind, cash_per_share=110,
        delivered_security_id='B', delivered_ticker='BBB', delivered_issuer_id='issuer-B',
        exchange_ratio='0.5', reference='source-terms')
    published = SimpleNamespace(session='2026-08-13', terminal_events=[terms],
        bars=[SimpleNamespace(security_id='B', session='2026-08-13', raw_close=100)])
    assert values(prior=prior, published=published) == {'A': expected}


@pytest.mark.parametrize('damage', ['missing-close', 'stale-close', 'missing-basis', 'duplicate', 'missing-reference'])
def test_terminal_witness_refuses_incomplete_authority(damage):
    from dataclasses import replace
    from types import SimpleNamespace
    from sentinel.controller.terminal_returns import values
    prior = SimpleNamespace(median5={'selected':['A']}, last_processed_session='2026-08-12',
        feed={'series':{'A':{'signal_basis_anchor':['2026-08-12', 50, 100]}}})
    terms = TerminalTerms('2026-08-13', 'A', TerminalKind.CONVERSION,
        delivered_security_id='B', delivered_ticker='BBB', delivered_issuer_id='issuer-B',
        exchange_ratio='0.5', reference='source-terms')
    published = SimpleNamespace(session='2026-08-13', terminal_events=[terms],
        bars=[SimpleNamespace(security_id='B', session='2026-08-13', raw_close=100)])
    if damage == 'missing-close':
        published.bars = []
    elif damage == 'stale-close':
        published.bars[0].session = '2026-08-12'
    elif damage == 'missing-basis':
        prior.feed['series'] = {}
    elif damage == 'duplicate':
        published.terminal_events.append(terms)
    else:
        published.terminal_events = [replace(terms, reference='')]
    with pytest.raises(ValueError):
        values(prior=prior, published=published)
