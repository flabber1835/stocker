#!/usr/bin/env python3
"""Refine stable classification-independent LDRC regions after coarse screen.

RESEARCH / NOT CERTIFIED. This phase uses the same frozen corrected Champion
path and proxy economics as the coarse screen. Exact economics are reserved for
full-replay finalists.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtester import research_champion_market_risk_screen as base

VIX_CUTOFF_SHA256 = "9bf13a7d758cd0727e3fb68d50a32715d6201ed7f0cd220841ecfe2a4901ee4b"
COARSE_RUN_ID = 34010233044
COARSE_ARTIFACT_ID = 9982228874


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def load_cutoff(path: Path) -> pd.DataFrame:
    if sha256(path) != VIX_CUTOFF_SHA256:
        raise RuntimeError("pinned Cboe VIX cutoff hash mismatch")
    v=pd.read_csv(path)
    if set(v.columns)!={"date","vix"}:
        raise RuntimeError(f"unexpected pinned VIX columns: {list(v.columns)}")
    v['date']=pd.to_datetime(v['date']); v['vix']=pd.to_numeric(v['vix'],errors='raise')
    v=v.sort_values('date').drop_duplicates('date',keep='last').set_index('date')
    v['vix_chg5']=v['vix'].pct_change(5); v['vix_chg20']=v['vix'].pct_change(20)
    roll=v['vix'].rolling(252,min_periods=126)
    v['vix_z252']=(v['vix']-roll.mean())/roll.std(ddof=1)
    v['vix_pct252']=v['vix'].rolling(252,min_periods=126).apply(lambda a:float(np.mean(a<=a[-1])),raw=True)
    return v


def grids():
    for rv,ratio,healthy in itertools.product((0.24,0.26,0.28,0.30),(1.05,1.10,1.15,1.20),(0.18,0.19,0.20,0.21)):
        yield "spy_vol", dict(rv20_stress=rv,ratio_stress=ratio,rv20_healthy=healthy,ratio_healthy=1.0)
    for pct,z,healthy in itertools.product((0.825,0.85,0.875,0.90,0.925),(0.50,0.75,1.00,1.25),(0.55,0.60,0.65)):
        yield "vix_percentile", dict(pct_stress=pct,z_stress=z,pct_healthy=healthy)
    for dd,vix,z,rebound in itertools.product((-0.10,-0.12,-0.14,-0.16),(22.5,25.0,27.5),(0.50,0.75,1.00),(0.08,0.095,0.11)):
        yield "spy_vix", dict(r20_stress=-0.05,dd_stress=dd,vix_stress=vix,z_stress=z,
                              vix_healthy=22.0,rebound=rebound,vix_rebound_chg5=-0.10)


def neighbor_stats(g: pd.DataFrame) -> pd.DataFrame:
    records=g.to_dict('records')
    parsed=[json.loads(r['params']) for r in records]
    axes={k:sorted({float(p[k]) for p in parsed}) for k in sorted(parsed[0])}
    index={tuple(float(p[k]) for k in axes):i for i,p in enumerate(parsed)}
    out=[]; keys=list(axes)
    for i,p in enumerate(parsed):
        neigh=[]
        for k in keys:
            vals=axes[k]; v=float(p[k]); pos=vals.index(v)
            for qpos in (pos-1,pos+1):
                if 0<=qpos<len(vals):
                    q=dict(p); q[k]=vals[qpos]
                    j=index.get(tuple(float(q[x]) for x in keys))
                    if j is not None: neigh.append(records[j])
        cg=[records[i]['proxy_cagr']]+[r['proxy_cagr'] for r in neigh]
        dd=[records[i]['proxy_max_dd']]+[r['proxy_max_dd'] for r in neigh]
        out.append({'neighbor_count':len(neigh),'neighbor_cagr_span':max(cg)-min(cg),
                    'neighbor_dd_span':max(dd)-min(dd),'neighbor_cagr_median':float(np.median(cg)),
                    'neighbor_dd_median':float(np.median(dd)),
                    'plateau_stable':bool(len(neigh)>=3 and max(cg)-min(cg)<=0.0125 and max(dd)-min(dd)<=0.02)})
    return pd.DataFrame(out,index=g.index)


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--baseline-daily',type=Path,required=True)
    ap.add_argument('--vix-cutoff',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    baseline=pd.read_csv(args.baseline_daily)
    frame=base.enrich(baseline,load_cutoff(args.vix_cutoff))
    current,_=base.simulate_current_proxy(frame)
    current_alloc=frame['research_allocation'].astype(float).reset_index(drop=True)
    rows=[]
    for n,(family,params) in enumerate(grids()):
        sim,state=base.simulate(frame,family,params)
        m=base.metrics(sim.proxy_nav,sim.date); alloc=sim.allocation.astype(float)
        changed=np.flatnonzero(np.abs(alloc.to_numpy()-current_alloc.to_numpy())>1e-12)
        eps,avgdur,maxdur=base.episode_stats(alloc)
        rows.append({'candidate_id':f'refine-{family}-{n:04d}','family':family,
                     'params':json.dumps(params,sort_keys=True,separators=(',',':')),
                     **m,**state,'reduced_sessions':int(np.sum(alloc<1-1e-12)),
                     'defensive_episodes':eps,'mean_defensive_duration':avgdur,'max_defensive_duration':maxdur,
                     'allocation_sessions_changed_vs_current':int(len(changed)),
                     'first_allocation_divergence':str(frame.iloc[int(changed[0])].date.date()) if len(changed) else ''})
    result=pd.DataFrame(rows)
    result['proxy_cagr_gap_vs_current']=result.proxy_cagr-current['proxy_cagr']
    result['proxy_dd_gap_vs_current']=result.proxy_max_dd-current['proxy_max_dd']
    enriched=[]
    for family,g in result.groupby('family',sort=False):
        ns=neighbor_stats(g); gg=g.copy()
        for c in ns.columns: gg[c]=ns[c]
        enriched.append(gg)
    result=pd.concat(enriched).sort_index(); result.to_csv(args.output/'refined-grid.csv',index=False)

    choices=[]; family_summary=[]
    for family,g in result.groupby('family'):
        stable=g[g.plateau_stable].copy()
        viable=stable[(stable.proxy_cagr_gap_vs_current>=-0.025)&(stable.proxy_dd_gap_vs_current<=0.025)].copy()
        pool=viable if not viable.empty else stable if not stable.empty else g.copy()
        pool['plateau_score']=pool.neighbor_cagr_median-0.35*np.maximum(0.,-pool.neighbor_dd_median-0.24)-pool.neighbor_cagr_span
        pick=pool.sort_values(['plateau_score','neighbor_cagr_span','neighbor_dd_span'],ascending=[False,True,True]).iloc[0]
        choices.append(pick.to_dict())
        family_summary.append({'family':family,'grid_points':int(len(g)),'stable_points':int(g.plateau_stable.sum()),
                               'viable_stable_points':int(len(viable)),'cagr_median':float(g.proxy_cagr.median()),
                               'cagr_max':float(g.proxy_cagr.max()),'dd_median':float(g.proxy_max_dd.median()),
                               'selected_candidate':pick.candidate_id})
    pd.DataFrame(family_summary).to_csv(args.output/'refined-family-summary.csv',index=False)
    pd.DataFrame(choices).to_csv(args.output/'full-replay-shortlist.csv',index=False)
    manifest={'status':'RESEARCH / NOT CERTIFIED','phase':'REFINED_PLATEAU_SCREEN',
              'coarse_run_id':COARSE_RUN_ID,'coarse_artifact_id':COARSE_ARTIFACT_ID,
              'vix_cutoff_sha256':VIX_CUTOFF_SHA256,'baseline_daily_sha256':base.sha256(args.baseline_daily),
              'current_proxy_metrics':current,'grid_points':int(len(result)),
              'plateau_rule':'immediate-grid-neighbor CAGR span <=1.25pp and DD span <=2pp with >=3 neighbors',
              'selection_rule':'choose stable plateau center using neighbor-median economics and local span; exact replay required'}
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    lines=['# Market-risk controller refined plateau screen','','**RESEARCH / NOT CERTIFIED**','',
           'Refinement is limited to the three families that survived the coarse screen: SPY realized volatility, VIX percentile/z-score, and combined SPY+VIX.','',
           '| Family | Points | Stable | Viable stable | Max proxy CAGR | Median proxy DD | Selected plateau center |',
           '|---|---:|---:|---:|---:|---:|---|']
    for r in family_summary:
        lines.append(f"| {r['family']} | {r['grid_points']} | {r['stable_points']} | {r['viable_stable_points']} | {r['cagr_max']:.2%} | {r['dd_median']:.2%} | {r['selected_candidate']} |")
    (args.output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    sums=[p for p in args.output.iterdir() if p.is_file() and p.name!='SHA256SUMS.txt']
    (args.output/'SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in sorted(sums)))
    print(json.dumps(manifest,indent=2,sort_keys=True)); print(pd.DataFrame(family_summary).to_string(index=False))
    return 0

if __name__=='__main__': raise SystemExit(main())
