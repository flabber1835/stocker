from pathlib import Path
import pandas as pd
import numpy as np
from dataclasses import dataclass, asdict
from itertools import product

BASE=Path('/mnt/data/elastic_survivor_firewall_deliverable/Wealth Core baseline_daily.csv')
BIN=Path('/mnt/data/elastic_survivor_firewall_deliverable/binary40_daily.csv')
DEF=Path('/mnt/data/wealth_core_progressive_controller_deliverable/defensive_composite.csv')
SPY=Path('/mnt/data/spy_sfp.csv')
OUT=Path('/mnt/data/systemic_shock_override')
OUT.mkdir(exist_ok=True)
COST=.001
END=pd.Timestamp('2026-07-31')

base=pd.read_csv(BASE,parse_dates=['date']).set_index('date').sort_index().loc[:END]
bin40=pd.read_csv(BIN,parse_dates=['date']).set_index('date').sort_index().loc[:END]
defn=pd.read_csv(DEF,parse_dates=['date']).set_index('date').sort_index().loc[:END]
idx=base.index.intersection(bin40.index).intersection(defn.index)
base=base.loc[idx];bin40=bin40.loc[idx];defn=defn.loc[idx]
spy=pd.read_csv(SPY,parse_dates=['date']).set_index('date').sort_index().loc[:END]
spy=spy.reindex(idx).ffill()

shadow=base.shadow_nav.to_numpy(float)
core_ret=np.zeros(len(idx));core_ret[1:]=shadow[1:]/shadow[:-1]-1
def_ret=defn.defense_return.to_numpy(float)
regular=bin40.systemic.astype(bool).to_numpy()
dd=base.shadow_dd.to_numpy(float)
damaged=base.damaged_breadth.fillna(0).to_numpy(float)
green=base.green_breadth.fillna(0).to_numpy(float)

def pct_change(arr,n):
 out=np.full(len(arr),np.nan);out[n:]=arr[n:]/arr[:-n]-1;return out
r5=pct_change(shadow,5);r10=pct_change(shadow,10);r20=pct_change(shadow,20)
db5=np.full(len(idx),np.nan);db5[5:]=damaged[5:]-damaged[:-5]
spy_px=spy.closeadj.to_numpy(float)
spy_ret=np.zeros(len(idx));spy_ret[1:]=spy_px[1:]/spy_px[:-1]-1

@dataclass(frozen=True)
class SignalCfg:
 dd_trigger:float
 damaged_min:float
 green_max:float
 r5_max:float
 r10_max:float
 jump_min:float|None

@dataclass(frozen=True)
class RunCfg:
 name:str
 signal:SignalCfg
 emergency_alloc:float=.40
 min_hold:int=10
 confirmation:int=3
 recovery_r20:float=0.0
 recovery_damaged:float=.60
 recovery_green:float=.25
 rearm_dd:float=.06


def signal_array(c:SignalCfg):
 broad=(dd<=-c.dd_trigger)&(damaged>=c.damaged_min)&(green<=c.green_max)
 fast=(r5<=c.r5_max)|(r10<=c.r10_max)
 if c.jump_min is None:
  return broad&fast
 return broad&fast&(db5>=c.jump_min)


