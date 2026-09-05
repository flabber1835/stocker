#!/usr/bin/env python3
"""Backtester-only retained-research financial-equivalence overlay.

The compact retained research engine predates several economic rules now owned
by Production. This transform makes those rules explicit and fail-closed:

1. exact authenticated terminal terms are applied when available;
2. incomplete terminal events use the same bounded carried-mark convention;
3. same-session splits precede dividend entitlement capture;
4. executable orders require 20 prior positive raw-compatible volume sessions
   and may not exceed 10% of their trailing average share volume.
"""
from __future__ import annotations

import math
from typing import Sequence


C1_GRACE_SESSIONS = 10
MIN_TRAILING_VOLUME_SESSIONS = 20
MAX_TRAILING_VOLUME_PARTICIPATION = 0.10


class ResearchFinancialGradeError(RuntimeError):
    """Retained research reached economics that cannot be certified."""


def _positive(value) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0.0


def capacity_guard(
    shares,
    prior_volumes: Sequence[float],
    *,
    security_id: str,
    session: str,
    defer_excess: bool = False,
) -> float | None:
    """Apply Production's prior-20-volume executable-order capacity rule.

    A missing 20-session authority is always a certification failure. An order
    above the 10% ceiling may be kept pending by the replay and retried on a
    later session; this preserves the strategy's requested share quantity while
    enforcing the execution-capacity boundary causally.
    """
    history = [float(value) for value in list(prior_volumes)[-MIN_TRAILING_VOLUME_SESSIONS:]
               if _positive(value)]
    if len(history) < MIN_TRAILING_VOLUME_SESSIONS:
        raise ResearchFinancialGradeError(
            f"capacity authority incomplete for executable order {security_id} on {session}: "
            f"have {len(history)} prior volume sessions, require "
            f"{MIN_TRAILING_VOLUME_SESSIONS}"
        )
    average = sum(history) / len(history)
    participation = float(shares) / average
    if participation > MAX_TRAILING_VOLUME_PARTICIPATION + 1e-15:
        if defer_excess:
            return None
        raise ResearchFinancialGradeError(
            f"capacity ceiling exceeded on {session} {security_id}: "
            f"participation={participation:.4%} > "
            f"{MAX_TRAILING_VOLUME_PARTICIPATION:.2%}"
        )
    return participation


def exact_terminal_economics(
    *,
    kind: str,
    shares,
    cash_per_share=None,
    exchange_ratio=None,
    cash_in_lieu_price=None,
) -> dict:
    """Return exact cash/share consideration for one authenticated terminal."""
    quantity = float(shares)
    if not _positive(quantity):
        raise ResearchFinancialGradeError("terminal settlement has non-positive shares")
    if kind == "WRITE_OFF":
        return {"cash": 0.0, "delivered_shares": 0, "fraction": 0.0}
    if kind == "CASH_MERGER":
        if cash_per_share is None or not math.isfinite(float(cash_per_share)) or float(cash_per_share) < 0:
            raise ResearchFinancialGradeError("cash merger lacks non-negative exact cash terms")
        return {
            "cash": quantity * float(cash_per_share),
            "delivered_shares": 0,
            "fraction": 0.0,
        }
    if kind not in {"CONVERSION", "CASH_PLUS_STOCK"}:
        raise ResearchFinancialGradeError(f"unsupported exact terminal kind {kind!r}")
    if not _positive(exchange_ratio):
        raise ResearchFinancialGradeError("conversion lacks positive exchange ratio")
    ratio = float(exchange_ratio)
    exact = quantity * ratio
    whole = int(math.floor(exact + 1e-9))
    fraction = max(0.0, exact - whole)
    lieu = 0.0
    if fraction > 0:
        if cash_in_lieu_price is None or not math.isfinite(float(cash_in_lieu_price)) or float(cash_in_lieu_price) < 0:
            raise ResearchFinancialGradeError("fractional conversion lacks cash-in-lieu price")
        lieu = fraction * float(cash_in_lieu_price)
    cash_leg = 0.0
    if kind == "CASH_PLUS_STOCK":
        if cash_per_share is None or not math.isfinite(float(cash_per_share)) or float(cash_per_share) < 0:
            raise ResearchFinancialGradeError("mixed terminal lacks non-negative cash leg")
        cash_leg = quantity * float(cash_per_share)
    return {
        "cash": cash_leg + lieu,
        "delivered_shares": whole,
        "fraction": fraction,
    }


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old, new, 1)


