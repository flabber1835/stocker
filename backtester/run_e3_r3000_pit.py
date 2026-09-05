#!/usr/bin/env python3
"""Run accepted Strategy 9 E3 on the certified R3000_PROXY(t) PIT corpus.

Strategy mechanics come verbatim from accepted E3 head
3f27834db427e71d9bb8d0b6160c8835b739c906. This wrapper changes only the
universe authority and reporting. Membership is the latest contemporaneous
IWB/IWM union snapshot available on or before each session. Only RESOLVED
permanent-security claims are admitted. Current-session ticker/listing/tradeable
state comes from the pinned canonical PIT observations, so no current Russell or
current-metadata universe gate is used.
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

LABEL = "STRATEGY9_E3_CERTIFIED_R3000_PIT"
E3_SOURCE_HEAD = "3f27834db427e71d9bb8d0b6160c8835b739c906"
CORPUS_HEAD = "0ee69dfc699927bf5e7d768ae57b77d65e99ed59"
CORPUS_RUN_ID = 33940944721
CORPUS_ARTIFACT_DIGEST = "sha256:c5ba5e6cf9d953797068a7af8b944129da9879051e1aac447acdc4b0c717346f"
WINDOWS = {
    "5": ("2021-07-30", 5.0),
    "10": ("2016-07-29", 10.0),
    "15": ("2011-07-29", 15.0),
    "20": ("2006-07-31", 20.0),
}
INITIAL_CAPITAL = 100_000_000.0


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one seam, found {count}")
    return text.replace(old, new, 1)


def transformed_source(output: Path) -> str:
    text = e3.transformed_source(output)

    marker = "def finite(x): return x is not None and np.isfinite(x)"
    authority = r'''def finite(x): return x is not None and np.isfinite(x)

_R3000_MEMBERSHIP_PATH=Path(os.environ['R3000_MEMBERSHIP_PATH'])
_CANONICAL_ROOT=Path(os.environ['CANONICAL_ROOT'])
_r3=pd.read_csv(_R3000_MEMBERSHIP_PATH,compression='gzip',dtype=str).fillna('')
_r3=_r3[(_r3.identity_status=='RESOLVED')&(_r3.permanent_security_id!='')].copy()
_r3['holdings_effective_date']=pd.to_datetime(_r3.holdings_effective_date).dt.normalize()
_R3_DATES=sorted(_r3.holdings_effective_date.unique())
_R3_BY_DATE={pd.Timestamp(d):set(_r3.loc[_r3.holdings_effective_date.eq(d),'permanent_security_id'].astype(str)) for d in _R3_DATES}
_R3_YEAR_CACHE={}

def _truth(v): return str(v).strip().lower() in ('1','true','t','yes')

def _membership_sids(session):
    d=pd.Timestamp(session).normalize()
    prior=[x for x in _R3_DATES if pd.Timestamp(x)<=d]
    return _R3_BY_DATE[pd.Timestamp(prior[-1])] if prior else set()

def r3000_year_tickers(year):
    if year in _R3_YEAR_CACHE: return _R3_YEAR_CACHE[year]
    p=_CANONICAL_ROOT/f'observations-{year}.csv.gz'
    if not p.is_file(): raise RuntimeError(f'missing canonical PIT partition {p}')
    q=pd.read_csv(p,compression='gzip',usecols=['session','security_id','ticker','listing_active','tradeable'],dtype=str).fillna('')
    q['session']=pd.to_datetime(q.session).dt.normalize()
    out={}
    for session,g in q.groupby('session',sort=True):
        members=_membership_sids(session)
        if not members:
            out[pd.Timestamp(session).strftime('%Y-%m-%d')]=set(); continue
        ok=g.security_id.astype(str).isin(members) & g.listing_active.map(_truth) & g.tradeable.map(_truth)
        out[pd.Timestamp(session).strftime('%Y-%m-%d')]=set(g.loc[ok,'ticker'].astype(str).str.upper())
    _R3_YEAR_CACHE.clear(); _R3_YEAR_CACHE[year]=out
    return out
'''
    text = replace_once(text, marker, authority, "R3000 authority helpers")

    year_seam = "        d.sort_values(['date','tid'],inplace=True,kind='mergesort')\n        for date,g in d.groupby('date',sort=True):"
    year_new = "        d.sort_values(['date','tid'],inplace=True,kind='mergesort')\n        _r3000_year=r3000_year_tickers(y)\n        for date,g in d.groupby('date',sort=True):"
    text = replace_once(text, year_seam, year_new, "year authority preload")

    old_elig = "            elig=common[tids]&listed&continuous&np.isfinite(mm)&np.isfinite(rr)&np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&np.isfinite(dv)&(dv>=MIN_DAY_DV)&np.isfinite(sc)&(fvol>0)"
    new_elig = "            _members=_r3000_year.get(ds,set()); r3000_mask=np.fromiter((str(tick[int(t)]).upper() in _members for t in tids),dtype=bool,count=len(tids))\n            elig=r3000_mask&continuous&np.isfinite(mm)&np.isfinite(rr)&np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&np.isfinite(dv)&(dv>=MIN_DAY_DV)&np.isfinite(sc)&(fvol>0)"
    text = replace_once(text, old_elig, new_elig, "replace broad universe with certified R3000")

    telemetry_old = "'eligible_count':int(len(et)),'leadership_population':int(nk),'held_count':int(len(held))})"
    telemetry_new = "'eligible_count':int(len(et)),'leadership_population':int(nk),'held_count':int(len(held)),'cum_buys':int(buys),'cum_sells':int(sells)})"
    text = replace_once(text, telemetry_old, telemetry_new, "trade-count telemetry")

    portfolio = r'''    final_eq,_=book.equity(clraw)
    final_alloc=float(eff['A'])
    _portfolio=[]; _held_value=0.0
    for s in book.slots:
        if not s.held(): continue
        px=clraw[s.tid]
        if not (finite(px) and px>0): px=book.last_raw.get(s.tid,np.nan)
        if not (finite(px) and px>0): continue
        value=float(s.qty)*float(px); _held_value+=value
        _portfolio.append({'ticker':str(tick[s.tid]),'security_id':str(sid[s.tid]),'shares':float(s.qty),'raw_price':float(px),'wealth_core_value':value,'wealth_core_weight':value/final_eq if final_eq>0 else np.nan,'e3_effective_weight':final_alloc*value/final_eq if final_eq>0 else np.nan})
    _internal_cash=max(final_eq-_held_value,0.0)
    _e3_cash=(1.0-final_alloc)+final_alloc*(_internal_cash/final_eq if final_eq>0 else 1.0)
    _portfolio.append({'ticker':'CASH','security_id':'','shares':np.nan,'raw_price':np.nan,'wealth_core_value':_internal_cash,'wealth_core_weight':_internal_cash/final_eq if final_eq>0 else np.nan,'e3_effective_weight':_e3_cash})
    pd.DataFrame(_portfolio).sort_values(['e3_effective_weight','ticker'],ascending=[False,True]).to_csv(OUT/'e3_r3000_final_portfolio.csv',index=False)

    out=pd.DataFrame(rows)'''
    text = replace_once(text, "    out=pd.DataFrame(rows)", portfolio, "final portfolio export")
    return text


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def trade_counts(daily: pd.DataFrame, start: str) -> tuple[int,int]:
    start_ts=pd.Timestamp(start)
    before=daily[daily.date<start_ts]
    window=daily[daily.date>=start_ts]
    if window.empty: raise RuntimeError(f'empty trade window {start}')
    b0=int(before.iloc[-1].cum_buys) if len(before) else 0
    s0=int(before.iloc[-1].cum_sells) if len(before) else 0
    return int(window.iloc[-1].cum_buys)-b0, int(window.iloc[-1].cum_sells)-s0


def finalize(output: Path) -> None:
    # Reuse accepted E3's exact postprocessing chain, excluding its old-universe
    # control-hash/release-date assertions, which are deliberately inapplicable.
    e3.strategy9.finalize(output)
    daily=pd.read_csv(output/'daily.csv.gz',compression='gzip',parse_dates=['date'])
    required={'A_nav','spy_nav','cum_buys','cum_sells','eligible_count'}
    missing=required-set(daily.columns)
    if missing: raise RuntimeError(f'missing E3 R3000 evidence columns: {sorted(missing)}')

    rows=[]; trades=[]
    for w,(start,years) in WINDOWS.items():
        for variant,col in (("E3","A_nav"),("SPY","spy_nav")):
            m=e3.corrected.old.metric_block(daily,col,start,years)
            m['ending_value_on_100m']=INITIAL_CAPITAL*float(m['ending_multiple'])
            rows.append({'window_years':w,'variant':variant,**m})
        b,s=trade_counts(daily,start)
        trades.append({'window_years':w,'start':start,'end':str(daily.iloc[-1].date.date()),'executed_buys':b,'executed_sells':s})
    metrics=pd.DataFrame(rows); counts=pd.DataFrame(trades)
    metrics.to_csv(output/'e3_r3000_metrics.csv',index=False)
    counts.to_csv(output/'e3_r3000_trade_counts.csv',index=False)

    portfolio=pd.read_csv(output/'e3_r3000_final_portfolio.csv')
    summary=json.loads((output/'summary.json').read_text())
    summary.update({
        'status':'PASS',
        'evidence_label':LABEL,
        'strategy_source_head':E3_SOURCE_HEAD,
        'corpus_head':CORPUS_HEAD,
        'corpus_run_id':CORPUS_RUN_ID,
        'corpus_artifact_digest':CORPUS_ARTIFACT_DIGEST,
        'universe_authority':'certified R3000_PROXY(t) union PIT membership; latest holdings_effective_date <= session; RESOLVED identities only',
        'universe_identity_binding':'permanent_security_id membership -> same-session canonical PIT ticker; canonical listing_active=true and tradeable=true',
        'redundant_russell_eligibility_lookup_removed':True,
        'e3_mechanics_changed':False,
        'measurement_windows':list(WINDOWS),
        'trade_counts':trades,
        'ending_portfolio_rows':int(len(portfolio)),
    })
    (output/'e3_r3000_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    manifest={
        'schema':'backtester.strategy9-e3-certified-r3000-pit/1','status':'PASS','evidence_label':LABEL,
        'strategy_source_head':E3_SOURCE_HEAD,'corpus_head':CORPUS_HEAD,'corpus_run_id':CORPUS_RUN_ID,
        'corpus_artifact_digest':CORPUS_ARTIFACT_DIGEST,'windows':list(WINDOWS),
        'fresh_chronological_replay':True,'decision_at_close_next_open_effect':True,
        'same_session_canonical_listing_tradeable_gate':True,'unresolved_membership_excluded':True,
    }
    (output/'e3_r3000_manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    files=[output/'daily.csv.gz',output/'e3_r3000_metrics.csv',output/'e3_r3000_trade_counts.csv',output/'e3_r3000_final_portfolio.csv',output/'e3_r3000_summary.json',output/'e3_r3000_manifest.json']
    (output/'E3_R3000_SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in files))
    print(metrics.to_string(index=False),flush=True)
    print(counts.to_string(index=False),flush=True)
    print(portfolio.to_string(index=False),flush=True)


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,required=True); args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    generated=Path('/tmp/strategy9_e3_certified_r3000.py')
    generated.write_text(transformed_source(args.output),encoding='utf-8')
    env=dict(os.environ); env['RESEARCH_REPLAY_MODE']='fullpit'
    print(f'[RUN] {LABEL} E3={E3_SOURCE_HEAD} corpus={CORPUS_HEAD}',flush=True)
    subprocess.run([sys.executable,str(generated)],check=True,env=env)
    finalize(args.output)
    return 0

if __name__=='__main__': raise SystemExit(main())
