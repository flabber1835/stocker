#!/usr/bin/env python3
from pathlib import Path

p = Path('audit-src/research/champion-alpha-five-run-validation-v2/experiment_runner.py')
s = p.read_text()

helper = r'''
def _instrument_slot_forensics(text: str) -> str:
    def rep(old: str, new: str, label: str) -> None:
        nonlocal text
        n = text.count(old)
        if n != 1:
            raise RuntimeError(f"slot forensics {label}: expected 1 anchor, got {n}")
        text = text.replace(old, new, 1)

    rep(
        "    actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()\n",
        "    actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()\n"
        "    _FORENSIC_TARGET_SIDS={'1125757768717674484':'LLYVK','700818629905779940':'RCUS'}\n"
        "    _slot_forensic_events=[]\n",
        "forensic init",
    )

    rep(
        "                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; resids.add(tid); resissuers.add(issuer_key(tid,ds)); ad+=1\n",
        "                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday\n"
        "                        _nominal=float(eq*ENTRY_W); _signal_notional=float(q)*float(px)*(1+COST)\n"
        "                        _slot_forensic_events.append({'kind':'reservation','session':ds,'gday':int(gday),'slot':int(next(_i for _i,_x in enumerate(book.slots) if _x is s)),'ticker':str(tick[tid]),'security_id':str(sid[tid]),'shares':float(q),'raw_close':float(px),'cash':float(book.cash),'equity':float(eq),'nominal_target':_nominal,'reserved_notional':_signal_notional,'fill_fraction_of_nominal':float(_signal_notional/_nominal) if _nominal>0 else None})\n"
        "                        resids.add(tid); resissuers.add(issuer_key(tid,ds)); ad+=1\n",
        "reservation",
    )

    rep(
        "                    if q>=1:\n                        book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1\n",
        "                    if q>=1:\n"
        "                        _cash_before=float(book.cash); _pending=float(s.pending_shares); _sigday=int(s.pending_signal_day)\n"
        "                        book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1\n"
        "                        _nominal_open=float(open_eq*ENTRY_W); _fill_notional=float(q)*float(px)*(1+COST)\n"
        "                        _slot_forensic_events.append({'kind':'buy_fill','session':ds,'gday':int(gday),'slot':int(next(_i for _i,_x in enumerate(book.slots) if _x is s)),'ticker':str(tick[tid]),'security_id':str(sid[tid]),'signal_gday':_sigday,'pending_shares':_pending,'executed_shares':float(q),'raw_open':float(px),'reported_volume':float(volume[tid]) if finite(volume[tid]) else None,'cash_before':_cash_before,'cash_after':float(book.cash),'open_equity':float(open_eq),'nominal_target_open':_nominal_open,'fill_notional':_fill_notional,'fill_fraction_of_nominal_open':float(_fill_notional/_nominal_open) if _nominal_open>0 else None})\n",
        "buy fill",
    )

    rep(
        "                if finite(px) and finite(s.peak) and s.peak>0 and float(px)<=s.peak*STOP_RET:\n                    s.pending_sell=True; s.sell_reason='stop'\n",
        "                if finite(px) and finite(s.peak) and s.peak>0 and float(px)<=s.peak*STOP_RET:\n"
        "                    _was_pending=bool(s.pending_sell); s.pending_sell=True; s.sell_reason='stop'\n"
        "                    _slot_forensic_events.append({'kind':'sell_signal','session':ds,'gday':int(gday),'reason':'stop','already_pending':_was_pending,'ticker':str(tick[s.tid]),'security_id':str(sid[s.tid]),'shares':float(s.qty),'signal_close':float(px),'peak':float(s.peak),'entry_sig':float(s.entry_sig) if finite(s.entry_sig) else None,'age':int(age)})\n",
        "stop signal",
    )

    rep(
        "                    if underwater and not qualifies: s.pending_sell=True; s.sell_reason='review'\n",
        "                    if underwater and not qualifies:\n"
        "                        _was_pending=bool(s.pending_sell); s.pending_sell=True; s.sell_reason='review'\n"
        "                        _slot_forensic_events.append({'kind':'sell_signal','session':ds,'gday':int(gday),'reason':'review','already_pending':_was_pending,'ticker':str(tick[s.tid]),'security_id':str(sid[s.tid]),'shares':float(s.qty),'signal_close':float(px),'peak':float(s.peak) if finite(s.peak) else None,'entry_sig':float(s.entry_sig) if finite(s.entry_sig) else None,'age':int(age),'qualifies':bool(qualifies),'underwater':bool(underwater)})\n",
        "review signal",
    )

    rep(
        "                px=opraw[s.tid]\n                if finite(px) and px>0 and finite(volume[s.tid]) and volume[s.tid]>0:\n",
        "                px=opraw[s.tid]\n"
        "                _tradeable=bool(finite(px) and px>0 and finite(volume[s.tid]) and volume[s.tid]>0)\n"
        "                _slot_forensic_events.append({'kind':'sell_attempt','session':ds,'gday':int(gday),'reason':str(s.sell_reason),'ticker':str(tick[s.tid]),'security_id':str(sid[s.tid]),'shares':float(s.qty),'raw_open':float(px) if finite(px) else None,'reported_volume':float(volume[s.tid]) if finite(volume[s.tid]) else None,'tradeable':_tradeable})\n"
        "                if _tradeable:\n",
        "sell attempt",
    )

    rep(
        "                    book.cash+=s.qty*float(px)*(1-COST); sells+=1\n",
        "                    _sell_qty=float(s.qty); _sell_tid=int(s.tid); _cash_before_sell=float(book.cash)\n"
        "                    book.cash+=s.qty*float(px)*(1-COST); sells+=1\n"
        "                    _slot_forensic_events.append({'kind':'sell_fill','session':ds,'gday':int(gday),'reason':str(s.sell_reason),'ticker':str(tick[_sell_tid]),'security_id':str(sid[_sell_tid]),'shares':_sell_qty,'raw_open':float(px),'cash_before':_cash_before_sell,'cash_after':float(book.cash)})\n",
        "sell fill",
    )

    rep(
        "            shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)\n",
        "            # Observer-only state for the two suspicious end-book slots and for\n"
        "            # a one-free-slot admission witness. This never mutates book state.\n"
        "            for _si,_ss in enumerate(book.slots):\n"
        "                _sidv=str(sid[_ss.tid]) if _ss.held() else (str(sid[_ss.pending_tid]) if _ss.reserved() else None)\n"
        "                if _sidv in _FORENSIC_TARGET_SIDS:\n"
        "                    _tidv=int(_ss.tid) if _ss.held() else int(_ss.pending_tid)\n"
        "                    _slot_forensic_events.append({'kind':'target_state','session':ds,'gday':int(gday),'slot':int(_si),'ticker':str(tick[_tidv]),'security_id':_sidv,'held':bool(_ss.held()),'reserved':bool(_ss.reserved()),'qty':float(_ss.qty),'pending_shares':float(_ss.pending_shares),'pending_sell':bool(_ss.pending_sell),'sell_reason':str(_ss.sell_reason),'entry_day':int(_ss.entry_day),'entry_sig':float(_ss.entry_sig) if finite(_ss.entry_sig) else None,'peak':float(_ss.peak) if finite(_ss.peak) else None,'raw_open':float(opraw[_tidv]) if finite(opraw[_tidv]) else None,'raw_close':float(clraw[_tidv]) if finite(clraw[_tidv]) else None,'signal_close':float(clsig[_tidv]) if finite(clsig[_tidv]) else None,'reported_volume':float(volume[_tidv]) if finite(volume[_tidv]) else None,'cash':float(book.cash),'equity':float(eq),'held_count':int(sum(1 for _x in book.slots if _x.held()))})\n"
        "            _full_now=(sum(1 for _x in book.slots if _x.held())>=N_SLOTS and not any(_x.reserved() and not _x.held() for _x in book.slots))\n"
        "            if _full_now and book.cash>0 and not unresolved:\n"
        "                for _target_slot in [x for x in book.slots if x.held() and str(sid[x.tid]) in _FORENSIC_TARGET_SIDS]:\n"
        "                    _drop=int(_target_slot.tid); _heldids={x.tid for x in book.slots if x.held() and x is not _target_slot}; _resids=book.reserved_ids()\n"
        "                    _heldissuers={issuer_key(x.tid,ds) for x in book.slots if x.held() and x is not _target_slot}; _resissuers={issuer_key(x.pending_tid,ds) for x in book.slots if x.reserved()}\n"
        "                    _cf=None\n"
        "                    for _ctid0 in _harden_order(durable,score,_rank_order_hist):\n"
        "                        _ctid=int(_ctid0)\n"
        "                        if _ctid==_drop or not finite(recent[_ctid]) or recent[_ctid]<0: continue\n"
        "                        if _ctid in _heldids or _ctid in _resids or book.sec_ready.get(_ctid,-1)>gday or _ctid in term_tids: continue\n"
        "                        if issuer_key(_ctid,ds) in _heldissuers or issuer_key(_ctid,ds) in _resissuers: continue\n"
        "                        _cpx=clraw[_ctid]\n"
        "                        if not(finite(_cpx) and _cpx>0): continue\n"
        "                        _ctarget=min(eq*ENTRY_W,book.cash); _cq=int(_ctarget//(float(_cpx)*(1+COST)))\n"
        "                        if _cq<1: continue\n"
        "                        _cf={'ticker':str(tick[_ctid]),'security_id':str(sid[_ctid]),'shares':float(_cq),'raw_close':float(_cpx),'reserved_notional':float(_cq)*float(_cpx)*(1+COST),'nominal_target':float(eq*ENTRY_W),'cash':float(book.cash)}; break\n"
        "                    _slot_forensic_events.append({'kind':'candidate_if_target_slot_free','session':ds,'gday':int(gday),'freed_ticker':str(tick[_drop]),'freed_security_id':str(sid[_drop]),'candidate':_cf})\n"
        "            shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)\n",
        "target state and blocked candidate",
    )

    rep(
        "    (OUT/'summary.json').write_text(json.dumps(summary,indent=2))\n",
        "    (OUT/'slot-forensics.json').write_text(json.dumps(_slot_forensic_events,indent=2,sort_keys=True))\n"
        "    (OUT/'summary.json').write_text(json.dumps(summary,indent=2))\n",
        "forensics output",
    )
    compile(text, '<median5-slot-forensics>', 'exec')
    return text
'''

anchor = '\ndef main() -> int:\n'
if anchor not in s:
    raise RuntimeError('runner main anchor missing')
s = s.replace(anchor, '\n' + helper + anchor, 1)
old = '    variant = apply_arm(certified_base, args.arm)\n'
new = old + '    variant = _instrument_slot_forensics(variant)\n'
if s.count(old) != 1:
    raise RuntimeError('variant instrumentation anchor missing')
s = s.replace(old, new, 1)
p.write_text(s)
print('instrumented Median-5 runner for slot forensics')
