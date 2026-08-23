from __future__ import annotations
import pandas as pd, numpy as np, json, importlib.util, sys, math
from pathlib import Path
ROOT=Path('/mnt/data'); OUT=ROOT/'sector_peer_v2_strict_out'; OUT.mkdir(exist_ok=True)
DIAG=ROOT/'strict_diag_d30_out/sector_diag.csv'; BASE=ROOT/'strict_diag_d30_out/sentinel_1p1_daily.csv'; CLOSES=ROOT/'strict_held_close_history.pkl'; SFP=ROOT/'recovered_spy_bil_partial.csv'
spec=importlib.util.spec_from_file_location('pitmod',str(ROOT/'pit_exp_currentcat_ff12.py')); pitmod=importlib.util.module_from_spec(spec); sys.modules['pitmod']=pitmod; spec.loader.exec_module(pitmod)
sys.path.insert(0,str(ROOT/'replay_source')); from sentinel.controller.ldrc import LDRCState, ldrc_step

diag=pd.read_csv(DIAG,parse_dates=['date']).sort_values(['date','ticker']).reset_index(drop=True)
for c in ['green','red']:
    if diag[c].dtype!=bool: diag[c]=diag[c].astype(str).str.lower().eq('true')
diag['core_amber']=(diag.own_dd<=-.10)|(diag.r21<=-.03)
diag['curkey']=diag.current_sector.fillna(''); m=diag.curkey.eq(''); diag.loc[m,'curkey']='UNK:'+diag.loc[m,'tid'].astype(str)
diag['ffkey']=diag.pit_sector.fillna(''); m=diag.ffkey.eq(''); diag.loc[m,'ffkey']='UNK:'+diag.loc[m,'tid'].astype(str)
groups={d:g.copy() for d,g in diag.groupby('date',sort=True)}
base=pd.read_csv(BASE,parse_dates=['date']).set_index('date').sort_index()

cols=['ticker','date','open','high','low','close','volume','closeadj','closeunadj','lastupdated']; sfp=pd.read_csv(SFP,header=None,names=cols); sfp.date=pd.to_datetime(sfp.date)
for c in ['open','close','closeadj']: sfp[c]=pd.to_numeric(sfp[c],errors='coerce')
spy=sfp[sfp.ticker.eq('SPY')].drop_duplicates('date').sort_values('date').set_index('date')
idx=base.index.union(spy.index).sort_values(); slog=np.log(spy.closeadj).reindex(idx).interpolate(method='time').ffill().bfill(); spy_close=np.exp(slog); spy_ret_full=spy_close.pct_change(); spy_r20=spy_close.pct_change(20).reindex(base.index); spy_volacc=(spy_ret_full.rolling(5).std(ddof=1)/spy_ret_full.rolling(20).std(ddof=1)-1).reindex(base.index)
bil=sfp[sfp.ticker.eq('BIL')].drop_duplicates('date').sort_values('date').set_index('date').copy(); bil['adj_open']=bil.open*bil.closeadj/bil.close
idx=base.index.union(bil.index).sort_values(); blog=np.log(bil.closeadj).reindex(idx).interpolate(method='time').ffill().bfill(); bil_close=np.exp(blog).reindex(base.index); bratio=(bil.adj_open/bil.closeadj).reindex(idx).interpolate(method='time').ffill().bfill(); bil_open=(np.exp(blog)*bratio).reindex(base.index)

closemat=pd.read_pickle(CLOSES).sort_index(); retmat=closemat.pct_change(fill_method=None); ridx=retmat.index; rcols={c:i for i,c in enumerate(retmat.columns)}; R=retmat.to_numpy(np.float32); M=spy_ret_full.reindex(ridx).to_numpy(float)

def damaged_by_key(key):
    x=diag[['date','tid','green','red','core_amber',key]].copy(); s=x.groupby(['date',key],dropna=False).red.agg(['sum','count']).reset_index(); s['stress']=s['sum']/s['count']; x=x.merge(s[['date',key,'stress']],on=['date',key],how='left'); x['amber']=x.core_amber|((x.stress>=.5)&(~x.green)); return x.groupby('date').amber.mean().reindex(base.index)

