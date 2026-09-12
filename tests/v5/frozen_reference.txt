#!/usr/bin/env python3
"""Research-only LD-RC A/B replay.

Pinned strategy source identity: flabber1835/stocker@c14f77b3c6c6fcc14cf00e8916d7968c853a5d6c
Data: local Sharadar SEP 1997-2026, TICKERS, ACTIONS, SFP.

This is intentionally NOT a PIT certification harness: the supplied TICKERS file is a
current snapshot, so historical category/issuer/sector metadata cannot be claimed PIT.
The purpose is a same-tape structural A/B experiment with current economic domains,
30pp Concordance parent, and next-open allocation timing.
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass, field
from collections import defaultdict
from backtester import champion_final_security_truth as _bestclass
from backtester.causal_terminal_terms import load_frozen_terminal_terms
from stock_strategy_shared.wealth_core.terminal import TerminalKind as _ProductionTerminalKind, TerminalTerms as _ProductionTerminalTerms
from backtester.research_terminal_grace_overlay import capacity_guard as _research_capacity_guard, exact_terminal_economics as _research_exact_terminal_economics
import pandas as pd
import numpy as np
import zipfile, glob, math, json, hashlib, time, gc, os, importlib.util
from backtester.canonical_pit_dataset import CanonicalPITDataset

gc.disable()
ROOT = Path('sharadar')
OUT = Path('/home/runner/work/stocker/stocker/final-output/engine')
OUT.mkdir(exist_ok=True)
COMMIT = 'c14f77b3c6c6fcc14cf00e8916d7968c853a5d6c'
START = pd.Timestamp('2006-07-31')
END = pd.Timestamp('2026-07-31')
MODE = os.environ.get('RESEARCH_REPLAY_MODE', 'nonpit')
PIT_MODE = MODE == 'fullpit'
N_SLOTS = 20
ENTRY_W = 0.05
COST = 0.001
REVIEW_AGE = 119
COOLDOWN = 21
STOP_RET = 0.70
MIN_PRICE = 1.0
MIN_ADV20 = 20_000_000.0
MIN_DAY_DV = 5_000_000.0
TOP = 0.10
TERMINAL = {'acquisitionby','mergerto','voluntarydelisting','regulatorydelisting','bankruptcyliquidation','delisted'}
ALLOWED_EXCH = {'NYSE','NASDAQ','NYSEMKT','NYSEARCA','BATS','AMEX'}

# Current production Concordance parent: 30 percentage-point damaged breadth acceleration.
ORD_DD = -0.155
FAST = {'dd':-.10,'dam':0.88,'green':.20,'r5':-.05,'r10':-.08,'ddam5':.30,'volacc':.04,'spy20':-.01,'r10confirm':-.10}
SLOW = {'dur':30,'ret':-.02,'r40':-.03,'dam':.75,'green':.25}

# Current Simplified LD-RC v3 constants.
LDRC_DD=-0.1; LDRC_R20=-0.085; LDRC_CEIL=.55; LDRC_REC=8; LDRC_V=0.11


def zcsv(path, usecols=None):
    with zipfile.ZipFile(path) as z:
        names=[n for n in z.namelist() if n.lower().endswith('.csv')]
        if len(names)!=1: raise RuntimeError(f'{path}: expected one csv, got {names}')
        with z.open(names[0]) as f:
            return pd.read_csv(f,usecols=usecols,low_memory=False)


def year_file(y):
    xs=sorted(glob.glob(str(ROOT/f'SHARADAR_SEP_{y}.csv*.gz')))
    if not xs: raise FileNotFoundError(y)
    if len(xs)>1:
        hs=[hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in xs]
        if len(set(hs))!=1:
            raise RuntimeError(f'non-identical duplicate SEP year {y}: {list(zip(xs,hs))}')
    return Path(xs[0])


def load_meta():
    global _CANONICAL, _PIT_EPISODES, _PIT_IDENTITY_AUDIT, _SID_TO_TID
    _CANONICAL=CanonicalPITDataset(
        Path(os.environ['CANONICAL_PIT_DATASET']),
        expected_start=os.environ.get('CERTIFICATION_WARMUP_START'),
        expected_end=os.environ.get('CERTIFICATION_END_SESSION'))
    rows=[]; _PIT_EPISODES=defaultdict(list)
    for _sid,_history in _CANONICAL._timeline_rows.items():
        _first=_history[0]; _ticker=str(_first['ticker'])
        rows.append((_ticker,str(_sid),str(_first['listing_first_session'])))
    rows.sort(key=lambda z:(z[0],z[2],z[1])); _SID_TO_TID={r[1]:i for i,r in enumerate(rows)}
    tick=np.asarray([r[0] for r in rows],object); sid=np.asarray([r[1] for r in rows],object)
    fp=pd.to_datetime([r[2] for r in rows]).to_numpy('datetime64[D]')
    lp=np.full(len(rows),np.datetime64('2262-04-11'),dtype='datetime64[D]')
    tmap={}
    for i,r in enumerate(rows): tmap.setdefault(r[0],i); _PIT_EPISODES[r[0]].append((r[2],i))
    common=np.zeros(len(rows),bool); sector=np.asarray([None]*len(rows),object)
    exchange=np.asarray(['']*len(rows),object); issuer=np.asarray([None]*len(rows),object)
    _PIT_IDENTITY_AUDIT=dict(_CANONICAL.manifest.get('identity_audit') or {})
    return tick,tmap,sid,common,sector,exchange,fp,lp,issuer

def strict_tid(ticker, ds):
    xs=_PIT_EPISODES.get(str(ticker),())
    if not xs: return None
    s=str(ds)[:10]; starts=[x[0] for x in xs]; i=np.searchsorted(np.asarray(starts,dtype='U10'),s,side='right')-1
    return None if i<0 else int(xs[int(i)][1])

def load_actions():
    d=pd.read_csv(_CANONICAL.root/'actions.csv.gz',compression='gzip',dtype=str,keep_default_na=False)
    bydate=defaultdict(lambda:defaultdict(list)); split_dates=defaultdict(list)
    for r in d.itertuples(index=False):
        ds=pd.Timestamp(r.effective_session); val=float(r.canonical_value) if r.canonical_value else None
        bydate[ds][str(r.ticker)].append((str(r.action),val,None))
        if str(r.action)=='split' and val is not None: split_dates[str(r.ticker)].append((ds,val))
    return bydate,split_dates

def load_funds():
    levels,returns=_CANONICAL.benchmark(); idx=pd.to_datetime(list(_CANONICAL.sessions))
    spy=pd.DataFrame({'closeadj':[levels[s] for s in _CANONICAL.sessions]},index=idx)
    spy['ret']=spy.closeadj.astype(float).pct_change(); spy['r20']=spy.closeadj.astype(float).pct_change(20)
    spy['volacc']=spy.ret.rolling(5).std(ddof=1)/spy.ret.rolling(20).std(ddof=1)-1
    cash=_CANONICAL.cash_factors()
    bil=pd.DataFrame({'gap_factor':[cash[s][0] for s in _CANONICAL.sessions],
                      'intraday_factor':[cash[s][1] for s in _CANONICAL.sessions]},index=idx)
    return spy,bil

def finite(x): return x is not None and np.isfinite(x)

PEER_LOOKBACK=252
PEER_MIN_OBS=120
PEER_COUNT=3
PEER_CORR_FLOOR=.145
PEER_STATS={'breadth_sessions':0,'holding_observations':0,'insufficient_residual_histories':0,'pair_correlations':0,'accepted_peer_edges':0,'neighborhood_size_sum':0}

def _peer_corr(left,right):
    common=sorted(set(left).intersection(right))
    if len(common)<PEER_MIN_OBS: return None
    a=np.array([left[k] for k in common],float); b=np.array([right[k] for k in common],float)
    am=float(a.mean()); bm=float(b.mean()); da=a-am; db=b-bm
    den=float(np.sqrt(np.dot(da,da)*np.dot(db,db)))
    if not np.isfinite(den) or den<=0: return None
    out=float(np.dot(da,db)/den)
    return out if np.isfinite(out) else None

def _prior_residuals(tid,gday,close_ring,spy,shadow_dates):
    start=max(1,gday-PEER_LOOKBACK); end=gday-1
    keys=[]; asset=[]; market=[]
    for j in range(start,end+1):
        if j>=len(shadow_dates): break
        p0=float(close_ring[(j-1)%len(close_ring),tid]); p1=float(close_ring[j%len(close_ring),tid])
        date=shadow_dates[j]; mv=spy.loc[date,'ret'] if date in spy.index else np.nan
        if finite(p0) and p0>0 and finite(p1) and p1>0 and finite(mv):
            keys.append(j); asset.append(p1/p0-1.); market.append(float(mv))
    if len(keys)<PEER_MIN_OBS:
        PEER_STATS['insufficient_residual_histories']+=1; return {}
    a=np.array(asset,float); m=np.array(market,float); am=float(a.mean()); mm=float(m.mean()); dm=m-mm
    den=float(np.dot(dm,dm))
    if not np.isfinite(den) or den<=0:
        PEER_STATS['insufficient_residual_histories']+=1; return {}
    beta=float(np.dot(a-am,dm)/den)
    return {k:float(x-beta*y) for k,x,y in zip(keys,a,m)}

def dynamic_peer_breadth(held,gday,close_ring,spy,shadow_dates):
    if not held: return 0.,0.
    PEER_STATS['breadth_sessions']+=1; PEER_STATS['holding_observations']+=len(held)
    residuals=[_prior_residuals(int(z[0]),gday,close_ring,spy,shadow_dates) for z in held]
    reds=[bool(z[7]) for z in held]; greens=[bool(z[6]) for z in held]; ng=na=0
    for i,z in enumerate(held):
        scores=[]; left=residuals[i]
        if left:
            for j,right in enumerate(residuals):
                if i==j or not right: continue
                c=_peer_corr(left,right); PEER_STATS['pair_correlations']+=1
                if c is not None and c>=PEER_CORR_FLOOR: scores.append((float(c),int(held[j][0]),j))
        scores.sort(key=lambda row:(-row[0],row[1]))
        neighbors=[i]+[row[2] for row in scores[:PEER_COUNT]]
        PEER_STATS['accepted_peer_edges']+=max(len(neighbors)-1,0); PEER_STATS['neighborhood_size_sum']+=len(neighbors)
        stress=sum(int(reds[j]) for j in neighbors)/len(neighbors)
        individual=(finite(z[2]) and z[2]<=-.10) or (finite(z[3]) and z[3]<=-.03)
        amber=individual or (stress>=.50 and not greens[i])
        ng+=int(greens[i]); na+=int(amber)
    return ng/len(held),na/len(held)


@dataclass
class Slot:
    tid:int=-1; qty:float=0.; entry_sig:float=np.nan; peak:float=np.nan; entry_day:int=-1; reviewed:bool=False
    pending_sell:bool=False; sell_reason:str=''; pending_tid:int=-1; pending_shares:float=0.; pending_signal_day:int=-1; pending_intended_capital:float=0.; ready_day:int=0
    def held(self): return self.tid>=0 and self.qty>1e-12
    def reserved(self): return self.pending_tid>=0

@dataclass
class Book:
    cash:float=100000.0; receivables:list=field(default_factory=list)
    slots:list=field(default_factory=lambda:[Slot() for _ in range(N_SLOTS)])
    sec_ready:dict=field(default_factory=dict); terminal_pending:dict=field(default_factory=dict); initialized:bool=False; last_raw:dict=field(default_factory=dict)
    def equity(self,raw):
        v=self.cash+sum(x[1] for x in self.receivables)
        unresolved=False
        for s in self.slots:
            if s.held():
                p=raw[s.tid]
                if not (finite(p) and p>0):
                    unresolved=True; p=self.last_raw.get(s.tid,np.nan)
                if finite(p) and p>0: v+=s.qty*float(p)
        return float(v),unresolved
    def held_ids(self): return {s.tid for s in self.slots if s.held()}
    def reserved_ids(self): return {s.pending_tid for s in self.slots if s.reserved()}

class Native:
    def __init__(self):
        self.ordinary=False; self.binary_armed=True; self.ordinary_age=0; self.ordinary_h=0
        self.base_fast=False; self.base_fast_armed=True; self.base_fast_age=0; self.base_fast_h=0; self.base_anchor=None; self.base_dur=0
        self.fast=False; self.fast_armed=True; self.fast_age=0; self.fast_h=0
        self.slow=False; self.slow_age=0; self.slow_h=0
        self.ramp=False; self.ramp_idx=None; self.ramp_h=0; self.r40hist=[]
    def step(self,ob):
        dd,r5,r10,r20,r40,dam,green,ddam5,spy20,volacc,stops,nav=ob
        healthy=finite(r20) and finite(dam) and finite(green) and r20>0 and dam<=0.63 and green>=.20
        short=(finite(r5) and r5<=FAST['r5']) or (finite(r10) and r10<=FAST['r10'])
        conf=(finite(spy20) and spy20<=FAST['spy20']) or (finite(r10) and r10<=FAST['r10confirm'])
        fastsig=all([finite(dd),finite(dam),finite(green),finite(ddam5),finite(volacc)]) and dd<=FAST['dd'] and dam>=FAST['dam'] and green<=FAST['green'] and short and ddam5>=FAST['ddam5'] and volacc>=FAST['volacc'] and conf
        prior_base=self.ordinary or self.base_fast
        if finite(dd) and dd>ORD_DD: self.binary_armed=True
        if finite(dd) and dd<=ORD_DD and self.binary_armed and not self.ordinary:
            self.ordinary=True; self.binary_armed=False; self.ordinary_age=0; self.ordinary_h=0
        elif self.ordinary:
            self.ordinary_age+=1
            bh=finite(r20) and r20>0 and stops is not None and stops<=2
            self.ordinary_h=self.ordinary_h+1 if bh else 0
            if self.ordinary_age>=20 and self.ordinary_h>=3: self.ordinary=False; self.ordinary_h=0
        if finite(dd) and dd>-.06 and not fastsig: self.base_fast_armed=True
        if fastsig and self.base_fast_armed and not self.base_fast and not self.ordinary:
            self.base_fast=True; self.base_fast_armed=False; self.base_fast_age=0; self.base_fast_h=0
        elif self.base_fast:
            self.base_fast_age+=1; self.base_fast_h=self.base_fast_h+1 if healthy else 0
            if self.base_fast_age>=10 and self.base_fast_h>=3: self.base_fast=False; self.base_fast_h=0
        base=self.ordinary or self.base_fast
        if base:
            if not prior_base: self.base_anchor=nav; self.base_dur=1
            else: self.base_dur+=1
        else: self.base_anchor=None; self.base_dur=0
        since=(nav/self.base_anchor-1) if base and self.base_anchor and finite(nav) else None
        slowsig=base and finite(since) and finite(r40) and finite(dam) and finite(green) and self.base_dur>=SLOW['dur'] and since<=SLOW['ret'] and r40<=SLOW['r40'] and dam>=SLOW['dam'] and green<=SLOW['green']
        prior_parent=0. if (self.fast or self.slow) else 1.
        if finite(dd) and dd>-.06 and not fastsig: self.fast_armed=True
        if fastsig and self.fast_armed and not self.fast:
            self.fast=True; self.fast_armed=False; self.fast_age=0; self.fast_h=0
        elif self.fast:
            self.fast_age+=1; self.fast_h=self.fast_h+1 if healthy else 0
            if self.fast_age+1>=10 and self.fast_h>=3: self.fast=False; self.fast_h=0
        if self.slow:
            self.slow_age+=1; self.slow_h=self.slow_h+1 if healthy else 0
            if self.slow_age+1>=20 and self.slow_h>=6: self.slow=False; self.slow_h=0
        elif slowsig:
            self.slow=True; self.slow_age=0; self.slow_h=0
        parent=0. if (self.fast or self.slow) else 1.
        severe=parent<=0.; recovering=prior_parent<=0. and not severe
        if severe:
            self.ramp=False; self.ramp_idx=None; self.ramp_h=0; target=0.
        elif recovering:
            delta=(self.r40hist[-1]-self.r40hist[-6]) if len(self.r40hist)>=6 and finite(self.r40hist[-1]) and finite(self.r40hist[-6]) else None
            fragile=(delta<=0.) if finite(delta) else None
            if fragile is not False:
                self.ramp=True; self.ramp_idx=0; self.ramp_h=1 if healthy else 0; target=.55
            else:
                self.ramp=False; self.ramp_idx=None; self.ramp_h=0; target=1.
        elif self.ramp:
            need=10
            if self.ramp_h>=need:
                self.ramp_idx+=1; self.ramp_h=0
                if self.ramp_idx>=2: self.ramp=False; self.ramp_idx=None; target=1.
                else: target=.65
            else: target=.55 if self.ramp_idx==0 else .65
            if self.ramp: self.ramp_h=self.ramp_h+1 if healthy else 0
        else: target=1.
        self.r40hist=(self.r40hist+[r40])[-6:]
        return float(target), bool(fastsig), bool(slowsig)

class ControlLDRC:
    """Exact current Simplified LD-RC v3 state transitions, compact transcription."""
    def __init__(self):
        self.episode=False; self.latched=False; self.streak=0; self.prev_native=1.; self.prev_desired=1.
    def step(self,native,effective_native,wcdd,r20,r40,spy20):
        healthy=finite(r20) and finite(r40) and r20>0 and r40>0
        self.streak=self.streak+1 if healthy else 0
        vre=finite(spy20) and spy20>LDRC_V
        reasons=[]
        if self.prev_native>=1-1e-12 and native<1-1e-12:
            self.episode=True; reasons.append('RECOVERY_EPISODE_START')
        cleared=self.latched and (self.streak>=LDRC_REC or vre)
        if cleared:
            self.latched=False; reasons.append('DIVERGENCE_CLEAR')
        desired=native
        if self.episode and native>=1-1e-12:
            if self.streak>=LDRC_REC or vre:
                self.episode=False; desired=1.; reasons.append('FULL_RISK_CERTIFIED')
            else:
                desired=self.prev_desired; reasons.append('FULL_RISK_HELD')
        avail=finite(wcdd) and finite(r20) and finite(spy20) and effective_native is not None and finite(effective_native)
        if not self.latched and not cleared:
            div=native>=1-1e-12 and effective_native is not None and effective_native>=1-1e-12 and avail and wcdd<=LDRC_DD and r20<=LDRC_R20 and spy20>=0.
            if div: self.latched=True; reasons.append('LD_ENTER_DIVERGENCE')
        if self.latched: desired=min(desired,LDRC_CEIL)
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return float(desired), '|'.join(reasons) if reasons else 'NORMAL'

class CandidateA:
    """Current LD-RC plus one early cross-surface recovery route."""
    def __init__(self):
        self.episode=False; self.latched=False
        self.full_streak=0; self.recent_positive_streak=0
        self.prev_native=1.; self.prev_desired=1.; self.episodes=0
        self.concordance_releases=0

    def step(self,native,effective_native,wcdd,recent_r20,recent_r40,spy20,wc_r20):
        full_healthy=(finite(recent_r20) and finite(recent_r40)
                      and recent_r20>0 and recent_r40>-0.04)
        self.full_streak=self.full_streak+1 if full_healthy else 0
        vre=finite(spy20) and spy20>LDRC_V
        reasons=[]

        if self.prev_native>=1-1e-12 and native<1-1e-12:
            if not self.episode: self.episodes+=1
            self.episode=True
            self.recent_positive_streak=0
            reasons.append('RECOVERY_EPISODE_START')

        if self.episode:
            if native>0 and finite(recent_r20) and recent_r20>0:
                self.recent_positive_streak+=1
            else:
                self.recent_positive_streak=0
        else:
            self.recent_positive_streak=0

        cleared=self.latched and (self.full_streak>=LDRC_REC or vre)
        if cleared:
            self.latched=False
            reasons.append('DIVERGENCE_CLEAR')

        desired=native
        if self.episode and native>=1-1e-12:
            concordant=(
                self.recent_positive_streak>=LDRC_REC
                and finite(wc_r20) and wc_r20>0
                and finite(recent_r20) and recent_r20>=wc_r20
                and finite(spy20) and spy20>=wc_r20
            )
            if self.full_streak>=LDRC_REC or vre or concordant:
                self.episode=False; desired=1.
                if concordant and self.full_streak<LDRC_REC and not vre:
                    self.concordance_releases+=1
                    reasons.append('FULL_RISK_CERTIFIED_CROSS_SURFACE')
                elif self.full_streak>=LDRC_REC:
                    reasons.append('FULL_RISK_CERTIFIED_PERSISTENCE')
                else:
                    reasons.append('FULL_RISK_CERTIFIED_SPY_V_REBOUND')
                self.recent_positive_streak=0
            else:
                desired=self.prev_desired
                reasons.append('FULL_RISK_HELD')

        avail=(finite(wcdd) and finite(recent_r20) and finite(spy20)
               and effective_native is not None and finite(effective_native))
        if not self.latched and not cleared:
            divergence=(
                native>=1-1e-12
                and effective_native is not None and finite(effective_native)
                and effective_native>=1-1e-12
                and avail and wcdd<=LDRC_DD
                and recent_r20<=LDRC_R20 and spy20>=0.0
            )
            if divergence:
                self.latched=True
                reasons.append('LD_ENTER_DIVERGENCE')

        if self.latched:
            desired=min(desired,LDRC_CEIL)
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return float(desired), '|'.join(reasons) if reasons else 'NORMAL'

class CandidateB:
    def __init__(self): self.episode=False; self.streak=0; self.prev_native=1.; self.prev_desired=1.; self.episodes=0
    def step(self,native,r20,spy20):
        healthy=finite(r20) and r20>0
        self.streak=self.streak+1 if healthy else 0
        reasons=[]
        if self.prev_native>=1-1e-12 and native<1-1e-12:
            if not self.episode: self.episodes+=1
            self.episode=True; reasons.append('EPISODE_START')
        desired=native
        if self.episode and native>=1-1e-12:
            release=(self.streak>=LDRC_REC) or (finite(spy20) and spy20>LDRC_V)
            if release:
                self.episode=False; desired=1.; reasons.append('RELEASE_R20_7' if self.streak>=LDRC_REC else 'RELEASE_SPY')
            else:
                desired=self.prev_desired; reasons.append('HOLD')
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return float(desired),'|'.join(reasons) if reasons else 'NORMAL'


_cash_frame=pd.read_csv(Path('backtester/data/GS3M_1996-12_2007-05.csv'))
_cash_frame['month']=pd.to_datetime(_cash_frame['month'])
_CASH_YIELD={pd.Timestamp(r.month):float(r.annual_yield_percent) for r in _cash_frame.itertuples(index=False)}

def bil_factors(bil,date,prevdate):
    if prevdate is None: return 0.,0.,1.
    if date not in bil.index: raise RuntimeError(f'canonical cash factor missing for {date}')
    gap=float(bil.loc[date,'gap_factor']); intra=float(bil.loc[date,'intraday_factor'])
    if min(gap,intra)<=0: raise RuntimeError(f'invalid canonical cash factor for {date}')
    return gap-1.0,intra-1.0,gap*intra
def nearest_split_authority(split_dates,ticker,date,observed):
    xs=split_dates.get(ticker,())
    best=None
    for d,v in xs:
        gap=abs((d-date).days)
        if gap<=5:
            err=abs(math.log(max(observed,1e-300)/max(v,1e-300)))
            cand=(err,gap,d,v)
            if best is None or cand<best: best=cand
    if best and best[0]<=math.log(1.08): return best[3]
    return None


def apply_overlay(nav, olda, newa, prev_close_eq, open_eq, close_eq, bil, date, prevdate):
    bo,bi,bc=bil_factors(bil,date,prevdate)
    if abs(newa-olda)<1e-15:
        wcf=close_eq/prev_close_eq
        bf=bc if olda<1 else 1.
        fac=olda*wcf+(1-olda)*bf
        trans_cost=0.
    else:
        won=open_eq/prev_close_eq-1
        win=close_eq/open_eq-1
        trans_cost=COST*abs(newa-olda)
        fac=(1+olda*won+(1-olda)*bo)*(1-trans_cost)*(1+newa*win+(1-newa)*bi)
    return nav*fac, trans_cost


def metrics(curve):
    curve=curve.dropna().astype(float)
    rets=curve.pct_change().dropna()
    years=(curve.index[-1]-curve.index[0]).days/365.2425
    cagr=(curve.iloc[-1]/curve.iloc[0])**(1/years)-1
    dd=curve/curve.cummax()-1
    sharpe=float(rets.mean()/rets.std(ddof=1)*np.sqrt(252)) if rets.std(ddof=1)>0 else np.nan
    return {'start':str(curve.index[0].date()),'end':str(curve.index[-1].date()),'sessions':int(len(curve)),
            'cagr':float(cagr),'max_drawdown':float(dd.min()),'sharpe':sharpe,
            'ending_multiple':float(curve.iloc[-1]/curve.iloc[0])}


def run():
    tick,tmap,sid,common,sector,exchange,firstdate,lastdate,issuer=load_meta(); n=len(tick)
    def _metadata(tid,ds): return _CANONICAL.metadata_for(str(sid[int(tid)]),str(ds)[:10])
    def sector_key(tid,ds):
        return f'SID:{sid[int(tid)]}'
    def issuer_key(tid,ds):
        return f'SID:{sid[int(tid)]}'
    actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()
    _BEST_TYPES=_bestclass.SecurityTypeEstimate(Path(os.environ['BEST_EFFORT_SECURITY_TYPES']),os.environ['BEST_EFFORT_CLASSIFICATION_SCENARIO'])
    _capacity_volumes=defaultdict(list)
    _sid_to_tid={str(value):i for i,value in enumerate(sid)}
    _exact_terminal_by_session={}; _exact_terminal_terms_hash=None
    if globals().get('_CANONICAL') is not None:
        def _terminal_resolve(_ticker,_session):
            _tid=strict_tid(_ticker,_session) if 'strict_tid' in globals() else tmap.get(str(_ticker))
            return None if _tid is None else str(sid[int(_tid)])
        def _terminal_issuer(_security_id,_ticker,_session):
            _tid=_sid_to_tid.get(str(_security_id))
            return (None,None) if _tid is None else (issuer_key(_tid,str(_session)), 'RESEARCH_STRICT_PIT')
        _loaded,_exact_terminal_terms_hash=load_frozen_terminal_terms(
            Path('backtester/data/causal-terminal-terms-v1.json'),
            Path('backtester/data/causal-terminal-terms-v1.SHA256'),
            sessions=list(_CANONICAL.sessions),
            resolve_identity=_terminal_resolve,
            meta={str(value):object() for value in sid},
            TerminalTerms=_ProductionTerminalTerms,
            TerminalKind=_ProductionTerminalKind,
            identity_binding='resolved',
            delivered_issuer_resolver=_terminal_issuer)
        for _session,_terms in _loaded.items():
            _exact_terminal_by_session[str(_session)]={
                _sid_to_tid[str(_term.security_id)]:_term for _term in _terms
                if str(_term.security_id) in _sid_to_tid}

    _SEC_COUNTS={'auto_common':0,'manual_common':0,'manual_non_common':0,'unknown_ineligible':0}
    _CANDIDATE_COVERAGE={'base_candidates':0,'known_classifications':0,'unknown_classifications':0,'sessions':0,'sessions_with_unknown':0,'worst_known_fraction':1.0,'worst_session':None,'first_unknown_session':None,'by_year':{}}
    _UNKNOWN_DETAIL={'by_ticker':{},'by_month':{},'by_cik_availability':{},'by_sec_evidence_availability':{},'by_security_type':{'unknown_ineligible':0}}
    _CANDIDATE_COVERAGE={'base_candidates':0,'known_classifications':0,'unknown_classifications':0,'sessions':0,'sessions_with_unknown':0,'worst_known_fraction':1.0,'worst_session':None,'first_unknown_session':None,'by_year':{}}
    _UNKNOWN_DETAIL={'by_ticker':{},'by_month':{},'by_cik_availability':{},'by_sec_evidence_availability':{},'by_security_type':{'unknown_ineligible':0}}
    def common_key(tid,ds):
        row=_metadata(tid,ds)
        if row is not None and row['security_type']=='common': _SEC_COUNTS['auto_common']+=1; return True
        if row is not None and row['security_type']=='non_common': _SEC_COUNTS['manual_non_common']+=1; return False
        _SEC_COUNTS['unknown_ineligible']+=1; return False

    def _hard_rank(_tid,_order):
        try: return _order.index(int(_tid))
        except ValueError: return len(_order)+1000

    def _median_top3(_durable,_hist,_lookback):
        _arr=[int(x) for x in _durable]
        if len(_arr)<2: return np.asarray(_arr,dtype=np.int32)
        _top=_arr[:3]; _hs=_hist[-int(_lookback):]
        def _key(_tid):
            _vals=[_hard_rank(_tid,_o) for _o in _hs]
            return (float(np.median(_vals)),_arr.index(_tid))
        _front=sorted(_top,key=_key)
        return np.asarray(_front+_arr[3:],dtype=np.int32)

    def _harden_order(_durable,_score,_hist):
        return _median_top3(_durable,_hist,5)

    ctl=ControlLDRC(); ca=CandidateA(); cb=CandidateB()
    L=260
    close_ring=np.full((L,n),np.nan,np.float32)
    r126=np.zeros((126,n),np.float32); rv126=np.zeros((126,n),bool); s126=np.zeros(n);q126=np.zeros(n);c126=np.zeros(n,np.int16)
    r21=np.zeros((21,n),np.float32); rv21=np.zeros((21,n),bool); s21=np.zeros(n);q21=np.zeros(n);c21=np.zeros(n,np.int16)
    dvbuf=np.zeros((20,n),np.float32); dvsum=np.zeros(n)
    opraw=np.full(n,np.nan); opsig=np.full(n,np.nan); clsig=np.full(n,np.nan); clraw=np.full(n,np.nan); volume=np.full(n,np.nan); rawdividend=np.zeros(n); canonicalsplit=np.ones(n)
    mom=np.full(n,np.nan); recent=np.full(n,np.nan); score=np.full(n,np.nan); adv=np.full(n,np.nan)
    last_factor=np.full(n,np.nan); touched=np.empty(0,np.int32); gday=-1; first_eligible=None
    shadow_dates=[]; shadow_eq=[]; damaged_hist=[]; stop_days=[]
    _rank_order_hist=[]
    recent_nav=1.; recent_nav_hist=[1.]; prior_recent_sel=tuple(); prior_close_map={}
    rows=[]; trade_rows=[]; gap_event_rows=[]; close_decision_rows=[]; _pending_meta={}; overlap_checks={}; buys=sells=split_events=div_events=0; scale_q0_candidate_skips=0; scale_one_share_entries=0; scale_cash_limited_decisions=0; scale_gap_clipped_entries=0; scale_entries=0; scale_lt1=0; scale_lt5=0; scale_lt10=0; scale_lt25=0; scale_lt50=0; scale_lt99=0; scale_min_entry_fraction=1.0; scale_max_entry_fraction=0.0; scale_entry_fraction_sum=0.0; buffer_blocked_open_entries=0; buffer_min_post_buy_excess=float('inf'); buffer_min_actual_cash=float(book.cash); buffer_reserve_violations=0; open_sizing_event_rows=[]; open_close_admissions=0; open_invalid_market_blocks=0; open_zero_quantity_blocks=0; open_cash_limited_execs=0; open_rounding_underfill_dollars=0.0; open_rounding_underfill_fraction_sum=0.0; open_full_target_execs=0; open_partial_target_execs=0; open_close_cash_scarcity_skips=0; open_close_whole_share_unaffordable_skips=0
    pending_native=1.; effective_native=1.
    pend={'control':1.,'A':1.,'B':1.}; eff={'control':1.,'A':1.,'B':1.}
    navs={'control':1.,'A':1.,'B':1.}; transition_cost={'control':0.,'A':0.,'B':0.}; transitions={'control':0,'A':0,'B':0}
    prev_close_eq=None; prev_perf_date=None
    # SPY normalized benchmark on closeadj, first measurement session rebased later.

    for y in range(2006,END.year+1):
        t0=time.time(); d=_CANONICAL.research_observations(y)
        d['open']=d['canonical_raw_open'].astype(float)*d['close'].astype(float)/d['closeunadj'].astype(float)
        d.date=pd.to_datetime(d.date); d=d[d.date<=END]
        d=d.dropna(subset=['ticker','date','close','closeunadj']).drop_duplicates(['ticker','date'],keep='last')
        ids=d.security_id.astype(str).map(_SID_TO_TID); d=d[ids.notna()].copy(); d['tid']=ids.loc[d.index].astype(np.int32).to_numpy()
        d.sort_values(['date','tid'],inplace=True,kind='mergesort')
        _quarter_last=set(pd.Timestamp(x) for x in d.groupby(d.date.dt.to_period('Q')).date.max())
        for date,g in d.groupby('date',sort=True):
            gday+=1; date=pd.Timestamp(date); ds=date.strftime('%Y-%m-%d')
            if touched.size:
                for a in (opraw,opsig,clsig,clraw,volume,mom,recent,score,adv): a[touched]=np.nan
                rawdividend[touched]=0.; canonicalsplit[touched]=1.
            tids=g.tid.to_numpy(np.int32,copy=False); touched=tids
            c=g.close.to_numpy(float,copy=False); cu=g.closeunadj.to_numpy(float,copy=False); oo=g.open.to_numpy(float,copy=False); vol=g.volume.to_numpy(float,copy=False)
            rawop=np.divide(oo*cu,c,out=np.full_like(oo,np.nan),where=np.isfinite(oo)&np.isfinite(cu)&np.isfinite(c)&(c>0))
            # Current main's sharadar_domains preserves liquidity via raw_close * raw_compatible_volume == split_adjusted_close * reported_volume.
            dv=np.nan_to_num(c*vol,nan=0.,posinf=0.,neginf=0.)
            lag21=close_ring[(gday-21)%L,tids] if gday>=21 else np.full(len(tids),np.nan)
            lag126=close_ring[(gday-126)%L,tids] if gday>=126 else np.full(len(tids),np.nan)
            prev=close_ring[(gday-1)%L,tids] if gday>=1 else np.full(len(tids),np.nan)
            rr=np.divide(c,lag21,out=np.full_like(c,np.nan),where=np.isfinite(lag21)&(lag21>0))-1
            mm=np.divide(lag21,lag126,out=np.full_like(c,np.nan),where=np.isfinite(lag21)&np.isfinite(lag126)&(lag126>0))-1
            lr=np.log(np.divide(c,prev,out=np.full_like(c,np.nan),where=np.isfinite(c)&(c>0)&np.isfinite(prev)&(prev>0)))
            k=gday%126; old=r126[k]; oldv=rv126[k]; s126-=old; q126-=old*old; c126-=oldv.astype(np.int16); old.fill(0); oldv.fill(False)
            m=np.isfinite(lr); old[tids[m]]=lr[m].astype(np.float32); oldv[tids[m]]=True; s126[tids[m]]+=lr[m]; q126[tids[m]]+=lr[m]*lr[m]; c126[tids[m]]+=1
            k2=gday%21; o2=r21[k2]; ov2=rv21[k2]; s21-=o2; q21-=o2*o2; c21-=ov2.astype(np.int16); o2.fill(0); ov2.fill(False)
            o2[tids[m]]=lr[m].astype(np.float32); ov2[tids[m]]=True; s21[tids[m]]+=lr[m]; q21[tids[m]]+=lr[m]*lr[m]; c21[tids[m]]+=1
            fsum=s126[tids]-s21[tids]; fsq=q126[tids]-q21[tids]; fcnt=c126[tids]-c21[tids]
            var=np.divide(fsq-fsum*fsum/np.maximum(fcnt,1),np.maximum(fcnt-1,1),out=np.full(len(tids),np.nan),where=fcnt>1)
            fvol=np.sqrt(np.maximum(var,0))*np.sqrt(252)
            sc=np.divide(np.log1p(mm),fvol,out=np.full(len(tids),np.nan),where=np.isfinite(mm)&(mm>-1)&np.isfinite(fvol)&(fvol>0))
            kd=gday%20; dvsum-=dvbuf[kd]; dvbuf[kd].fill(0); dvbuf[kd,tids]=dv.astype(np.float32); dvsum[tids]+=dv
            av=dvsum[tids]/20 if gday>=19 else np.full(len(tids),np.nan)
            close_ring[gday%L].fill(np.nan); close_ring[gday%L,tids]=c.astype(np.float32)
            opraw[tids]=rawop; opsig[tids]=oo; clsig[tids]=c; clraw[tids]=cu; volume[tids]=vol; rawdividend[tids]=g.dividend_per_share.to_numpy(float,copy=False); canonicalsplit[tids]=g.split_ratio.to_numpy(float,copy=False); mom[tids]=mm; recent[tids]=rr; score[tids]=sc; adv[tids]=av
            dt64=np.datetime64(date.date()); listed=(firstdate[tids]<=dt64); continuous=c126[tids]>=126
            # Exchange is intentionally NOT used here because a single current TICKERS snapshot cannot establish historical exchange authority.
            _base_elig=listed&continuous&np.isfinite(mm)&np.isfinite(rr)&np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&np.isfinite(dv)&(dv>=MIN_DAY_DV)&np.isfinite(sc)&(fvol>0)
            _sec_ok=np.zeros(len(tids),dtype=bool); _known=0; _unknown=0
            for _j in np.flatnonzero(_base_elig):
                _tid=int(tids[int(_j)]); _tk=str(tick[_tid]).upper(); _u0=_SEC_COUNTS['unknown_ineligible']; _sec_ok[int(_j)]=common_key(_tid,ds)
                if _SEC_COUNTS['unknown_ineligible']>_u0:
                    _unknown+=1; _UNKNOWN_DETAIL['by_security_type']['unknown_ineligible']+=1
                    _mr=_metadata(_tid,ds); _issuer='' if _mr is None else str(_mr['issuer_id'])
                    _cik=None if not _issuer.startswith('SEC_CIK:') else _issuer.split(':',1)[1]
                    _cik_key='available' if _cik is not None else 'missing'
                    _UNKNOWN_DETAIL['by_cik_availability'][_cik_key]=_UNKNOWN_DETAIL['by_cik_availability'].get(_cik_key,0)+1
                    _ev='missing_canonical_metadata' if _mr is None else str(_mr['security_type_source']).lower()
                    _UNKNOWN_DETAIL['by_sec_evidence_availability'][_ev]=_UNKNOWN_DETAIL['by_sec_evidence_availability'].get(_ev,0)+1
                    _mon=ds[:7]; _UNKNOWN_DETAIL['by_month'][_mon]=_UNKNOWN_DETAIL['by_month'].get(_mon,0)+1
                    _td=_UNKNOWN_DETAIL['by_ticker'].setdefault(_tk,{'observations':0,'first_session':ds,'last_session':ds,'cik_available':0,'cik_missing':0,'evidence':{}})
                    _td['observations']+=1; _td['last_session']=ds; _td['cik_available' if _cik is not None else 'cik_missing']+=1; _td['evidence'][_ev]=_td['evidence'].get(_ev,0)+1
                else: _known+=1
            _nbase=_known+_unknown
            if _nbase:
                _CANDIDATE_COVERAGE['base_candidates']+=_nbase; _CANDIDATE_COVERAGE['known_classifications']+=_known; _CANDIDATE_COVERAGE['unknown_classifications']+=_unknown; _CANDIDATE_COVERAGE['sessions']+=1
                _yf=_CANDIDATE_COVERAGE['by_year'].setdefault(ds[:4],{'base_candidates':0,'known_classifications':0,'unknown_classifications':0,'sessions':0,'sessions_with_unknown':0})
                _yf['base_candidates']+=_nbase; _yf['known_classifications']+=_known; _yf['unknown_classifications']+=_unknown; _yf['sessions']+=1
                if _unknown:
                    _CANDIDATE_COVERAGE['sessions_with_unknown']+=1; _yf['sessions_with_unknown']+=1
                    if _CANDIDATE_COVERAGE['first_unknown_session'] is None: _CANDIDATE_COVERAGE['first_unknown_session']=ds
                _frac=_known/_nbase
                if _frac<_CANDIDATE_COVERAGE['worst_known_fraction']:
                    _CANDIDATE_COVERAGE['worst_known_fraction']=_frac; _CANDIDATE_COVERAGE['worst_session']=ds
            for _j in np.flatnonzero(_base_elig):
                _tid=int(tids[int(_j)]); _mr=_metadata(_tid,ds)
                if _mr is None or str(_mr.get('security_type','')).strip().lower()=='unknown':
                    _estimated=_BEST_TYPES.classify(str(sid[_tid]),ds)
                    _sec_ok[int(_j)]=_estimated=='common'
            elig=_sec_ok&_base_elig
            et=tids[elig]
            if len(et):
                sid_et=sid[et]; ordm=np.lexsort((sid_et,-mom[et])); rawall=et[ordm]
                nk=min(len(et),max(25,int(math.ceil(len(et)*TOP)))); pool=rawall[:nk]
                ordscore=np.lexsort((tick[pool],sid[pool],-score[pool])); durable=pool[ordscore]
                ordrec=np.lexsort((sid_et,-recent[et])); recsel=et[ordrec[:nk]]
            else:
                rawall=pool=durable=recsel=np.empty(0,np.int32); nk=0
            _rank_order_hist.append(tuple(int(x) for x in durable))
            if len(_rank_order_hist)>5: del _rank_order_hist[:-5]
            inpool=np.zeros(n,bool); inpool[pool]=True
            if first_eligible is None and len(et)>=25: first_eligible=gday
            # Causal recent-leadership witness: prior close selection earns current close-to-close return.
            if prior_recent_sel:
                vals=[]
                for tid0 in prior_recent_sel:
                    p0=prior_close_map.get(int(tid0)); p1=clsig[int(tid0)]
                    if not(finite(p0) and p0>0 and finite(p1) and p1>0):
                        raise RuntimeError(f'unresolved recent-leadership return: {ds} {tick[int(tid0)]}')
                    vals.append(float(p1)/float(p0)-1)
                recent_nav*=1+sum(vals)/len(prior_recent_sel)
            recent_nav_hist.append(recent_nav)
            recent_r20=recent_nav_hist[-1]/recent_nav_hist[-21]-1 if len(recent_nav_hist)>20 else None
            recent_r40=recent_nav_hist[-1]/recent_nav_hist[-41]-1 if len(recent_nav_hist)>40 else None
            def _leadership_term_tid(_ticker):
                return strict_tid(_ticker,ds) if 'strict_tid' in globals() else tmap.get(str(_ticker))
            _leadership_terminal_tids={z for tk,rs in actions.get(date,{}).items() if (z:=_leadership_term_tid(tk)) is not None and any(a in TERMINAL for a,_,_ in rs)}
            _leadership_terminal_tids.update(_exact_terminal_by_session.get(ds,{}))
            prior_recent_sel=tuple(int(t) for t in recsel if int(t) not in _leadership_terminal_tids)
            prior_close_map={int(t):float(clsig[int(t)]) for t in prior_recent_sel if finite(clsig[int(t)])}
            if ds in ('2008-12-23','2022-01-03'):
                overlap_checks[ds]={'eligible':int(len(et)),'population':int(nk),'overlap':int(len(set(map(int,pool))&set(map(int,recsel))))}

            # Open: settle prior receivables, transform splits, then execute pending exits/buys.
            due=sum(a for dd,a in book.receivables if dd<=gday); book.cash+=due; book.receivables=[x for x in book.receivables if x[0]>gday]
            for tid0,ratio0 in zip(tids,canonicalsplit[tids]):
                tid=int(tid0); ratio=float(ratio0)
                if abs(ratio-1.0)>1e-12:
                    split_events+=1
                    for s in book.slots:
                        if s.held() and s.tid==tid: s.qty*=ratio
                        if s.reserved() and s.pending_tid==tid:
                            q=s.pending_shares*ratio
                            if abs(q-round(q))>1e-8: _pending_meta.pop(id(s),None); s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_intended_capital=0.
                            else: s.pending_shares=float(round(q))
            # Capture prior-close entitlement after split-domain conversion,
            # before any same-open exits or buys.
            prior_qty={s.tid:s.qty for s in book.slots if s.held()}
            dayact=actions.get(date,{})
            def _term_tid(_ticker):
                return strict_tid(_ticker,ds) if 'strict_tid' in globals() else tmap.get(str(_ticker))
            term_tids={z for tk,rs in dayact.items() if (z:=_term_tid(tk)) is not None and any(a in TERMINAL for a,_,_ in rs)}
            _exact_terms=_exact_terminal_by_session.get(ds,{})
            term_tids.update(_exact_terms)
            for s in book.slots:
                if s.reserved() and s.pending_tid in term_tids: _pending_meta.pop(id(s),None); s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_intended_capital=0.
                if not(s.held() and s.tid in term_tids): continue
                _term=_exact_terms.get(s.tid)
                if _term is not None:
                    _kind=getattr(_term.kind,'value',str(_term.kind))
                    _econ=_research_exact_terminal_economics(
                        kind=_kind, shares=s.qty,
                        cash_per_share=getattr(_term,'cash_per_share',None),
                        exchange_ratio=getattr(_term,'exchange_ratio',None),
                        cash_in_lieu_price=getattr(_term,'cash_in_lieu_price_per_delivered_share',None))
                    _old_tid=s.tid; book.cash+=float(_econ['cash']); book.terminal_pending.pop(_old_tid,None)
                    if _kind in ('WRITE_OFF','CASH_MERGER') or int(_econ['delivered_shares'])<=0:
                        book.sec_ready[_old_tid]=gday+COOLDOWN
                        s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN
                    else:
                        _delivered=_sid_to_tid.get(str(getattr(_term,'delivered_security_id',None)))
                        _ratio=float(getattr(_term,'exchange_ratio'))
                        if _delivered is None or not(finite(_ratio) and _ratio>0):
                            raise RuntimeError(f'exact terminal delivered identity unresolved: {ds} {tick[_old_tid]}')
                        s.tid=int(_delivered); s.qty=float(_econ['delivered_shares'])
                        if finite(s.entry_sig): s.entry_sig=float(s.entry_sig)/_ratio
                        if finite(s.peak): s.peak=float(s.peak)/_ratio
                    continue
                # Production C1: incomplete documented terms become a carried
                # claim. A real prior trustworthy mark is required.
                _prior=book.last_raw.get(s.tid,np.nan)
                if finite(_prior) and _prior>0:
                    book.terminal_pending.setdefault(s.tid,{'missing_sessions':0,'stale_at_event':0})
                elif finite(clraw[s.tid]) and clraw[s.tid]>0 and finite(volume[s.tid]) and volume[s.tid]>0:
                    _tid=s.tid; book.cash+=s.qty*float(clraw[_tid]); book.sec_ready[_tid]=gday+COOLDOWN
                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN
                else:
                    raise RuntimeError(f'known terminal event cannot be valued causally: {ds} {tick[s.tid]}')
            # Production-equivalent ex-date entitlement is part of overnight open equity.
            for tid in tids:
                q=prior_qty.get(int(tid),0.); rawdiv=float(rawdividend[int(tid)])
                if q>0 and rawdiv>0: book.receivables.append((gday+1,q*rawdiv)); div_events+=1
            open_eq,_=book.equity(opraw)
            for s in book.slots:
                if not(s.held() and s.pending_sell): continue
                px=opraw[s.tid]
                if finite(px) and px>0 and finite(volume[s.tid]) and volume[s.tid]>0:
                    _sell_qty=float(s.qty); _sell_tid=int(s.tid); book.cash+=s.qty*float(px)*(1-COST); sells+=1; trade_rows.append({'Transaction date':ds,'Buy or sell':'SELL','Ticker':str(tick[_sell_tid]),'Ticker name':'','Amount of shares':_sell_qty})
                    if s.sell_reason=='stop': stop_days.append(gday)
                    _sold_tid=s.tid; book.sec_ready[_sold_tid]=gday+COOLDOWN; book.terminal_pending.pop(_sold_tid,None)
                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN
            for s in book.slots:
                if not(s.reserved() and not s.held()): continue
                tid=s.pending_tid; px=opraw[tid]; _pm=_pending_meta.get(id(s),{})
                _desired=float(s.pending_intended_capital); _cash_before=float(book.cash)
                if finite(px) and px>0 and finite(volume[tid]) and volume[tid]>0:
                    _execution_budget=max(0.0,min(_desired,_cash_before)); q=float(math.floor(_execution_budget/(float(px)*(1+COST)))) if _execution_budget>0 else 0.0
                    if q>1e-12:
                        _gross=float(q)*float(px)*(1+COST); _frac=(_gross/_desired if _desired>0 else 0.0)
                        _cash_limited=bool(_cash_before+1e-8<_desired); _rounding=max(0.0,_execution_budget-_gross)
                        _round_frac=(_rounding/_execution_budget if _execution_budget>0 else 0.0)
                        scale_entries+=1; scale_one_share_entries+=int(abs(q-1.0)<=1e-9); scale_entry_fraction_sum+=_frac; scale_min_entry_fraction=min(scale_min_entry_fraction,_frac); scale_max_entry_fraction=max(scale_max_entry_fraction,_frac); scale_lt1+=int(_frac<0.01); scale_lt5+=int(_frac<0.05); scale_lt10+=int(_frac<0.10); scale_lt25+=int(_frac<0.25); scale_lt50+=int(_frac<0.50); scale_lt99+=int(_frac<0.99)
                        open_cash_limited_execs+=int(_cash_limited); open_rounding_underfill_dollars+=_rounding; open_rounding_underfill_fraction_sum+=_round_frac; open_full_target_execs+=int(abs(_gross-_desired)<=max(1e-8,1e-10*_desired)); open_partial_target_execs+=int(abs(_gross-_desired)>max(1e-8,1e-10*_desired))
                        open_sizing_event_rows.append({'decision_date':str(_pm.get('decision_date','')),'execution_date':ds,'ticker':str(tick[tid]),'mode':'whole','close_price':float(_pm.get('close_price',np.nan)),'open_price':float(px),'intended_target_dollars':_desired,'cash_before_execution':_cash_before,'execution_budget':_execution_budget,'executed_shares':float(q),'executed_gross_dollars':_gross,'entry_fraction_of_intended':_frac,'cash_limited_at_open':_cash_limited,'rounding_underfill_dollars':_rounding,'rounding_underfill_fraction':_round_frac,'close_required_10bp_cushion':float(_pm.get('close_required_reserve',np.nan)),'close_cash_above_cushion':float(_pm.get('close_uncommitted_cash',np.nan)),'blocked':False,'block_reason':''})
                        book.cash-=_gross; buffer_min_actual_cash=min(buffer_min_actual_cash,float(book.cash)); buffer_min_post_buy_excess=min(buffer_min_post_buy_excess,float(book.cash)); trade_rows.append({'Transaction date':ds,'Buy or sell':'BUY','Ticker':str(tick[tid]),'Ticker name':'','Amount of shares':float(q)}); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1
                    else:
                        open_zero_quantity_blocks+=1; buffer_blocked_open_entries+=1; open_sizing_event_rows.append({'decision_date':str(_pm.get('decision_date','')),'execution_date':ds,'ticker':str(tick[tid]),'mode':'whole','close_price':float(_pm.get('close_price',np.nan)),'open_price':float(px),'intended_target_dollars':_desired,'cash_before_execution':_cash_before,'execution_budget':_execution_budget,'executed_shares':0.0,'executed_gross_dollars':0.0,'entry_fraction_of_intended':0.0,'cash_limited_at_open':bool(_cash_before+1e-8<_desired),'rounding_underfill_dollars':_execution_budget,'rounding_underfill_fraction':1.0 if _execution_budget>0 else 0.0,'close_required_10bp_cushion':float(_pm.get('close_required_reserve',np.nan)),'close_cash_above_cushion':float(_pm.get('close_uncommitted_cash',np.nan)),'blocked':True,'block_reason':'ZERO_QUANTITY_AT_OPEN'})
                else:
                    open_invalid_market_blocks+=1; buffer_blocked_open_entries+=1; open_sizing_event_rows.append({'decision_date':str(_pm.get('decision_date','')),'execution_date':ds,'ticker':str(tick[tid]),'mode':'whole','close_price':float(_pm.get('close_price',np.nan)),'open_price':float(px) if finite(px) else np.nan,'intended_target_dollars':_desired,'cash_before_execution':_cash_before,'execution_budget':0.0,'executed_shares':0.0,'executed_gross_dollars':0.0,'entry_fraction_of_intended':0.0,'cash_limited_at_open':False,'rounding_underfill_dollars':0.0,'rounding_underfill_fraction':0.0,'close_required_10bp_cushion':float(_pm.get('close_required_reserve',np.nan)),'close_cash_above_cushion':float(_pm.get('close_uncommitted_cash',np.nan)),'blocked':True,'block_reason':'INVALID_OPEN_MARKET'})
                _pending_meta.pop(id(s),None); s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_intended_capital=0.
            for _tid0,_sig_close,_raw_close,_reported_volume in zip(tids,c,cu,vol):
                if finite(_sig_close) and _sig_close>0 and finite(_raw_close) and _raw_close>0 and finite(_reported_volume) and _reported_volume>0:
                    _raw_compatible=float(_reported_volume)*float(_sig_close)/float(_raw_close)
                    if finite(_raw_compatible) and _raw_compatible>0:
                        _hist=_capacity_volumes[int(_tid0)]; _hist.append(float(_raw_compatible))
                        if len(_hist)>20: del _hist[:-20]

            # Canonical dividends already use the as-traded share basis.
            for tid0 in tids:
                if finite(clraw[int(tid0)]) and clraw[int(tid0)]>0: book.last_raw[int(tid0)]=float(clraw[int(tid0)])

            # Production C1 sweep: age only sessions lacking a current mark.
            for _tid in list(book.terminal_pending):
                _slot=next((x for x in book.slots if x.held() and x.tid==_tid),None)
                if _slot is None:
                    book.terminal_pending.pop(_tid,None); continue
                if _tid in term_tids: continue
                if finite(clraw[_tid]) and clraw[_tid]>0: continue
                _rec=book.terminal_pending[_tid]; _rec['missing_sessions']+=1
                if _rec['missing_sessions'] < 10: continue
                _px=book.last_raw.get(_tid,np.nan)
                if not(finite(_px) and _px>0):
                    raise RuntimeError(f'pending terminal settlement lost trustworthy mark: {ds} {tick[_tid]}')
                book.cash+=_slot.qty*float(_px); book.sec_ready[_tid]=gday+COOLDOWN; book.terminal_pending.pop(_tid,None)
                _slot.tid=-1; _slot.qty=0.; _slot.entry_sig=np.nan; _slot.peak=np.nan; _slot.entry_day=-1; _slot.reviewed=False; _slot.pending_sell=False; _slot.sell_reason=''; _slot.ready_day=gday+COOLDOWN

            # Close: peaks/exits, mark equity, breadth, then admissions.
            for s in book.slots:
                if not s.held(): continue
                px=clsig[s.tid]
                if s.entry_day==gday:
                    if finite(px) and px>0: s.peak=float(px)
                elif finite(px) and px>0:
                    s.peak=float(px) if not finite(s.peak) else max(float(s.peak),float(px))
                age=gday-s.entry_day
                if finite(px) and finite(s.peak) and s.peak>0 and float(px)<=s.peak*STOP_RET:
                    s.pending_sell=True; s.sell_reason='stop'
                elif age>=REVIEW_AGE and not s.reviewed and finite(px):
                    qualifies=bool(inpool[s.tid] and finite(recent[s.tid]) and recent[s.tid]>=0)
                    underwater=finite(s.entry_sig) and float(px)<s.entry_sig
                    if underwater and not qualifies: s.pending_sell=True; s.sell_reason='review'
                    else: s.reviewed=True
            eq,unresolved=book.equity(clraw)
            held=[]
            for s in book.slots:
                if not s.held(): continue
                tid=s.tid; px=clsig[tid]
                own=(float(px)/s.peak-1) if finite(px) and finite(s.peak) and s.peak>0 else None
                r21v=float(recent[tid]) if finite(recent[tid]) else None
                lag63=close_ring[(gday-63)%L,tid] if gday>=63 else np.nan
                r63v=float(px/lag63-1) if finite(px) and finite(lag63) and lag63>0 else None
                age=gday-s.entry_day
                green=finite(own) and own>-.075 and finite(r21v) and r21v>0 and (age<63 or (finite(r63v) and r63v>0))
                red=finite(own) and own<=-.10 and finite(r21v) and r21v<0
                held.append((tid,sector_key(tid,ds),own,r21v,r63v,age,green,red))
            green_b,dam_b=dynamic_peer_breadth(held,gday,close_ring,spy,shadow_dates)
            if first_eligible is not None and gday>=first_eligible:
                ready=[s for s in book.slots if not s.held() and not s.reserved() and gday>=s.ready_day]
                if ready and not unresolved and book.cash>0:
                    budget=len(ready) if not book.initialized else 1
                    heldids=book.held_ids(); resids=book.reserved_ids()
                    heldissuers={issuer_key(s.tid,ds) for s in book.slots if s.held()}; resissuers={issuer_key(s.pending_tid,ds) for s in book.slots if s.reserved()}
                    ad=0
                    for tid0 in _harden_order(durable,score,_rank_order_hist):
                        if ad>=budget or ad>=len(ready): break
                        tid=int(tid0)
                        if not finite(recent[tid]) or recent[tid]<0: continue
                        if tid in heldids or tid in resids or book.sec_ready.get(tid,-1)>gday or tid in term_tids: continue
                        if issuer_key(tid,ds) in heldissuers or issuer_key(tid,ds) in resissuers: continue
                        px=clraw[tid]
                        if not(finite(px) and px>0): continue
                        _desired=float(eq*ENTRY_W); _buffer_required_close=max(0.0,float(eq)*0.001); _buffer_available_close=max(0.0,float(book.cash)-_buffer_required_close); _funding_fraction=(float(min(_desired,_buffer_available_close))/_desired if _desired>0 else 0.0)
                        if _buffer_available_close<=1e-12: scale_q0_candidate_skips+=1; open_close_cash_scarcity_skips+=1; close_decision_rows.append({'decision_date':ds,'ticker':str(tick[tid]),'outcome':'Q0_SKIP','planned_shares':0,'close_price':float(px),'close_nav':float(eq),'cash_before_decision':float(book.cash),'required_reserve':float(_buffer_required_close),'uncommitted_cash_after_reserve':float(_buffer_available_close),'intended_capital':float(_desired),'funding_fraction':float(_funding_fraction),'q0_reason':'CASH_SCARCITY','buffer_basis_points':10}); continue
                        _one_share_close_cost=float(px)*(1+COST)
                        if float(book.cash)+1e-12<_one_share_close_cost: scale_q0_candidate_skips+=1; open_close_whole_share_unaffordable_skips+=1; close_decision_rows.append({'decision_date':ds,'ticker':str(tick[tid]),'outcome':'Q0_SKIP','planned_shares':0,'close_price':float(px),'close_nav':float(eq),'cash_before_decision':float(book.cash),'required_reserve':float(_buffer_required_close),'uncommitted_cash_after_reserve':float(_buffer_available_close),'intended_capital':float(_desired),'funding_fraction':float(_funding_fraction),'q0_reason':'TOTAL_CASH_ONE_SHARE_UNAFFORDABLE_AT_CLOSE','buffer_basis_points':10}); continue
                        scale_cash_limited_decisions+=int(_funding_fraction<0.999999999); close_decision_rows.append({'decision_date':ds,'ticker':str(tick[tid]),'outcome':'PLAN_OPEN_SIZE','planned_shares':0,'close_price':float(px),'close_nav':float(eq),'cash_before_decision':float(book.cash),'required_reserve':float(_buffer_required_close),'uncommitted_cash_after_reserve':float(_buffer_available_close),'intended_capital':float(_desired),'funding_fraction':float(_funding_fraction),'q0_reason':'','buffer_basis_points':10})
                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=0.; s.pending_signal_day=gday; s.pending_intended_capital=_desired; _pending_meta[id(s)]={'decision_date':ds,'close_price':float(px),'close_nav':float(eq),'close_cash_before':float(book.cash),'close_required_reserve':float(_buffer_required_close),'close_uncommitted_cash':float(_buffer_available_close),'intended_capital':float(_desired)}; open_close_admissions+=1; resids.add(tid); resissuers.add(issuer_key(tid,ds)); ad+=1
            buffer_min_actual_cash=min(buffer_min_actual_cash,float(book.cash)); shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)
            peak=max(shadow_eq); dd=eq/peak-1
            r5=eq/shadow_eq[-6]-1 if len(shadow_eq)>=6 else None
            r10=eq/shadow_eq[-11]-1 if len(shadow_eq)>=11 else None
            r20=eq/shadow_eq[-21]-1 if len(shadow_eq)>=21 else None
            r40=eq/shadow_eq[-41]-1 if len(shadow_eq)>=41 else None
            ddam5=dam_b-damaged_hist[-6] if len(damaged_hist)>=6 else None
            stops20=sum(1 for q in stop_days if 0<=gday-q<20)
            spy20=float(spy.loc[date,'r20']) if date in spy.index and finite(spy.loc[date,'r20']) else None
            volacc=float(spy.loc[date,'volacc']) if date in spy.index and finite(spy.loc[date,'volacc']) else None
            native_target,fastsig,slowsig=native.step((dd,r5,r10,r20,r40,dam_b,green_b,ddam5,spy20,volacc,stops20,eq))
            ctl_d,ctl_reason=ctl.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20)
            a_d,a_reason=ca.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20,r20)
            b_d,b_reason=cb.step(native_target,recent_r20,spy20)

            if date in _quarter_last and date < START:
                print(f'[CERT_PROGRESS] role=research date={ds} phase=WARMUP cagr=N/A',flush=True)
            if date>=START:
                if prev_close_eq is None:
                    # first measured open receives prior close's pending targets.
                    effective_native=pending_native
                    for kname in eff: eff[kname]=pend[kname]
                else:
                    effective_native=pending_native
                    for kname in ('control','A','B'):
                        olda=eff[kname]; newa=pend[kname]
                        if abs(newa-olda)>1e-15: transitions[kname]+=1
                        navs[kname],tc=apply_overlay(navs[kname],olda,newa,prev_close_eq,open_eq,eq,bil,date,prev_perf_date)
                        transition_cost[kname]+=tc
                        eff[kname]=newa
                spy_nav=np.nan
                if date in spy.index and START in spy.index:
                    spy_nav=float(spy.loc[date,'closeadj'])/float(spy.loc[START,'closeadj'])
                _rank_ids=[str(sid[int(x)]) for x in durable]
                _position_ids=sorted(str(sid[int(s.tid)]) for s in book.slots if s.held())
                _rank_hash=hashlib.sha256(json.dumps(_rank_ids,separators=(',',':')).encode()).hexdigest()
                _position_hash=hashlib.sha256(json.dumps(_position_ids,separators=(',',':')).encode()).hexdigest()
                rows.append({'date':date,'shadow_equity':eq,'open_equity':open_eq,'wc_dd':dd,'damaged':dam_b,'green':green_b,
                             'recent_r20':recent_r20,'recent_r40':recent_r40,'spy_r20':spy20,'native_close_target':native_target,
                             'effective_native':effective_native,'control_allocation':eff['control'],'A_allocation':eff['A'],'B_allocation':eff['B'],
                             'control_nav':navs['control'],'A_nav':navs['A'],'B_nav':navs['B'],'spy_nav':spy_nav,
                             'control_reason':a_reason,'A_reason':a_reason,'B_reason':b_reason,'fast_signal':fastsig,'slow_signal':slowsig,'eligible_count':int(len(et)),'leadership_population':int(nk),'held_count':int(len(held)),'research_eligible_universe':int(len(et)),'research_ranking_count':int(len(durable)),'research_ranking_sha256':_rank_hash,'research_selected_positions_sha256':_position_hash,'research_selected_positions':json.dumps(_position_ids,separators=(',',':')),'research_ldrc_state':json.dumps(ca.__dict__,sort_keys=True,separators=(',',':'))})
                if date in _quarter_last:
                    _elapsed=(date-START).days/365.2425
                    _cc=0.0 if _elapsed<=0 else float(navs['control'])**(1.0/_elapsed)-1.0
                    _spy_multiple=float(spy.loc[date,'closeadj'])/float(spy.loc[START,'closeadj'])
                    _spy_cagr=0.0 if _elapsed<=0 else _spy_multiple**(1.0/_elapsed)-1.0
                    print(f'[CERT_CAGR] role=research date={ds} cagr={_cc:.12f}',flush=True)
                    print(f'[CERT_CAGR] role=spy date={ds} cagr={_spy_cagr:.12f}',flush=True)
                prev_perf_date=date; prev_close_eq=eq
            pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d
        if rows:
            _curve=pd.Series([float(r['control_nav']) for r in rows], index=pd.to_datetime([r['date'] for r in rows]))
            _yrs=(_curve.index[-1]-_curve.index[0]).days/365.2425
            _cagr=float((_curve.iloc[-1]/_curve.iloc[0])**(1/_yrs)-1) if _yrs>0 and _curve.iloc[-1]>0 else float('nan')
            print(f'[YEAR-END] mode={MODE} year={y} session={_curve.index[-1].date()} multiple={_curve.iloc[-1]/_curve.iloc[0]:.10f} cagr={_cagr:.10%}',flush=True)
        print(f'YEAR {y} rows={len(d):,} seconds={time.time()-t0:.1f}',flush=True)

    out=pd.DataFrame(rows)
    out.to_csv(OUT/'daily.csv',index=False)
    pd.DataFrame(trade_rows,columns=['Transaction date','Buy or sell','Ticker','Ticker name','Amount of shares']).to_csv(OUT/'transactions.csv',index=False)
    pd.DataFrame(gap_event_rows,columns=['decision_date','execution_date','ticker','intended_shares','executed_shares','close_price_used_for_planning','next_open_price','close_to_open_percentage_gap','cash_available_before_execution','required_reserve','uncommitted_cash_after_reserve','close_required_reserve','close_uncommitted_cash_after_reserve','intended_notional','executed_notional','became_q0','buffer_basis_points','gap_alone_would_clip','open_uncommitted_cash_change_vs_close']).to_csv(OUT/'gap-events.csv',index=False)
    pd.DataFrame(close_decision_rows,columns=['decision_date','ticker','outcome','planned_shares','close_price','close_nav','cash_before_decision','required_reserve','uncommitted_cash_after_reserve','intended_capital','funding_fraction','q0_reason','buffer_basis_points']).to_csv(OUT/'close-decisions.csv',index=False)
    pd.DataFrame(open_sizing_event_rows,columns=['decision_date','execution_date','ticker','mode','close_price','open_price','intended_target_dollars','cash_before_execution','execution_budget','executed_shares','executed_gross_dollars','entry_fraction_of_intended','cash_limited_at_open','rounding_underfill_dollars','rounding_underfill_fraction','close_required_10bp_cushion','close_cash_above_cushion','blocked','block_reason']).to_csv(OUT/'open-sizing-events.csv',index=False)
    idx=out.set_index('date')
    summary={
        'code_commit':COMMIT,
        'window':[str(START.date()),str(END.date())],
        'evidence_level':('full_stack_PIT_SEC_CIK_SIC_plus_PIT_ACTIONS' if PIT_MODE else 'research_non_PIT_current_TICKERS_and_ACTIONS'),
        'replay_mode':MODE,
        'canonical_pit_dataset_hash':_CANONICAL.dataset_hash,
        'strict_identity_audit':_PIT_IDENTITY_AUDIT,
        'strict_security_type_counts':_SEC_COUNTS,
        'financial_grade_dividend_lag_sessions':1,
        'financial_grade_requires_resolved_nav':True,
        'financial_grade_missing_leadership_return_policy':'FAIL_CLOSED',
        'strict_candidate_security_type_coverage':_CANDIDATE_COVERAGE,
        'strict_candidate_security_type_unknown_breakdown':_UNKNOWN_DETAIL,
        'liquidity_domain':'current_main_equivalent: SEP.close * reported SEP.volume; algebraically raw close * raw-compatible volume per sharadar_domains.py',
        'exchange_gate':'not applied because supplied current TICKERS snapshot cannot establish historical exchange authority',
        'metrics':{k:metrics(idx[f'{k}_nav']) for k in ('control','A','B')},
        'spy':metrics(idx['spy_nav'].dropna()),
        'transition_counts':transitions,
        'modeled_allocation_transition_cost_sum':transition_cost,
        'buys':buys,'sells':sells,'split_events_applied':split_events,'dividend_events_held':div_events,
        'wealth_core_capital_scale':{'initial_capital':float(100000.0),'entries':int(scale_entries),'q0_candidate_skips':int(scale_q0_candidate_skips),'one_share_entries':int(scale_one_share_entries),'cash_limited_decisions':int(scale_cash_limited_decisions),'gap_clipped_entries':int(scale_gap_clipped_entries),'entry_fraction_lt_1pct':int(scale_lt1),'entry_fraction_lt_5pct':int(scale_lt5),'entry_fraction_lt_10pct':int(scale_lt10),'entry_fraction_lt_25pct':int(scale_lt25),'entry_fraction_lt_50pct':int(scale_lt50),'entry_fraction_lt_99pct':int(scale_lt99),'minimum_entry_fraction':(float(scale_min_entry_fraction) if scale_entries else None),'maximum_entry_fraction':(float(scale_max_entry_fraction) if scale_entries else None),'average_entry_fraction':(float(scale_entry_fraction_sum/scale_entries) if scale_entries else None)},
        'leadership_overlap_checks':overlap_checks,
        'candidate_A_episodes':ca.episodes,'candidate_A_concordance_releases':ca.concordance_releases,'candidate_B_episodes':cb.episodes,'correlation_peer_stats':PEER_STATS,
    }
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2))
    _buy_q=[float(r['Amount of shares']) for r in trade_rows if r['Buy or sell']=='BUY']
    _telemetry={'buffer_basis_points':10,'buffer_fraction':0.001,'blocked_open_entries':int(buffer_blocked_open_entries),'gap_clipped_entries':int(sum(1 for r in gap_event_rows if int(r['executed_shares'])>=1)),'open_shortfall_events':int(len(gap_event_rows)),'minimum_post_buy_cash_excess_over_required_reserve':(float(buffer_min_post_buy_excess) if _buy_q else None),'reserve_violations':int(buffer_reserve_violations),'minimum_actual_cash':float(buffer_min_actual_cash),'fractional_share_buys':bool(any(abs(q-round(q))>1e-9 for q in _buy_q)),'all_buy_quantities_integer':bool(all(abs(q-round(q))<=1e-9 for q in _buy_q)),'close_q0_candidate_skips':int(sum(1 for r in close_decision_rows if r['outcome']=='Q0_SKIP')),'close_cash_scarcity_q0':int(sum(1 for r in close_decision_rows if r['q0_reason']=='CASH_SCARCITY')),'close_target_granularity_q0':int(sum(1 for r in close_decision_rows if r['q0_reason']=='TARGET_GRANULARITY')),'gap_alone_would_clip_events':int(sum(1 for r in gap_event_rows if bool(r['gap_alone_would_clip']))),'positive_gap_shortfall_events':int(sum(1 for r in gap_event_rows if finite(r['close_to_open_percentage_gap']) and float(r['close_to_open_percentage_gap'])>0)),'gap_gt_2_5pct_shortfall_events':int(sum(1 for r in gap_event_rows if finite(r['close_to_open_percentage_gap']) and float(r['close_to_open_percentage_gap'])>2.5)),'transaction_rows':int(len(trade_rows)),'close_decision_rows':int(len(close_decision_rows))}
    (OUT/'buffer-telemetry.json').write_text(json.dumps(_telemetry,indent=2,sort_keys=True))
    _open_telemetry={'schema':'research.wealth-core-v5-open-time-whole-shares-10bp/1','mode':'whole','buffer_basis_points':10,'buffer_fraction':0.001,'buffer_role':'CLOSE_TIME_ADMISSION_CUSHION_RELEASED_AT_OPEN','close_admission_rule':'REQUIRE_POSITIVE_CASH_ABOVE_10BP_RESERVE_AND_ONE_WHOLE_SHARE_AFFORDABLE_FROM_TOTAL_CASH','close_admission_rule_cash_basis':'TOTAL_CASH','close_admission_rule_is_quantity_binding':False,'close_admissions':int(open_close_admissions),'completed_entries':int(scale_entries),'close_q0_total':int(scale_q0_candidate_skips),'close_q0_cash_scarcity':int(open_close_cash_scarcity_skips),'close_q0_total_cash_one_share_unaffordable':int(open_close_whole_share_unaffordable_skips),'next_open_blocks':int(open_invalid_market_blocks+open_zero_quantity_blocks),'invalid_open_market_blocks':int(open_invalid_market_blocks),'zero_quantity_blocks':int(open_zero_quantity_blocks),'cash_limited_open_executions':int(open_cash_limited_execs),'rounding_underfill_dollars_total':float(open_rounding_underfill_dollars),'average_rounding_underfill_fraction':float(open_rounding_underfill_fraction_sum/scale_entries) if scale_entries else None,'full_target_executions':int(open_full_target_execs),'partial_target_executions':int(open_partial_target_execs),'minimum_actual_cash':float(buffer_min_actual_cash),'fractional_shares_allowed':False,'all_admitted_trades_executed':bool(open_invalid_market_blocks+open_zero_quantity_blocks==0)}
    (OUT/'open-sizing-telemetry.json').write_text(json.dumps(_open_telemetry,indent=2,sort_keys=True))
    print(json.dumps(summary,indent=2),flush=True)

if __name__=='__main__': run()
