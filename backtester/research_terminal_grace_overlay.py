#!/usr/bin/env python3
"""Backtester-only retained-research terminal settlement overlay.

Align the compact retained research replay with frozen production's C1 semantics:
a documented terminal event with unreadable consideration is carried while it
continues to print, then ages only on sessions without a valid price. After ten
missing-price sessions it is proxy-settled at the last trustworthy raw mark,
without transaction cost, and the slot/security cooldown begins at age zero.
"""
from __future__ import annotations


C1_GRACE_SESSIONS = 10


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old, new, 1)


def install(text: str) -> str:
    text = _replace_once(
        text,
        "    sec_ready:dict=field(default_factory=dict); initialized:bool=False; last_raw:dict=field(default_factory=dict)",
        "    sec_ready:dict=field(default_factory=dict); terminal_pending:dict=field(default_factory=dict); initialized:bool=False; last_raw:dict=field(default_factory=dict)",
        "terminal pending state",
    )

    old_event = """            dayact=actions.get(date,{})
            term_tids={tmap[tk] for tk,rs in dayact.items() if tk in tmap and any(a in TERMINAL for a,_,_ in rs)}
            for s in book.slots:
                if s.reserved() and s.pending_tid in term_tids: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1
                if s.held() and s.tid in term_tids and not s.pending_sell: s.pending_sell=True; s.sell_reason='terminal'
            open_eq,_=book.equity(opraw)
"""
    new_event = """            dayact=actions.get(date,{})
            term_tids={tmap[tk] for tk,rs in dayact.items() if tk in tmap and any(a in TERMINAL for a,_,_ in rs)}
            for s in book.slots:
                if s.reserved() and s.pending_tid in term_tids: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1
                if not(s.held() and s.tid in term_tids): continue
                # Production C1: a known terminal event with unreadable terms is
                # a carried claim, not an immediate market sell. Carry requires
                # a trustworthy mark that existed before the event. If none
                # exists but today's security has a valid executable print,
                # production settles on that print without transaction cost.
                _prior=book.last_raw.get(s.tid,np.nan)
                if finite(_prior) and _prior>0:
                    book.terminal_pending.setdefault(s.tid,{'missing_sessions':0,'stale_at_event':0})
                elif finite(clraw[s.tid]) and clraw[s.tid]>0 and finite(volume[s.tid]) and volume[s.tid]>0:
                    _tid=s.tid; book.cash+=s.qty*float(clraw[_tid]); book.sec_ready[_tid]=gday+COOLDOWN
                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN
                else:
                    raise RuntimeError(f'known terminal event cannot be valued causally: {ds} {tick[s.tid]}')
            open_eq,_=book.equity(opraw)
"""
    text = _replace_once(text, old_event, new_event, "terminal event carry")

    old_fallback = """                elif s.sell_reason=='terminal':
                    px2=book.last_raw.get(s.tid,np.nan)
                    if finite(px2) and px2>0: book.cash+=s.qty*float(px2)*(1-COST)
                    book.sec_ready[s.tid]=gday+COOLDOWN
                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN
"""
    text = _replace_once(text, old_fallback, "", "remove immediate terminal sale fallback")

    old_sell_release = """                    book.sec_ready[s.tid]=gday+COOLDOWN
                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN
"""
    new_sell_release = """                    _sold_tid=s.tid; book.sec_ready[_sold_tid]=gday+COOLDOWN; book.terminal_pending.pop(_sold_tid,None)
                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN
"""
    text = _replace_once(text, old_sell_release, new_sell_release, "ordinary exit terminal-state cleanup")

    old_mark = """            for tid0 in tids:
                if finite(clraw[int(tid0)]) and clraw[int(tid0)]>0: book.last_raw[int(tid0)]=float(clraw[int(tid0)])

            # Close: peaks/exits, mark equity, breadth, then admissions.
"""
    new_mark = f"""            for tid0 in tids:
                if finite(clraw[int(tid0)]) and clraw[int(tid0)]>0: book.last_raw[int(tid0)]=float(clraw[int(tid0)])

            # Production C1 sweep: the grace clock advances only when the
            # carried security fails to produce a current mark. A current print
            # pauses (but does not reset) the clock. Settlement is a proxy claim
            # valuation, not a simulated sale, so no transaction cost is charged.
            for _tid in list(book.terminal_pending):
                _slot=next((x for x in book.slots if x.held() and x.tid==_tid),None)
                if _slot is None:
                    book.terminal_pending.pop(_tid,None); continue
                if _tid in term_tids: continue
                if finite(clraw[_tid]) and clraw[_tid]>0: continue
                _rec=book.terminal_pending[_tid]; _rec['missing_sessions']+=1
                if _rec['missing_sessions'] < {C1_GRACE_SESSIONS}: continue
                _px=book.last_raw.get(_tid,np.nan)
                if not(finite(_px) and _px>0):
                    raise RuntimeError(f'pending terminal settlement lost trustworthy mark: {{ds}} {{tick[_tid]}}')
                book.cash+=_slot.qty*float(_px); book.sec_ready[_tid]=gday+COOLDOWN; book.terminal_pending.pop(_tid,None)
                _slot.tid=-1; _slot.qty=0.; _slot.entry_sig=np.nan; _slot.peak=np.nan; _slot.entry_day=-1; _slot.reviewed=False; _slot.pending_sell=False; _slot.sell_reason=''; _slot.ready_day=gday+COOLDOWN

            # Close: peaks/exits, mark equity, breadth, then admissions.
"""
    text = _replace_once(text, old_mark, new_mark, "terminal grace sweep")

    forbidden = ("sell_reason='terminal'", "px2=book.last_raw.get(s.tid")
    for needle in forbidden:
        if needle in text:
            raise RuntimeError(f"retained research immediate-terminal-sale defect survived overlay: {needle}")
    return text
