#!/usr/bin/env python3
"""Median-5 + 10bp pure Wealth Core overlay for the frozen full-PIT harness."""
from __future__ import annotations

import ast

ARMS = ("MEDIAN5_10BP_PURE",)
BUFFER_FRACTION = 0.001
BASE_MEDIAN5_RAW_SHA256 = "3b1bb12dc4f246dc855c135bce04f97cef79a38c9bd81245c543b733c492290b"


def _replace_exact(text: str, old: str, new: str, count: int, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"{label}: expected {count} exact occurrence(s), got {actual}")
    return text.replace(old, new, count)


def median5_only(text: str) -> str:
    text = _replace_exact(text, "N_SLOTS = 25", "N_SLOTS = 20", 1, "Median-5 capacity")
    text = _replace_exact(text, "ENTRY_W = 0.04", "ENTRY_W = 0.05", 1, "Median-5 entry weight")
    helper = '''
    def _hard_rank(_tid,_order):
        try: return _order.index(int(_tid))
        except ValueError: return len(_order)+1000

    def _median_top3(_durable,_hist,_lookback):
        _arr=[int(x) for x in _durable]
        if len(_arr)<2: return np.asarray(_arr,dtype=np.int32)
        _top=_arr[:3]; _hs=_hist[-int(_lookback):]
        def _key(_tid):
            _vals=[_hard_rank(_tid,_o) for _o in _hs]
            return (float(np.median(_vals)),_arr.index(_tid))
        _front=sorted(_top,key=_key)
        return np.asarray(_front+_arr[3:],dtype=np.int32)

    def _harden_order(_durable,_score,_hist):
        return _median_top3(_durable,_hist,5)
'''
    marker = "    ctl=ControlLDRC(); ca=CandidateA(); cb=CandidateB()"
    text = _replace_exact(text, marker, helper + "\n" + marker, 1, "Median-5 helper insertion")
    init = "    shadow_dates=[]; shadow_eq=[]; damaged_hist=[]; stop_days=[]"
    text = _replace_exact(text, init, init + "\n    _rank_order_hist=[]", 1, "Median-5 history initialization")
    hist_marker = "            inpool=np.zeros(n,bool); inpool[pool]=True"
    hist_code = (
        "            _rank_order_hist.append(tuple(int(x) for x in durable))\n"
        "            if len(_rank_order_hist)>5: del _rank_order_hist[:-5]\n"
        + hist_marker
    )
    text = _replace_exact(text, hist_marker, hist_code, 1, "Median-5 causal rank-history update")
    text = _replace_exact(
        text,
        "                    for tid0 in durable:",
        "                    for tid0 in _harden_order(durable,score,_rank_order_hist):",
        1,
        "Median-5 admission seam",
    )
    return text


