from __future__ import annotations
import json, math
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

from fast_confirmation import (
    Evidence as GateEvidence, State as GateState, compose_after_ldrc,
    step as gate_step,
)

ROOT=Path('/mnt/data')
OUT=ROOT/'alpha_recovery_narrow'
OUT.mkdir(exist_ok=True)
TAPE=ROOT/'ldrc_full_research/smoke_tapes/sentinel_1p1_daily(3).csv'
SFP=ROOT/'ldrc_full_research/sfp_spy_bil.csv'
COST=.001
ORDINARY_DD=-.155
FAST_D5=.30
RAMP_STEPS=(.55,.65,1.0)
RAMP_CONFIRM=(10,10)

# Retained causal dynamic-contagion confirmations, ported to the authoritative
# tape. 2015-08-24 becomes 2015-08-25 because that is the first authoritative
# session satisfying the frozen non-peer FAST predicates. 2018-02-08 is omitted
# because the authoritative shadow never crossed the frozen -10% DD predicate.
DYNAMIC_CONFIRMED_DATES={
    pd.Timestamp('2008-07-02'), pd.Timestamp('2008-10-03'),
    pd.Timestamp('2011-08-04'), pd.Timestamp('2015-08-25'),
    pd.Timestamp('2018-10-11'), pd.Timestamp('2020-02-27'),
    pd.Timestamp('2022-04-26'), pd.Timestamp('2022-06-15'),
}


def finite(x): return x is not None and isinstance(x,(int,float,np.integer,np.floating)) and math.isfinite(float(x))
def val(x): return float(x) if pd.notna(x) else None

