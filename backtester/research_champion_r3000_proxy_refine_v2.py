#!/usr/bin/env python3
"""Refine the IWV/Russell-3000 volatility observation plateau.

RESEARCH / NOT CERTIFIED. The V2 state machine is unchanged.
"""
from __future__ import annotations
import argparse, itertools, json
from pathlib import Path
import numpy as np
import pandas as pd
from research_champion_market_risk_screen_v2 import current_proxy, episode_stats, metrics, simulate
from research_champion_r3000_proxy_screen_v2 import enrich_iwv, load_iwv, sha256

RV=(0.18,0.20,0.22,0.24,0.26,0.28)
RATIO=(1.05,1.10,1.15,1.20,1.25)
HEALTHY=(0.16,0.17,0.18,0.19,0.20,0.21)


def grid_distance(a,b):
 return sum(abs(a[k]-b[k]) for k in ('rv20_stress','ratio_stress','rv20_healthy'))

def immediate_neighbors(rows, p):
 vals={'rv20_stress':RV,'ratio_stress':RATIO,'rv20_healthy':HEALTHY}
 out=[]
 for k,seq in vals.items():
  i=seq.index(p[k])
  for j in (i-1,i+1):
   if 0<=j<len(seq):
    q=dict(p); q[k]=seq[j]
    key=json.dumps(q,sort_keys=True,separators=(',',':'))
    if key in rows: out.append(rows[key])
 return out

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--baseline-daily',type=Path,required=True); ap.add_argument('--iwv-csv',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
 frame=enrich_iwv(pd.read_csv(a.baseline_daily),load_iwv(a.iwv_csv)); cur=current_proxy(frame); cura=frame.research_allocation.astype(float).to_numpy(); records=[]
 for n,(rv,ratio,healthy) in enumerate(itertools.product(RV,RATIO,HEALTHY)):
  p={'rv20_stress':rv,'ratio_stress':ratio,'rv20_healthy':healthy,'ratio_healthy':1.0}; sim,state=simulate(frame,'spy_vol',p); m=metrics(sim.proxy_nav,sim.date); aa=sim.allocation.astype(float).to_numpy(); changed=np.flatnonzero(abs(aa-cura)>1e-12); eps,avg,mx=episode_stats(aa)
  records.append({'candidate_id':f'v2r-r3000-vol-{n:04d}','family':'r3000_vol','params':json.dumps(p,sort_keys=True,separators=(',',':')),**m,**state,'reduced_sessions':int((aa<1-1e-12).sum()),'defensive_episodes':eps,'mean_defensive_duration':avg,'max_defensive_duration':mx,'allocation_sessions_changed_vs_current':int(len(changed)),'first_allocation_divergence':str(frame.iloc[int(changed[0])].date.date()) if len(changed) else ''})
 out=pd.DataFrame(records); out['proxy_cagr_gap_vs_current']=out.proxy_cagr-cur['proxy_cagr']; out['proxy_dd_gap_vs_current']=out.proxy_max_dd-cur['proxy_max_dd']
 by={r.params:r for r in out.itertuples(index=False)}; stats=[]
 for r in out.itertuples(index=False):
  p=json.loads(r.params); ns=immediate_neighbors(by,p); cg=[r.proxy_cagr]+[x.proxy_cagr for x in ns]; dd=[r.proxy_max_dd]+[x.proxy_max_dd for x in ns]; cspan=max(cg)-min(cg); dspan=max(dd)-min(dd); stable=len(ns)>=3 and cspan<=0.010 and dspan<=0.020
  stats.append((len(ns),cspan,dspan,float(np.median(cg)),float(np.median(dd)),stable))
 out[['neighbor_count','neighbor_cagr_span','neighbor_dd_span','neighbor_cagr_median','neighbor_dd_median','plateau_stable']]=stats
 out['viable']= (out.proxy_cagr_gap_vs_current>=-0.015) & (out.proxy_dd_gap_vs_current>=-0.010)
 stable=out[out.plateau_stable & out.viable].copy()
 if stable.empty: raise RuntimeError('no viable stable R3000 volatility plateau')
 # Geometric center in normalized grid-index space, not performance space.
 def idxdist(row):
  p=json.loads(row.params); coords=np.array([RV.index(p['rv20_stress'])/(len(RV)-1),RATIO.index(p['ratio_stress'])/(len(RATIO)-1),HEALTHY.index(p['rv20_healthy'])/(len(HEALTHY)-1)],float); return float(np.linalg.norm(coords-0.5))
 stable['geometric_center_distance']=stable.apply(idxdist,axis=1)
 sel=stable.sort_values(['geometric_center_distance','neighbor_cagr_span','neighbor_dd_span','neighbor_cagr_median'],ascending=[True,True,True,False]).iloc[0]
 out.to_csv(a.output/'refined-grid-r3000-v2.csv',index=False); stable.sort_values('proxy_cagr',ascending=False).to_csv(a.output/'viable-stable-r3000-v2.csv',index=False)
 pd.DataFrame([sel]).to_csv(a.output/'full-replay-shortlist-r3000-v2.csv',index=False)
 summary={'status':'RESEARCH / NOT CERTIFIED','phase':'R3000_VOL_REFINED_PLATEAU_V2','grid_points':len(out),'stable_points':int(out.plateau_stable.sum()),'viable_stable_points':len(stable),'current_proxy':cur,'selected_candidate':sel.candidate_id,'selected_params':sel.params,'selected_proxy_cagr':float(sel.proxy_cagr),'selected_proxy_max_dd':float(sel.proxy_max_dd),'selected_proxy_sharpe':float(sel.proxy_sharpe),'selected_neighbor_cagr_span':float(sel.neighbor_cagr_span),'selected_neighbor_dd_span':float(sel.neighbor_dd_span),'baseline_daily_sha256':sha256(a.baseline_daily),'iwv_cutoff_sha256':sha256(a.iwv_csv),'selection_rule':'geometric center of viable stable region; tie-break local spans and neighbor median CAGR'}
 (a.output/'manifest-r3000-refine-v2.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n'); print(json.dumps(summary,indent=2,sort_keys=True)); print(pd.DataFrame([sel]).to_string(index=False))
if __name__=='__main__': main()