def _pure_10bp(text: str) -> str:
    text = _replace_exact(text, "COST = 0.001", "COST = 0.001\nBUFFER_FRACTION = 0.001", 1, "10bp constant")
    text = _replace_exact(text, "    actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()",
                          "    actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book()", 1, "native controller instance")
    text = _replace_exact(text, "    ctl=ControlLDRC(); ca=CandidateA(); cb=CandidateB()\n", "", 1, "EX3 controller instances")
    text = _replace_exact(text, "    recent_nav=1.; recent_nav_hist=[1.]; prior_recent_sel=tuple(); prior_close_map={}\n", "", 1, "leadership state")
    text = _replace_exact(text,
                          "    pending_native=1.; effective_native=1.\n    pend={'control':1.,'A':1.,'B':1.}; eff={'control':1.,'A':1.,'B':1.}\n    navs={'control':1.,'A':1.,'B':1.}; transition_cost={'control':0.,'A':0.,'B':0.}; transitions={'control':0,'A':0,'B':0}\n    prev_close_eq=None; prev_perf_date=None\n",
                          "    prev_close_eq=None; prev_perf_date=None\n", 1, "controller portfolio state")
    start = "            # Causal recent-leadership witness: prior close selection earns current close-to-close return.\n"
    end = "            if ds in ('2008-12-23','2022-01-03'):\n                overlap_checks[ds]={'eligible':int(len(et)),'population':int(nk),'overlap':int(len(set(map(int,pool))&set(map(int,recsel))))}\n\n"
    i = text.index(start); j = text.index(end, i) + len(end)
    text = text[:i] + "            # Exposure-controller recent-leadership witness intentionally omitted.\n\n" + text[j:]
    text = _replace_exact(text,
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0",
        "    rows=[]; trade_rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0\n"
        "    buffer_q0_candidate_skips=0; buffer_cash_limited_decisions=0; buffer_blocked_open_entries=0; buffer_gap_clipped_entries=0; buffer_one_share_entries=0\n"
        "    buffer_reserve_violations=0; buffer_min_post_buy_excess=float('inf'); buffer_min_cash=float(book.cash)",
        1, "telemetry initialization")
    text = _replace_exact(text,
        "                    book.cash+=s.qty*float(px)*(1-COST); sells+=1",
        "                    _sell_qty=float(s.qty); _sell_tid=int(s.tid); book.cash+=s.qty*float(px)*(1-COST); sells+=1\n"
        "                    trade_rows.append({'Transaction date':ds,'Buy or sell':'SELL','Ticker':str(tick[_sell_tid]),'Ticker name':'','Amount of shares':_sell_qty})",
        1, "sell ledger")
    text = _replace_exact(text,
        "                    afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford)\n"
        "                    if q>=1:\n"
        "                        book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1",
        "                    _planned_q=int(round(s.pending_shares)); _buffer_required=max(0.0,float(open_eq)*BUFFER_FRACTION); _buffer_available=max(0.0,book.cash-_buffer_required); afford=math.floor(_buffer_available/(float(px)*(1+COST))); q=min(_planned_q,afford)\n"
        "                    buffer_blocked_open_entries+=int(_planned_q>=1 and q<1)\n"
        "                    if q>=1:\n"
        "                        _gross=float(q)*float(px)*(1+COST); buffer_gap_clipped_entries+=int(q<_planned_q); buffer_one_share_entries+=int(q==1); book.cash-=_gross; buffer_min_post_buy_excess=min(buffer_min_post_buy_excess,book.cash-_buffer_required); buffer_reserve_violations+=int(book.cash+1e-9<_buffer_required); trade_rows.append({'Transaction date':ds,'Buy or sell':'BUY','Ticker':str(tick[tid]),'Ticker name':'','Amount of shares':float(q)}); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1",
        1, "next-open 10bp affordability")
    text = _replace_exact(text,
        "                        target=min(eq*ENTRY_W,book.cash); q=int(target//(float(px)*(1+COST)))\n"
        "                        if q<1: continue",
        "                        _desired=float(eq*ENTRY_W); _buffer_required_close=max(0.0,float(eq)*BUFFER_FRACTION); _buffer_available_close=max(0.0,book.cash-_buffer_required_close); target=min(_desired,_buffer_available_close); buffer_cash_limited_decisions+=int(target<_desired-1e-12); q=int(target//(float(px)*(1+COST)))\n"
        "                        if q<1: buffer_q0_candidate_skips+=1; continue",
        1, "decision-close 10bp affordability")
    start = "            held=[]\n"; end = "            green_b,dam_b=dynamic_peer_breadth(held,gday,close_ring,spy,shadow_dates)\n"
    i = text.index(start); j = text.index(end, i) + len(end)
    text = text[:i] + "            _held_count=sum(1 for s in book.slots if s.held())\n" + text[j:]
    start = "            shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)\n"; end = "            b_d,b_reason=cb.step(native_target,recent_r20,spy20)\n"
    i = text.index(start); j = text.index(end, i) + len(end)
    text = text[:i] + "            shadow_dates.append(date); shadow_eq.append(eq)\n" + text[j:]
    start = "            if date in _quarter_last and date < START:\n"; end = "            pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d\n"
    i = text.index(start); j = text.index(end, i) + len(end)
    replacement = '''            if date in _quarter_last and date < START:
                print(f'[CERT_PROGRESS] role=wealth_core date={ds} phase=WARMUP cagr=N/A',flush=True)
            if date>=START:
                spy_nav=np.nan
                if date in spy.index and START in spy.index:
                    spy_nav=float(spy.loc[date,'closeadj'])/float(spy.loc[START,'closeadj'])
                _rank_ids=[str(sid[int(x)]) for x in durable]
                _position_ids=sorted(str(sid[int(s.tid)]) for s in book.slots if s.held())
                _rank_hash=hashlib.sha256(json.dumps(_rank_ids,separators=(',',':')).encode()).hexdigest()
                _position_hash=hashlib.sha256(json.dumps(_position_ids,separators=(',',':')).encode()).hexdigest()
                rows.append({'date':date,'shadow_equity':eq,'open_equity':open_eq,'spy_nav':spy_nav,'held_count':int(_held_count),'research_eligible_universe':int(len(et)),'research_ranking_count':int(len(durable)),'research_ranking_sha256':_rank_hash,'research_selected_positions_sha256':_position_hash,'research_selected_positions':json.dumps(_position_ids,separators=(',',':'))})
                buffer_min_cash=min(buffer_min_cash,float(book.cash))
                if date in _quarter_last:
                    _curve_now=pd.Series([float(r['shadow_equity']) for r in rows],index=pd.to_datetime([r['date'] for r in rows]))
                    _elapsed=(date-START).days/365.2425
                    _cc=0.0 if _elapsed<=0 else float(_curve_now.iloc[-1]/_curve_now.iloc[0])**(1.0/_elapsed)-1.0
                    print(f'[CERT_CAGR] role=wealth_core date={ds} cagr={_cc:.12f}',flush=True)
                prev_perf_date=date; prev_close_eq=eq
'''
    text = text[:i] + replacement + text[j:]
    text = _replace_exact(text,
        "        if rows:\n            _curve=pd.Series([float(r['control_nav']) for r in rows], index=pd.to_datetime([r['date'] for r in rows]))",
        "        if rows:\n            _curve=pd.Series([float(r['shadow_equity']) for r in rows], index=pd.to_datetime([r['date'] for r in rows]))", 1, "year-end pure Wealth Core curve")
    text = _replace_exact(text,
        "        'metrics':{k:metrics(idx[f'{k}_nav']) for k in ('control','A','B')},\n"
        "        'spy':metrics(idx['spy_nav'].dropna()),\n"
        "        'transition_counts':transitions,\n"
        "        'modeled_allocation_transition_cost_sum':transition_cost,\n"
        "        'buys':buys,'sells':sells,'split_events_applied':split_events,'dividend_events_held':div_events,\n"
        "        'leadership_overlap_checks':overlap_checks,\n"
        "        'candidate_A_episodes':ca.episodes,'candidate_A_concordance_releases':ca.concordance_releases,'candidate_B_episodes':cb.episodes,'correlation_peer_stats':PEER_STATS,\n",
        "        'wealth_core':metrics(idx['shadow_equity']),\n"
        "        'spy':metrics(idx['spy_nav'].dropna()),\n"
        "        'buys':buys,'sells':sells,'split_events_applied':split_events,'dividend_events_held':div_events,\n"
        "        'cash_buffer_basis_points':10.0,'cash_buffer_fraction':BUFFER_FRACTION,'fractional_share_buys':False,\n"
        "        'buffer_telemetry':{'q0_candidate_skips':buffer_q0_candidate_skips,'cash_limited_decisions':buffer_cash_limited_decisions,'blocked_open_entries':buffer_blocked_open_entries,'gap_clipped_entries':buffer_gap_clipped_entries,'one_share_entries':buffer_one_share_entries,'reserve_violations':buffer_reserve_violations,'minimum_post_buy_cash_excess_over_buffer':(None if buffer_min_post_buy_excess==float('inf') else buffer_min_post_buy_excess),'minimum_cash':buffer_min_cash},\n"
        "        'sentinel_metrics_used':False,'ex3_metrics_used':False,\n", 1, "pure Wealth Core summary")
    text = _replace_exact(text,
        "    (OUT/'summary.json').write_text(json.dumps(summary,indent=2))",
        "    (OUT/'summary.json').write_text(json.dumps(summary,indent=2))\n"
        "    pd.DataFrame(trade_rows,columns=['Transaction date','Buy or sell','Ticker','Ticker name','Amount of shares']).to_csv(OUT/'transactions.csv',index=False)", 1, "transaction ledger write")
    return text


