#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, math, os, shutil, subprocess, sys
from pathlib import Path
import numpy as np
import pandas as pd

CONTROL_SOURCE_SHA256='bbd6783d0cd0e5d1662a0146190962e5845cc4b6bdb8feb50d0c7788f90a6077'
CONTROL_NORMALIZED_AST_SHA256='435d42ac56f160a665588a997335a923c25110404972e262aa6e47058b3befde'
CONTROL_DAILY_SHA256='2fc1137529a7bb6e4c596d42a7af9bb0e3c891c3126116d15c342b8988235dfe'
CONTROL_SUMMARY_SHA256='d49d28069647097dea6c1c3417213a5dc9333e1ea33c8ef651f015b718cb22da'
DATASET_SHA256='5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993'
MICRO_FRACTION=0.01

def sha(b: bytes)->str: return hashlib.sha256(b).hexdigest()
def replace_once(text, old, new, label):
    n=text.count(old)
    if n!=1: raise RuntimeError(f'{label}: expected one seam, found {n}')
    return text.replace(old,new,1)

def patch_source(v1: str)->str:
    out=v1
    out=replace_once(out,
        "    pending_sell:bool=False; sell_reason:str=''; pending_tid:int=-1; pending_shares:float=0.; pending_signal_day:int=-1; ready_day:int=0",
        "    pending_sell:bool=False; sell_reason:str=''; pending_tid:int=-1; pending_shares:float=0.; pending_signal_day:int=-1; pending_intended_capital:float=0.; clean_virtual:bool=False; ready_day:int=0",
        'slot clean state')
    out=replace_once(out,
        "    cash:float=100_000_000.; receivables:list=field(default_factory=list)",
        "    cash:float=100_000_000.; receivables:list=field(default_factory=list); clean_cash:float=100_000_000.; clean_receivables:list=field(default_factory=list)",
        'clean cash state')
    out=replace_once(out,
        "        return float(v),unresolved\n    def held_ids(self):",
        "        return float(v),unresolved\n    def clean_equity(self,raw):\n        v=self.clean_cash+sum(x[1] for x in self.clean_receivables)\n        unresolved=False\n        for s in self.slots:\n            if s.held() and not s.clean_virtual:\n                p=raw[s.tid]\n                if not (finite(p) and p>0):\n                    unresolved=True; p=self.last_raw.get(s.tid,np.nan)\n                if finite(p) and p>0: v+=s.qty*float(p)\n        return float(v),unresolved\n    def held_ids(self):",
        'clean equity method')
    out=replace_once(out,
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0",
        "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; clean_virtual_entries=0; clean_omitted_gross=0.0; clean_affordability_breaches=0; clean_min_cash=100_000_000.0; clean_micro_min_fraction=1.0; clean_micro_max_fraction=0.0",
        'clean counters')
    out=replace_once(out,
        "            due=sum(a for dd,a in book.receivables if dd<=gday); book.cash+=due; book.receivables=[x for x in book.receivables if x[0]>gday]",
        "            due=sum(a for dd,a in book.receivables if dd<=gday); book.cash+=due; book.receivables=[x for x in book.receivables if x[0]>gday]\n            _clean_due=sum(a for dd,a in book.clean_receivables if dd<=gday); book.clean_cash+=_clean_due; book.clean_receivables=[x for x in book.clean_receivables if x[0]>gday]",
        'clean receivable settlement')
    out=replace_once(out,
        "                            if abs(q-round(q))>1e-8: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1\n                            else: s.pending_shares=float(round(q))",
        "                            if abs(q-round(q))>1e-8: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_intended_capital=0.\n                            else: s.pending_shares=float(round(q))",
        'cancel pending intended capital on split')
    out=replace_once(out,
        "            prior_qty={s.tid:s.qty for s in book.slots if s.held()}",
        "            prior_qty={s.tid:s.qty for s in book.slots if s.held()}\n            _clean_prior_qty={s.tid:s.qty for s in book.slots if s.held() and not s.clean_virtual}",
        'clean dividend entitlement')
    out=replace_once(out,
        "                if s.reserved() and s.pending_tid in term_tids: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "                if s.reserved() and s.pending_tid in term_tids: s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_intended_capital=0.",
        'terminal pending cancel clean')
    out=replace_once(out,
        "                    _old_tid=s.tid; book.cash+=float(_econ['cash']); book.terminal_pending.pop(_old_tid,None)",
        "                    _old_tid=s.tid; book.cash+=float(_econ['cash']); book.clean_cash+=(0.0 if s.clean_virtual else float(_econ['cash'])); book.terminal_pending.pop(_old_tid,None)",
        'exact terminal clean cash')
    out=replace_once(out,
        "                        s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN",
        "                        s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.clean_virtual=False; s.ready_day=gday+COOLDOWN",
        'exact terminal reset clean state')
    out=replace_once(out,
        "                    _tid=s.tid; book.cash+=s.qty*float(clraw[_tid]); book.sec_ready[_tid]=gday+COOLDOWN\n                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN",
        "                    _tid=s.tid; book.cash+=s.qty*float(clraw[_tid]); book.clean_cash+=(0.0 if s.clean_virtual else s.qty*float(clraw[_tid])); book.sec_ready[_tid]=gday+COOLDOWN\n                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.clean_virtual=False; s.ready_day=gday+COOLDOWN",
        'fallback terminal clean cash')
    out=replace_once(out,
        "                if q>0 and rawdiv>0: book.receivables.append((gday+1,q*rawdiv)); div_events+=1",
        "                if q>0 and rawdiv>0: book.receivables.append((gday+1,q*rawdiv)); div_events+=1\n                _cq=_clean_prior_qty.get(int(tid),0.);\n                if _cq>0 and rawdiv>0: book.clean_receivables.append((gday+1,_cq*rawdiv))",
        'clean dividends')
    out=replace_once(out,
        "                    book.cash+=s.qty*float(px)*(1-COST); sells+=1\n                    if s.sell_reason=='stop': stop_days.append(gday)\n                    _sold_tid=s.tid; book.sec_ready[_sold_tid]=gday+COOLDOWN; book.terminal_pending.pop(_sold_tid,None)\n                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.ready_day=gday+COOLDOWN",
        "                    book.cash+=s.qty*float(px)*(1-COST); book.clean_cash+=(0.0 if s.clean_virtual else s.qty*float(px)*(1-COST)); sells+=1\n                    if s.sell_reason=='stop': stop_days.append(gday)\n                    _sold_tid=s.tid; book.sec_ready[_sold_tid]=gday+COOLDOWN; book.terminal_pending.pop(_sold_tid,None)\n                    s.tid=-1; s.qty=0.; s.entry_sig=np.nan; s.peak=np.nan; s.entry_day=-1; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.clean_virtual=False; s.ready_day=gday+COOLDOWN",
        'clean normal exits')
    out=replace_once(out,
        "                    afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford)\n                    if q>=1:\n                        book.cash-=q*float(px)*(1+COST); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1\n                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1",
        "                    afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford)\n                    if q>=1:\n                        _gross=q*float(px)*(1+COST); _frac=(_gross/float(s.pending_intended_capital) if s.pending_intended_capital>0 else 0.0); _micro=bool(_frac<0.01)\n                        if _micro:\n                            clean_virtual_entries+=1; clean_omitted_gross+=_gross; clean_micro_min_fraction=min(clean_micro_min_fraction,_frac); clean_micro_max_fraction=max(clean_micro_max_fraction,_frac)\n                        else:\n                            if book.clean_cash+1e-8 < _gross: clean_affordability_breaches+=1\n                            book.clean_cash-=_gross; clean_min_cash=min(clean_min_cash,book.clean_cash)\n                        book.cash-=_gross; s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; s.clean_virtual=_micro; book.initialized=True; buys+=1\n                    s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_intended_capital=0.",
        'clean pending buy')
    out=replace_once(out,
        "                book.cash+=_slot.qty*float(_px); book.sec_ready[_tid]=gday+COOLDOWN; book.terminal_pending.pop(_tid,None)\n                _slot.tid=-1; _slot.qty=0.; _slot.entry_sig=np.nan; _slot.peak=np.nan; _slot.entry_day=-1; _slot.reviewed=False; _slot.pending_sell=False; _slot.sell_reason=''; _slot.ready_day=gday+COOLDOWN",
        "                book.cash+=_slot.qty*float(_px); book.clean_cash+=(0.0 if _slot.clean_virtual else _slot.qty*float(_px)); book.sec_ready[_tid]=gday+COOLDOWN; book.terminal_pending.pop(_tid,None)\n                _slot.tid=-1; _slot.qty=0.; _slot.entry_sig=np.nan; _slot.peak=np.nan; _slot.entry_day=-1; _slot.reviewed=False; _slot.pending_sell=False; _slot.sell_reason=''; _slot.clean_virtual=False; _slot.ready_day=gday+COOLDOWN",
        'clean C1 sweep')
    out=replace_once(out,
        "                        target=min(eq*ENTRY_W,book.cash); q=int(target//(float(px)*(1+COST)))\n                        if q<1: continue\n                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; resids.add(tid); resissuers.add(issuer_key(tid,ds)); ad+=1",
        "                        target=min(eq*ENTRY_W,book.cash); q=int(target//(float(px)*(1+COST)))\n                        if q<1: continue\n                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; s.pending_intended_capital=float(eq*ENTRY_W); resids.add(tid); resissuers.add(issuer_key(tid,ds)); ad+=1",
        'remember intended capital')
    out=replace_once(out,
        "            shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)",
        "            clean_eq,_clean_unresolved=book.clean_equity(clraw)\n            shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)",
        'clean close equity')
    out=replace_once(out,
        "'held_count':int(len(held)),'research_eligible_universe'",
        "'held_count':int(len(held)),'clean_equity':float(clean_eq),'clean_cash':float(book.clean_cash),'clean_virtual_count':int(sum(1 for s in book.slots if s.held() and s.clean_virtual)),'clean_virtual_entries_cum':int(clean_virtual_entries),'clean_omitted_gross_cum':float(clean_omitted_gross),'clean_affordability_breaches_cum':int(clean_affordability_breaches),'clean_min_cash_cum':float(clean_min_cash),'clean_micro_min_fraction_cum':(float(clean_micro_min_fraction) if clean_virtual_entries else None),'clean_micro_max_fraction_cum':(float(clean_micro_max_fraction) if clean_virtual_entries else None),'research_eligible_universe'",
        'clean daily telemetry')
    return out

