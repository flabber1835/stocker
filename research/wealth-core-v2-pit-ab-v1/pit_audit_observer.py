#!/usr/bin/env python3
"""Observer-only instrumentation for the certified Research Champion replay.

This transform must not alter strategy decisions. It records the raw Wealth Core
book as a separate audit surface: chronological orders, position lifecycles, and
per-session cash/investment state. The same observer is installed on V1 and V2.
"""
from __future__ import annotations


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old, new, 1)


def replace_one_of(text: str, choices: tuple[str, ...], new_for, label: str) -> str:
    hits = [old for old in choices if text.count(old) == 1]
    if len(hits) != 1:
        raise RuntimeError(f"{label}: expected exactly one matching source seam, found {len(hits)}")
    old = hits[0]
    return text.replace(old, new_for(old), 1)


def install(text: str, *, variant: str) -> str:
    """Install observer state after all economic/PIT transforms are complete."""
    if variant not in {"V1", "V2"}:
        raise ValueError(variant)

    init_v1 = "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0"
    init_v2 = (
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; "
        "slot_v2_reserved=slot_v2_rejected=slot_v2_gap_clipped=slot_v2_gap_cancelled=0"
    )

    observer_init = r'''\n    # OBSERVER ONLY. None of these structures is read by ranking, sizing, exits,\n    # Sentinel, LDRC, or portfolio accounting.\n    audit_variant=__AUDIT_VARIANT__\n    audit_orders=[]; audit_positions=[]; audit_live={}; audit_daily=[]\n    audit_pending_buy={}; audit_pending_sell={}\n    audit_order_seq=0; audit_episode_seq=0; audit_last_session=None\n\n    def _audit_issue(side, issued_session, slot_id, tid, shares, reason, reserved_cash=None):\n        nonlocal audit_order_seq\n        audit_order_seq+=1\n        row={'order_seq':audit_order_seq,'variant':audit_variant,'side':side,\n             'issued_session':issued_session,'slot_id':int(slot_id),\n             'security_id':str(sid[int(tid)]),'ticker':str(tick[int(tid)]),\n             'requested_shares':float(shares),'reason':str(reason),\n             'reserved_cash':None if reserved_cash is None else float(reserved_cash),\n             'status':'ISSUED','execution_session':None,'execution_price_raw':None,\n             'filled_shares':0.0,'execution_notional':0.0,'cancel_reason':None}\n        audit_orders.append(row)\n        return audit_order_seq\n\n    def _audit_order_row(seq):\n        for row in audit_orders:\n            if row['order_seq']==seq: return row\n        raise RuntimeError(f'audit order {seq} missing')\n\n    def _audit_resolve_order(seq, *, status, session, price=None, filled=0.0, cancel_reason=None):\n        row=_audit_order_row(seq); row['status']=status; row['execution_session']=session\n        row['execution_price_raw']=None if price is None or not finite(price) else float(price)\n        row['filled_shares']=float(filled)\n        row['execution_notional']=(float(filled)*float(price) if filled and price is not None and finite(price) else 0.0)\n        row['cancel_reason']=cancel_reason\n\n    def _audit_start_episode(slot_id, tid, qty, signal_session, session, price, open_equity):\n        nonlocal audit_episode_seq\n        audit_episode_seq+=1\n        value=float(qty)*float(price)\n        weight=value/float(open_equity) if finite(open_equity) and open_equity>0 else None\n        audit_live[int(slot_id)]={\n            'episode_id':audit_episode_seq,'variant':audit_variant,'slot_id':int(slot_id),\n            'security_id':str(sid[int(tid)]),'ticker':str(tick[int(tid)]),\n            'entry_signal_session':signal_session,'entry_session':session,\n            'entry_price_raw_open':float(price),'initial_shares':float(qty),\n            'entry_open_position_value':value,'entry_open_portfolio_weight':weight,\n            'min_close_position_value':None,'max_close_position_value':None,\n            'min_close_portfolio_weight':None,'max_close_portfolio_weight':None,\n            'min_shares':float(qty),'max_shares':float(qty),\n            'last_close_session':None,'last_close_price_raw':None,\n            'last_close_position_value':None,'last_close_portfolio_weight':None,\n            'exit_session':None,'exit_price_raw_open':None,'exit_position_value':None,\n            'exit_portfolio_weight':None,'exit_reason':None,'final_shares':None,\n            'held_close_observations':0}\n\n    def _audit_mark_positions(session, equity):\n        if not finite(equity) or equity<=0: return\n        for slot_id,s in enumerate(book.slots):\n            rec=audit_live.get(slot_id)\n            if rec is None or not s.held(): continue\n            px=clraw[s.tid]\n            if not(finite(px) and px>0): px=book.last_raw.get(s.tid,np.nan)\n            if not(finite(px) and px>0): continue\n            value=float(s.qty)*float(px); weight=value/float(equity)\n            rec['last_close_session']=session; rec['last_close_price_raw']=float(px)\n            rec['last_close_position_value']=value; rec['last_close_portfolio_weight']=weight\n            rec['held_close_observations']+=1\n            rec['min_close_position_value']=value if rec['min_close_position_value'] is None else min(rec['min_close_position_value'],value)\n            rec['max_close_position_value']=value if rec['max_close_position_value'] is None else max(rec['max_close_position_value'],value)\n            rec['min_close_portfolio_weight']=weight if rec['min_close_portfolio_weight'] is None else min(rec['min_close_portfolio_weight'],weight)\n            rec['max_close_portfolio_weight']=weight if rec['max_close_portfolio_weight'] is None else max(rec['max_close_portfolio_weight'],weight)\n            rec['min_shares']=min(rec['min_shares'],float(s.qty)); rec['max_shares']=max(rec['max_shares'],float(s.qty))\n\n    def _audit_close_episode(slot_id, session, price, open_equity, reason, final_shares):\n        rec=audit_live.pop(int(slot_id),None)\n        if rec is None: return\n        value=float(final_shares)*float(price) if price is not None and finite(price) else None\n        weight=(value/float(open_equity) if value is not None and finite(open_equity) and open_equity>0 else None)\n        rec['exit_session']=session; rec['exit_price_raw_open']=None if price is None or not finite(price) else float(price)\n        rec['exit_position_value']=value; rec['exit_portfolio_weight']=weight\n        rec['exit_reason']=str(reason); rec['final_shares']=float(final_shares)\n        audit_positions.append(rec)\n'''.replace("__AUDIT_VARIANT__", repr(variant))

    text = replace_one_of(
        text, (init_v1, init_v2),
        lambda old: old + observer_init,
        "observer initialization",
    )

    open_marker = "            # Open: settle prior receivables, transform splits, then execute pending exits/buys."
    pre_open = r'''            # Observer snapshots orders that existed after the prior close.\n            for _slot_id,_s in enumerate(book.slots):\n                if _s.reserved() and _slot_id not in audit_pending_buy:\n                    _issued=audit_last_session or ds\n                    _reserved=getattr(_s,'reserved_cash',None)\n                    audit_pending_buy[_slot_id]=_audit_issue('BUY',_issued,_slot_id,_s.pending_tid,_s.pending_shares,'ENTRY_DURABLE_RANK',_reserved)\n                if _s.held() and _s.pending_sell and _slot_id not in audit_pending_sell:\n                    _issued=audit_last_session or ds\n                    audit_pending_sell[_slot_id]=_audit_issue('SELL',_issued,_slot_id,_s.tid,_s.qty,_s.sell_reason)\n            audit_pre_slots=[(s.held(),int(s.tid),float(s.qty),bool(s.pending_sell),str(s.sell_reason),\n                              s.reserved(),int(s.pending_tid),float(s.pending_shares),int(s.pending_signal_day))\n                             for s in book.slots]\n'''
    text = replace_once(text, open_marker, pre_open + open_marker, "pre-open observer snapshot")

    dividends_marker = "            # Dividends use prior-close raw share quantity and current raw/signal price factor."
    post_open = r'''            # Observer compares the pre-open slot state to the post-execution state.\n            _audit_open_equity,_audit_open_unresolved=book.equity(opraw)\n            for _slot_id,_pre in enumerate(audit_pre_slots):\n                _was_held,_old_tid,_old_qty,_was_pending_sell,_old_sell_reason,_was_reserved,_pending_tid,_pending_shares,_pending_signal_day=_pre\n                _cur=book.slots[_slot_id]\n                if _was_reserved:\n                    _seq=audit_pending_buy.get(_slot_id)\n                    if _seq is None:\n                        _seq=_audit_issue('BUY',audit_last_session or ds,_slot_id,_pending_tid,_pending_shares,'ENTRY_DURABLE_RANK',getattr(_cur,'reserved_cash',None)); audit_pending_buy[_slot_id]=_seq\n                    if _cur.held() and int(_cur.tid)==_pending_tid:\n                        _px=opraw[_pending_tid]; _filled=float(_cur.qty)\n                        _status='FILLED' if abs(_filled-_pending_shares)<=1e-12 else 'PARTIAL_FILLED'\n                        _audit_resolve_order(_seq,status=_status,session=ds,price=_px,filled=_filled)\n                        _signal=audit_last_session or ds\n                        _audit_start_episode(_slot_id,_pending_tid,_filled,_signal,ds,_px,_audit_open_equity)\n                        audit_pending_buy.pop(_slot_id,None)\n                    elif not _cur.reserved() and not _cur.held():\n                        _px=opraw[_pending_tid] if 0<=_pending_tid<len(opraw) else np.nan\n                        if _pending_tid in term_tids: _why='TERMINAL_CANCEL'\n                        elif finite(_px) and _px>0 and finite(volume[_pending_tid]) and volume[_pending_tid]>0: _why='UNAFFORDABLE_AT_OPEN_OR_CORPORATE_ACTION'\n                        else: _why='CORPORATE_ACTION_OR_UNTRADEABLE_CANCEL'\n                        _audit_resolve_order(_seq,status='CANCELLED',session=ds,price=_px,filled=0.,cancel_reason=_why)\n                        audit_pending_buy.pop(_slot_id,None)\n\n                if _was_held and not _cur.held():\n                    _seq=audit_pending_sell.get(_slot_id)\n                    _reason=_old_sell_reason or ('terminal' if _old_tid in term_tids else 'exit')\n                    if _seq is None:\n                        _seq=_audit_issue('SELL',ds,_slot_id,_old_tid,_old_qty,_reason)\n                    _px=opraw[_old_tid]\n                    if not(finite(_px) and _px>0): _px=book.last_raw.get(_old_tid,np.nan)\n                    _status='FILLED' if finite(_px) and _px>0 else 'SETTLED_WITHOUT_EXECUTABLE_OPEN'\n                    _audit_resolve_order(_seq,status=_status,session=ds,price=_px,filled=_old_qty)\n                    _audit_close_episode(_slot_id,ds,_px,open_eq,_reason,_old_qty)\n                    audit_pending_sell.pop(_slot_id,None)\n                elif _was_held and _cur.held() and int(_cur.tid)!=_old_tid:\n                    _px_old=opraw[_old_tid] if 0<=_old_tid<len(opraw) else np.nan\n                    if not(finite(_px_old) and _px_old>0): _px_old=book.last_raw.get(_old_tid,np.nan)\n                    _audit_close_episode(_slot_id,ds,_px_old,open_eq,'CORPORATE_ACTION_CONVERSION',_old_qty)\n                    _px_new=opraw[int(_cur.tid)]\n                    if not(finite(_px_new) and _px_new>0): _px_new=book.last_raw.get(int(_cur.tid),np.nan)\n                    if finite(_px_new) and _px_new>0:\n                        _audit_start_episode(_slot_id,int(_cur.tid),float(_cur.qty),ds,ds,_px_new,_audit_open_equity)\n'''
    text = replace_once(text, dividends_marker, post_open + dividends_marker, "post-open observer reconciliation")

    held_marker = "            held=[]"
    text = replace_once(
        text, held_marker,
        "            _audit_mark_positions(ds,eq)\n" + held_marker,
        "position close-state observer",
    )

    rows_marker = "                rows.append({'date':date,"
    daily_observer = r'''                _recv=float(sum(x[1] for x in book.receivables))\n                _reserved_cash=float(sum(getattr(s,'reserved_cash',0.) for s in book.slots if s.reserved()))\n                _cash=float(book.cash); _uncommitted=_cash-_reserved_cash\n                _held_count=int(sum(1 for s in book.slots if s.held())); _reserved_count=int(sum(1 for s in book.slots if s.reserved()))\n                _invested=max(0.,float(eq)-_cash-_recv)\n                audit_daily.append({'date':ds,'variant':audit_variant,'wealth_core_equity':float(eq),\n                                    'cash':_cash,'receivables':_recv,'reserved_entry_cash':_reserved_cash,\n                                    'uncommitted_cash':_uncommitted,'invested_equity':_invested,\n                                    'invested_weight':(_invested/float(eq) if eq>0 else None),\n                                    'held_count':_held_count,'reserved_count':_reserved_count})\n'''
    text = replace_once(text, rows_marker, daily_observer + rows_marker, "daily Wealth Core observer")

    pending_marker = "            pending_native=native_target; pend['control']=ctl_d; pend['A']=a_d; pend['B']=b_d"
    text = replace_once(
        text, pending_marker,
        pending_marker + "\n            audit_last_session=ds",
        "observer session clock",
    )

    out_marker = "    out=pd.DataFrame(rows)"
    flush = r'''    # Flush any orders/episodes still open on the terminal replay session.\n    for _slot_id,_s in enumerate(book.slots):\n        if _s.reserved() and _slot_id not in audit_pending_buy:\n            audit_pending_buy[_slot_id]=_audit_issue('BUY',audit_last_session,_slot_id,_s.pending_tid,_s.pending_shares,'ENTRY_DURABLE_RANK',getattr(_s,'reserved_cash',None))\n        if _s.held() and _s.pending_sell and _slot_id not in audit_pending_sell:\n            audit_pending_sell[_slot_id]=_audit_issue('SELL',audit_last_session,_slot_id,_s.tid,_s.qty,_s.sell_reason)\n    for _slot_id,_rec in list(audit_live.items()):\n        _s=book.slots[_slot_id]\n        _rec['exit_reason']='OPEN_AT_END'; _rec['final_shares']=float(_s.qty) if _s.held() else _rec.get('final_shares')\n        audit_positions.append(_rec); audit_live.pop(_slot_id,None)\n\n    pd.DataFrame(audit_orders).sort_values(['order_seq']).to_csv(OUT/'wealth_core_order_blotter.csv',index=False)\n    pd.DataFrame(audit_positions).sort_values(['entry_session','episode_id']).to_csv(OUT/'wealth_core_position_lifecycle.csv',index=False)\n    pd.DataFrame(audit_daily).to_csv(OUT/'wealth_core_daily_observer.csv',index=False)\n'''
    text = replace_once(text, out_marker, flush + "\n" + out_marker, "observer output flush")

    required = (
        "wealth_core_order_blotter.csv",
        "wealth_core_position_lifecycle.csv",
        "wealth_core_daily_observer.csv",
        "audit_pre_slots=",
        "_audit_mark_positions(ds,eq)",
    )
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise RuntimeError(f"observer transform incomplete: {missing}")
    return text
