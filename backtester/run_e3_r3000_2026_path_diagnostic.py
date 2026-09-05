#!/usr/bin/env python3
"""Zero-budget 2026 path diagnostic for accepted E3 on certified R3000 PIT.

The strategy mechanics are unchanged. This wrapper instruments the accepted R3000
replay to explain why major broad-universe 2026 winners that were valid R3000
members were not selected/held on the same path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from backtester import run_e3_r3000_pit as r3

LABEL = "E3_R3000_2026_PATH_DIAGNOSTIC"
TARGETS = ("SNDK", "WDC", "LITE", "CRS", "CIEN")
BROAD_ENTRY_DATES = {
    "CRS": "2024-09-03",
    "WDC": "2025-10-24",
    "LITE": "2025-12-01",
    "SNDK": "2025-12-02",
    "CIEN": "2025-12-12",
}


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one seam, found {count}")
    return text.replace(old, new, 1)


def transformed_source(output: Path) -> str:
    text = r3.transformed_source(output)

    marker = "_R3_YEAR_CACHE={}"
    text = replace_once(
        text,
        marker,
        marker + "\n_DIAG_TARGETS=('SNDK','WDC','LITE','CRS','CIEN')",
        "target declaration",
    )

    seam = """            b_d,b_reason=cb.step(native_target,recent_r20,spy20)\n\n            if date>=START:"""
    diag = r'''            b_d,b_reason=cb.step(native_target,recent_r20,spy20)

            _diag_fields={}
            _diag_selected=[str(tick[s.pending_tid]) for s in book.slots if s.reserved() and s.pending_signal_day==gday]
            _diag_post_ready=sum(1 for s in book.slots if (not s.held()) and (not s.reserved()) and gday>=s.ready_day)
            _diag_pre_ready=_diag_post_ready+len(_diag_selected)
            _diag_et=set(map(int,et)); _diag_pool=set(map(int,pool)); _diag_durable_rank={int(t):i+1 for i,t in enumerate(durable)}
            _diag_pos={int(t):i for i,t in enumerate(tids)}
            _diag_held={int(s.tid) for s in book.slots if s.held()}
            _diag_reserved={int(s.pending_tid) for s in book.slots if s.reserved()}
            _diag_fields['diag_selected_today']='|'.join(_diag_selected)
            _diag_fields['diag_pre_ready_slots']=int(_diag_pre_ready)
            _diag_fields['diag_post_ready_slots']=int(_diag_post_ready)
            _diag_fields['diag_book_unresolved']=bool(unresolved)
            _diag_fields['diag_cash']=float(book.cash)
            _diag_fields['diag_equity']=float(eq)
            for _tk in _DIAG_TARGETS:
                _tid=tmap.get(_tk)
                _pfx='diag_'+_tk.lower()+'_'
                _diag_fields[_pfx+'member']=bool(_tk in _members)
                _diag_fields[_pfx+'observed']=False
                _diag_fields[_pfx+'eligible']=False
                _diag_fields[_pfx+'in_pool']=False
                _diag_fields[_pfx+'durable_rank']=np.nan
                _diag_fields[_pfx+'momentum']=np.nan
                _diag_fields[_pfx+'recent']=np.nan
                _diag_fields[_pfx+'score']=np.nan
                _diag_fields[_pfx+'adv20']=np.nan
                _diag_fields[_pfx+'day_dv']=np.nan
                _diag_fields[_pfx+'held']=False
                _diag_fields[_pfx+'reserved']=False
                _diag_fields[_pfx+'cooldown_until']=-1
                _diag_fields[_pfx+'selected_today']=False
                _diag_fields[_pfx+'blocker']='NO_TICKER_ID'
                if _tid is None: continue
                _tid=int(_tid); _diag_fields[_pfx+'held']=bool(_tid in _diag_held); _diag_fields[_pfx+'reserved']=bool(_tid in _diag_reserved)
                _diag_fields[_pfx+'cooldown_until']=int(book.sec_ready.get(_tid,-1)); _diag_fields[_pfx+'selected_today']=bool(_tk in _diag_selected)
                _i=_diag_pos.get(_tid)
                if _i is None:
                    _diag_fields[_pfx+'blocker']='NO_BAR_TODAY'; continue
                _diag_fields[_pfx+'observed']=True
                _diag_fields[_pfx+'eligible']=bool(_tid in _diag_et); _diag_fields[_pfx+'in_pool']=bool(_tid in _diag_pool)
                _diag_fields[_pfx+'durable_rank']=float(_diag_durable_rank.get(_tid,np.nan))
                _diag_fields[_pfx+'momentum']=float(mm[_i]) if np.isfinite(mm[_i]) else np.nan
                _diag_fields[_pfx+'recent']=float(rr[_i]) if np.isfinite(rr[_i]) else np.nan
                _diag_fields[_pfx+'score']=float(sc[_i]) if np.isfinite(sc[_i]) else np.nan
                _diag_fields[_pfx+'adv20']=float(av[_i]) if np.isfinite(av[_i]) else np.nan
                _diag_fields[_pfx+'day_dv']=float(dv[_i]) if np.isfinite(dv[_i]) else np.nan
                if _diag_fields[_pfx+'held']:
                    _blk='ALREADY_HELD'
                elif _diag_fields[_pfx+'selected_today']:
                    _blk='SELECTED_TODAY'
                elif _diag_fields[_pfx+'reserved']:
                    _blk='ALREADY_RESERVED'
                elif not _diag_fields[_pfx+'member']:
                    _blk='NOT_ACTIVE_R3000_MEMBER'
                elif not bool(continuous[_i]):
                    _blk='INSUFFICIENT_126_SESSION_HISTORY'
                elif not np.isfinite(mm[_i]):
                    _blk='MOMENTUM_UNAVAILABLE'
                elif not np.isfinite(rr[_i]):
                    _blk='RECENT_RETURN_UNAVAILABLE'
                elif not (np.isfinite(cu[_i]) and cu[_i]>=MIN_PRICE):
                    _blk='MIN_PRICE'
                elif not (np.isfinite(av[_i]) and av[_i]>=MIN_ADV20):
                    _blk='MIN_ADV20'
                elif not (np.isfinite(dv[_i]) and dv[_i]>=MIN_DAY_DV):
                    _blk='MIN_DAY_DV'
                elif not (np.isfinite(sc[_i]) and np.isfinite(fvol[_i]) and fvol[_i]>0):
                    _blk='SCORE_OR_VOL'
                elif _tid not in _diag_pool:
                    _blk='OUTSIDE_TOP_DECILE_MOMENTUM_POOL'
                elif not (np.isfinite(recent[_tid]) and recent[_tid]>=0):
                    _blk='NEGATIVE_RECENT_RETURN'
                elif book.sec_ready.get(_tid,-1)>gday:
                    _blk='COOLDOWN'
                elif _tid in term_tids:
                    _blk='TERMINAL_EVENT'
                elif unresolved:
                    _blk='UNRESOLVED_BOOK_MARK'
                elif not (book.cash>0):
                    _blk='NO_CASH'
                elif _diag_pre_ready<=0:
                    _blk='NO_READY_SLOT'
                elif _diag_selected:
                    _blk='RANKED_BEHIND_DAILY_ADMISSION'
                else:
                    _blk='OTHER_ADMISSION_PATH'
                _diag_fields[_pfx+'blocker']=_blk

            if date>=START:'''
    text = replace_once(text, seam, diag, "daily target diagnostic state")

    row_old = "'eligible_count':int(len(et)),'leadership_population':int(nk),'held_count':int(len(held)),'cum_buys':int(buys),'cum_sells':int(sells)})"
    row_new = "'eligible_count':int(len(et)),'leadership_population':int(nk),'held_count':int(len(held)),'cum_buys':int(buys),'cum_sells':int(sells),**_diag_fields})"
    text = replace_once(text, row_old, row_new, "append diagnostic fields")
    return text


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def summarize(output: Path) -> None:
    daily=pd.read_csv(output/'daily.csv.gz',compression='gzip',parse_dates=['date'])
    rows=[]; blocker_rows=[]
    dates=list(daily.date)
    for tk in TARGETS:
        p='diag_'+tk.lower()+'_'
        broad_entry=pd.Timestamp(BROAD_ENTRY_DATES[tk])
        before=daily[daily.date<broad_entry]
        signal=before.iloc[-1] if len(before) else None
        first_member=daily.loc[daily[p+'member'].astype(bool),'date']
        first_eligible=daily.loc[daily[p+'eligible'].astype(bool),'date']
        first_pool=daily.loc[daily[p+'in_pool'].astype(bool),'date']
        first_selected=daily.loc[daily[p+'selected_today'].astype(bool),'date']
        first_held=daily.loc[daily[p+'held'].astype(bool),'date']
        rows.append({
            'ticker':tk,
            'broad_entry_date':str(broad_entry.date()),
            'broad_signal_date':str(pd.Timestamp(signal.date).date()) if signal is not None else '',
            'r3000_blocker_on_broad_signal':str(signal[p+'blocker']) if signal is not None else '',
            'r3000_member_on_broad_signal':bool(signal[p+'member']) if signal is not None else False,
            'r3000_eligible_on_broad_signal':bool(signal[p+'eligible']) if signal is not None else False,
            'r3000_in_pool_on_broad_signal':bool(signal[p+'in_pool']) if signal is not None else False,
            'r3000_durable_rank_on_broad_signal':float(signal[p+'durable_rank']) if signal is not None and pd.notna(signal[p+'durable_rank']) else np.nan,
            'r3000_recent_on_broad_signal':float(signal[p+'recent']) if signal is not None and pd.notna(signal[p+'recent']) else np.nan,
            'selected_other_on_broad_signal':str(signal['diag_selected_today']) if signal is not None else '',
            'pre_ready_slots_on_broad_signal':int(signal['diag_pre_ready_slots']) if signal is not None else -1,
            'first_r3000_member_date':str(first_member.iloc[0].date()) if len(first_member) else '',
            'first_r3000_eligible_date':str(first_eligible.iloc[0].date()) if len(first_eligible) else '',
            'first_r3000_pool_date':str(first_pool.iloc[0].date()) if len(first_pool) else '',
            'first_r3000_selected_date':str(first_selected.iloc[0].date()) if len(first_selected) else '',
            'first_r3000_held_date':str(first_held.iloc[0].date()) if len(first_held) else '',
        })
        q=daily[(daily.date>=pd.Timestamp('2024-01-01')) & (daily.date<=pd.Timestamp('2026-07-31'))]
        vc=q[p+'blocker'].astype(str).value_counts()
        for blocker,count in vc.items():
            blocker_rows.append({'ticker':tk,'blocker':blocker,'sessions':int(count)})
    summary=pd.DataFrame(rows)
    blockers=pd.DataFrame(blocker_rows).sort_values(['ticker','sessions'],ascending=[True,False])
    summary.to_csv(output/'r3000_2026_path_summary.csv',index=False)
    blockers.to_csv(output/'r3000_2026_path_blockers.csv',index=False)
    cols=['date','eligible_count','leadership_population','held_count','diag_selected_today','diag_pre_ready_slots']
    for tk in TARGETS:
        p='diag_'+tk.lower()+'_'
        cols += [p+'member',p+'eligible',p+'in_pool',p+'durable_rank',p+'momentum',p+'recent',p+'score',p+'held',p+'reserved',p+'selected_today',p+'blocker']
    daily.loc[daily.date>=pd.Timestamp('2024-01-01'),cols].to_csv(output/'r3000_2026_path_daily.csv.gz',index=False,compression={'method':'gzip','compresslevel':6,'mtime':0})
    manifest={
        'schema':'backtester.e3-r3000-2026-path-diagnostic/1',
        'status':'PASS',
        'zero_budget_diagnostic':True,
        'strategy_mechanics_changed':False,
        'strategy_source_head':r3.E3_SOURCE_HEAD,
        'corpus_head':r3.CORPUS_HEAD,
        'targets':list(TARGETS),
        'broad_entry_dates':BROAD_ENTRY_DATES,
    }
    (output/'r3000_2026_path_manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    files=[output/'r3000_2026_path_summary.csv',output/'r3000_2026_path_blockers.csv',output/'r3000_2026_path_daily.csv.gz',output/'r3000_2026_path_manifest.json']
    (output/'R3000_2026_PATH_SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in files))
    print('[PATH SUMMARY]',flush=True); print(summary.to_string(index=False),flush=True)
    print('[BLOCKERS]',flush=True); print(blockers.to_string(index=False),flush=True)


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,required=True); args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    generated=Path('/tmp/e3_r3000_2026_path_diagnostic.py')
    generated.write_text(transformed_source(args.output),encoding='utf-8')
    env=dict(os.environ); env['RESEARCH_REPLAY_MODE']='fullpit'
    print(f'[RUN] {LABEL}',flush=True)
    subprocess.run([sys.executable,str(generated)],check=True,env=env)
    r3.finalize(args.output)
    summarize(args.output)
    return 0

if __name__=='__main__': raise SystemExit(main())
