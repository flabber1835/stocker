from __future__ import annotations
from pathlib import Path
import pandas as pd, numpy as np, json, time, sys, importlib.util
from dataclasses import dataclass, asdict

ROOT=Path('/mnt/data/selective_firewall'); OUT=ROOT/'results_v2_fixed'; OUT.mkdir(parents=True,exist_ok=True)
ORIG=ROOT/'run_firewall_experiment.py'
spec=importlib.util.spec_from_file_location('fw_orig',ORIG)
fw=importlib.util.module_from_spec(spec);sys.modules['fw_orig']=fw;spec.loader.exec_module(fw)
COST=0.001

@dataclass(frozen=True)
class Cfg:
    name:str
    selection:str='none' # none, rolling, cohort, threshold
    trigger:float=.10
    release:float=.05
    rank_n:int=5
    cut_scale:float=.25
    amber_scale:float=.50
    refresh_depth:float=.05 # 99 disables refresh
    min_change:int=10
    recovery_step:float=.50
    entry_policy:str='allow' # allow, weak, position_cap, systemic
    position_caps:tuple=(20,17,12)
    systemic_trigger:float|None=None
    systemic_breadth:float=2.0
    systemic_alloc:float=.25
    systemic_min_hold:int=20
    systemic_confirmation:int=3
    bridge_asset:str|None=None
    bridge_cap:float=0.
    bridge_leverage:float=2.
    bridge_target_beta:float=.90
    bridge_max_days:int=40


def precompute(core,panel,entries):
    default=fw.Config('pre')
    pg={}
    for dt,g in panel.groupby('date',sort=True):
        x,sec=fw.position_features(g,default)
        pg[dt]=dict(episode=x.episode.to_numpy(np.int64),ticker=x.ticker.astype(str).to_numpy(),sector=x.sector.astype(str).to_numpy(),
                    weight=x.weight_equity.to_numpy(float),contribution=x.contribution.to_numpy(float),green=x.green.to_numpy(bool),
                    red=x.red.to_numpy(bool),amber=x.amber.to_numpy(bool),priority=x.priority.to_numpy(float),r21=x.r21.to_numpy(float),
                    sector_stress=sec.to_dict())
    eg={}
    for dt,g in entries.groupby('decision_date',sort=True):
        eg[dt]=dict(episode=g.episode.to_numpy(np.int64),ticker=g.ticker.astype(str).to_numpy(),sector=g.sector.astype(str).to_numpy(),
                    recent21=g.recent21.to_numpy(float),planned_weight=g.planned_weight.to_numpy(float),entry_contribution=g.entry_contribution.to_numpy(float))
    return pg,eg


def metrics(nav,dates):
    s=pd.Series(nav,index=dates);return fw.metrics(s)


