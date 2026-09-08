#!/usr/bin/env python3
"""Observer-only Wealth Core audit transform for the broad-PIT V1/V2 replay."""
from __future__ import annotations


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {n}")
    return text.replace(old, new, 1)


def replace_one_of(text: str, olds: tuple[str, ...], new_prefix: str, label: str) -> str:
    hits = [(old, text.count(old)) for old in olds if text.count(old)]
    exact = [old for old, n in hits if n == 1]
    if len(exact) != 1 or any(n != 1 for _, n in hits):
        raise RuntimeError(f"{label}: expected exactly one known source seam, found {hits}")
    old = exact[0]
    return text.replace(old, new_prefix + old, 1)


def install(text: str, *, variant: str) -> str:
    if variant not in {"V1", "V2"}:
        raise ValueError(variant)

    init_v1 = "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0"
    init_v2 = "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; slot_v2_reserved=slot_v2_rejected=slot_v2_gap_clipped=slot_v2_gap_cancelled=0"
    hits = [x for x in (init_v1, init_v2) if text.count(x) == 1]
    if len(hits) != 1:
        raise RuntimeError(f"observer init seam count={len(hits)}")
    init = hits[0]

    observer_init = '''
    # OBSERVER ONLY: never read by strategy decisions or controller state.
    audit_variant=__VARIANT__
    audit_orders=[]; audit_positions=[]; audit_live={}; audit_daily=[]
    audit_pending_buy={}; audit_pending_sell={}
    audit_order_seq=0; audit_episode_seq=0; audit_last_session=None

    def _audit_issue(side, issued_session, slot_id, tid, shares, reason, reserved_cash=None):
        nonlocal audit_order_seq
        audit_order_seq+=1
        audit_orders.append({
            'order_seq':audit_order_seq,'variant':audit_variant,'side':side,
            'issued_session':issued_session,'slot_id':int(slot_id),
            'security_id':str(sid[int(tid)]),'ticker':str(tick[int(tid)]),
            'requested_shares':float(shares),'reason':str(reason),
            'reserved_cash':None if reserved_cash is None else float(reserved_cash),
            'status':'ISSUED','execution_session':None,'execution_price_raw':None,
            'filled_shares':0.0,'execution_notional':0.0,'cancel_reason':None})
        return audit_order_seq

    def _audit_order(seq):
        for row in audit_orders:
            if row['order_seq']==seq: return row
        raise RuntimeError(f'audit order missing: {seq}')

    def _audit_resolve(seq,status,session,price=None,filled=0.,cancel_reason=None):
        row=_audit_order(seq); row['status']=status; row['execution_session']=session
        row['execution_price_raw']=None if price is None or not finite(price) else float(price)
        row['filled_shares']=float(filled)
        row['execution_notional']=float(filled)*float(price) if filled and price is not None and finite(price) else 0.0
        row['cancel_reason']=cancel_reason

    def _audit_start(slot_id,tid,qty,signal_session,session,price,open_equity):
        nonlocal audit_episode_seq
        audit_episode_seq+=1
        value=float(qty)*float(price)
        weight=value/float(open_equity) if finite(open_equity) and open_equity>0 else None
        audit_live[int(slot_id)]={
            'episode_id':audit_episode_seq,'variant':audit_variant,'slot_id':int(slot_id),
            'security_id':str(sid[int(tid)]),'ticker':str(tick[int(tid)]),
            'entry_signal_session':signal_session,'entry_session':session,
            'entry_price_raw_open':float(price),'initial_shares':float(qty),
            'entry_open_position_value':value,'entry_open_portfolio_weight':weight,
            'min_close_position_value':None,'max_close_position_value':None,
            'min_close_portfolio_weight':None,'max_close_portfolio_weight':None,
            'min_shares':float(qty),'max_shares':float(qty),
            'last_close_session':None,'last_close_price_raw':None,
            'last_close_position_value':None,'last_close_portfolio_weight':None,
            'exit_session':None,'exit_price_raw_open':None,'exit_position_value':None,
            'exit_portfolio_weight':None,'exit_reason':None,'final_shares':None,
            'held_close_observations':0}

    def _audit_mark(session,equity):
        if not finite(equity) or equity<=0: return
        for slot_id,s in enumerate(book.slots):
            rec=audit_live.get(slot_id)
            if rec is None or not s.held(): continue
            px=clraw[s.tid]
            if not(finite(px) and px>0): px=book.last_raw.get(s.tid,np.nan)
            if not(finite(px) and px>0): continue
            value=float(s.qty)*float(px); weight=value/float(equity)
            rec['last_close_session']=session; rec['last_close_price_raw']=float(px)
            rec['last_close_position_value']=value; rec['last_close_portfolio_weight']=weight
            rec['held_close_observations']+=1
            rec['min_close_position_value']=value if rec['min_close_position_value'] is None else min(rec['min_close_position_value'],value)
            rec['max_close_position_value']=value if rec['max_close_position_value'] is None else max(rec['max_close_position_value'],value)
            rec['min_close_portfolio_weight']=weight if rec['min_close_portfolio_weight'] is None else min(rec['min_close_portfolio_weight'],weight)
            rec['max_close_portfolio_weight']=weight if rec['max_close_portfolio_weight'] is None else max(rec['max_close_portfolio_weight'],weight)
            rec['min_shares']=min(rec['min_shares'],float(s.qty)); rec['max_shares']=max(rec['max_shares'],float(s.qty))

    def _audit_close(slot_id,session,price,open_equity,reason,shares):
        rec=audit_live.pop(int(slot_id),None)
        if rec is None: return
        value=float(shares)*float(price) if price is not None and finite(price) else None
        weight=value/float(open_equity) if value is not None and finite(open_equity) and open_equity>0 else None
        rec['exit_session']=session; rec['exit_price_raw_open']=None if price is None or not finite(price) else float(price)
        rec['exit_position_value']=value; rec['exit_portfolio_weight']=weight
        rec['exit_reason']=str(reason); rec['final_shares']=float(shares)
        audit_positions.append(rec)
'''.replace("__VARIANT__", repr(variant))
    text = text.replace(init, init + observer_init, 1)

    open_marker = "            # Open: settle prior receivables, transform splits, then execute pending exits/buys."
    pre_open = '''            # Observer: capture orders outstanding from the prior close.
            for _slot_id,_s in enumerate(book.slots):
                if _s.reserved() and _slot_id not in audit_pending_buy:
                    audit_pending_buy[_slot_id]=_audit_issue('BUY',audit_last_session or ds,_slot_id,_s.pending_tid,_s.pending_shares,'ENTRY_DURABLE_RANK',getattr(_s,'reserved_cash',None))
                if _s.held() and _s.pending_sell and _slot_id not in audit_pending_sell:
                    audit_pending_sell[_slot_id]=_audit_issue('SELL',audit_last_session or ds,_slot_id,_s.tid,_s.qty,_s.sell_reason)
            audit_pre_slots=[(s.held(),int(s.tid),float(s.qty),bool(s.pending_sell),str(s.sell_reason),s.reserved(),int(s.pending_tid),float(s.pending_shares)) for s in book.slots]
'''
    text = replace_once(text, open_marker, pre_open + open_marker, "pre-open observer")

    # Strict-PIT source generation has two legitimate forms: before canonical
    # corpus binding it carries the retained dividend comment; with the canonical
    # dataset bound, the strict transform replaces the entire dividend block and
    # emits the canonical comment. Anchor on exactly one known form.
    dividend_markers = (
        "            # Dividends use prior-close raw share quantity and current raw/signal price factor.",
        "            # Canonical dividends already use the as-traded share basis.",
    )
    post_open = '''            # Observer: reconcile fills, cancellations and exits after open execution.
            _audit_open_equity,_audit_unresolved=book.equity(opraw)
            for _slot_id,_pre in enumerate(audit_pre_slots):
                _was_held,_old_tid,_old_qty,_was_pending_sell,_old_reason,_was_reserved,_pending_tid,_pending_shares=_pre
                _cur=book.slots[_slot_id]
                if _was_reserved:
                    _seq=audit_pending_buy.get(_slot_id)
                    if _seq is None:
                        _seq=_audit_issue('BUY',audit_last_session or ds,_slot_id,_pending_tid,_pending_shares,'ENTRY_DURABLE_RANK',getattr(_cur,'reserved_cash',None)); audit_pending_buy[_slot_id]=_seq
                    if _cur.held() and int(_cur.tid)==_pending_tid:
                        _px=opraw[_pending_tid]; _filled=float(_cur.qty)
                        _status='FILLED' if abs(_filled-_pending_shares)<=1e-12 else 'PARTIAL_FILLED'
                        _audit_resolve(_seq,_status,ds,_px,_filled)
                        _audit_start(_slot_id,_pending_tid,_filled,audit_last_session or ds,ds,_px,_audit_open_equity)
                        audit_pending_buy.pop(_slot_id,None)
                    elif not _cur.reserved() and not _cur.held():
                        _px=opraw[_pending_tid] if 0<=_pending_tid<len(opraw) else np.nan
                        _why='TERMINAL_CANCEL' if _pending_tid in term_tids else ('UNAFFORDABLE_AT_OPEN_OR_CORPORATE_ACTION' if finite(_px) and _px>0 else 'CORPORATE_ACTION_OR_UNTRADEABLE_CANCEL')
                        _audit_resolve(_seq,'CANCELLED',ds,_px,0.,_why); audit_pending_buy.pop(_slot_id,None)
                if _was_held and not _cur.held():
                    _reason=_old_reason or ('terminal' if _old_tid in term_tids else 'exit')
                    _seq=audit_pending_sell.get(_slot_id)
                    if _seq is None: _seq=_audit_issue('SELL',ds,_slot_id,_old_tid,_old_qty,_reason)
                    _px=opraw[_old_tid]
                    if not(finite(_px) and _px>0): _px=book.last_raw.get(_old_tid,np.nan)
                    _audit_resolve(_seq,'FILLED' if finite(_px) and _px>0 else 'SETTLED_WITHOUT_EXECUTABLE_OPEN',ds,_px,_old_qty)
                    _audit_close(_slot_id,ds,_px,open_eq,_reason,_old_qty); audit_pending_sell.pop(_slot_id,None)
                elif _was_held and _cur.held() and int(_cur.tid)!=_old_tid:
                    _px_old=opraw[_old_tid] if 0<=_old_tid<len(opraw) else book.last_raw.get(_old_tid,np.nan)
                    if not(finite(_px_old) and _px_old>0): _px_old=book.last_raw.get(_old_tid,np.nan)
                    _audit_close(_slot_id,ds,_px_old,open_eq,'CORPORATE_ACTION_CONVERSION',_old_qty)
                    _px_new=opraw[int(_cur.tid)]
                    if not(finite(_px_new) and _px_new>0): _px_new=book.last_raw.get(int(_cur.tid),np.nan)
                    if finite(_px_new) and _px_new>0: _audit_start(_slot_id,int(_cur.tid),float(_cur.qty),ds,ds,_px_new,_audit_open_equity)
'''
    text = replace_one_of(text, dividend_markers, post_open, "post-open observer")

    text = replace_once(text, "            held=[]", "            _audit_mark(ds,eq)\n            held=[]", "position mark observer")

    # Champion's canonical transform may have inserted strategy-boundary
    # telemetry immediately before rows.append, but the rows.append prefix itself
    # remains singular in both source forms.
    rows_marker = "                rows.append({'date':date,"
    daily = '''                _recv=float(sum(x[1] for x in book.receivables))
                _reserved_cash=float(sum(getattr(s,'reserved_cash',0.) for s in book.slots if s.reserved()))
                _cash=float(book.cash); _invested=max(0.,float(eq)-_cash-_recv)
                audit_daily.append({'date':ds,'variant':audit_variant,'wealth_core_equity':float(eq),'cash':_cash,'receivables':_recv,
                                    'reserved_entry_cash':_reserved_cash,'uncommitted_cash':_cash-_reserved_cash,'invested_equity':_invested,
                                    'invested_weight':(_invested/float(eq) if eq>0 else None),'held_count':int(sum(1 for s in book.slots if s.held())),
                                    'reserved_count':int(sum(1 for s in book.slots if s.reserved()))})
'''
    text = replace_once(text, rows_marker, daily + rows_marker, "daily observer")

    pending = "            pending_native=native_target; pend['control']=ctl_d; pend['A']=a_d; pend['B']=b_d"
    text = replace_once(text, pending, pending + "\n            audit_last_session=ds", "observer session clock")

    out_marker = "    out=pd.DataFrame(rows)"
    flush = '''    for _slot_id,_s in enumerate(book.slots):
        if _s.reserved() and _slot_id not in audit_pending_buy:
            audit_pending_buy[_slot_id]=_audit_issue('BUY',audit_last_session,_slot_id,_s.pending_tid,_s.pending_shares,'ENTRY_DURABLE_RANK',getattr(_s,'reserved_cash',None))
        if _s.held() and _s.pending_sell and _slot_id not in audit_pending_sell:
            audit_pending_sell[_slot_id]=_audit_issue('SELL',audit_last_session,_slot_id,_s.tid,_s.qty,_s.sell_reason)
    for _slot_id,_rec in list(audit_live.items()):
        _s=book.slots[_slot_id]; _rec['exit_reason']='OPEN_AT_END'; _rec['final_shares']=float(_s.qty) if _s.held() else _rec.get('final_shares')
        audit_positions.append(_rec); audit_live.pop(_slot_id,None)
    pd.DataFrame(audit_orders).sort_values(['order_seq']).to_csv(OUT/'wealth_core_order_blotter.csv',index=False)
    pd.DataFrame(audit_positions).sort_values(['entry_session','episode_id']).to_csv(OUT/'wealth_core_position_lifecycle.csv',index=False)
    pd.DataFrame(audit_daily).to_csv(OUT/'wealth_core_daily_observer.csv',index=False)

'''
    text = replace_once(text, out_marker, flush + out_marker, "observer output")

    for needle in ("wealth_core_order_blotter.csv", "wealth_core_position_lifecycle.csv", "wealth_core_daily_observer.csv", "_audit_mark(ds,eq)"):
        if needle not in text:
            raise RuntimeError(f"observer transform missing {needle}")
    return text
