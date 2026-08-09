from __future__ import annotations
import glob, math, time, zipfile, json, hashlib, csv
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
import pandas as pd

DATA=Path('/mnt/data/sep')
OUT=Path('/mnt/data/selective_firewall/position_replay')
OUT.mkdir(exist_ok=True)
START,END=1998,2026
NPOS=25; ENTRY_W=.04; STOP=.30; COOLDOWN=21; COST=.001
MIN_PRICE=1.; MIN_ADV=20_000_000.; MIN_DOL=5_000_000.; TOP_FRAC=.10
START_CAPITAL=100_000_000.0
TERMINAL={'acquisitionby','mergerto','voluntarydelisting','regulatorydelisting','bankruptcyliquidation','delisted'}
NO_EFFECT={'listed','initiated','relation','acquisitionof','tickerchangefrom'}
SPLIT_KINDS={'split','adrratiosplit'}
VERIFIED_CASH_SETTLEMENTS={'VRNA':107.0,'DAWN':21.50}


def yf(y):
    fs=glob.glob(str(DATA/f'SHARADAR_SEP_{y}.csv*.gz'))
    fs=[f for f in fs if '(' not in Path(f).name]
    if len(fs)!=1: raise RuntimeError((y,fs))
    return fs[0]

def load_meta():
    p='/mnt/data/simulator_validation/tickers/SHARADAR_TICKERS_3_9d55c66cf84cd02091405a84d061ba83.csv'
    use=['table','permaticker','ticker','category','sector','exchange','relatedtickers','lastpricedate']
    d=pd.read_csv(p,usecols=use,low_memory=False)
    d=d[d.table.eq('SEP')].dropna(subset=['ticker']).copy()
    assert not d.ticker.duplicated().any()
    tick=d.ticker.astype(str).tolist(); mp={t:i for i,t in enumerate(tick)}
    cat=d.category.fillna('').astype(str).to_numpy()
    common=np.array([('Common Stock' in c) and ('Warrant' not in c) and ('Preferred' not in c) for c in cat],bool)
    sec=d.sector.fillna('Unknown').astype(str).to_numpy()
    perm=d.permaticker.fillna(-1).astype(str).to_numpy()
    rel=d.relatedtickers.fillna('').astype(str).to_numpy()
    issuer=[]
    for t,p,r in zip(tick,perm,rel):
        names=sorted(set([t]+[x.strip() for x in r.replace(';',',').split(',') if x.strip()]))
        issuer.append('|'.join(names) if len(names)>1 else ('P:'+p))
    return d,tick,mp,common,sec,np.array(issuer,dtype=object)

def load_actions():
    p='/mnt/data/simulator_validation/actions/SHARADAR_ACTIONS_2_29fe246cadf640e7e1609af39f779093.csv'
    d=pd.read_csv(p,usecols=['date','action','ticker','value','contraticker'],low_memory=False)
    d['date']=d.date.astype(str); d['action']=d.action.astype(str).str.lower(); d['ticker']=d.ticker.astype(str)
    out=defaultdict(lambda:defaultdict(list))
    for r in d.itertuples(index=False):
        val=float(r.value) if pd.notna(r.value) else None
        out[r.date][r.ticker].append((r.action,val,None if pd.isna(r.contraticker) else str(r.contraticker)))
    return out

def load_spy():
    return {}

@dataclass
class Slot:
    ticker:int=-1; qty:float=0.; peak_signal:float=np.nan; entry_signal:float=np.nan; entry_raw:float=np.nan
    entry_day:int=-1; ready:int=0; pending_buy:int=-1; pending_notional:float=0.; pending_sell:bool=False
    pending_reason:str=''; reviewed:bool=False; cost_basis:float=0.; dividends:float=0.; episode:int=-1
    atr_pct_frozen:float=np.nan; stop_level:float=np.nan
    @property
    def held(self): return self.ticker>=0 and self.qty>1e-12

@dataclass
class Variant:
    label:str; rank_mode:str='durable'; review_age:int|None=119; stop_kind:str='fixed'; stop_pct:float=0.30
    atr_period:int=21; atr_mult:float=5.0; atr_mode:str='dynamic_pct_ratchet'; atr_min_pct:float=0.15; atr_max_pct:float=0.40
    failure_pause:bool=False; market_permission:bool=False; recent_max:float|None=None
    cash:float=START_CAPITAL; receivable:float=0.; slots:list[Slot]=field(default_factory=lambda:[Slot() for _ in range(NPOS)])
    cooldown:dict=field(default_factory=dict); bootstrap:bool=False; exit_days:list=field(default_factory=list)
    last_raw:dict=field(default_factory=dict); last_signal:dict=field(default_factory=dict); episode_seq:int=0
    daily:list=field(default_factory=list); entries:list=field(default_factory=list); exits:list=field(default_factory=list)
    actions:list=field(default_factory=list); orders:list=field(default_factory=list); blocked:list=field(default_factory=list)
    dividends_total:float=0.; commissions_total:float=0.; cil_total:float=0.; terminal_zero_total:float=0.
    def held_ids(self): return {s.ticker for s in self.slots if s.held}
    def pending_ids(self): return {s.pending_buy for s in self.slots if s.pending_buy>=0}
    def held_issuers(self,issuer): return {issuer[s.ticker] for s in self.slots if s.held}
    def equity(self,raw_close):
        x=self.cash+self.receivable
        for s in self.slots:
            if s.held:
                p=raw_close[s.ticker]
                if not np.isfinite(p): p=self.last_raw.get(s.ticker,np.nan)
                if np.isfinite(p): x+=s.qty*float(p)
        return float(x)
    def stock_value(self,raw_close):
        x=0.
        for s in self.slots:
            if s.held:
                p=raw_close[s.ticker]
                if not np.isfinite(p): p=self.last_raw.get(s.ticker,np.nan)
                if np.isfinite(p): x+=s.qty*float(p)
        return float(x)

