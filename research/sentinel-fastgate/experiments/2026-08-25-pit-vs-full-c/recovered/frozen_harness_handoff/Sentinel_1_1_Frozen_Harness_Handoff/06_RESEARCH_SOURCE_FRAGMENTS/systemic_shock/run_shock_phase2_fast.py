from pathlib import Path
import pandas as pd, numpy as np, json
from itertools import product
from numba import njit

OUT=Path('/mnt/data/systemic_shock_override');OUT.mkdir(exist_ok=True)
END=pd.Timestamp('2026-07-31');COST=.001
base=pd.read_csv('/mnt/data/elastic_survivor_firewall_deliverable/Wealth Core baseline_daily.csv',parse_dates=['date']).set_index('date').sort_index().loc[:END]
bin40=pd.read_csv('/mnt/data/elastic_survivor_firewall_deliverable/binary40_daily.csv',parse_dates=['date']).set_index('date').sort_index().loc[:END]
defn=pd.read_csv('/mnt/data/wealth_core_progressive_controller_deliverable/defensive_composite.csv',parse_dates=['date']).set_index('date').sort_index().loc[:END]
spy=pd.read_csv('/mnt/data/spy_sfp.csv',parse_dates=['date']).set_index('date').sort_index().loc[:END]
idx=base.index.intersection(bin40.index).intersection(defn.index)
base=base.loc[idx];bin40=bin40.loc[idx];defn=defn.loc[idx];spy=spy.reindex(idx).ffill()
n=len(idx)
shadow=base.shadow_nav.to_numpy(np.float64);core_ret=np.zeros(n);core_ret[1:]=shadow[1:]/shadow[:-1]-1
def_ret=defn.defense_return.to_numpy(np.float64);regular=bin40.systemic.to_numpy(np.bool_)
dd=base.shadow_dd.to_numpy(np.float64);dam=base.damaged_breadth.fillna(0).to_numpy(np.float64);green=base.green_breadth.fillna(0).to_numpy(np.float64)
def pc(a,k):
 o=np.full(len(a),np.nan);o[k:]=a[k:]/a[:-k]-1;return o
r5=pc(shadow,5);r10=pc(shadow,10);r20=pc(shadow,20);db5=np.full(n,np.nan);db5[5:]=dam[5:]-dam[:-5]
spy_px=spy.closeadj.to_numpy(np.float64);spy_nav=spy_px/spy_px[0]

# window definitions
windows={
 't5':(END-pd.DateOffset(years=5),END),'t10':(END-pd.DateOffset(years=10),END),'t15':(END-pd.DateOffset(years=15),END),'t20':(END-pd.DateOffset(years=20),END),
 'dotcom':(pd.Timestamp('2000-03-01'),pd.Timestamp('2000-06-30')),
 'gfc':(pd.Timestamp('2007-10-01'),pd.Timestamp('2009-03-31')),
 '2011':(pd.Timestamp('2011-05-01'),pd.Timestamp('2011-10-31')),
 '2018':(pd.Timestamp('2018-09-01'),pd.Timestamp('2018-12-31')),
 'covid':(pd.Timestamp('2020-02-01'),pd.Timestamp('2020-04-30')),
 '2022':(pd.Timestamp('2021-11-01'),pd.Timestamp('2022-10-31')),
 'rec2001':(pd.Timestamp('2001-03-01'),pd.Timestamp('2001-11-30')),
 'recgfc':(pd.Timestamp('2007-12-01'),pd.Timestamp('2009-06-30')),
 'reccovid':(pd.Timestamp('2020-02-01'),pd.Timestamp('2020-04-30')),
}
names=list(windows);starts=[];ends=[];years=[]
for k in names:
 a,b=windows[k];si=int(np.searchsorted(idx.values,np.datetime64(a),'left'));ei=int(np.searchsorted(idx.values,np.datetime64(b),'right')-1);starts.append(si);ends.append(ei);years.append((idx[ei]-idx[si]).days/365.25)
starts=np.array(starts,np.int64);ends=np.array(ends,np.int64);years=np.array(years,np.float64)
full_years=(idx[-1]-idx[0]).days/365.25

