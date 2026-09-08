#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

START=pd.Timestamp('2006-07-31'); END=pd.Timestamp('2026-07-31')
DATASET='5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993'
CERTIFIED_V1_SUMMARY='7488908b6e3da6141560838e8a825009e4462a11de733681addd17ac0658267a'
V2_PROFILE='wealth-core-v2-full-whole-share-target-v1'


def sha(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()


def load_daily(root:Path)->pd.DataFrame:
    df=pd.read_csv(root/'daily.csv.gz',compression='gzip',parse_dates=['date'])
    return df[(df.date>=START)&(df.date<=END)].reset_index(drop=True)


def load_observer(root:Path)->pd.DataFrame:
    p=root/'wealth_core_daily_observer.csv'
    if not p.is_file(): raise RuntimeError(f'missing observer daily file: {p}')
    df=pd.read_csv(p,parse_dates=['date'])
    return df[(df.date>=START)&(df.date<=END)].reset_index(drop=True)


def metrics(df:pd.DataFrame,col:str)->dict:
    x=df[['date',col]].dropna().copy()
    if len(x)<2: raise RuntimeError(f'{col}: insufficient observations')
    a=x[col].astype(float).to_numpy(); norm=a/a[0]; ret=norm[1:]/norm[:-1]-1.
    years=(x.date.iloc[-1]-x.date.iloc[0]).days/365.2425; peak=np.maximum.accumulate(norm)
    std=float(np.std(ret,ddof=1)) if len(ret)>1 else float('nan')
    return {'cagr':float(norm[-1]**(1/years)-1),'max_drawdown':float(np.min(norm/peak-1)),
            'sharpe':float(np.mean(ret)/std*np.sqrt(252)) if np.isfinite(std) and std>0 else None,
            'ending_multiple':float(norm[-1]),'sessions':int(len(x))}


def first_numeric_divergence(a:pd.DataFrame,b:pd.DataFrame,col:str)->str|None:
    x=a[col].astype(float).to_numpy(); y=b[col].astype(float).to_numpy(); scale=np.maximum(np.maximum(np.abs(x),np.abs(y)),1.)
    idx=np.flatnonzero(np.abs(x-y)>1e-10*scale); return str(a.date.iloc[int(idx[0])].date()) if len(idx) else None


def observer_stats(df:pd.DataFrame)->dict:
    eq=df.wealth_core_equity.astype(float); cash=df.cash.astype(float)
    return {'average_cash_weight':float((cash/eq).mean()),'median_cash_weight':float((cash/eq).median()),
            'average_invested_weight':float(df.invested_weight.astype(float).mean()),'median_invested_weight':float(df.invested_weight.astype(float).median()),
            'average_held_count':float(df.held_count.astype(float).mean()),'median_held_count':float(df.held_count.astype(float).median()),
            'full_slot_sessions':int((df.held_count.astype(float)>=25).sum()),'average_reserved_count':float(df.reserved_count.astype(float).mean()),
            'max_reserved_entry_cash':float(df.reserved_entry_cash.astype(float).max()),'min_uncommitted_cash':float(df.uncommitted_cash.astype(float).min())}


def read_audit(root:Path,variant:str)->tuple[pd.DataFrame,pd.DataFrame]:
    op=root/'wealth_core_order_blotter.csv'; pp=root/'wealth_core_position_lifecycle.csv'
    if not op.is_file() or not pp.is_file(): raise RuntimeError(f'{variant}: missing audit files')
    orders=pd.read_csv(op); positions=pd.read_csv(pp)
    if orders.empty or positions.empty: raise RuntimeError(f'{variant}: audit surfaces are empty')
    if not orders.order_seq.astype(int).is_monotonic_increasing: raise RuntimeError(f'{variant}: non-monotonic order sequence')
    orders.insert(0,'comparison_variant',variant); positions.insert(0,'comparison_variant',variant); return orders,positions


def annual_rows(name:str,df:pd.DataFrame,layer:str,col:str)->list[dict]:
    r=df.set_index('date')[col].astype(float).pct_change().fillna(0.)
    return [{'variant':name,'layer':layer,'year':int(y),'return':float((1+x).prod()-1)} for y,x in r.groupby(r.index.year)]


def main()->int:
    v1root=Path('backtester-results/wc-v1'); v2root=Path('backtester-results/wc-v2'); out=Path('backtester-results/comparison'); out.mkdir(parents=True,exist_ok=True)
    h1=v1root/'canonical_input_session_hashes.csv'; h2=v2root/'canonical_input_session_hashes.csv'
    if not h1.is_file() or not h2.is_file(): raise RuntimeError('canonical input session hashes missing from V1 or V2')
    if h1.read_bytes()!=h2.read_bytes(): raise RuntimeError('canonical input session hashes differ')
    s1=json.loads((v1root/'summary.json').read_text()); s2=json.loads((v2root/'summary.json').read_text())
    if s1.get('canonical_pit_dataset_hash')!=DATASET or s2.get('canonical_pit_dataset_hash')!=DATASET: raise RuntimeError('V1/V2 summary canonical dataset hash mismatch')
    v1_summary_sha=sha(v1root/'summary.json')
    if v1_summary_sha!=CERTIFIED_V1_SUMMARY: raise RuntimeError(f'V1 certified summary parity failed: {v1_summary_sha}')
    v2binding=s2.get('wealth_core_v2') or {}
    if v2binding.get('profile')!=V2_PROFILE or v2binding.get('changed_domain')!='wealth_core_entry_slot_funding': raise RuntimeError(f'V2 identity binding missing/invalid: {v2binding}')
    v1,v2=load_daily(v1root),load_daily(v2root); o1,o2=load_observer(v1root),load_observer(v2root)
    if not (len(v1)==len(v2)>5000 and v1.date.equals(v2.date)): raise RuntimeError(f'daily session mismatch V1={len(v1)} V2={len(v2)}')
    if not (len(o1)==len(o2)==len(v1) and o1.date.equals(o2.date) and o1.date.equals(v1.date)): raise RuntimeError('observer session coverage mismatch')
    variants={}
    for name,df,obs in [('V1',v1,o1),('V2',v2,o2)]:
        variants[name]={'wealth_core':metrics(df,'research_wealth_core_equity'),'research_champion_ex3':metrics(df,'research_nav'),
                        'wealth_core_state':observer_stats(obs),'allocation_transitions':int((df.research_allocation.astype(float).diff().abs()>1e-12).sum())}
    first={'wealth_core_equity':first_numeric_divergence(v1,v2,'research_wealth_core_equity'),'research_champion_nav':first_numeric_divergence(v1,v2,'research_nav'),
           'research_champion_allocation':first_numeric_divergence(v1,v2,'research_allocation'),'wealth_core_cash':first_numeric_divergence(o1,o2,'cash'),
           'wealth_core_held_count':first_numeric_divergence(o1,o2,'held_count')}
    if 'research_selected_positions_sha256' in v1 and 'research_selected_positions_sha256' in v2:
        z=v1.research_selected_positions_sha256.astype(str).ne(v2.research_selected_positions_sha256.astype(str)); first['selected_positions']=str(v1.loc[z,'date'].iloc[0].date()) if z.any() else None
    annual=[]
    for name,df in [('V1',v1),('V2',v2)]: annual+=annual_rows(name,df,'wealth_core','research_wealth_core_equity')+annual_rows(name,df,'research_champion_ex3','research_nav')
    pd.DataFrame(annual).to_csv(out/'annual_returns.csv',index=False)
    o1.add_prefix('v1_').join(o2.add_prefix('v2_')).to_csv(out/'wealth_core_state_comparison.csv.gz',index=False,compression='gzip')
    orders1,positions1=read_audit(v1root,'V1'); orders2,positions2=read_audit(v2root,'V2')
    orders=pd.concat([orders1,orders2],ignore_index=True); orders['issued_session']=pd.to_datetime(orders.issued_session); orders.sort_values(['issued_session','comparison_variant','order_seq'],inplace=True); orders.to_csv(out/'chronological_order_blotter_v1_v2.csv',index=False)
    positions=pd.concat([positions1,positions2],ignore_index=True); positions['entry_session']=pd.to_datetime(positions.entry_session); positions.sort_values(['entry_session','comparison_variant','episode_id'],inplace=True); positions.to_csv(out/'position_lifecycle_v1_v2.csv',index=False)
    order_summary={}; position_summary={}
    for name,oo,pp in [('V1',orders1,positions1),('V2',orders2,positions2)]:
        side=oo.side.astype(str); status=oo.status.astype(str)
        order_summary[name]={'orders_issued':int(len(oo)),'buy_orders':int(side.eq('BUY').sum()),'sell_orders':int(side.eq('SELL').sum()),'cancelled_orders':int(status.eq('CANCELLED').sum()),'partial_or_adjusted_fills':int(status.eq('PARTIAL_OR_ADJUSTED_FILLED').sum())}
        position_summary[name]={'episodes':int(len(pp)),'open_at_end':int(pp.exit_reason.astype(str).eq('OPEN_AT_END').sum()),'terminal_settlements':int(pp.exit_reason.astype(str).isin(['TERMINAL_SETTLEMENT','TERMINAL_GRACE_SETTLEMENT','TERMINAL_CONVERSION']).sum()),'median_entry_open_weight':float(pd.to_numeric(pp.entry_open_portfolio_weight,errors='coerce').median()),'minimum_observed_position_weight':float(pd.to_numeric(pp.min_close_portfolio_weight,errors='coerce').min())}
    result={'schema':'research.wealth-core-formal-v1-v2-pit-ab/1','status':'PASS','dataset_sha256':DATASET,
            'window':{'warmup_start':'2006-01-03','measurement_start':'2006-07-31','end':'2026-07-31'},
            'architecture':{'harness':'final formal Research Champion source','slots':25,'entry_weight':0.04,'v1_entry_funding':'cash_clipped_target','v2_entry_funding':V2_PROFILE,'controller_retuned':False},
            'v1_control':{'summary_sha256':v1_summary_sha,'certified_summary_sha256':CERTIFIED_V1_SUMMARY,'exact_summary_parity':True},
            'canonical_session_hashes_sha256':sha(h1),'metrics':variants,'first_divergence':first,'orders':order_summary,'positions':position_summary,
            'v2_funding_diagnostics':s2.get('wealth_core_entry_funding') or {},'v1_buys':s1.get('buys'),'v1_sells':s1.get('sells'),'v2_buys':s2.get('buys'),'v2_sells':s2.get('sells')}
    (out/'comparison.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    md=['# Wealth Core V1 vs V2 — formal broad-PIT A/B','',f"Status: **{result['status']}**",'',f"Dataset: `{DATASET}`",'',
        'V1 is the exact certified formal control. V2 changes one economic domain: Wealth Core entry-slot funding.','',
        '## Pure Wealth Core','', '| Metric | V1 | V2 |','|---|---:|---:|']
    for key,label in [('cagr','CAGR'),('max_drawdown','Max DD'),('sharpe','Sharpe'),('ending_multiple','Ending multiple')]: md.append(f"| {label} | {variants['V1']['wealth_core'][key]:.10g} | {variants['V2']['wealth_core'][key]:.10g} |")
    md += ['',f"First Wealth Core equity divergence: **{first['wealth_core_equity']}**",f"First cash divergence: **{first['wealth_core_cash']}**",f"First holding-count divergence: **{first['wealth_core_held_count']}**",'',
           '## Frozen Research Champion / EX3','', '| Metric | V1 | V2 |','|---|---:|---:|']
    for key,label in [('cagr','CAGR'),('max_drawdown','Max DD'),('sharpe','Sharpe'),('ending_multiple','Ending multiple')]: md.append(f"| {label} | {variants['V1']['research_champion_ex3'][key]:.10g} | {variants['V2']['research_champion_ex3'][key]:.10g} |")
    md += ['',f"First full-account NAV divergence: **{first['research_champion_nav']}**",f"First allocation divergence: **{first['research_champion_allocation']}**",'',
           '## V2 funding diagnostics','```json',json.dumps(result['v2_funding_diagnostics'],indent=2,sort_keys=True),'```','']
    (out/'COMPARISON.md').write_text('\n'.join(md)); print(json.dumps(result,indent=2,sort_keys=True)); return 0


if __name__=='__main__': raise SystemExit(main())