def metrics(curve:pd.Series):
    curve=curve.dropna(); ret=curve.pct_change().dropna()
    yrs=(curve.index[-1]-curve.index[0]).days/365.25
    c=(curve.iloc[-1]/curve.iloc[0])**(1/yrs)-1
    dd=curve/curve.cummax()-1
    sh=np.sqrt(252)*ret.mean()/ret.std(ddof=1) if ret.std(ddof=1)>0 else np.nan
    trough=dd.idxmin(); peak=curve.loc[:trough].idxmax(); recov=curve.loc[trough:][curve.loc[trough:]>=curve.loc[peak]]
    recovery=None if recov.empty else str(recov.index[0].date())
    return dict(start=str(curve.index[0].date()),end=str(curve.index[-1].date()),final_multiple=float(curve.iloc[-1]/curve.iloc[0]),cagr=float(c),sharpe=float(sh),max_drawdown=float(dd.min()),calmar=float(c/abs(dd.min())),annualized_vol=float(ret.std(ddof=1)*np.sqrt(252)),max_dd_peak=str(peak.date()),max_dd_trough=str(trough.date()),max_dd_recovery=recovery)

def infer_dividend_basis(prev_raw,cur_raw,prev_adj,cur_adj,split_ratio,dividend):
    if not all(np.isfinite(x) and x>0 for x in [prev_raw,cur_raw,prev_adj,cur_adj,split_ratio]):
        raise RuntimeError('cannot infer same-day split/dividend basis')
    obs=cur_adj/prev_adj
    pre=(split_ratio*cur_raw+dividend)/prev_raw
    post=(split_ratio*cur_raw+split_ratio*dividend)/prev_raw
    epre=abs(math.log(max(pre,1e-300)/max(obs,1e-300)))
    epost=abs(math.log(max(post,1e-300)/max(obs,1e-300)))
    return ('pre_split' if epre<=epost else 'post_split'),epre,epost

