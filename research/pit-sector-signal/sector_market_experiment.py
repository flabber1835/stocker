from __future__ import annotations
import pandas as pd, numpy as np, math, json, importlib.util, sys
from pathlib import Path
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform

ROOT=Path('/mnt/data')
DIAG=ROOT/'pit_sector_diag_full_out/sector_diag.csv'
BASE=ROOT/'pit_exp_currentcat_ff12_out/sentinel_1p1_daily.csv'
CLOSES=ROOT/'held_close_history.pkl'
SFP_PART=ROOT/'recovered_spy_bil_partial.csv'
OUT=ROOT/'sector_market_experiment'
OUT.mkdir(exist_ok=True)

spec=importlib.util.spec_from_file_location('pitmod',str(ROOT/'pit_exp_currentcat_ff12.py'))
pitmod=importlib.util.module_from_spec(spec); sys.modules['pitmod']=pitmod; spec.loader.exec_module(pitmod)
sys.path.insert(0,str(ROOT/'replay_source'))
from sentinel.controller.ldrc import LDRCState, ldrc_step

diag=pd.read_csv(DIAG,parse_dates=['date']).sort_values(['date','ticker']).reset_index(drop=True)
for c in ['green','red']:
    if diag[c].dtype != bool: diag[c]=diag[c].astype(str).str.lower().eq('true')
diag['core_amber']=(diag['own_dd']<=-0.10)|(diag['r21']<=-0.03)
diag['current_key']=diag['current_sector'].fillna('')
m=diag.current_key.eq(''); diag.loc[m,'current_key']='UNK:'+diag.loc[m,'tid'].astype(str)
diag['ff12_key']=diag['pit_sector'].fillna('')
m=diag.ff12_key.eq(''); diag.loc[m,'ff12_key']='UNK:'+diag.loc[m,'tid'].astype(str)

groups={d:g.copy() for d,g in diag.groupby('date',sort=True)}
base=pd.read_csv(BASE,parse_dates=['date']).set_index('date').sort_index()
cols=['ticker','date','open','high','low','close','volume','closeadj','closeunadj','lastupdated']
sfp=pd.read_csv(SFP_PART,header=None,names=cols)
sfp['date']=pd.to_datetime(sfp.date)
for c in ['open','close','closeadj']: sfp[c]=pd.to_numeric(sfp[c],errors='coerce')
spy=sfp[sfp.ticker.eq('SPY')].drop_duplicates('date').sort_values('date').set_index('date')
idx=base.index.union(spy.index).sort_values(); spy_log=np.log(spy.closeadj).reindex(idx).interpolate(method='time').ffill().bfill()
spy_close=np.exp(spy_log).reindex(base.index); spy_ret=spy_close.pct_change(); spy_r20=spy_close.pct_change(20)
spy_volacc=spy_ret.rolling(5).std(ddof=1)/spy_ret.rolling(20).std(ddof=1)-1
bil=sfp[sfp.ticker.eq('BIL')].drop_duplicates('date').sort_values('date').set_index('date').copy(); bil['adj_open']=bil.open*bil.closeadj/bil.close
idx=base.index.union(bil.index).sort_values(); blog=np.log(bil.closeadj).reindex(idx).interpolate(method='time').ffill().bfill()
bil_close=np.exp(blog).reindex(base.index); bratio=(bil.adj_open/bil.closeadj).reindex(idx).interpolate(method='time').ffill().bfill(); bil_open=(np.exp(blog)*bratio).reindex(base.index)

closemat=pd.read_pickle(CLOSES).sort_index(); retmat=closemat.pct_change(fill_method=None); ridx=retmat.index; rcols={c:i for i,c in enumerate(retmat.columns)}; R=retmat.to_numpy(np.float32)

def damaged_by_key(keycol):
    x=diag[['date','tid','green','red','core_amber',keycol]].copy()
    stat=x.groupby(['date',keycol],dropna=False).red.agg(['sum','count']).reset_index(); stat['stress']=stat['sum']/stat['count']
    x=x.merge(stat[['date',keycol,'stress']],on=['date',keycol],how='left')
    x['amber']=x.core_amber|((x.stress>=0.5)&(~x.green))
    return x.groupby('date').amber.mean().reindex(base.index)

