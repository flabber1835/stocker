#!/usr/bin/env python3
"""Targeted triage for unresolved split rows that have real SEP price-domain transitions."""
from __future__ import annotations

import csv, gzip, hashlib, json, math, os
from datetime import date
from pathlib import Path

from stock_strategy_shared.split_reconciliation import split_ratio_from_prices

TARGETS = [
    ("ACER","2017-09-21",0.09662), ("AZN","1998-04-08",0.33333),
    ("ETELY","2007-09-04",0.5), ("NCRI","2003-06-16",1.9),
    ("DAYR","1998-03-18",2.0), ("GOLLQ","2017-11-22",2.0),
    ("MTL","2008-05-20",0.5), ("MTL","2016-01-12",3.0),
    ("NEOM","2014-05-29",0.06667), ("ONSM","2003-06-24",0.16667),
    ("PRPO","2017-06-06",0.03333), ("PRTK","2009-02-06",0.2),
    ("PTIX","2016-07-27",0.00006), ("SQNS","2019-11-29",0.4),
]

def sha256(path: Path) -> str:
    h=hashlib.sha256();
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def relerr(a,b):
    return abs(float(a)-float(b))/max(abs(float(a)),abs(float(b)),1e-15)

def main() -> int:
    root=Path(os.environ.get('BACKTESTER_LAB_ROOT','.')).resolve()
    out=Path(os.environ.get('BACKTESTER_SPLIT_TRIAGE_OUTPUT','backtester-results/price-domain-split-triage.json')).resolve()
    out.parent.mkdir(parents=True,exist_ok=True)
    with (root/'PIT input data'/'MANIFEST.csv').open(newline='',encoding='utf-8') as f:
        manifest={r['file']:r for r in csv.DictReader(f)}
    years=sorted({int(s[:4]) for _,s,_ in TARGETS})
    wanted={t for t,_,_ in TARGETS}
    rows={t:[] for t in wanted}
    observed={}
    for year in years:
        p=root/'sharadar'/f'SHARADAR_SEP_{year}.csv.gz'
        expected=manifest[f'SEP_{year}_PIT_ONLY.csv.gz']['source_sha256']
        got=sha256(p)
        if got!=expected: raise RuntimeError(f'SEP {year} hash mismatch')
        observed[str(p.relative_to(root))]=got
        with gzip.open(p,'rt',encoding='utf-8',newline='') as f:
            for r in csv.DictReader(f):
                t=str(r.get('ticker') or '')
                if t in wanted:
                    rows[t].append({
                        'date':str(r['date'])[:10],
                        'close':None if not r.get('close') else float(r['close']),
                        'closeunadj':None if not r.get('closeunadj') else float(r['closeunadj']),
                    })
    for t in rows: rows[t].sort(key=lambda r:r['date'])
    results=[]
    for ticker,session,stated in TARGETS:
        series=rows[ticker]
        trans=[]
        for prev,cur in zip(series,series[1:]):
            d=split_ratio_from_prices(prev['close'],prev['closeunadj'],cur['close'],cur['closeunadj'])
            if d is None: continue
            days=abs((date.fromisoformat(cur['date'])-date.fromisoformat(session)).days)
            if days<=20:
                trans.append({
                    'previous_session':prev['date'],'session':cur['date'],'calendar_distance_days':days,
                    'derived_ratio':d,'direct_relative_error':relerr(d,stated),
                    'inverse_relative_error':relerr(d,1.0/stated),
                    'previous_close':prev['close'],'previous_closeunadj':prev['closeunadj'],
                    'close':cur['close'],'closeunadj':cur['closeunadj'],
                })
        exact=next((r for r in trans if r['session']==session),None)
        best_direct=min(trans,key=lambda r:r['direct_relative_error']) if trans else None
        best_inverse=min(trans,key=lambda r:r['inverse_relative_error']) if trans else None
        results.append({
            'ticker':ticker,'action_session':session,'stated_ratio':stated,
            'action_date_transition':exact,'best_direct_nearby':best_direct,
            'best_inverse_nearby':best_inverse,'nearby_transitions':trans,
        })
    payload={
        'schema':'backtester.price-domain-split-triage/1','status':'PASS',
        'strategy_main_sha':os.environ.get('BACKTESTER_MAIN_SHA'),
        'backtester_sha':os.environ.get('BACKTESTER_BRANCH_SHA'),
        'window_calendar_days':20,'target_count':len(TARGETS),
        'source_hashes':observed,'results':results,
    }
    out.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({'status':'PASS','target_count':len(results),'summary':[
        {'ticker':r['ticker'],'action_session':r['action_session'],
         'best_direct':None if r['best_direct_nearby'] is None else {k:r['best_direct_nearby'][k] for k in ('session','derived_ratio','direct_relative_error')},
         'best_inverse':None if r['best_inverse_nearby'] is None else {k:r['best_inverse_nearby'][k] for k in ('session','derived_ratio','inverse_relative_error')}}
        for r in results]},indent=2,sort_keys=True),flush=True)
    return 0

if __name__=='__main__': raise SystemExit(main())
