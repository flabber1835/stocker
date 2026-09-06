#!/usr/bin/env python3
"""Observation-only market-risk controller screen for the Research Champion.

RESEARCH / NOT CERTIFIED.

V2 preserves Candidate A's state machine: episode creation, persistence streak,
SPY rebound route, cross-surface recovery route, latch/clear behavior, 55% cap,
and one-session target timing. Only the classification-derived leadership
observations are replaced by classification-independent market observations.
Proxy NAV uses zero defensive-cash return for coarse screening only.
"""
from __future__ import annotations
import argparse, hashlib, itertools, json, math
from pathlib import Path
import numpy as np
import pandas as pd

LDRC_REC=8; LDRC_V=0.11; LDRC_DD=-0.10; LDRC_CEIL=0.55; COST=0.001
MEASUREMENT_START=pd.Timestamp('2006-07-31'); MEASUREMENT_END=pd.Timestamp('2026-07-31')
BASELINE_RUN_ID=34007704385; BASELINE_ARTIFACT_ID=9981966560


def sha256(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
 return h.hexdigest()

def finite(x): return x is not None and np.isfinite(x)

def load_vix(path:Path)->pd.DataFrame:
 raw=pd.read_csv(path); names={str(c).strip().upper():c for c in raw.columns}
 dc=names.get('DATE') or names.get('OBSERVATION_DATE'); vc=names.get('CLOSE') or names.get('VIXCLS') or names.get('VIX')
 if dc is None or vc is None: raise RuntimeError(f'unsupported VIX columns {list(raw.columns)}')
 v=raw[[dc,vc]].copy(); v.columns=['date','vix']; v.date=pd.to_datetime(v.date,errors='coerce'); v.vix=pd.to_numeric(v.vix,errors='coerce')
 v=v.dropna().drop_duplicates('date',keep='last').sort_values('date').set_index('date')
 v['vix_chg5']=v.vix.pct_change(5); v['vix_chg20']=v.vix.pct_change(20)
 roll=v.vix.rolling(252,min_periods=126); v['vix_z252']=(v.vix-roll.mean())/roll.std(ddof=1)
 v['vix_pct252']=v.vix.rolling(252,min_periods=126).apply(lambda a:float(np.mean(a<=a[-1])),raw=True)
 return v

def enrich(baseline:pd.DataFrame,vix:pd.DataFrame)->pd.DataFrame:
 d=baseline.copy(); d['date']=pd.to_datetime(d.date); d=d.sort_values('date').reset_index(drop=True)
 if d.iloc[0].date!=MEASUREMENT_START or d.iloc[-1].date!=MEASUREMENT_END: raise RuntimeError('baseline window changed')
 spy=d.spy_nav.astype(float); d['spy_ret']=spy.pct_change(); d['spy_r40']=spy.pct_change(40); d['spy_dd']=spy/spy.cummax()-1
 d['spy_rv20']=d.spy_ret.rolling(20).std(ddof=1)*math.sqrt(252); d['spy_rv40']=d.spy_ret.rolling(40).std(ddof=1)*math.sqrt(252); d['spy_vol_ratio']=d.spy_rv20/d.spy_rv40
 d['wc_r20']=d.research_wealth_core_equity.astype(float).pct_change(20); d=d.join(vix,on='date')
 for c in ['vix','vix_chg5','vix_chg20','vix_z252','vix_pct252']: d[c]=d[c].ffill(limit=1)
 return d

class ObservationOnlyCandidateA:
 def __init__(self,family:str,params:dict):
  self.family=family; self.p=params; self.episode=False; self.latched=False; self.full_streak=0; self.positive_streak=0; self.prev_native=1.; self.prev_desired=1.; self.episodes=0; self.concordance_releases=0; self.entries=0
 def signals(self,r):
  p=self.p; f=self.family
  if f=='spy_price':
   avail=finite(r.spy_r20) and finite(r.spy_r40) and finite(r.spy_dd)
   stress=avail and (r.spy_r20<=p['r20_stress'] or r.spy_dd<=p['dd_stress'])
   full=avail and r.spy_r20>p.get('r20_healthy',0.) and r.spy_r40>p.get('r40_healthy',0.)
   positive=finite(r.spy_r20) and r.spy_r20>0.; recover=positive
  elif f=='spy_vol':
   avail=finite(r.spy_rv20) and finite(r.spy_vol_ratio)
   stress=avail and r.spy_rv20>=p['rv20_stress'] and r.spy_vol_ratio>=p['ratio_stress']
   full=avail and r.spy_rv20<=p['rv20_healthy'] and r.spy_vol_ratio<=p.get('ratio_healthy',1.)
   positive=finite(r.spy_vol_ratio) and r.spy_vol_ratio<1.; recover=avail and r.spy_vol_ratio<=1. and r.spy_rv20<p['rv20_stress']
  elif f=='vix_level_change':
   avail=finite(r.vix) and finite(r.vix_chg5)
   stress=avail and r.vix>=p['vix_stress'] and r.vix_chg5>=p['chg5_stress']
   full=avail and r.vix<=p['vix_healthy'] and r.vix_chg5<=p.get('chg5_healthy',0.)
   positive=finite(r.vix_chg5) and r.vix_chg5<0.; recover=avail and r.vix<p['vix_stress'] and r.vix_chg5<=0.
  elif f=='vix_percentile':
   avail=finite(r.vix_pct252) and finite(r.vix_z252) and finite(r.vix_chg5)
   stress=avail and r.vix_pct252>=p['pct_stress'] and r.vix_z252>=p['z_stress']
   full=avail and r.vix_pct252<=p['pct_healthy']
   positive=finite(r.vix_chg5) and r.vix_chg5<0.; recover=avail and r.vix_pct252<p['pct_stress'] and r.vix_chg5<=0.
  elif f=='spy_vix':
   avail=finite(r.spy_r20) and finite(r.spy_r40) and finite(r.spy_dd) and finite(r.vix) and finite(r.vix_z252) and finite(r.vix_chg5)
   spy_stress=avail and (r.spy_r20<=p['r20_stress'] or r.spy_dd<=p['dd_stress']); vix_stress=avail and (r.vix>=p['vix_stress'] or r.vix_z252>=p['z_stress'])
   stress=spy_stress and vix_stress; full=avail and r.spy_r20>0 and r.spy_r40>0 and r.vix<=p['vix_healthy']
   positive=avail and r.spy_r20>0 and r.vix_chg5<0; recover=avail and r.spy_r20>0 and r.vix<p['vix_stress'] and r.vix_chg5<=0
  else: raise RuntimeError(f)
  return bool(avail),bool(stress),bool(full),bool(positive),bool(recover)
 def step(self,r):
  native=float(r.native_close_target); effective=float(r.effective_native); avail,stress,full_healthy,positive,recovery_confirmed=self.signals(r)
  self.full_streak=self.full_streak+1 if full_healthy else 0; vre=finite(r.spy_r20) and r.spy_r20>LDRC_V; reasons=[]
  if self.prev_native>=1-1e-12 and native<1-1e-12:
   if not self.episode:self.episodes+=1
   self.episode=True; self.positive_streak=0; reasons.append('RECOVERY_EPISODE_START')
  if self.episode:
   self.positive_streak=self.positive_streak+1 if native>0 and positive else 0
  else:self.positive_streak=0
  cleared=self.latched and (self.full_streak>=LDRC_REC or vre)
  if cleared:self.latched=False; reasons.append('DIVERGENCE_CLEAR')
  desired=native
  if self.episode and native>=1-1e-12:
   concordant=(self.positive_streak>=LDRC_REC and finite(r.wc_r20) and r.wc_r20>0 and recovery_confirmed and finite(r.spy_r20) and r.spy_r20>=r.wc_r20)
   if self.full_streak>=LDRC_REC or vre or concordant:
    self.episode=False; desired=1.; self.positive_streak=0
    if concordant and self.full_streak<LDRC_REC and not vre:self.concordance_releases+=1; reasons.append('FULL_RISK_CERTIFIED_CROSS_SURFACE')
    elif self.full_streak>=LDRC_REC:reasons.append('FULL_RISK_CERTIFIED_PERSISTENCE')
    else:reasons.append('FULL_RISK_CERTIFIED_SPY_V_REBOUND')
   else:desired=self.prev_desired; reasons.append('FULL_RISK_HELD')
  entry=(not self.latched and not cleared and avail and finite(r.wc_dd) and native>=1-1e-12 and effective>=1-1e-12 and r.wc_dd<=LDRC_DD and stress)
  if entry:self.latched=True; self.entries+=1; reasons.append('MARKET_RISK_ENTER')
  if self.latched:desired=min(desired,LDRC_CEIL)
  desired=min(native,desired); self.prev_native=native; self.prev_desired=desired
  return float(desired),'|'.join(reasons) if reasons else 'NORMAL'

def simulate(frame,family,params):
 ctl=ObservationOnlyCandidateA(family,params); pending=effective=1.; nav=1.; prev_close=None; prev_eff=1.; rows=[]
 for i,r in enumerate(frame.itertuples(index=False)):
  effective=pending if i else 1.
  if prev_close is not None:
   ce=float(r.research_wealth_core_equity); oe=float(r.research_wealth_core_open_equity)
   if abs(effective-prev_eff)<1e-15: fac=prev_eff*(ce/prev_close)+(1-prev_eff)
   else:
    won=oe/prev_close-1; win=ce/oe-1; fac=(1+prev_eff*won)*(1-COST*abs(effective-prev_eff))*(1+effective*win)
   nav*=fac
  # effective_native in frozen telemetry is current-controller effective native and independent of Candidate A.
  rr=r._asdict(); rr['effective_native']=effective_native=float(r.effective_native); proxy=type('R',(),rr)
  desired,reason=ctl.step(proxy); rows.append((r.date,effective,desired,nav,reason)); pending=desired; prev_eff=effective; prev_close=float(r.research_wealth_core_equity)
 out=pd.DataFrame(rows,columns=['date','allocation','close_target','proxy_nav','reason'])
 return out,{'episodes':ctl.episodes,'entries':ctl.entries,'concordance_releases':ctl.concordance_releases}

def metrics(curve,dates):
 v=np.asarray(curve,float); t=pd.to_datetime(dates).reset_index(drop=True); yrs=(t.iloc[-1]-t.iloc[0]).days/365.2425; rets=pd.Series(v).pct_change().dropna(); peak=np.maximum.accumulate(v)
 return {'proxy_cagr':float((v[-1]/v[0])**(1/yrs)-1),'proxy_max_dd':float(np.min(v/peak-1)),'proxy_sharpe':float(rets.mean()/rets.std(ddof=1)*math.sqrt(252)),'proxy_ending_multiple':float(v[-1]/v[0])}

def current_proxy(frame):
 a=frame.research_allocation.astype(float).reset_index(drop=True); nav=1.; vals=[nav]
 for i in range(1,len(frame)):
  r=frame.iloc[i]; old=float(a.iloc[i-1]); new=float(a.iloc[i]); pc=float(frame.iloc[i-1].research_wealth_core_equity); ce=float(r.research_wealth_core_equity); oe=float(r.research_wealth_core_open_equity)
  fac=old*(ce/pc)+(1-old) if abs(new-old)<1e-15 else (1+old*(oe/pc-1))*(1-COST*abs(new-old))*(1+new*(ce/oe-1)); nav*=fac; vals.append(nav)
 return metrics(vals,frame.date)

def grids():
 for r20,dd in itertools.product((-0.04,-0.06,-0.08,-0.10),(-0.06,-0.10,-0.14,-0.18)): yield 'spy_price',dict(r20_stress=r20,dd_stress=dd,r20_healthy=0.,r40_healthy=0.)
 for rv,ratio,healthy in itertools.product((0.18,0.22,0.26,0.30),(1.,1.1,1.2),(0.16,0.18,0.20)): yield 'spy_vol',dict(rv20_stress=rv,ratio_stress=ratio,rv20_healthy=healthy,ratio_healthy=1.)
 for level,chg,healthy in itertools.product((20.,22.5,25.,27.5,30.),(0.,0.10,0.20),(18.,20.,22.)): yield 'vix_level_change',dict(vix_stress=level,chg5_stress=chg,vix_healthy=healthy,chg5_healthy=0.)
 for pct,z,healthy in itertools.product((0.75,0.85,0.90),(0.5,1.,1.5),(0.50,0.60)): yield 'vix_percentile',dict(pct_stress=pct,z_stress=z,pct_healthy=healthy)
 for r20,dd,vix,z in itertools.product((-0.05,-0.08),(-0.08,-0.12,-0.16),(20.,25.),(0.5,1.)): yield 'spy_vix',dict(r20_stress=r20,dd_stress=dd,vix_stress=vix,z_stress=z,vix_healthy=22.)

def episode_stats(a):
 red=np.asarray(a,float)<1-1e-12; lens=[]; s=None
 for i,x in enumerate(red):
  if x and s is None:s=i
  if s is not None and (not x or i==len(red)-1): e=i if x and i==len(red)-1 else i-1; lens.append(e-s+1); s=None
 return len(lens),float(np.mean(lens)) if lens else 0.,max(lens) if lens else 0

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--baseline-daily',type=Path,required=True); ap.add_argument('--vix-csv',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
 frame=enrich(pd.read_csv(a.baseline_daily),load_vix(a.vix_csv)); cur=current_proxy(frame); cura=frame.research_allocation.astype(float).to_numpy(); rows=[]
 for n,(fam,p) in enumerate(grids()):
  sim,state=simulate(frame,fam,p); m=metrics(sim.proxy_nav,sim.date); aa=sim.allocation.astype(float).to_numpy(); changed=np.flatnonzero(abs(aa-cura)>1e-12); eps,avg,mx=episode_stats(aa)
  rows.append({'candidate_id':f'v2-{fam}-{n:04d}','family':fam,'params':json.dumps(p,sort_keys=True,separators=(',',':')),**m,**state,'reduced_sessions':int((aa<1-1e-12).sum()),'defensive_episodes':eps,'mean_defensive_duration':avg,'max_defensive_duration':mx,'allocation_sessions_changed_vs_current':int(len(changed)),'first_allocation_divergence':str(frame.iloc[int(changed[0])].date.date()) if len(changed) else ''})
 out=pd.DataFrame(rows); out['proxy_cagr_gap_vs_current']=out.proxy_cagr-cur['proxy_cagr']; out['proxy_dd_gap_vs_current']=out.proxy_max_dd-cur['proxy_max_dd']; out.to_csv(a.output/'coarse-grid-v2.csv',index=False)
 fs=[]
 for fam,g in out.groupby('family'):
  acceptable=g[(g.proxy_cagr_gap_vs_current>=-0.02)&(g.proxy_dd_gap_vs_current<=0.03)]
  fs.append({'family':fam,'grid_points':len(g),'acceptable_points':len(acceptable),'proxy_cagr_median':g.proxy_cagr.median(),'proxy_cagr_max':g.proxy_cagr.max(),'proxy_max_dd_median':g.proxy_max_dd.median()})
 pd.DataFrame(fs).to_csv(a.output/'family-summary-v2.csv',index=False)
 cutoff=load_vix(a.vix_csv); cutoff=cutoff[(cutoff.index>=pd.Timestamp('1997-01-01'))&(cutoff.index<=MEASUREMENT_END)][['vix']]; cp=a.output/'vix-cboe-cutoff-through-2026-07-31.csv'; cutoff.reset_index().to_csv(cp,index=False,date_format='%Y-%m-%d')
 manifest={'status':'RESEARCH / NOT CERTIFIED','phase':'OBSERVATION_ONLY_COARSE_SCREEN_V2','baseline_run_id':BASELINE_RUN_ID,'baseline_daily_sha256':sha256(a.baseline_daily),'vix_download_sha256':sha256(a.vix_csv),'vix_cutoff_sha256':sha256(cp),'current_proxy_metrics':cur,'grid_points':len(out),'controller_state_preserved':['episode creation','persistence streak','SPY > 11% rebound route','cross-surface recovery route','latch clear','55% cap','next-session target timing'],'changed_layer':'classification-derived leadership observations only'}
 (a.output/'manifest-v2.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n'); print(json.dumps(manifest,indent=2)); print(pd.DataFrame(fs).to_string(index=False)); return 0
if __name__=='__main__': raise SystemExit(main())