@njit(cache=True)
def sim_nav(sig,alloc,hold,conf,rr20,rdb,rgr,rearm,regular,dd,dam,green,r20,core_ret,def_ret):
 n=len(dd);nav=np.ones(n);active=False;armed=True;enter=-10000000;streak=0;prev=1.;entries=0;days=0
 for i in range(n-1):
  if dd[i]>-rearm and not sig[i]:armed=True
  if sig[i] and armed and (not active) and (not regular[i]):
   active=True;armed=False;enter=i;streak=0;entries+=1
  elif active:
   healthy=(not np.isnan(r20[i])) and r20[i]>rr20 and dam[i]<=rdb and green[i]>=rgr
   if healthy:streak+=1
   else:streak=0
   if i-enter>=hold and streak>=conf:
    active=False;streak=0
  a=1.
  if regular[i]:a=.4
  if active and alloc<a:a=alloc
  if active:days+=1
  cost=2*.001*abs(a-prev)
  nav[i+1]=nav[i]*(1+a*core_ret[i+1]+(1-a)*def_ret[i+1]-cost)
  prev=a
 return nav,entries,days

@njit(cache=True)
def eval_nav(nav,starts,ends,years,full_years):
 nw=len(starts);out=np.empty((nw,3));
 peak=nav[0];mdd=0.
 for i in range(len(nav)):
  if nav[i]>peak:peak=nav[i]
  d=nav[i]/peak-1
  if d<mdd:mdd=d
 full_cagr=(nav[-1]/nav[0])**(1/full_years)-1
 for w in range(nw):
  s=starts[w];e=ends[w];p=nav[s];md=0.
  for i in range(s,e+1):
   if nav[i]>p:p=nav[i]
   d=nav[i]/p-1
   if d<md:md=d
  tr=nav[e]/nav[s]-1
  c=(nav[e]/nav[s])**(1/years[w])-1
  out[w,0]=c;out[w,1]=md;out[w,2]=tr
 return full_cagr,mdd,nav[-1],out

def signal_tuple(row):
 jump=None if pd.isna(row.jump_min) else float(row.jump_min)
 return (float(row.dd_trigger),float(row.damaged_min),float(row.green_max),float(row.r5_max),float(row.r10_max),jump)
def make_sig(t):
 d,b,g,s5,s10,j=t
 x=(dd<=-d)&(dam>=b)&(green<=g)&((r5<=s5)|(r10<=s10))
 if j is not None:x=x&(db5>=j)
 return np.nan_to_num(x).astype(np.bool_)

screen=pd.read_csv(OUT/'phase1_signal_grid.csv')
ids=[1118,242,237,1548,24,1464,1121,352]
# add best IDs by different criteria
ids += screen.sort_values(['cagr','covid_improve'],ascending=False).head(20).signal_id.astype(int).tolist()
unique=[];seen=set()
for sid in ids:
 row=screen.loc[screen.signal_id==sid].iloc[0];t=signal_tuple(row);sig=make_sig(t);h=hash(sig.tobytes())
 if h not in seen:seen.add(h);unique.append((sid,t,sig))
print('unique signals',[(x[0],x[1],int(x[2].sum())) for x in unique])

# current metrics from exact supplied path
current=bin40.nav.to_numpy(np.float64);curfull=eval_nav(current,starts,ends,years,full_years)
rows=[]
params=list(product([.25,.40,.55],[5,10,15,20],[1,3,5],[0.,.01],[.50,.60,.70],[.20,.30,.40],[.04,.06,.08]))
for sid,t,sig in unique:
 for alloc,hold,conf,rr20,rdb,rgr,rearm in params:
  nav,entries,days=sim_nav(sig,alloc,hold,conf,rr20,rdb,rgr,rearm,regular,dd,dam,green,r20,core_ret,def_ret)
  fc,md,endv,w=eval_nav(nav,starts,ends,years,full_years)
  row={'signal_id':sid,'dd_trigger':t[0],'damaged_min':t[1],'green_max':t[2],'r5_max':t[3],'r10_max':t[4],'jump_min':np.nan if t[5] is None else t[5],
       'emergency_alloc':alloc,'min_hold':hold,'confirmation':conf,'recovery_r20':rr20,'recovery_damaged':rdb,'recovery_green':rgr,'rearm_dd':rearm,
       'cagr':fc,'max_drawdown':md,'ending_multiple':endv,'emergency_entries':entries,'emergency_days':days}
  for q,k in enumerate(names):row[f'{k}_cagr']=w[q,0];row[f'{k}_dd']=w[q,1];row[f'{k}_return']=w[q,2]
  rows.append(row)
