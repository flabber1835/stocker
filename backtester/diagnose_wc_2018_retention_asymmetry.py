#!/usr/bin/env python3
"""Zero-budget structural diagnostic for Wealth Core 2018 retention asymmetry.

This performs a fresh chronological Strategy 9 replay only to observe the existing
Wealth Core state. It does not change any strategy decision or economic output and
therefore does not consume an experiment from the owner-authorized 10-run budget.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pandas as pd

from backtester import calibrate_broad_simplified_breadth as strategy9

LABEL = "WEALTH_CORE_2018_RETENTION_ASYMMETRY_DIAGNOSTIC"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one seam, found {count}")
    return text.replace(old, new, 1)


def transformed_source(output: Path) -> str:
    text = strategy9.transformed_source(output)

    # Stop after the recovery window; no post-2019 economics are needed for this
    # purely observational diagnostic.
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
    # Diagnostic state only. These structures never feed any strategy decision.
    diag_records={}
    diag_last_episode_by_tid={}
    diag_prev_value={}
    diag_holding_rows=[]
    diag_equity_rows=[]
    diag_all_pnl_2018=0.0
    diag_all_negative_pnl_2018=0.0
    diag_post_pnl_2018=0.0
    diag_post_negative_pnl_2018=0.0"""
    text = replace_once(text, init_old, init_new, "diagnostic state")

    # Instrument ordinary next-open exits before the slot is cleared.
    sell_old = """                if finite(px) and px>0 and finite(volume[s.tid]) and volume[s.tid]>0:
                    book.cash+=s.qty*float(px)*(1-COST); sells+=1"""
    sell_new = """                if finite(px) and px>0 and finite(volume[s.tid]) and volume[s.tid]>0:
                    diag_key=f'{s.tid}:{s.entry_day}'
                    diag_exit_value=s.qty*float(px)*(1-COST)
                    if diag_key in diag_prev_value:
                        diag_delta=diag_exit_value-diag_prev_value[diag_key]
                        if date.year==2018:
                            diag_all_pnl_2018+=diag_delta
                            if diag_delta<0: diag_all_negative_pnl_2018+=diag_delta
                            diag_rec=diag_records.get(diag_key)
                            if diag_rec is not None and diag_rec.get('active',False):
                                diag_post_pnl_2018+=diag_delta
                                if diag_delta<0: diag_post_negative_pnl_2018+=diag_delta
                    diag_rec=diag_records.get(diag_key)
                    if diag_rec is not None and diag_rec.get('active',False):
                        diag_rec['active']=False; diag_rec['exit_date']=ds; diag_rec['exit_reason']=s.sell_reason
                        diag_rec['exit_value']=float(diag_exit_value)
                    diag_prev_value.pop(diag_key,None)
                    book.cash+=diag_exit_value; sells+=1"""
    text = replace_once(text, sell_old, sell_new, "ordinary exit diagnostic")

    # Instrument terminal exits as well.
    term_old = """                elif s.sell_reason=='terminal':
                    px2=book.last_raw.get(s.tid,np.nan)
                    if finite(px2) and px2>0: book.cash+=s.qty*float(px2)*(1-COST)"""
    term_new = """                elif s.sell_reason=='terminal':
                    px2=book.last_raw.get(s.tid,np.nan)
                    diag_key=f'{s.tid}:{s.entry_day}'
                    diag_exit_value=s.qty*float(px2)*(1-COST) if finite(px2) and px2>0 else 0.0
                    if diag_key in diag_prev_value:
                        diag_delta=diag_exit_value-diag_prev_value[diag_key]
                        if date.year==2018:
                            diag_all_pnl_2018+=diag_delta
                            if diag_delta<0: diag_all_negative_pnl_2018+=diag_delta
                            diag_rec=diag_records.get(diag_key)
                            if diag_rec is not None and diag_rec.get('active',False):
                                diag_post_pnl_2018+=diag_delta
                                if diag_delta<0: diag_post_negative_pnl_2018+=diag_delta
                    diag_rec=diag_records.get(diag_key)
                    if diag_rec is not None and diag_rec.get('active',False):
                        diag_rec['active']=False; diag_rec['exit_date']=ds; diag_rec['exit_reason']='terminal'; diag_rec['exit_value']=float(diag_exit_value)
                    diag_prev_value.pop(diag_key,None)
                    if finite(px2) and px2>0: book.cash+=diag_exit_value"""
    text = replace_once(text, term_old, term_new, "terminal exit diagnostic")

    # Dividends belong to the holding episode that owned the prior close.
    div_old = """                    rawdiv=sum(vals)*float(clraw[tid])/float(clsig[tid]); book.receivables.append((gday+1,q*rawdiv)); div_events+=1"""
    div_new = """                    rawdiv=sum(vals)*float(clraw[tid])/float(clsig[tid]); diag_div=float(q*rawdiv); book.receivables.append((gday+1,diag_div)); div_events+=1
                    if date.year==2018:
                        diag_all_pnl_2018+=diag_div
                        diag_key=diag_last_episode_by_tid.get(tid)
                        diag_rec=diag_records.get(diag_key) if diag_key is not None else None
                        if diag_rec is not None:
                            diag_post_pnl_2018+=diag_div
                            diag_rec['dividends_after_deterioration']=float(diag_rec.get('dividends_after_deterioration',0.0)+diag_div)"""
    text = replace_once(text, div_old, div_new, "dividend diagnostic")

    # Observe every held episode at the close before the existing stop/review logic.
    close_old = """                age=gday-s.entry_day
                if finite(px) and finite(s.peak) and s.peak>0 and float(px)<=s.peak*STOP_RET:"""
    close_new = """                age=gday-s.entry_day
                diag_tid=int(s.tid); diag_key=f'{diag_tid}:{s.entry_day}'; diag_last_episode_by_tid[diag_tid]=diag_key
                diag_mark=float(s.qty)*float(clraw[diag_tid]) if finite(clraw[diag_tid]) and clraw[diag_tid]>0 else None
                diag_rec=diag_records.get(diag_key)
                if diag_mark is not None:
                    if diag_key in diag_prev_value:
                        diag_delta=diag_mark-diag_prev_value[diag_key]
                        if date.year==2018:
                            diag_all_pnl_2018+=diag_delta
                            if diag_delta<0: diag_all_negative_pnl_2018+=diag_delta
                            if diag_rec is not None and diag_rec.get('active',False):
                                diag_post_pnl_2018+=diag_delta
                                if diag_delta<0: diag_post_negative_pnl_2018+=diag_delta
                        if diag_rec is not None and diag_rec.get('active',False):
                            diag_rec['sessions_retained_after']=int(diag_rec.get('sessions_retained_after',0)+1)
                    diag_prev_value[diag_key]=diag_mark
                diag_recent=float(recent[diag_tid]) if finite(recent[diag_tid]) else None
                diag_deteriorated=(not bool(inpool[diag_tid])) and diag_recent is not None and diag_recent<0.0
                if diag_deteriorated and diag_rec is None:
                    diag_rank_idx=np.flatnonzero(rawall==diag_tid)
                    diag_rank=int(diag_rank_idx[0])+1 if len(diag_rank_idx) else None
                    diag_rec={'episode_key':diag_key,'tid':diag_tid,'ticker':str(tick[diag_tid]),'entry_day':int(s.entry_day),
                              'first_deterioration_date':ds,'first_deterioration_age':int(age),'first_value':diag_mark,
                              'first_momentum_rank':diag_rank,'first_pool_size':int(nk),'first_recent_r21':diag_recent,
                              'sessions_retained_after':0,'dividends_after_deterioration':0.0,'active':True,
                              'exit_date':None,'exit_reason':None,'exit_value':None}
                    diag_records[diag_key]=diag_rec
                if finite(px) and finite(s.peak) and s.peak>0 and float(px)<=s.peak*STOP_RET:"""
    text = replace_once(text, close_old, close_new, "close deterioration diagnostic")

    # Position-level daily ledger after close equity is known.
    held_old = """                age=gday-s.entry_day
                green=finite(own) and own>-.075 and finite(r21v) and r21v>0 and (age<63 or (finite(r63v) and r63v>0))"""
    held_new = """                age=gday-s.entry_day
                if pd.Timestamp('2018-06-01')<=date<=pd.Timestamp('2019-03-31'):
                    diag_key=f'{tid}:{s.entry_day}'; diag_rank_idx=np.flatnonzero(rawall==tid); diag_rank=int(diag_rank_idx[0])+1 if len(diag_rank_idx) else None
                    diag_rec=diag_records.get(diag_key); diag_mark=float(s.qty)*float(clraw[tid]) if finite(clraw[tid]) and clraw[tid]>0 else None
                    diag_holding_rows.append({'date':ds,'episode_key':diag_key,'ticker':str(tick[tid]),'tid':int(tid),'age':int(age),
                                              'quantity':float(s.qty),'mark_value':diag_mark,'weight':(diag_mark/eq if diag_mark is not None and finite(eq) and eq>0 else None),
                                              'momentum':(float(mom[tid]) if finite(mom[tid]) else None),'momentum_rank':diag_rank,'pool_size':int(nk),
                                              'in_top_decile_pool':bool(inpool[tid]),'recent_r21':r21v,
                                              'deteriorated_now':bool((not bool(inpool[tid])) and r21v is not None and r21v<0.0),
                                              'post_deterioration_active':bool(diag_rec is not None and diag_rec.get('active',False)),
                                              'pending_sell':bool(s.pending_sell),'pending_sell_reason':str(s.sell_reason)})
                green=finite(own) and own>-.075 and finite(r21v) and r21v>0 and (age<63 or (finite(r63v) and r63v>0))"""
    text = replace_once(text, held_old, held_new, "daily holding ledger")

    eq_old = """            shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)"""
    eq_new = """            if pd.Timestamp('2018-01-01')<=date<=pd.Timestamp('2019-03-31'):
                diag_equity_rows.append({'date':ds,'wealth_core_equity':float(eq)})
            shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)"""
    text = replace_once(text, eq_old, eq_new, "diagnostic equity ledger")

    # Persist diagnostics before the existing replay outputs are finalized.
    output_old = """    out=pd.DataFrame(rows)
    out.to_csv(OUT/'daily.csv',index=False)"""
    output_new = """    pd.DataFrame(diag_holding_rows).to_csv(OUT/'wc_2018_holding_daily.csv',index=False)
    pd.DataFrame(diag_equity_rows).to_csv(OUT/'wc_2018_equity.csv',index=False)
    diag_payload={'label':'WEALTH_CORE_2018_RETENTION_ASYMMETRY_DIAGNOSTIC','economic_experiments_consumed':0,
                  'budget_completed_before_and_after':3,'records':list(diag_records.values()),
                  'aggregate':{'all_holding_pnl_2018':float(diag_all_pnl_2018),
                               'all_negative_holding_pnl_2018':float(diag_all_negative_pnl_2018),
                               'post_deterioration_pnl_2018':float(diag_post_pnl_2018),
                               'post_deterioration_negative_pnl_2018':float(diag_post_negative_pnl_2018)}}
    (OUT/'wc_2018_deterioration_records.json').write_text(json.dumps(diag_payload,indent=2,sort_keys=True)+'\\n')
    out=pd.DataFrame(rows)
    out.to_csv(OUT/'daily.csv',index=False)"""
    text = replace_once(text, output_old, output_new, "diagnostic persistence")

    return text