def corr_mats(d,ticks,lookback=126,minobs=60):
    pos=ridx.searchsorted(d,'left'); lo=max(0,pos-lookback); ci=[rcols[t] for t in ticks]; X=R[lo:pos,:][:,ci].astype(float); mm=M[lo:pos]
    counts=np.isfinite(X).sum(axis=0); raw=pd.DataFrame(X,columns=ticks).corr(min_periods=minobs).to_numpy()
    RX=np.full_like(X,np.nan,float)
    vm=np.isfinite(mm); mv=np.nanvar(mm[vm],ddof=1) if vm.sum()>2 else np.nan
    if np.isfinite(mv) and mv>0:
        for j in range(X.shape[1]):
            ok=vm & np.isfinite(X[:,j])
            if ok.sum()>=minobs:
                xv=X[ok,j]; m0=mm[ok]; beta=np.cov(xv,m0,ddof=1)[0,1]/np.var(m0,ddof=1); RX[ok,j]=xv-beta*m0
    resid=pd.DataFrame(RX,columns=ticks).corr(min_periods=minobs).to_numpy()
    neg=np.minimum(X,0.0); negpart=pd.DataFrame(neg,columns=ticks).corr(min_periods=minobs).to_numpy()
    md=(mm<0)&np.isfinite(mm); down=np.full((len(ticks),len(ticks)),np.nan)
    if md.sum()>=25: down=pd.DataFrame(X[md],columns=ticks).corr(min_periods=25).to_numpy()
    return {'raw':raw,'resid':resid,'negpart':negpart,'downmkt':down},counts

def peer_damage(C,counts,g,k=3,weighted=False,bonus=0.0,minobs=60):
    n=len(g); red=g.red.to_numpy(bool); green=g.green.to_numpy(bool); amber=g.core_amber.to_numpy(bool).copy(); ff=g.ffkey.to_numpy(str)
    for i in range(n):
        if counts[i]<minobs: continue
        c=C[i].copy(); c[i]=np.nan; ok=np.where(np.isfinite(c)&(counts>=minobs))[0]
        if not len(ok): continue
        score=c[ok].copy()
        if bonus: score += bonus*(ff[ok]==ff[i])
        chosen=ok[np.argsort(score)[::-1]][:k]
        if weighted:
            w=np.clip(c[chosen],0,None); denom=1.0+w.sum(); stress=(float(red[i])+float((w*red[chosen]).sum()))/denom if denom>0 else float(red[i])
        else: stress=red[np.r_[i,chosen]].mean()
        if stress>=.5 and not green[i]: amber[i]=True
    return amber.mean()

configs={}
for k in [2,3,4,5]: configs[f'raw_knn{k}']=('raw',k,False,0.0,60)
for k in [2,3,4,5]: configs[f'resid_knn{k}']=('resid',k,False,0.0,60)
for k in [3,5]: configs[f'negpart_knn{k}']=('negpart',k,False,0.0,60)
for k in [3,5]: configs[f'downmkt_knn{k}']=('downmkt',k,False,0.0,25)
for k in [3,5,8]: configs[f'resid_weighted{k}']=('resid',k,True,0.0,60)
for b in [0.10,0.20,0.30]: configs[f'hybrid_resid_ff12_k3_b{int(b*100):02d}']=('resid',3,False,b,60)
vals={k:[] for k in configs}
for ix,d in enumerate(base.index):
    g=groups[d]; ticks=g.ticker.tolist(); mats,counts=corr_mats(d,ticks)
    for name,(kind,k,w,b,mo) in configs.items(): vals[name].append(peer_damage(mats[kind],counts,g,k,w,b,mo))
    if ix%500==0: print('signals',ix,str(d.date()),flush=True)
variants={'current_sharadar':damaged_by_key('curkey'),'sec_ff12':damaged_by_key('ffkey'),'sector_neutral':diag.groupby('date').core_amber.mean().reindex(base.index)}
for name,v in vals.items(): variants[name]=pd.Series(v,index=base.index,name=name)