def simulate(core,pg,eg,diag,cfg,detail=False):
    dates=core.index;n=len(dates);nav=np.ones(n);records=[];trans=[]
    q={};last_change={};protected=set();stress=False;last_refresh_dd=0.;
    systemic=False;sys_armed=True;sys_enter=-10**9;sys_streak=0;core_alloc=1.;prev_core_alloc=1.
    bridge_armed=False;bridge_days=0;prev_bridge=0.
    turnover=0.;cost_sum=0.;blocked=0;bridge_entries=0;stress_days=0;sys_days=0;sum_stock=0.;sum_bridge=0.;sum_count=0.;pres=[]
    empty=dict(episode=np.array([],np.int64),ticker=np.array([],object),sector=np.array([],object),weight=np.array([],float),contribution=np.array([],float),green=np.array([],bool),red=np.array([],bool),amber=np.array([],bool),priority=np.array([],float),r21=np.array([],float),sector_stress={})
    emptye=dict(episode=np.array([],np.int64),ticker=np.array([],object),sector=np.array([],object),recent21=np.array([],float),planned_weight=np.array([],float),entry_contribution=np.array([],float))
    residual=diag.residual.reindex(dates).fillna(0).to_numpy(float)
    core_exposure=core.exposure.to_numpy(float)
    for i in range(n-1):
        dt=dates[i];row=core.iloc[i];dd=float(row.dd);r20=float(row.r20) if pd.notna(row.r20) else np.nan
        was_stress=stress
        if dd<=-cfg.trigger:stress=True
        elif stress and dd<=-cfg.release:stress=True
        else:stress=False
        d=pg.get(dt,empty);m=len(d['episode']);eps=d['episode'];ep_set=set(map(int,eps))
        # Retire disappeared episodes from controller state.
        protected.intersection_update(ep_set)
        damaged_breadth=float(d['amber'].mean()) if m else 0.;healthy=np.isfinite(r20) and r20>0 and int(row.stops20)<=2
        raw_sys_signal=(cfg.systemic_trigger is not None) and ((dd<=-cfg.systemic_trigger) or (stress and damaged_breadth>=cfg.systemic_breadth))
        # Hysteresis: after a defensive episode exits, the trigger must first clear before it can fire again.
        if cfg.systemic_trigger is not None and dd>-cfg.systemic_trigger and (cfg.systemic_breadth>=2.0 or damaged_breadth<max(0.0,cfg.systemic_breadth-0.10)):
            sys_armed=True
        if raw_sys_signal and sys_armed and not systemic:
            systemic=True;sys_armed=False;sys_enter=i;sys_streak=0;bridge_armed=True
        elif systemic:
            sys_streak=sys_streak+1 if healthy else 0
            if (i-sys_enter)>=cfg.systemic_min_hold and sys_streak>=cfg.systemic_confirmation:
                systemic=False;sys_streak=0
        core_alloc=cfg.systemic_alloc if systemic else 1.
        # Cohort selection: snapshot at stress onset, refresh only after material deeper damage.
        refresh=False
        if stress and not was_stress:refresh=True;last_refresh_dd=dd
        elif stress and cfg.selection=='cohort' and dd<=last_refresh_dd-cfg.refresh_depth:refresh=True;last_refresh_dd=dd
        if refresh and m and cfg.selection=='cohort':
            cand=np.flatnonzero(~d['green']);order=cand[np.argsort(-d['priority'][cand],kind='stable')] if len(cand) else np.array([],int)
            chosen=[int(eps[k]) for k in order[:cfg.rank_n]];protected.update(chosen)
            if detail:trans.append(dict(date=dt,kind='cohort_refresh',episode=-1,ticker='',from_scale=np.nan,to_scale=np.nan,shadow_dd=dd,reason='|'.join(map(str,chosen))))
        # Rolling ranking or threshold updates.
        rolling=set()
        if stress and m and cfg.selection=='rolling':
            cand=np.flatnonzero(~d['green']);order=cand[np.argsort(-d['priority'][cand],kind='stable')] if len(cand) else np.array([],int)
            rolling=set(int(eps[k]) for k in order[:cfg.rank_n])
        if stress and m and cfg.selection=='threshold':protected.update(int(eps[k]) for k in np.flatnonzero(d['red']))
        desired=np.ones(m,float)
        for k,epv in enumerate(eps):
            ep=int(epv)
            if ep in protected or ep in rolling:desired[k]=cfg.cut_scale
            elif stress and cfg.selection in ('cohort','rolling') and d['amber'][k] and not d['green'][k]:desired[k]=cfg.amber_scale
            if d['green'][k] and ep not in protected:desired[k]=1.
        current=np.ones(m,float);sel_trade=0.
        for k,epv in enumerate(eps):
            ep=int(epv);prev=float(q.get(ep,1.));want=float(desired[k]);last=int(last_change.get(ep,-10**9))
            if want<prev-1e-12:new=want
            elif want>prev+1e-12:
                can=(i-last)>=cfg.min_change and healthy and (not stress or d['green'][k])
                new=min(want,prev+cfg.recovery_step) if can else prev
            else:new=prev
            # A protected cohort member exits protection only after it becomes green and recovery is healthy.
            if ep in protected and prev<1 and d['green'][k] and healthy and (i-last)>=cfg.min_change:
                new=min(1.,prev+cfg.recovery_step)
                if new>=1-1e-12:protected.discard(ep)
            current[k]=new;q[ep]=new
            if abs(new-prev)>1e-12:
                sel_trade+=core_alloc*d['weight'][k]*abs(new-prev);last_change[ep]=i
                if detail:trans.append(dict(date=dt,kind='position_scale',episode=ep,ticker=d['ticker'][k],from_scale=prev,to_scale=new,shadow_dd=dd,reason='cohort_down' if new<prev else 'recovery_up'))
        # Selective exposure inside the core sleeve.
        shadow_stock=float(d['weight'].sum()) if m else 0.;selective_stock=float(np.dot(d['weight'],current)) if m else 0.
        scaled_cont=float(np.dot(d['contribution'],current)) if m else 0.
        live_count=int(np.sum(current>0.05))
        if m and d['green'].any():
            gw=d['weight'][d['green']]
            if gw.sum()>0:pres.append(float(np.average(current[d['green']],weights=gw)))
        # Entries executed during next interval.
        e=eg.get(dt,emptye);scaled_entry=0.;entry_shadow=0.;entry_live=0.
        # Position cap varies with shadow drawdown.
        if dd>-0.125:pcap=cfg.position_caps[0]
        elif dd>-0.155:pcap=cfg.position_caps[1]
        else:pcap=cfg.position_caps[2]
        for k,epv in enumerate(e['episode']):
            ep=int(epv);mom=e['recent21'][k];secv=float(d['sector_stress'].get(e['sector'][k],0.));block=False
            weak=(not np.isfinite(mom)) or mom<0 or secv>=.50
            if cfg.entry_policy=='weak':block=stress and weak
            elif cfg.entry_policy=='position_cap':block=stress and (live_count>=pcap or weak)
            elif cfg.entry_policy=='systemic':block=systemic
            entry_shadow+=float(e['planned_weight'][k])
            if block:
                blocked+=1;q[ep]=0.;last_change[ep]=i
                if detail:trans.append(dict(date=dt,kind='blocked_entry',episode=ep,ticker=e['ticker'][k],from_scale=1.,to_scale=0.,shadow_dd=dd,reason='position_count_or_weak'))
            else:
                q[ep]=1.;scaled_entry+=float(e['entry_contribution'][k]);entry_live+=float(e['planned_weight'][k]);live_count+=1
        # Scale exact core residual proportionally to active core risk. Full baseline ratio is one.
        denom=max(float(core_exposure[i]),1e-9)
        selective_ratio=np.clip((selective_stock+entry_live)/(shadow_stock+entry_shadow+1e-12),0,1.5) if (shadow_stock+entry_shadow)>0 else 1.
        core_component=scaled_cont+scaled_entry+selective_ratio*residual[i]
        # Released stock inside core sleeve plus the systemic allocation release goes to defensive bills.
        selective_release=max(0.,shadow_stock+entry_shadow-selective_stock-entry_live)
        defense_weight=(1-core_alloc)+core_alloc*selective_release
        stock_exposure=core_alloc*selective_stock
        # Recovery bridge can only use released defensive capital.
        if dd<=-.125:bridge_armed=True
        green_breadth=float(d['green'].mean()) if m else 0.;spy20=float(row.spy_r20) if pd.notna(row.spy_r20) else np.nan;spy63=float(row.spy_r63) if pd.notna(row.spy_r63) else np.nan
        bridge_ok=(cfg.bridge_asset and cfg.bridge_cap>0 and bridge_armed and not systemic and np.isfinite(r20) and r20>0 and np.isfinite(spy20) and spy20>0 and np.isfinite(spy63) and spy63>0 and int(row.stops20)<=2 and float(row.dd_rebound20)>=.04 and green_breadth>=.5)
        bridge=0.;bridge_ret=0.;avail=True
        if cfg.bridge_asset=='SSO':avail=bool(row.sso_available);bridge_ret=float(core.iloc[i+1].sso_ret)
        elif cfg.bridge_asset=='SPY':bridge_ret=float(core.iloc[i+1].spy_ret)
        else:avail=False
        if bridge_ok and avail and bridge_days<cfg.bridge_max_days:
            gap=max(0.,cfg.bridge_target_beta-stock_exposure);bridge=min(cfg.bridge_cap,defense_weight,gap/cfg.bridge_leverage);bridge_days+=1
            if prev_bridge<=1e-12 and bridge>1e-12:bridge_entries+=1
        else:
            if bridge_days>=cfg.bridge_max_days:bridge_armed=False
            bridge_days=0
        bridge_trade=abs(bridge-prev_bridge);sys_trade=abs(core_alloc-prev_core_alloc)
        if detail and bridge_trade>1e-12:trans.append(dict(date=dt,kind='bridge_rebalance',episode=-1,ticker=cfg.bridge_asset or '',from_scale=prev_bridge,to_scale=bridge,shadow_dd=dd,reason='recovery_bridge'))
        if detail and sys_trade>1e-12:trans.append(dict(date=dt,kind='systemic_rebalance',episode=-1,ticker='',from_scale=prev_core_alloc,to_scale=core_alloc,shadow_dd=dd,reason='systemic'))
        prev_bridge=bridge;prev_core_alloc=core_alloc
        extra_cost=2*COST*(sel_trade+bridge_trade+sys_trade);turnover+=sel_trade+bridge_trade+sys_trade;cost_sum+=extra_cost
        nextrow=core.iloc[i+1];defret=float(nextrow.defense_return)
        live_ret=core_alloc*core_component+(defense_weight-bridge)*defret+bridge*bridge_ret-extra_cost
        # Baseline identity guard.
        if cfg.selection=='none' and cfg.systemic_trigger is None and cfg.bridge_asset is None:
            live_ret=float(nextrow.ret)
        if live_ret<=-1:raise RuntimeError((cfg.name,dt,live_ret))
        nav[i+1]=nav[i]*(1+live_ret)
        if stress:stress_days+=1
        if systemic:sys_days+=1
        sum_stock+=stock_exposure;sum_bridge+=bridge;sum_count+=live_count
        if detail:records.append(dict(date=dt,nav=nav[i],shadow_nav=float(row.nav),shadow_dd=dd,stress=stress,systemic=systemic,core_allocation=core_alloc,stock_exposure=stock_exposure,defense_weight=defense_weight,bridge_weight=bridge,live_positions=live_count,protected_count=len(protected),damaged_breadth=damaged_breadth,green_breadth=green_breadth,extra_cost=extra_cost))
    s=pd.Series(nav,index=dates);mtr=fw.metrics(s);mtr.update(asdict(cfg))
    for label,start in [('trailing15',fw.TR15),('trailing10',fw.TR10)]:
        mm=fw.metrics(s.loc[s.index>=start])
        for k,v in mm.items():mtr[f'{label}_{k}']=v
    mtr.update(stress_days=stress_days,systemic_days=sys_days,average_stock_exposure=sum_stock/(n-1),average_bridge_weight=sum_bridge/(n-1),average_live_positions=sum_count/(n-1),green_weight_preservation=float(np.mean(pres)) if pres else np.nan,blocked_entries=blocked,bridge_entries=bridge_entries,extra_turnover=turnover,extra_cost_nav=cost_sum)
    return s,pd.DataFrame(trans),mtr,pd.DataFrame(records).set_index('date') if detail else None