class NativeSentinel:
    """Authoritative native path, with only parent FAST entry injected.

    raw_fast continues to drive the base-stress/slow branch. parent_fast_signal
    drives only the capital-control FAST state. Recovery mechanics are unchanged.
    """
    def __init__(self):
        self.s={
            '_r40':[], 'ordinary':False,'ordinary_age':0,'ordinary_h':0,'binary_armed':True,
            'base_fast':False,'base_fast_age':0,'base_fast_h':0,'base_fast_armed':True,
            'base_anchor':None,'base_duration':0,
            'fast':False,'fast_age':0,'fast_h':0,'fast_armed':True,
            'slow':False,'slow_age':0,'slow_h':0,
            'ramp':False,'ramp_idx':None,'ramp_h':0,'last':1.0,
        }
    def step(self, ob, *, raw_fast: bool, parent_fast_signal: bool):
        s=self.s; dd=ob['dd']; damaged=ob['damaged']; green=ob['green']; r20=ob['r20']; r40=ob['r40']
        healthy=finite(r20) and r20>0 and finite(damaged) and damaged<=.60 and finite(green) and green>=.20

        # Ordinary stress unchanged.
        if finite(dd) and dd>ORDINARY_DD: s['binary_armed']=True
        if finite(dd) and dd<=ORDINARY_DD and s['binary_armed'] and not s['ordinary']:
            s['ordinary']=True; s['binary_armed']=False; s['ordinary_age']=0; s['ordinary_h']=0
        elif s['ordinary']:
            s['ordinary_age']+=1
            base_healthy=finite(r20) and r20>0 and finite(ob['stops20']) and ob['stops20']<=2
            s['ordinary_h']=s['ordinary_h']+1 if base_healthy else 0
            if s['ordinary_age']>=20 and s['ordinary_h']>=3:
                s['ordinary']=False; s['ordinary_h']=0

        # Base FAST remains the current authoritative raw signal so the slow
        # prolonged-stress path is untouched.
        if finite(dd) and dd>-.06 and not raw_fast: s['base_fast_armed']=True
        if raw_fast and s['base_fast_armed'] and not s['base_fast'] and not s['ordinary']:
            s['base_fast']=True; s['base_fast_armed']=False; s['base_fast_age']=0; s['base_fast_h']=0
        elif s['base_fast']:
            s['base_fast_age']+=1
            s['base_fast_h']=s['base_fast_h']+1 if healthy else 0
            if s['base_fast_age']>=10 and s['base_fast_h']>=3:
                s['base_fast']=False; s['base_fast_h']=0

        base=s['ordinary'] or s['base_fast']
        if base:
            if s['base_anchor'] is None:
                s['base_anchor']=ob['nav']; s['base_duration']=1
            else: s['base_duration']+=1
        else:
            s['base_anchor']=None; s['base_duration']=0
        slow_signal=False
        if base and finite(s['base_anchor']) and finite(ob['nav']):
            since=ob['nav']/s['base_anchor']-1
            slow_signal=(s['base_duration']>=30 and since<=-.02 and finite(r40) and r40<=-.03
                         and finite(damaged) and damaged>=.75 and finite(green) and green<=.25)

        # Only this entry signal differs by arm.
        if finite(dd) and dd>-.06 and not parent_fast_signal: s['fast_armed']=True
        if parent_fast_signal and s['fast_armed'] and not s['fast']:
            s['fast']=True; s['fast_armed']=False; s['fast_age']=0; s['fast_h']=0
        elif s['fast']:
            s['fast_age']+=1
            s['fast_h']=s['fast_h']+1 if healthy else 0
            if s['fast_age']+1>=10 and s['fast_h']>=3:
                s['fast']=False; s['fast_h']=0

        # Slow severe and its recovery unchanged.
        if s['slow']:
            s['slow_age']+=1
            s['slow_h']=s['slow_h']+1 if healthy else 0
            if s['slow_age']+1>=20 and s['slow_h']>=6:
                s['slow']=False; s['slow_h']=0
        elif slow_signal:
            s['slow']=True; s['slow_age']=0; s['slow_h']=0

        parent=0.0 if s['fast'] or s['slow'] else 1.0
        prior_parent=0.0 if ob['prior_severe'] else 1.0
        severe=parent<=0.0
        recovering=prior_parent<=0.0 and not severe
        if severe:
            s['ramp']=False; s['ramp_idx']=None; s['ramp_h']=0
            target=0.0; reason='SEVERE'
        elif recovering:
            hist=s['_r40']
            delta=(hist[-1]-hist[-6]) if len(hist)>=6 and finite(hist[-1]) and finite(hist[-6]) else None
            fragile=None if delta is None else delta<=0
            if fragile is not False:
                s['ramp']=True; s['ramp_idx']=0; s['ramp_h']=0
                target=.55; reason='RECOVERY_RAMP'
            else:
                s['ramp']=False; s['ramp_idx']=None; s['ramp_h']=0
                target=1.0; reason='RECOVERY_FULL'
        elif s['ramp']:
            idx=s['ramp_idx']; need=RAMP_CONFIRM[idx]
            s['ramp_h']=s['ramp_h']+1 if healthy else 0
            if s['ramp_h']>=need:
                idx+=1; s['ramp_idx']=idx; s['ramp_h']=0
                if idx>=len(RAMP_STEPS)-1:
                    s['ramp']=False; s['ramp_idx']=None
                    target=1.0; reason='RAMP_COMPLETE'
                else:
                    target=RAMP_STEPS[idx]; reason='RAMP_PROMOTED'
            else:
                target=RAMP_STEPS[idx]; reason='RAMP_HOLDING'
        else:
            target=1.0; reason='NORMAL'
        s['_r40']=(s['_r40']+[r40])[-6:]
        s['last']=target
        return target, reason, severe, bool(s['fast']), bool(s['slow'])

class LDRC:
    """Current authoritative LD-RC semantics, unchanged."""
    def __init__(self):
        self.episode=False; self.latched=False; self.streak=0
        self.prev_native=1.0; self.prev_desired=1.0
    def step(self,native,effective_native,wc_dd,recent20,recent40,spy20):
        healthy=finite(recent20) and finite(recent40) and recent20>0 and recent40>0
        self.streak=self.streak+1 if healthy else 0
        v=finite(spy20) and spy20>.11
        reasons=[]
        if self.prev_native>=1-1e-12 and native<1-1e-12:
            self.episode=True; reasons.append('RECOVERY_EPISODE_START')
        cleared=self.latched and (self.streak>=7 or v)
        if cleared:
            self.latched=False; reasons.append('DIVERGENCE_CLEAR')
        desired=native
        if self.episode and native>=1-1e-12:
            if self.streak>=7 or v:
                self.episode=False; desired=1.0; reasons.append('FULL_RISK_CERTIFIED')
            else:
                desired=self.prev_desired; reasons.append('FULL_RISK_HELD')
        if not self.latched and not cleared:
            if (native>=1-1e-12 and effective_native is not None and effective_native>=1-1e-12
                and finite(wc_dd) and finite(recent20) and finite(spy20)
                and wc_dd<=-.10 and recent20<=-.08 and spy20>=0):
                self.latched=True; reasons.append('LD_ENTER_DIVERGENCE')
        if self.latched: desired=min(desired,.55)
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return desired, self.episode, self.latched, '|'.join(reasons) if reasons else 'NORMAL'

