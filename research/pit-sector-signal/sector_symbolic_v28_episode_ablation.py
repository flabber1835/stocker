from __future__ import annotations
import importlib.util,sys,pandas as pd,numpy as np,json
from pathlib import Path
ROOT=Path('/mnt/data');OUT=ROOT/'sector_symbolic_v28_episode_ablation_out';OUT.mkdir(exist_ok=True)
s=importlib.util.spec_from_file_location('core','/mnt/data/sector_peer_core.py');v=importlib.util.module_from_spec(s);sys.modules['core28']=v;s.loader.exec_module(v)
sym=pd.read_csv(ROOT/'sector_symbolic_v5_out/symbolic_days.csv',parse_dates=['date']).set_index('date').reindex(v.base.index);ctrl=sym.symbolic_status.eq('controllable');inev=sym.symbolic_status.eq('inevitable')
market=pd.read_csv(ROOT/'sector_peer_v10_market_only_out/market_res252_0.150.csv',parse_dates=['date']).set_index('date').fast.astype(bool).reindex(v.base.index,fill_value=False)
jac=pd.read_csv(ROOT/'sector_peer_v3_extra_out/jaccard_knn3_252.csv',parse_dates=['date']).set_index('date').fast.astype(bool).reindex(v.base.index,fill_value=False)
best=inev|(ctrl & market & (jac | (sym.min_d.astype(float)<=.75)))
dam=pd.read_csv(ROOT/'sector_peer_v2_strict_out/damaged_breadth.csv',parse_dates=['date']).set_index('date').sec_ff12.reindex(v.base.index)
def metric(x,a=None,b=None):
 if a is not None:x=x.loc[(x.index>=pd.Timestamp(a))&(x.index<=pd.Timestamp(b))]
 yrs=(x.index[-1]-x.index[0]).days/365.2425;c=(x.iloc[-1]/x.iloc[0])**(1/yrs)-1;r=x.pct_change().dropna();return {'cagr':float(c),'sharpe':float(r.mean()/r.std(ddof=1)*np.sqrt(252)),'mdd':float((x/x.cummax()-1).min()),'multiple':float(x.iloc[-1]/x.iloc[0])}
baseout=v.replay(dam,override=best)
base_metrics={'full':metric(baseout.nav),'validation':metric(baseout.nav,'2016-01-04','2026-07-31')}
arr=best.to_numpy(bool);runs=[];i=0
while i<len(arr):
 if not arr[i]:i+=1;continue
 j=i
 while j+1<len(arr) and arr[j+1]:j+=1
 runs.append((i,j));i=j+1
rows=[]
for a,b in runs:
 mask=best.copy();mask.iloc[a:b+1]=False
 out=v.replay(dam,override=mask)
 row={'episode_start':str(best.index[a].date()),'episode_end':str(best.index[b].date()),'sessions':b-a+1,'kind':'inevitable' if inev.iloc[a:b+1].any() else 'controllable'}
 for lab,aa,bb in [('full',None,None),('validation','2016-01-04','2026-07-31')]:
  mm=metric(out.nav,aa,bb);row.update({f'{lab}_{k}':vv for k,vv in mm.items()});row[f'{lab}_cagr_delta_pp']=(mm['cagr']-base_metrics[lab]['cagr'])*100
 rows.append(row)
pd.DataFrame(rows).to_csv(OUT/'episode_ablation.csv',index=False)
Path(OUT/'summary.json').write_text(json.dumps({'baseline':base_metrics,'episodes':rows},indent=2))
print('BASE',json.dumps(base_metrics,indent=2))
print(pd.DataFrame(rows)[['episode_start','episode_end','kind','full_cagr_delta_pp','validation_cagr_delta_pp','full_mdd','validation_mdd']].to_string(index=False))
