from pathlib import Path
import pandas as pd, numpy as np, json
from itertools import product
# Load common data
BASE=Path('/mnt/data/elastic_survivor_firewall_deliverable/Wealth Core baseline_daily.csv')
BIN=Path('/mnt/data/elastic_survivor_firewall_deliverable/binary40_daily.csv')
DEF=Path('/mnt/data/wealth_core_progressive_controller_deliverable/defensive_composite.csv')
SPY=Path('/mnt/data/spy_sfp.csv')
OUT=Path('/mnt/data/shock_systemic_confirmation');OUT.mkdir(exist_ok=True)
END=pd.Timestamp('2026-07-31');COST=.001
base=pd.read_csv(BASE,parse_dates=['date']).set_index('date').sort_index().loc[:END]
bin40=pd.read_csv(BIN,parse_dates=['date']).set_index('date').sort_index().loc[:END]
defn=pd.read_csv(DEF,parse_dates=['date']).set_index('date').sort_index().loc[:END]
idx=base.index.intersection(bin40.index).intersection(defn.index);base=base.loc[idx];bin40=bin40.loc[idx];defn=defn.loc[idx]
spy=pd.read_csv(SPY,parse_dates=['date']).set_index('date').sort_index().loc[:END].reindex(idx).ffill()
shadow=base.shadow_nav.to_numpy(float);core_ret=np.zeros(len(idx));core_ret[1:]=shadow[1:]/shadow[:-1]-1
def_ret=defn.defense_return.to_numpy(float);regular=bin40.systemic.astype(bool).to_numpy();dd=base.shadow_dd.to_numpy(float)
damaged=base.damaged_breadth.fillna(0).to_numpy(float);green=base.green_breadth.fillna(0).to_numpy(float)
def pct(a,n):o=np.full(len(a),np.nan);o[n:]=a[n:]/a[:-n]-1;return o
r5=pct(shadow,5);r10=pct(shadow,10);r20=pct(shadow,20);db5=np.full(len(idx),np.nan);db5[5:]=damaged[5:]-damaged[:-5]
spy_px=spy.closeadj.to_numpy(float);spy_r=np.zeros(len(idx));spy_r[1:]=spy_px[1:]/spy_px[:-1]-1
sr=pd.Series(spy_r,index=idx);v5=sr.rolling(5).std(ddof=1).to_numpy()*np.sqrt(252);v20=sr.rolling(20).std(ddof=1).to_numpy()*np.sqrt(252);va=v5/v20-1
spy_r20=pct(spy_px,20)
internal=(dd<=-.10)&(damaged>=.85)&(green<=.20)&((r5<=-.05)|(r10<=-.08))&(db5>=.40)

def signal(volmin,spy20max,fallback_r10):
 return internal & np.isfinite(va)&(va>=volmin)&((spy_r20<=spy20max)|(r10<=fallback_r10))

def sim(sig,alloc=.4,hold=10,conf=3,detail=False):
 n=len(idx);nav=np.ones(n);aa=np.ones(n);em=np.zeros(n,bool);active=False;armed=True;enter=-10**9;streak=0;prev=1.;trs=[]
 for i in range(n-1):
  if dd[i]>-.06 and not sig[i]:armed=True
  if sig[i] and armed and not active and not regular[i]:
   active=True;armed=False;enter=i;streak=0
   if detail:trs.append([idx[i],'enter',dd[i],damaged[i],green[i],r5[i],r10[i],db5[i],va[i],spy_r20[i]])
  elif active:
   healthy=np.isfinite(r20[i]) and r20[i]>0 and damaged[i]<=.60 and green[i]>=.20
   streak=streak+1 if healthy else 0
   if i-enter>=hold and streak>=conf:
    active=False;streak=0
    if detail:trs.append([idx[i],'exit',dd[i],damaged[i],green[i],r5[i],r10[i],db5[i],va[i],spy_r20[i]])
  a=.4 if regular[i] else 1.
  if active:a=min(a,alloc)
  aa[i]=a;em[i]=active;cost=2*COST*abs(a-prev);nav[i+1]=nav[i]*(1+a*core_ret[i+1]+(1-a)*def_ret[i+1]-cost);prev=a
 aa[-1]=aa[-2];em[-1]=em[-2]
 if detail:
  d=pd.DataFrame({'nav':nav,'allocation':aa,'emergency':em,'signal':sig,'vol_accel':va,'spy_r20':spy_r20,'shadow_nav':shadow,'shadow_dd':dd,'damaged':damaged,'green':green,'r5':r5,'r10':r10,'r20':r20,'db5':db5,'regular':regular},index=idx)
  t=pd.DataFrame(trs,columns=['date','event','shadow_dd','damaged','green','r5','r10','db5','vol_accel','spy_r20'])
  return nav,d,t
 return nav

def met(a):
 y=(idx[-1]-idx[0]).days/365.25;return (a[-1]/a[0])**(1/y)-1,np.min(a/np.maximum.accumulate(a)-1),a[-1]
def win(a,s,e=END):
 m=(idx>=pd.Timestamp(s))&(idx<=pd.Timestamp(e));x=a[m];d=idx[m];y=(d[-1]-d[0]).days/365.25;return (x[-1]/x[0])**(1/y)-1,np.min(x/np.maximum.accumulate(x)-1),x[-1]/x[0]-1
