#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd

CONTROL_COMMIT = "1d3ab06a0b6c1ef5db4939bbecfe24953ae2195d"
CONTROL_RUN_ID = 34071569702
CONTROL_ARTIFACT_ID = 10001317230
CONTROL_ARTIFACT_DIGEST = "sha256:803b1b8288d77fc9c275cec5ebac91f8bac23ba030dad3dfb5d523fceed2415f"
CONTROL_SOURCE_SHA256 = "bbd6783d0cd0e5d1662a0146190962e5845cc4b6bdb8feb50d0c7788f90a6077"
CONTROL_NORMALIZED_AST_SHA256 = "435d42ac56f160a665588a997335a923c25110404972e262aa6e47058b3befde"
CONTROL_DAILY_SHA256 = "2fc1137529a7bb6e4c596d42a7af9bb0e3c891c3126116d15c342b8988235dfe"
CONTROL_SUMMARY_SHA256 = "d49d28069647097dea6c1c3417213a5dc9333e1ea33c8ef651f015b718cb22da"
DATASET_SHA256 = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"
MICRO_FRACTION = 0.01

CONTROL_METRICS = {
    "cagr": 0.1524665012369839,
    "ending_multiple": 17.08407706744625,
    "max_drawdown": -0.4804421814863442,
    "sharpe_daily_252": 0.8044766146429867,
    "average_held_count": 22.67885532591415,
    "median_held_count": 24.0,
    "full_slot_sessions": 1217,
    "buys": 505,
    "sells": 424,
}