def simulate(cfg:RunCfg, detail=False):
 sig=signal_array(cfg.signal)
 n=len(idx);nav=np.ones(n);alloc=np.ones(n);em=np.zeros(n,dtype=bool)
 active=False;armed=True;enter=-10**9;streak=0;prev_alloc=1.0
 transitions=[]
 for i in range(n-1):
  if dd[i]>-cfg.rearm_dd and not sig[i]: armed=True
  if sig[i] and armed and not active and not regular[i]:
   active=True;armed=False;enter=i;streak=0
   if detail: transitions.append((idx[i],'emergency_enter',dd[i],damaged[i],green[i],r5[i],r10[i],db5[i]))
  elif active:
   healthy=(np.isfinite(r20[i]) and r20[i]>cfg.recovery_r20 and damaged[i]<=cfg.recovery_damaged and green[i]>=cfg.recovery_green)
   streak=streak+1 if healthy else 0
   if (i-enter)>=cfg.min_hold and streak>=cfg.confirmation:
    active=False;streak=0
    if detail: transitions.append((idx[i],'emergency_exit',dd[i],damaged[i],green[i],r5[i],r10[i],db5[i]))
  em[i]=active
  a=1.0
  if regular[i]: a=min(a,.40)
  if active: a=min(a,cfg.emergency_alloc)
  alloc[i]=a
  cost=2*COST*abs(a-prev_alloc)
  live=a*core_ret[i+1]+(1-a)*def_ret[i+1]-cost
  nav[i+1]=nav[i]*(1+live)
  prev_alloc=a
 alloc[-1]=alloc[-2];em[-1]=em[-2]
 s=pd.Series(nav,index=idx,name=cfg.name)
 if detail:
  daily=pd.DataFrame({'nav':nav,'shadow_nav':shadow,'shadow_dd':dd,'regular_systemic':regular,'emergency':em,'allocation':alloc,'damaged_breadth':damaged,'green_breadth':green,'r5':r5,'r10':r10,'r20':r20,'db5':db5},index=idx)
  tr=pd.DataFrame(transitions,columns=['date','event','shadow_dd','damaged_breadth','green_breadth','r5','r10','db5'])
  return s,daily,tr
 return s


def metrics(s):
 s=s.dropna();years=(s.index[-1]-s.index[0]).days/365.25
 ret=s.pct_change().dropna();ddv=s/s.cummax()-1
 return {'cagr':float((s.iloc[-1]/s.iloc[0])**(1/years)-1),'max_drawdown':float(ddv.min()),'calmar':float(((s.iloc[-1]/s.iloc[0])**(1/years)-1)/abs(ddv.min())),'ending_multiple':float(s.iloc[-1]/s.iloc[0])}

def window_metrics(s,start,end=END):
 x=s.loc[(s.index>=pd.Timestamp(start))&(s.index<=pd.Timestamp(end))]
 if len(x)<2:return {'cagr':np.nan,'max_drawdown':np.nan,'total_return':np.nan}
 years=(x.index[-1]-x.index[0]).days/365.25
 cagr=(x.iloc[-1]/x.iloc[0])**(1/years)-1
 md=(x/x.cummax()-1).min()
 return {'cagr':float(cagr),'max_drawdown':float(md),'total_return':float(x.iloc[-1]/x.iloc[0]-1)}

# verify current binary reconstruction
cur_cfg=None
cur_nav=np.ones(len(idx));prev=1.0
for i in range(len(idx)-1):
 a=.4 if regular[i] else 1.;cost=2*COST*abs(a-prev)
 cur_nav[i+1]=cur_nav[i]*(1+a*core_ret[i+1]+(1-a)*def_ret[i+1]-cost);prev=a
assert np.max(np.abs(cur_nav-bin40.nav.to_numpy(float)))<1e-8
current=pd.Series(cur_nav,index=idx,name='current_binary40')
core=pd.Series(shadow/shadow[0],index=idx,name='wealth_core')
spy_series=pd.Series(spy_px/spy_px[0],index=idx,name='spy')

# phase 1: signal screen with conservative fixed recovery
signals=[]
for vals in product([.06,.08,.10,.12],[.65,.75,.85,.95],[.10,.20,.30],[-.05,-.07,-.09],[-.08,-.10,-.12],[None,.20,.40,.60]):
 signals.append(SignalCfg(*vals))
rows=[]
crises={'dotcom':('2000-03-01','2000-06-30'),'gfc':('2007-10-01','2009-03-31'),'2011':('2011-05-01','2011-10-31'),'2018':('2018-09-01','2018-12-31'),'covid':('2020-02-01','2020-04-30'),'2022':('2021-11-01','2022-10-31')}
for j,sig in enumerate(signals):
 cfg=RunCfg(f'signal_{j}',sig)
 s=simulate(cfg);m=metrics(s)
 row={'signal_id':j,**asdict(sig),**m}
 for name,(a,b) in crises.items():
  wm=window_metrics(s,a,b);row[f'{name}_dd']=wm['max_drawdown'];row[f'{name}_return']=wm['total_return']
 for yrs in [5,10,15,20]:
  start=END-pd.DateOffset(years=yrs);wm=window_metrics(s,start,END);row[f't{yrs}_cagr']=wm['cagr'];row[f't{yrs}_dd']=wm['max_drawdown']
 rows.append(row)
