import importlib.util,sys, numpy as np,pandas as pd,json
from pathlib import Path
P='/mnt/data/sector_peer_v2_strict.py'; spec=importlib.util.spec_from_file_location('m',P); m=importlib.util.module_from_spec(spec); sys.modules['m']=m; spec.loader.exec_module(m)
OUT=Path('/mnt/data/sector_peer_v3_extra_out');OUT.mkdir(exist_ok=True)

def build_knn(kind,k,lookback,minobs):
 vals=[]
 for ix,d in enumerate(m.base.index):
  g=m.groups[d]; mats,counts=m.corr_mats(d,g.ticker.tolist(),lookback=lookback,minobs=minobs); vals.append(m.peer_damage(mats[kind],counts,g,k,False,0.0,minobs))
  if ix%1000==0:print(kind,k,lookback,ix,flush=True)
 return pd.Series(vals,index=m.base.index)

def monthly_knn(kind='resid',k=3,lookback=126,minobs=60):
 vals=[]; peer_map={}; month=None
 for ix,d in enumerate(m.base.index):
  g=m.groups[d]; ticks=g.ticker.tolist(); mats,counts=m.corr_mats(d,ticks,lookback=lookback,minobs=minobs); C=mats[kind]; cur=(d.year,d.month); pos={t:i for i,t in enumerate(ticks)}
  if cur!=month: peer_map={};month=cur
  for i,t in enumerate(ticks):
   if t in peer_map:continue
   if counts[i]<minobs:peer_map[t]=[];continue
   c=C[i].copy();c[i]=np.nan;ok=np.where(np.isfinite(c)&(counts>=minobs))[0];peer_map[t]=[ticks[j] for j in ok[np.argsort(c[ok])[::-1]][:k]] if len(ok) else []
  red=dict(zip(ticks,g.red.to_numpy(bool)));green=dict(zip(ticks,g.green.to_numpy(bool)));core=dict(zip(ticks,g.core_amber.to_numpy(bool))); amber=[]
  for t in ticks:
   aa=core[t]; peers=[p for p in peer_map.get(t,[]) if p in red]
   if peers:
    stress=np.mean([red[t]]+[red[p] for p in peers]); aa=aa or (stress>=.5 and not green[t])
   amber.append(aa)
  vals.append(np.mean(amber))
 return pd.Series(vals,index=m.base.index)

C=m.closemat.sort_index(); r21=C.pct_change(21,fill_method=None); dd63=C/C.rolling(63,min_periods=40).max()-1; D=((r21<0)&(dd63<=-.10)).astype(float); D[C.isna()]=np.nan; DR=D.to_numpy(float); ridx=D.index;rcols={c:i for i,c in enumerate(D.columns)}
def distress_knn(metric='jaccard',k=3,lookback=252,minobs=120):
 vals=[]
 for ix,d in enumerate(m.base.index):
  g=m.groups[d];ticks=g.ticker.tolist();ci=[rcols[t] for t in ticks];pos=ridx.searchsorted(d,'left');lo=max(0,pos-lookback);X=DR[lo:pos,:][:,ci];n=len(ticks);red=g.red.to_numpy(bool);green=g.green.to_numpy(bool);amber=g.core_amber.to_numpy(bool).copy(); counts=np.isfinite(X).sum(axis=0)
  for i in range(n):
   if counts[i]<minobs:continue
   scores=[]
   for j in range(n):
    if i==j or counts[j]<minobs:continue
    ok=np.isfinite(X[:,i])&np.isfinite(X[:,j]);
    if ok.sum()<minobs:continue
    a=X[ok,i]>0.5;b=X[ok,j]>0.5
    if metric=='jaccard':
     un=np.logical_or(a,b).sum(); sc=(np.logical_and(a,b).sum()/un) if un>=5 else np.nan
    else:
     if a.std()==0 or b.std()==0:sc=np.nan
     else:sc=np.corrcoef(a.astype(float),b.astype(float))[0,1]
    if np.isfinite(sc):scores.append((sc,j))
   if scores:
    chosen=[j for _,j in sorted(scores,reverse=True)[:k]]; stress=red[np.r_[i,chosen]].mean();
    if stress>=.5 and not green[i]:amber[i]=True
  vals.append(amber.mean())
  if ix%1000==0:print(metric,lookback,ix,flush=True)
 return pd.Series(vals,index=m.base.index)

variants={
 'raw_knn3_63':build_knn('raw',3,63,40),
 'raw_knn3_252':build_knn('raw',3,252,120),
 'resid_knn3_63':build_knn('resid',3,63,40),
 'resid_knn3_252':build_knn('resid',3,252,120),
 'resid_knn3_monthly126':monthly_knn(),
 'jaccard_knn3_252':distress_knn('jaccard',3,252,120),
 'jaccard_knn3_504':distress_knn('jaccard',3,504,240),
 'phi_knn3_252':distress_knn('phi',3,252,120),
}
rows=[]
for name,dam in variants.items():
 out=m.replay(dam,.30);out.to_csv(OUT/(name+'.csv')); rows.append({'variant':name,'full':m.metric_period(out.nav,m.base.index[0],m.base.index[-1]),'discovery':m.metric_period(out.nav,'2006-07-31','2015-12-31'),'validation':m.metric_period(out.nav,'2016-01-04','2026-07-31'),'fast':m.fast_diag(out),'defensive_sessions':int((out.allocation<.999999).sum())})
Path(OUT/'summary.json').write_text(json.dumps(rows,indent=2)); flat=[]
for r in rows:
 z={'variant':r['variant'],'defensive_sessions':r['defensive_sessions'],'fast_episodes':r['fast']['episodes'],'fast_beneficial_fraction':r['fast']['beneficial_fraction']}
 for p in ['full','discovery','validation']:
  for k,v in r[p].items():z[p+'_'+k]=v
 flat.append(z)
pd.DataFrame(flat).sort_values('full_cagr',ascending=False).to_csv(OUT/'summary.csv',index=False);print(pd.DataFrame(flat).sort_values('full_cagr',ascending=False).to_string(index=False))
