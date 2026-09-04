#!/usr/bin/env python3
"""Zero-budget mechanical-state diagnostic for Wealth Core around 2018.

This runs the untouched Strategy 9 chronological replay only to observe:
- whether deteriorating holdings had already completed the intentional one-time review;
- whether pending exits were delayed by non-tradeable opens;
- slot cooldown / reservation / ready geometry;
- whether the one-admission-per-session steady-state cap actually binds;
- the cooldown session-count convention in the research replay versus the
  canonical Wealth Core state machine.

No strategy decision is changed. No economic candidate is created. Experiment
budget remains 4/10.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

import pandas as pd

from backtester import calibrate_broad_simplified_breadth as strategy9

LABEL = "WEALTH_CORE_2018_MECHANICAL_STATE_DIAGNOSTIC"
BUDGET_COMPLETED = 4
EXPECTED_STRATEGY9_2018_NAV = 21.214765615495


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one seam, found {count}")
    return text.replace(old, new, 1)


def transformed_source(output: Path) -> str:
    text = strategy9.transformed_source(output)

    # Stop after the original recovery window. The diagnostic observes the
    # existing path only; later economics cannot answer the 2018 state question.
    text, count = re.subn(
        r"END\s*=\s*pd\.Timestamp\('2026-07-31'\)",
        "END = pd.Timestamp('2019-03-31')",
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError(f"diagnostic END seam: expected one match, got {count}")

    init_old = "rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0"
    init_new = """rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0
    # Observational state only. Nothing below is consumed by Wealth Core,
    # Native Sentinel, LD-RC, ranking, sizing, exits, admissions, or execution.
    mech_daily=[]
    mech_deterioration={}
    mech_review_events=[]
    mech_exit_events=[]
    mech_fill_events=[]
    mech_pending_exit={}
    mech_last_exit_by_slot={}"""
    text = replace_once(text, init_old, init_new, "diagnostic state")

    # Record ordinary executable exits before the existing state is cleared.
    sell_old = """                if finite(px) and px>0 and finite(volume[s.tid]) and volume[s.tid]>0:
                    book.cash+=s.qty*float(px)*(1-COST); sells+=1
                    if s.sell_reason=='stop': stop_days.append(gday)
                    book.sec_ready[s.tid]=gday+COOLDOWN"""
    sell_new = """                if finite(px) and px>0 and finite(volume[s.tid]) and volume[s.tid]>0:
                    mech_slot=int(book.slots.index(s)); mech_key=f'{s.tid}:{s.entry_day}'
                    mech_sig=mech_pending_exit.pop(mech_key,None)
                    mech_exit_events.append({'date':ds,'gday':int(gday),'slot':mech_slot,
                                             'ticker':str(tick[s.tid]),'tid':int(s.tid),
                                             'reason':str(s.sell_reason),
                                             'signal_date':(mech_sig.get('date') if mech_sig else None),
                                             'signal_to_fill_sessions':(int(gday-mech_sig['gday']) if mech_sig else None)})
                    mech_last_exit_by_slot[mech_slot]={'gday':int(gday),'date':ds,
                                                       'ticker':str(tick[s.tid]),'tid':int(s.tid),
                                                       'reason':str(s.sell_reason)}
                    book.cash+=s.qty*float(px)*(1-COST); sells+=1
                    if s.sell_reason=='stop': stop_days.append(gday)
                    book.sec_ready[s.tid]=gday+COOLDOWN"""
    text = replace_once(text, sell_old, sell_new, "ordinary exit diagnostic")

    # Record terminal slot releases too. They obey the same slot/security
    # cooldown and therefore belong in replacement-capacity geometry.
    term_old = """                elif s.sell_reason=='terminal':
                    px2=book.last_raw.get(s.tid,np.nan)
                    if finite(px2) and px2>0: book.cash+=s.qty*float(px2)*(1-COST)
                    book.sec_ready[s.tid]=gday+COOLDOWN"""
    term_new = """                elif s.sell_reason=='terminal':
                    px2=book.last_raw.get(s.tid,np.nan)
                    mech_slot=int(book.slots.index(s)); mech_key=f'{s.tid}:{s.entry_day}'
                    mech_sig=mech_pending_exit.pop(mech_key,None)
                    mech_exit_events.append({'date':ds,'gday':int(gday),'slot':mech_slot,
                                             'ticker':str(tick[s.tid]),'tid':int(s.tid),
                                             'reason':'terminal',
                                             'signal_date':(mech_sig.get('date') if mech_sig else None),
                                             'signal_to_fill_sessions':(int(gday-mech_sig['gday']) if mech_sig else None)})
                    mech_last_exit_by_slot[mech_slot]={'gday':int(gday),'date':ds,
                                                       'ticker':str(tick[s.tid]),'tid':int(s.tid),
                                                       'reason':'terminal'}
                    if finite(px2) and px2>0: book.cash+=s.qty*float(px2)*(1-COST)
                    book.sec_ready[s.tid]=gday+COOLDOWN"""
    text = replace_once(text, term_old, term_new, "terminal exit diagnostic")

    # Record fills and the elapsed session distance from the last exit of that
    # persistent slot. This observes actual replacement latency without changing
    # the existing one-admission policy.
    fill_old = """                    if q>=1:
                        book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(clsig[tid]) if finite(clsig[tid]) else np.nan; s.peak=np.nan; book.initialized=True; buys+=1
                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1"""
    fill_new = """                    if q>=1:
                        mech_slot=int(book.slots.index(s)); mech_prior=mech_last_exit_by_slot.pop(mech_slot,None)
                        mech_fill_events.append({'date':ds,'gday':int(gday),'slot':mech_slot,
                                                 'ticker':str(tick[tid]),'tid':int(tid),
                                                 'prior_exit_date':(mech_prior.get('date') if mech_prior else None),
                                                 'prior_exit_reason':(mech_prior.get('reason') if mech_prior else None),
                                                 'exit_to_fill_sessions':(int(gday-mech_prior['gday']) if mech_prior else None)})
                        book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(clsig[tid]) if finite(clsig[tid]) else np.nan; s.peak=np.nan; book.initialized=True; buys+=1
                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1"""
    text = replace_once(text, fill_old, fill_new, "fill diagnostic")

    # Observe first deterioration, the review state that already existed, review
    # events, and close-to-open exit waiting. The decision logic itself is copied
    # byte-for-byte after the observational statements.
    exit_old = """                age=gday-s.entry_day
                if finite(px) and finite(s.peak) and s.peak>0 and float(px)<=s.peak*STOP_RET:
                    s.pending_sell=True; s.sell_reason='stop'
                elif age>=REVIEW_AGE and not s.reviewed and finite(px):
                    qualifies=bool(inpool[s.tid] and finite(recent[s.tid]) and recent[s.tid]>=0)
                    underwater=finite(s.entry_sig) and float(px)<s.entry_sig
                    if underwater and not qualifies: s.pending_sell=True; s.sell_reason='review'
                    else: s.reviewed=True"""
    exit_new = """                age=gday-s.entry_day
                mech_key=f'{s.tid}:{s.entry_day}'
                mech_recent=float(recent[s.tid]) if finite(recent[s.tid]) else None
                mech_deteriorated=(not bool(inpool[s.tid])) and mech_recent is not None and mech_recent<0.0
                if pd.Timestamp('2018-01-01')<=date<=pd.Timestamp('2018-12-31') and mech_deteriorated and mech_key not in mech_deterioration:
                    mech_rank_idx=np.flatnonzero(rawall==s.tid); mech_rank=int(mech_rank_idx[0])+1 if len(mech_rank_idx) else None
                    mech_deterioration[mech_key]={'episode_key':mech_key,'ticker':str(tick[s.tid]),'tid':int(s.tid),
                                                  'first_deterioration_date':ds,'age':int(age),
                                                  'reviewed_before_deterioration':bool(s.reviewed),
                                                  'review_due_before_deterioration':bool(age>=REVIEW_AGE and not s.reviewed),
                                                  'momentum_rank':mech_rank,'pool_size':int(nk),
                                                  'recent_r21':mech_recent,
                                                  'entry_signal_price':(float(s.entry_sig) if finite(s.entry_sig) else None),
                                                  'close_signal_price':(float(px) if finite(px) else None),
                                                  'peak_signal_price':(float(s.peak) if finite(s.peak) else None)}
                if finite(px) and finite(s.peak) and s.peak>0 and float(px)<=s.peak*STOP_RET:
                    if not s.pending_sell: mech_pending_exit.setdefault(mech_key,{'gday':int(gday),'date':ds,'reason':'stop'})
                    s.pending_sell=True; s.sell_reason='stop'
                elif age>=REVIEW_AGE and not s.reviewed and finite(px):
                    qualifies=bool(inpool[s.tid] and finite(recent[s.tid]) and recent[s.tid]>=0)
                    underwater=finite(s.entry_sig) and float(px)<s.entry_sig
                    mech_review_events.append({'date':ds,'episode_key':mech_key,'ticker':str(tick[s.tid]),
                                               'tid':int(s.tid),'age':int(age),'qualified':bool(qualifies),
                                               'underwater':bool(underwater),
                                               'action':('exit' if underwater and not qualifies else 'pass')})
                    if underwater and not qualifies:
                        mech_pending_exit.setdefault(mech_key,{'gday':int(gday),'date':ds,'reason':'review'})
                        s.pending_sell=True; s.sell_reason='review'
                    else: s.reviewed=True"""
    text = replace_once(text, exit_old, exit_new, "review/deterioration diagnostic")

    # Replace only the admission block with an observational pre-count followed
    # by the exact original admission loop. The count asks whether the existing
    # one-admission limit was the active bottleneck on a given close.
    admission_old = """            if first_eligible is not None and gday>=first_eligible:
                ready=[s for s in book.slots if not s.held() and not s.reserved() and gday>=s.ready_day]
                if ready and not unresolved and book.cash>0:
                    budget=len(ready) if not book.initialized else 1
                    heldids=book.held_ids(); resids=book.reserved_ids()
                    heldissuers={issuer[s.tid] for s in book.slots if s.held()}; resissuers={issuer[s.pending_tid] for s in book.slots if s.reserved()}
                    ad=0
                    for tid0 in durable:
                        if ad>=budget or ad>=len(ready): break
                        tid=int(tid0)
                        if not finite(recent[tid]) or recent[tid]<0: continue
                        if tid in heldids or tid in resids or book.sec_ready.get(tid,-1)>gday or tid in term_tids: continue
                        if issuer[tid] in heldissuers or issuer[tid] in resissuers: continue
                        px=clraw[tid]
                        if not(finite(px) and px>0): continue
                        target=min(eq*ENTRY_W,book.cash); q=int(target//(float(px)*(1+COST)))
                        if q<1: continue
                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; resids.add(tid); resissuers.add(issuer[tid]); ad+=1
            shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)"""
    admission_new = """            mech_held_slots=sum(int(s.held()) for s in book.slots)
            mech_reserved_slots=sum(int(s.reserved()) for s in book.slots)
            mech_cooling_slots=sum(int((not s.held()) and (not s.reserved()) and gday<s.ready_day) for s in book.slots)
            mech_ready=[]; mech_admissible=0; mech_queued=0; mech_cap_binding=False
            if first_eligible is not None and gday>=first_eligible:
                mech_ready=[s for s in book.slots if not s.held() and not s.reserved() and gday>=s.ready_day]
                mech_heldids=book.held_ids(); mech_resids=book.reserved_ids()
                mech_heldissuers={issuer[s.tid] for s in book.slots if s.held()}; mech_resissuers={issuer[s.pending_tid] for s in book.slots if s.reserved()}
                for tid0 in durable:
                    tid=int(tid0)
                    if not finite(recent[tid]) or recent[tid]<0: continue
                    if tid in mech_heldids or tid in mech_resids or book.sec_ready.get(tid,-1)>gday or tid in term_tids: continue
                    if issuer[tid] in mech_heldissuers or issuer[tid] in mech_resissuers: continue
                    px=clraw[tid]
                    if not(finite(px) and px>0): continue
                    target=min(eq*ENTRY_W,book.cash); q=int(target//(float(px)*(1+COST)))
                    if q<1: continue
                    mech_admissible+=1
                mech_cap_binding=bool(book.initialized and not unresolved and book.cash>0 and len(mech_ready)>=2 and mech_admissible>=2)
                ready=mech_ready
                if ready and not unresolved and book.cash>0:
                    budget=len(ready) if not book.initialized else 1
                    heldids=book.held_ids(); resids=book.reserved_ids()
                    heldissuers={issuer[s.tid] for s in book.slots if s.held()}; resissuers={issuer[s.pending_tid] for s in book.slots if s.reserved()}
                    ad=0
                    for tid0 in durable:
                        if ad>=budget or ad>=len(ready): break
                        tid=int(tid0)
                        if not finite(recent[tid]) or recent[tid]<0: continue
                        if tid in heldids or tid in resids or book.sec_ready.get(tid,-1)>gday or tid in term_tids: continue
                        if issuer[tid] in heldissuers or issuer[tid] in resissuers: continue
                        px=clraw[tid]
                        if not(finite(px) and px>0): continue
                        target=min(eq*ENTRY_W,book.cash); q=int(target//(float(px)*(1+COST)))
                        if q<1: continue
                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; resids.add(tid); resissuers.add(issuer[tid]); ad+=1
                    mech_queued=int(ad)
            if pd.Timestamp('2018-01-01')<=date<=pd.Timestamp('2019-03-31'):
                mech_daily.append({'date':ds,'held_slots':int(mech_held_slots),'reserved_slots':int(mech_reserved_slots),
                                   'cooling_slots':int(mech_cooling_slots),'ready_slots':int(len(mech_ready)),
                                   'admissible_candidates':int(mech_admissible),'queued_admissions':int(mech_queued),
                                   'admission_cap_binding':bool(mech_cap_binding),'cash':float(book.cash),'equity':float(eq),
                                   'unresolved_equity':bool(unresolved)})
            shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)"""
    text = replace_once(text, admission_old, admission_new, "admission pressure diagnostic")

    output_old = """    out=pd.DataFrame(rows)
    out.to_csv(OUT/'daily.csv',index=False)"""
    output_new = """    pd.DataFrame(mech_daily).to_csv(OUT/'wc_mechanical_daily.csv',index=False)
    pd.DataFrame(mech_review_events).to_csv(OUT/'wc_review_events.csv',index=False)
    pd.DataFrame(mech_exit_events).to_csv(OUT/'wc_exit_events.csv',index=False)
    pd.DataFrame(mech_fill_events).to_csv(OUT/'wc_fill_events.csv',index=False)
    (OUT/'wc_deterioration_state.json').write_text(json.dumps({'records':list(mech_deterioration.values())},indent=2,sort_keys=True)+'\\n')
    out=pd.DataFrame(rows)
    out.to_csv(OUT/'daily.csv',index=False)"""
    text = replace_once(text, output_old, output_new, "diagnostic persistence")
    return text


def _canonical_cooldown_fill_offset() -> dict:
    """Execute the canonical state-machine cooldown clock in isolation.

    An exit occurs at the session open. The adapter later calls age_one_session
    at that same session close, then decide(), and any new reservation fills at
    the following open. This function calculates that exact boundary from the
    canonical state type rather than transcribing it into the diagnostic.
    """
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "shared"))
    from stock_strategy_shared.wealth_core.state import (  # type: ignore
        COOLDOWN_SESSIONS,
        PortfolioState,
    )

    state = PortfolioState.fresh(100.0, n_slots=1)
    slot = state.slots[0]
    slot.start_cooldown()  # exit at open, cooldown age 0
    state.security_cooldowns["S"] = 0
    decision_offset = None
    security_available_offset = None
    for close_offset in range(0, COOLDOWN_SESSIONS + 5):
        # Mirrors adapter step 5 after an exit at this run's offset-0 open.
        state.age_one_session({})
        if decision_offset is None and slot.ready:
            decision_offset = close_offset
        if security_available_offset is None and not state.security_in_cooldown("S"):
            security_available_offset = close_offset
        if decision_offset is not None and security_available_offset is not None:
            break
    if decision_offset is None or security_available_offset is None:
        raise RuntimeError("canonical cooldown did not expire")
    return {
        "cooldown_sessions": int(COOLDOWN_SESSIONS),
        "canonical_first_reservation_close_offset": int(decision_offset),
        "canonical_first_replacement_fill_open_offset": int(decision_offset + 1),
        "canonical_security_available_close_offset": int(security_available_offset),
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def finalize(output: Path) -> None:
    # Preserve the ordinary Strategy 9 output/summary first.
    strategy9.finalize(output)

    daily = pd.read_csv(output / "daily.csv.gz", compression="gzip", parse_dates=["date"])
    mech = pd.read_csv(output / "wc_mechanical_daily.csv", parse_dates=["date"])
    reviews = pd.read_csv(output / "wc_review_events.csv")
    exits = pd.read_csv(output / "wc_exit_events.csv")
    fills = pd.read_csv(output / "wc_fill_events.csv")
    deterioration = pd.DataFrame(json.loads((output / "wc_deterioration_state.json").read_text())["records"])

    y2018 = daily[daily.date.dt.year == 2018]
    if y2018.empty:
        raise RuntimeError("no 2018 Strategy 9 evidence")
    nav_2018 = float(y2018.iloc[-1].research_nav)
    if abs(nav_2018 - EXPECTED_STRATEGY9_2018_NAV) > 5e-9:
        raise RuntimeError(f"observational instrumentation moved Strategy 9: {nav_2018}")

    canonical = _canonical_cooldown_fill_offset()
    research_first_reservation_close_offset = 21
    research_first_replacement_fill_open_offset = research_first_reservation_close_offset + 1
    cooldown = {
        **canonical,
        "research_replay_ready_day_rule": "exit_gday + COOLDOWN; reservation requires gday >= ready_day",
        "research_first_reservation_close_offset": research_first_reservation_close_offset,
        "research_first_replacement_fill_open_offset": research_first_replacement_fill_open_offset,
        "research_extra_replacement_session_vs_canonical": int(
            research_first_replacement_fill_open_offset
            - canonical["canonical_first_replacement_fill_open_offset"]),
    }

    m18 = mech[mech.date.dt.year == 2018]
    if m18.empty:
        raise RuntimeError("no 2018 mechanical telemetry")
    cap_days = m18[m18.admission_cap_binding.astype(bool)]

    if deterioration.empty:
        deterioration_stats = {
            "episodes": 0,
            "reviewed_before": 0,
            "review_due_before": 0,
            "reviewed_before_fraction": 0.0,
        }
    else:
        deterioration_stats = {
            "episodes": int(len(deterioration)),
            "reviewed_before": int(deterioration.reviewed_before_deterioration.astype(bool).sum()),
            "review_due_before": int(deterioration.review_due_before_deterioration.astype(bool).sum()),
            "reviewed_before_fraction": float(deterioration.reviewed_before_deterioration.astype(bool).mean()),
            "median_age_at_first_deterioration": float(deterioration.age.astype(float).median()),
        }

    review18 = reviews[pd.to_datetime(reviews.date).dt.year == 2018] if not reviews.empty else reviews
    exit18 = exits[pd.to_datetime(exits.date).dt.year == 2018] if not exits.empty else exits
    fill18 = fills[pd.to_datetime(fills.date).dt.year == 2018] if not fills.empty else fills
    delayed_exit = exit18[pd.to_numeric(exit18.signal_to_fill_sessions, errors="coerce") > 1] if not exit18.empty else exit18
    replacement = pd.to_numeric(fill18.exit_to_fill_sessions, errors="coerce").dropna() if not fill18.empty else pd.Series(dtype=float)

    summary = {
        "status": "PASS",
        "evidence_label": LABEL,
        "kind": "observational_zero_budget_mechanical_diagnostic",
        "economic_experiments_consumed": 0,
        "experiment_budget_completed": BUDGET_COMPLETED,
        "strategy_decisions_changed": False,
        "strategy9_2018_year_end_nav": nav_2018,
        "cooldown_convention": cooldown,
        "deterioration_review_state_2018": deterioration_stats,
        "review_events_2018": {
            "count": int(len(review18)),
            "pass": int((review18.action.astype(str) == "pass").sum()) if not review18.empty else 0,
            "exit": int((review18.action.astype(str) == "exit").sum()) if not review18.empty else 0,
        },
        "exit_execution_2018": {
            "executed_exits": int(len(exit18)),
            "exits_waiting_more_than_next_open": int(len(delayed_exit)),
            "max_signal_to_fill_sessions": (
                int(pd.to_numeric(exit18.signal_to_fill_sessions, errors="coerce").max())
                if not exit18.empty and pd.to_numeric(exit18.signal_to_fill_sessions, errors="coerce").notna().any()
                else None),
        },
        "admission_pressure_2018": {
            "sessions": int(len(m18)),
            "cap_binding_sessions": int(len(cap_days)),
            "cap_binding_fraction": float(len(cap_days) / len(m18)),
            "max_ready_slots": int(m18.ready_slots.max()),
            "max_admissible_candidates": int(m18.admissible_candidates.max()),
            "mean_held_slots": float(m18.held_slots.mean()),
            "mean_cooling_slots": float(m18.cooling_slots.mean()),
            "mean_ready_slots": float(m18.ready_slots.mean()),
            "total_queued_admissions": int(m18.queued_admissions.sum()),
        },
        "replacement_latency_2018": {
            "fills_with_prior_slot_exit": int(len(replacement)),
            "median_exit_to_fill_sessions": float(replacement.median()) if len(replacement) else None,
            "mean_exit_to_fill_sessions": float(replacement.mean()) if len(replacement) else None,
            "min_exit_to_fill_sessions": int(replacement.min()) if len(replacement) else None,
            "max_exit_to_fill_sessions": int(replacement.max()) if len(replacement) else None,
        },
    }
    (output / "wc_mechanical_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files = [
        output / "daily.csv.gz",
        output / "wc_mechanical_daily.csv",
        output / "wc_review_events.csv",
        output / "wc_exit_events.csv",
        output / "wc_fill_events.csv",
        output / "wc_deterioration_state.json",
        output / "wc_mechanical_summary.json",
    ]
    (output / "MECHANICAL_SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(p)}  {p.name}\n" for p in files), encoding="utf-8")

    print("[MECHANICAL DIAGNOSTIC]", flush=True)
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    generated = Path("/tmp/wc_2018_mechanical_state_generated.py")
    generated.write_text(transformed_source(args.output), encoding="utf-8")
    env = dict(os.environ)
    env["RESEARCH_REPLAY_MODE"] = "fullpit"
    print(f"[RUN] {LABEL} budget={BUDGET_COMPLETED}/10 diagnostic_consumes=0", flush=True)
    subprocess.run([sys.executable, str(generated)], check=True, env=env)
    finalize(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
