#!/usr/bin/env python3
from __future__ import annotations

import json, os, zipfile
from pathlib import Path
import pandas as pd

SID='123177'

def main():
    root=Path(os.environ.get('BACKTESTER_LAB_ROOT','.')).resolve()
    out=Path(os.environ.get('BACKTESTER_PRTK_IDENTITY_OUTPUT','backtester-results/prtk-identity-split-boundary.json')).resolve()
    out.parent.mkdir(parents=True,exist_ok=True)
    zpath=root/'sharadar/SHARADAR_TICKERS.zip'
    with zipfile.ZipFile(zpath) as zf:
        member=[n for n in zf.namelist() if n.lower().endswith('.csv')][0]
        with zf.open(member) as f:
            t=pd.read_csv(f,low_memory=False)
    p=t[t['permaticker'].astype(str).str.replace('.0','',regex=False)==SID].copy()
    cols=[c for c in ['table','permaticker','ticker','name','firstpricedate','lastpricedate','firstquarter','lastquarter','isdelisted','exchange'] if c in p.columns]
    ticker_rows=p[cols].where(pd.notna(p[cols]),None).to_dict(orient='records')
    aliases=sorted({str(x) for x in p['ticker'].dropna()})

    sep=pd.read_csv(root/'sharadar/SHARADAR_SEP_2009.csv.gz',compression='gzip',low_memory=False)
    sep['date']=sep['date'].astype(str).str[:10]
    x=sep[(sep['ticker'].astype(str).isin(aliases)) & (sep['date']>='2009-01-20') & (sep['date']<='2009-02-12')].copy()
    keep=[c for c in ['ticker','date','open','close','closeunadj','volume'] if c in x.columns]
    x=x[keep].sort_values(['date','ticker'],kind='mergesort')
    sep_rows=x.where(pd.notna(x),None).to_dict(orient='records')

    actions=pd.read_csv(root/'PIT input data/ACTIONS_PIT_ONLY.csv.gz',compression='gzip',low_memory=False)
    actions['date']=actions['date'].astype(str).str[:10]
    a=actions[(actions['ticker'].astype(str).isin(aliases)) & (actions['date']>='2009-01-20') & (actions['date']<='2009-02-12')]
    acols=[c for c in ['ticker','date','action','value'] if c in a.columns]
    action_rows=a[acols].where(pd.notna(a[acols]),None).to_dict(orient='records')
    payload={'schema':'backtester.prtk-identity-boundary/1','security_id':SID,'aliases':aliases,'ticker_rows':ticker_rows,'sep_rows':sep_rows,'actions':action_rows}
    out.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
    print(json.dumps(payload,indent=2,sort_keys=True))
    return 0

if __name__=='__main__': raise SystemExit(main())
