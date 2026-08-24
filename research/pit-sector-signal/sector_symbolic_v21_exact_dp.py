from __future__ import annotations
import pandas as pd,numpy as np,copy,math,json,importlib.util,sys
from dataclasses import dataclass
from pathlib import Path
ROOT=Path('/mnt/data');OUT=ROOT/'sector_symbolic_v21_exact_dp_out';OUT.mkdir(exist_ok=True)
# Load core data/controller semantics
s=importlib.util.spec_from_file_location('core','/mnt/data/sector_peer_core.py');v=importlib.util.module_from_spec(s);sys.modules['core21']=v;s.loader.exec_module(v)
sym=pd.read_csv(ROOT/'sector_symbolic_v5_out/symbolic_days.csv',parse_dates=['date']).set_index('date').reindex(v.base.index)
dam=pd.read_csv(ROOT/'sector_peer_v2_strict_out/damaged_breadth.csv',parse_dates=['date']).set_index('date').sec_ff12.reindex(v.base.index).astype(float)
from sentinel.controller.ldrc import LDRCState,ldrc_step

@dataclass
class PathState:
    binary: object; bfast: object; pfast: object; slow: object; ramp: object; ld: object
    baseprev: bool=False; stress_i: int|None=None; stress_d:int=0; stress_ret:float=0.0
    parent_current:float=1.0; native_current:float=1.0; pending_native:float=1.0
    final_current:float=1.0; pending_final:float=1.0; nav:float=1.0
    choices: tuple=()

def key(s):
    b=s.binary;bf=s.bfast;pf=s.pfast;sl=s.slow;rp=s.ramp;ld=s.ld
    # last_session is same for all states at a processed date, omit it.
    return (b.active,b.armed,b.entry_i,b.healthy_streak,
            bf.active,bf.armed,bf.entry_i,bf.healthy_streak,
            pf.active,pf.armed,pf.entry_i,pf.healthy_streak,
            sl.active,sl.entry_i,sl.healthy_streak,
            rp.phase,rp.healthy_streak,
            s.baseprev,s.stress_i,s.stress_d,
            round(s.parent_current,12),round(s.native_current,12),round(s.pending_native,12),
            round(s.final_current,12),round(s.pending_final,12),
            ld.recovery_episode,ld.divergence_latched,ld.recovery_streak,
            round(ld.previous_native_allocation,12),round(ld.previous_desired_allocation,12))

