#!/usr/bin/env python3
"""Refine observation-only market-risk controller plateaus.

RESEARCH / NOT CERTIFIED.

Uses the V2 Candidate A state-preserving adapter. Plateau centers are selected
geometrically from viable stable regions, not from the highest-CAGR point.
"""
from __future__ import annotations
import argparse, itertools, json
from pathlib import Path
import numpy as np
import pandas as pd
from backtester import research_champion_market_risk_screen_v2 as base

SCREEN_V2_RUN=34010839114
SCREEN_V2_ARTIFACT=9982400915
VIX_CUTOFF_SHA256='9bf13a7d758cd0727e3fb68d50a32715d6201ed7f0cd220841ecfe2a4901ee4b'


def grids():
 for rv,ratio,healthy in itertools.product((0.20,0.22,0.24,0.26,0.28),(1.05,1.10,1.15,1.20),(0.17,0.18,0.19,0.20,0.21)):
  yield 'spy_vol',dict(rv20_stress=rv,ratio_stress=ratio,rv20_healthy=healthy,ratio_healthy=1.0)
 for pct,z,healthy in itertools.product((0.85,0.875,0.90,0.925,0.95),(0.50,0.75,1.00,1.25,1.50),(0.50,0.55,0.60,0.65)):
  yield 'vix_percentile',dict(pct_stress=pct,z_stress=z,pct_healthy=healthy)
 for r20,dd,vix,z,vhealthy in itertools.product((-0.05,-0.08),(-0.12,-0.14,-0.16,-0.18),(20.0,22.5,25.0),(0.5,1.0),(20.0,22.0,24.0)):
  yield 'spy_vix',dict(r20_stress=r20,dd_stress=dd,vix_stress=vix,z_stress=z,vix_healthy=vhealthy)

def neighbor_stats(g):
 rec=g.to_dict('records'); parsed=[json.loads(r['params']) for r in rec]; keys=sorted(parsed[0]); axes={k:sorted({float(p[k]) for p in parsed}) for k in keys}; idx={tuple(float(p[k]) for k in keys):i for i,p in enumerate(parsed)}; out=[]
 for i,p in enumerate(parsed):
  ns=[]
  for k in keys:
   vals=axes[k]; pos=vals.index(float(p[k]))
   for qpos in (pos-1,pos+1):
    if 0<=qpos<len(vals):
     q=dict(p); q[k]=vals[qpos]; j=idx.get(tuple(float(q[x]) for x in keys))
     if j is not None:ns.append(rec[j])
  cg=[rec[i]['proxy_cagr']]+[x['proxy_cagr'] for x in ns]; dd=[rec[i]['proxy_max_dd']]+[x['proxy_max_dd'] for x in ns]
  out.append({'neighbor_count':len(ns),'neighbor_cagr_span':max(cg)-min(cg),'neighbor_dd_span':max(dd)-min(dd),'neighbor_cagr_median':float(np.median(cg)),'neighbor_dd_median':float(np.median(dd)),'plateau_stable':bool(len(ns)>=3 and max(cg)-min(cg)<=0.010 and max(dd)-min(dd)<=0.020)})
 return pd.DataFrame(out,index=g.index)