screen=pd.DataFrame(rows)
# robust screen: improve COVID by >=2 points, retain CAGR, no worse full MDD; rank across crisis/rolling calmar
curm=metrics(current);curcov=window_metrics(current,*crises['covid'])
for name in crises:
 screen[f'{name}_dd_improve']=screen[f'{name}_dd']-window_metrics(current,*crises[name])['max_drawdown']
screen['cagr_cost']=curm['cagr']-screen.cagr
screen['covid_improve']=screen.covid_dd-curcov['max_drawdown']
screen['worst_crisis_delta']=screen[[f'{x}_dd_improve' for x in crises]].min(axis=1)
screen['min_trailing_calmar']=np.min(np.column_stack([screen[f't{y}_cagr']/(-screen[f't{y}_dd']) for y in [5,10,15,20]]),axis=1)
qualified=screen[(screen.cagr>=curm['cagr']-.0075)&(screen.max_drawdown>=curm['max_drawdown']-.005)&(screen.covid_improve>=.02)]
if len(qualified)==0:qualified=screen.sort_values(['covid_improve','cagr'],ascending=False).head(30)
qualified=qualified.sort_values(['worst_crisis_delta','min_trailing_calmar','cagr'],ascending=False)
screen.to_csv(OUT/'phase1_signal_grid.csv',index=False)
qualified.head(30).to_csv(OUT/'phase1_top_signals.csv',index=False)

# phase 2 recovery/floor around top 20 unique signals
rows2=[]
for _,rr in qualified.head(20).iterrows():
 sig=SignalCfg(float(rr.dd_trigger),float(rr.damaged_min),float(rr.green_max),float(rr.r5_max),float(rr.r10_max),None if pd.isna(rr.jump_min) else float(rr.jump_min))
 for vals in product([.25,.40,.55],[5,10,15,20],[1,3,5],[0.,.01],[.50,.60,.70],[.20,.30,.40],[.04,.06,.08]):
  alloc,hold,conf,rr20,rdb,rgr,rearm=vals
  name=f"s{int(rr.signal_id)}_a{alloc}_h{hold}_c{conf}_r{rr20}_db{rdb}_g{rgr}_re{rearm}"
  cfg=RunCfg(name,sig,alloc,hold,conf,rr20,rdb,rgr,rearm)
  s=simulate(cfg);m=metrics(s)
  row={'name':name,'signal_id':int(rr.signal_id),**asdict(sig),'emergency_alloc':alloc,'min_hold':hold,'confirmation':conf,'recovery_r20':rr20,'recovery_damaged':rdb,'recovery_green':rgr,'rearm_dd':rearm,**m}
  for cname,(a,b) in crises.items():
   wm=window_metrics(s,a,b);row[f'{cname}_dd']=wm['max_drawdown'];row[f'{cname}_return']=wm['total_return']
  for yrs in [5,10,15,20]:
   wm=window_metrics(s,END-pd.DateOffset(years=yrs),END);row[f't{yrs}_cagr']=wm['cagr'];row[f't{yrs}_dd']=wm['max_drawdown']
  rows2.append(row)
phase2=pd.DataFrame(rows2)
for cname in crises:
 phase2[f'{cname}_dd_improve']=phase2[f'{cname}_dd']-window_metrics(current,*crises[cname])['max_drawdown']
phase2['cagr_cost']=curm['cagr']-phase2.cagr
phase2['covid_improve']=phase2.covid_dd-curcov['max_drawdown']
phase2['worst_crisis_delta']=phase2[[f'{x}_dd_improve' for x in crises]].min(axis=1)
phase2['mean_crisis_improve']=phase2[[f'{x}_dd_improve' for x in crises]].mean(axis=1)
phase2['min_trailing_calmar']=np.min(np.column_stack([phase2[f't{y}_cagr']/(-phase2[f't{y}_dd']) for y in [5,10,15,20]]),axis=1)
# Candidate: COVID improves at least 3pp, full CAGR cost <= 60bp, full MDD no worse, no crisis worsened >2pp.
q=phase2[(phase2.cagr>=curm['cagr']-.006)&(phase2.max_drawdown>=curm['max_drawdown'])&(phase2.covid_improve>=.03)&(phase2.worst_crisis_delta>=-.02)]
if len(q)==0:
 q=phase2[(phase2.cagr>=curm['cagr']-.008)&(phase2.covid_improve>=.02)&(phase2.worst_crisis_delta>=-.025)]