def corr_for(d,ticks,lookback=126,minobs=60):
    pos=ridx.searchsorted(d,'left'); lo=max(0,pos-lookback); ci=[rcols[t] for t in ticks]
    X=R[lo:pos,:][:,ci].astype(float); C=pd.DataFrame(X,columns=ticks).corr(min_periods=minobs).to_numpy(); counts=np.isfinite(X).sum(axis=0)
    return C,counts

def hard_corr(k=8,lookback=126,minobs=60):
    vals=[]
    for d in base.index:
        g=groups[d]; ticks=g.ticker.tolist(); n=len(ticks); C,counts=corr_for(d,ticks,lookback,minobs); valid=np.where(counts>=minobs)[0]; labs=np.full(n,-1,int)
        if len(valid)>=2:
            A=C[np.ix_(valid,valid)]; A=np.nan_to_num(A,nan=0.0,posinf=1.0,neginf=-1.0); A=np.clip(A,-1,1); np.fill_diagonal(A,1)
            D=1-A; D=(D+D.T)/2; np.fill_diagonal(D,0); kk=min(k,len(valid))
            ll=np.ones(len(valid),int) if kk<=1 else fcluster(linkage(squareform(D,checks=False),method='average'),t=kk,criterion='maxclust')
            labs[valid]=ll
        nxt=max(1,labs.max()+1)
        for j in range(n):
            if labs[j]<0: labs[j]=nxt; nxt+=1
        red=g.red.to_numpy(bool); green=g.green.to_numpy(bool); core=g.core_amber.to_numpy(bool); stress=np.zeros(n)
        for lab in np.unique(labs):
            mm=labs==lab; stress[mm]=red[mm].mean()
        vals.append((core|((stress>=.5)&(~green))).mean())
    return pd.Series(vals,index=base.index,name=f'corr{k}')

def monthly_corr(k=8,lookback=126,minobs=60):
    vals=[]; assignments={}; current_month=None; serial=0
    for d in base.index:
        g=groups[d]; ticks=g.ticker.tolist(); n=len(ticks); month=(d.year,d.month); C,counts=corr_for(d,ticks,lookback,minobs)
        if month!=current_month:
            assignments={}; current_month=month; serial+=1; valid=np.where(counts>=minobs)[0]; labs=np.full(n,-1,int)
            if len(valid)>=2:
                A=C[np.ix_(valid,valid)]; A=np.nan_to_num(A,nan=0.0,posinf=1.0,neginf=-1.0); A=np.clip(A,-1,1); np.fill_diagonal(A,1); D=1-A; D=(D+D.T)/2; np.fill_diagonal(D,0); kk=min(k,len(valid))
                ll=np.ones(len(valid),int) if kk<=1 else fcluster(linkage(squareform(D,checks=False),method='average'),t=kk,criterion='maxclust'); labs[valid]=ll
            nxt=max(1,labs.max()+1)
            for j,t in enumerate(ticks):
                assignments[t]=f'{serial}:U:{t}' if labs[j]<0 else f'{serial}:C:{int(labs[j])}'
        tick_pos={t:i for i,t in enumerate(ticks)}
        for i,t in enumerate(ticks):
            if t in assignments: continue
            if counts[i]<minobs: assignments[t]=f'{serial}:U:{t}'; continue
            scores={}
            for ot in ticks:
                if ot==t or ot not in assignments: continue
                j=tick_pos[ot]; c=C[i,j]
                if not np.isfinite(c): continue
                lab=assignments[ot]
                if ':C:' not in lab: continue
                scores.setdefault(lab,[]).append(float(c))
            assignments[t]=max(scores,key=lambda lab:np.mean(scores[lab])) if scores else f'{serial}:U:{t}'
        labs=np.array([assignments[t] for t in ticks],object); red=g.red.to_numpy(bool); green=g.green.to_numpy(bool); core=g.core_amber.to_numpy(bool); stress=np.zeros(n)
        for lab in set(labs):
            mm=labs==lab; stress[mm]=red[mm].mean()
        vals.append((core|((stress>=.5)&(~green))).mean())
    return pd.Series(vals,index=base.index,name='corr8_monthly')