def configs():
    c=[Cfg('Wealth Core baseline')]
    c += [
      Cfg('binary_155_validation',systemic_trigger=.155,systemic_breadth=2.,systemic_alloc=.25),
      Cfg('rolling5_q25',selection='rolling',trigger=.10,rank_n=5,cut_scale=.25),
      Cfg('rolling8_q25',selection='rolling',trigger=.10,rank_n=8,cut_scale=.25),
      Cfg('cohort5_q25_frozen',selection='cohort',trigger=.10,rank_n=5,cut_scale=.25,refresh_depth=.99),
      Cfg('cohort8_q25_frozen',selection='cohort',trigger=.10,rank_n=8,cut_scale=.25,refresh_depth=.99),
      Cfg('cohort5_q25_refresh5',selection='cohort',trigger=.10,rank_n=5,cut_scale=.25,refresh_depth=.05),
      Cfg('cohort8_q25_refresh5',selection='cohort',trigger=.10,rank_n=8,cut_scale=.25,refresh_depth=.05),
      Cfg('cohort5_zero_frozen',selection='cohort',trigger=.10,rank_n=5,cut_scale=0.,amber_scale=1.,refresh_depth=.99),
      Cfg('cohort8_zero_frozen',selection='cohort',trigger=.10,rank_n=8,cut_scale=0.,amber_scale=1.,refresh_depth=.99),
      Cfg('elastic_count_cohort',selection='cohort',trigger=.10,rank_n=8,cut_scale=0.,amber_scale=1.,refresh_depth=.05,entry_policy='position_cap'),
      Cfg('cohort5_systemic25',selection='cohort',trigger=.10,rank_n=5,cut_scale=.25,refresh_depth=.05,systemic_trigger=.155,systemic_breadth=2.,systemic_alloc=.25),
      Cfg('cohort5_systemic40',selection='cohort',trigger=.10,rank_n=5,cut_scale=.25,refresh_depth=.05,systemic_trigger=.155,systemic_breadth=2.,systemic_alloc=.40),
      Cfg('cohort5_breadth_systemic40',selection='cohort',trigger=.10,rank_n=5,cut_scale=.25,refresh_depth=.05,systemic_trigger=.155,systemic_breadth=.60,systemic_alloc=.40),
    ]
    # Small, interpretable local neighborhood.
    for trig in [.08,.10,.12]:
      for n in [3,5,8]:
       for scale in [0.,.25,.50]:
        for refresh in [.05,.99]:
         c.append(Cfg(f'grid_cohort_t{trig:.2f}_n{n}_s{scale:.2f}_r{refresh}',selection='cohort',trigger=trig,rank_n=n,cut_scale=scale,amber_scale=1.,refresh_depth=refresh))
    # Elastic count variants.
    for trig in [.08,.10,.12]:
      for n in [5,8]:
       c.append(Cfg(f'grid_elastic_t{trig:.2f}_n{n}',selection='cohort',trigger=trig,rank_n=n,cut_scale=0.,amber_scale=1.,refresh_depth=.05,entry_policy='position_cap'))
    # Add systemic backstop to best structural bases; bridge variants tested independently.
    for alloc in [.25,.40]:
      for n in [3,5,8]:
       c.append(Cfg(f'grid_cohort_n{n}_sys{alloc:.2f}',selection='cohort',trigger=.10,rank_n=n,cut_scale=.25,amber_scale=1.,refresh_depth=.05,systemic_trigger=.155,systemic_breadth=2.,systemic_alloc=alloc))
    for cap in [.05,.10,.15]:
      for days in [20,40,60]:
       c.append(Cfg(f'bridge_SSO_{cap:.2f}_{days}',selection='cohort',trigger=.10,rank_n=5,cut_scale=.25,amber_scale=1.,refresh_depth=.05,systemic_trigger=.155,systemic_breadth=2.,systemic_alloc=.40,bridge_asset='SSO',bridge_cap=cap,bridge_max_days=days))
    return c