res=pd.DataFrame(rows)
# current comparison fields
curfc,curmd,curend,curw=curfull
for q,k in enumerate(names):res[f'{k}_dd_improve']=res[f'{k}_dd']-curw[q,1]
res['cagr_delta']=res.cagr-curfc;res['covid_improve']=res.covid_dd-curw[names.index('covid'),1]
res['worst_crisis_delta']=res[[f'{k}_dd_improve' for k in ['dotcom','gfc','2011','2018','covid','2022']]].min(axis=1)
res['mean_crisis_delta']=res[[f'{k}_dd_improve' for k in ['dotcom','gfc','2011','2018','covid','2022']]].mean(axis=1)
res['min_trailing_calmar']=np.min(np.column_stack([res[f't{y}_cagr']/(-res[f't{y}_dd']) for y in [5,10,15,20]]),axis=1)
res.to_csv(OUT/'phase2_fast_grid.csv',index=False)
# constraints prioritize robust improvement and limited compounding cost
q=res[(res.covid_improve>=.03)&(res.cagr_delta>=-.005)&(res.max_drawdown>=curmd)&(res.worst_crisis_delta>=-.015)&(res.emergency_entries<=12)]
print('qualified',len(q))
if len(q)==0:q=res[(res.covid_improve>=.02)&(res.cagr_delta>=-.008)&(res.worst_crisis_delta>=-.02)]
q=q.sort_values(['worst_crisis_delta','mean_crisis_delta','min_trailing_calmar','cagr'],ascending=False)
q.head(200).to_csv(OUT/'phase2_fast_qualified.csv',index=False)
print(q.head(20)[['signal_id','dd_trigger','damaged_min','green_max','r5_max','r10_max','jump_min','emergency_alloc','min_hold','confirmation','recovery_r20','recovery_damaged','recovery_green','rearm_dd','cagr','max_drawdown','covid_dd','covid_improve','worst_crisis_delta','mean_crisis_delta','emergency_entries','emergency_days']].to_string(index=False))
# Pick a stable/simple candidate: among top 10% robust score, prefer signal 1118, alloc .4, simple recovery if qualified; otherwise top.
preferred=q[(q.signal_id==1118)&(q.emergency_alloc==.40)&(q.min_hold.isin([10,15]))&(q.confirmation.isin([3]))&(q.recovery_r20==0.)&(q.recovery_damaged==.60)&(q.recovery_green.isin([.20,.30]))&(q.rearm_dd==.06)]
if len(preferred):best=preferred.sort_values(['worst_crisis_delta','cagr'],ascending=False).iloc[0]
else:best=q.iloc[0]
print('\nBEST',best.to_dict())
# rerun best detail in Python to capture state/transitions
bt=(float(best.dd_trigger),float(best.damaged_min),float(best.green_max),float(best.r5_max),float(best.r10_max),None if pd.isna(best.jump_min) else float(best.jump_min));sig=make_sig(bt)
nav,entries,days=sim_nav(sig,float(best.emergency_alloc),int(best.min_hold),int(best.confirmation),float(best.recovery_r20),float(best.recovery_damaged),float(best.recovery_green),float(best.rearm_dd),regular,dd,dam,green,r20,core_ret,def_ret)
# reconstruct state exactly for logs
active=False;armed=True;enter=-10**9;streak=0;prev=1.;em=np.zeros(n,bool);allocs=np.ones(n);trs=[]
for i in range(n-1):
 if dd[i]>-best.rearm_dd and not sig[i]:armed=True
 if sig[i] and armed and not active and not regular[i]:active=True;armed=False;enter=i;streak=0;trs.append([idx[i],'enter',dd[i],dam[i],green[i],r5[i],r10[i],db5[i]])
 elif active:
  healthy=np.isfinite(r20[i]) and r20[i]>best.recovery_r20 and dam[i]<=best.recovery_damaged and green[i]>=best.recovery_green
  streak=streak+1 if healthy else 0
  if i-enter>=best.min_hold and streak>=best.confirmation:active=False;streak=0;trs.append([idx[i],'exit',dd[i],dam[i],green[i],r5[i],r10[i],db5[i]])
 em[i]=active;a=.4 if regular[i] else 1.;a=min(a,best.emergency_alloc) if active else a;allocs[i]=a