def finalize(output: Path) -> None:
    eq = pd.read_csv(output / 'wc_2018_equity.csv', parse_dates=['date']).sort_values('date')
    payload = json.loads((output / 'wc_2018_deterioration_records.json').read_text(encoding='utf-8'))
    records = pd.DataFrame(payload['records'])
    agg = payload['aggregate']

    y2018 = eq[eq.date.dt.year == 2018].copy()
    if y2018.empty:
        raise RuntimeError('diagnostic emitted no 2018 Wealth Core equity')
    start_eq = float(y2018.iloc[0].wealth_core_equity)
    end_eq = float(y2018.iloc[-1].wealth_core_equity)
    curve = y2018.wealth_core_equity.astype(float)
    dd = curve / curve.cummax() - 1.0
    net_wc_pnl = end_eq - start_eq

    if records.empty:
        first_2018 = records
        unique_tickers = 0
        retention_stats = {'mean': 0.0, 'median': 0.0, 'max': 0}
        top_losses = []
    else:
        records['first_deterioration_date'] = pd.to_datetime(records.first_deterioration_date)
        first_2018 = records[records.first_deterioration_date.dt.year == 2018].copy()
        unique_tickers = int(first_2018.ticker.nunique())
        vals = first_2018.sessions_retained_after.astype(float)
        retention_stats = {
            'mean': float(vals.mean()) if len(vals) else 0.0,
            'median': float(vals.median()) if len(vals) else 0.0,
            'max': int(vals.max()) if len(vals) else 0,
        }
        # Exact per-episode 2018 P&L is not duplicated in records; rank top names by
        # exposure persistence and first deterioration state. Detailed loss attribution
        # remains available in the daily ledger and aggregate counters.
        top_losses = first_2018.sort_values(['sessions_retained_after','first_deterioration_age'], ascending=[False,False]).head(15)[
            ['ticker','first_deterioration_date','first_recent_r21','first_momentum_rank','first_pool_size','sessions_retained_after','exit_date','exit_reason']
        ].assign(first_deterioration_date=lambda x: x.first_deterioration_date.dt.strftime('%Y-%m-%d')).to_dict('records')

    gross_neg = float(agg['all_negative_holding_pnl_2018'])
    post_neg = float(agg['post_deterioration_negative_pnl_2018'])
    post_net = float(agg['post_deterioration_pnl_2018'])
    summary = {
        'status': 'PASS',
        'evidence_label': LABEL,
        'kind': 'observational_zero_budget_diagnostic',
        'economic_experiments_consumed': 0,
        'experiment_budget_completed': 3,
        'strategy_decisions_changed': False,
        'diagnostic_condition': 'held security is outside existing top-10% momentum pool AND existing recent-21 return is negative',
        'wealth_core_2018': {
            'first_session': str(y2018.iloc[0].date.date()),
            'last_session': str(y2018.iloc[-1].date.date()),
            'start_equity': start_eq,
            'end_equity': end_eq,
            'calendar_return': float(end_eq/start_eq - 1.0),
            'calendar_net_pnl': float(net_wc_pnl),
            'max_drawdown_within_2018': float(dd.min()),
        },
        'deterioration': {
            'episodes_first_detected_in_2018': int(len(first_2018)),
            'unique_tickers_first_detected_in_2018': unique_tickers,
            'retained_sessions_after_first_detection': retention_stats,
            'all_holding_net_pnl_2018_observed': float(agg['all_holding_pnl_2018']),
            'all_negative_holding_pnl_2018_observed': gross_neg,
            'post_deterioration_net_pnl_2018': post_net,
            'post_deterioration_negative_pnl_2018': post_neg,
            'share_of_gross_negative_holding_pnl': float(post_neg/gross_neg) if gross_neg < 0 else None,
            'post_deterioration_net_loss_as_share_of_wc_net_loss': float(post_net/net_wc_pnl) if post_net < 0 and net_wc_pnl < 0 else None,
        },
        'longest_retained_episodes': top_losses,
        'interpretation_note': 'Ratios can exceed 1 because profitable holdings offset losing holdings. The gross-negative share is the cleaner structural attribution measure.',
    }
    (output / 'wc_2018_diagnostic_summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='utf-8')

    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    generated = Path('/tmp/wc_2018_retention_diagnostic.py')
    generated.write_text(transformed_source(args.output), encoding='utf-8')
    env = dict(os.environ)
    env['RESEARCH_REPLAY_MODE'] = 'fullpit'
    print(f'[RUN] {LABEL} budget=3/10 diagnostic_consumes=0', flush=True)
    subprocess.run([sys.executable, str(generated)], check=True, env=env)
    finalize(args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
