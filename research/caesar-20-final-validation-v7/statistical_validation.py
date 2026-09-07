#!/usr/bin/env python3
"""DSR, CSCV/PBO and block-bootstrap reality check for the frozen portfolio-size family."""
from __future__ import annotations
import argparse, itertools, json, math
from pathlib import Path
from statistics import NormalDist
import numpy as np
import pandas as pd

ND=NormalDist(); GAMMA=0.5772156649015329

def load_daily(root: Path):
    out={}
    for p in root.rglob('daily.csv'):
        f=pd.read_csv(p,parse_dates=['date'])
        if len(f)!=5032: continue
        s=str(p)
        name=None
        for n in ('16','18','19','20','21','22','23','24','25'):
            if f'SIZE_{n}' in s or (n=='25' and 'recert' in s.lower()): name=n
        if name: out[name]=f[['date','A_nav','spy_nav']].copy()
    return out

def rets(f,col): return f[col].astype(float).pct_change().fillna(0.0).to_numpy()
def sharpe(x):
    sd=np.std(x,ddof=1); return float(np.mean(x)/sd) if sd>0 else -1e9

def dsr(r, trials):
    T=len(r); sr=sharpe(r); m=np.mean(r); sd=np.std(r,ddof=1)
    z=(r-m)/sd
    skew=float(np.mean(z**3)); kurt=float(np.mean(z**4))
    var=(1-skew*sr+((kurt-1)/4)*(sr**2))/(T-1)
    sr0=math.sqrt(max(var,0))*((1-GAMMA)*ND.inv_cdf(1-1/trials)+GAMMA*ND.inv_cdf(1-1/(trials*math.e)))
    prob=ND.cdf((sr-sr0)/math.sqrt(var)) if var>0 else 1.0
    return {'daily_sr':sr,'annualized_sr':sr*math.sqrt(252),'skew':skew,'kurtosis':kurt,'trials':trials,'expected_max_null_daily_sr':sr0,'deflated_sharpe_probability':prob}

def pbo(R, segments=16):
    T,N=R.shape
    blocks=np.array_split(np.arange(T),segments)
    logits=[]; selected=[]
    for comb in itertools.combinations(range(segments),segments//2):
        if 0 not in comb: continue
        tr=np.concatenate([blocks[i] for i in comb]); te=np.concatenate([blocks[i] for i in range(segments) if i not in comb])
        is_sr=np.array([sharpe(R[tr,j]) for j in range(N)])
        j=int(np.argmax(is_sr)); os_sr=np.array([sharpe(R[te,k]) for k in range(N)])
        order=np.argsort(np.argsort(os_sr))+1
        w=float(order[j]/(N+1.0)); logits.append(math.log(w/(1-w))); selected.append(j)
    a=np.asarray(logits)
    return {'segments':segments,'splits':len(a),'pbo':float(np.mean(a<0)),'median_oos_logit':float(np.median(a)),'selected_counts':np.bincount(selected,minlength=N).tolist()}

def reality(excess, reps=2000, block=20, seed=20260907):
    T,N=excess.shape; sd=np.std(excess,axis=0,ddof=1); obs=np.sqrt(T)*np.mean(excess,axis=0)/sd; obsmax=float(np.max(obs))
    centered=excess-np.mean(excess,axis=0)
    rng=np.random.default_rng(seed); mx=[]
    nblocks=math.ceil(T/block)
    for _ in range(reps):
        starts=rng.integers(0,T,size=nblocks)
        idx=np.concatenate([(np.arange(s,s+block)%T) for s in starts])[:T]
        x=centered[idx]; s=np.std(x,axis=0,ddof=1); t=np.sqrt(T)*np.mean(x,axis=0)/s; mx.append(float(np.max(t)))
    mx=np.asarray(mx)
    return {'bootstrap_reps':reps,'circular_block_sessions':block,'observed_max_t':obsmax,'reality_check_pvalue':float((1+np.sum(mx>=obsmax))/(reps+1))}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--artifacts',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args()
    frames=load_daily(a.artifacts); required=['16','18','19','20','21','22','23','24','25']
    miss=[x for x in required if x not in frames]
    if miss: raise RuntimeError(f'missing candidate dailies: {miss}; found={sorted(frames)}')
    dates=frames['20'].date.astype(str).tolist()
    for n in required:
        if frames[n].date.astype(str).tolist()!=dates: raise RuntimeError(f'date mismatch {n}')
    R=np.column_stack([rets(frames[n],'A_nav') for n in required]); spy=rets(frames['20'],'spy_nav')
    report={'schema':'caesar20.final-statistical-validation/1','candidate_family':required,'sessions':len(R),'dsr_known_trials_33':dsr(R[:,required.index('20')],33),'dsr_sensitivity_100_trials':dsr(R[:,required.index('20')],100),'dsr_sensitivity_250_trials':dsr(R[:,required.index('20')],250),'cscv_pbo':pbo(R,16),'white_style_block_reality_check':reality(R-spy[:,None]),'notes':['DSR trial count 33 is the documented minimum unique economic variants in this Caesar/Champion research sequence; 100 and 250 trial sensitivities are reported because earlier undocumented research may increase multiplicity.','CSCV/PBO candidate family is the complete frozen tested portfolio-size neighborhood 16,18,19,20,21,22,23,24,25.','Reality check uses paired daily excess returns versus SPY, centered under the null, with circular 20-session blocks.']}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n'); print(json.dumps(report,sort_keys=True))
if __name__=='__main__': main()