def knn(peers=3,lookback=126,minobs=60):
    vals=[]
    for d in base.index:
        g=groups[d]; ticks=g.ticker.tolist(); n=len(ticks); C,counts=corr_for(d,ticks,lookback,minobs); red=g.red.to_numpy(bool); green=g.green.to_numpy(bool); amber=g.core_amber.to_numpy(bool).copy()
        for i in range(n):
            if counts[i]<minobs: continue
            c=C[i].copy(); c[i]=np.nan; ok=np.where(np.isfinite(c)&(counts>=minobs))[0]
            if not len(ok): continue
            chosen=ok[np.argsort(c[ok])[::-1]][:peers]; ix=np.r_[i,chosen]
            if red[ix].mean()>=0.5 and not green[i]: amber[i]=True
        vals.append(amber.mean())
    return pd.Series(vals,index=base.index,name=f'knn{peers}')

def replay(damaged,delta=.30):
    damaged=damaged.reindex(base.index); assert damaged.notna().all()
    eq=base.shadow_equity.astype(float); oe=base.open_shadow_equity.astype(float); green=base.green.astype(float); stops=base.stops20.astype(float); wit20=base.witness_r20; wit40=base.witness_r40; r20=base.r20.astype(float); r40=base.r40.astype(float); r5=eq.pct_change(5); r10=eq.pct_change(10); dd=base.shadow_dd.astype(float)
    binary=pitmod.BinaryStress(); bfast=pitmod.FastState(base_mode=True); pfast=pitmod.FastState(base_mode=False); slow=pitmod.SlowState(); ramp=pitmod.SentinelRamp(); ld=LDRCState()
    baseprev=False; stress_i=None; stress_d=0; stress_ret=0.; parent_current=1.; native_current=pending_native=1.; final_current=pending_final=1.; nav=1.; prev_eq=None; r40hist=[]; dh=[]; rows=[]
    for i,d in enumerate(base.index):
        dam=float(damaged.iloc[i]); gr=float(green.iloc[i]); dh.append(dam); r40i=float(r40.iloc[i]) if np.isfinite(r40.iloc[i]) else np.nan; r40hist.append(r40i); d5=dam-dh[-6] if len(dh)>=6 else np.nan; sp20=float(spy_r20.loc[d]) if np.isfinite(spy_r20.loc[d]) else np.nan; va=float(spy_volacc.loc[d]) if np.isfinite(spy_volacc.loc[d]) else np.nan; r5i=float(r5.iloc[i]) if np.isfinite(r5.iloc[i]) else np.nan; r10i=float(r10.iloc[i]) if np.isfinite(r10.iloc[i]) else np.nan; r20i=float(r20.iloc[i]) if np.isfinite(r20.iloc[i]) else np.nan; ddi=float(dd.iloc[i]); st=float(stops.iloc[i])
        fast=(ddi<=-.10 and dam>=.85 and gr<=.20 and ((np.isfinite(r5i) and r5i<=-.05) or (np.isfinite(r10i) and r10i<=-.08)) and np.isfinite(d5) and d5>=delta and np.isfinite(va) and va>=.04 and ((np.isfinite(sp20) and sp20<=-.01) or (np.isfinite(r10i) and r10i<=-.10)))
        healthy=np.isfinite(r20i) and r20i>0 and dam<=.60 and gr>=.20
        regular=binary.step(i,ddi,r20i,st); bf=bfast.step(i,fast,ddi,healthy,entry_allowed=not regular); bstress=regular or bf
        if bstress:
            if not baseprev: stress_i=i
            stress_d=i-stress_i+1 if stress_i is not None else 0; stress_ret=eq.iloc[i]/eq.iloc[stress_i]-1 if stress_i is not None else 0.
        else: stress_i=None; stress_d=0; stress_ret=0.
        baseprev=bstress; pf=pfast.step(i,fast,ddi,healthy,entry_allowed=True); se=(stress_d>=30 and stress_ret<=-.02 and np.isfinite(r40i) and r40i<=-.03 and dam>=.75 and gr<=.25); ps=slow.step(i,se,healthy); parent_next=0. if (pf or ps) else 1.; native_next=ramp.next_target(i,parent_current,parent_next,r40hist,healthy)
        ld,dec=ldrc_step(session=str(d.date()),native_allocation=float(native_next),effective_native_allocation=float(ld.previous_native_allocation),wc_drawdown=ddi,recent_r20=float(wit20.iloc[i]) if np.isfinite(wit20.iloc[i]) else None,recent_r40=float(wit40.iloc[i]) if np.isfinite(wit40.iloc[i]) else None,spy_r20=sp20 if np.isfinite(sp20) else None,state=ld); final_next=float(dec.desired_allocation)
        if prev_eq is not None:
            old=final_current; new=pending_final; pd0=base.index[i-1]; bc0=float(bil_close.loc[pd0]); bc1=float(bil_close.loc[d]); bo1=float(bil_open.loc[d])
            if abs(new-old)<1e-15:
                wf=float(eq.iloc[i]/prev_eq); bfct=bc1/bc0 if old<1 else 1.; factor=old*wf+(1-old)*bfct
            else:
                wo=float(oe.iloc[i]/prev_eq-1); wi=float(eq.iloc[i]/oe.iloc[i]-1); bo=bo1/bc0-1 if old<1 else 0.; bi=bc1/bo1-1 if new<1 else 0.; factor=(1+old*wo+(1-old)*bo)*(1-pitmod.COST*abs(new-old))*(1+new*wi+(1-new)*bi)
            nav*=factor; final_current=new; native_current=pending_native
        else: final_current=pending_final; native_current=pending_native
        pending_native=float(native_next); pending_final=final_next; parent_current=parent_next; prev_eq=float(eq.iloc[i]); rows.append((d,nav,final_current,native_current,parent_current,fast,stress_d,bool(dec.divergence_latched)))
    return pd.DataFrame(rows,columns=['date','nav','allocation','native_allocation','parent_allocation','fast','stress_duration','ld_latched']).set_index('date')