VARIANTS = {
    "virtual-slot-escrow": (
        "Convert decision-time entries below 1% of intended Wealth Core entry capital into non-invested capacity slots. "
        "The slot shadow-tracks the same candidate lifecycle; the would-be execution capital is held as locked cash and is not available for new admissions until release."
    ),
    "virtual-slot-free-cash": (
        "Convert decision-time entries below 1% of intended Wealth Core entry capital into non-invested capacity slots. "
        "The slot shadow-tracks the same candidate lifecycle; no capital is locked, so all cash remains available for other admissions."
    ),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {n}")
    return text.replace(old, new, 1)


def patch_source(v1: str, variant: str) -> str:
    if variant not in VARIANTS:
        raise ValueError(variant)
    escrow = variant == "virtual-slot-escrow"
    out = v1

    # Explicit capacity state. qty remains the hypothetical share count so the
    # candidate follows the exact V1 stop/review/split lifecycle, but equity and
    # cash flows distinguish virtual slots from real holdings.
    out = replace_once(
        out,
        "    pending_sell:bool=False; sell_reason:str=''; pending_tid:int=-1; pending_shares:float=0.; pending_signal_day:int=-1; ready_day:int=0",
        "    pending_sell:bool=False; sell_reason:str=''; pending_tid:int=-1; pending_shares:float=0.; pending_signal_day:int=-1; pending_virtual:bool=False; pending_intended_capital:float=0.; virtual:bool=False; virtual_cash:float=0.; ready_day:int=0",
        "slot virtual state",
    )

    out = replace_once(
        out,
        "            if s.held():\n                p=raw[s.tid]",
        "            if s.held():\n                if s.virtual:\n                    p=raw[s.tid]\n                    if not (finite(p) and p>0): unresolved=True\n                    v+=float(s.virtual_cash); continue\n                p=raw[s.tid]",
        "virtual equity is cash, not security mark",
    )

    out = replace_once(
        out,
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0",
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; virtual_entries=virtual_releases=virtual_terminal_releases=virtual_stock_deliveries=virtual_decisions=virtual_gap_promotions=real_micro_executions=0; virtual_cash_locked_peak=0.0",
        "virtual telemetry counters",
    )

    # Terminal exact path: real positions preserve production economics; virtual
    # slots only shadow identity/lifecycle and eventually unlock escrowed cash.
    out = replace_once(
        out,
        "                    _old_tid=s.tid; book.cash+=float(_econ['cash']); book.terminal_pending.pop(_old_tid,None)\n                    if _kind in ('WRITE_OFF','CASH_MERGER') or int(_econ['delivered_shares'])<=0:\n                        book.sec_ready[_old_tid]=gday+COOLDOWN\n                        s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN\n                    else:\n                        _delivered=_sid_to_tid.get(str(getattr(_term,'delivered_security_id',None)))\n                        _ratio=float(getattr(_term,'exchange_ratio'))\n                        if _delivered is None or not(finite(_ratio) and _ratio>0):\n                            raise RuntimeError(f'exact terminal delivered identity unresolved: {ds} {tick[_old_tid]}')\n                        s.tid=int(_delivered); s.qty=float(_econ['delivered_shares'])\n                        if finite(s.entry_sig): s.entry_sig=float(s.entry_sig)/_ratio\n                        if finite(s.peak): s.peak=float(s.peak)/_ratio",
        "                    _old_tid=s.tid; book.terminal_pending.pop(_old_tid,None)\n                    if not s.virtual: book.cash+=float(_econ['cash'])\n                    if _kind in ('WRITE_OFF','CASH_MERGER') or int(_econ['delivered_shares'])<=0:\n                        if s.virtual: book.cash+=float(s.virtual_cash); virtual_terminal_releases+=1\n                        book.sec_ready[_old_tid]=gday+COOLDOWN\n                        s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.virtual=False; s.virtual_cash=0.; s.ready_day=gday+COOLDOWN\n                    else:\n                        _delivered=_sid_to_tid.get(str(getattr(_term,'delivered_security_id',None)))\n                        _ratio=float(getattr(_term,'exchange_ratio'))\n                        if _delivered is None or not(finite(_ratio) and _ratio>0):\n                            raise RuntimeError(f'exact terminal delivered identity unresolved: {ds} {tick[_old_tid]}')\n                        s.tid=int(_delivered); s.qty=float(_econ['delivered_shares'])\n                        if s.virtual: virtual_stock_deliveries+=1\n                        if finite(s.entry_sig): s.entry_sig=float(s.entry_sig)/_ratio\n                        if finite(s.peak): s.peak=float(s.peak)/_ratio",
        "exact terminal virtual semantics",
    )

    out = replace_once(
        out,
        "                    _tid=s.tid; book.cash+=s.qty*float(clraw[_tid]); book.sec_ready[_tid]=gday+COOLDOWN\n                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN",
        "                    _tid=s.tid; book.cash+=(float(s.virtual_cash) if s.virtual else s.qty*float(clraw[_tid])); virtual_terminal_releases+=int(s.virtual); book.sec_ready[_tid]=gday+COOLDOWN\n                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.virtual=False; s.virtual_cash=0.; s.ready_day=gday+COOLDOWN",
        "fallback terminal virtual release",
    )

    # Virtual slots never earn dividends because no security was actually owned.
    out = replace_once(
        out,
        "            prior_qty={s.tid:s.qty for s in book.slots if s.held()}",
        "            prior_qty={s.tid:s.qty for s in book.slots if s.held() and not s.virtual}",
        "virtual slots receive no dividends",
    )

    # Normal exits unlock any escrow instead of generating a security sale.
    out = replace_once(
        out,
        "                    book.cash+=s.qty*float(px)*(1-COST); sells+=1\n                    if s.sell_reason=='stop': stop_days.append(gday)\n                    _sold_tid=s.tid; book.sec_ready[_sold_tid]=gday+COOLDOWN; book.terminal_pending.pop(_sold_tid,None)\n                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN",
        "                    if s.virtual:\n                        book.cash+=float(s.virtual_cash); virtual_releases+=1\n                    else:\n                        book.cash+=s.qty*float(px)*(1-COST); sells+=1\n                    if s.sell_reason=='stop': stop_days.append(gday)\n                    _sold_tid=s.tid; book.sec_ready[_sold_tid]=gday+COOLDOWN; book.terminal_pending.pop(_sold_tid,None)\n                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.virtual=False; s.virtual_cash=0.; s.ready_day=gday+COOLDOWN",
        "normal virtual release",
    )

    # Pending buy resolution: microscopic decisions become capacity slots. The
    # escrow version removes the exact hypothetical gross execution cost from
    # free cash and keeps it as locked cash; the free-cash version locks zero.
    lock_expr = "q*float(px)*(1+COST)" if escrow else "0.0"
    out = replace_once(
        out,
        "                    afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford)\n                    if q>=1:\n                        book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1\n                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "                    afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford)\n                    if q>=1:\n                        _actual_fraction=(float(q)*float(px)*(1+COST)/float(s.pending_intended_capital) if s.pending_intended_capital>0 else 0.0)\n                        _make_virtual=bool(s.pending_virtual or _actual_fraction<0.01); virtual_gap_promotions+=int((not s.pending_virtual) and _actual_fraction<0.01)\n                        if _make_virtual:\n                            _vlock=float(" + lock_expr + "); book.cash-=_vlock; s.virtual=True; s.virtual_cash=_vlock; virtual_entries+=1; virtual_cash_locked_peak=max(virtual_cash_locked_peak,float(sum(x.virtual_cash for x in book.slots)))\n                            s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True\n                        else:\n                            real_micro_executions+=int(_actual_fraction<0.01); book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1\n                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_virtual=False; s.pending_intended_capital=0.",
        "virtual pending buy resolution",
    )

    # C1 delayed terminal settlement unlocks virtual escrow, no phantom security value.
    out = replace_once(
        out,
        "                book.cash+=_slot.qty*float(_px); book.sec_ready[_tid]=gday+COOLDOWN; book.terminal_pending.pop(_tid,None)\n                _slot.tid=-1; _slot.qty=0.; _slot.entry_sig=np.nan; _slot.peak=np.nan; _slot.entry_day=-1; _slot.reviewed=False; _slot.pending_sell=False; _slot.sell_reason=''; _slot.ready_day=gday+COOLDOWN",
        "                book.cash+=(float(_slot.virtual_cash) if _slot.virtual else _slot.qty*float(_px)); virtual_terminal_releases+=int(_slot.virtual); book.sec_ready[_tid]=gday+COOLDOWN; book.terminal_pending.pop(_tid,None)\n                _slot.tid=-1; _slot.qty=0.; _slot.entry_sig=np.nan; _slot.peak=np.nan; _slot.entry_day=-1; _slot.reviewed=False; _slot.pending_sell=False; _slot.sell_reason=''; _slot.virtual=False; _slot.virtual_cash=0.; _slot.ready_day=gday+COOLDOWN",
        "C1 virtual release",
    )

    # Admission classification is the same frozen <1% definition used by the
    # prior micro-tail experiment. No micro security order is allowed to reach
    # the real-buy branch.
    out = replace_once(
        out,
        "                        target=min(eq*ENTRY_W,book.cash); q=int(target//(float(px)*(1+COST)))\n                        if q<1: continue\n                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; resids.add(tid); resissuers.add(issuer_key(tid,ds)); ad+=1",
        "                        desired=eq*ENTRY_W; target=min(desired,book.cash); funding_fraction=(float(target)/float(desired) if desired>0 else 0.0); q=int(target//(float(px)*(1+COST)))\n                        if q<1: continue\n                        _is_virtual=bool(funding_fraction<0.01); virtual_decisions+=int(_is_virtual)\n                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; s.pending_virtual=_is_virtual; s.pending_intended_capital=float(desired); resids.add(tid); resissuers.add(issuer_key(tid,ds)); ad+=1",
        "micro decisions become virtual slots",
    )

    # User-facing real holdings exclude capacity slots; capacity state is explicit.
    out = replace_once(
        out,
        "                _position_ids=sorted(str(sid[int(s.tid)]) for s in book.slots if s.held())",
        "                _position_ids=sorted(str(sid[int(s.tid)]) for s in book.slots if s.held() and not s.virtual)\n                _capacity_ids=sorted(str(sid[int(s.tid)]) for s in book.slots if s.held() and s.virtual)",
        "real positions exclude virtual slots",
    )
    out = replace_once(
        out,
        "'held_count':int(len(held)),'research_eligible_universe'",
        "'held_count':int(len(held)),'real_held_count':int(sum(1 for s in book.slots if s.held() and not s.virtual)),'virtual_slot_count':int(sum(1 for s in book.slots if s.held() and s.virtual)),'virtual_cash_locked':float(sum(s.virtual_cash for s in book.slots if s.held() and s.virtual)),'research_capacity_slots':json.dumps(_capacity_ids,separators=(',',':')),'research_eligible_universe'",
        "virtual daily telemetry",
    )

    out = replace_once(
        out,
        "        'buys':buys,'sells':sells,'split_events_applied':split_events,'dividend_events_held':div_events,",
        "        'buys':buys,'sells':sells,'split_events_applied':split_events,'dividend_events_held':div_events,\n"
        f"        'wealth_core_virtual_slot_experiment':{{'variant':{variant!r},'micro_fraction':0.01,'virtual_decisions':virtual_decisions,'virtual_entries':virtual_entries,'virtual_releases':virtual_releases,'virtual_terminal_releases':virtual_terminal_releases,'virtual_stock_deliveries':virtual_stock_deliveries,'virtual_gap_promotions':virtual_gap_promotions,'real_micro_executions':real_micro_executions,'virtual_cash_locked_peak':virtual_cash_locked_peak}},",
        "virtual summary telemetry",
    )

    # Every release/cancellation path must clear pending/virtual state. Terminal
    # reservation cancellation needs only pending_virtual clear because no slot
    # was ever established.
    out = out.replace(
        "if s.reserved() and s.pending_tid in term_tids: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "if s.reserved() and s.pending_tid in term_tids: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_virtual=False; s.pending_intended_capital=0.",
    )
    out = out.replace(
        "if abs(q-round(q))>1e-8: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "if abs(q-round(q))>1e-8: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_virtual=False; s.pending_intended_capital=0.",
    )

    required = [
        "pending_virtual:bool=False", "pending_intended_capital:float=0.", "virtual:bool=False", "virtual_cash:float=0.",
        "wealth_core_virtual_slot_experiment", "research_capacity_slots", "if s.virtual:",
    ]
    missing = [x for x in required if x not in out]
    if missing:
        raise RuntimeError(f"virtual slot patch incomplete: {missing}")
    if out == v1:
        raise RuntimeError("virtual slot source unchanged")
    return out
