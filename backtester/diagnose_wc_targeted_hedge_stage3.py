#!/usr/bin/env python3
"""Zero-budget targeted-hedge Stage 3: prior-only SPY/IWM/QQQ exposure mapping."""
from __future__ import annotations
import argparse, hashlib, itertools, json, math, zipfile
from pathlib import Path
import numpy as np
import pandas as pd

LABEL="WC_TARGETED_HEDGE_STAGE3_MULTI_INDEX_ZERO_BUDGET"
WINDOWS=(63,126,252); PRIMARY=126; TICKERS=("SPY","IWM","QQQ")

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for ch in iter(lambda:f.read(1024*1024),b""): h.update(ch)
    return h.hexdigest()

def load_sfp(path):
    parts=[]
    with zipfile.ZipFile(path) as z:
        names=[n for n in z.namelist() if n.lower().endswith('.csv')]
        if len(names)!=1: raise RuntimeError(f"SFP member count {names}")
        with z.open(names[0]) as f:
            for ch in pd.read_csv(f,usecols=['ticker','date','closeadj'],chunksize=450000,low_memory=False):
                q=ch[ch.ticker.astype(str).isin(TICKERS)]
                if len(q): parts.append(q)
    x=pd.concat(parts,ignore_index=True); x['date']=pd.to_datetime(x.date)
    x=x.sort_values(['ticker','date'],kind='mergesort').drop_duplicates(['ticker','date'],keep='last')
    w=x.pivot(index='date',columns='ticker',values='closeadj').sort_index()
    for t in TICKERS:
        if t not in w: raise RuntimeError(f"missing SFP {t}")
    return w[list(TICKERS)].astype(float)

def prior_beta(y,x,w):
    cov=y.rolling(w,min_periods=w).cov(x); var=x.rolling(w,min_periods=w).var(ddof=1)
    return (cov/var).replace([np.inf,-np.inf],np.nan).shift(1)

def nnls_small(A,y):
    p=A.shape[1]; best=np.zeros(p); best_sse=float(np.dot(y,y))
    for r in range(1,p+1):
        for subset in itertools.combinations(range(p),r):
            B=A[:,subset]
            try: coef=np.linalg.lstsq(B,y,rcond=None)[0]
            except np.linalg.LinAlgError: continue
            if np.any(coef < -1e-12): continue
            coef=np.maximum(coef,0.0); res=y-B@coef; sse=float(res@res)
            if sse<best_sse:
                best_sse=sse; best=np.zeros(p); best[list(subset)]=coef
    return best

def prior_nnls(y,R,w):
    out=np.full((len(y),R.shape[1]),np.nan); yy=y.to_numpy(float); xx=R.to_numpy(float)
    for i in range(w,len(y)):
        a=xx[i-w:i]; b=yy[i-w:i]; m=np.isfinite(b)&np.isfinite(a).all(axis=1)
        if int(m.sum())<w: continue
        out[i]=nnls_small(a[m],b[m])
    return pd.DataFrame(out,index=y.index,columns=R.columns)

