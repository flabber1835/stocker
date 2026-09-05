#!/usr/bin/env python3
"""Freeze the Cboe VIX daily-close history used by targeted-hedge diagnostics."""
from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path
import pandas as pd

START = pd.Timestamp('1998-01-01')
END = pd.Timestamp('2026-07-31')
SOURCE = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for ch in iter(lambda:f.read(1024*1024),b''): h.update(ch)
    return h.hexdigest()


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--raw',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    raw=pd.read_csv(a.raw)
    raw.columns=[str(c).strip().upper() for c in raw.columns]
    if 'DATE' not in raw.columns or 'CLOSE' not in raw.columns:
        raise RuntimeError(f'unexpected Cboe VIX schema: {raw.columns.tolist()}')
    raw['DATE']=pd.to_datetime(raw['DATE'],errors='raise')
    raw['CLOSE']=pd.to_numeric(raw['CLOSE'],errors='raise')
    x=raw[(raw.DATE>=START)&(raw.DATE<=END)][['DATE','CLOSE']].copy()
    x=x.sort_values('DATE',kind='mergesort').drop_duplicates('DATE',keep='last')
    if len(x)<7000:
        raise RuntimeError(f'insufficient VIX history: {len(x)} rows')
    if x.DATE.min()>pd.Timestamp('1998-01-02') or x.DATE.max()!=END:
        raise RuntimeError(f'VIX coverage mismatch {x.DATE.min()} -> {x.DATE.max()}')
    if (x.CLOSE<=0).any():
        raise RuntimeError('non-positive VIX close')
    out=a.output/'VIX_1998_2026-07-31.csv'
    x.to_csv(out,index=False,date_format='%Y-%m-%d')
    report={
        'status':'PASS',
        'zero_budget_diagnostic':True,
        'experiment_budget_consumed':False,
        'e8_spent':False,
        'source_url':SOURCE,
        'source_description':'Cboe VIX Index daily historical close data',
        'start':str(x.DATE.min().date()),
        'end':str(x.DATE.max().date()),
        'rows':int(len(x)),
        'raw_sha256':sha256(a.raw),
        'frozen_sha256':sha256(out),
    }
    (a.output/'vix_authority.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    files=[out,a.output/'vix_authority.json']
    (a.output/'VIX_SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in files))
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