def replay(damaged,delta=.30):
    damaged=damaged.reindex(base.index); eq=base.shadow_equity.astype(float); oe=base.open_shadow_equity.astype(float); green=base.green.astype(float); stops=base.stops20.astype(float); wit20=base.witness_r20; wit40=base.witness_r40; r20=base.r20.astype(float); r40=base.r40.astype(float); r5=eq.pct_change(5); r10=eq.pct_change(10); dd=base.shadow_dd.astype(float)
    binary=pitmod.BinaryStress(); bfast=pitmod.FastState(base_mode=True); pfast=pitmod.FastState(base_mode=False); slow=pitmod.SlowState(); ramp=pitmod.SentinelRamp(); ld=LDRCState(); baseprev=False; stress_i=None; stress_d=0; stress_ret=0.; parent_current=1.; native_current=pending_native=1.; final_current=pending_final=1.; nav=1.; prev_eq=None; r40hist=[]; dh=[]; rows=[]
    for i,d in enumerate(base.index):
        dam=float(damaged.iloc[i]); gr=float(green.iloc[i]); dh.append(dam); r40i=float(r40.iloc[i]) if np.isfinite(r40.iloc[i]) else np.nan; r40hist.append(r40i); d5=dam-dh[-6] if len(dh)>=6 else np.nan; sp20=float(spy_r20.loc[d]) if np.isfinite(spy_r20.loc[d]) else np.nan; va=float(spy_volacc.loc[d]) if np.isfinite(spy_volacc.loc[d]) else np.nan; r5i=float(r5.iloc[i]) if np.isfinite(r5.iloc[i]) else np.nan; r10i=float(r10.iloc[i]) if np.isfinite(r10.iloc[i]) else np.nan; r20i=float(r20.iloc[i]) if np.isfinite(r20.iloc[i]) else np.nan; ddi=float(dd.iloc[i]); st=float(stops.iloc[i])
        fast=(ddi<=-.10 and dam>=.85 and gr<=.20 and ((np.isfinite(r5i) and r5i<=-.05) or (np.isfinite(r10i) and r10i<=-.08)) and np.isfinite(d5) and d5>=delta and np.isfinite(va) and va>=.04 and ((np.isfinite(sp20) and sp20<=-.01) or (np.isfinite(r10i) and r10i<=-.10)))
        healthy=np.isfinite(r20i) and r20i>0 and dam<=.60 and gr>=.20; regular=binary.step(i,ddi,r20i,st); bf=bfast.step(i,fast,ddi,healthy,entry_allowed=not regular); bstress=regular or bf
        if bstress:
            if not baseprev: stress_i=i
            stress_d=i-stress_i+1 if stress_i is not None else 0; stress_ret=eq.iloc[i]/eq.iloc[stress_i]-1 if stress_i is not None else 0.
        else: stress_i=None; stress_d=0; stress_ret=0.
        baseprev=bstress; pf=pfast.step(i,fast,ddi,healthy,entry_allowed=True); se=(stress_d>=30 and stress_ret<=-.02 and np.isfinite(r40i) and r40i<=-.03 and dam>=.75 and gr<=.25); ps=slow.step(i,se,healthy); parent_next=0. if (pf or ps) else 1.; native_next=ramp.next_target(i,parent_current,parent_next,r40hist,healthy)
        ld,dec=ldrc_step(session=str(d.date()),native_allocation=float(native_next),effective_native_allocation=float(ld.previous_native_allocation),wc_drawdown=ddi,recent_r20=float(wit20.iloc[i]) if np.isfinite(wit20.iloc[i]) else None,recent_r40=float(wit40.iloc[i]) if np.isfinite(wit40.iloc[i]) else None,spy_r20=sp20 if np.isfinite(sp20) else None,state=ld); final_next=float(dec.desired_allocation)
        if prev_eq is not None:
            old=final_current; new=pending_final; pd0=base.index[i-1]; bc0=float(bil_close.loc[pd0]); bc1=float(bil_close.loc[d]); bo1=float(bil_open.loc[d])
            if abs(new-old)<1e-15: wf=float(eq.iloc[i]/prev_eq); bfct=bc1/bc0 if old<1 else 1.; factor=old*wf+(1-old)*bfct
            else:
                wo=float(oe.iloc[i]/prev_eq-1); wi=float(eq.iloc[i]/oe.iloc[i]-1); bo=bo1/bc0-1 if old<1 else 0.; bi=bc1/bo1-1 if new<1 else 0.; factor=(1+old*wo+(1-old)*bo)*(1-pitmod.COST*abs(new-old))*(1+new*wi+(1-new)*bi)
            nav*=factor; final_current=new; native_current=pending_native
        else: final_current=pending_final; native_current=pending_native
        pending_native=float(native_next); pending_final=final_next; parent_current=parent_next; prev_eq=float(eq.iloc[i]); rows.append((d,nav,final_current,native_current,parent_current,fast,stress_d,bool(dec.divergence_latched)))
    return pd.DataFrame(rows,columns=['date','nav','allocation','native_allocation','parent_allocation','fast','stress_duration','ld_latched']).set_index('date')