def metrics(nav: pd.Series, dates: pd.Series):
    nav=nav.astype(float); years=(dates.iloc[-1]-dates.iloc[0]).days/365.2425; mult=float(nav.iloc[-1]/nav.iloc[0]); r=nav.pct_change().dropna(); vol=float(r.std(ddof=1))
    return {'cagr':mult**(1/years)-1,'ending_multiple':mult,'max_drawdown':float((nav/nav.cummax()-1).min()),'sharpe_daily_252':float(r.mean()/vol*np.sqrt(252)) if vol>0 else None,'start_equity':float(nav.iloc[0]),'end_equity':float(nav.iloc[-1])}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--candidate-root',type=Path,required=True); ap.add_argument('--engine',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); args=ap.parse_args()
    from backtester import champion_full_classification_control as control
    from backtester.production_equivalent_economic_overlay import install,assert_contract,assert_one_session_dividend_lag
    from backtester.champion_economic_prefix_audit import normalized_ast
    engine=args.engine.resolve(); outdir=args.output.resolve(); engine.mkdir(parents=True,exist_ok=True); outdir.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((Path(os.environ['CANONICAL_PIT_DATASET'])/'manifest.json').read_text())
    if manifest.get('dataset_hash')!=DATASET_SHA256: raise RuntimeError('canonical PIT dataset mismatch')
    _,_,prior=control.build_source(engine,args.candidate_root.resolve()); v1=install(prior); assert_contract(v1)
    if assert_one_session_dividend_lag(v1)!=1: raise RuntimeError('baseline dividend mismatch')
    if sha(v1.encode())!=CONTROL_SOURCE_SHA256: raise RuntimeError('V1 source mismatch')
    if sha(normalized_ast(v1).encode())!=CONTROL_NORMALIZED_AST_SHA256: raise RuntimeError('V1 AST mismatch')
    exp=patch_source(v1); assert_contract(exp)
    if assert_one_session_dividend_lag(exp)!=1: raise RuntimeError('instrumentation changed dividend semantics')
    p=outdir/'wealth-core-v1-path-preserving-clean-generated.py'; p.write_text(exp); subprocess.run([sys.executable,'-m','py_compile',str(p)],check=True)
    for stale in (engine/'daily.csv',engine/'summary.json'):
        if stale.exists(): stale.unlink()
    env=os.environ.copy(); env['RESEARCH_REPLAY_MODE']='fullpit'; subprocess.run([sys.executable,str(p)],cwd=Path.cwd(),env=env,check=True)
    frame=pd.read_csv(engine/'daily.csv',parse_dates=['date'])
    if len(frame)!=5032 or str(frame.date.iloc[0].date())!='2006-07-31' or str(frame.date.iloc[-1].date())!='2026-07-31': raise RuntimeError('horizon mismatch')
    extra=[c for c in frame.columns if c.startswith('clean_')]
    original=frame[[c for c in frame.columns if c not in extra]].copy(); original.to_csv(outdir/'v1-original-columns.csv',index=False)
    daily_hash=sha((outdir/'v1-original-columns.csv').read_bytes())
    if daily_hash!=CONTROL_DAILY_SHA256: raise RuntimeError(f'V1 path diverged: {daily_hash}')
    summary_hash=sha((engine/'summary.json').read_bytes())
    if summary_hash!=CONTROL_SUMMARY_SHA256: raise RuntimeError(f'V1 summary diverged: {summary_hash}')
    v1m=metrics(frame.shadow_equity,frame.date); cleanm=metrics(frame.clean_equity,frame.date)
    result={'schema':'research.wealth-core-v1-path-preserving-clean/1','status':'PASS','economic_scope':'WEALTH_CORE_ONLY','decision_path':'EXACT_V1','v1_daily_sha256':daily_hash,'v1_summary_sha256':summary_hash,'dataset_sha256':DATASET_SHA256,'micro_fraction':MICRO_FRACTION,'v1':v1m,'clean_no_micro':cleanm,'delta_vs_v1':{'cagr_percentage_points':(cleanm['cagr']-v1m['cagr'])*100,'ending_equity':cleanm['end_equity']-v1m['end_equity']},'telemetry':{'virtual_entries':int(frame.clean_virtual_entries_cum.iloc[-1]),'omitted_gross_capital_cumulative':float(frame.clean_omitted_gross_cum.iloc[-1]),'affordability_breaches':int(frame.clean_affordability_breaches_cum.iloc[-1]),'minimum_clean_cash':float(frame.clean_min_cash_cum.min()),'minimum_micro_fraction':float(frame.clean_micro_min_fraction_cum.dropna().min()),'maximum_micro_fraction':float(frame.clean_micro_max_fraction_cum.dropna().max()),'max_concurrent_virtual':int(frame.clean_virtual_count.max()),'sessions_with_virtual':int((frame.clean_virtual_count>0).sum())}}
    (outdir/'RESULT.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n'); shutil.copy2(engine/'daily.csv',outdir/'daily.csv'); shutil.copy2(engine/'summary.json',outdir/'summary.json')
    print('[PATH_PRESERVING_CLEAN] '+json.dumps(result,sort_keys=True),flush=True)
    return 0
if __name__=='__main__': raise SystemExit(main())
