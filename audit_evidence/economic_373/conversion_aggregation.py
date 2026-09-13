"""E1: observe the defect on the pinned canonical kernel; no broker I/O."""
from decimal import Decimal, ROUND_FLOOR
import json
from stock_strategy_shared.wealth_core.adapter import step_session
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms
from stock_strategy_shared.wealth_core.prices import DailyBar

def run_case(lots, cil):
    st = PortfolioState.fresh(10000.0)
    st.initialized = True
    for i, q in enumerate(lots):
        st.slots[i].occupied_by = 'OLD'
        st.episodes[i] = HoldingEpisode('OLD', 'OLD', 'ISSUER_OLD', i,
            '2026-01-02', '2026-01-05', 60., 60., q, q, 60.)
    led = Ledger()
    terms = TerminalTerms(session='2026-09-01', security_id='OLD',
        kind=TerminalKind.CONVERSION, delivered_security_id='NEW',
        delivered_ticker='NEW', delivered_issuer_id='ISSUER_NEW',
        exchange_ratio='0.5', cash_in_lieu_price_per_delivered_share=cil,
        reference='audit/holder-aggregate')
    bars = [DailyBar(security_id=s, ticker=s, issuer_id='ISSUER_'+s,
        session='2026-09-01', signal_close_split_adj_div_unadj=px,
        raw_open=px, raw_mark_close=px, tradeable=True)
        for s, px in [('OLD', 60.), ('NEW', 120.)]]
    res = step_session(session='2026-09-01', state=st, bars=bars, pending=[],
        ledger=led, last_known={'OLD': 60.}, cfg=WealthCoreConfig(),
        strategy_id='audit', strategy_version=1, security_bars=[],
        terminal_terms=[terms])
    exact = Decimal(sum(lots))*Decimal('0.5')
    whole = int(exact.to_integral_value(rounding=ROUND_FLOOR))
    fraction = exact-Decimal(whole)
    return {'lots': lots, 'cil_price': cil,
        'actual_shares': st.shares_by_security(), 'actual_cash': st.cash,
        'actual_open_equity': res.resolved_open_equity,
        'actual_pending_term_sessions': st.terminal_pending_sessions,
        'holder_oracle_shares': whole, 'holder_oracle_fraction': str(fraction),
        'holder_oracle_cash': 10000.+float(fraction)*float(cil or 0),
        'holder_oracle_open_equity': 10000.+float(fraction)*float(cil or 0)+whole*120.}

if __name__ == '__main__':
    cases = [run_case([202], 100.), run_case([101, 101], 100.),
             run_case([202], None), run_case([101, 101], None),
             run_case([1, 1], 100.)]
    print(json.dumps({'finding': 'E1', 'status': 'DEFECT_REPRODUCED',
                      'cases': cases}, indent=2, sort_keys=True))
    assert cases[0]['actual_shares'] == {'NEW': 101}
    assert cases[1]['actual_shares'] == {'NEW': 100}
    assert cases[1]['actual_open_equity'] == cases[0]['actual_open_equity']-20.
    assert cases[3]['actual_shares'] == {'OLD': 202}
    assert cases[3]['actual_pending_term_sessions'] == {'OLD': 0}
    assert cases[4]['actual_shares'] == {}
