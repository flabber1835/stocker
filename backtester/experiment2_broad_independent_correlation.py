#!/usr/bin/env python3
"""Experiment 2: broad universe with independent-security Wealth Core and correlation-peer Sentinel.

Purpose: isolate whether the R1000 simplifications themselves destroy alpha.
The broad eligibility/ranking/liquidity tape remains the same as the broad full-PIT research estimate.
Only issuer-family blocking is disabled and sector contagion is replaced by causal residual-correlation peers.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pandas as pd

from backtester import run_research_ldrc_corrected_warmup_cash as corrected
from backtester import run_r1000_correlation_peers as r1000

LABEL='EXPERIMENT_2_BROAD_INDEPENDENT_CORRELATION'


def replace_regex(text, pattern, replacement, label):
    out,count=re.subn(pattern,replacement,text,count=1,flags=re.S)
    if count!=1: raise RuntimeError(f'{label}: expected one match, got {count}')
    return out


def transformed_source(output: Path) -> str:
    text=corrected.transformed_source('fullpit',output)
    text=corrected.old.replace_once(
        text,
        'import zipfile, glob, math, json, hashlib, time, gc, os, importlib.util',
        'import zipfile, glob, math, json, hashlib, time, gc, os, importlib.util',
        'imports unchanged')
    # Remove CIK/SIC authority from economically-active issuer/sector decisions.
    init_pattern=(r"    pit_model=None\n" r"    if PIT_MODE:.*?" r"    actions,split_dates=load_actions\(\); spy,bil=load_funds\(\); book=Book\(\); native=Native\(\)")
    init_replacement="""    def sector_key(tid, ds):
        return f'SID:{sid[tid]}'
    def issuer_key(tid, ds):
        return f'SID:{sid[tid]}'
    actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()"""
    text=replace_regex(text,init_pattern,init_replacement,'remove SEC metadata authority')

    # Install the exact correlation-peer definition used by the R1000 baseline.
    helper_marker='def finite(x): return x is not None and np.isfinite(x)'
    helper=r1000.transformed_source.__doc__  # sentinel only to keep import live
    del helper
    peer_code="""def finite(x): return x is not None and np.isfinite(x)

PEER_LOOKBACK=252
PEER_MIN_OBS=120
PEER_COUNT=3
PEER_CORR_FLOOR=.145
PEER_STATS={'breadth_sessions':0,'holding_observations':0,'insufficient_residual_histories':0,'pair_correlations':0,'accepted_peer_edges':0,'neighborhood_size_sum':0}

def _peer_corr(left,right):
    common=sorted(set(left).intersection(right))
    if len(common)<PEER_MIN_OBS: return None
    a=np.array([left[k] for k in common],float); b=np.array([right[k] for k in common],float)
    am=float(a.mean()); bm=float(b.mean()); da=a-am; db=b-bm
    den=float(np.sqrt(np.dot(da,da)*np.dot(db,db)))
    if not np.isfinite(den) or den<=0: return None
    out=float(np.dot(da,db)/den)
    return out if np.isfinite(out) else None

def _prior_residuals(tid,gday,close_ring,spy,shadow_dates):
    start=max(1,gday-PEER_LOOKBACK); end=gday-1
    keys=[]; asset=[]; market=[]
    for j in range(start,end+1):
        if j>=len(shadow_dates): break
        p0=float(close_ring[(j-1)%len(close_ring),tid]); p1=float(close_ring[j%len(close_ring),tid])
        date=shadow_dates[j]; mv=spy.loc[date,'ret'] if date in spy.index else np.nan
        if finite(p0) and p0>0 and finite(p1) and p1>0 and finite(mv):
            keys.append(j); asset.append(p1/p0-1.); market.append(float(mv))
    if len(keys)<PEER_MIN_OBS:
        PEER_STATS['insufficient_residual_histories']+=1; return {}
    a=np.array(asset,float); m=np.array(market,float); am=float(a.mean()); mm=float(m.mean()); dm=m-mm
    den=float(np.dot(dm,dm))
    if not np.isfinite(den) or den<=0:
        PEER_STATS['insufficient_residual_histories']+=1; return {}
    beta=float(np.dot(a-am,dm)/den)
    return {k:float(x-beta*y) for k,x,y in zip(keys,a,m)}