def _replace_bounded_once(
    text: str, start_anchor: str, end_anchor: str, replacement: str, label: str
) -> str:
    starts = text.count(start_anchor)
    ends = text.count(end_anchor)
    if starts != 1 or ends != 1:
        raise RuntimeError(
            f"{label}: expected unique anchors, found start={starts} end={ends}"
        )
    start = text.index(start_anchor)
    end = text.index(end_anchor, start)
    if end <= start:
        raise RuntimeError(f"{label}: malformed source seam")
    return text[:start] + replacement + text[end:]


def _move_prior_qty_after_split(text: str) -> str:
    entitlement = "            prior_qty={s.tid:s.qty for s in book.slots if s.held()}\n"
    dayact = "            dayact=actions.get(date,{})\n"
    if text.count(entitlement) != 1:
        raise RuntimeError(
            "dividend entitlement capture: expected one source seam, "
            f"found {text.count(entitlement)}"
        )
    if text.count(dayact) != 1:
        raise RuntimeError(
            f"post-split day-action anchor: expected one source seam, found {text.count(dayact)}"
        )
    if text.index(entitlement) > text.index(dayact):
        raise RuntimeError("dividend entitlement capture unexpectedly already follows day-action anchor")
    text = text.replace(entitlement, "", 1)
    insertion = (
        "            # Capture prior-close entitlement after split-domain conversion,\n"
        "            # before any same-open exits or buys.\n"
        + entitlement
        + dayact
    )
    return text.replace(dayact, insertion, 1)