def metric(curve,years=None):
    if years is not None:
        cutoff=curve.index[-1]-pd.DateOffset(years=years); start=curve.index[curve.index>=cutoff][0]; curve=curve.loc[start:]
    yrs=(curve.index[-1]-curve.index[0]).days/365.2425; cagr=(curve.iloc[-1]/curve.iloc[0])**(1/yrs)-1; rr=curve.pct_change().dropna(); shp=rr.mean()/rr.std(ddof=1)*np.sqrt(252); mdd=(curve/curve.cummax()-1).min(); return dict(start=str(curve.index[0].date()),end=str(curve.index[-1].date()),cagr=float(cagr),sharpe=float(shp),mdd=float(mdd),multiple=float(curve.iloc[-1]/curve.iloc[0]))

variants={}
variants['current_sharadar']=damaged_by_key('current_key')
variants['sec_ff12']=damaged_by_key('ff12_key')
variants['sector_neutral']=diag.groupby('date').core_amber.mean().reindex(base.index)
variants['corr6_daily']=hard_corr(6)
variants['corr8_daily']=hard_corr(8)
variants['corr10_daily']=hard_corr(10)
variants['corr8_monthly']=monthly_corr(8)
variants['nearest3_daily']=knn(3)
variants['sic_sharadar_like']=pd.read_csv(ROOT/'sharadar_like_sic_damaged.csv',parse_dates=['date']).set_index('date')['damaged'].reindex(base.index)
variants['corr8_63d']=hard_corr(8,lookback=63,minobs=40)
variants['corr8_252d']=hard_corr(8,lookback=252,minobs=120)
variants['nearest2_126d']=knn(2,lookback=126,minobs=60)
variants['nearest4_126d']=knn(4,lookback=126,minobs=60)
variants['nearest3_63d']=knn(3,lookback=63,minobs=40)
variants['nearest3_252d']=knn(3,lookback=252,minobs=120)

summary=[]
for delta in [0.30,0.40]:
    for name,dam in variants.items():
        out=replay(dam,delta); out.to_csv(OUT/f'{name}_d{int(delta*100):02d}.csv')
        row={'variant':name,'damaged_delta5_threshold':delta,'defensive_sessions':int((out.allocation<.999999).sum()),'fast_signal_sessions':int(out.fast.sum()),'allocation_transitions':int((out.allocation.diff().fillna(0).abs()>1e-12).sum())}
        for y in [5,10,15,20]:
            mm=metric(out.nav,y)
            for k,v in mm.items(): row[f'{y}y_{k}']=v
        summary.append(row)
pd.DataFrame(summary).to_csv(OUT/'summary.csv',index=False)
(Path(OUT/'summary.json')).write_text(json.dumps(summary,indent=2))
pd.DataFrame({k:v for k,v in variants.items()}).to_csv(OUT/'damaged_breadth.csv')
print(pd.DataFrame(summary)[['variant','damaged_delta5_threshold','20y_cagr','20y_sharpe','20y_mdd','20y_multiple','defensive_sessions','fast_signal_sessions']].to_string(index=False))
