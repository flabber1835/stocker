#!/usr/bin/env python3
"""Zero-budget Stage 6: causal modeled long-put hedge economics.

This is a DIAGNOSTIC ESTIMATE, not an observed-options backtest. Pre-2024 option
chains are not asserted. It consumes immutable Stage 4 cash telemetry, Stage 5
systemic-concordance episodes, frozen Cboe VIX closes, and pinned SFP ETF prices.

The accepted E3 control remains untouched. A separate modeled Sentinel hedge
sleeve is funded only from the active Wealth Core sleeve's natural unreserved
cash. Premium is an asset transfer; only execution slippage and subsequent option
P&L alter combined account NAV.
"""
from __future__ import annotations

import argparse, hashlib, itertools, json, math, zipfile
from pathlib import Path
import numpy as np
import pandas as pd

LABEL="WC_TARGETED_HEDGE_STAGE6_MODELED_PUTS_ZERO_BUDGET"
TICKERS=("SPY","IWM","QQQ")
BETA_WINDOW=126
VOL_WINDOW=63
INITIAL_ACCOUNT_DOLLARS=100_000_000.0
SHAPES={
    "ATM_90D":{"strike_ratio":1.00,"dte_calendar":90},
    "OTM5_120D":{"strike_ratio":0.95,"dte_calendar":120},
    "OTM10_180D":{"strike_ratio":0.90,"dte_calendar":180},
}
STRESSES={
    "BASE":{"entry_iv_multiplier":1.00,"half_spread_fraction":0.02},
    "CONSERVATIVE":{"entry_iv_multiplier":1.25,"half_spread_fraction":0.10},
}
TARGETS={
    "2011":("2011-07-07","2011-10-03"),
    "2020":("2020-02-18","2020-03-23"),
    "2024_JULAUG":("2024-07-15","2024-08-05"),
    "2025":("2025-02-14","2025-04-08"),
}
WINDOWS={
    "5":("2021-07-30",5.0),
    "10":("2016-07-29",10.0),
    "15":("2011-07-29",15.0),
    "20":("2006-07-31",20.0),
    "max":("1998-01-02",None),
}


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for ch in iter(lambda:f.read(1024*1024),b""): h.update(ch)
    return h.hexdigest()


def load_sfp(path: Path) -> pd.DataFrame:
    parts=[]
    with zipfile.ZipFile(path) as z:
        names=[n for n in z.namelist() if n.lower().endswith('.csv')]
        if len(names)!=1: raise RuntimeError(f"SFP member count {names}")
        with z.open(names[0]) as f:
            for ch in pd.read_csv(f,usecols=['ticker','date','open','close','closeadj'],chunksize=450_000,low_memory=False):
                q=ch[ch.ticker.astype(str).isin(TICKERS)].copy()
                if len(q): parts.append(q)
    x=pd.concat(parts,ignore_index=True)
    x['date']=pd.to_datetime(x.date)
    x['adjopen']=x.open.astype(float)*x.closeadj.astype(float)/x.close.astype(float)
    x=x.sort_values(['ticker','date'],kind='mergesort').drop_duplicates(['ticker','date'],keep='last')
    frames=[]
    for t in TICKERS:
        q=x[x.ticker.eq(t)][['date','adjopen','closeadj']].set_index('date').astype(float)
        q.columns=[f'{t}_open',f'{t}_close']
        frames.append(q)
    return pd.concat(frames,axis=1).sort_index()


def nnls_small(A: np.ndarray,y: np.ndarray) -> np.ndarray:
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


def beta_at_signal(frame: pd.DataFrame, idx: int) -> dict[str,float]:
    if idx < BETA_WINDOW: return {}
    y=frame.wc_ret.iloc[idx-BETA_WINDOW+1:idx+1]
    available=[]
    for t in TICKERS:
        s=frame[f'{t}_ret'].iloc[idx-BETA_WINDOW+1:idx+1]
        if s.notna().all(): available.append(t)
    if not available or y.isna().any(): return {}
    A=np.column_stack([frame[f'{t}_ret'].iloc[idx-BETA_WINDOW+1:idx+1].to_numpy(float) for t in available])
    coef=nnls_small(A,y.to_numpy(float))
    return {t:float(c) for t,c in zip(available,coef) if c>1e-12}


def norm_cdf(x: float) -> float:
    return 0.5*(1.0+math.erf(x/math.sqrt(2.0)))