base=v.base;eq=base.shadow_equity.astype(float);oe=base.open_shadow_equity.astype(float);green=base.green.astype(float);stops=base.stops20.astype(float);wit20=base.witness_r20;wit40=base.witness_r40;r20=base.r20.astype(float);r40=base.r40.astype(float);r5=eq.pct_change(5);r10=eq.pct_change(10);dd=base.shadow_dd.astype(float)
r40hist=[]
init=PathState(v.pitmod.BinaryStress(),v.pitmod.FastState(base_mode=True),v.pitmod.FastState(base_mode=False),v.pitmod.SlowState(),v.pitmod.SentinelRamp(),LDRCState())
states={key(init):init}; state_counts=[]
for i,d in enumerate(base.index):
    r40i=float(r40.iloc[i]) if np.isfinite(r40.iloc[i]) else np.nan;r40hist.append(r40i)
    gr=float(green.iloc[i]);r20i=float(r20.iloc[i]) if np.isfinite(r20.iloc[i]) else np.nan;ddi=float(dd.iloc[i]);st=float(stops.iloc[i]);sp20=float(v.spy20.loc[d]) if np.isfinite(v.spy20.loc[d]) else np.nan
    status=str(sym.loc[d,'symbolic_status']) if pd.notna(sym.loc[d,'symbolic_status']) else 'impossible'
    opts=[True] if status=='inevitable' else ([False,True] if status=='controllable' else [False])
    nxt={}
    for old in states.values():
      # Today's realized return is determined by yesterday's pending allocations, before today's fast choice.
      nav0=old.nav; final_current=old.final_current; native_current=old.native_current
      if i>0:
        olda=old.final_current;newa=old.pending_final;pd0=base.index[i-1];bc0=float(v.bc.loc[pd0]);bc1=float(v.bc.loc[d]);bo1=float(v.bo.loc[d])
        if abs(newa-olda)<1e-15: factor=olda*float(eq.iloc[i]/eq.iloc[i-1])+(1-olda)*(bc1/bc0 if olda<1 else 1.)
        else:
          wo=float(oe.iloc[i]/eq.iloc[i-1]-1);wi=float(eq.iloc[i]/oe.iloc[i]-1);bov=bo1/bc0-1 if olda<1 else 0.;bi=bc1/bo1-1 if newa<1 else 0.
          factor=(1+olda*wo+(1-olda)*bov)*(1-v.pitmod.COST*abs(newa-olda))*(1+newa*wi+(1-newa)*bi)
        nav0*=factor; final_current=newa; native_current=old.pending_native
      for fast in opts:
        ns=copy.deepcopy(old);ns.nav=nav0;ns.final_current=final_current;ns.native_current=native_current
        healthy=np.isfinite(r20i) and r20i>0 and float(dam.iloc[i])<=.60 and gr>=.20
        regular=ns.binary.step(i,ddi,r20i,st);bf=ns.bfast.step(i,fast,ddi,healthy,entry_allowed=not regular);bstress=regular or bf
        if bstress:
          if not ns.baseprev:ns.stress_i=i
          ns.stress_d=i-ns.stress_i+1 if ns.stress_i is not None else 0;ns.stress_ret=eq.iloc[i]/eq.iloc[ns.stress_i]-1 if ns.stress_i is not None else 0.
        else:ns.stress_i=None;ns.stress_d=0;ns.stress_ret=0.
        ns.baseprev=bstress;pf=ns.pfast.step(i,fast,ddi,healthy,entry_allowed=True)
        se=(ns.stress_d>=30 and ns.stress_ret<=-.02 and np.isfinite(r40i) and r40i<=-.03 and float(dam.iloc[i])>=.75 and gr<=.25);ps=ns.slow.step(i,se,healthy);parent_next=0. if (pf or ps) else 1.
        native_next=ns.ramp.next_target(i,ns.parent_current,parent_next,r40hist,healthy)
        ld,dec=ldrc_step(session=str(d.date()),native_allocation=float(native_next),effective_native_allocation=float(ns.ld.previous_native_allocation),wc_drawdown=ddi,recent_r20=float(wit20.iloc[i]) if np.isfinite(wit20.iloc[i]) else None,recent_r40=float(wit40.iloc[i]) if np.isfinite(wit40.iloc[i]) else None,spy_r20=sp20 if np.isfinite(sp20) else None,state=ns.ld)
        ns.ld=ld;ns.pending_native=float(native_next);ns.pending_final=float(dec.desired_allocation);ns.parent_current=parent_next
        if status=='controllable':ns.choices=ns.choices+((str(d.date()),int(fast)),)
        k=key(ns);prior=nxt.get(k)
        if prior is None or ns.nav>prior.nav: nxt[k]=ns
    states=nxt;state_counts.append((str(d.date()),status,len(states)))
    if i%500==0 or status=='controllable':print(i,d.date(),status,'states',len(states),'best',max(s.nav for s in states.values()))
# terminal: last decision pending isn't executed, consistent existing replay; pick max nav
best=max(states.values(),key=lambda s:s.nav)
choice_map={pd.Timestamp(d):bool(x) for d,x in best.choices}
override=pd.Series(False,index=base.index)
override.loc[sym.symbolic_status.eq('inevitable')]=True
for d,x in choice_map.items(): override.loc[d]=x
out=v.replay(dam,override=override);out.to_csv(OUT/'exact_terminal_nav_oracle.csv')
Path(OUT/'choices.json').write_text(json.dumps(best.choices,indent=2));pd.DataFrame(state_counts,columns=['date','status','states']).to_csv(OUT/'state_counts.csv',index=False)

def metric(x,a=None,b=None):
 if a is not None:x=x.loc[(x.index>=pd.Timestamp(a))&(x.index<=pd.Timestamp(b))]
 yrs=(x.index[-1]-x.index[0]).days/365.2425;c=(x.iloc[-1]/x.iloc[0])**(1/yrs)-1;r=x.pct_change().dropna();return {'cagr':float(c),'sharpe':float(r.mean()/r.std(ddof=1)*np.sqrt(252)),'mdd':float((x/x.cummax()-1).min()),'multiple':float(x.iloc[-1]/x.iloc[0])}
res={'full':metric(out.nav),'discovery':metric(out.nav,'2006-07-31','2015-12-31'),'v1':metric(out.nav,'2016-01-04','2020-12-31'),'v2':metric(out.nav,'2021-01-04','2026-07-31'),'validation':metric(out.nav,'2016-01-04','2026-07-31'),'terminal_states':len(states),'choices':best.choices}
Path(OUT/'summary.json').write_text(json.dumps(res,indent=2));print(json.dumps(res,indent=2))
