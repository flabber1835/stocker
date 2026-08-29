#!/usr/bin/env python3
from pathlib import Path
import json, zipfile
import pandas as pd

ROOT=Path('.')
EVENTS=[('ICIX','1998-06-16'),('SEM2','2003-12-23')]
out={}
# tickers
zp=ROOT/'sharadar'/'SHARADAR_TICKERS.zip'
with zipfile.ZipFile(zp) as z:
    names=z.namelist()
    csvname=next(n for n in names if n.lower().endswith('.csv'))
    with z.open(csvname) as f:
        tf=pd.read_csv(f, low_memory=False)
for ticker,session in EVENTS:
    rec={}
    rows=tf[tf['ticker'].astype(str).eq(ticker)]
    rec['tickers_rows']=rows.fillna('').to_dict('records')
    year=int(session[:4])
    sf=pd.read_csv(ROOT/'sharadar'/f'SHARADAR_SEP_{year}.csv.gz', compression='gzip', low_memory=False)
    sf['ticker']=sf['ticker'].astype(str); sf['date']=sf['date'].astype(str).str[:10]
    sr=sf[(sf.ticker.eq(ticker)) & (sf.date<=session)].sort_values('date').tail(3)
    rec['sep_rows']=sr.fillna('').to_dict('records')
    out[f'{ticker}|{session}']=rec
# actions
act=pd.read_csv(ROOT/'PIT input data'/'ACTIONS_PIT_ONLY.csv.gz', compression='gzip', low_memory=False)
act['ticker']=act['ticker'].astype(str); act['date']=act['date'].astype(str).str[:10]
for ticker,session in EVENTS:
    out[f'{ticker}|{session}']['action_rows']=act[(act.ticker.eq(ticker)) & (act.date.eq(session))].fillna('').to_dict('records')
print(json.dumps(out, indent=2, default=str))
