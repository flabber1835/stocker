"""E3: real PostgreSQL source predicates -> unchanged canonical accounting."""
import json
import sys
from sentinel.core.terminal import load_terminal_events
from sentinel.feed import store as S
from sentinel.feed.calendar import sessions_in_range
from sentinel.feed.domains import NormalisedBar
from stock_strategy_shared.wealth_core.adapter import step_session
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.feed import VendorBar
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from tests.support.postgres import _EphemeralPostgres

PREV = '2026-08-31'
EVENT = '2026-09-01'
SESSIONS = sessions_in_range(EVENT, '2026-10-01')[:20]


def load(conn, start, end):
    return load_terminal_events(conn, start=start, end=end,
        resolve_with_reason=lambda ticker, session: ('P:'+ticker, None))


def economic_path(conn, broad_window):
    st = PortfolioState.fresh(10000.)
    st.initialized = True
    st.slots[0].occupied_by = 'P:OLD'
    st.episodes[0] = HoldingEpisode('P:OLD', 'OLD', 'ISSUER:OLD', 0,
        '2026-01-02', '2026-01-05', 100., 100., 100, 100, 100.)
    last = {'P:OLD': 100.}
    led = Ledger()
    counters = {}
    daily = []
    pending = []
    for day in SESSIONS:
        loaded = load(conn, PREV if broad_window else day, day)
        events = [t for t in loaded.events if t.session == day]
        bar = DailyBar(security_id='P:KEEP', ticker='KEEP', issuer_id='ISSUER:KEEP',
            session=day, signal_close_split_adj_div_unadj=100., raw_open=100.,
            raw_mark_close=100., tradeable=True)
        result = step_session(session=day, state=st, bars=[bar], pending=pending,
            ledger=led, last_known=last, cfg=WealthCoreConfig(), strategy_id='audit',
            strategy_version=1, security_bars=[], terminal_terms=events,
            settlement_counters=counters)
        if result.terminal_results:
            daily.append({'session': day, 'cash': st.cash,
                          'terminal_results': result.terminal_results})
    return {'cash': st.cash, 'shares': st.shares_by_security(),
            'counters': counters, 'transitions': daily}


def main():
    server = _EphemeralPostgres()
    conn = None
    try:
        server.start()
        conn = S.connect(server.sync_dsn)
        S.migrate_schema(conn)  # Explicit initialization of the fresh audit database.
        S.require_feed_schema(conn)
        bars = [(PREV, 'OLD'), (PREV, 'KEEP')] + [(d, 'KEEP') for d in SESSIONS]
        S.write_bars(conn, [NormalisedBar(close_signal=100., vendor=VendorBar(
            session=d, security_id='P:'+tk, ticker=tk, raw_close=100.,
            raw_open=100., volume=1e6, split_ratio=1., dividend_per_share=0.))
            for d, tk in bars])
        with conn.cursor() as cur:
            cur.execute('INSERT INTO sentinel_actions (ticker,session,action,value,contraticker) VALUES (%s,%s,%s,%s,%s)',
                        ('OLD', EVENT, 'acquisitionby', None, 'NEW'))
            cur.execute('SELECT version()')
            pg_version = cur.fetchone()[0]
        conn.commit()
        whole = load(conn, PREV, EVENT)
        daily = load(conn, EVENT, EVENT)
        broad = economic_path(conn, True)
        narrow = economic_path(conn, False)
        summary = {
            'finding': 'E3', 'status': 'DEFECT_REPRODUCED',
            'baseline': '09dde38d270ad069a006ee3cb458037d42ade316',
            'python': sys.version, 'postgres': pg_version,
            'lookback_load': whole.to_dict(), 'daily_load': daily.to_dict(),
            'broad_window': broad, 'daily_window': narrow,
            'false_loss': broad['cash']-narrow['cash'],
            'scope': 'Real PostgreSQL schema/rows/read predicates -> terminal loader -> canonical session accounting. Full operational readiness and broker execution are separate.'}
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
        assert len(whole.events) == 1 and len(daily.events) == 0
        assert daily.excluded[0].reason == 'SECURITY_ABSENT_FROM_CORPUS'
        assert daily.conservation_holds() and daily.normalized_stream_holds()
        assert not daily.unresolved
        assert broad['cash'] == 20000.
        assert narrow['cash'] == 10000.
        assert narrow['counters']['orphan_zero_writeoffs'] == 1
    finally:
        if conn is not None:
            conn.close()
        server.stop()

if __name__ == '__main__':
    main()