def install(text: str) -> str:
    # Generated research source may run outside the canonical package in import
    # self-tests, so exact-term activation is runtime-conditional on _CANONICAL.
    import_anchor = "from collections import defaultdict\n"
    import_replacement = (
        import_anchor
        + "from backtester.causal_terminal_terms import load_frozen_terminal_terms\n"
        + "from stock_strategy_shared.wealth_core.terminal import TerminalKind as _ProductionTerminalKind, TerminalTerms as _ProductionTerminalTerms\n"
        + "from backtester.research_terminal_grace_overlay import "
          "capacity_guard as _research_capacity_guard, exact_terminal_economics as _research_exact_terminal_economics\n"
    )
    text = _replace_once(text, import_anchor, import_replacement, "financial-grade imports")

    text = _replace_once(
        text,
        "    sec_ready:dict=field(default_factory=dict); initialized:bool=False; last_raw:dict=field(default_factory=dict)",
        "    sec_ready:dict=field(default_factory=dict); terminal_pending:dict=field(default_factory=dict); initialized:bool=False; last_raw:dict=field(default_factory=dict)",
        "terminal pending state",
    )

    init_anchor = "actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()"
    init_replacement = init_anchor + r'''
    _capacity_volumes=defaultdict(list)
    _sid_to_tid={str(value):i for i,value in enumerate(sid)}
    _exact_terminal_by_session={}; _exact_terminal_terms_hash=None
    if globals().get('_CANONICAL') is not None:
        def _terminal_resolve(_ticker,_session):
            _tid=strict_tid(_ticker,_session) if 'strict_tid' in globals() else tmap.get(str(_ticker))
            return None if _tid is None else str(sid[int(_tid)])
        def _terminal_issuer(_security_id,_ticker,_session):
            _tid=_sid_to_tid.get(str(_security_id))
            return (None,None) if _tid is None else (issuer_key(_tid,str(_session)), 'RESEARCH_STRICT_PIT')
        _loaded,_exact_terminal_terms_hash=load_frozen_terminal_terms(
            Path('backtester/data/causal-terminal-terms-v1.json'),
            Path('backtester/data/causal-terminal-terms-v1.SHA256'),
            sessions=list(_CANONICAL.sessions),
            resolve_identity=_terminal_resolve,
            meta={str(value):object() for value in sid},
            TerminalTerms=_ProductionTerminalTerms,
            TerminalKind=_ProductionTerminalKind,
            identity_binding='resolved',
            delivered_issuer_resolver=_terminal_issuer)
        for _session,_terms in _loaded.items():
            _exact_terminal_by_session[str(_session)]={
                _sid_to_tid[str(_term.security_id)]:_term for _term in _terms
                if str(_term.security_id) in _sid_to_tid}
'''
    text = _replace_once(text, init_anchor, init_replacement, "financial-grade runtime state")

    # Split transformations must precede the ex-date entitlement quantity.
    text = _move_prior_qty_after_split(text)

    start_anchor = "            dayact=actions.get(date,{})\n"
    end_anchor = "            open_eq,_=book.equity(opraw)\n"
    new_event = """            dayact=actions.get(date,{})
            def _term_tid(_ticker):
                return strict_tid(_ticker,ds) if 'strict_tid' in globals() else tmap.get(str(_ticker))
            term_tids={z for tk,rs in dayact.items() if (z:=_term_tid(tk)) is not None and any(a in TERMINAL for a,_,_ in rs)}
            _exact_terms=_exact_terminal_by_session.get(ds,{})
            term_tids.update(_exact_terms)
            for s in book.slots:
                if s.reserved() and s.pending_tid in term_tids: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1
                if not(s.held() and s.tid in term_tids): continue
                _term=_exact_terms.get(s.tid)
                if _term is not None:
                    _kind=getattr(_term.kind,'value',str(_term.kind))
                    _econ=_research_exact_terminal_economics(
                        kind=_kind, shares=s.qty,
                        cash_per_share=getattr(_term,'cash_per_share',None),
                        exchange_ratio=getattr(_term,'exchange_ratio',None),
                        cash_in_lieu_price=getattr(_term,'cash_in_lieu_price_per_delivered_share',None))
                    _old_tid=s.tid; book.cash+=float(_econ['cash']); book.terminal_pending.pop(_old_tid,None)
                    if _kind in ('WRITE_OFF','CASH_MERGER') or int(_econ['delivered_shares'])<=0:
                        book.sec_ready[_old_tid]=gday+COOLDOWN
                        s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN
                    else:
                        _delivered=_sid_to_tid.get(str(getattr(_term,'delivered_security_id',None)))
                        _ratio=float(getattr(_term,'exchange_ratio'))
                        if _delivered is None or not(finite(_ratio) and _ratio>0):
                            raise RuntimeError(f'exact terminal delivered identity unresolved: {ds} {tick[_old_tid]}')
                        s.tid=int(_delivered); s.qty=float(_econ['delivered_shares'])
                        if finite(s.entry_sig): s.entry_sig=float(s.entry_sig)/_ratio
                        if finite(s.peak): s.peak=float(s.peak)/_ratio
                    continue
                # Production C1: incomplete documented terms become a carried
                # claim. A real prior trustworthy mark is required.
                _prior=book.last_raw.get(s.tid,np.nan)
                if finite(_prior) and _prior>0:
                    book.terminal_pending.setdefault(s.tid,{'missing_sessions':0,'stale_at_event':0})
                elif finite(clraw[s.tid]) and clraw[s.tid]>0 and finite(volume[s.tid]) and volume[s.tid]>0:
                    _tid=s.tid; book.cash+=s.qty*float(clraw[_tid]); book.sec_ready[_tid]=gday+COOLDOWN
                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN
                else:
                    raise RuntimeError(f'known terminal event cannot be valued causally: {ds} {tick[s.tid]}')
"""
    text = _replace_bounded_once(
        text, start_anchor, end_anchor, new_event, "terminal event accounting"
    )

    old_fallback = """                elif s.sell_reason=='terminal':
                    px2=book.last_raw.get(s.tid,np.nan)
                    if finite(px2) and px2>0: book.cash+=s.qty*float(px2)*(1-COST)
                    book.sec_ready[s.tid]=gday+COOLDOWN
                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN
"""
    text = _replace_once(text, old_fallback, "", "remove immediate terminal sale fallback")

    old_sell_guard = """                if finite(px) and px>0 and finite(volume[s.tid]) and volume[s.tid]>0:
                    book.cash+=s.qty*float(px)*(1-COST); sells+=1
"""
    new_sell_guard = """                if finite(px) and px>0 and finite(volume[s.tid]) and volume[s.tid]>0:
                    if _research_capacity_guard(s.qty,_capacity_volumes.get(int(s.tid),()),security_id=str(sid[int(s.tid)]),session=ds,defer_excess=True) is None:
                        continue
                    book.cash+=s.qty*float(px)*(1-COST); sells+=1
"""
    text = _replace_once(text, old_sell_guard, new_sell_guard, "exit capacity guard")

    old_buy_guard = """                if finite(px) and px>0 and finite(volume[tid]) and volume[tid]>0:
                    afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford)
"""
    new_buy_guard = """                if finite(px) and px>0 and finite(volume[tid]) and volume[tid]>0:
                    if _research_capacity_guard(s.pending_shares,_capacity_volumes.get(int(tid),()),security_id=str(sid[int(tid)]),session=ds,defer_excess=True) is None:
                        continue
                    afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford)
"""
    text = _replace_once(text, old_buy_guard, new_buy_guard, "entry capacity guard")

    # Record current session raw-compatible share volume only after all current
    # open fills. The next session therefore sees exactly prior observations.
    dividend_anchor = "            # Canonical dividends already use the as-traded share basis.\n"
    if dividend_anchor not in text:
        dividend_anchor = "            # Dividends use prior-close raw share quantity and current raw/signal price factor.\n"
    volume_update = """            for _tid0,_sig_close,_raw_close,_reported_volume in zip(tids,c,cu,vol):
                if finite(_sig_close) and _sig_close>0 and finite(_raw_close) and _raw_close>0 and finite(_reported_volume) and _reported_volume>0:
                    _raw_compatible=float(_reported_volume)*float(_sig_close)/float(_raw_close)
                    if finite(_raw_compatible) and _raw_compatible>0:
                        _hist=_capacity_volumes[int(_tid0)]; _hist.append(float(_raw_compatible))
                        if len(_hist)>20: del _hist[:-20]

"""
    text = _replace_once(text, dividend_anchor, volume_update + dividend_anchor, "capacity history update")

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

            # Production C1 sweep: age only sessions lacking a current mark.
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

    entitlement = "prior_qty={s.tid:s.qty for s in book.slots if s.held()}"
    dayact = "dayact=actions.get(date,{})"
    if text.count(entitlement) != 1 or text.index(entitlement) > text.index(dayact):
        raise RuntimeError("retained research split-dividend ordering repair did not survive overlay")
    required = (
        "load_frozen_terminal_terms(",
        "_ProductionTerminalTerms",
        "_ProductionTerminalKind",
        "_research_exact_terminal_economics(",
        "_research_capacity_guard(s.qty",
        "_research_capacity_guard(s.pending_shares",
        "defer_excess=True",
        "_capacity_volumes[int(_tid0)]",
    )
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise RuntimeError(f"retained research financial-grade seams missing: {missing}")
    forbidden = (
        "SimpleNamespace",
        "sell_reason='terminal'",
        "px2=book.last_raw.get(s.tid",
    )
    for needle in forbidden:
        if needle in text:
            raise RuntimeError(f"retained research economic defect survived overlay: {needle}")
    return text