def apply_arm(text: str, arm: str) -> str:
    if arm != "MEDIAN5_10BP_PURE": raise ValueError(arm)
    median = median5_only(text); out = _pure_10bp(median); ast.parse(out); assert_arm_contract(text, median, out, arm); return out


def assert_arm_contract(base: str, median: str, variant: str, arm: str) -> None:
    if arm != "MEDIAN5_10BP_PURE": raise ValueError(arm)
    for invariant in (
        "N_SLOTS = 20", "ENTRY_W = 0.05", "COOLDOWN = 21", "REVIEW_AGE = 119", "STOP_RET = 0.70", "COST = 0.001",
        "MIN_ADV20 = 20_000_000.0", "MIN_DAY_DV = 5_000_000.0", "return _median_top3(_durable,_hist,5)",
        "for tid0 in _harden_order(durable,score,_rank_order_hist):", "BUFFER_FRACTION = 0.001", "book.receivables.append((gday+1,q*rawdiv))",
        "_buffer_required_close=max(0.0,float(eq)*BUFFER_FRACTION)", "_buffer_required=max(0.0,float(open_eq)*BUFFER_FRACTION)",
        "'sentinel_metrics_used':False", "'ex3_metrics_used':False"):
        if invariant not in variant: raise RuntimeError(f"required invariant missing: {invariant}")
    if variant.count("book.receivables.append((gday+1,q*rawdiv))") != 1: raise RuntimeError("one-session dividend schedule changed")
    if "gday+15" in variant: raise RuntimeError("15-session dividend lag present")
    for forbidden_call in ("native.step(", "ctl.step(", "ca.step(", "cb.step(", "apply_overlay(navs"):
        if forbidden_call in variant: raise RuntimeError(f"exposure controller still executes: {forbidden_call}")
    if variant.count("q=int(target//(float(px)*(1+COST)))") != 1: raise RuntimeError("whole-share decision sizing changed")
    if variant.count("afford=math.floor(_buffer_available/(float(px)*(1+COST)))") != 1: raise RuntimeError("whole-share open affordability changed")


def arm_dimensions(arm: str) -> list[str]:
    if arm != "MEDIAN5_10BP_PURE": raise ValueError(arm)
    return ["median5", "cash_buffer_10bp", "whole_shares", "pure_wealth_core", "no_ex3", "no_sentinel", "fullpit"]
