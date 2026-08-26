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
import pandas as pd
import numpy as np
import zipfile, glob, math, json, hashlib, time, gc

gc.disable()
ROOT = Path('/mnt/data')
OUT = ROOT / 'ldrc_ab_replay_20260825'
OUT.mkdir(exist_ok=True)
COMMIT = 'c14f77b3c6c6fcc14cf00e8916d7968c853a5d6c'
START = pd.Timestamp('2006-07-31')
END = pd.Timestamp('2026-07-31')
N_SLOTS = 25
ENTRY_W = 0.04
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
FAST = {'dd':-.10,'dam':.85,'green':.20,'r5':-.05,'r10':-.08,'ddam5':.30,'volacc':.04,'spy20':-.01,'r10confirm':-.10}
SLOW = {'dur':30,'ret':-.02,'r40':-.03,'dam':.75,'green':.25}

# Current Simplified LD-RC v3 constants.
LDRC_DD=-.10; LDRC_R20=-.08; LDRC_CEIL=.55; LDRC_REC=7; LDRC_V=.11


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
    cols=['table','permaticker','ticker','category','sector','relatedtickers','firstpricedate','lastpricedate','exchange']
    d=zcsv(ROOT/'SHARADAR_TICKERS.zip',cols)
    d=d[d.table.eq('SEP')].dropna(subset=['ticker']).copy()
    if d.ticker.duplicated().any():
        dup=d[d.ticker.duplicated(False)].ticker.astype(str).tolist()
        raise RuntimeError(f'duplicate SEP ticker identity: {dup[:10]}')
    d=d.sort_values('ticker').reset_index(drop=True)
    tick=d.ticker.astype(str).to_numpy()
    tmap={t:i for i,t in enumerate(tick)}
    sid=d.permaticker.astype('Int64').astype(str).to_numpy()
    common=d.category.fillna('').astype(str).map(lambda c:'Common Stock' in c and 'Warrant' not in c and 'Preferred' not in c).to_numpy(bool)
    sector=d.sector.where(d.sector.notna(),None).to_numpy(object)
    exchange=d.exchange.fillna('').astype(str).str.upper().to_numpy(object)
    fp=pd.to_datetime(d.firstpricedate,errors='coerce').to_numpy('datetime64[D]')
    lp=pd.to_datetime(d.lastpricedate,errors='coerce').to_numpy('datetime64[D]')
    issuer=[]
    for t,p,r in zip(tick,d.permaticker,d.relatedtickers):
        rel=[] if pd.isna(r) else [x.strip().upper() for x in str(r).replace(',',' ').split() if x.strip()]
        names=sorted(set([str(t).upper()]+rel))
        issuer.append('|'.join(names) if len(names)>1 else ('P:'+str(int(p)) if pd.notna(p) else None))
    return tick,tmap,sid,common,sector,exchange,fp,lp,np.array(issuer,object)


def load_actions():
    d=zcsv(ROOT/'SHARADAR_ACTIONS.zip',['date','action','ticker','value','contraticker'])
    d['date']=pd.to_datetime(d.date)
    d['action']=d.action.astype(str).str.lower()
    d['ticker']=d.ticker.astype(str)
    bydate=defaultdict(lambda:defaultdict(list)); split_dates=defaultdict(list)
    for r in d.itertuples(index=False):
        val=float(r.value) if pd.notna(r.value) else None
        ds=pd.Timestamp(r.date).normalize()
        contra=None if pd.isna(r.contraticker) else str(r.contraticker)
        bydate[ds][r.ticker].append((r.action,val,contra))
        if r.action=='split' and val is not None and math.isfinite(val) and val>0:
            split_dates[r.ticker].append((ds,val))
    for k in split_dates: split_dates[k].sort()
    return bydate,split_dates