q=q.sort_values(['worst_crisis_delta','mean_crisis_improve','min_trailing_calmar','cagr'],ascending=False)
phase2.to_csv(OUT/'phase2_full_grid.csv',index=False)
q.head(100).to_csv(OUT/'phase2_qualified.csv',index=False)

best=q.iloc[0]
sig=SignalCfg(float(best.dd_trigger),float(best.damaged_min),float(best.green_max),float(best.r5_max),float(best.r10_max),None if pd.isna(best.jump_min) else float(best.jump_min))
bestcfg=RunCfg(str(best['name']),sig,float(best.emergency_alloc),int(best.min_hold),int(best.confirmation),float(best.recovery_r20),float(best.recovery_damaged),float(best.recovery_green),float(best.rearm_dd))
best_s,best_daily,best_tr=simulate(bestcfg,True)
best_daily.to_csv(OUT/'best_override_daily.csv')
best_tr.to_csv(OUT/'best_override_transitions.csv',index=False)

# local neighborhood stability: candidates sharing signal thresholds around best, aggregate quantiles
local=phase2[(abs(phase2.dd_trigger-best.dd_trigger)<=.02)&(abs(phase2.damaged_min-best.damaged_min)<=.10)&(abs(phase2.green_max-best.green_max)<=.10)&(abs(phase2.r5_max-best.r5_max)<=.02)&(abs(phase2.r10_max-best.r10_max)<=.02)]
local.to_csv(OUT/'best_local_neighborhood.csv',index=False)

# Trailing tables and recession tables
strategies={'Wealth Core':core,'Current backstop':current,'Shock override':best_s,'SPY':spy_series}
trail=[]
for yrs in [5,10,15,20]:
 for name,s in strategies.items():
  wm=window_metrics(s,END-pd.DateOffset(years=yrs),END)
  trail.append({'period':f'{yrs} years','strategy':name,**wm})
pd.DataFrame(trail).to_csv(OUT/'trailing_comparison.csv',index=False)

# Official recession month windows, bounded to trading days
recessions={'2001 recession':('2001-03-01','2001-11-30'),'Great Recession':('2007-12-01','2009-06-30'),'COVID recession':('2020-02-01','2020-04-30')}
rec=[]
for rname,(a,b) in recessions.items():
 for name,s in strategies.items():
  wm=window_metrics(s,a,b)
  rec.append({'recession':rname,'strategy':name,**wm})
pd.DataFrame(rec).to_csv(OUT/'recession_comparison.csv',index=False)

# Peak-to-trough COVID and recovery dates
cov_start=pd.Timestamp('2020-02-19');cov_end=pd.Timestamp('2020-03-23')
cov=[]
for name,s in strategies.items():
 wm=window_metrics(s,cov_start,cov_end)
 pre=s.loc[:cov_start].iloc[-1]
 after=s.loc[cov_end:]
 recovered=after[after>=pre]
 cov.append({'strategy':name,**wm,'recovery_date':recovered.index[0].date().isoformat() if len(recovered) else ''})
pd.DataFrame(cov).to_csv(OUT/'covid_peak_trough.csv',index=False)

# Summary
summary={'current':curm,'best':metrics(best_s),'best_config':asdict(bestcfg),'current_covid':curcov,'best_covid':window_metrics(best_s,*crises['covid']),'qualified_count':len(q),'local_count':len(local),'local_cagr_median':float(local.cagr.median()),'local_covid_improve_median':float(local.covid_improve.median()),'local_maxdd_median':float(local.max_drawdown.median())}
import json
(OUT/'summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
print('\nTRAILING')
print(pd.DataFrame(trail).pivot(index='period',columns='strategy',values=['cagr','max_drawdown']).round(5))
print('\nRECESSIONS')
print(pd.DataFrame(rec).pivot(index='recession',columns='strategy',values=['total_return','max_drawdown']).round(5))
print('\nTRANSITIONS',len(best_tr))
print(best_tr.to_string(index=False))
