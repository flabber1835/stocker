from pathlib import Path
import pandas as pd, numpy as np, glob, time
P=Path('/mnt/data/selective_firewall/position_replay/fixed30_position_panel.csv.gz')
OUT=Path('/mnt/data/selective_firewall/position_panel_enriched.csv.gz')
panel=pd.read_csv(P,parse_dates=['date'])
frames=[]
for y,g in panel.groupby(panel.date.dt.year,sort=True):
    t=time.time(); tickers=set(g.ticker.astype(str))
    fs=[f for f in glob.glob(f'/mnt/data/sep/SHARADAR_SEP_{y}.csv*.gz') if '(' not in Path(f).name]
    if len(fs)!=1: raise RuntimeError((y,fs))
    px=pd.read_csv(fs[0],usecols=['ticker','date','closeadj'],low_memory=False)
    px=px[px.ticker.astype(str).isin(tickers)].copy(); px['date']=pd.to_datetime(px.date)
    px=px.drop_duplicates(['ticker','date'],keep='last')
    m=g.merge(px,on=['ticker','date'],how='left',validate='one_to_one')
    if m.closeadj.isna().any():
        print('missing',y,int(m.closeadj.isna().sum()))
    frames.append(m)
    print('year',y,'panel',len(g),'price',len(px),'sec',round(time.time()-t,2),flush=True)
out=pd.concat(frames,ignore_index=True).sort_values(['date','episode'])
out.to_csv(OUT,index=False,compression='gzip')
print('wrote',OUT,len(out),'missing',int(out.closeadj.isna().sum()))