def load_funds():
    parts=[]
    with zipfile.ZipFile(ROOT/'SHARADAR_SFP.zip') as z:
        names=[x for x in z.namelist() if x.lower().endswith('.csv')]
        if len(names)!=1: raise RuntimeError('SFP zip member count')
        with z.open(names[0]) as f:
            for ch in pd.read_csv(f,usecols=['ticker','date','open','close','closeadj'],chunksize=450_000,low_memory=False):
                q=ch[ch.ticker.astype(str).isin(['SPY','BIL'])]
                if len(q): parts.append(q)
    x=pd.concat(parts,ignore_index=True)
    x.date=pd.to_datetime(x.date)
    x=x.sort_values(['ticker','date']).drop_duplicates(['ticker','date'],keep='last')
    spy=x[x.ticker.eq('SPY')].set_index('date').copy()
    spy['ret']=spy.closeadj.astype(float).pct_change()
    spy['r20']=spy.closeadj.astype(float).pct_change(20)
    spy['volacc']=spy.ret.rolling(5).std(ddof=1)/spy.ret.rolling(20).std(ddof=1)-1
    bil=x[x.ticker.eq('BIL')].set_index('date').copy()
    bil['adjopen']=bil.open.astype(float)*bil.closeadj.astype(float)/bil.close.astype(float)
    return spy,bil


def finite(x): return x is not None and np.isfinite(x)

@dataclass
class Slot:
    tid:int=-1; qty:float=0.; entry_sig:float=np.nan; peak:float=np.nan; entry_day:int=-1; reviewed:bool=False
    pending_sell:bool=False; sell_reason:str=''; pending_tid:int=-1; pending_shares:float=0.; pending_signal_day:int=-1; ready_day:int=0
    def held(self): return self.tid>=0 and self.qty>1e-12
    def reserved(self): return self.pending_tid>=0

@dataclass
class Book:
    cash:float=100_000_000.; receivables:list=field(default_factory=list)
    slots:list=field(default_factory=lambda:[Slot() for _ in range(N_SLOTS)])
    sec_ready:dict=field(default_factory=dict); initialized:bool=False; last_raw:dict=field(default_factory=dict)
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
        healthy=finite(r20) and finite(dam) and finite(green) and r20>0 and dam<=.60 and green>=.20
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
    def __init__(self): self.episode=False; self.prev_native=1.; self.prev_desired=1.; self.episodes=0
    def step(self,native,r20,spy20):
        reasons=[]
        if self.prev_native>=1-1e-12 and native<1-1e-12:
            if not self.episode: self.episodes+=1
            self.episode=True; reasons.append('EPISODE_START')
        desired=native
        if self.episode and native>=1-1e-12:
            release=(finite(r20) and r20>0) or (finite(spy20) and spy20>LDRC_V)
            if release:
                self.episode=False; desired=1.; reasons.append('RELEASE_R20' if finite(r20) and r20>0 else 'RELEASE_SPY')
            else:
                desired=self.prev_desired; reasons.append('HOLD')
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return float(desired),'|'.join(reasons) if reasons else 'NORMAL'

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