def geometric_center(pool):
 parsed=[json.loads(x) for x in pool.params]; keys=sorted(parsed[0]); axes={k:sorted({float(p[k]) for p in parsed}) for k in keys}; meds={k:float(np.median([p[k] for p in parsed])) for k in keys}
 scores=[]
 for p in parsed:
  dist=0.
  for k in keys:
   vals=axes[k]; span=max(vals)-min(vals)
   if span>0:dist+=abs(float(p[k])-meds[k])/span
  scores.append(dist)
 q=pool.copy(); q['geometric_center_distance']=scores
 return q.sort_values(['geometric_center_distance','neighbor_cagr_span','neighbor_dd_span','neighbor_cagr_median'],ascending=[True,True,True,False]).iloc[0]

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--baseline-daily',type=Path,required=True); ap.add_argument('--vix-csv',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
 if base.sha256(a.vix_csv)!=VIX_CUTOFF_SHA256:raise RuntimeError('pinned VIX cutoff hash mismatch')
 frame=base.enrich(pd.read_csv(a.baseline_daily),base.load_vix(a.vix_csv)); cur=base.current_proxy(frame); cura=frame.research_allocation.astype(float).to_numpy(); rows=[]
 for n,(fam,p) in enumerate(grids()):
  sim,state=base.simulate(frame,fam,p); m=base.metrics(sim.proxy_nav,sim.date); aa=sim.allocation.astype(float).to_numpy(); changed=np.flatnonzero(abs(aa-cura)>1e-12); eps,avg,mx=base.episode_stats(aa)
  rows.append({'candidate_id':f'v2r-{fam}-{n:04d}','family':fam,'params':json.dumps(p,sort_keys=True,separators=(',',':')),**m,**state,'reduced_sessions':int((aa<1-1e-12).sum()),'defensive_episodes':eps,'mean_defensive_duration':avg,'max_defensive_duration':mx,'allocation_sessions_changed_vs_current':int(len(changed)),'first_allocation_divergence':str(frame.iloc[int(changed[0])].date.date()) if len(changed) else ''})
 out=pd.DataFrame(rows); out['proxy_cagr_gap_vs_current']=out.proxy_cagr-cur['proxy_cagr']; out['proxy_dd_gap_vs_current']=out.proxy_max_dd-cur['proxy_max_dd']; enriched=[]
 for fam,g in out.groupby('family',sort=False):
  ns=neighbor_stats(g); q=g.copy()
  for c in ns.columns:q[c]=ns[c]
  enriched.append(q)
 out=pd.concat(enriched).sort_index(); out.to_csv(a.output/'refined-grid-v2.csv',index=False)
 summary=[]; picks=[]
 for fam,g in out.groupby('family'):
  stable=g[g.plateau_stable].copy(); viable=stable[(stable.proxy_cagr_gap_vs_current>=-0.015)&(stable.proxy_dd_gap_vs_current<=0.010)].copy(); pool=viable if len(viable) else stable if len(stable) else g
  pick=geometric_center(pool); picks.append(pick.to_dict()); summary.append({'family':fam,'grid_points':len(g),'stable_points':len(stable),'viable_stable_points':len(viable),'stable_cagr_min':stable.proxy_cagr.min() if len(stable) else np.nan,'stable_cagr_max':stable.proxy_cagr.max() if len(stable) else np.nan,'stable_dd_best':stable.proxy_max_dd.max() if len(stable) else np.nan,'stable_dd_worst':stable.proxy_max_dd.min() if len(stable) else np.nan,'selected_candidate':pick.candidate_id,'selected_params':pick.params,'selected_proxy_cagr':pick.proxy_cagr,'selected_proxy_max_dd':pick.proxy_max_dd,'selected_neighbor_cagr_span':pick.neighbor_cagr_span,'selected_neighbor_dd_span':pick.neighbor_dd_span})
 pd.DataFrame(summary).to_csv(a.output/'refined-family-summary-v2.csv',index=False); pd.DataFrame(picks).to_csv(a.output/'full-replay-shortlist-v2.csv',index=False)
 manifest={'status':'RESEARCH / NOT CERTIFIED','phase':'OBSERVATION_ONLY_REFINED_PLATEAU_V2','screen_v2_run':SCREEN_V2_RUN,'screen_v2_artifact':SCREEN_V2_ARTIFACT,'baseline_daily_sha256':base.sha256(a.baseline_daily),'vix_cutoff_sha256':base.sha256(a.vix_csv),'grid_points':len(out),'plateau_rule':'immediate-neighbor CAGR span <=1.0pp and DD span <=2.0pp with >=3 neighbors','viability_rule':'CAGR no more than 1.5pp below current proxy and DD no more than 1.0pp worse','selection_rule':'geometric center of viable stable region; tie-break by local spans and neighbor-median CAGR; no single-point CAGR maximization'}
 (a.output/'manifest-v2.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n'); print(json.dumps(manifest,indent=2)); print(pd.DataFrame(summary).to_string(index=False)); return 0
if __name__=='__main__':raise SystemExit(main())