def main():
    t=time.time();core,panel,entries,diag=fw.load_data();pg,eg=precompute(core,panel,entries);print('DATA',len(core),len(panel),len(entries),flush=True)
    cs=configs();rows=[];curves={}
    for j,cfg in enumerate(cs):
        s,tr,m,d=simulate(core,pg,eg,diag,cfg,False);rows.append(m);curves[cfg.name]=s
        if j%10==0 or j==len(cs)-1:print('RUN',j+1,len(cs),cfg.name,round(m['cagr'],5),round(m['max_drawdown'],5),flush=True)
    res=pd.DataFrame(rows);res['min_calmar']=res[['calmar','trailing15_calmar','trailing10_calmar']].min(axis=1);res['mean_calmar']=res[['calmar','trailing15_calmar','trailing10_calmar']].mean(axis=1);res.to_csv(OUT/'firewall_v2_grid.csv',index=False)
    # Baseline and binary validation print.
    print(res[res.name.isin(['Wealth Core baseline','binary_155_validation'])][['name','cagr','max_drawdown','ending_multiple']].to_string(index=False),flush=True)
    candidates=res[(res.cagr>=.18)&(res.max_drawdown>=-.37)].sort_values(['min_calmar','cagr'],ascending=False)
    top=candidates.head(10).name.tolist();named=['Wealth Core baseline','binary_155_validation','rolling5_q25','cohort5_q25_frozen','cohort5_q25_refresh5','cohort8_q25_refresh5','elastic_count_cohort','cohort5_systemic25','cohort5_systemic40','cohort5_breadth_systemic40']
    selected=[]
    for x in named+top:
        if x not in selected:selected.append(x)
    details=[]
    for name in selected:
        cfg=next(x for x in cs if x.name==name);s,tr,m,d=simulate(core,pg,eg,diag,cfg,True);d.to_csv(OUT/f'{name}_daily.csv');tr.to_csv(OUT/f'{name}_transitions.csv',index=False);fw.crisis_metrics(s).to_csv(OUT/f'{name}_crisis.csv',index=False);details.append(m)
    pd.DataFrame(details).to_csv(OUT/'selected_v2_results.csv',index=False)
    best=candidates.iloc[0] if len(candidates) else res.sort_values('calmar',ascending=False).iloc[0]
    meta=dict(runtime_seconds=time.time()-t,configs=len(cs),best_name=best['name'],contribution_fit_correlation=float(diag[['core_next_ret','estimated_position_contribution']].corr().iloc[0,1]),contribution_fit_mae=float(diag.residual.abs().mean()),method='exact core return decomposition with residual scaled to active core risk; frozen-cohort selective overlay; actual SHY/BIL/SSO returns')
    (OUT/'metadata.json').write_text(json.dumps(meta,indent=2));print('BEST',best[['name','cagr','max_drawdown','calmar','trailing10_cagr','trailing10_max_drawdown','min_calmar']].to_dict(),flush=True);print('DONE',round(time.time()-t,2),flush=True)
if __name__=='__main__':main()