em[-1]=em[-2];allocs[-1]=allocs[-2]
daily=pd.DataFrame({'nav':nav,'shadow_nav':shadow,'shadow_dd':dd,'regular_systemic':regular,'emergency':em,'allocation':allocs,'damaged_breadth':dam,'green_breadth':green,'r5':r5,'r10':r10,'r20':r20,'db5':db5},index=idx)
daily.to_csv(OUT/'best_override_daily.csv')
pd.DataFrame(trs,columns=['date','event','shadow_dd','damaged_breadth','green_breadth','r5','r10','db5']).to_csv(OUT/'best_override_transitions.csv',index=False)
best.to_frame('value').to_csv(OUT/'best_config_metrics.csv')
# Generate tables
series={'Wealth Core':shadow/shadow[0],'Current backstop':current,'Shock override':nav,'SPY':spy_nav}
trail=[]
for y in [5,10,15,20]:
 qn=names.index(f't{y}')
 for nm,arr in series.items():
  fc,md,en,w=eval_nav(np.asarray(arr,np.float64),starts,ends,years,full_years)
  trail.append({'period_years':y,'strategy':nm,'cagr':w[qn,0],'max_drawdown':w[qn,1],'total_return':w[qn,2]})
pd.DataFrame(trail).to_csv(OUT/'trailing_comparison.csv',index=False)
recs=[('2001 recession','rec2001'),('Great Recession','recgfc'),('COVID recession','reccovid')]
rec=[]
for label,k in recs:
 qn=names.index(k)
 for nm,arr in series.items():
  fc,md,en,w=eval_nav(np.asarray(arr,np.float64),starts,ends,years,full_years)
  rec.append({'recession':label,'strategy':nm,'annualized_cagr':w[qn,0],'max_drawdown':w[qn,1],'total_return':w[qn,2]})
pd.DataFrame(rec).to_csv(OUT/'recession_comparison.csv',index=False)
# COVID peak-trough and recovery
cov=[];a=pd.Timestamp('2020-02-19');b=pd.Timestamp('2020-03-23')
si=np.searchsorted(idx.values,np.datetime64(a),'left');ei=np.searchsorted(idx.values,np.datetime64(b),'right')-1
for nm,arr in series.items():
 arr=np.asarray(arr,float);x=arr[si:ei+1];md=np.min(x/np.maximum.accumulate(x)-1);tr=x[-1]/x[0]-1;pre=arr[si];post=np.where(arr[ei:]>=pre)[0];rd=idx[ei+post[0]].date().isoformat() if len(post) else ''
 cov.append({'strategy':nm,'total_return':tr,'max_drawdown':md,'recovery_date':rd})
pd.DataFrame(cov).to_csv(OUT/'covid_peak_to_trough.csv',index=False)
# local robustness same signal around recovery params
local=res[(res.signal_id==best.signal_id)&(abs(res.emergency_alloc-best.emergency_alloc)<=.15)&(abs(res.min_hold-best.min_hold)<=5)&(abs(res.confirmation-best.confirmation)<=2)]
local.to_csv(OUT/'best_local_neighborhood.csv',index=False)
summary={'current_full':{'cagr':curfc,'max_drawdown':curmd,'ending_multiple':curend},'best':best.to_dict(),'local_medians':{'cagr':float(local.cagr.median()),'max_drawdown':float(local.max_drawdown.median()),'covid_improve':float(local.covid_improve.median())},'unique_signals':len(unique),'tested_configs':len(res)}
(OUT/'summary_fast.json').write_text(json.dumps(summary,indent=2,default=float))
print('\nTRAILING\n',pd.DataFrame(trail).to_string(index=False))
print('\nRECESSIONS\n',pd.DataFrame(rec).to_string(index=False))
print('\nCOVID\n',pd.DataFrame(cov).to_string(index=False))
print('\nTRANSITIONS\n',pd.DataFrame(trs).to_string(index=False))