def metric_period(curve,start,end):
    x=curve.loc[(curve.index>=pd.Timestamp(start))&(curve.index<=pd.Timestamp(end))]; yrs=(x.index[-1]-x.index[0]).days/365.2425; cagr=(x.iloc[-1]/x.iloc[0])**(1/yrs)-1; rr=x.pct_change().dropna(); return {'cagr':float(cagr),'sharpe':float(rr.mean()/rr.std(ddof=1)*np.sqrt(252)),'mdd':float((x/x.cummax()-1).min()),'multiple':float(x.iloc[-1]/x.iloc[0])}
def metric_years(curve,y): cutoff=curve.index[-1]-pd.DateOffset(years=y); start=curve.index[curve.index>=cutoff][0]; return metric_period(curve,start,curve.index[-1])
def fast_diag(out):
    f=out.fast.astype(bool); starts=out.index[f & ~f.shift(1,fill_value=False)]; eq=base.shadow_equity.astype(float); rows=[]
    for d in starts:
        i=base.index.get_loc(d); j=min(i+20,len(base.index)-1); d2=base.index[j]; sr=float(eq.iloc[j]/eq.iloc[i]-1); br=float(bil_close.iloc[j]/bil_close.iloc[i]-1); rows.append((str(d.date()),sr,br,br-sr))
    if not rows:return {'episodes':0,'beneficial_fraction':None,'mean_bil_minus_shadow20':None}
    aa=np.array([r[3] for r in rows]); return {'episodes':len(rows),'beneficial_fraction':float((aa>0).mean()),'mean_bil_minus_shadow20':float(aa.mean()),'episodes_detail':rows}

summary=[]; curves={}
for name,dam in variants.items():
    out=replay(dam,.30); curves[name]=out; out.to_csv(OUT/f'{name}.csv')
    row={'variant':name,'full':metric_period(out.nav,base.index[0],base.index[-1]),'discovery_2006_2015':metric_period(out.nav,'2006-07-31','2015-12-31'),'validation_2016_2026':metric_period(out.nav,'2016-01-04','2026-07-31'),'trailing5':metric_years(out.nav,5),'trailing10':metric_years(out.nav,10),'defensive_sessions':int((out.allocation<.999999).sum()),'fast_signal_sessions':int(out.fast.sum()),'fast_diagnostic':fast_diag(out)}; summary.append(row)
(Path(OUT/'summary.json')).write_text(json.dumps(summary,indent=2)); flat=[]
for r in summary:
    z={'variant':r['variant'],'defensive_sessions':r['defensive_sessions'],'fast_signal_sessions':r['fast_signal_sessions'],'fast_episodes':r['fast_diagnostic']['episodes'],'fast_beneficial_fraction':r['fast_diagnostic']['beneficial_fraction'],'fast_mean_bil_minus_shadow20':r['fast_diagnostic']['mean_bil_minus_shadow20']}
    for p in ['full','discovery_2006_2015','validation_2016_2026','trailing5','trailing10']:
        for k,v in r[p].items():z[p+'_'+k]=v
    flat.append(z)
pd.DataFrame(flat).sort_values('full_cagr',ascending=False).to_csv(OUT/'summary.csv',index=False); pd.DataFrame({k:v for k,v in variants.items()}).to_csv(OUT/'damaged_breadth.csv')
print(pd.DataFrame(flat).sort_values('full_cagr',ascending=False)[['variant','full_cagr','full_sharpe','full_mdd','discovery_2006_2015_cagr','validation_2016_2026_cagr','fast_episodes','fast_beneficial_fraction']].to_string(index=False))
