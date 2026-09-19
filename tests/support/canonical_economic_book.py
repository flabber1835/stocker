"""A warmed canonical book with admissions, fills and JSON restart boundaries."""
from decimal import Decimal
from sentinel.strategy import production_strategy
from sentinel.controller.machine import Controller
from sentinel.core.session import SessionState, PublishedSession
from sentinel.core.production import warm_session_state
from sentinel.core.kernel import advance_session
from sentinel.core.loader import CorpusWindow
from sentinel.feed import calendar
from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar
import json


def canonical_two_days(close_adjustment):
    d1, d2 = '2026-08-11', '2026-08-12'
    hist = calendar.previous_sessions(d1, 253)[:-1]
    meta = {str(i): SecurityMeta(str(i), f'T{i}', 'Common Stock', str(i), first_session=hist[0]) for i in range(25)}
    bars = {s: [VendorBar(s, sid, m.ticker, 100-(252-k)*.2, 100-(252-k)*.2, 1e6,
                         signal_close=100-(252-k)*.2) for sid,m in meta.items()] for k,s in enumerate(hist)}
    window = CorpusWindow(hist, bars, meta)
    spy = {s: 100+k*.05 for k,s in enumerate(hist)}
    spy[d1] = 112.6; spy[d2] = 112.65
    window.median5_spy_closes = spy
    window.median5_terminals = {}
    cfg, identity = production_strategy()
    from sentinel.shadow_runtime import _starting_cash
    assert _starting_cash('20020') == Decimal(20020)
    env = SessionState.fresh(starting_cash=20020., controller=Controller(cfg), strategy_identity=identity)
    env = warm_session_state(env, window, publication_version=7, prospective_concordance_witness=True)
    stages = []
    for d in (d1,d2):
        days = calendar.previous_sessions(d, 210)
        p = PublishedSession(session=d, data_version=7,
            bars=[VendorBar(session=d,security_id=sid,ticker=m.ticker,raw_open=100.,
                            raw_close=100.+(close_adjustment if d==d2 and sid=='0' else 0),volume=1e6,
                            signal_close=100.+(close_adjustment if d==d2 and sid=='0' else 0)) for sid,m in meta.items()],
            meta=meta, sectors={sid:'Sector' for sid in meta}, spy_sessions=days,
            spy_expected_sessions=days, spy_closeadj=[spy[s] for s in days])
        prior = env.to_dict()
        env = advance_session(env,p,controller_config=cfg,strategy_identity=identity)
        assert prior == SessionState.from_dict(prior).to_dict()
        env = SessionState.from_dict(json.loads(json.dumps(env.to_dict())))
        stages.append(env)
        print(d, 'cash',env.wealth_core['cash'],'episodes', len(env.wealth_core['episodes']),
              'pending',len(env.pending), 'nav',env.shadow_nav_history[-1],
              'estimated',env.last_evidence['wealth_core']['estimated_equity'],
              'exposure',env.last_decision['target_core_exposure'])
    return env, meta, stages