def bs_put(S: float,K: float,T: float,sigma: float) -> tuple[float,float]:
    # Diagnostic European approximation with r=q=0. Positive rates would reduce
    # put value; ignored ETF dividends would increase it. Conservative execution
    # stress is therefore evaluated separately and E8 remains closed pending
    # observed 2024-26 validation.
    if not (S>0 and K>0 and sigma>0): return (float('nan'),float('nan'))
    if T<=1e-12:
        return (max(K-S,0.0), -1.0 if S<K else 0.0)
    st=sigma*math.sqrt(T)
    d1=(math.log(S/K)+0.5*sigma*sigma*T)/st
    d2=d1-st
    price=K*norm_cdf(-d2)-S*norm_cdf(-d1)
    delta=norm_cdf(d1)-1.0
    return float(max(price,0.0)),float(delta)


def metrics(frame: pd.DataFrame,column: str,start: str,years: float|None) -> dict:
    x=frame[frame.date>=pd.Timestamp(start)][['date',column]].dropna().copy()
    if x.empty: raise RuntimeError(f'empty metrics {column} {start}')
    v=x[column].astype(float).to_numpy(); norm=v/v[0]; rets=norm[1:]/norm[:-1]-1
    peak=np.maximum.accumulate(norm); dd=float(np.min(norm/peak-1))
    if years is None: years=(x.date.iloc[-1]-x.date.iloc[0]).days/365.2425
    cagr=float(norm[-1]**(1/years)-1)
    std=float(np.std(rets,ddof=1)) if len(rets)>1 else np.nan
    sharpe=float(np.mean(rets)/std*math.sqrt(252)) if std>0 else np.nan
    return {'start':str(x.date.iloc[0].date()),'end':str(x.date.iloc[-1].date()),'sessions':int(len(x)),
            'cagr':cagr,'max_drawdown':dd,'sharpe':sharpe,'ending_multiple':float(norm[-1])}


def previous_value(s: pd.Series,idx: int) -> float:
    q=s.iloc[:idx+1].dropna()
    if q.empty: return np.nan
    return float(q.iloc[-1])


def vol_for(frame: pd.DataFrame,ticker: str,idx: int,vix: pd.Series,entry_mult: float=1.0) -> float:
    vv=previous_value(vix,idx)
    if not np.isfinite(vv) or vv<=0: return np.nan
    if ticker=='SPY': ratio=1.0
    else:
        a=previous_value(frame[f'{ticker}_rv63'],idx); b=previous_value(frame['SPY_rv63'],idx)
        if not (np.isfinite(a) and np.isfinite(b) and a>0 and b>0): return np.nan
        ratio=a/b
    return float(vv/100.0*ratio*entry_mult)


def contracts_for(beta: dict[str,float],spots: dict[str,float],vols: dict[str,float],shape: dict,
                  exposure_dollars: float,budget: float,spread: float) -> tuple[dict[str,int],dict[str,dict],float,float]:
    target={}; quotes={}; full_cost=0.0
    for t,b in beta.items():
        S=spots.get(t,np.nan); sig=vols.get(t,np.nan)
        if not (np.isfinite(S) and S>0 and np.isfinite(sig) and sig>0 and b>0): continue
        K=S*shape['strike_ratio']; T=shape['dte_calendar']/365.2425
        mid,delta=bs_put(S,K,T,sig)
        if not (np.isfinite(mid) and mid>0 and np.isfinite(delta) and abs(delta)>1e-6): continue
        need=exposure_dollars*b
        n=int(math.floor(need/(abs(delta)*S*100.0)))
        if n<=0: continue
        quotes[t]={'S':S,'K':K,'sigma':sig,'mid':mid,'delta':delta}
        target[t]=n; full_cost+=n*mid*100.0*(1+spread)
    if full_cost<=0 or budget<=0: return {},quotes,0.0,0.0
    scale=min(1.0,budget/full_cost)
    chosen={t:int(math.floor(n*scale)) for t,n in target.items()}
    chosen={t:n for t,n in chosen.items() if n>0}
    cost=sum(n*quotes[t]['mid']*100.0*(1+spread) for t,n in chosen.items())
    while cost>budget+1e-6 and chosen:
        t=max(chosen,key=lambda k:chosen[k]*quotes[k]['mid'])
        chosen[t]-=1
        if chosen[t]<=0: del chosen[t]
        cost=sum(n*quotes[k]['mid']*100.0*(1+spread) for k,n in chosen.items())
    target_delta=sum(target[t]*abs(quotes[t]['delta'])*quotes[t]['S']*100.0 for t in target)
    achieved_delta=sum(chosen[t]*abs(quotes[t]['delta'])*quotes[t]['S']*100.0 for t in chosen)
    coverage=achieved_delta/target_delta if target_delta>0 else 0.0
    return chosen,quotes,float(cost),float(coverage)