def dynamic_peer_breadth(held,gday,close_ring,spy,shadow_dates):
    if not held: return 0.,0.
    PEER_STATS['breadth_sessions']+=1; PEER_STATS['holding_observations']+=len(held)
    residuals=[_prior_residuals(int(z[0]),gday,close_ring,spy,shadow_dates) for z in held]
    reds=[bool(z[7]) for z in held]; greens=[bool(z[6]) for z in held]; ng=na=0
    for i,z in enumerate(held):
        scores=[]; left=residuals[i]
        if left:
            for j,right in enumerate(residuals):
                if i==j or not right: continue
                c=_peer_corr(left,right); PEER_STATS['pair_correlations']+=1
                if c is not None and c>=PEER_CORR_FLOOR: scores.append((float(c),int(held[j][0]),j))
        scores.sort(key=lambda row:(-row[0],row[1]))
        neighbors=[i]+[row[2] for row in scores[:PEER_COUNT]]
        PEER_STATS['accepted_peer_edges']+=max(len(neighbors)-1,0); PEER_STATS['neighborhood_size_sum']+=len(neighbors)
        stress=sum(int(reds[j]) for j in neighbors)/len(neighbors)
        individual=(finite(z[2]) and z[2]<=-.10) or (finite(z[3]) and z[3]<=-.03)
        amber=individual or (stress>=.50 and not greens[i])
        ng+=int(greens[i]); na+=int(amber)
    return ng/len(held),na/len(held)
"""
    text=corrected.old.replace_once(text,helper_marker,peer_code,'correlation peer helpers')
    text=corrected.old.replace_once(text,'    L=130','    L=260','correlation history ring')
    old_breadth="""            secct=defaultdict(lambda:[0,0])
            for z in held: secct[z[1]][0]+=int(z[7]); secct[z[1]][1]+=1
            ng=na=0
            for z in held:
                stress=secct[z[1]][0]/secct[z[1]][1] if secct[z[1]][1] else 0.
                amber=(finite(z[2]) and z[2]<=-.10) or (finite(z[3]) and z[3]<=-.03) or (stress>=.50 and not z[6])
                ng+=int(z[6]); na+=int(amber)
            green_b=ng/len(held) if held else 0.; dam_b=na/len(held) if held else 0."""
    text=corrected.old.replace_once(text,old_breadth,"            green_b,dam_b=dynamic_peer_breadth(held,gday,close_ring,spy,shadow_dates)",'correlation breadth')
    # Geometry telemetry for attribution.
    old="'control_reason':ctl_reason,'A_reason':a_reason,'B_reason':b_reason,'fast_signal':fastsig,'slow_signal':slowsig})"
    new="'control_reason':ctl_reason,'A_reason':a_reason,'B_reason':b_reason,'fast_signal':fastsig,'slow_signal':slowsig,'eligible_count':int(len(et)),'leadership_population':int(nk),'held_count':int(len(held))})"
    text=corrected.old.replace_once(text,old,new,'geometry telemetry')
    text=corrected.old.replace_once(text,"'candidate_A_episodes':ca.episodes,'candidate_B_episodes':cb.episodes,","'candidate_A_episodes':ca.episodes,'candidate_B_episodes':cb.episodes,'correlation_peer_stats':PEER_STATS,",'peer summary')
    return text


def finalize(output: Path):
    corrected.old.postprocess('fullpit',output)
    corrected.finalize('fullpit',output)
    daily=pd.read_csv(output/'daily.csv.gz',compression='gzip',parse_dates=['date'])
    metrics=[]
    starts={'5':('2021-07-30',5.0),'10':('2016-07-29',10.0),'15':('2011-07-29',15.0),'20':('2006-07-31',20.0),'max':('1998-01-02',None)}
    for w,(start,years) in starts.items():
        for variant,col in [('RESEARCH','research_nav'),('CORE','research_wealth_core_equity'),('SPY','spy_nav')]:
            metrics.append({'window_years':w,'variant':variant,**corrected.old.metric_block(daily,col,start,years)})
    pd.DataFrame(metrics).to_csv(output/'metrics.csv',index=False)
    sp=output/'summary.json'; s=json.loads(sp.read_text()); s['experiment']='experiment2_broad_independent_security_correlation_peers'; s['evidence_label']=LABEL; s['formal_pit_certified']=False; s['domain_changes']={'universe':'unchanged broad full-PIT-estimate eligibility','issuer_family':'disabled; each security independent','sector_contagion':'prior-only residual-correlation peers'}; sp.write_text(json.dumps(s,indent=2,sort_keys=True)+'\n')
    manifest={'schema':'backtester.broad-exp2-independent-correlation/1','status':'PASS','evidence_label':LABEL,'metrics':metrics,'correlation_peer_stats':s.get('correlation_peer_stats')}
    mp=output/'experiment2-manifest.json'; mp.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    files=[output/'daily.csv.gz',output/'metrics.csv',sp,mp]
    (output/'SHA256SUMS.txt').write_text(''.join(f"{corrected.old.sha256(p)}  {p.name}\n" for p in files))
    print(pd.DataFrame(metrics).to_string(index=False),flush=True)


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,required=True); args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    generated=Path('/tmp/experiment2_broad_independent_correlation.py'); generated.write_text(transformed_source(args.output),encoding='utf-8')
    env=dict(os.environ); env['RESEARCH_REPLAY_MODE']='fullpit'; print(f'[RUN] {LABEL}',flush=True)
    subprocess.run([sys.executable,str(generated)],check=True,env=env); finalize(args.output); return 0

if __name__=='__main__': raise SystemExit(main())
