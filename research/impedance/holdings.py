"""Actual production breadth and Core stop/sale interface on synthetic ownership."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from sentinel.controller.median5_breadth import breadth
from stock_strategy_shared.wealth_core import median5, v5
from stock_strategy_shared.wealth_core.adapter import step_session
from stock_strategy_shared.wealth_core.engine import SecurityBar
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState


def fixture(damaged=18, damage_price=80.):
    state=PortfolioState.fresh(0.,20)
    state.initialized=True
    state.entry_sizing_profile=v5.PROFILE
    state.median5=median5.fresh()
    series,keys={},{}
    for i in range(20):
        sid=f"S{i:02d}"
        close=damage_price if i<damaged else 110.
        state.slots[i].occupied_by=sid
        state.episodes[i]=HoldingEpisode(sid,sid,"SID:"+sid,i,"0000","0001",
            100.,100.,1,1,episode_peak_split_adjusted_close=max(100.,close),
            market_sessions_held=100,review_completed=True)
        series[sid]=SimpleNamespace(session_indices=list(range(261)),
            signal_closes=[100.]*260+[close])
        keys[sid]=[sid,"0001",sid]
    feed=SimpleNamespace(_session_index=260,series=series)
    # Degenerate, explicitly constant prior market returns produce no peer edges.
    # Individual damage and green rules remain the production rules.
    spy=[[i,100.,0.] for i in range(261)]
    return state,feed,spy,keys


def measure(state,feed,spy,keys):
    b,_=breadth(state,feed,spy,keys)
    damaged={label.ticker for label in b.labels if label.amber}
    values={ep.ticker:ep.current_shares*feed.series[ep.security_id].signal_closes[-1]
            for ep in state.episodes.values()}
    stocks=sum(values.values());nav=stocks+state.cash
    return {"held":b.denominator,"damage_count":b.ambers,"damage_fraction":b.damaged_breadth,
        "green_fraction":b.green_breadth,"damaged_capital_fraction_of_stocks":
            sum(v for k,v in values.items() if k in damaged)/stocks if stocks else 0.,
        "stock_value":stocks,"cash":state.cash,"nav":nav,
        "invested_fraction":stocks/nav if nav else 0.}


def capital_probe():
    state,feed,spy,keys=fixture()
    out={}
    for name,bad_q,good_q in [("tiny_damaged",1,1000),("large_damaged",1000,1)]:
        book=deepcopy(state)
        for i,ep in book.episodes.items():
            ep.current_shares=ep.initial_shares=bad_q if i<18 else good_q
        out[name]=measure(book,feed,spy,keys)
    return out


def turnover_probe():
    state,feed,spy,keys=fixture(10,60.)
    before=measure(state,feed,spy,keys)
    pending,ledger,last_known=[],Ledger(),{}
    results=[]
    for day in ("1000","1001"):
        bars=[];securities=[]
        for sid,s in feed.series.items():
            price=s.signal_closes[-1]
            bars.append(DailyBar(sid,sid,"SID:"+sid,day,price,price,price))
            securities.append(SecurityBar(sid,sid,"SID:"+sid,s.signal_closes,price,False,"SYNTHETIC_HELD_ONLY"))
        result=step_session(session=day,state=state,bars=bars,pending=pending,
            ledger=ledger,last_known=last_known,cfg=v5.config(),
            strategy_id="synthetic-interface-probe",strategy_version=1,security_bars=securities)
        results.append(result)
    after=measure(state,feed,spy,keys)
    return {"before":before,"after":after,
        "first_close_fills":len(results[0].fills),"next_open_fills":len(results[1].fills),
        "fees":sum(e.fees for e in ledger.events),
        "actual_stock_fraction_at_core_multiplier_055":.55*after['invested_fraction'],
        "note":"Prices never recover. Sells move value to cash less fees. Flat prehistory deliberately has no residual peers."}