def main():
    t0=time.time(); meta,tick,tmap,common,sector,issuer=load_meta(); actions=load_actions(); spy=load_spy(); n=len(tick)
    print('META',n,'COMMON',int(common.sum()),'ACTION_DATES',len(actions),flush=True)
    variants=[Variant('fixed30_control', stop_kind='fixed', stop_pct=0.30)]
    L=201
    close_ring=np.full((L,n),np.nan,np.float32); adj_ring=np.full((L,n),np.nan,np.float32); raw_ring=np.full((L,n),np.nan,np.float32)
    dv_ring=np.zeros((20,n),np.float32); dvsum=np.zeros(n,np.float64)
    r126=np.zeros((126,n),np.float32); r126v=np.zeros((126,n),np.bool_); s126=np.zeros(n,np.float64); q126=np.zeros(n,np.float64); c126=np.zeros(n,np.int16)
    r21=np.zeros((21,n),np.float32); r21v=np.zeros((21,n),np.bool_); s21=np.zeros(n,np.float64); q21=np.zeros(n,np.float64); c21=np.zeros(n,np.int16)
    ATR_MAX=42
    tr_ring=np.zeros((ATR_MAX,n),np.float32); tr_valid=np.zeros((ATR_MAX,n),np.bool_)
    atr_periods=sorted({v.atr_period for v in variants if v.stop_kind=='atr'})
    tr_sums={p:np.zeros(n,np.float64) for p in atr_periods}; tr_counts={p:np.zeros(n,np.int16) for p in atr_periods}
    atr_values={p:np.full(n,np.nan,np.float64) for p in atr_periods}
    op_raw=np.full(n,np.nan,np.float64); cl_sig=np.full(n,np.nan,np.float64); cl_raw=np.full(n,np.nan,np.float64); cl_adj=np.full(n,np.nan,np.float64)
    hi_sig=np.full(n,np.nan,np.float64); lo_sig=np.full(n,np.nan,np.float64)
    volume=np.full(n,np.nan,np.float64); dollar=np.full(n,np.nan,np.float64); sig=np.full(n,np.nan,np.float64); rec=np.full(n,np.nan,np.float64); risk=np.full(n,np.nan,np.float64); adv=np.full(n,np.nan,np.float64)
    touched=np.empty(0,np.int32); gday=-1; first=None; all_dates=[]; split_audit=[]; action_exposure=[]
    decision_rows=[]; candidate_rows=[]; position_rows=[]; decision_id=0
    cols=['ticker','date','open','high','low','close','volume','closeadj','closeunadj']
    for y in range(START,END+1):
        ry=time.time(); d=pd.read_csv(yf(y),usecols=cols,low_memory=False); d.date=pd.to_datetime(d.date)
        d=d.dropna(subset=['ticker','date','open','close','closeunadj']).drop_duplicates(['ticker','date'],keep='last')
        ids=d.ticker.map(tmap); d=d.loc[ids.notna()].copy(); d['tid']=ids.loc[ids.notna()].astype(np.int32).to_numpy()
        d.sort_values(['date','tid'],inplace=True,kind='mergesort')
        for day_i,(date,g) in enumerate(d.groupby('date',sort=True)):
            if y>=2009 and day_i%25==0: print('PROGRESS',y,day_i,str(date.date()),flush=True)
            gday+=1; ds=str(date.date()); all_dates.append(ds); spy_close,spy_sig,spy_sma=spy.get(ds,(np.nan,np.nan,np.nan))
            if touched.size:
                for a in (op_raw,cl_sig,cl_raw,cl_adj,hi_sig,lo_sig,volume,dollar,sig,rec,risk,adv): a[touched]=np.nan
            tids=g.tid.to_numpy(np.int32,copy=False); touched=tids
            c=g.close.to_numpy(float,copy=False); h=g.high.to_numpy(float,copy=False); l=g.low.to_numpy(float,copy=False); ca=g.closeadj.to_numpy(float,copy=False); cu=g.closeunadj.to_numpy(float,copy=False); oo=g.open.to_numpy(float,copy=False); vol=g.volume.to_numpy(float,copy=False)
            rawop=np.divide(oo*cu,c,out=np.full_like(oo,np.nan),where=np.isfinite(oo)&np.isfinite(cu)&np.isfinite(c)&(c>0))
            dv=np.nan_to_num(cu*vol,nan=0.,posinf=0.,neginf=0.)
            lag21=close_ring[(gday-21)%L,tids] if gday>=21 else np.full(len(tids),np.nan)
            lag126=close_ring[(gday-126)%L,tids] if gday>=126 else np.full(len(tids),np.nan)
            prev=close_ring[(gday-1)%L,tids] if gday>=1 else np.full(len(tids),np.nan)
            tr=np.maximum(h-l,np.maximum(np.abs(h-prev),np.abs(l-prev)))
            tr[~(np.isfinite(h)&np.isfinite(l)&np.isfinite(prev)&(h>0)&(l>0)&(prev>0))]=np.nan
            for p in atr_periods:
                if gday>=p:
                    oldtr=tr_ring[(gday-p)%ATR_MAX]; oldtv=tr_valid[(gday-p)%ATR_MAX]
                    tr_sums[p]-=oldtr; tr_counts[p]-=oldtv.astype(np.int16)
                mt=np.isfinite(tr)
                tr_sums[p][tids[mt]]+=tr[mt]; tr_counts[p][tids[mt]]+=1
                atr_values[p].fill(np.nan)
                ok=tr_counts[p]>=p
                atr_values[p][ok]=tr_sums[p][ok]/tr_counts[p][ok]
            tr_ring[gday%ATR_MAX].fill(0); tr_valid[gday%ATR_MAX].fill(False)
            mt=np.isfinite(tr); tr_ring[gday%ATR_MAX,tids[mt]]=tr[mt].astype(np.float32); tr_valid[gday%ATR_MAX,tids[mt]]=True
            rr=np.divide(c,lag21,out=np.full_like(c,np.nan),where=np.isfinite(lag21)&(lag21>0))-1
            ss=np.divide(lag21,lag126,out=np.full_like(c,np.nan),where=np.isfinite(lag21)&np.isfinite(lag126)&(lag126>0))-1
            lr=np.log(np.divide(c,prev,out=np.full_like(c,np.nan),where=np.isfinite(prev)&(prev>0)&np.isfinite(c)&(c>0)))
            k=gday%126; old=r126[k]; oldv=r126v[k]; s126-=old; q126-=old*old; c126-=oldv.astype(np.int16); old.fill(0); oldv.fill(False)
            m=np.isfinite(lr); old[tids[m]]=lr[m].astype(np.float32); oldv[tids[m]]=True; s126[tids[m]]+=lr[m]; q126[tids[m]]+=lr[m]*lr[m]; c126[tids[m]]+=1
            k2=gday%21; old2=r21[k2]; oldv2=r21v[k2]; s21-=old2; q21-=old2*old2; c21-=oldv2.astype(np.int16); old2.fill(0); oldv2.fill(False)
            old2[tids[m]]=lr[m].astype(np.float32); oldv2[tids[m]]=True; s21[tids[m]]+=lr[m]; q21[tids[m]]+=lr[m]*lr[m]; c21[tids[m]]+=1
            fsum=s126[tids]-s21[tids]; fsq=q126[tids]-q21[tids]; fcnt=c126[tids]-c21[tids]
            var=np.divide(fsq-fsum*fsum/np.maximum(fcnt,1),np.maximum(fcnt-1,1),out=np.full(len(tids),np.nan),where=fcnt>1)
            fvol=np.sqrt(np.maximum(var,0))*np.sqrt(252)
            score=np.divide(np.log1p(ss),fvol,out=np.full(len(tids),np.nan),where=np.isfinite(ss)&(ss>-1)&np.isfinite(fvol)&(fvol>0))
            kd=gday%20; dvsum-=dv_ring[kd]; dv_ring[kd].fill(0); dv_ring[kd,tids]=dv.astype(np.float32); dvsum[tids]+=dv; av=dvsum[tids]/20. if gday>=19 else np.full(len(tids),np.nan)
            # write arrays after lag retrieval
            close_ring[gday%L].fill(np.nan); close_ring[gday%L,tids]=c.astype(np.float32)
            adj_ring[gday%L].fill(np.nan); adj_ring[gday%L,tids]=ca.astype(np.float32)
            raw_ring[gday%L].fill(np.nan); raw_ring[gday%L,tids]=cu.astype(np.float32)
            op_raw[tids]=rawop; cl_sig[tids]=c; hi_sig[tids]=h; lo_sig[tids]=l; cl_raw[tids]=cu; cl_adj[tids]=ca; volume[tids]=vol; dollar[tids]=dv; sig[tids]=ss; rec[tids]=rr; risk[tids]=score; adv[tids]=av
            continuous=c126[tids]>=126
            elig=common[tids]&continuous&np.isfinite(ss)&np.isfinite(rr)&np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV)&np.isfinite(dv)&(dv>=MIN_DOL)&np.isfinite(score)
            vt=tids[elig]; vs=ss[elig]
            if len(vt):
                raword=np.argsort(-vs,kind='mergesort'); rawall=vt[raword]; npool=max(NPOS,int(math.ceil(len(vt)*TOP_FRAC))); pool_raw=rawall[:npool]
                riskord=np.argsort(-risk[pool_raw],kind='mergesort'); pool_durable=pool_raw[riskord]
            else: rawall=pool_raw=pool_durable=np.empty(0,np.int32)
            in_pool=np.zeros(n,np.bool_); in_pool[pool_raw]=True
            if first is None and len(pool_raw)>=NPOS: first=gday
            # actions for date
            day_actions=actions.get(ds,{})
            split_products={}
            for tk,rows in day_actions.items():
                vals=[v for a,v,_ in rows if a in SPLIT_KINDS and v is not None and np.isfinite(v) and v>0]
                if vals: split_products[tk]=float(np.prod(vals))
            for v in variants:
                # settle prior ex-date dividends; zero cash interest is explicit.
                if v.receivable:
                    v.cash+=v.receivable; v.receivable=0.
                prior_qty={s.ticker:s.qty for s in v.slots if s.held}
                # apply held splits before open, with factor validation and explicit CIL.
                # If ACTIONS conflicts with the independently observable SEP share-factor jump,
                # quarantine the declared ratio and use the SEP-implied ratio as a corrected input.
                effective_splits={}
                for s in v.slots:
                    if not s.held: continue
                    tk=tick[s.ticker]; ratio=split_products.get(tk)
                    if ratio is None: continue
                    prev_sig=float(close_ring[(gday-1)%L,s.ticker]) if gday>=1 else np.nan
                    prev_raw=float(raw_ring[(gday-1)%L,s.ticker]) if gday>=1 else np.nan
                    cur_sig=cl_sig[s.ticker]; cur_raw=cl_raw[s.ticker]
                    implied=(prev_raw/prev_sig)/(cur_raw/cur_sig) if all(np.isfinite(x) and x>0 for x in [prev_sig,prev_raw,cur_sig,cur_raw]) else np.nan
                    relerr=abs(implied/ratio-1) if np.isfinite(implied) else np.nan
                    effective=ratio
                    correction='none'
                    if not np.isfinite(relerr):
                        v.blocked.append(dict(date=ds,ticker=tk,reason='split_ratio_unverifiable',declared=ratio,implied=implied)); raise RuntimeError(v.blocked[-1])
                    if relerr>0.05:
                        if not (np.isfinite(implied) and implied>0):
                            v.blocked.append(dict(date=ds,ticker=tk,reason='split_ratio_mismatch',declared=ratio,implied=implied)); raise RuntimeError(v.blocked[-1])
                        effective=float(implied); correction='sep_implied_override'
                    effective_splits[s.ticker]=effective
                    split_audit.append(dict(date=ds,variant=v.label,ticker=tk,declared=ratio,effective=effective,implied=implied,relative_error=relerr,held=True,correction=correction))
                    qnew=s.qty*effective; qwhole=math.floor(qnew+1e-9); frac=qnew-qwhole
                    s.qty=float(qwhole)
                    if frac>1e-9:
                        px=op_raw[s.ticker]
                        if not (np.isfinite(px) and px>0 and np.isfinite(volume[s.ticker]) and volume[s.ticker]>0):
                            raise RuntimeError({'date':ds,'ticker':tk,'reason':'fractional_split_no_cash_in_lieu_price'})
                        cil=frac*float(px)*(1-COST); v.cash+=cil; v.cil_total+=cil; v.commissions_total+=frac*float(px)*COST
                        v.actions.append(dict(date=ds,ticker=tk,action='cash_in_lieu',amount=cil,qty=frac,price=float(px)))
                # terminal/conversion safety: explicit effective-date open exit. Bankruptcy with no open -> zero.
                for s in v.slots:
                    if not s.held: continue
                    tk=tick[s.ticker]; kinds={a for a,_,_ in day_actions.get(tk,[])}
                    term=sorted(kinds & TERMINAL)
                    if term and not s.pending_sell:
                        s.pending_sell=True; s.pending_reason='corporate_action:'+','.join(term)
                        action_exposure.append(dict(date=ds,variant=v.label,ticker=tk,actions='|'.join(term),qty=s.qty))
                # execute sells first
                for s in v.slots:
                    if not (s.pending_sell and s.held): continue
                    px=op_raw[s.ticker]; tk=tick[s.ticker]
                    executable=np.isfinite(px) and px>0 and np.isfinite(volume[s.ticker]) and volume[s.ticker]>0
                    is_terminal=s.pending_reason.startswith('corporate_action:')
                    if executable:
                        gross=s.qty*float(px); comm=gross*COST; v.cash+=gross-comm; v.commissions_total+=comm
                        episode_ret=(gross-comm+s.dividends-s.cost_basis)/s.cost_basis if s.cost_basis>0 else np.nan
                        v.exits.append(dict(date=ds,ticker=tk,reason=s.pending_reason,raw_price=float(px),qty=s.qty,episode_total_return=episode_ret,holding_sessions=gday-s.entry_day,dividends=s.dividends,commission=comm,episode=s.episode))
                        v.orders.append(dict(date=ds,ticker=tk,side='sell',qty=s.qty,reason=s.pending_reason))
                        if s.pending_reason=='trailing_stop': v.exit_days.append(gday)
                        v.cooldown[s.ticker]=gday+COOLDOWN
                        s.ticker=-1;s.qty=0.;s.peak_signal=np.nan;s.entry_signal=np.nan;s.entry_raw=np.nan;s.entry_day=-1;s.ready=gday+COOLDOWN;s.pending_sell=False;s.pending_reason='';s.pending_buy=-1;s.pending_notional=0.;s.reviewed=False;s.cost_basis=0.;s.dividends=0.;s.episode=-1;s.atr_pct_frozen=np.nan;s.stop_level=np.nan
                    elif is_terminal:
                        settlement=VERIFIED_CASH_SETTLEMENTS.get(tk)
                        if settlement is not None:
                            gross=s.qty*float(settlement); v.cash+=gross
                            episode_ret=(gross+s.dividends-s.cost_basis)/s.cost_basis if s.cost_basis>0 else np.nan
                            v.exits.append(dict(date=ds,ticker=tk,reason=s.pending_reason+':verified_cash_settlement',raw_price=float(settlement),qty=s.qty,episode_total_return=episode_ret,holding_sessions=gday-s.entry_day,dividends=s.dividends,commission=0.,episode=s.episode))
                            v.actions.append(dict(date=ds,ticker=tk,action='verified_cash_settlement',amount=gross,qty=s.qty,price=float(settlement)))
                        else:
                            # No guessed consideration is permitted.  A missing
                            # verified settlement remains the conservative lower bound.
                            loss=s.cost_basis; v.terminal_zero_total+=loss
                            v.exits.append(dict(date=ds,ticker=tk,reason=s.pending_reason+':zero_recovery',raw_price=0.,qty=s.qty,episode_total_return=-1.0,holding_sessions=gday-s.entry_day,dividends=s.dividends,commission=0.,episode=s.episode))
                            v.actions.append(dict(date=ds,ticker=tk,action='terminal_zero_recovery',amount=0.,qty=s.qty))
                        v.cooldown[s.ticker]=gday+COOLDOWN
                        s.ticker=-1;s.qty=0.;s.peak_signal=np.nan;s.entry_signal=np.nan;s.entry_raw=np.nan;s.entry_day=-1;s.ready=gday+COOLDOWN;s.pending_sell=False;s.pending_reason='';s.pending_buy=-1;s.pending_notional=0.;s.reviewed=False;s.cost_basis=0.;s.dividends=0.;s.episode=-1;s.atr_pct_frozen=np.nan;s.stop_level=np.nan
                # execute buys
                for s in v.slots:
                    if s.pending_buy<0 or s.held: continue
                    tid=s.pending_buy; px=op_raw[tid]; tk=tick[tid]
                    if np.isfinite(px) and px>0 and np.isfinite(volume[tid]) and volume[tid]>0:
                        affordable=math.floor(v.cash/(float(px)*(1+COST)))
                        desired=math.floor(s.pending_notional/(float(px)*(1+COST)))
                        qty=float(max(0,min(affordable,desired)))
                        if qty>=1:
                            gross=qty*float(px); comm=gross*COST; v.cash-=gross+comm; v.commissions_total+=comm
                            v.episode_seq+=1; s.ticker=tid;s.qty=qty;s.peak_signal=float(cl_sig[tid]) if np.isfinite(cl_sig[tid]) else float(g.open.iloc[0]);s.entry_signal=float(g.loc[g.tid.eq(tid),'open'].iloc[0]);s.entry_raw=float(px);s.entry_day=gday;s.ready=0;s.reviewed=False;s.cost_basis=gross+comm;s.dividends=0.;s.episode=v.episode_seq;s.atr_pct_frozen=np.nan;s.stop_level=np.nan
                            v.last_raw[tid]=float(cl_raw[tid]) if np.isfinite(cl_raw[tid]) else float(px); v.last_signal[tid]=float(cl_sig[tid]) if np.isfinite(cl_sig[tid]) else s.entry_signal
                            v.entries.append(dict(date=ds,ticker=tk,raw_price=float(px),signal_open=s.entry_signal,qty=qty,notional=gross,signal6_1=float(sig[tid]),recent21=float(rec[tid]),durable_score=float(risk[tid]),sector=sector[tid],episode=s.episode))
                            v.orders.append(dict(date=ds,ticker=tk,side='buy',notional=s.pending_notional,reason='vacancy_fill'))
                    s.pending_buy=-1;s.pending_notional=0.
                # dividends/spinoff cash equivalents for prior-close holders.
                div_total=0.
                for tid,qprior in prior_qty.items():
                    tk=tick[tid]; rows=day_actions.get(tk,[]); divs=[val for a,val,_ in rows if a=='dividend' and val is not None and np.isfinite(val) and val>=0]
                    spinvals=[val for a,val,_ in rows if a=='spinoffdividend' and val is not None and np.isfinite(val) and val>=0]
                    if spinvals and not any(a=='spinoff' for a,_,_ in rows): raise RuntimeError({'date':ds,'ticker':tk,'reason':'orphan_spinoffdividend'})
                    if divs:
                        amount=float(sum(divs)); ratio=effective_splits.get(tid,split_products.get(tk,1.0)); basis='pre_split'
                        if ratio!=1.0:
                            prev_raw=float(raw_ring[(gday-1)%L,tid]); prev_adj=float(adj_ring[(gday-1)%L,tid]); cur_raw=cl_raw[tid]; cur_adj=cl_adj[tid]
                            basis,epre,epost=infer_dividend_basis(prev_raw,cur_raw,prev_adj,cur_adj,ratio,amount)
                            split_audit.append(dict(date=ds,variant=v.label,ticker=tk,declared=ratio,implied=np.nan,relative_error=np.nan,held=True,dividend_basis=basis,basis_error_pre=epre,basis_error_post=epost))
                        entitlement=qprior*(ratio if basis=='post_split' else 1.0)*amount
                        div_total+=entitlement
                        for s in v.slots:
                            if s.held and s.ticker==tid: s.dividends+=entitlement
                    if spinvals:
                        # Vendor cash-equivalent distribution; parent remains held, child is not introduced.
                        amount=qprior*float(sum(spinvals)); div_total+=amount
                        for s in v.slots:
                            if s.held and s.ticker==tid: s.dividends+=amount
                        v.actions.append(dict(date=ds,ticker=tk,action='spinoff_cash_equivalent',amount=amount))
                v.receivable+=div_total; v.dividends_total+=div_total
                # update marks and signals after all open events
                for s in v.slots:
                    if not s.held: continue
                    if np.isfinite(cl_raw[s.ticker]) and cl_raw[s.ticker]>0: v.last_raw[s.ticker]=float(cl_raw[s.ticker])
                    if np.isfinite(cl_sig[s.ticker]) and cl_sig[s.ticker]>0: v.last_signal[s.ticker]=float(cl_sig[s.ticker])
                # close-based stop and one-time thesis review
                for s in v.slots:
                    if not s.held: continue
                    px=cl_sig[s.ticker]
                    if not (np.isfinite(px) and px>0): continue
                    s.peak_signal=max(s.peak_signal,float(px)) if np.isfinite(s.peak_signal) else float(px)
                    age=gday-s.entry_day
                    if v.stop_kind=='fixed':
                        stop_level=s.peak_signal*(1-v.stop_pct)
                    else:
                        atr=atr_values[v.atr_period][s.ticker]
                        if v.atr_mode=='entry_pct_frozen':
                            if not np.isfinite(s.atr_pct_frozen) and np.isfinite(atr) and atr>0:
                                s.atr_pct_frozen=float(np.clip(v.atr_mult*atr/px,v.atr_min_pct,v.atr_max_pct))
                            dist_pct=s.atr_pct_frozen
                        else:
                            dist_pct=float(np.clip(v.atr_mult*atr/px,v.atr_min_pct,v.atr_max_pct)) if np.isfinite(atr) and atr>0 else np.nan
                        candidate=s.peak_signal*(1-dist_pct) if np.isfinite(dist_pct) else np.nan
                        if np.isfinite(candidate):
                            s.stop_level=max(s.stop_level,candidate) if np.isfinite(s.stop_level) else candidate
                        stop_level=s.stop_level
                    if np.isfinite(stop_level) and px<=stop_level: s.pending_sell=True;s.pending_reason='trailing_stop'
                    qualifies=bool(in_pool[s.ticker] and np.isfinite(rec[s.ticker]) and rec[s.ticker]>=0)
                    if v.review_age is not None and age>=v.review_age and not s.reviewed:
                        s.reviewed=True
                        if px<s.entry_signal and not qualifies: s.pending_sell=True;s.pending_reason='quarterly_thesis_review'
                eq=v.equity(cl_raw); stock=v.stock_value(cl_raw); exp=stock/eq if eq>0 else np.nan
                stops20=sum(1 for x in v.exit_days if 0<=gday-x<20)
                v.daily.append(dict(date=ds,equity=eq,exposure=exp,cash=v.cash,receivable=v.receivable,positions=sum(s.held for s in v.slots),stops20=stops20,spy=spy_close))
                for s in v.slots:
                    if not s.held: continue
                    tid=s.ticker; rawpx=cl_raw[tid]
                    if not (np.isfinite(rawpx) and rawpx>0): rawpx=v.last_raw.get(tid,np.nan)
                    sigpx=cl_sig[tid]
                    own_dd=(sigpx/s.peak_signal-1.0) if np.isfinite(sigpx) and np.isfinite(s.peak_signal) and s.peak_signal>0 else np.nan
                    lag63=float(close_ring[(gday-63)%L,tid]) if gday>=63 else np.nan
                    r63=(sigpx/lag63-1.0) if np.isfinite(sigpx) and np.isfinite(lag63) and lag63>0 else np.nan
                    value=s.qty*rawpx if np.isfinite(rawpx) else np.nan
                    position_rows.append(dict(date=ds,ticker=tick[tid],tid=int(tid),sector=sector[tid],episode=int(s.episode),entry_day=int(s.entry_day),age_sessions=int(gday-s.entry_day),qty=float(s.qty),raw_close=float(rawpx) if np.isfinite(rawpx) else np.nan,signal_close=float(sigpx) if np.isfinite(sigpx) else np.nan,peak_signal=float(s.peak_signal) if np.isfinite(s.peak_signal) else np.nan,entry_signal=float(s.entry_signal) if np.isfinite(s.entry_signal) else np.nan,position_value=float(value) if np.isfinite(value) else np.nan,weight_equity=float(value/eq) if np.isfinite(value) and eq>0 else np.nan,weight_stock=float(value/stock) if np.isfinite(value) and stock>0 else np.nan,own_dd=float(own_dd) if np.isfinite(own_dd) else np.nan,r21=float(rec[tid]) if np.isfinite(rec[tid]) else np.nan,r63=float(r63) if np.isfinite(r63) else np.nan,durable_score=float(risk[tid]) if np.isfinite(risk[tid]) else np.nan,shadow_equity=float(eq),shadow_exposure=float(exp),stops20=int(stops20),pending_sell=bool(s.pending_sell),pending_reason=str(s.pending_reason)))
                # schedule buys after close
                if first is not None and gday>=first:
                    ready=[s for s in v.slots if not s.held and s.pending_buy<0 and gday>=s.ready]
                    healthy=(not v.failure_pause) or stops20<10
                    marketok=(not v.market_permission) or (np.isfinite(spy_sig) and np.isfinite(spy_sma) and spy_sig>=0 and spy_sma>=0)
                    if ready and healthy and marketok and v.cash>1:
                        order=pool_durable if v.rank_mode=='durable' else pool_raw
                        maxe=len(ready) if not v.bootstrap else 1
                        held=v.held_ids(); pend=v.pending_ids(); issuers=v.held_issuers(issuer); scheduled=0
                        # log top candidates only for structural-core true vacancy decisions.
                        if v.label=='structural_core':
                            decision_id+=1; decision_rows.append(dict(decision_id=decision_id,date=ds,gday=gday,ready_slots=len(ready),stops20=stops20,exposure=exp,spy_sig=spy_sig,spy_sma=spy_sma))
                            raw_rank_map={int(t):i+1 for i,t in enumerate(pool_raw)}
                            durable_rank_map={int(t):i+1 for i,t in enumerate(pool_durable)}
                            # Preserve the complete qualified top-decile population.
                            # The oracle must be able to compare the most explosive
                            # raw leader with the most durable leader even when the
                            # former ranks poorly on volatility-adjusted durability.
                            for tid0 in pool_raw:
                                tid=int(tid0); candidate_rows.append(dict(decision_id=decision_id,date=ds,gday=gday,raw_rank=raw_rank_map[tid],durable_rank=durable_rank_map[tid],ticker=tick[tid],tid=tid,raw_signal=float(sig[tid]),recent21=float(rec[tid]),durable_score=float(risk[tid]),sector=sector[tid],already_held=tid in held,ticker_cooldown=v.cooldown.get(tid,-1)>gday,issuer_conflict=issuer[tid] in issuers))
                        for tid0 in order:
                            tid=int(tid0)
                            if scheduled>=maxe: break
                            if tid in held or tid in pend or v.cooldown.get(tid,-1)>gday: continue
                            if issuer[tid] in issuers: continue
                            if not np.isfinite(rec[tid]) or rec[tid]<0: continue
                            if v.recent_max is not None and rec[tid]>v.recent_max: continue
                            s=ready[scheduled]; s.pending_buy=tid; s.pending_notional=ENTRY_W*eq; pend.add(tid); issuers.add(issuer[tid]); scheduled+=1
                        if not v.bootstrap and scheduled>0: v.bootstrap=True
        print('YEAR',y,'ROWS',len(d),'SEC',round(time.time()-ry,1),flush=True)
    # finalize and outputs
    summary=[]; eras={
        'dotcom_bear_2000_2002':('2000-03-24','2002-10-09'),
        'bull_2003_2007':('2003-01-01','2007-10-09'),
        'gfc_2007_2009':('2007-10-09','2009-03-09'),
        'bull_2009_2019':('2009-03-10','2019-12-31'),
        'covid_crash':('2020-02-19','2020-03-23'),
        'covid_bull_2020_2021':('2020-03-24','2021-12-31'),
        'rate_bear_2022':('2022-01-03','2022-10-12'),
        'bull_2023_2026':('2023-01-01','2026-08-03'),
        'nber_recession_2001':('2001-03-01','2001-11-30'),
        'nber_recession_gfc':('2007-12-01','2009-06-30'),
        'nber_recession_covid':('2020-02-01','2020-04-30'),
    }
    era_rows=[]; annual=[]
    for v in variants:
        dd=pd.DataFrame(v.daily); dd['date']=pd.to_datetime(dd.date); dd.to_csv(OUT/f'{v.label}_daily.csv',index=False)
        pd.DataFrame(v.entries).to_csv(OUT/f'{v.label}_entries.csv',index=False); pd.DataFrame(v.exits).to_csv(OUT/f'{v.label}_exits.csv',index=False); pd.DataFrame(v.orders).to_csv(OUT/f'{v.label}_orders.csv',index=False); pd.DataFrame(v.actions).to_csv(OUT/f'{v.label}_actions.csv',index=False)
        curve=dd.set_index('date').equity; m=metrics(curve); m.update(variant=v.label,entries=len(v.entries),exits=len(v.exits),avg_exposure=float(dd.exposure.mean()),min_exposure=float(dd.exposure.min()),dividends=v.dividends_total,commissions=v.commissions_total,cash_in_lieu=v.cil_total,terminal_zero_cost_basis=v.terminal_zero_total,blocked=len(v.blocked)); summary.append(m)
        for name,(a,b) in eras.items():
            x=curve.loc[a:b]
            if len(x)>1:
                em=metrics(x); sub=dd[(dd.date>=a)&(dd.date<=b)]
                era_rows.append(dict(variant=v.label,era=name,avg_exposure=float(sub.exposure.mean()),min_exposure=float(sub.exposure.min()),stop_exits=sum(1 for e in v.exits if a<=e['date']<=b and e['reason']=='trailing_stop'),thesis_exits=sum(1 for e in v.exits if a<=e['date']<=b and e['reason']=='quarterly_thesis_review'),**em))
        rets=curve.resample('YE').last().pct_change()
        for dt,val in rets.items(): annual.append(dict(variant=v.label,year=dt.year,return_=val))
    pd.DataFrame(summary).sort_values('calmar',ascending=False).to_csv(OUT/'certified_structural_summary.csv',index=False)
    pd.DataFrame(era_rows).to_csv(OUT/'certified_era_metrics.csv',index=False); pd.DataFrame(annual).to_csv(OUT/'certified_annual_returns.csv',index=False)
    pd.DataFrame(split_audit).to_csv(OUT/'split_and_dividend_basis_audit.csv',index=False); pd.DataFrame(action_exposure).to_csv(OUT/'terminal_action_exposure.csv',index=False)
    pd.DataFrame(decision_rows).to_csv(OUT/'structural_decisions.csv',index=False); pd.DataFrame(candidate_rows).to_csv(OUT/'structural_candidates_top100.csv.gz',index=False,compression='gzip')
    pd.DataFrame(position_rows).to_csv(OUT/'fixed30_position_panel.csv.gz',index=False,compression='gzip')
    meta_out={'runtime_seconds':time.time()-t0,'start_capital':START_CAPITAL,'cash_return_policy':'explicit_zero_daily_return_conservative','verified_cash_settlements':VERIFIED_CASH_SETTLEMENTS,'signal_price':'Sharadar close (split-adjusted, dividend-unadjusted)','execution_price':'raw open = open * closeunadj / close','mark_price':'closeunadj','transaction_cost_each_side':COST,'data_years':[START,END],'variants':[v.label for v in variants],'atr_definition':'true range=max(high-low,abs(high-prev_close),abs(low-prev_close)); stop distance=clip(k*ATR/close,15%,40%); peak-close trailing; ratchet-only' ,'decision_days':decision_id,'candidate_rows':len(candidate_rows)}
    (OUT/'certified_structural_metadata.json').write_text(json.dumps(meta_out,indent=2))
    print('DONE',json.dumps(meta_out),flush=True)

if __name__=='__main__': main()
