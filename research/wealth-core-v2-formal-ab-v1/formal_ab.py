#!/usr/bin/env python3
"""Clean formal-harness A/B for Wealth Core V1 vs decision-funded V2.

This research entrypoint consumes the certified Research Champion formal source
*after* its strict-PIT, 20-year financial-grade, terminal, capacity and Champion
transforms have been composed. V1 is that source unchanged economically. V2 is
constructed by one reversible patch set limited to Wealth Core entry-slot funding.

Audit instrumentation is insertion-only. A self-test removes every inserted audit
block and requires byte-for-byte recovery of the corresponding economic source.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys

CERTIFIED_BASE_SHA = "3af356ab6d329e7bc6cdc015a49a6ca2d4e4b864"
PIT_RUNTIME_MAIN_SHA = "887f479b15ad861313da666ad698034d3847121c"
CERTIFIED_DATASET_SHA256 = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"
CERTIFIED_V1_SUMMARY_SHA256 = "7488908b6e3da6141560838e8a825009e4462a11de733681addd17ac0658267a"
PROFILE = "wealth-core-v2-full-whole-share-target-v1"


@dataclass(frozen=True)
class Patch:
    label: str
    old: str
    new: str


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old, new, 1)


def _insert_before_once(text: str, anchor: str, block: str, label: str) -> str:
    return _replace_once(text, anchor, block + anchor, label)


def _insert_after_once(text: str, anchor: str, block: str, label: str) -> str:
    return _replace_once(text, anchor, anchor + block, label)


def _indented_marked(tag: str, body: str, indent: str) -> str:
    return f"{indent}# WC_AB_AUDIT_BEGIN {tag}\n" + body + f"{indent}# WC_AB_AUDIT_END {tag}\n"


V2_PATCHES: tuple[Patch, ...] = (
    Patch(
        "slot reservation cash state",
        "    pending_sell:bool=False; sell_reason:str=''; pending_tid:int=-1; pending_shares:float=0.; pending_signal_day:int=-1; ready_day:int=0",
        "    pending_sell:bool=False; sell_reason:str=''; pending_tid:int=-1; pending_shares:float=0.; pending_signal_day:int=-1; reserved_cash:float=0.; ready_day:int=0",
    ),
    Patch(
        "book uncommitted cash accounting",
        "    def reserved_ids(self): return {s.pending_tid for s in self.slots if s.reserved()}\n",
        "    def reserved_ids(self): return {s.pending_tid for s in self.slots if s.reserved()}\n"
        "    def reserved_cash_total(self): return float(sum(s.reserved_cash for s in self.slots if s.reserved()))\n"
        "    def uncommitted_cash(self): return max(0.,float(self.cash)-self.reserved_cash_total())\n",
    ),
    Patch(
        "slot-funding diagnostic counters",
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0",
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; slot_v2_reserved=slot_v2_rejected=slot_v2_gap_clipped=slot_v2_gap_cancelled=0",
    ),
    Patch(
        "fractional split reservation cancellation",
        "if abs(q-round(q))>1e-8: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "if abs(q-round(q))>1e-8: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.reserved_cash=0.",
    ),
    Patch(
        "terminal reservation cancellation",
        "if s.reserved() and s.pending_tid in term_tids: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "if s.reserved() and s.pending_tid in term_tids: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.reserved_cash=0.",
    ),
    Patch(
        "reservation-bounded next-open fill",
        "afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford)",
        "afford=math.floor(s.reserved_cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford); slot_v2_gap_clipped+=int(q<int(round(s.pending_shares))); slot_v2_gap_cancelled+=int(q<1)",
    ),
    Patch(
        "open resolution reservation release",
        "book.initialized=True; buys+=1\n                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "book.initialized=True; buys+=1\n                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.reserved_cash=0.",
    ),
    Patch(
        "full whole-share decision target",
        "target=min(eq*ENTRY_W,book.cash); q=int(target//(float(px)*(1+COST)))",
        "target=eq*ENTRY_W; q=int(target//(float(px)*(1+COST))); required_cash=float(q)*float(px)*(1+COST)",
    ),
    Patch(
        "fully funded slot reservation",
        "                        if q<1: continue\n                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday;",
        "                        if q<1: continue\n"
        "                        if required_cash>book.uncommitted_cash()+1e-8: slot_v2_rejected+=1; continue\n"
        "                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; s.reserved_cash=required_cash; slot_v2_reserved+=1;",
    ),
    Patch(
        "slot-funding summary telemetry",
        "        'buys':buys,'sells':sells,'split_events_applied':split_events,'dividend_events_held':div_events,",
        "        'buys':buys,'sells':sells,'split_events_applied':split_events,'dividend_events_held':div_events,\n"
        "        'wealth_core_entry_funding':{'profile':'wealth-core-v2-full-whole-share-target-v1','reserved':slot_v2_reserved,'rejected_insufficient_uncommitted_cash':slot_v2_rejected,'gap_clipped':slot_v2_gap_clipped,'gap_cancelled':slot_v2_gap_cancelled},",
    ),
)


def apply_v2_patch(v1_source: str) -> str:
    out = v1_source
    for patch in V2_PATCHES:
        out = _replace_once(out, patch.old, patch.new, patch.label)
    restored = out
    for patch in reversed(V2_PATCHES):
        restored = _replace_once(restored, patch.new, patch.old, f"reverse {patch.label}")
    if restored != v1_source:
        raise RuntimeError("V2 patch is not mechanically reversible to exact V1 source")
    forbidden = ("target=min(eq*ENTRY_W,book.cash)", "afford=math.floor(book.cash/(float(px)*(1+COST)))")
    survived = [needle for needle in forbidden if needle in out]
    if survived:
        raise RuntimeError(f"legacy V1 funding survived V2 patch: {survived}")
    required = ("reserved_cash:float=0.", "def uncommitted_cash(self)", "required_cash>book.uncommitted_cash()", "afford=math.floor(s.reserved_cash/", "wealth-core-v2-full-whole-share-target-v1")
    missing = [needle for needle in required if needle not in out]
    if missing:
        raise RuntimeError(f"V2 funding patch incomplete: {missing}")
    return out


def install_audit(economic_source: str, *, variant: str) -> tuple[str, tuple[str, ...]]:
    if variant not in {"V1", "V2"}:
        raise ValueError(variant)
    text = economic_source
    inserted: list[str] = []

    init_anchor = "    prev_close_eq=None; prev_perf_date=None\n"
    init_body = f'''    audit_variant={variant!r}
    audit_orders=[]; audit_positions=[]; audit_live={{}}; audit_daily=[]
    audit_pending_buy={{}}; audit_pending_sell={{}}
    audit_order_seq=0; audit_episode_seq=0; audit_last_session=None

    def _wc_audit_issue(side,issued_session,slot_id,tid,shares,reason,reserved_cash=None):
        nonlocal audit_order_seq
        audit_order_seq+=1
        audit_orders.append({{
            'order_seq':audit_order_seq,'variant':audit_variant,'side':str(side),
            'issued_session':issued_session,'slot_id':int(slot_id),
            'security_id':str(sid[int(tid)]),'ticker':str(tick[int(tid)]),
            'requested_shares':float(shares),'reason':str(reason),
            'reserved_cash':None if reserved_cash is None else float(reserved_cash),
            'status':'ISSUED','execution_session':None,'execution_price_raw':None,
            'filled_shares':0.0,'execution_notional':0.0,'cancel_reason':None}})
        return audit_order_seq

    def _wc_audit_order(seq):
        for row in audit_orders:
            if row['order_seq']==seq: return row
        raise RuntimeError(f'audit order missing: {{seq}}')

    def _wc_audit_resolve(seq,status,session,price=None,filled=0.,cancel_reason=None):
        row=_wc_audit_order(seq); row['status']=str(status); row['execution_session']=session
        row['execution_price_raw']=None if price is None or not finite(price) else float(price)
        row['filled_shares']=float(filled)
        row['execution_notional']=float(filled)*float(price) if filled and price is not None and finite(price) else 0.0
        row['cancel_reason']=cancel_reason

    def _wc_audit_start(slot_id,tid,qty,signal_session,session,price,open_equity,event_type='ENTRY'):
        nonlocal audit_episode_seq
        audit_episode_seq+=1
        value=float(qty)*float(price) if price is not None and finite(price) else None
        weight=value/float(open_equity) if value is not None and finite(open_equity) and open_equity>0 else None
        audit_live[int(slot_id)]={{
            'episode_id':audit_episode_seq,'variant':audit_variant,'slot_id':int(slot_id),
            'security_id':str(sid[int(tid)]),'ticker':str(tick[int(tid)]),'entry_event_type':str(event_type),
            'entry_signal_session':signal_session,'entry_session':session,
            'entry_price_raw_open':None if price is None or not finite(price) else float(price),
            'initial_shares':float(qty),'entry_open_position_value':value,
            'entry_open_portfolio_weight':weight,'min_close_position_value':None,
            'max_close_position_value':None,'min_close_portfolio_weight':None,
            'max_close_portfolio_weight':None,'min_shares':float(qty),'max_shares':float(qty),
            'last_close_session':None,'last_close_price_raw':None,
            'last_close_position_value':None,'last_close_portfolio_weight':None,
            'exit_session':None,'exit_price_raw_open':None,'exit_position_value':None,
            'exit_portfolio_weight':None,'exit_reason':None,'final_shares':None,
            'held_close_observations':0}}

    def _wc_audit_mark(session,equity):
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

    def _wc_audit_close(slot_id,session,price,open_equity,reason,shares):
        rec=audit_live.pop(int(slot_id),None)
        if rec is None: return
        value=float(shares)*float(price) if price is not None and finite(price) else None
        weight=value/float(open_equity) if value is not None and finite(open_equity) and open_equity>0 else None
        rec['exit_session']=session
        rec['exit_price_raw_open']=None if price is None or not finite(price) else float(price)
        rec['exit_position_value']=value; rec['exit_portfolio_weight']=weight
        rec['exit_reason']=str(reason); rec['final_shares']=float(shares)
        audit_positions.append(rec)
'''
    block = _indented_marked("INIT", init_body, "    ")
    text = _insert_after_once(text, init_anchor, block, "audit initialization"); inserted.append(block)

    open_anchor = "            # Open: settle prior receivables, transform splits, then execute pending exits/buys.\n"
    pre_open_body = '''            for _slot_id,_s in enumerate(book.slots):
                if _s.reserved() and _slot_id not in audit_pending_buy:
                    audit_pending_buy[_slot_id]=_wc_audit_issue('BUY',audit_last_session or ds,_slot_id,_s.pending_tid,_s.pending_shares,'ENTRY_DURABLE_RANK',getattr(_s,'reserved_cash',None))
                if _s.held() and _s.pending_sell and _slot_id not in audit_pending_sell:
                    audit_pending_sell[_slot_id]=_wc_audit_issue('SELL',audit_last_session or ds,_slot_id,_s.tid,_s.qty,_s.sell_reason)
            audit_pre_slots=[{
                'held':s.held(),'tid':int(s.tid),'qty':float(s.qty),
                'pending_sell':bool(s.pending_sell),'sell_reason':str(s.sell_reason),
                'reserved':s.reserved(),'pending_tid':int(s.pending_tid),
                'pending_shares':float(s.pending_shares),
                'terminal_pending':bool(s.held() and hasattr(book,'terminal_pending') and int(s.tid) in book.terminal_pending)
            } for s in book.slots]
'''
    block = _indented_marked("PRE_OPEN", pre_open_body, "            ")
    text = _insert_after_once(text, open_anchor, block, "audit pre-open snapshot"); inserted.append(block)

    close_anchor = "            # Close: peaks/exits, mark equity, breadth, then admissions.\n"
    reconcile_body = '''            _wc_audit_open_equity=float(open_eq) if finite(open_eq) and open_eq>0 else book.equity(opraw)[0]
            for _slot_id,_pre in enumerate(audit_pre_slots):
                _cur=book.slots[_slot_id]
                if _pre['reserved']:
                    _seq=audit_pending_buy.get(_slot_id)
                    if _seq is None:
                        _seq=_wc_audit_issue('BUY',audit_last_session or ds,_slot_id,_pre['pending_tid'],_pre['pending_shares'],'ENTRY_DURABLE_RANK',None); audit_pending_buy[_slot_id]=_seq
                    if _cur.held() and int(_cur.tid)==_pre['pending_tid']:
                        _px=opraw[_pre['pending_tid']]; _filled=float(_cur.qty)
                        _status='FILLED' if abs(_filled-_pre['pending_shares'])<=1e-12 else 'PARTIAL_OR_ADJUSTED_FILLED'
                        _wc_audit_resolve(_seq,_status,ds,_px,_filled)
                        _wc_audit_start(_slot_id,_pre['pending_tid'],_filled,audit_last_session or ds,ds,_px,_wc_audit_open_equity)
                        audit_pending_buy.pop(_slot_id,None)
                    elif not _cur.reserved() and not _cur.held():
                        _ptid=_pre['pending_tid']; _px=opraw[_ptid] if 0<=_ptid<len(opraw) else np.nan
                        _why='TERMINAL_CANCEL' if _ptid in term_tids else ('GAP_CANCEL' if finite(_px) and _px>0 else 'CORPORATE_ACTION_OR_UNTRADEABLE_CANCEL')
                        _wc_audit_resolve(_seq,'CANCELLED',ds,_px,0.,_why); audit_pending_buy.pop(_slot_id,None)
                if not _pre['held']: continue
                _old_tid=_pre['tid']; _old_qty=_pre['qty']
                if not _cur.held():
                    if _pre['pending_sell']:
                        _seq=audit_pending_sell.get(_slot_id)
                        if _seq is None: _seq=_wc_audit_issue('SELL',audit_last_session or ds,_slot_id,_old_tid,_old_qty,_pre['sell_reason'] or 'exit')
                        _px=opraw[_old_tid] if 0<=_old_tid<len(opraw) else np.nan
                        if not(finite(_px) and _px>0): _px=book.last_raw.get(_old_tid,np.nan)
                        _wc_audit_resolve(_seq,'FILLED' if finite(_px) and _px>0 else 'SETTLED_WITHOUT_EXECUTABLE_OPEN',ds,_px,_old_qty)
                        _wc_audit_close(_slot_id,ds,_px,_wc_audit_open_equity,_pre['sell_reason'] or 'exit',_old_qty); audit_pending_sell.pop(_slot_id,None)
                    else:
                        _reason='TERMINAL_GRACE_SETTLEMENT' if _pre['terminal_pending'] else ('TERMINAL_SETTLEMENT' if _old_tid in term_tids else 'NON_ORDER_EXIT')
                        _wc_audit_close(_slot_id,ds,None,_wc_audit_open_equity,_reason,_old_qty)
                elif int(_cur.tid)!=_old_tid:
                    _reason='TERMINAL_CONVERSION' if (_pre['terminal_pending'] or _old_tid in term_tids) else 'CORPORATE_ACTION_CONVERSION'
                    _wc_audit_close(_slot_id,ds,None,_wc_audit_open_equity,_reason,_old_qty)
                    _new_tid=int(_cur.tid); _px=opraw[_new_tid] if 0<=_new_tid<len(opraw) else np.nan
                    if not(finite(_px) and _px>0): _px=book.last_raw.get(_new_tid,np.nan)
                    _wc_audit_start(_slot_id,_new_tid,float(_cur.qty),ds,ds,_px,_wc_audit_open_equity,event_type=_reason)
'''
    block = _indented_marked("RECONCILE_OPEN", reconcile_body, "            ")
    text = _insert_before_once(text, close_anchor, block, "audit open reconciliation"); inserted.append(block)

    held_anchor = "            held=[]\n"
    block = _indented_marked("MARK_CLOSE", "            _wc_audit_mark(ds,eq)\n", "            ")
    text = _insert_before_once(text, held_anchor, block, "audit close mark"); inserted.append(block)

    rows_anchor = "                rows.append({'date':date,"
    daily_body = '''                _audit_recv=float(sum(x[1] for x in book.receivables))
                _audit_reserved_cash=float(sum(getattr(s,'reserved_cash',0.) for s in book.slots if s.reserved()))
                _audit_cash=float(book.cash); _audit_invested=max(0.,float(eq)-_audit_cash-_audit_recv)
                audit_daily.append({'date':ds,'variant':audit_variant,'wealth_core_equity':float(eq),'cash':_audit_cash,
                    'receivables':_audit_recv,'reserved_entry_cash':_audit_reserved_cash,
                    'uncommitted_cash':_audit_cash-_audit_reserved_cash,'invested_equity':_audit_invested,
                    'invested_weight':(_audit_invested/float(eq) if eq>0 else None),
                    'held_count':int(sum(1 for s in book.slots if s.held())),
                    'reserved_count':int(sum(1 for s in book.slots if s.reserved()))})
'''
    block = _indented_marked("DAILY", daily_body, "                ")
    text = _insert_before_once(text, rows_anchor, block, "audit daily state"); inserted.append(block)

    clock_anchor = "            pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d\n"
    block = _indented_marked("CLOCK", "            audit_last_session=ds\n", "            ")
    text = _insert_after_once(text, clock_anchor, block, "audit session clock"); inserted.append(block)

    out_anchor = "    out=pd.DataFrame(rows)\n"
    flush_body = '''    for _slot_id,_s in enumerate(book.slots):
        if _s.reserved() and _slot_id not in audit_pending_buy:
            audit_pending_buy[_slot_id]=_wc_audit_issue('BUY',audit_last_session,_slot_id,_s.pending_tid,_s.pending_shares,'ENTRY_DURABLE_RANK',getattr(_s,'reserved_cash',None))
        if _s.held() and _s.pending_sell and _slot_id not in audit_pending_sell:
            audit_pending_sell[_slot_id]=_wc_audit_issue('SELL',audit_last_session,_slot_id,_s.tid,_s.qty,_s.sell_reason)
    for _slot_id,_rec in list(audit_live.items()):
        _s=book.slots[_slot_id]; _rec['exit_reason']='OPEN_AT_END'; _rec['final_shares']=float(_s.qty) if _s.held() else _rec.get('final_shares')
        audit_positions.append(_rec); audit_live.pop(_slot_id,None)
    _order_cols=['order_seq','variant','side','issued_session','slot_id','security_id','ticker','requested_shares','reason','reserved_cash','status','execution_session','execution_price_raw','filled_shares','execution_notional','cancel_reason']
    _position_cols=['episode_id','variant','slot_id','security_id','ticker','entry_event_type','entry_signal_session','entry_session','entry_price_raw_open','initial_shares','entry_open_position_value','entry_open_portfolio_weight','min_close_position_value','max_close_position_value','min_close_portfolio_weight','max_close_portfolio_weight','min_shares','max_shares','last_close_session','last_close_price_raw','last_close_position_value','last_close_portfolio_weight','exit_session','exit_price_raw_open','exit_position_value','exit_portfolio_weight','exit_reason','final_shares','held_close_observations']
    pd.DataFrame(audit_orders,columns=_order_cols).sort_values(['order_seq']).to_csv(OUT/'wealth_core_order_blotter.csv',index=False)
    pd.DataFrame(audit_positions,columns=_position_cols).sort_values(['entry_session','episode_id']).to_csv(OUT/'wealth_core_position_lifecycle.csv',index=False)
    pd.DataFrame(audit_daily).to_csv(OUT/'wealth_core_daily_observer.csv',index=False)
'''
    block = _indented_marked("FLUSH", flush_body, "    ")
    text = _insert_before_once(text, out_anchor, block, "audit output flush"); inserted.append(block)

    stripped = text
    for inserted_block in reversed(inserted):
        stripped = _replace_once(stripped, inserted_block, "", "strip audit block")
    if stripped != economic_source:
        raise RuntimeError("audit instrumentation is not insertion-only reversible")
    required = ("wealth_core_order_blotter.csv", "wealth_core_position_lifecycle.csv", "wealth_core_daily_observer.csv", "TERMINAL_GRACE_SETTLEMENT", "TERMINAL_SETTLEMENT")
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise RuntimeError(f"audit instrumentation incomplete: {missing}")
    return text, tuple(inserted)


def _load_formal():
    return importlib.import_module("backtester.run_research_champion_strict_pit_20y_v2")


def _formal_transform():
    formal = _load_formal()
    return formal, formal.champion.strict20.corrected.transformed_source


def _seal_v2(output: Path) -> None:
    summary_path=output/"summary.json"; identity_path=output/"research-champion-identity.json"
    summary=json.loads(summary_path.read_text(encoding="utf-8")); identity=json.loads(identity_path.read_text(encoding="utf-8"))
    binding={"profile":PROFILE,"economic_change_count":1,"changed_domain":"wealth_core_entry_slot_funding","target_slots":25,"entry_weight":0.04,"cash_clip_at_decision":False,"full_whole_share_target_required":True,"pending_cash_reserved":True,"next_open_fill_bounded_by_reservation":True,"later_unrelated_cash_can_rescue":False,"top_up":False,"winner_trim":False,"leverage":False,"minimum_fill_threshold":None}
    summary["wealth_core_v2"]=binding; identity["wealth_core_v2"]=binding
    summary_path.write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    identity_path.write_text(json.dumps(identity,indent=2,sort_keys=True)+"\n",encoding="utf-8")


def _self_test_helpers() -> int:
    synthetic="\n".join(p.old for p in V2_PATCHES); v2=apply_v2_patch(synthetic)
    if v2==synthetic: raise RuntimeError("synthetic V2 patch made no changes")
    print("[HELPER_SELFTEST] PASS reversible-v2-patch",flush=True); return 0


def _self_test_formal() -> int:
    prior=os.environ.pop("CANONICAL_PIT_DATASET",None)
    try:
        _,transform=_formal_transform()
        v1u=transform("fullpit",Path("/tmp/wc-formal-ab-v1-unbound")); v2u=apply_v2_patch(v1u)
        o1,_=install_audit(v1u,variant="V1"); o2,_=install_audit(v2u,variant="V2")
        compile(o1,"<wc-formal-v1-unbound>","exec"); compile(o2,"<wc-formal-v2-unbound>","exec")
        os.environ["CANONICAL_PIT_DATASET"]="/tmp/source-generation-only-canonical-pit"
        v1=transform("fullpit",Path("/tmp/wc-formal-ab-v1-canonical")); v2=apply_v2_patch(v1)
        o1,_=install_audit(v1,variant="V1"); o2,_=install_audit(v2,variant="V2")
        compile(o1,"<wc-formal-v1-canonical>","exec"); compile(o2,"<wc-formal-v2-canonical>","exec")
        if "Canonical dividends already use the as-traded share basis." not in v1: raise RuntimeError("canonical formal source path was not exercised")
        if hashlib.sha256(v1.encode()).hexdigest()==hashlib.sha256(v2.encode()).hexdigest(): raise RuntimeError("V1 and V2 economic sources unexpectedly identical")
    finally:
        if prior is None: os.environ.pop("CANONICAL_PIT_DATASET",None)
        else: os.environ["CANONICAL_PIT_DATASET"]=prior
    print("[FORMAL_SOURCE_SELFTEST] PASS V1+V2 canonical/unbound reversible+audit",flush=True); return 0


def main() -> int:
    if "--self-test-helpers" in sys.argv[1:]: return _self_test_helpers()
    if "--self-test-formal" in sys.argv[1:]: return _self_test_formal()
    variant=os.environ.get("WC_AB_VARIANT","").upper()
    if variant not in {"V1","V2"}: raise RuntimeError("WC_AB_VARIANT must be V1 or V2")
    formal,transform=_formal_transform()
    def observed_transform(mode,output):
        v1=transform(mode,output); economic=v1 if variant=="V1" else apply_v2_patch(v1)
        observed,_=install_audit(economic,variant=variant); return observed
    formal.champion.strict20.corrected.transformed_source=observed_transform
    rc=int(formal.main())
    if rc!=0: return rc
    args=sys.argv[1:]
    try: output=Path(args[args.index("--output")+1])
    except (ValueError,IndexError): raise RuntimeError("formal A/B wrapper requires --output")
    if variant=="V2": _seal_v2(output)
    print(f"[WEALTH_CORE_FORMAL_AB] PASS variant={variant}",flush=True); return 0


if __name__=="__main__": raise SystemExit(main())