def run_variant(base: pd.DataFrame,episodes: pd.DataFrame,shape_name: str,stress_name: str) -> tuple[pd.DataFrame,pd.DataFrame]:
    shape=SHAPES[shape_name]; stress=STRESSES[stress_name]
    d=base.copy().reset_index(drop=True); d['hedge_pnl_dollars']=0.0
    realized=0.0; trade_rows=[]
    date_to_i={pd.Timestamp(v):int(i) for i,v in enumerate(d.date)}

    for ep in episodes.itertuples(index=False):
        trig=pd.Timestamp(ep.trigger_date); rel=pd.Timestamp(ep.release_date)
        if trig not in date_to_i: continue
        ti=date_to_i[trig]
        if ti+1>=len(d): continue
        entry_i=ti+1
        # Exit no earlier than the next open after the recovery close. If recovery
        # is end-of-sample, mark through the sample end.
        release_i=date_to_i.get(rel,len(d)-1)
        exit_i=min(release_i+1,len(d)-1)
        if str(ep.release_reason)=='END_OF_SAMPLE': exit_i=len(d)-1

        next_alloc=float(d.iloc[entry_i].research_allocation)
        account_value=float(d.iloc[ti].research_nav)*INITIAL_ACCOUNT_DOLLARS
        cash_frac=float(d.iloc[ti].wc_next_open_unreserved_cash_fraction)
        # Use only natural cash attributable to the active WC sleeve. This is a
        # conservative cap; Sentinel defensive cash is excluded.
        initial_budget=max(account_value*max(next_alloc,0.0)*max(cash_frac,0.0),0.0)
        exposure=account_value*max(next_alloc,0.0)
        beta=beta_at_signal(d,ti)
        spots={t:float(d.iloc[entry_i][f'{t}_open']) for t in beta if pd.notna(d.iloc[entry_i][f'{t}_open'])}
        vols={t:vol_for(d,t,ti,d.vix_close,stress['entry_iv_multiplier']) for t in beta}
        chosen,quotes,cost,coverage=contracts_for(beta,spots,vols,shape,exposure,initial_budget,stress['half_spread_fraction'])
        budget=initial_budget-cost
        positions={}
        nominal_expiry=pd.Timestamp(d.iloc[entry_i].date)+pd.Timedelta(days=shape['dte_calendar'])
        for t,n in chosen.items():
            positions[t]={'contracts':n,'K':quotes[t]['K'],'expiry':nominal_expiry,'entry_mid':quotes[t]['mid']}
            trade_rows.append({'variant':f'{shape_name}__{stress_name}','episode':int(ep.episode),'action':'BUY','date':str(pd.Timestamp(d.iloc[entry_i].date).date()),'ticker':t,'contracts':n,'spot':quotes[t]['S'],'strike':quotes[t]['K'],'dte_calendar':shape['dte_calendar'],'iv':quotes[t]['sigma'],'mid':quotes[t]['mid'],'half_spread_fraction':stress['half_spread_fraction'],'cash_flow':-n*quotes[t]['mid']*100.0*(1+stress['half_spread_fraction']),'initial_budget':initial_budget,'delta_coverage_fraction':coverage,'control_allocation':next_alloc})

        # If no active WC exposure/cash, the episode is deliberately unhedged.
        if not positions:
            trade_rows.append({'variant':f'{shape_name}__{stress_name}','episode':int(ep.episode),'action':'SKIP_NO_FUNDED_EXPOSURE','date':str(pd.Timestamp(d.iloc[entry_i].date).date()),'ticker':'','contracts':0,'spot':np.nan,'strike':np.nan,'dte_calendar':shape['dte_calendar'],'iv':np.nan,'mid':np.nan,'half_spread_fraction':stress['half_spread_fraction'],'cash_flow':0.0,'initial_budget':initial_budget,'delta_coverage_fraction':0.0,'control_allocation':next_alloc})
            continue

        for i in range(entry_i,exit_i+1):
            day=pd.Timestamp(d.iloc[i].date)
            # Scheduled expiry/roll at the first trading open on or after nominal expiry.
            if positions and day>=min(p['expiry'] for p in positions.values()) and i<exit_i:
                # Settle all old puts at open intrinsic, then re-establish the same
                # shape using only the original hedge budget plus realized proceeds.
                proceeds=0.0
                for t,p in list(positions.items()):
                    S=float(d.iloc[i][f'{t}_open']); intrinsic=max(p['K']-S,0.0)
                    cf=p['contracts']*intrinsic*100.0; proceeds+=cf
                    trade_rows.append({'variant':f'{shape_name}__{stress_name}','episode':int(ep.episode),'action':'EXPIRY','date':str(day.date()),'ticker':t,'contracts':p['contracts'],'spot':S,'strike':p['K'],'dte_calendar':0,'iv':np.nan,'mid':intrinsic,'half_spread_fraction':0.0,'cash_flow':cf,'initial_budget':initial_budget,'delta_coverage_fraction':np.nan,'control_allocation':float(d.iloc[i].research_allocation)})
                budget+=proceeds; positions={}
                sig_i=max(i-1,0); alloc=float(d.iloc[i].research_allocation); acct=float(d.iloc[sig_i].research_nav)*INITIAL_ACCOUNT_DOLLARS
                beta=beta_at_signal(d,sig_i); spots={t:float(d.iloc[i][f'{t}_open']) for t in beta if pd.notna(d.iloc[i][f'{t}_open'])}; vols={t:vol_for(d,t,sig_i,d.vix_close,stress['entry_iv_multiplier']) for t in beta}
                chosen,quotes,cost,coverage=contracts_for(beta,spots,vols,shape,acct*max(alloc,0.0),budget,stress['half_spread_fraction'])
                budget-=cost; nominal_expiry=day+pd.Timedelta(days=shape['dte_calendar'])
                for t,n in chosen.items():
                    positions[t]={'contracts':n,'K':quotes[t]['K'],'expiry':nominal_expiry,'entry_mid':quotes[t]['mid']}
                    trade_rows.append({'variant':f'{shape_name}__{stress_name}','episode':int(ep.episode),'action':'ROLL_BUY','date':str(day.date()),'ticker':t,'contracts':n,'spot':quotes[t]['S'],'strike':quotes[t]['K'],'dte_calendar':shape['dte_calendar'],'iv':quotes[t]['sigma'],'mid':quotes[t]['mid'],'half_spread_fraction':stress['half_spread_fraction'],'cash_flow':-n*quotes[t]['mid']*100.0*(1+stress['half_spread_fraction']),'initial_budget':initial_budget,'delta_coverage_fraction':coverage,'control_allocation':alloc})

            # Exit at next open after recovery close. Value using only the previous
            # completed session's volatility information.
            if i==exit_i and str(ep.release_reason)!='END_OF_SAMPLE':
                proceeds=0.0
                for t,p in list(positions.items()):
                    S=float(d.iloc[i][f'{t}_open']); sig=vol_for(d,t,max(i-1,0),d.vix_close,1.0); T=max((p['expiry']-day).days,0)/365.2425
                    mid,_=bs_put(S,p['K'],T,sig); cf=p['contracts']*mid*100.0*(1-stress['half_spread_fraction']); proceeds+=cf
                    trade_rows.append({'variant':f'{shape_name}__{stress_name}','episode':int(ep.episode),'action':'SELL_RECOVERY','date':str(day.date()),'ticker':t,'contracts':p['contracts'],'spot':S,'strike':p['K'],'dte_calendar':max((p['expiry']-day).days,0),'iv':sig,'mid':mid,'half_spread_fraction':stress['half_spread_fraction'],'cash_flow':cf,'initial_budget':initial_budget,'delta_coverage_fraction':np.nan,'control_allocation':float(d.iloc[i].research_allocation)})
                budget+=proceeds; positions={}; realized+=(budget-initial_budget)
                d.loc[i:,'hedge_pnl_dollars']=realized
                break

            # End-of-day mark. Mid marks do not charge an artificial liquidation spread.
            mark=budget
            for t,p in positions.items():
                S=float(d.iloc[i][f'{t}_close']); sig=vol_for(d,t,i,d.vix_close,1.0); T=max((p['expiry']-day).days,0)/365.2425
                mid,_=bs_put(S,p['K'],T,sig); mark+=p['contracts']*mid*100.0
            current=realized+(mark-initial_budget)
            d.loc[i,'hedge_pnl_dollars']=current
            if i+1<len(d): d.loc[i+1:,'hedge_pnl_dollars']=current

        if str(ep.release_reason)=='END_OF_SAMPLE' and positions:
            # Keep the final sample mark unrealized; it is already in the curve.
            pass

    d['combined_nav']=d.research_nav.astype(float)+d.hedge_pnl_dollars/INITIAL_ACCOUNT_DOLLARS
    return d,pd.DataFrame(trade_rows)