@dataclass(frozen=True)
class Arm:
    name:str
    dynamic_confirmation:bool
    provisional_first_warning:bool

ARMS=(
    Arm('A_current',False,False),
    Arm('B_dynamic_confirmation_only',True,False),
    Arm('C_provisional_only',False,True),
    Arm('D_narrow_combined',True,True),
)

def metric(nav: pd.Series, start, end):
    x=nav.loc[(nav.index>=pd.Timestamp(start))&(nav.index<=pd.Timestamp(end))]
    years=(x.index[-1]-x.index[0]).days/365.2425
    cagr=(x.iloc[-1]/x.iloc[0])**(1/years)-1
    r=x.pct_change().dropna(); sharpe=r.mean()/r.std(ddof=1)*np.sqrt(252)
    mdd=(x/x.cummax()-1).min()
    return {'start':str(x.index[0].date()),'end':str(x.index[-1].date()),'sessions':len(x),
            'cagr':float(cagr),'sharpe':float(sharpe),'max_drawdown':float(mdd),
            'ending_multiple':float(x.iloc[-1]/x.iloc[0])}

def main():
    base=pd.read_csv(TAPE,parse_dates=['date']).set_index('date').sort_index()
    sfp=pd.read_csv(SFP,parse_dates=['date'])
    spy=sfp[sfp.ticker.eq('SPY')].drop_duplicates('date').sort_values('date').set_index('date')
    bil=sfp[sfp.ticker.eq('BIL')].drop_duplicates('date').sort_values('date').set_index('date').copy()
    idx=base.index.union(spy.index).sort_values()
    spy_close=np.exp(np.log(spy.closeadj).reindex(idx).interpolate(method='time').ffill().bfill())
    spy_ret=spy_close.pct_change()
    spy_r20=spy_close.pct_change(20).reindex(base.index)
    spy_vol=(spy_ret.rolling(5).std(ddof=1)/spy_ret.rolling(20).std(ddof=1)-1).reindex(base.index)
    spy_index=(spy_close.reindex(base.index)/spy_close.reindex(base.index).iloc[0]).rename('SPY')

    bil['adj_open']=bil.open*bil.closeadj/bil.close
    idx2=base.index.union(bil.index).sort_values()
    blog=np.log(bil.closeadj).reindex(idx2).interpolate(method='time').ffill().bfill()
    bil_close=np.exp(blog).reindex(base.index)
    bratio=(bil.adj_open/bil.closeadj).reindex(idx2).interpolate(method='time').ffill().bfill()
    bil_open=(np.exp(blog)*bratio).reindex(base.index)

    r5=base.shadow_equity.pct_change(5); r10=base.shadow_equity.pct_change(10)
    d5=base.damaged-base.damaged.shift(5)
    short=(r5.le(-.05)|r10.le(-.08))
    confirm=(spy_r20.le(-.01)|r10.le(-.10))
    nonpeer=(base.shadow_dd.le(-.10)&base.green.le(.20)&short&spy_vol.ge(.04)&confirm)
    raw_fast=(nonpeer&base.damaged.ge(.85)&d5.ge(FAST_D5)).fillna(False)
    dynamic_confirm=pd.Series(base.index.isin(DYNAMIC_CONFIRMED_DATES),index=base.index)
    # Never import a retained signal where the fixed non-peer conditions fail.
    dynamic_confirm &= nonpeer.fillna(False)

    all_daily={}
    diagnostics=[]
    for arm in ARMS:
        native=NativeSentinel(); ldrc=LDRC(); prior_severe=False
        effective_native=1.0; effective_final=1.0; pending_final=1.0
        nav=1.0; prev_eq=None; rows=[]; gate_state=GateState()
        for i,(d,row) in enumerate(base.iterrows()):
            # Apply prior close's pending allocation at this open with exact
            # authoritative hold-vs-transition accounting.
            factor=1.0; transitioned=False
            if i>0:
                old=effective_final; new=pending_final
                pd0=base.index[i-1]
                if abs(new-old)<=1e-15:
                    wf=float(row.shadow_equity/prev_eq)
                    bf=float(bil_close.loc[d]/bil_close.loc[pd0])
                    factor=old*wf+(1-old)*bf
                else:
                    wo=float(row.open_shadow_equity/prev_eq-1)
                    wi=float(row.shadow_equity/row.open_shadow_equity-1)
                    bo=float(bil_open.loc[d]/bil_close.loc[pd0]-1)
                    bi=float(bil_close.loc[d]/bil_open.loc[d]-1)
                    factor=(1+old*wo+(1-old)*bo)*(1-COST*abs(new-old))*(1+new*wi+(1-new)*bi)
                    transitioned=True
                nav*=factor; effective_final=new

            raw=bool(raw_fast.loc[d])
            dyn=bool(dynamic_confirm.loc[d]) if arm.dynamic_confirmation else False
            if arm.name == 'A_current':
                warning, confirmed, provisional_ceiling, gate_reason = raw, raw, None, 'CURRENT_FAST_IMMEDIATE'
                warning_streak = 1 if raw else 0
            elif arm.name == 'B_dynamic_confirmation_only':
                warning, confirmed, provisional_ceiling, gate_reason = (raw or dyn), dyn, None, 'DYNAMIC_CONFIRMATION_ONLY'
                warning_streak = 1 if warning else 0
            else:
                warning = raw or dyn
                causal = dyn if arm.dynamic_confirmation else False
                gate_state, gate = gate_step(
                    evidence=GateEvidence(str(d.date()), warning, causal),
                    state=gate_state,
                )
                confirmed = gate.parent_fast_signal
                provisional_ceiling = gate.provisional_ceiling
                gate_reason = gate.reason
                warning_streak = gate.warning_streak

            ob={'nav':val(row.shadow_equity),'dd':val(row.shadow_dd),'damaged':val(row.damaged),
                'green':val(row.green),'r20':val(row.r20),'r40':val(row.r40),
                'stops20':val(row.stops20),'prior_severe':prior_severe}
            native_next,nreason,severe,fast_active,slow_active=native.step(
                ob,raw_fast=raw,parent_fast_signal=confirmed)
            prior_severe=severe
            desired,episode,latched,lreason=ldrc.step(
                native_next,effective_native,val(row.shadow_dd),val(row.recent_r20),
                val(row.recent_r40),val(spy_r20.loc[d]))
            effective_native=native_next

            provisional=(provisional_ceiling is not None and not fast_active
                         and not slow_active and native_next>0)
            final_next=compose_after_ldrc(
                authoritative_allocation=desired,
                provisional_ceiling=provisional_ceiling if provisional else None,
            )
            reason='|'.join(x for x in [nreason,lreason,gate_reason if provisional or confirmed else ''] if x and x!='NORMAL') or 'NORMAL'
            rows.append({'date':d,'nav':nav,'effective_allocation':effective_final,
                         'pending_allocation':final_next,'native_next':native_next,
                         'ldrc_desired_next':desired,'raw_fast':raw,'dynamic_confirmed':dyn,
                         'warning':warning,'warning_streak':warning_streak,'confirmed':confirmed,
                         'provisional':provisional,'fast_active':fast_active,'slow_active':slow_active,
                         'ldrc_episode':episode,'ldrc_latched':latched,'reason':reason,
                         'factor':factor,'transitioned':transitioned})
            pending_final=final_next; prev_eq=float(row.shadow_equity)
        out=pd.DataFrame(rows).set_index('date')
        all_daily[arm.name]=out
        out.to_csv(OUT/f'{arm.name}_daily.csv')

    # Exact control gates.
    ctrl=all_daily['A_current']
    gates={
        'native_next_max_abs':float((ctrl.native_next-base.native_next).abs().max()),
        'ldrc_desired_next_max_abs':float((ctrl.ldrc_desired_next-base.desired_next).abs().max()),
        'effective_allocation_max_abs':float((ctrl.effective_allocation-base.allocation).abs().max()),
        'nav_max_abs':float((ctrl.nav-base.nav).abs().max()),
        'nav_final_control':float(ctrl.nav.iloc[-1]),
        'nav_final_authoritative':float(base.nav.iloc[-1]),
    }
    if any(gates[k]>2e-11 for k in ('native_next_max_abs','ldrc_desired_next_max_abs','effective_allocation_max_abs','nav_max_abs')):
        raise AssertionError(f'control parity failed: {gates}')

    windows={5:'2021-07-30',10:'2016-07-29',15:'2011-07-29',20:'2006-07-31'}
    metrics=[]
    for years,start in windows.items():
        for name,out in all_daily.items():
            m=metric(out.nav,start,'2026-07-31'); m.update({'window_years':years,'strategy':name}); metrics.append(m)
        m=metric(spy_index,start,'2026-07-31'); m.update({'window_years':years,'strategy':'SPY'});metrics.append(m)
    met=pd.DataFrame(metrics)[['window_years','strategy','start','end','sessions','cagr','sharpe','max_drawdown','ending_multiple']]
    met.to_csv(OUT/'metrics_5_10_15_20.csv',index=False)

    # Combined comparison and transition log.
    combined=all_daily['D_narrow_combined']
    comp=pd.DataFrame({'date':base.index,'current_nav':ctrl.nav.values,'narrow_nav':combined.nav.values,
                       'spy_nav':spy_index.values,'current_allocation':ctrl.effective_allocation.values,
                       'narrow_allocation':combined.effective_allocation.values,
                       'narrow_pending':combined.pending_allocation.values})
    comp.to_csv(OUT/'daily_equity_curves.csv',index=False)
    tr=combined.loc[combined.pending_allocation.ne(combined.pending_allocation.shift(1)) | combined.provisional]
    tr.to_csv(OUT/'narrow_transitions.csv')
    # 2x2 attribution vs current.
    attr=[]
    for years,start in windows.items():
        control=metric(ctrl.nav,start,'2026-07-31')
        for name in ['B_dynamic_confirmation_only','C_provisional_only','D_narrow_combined']:
            mm=metric(all_daily[name].nav,start,'2026-07-31')
            attr.append({'window_years':years,'strategy':name,
                         'cagr_delta_pp':(mm['cagr']-control['cagr'])*100,
                         'sharpe_delta':mm['sharpe']-control['sharpe'],
                         'max_dd_delta_pp':(mm['max_drawdown']-control['max_drawdown'])*100})
    pd.DataFrame(attr).to_csv(OUT/'factorial_attribution.csv',index=False)
    provenance={'base_main_commit':'722aa14ae0e452437b80425528ba30fcf133b029',
                'strategy_files_unchanged_since':'22ebcf48addadbc7ec4531df415041d1b8674f48',
                'authoritative_tape':'sentinel_1p1_daily(3).csv','control_gates':gates,
                'dynamic_confirmed_dates':[str(d.date()) for d in sorted(DYNAMIC_CONFIRMED_DATES)],
                'portable_dynamic_confirmed_dates':[str(d.date()) for d in base.index[dynamic_confirm]],
                'limitations':['Retained causal dynamic-peer decision schedule is ported to the authoritative tape; per-security peer histories were not freshly recomputed.','Severe recovery, slow branch, Sentinel 1.1 ramp, and LD-RC logic are replayed unchanged.','Authoritative hold-versus-transition accounting is used.']}
    (OUT/'provenance.json').write_text(json.dumps(provenance,indent=2))
    print(json.dumps(gates,indent=2))
    print(met.to_string(index=False))
    print('\nATTRIBUTION')
    print(pd.DataFrame(attr).to_string(index=False))
    print('\nTRANSITIONS')
    print(tr[['pending_allocation','native_next','ldrc_desired_next','raw_fast','dynamic_confirmed','provisional','fast_active','slow_active','reason']].to_string())

if __name__=='__main__': main()
