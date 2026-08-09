#!/usr/bin/env python3
"""Sentinel 1.1-RC standalone historical implementation.

Runtime inputs: Sharadar SEP yearly .csv.gz files, SHARADAR_TICKERS.zip,
SHARADAR_ACTIONS.zip, and SHARADAR_SFP.zip.  No frozen path, allocation,
breadth, transition, CSV/JSON oracle, or precomputed strategy output is read.

The program independently builds the immutable Wealth Core shadow from raw
Sharadar data, computes holding-level GREEN/RED/AMBER breadth, runs the
Sentinel 1.0x fast/slow controller and Sentinel 1.1 recovery ramp, and applies
next-open scalar allocation accounting with BIL as the defensive sleeve.

This source is the raw-Sharadar restatement.  It intentionally does not ingest
the frozen Sentinel 1.0x parent NAV tape.  Consequently its allocation path is
expected to be certification-identical to frozen Sentinel 1.1, while historical
NAV can differ by tiny amounts at old parent transition opens because the
retained frozen 1.1 NAV inherited an earlier parent open-reconstruction lineage.
See PARITY_REPORT.json in the distribution.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import time
import zipfile
import gc
gc.disable()  # pandas/numpy replay is refcount-clean; cyclic scans are prohibitively expensive

import numpy as np
import pandas as pd

# ---------------------------- Frozen strategy ----------------------------
WC_START_CAPITAL = 100_000_000.0
NPOS = 25
ENTRY_W = 0.04
STOP_PCT = 0.30
REVIEW_AGE = 119
COOLDOWN = 21
COST = 0.001                         # 10 bp each executed stock side / overlay change
MIN_PRICE = 1.0
MIN_ADV20 = 20_000_000.0
MIN_DAILY_DOLLAR = 5_000_000.0
TOP_FRAC = 0.10
MOM_LOOKBACK = 126
SKIP_RECENT = 21

TERMINAL = {
    'acquisitionby', 'mergerto', 'voluntarydelisting',
    'regulatorydelisting', 'bankruptcyliquidation', 'delisted'
}
SPLIT_KINDS = {'split', 'adrratiosplit'}
# Audited terminal cash terms absent from the raw terminal row itself.
VERIFIED_CASH_SETTLEMENTS = {'VRNA': 107.0, 'DAWN': 21.50}

# Optional exact-corpus verification.  These are hashes, not strategy oracles.
EXPECTED_HASHES = {
'SHARADAR_SEP_1998.csv.gz':'cb0549b4e80ab55a11adec465ac5caa6f45159e465e593b7e541f222988119f8',
'SHARADAR_SEP_1999.csv.gz':'86d2efc937b792353b4ea5b44035d698f62348435b4a02b99f3fb72aa283c6da',
'SHARADAR_SEP_2000.csv.gz':'431fc93957070750b1beae3ebffe2a27c9792ce6829f3c1b7bba5b4b242ab9c0',
'SHARADAR_SEP_2001.csv.gz':'23f8a84400e69077ad251563c25ece80632d00fe9cce317ac421b0525a0da140',
'SHARADAR_SEP_2002.csv.gz':'21cd434da89cee2b71914e34143ef6480eb47608fe8c5d5fceb8a61482df3071',
'SHARADAR_SEP_2003.csv.gz':'5fbbd7fe8418c37d42ff1008fab59b9eb0e83e3e5897d662fb2a88fd89df265c',
'SHARADAR_SEP_2004.csv.gz':'377f5e4d531d96a96fa42000edb67c45624fd7ce969b6f7355a13add1590de70',
'SHARADAR_SEP_2005.csv.gz':'78b939b9ce75a2da0e31c1f1b3970a59f77f80ea40329090dd6a965d664eb13f',
'SHARADAR_SEP_2006.csv.gz':'fe79c1d3d77c39c5cac0ed622b8a0d79f76f2dd691b94953acc8392eaa78135c',
'SHARADAR_SEP_2007.csv.gz':'0a69d838ffa7f4759f58a59fdb920058ca2528ffa03cb409feb4cae3c9085cf8',
'SHARADAR_SEP_2008.csv.gz':'50c672ec263fd570e21033e66eb31bb29a3bfa93456bc96f7f09e5dbde4a2d3e',
'SHARADAR_SEP_2009.csv.gz':'9682265dcd00dfd248fc697ad40ce0a24e46474980855eb783e01537ff4d0a55',
'SHARADAR_SEP_2010.csv.gz':'5b89e806e0dc358518d69c8287daa3f5134d0e52dca3f989d9fd7d06f1797a16',
'SHARADAR_SEP_2011.csv.gz':'6df33ef5f704c339093224d9ea6727e8d94171f47bcef4821c452d830bc04c9c',
'SHARADAR_SEP_2012.csv.gz':'7f88cbc4430f114a3a42370c250bca71a309602171d81a4b31177f5756436710',
'SHARADAR_SEP_2013.csv.gz':'8525ced4b73cb2b68ed6de6770ea0201244739722de3bc01f22465c784556451',
'SHARADAR_SEP_2014.csv.gz':'eb5c92f3b9b22377caa929fcbf1d3b21d815de4b808f5dbfae0d120e0f2b2b9e',
'SHARADAR_SEP_2015.csv.gz':'cc57d31d38a7637febd8df6d6a468d098bd6d50742d565abec51ddd767332856',
'SHARADAR_SEP_2016.csv.gz':'85ddbed15f017a9f9265a90460199acf7af2862dd0c622595c2abb0a2b159bdf',
'SHARADAR_SEP_2017.csv.gz':'cc507819b6e5b6aac8fc15bc99a7cfed78a5babb74ab88ad87ee971b8241a43f',
'SHARADAR_SEP_2018.csv.gz':'6a36f002bb6ae3d6a939046859e6624aff78e49a0146a21bb8b4e3151b496273',
'SHARADAR_SEP_2019.csv.gz':'e4612a33a70c8259663e31110d11b0e9a59f23180ed3a68a01bb7b4edcdcf17a',
'SHARADAR_SEP_2020.csv.gz':'1f9558ce26cf8f1d2c1551add9c2f60a41b080ab8d8c3c7a54c2a262566f2e02',
'SHARADAR_SEP_2021.csv.gz':'db0936c44d597d508c17bb962e105eee0be9928500389fcf382a0f379bf2a987',
'SHARADAR_SEP_2022.csv.gz':'c4e19b7e193dadfb014ce14fa276e2237f741b2e0ff586973b75222504a13a55',
'SHARADAR_SEP_2023.csv.gz':'ff6e732f33c948e535a9c2d836339fad6aec6a2f3867cfc51abbe94ee24480d5',
'SHARADAR_SEP_2024.csv.gz':'235891b9afa87ea4fd04e9a61e6a9d0b324ee7daf0a60da4381e413c8efcb2ae',
'SHARADAR_SEP_2025.csv.gz':'a467e89458a2287398af4de13150cb57b07cb5300e56b2dc9280197102fc05c4',
'SHARADAR_SEP_2026.csv.gz':'a3870f8d5d92762eb4a6d9b875a712d47af6f7beb2cb5ede69caeba082bf0001',
'SHARADAR_ACTIONS.zip':'db67132dca8cf38107ca4bcaea7276ea5d0e8f77254f6556802caad6efa91b02',
'SHARADAR_TICKERS.zip':'308bcc46f4efaffe6f6fc4f7236af82df5c57a9f2be07c677089f0e6fba2eebf',
'SHARADAR_SFP.zip':'8d2ebf7485977d9c40ec379eb33bd9d36d39d69db13602e5c51862d03172400c',
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def verify_corpus(data: Path) -> None:
    bad = []
    for name, expected in EXPECTED_HASHES.items():
        p = data / name
        if not p.exists():
            bad.append((name, 'missing'))
        else:
            actual = sha256(p)
            if actual != expected:
                bad.append((name, actual))
    if bad:
        raise RuntimeError(f'Sharadar corpus mismatch: {bad[:5]}')


def read_zip_csv(path: Path, usecols=None) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith('.csv')]
        if len(names) != 1:
            raise RuntimeError(f'Expected one CSV in {path}, found {names}')
        with z.open(names[0]) as f:
            return pd.read_csv(f, usecols=usecols, low_memory=False)


def load_meta(data: Path):
    use = ['table','permaticker','ticker','category','sector','exchange','relatedtickers','lastpricedate']
    d = read_zip_csv(data/'SHARADAR_TICKERS.zip', use)
    d = d[d.table.eq('SEP')].dropna(subset=['ticker']).copy()
    if d.ticker.duplicated().any():
        raise RuntimeError('duplicate SEP ticker metadata')
    tick = d.ticker.astype(str).tolist()
    tmap = {t:i for i,t in enumerate(tick)}
    cat = d.category.fillna('').astype(str).to_numpy()
    common = np.array([('Common Stock' in c) and ('Warrant' not in c) and ('Preferred' not in c) for c in cat], bool)
    sector = d.sector.fillna('Unknown').astype(str).to_numpy()
    perm = d.permaticker.fillna(-1).astype(str).to_numpy()
    rel = d.relatedtickers.fillna('').astype(str).to_numpy()
    issuer=[]
    for t,p,r in zip(tick,perm,rel):
        # Certified issuer identity. Sharadar RELATEDTICKERS is space- or
        # comma-separated; sort and de-duplicate {ticker} U relatedtickers.
        # If no related security exists, use the permanent ticker identity.
        related=[x.strip().upper() for x in str(r).replace(',', ' ').split() if x.strip()]
        names=sorted(set([str(t).upper()]+related))
        issuer.append('|'.join(names) if len(names)>1 else ('P:'+p))
    return tick,tmap,common,sector,np.array(issuer,dtype=object)


def load_actions(data: Path):
    use=['date','action','ticker','value','contraticker']
    d=read_zip_csv(data/'SHARADAR_ACTIONS.zip', use)
    d['date']=d.date.astype(str);d['action']=d.action.astype(str).str.lower();d['ticker']=d.ticker.astype(str)
    out=defaultdict(lambda:defaultdict(list))
    for r in d.itertuples(index=False):
        val=float(r.value) if pd.notna(r.value) else None
        out[r.date][r.ticker].append((r.action,val,None if pd.isna(r.contraticker) else str(r.contraticker)))
    return out


def load_spy_bil(data: Path):
    parts=[]
    with zipfile.ZipFile(data/'SHARADAR_SFP.zip') as z:
        names=[n for n in z.namelist() if n.lower().endswith('.csv')]
        if len(names)!=1: raise RuntimeError('SFP ZIP must contain one CSV')
        with z.open(names[0]) as f:
            for ch in pd.read_csv(f,chunksize=500_000,low_memory=False):
                q=ch[ch.ticker.astype(str).isin(['SPY','BIL'])]
                if len(q): parts.append(q[['ticker','date','open','close','closeadj']])
    x=pd.concat(parts,ignore_index=True)
    x['date']=pd.to_datetime(x.date)
    x=x.sort_values(['ticker','date'])
    spy=x[x.ticker.eq('SPY')].copy().set_index('date')
    spy['ret']=spy.closeadj.astype(float).pct_change()
    spy['r20']=spy.closeadj.astype(float).pct_change(20)
    spy['volacc']=spy['ret'].rolling(5).std(ddof=1)/spy['ret'].rolling(20).std(ddof=1)-1
    bil=x[x.ticker.eq('BIL')].copy().set_index('date')
    bil['adj_open']=bil.open.astype(float)*bil.closeadj.astype(float)/bil.close.astype(float)
    return spy, bil


@dataclass
class Slot:
    ticker:int=-1;qty:float=0.;peak_signal:float=np.nan;entry_signal:float=np.nan;entry_raw:float=np.nan
    entry_day:int=-1;ready:int=0;pending_buy:int=-1;pending_notional:float=0.;pending_sell:bool=False
    pending_reason:str='';reviewed:bool=False;cost_basis:float=0.;dividends:float=0.;episode:int=-1
    @property
    def held(self): return self.ticker>=0 and self.qty>1e-12


@dataclass
class WealthCore:
    cash:float=WC_START_CAPITAL;receivable:float=0.;slots:list[Slot]=field(default_factory=lambda:[Slot() for _ in range(NPOS)])
    cooldown:dict=field(default_factory=dict);bootstrap:bool=False;exit_days:list=field(default_factory=list)
    last_raw:dict=field(default_factory=dict);episode_seq:int=0
    def held_ids(self): return {s.ticker for s in self.slots if s.held}
    def pending_ids(self): return {s.pending_buy for s in self.slots if s.pending_buy>=0}
    def held_issuers(self, issuer): return {issuer[s.ticker] for s in self.slots if s.held}
    def equity(self, raw_close):
        x=self.cash+self.receivable
        for s in self.slots:
            if s.held:
                p=raw_close[s.ticker]
                if not np.isfinite(p):p=self.last_raw.get(s.ticker,np.nan)
                if np.isfinite(p):x+=s.qty*float(p)
        return float(x)
    def open_equity(self, raw_open):
        x=self.cash+self.receivable
        for s in self.slots:
            if s.held:
                p=raw_open[s.ticker]
                if not np.isfinite(p):p=self.last_raw.get(s.ticker,np.nan)
                if np.isfinite(p):x+=s.qty*float(p)
        return float(x)


def reset_slot(s: Slot, ready: int):
    s.ticker=-1;s.qty=0.;s.peak_signal=np.nan;s.entry_signal=np.nan;s.entry_raw=np.nan
    s.entry_day=-1;s.ready=ready;s.pending_sell=False;s.pending_reason='';s.pending_buy=-1
    s.pending_notional=0.;s.reviewed=False;s.cost_basis=0.;s.dividends=0.;s.episode=-1


def infer_dividend_basis(prev_raw,cur_raw,prev_adj,cur_adj,split_ratio,dividend):
    if not all(np.isfinite(x) and x>0 for x in [prev_raw,cur_raw,prev_adj,cur_adj,split_ratio]):
        raise RuntimeError('cannot infer same-day split/dividend basis')
    obs=cur_adj/prev_adj
    pre=(split_ratio*cur_raw+dividend)/prev_raw
    post=(split_ratio*cur_raw+split_ratio*dividend)/prev_raw
    epre=abs(math.log(max(pre,1e-300)/max(obs,1e-300)))
    epost=abs(math.log(max(post,1e-300)/max(obs,1e-300)))
    return 'pre_split' if epre<=epost else 'post_split'


@dataclass
class BinaryStress:
    active:bool=False;armed:bool=True;entry_i:int=-10**9;healthy_streak:int=0
    def step(self,i,dd,r20,stops20):
        if dd>-0.155:self.armed=True
        if dd<=-0.155 and self.armed and not self.active:
            self.active=True;self.armed=False;self.entry_i=i;self.healthy_streak=0
        elif self.active:
            healthy=np.isfinite(r20) and r20>0 and stops20<=2
            self.healthy_streak=self.healthy_streak+1 if healthy else 0
            if (i-self.entry_i)>=20 and self.healthy_streak>=3:
                self.active=False;self.healthy_streak=0
        return self.active


@dataclass
class FastState:
    # base_mode reproduces the earlier 40% shock-overlay clock; parent mode is Sentinel 1.0x.
    base_mode:bool=False;active:bool=False;armed:bool=True;entry_i:int=-10**9;healthy_streak:int=0
    def step(self,i,signal,dd,healthy,entry_allowed=True):
        if dd>-0.06 and not signal:self.armed=True
        if signal and self.armed and not self.active and entry_allowed:
            self.active=True;self.armed=False;self.entry_i=i;self.healthy_streak=0
        elif self.active:
            self.healthy_streak=self.healthy_streak+1 if healthy else 0
            held_ok=(i-self.entry_i)>=10 if self.base_mode else (i-self.entry_i+1)>=10
            if held_ok and self.healthy_streak>=3:
                self.active=False;self.healthy_streak=0
        return self.active


@dataclass
class SlowState:
    active:bool=False;entry_i:int=-10**9;healthy_streak:int=0
    def step(self,i,entry_signal,healthy):
        if self.active:
            self.healthy_streak=self.healthy_streak+1 if healthy else 0
            # The retained research transition ordering emits on the close after
            # five already-established healthy confirmations; this is the exact
            # historical state-machine semantics (sixth healthy observation here).
            if (i-self.entry_i+1)>=20 and self.healthy_streak>=6:
                self.active=False;self.healthy_streak=0
        elif entry_signal:
            self.active=True;self.entry_i=i;self.healthy_streak=0
        return self.active


@dataclass
class SentinelRamp:
    phase:str|None=None;healthy_streak:int=0
    def next_target(self, i, parent_now, parent_next, r40_hist, healthy):
        if parent_next==0.0:
            self.phase=None;self.healthy_streak=0;return 0.0
        if parent_now==0.0 and parent_next==1.0:
            prior5=r40_hist[-6] if len(r40_hist)>=6 else np.nan
            cur=r40_hist[-1] if r40_hist else np.nan
            delta=cur-prior5 if np.isfinite(cur) and np.isfinite(prior5) else np.nan
            if np.isfinite(delta) and delta<=0:
                self.phase='55';self.healthy_streak=0;return 0.55
            self.phase=None;self.healthy_streak=0;return 1.0
        if parent_next==1.0 and self.phase is not None:
            self.healthy_streak=self.healthy_streak+1 if healthy else 0
            if self.phase=='55' and self.healthy_streak>=10:
                self.phase='65';self.healthy_streak=0;return 0.65
            if self.phase=='65' and self.healthy_streak>=10:
                self.phase=None;self.healthy_streak=0;return 1.0
            return 0.55 if self.phase=='55' else 0.65
        self.phase=None;self.healthy_streak=0;return 1.0


def max_drawdown(curve: pd.Series):
    dd=curve/curve.cummax()-1
    trough=dd.idxmin();peak=curve.loc[:trough].idxmax()
    return float(dd.min()),peak,trough


def run(data:Path,start:pd.Timestamp,end:pd.Timestamp,outdir:Path|None,verify_hashes:bool,progress:bool):
    if verify_hashes: verify_corpus(data)
    tick,tmap,common,sector,issuer=load_meta(data);actions=load_actions(data);spy,bil=load_spy_bil(data);n=len(tick)
    wc=WealthCore();binary=BinaryStress();base_fast=FastState(base_mode=True);parent_fast=FastState(base_mode=False);slow=SlowState();ramp=SentinelRamp()
    # Terminal corporate-action state is part of the causal session state.
    # Corporate actions are processed before pending fills and before close-time
    # admissions, so a terminal security can neither fill nor be re-admitted.
    terminal_seen=set()
    terminal_pending_entry_blocks=[]
    terminal_close_admission_blocks=[]
    executed_buys=[]
    issuer_conflict_invariant_checks=0

    L=201
    close_ring=np.full((L,n),np.nan,np.float32);adj_ring=np.full((L,n),np.nan,np.float32);raw_ring=np.full((L,n),np.nan,np.float32)
    dv_ring=np.zeros((20,n),np.float32);dvsum=np.zeros(n,np.float64)
    r126=np.zeros((126,n),np.float32);r126v=np.zeros((126,n),np.bool_);s126=np.zeros(n,np.float64);q126=np.zeros(n,np.float64);c126=np.zeros(n,np.int16)
    r21buf=np.zeros((21,n),np.float32);r21v=np.zeros((21,n),np.bool_);s21=np.zeros(n,np.float64);q21=np.zeros(n,np.float64);c21=np.zeros(n,np.int16)
    op_raw=np.full(n,np.nan,np.float64);cl_sig=np.full(n,np.nan,np.float64);cl_raw=np.full(n,np.nan,np.float64);cl_adj=np.full(n,np.nan,np.float64)
    volume=np.full(n,np.nan,np.float64);sig=np.full(n,np.nan,np.float64);rec=np.full(n,np.nan,np.float64);risk=np.full(n,np.nan,np.float64);adv=np.full(n,np.nan,np.float64)
    touched=np.empty(0,np.int32);gday=-1;first=None

    # controller histories
    dates=[];shadow_eq=[];open_eq=[];stops_hist=[];damaged_hist=[];green_hist=[];r20hist=[];r40hist=[];r5hist=[];r10hist=[];ddhist=[]
    base_stress_prev=False;stress_start_i=None;stress_duration=0;stress_return=0.0
    parent_current=1.0;sentinel_current=1.0;pending_sentinel=1.0
    live_nav=None;live_rows=[]
    prev_close_eq=None

    for y in range(1998,end.year+1):
        p=data/f'SHARADAR_SEP_{y}.csv.gz'
        if not p.exists():raise FileNotFoundError(p)
        ry=time.time()
        cols=['ticker','date','open','close','volume','closeadj','closeunadj']
        d=pd.read_csv(p,usecols=cols,low_memory=False);d.date=pd.to_datetime(d.date)
        d=d.dropna(subset=['ticker','date','open','close','closeunadj']).drop_duplicates(['ticker','date'],keep='last')
        ids=d.ticker.map(tmap);keep=ids.notna();d=d.loc[keep].copy();d['tid']=ids.loc[keep].astype(np.int32).to_numpy();d.drop(columns=['ticker'],inplace=True);del ids,keep
        d.sort_values(['date','tid'],inplace=True,kind='mergesort')
        for date,g in d.groupby('date',sort=True):
            if date>end:break
            gday+=1;ds=str(date.date())
            if touched.size:
                for a in (op_raw,cl_sig,cl_raw,cl_adj,volume,sig,rec,risk,adv):a[touched]=np.nan
            tids=g.tid.to_numpy(np.int32,copy=False);touched=tids
            c=g.close.to_numpy(float,copy=False);ca=g.closeadj.to_numpy(float,copy=False);cu=g.closeunadj.to_numpy(float,copy=False);oo=g.open.to_numpy(float,copy=False);vol=g.volume.to_numpy(float,copy=False)
            rawop=np.divide(oo*cu,c,out=np.full_like(oo,np.nan),where=np.isfinite(oo)&np.isfinite(cu)&np.isfinite(c)&(c>0))
            dv=np.nan_to_num(cu*vol,nan=0.,posinf=0.,neginf=0.)
            lag21=close_ring[(gday-21)%L,tids] if gday>=21 else np.full(len(tids),np.nan)
            lag126=close_ring[(gday-126)%L,tids] if gday>=126 else np.full(len(tids),np.nan)
            prev=close_ring[(gday-1)%L,tids] if gday>=1 else np.full(len(tids),np.nan)
            rr=np.divide(c,lag21,out=np.full_like(c,np.nan),where=np.isfinite(lag21)&(lag21>0))-1
            ss=np.divide(lag21,lag126,out=np.full_like(c,np.nan),where=np.isfinite(lag21)&np.isfinite(lag126)&(lag126>0))-1
            lr=np.log(np.divide(c,prev,out=np.full_like(c,np.nan),where=np.isfinite(prev)&(prev>0)&np.isfinite(c)&(c>0)))
            k=gday%126;old=r126[k];oldv=r126v[k];s126-=old;q126-=old*old;c126-=oldv.astype(np.int16);old.fill(0);oldv.fill(False)
            m=np.isfinite(lr);old[tids[m]]=lr[m].astype(np.float32);oldv[tids[m]]=True;s126[tids[m]]+=lr[m];q126[tids[m]]+=lr[m]*lr[m];c126[tids[m]]+=1
            k2=gday%21;old2=r21buf[k2];oldv2=r21v[k2];s21-=old2;q21-=old2*old2;c21-=oldv2.astype(np.int16);old2.fill(0);oldv2.fill(False)
            old2[tids[m]]=lr[m].astype(np.float32);oldv2[tids[m]]=True;s21[tids[m]]+=lr[m];q21[tids[m]]+=lr[m]*lr[m];c21[tids[m]]+=1
            fsum=s126[tids]-s21[tids];fsq=q126[tids]-q21[tids];fcnt=c126[tids]-c21[tids]
            var=np.divide(fsq-fsum*fsum/np.maximum(fcnt,1),np.maximum(fcnt-1,1),out=np.full(len(tids),np.nan),where=fcnt>1)
            fvol=np.sqrt(np.maximum(var,0))*np.sqrt(252)
            score=np.divide(np.log1p(ss),fvol,out=np.full(len(tids),np.nan),where=np.isfinite(ss)&(ss>-1)&np.isfinite(fvol)&(fvol>0))
            kd=gday%20;dvsum-=dv_ring[kd];dv_ring[kd].fill(0);dv_ring[kd,tids]=dv.astype(np.float32);dvsum[tids]+=dv;av=dvsum[tids]/20. if gday>=19 else np.full(len(tids),np.nan)
            # write rings only after lag retrieval
            close_ring[gday%L].fill(np.nan);close_ring[gday%L,tids]=c.astype(np.float32)
            adj_ring[gday%L].fill(np.nan);adj_ring[gday%L,tids]=ca.astype(np.float32)
            raw_ring[gday%L].fill(np.nan);raw_ring[gday%L,tids]=cu.astype(np.float32)
            op_raw[tids]=rawop;cl_sig[tids]=c;cl_raw[tids]=cu;cl_adj[tids]=ca;volume[tids]=vol;sig[tids]=ss;rec[tids]=rr;risk[tids]=score;adv[tids]=av
            continuous=c126[tids]>=126
            elig=common[tids]&continuous&np.isfinite(ss)&np.isfinite(rr)&np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&np.isfinite(dv)&(dv>=MIN_DAILY_DOLLAR)&np.isfinite(score)
            vt=tids[elig];vs=ss[elig]
            if len(vt):
                raword=np.argsort(-vs,kind='mergesort');rawall=vt[raword];npool=max(NPOS,int(math.ceil(len(vt)*TOP_FRAC)));pool_raw=rawall[:npool]
                riskord=np.argsort(-risk[pool_raw],kind='mergesort');pool_durable=pool_raw[riskord]
            else:pool_raw=pool_durable=np.empty(0,np.int32)
            in_pool=np.zeros(n,np.bool_);in_pool[pool_raw]=True
            if first is None and len(pool_raw)>=NPOS:first=gday

            day_actions=actions.get(ds,{})
            today_terminal={}
            for tk0,rows0 in day_actions.items():
                kinds0=sorted({a for a,_,_ in rows0} & TERMINAL)
                if kinds0 and tk0 in tmap:
                    today_terminal[tmap[tk0]]=kinds0
            terminal_seen.update(today_terminal)

            # Atomic reconciliation: a pending entry cannot survive a terminal
            # event that is effective at this open.  The prior close did not know
            # tomorrow's event; this open-time check therefore adds no look-ahead.
            for s in wc.slots:
                if s.pending_buy < 0 or s.held:
                    continue
                tid=s.pending_buy
                if tid in terminal_seen:
                    terminal_pending_entry_blocks.append({
                        'date': ds, 'ticker': tick[tid],
                        'terminal_actions': '|'.join(today_terminal.get(tid,['prior_terminal'])),
                        'pending_notional': float(s.pending_notional),
                    })
                    s.pending_buy=-1
                    s.pending_notional=0.0

            split_products={}
            for tk,rows in day_actions.items():
                vals=[v for a,v,_ in rows if a in SPLIT_KINDS and v is not None and np.isfinite(v) and v>0]
                if vals:split_products[tk]=float(np.prod(vals))

            # settle prior ex-date dividends
            if wc.receivable:wc.cash+=wc.receivable;wc.receivable=0.
            prior_qty={s.ticker:s.qty for s in wc.slots if s.held}
            effective_splits={}
            for s in wc.slots:
                if not s.held:continue
                tk=tick[s.ticker];ratio=split_products.get(tk)
                if ratio is None:continue
                prev_sig=float(close_ring[(gday-1)%L,s.ticker]) if gday>=1 else np.nan
                prev_raw=float(raw_ring[(gday-1)%L,s.ticker]) if gday>=1 else np.nan
                cur_sig=cl_sig[s.ticker];cur_raw=cl_raw[s.ticker]
                implied=(prev_raw/prev_sig)/(cur_raw/cur_sig) if all(np.isfinite(x) and x>0 for x in [prev_sig,prev_raw,cur_sig,cur_raw]) else np.nan
                relerr=abs(implied/ratio-1) if np.isfinite(implied) else np.nan
                if not np.isfinite(relerr):raise RuntimeError({'date':ds,'ticker':tk,'reason':'split_ratio_unverifiable'})
                effective=float(implied) if relerr>0.05 else ratio
                if not np.isfinite(effective) or effective<=0:raise RuntimeError({'date':ds,'ticker':tk,'reason':'split_ratio_bad'})
                effective_splits[s.ticker]=effective
                qnew=s.qty*effective;qwhole=math.floor(qnew+1e-9);frac=qnew-qwhole;s.qty=float(qwhole)
                if frac>1e-9:
                    px=op_raw[s.ticker]
                    if not (np.isfinite(px) and px>0 and np.isfinite(volume[s.ticker]) and volume[s.ticker]>0):raise RuntimeError({'date':ds,'ticker':tk,'reason':'fractional_split_no_CIL'})
                    wc.cash+=frac*float(px)*(1-COST)

            # Open equity before Wealth Core's own open trades.  This is the close->open shadow leg.
            oe=wc.open_equity(op_raw)

            # terminal/conversion actions become open exits
            for s in wc.slots:
                if not s.held:continue
                tk=tick[s.ticker];kinds={a for a,_,_ in day_actions.get(tk,[])};term=sorted(kinds&TERMINAL)
                if term and not s.pending_sell:s.pending_sell=True;s.pending_reason='corporate_action:'+','.join(term)
            # sells first
            for s in wc.slots:
                if not(s.pending_sell and s.held):continue
                tid=s.ticker;px=op_raw[tid];tk=tick[tid]
                executable=np.isfinite(px) and px>0 and np.isfinite(volume[tid]) and volume[tid]>0
                is_terminal=s.pending_reason.startswith('corporate_action:')
                if executable:
                    gross=s.qty*float(px);wc.cash+=gross-gross*COST
                    if s.pending_reason=='trailing_stop':wc.exit_days.append(gday)
                    wc.cooldown[tid]=gday+COOLDOWN;reset_slot(s,gday+COOLDOWN)
                elif is_terminal:
                    settlement=VERIFIED_CASH_SETTLEMENTS.get(tk)
                    if settlement is not None:wc.cash+=s.qty*float(settlement)
                    wc.cooldown[tid]=gday+COOLDOWN;reset_slot(s,gday+COOLDOWN)
            # buys
            for s in wc.slots:
                if s.pending_buy<0 or s.held:continue
                tid=s.pending_buy
                if tid in terminal_seen:
                    raise RuntimeError({'date':ds,'ticker':tick[tid],'reason':'terminal_security_buy_reached_fill_loop'})
                px=op_raw[tid]
                if np.isfinite(px) and px>0 and np.isfinite(volume[tid]) and volume[tid]>0:
                    affordable=math.floor(wc.cash/(float(px)*(1+COST)));desired=math.floor(s.pending_notional/(float(px)*(1+COST)));qty=float(max(0,min(affordable,desired)))
                    if qty>=1:
                        gross=qty*float(px);wc.cash-=gross+gross*COST;wc.episode_seq+=1
                        s.ticker=tid;s.qty=qty;s.peak_signal=float(cl_sig[tid]) if np.isfinite(cl_sig[tid]) else float(g.open.iloc[0]);s.entry_signal=float(g.loc[g.tid.eq(tid),'open'].iloc[0]);s.entry_raw=float(px);s.entry_day=gday;s.ready=0;s.reviewed=False;s.cost_basis=gross*(1+COST);s.dividends=0.;s.episode=wc.episode_seq
                        wc.last_raw[tid]=float(cl_raw[tid]) if np.isfinite(cl_raw[tid]) else float(px)
                        executed_buys.append({'date':ds,'ticker':tick[tid],'qty':qty,'price':float(px),'notional':gross})
                s.pending_buy=-1;s.pending_notional=0.

            # Certification invariant: never hold two securities from the same
            # economic issuer. This is deliberately checked after every open fill.
            held_issuer_keys=[issuer[s.ticker] for s in wc.slots if s.held]
            issuer_conflict_invariant_checks += 1
            if len(held_issuer_keys) != len(set(held_issuer_keys)):
                counts={}
                for k0 in held_issuer_keys: counts[k0]=counts.get(k0,0)+1
                dupkeys={k0 for k0,v0 in counts.items() if v0>1}
                dupholdings=[[tick[s.ticker],issuer[s.ticker]] for s in wc.slots if s.held and issuer[s.ticker] in dupkeys]
                raise RuntimeError({'date':ds,'reason':'duplicate_economic_issuer_held','holdings':dupholdings})

            # dividends/spinoff cash equivalents for prior-close holders
            div_total=0.
            for tid,qprior in prior_qty.items():
                tk=tick[tid];rows=day_actions.get(tk,[]);divs=[val for a,val,_ in rows if a=='dividend' and val is not None and np.isfinite(val) and val>=0];spinvals=[val for a,val,_ in rows if a=='spinoffdividend' and val is not None and np.isfinite(val) and val>=0]
                if spinvals and not any(a=='spinoff' for a,_,_ in rows):raise RuntimeError({'date':ds,'ticker':tk,'reason':'orphan_spinoffdividend'})
                if divs:
                    amount=float(sum(divs));ratio=effective_splits.get(tid,split_products.get(tk,1.0));basis='pre_split'
                    if ratio!=1.0:
                        pr=float(raw_ring[(gday-1)%L,tid]);pa=float(adj_ring[(gday-1)%L,tid]);cr=cl_raw[tid];ca0=cl_adj[tid]
                        basis=infer_dividend_basis(pr,cr,pa,ca0,ratio,amount)
                    entitlement=qprior*(ratio if basis=='post_split' else 1.0)*amount;div_total+=entitlement
                    for s in wc.slots:
                        if s.held and s.ticker==tid:s.dividends+=entitlement
                if spinvals:
                    amount=qprior*float(sum(spinvals));div_total+=amount
                    for s in wc.slots:
                        if s.held and s.ticker==tid:s.dividends+=amount
            wc.receivable+=div_total

            for s in wc.slots:
                if s.held and np.isfinite(cl_raw[s.ticker]) and cl_raw[s.ticker]>0:wc.last_raw[s.ticker]=float(cl_raw[s.ticker])
            # close stops/review
            for s in wc.slots:
                if not s.held:continue
                px=cl_sig[s.ticker]
                if not(np.isfinite(px) and px>0):continue
                s.peak_signal=max(s.peak_signal,float(px)) if np.isfinite(s.peak_signal) else float(px)
                age=gday-s.entry_day
                if px<=s.peak_signal*(1-STOP_PCT):s.pending_sell=True;s.pending_reason='trailing_stop'
                qualifies=bool(in_pool[s.ticker] and np.isfinite(rec[s.ticker]) and rec[s.ticker]>=0)
                if age>=REVIEW_AGE and not s.reviewed:
                    s.reviewed=True
                    if px<s.entry_signal and not qualifies:s.pending_sell=True;s.pending_reason='quarterly_thesis_review'

            eq=wc.equity(cl_raw);stops20=sum(1 for z in wc.exit_days if 0<=gday-z<20)

            # Exact recovered breadth classifier, computed directly from current shadow holdings.
            held=[]
            for s in wc.slots:
                if not s.held:continue
                tid=s.ticker;sigpx=cl_sig[tid]
                own_dd=sigpx/s.peak_signal-1 if np.isfinite(sigpx) and np.isfinite(s.peak_signal) and s.peak_signal>0 else np.nan
                lag63=float(close_ring[(gday-63)%L,tid]) if gday>=63 else np.nan
                r63=sigpx/lag63-1 if np.isfinite(sigpx) and np.isfinite(lag63) and lag63>0 else np.nan
                r21=float(rec[tid]) if np.isfinite(rec[tid]) else np.nan
                age=gday-s.entry_day
                green=(np.isfinite(own_dd) and own_dd>-0.075 and np.isfinite(r21) and r21>0 and (age<63 or (np.isfinite(r63) and r63>0)))
                red=(np.isfinite(own_dd) and own_dd<=-0.10 and np.isfinite(r21) and r21<0)
                held.append([tid,sector[tid],own_dd,r21,r63,age,green,red])
            sec_counts=defaultdict(lambda:[0,0])
            for z in held:sec_counts[z[1]][0]+=int(z[7]);sec_counts[z[1]][1]+=1
            greens=0;ambers=0
            for z in held:
                tid,sec,own_dd,r21v0,r63v,age,green,red=z;sstress=sec_counts[sec][0]/sec_counts[sec][1] if sec_counts[sec][1] else 0.
                amber=(np.isfinite(own_dd) and own_dd<=-0.10) or (np.isfinite(r21v0) and r21v0<=-0.03) or (sstress>=0.50 and not green)
                greens+=int(green);ambers+=int(amber)
            green_b=greens/len(held) if held else 0.;damaged_b=ambers/len(held) if held else 0.

            # schedule next Wealth Core buys after close
            if first is not None and gday>=first:
                ready=[s for s in wc.slots if not s.held and s.pending_buy<0 and gday>=s.ready]
                if ready and wc.cash>1:
                    order=pool_durable;maxe=len(ready) if not wc.bootstrap else 1;heldids=wc.held_ids();pend=wc.pending_ids();issuers=wc.held_issuers(issuer);scheduled=0
                    for tid0 in order:
                        tid=int(tid0)
                        if scheduled>=maxe:break
                        if tid in heldids or tid in pend or wc.cooldown.get(tid,-1)>gday:continue
                        if issuer[tid] in issuers:continue
                        if not np.isfinite(rec[tid]) or rec[tid]<0:continue
                        # Today's corporate actions are already finalized before
                        # admissions.  Do not create a next-open order for a
                        # security that terminated today.
                        if tid in today_terminal:
                            terminal_close_admission_blocks.append({
                                'date':ds,'ticker':tick[tid],
                                'terminal_actions':'|'.join(today_terminal[tid]),
                                'candidate_rank':int(np.where(order==tid)[0][0])+1,
                            })
                            continue
                        s=ready[scheduled];s.pending_buy=tid;s.pending_notional=ENTRY_W*eq;pend.add(tid);issuers.add(issuer[tid]);scheduled+=1
                    if not wc.bootstrap and scheduled>0:wc.bootstrap=True

            dates.append(date);shadow_eq.append(eq);open_eq.append(oe);stops_hist.append(stops20);damaged_hist.append(damaged_b);green_hist.append(green_b)
            peak=max(shadow_eq);dd=eq/peak-1
            r5=eq/shadow_eq[-6]-1 if len(shadow_eq)>=6 else np.nan;r10=eq/shadow_eq[-11]-1 if len(shadow_eq)>=11 else np.nan;r20=eq/shadow_eq[-21]-1 if len(shadow_eq)>=21 else np.nan;r40=eq/shadow_eq[-41]-1 if len(shadow_eq)>=41 else np.nan
            r5hist.append(r5);r10hist.append(r10);r20hist.append(r20);r40hist.append(r40);ddhist.append(dd)
            dam_delta5=damaged_b-damaged_hist[-6] if len(damaged_hist)>=6 else np.nan
            if date in spy.index:
                spy_r20=float(spy.loc[date,'r20']);volacc=float(spy.loc[date,'volacc'])
            else:spy_r20=volacc=np.nan
            fast_signal=(dd<=-0.10 and damaged_b>=0.85 and green_b<=0.20 and ((np.isfinite(r5) and r5<=-0.05) or (np.isfinite(r10) and r10<=-0.08)) and np.isfinite(dam_delta5) and dam_delta5>=0.40 and np.isfinite(volacc) and volacc>=0.04 and ((np.isfinite(spy_r20) and spy_r20<=-0.01) or (np.isfinite(r10) and r10<=-0.10)))
            severe_healthy=np.isfinite(r20) and r20>0 and damaged_b<=0.60 and green_b>=0.20

            # Underlying pre-Sentinel stress clock: binary 15.5% controller plus the
            # prior 40%-floor fast-shock overlay.  This clock is a sensor in 1.0x.
            regular=binary.step(gday,dd,r20,stops20)
            bf=base_fast.step(gday,fast_signal,dd,severe_healthy,entry_allowed=not regular)
            base_stress=regular or bf
            if base_stress:
                if not base_stress_prev:stress_start_i=len(shadow_eq)-1
                # len(shadow_eq)-start_index already yields 1 on the entry day.
                stress_duration=(len(shadow_eq)-stress_start_i) if stress_start_i is not None else 0
                stress_return=eq/shadow_eq[stress_start_i]-1 if stress_start_i is not None else 0.
            else:
                stress_start_i=None;stress_duration=0;stress_return=0.
            base_stress_prev=base_stress

            # Sentinel 1.0x severe controller.
            pf=parent_fast.step(gday,fast_signal,dd,severe_healthy,entry_allowed=True)
            slow_entry=(stress_duration>=30 and stress_return<=-0.02 and np.isfinite(r40) and r40<=-0.03 and damaged_b>=0.75 and green_b<=0.25)
            ps=slow.step(gday,slow_entry,severe_healthy)
            parent_next=0.0 if (pf or ps) else 1.0
            sentinel_next=ramp.next_target(gday,parent_current,parent_next,r40hist,severe_healthy)

            # Scalar next-open accounting.  At today's open, pending_sentinel was
            # decided at yesterday's close.  The old allocation owns overnight;
            # the new allocation owns open->close.
            if prev_close_eq is not None and date>start:
                old_alloc=sentinel_current;new_alloc=pending_sentinel
                prevdt=dates[-2]
                if old_alloc<1 or new_alloc<1:
                    if date not in bil.index or prevdt not in bil.index:raise RuntimeError(f'BIL unavailable for defensive interval {date}')
                if abs(new_alloc-old_alloc)<1e-15:
                    # Frozen scalar semantics: when allocation is unchanged, sleeves
                    # compound close-to-close and are mixed at the fixed allocation.
                    wc_factor=eq/prev_close_eq
                    bil_factor=float(bil.loc[date,'closeadj']/bil.loc[prevdt,'closeadj']) if old_alloc<1 else 1.0
                    factor=old_alloc*wc_factor+(1-old_alloc)*bil_factor
                else:
                    # Allocation changes execute at the next open: old allocation owns
                    # the overnight leg; new allocation owns open->close.
                    wc_overnight=oe/prev_close_eq-1;wc_intraday=eq/oe-1
                    bo=float(bil.loc[date,'adj_open']/bil.loc[prevdt,'closeadj']-1) if old_alloc<1 else 0.0
                    bi=float(bil.loc[date,'closeadj']/bil.loc[date,'adj_open']-1) if new_alloc<1 else 0.0
                    factor=(1+old_alloc*wc_overnight+(1-old_alloc)*bo)*(1-COST*abs(new_alloc-old_alloc))*(1+new_alloc*wc_intraday+(1-new_alloc)*bi)
                if live_nav is None:live_nav=1.0
                live_nav*=factor;sentinel_current=new_alloc
            elif date==start:
                live_nav=1.0
                # allocation actually held at this close after today's open
                sentinel_current=pending_sentinel
            pending_sentinel=sentinel_next;parent_current=parent_next;prev_close_eq=eq

            if date>=start:
                live_rows.append(dict(date=date,nav=live_nav,allocation=sentinel_current,parent_allocation=parent_current,shadow_equity=eq,open_shadow_equity=oe,shadow_dd=dd,damaged=damaged_b,green=green_b,r20=r20,r40=r40,stops20=stops20,stress_duration=stress_duration))

        if progress:print(f'{y}: {len(d):,} rows, {time.time()-ry:.1f}s',flush=True)
        # Release views into the yearly DataFrame before loading the next year.
        del g,tids,c,ca,cu,oo,vol,rawop,dv,lag21,lag126,prev,rr,ss,lr,fsum,fsq,fcnt,var,fvol,score,av,vt,vs,pool_raw,pool_durable
        del d

    out=pd.DataFrame(live_rows)
    out=out[(out.date>=start)&(out.date<=end)].copy()
    if len(out)<2:raise RuntimeError('insufficient output history')
    curve=out.set_index('date').nav.astype(float)
    years=(curve.index[-1]-curve.index[0]).days/365.2425
    cagr=float((curve.iloc[-1]/curve.iloc[0])**(1/years)-1);mdd,peak,trough=max_drawdown(curve);multiple=float(curve.iloc[-1]/curve.iloc[0])
    # Certification invariants and final Wealth Core book.
    zombie=[tick[s.ticker] for s in wc.slots if s.held and s.ticker in terminal_seen]
    if zombie:
        raise RuntimeError({'reason':'terminal_security_still_held','tickers':zombie})
    final_eq=float(shadow_eq[-1])
    final_holdings=[]
    for s in wc.slots:
        if not s.held: continue
        tid=s.ticker
        px=float(cl_raw[tid]) if np.isfinite(cl_raw[tid]) and cl_raw[tid]>0 else float(wc.last_raw.get(tid,np.nan))
        if not np.isfinite(px) or px<=0:
            raise RuntimeError({'reason':'unresolved_final_mark','ticker':tick[tid]})
        mv=float(s.qty*px)
        final_holdings.append({'ticker':tick[tid],'qty':float(s.qty),'mark':px,'market_value':mv,'portfolio_weight':mv/final_eq,'entry_day':int(s.entry_day),'episode':int(s.episode)})
    final_holdings=sorted(final_holdings,key=lambda r:-r['portfolio_weight'])
    final_cash=float(wc.cash+wc.receivable)
    summary={'strategy':'Sentinel 1.1-RC zero recovery gate + terminal-order + certified issuer-identity correction','runtime_inputs':'Sharadar only; no oracle files','start':str(curve.index[0].date()),'end':str(curve.index[-1].date()),'sessions':int(len(curve)),'cagr':cagr,'max_drawdown':mdd,'max_drawdown_peak':str(peak.date()),'max_drawdown_trough':str(trough.date()),'ending_multiple':multiple,'final_nav':float(curve.iloc[-1]),'wealth_core_final_multiple_from_1998':float(shadow_eq[-1]/shadow_eq[0]),'terminal_pending_entry_blocks':len(terminal_pending_entry_blocks),'terminal_close_admission_blocks':len(terminal_close_admission_blocks),'executed_buys':len(executed_buys),'ending_held_positions':len(final_holdings),'ending_cash_weight':final_cash/final_eq,'ending_stock_weight':sum(r['portfolio_weight'] for r in final_holdings),'issuer_conflict_invariant_checks':issuer_conflict_invariant_checks,'issuer_conflict_violations':0}
    if outdir:
        outdir.mkdir(parents=True,exist_ok=True)
        out.to_csv(outdir/'sentinel_1p1_daily.csv',index=False)
        (outdir/'sentinel_1p1_summary.json').write_text(json.dumps(summary,indent=2))
        pd.DataFrame(terminal_pending_entry_blocks,columns=['date','ticker','terminal_actions','pending_notional']).to_csv(outdir/'terminal_pending_entry_blocks.csv',index=False)
        pd.DataFrame(terminal_close_admission_blocks,columns=['date','ticker','terminal_actions','candidate_rank']).to_csv(outdir/'terminal_close_admission_blocks.csv',index=False)
        pd.DataFrame(executed_buys,columns=['date','ticker','qty','price','notional']).to_csv(outdir/'executed_buys.csv',index=False)
        pd.DataFrame(final_holdings,columns=['ticker','qty','mark','market_value','portfolio_weight','entry_day','episode']).to_csv(outdir/'ending_holdings.csv',index=False)
    return summary,out


def main():
    ap=argparse.ArgumentParser(description='Standalone Sentinel 1.1 historical replay from Sharadar')
    ap.add_argument('--sharadar',type=Path,required=True,help='Directory containing SEP yearly .csv.gz and ACTIONS/TICKERS/SFP ZIPs')
    ap.add_argument('--start',default='2006-07-31');ap.add_argument('--end',default='2026-07-31')
    ap.add_argument('--out',type=Path,default=Path('./sentinel_1p1_output'))
    ap.add_argument('--skip-hash-check',action='store_true');ap.add_argument('--quiet',action='store_true')
    a=ap.parse_args();summary,_=run(a.sharadar,pd.Timestamp(a.start),pd.Timestamp(a.end),a.out,not a.skip_hash_check,not a.quiet);print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