def target_episode_metrics(curve: pd.DataFrame,variant: str) -> list[dict]:
    rows=[]
    for name,(p0,t0) in TARGETS.items():
        p=pd.Timestamp(p0); t=pd.Timestamp(t0); b=curve[(curve.date>=p)&(curve.date<=t)]
        if b.empty: continue
        base=float(b.iloc[-1].research_nav/b.iloc[0].research_nav-1)
        hedged=float(b.iloc[-1].combined_nav/b.iloc[0].combined_nav-1)
        rows.append({'variant':variant,'target':name,'peak_date':p0,'trough_date':t0,'baseline_peak_to_trough_return':base,'hedged_peak_to_trough_return':hedged,'improvement':hedged-base})
    return rows


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--stage4-root',type=Path,required=True)
    ap.add_argument('--stage5-root',type=Path,required=True)
    ap.add_argument('--vix-root',type=Path,required=True)
    ap.add_argument('--sfp',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args(); a.output.mkdir(parents=True,exist_ok=True)

    s4=json.loads((a.stage4_root/'stage4_cash_summary.json').read_text())
    s5=json.loads((a.stage5_root/'stage5_summary.json').read_text())
    va=json.loads((a.vix_root/'vix_authority.json').read_text())
    if s4['status']!='PASS' or s4['accepted_e3_control_parity']['status']!='PASS': raise RuntimeError('Stage4 not accepted')
    if not s5['target_coverage']['pricing_diagnostic_gate']: raise RuntimeError('Stage5 pricing gate closed')
    if va['status']!='PASS': raise RuntimeError('VIX authority not accepted')

    d=pd.read_csv(a.stage4_root/'daily.csv.gz',compression='gzip',parse_dates=['date']).sort_values('date',kind='mergesort').reset_index(drop=True)
    eps=pd.read_csv(a.stage5_root/'systemic_concordance_episodes.csv')
    px=load_sfp(a.sfp); d=d.merge(px.reset_index(),on='date',how='left',validate='one_to_one')
    for t in TICKERS:
        d[f'{t}_ret']=d[f'{t}_close'].astype(float).pct_change()
        d[f'{t}_rv63']=d[f'{t}_ret'].rolling(VOL_WINDOW,min_periods=VOL_WINDOW).std(ddof=1)*math.sqrt(252.0)
    d['wc_ret']=d.research_wealth_core_equity.astype(float).pct_change()
    vx=pd.read_csv(a.vix_root/'VIX_1998_2026-07-31.csv',parse_dates=['DATE']).set_index('DATE').CLOSE.astype(float)
    d['vix_close']=vx.reindex(pd.DatetimeIndex(d.date)).ffill().to_numpy()
    if d.vix_close.isna().sum()>1: raise RuntimeError('VIX alignment gap')

    metric_rows=[]; episode_rows=[]; all_trades=[]; summaries={}
    baseline={w:metrics(d,'research_nav',start,yrs) for w,(start,yrs) in WINDOWS.items()}
    for shape in SHAPES:
        for stress in STRESSES:
            variant=f'{shape}__{stress}'
            curve,trades=run_variant(d,eps,shape,stress)
            curve[['date','research_nav','hedge_pnl_dollars','combined_nav']].to_csv(a.output/f'curve_{variant}.csv.gz',index=False,compression={'method':'gzip','compresslevel':6,'mtime':0})
            if not trades.empty: all_trades.append(trades)
            vm={}
            for w,(start,yrs) in WINDOWS.items():
                h=metrics(curve,'combined_nav',start,yrs); b=baseline[w]
                row={'variant':variant,'shape':shape,'stress':stress,'window':w,**h,
                     'baseline_cagr':b['cagr'],'baseline_max_drawdown':b['max_drawdown'],
                     'cagr_delta':h['cagr']-b['cagr'],
                     'relative_maxdd_improvement':1-abs(h['max_drawdown'])/abs(b['max_drawdown']) if b['max_drawdown']<0 else np.nan}
                metric_rows.append(row); vm[w]=row
            er=target_episode_metrics(curve,variant); episode_rows.extend(er)
            positive=sum(1 for r in er if r['improvement']>0)
            conservative=(stress=='CONSERVATIVE')
            model_gate=bool(conservative and vm['max']['relative_maxdd_improvement']>=.20 and vm['max']['cagr_delta']>=-.01 and vm['20']['cagr_delta']>=-.01 and positive>=2)
            summaries[variant]={'model_gate':model_gate,'positive_target_episode_improvements':int(positive),'max':vm['max'],'20':vm['20']}

    metrics_df=pd.DataFrame(metric_rows); metrics_df.to_csv(a.output/'modeled_put_metrics.csv',index=False)
    episode_df=pd.DataFrame(episode_rows); episode_df.to_csv(a.output/'modeled_put_target_episodes.csv',index=False)
    trades_df=pd.concat(all_trades,ignore_index=True) if all_trades else pd.DataFrame(); trades_df.to_csv(a.output/'modeled_put_trade_ledger.csv',index=False)

    conservative_candidates=[(k,v) for k,v in summaries.items() if k.endswith('__CONSERVATIVE') and v['model_gate']]
    conservative_candidates.sort(key=lambda kv:(kv[1]['max']['relative_maxdd_improvement'],kv[1]['20']['cagr_delta']),reverse=True)
    best=conservative_candidates[0][0] if conservative_candidates else None
    report={
        'status':'PASS','label':LABEL,'zero_budget_diagnostic':True,'strategy_mechanics_changed':False,
        'experiment_budget_consumed':False,'e8_spent':False,'evidence_level':'DIAGNOSTIC_ESTIMATE_MODELED_OPTIONS',
        'SFP_sha256':sha256(a.sfp),'vix_authority':va,'stage5_trigger_summary':s5['episode_statistics'],
        'pricing_contract':{
            'instrument_set':list(TICKERS),'beta_window_sessions':BETA_WINDOW,'relative_vol_window_sessions':VOL_WINDOW,
            'beta_method':'nonnegative least squares on returns through signal close; only instruments with complete prior window',
            'iv_method':'SPY IV = frozen Cboe VIX close; IWM/QQQ IV = VIX times causal 63-session realized-vol ratio to SPY',
            'entry_execution':'next trading open after Stage5 trigger close using trigger-close volatility information',
            'exit_execution':'next trading open after Stage5 recovery close using recovery-close volatility information',
            'funding':'active WC sleeve natural next-open unreserved cash only; defensive cash excluded; no WC liquidation',
            'delta_target':'prior systematic beta exposure times accepted E3 control account value and next-open control allocation',
            'roll_policy':'at modeled calendar expiry while Stage5 episode remains active; finance roll only from original hedge budget and proceeds',
            'risk_free_rate':0.0,'dividend_yield':0.0,'pricing_model':'European Black-Scholes diagnostic approximation',
            'shapes':SHAPES,'stresses':STRESSES,
        },
        'model_gate_contract':{
            'applies_to':'CONSERVATIVE stress only','required_relative_max_history_dd_improvement':.20,
            'required_max_history_cagr_delta_min':-.01,'required_20y_cagr_delta_min':-.01,
            'required_positive_target_episode_improvements':2,
            'observed_options_validation_still_required_before_E8':True,
        },
        'variant_summaries':summaries,
        'conservative_model_gate_passed':bool(conservative_candidates),
        'best_conservative_candidate':best,
        'e8_gate':'CLOSED_PENDING_OBSERVED_2024_2026_VALIDATION' if conservative_candidates else 'CLOSED_MODELED_ECONOMICS_NO_GO',
    }
    (a.output/'stage6_summary.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    files=[a.output/'modeled_put_metrics.csv',a.output/'modeled_put_target_episodes.csv',a.output/'modeled_put_trade_ledger.csv',a.output/'stage6_summary.json']+sorted(a.output.glob('curve_*.csv.gz'))
    (a.output/'STAGE6_SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in files))
    print(json.dumps(report,indent=2,sort_keys=True))
    print(metrics_df[metrics_df.window.isin(['max','20'])].to_string(index=False))
    print(episode_df.to_string(index=False))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
