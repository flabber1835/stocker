#!/usr/bin/env python3
"""Canonical research execution transform for 10 bp + next-open whole-share sizing.

This is the single active execution harness for future research on this lineage.
Stock-selection overlays (for example Median-5) are applied before this transform.
Historical harness branches remain immutable evidence and are not execution authority.
"""
from __future__ import annotations

CONTRACT_VERSION = "wealth-core.open-time-whole-shares-10bp/2"
BUFFER_FRACTION = 0.001
BUFFER_BASIS_POINTS = 10.0


def _replace_between(src: str, start: str, end: str, replacement: str, label: str) -> str:
    if src.count(start) != 1:
        raise RuntimeError(f"{label} start seam mismatch: {src.count(start)}")
    i = src.index(start)
    j = src.index(end, i)
    return src[:i] + replacement + src[j:]


def apply_open_time_whole_share_10bp(src: str) -> str:
    """Apply the canonical execution contract to a frozen 10 bp source.

    Close:
      * bind ticker + intended dollar target only;
      * retain 10 bp admission cushion;
      * require that cash above the cushion can afford at least one whole share
        at the known close price including modeled cost;
      * do not bind share quantity.

    Next valid open:
      * release the admission cushion into the funding pool;
      * determine whole-share quantity from actual open price and actual cash;
      * keep zero-quantity and invalid-market guards for overnight edge cases.
    """
    init_old = (
        "rows=[]; trade_rows=[]; gap_event_rows=[]; close_decision_rows=[]; _pending_meta={}; "
        "overlap_checks={}; buys=sells=split_events=div_events=0; scale_q0_candidate_skips=0; "
        "scale_one_share_entries=0; scale_cash_limited_decisions=0; scale_gap_clipped_entries=0; "
        "scale_entries=0; scale_lt1=0; scale_lt5=0; scale_lt10=0; scale_lt25=0; scale_lt50=0; "
        "scale_lt99=0; scale_min_entry_fraction=1.0; scale_max_entry_fraction=0.0; "
        "scale_entry_fraction_sum=0.0; buffer_blocked_open_entries=0; "
        "buffer_min_post_buy_excess=float('inf'); buffer_min_actual_cash=float(book.cash); "
        "buffer_reserve_violations=0"
    )
    init_new = init_old + (
        "; open_sizing_event_rows=[]; open_close_admissions=0; open_invalid_market_blocks=0; "
        "open_zero_quantity_blocks=0; open_cash_limited_execs=0; open_rounding_underfill_dollars=0.0; "
        "open_rounding_underfill_fraction_sum=0.0; open_full_target_execs=0; open_partial_target_execs=0; "
        "open_close_cash_scarcity_skips=0; open_close_whole_share_unaffordable_skips=0"
    )
    if src.count(init_old) != 1:
        raise RuntimeError(f"init seam mismatch: {src.count(init_old)}")
    src = src.replace(init_old, init_new, 1)

    open_start = (
        "            for s in book.slots:\n"
        "                if not(s.reserved() and not s.held()): continue\n"
        "                tid=s.pending_tid; px=opraw[tid]\n"
    )
    open_end = "            for _tid0,_sig_close,_raw_close,_reported_volume in zip(tids,c,cu,vol):\n"
    open_replacement = '''            for s in book.slots:\n                if not(s.reserved() and not s.held()): continue\n                tid=s.pending_tid; px=opraw[tid]; _pm=_pending_meta.get(id(s),{})\n                _desired=float(s.pending_intended_capital); _cash_before=float(book.cash)\n                if finite(px) and px>0 and finite(volume[tid]) and volume[tid]>0:\n                    _execution_budget=max(0.0,min(_desired,_cash_before)); q=float(math.floor(_execution_budget/(float(px)*(1+COST)))) if _execution_budget>0 else 0.0\n                    if q>1e-12:\n                        _gross=float(q)*float(px)*(1+COST); _frac=(_gross/_desired if _desired>0 else 0.0)\n                        _cash_limited=bool(_cash_before+1e-8<_desired); _rounding=max(0.0,_execution_budget-_gross)\n                        _round_frac=(_rounding/_execution_budget if _execution_budget>0 else 0.0)\n                        scale_entries+=1; scale_one_share_entries+=int(abs(q-1.0)<=1e-9); scale_entry_fraction_sum+=_frac; scale_min_entry_fraction=min(scale_min_entry_fraction,_frac); scale_max_entry_fraction=max(scale_max_entry_fraction,_frac); scale_lt1+=int(_frac<0.01); scale_lt5+=int(_frac<0.05); scale_lt10+=int(_frac<0.10); scale_lt25+=int(_frac<0.25); scale_lt50+=int(_frac<0.50); scale_lt99+=int(_frac<0.99)\n                        open_cash_limited_execs+=int(_cash_limited); open_rounding_underfill_dollars+=_rounding; open_rounding_underfill_fraction_sum+=_round_frac; open_full_target_execs+=int(abs(_gross-_desired)<=max(1e-8,1e-10*_desired)); open_partial_target_execs+=int(abs(_gross-_desired)>max(1e-8,1e-10*_desired))\n                        open_sizing_event_rows.append({'decision_date':str(_pm.get('decision_date','')),'execution_date':ds,'ticker':str(tick[tid]),'mode':'whole','close_price':float(_pm.get('close_price',np.nan)),'open_price':float(px),'intended_target_dollars':_desired,'cash_before_execution':_cash_before,'execution_budget':_execution_budget,'executed_shares':float(q),'executed_gross_dollars':_gross,'entry_fraction_of_intended':_frac,'cash_limited_at_open':_cash_limited,'rounding_underfill_dollars':_rounding,'rounding_underfill_fraction':_round_frac,'close_required_10bp_cushion':float(_pm.get('close_required_reserve',np.nan)),'close_cash_above_cushion':float(_pm.get('close_uncommitted_cash',np.nan)),'blocked':False,'block_reason':''})\n                        book.cash-=_gross; buffer_min_actual_cash=min(buffer_min_actual_cash,float(book.cash)); buffer_min_post_buy_excess=min(buffer_min_post_buy_excess,float(book.cash)); trade_rows.append({'Transaction date':ds,'Buy or sell':'BUY','Ticker':str(tick[tid]),'Ticker name':'','Amount of shares':float(q)}); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1\n                    else:\n                        open_zero_quantity_blocks+=1; buffer_blocked_open_entries+=1; open_sizing_event_rows.append({'decision_date':str(_pm.get('decision_date','')),'execution_date':ds,'ticker':str(tick[tid]),'mode':'whole','close_price':float(_pm.get('close_price',np.nan)),'open_price':float(px),'intended_target_dollars':_desired,'cash_before_execution':_cash_before,'execution_budget':_execution_budget,'executed_shares':0.0,'executed_gross_dollars':0.0,'entry_fraction_of_intended':0.0,'cash_limited_at_open':bool(_cash_before+1e-8<_desired),'rounding_underfill_dollars':_execution_budget,'rounding_underfill_fraction':1.0 if _execution_budget>0 else 0.0,'close_required_10bp_cushion':float(_pm.get('close_required_reserve',np.nan)),'close_cash_above_cushion':float(_pm.get('close_uncommitted_cash',np.nan)),'blocked':True,'block_reason':'ZERO_QUANTITY_AT_OPEN'})\n                else:\n                    open_invalid_market_blocks+=1; buffer_blocked_open_entries+=1; open_sizing_event_rows.append({'decision_date':str(_pm.get('decision_date','')),'execution_date':ds,'ticker':str(tick[tid]),'mode':'whole','close_price':float(_pm.get('close_price',np.nan)),'open_price':float(px) if finite(px) else np.nan,'intended_target_dollars':_desired,'cash_before_execution':_cash_before,'execution_budget':0.0,'executed_shares':0.0,'executed_gross_dollars':0.0,'entry_fraction_of_intended':0.0,'cash_limited_at_open':False,'rounding_underfill_dollars':0.0,'rounding_underfill_fraction':0.0,'close_required_10bp_cushion':float(_pm.get('close_required_reserve',np.nan)),'close_cash_above_cushion':float(_pm.get('close_uncommitted_cash',np.nan)),'blocked':True,'block_reason':'INVALID_OPEN_MARKET'})\n                _pending_meta.pop(id(s),None); s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_intended_capital=0.\n'''
    src = _replace_between(src, open_start, open_end, open_replacement, "open execution")

    close_start = "                        _desired=float(eq*ENTRY_W); _buffer_required_close=max(0.0,float(eq)*0.001);"
    close_end = "            buffer_min_actual_cash=min(buffer_min_actual_cash,float(book.cash)); shadow_dates.append(date);"
    close_replacement = '''                        _desired=float(eq*ENTRY_W); _buffer_required_close=max(0.0,float(eq)*0.001); _buffer_available_close=max(0.0,float(book.cash)-_buffer_required_close); _funding_fraction=(float(min(_desired,_buffer_available_close))/_desired if _desired>0 else 0.0)\n                        if _buffer_available_close<=1e-12: scale_q0_candidate_skips+=1; open_close_cash_scarcity_skips+=1; close_decision_rows.append({'decision_date':ds,'ticker':str(tick[tid]),'outcome':'Q0_SKIP','planned_shares':0,'close_price':float(px),'close_nav':float(eq),'cash_before_decision':float(book.cash),'required_reserve':float(_buffer_required_close),'uncommitted_cash_after_reserve':float(_buffer_available_close),'intended_capital':float(_desired),'funding_fraction':float(_funding_fraction),'q0_reason':'CASH_SCARCITY','buffer_basis_points':10}); continue\n                        _one_share_close_cost=float(px)*(1+COST)\n                        if _buffer_available_close+1e-12<_one_share_close_cost: scale_q0_candidate_skips+=1; open_close_whole_share_unaffordable_skips+=1; close_decision_rows.append({'decision_date':ds,'ticker':str(tick[tid]),'outcome':'Q0_SKIP','planned_shares':0,'close_price':float(px),'close_nav':float(eq),'cash_before_decision':float(book.cash),'required_reserve':float(_buffer_required_close),'uncommitted_cash_after_reserve':float(_buffer_available_close),'intended_capital':float(_desired),'funding_fraction':float(_funding_fraction),'q0_reason':'WHOLE_SHARE_UNAFFORDABLE_AT_CLOSE','buffer_basis_points':10}); continue\n                        scale_cash_limited_decisions+=int(_funding_fraction<0.999999999); close_decision_rows.append({'decision_date':ds,'ticker':str(tick[tid]),'outcome':'PLAN_OPEN_SIZE','planned_shares':0,'close_price':float(px),'close_nav':float(eq),'cash_before_decision':float(book.cash),'required_reserve':float(_buffer_required_close),'uncommitted_cash_after_reserve':float(_buffer_available_close),'intended_capital':float(_desired),'funding_fraction':float(_funding_fraction),'q0_reason':'','buffer_basis_points':10})\n                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=0.; s.pending_signal_day=gday; s.pending_intended_capital=_desired; _pending_meta[id(s)]={'decision_date':ds,'close_price':float(px),'close_nav':float(eq),'close_cash_before':float(book.cash),'close_required_reserve':float(_buffer_required_close),'close_uncommitted_cash':float(_buffer_available_close),'intended_capital':float(_desired)}; open_close_admissions+=1; resids.add(tid); resissuers.add(issuer_key(tid,ds)); ad+=1\n'''
    src = _replace_between(src, close_start, close_end, close_replacement, "close admission")

    csv_marker = "    pd.DataFrame(close_decision_rows,columns=['decision_date','ticker','outcome','planned_shares','close_price','close_nav','cash_before_decision','required_reserve','uncommitted_cash_after_reserve','intended_capital','funding_fraction','q0_reason','buffer_basis_points']).to_csv(OUT/'close-decisions.csv',index=False)\n"
    csv_insert = csv_marker + "    pd.DataFrame(open_sizing_event_rows,columns=['decision_date','execution_date','ticker','mode','close_price','open_price','intended_target_dollars','cash_before_execution','execution_budget','executed_shares','executed_gross_dollars','entry_fraction_of_intended','cash_limited_at_open','rounding_underfill_dollars','rounding_underfill_fraction','close_required_10bp_cushion','close_cash_above_cushion','blocked','block_reason']).to_csv(OUT/'open-sizing-events.csv',index=False)\n"
    if src.count(csv_marker) != 1:
        raise RuntimeError("CSV marker mismatch")
    src = src.replace(csv_marker, csv_insert, 1)

    telemetry_marker = "    print(json.dumps(summary,indent=2),flush=True)\n"
    telemetry = '''    _open_telemetry={'schema':'research.canonical-open-time-whole-shares-10bp/2','mode':'whole','buffer_basis_points':10,'buffer_fraction':0.001,'buffer_role':'CLOSE_TIME_ADMISSION_CUSHION_RELEASED_AT_OPEN','close_admission_rule':'REQUIRE_ONE_WHOLE_SHARE_AFFORDABLE_AT_CLOSE_ABOVE_10BP_RESERVE','close_admission_rule_is_quantity_binding':False,'close_admissions':int(open_close_admissions),'completed_entries':int(scale_entries),'close_q0_total':int(scale_q0_candidate_skips),'close_q0_cash_scarcity':int(open_close_cash_scarcity_skips),'close_q0_whole_share_unaffordable':int(open_close_whole_share_unaffordable_skips),'next_open_blocks':int(open_invalid_market_blocks+open_zero_quantity_blocks),'invalid_open_market_blocks':int(open_invalid_market_blocks),'zero_quantity_blocks':int(open_zero_quantity_blocks),'cash_limited_open_executions':int(open_cash_limited_execs),'rounding_underfill_dollars_total':float(open_rounding_underfill_dollars),'average_rounding_underfill_fraction':float(open_rounding_underfill_fraction_sum/scale_entries) if scale_entries else None,'full_target_executions':int(open_full_target_execs),'partial_target_executions':int(open_partial_target_execs),'minimum_actual_cash':float(buffer_min_actual_cash),'fractional_shares_allowed':False,'all_admitted_trades_executed':bool(open_invalid_market_blocks+open_zero_quantity_blocks==0)}\n    (OUT/'open-sizing-telemetry.json').write_text(json.dumps(_open_telemetry,indent=2,sort_keys=True))\n    print(json.dumps(summary,indent=2),flush=True)\n'''
    if src.count(telemetry_marker) != 1:
        raise RuntimeError("telemetry marker mismatch")
    src = src.replace(telemetry_marker, telemetry, 1)

    required = (
        "_one_share_close_cost=float(px)*(1+COST)",
        "WHOLE_SHARE_UNAFFORDABLE_AT_CLOSE",
        "q=float(math.floor(_execution_budget/(float(px)*(1+COST))))",
        "close_admission_rule_is_quantity_binding':False",
    )
    for marker in required:
        if src.count(marker) != 1:
            raise RuntimeError(f"canonical execution marker missing/duplicated: {marker}")
    compile(src, "<canonical-open-time-whole-share-10bp>", "exec")
    return src