def fit_metrics(actual,pred):
    q=pd.concat([actual,pred],axis=1).dropna(); y=q.iloc[:,0].to_numpy(float); p=q.iloc[:,1].to_numpy(float)
    sse=float(np.sum((y-p)**2)); sst=float(np.sum(y*y))
    return {'sessions':int(len(q)),'mse':sse/len(q),'rmse':math.sqrt(sse/len(q)),
            'zero_intercept_oos_r2':1-sse/sst if sst>0 else None,'correlation':float(np.corrcoef(y,p)[0,1]) if len(q)>2 else None}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--accepted-root',type=Path,required=True); ap.add_argument('--beta-root',type=Path,required=True); ap.add_argument('--sfp',type=Path,required=True); ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    daily=pd.read_csv(a.accepted_root/'daily.csv.gz',compression='gzip',parse_dates=['date']).sort_values('date')
    attrs=pd.read_csv(a.beta_root/'wc_drawdown_beta_attribution.csv'); px=load_sfp(a.sfp); ret=px.pct_change()
    x=daily.set_index('date').copy(); x['wc_ret']=x.research_wealth_core_equity.astype(float).pct_change(); x['wc_pnl']=x.research_wealth_core_equity.astype(float).diff(); x['prior_equity']=x.research_wealth_core_equity.astype(float).shift(1)
    x=x.join(ret.rename(columns={t:f'{t}_ret' for t in TICKERS}),how='left')
    spy_from_e3=daily.set_index('date').spy_nav.astype(float).pct_change(); check=pd.concat([spy_from_e3,x['SPY_ret']],axis=1).dropna(); maxdiff=float((check.iloc[:,0]-check.iloc[:,1]).abs().max())
    if maxdiff>1e-9: raise RuntimeError(f"SPY SFP parity failed {maxdiff}")
    fit_rows=[]; attr_rows=[]; beta_rows=[]; models={}
    for w in WINDOWS:
        for t in TICKERS:
            b=prior_beta(x.wc_ret,x[f'{t}_ret'],w); pred=b*x[f'{t}_ret']; models[(w,t)]=(pred,{t:b}); fm=fit_metrics(x.wc_ret,pred); fit_rows.append({'window':w,'model':t,**fm})
            beta_rows.append({'window':w,'model':t,'component':t,'mean_beta':float(b.mean()),'median_beta':float(b.median()),'p10_beta':float(b.quantile(.1)),'p90_beta':float(b.quantile(.9))})
        R=x[[f'{t}_ret' for t in TICKERS]].copy(); R.columns=list(TICKERS); B=prior_nnls(x.wc_ret,R,w); pred=(B*R).sum(axis=1,min_count=1); models[(w,'NNLS_BLEND')]=(pred,{t:B[t] for t in TICKERS}); fm=fit_metrics(x.wc_ret,pred); fit_rows.append({'window':w,'model':'NNLS_BLEND',**fm})
        for t in TICKERS:
            b=B[t]; beta_rows.append({'window':w,'model':'NNLS_BLEND','component':t,'mean_beta':float(b.mean()),'median_beta':float(b.median()),'p10_beta':float(b.quantile(.1)),'p90_beta':float(b.quantile(.9))})
    for e in attrs.head(15).itertuples(index=False):
        p=pd.Timestamp(e.peak_date); t=pd.Timestamp(e.trough_date); block=x[(x.index>p)&(x.index<=t)]
        for w in WINDOWS:
            for model in (*TICKERS,'NNLS_BLEND'):
                pred,_=models[(w,model)]; q=pd.concat([block.wc_pnl,block.prior_equity,pred.loc[block.index]],axis=1).dropna(); q.columns=['wc_pnl','prior_equity','predret']; actual=float(q.wc_pnl.sum()) if len(q) else np.nan; market=float((q.prior_equity*q.predret).sum()) if len(q) else np.nan; share=market/actual if np.isfinite(actual) and actual<0 and np.isfinite(market) else np.nan
                attr_rows.append({'rank':int(e.rank),'peak_date':e.peak_date,'trough_date':e.trough_date,'drawdown':float(e.drawdown),'window':w,'model':model,'covered_sessions':int(len(q)),'market_pnl':market,'covered_actual_pnl':actual,'market_share_of_covered_loss':share})
    fits=pd.DataFrame(fit_rows); fits.to_csv(a.output/'multi_index_fit.csv',index=False); betas=pd.DataFrame(beta_rows); betas.to_csv(a.output/'multi_index_beta_stability.csv',index=False); at=pd.DataFrame(attr_rows); at.to_csv(a.output/'multi_index_drawdown_attribution.csv',index=False)
    primary=fits[fits.window.eq(PRIMARY)].sort_values('zero_intercept_oos_r2',ascending=False,kind='mergesort'); singles=primary[primary.model.isin(TICKERS)]; best_single=str(singles.iloc[0].model); best_single_r2=float(singles.iloc[0].zero_intercept_oos_r2); blend_r2=float(primary[primary.model.eq('NNLS_BLEND')].iloc[0].zero_intercept_oos_r2)
    winners={str(w):str(fits[(fits.window.eq(w))&fits.model.isin(TICKERS)].sort_values('zero_intercept_oos_r2',ascending=False).iloc[0].model) for w in WINDOWS}
    summary={'status':'PASS','label':LABEL,'zero_budget_diagnostic':True,'strategy_mechanics_changed':False,'experiment_budget_consumed':False,'SFP_sha256':sha256(a.sfp),'SPY_parity_max_abs_return_diff':maxdiff,'coverage':{'SPY':str(px.SPY.first_valid_index().date()),'IWM':str(px.IWM.first_valid_index().date()),'QQQ':str(px.QQQ.first_valid_index().date())},'primary_window':PRIMARY,'best_single_index':best_single,'best_single_oos_r2':best_single_r2,'nnls_blend_oos_r2':blend_r2,'nnls_blend_r2_gain_vs_best_single':blend_r2-best_single_r2,'single_index_winner_by_window':winners,'interpretation_contract':{'beta_and_blend_coefficients_strictly_prior_only':True,'same_day_future_return_in_beta_estimation':False,'multi_index_fit_is_diagnostic_not_a_hedge_backtest':True,'option_prices_used':False,'e8_spent':False}}
    (a.output/'stage3_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n'); files=[a.output/'multi_index_fit.csv',a.output/'multi_index_beta_stability.csv',a.output/'multi_index_drawdown_attribution.csv',a.output/'stage3_summary.json']; (a.output/'STAGE3_SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in files)); print(json.dumps(summary,indent=2,sort_keys=True)); print(primary.to_string(index=False)); return 0
if __name__=='__main__': raise SystemExit(main())