def bil_factors(bil,date,prevdate):
    if prevdate is None or date not in bil.index or prevdate not in bil.index: return 0.,0.,1.
    prev=float(bil.loc[prevdate,'closeadj']); op=float(bil.loc[date,'adjopen']); cl=float(bil.loc[date,'closeadj'])
    if not all(np.isfinite([prev,op,cl])) or min(prev,op,cl)<=0: return 0.,0.,1.
    return op/prev-1,cl/op-1,cl/prev


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
    actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()
    ctl=ControlLDRC(); ca=CandidateA(); cb=CandidateB()
    L=130
    close_ring=np.full((L,n),np.nan,np.float32)
    r126=np.zeros((126,n),np.float32); rv126=np.zeros((126,n),bool); s126=np.zeros(n);q126=np.zeros(n);c126=np.zeros(n,np.int16)
    r21=np.zeros((21,n),np.float32); rv21=np.zeros((21,n),bool); s21=np.zeros(n);q21=np.zeros(n);c21=np.zeros(n,np.int16)
    dvbuf=np.zeros((20,n),np.float32); dvsum=np.zeros(n)
    opraw=np.full(n,np.nan); clsig=np.full(n,np.nan); clraw=np.full(n,np.nan); volume=np.full(n,np.nan)
    mom=np.full(n,np.nan); recent=np.full(n,np.nan); score=np.full(n,np.nan); adv=np.full(n,np.nan)
    last_factor=np.full(n,np.nan); touched=np.empty(0,np.int32); gday=-1; first_eligible=None
    shadow_dates=[]; shadow_eq=[]; damaged_hist=[]; stop_days=[]
    recent_nav=1.; recent_nav_hist=[1.]; prior_recent_sel=tuple(); prior_close_map={}
    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0
    pending_native=1.; effective_native=1.
    pend={'control':1.,'A':1.,'B':1.}; eff={'control':1.,'A':1.,'B':1.}
    navs={'control':1.,'A':1.,'B':1.}; transition_cost={'control':0.,'A':0.,'B':0.}; transitions={'control':0,'A':0,'B':0}
    prev_close_eq=None; prev_perf_date=None
    # SPY normalized benchmark on closeadj, first measurement session rebased later.

    for y in range(1998,END.year+1):
        p=year_file(y); t0=time.time(); cols=['ticker','date','open','close','volume','closeunadj']
        d=pd.read_csv(p,usecols=cols,low_memory=False)
        d.date=pd.to_datetime(d.date); d=d[d.date<=END]
        d=d.dropna(subset=['ticker','date','close','closeunadj']).drop_duplicates(['ticker','date'],keep='last')
        ids=d.ticker.astype(str).map(tmap); d=d[ids.notna()].copy(); d['tid']=ids[ids.notna()].astype(np.int32).to_numpy()
        d.sort_values(['date','tid'],inplace=True,kind='mergesort')
        for date,g in d.groupby('date',sort=True):
            gday+=1; date=pd.Timestamp(date); ds=date.strftime('%Y-%m-%d')
            if touched.size:
                for a in (opraw,clsig,clraw,volume,mom,recent,score,adv): a[touched]=np.nan
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
            opraw[tids]=rawop; clsig[tids]=c; clraw[tids]=cu; volume[tids]=vol; mom[tids]=mm; recent[tids]=rr; score[tids]=sc; adv[tids]=av
            dt64=np.datetime64(date.date()); listed=(firstdate[tids]<=dt64)&(lastdate[tids]>=dt64); continuous=c126[tids]>=126
            # Exchange is intentionally NOT used here because a single current TICKERS snapshot cannot establish historical exchange authority.
            elig=common[tids]&listed&continuous&np.isfinite(mm)&np.isfinite(rr)&np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&np.isfinite(dv)&(dv>=MIN_DAY_DV)&np.isfinite(sc)&(fvol>0)
            et=tids[elig]
            if len(et):
                sid_et=sid[et]; ordm=np.lexsort((sid_et,-mom[et])); rawall=et[ordm]
                nk=min(len(et),max(25,int(math.ceil(len(et)*TOP)))); pool=rawall[:nk]
                ordscore=np.lexsort((tick[pool],sid[pool],-score[pool])); durable=pool[ordscore]
                ordrec=np.lexsort((sid_et,-recent[et])); recsel=et[ordrec[:nk]]
            else:
                rawall=pool=durable=recsel=np.empty(0,np.int32); nk=0
            inpool=np.zeros(n,bool); inpool[pool]=True
            if first_eligible is None and len(et)>=25: first_eligible=gday
            # Causal recent-leadership witness: prior close selection earns current close-to-close return.
            if prior_recent_sel:
                vals=[]
                for tid0 in prior_recent_sel:
                    p0=prior_close_map.get(int(tid0)); p1=clsig[int(tid0)]
                    vals.append(float(p1)/float(p0)-1 if finite(p0) and p0>0 and finite(p1) and p1>0 else 0.0)
                recent_nav*=1+sum(vals)/len(prior_recent_sel)
            recent_nav_hist.append(recent_nav)
            recent_r20=recent_nav_hist[-1]/recent_nav_hist[-21]-1 if len(recent_nav_hist)>20 else None
            recent_r40=recent_nav_hist[-1]/recent_nav_hist[-41]-1 if len(recent_nav_hist)>40 else None
            prior_recent_sel=tuple(map(int,recsel)); prior_close_map={int(t):float(clsig[int(t)]) for t in recsel if finite(clsig[int(t)])}
            if ds in ('2008-12-23','2022-01-03'):
                overlap_checks[ds]={'eligible':int(len(et)),'population':int(nk),'overlap':int(len(set(map(int,pool))&set(map(int,recsel))))}

            # Open: settle prior receivables, transform splits, then execute pending exits/buys.
            due=sum(a for dd,a in book.receivables if dd<=gday); book.cash+=due; book.receivables=[x for x in book.receivables if x[0]>gday]
            prior_qty={s.tid:s.qty for s in book.slots if s.held()}
            for tid0,cs,cr in zip(tids,c,cu):
                tid=int(tid0); factor=float(cr/cs) if finite(cr) and finite(cs) and cs>0 else np.nan; pf=last_factor[tid]
                if finite(pf) and finite(factor) and pf>0 and factor>0:
                    observed=pf/factor
                    if abs(math.log(observed))>.005:
                        auth=nearest_split_authority(split_dates,tick[tid],date,observed)
                        if auth is not None:
                            ratio=observed; split_events+=1
                            for s in book.slots:
                                if s.held() and s.tid==tid: s.qty*=ratio
                                if s.reserved() and s.pending_tid==tid:
                                    q=s.pending_shares*ratio
                                    if abs(q-round(q))>1e-8: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1
                                    else: s.pending_shares=float(round(q))
                if finite(factor) and factor>0: last_factor[tid]=factor
            dayact=actions.get(date,{})
            term_tids={tmap[tk] for tk,rs in dayact.items() if tk in tmap and any(a in TERMINAL for a,_,_ in rs)}
            for s in book.slots:
                if s.reserved() and s.pending_tid in term_tids: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1
                if s.held() and s.tid in term_tids and not s.pending_sell: s.pending_sell=True; s.sell_reason='terminal'
            open_eq,_=book.equity(opraw)
            for s in book.slots:
                if not(s.held() and s.pending_sell): continue
                px=opraw[s.tid]
                if finite(px) and px>0 and finite(volume[s.tid]) and volume[s.tid]>0:
                    book.cash+=s.qty*float(px)*(1-COST); sells+=1
                    if s.sell_reason=='stop': stop_days.append(gday)
                    book.sec_ready[s.tid]=gday+COOLDOWN
                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN
                elif s.sell_reason=='terminal':
                    px2=book.last_raw.get(s.tid,np.nan)
                    if finite(px2) and px2>0: book.cash+=s.qty*float(px2)*(1-COST)
                    book.sec_ready[s.tid]=gday+COOLDOWN
                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN
            for s in book.slots:
                if not(s.reserved() and not s.held()): continue
                tid=s.pending_tid; px=opraw[tid]
                if finite(px) and px>0 and finite(volume[tid]) and volume[tid]>0:
                    afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford)
                    if q>=1:
                        book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(clsig[tid]) if finite(clsig[tid]) else np.nan; s.peak=np.nan; book.initialized=True; buys+=1
                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1
            # Dividends use prior-close raw share quantity and current raw/signal price factor.
            for tk,rs in dayact.items():
                if tk not in tmap: continue
                tid=tmap[tk]; q=prior_qty.get(tid,0.)
                if q<=0: continue
                vals=[v for a,v,_ in rs if a=='dividend' and v is not None and finite(v) and v>=0]
                if vals and finite(clsig[tid]) and clsig[tid]>0 and finite(clraw[tid]) and clraw[tid]>0:
                    rawdiv=sum(vals)*float(clraw[tid])/float(clsig[tid]); book.receivables.append((gday+1,q*rawdiv)); div_events+=1
            for tid0 in tids:
                if finite(clraw[int(tid0)]) and clraw[int(tid0)]>0: book.last_raw[int(tid0)]=float(clraw[int(tid0)])

            # Close: peaks/exits, mark equity, breadth, then admissions.
            for s in book.slots:
                if not s.held(): continue
                px=clsig[s.tid]
                if s.entry_day==gday:
                    if finite(px) and px>0: s.peak=float(px); s.entry_sig=float(px)
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
                held.append((tid,sector[tid],own,r21v,r63v,age,green,red))
            secct=defaultdict(lambda:[0,0])
            for z in held: secct[z[1]][0]+=int(z[7]); secct[z[1]][1]+=1
            ng=na=0
            for z in held:
                stress=secct[z[1]][0]/secct[z[1]][1] if secct[z[1]][1] else 0.
                amber=(finite(z[2]) and z[2]<=-.10) or (finite(z[3]) and z[3]<=-.03) or (stress>=.50 and not z[6])
                ng+=int(z[6]); na+=int(amber)
            green_b=ng/len(held) if held else 0.; dam_b=na/len(held) if held else 0.
            if first_eligible is not None and gday>=first_eligible:
                ready=[s for s in book.slots if not s.held() and not s.reserved() and gday>=s.ready_day]
                if ready and not unresolved and book.cash>0:
                    budget=len(ready) if not book.initialized else 1
                    heldids=book.held_ids(); resids=book.reserved_ids()
                    heldissuers={issuer[s.tid] for s in book.slots if s.held()}; resissuers={issuer[s.pending_tid] for s in book.slots if s.reserved()}
                    ad=0
                    for tid0 in durable:
                        if ad>=budget or ad>=len(ready): break
                        tid=int(tid0)
                        if not finite(recent[tid]) or recent[tid]<0: continue
                        if tid in heldids or tid in resids or book.sec_ready.get(tid,-1)>gday or tid in term_tids: continue
                        if issuer[tid] in heldissuers or issuer[tid] in resissuers: continue
                        px=clraw[tid]
                        if not(finite(px) and px>0): continue
                        target=min(eq*ENTRY_W,book.cash); q=int(target//(float(px)*(1+COST)))
                        if q<1: continue
                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; resids.add(tid); resissuers.add(issuer[tid]); ad+=1
            shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)
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
            a_d,a_reason=ca.step(native_target,recent_r20,spy20)
            b_d,b_reason=cb.step(native_target,recent_r20,spy20)

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
                rows.append({'date':date,'shadow_equity':eq,'open_equity':open_eq,'wc_dd':dd,'damaged':dam_b,'green':green_b,
                             'recent_r20':recent_r20,'recent_r40':recent_r40,'spy_r20':spy20,'native_close_target':native_target,
                             'effective_native':effective_native,'control_allocation':eff['control'],'A_allocation':eff['A'],'B_allocation':eff['B'],
                             'control_nav':navs['control'],'A_nav':navs['A'],'B_nav':navs['B'],'spy_nav':spy_nav,
                             'control_reason':ctl_reason,'A_reason':a_reason,'B_reason':b_reason,'fast_signal':fastsig,'slow_signal':slowsig})
                prev_perf_date=date; prev_close_eq=eq
            pending_native=native_target; pend['control']=ctl_d; pend['A']=a_d; pend['B']=b_d
        print(f'YEAR {y} rows={len(d):,} seconds={time.time()-t0:.1f}',flush=True)

    out=pd.DataFrame(rows)
    out.to_csv(OUT/'daily.csv',index=False)
    idx=out.set_index('date')
    summary={
        'code_commit':COMMIT,
        'window':[str(START.date()),str(END.date())],
        'evidence_level':'exploratory_only_non_PIT_TICKERS_metadata',
        'liquidity_domain':'current_main_equivalent: SEP.close * reported SEP.volume; algebraically raw close * raw-compatible volume per sharadar_domains.py',
        'exchange_gate':'not applied because supplied current TICKERS snapshot cannot establish historical exchange authority',
        'metrics':{k:metrics(idx[f'{k}_nav']) for k in ('control','A','B')},
        'spy':metrics(idx['spy_nav'].dropna()),
        'transition_counts':transitions,
        'modeled_allocation_transition_cost_sum':transition_cost,
        'buys':buys,'sells':sells,'split_events_applied':split_events,'dividend_events_held':div_events,
        'leadership_overlap_checks':overlap_checks,
        'candidate_A_episodes':ca.episodes,'candidate_B_episodes':cb.episodes,
    }
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2),flush=True)

if __name__=='__main__': run()
