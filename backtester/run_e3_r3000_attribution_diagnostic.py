#!/usr/bin/env python3
"""Zero-budget attribution diagnostic: accepted broad E3 vs certified R3000 membership.

The accepted E3/broad strategy is not changed. This wrapper adds read-only telemetry
that tags each executed broad-universe trade with contemporaneous certified R3000
membership and emits per-position mark-to-market PnL for attribution.
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

from backtester import experiment_architecture_recovery_concordance_e3 as e3

LABEL = "E3_BROAD_VS_CERTIFIED_R3000_ATTRIBUTION_DIAGNOSTIC"
E3_SOURCE_HEAD = "3f27834db427e71d9bb8d0b6160c8835b739c906"
CORPUS_HEAD = "0ee69dfc699927bf5e7d768ae57b77d65e99ed59"
CORPUS_RUN_ID = 33940944721
CORPUS_ARTIFACT_DIGEST = "sha256:c5ba5e6cf9d953797068a7af8b944129da9879051e1aac447acdc4b0c717346f"
TARGET_YEARS = (2007, 2017, 2020, 2026)
START_ATTRIBUTION = pd.Timestamp("2006-07-31")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one seam, found {count}")
    return text.replace(old, new, 1)


def transformed_source(output: Path) -> str:
    text = e3.transformed_source(output)

    marker = "def finite(x): return x is not None and np.isfinite(x)"
    helper = r'''def finite(x): return x is not None and np.isfinite(x)

_DIAG_R3000_MEMBERSHIP_PATH=Path(os.environ['R3000_MEMBERSHIP_PATH'])
_DIAG_CANONICAL_ROOT=Path(os.environ['CANONICAL_ROOT'])
_diag_r3=pd.read_csv(_DIAG_R3000_MEMBERSHIP_PATH,compression='gzip',dtype=str).fillna('')
_diag_r3['holdings_effective_date']=pd.to_datetime(_diag_r3.holdings_effective_date).dt.normalize()
_DIAG_R3_DATES=sorted(pd.Timestamp(x) for x in _diag_r3.holdings_effective_date.unique())
_DIAG_R3_ROWS_BY_DATE={d:_diag_r3[_diag_r3.holdings_effective_date.eq(d)].copy() for d in _DIAG_R3_DATES}
_DIAG_R3_YEAR_CACHE={}
_DIAG_TICKER_DATES=defaultdict(list)
for _d,_g in _DIAG_R3_ROWS_BY_DATE.items():
    for _tk in set(_g.normalized_ticker_on_snapshot_date.astype(str).str.upper()):
        if _tk: _DIAG_TICKER_DATES[_tk].append(_d)

def _diag_truth(v): return str(v).strip().lower() in ('1','true','t','yes')

def _diag_active_date(session):
    d=pd.Timestamp(session).normalize()
    prior=[x for x in _DIAG_R3_DATES if x<=d]
    return prior[-1] if prior else None

def _diag_membership_sids(session):
    d=_diag_active_date(session)
    if d is None: return set()
    g=_DIAG_R3_ROWS_BY_DATE[d]
    return set(g.loc[(g.identity_status=='RESOLVED')&(g.permanent_security_id!=''),'permanent_security_id'].astype(str))

def diag_r3000_year_tickers(year):
    if year in _DIAG_R3_YEAR_CACHE: return _DIAG_R3_YEAR_CACHE[year]
    p=_DIAG_CANONICAL_ROOT/f'observations-{year}.csv.gz'
    if not p.is_file():
        out={}; _DIAG_R3_YEAR_CACHE.clear(); _DIAG_R3_YEAR_CACHE[year]=out; return out
    q=pd.read_csv(p,compression='gzip',usecols=['session','security_id','ticker','listing_active','tradeable'],dtype=str).fillna('')
    q['session']=pd.to_datetime(q.session).dt.normalize()
    out={}
    for session,g in q.groupby('session',sort=True):
        members=_diag_membership_sids(session)
        if not members:
            out[pd.Timestamp(session).strftime('%Y-%m-%d')]=set(); continue
        ok=g.security_id.astype(str).isin(members) & g.listing_active.map(_diag_truth) & g.tradeable.map(_diag_truth)
        out[pd.Timestamp(session).strftime('%Y-%m-%d')]=set(g.loc[ok,'ticker'].astype(str).str.upper())
    _DIAG_R3_YEAR_CACHE.clear(); _DIAG_R3_YEAR_CACHE[year]=out
    return out

def diag_r3000_classification(ticker,session,mapped_members):
    tk=str(ticker).upper(); d=pd.Timestamp(session).normalize(); active=_diag_active_date(d)
    if active is None: return 'PRE_R3000_CORPUS'
    if tk in mapped_members: return 'IN_ACTIVE_R3000'
    g=_DIAG_R3_ROWS_BY_DATE[active]
    q=g[g.normalized_ticker_on_snapshot_date.astype(str).str.upper().eq(tk)]
    if len(q):
        statuses=set(q.identity_status.astype(str))
        if 'RESOLVED' in statuses: return 'ACTIVE_CLAIM_RESOLVED_BINDING_MISS'
        return 'ACTIVE_CLAIM_UNRESOLVED'
    dates=_DIAG_TICKER_DATES.get(tk,[])
    future=[x for x in dates if x>d]
    if future and (future[0]-d).days<=370: return 'NOT_ACTIVE_APPEARS_NEXT_SNAPSHOT'
    past=[x for x in dates if x<active]
    if past: return 'NOT_ACTIVE_WAS_PRIOR_MEMBER'
    return 'NO_ACTIVE_R3000_CLAIM'
'''
    text = replace_once(text, marker, helper, "membership attribution helpers")

    state_old = "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0"
    state_new = state_old + "\n    _diag_open={}; _diag_trade_seq=0; _diag_trades=[]; _diag_marks=[]"
    text = replace_once(text, state_old, state_new, "diagnostic state")

    year_old = "        d.sort_values(['date','tid'],inplace=True,kind='mergesort')\n        for date,g in d.groupby('date',sort=True):"
    year_new = "        d.sort_values(['date','tid'],inplace=True,kind='mergesort')\n        _diag_r3_year=diag_r3000_year_tickers(y)\n        for date,g in d.groupby('date',sort=True):"
    text = replace_once(text, year_old, year_new, "year membership preload")

    sell_old = """                if finite(px) and px>0 and finite(volume[s.tid]) and volume[s.tid]>0:
                    book.cash+=s.qty*float(px)*(1-COST); sells+=1
                    if s.sell_reason=='stop': stop_days.append(gday)"""
    sell_new = """                if finite(px) and px>0 and finite(volume[s.tid]) and volume[s.tid]>0:
                    _diag_meta=_diag_open.get(id(s)); _diag_reason=s.sell_reason; _diag_proceeds=s.qty*float(px)*(1-COST)
                    if _diag_meta is not None:
                        _diag_trades.append({**_diag_meta,'exit_date':ds,'exit_reason':_diag_reason,'exit_qty':float(s.qty),'exit_raw_open':float(px),'exit_proceeds':float(_diag_proceeds),'total_pnl':float(_diag_proceeds+_diag_meta['dividends']-_diag_meta['entry_cost']),'return_on_entry_cost':float((_diag_proceeds+_diag_meta['dividends'])/_diag_meta['entry_cost']-1.0) if _diag_meta['entry_cost']>0 else np.nan,'exit_r3000_classification':diag_r3000_classification(tick[s.tid],date,_diag_r3_year.get(ds,set()))})
                        _diag_open.pop(id(s),None)
                    book.cash+=_diag_proceeds; sells+=1
                    if s.sell_reason=='stop': stop_days.append(gday)"""
    text = replace_once(text, sell_old, sell_new, "normal sell attribution")

    terminal_old = """                elif s.sell_reason=='terminal':
                    px2=book.last_raw.get(s.tid,np.nan)
                    if finite(px2) and px2>0: book.cash+=s.qty*float(px2)*(1-COST)
                    book.sec_ready[s.tid]=gday+COOLDOWN"""
    terminal_new = """                elif s.sell_reason=='terminal':
                    px2=book.last_raw.get(s.tid,np.nan); _diag_meta=_diag_open.get(id(s)); _diag_proceeds=s.qty*float(px2)*(1-COST) if finite(px2) and px2>0 else 0.0
                    if _diag_meta is not None:
                        _diag_trades.append({**_diag_meta,'exit_date':ds,'exit_reason':'terminal','exit_qty':float(s.qty),'exit_raw_open':float(px2) if finite(px2) else np.nan,'exit_proceeds':float(_diag_proceeds),'total_pnl':float(_diag_proceeds+_diag_meta['dividends']-_diag_meta['entry_cost']),'return_on_entry_cost':float((_diag_proceeds+_diag_meta['dividends'])/_diag_meta['entry_cost']-1.0) if _diag_meta['entry_cost']>0 else np.nan,'exit_r3000_classification':diag_r3000_classification(tick[s.tid],date,_diag_r3_year.get(ds,set()))})
                        _diag_open.pop(id(s),None)
                    if finite(px2) and px2>0: book.cash+=_diag_proceeds
                    book.sec_ready[s.tid]=gday+COOLDOWN"""
    text = replace_once(text, terminal_old, terminal_new, "terminal sell attribution")

    buy_old = "book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1"
    buy_new = buy_old + "; _diag_trade_seq+=1; _diag_open[id(s)]={'trade_id':int(_diag_trade_seq),'ticker':str(tick[tid]),'security_id':str(sid[tid]),'entry_date':ds,'entry_qty':float(q),'entry_raw_open':float(px),'entry_cost':float(q*float(px)*(1+COST)),'dividends':0.0,'entry_r3000_classification':diag_r3000_classification(tick[tid],date,_diag_r3_year.get(ds,set()))}"
    text = replace_once(text, buy_old, buy_new, "buy attribution")

    dividend_old = "rawdiv=sum(vals)*float(clraw[tid])/float(clsig[tid]); book.receivables.append((gday+1,q*rawdiv)); div_events+=1"
    dividend_new = dividend_old + "; [_diag_open[id(_s)].__setitem__('dividends',_diag_open[id(_s)]['dividends']+q*rawdiv) for _s in book.slots if _s.held() and _s.tid==tid and id(_s) in _diag_open]"
    text = replace_once(text, dividend_old, dividend_new, "dividend attribution")

    mark_old = "            eq,unresolved=book.equity(clraw)\n            held=[]"
    mark_new = """            eq,unresolved=book.equity(clraw)
            if date>=pd.Timestamp('2006-07-31'):
                _diag_members=_diag_r3_year.get(ds,set())
                for _s in book.slots:
                    if not _s.held() or id(_s) not in _diag_open: continue
                    _dm=_diag_open[id(_s)]; _px=clraw[_s.tid]
                    if not (finite(_px) and _px>0): _px=book.last_raw.get(_s.tid,np.nan)
                    if finite(_px) and _px>0:
                        _mv=float(_s.qty)*float(_px); _tp=_mv+float(_dm['dividends'])-float(_dm['entry_cost'])
                        _diag_marks.append({'date':ds,'trade_id':int(_dm['trade_id']),'ticker':str(tick[_s.tid]),'security_id':str(sid[_s.tid]),'market_value':_mv,'dividends':float(_dm['dividends']),'total_pnl':float(_tp),'current_r3000_classification':diag_r3000_classification(tick[_s.tid],date,_diag_members)})
            held=[]"""
    text = replace_once(text, mark_old, mark_new, "daily mark attribution")

    output_old = "    out=pd.DataFrame(rows)\n    out.to_csv(OUT/'daily.csv',index=False)"
    output_new = """    pd.DataFrame(_diag_trades).to_csv(OUT/'broad_r3000_trade_attribution.csv',index=False)
    pd.DataFrame(_diag_marks).to_csv(OUT/'broad_r3000_daily_position_marks.csv.gz',index=False,compression={'method':'gzip','compresslevel':6,'mtime':0})
    pd.DataFrame([{**m,'exit_date':'','exit_reason':'OPEN','exit_qty':np.nan,'exit_raw_open':np.nan,'exit_proceeds':np.nan,'total_pnl':np.nan,'return_on_entry_cost':np.nan,'exit_r3000_classification':''} for m in _diag_open.values()]).to_csv(OUT/'broad_r3000_open_trades.csv',index=False)
    out=pd.DataFrame(rows)
    out.to_csv(OUT/'daily.csv',index=False)"""
    text = replace_once(text, output_old, output_new, "diagnostic file emission")
    return text


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def year_trade_contributions(trades: pd.DataFrame, marks: pd.DataFrame, year: int) -> pd.DataFrame:
    y0=pd.Timestamp(f'{year}-01-01'); y1=pd.Timestamp(f'{year}-12-31')
    trades=trades.copy(); marks=marks.copy()
    if len(trades):
        trades['entry_date']=pd.to_datetime(trades.entry_date); trades['exit_date']=pd.to_datetime(trades.exit_date,errors='coerce')
    marks['date']=pd.to_datetime(marks.date)
    ids=set(marks.loc[(marks.date>=y0)&(marks.date<=y1),'trade_id'].astype(int))
    if len(trades): ids |= set(trades.loc[(trades.exit_date>=y0)&(trades.exit_date<=y1),'trade_id'].astype(int))
    rows=[]
    for tid in sorted(ids):
        m=marks[marks.trade_id.astype(int).eq(tid)].sort_values('date')
        tr=trades[trades.trade_id.astype(int).eq(tid)] if len(trades) else pd.DataFrame()
        meta=(tr.iloc[0].to_dict() if len(tr) else {})
        before=m[m.date<y0]
        base=float(before.iloc[-1].total_pnl) if len(before) else 0.0
        if len(tr) and pd.notna(tr.iloc[0].exit_date) and y0<=tr.iloc[0].exit_date<=y1:
            end=float(tr.iloc[0].total_pnl); endpoint=str(tr.iloc[0].exit_date.date()); closed=True
        else:
            inside=m[(m.date>=y0)&(m.date<=y1)]
            if not len(inside): continue
            end=float(inside.iloc[-1].total_pnl); endpoint=str(inside.iloc[-1].date.date()); closed=False
        entry_cls=str(meta.get('entry_r3000_classification',''))
        ticker=str(meta.get('ticker', m.iloc[0].ticker if len(m) else ''))
        rows.append({'year':year,'trade_id':tid,'ticker':ticker,'entry_date':str(pd.Timestamp(meta.get('entry_date')).date()) if meta.get('entry_date') else '',
                     'entry_r3000_classification':entry_cls,'pnl_start':base,'pnl_end':end,'pnl_contribution':end-base,'endpoint':endpoint,'closed_in_year':closed})
    return pd.DataFrame(rows)


def finalize(output: Path) -> None:
    e3.finalize(output)
    trades=pd.read_csv(output/'broad_r3000_trade_attribution.csv')
    marks=pd.read_csv(output/'broad_r3000_daily_position_marks.csv.gz',compression='gzip')
    daily=pd.read_csv(output/'daily.csv.gz',compression='gzip',parse_dates=['date'])
    rows=[]
    top=[]
    for year in TARGET_YEARS:
        c=year_trade_contributions(trades,marks,year)
        if c.empty: continue
        yd=daily.loc[daily.date.dt.year.eq(year),'research_wealth_core_equity']
        broad_delta=float(yd.iloc[-1]/yd.iloc[0]-1.0)
        total=float(c.pnl_contribution.sum())
        inside=float(c.loc[c.entry_r3000_classification.eq('IN_ACTIVE_R3000'),'pnl_contribution'].sum())
        outside=float(c.loc[~c.entry_r3000_classification.eq('IN_ACTIVE_R3000'),'pnl_contribution'].sum())
        rows.append({'year':year,'broad_wc_return':broad_delta,'trade_pnl_contribution_total':total,'in_r3000_entry_pnl':inside,'outside_r3000_entry_pnl':outside,'outside_share_of_trade_pnl':outside/total if total else np.nan,'trade_count':int(len(c)),'outside_trade_count':int((~c.entry_r3000_classification.eq('IN_ACTIVE_R3000')).sum())})
        c.to_csv(output/f'broad_r3000_attribution_{year}.csv',index=False)
        x=c[~c.entry_r3000_classification.eq('IN_ACTIVE_R3000')].sort_values('pnl_contribution',ascending=False).head(25).copy()
        top.append(x)
    summary=pd.DataFrame(rows)
    summary.to_csv(output/'broad_r3000_attribution_summary.csv',index=False)
    tops=pd.concat(top,ignore_index=True) if top else pd.DataFrame()
    tops.to_csv(output/'broad_r3000_top_excluded_winners.csv',index=False)
    class_summary=(trades.groupby('entry_r3000_classification',dropna=False).agg(trades=('trade_id','count'),total_realized_pnl=('total_pnl','sum')).reset_index())
    class_summary.to_csv(output/'broad_r3000_trade_class_summary.csv',index=False)
    manifest={'schema':'backtester.e3-broad-vs-r3000-attribution-diagnostic/1','status':'PASS','evidence_label':LABEL,'zero_budget_diagnostic':True,'strategy_mechanics_changed':False,'strategy_source_head':E3_SOURCE_HEAD,'corpus_head':CORPUS_HEAD,'corpus_run_id':CORPUS_RUN_ID,'corpus_artifact_digest':CORPUS_ARTIFACT_DIGEST,'target_years':list(TARGET_YEARS),'files':{}}
    files=[output/'broad_r3000_trade_attribution.csv',output/'broad_r3000_daily_position_marks.csv.gz',output/'broad_r3000_open_trades.csv',output/'broad_r3000_attribution_summary.csv',output/'broad_r3000_top_excluded_winners.csv',output/'broad_r3000_trade_class_summary.csv']
    files += [output/f'broad_r3000_attribution_{y}.csv' for y in TARGET_YEARS if (output/f'broad_r3000_attribution_{y}.csv').exists()]
    for p in files: manifest['files'][p.name]=sha256(p)
    (output/'broad_r3000_attribution_manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    files.append(output/'broad_r3000_attribution_manifest.json')
    (output/'BROAD_R3000_ATTRIBUTION_SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in files))
    print('[ATTRIBUTION SUMMARY]',flush=True); print(summary.to_string(index=False),flush=True)
    print('[CLASS SUMMARY]',flush=True); print(class_summary.to_string(index=False),flush=True)
    print('[TOP EXCLUDED WINNERS]',flush=True); print(tops.to_string(index=False),flush=True)


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,required=True); args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    generated=Path('/tmp/e3_broad_vs_r3000_attribution.py'); generated.write_text(transformed_source(args.output),encoding='utf-8')
    env=dict(os.environ); env['RESEARCH_REPLAY_MODE']='fullpit'
    print(f'[RUN] {LABEL} E3={E3_SOURCE_HEAD} corpus={CORPUS_HEAD}',flush=True)
    subprocess.run([sys.executable,str(generated)],check=True,env=env)
    finalize(args.output)
    return 0

if __name__=='__main__': raise SystemExit(main())
