#!/usr/bin/env python3
"""Strategy 9 E7: one temporary margin-funded overflow slot.

Single Wealth Core change, activated only from 2020-01-02 for the bounded A/B:
when the 25 ordinary slots are fully occupied, no exit/admission is already pending,
and the current durable rank #1 security is otherwise admissible, reserve one
26th overflow slot at the normal 4% target. The next-open purchase uses available
cash first and borrows only the shortfall. No second overflow may stack.

The margin debit is a liability in Wealth Core equity. It accrues at 6.25% APR
using Alpaca's documented /360 overnight convention and actual calendar-day gaps.
All cash receipts reduce the debit before new purchases. When a natural exit frees
an ordinary slot and the debit has been repaid, the overflow holding is promoted
into the ordinary book without changing its entry/stop/review state.

No Sentinel/E3 parameters or mechanics are changed. Research experiment; consumes
Strategy 9 experiment budget slot 7/10.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from backtester import experiment_architecture_recovery_concordance_e3 as e3

LABEL = "STRATEGY9_E7_MARGIN_OVERFLOW"
VARIANT = "E7_MARGIN_OVERFLOW"
BUDGET_NUMBER = 7
E3_SOURCE_HEAD = "3f27834db427e71d9bb8d0b6160c8835b739c906"
ACTIVATION = pd.Timestamp("2020-01-02")
MARGIN_APR = 0.0625
MARGIN_DAY_BASIS = 360.0
ACCEPTED_E3_RUN_ID = 33912976460
ACCEPTED_E3_ARTIFACT_ID = 9953264982
ACCEPTED_E3_DIGEST = "sha256:22011d018a336c6da4d92b31e8786811a4f4288daa91d56a80c30c9f144f174f"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one seam, found {count}")
    return text.replace(old, new, 1)


def transformed_source(output: Path) -> str:
    text = e3.transformed_source(output)

    text = replace_once(
        text,
        "N_SLOTS = 25\nENTRY_W = 0.04",
        "N_SLOTS = 25\nENTRY_W = 0.04\nE7_MARGIN_APR = 0.0625\nE7_MARGIN_DAY_BASIS = 360.0\nE7_ACTIVATION = pd.Timestamp('2020-01-02')",
        "E7 constants",
    )

    book_old = """    cash:float=100_000_000.; receivables:list=field(default_factory=list)\n    slots:list=field(default_factory=lambda:[Slot() for _ in range(N_SLOTS)])\n    sec_ready:dict=field(default_factory=dict); initialized:bool=False; last_raw:dict=field(default_factory=dict)"""
    book_new = """    cash:float=100_000_000.; receivables:list=field(default_factory=list)\n    slots:list=field(default_factory=lambda:[Slot() for _ in range(N_SLOTS+1)])\n    sec_ready:dict=field(default_factory=dict); initialized:bool=False; last_raw:dict=field(default_factory=dict)\n    margin_debt:float=0.; margin_interest_total:float=0.; margin_repaid_total:float=0."""
    text = replace_once(text, book_old, book_new, "E7 book margin state")
    text = replace_once(
        text,
        "        v=self.cash+sum(x[1] for x in self.receivables)",
        "        v=self.cash+sum(x[1] for x in self.receivables)-self.margin_debt",
        "E7 margin liability in equity",
    )

    state_old = "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0"
    state_new = state_old + "\n    e7_margin_signals=[]; e7_margin_execs=[]; e7_promotions=0; e7_prev_margin_date=None; e7_max_debt_fraction=0.; e7_max_gross=0."
    text = replace_once(text, state_old, state_new, "E7 telemetry state")

    session_old = "            gday+=1; date=pd.Timestamp(date); ds=date.strftime('%Y-%m-%d')"
    session_new = session_old + r'''
            # Accrue financing carried from the prior session close. Calendar-day
            # gaps reproduce Alpaca's overnight /360 convention (Fri->Mon = 3 days).
            if e7_prev_margin_date is not None and book.margin_debt>0:
                _e7_days=(date-e7_prev_margin_date).days
                if _e7_days<=0: raise RuntimeError(f'E7 non-positive margin accrual gap {e7_prev_margin_date} -> {date}')
                _e7_interest=book.margin_debt*E7_MARGIN_APR*float(_e7_days)/E7_MARGIN_DAY_BASIS
                book.margin_debt+=_e7_interest; book.margin_interest_total+=_e7_interest
            e7_prev_margin_date=date'''
    text = replace_once(text, session_old, session_new, "E7 financing accrual")

    settle_old = "            due=sum(a for dd,a in book.receivables if dd<=gday); book.cash+=due; book.receivables=[x for x in book.receivables if x[0]>gday]"
    settle_new = settle_old + r'''
            if book.margin_debt>0 and book.cash>0:
                _e7_repay=min(book.cash,book.margin_debt); book.cash-=_e7_repay; book.margin_debt-=_e7_repay; book.margin_repaid_total+=_e7_repay'''
    text = replace_once(text, settle_old, settle_new, "E7 cash-first debt repayment")

    buy_old = """            for s in book.slots:\n                if not(s.reserved() and not s.held()): continue\n                tid=s.pending_tid; px=opraw[tid]\n                if finite(px) and px>0 and finite(volume[tid]) and volume[tid]>0:\n                    afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford)\n                    if q>=1:\n                        book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1\n                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1"""
    buy_new = r'''            # Any sale proceeds or settled cash extinguish margin before a new buy.
            if book.margin_debt>0 and book.cash>0:
                _e7_repay=min(book.cash,book.margin_debt); book.cash-=_e7_repay; book.margin_debt-=_e7_repay; book.margin_repaid_total+=_e7_repay
            # Once a natural ordinary-slot exit has supplied enough cash to repay
            # the debit, promote the overflow holding into the ordinary 25-slot book.
            _e7_overflow=book.slots[N_SLOTS]
            if _e7_overflow.held() and book.margin_debt<=1e-8:
                _e7_empty=[_s for _s in book.slots[:N_SLOTS] if not _s.held() and not _s.reserved()]
                if _e7_empty:
                    _e7_dst=_e7_empty[0]
                    for _e7_attr in ('tid','qty','entry_sig','peak','entry_day','reviewed','pending_sell','sell_reason','pending_tid','pending_shares','pending_signal_day','ready_day'):
                        setattr(_e7_dst,_e7_attr,getattr(_e7_overflow,_e7_attr))
                    book.slots[N_SLOTS]=Slot(); e7_promotions+=1
            for s in book.slots:
                if not(s.reserved() and not s.held()): continue
                tid=s.pending_tid; px=opraw[tid]
                if finite(px) and px>0 and finite(volume[tid]) and volume[tid]>0:
                    if s is book.slots[N_SLOTS]:
                        q=int(round(s.pending_shares))
                        if q>=1:
                            _e7_cost=q*float(px)*(1+COST); _e7_cash_used=min(book.cash,_e7_cost); _e7_borrow=_e7_cost-_e7_cash_used
                            book.cash-=_e7_cash_used; book.margin_debt+=_e7_borrow
                            s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1
                            e7_margin_execs.append({'execution_date':ds,'ticker':str(tick[tid]),'security_id':str(sid[tid]),'shares':int(q),'raw_open':float(px),'purchase_cost':float(_e7_cost),'cash_used':float(_e7_cash_used),'margin_borrowed':float(_e7_borrow),'margin_debt_after':float(book.margin_debt)})
                    else:
                        afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford)
                        if q>=1:
                            book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1
                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1'''
    text = replace_once(text, buy_old, buy_new, "E7 margin-aware execution")

    admission_marker = "                ready=[s for s in book.slots if not s.held() and not s.reserved() and gday>=s.ready_day]"
    e7_block = r'''                # E7: one margin-funded overflow slot. The candidate gate is
                # deliberately the same narrow durable-rank-#1 gate studied in E6;
                # only the funding mechanism changes (no incumbent is forcibly sold).
                _e7_overflow=book.slots[N_SLOTS]
                if (date>=E7_ACTIVATION
                    and sum(int(_s.held()) for _s in book.slots[:N_SLOTS])==N_SLOTS
                    and not _e7_overflow.held() and not _e7_overflow.reserved()
                    and gday>=_e7_overflow.ready_day
                    and book.margin_debt<=1e-8
                    and not any(_s.pending_sell or _s.reserved() for _s in book.slots)
                    and not unresolved and len(durable)>0):
                    _e7_tid=int(durable[0]); _e7_tk=str(tick[_e7_tid])
                    _e7_held=book.held_ids(); _e7_res=book.reserved_ids()
                    _e7_heldissuers={issuer_key(_s.tid,ds) for _s in book.slots if _s.held()}
                    _e7_resissuers={issuer_key(_s.pending_tid,ds) for _s in book.slots if _s.reserved()}
                    _e7_admissible=(
                        finite(recent[_e7_tid]) and recent[_e7_tid]>=0
                        and _e7_tid not in _e7_held and _e7_tid not in _e7_res
                        and book.sec_ready.get(_e7_tid,-1)<=gday
                        and _e7_tid not in term_tids
                        and issuer_key(_e7_tid,ds) not in _e7_heldissuers
                        and issuer_key(_e7_tid,ds) not in _e7_resissuers
                        and finite(clraw[_e7_tid]) and clraw[_e7_tid]>0
                    )
                    if _e7_admissible:
                        _e7_target=float(eq)*ENTRY_W; _e7_px=float(clraw[_e7_tid]); _e7_q=int(_e7_target//(_e7_px*(1+COST)))
                        if _e7_q>=1:
                            _e7_overflow.pending_tid=_e7_tid; _e7_overflow.pending_shares=float(_e7_q); _e7_overflow.pending_signal_day=gday
                            e7_margin_signals.append({'signal_date':ds,'candidate_ticker':_e7_tk,'candidate_security_id':str(sid[_e7_tid]),'candidate_durable_rank':1,'candidate_score':float(score[_e7_tid]),'candidate_recent_r21':float(recent[_e7_tid]),'close_equity':float(eq),'target_notional':float(_e7_target),'planned_shares':int(_e7_q)})
                ready=[s for s in book.slots[:N_SLOTS] if not s.held() and not s.reserved() and gday>=s.ready_day]'''
    text = replace_once(text, admission_marker, e7_block, "E7 overflow admission")

    telemetry_old = "'eligible_count':int(len(et)),'leadership_population':int(nk),'held_count':int(len(held))})"
    telemetry_new = "'eligible_count':int(len(et)),'leadership_population':int(nk),'held_count':int(len(held)),'margin_debt':float(book.margin_debt),'margin_interest_total':float(book.margin_interest_total),'overflow_active':bool(book.slots[N_SLOTS].held() or book.slots[N_SLOTS].reserved()),'gross_exposure':(float(sum(_s.qty*float(clraw[_s.tid]) for _s in book.slots if _s.held() and finite(clraw[_s.tid]) and clraw[_s.tid]>0)/eq) if eq>0 else np.nan)})"
    text = replace_once(text, telemetry_old, telemetry_new, "E7 daily margin telemetry")

    output_marker = "    out=pd.DataFrame(rows)"
    output_new = r'''    pd.DataFrame(e7_margin_signals).to_csv(OUT/'e7_margin_signals.csv',index=False)
    pd.DataFrame(e7_margin_execs).to_csv(OUT/'e7_margin_executions.csv',index=False)
    out=pd.DataFrame(rows)'''
    text = replace_once(text, output_marker, output_new, "E7 telemetry output")

    return text


def hash_pre_activation(frame: pd.DataFrame) -> str:
    cols = ["date", "research_wealth_core_equity", "research_nav", "A_nav"]
    missing = [c for c in cols if c not in frame.columns]
    if missing:
        raise RuntimeError(f"pre-activation parity columns missing: {missing}")
    x = frame[pd.to_datetime(frame.date) < ACTIVATION][cols].copy()
    h = hashlib.sha256()
    for row in x.itertuples(index=False, name=None):
        payload = [pd.Timestamp(row[0]).strftime("%Y-%m-%d")]
        payload.extend(None if pd.isna(v) else format(float(v), ".12g") for v in row[1:])
        h.update((json.dumps(payload, separators=(",", ":")) + "\n").encode())
    return h.hexdigest()


def metric(frame: pd.DataFrame, column: str) -> dict:
    return e3.corrected.old.metric_block(frame, column, str(ACTIVATION.date()), None)


def finalize(output: Path) -> None:
    # Preserve accepted Strategy 9 post-processing, but do not invoke E3's control
    # parity assertion because Wealth Core intentionally changes after activation.
    e3.strategy9.finalize(output)

    accepted_root = Path(os.environ["ACCEPTED_E3_ROOT"])
    accepted = pd.read_csv(accepted_root / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    candidate = pd.read_csv(output / "daily.csv.gz", compression="gzip", parse_dates=["date"])

    ah = hash_pre_activation(accepted)
    ch = hash_pre_activation(candidate)
    if ah != ch:
        raise RuntimeError(f"E7 pre-activation parity failure accepted={ah} candidate={ch}")

    signals = pd.read_csv(output / "e7_margin_signals.csv")
    execs = pd.read_csv(output / "e7_margin_executions.csv")
    if signals.empty or execs.empty:
        raise RuntimeError("E7 produced zero margin-overflow events")

    rows = []
    for label, frame, col in (
        ("ACCEPTED_E3", accepted, "A_nav"),
        ("ACCEPTED_CORE", accepted, "research_wealth_core_equity"),
        ("E7_E3", candidate, "A_nav"),
        ("E7_CORE", candidate, "research_wealth_core_equity"),
        ("SPY", candidate, "spy_nav"),
    ):
        rows.append({"variant": label, **metric(frame, col)})
    metrics = pd.DataFrame(rows)
    metrics.to_csv(output / "e7_2020_2026_metrics.csv", index=False)

    annual = []
    for year in range(2020, 2027):
        for label, frame, col in (
            ("ACCEPTED_E3", accepted, "A_nav"),
            ("ACCEPTED_CORE", accepted, "research_wealth_core_equity"),
            ("E7_E3", candidate, "A_nav"),
            ("E7_CORE", candidate, "research_wealth_core_equity"),
        ):
            y = frame[pd.to_datetime(frame.date).dt.year.eq(year)][["date", col]].dropna()
            if len(y) < 2:
                continue
            annual.append({"year": year, "variant": label, "return": float(y.iloc[-1][col] / y.iloc[0][col] - 1.0)})
    pd.DataFrame(annual).to_csv(output / "e7_annual_returns.csv", index=False)

    active = candidate[pd.to_datetime(candidate.date) >= ACTIVATION].copy()
    margin_days = active[active.margin_debt.astype(float) > 1e-8]
    summary = json.loads((output / "summary.json").read_text())
    summary.update({
        "experiment": "strategy9_e7_margin_overflow",
        "evidence_label": LABEL,
        "experiment_budget_number": BUDGET_NUMBER,
        "experiment_budget_consumed_after_completion": 7,
        "experiment_budget_limit": 10,
        "activation_date": str(ACTIVATION.date()),
        "pre_activation_parity": {"status": "PASS", "accepted_sha256": ah, "candidate_sha256": ch},
        "margin_rule": {
            "wealth_core_changed": True,
            "native_sentinel_changed": False,
            "e3_overlay_code_changed": False,
            "candidate": "current durable rank #1, ordinary admission gates satisfied, recent_r21 >= 0",
            "portfolio_condition": "all 25 ordinary slots held; no pending exit/reservation; no existing overflow or margin debit",
            "overflow_capacity": "one temporary 26th holding; no stacking",
            "position_target": "normal 4% close-equity target; next-open fill",
            "funding": "available cash first, margin debit for shortfall",
            "margin_apr": MARGIN_APR,
            "day_basis": MARGIN_DAY_BASIS,
            "accrual": "overnight debit with actual calendar-day gaps",
            "repayment": "all available cash receipts reduce debit before purchases; natural ordinary-slot exit permits overflow promotion after debit reaches zero",
        },
        "margin_signals": int(len(signals)),
        "margin_executions": int(len(execs)),
        "margin_sessions": int(len(margin_days)),
        "max_margin_debt_fraction_of_equity": float((active.margin_debt.astype(float) / active.research_wealth_core_equity.astype(float)).max()),
        "max_gross_exposure": float(active.gross_exposure.astype(float).max()),
        "total_margin_interest": float(active.margin_interest_total.astype(float).max()),
        "accepted_e3_run_id": ACCEPTED_E3_RUN_ID,
        "accepted_e3_artifact_id": ACCEPTED_E3_ARTIFACT_ID,
        "accepted_e3_digest": ACCEPTED_E3_DIGEST,
    })
    (output / "e7_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    manifest = {
        "schema": "backtester.strategy9-e7-margin-overflow/1",
        "status": "PASS",
        "evidence_label": LABEL,
        "strategy_source_head": E3_SOURCE_HEAD,
        "experiment_budget_number": BUDGET_NUMBER,
        "activation_date": str(ACTIVATION.date()),
        "pre_activation_parity": True,
        "fresh_chronological_replay": True,
        "decision_at_close_next_open_effect": True,
        "native_sentinel_changed": False,
        "e3_overlay_code_changed": False,
        "margin_apr": MARGIN_APR,
        "margin_day_basis": MARGIN_DAY_BASIS,
        "max_concurrent_overflow_positions": 1,
    }
    (output / "e7_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    files = [
        output / "daily.csv.gz",
        output / "e7_margin_signals.csv",
        output / "e7_margin_executions.csv",
        output / "e7_2020_2026_metrics.csv",
        output / "e7_annual_returns.csv",
        output / "e7_summary.json",
        output / "e7_manifest.json",
    ]
    (output / "E7_SHA256SUMS.txt").write_text(
        "".join(f"{e3.corrected.old.sha256(p)}  {p.name}\n" for p in files)
    )
    print("[E7 METRICS]", flush=True)
    print(metrics.to_string(index=False), flush=True)
    print(f"[E7 MARGIN] signals={len(signals)} executions={len(execs)} margin_sessions={len(margin_days)} max_debt_frac={summary['max_margin_debt_fraction_of_equity']:.6%} max_gross={summary['max_gross_exposure']:.6f} interest={summary['total_margin_interest']:.2f}", flush=True)
    print(execs.head(50).to_string(index=False), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    generated = Path("/tmp/strategy9_e7_margin_overflow.py")
    generated.write_text(transformed_source(args.output), encoding="utf-8")
    env = dict(os.environ)
    env["RESEARCH_REPLAY_MODE"] = "fullpit"
    print(f"[RUN] {LABEL} experiment={BUDGET_NUMBER}/10 activation={ACTIVATION.date()} margin_apr={MARGIN_APR:.4%}", flush=True)
    subprocess.run([sys.executable, str(generated)], check=True, env=env)
    finalize(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