old=pd.read_csv('/mnt/data/systemic_shock_override_deliverable/best_override_daily.csv',parse_dates=['date']).set_index('date').reindex(idx).nav.to_numpy(float)
cur=bin40.nav.to_numpy(float)
crises={'dotcom':('2000-03-01','2000-06-30'),'gfc':('2007-10-01','2009-03-31'),'2011':('2011-05-01','2011-10-31'),'2015':('2015-07-01','2016-02-29'),'2018':('2018-09-01','2018-12-31'),'covid':('2020-02-01','2020-04-30'),'2022':('2021-11-01','2022-10-31')}
rows=[]
for volmin,spymax,fb,alloc,hold,conf in product([.02,.04,.06],[-.005,-.01,-.015],[-.09,-.10,-.11],[.25,.4,.55],[5,10,15],[1,3]):
 sig=signal(volmin,spymax,fb);nav=sim(sig,alloc,hold,conf);c,m,e=met(nav);r={'vol_accel_min':volmin,'spy20max':spymax,'fallback_r10':fb,'alloc':alloc,'min_hold':hold,'confirmation':conf,'signal_days':int(sig.sum()),'cagr':c,'max_drawdown':m,'ending_multiple':e}
 for k,(a,b) in crises.items():cc,mm,t=win(nav,a,b);r[f'{k}_dd']=mm;r[f'{k}_return']=t
 for y in [5,10,15,20]:cc,mm,t=win(nav,END-pd.DateOffset(years=y),END);r[f't{y}_cagr']=cc;r[f't{y}_dd']=mm
 rows.append(r)
res=pd.DataFrame(rows);om=met(old);cm=met(cur);res['cagr_vs_old']=res.cagr-om[0];res['dd_vs_old']=res.max_drawdown-om[1];res['calmar']=res.cagr/(-res.max_drawdown);res['min_trailing_calmar']=np.min(np.column_stack([res[f't{y}_cagr']/(-res[f't{y}_dd']) for y in [5,10,15,20]]),axis=1);res['worst_crisis_vs_old']=np.min(np.column_stack([res[f'{k}_dd']-win(old,*v)[1] for k,v in crises.items()]),axis=1)
res.to_csv(OUT/'systemic_confirmation_grid.csv',index=False)
q=res[(res.alloc==.4)&(res.max_drawdown>=om[1]-.001)&(res.covid_dd>=win(old,*crises['covid'])[1]-.001)&(res.worst_crisis_vs_old>=-.001)].sort_values(['cagr','min_trailing_calmar'],ascending=False)
q.to_csv(OUT/'systemic_confirmation_candidates.csv',index=False)
print('old',om,'current',cm)
print(q.head(50)[['vol_accel_min','spy20max','fallback_r10','min_hold','confirmation','cagr','max_drawdown','ending_multiple','gfc_return','covid_dd','t10_cagr','t15_cagr','t20_cagr','signal_days']].to_string(index=False))
# choose plateau center vol .04, spy -0.01, fallback -.10, hold10 conf3
pref=q[(q.vol_accel_min==.04)&(q.spy20max==-.01)&(q.fallback_r10==-.10)&(q.min_hold==10)&(q.confirmation==3)]
if len(pref)==0:pref=q.iloc[[0]]
b=pref.iloc[0];sig=signal(b.vol_accel_min,b.spy20max,b.fallback_r10);nav,d,t=sim(sig,b.alloc,int(b.min_hold),int(b.confirmation),True);d.to_csv(OUT/'best_systemic_confirmation_daily.csv');t.to_csv(OUT/'best_systemic_confirmation_transitions.csv',index=False);b.to_frame('value').to_csv(OUT/'best_systemic_confirmation_metrics.csv')
strategies={'Wealth Core':shadow/shadow[0],'Current backstop':cur,'Old shock override':old,'Systemic-confirmed override':nav,'SPY':spy_px/spy_px[0]};trail=[]
for y in [5,10,15,20]:
 for nm,a in strategies.items():c,m,r=win(a,END-pd.DateOffset(years=y),END);trail.append({'period_years':y,'strategy':nm,'cagr':c,'max_drawdown':m,'total_return':r})
pd.DataFrame(trail).to_csv(OUT/'trailing_comparison.csv',index=False)
recs={'2001 recession':('2001-03-01','2001-11-30'),'Great Recession':('2007-12-01','2009-06-30'),'COVID recession':('2020-02-01','2020-04-30')};rr=[]
for rn,(s,e) in recs.items():
 for nm,a in strategies.items():c,m,r=win(a,s,e);rr.append({'recession':rn,'strategy':nm,'annualized_cagr':c,'max_drawdown':m,'total_return':r})
pd.DataFrame(rr).to_csv(OUT/'recession_comparison.csv',index=False)
(OUT/'summary.json').write_text(json.dumps({'old':dict(zip(['cagr','mdd','ending'],om)),'current':dict(zip(['cagr','mdd','ending'],cm)),'best':b.to_dict()},indent=2,default=float))
print('\nBEST',b.to_dict());print(t.to_string(index=False))
