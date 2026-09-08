#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path
import numpy as np, pandas as pd

CAPITAL=100_000.0; BUFFER=0.001

def load(path):
    ns={"__name__":f"loaded_{path.stem}","__file__":str(path)}
    exec(compile(path.read_text(),str(path),"exec"),ns); return ns

def one(src,old,new,label):
    n=src.count(old)
    if n!=1: raise RuntimeError(f"{label} seam mismatch: {n}")
    return src.replace(old,new,1)

def patch(src):
    src=one(src,
      "rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; scale_q0_candidate_skips=0; scale_one_share_entries=0; scale_cash_limited_decisions=0; scale_gap_clipped_entries=0; scale_entries=0; scale_lt1=0; scale_lt5=0; scale_lt10=0; scale_lt25=0; scale_lt50=0; scale_lt99=0; scale_min_entry_fraction=1.0; scale_max_entry_fraction=0.0; scale_entry_fraction_sum=0.0",
      "rows=[]; trade_rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; scale_q0_candidate_skips=0; scale_one_share_entries=0; scale_cash_limited_decisions=0; scale_gap_clipped_entries=0; scale_entries=0; scale_lt1=0; scale_lt5=0; scale_lt10=0; scale_lt25=0; scale_lt50=0; scale_lt99=0; scale_min_entry_fraction=1.0; scale_max_entry_fraction=0.0; scale_entry_fraction_sum=0.0; buffer_blocked_open_entries=0; buffer_min_post_buy_excess=float('inf'); buffer_micro_entries=0",'init')
    src=one(src,"book.cash+=s.qty*float(px)*(1-COST); sells+=1",
      "_sell_qty=float(s.qty); _sell_tid=int(s.tid); book.cash+=s.qty*float(px)*(1-COST); sells+=1; trade_rows.append({'Transaction date':ds,'Buy or sell':'SELL','Ticker':str(tick[_sell_tid]),'Ticker name':'','Amount of shares':_sell_qty})",'sell ledger')
    src=one(src,"_planned_q=int(round(s.pending_shares)); afford=math.floor(book.cash/(float(px)*(1+COST))); q=min(_planned_q,afford)",
      "_planned_q=int(round(s.pending_shares)); _buffer_required=max(0.0,float(open_eq)*0.001); _buffer_available=max(0.0,book.cash-_buffer_required); afford=math.floor(_buffer_available/(float(px)*(1+COST))); q=min(_planned_q,afford); buffer_blocked_open_entries+=int(_planned_q>=1 and q<1)",'open buffer')
    src=one(src,"book.cash-=_gross; s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1",
      "book.cash-=_gross; buffer_min_post_buy_excess=min(buffer_min_post_buy_excess,book.cash-_buffer_required); buffer_micro_entries+=int(_frac<0.01); trade_rows.append({'Transaction date':ds,'Buy or sell':'BUY','Ticker':str(tick[tid]),'Ticker name':'','Amount of shares':float(q)}); s.tid=tid; s.qty=float(q); s.entry_day=gday; s.reviewed=False; s.pending_sell=False; s.sell_reason=''; s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) and opsig[tid]>0 else np.nan; s.peak=np.nan; book.initialized=True; buys+=1",'buy ledger')
    src=one(src,"_desired=float(eq*ENTRY_W); target=min(_desired,book.cash); _funding_fraction=(float(target)/_desired if _desired>0 else 0.0); q=int(target//(float(px)*(1+COST)))",
      "_desired=float(eq*ENTRY_W); _buffer_required_close=max(0.0,float(eq)*0.001); _buffer_available_close=max(0.0,book.cash-_buffer_required_close); target=min(_desired,_buffer_available_close); _funding_fraction=(float(target)/_desired if _desired>0 else 0.0); q=int(target//(float(px)*(1+COST)))",'close buffer')
    src=one(src,"out.to_csv(OUT/'daily.csv',index=False)",
      "out.to_csv(OUT/'daily.csv',index=False)\n    pd.DataFrame(trade_rows,columns=['Transaction date','Buy or sell','Ticker','Ticker name','Amount of shares']).to_csv(OUT/'transactions.csv',index=False)",'csv')
    src=one(src,"'leadership_overlap_checks':overlap_checks,",
      "'wealth_core_cash_buffer':{'buffer_fraction':0.001,'fractional_share_buys':False,'blocked_open_entries':int(buffer_blocked_open_entries),'micro_entries_lt_1pct':int(buffer_micro_entries),'minimum_post_buy_cash_excess_over_buffer':(float(buffer_min_post_buy_excess) if scale_entries else None),'transaction_rows':int(len(trade_rows))},\n        'leadership_overlap_checks':overlap_checks,",'summary')
    compile(src,'<buffer>','exec'); return src

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--candidate-root',type=Path,required=True); ap.add_argument('--engine',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args()
    from backtester import champion_full_classification_control as control
    from backtester.production_equivalent_economic_overlay import install,assert_contract,assert_one_session_dividend_lag
    from backtester.champion_economic_prefix_audit import normalized_ast
    here=Path(__file__).resolve().parents[1]
    prev=load(here/'wealth-core-v1-clean-100k-v1'/'run_clean_100k.py'); cap=load(here/'wealth-core-v1-capital-scale-v1'/'run_capital_scale.py')
    sha=prev['sha']; metrics=prev['metrics']; run_source=prev['run_source']
    ds=prev['DATASET_SHA256']; src_hash=prev['CONTROL_SOURCE_SHA256']; ast_hash=prev['CONTROL_NORMALIZED_AST_SHA256']; base_src_hash=prev['BASELINE_SOURCE_SHA256']; base_daily_hash=prev['BASELINE_DAILY_SHA256']; base_summary_hash=prev['BASELINE_SUMMARY_SHA256']; base_cagr=prev['BASELINE_CAGR']
    engine=a.engine.resolve(); out=a.output.resolve(); engine.mkdir(parents=True,exist_ok=True); out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((Path(os.environ['CANONICAL_PIT_DATASET'])/'manifest.json').read_text())
    if manifest.get('dataset_hash')!=ds: raise RuntimeError('canonical PIT mismatch')
    _,_,raw=control.build_source(engine,a.candidate_root.resolve()); v1=install(raw); assert_contract(v1)
    if assert_one_session_dividend_lag(v1)!=1 or sha(v1.encode())!=src_hash or sha(normalized_ast(v1).encode())!=ast_hash: raise RuntimeError('V1 authority mismatch')
    baseline=cap['patch_source'](v1,CAPITAL); assert_contract(baseline)
    if sha(baseline.encode())!=base_src_hash: raise RuntimeError('100k source mismatch')
    bsrc=out/'baseline-generated.py'; bsrc.write_text(baseline); env=os.environ.copy(); env['RESEARCH_REPLAY_MODE']='fullpit'
    for p in (engine/'daily.csv',engine/'summary.json',engine/'transactions.csv'):
        if p.exists(): p.unlink()
    run_source(bsrc,Path.cwd(),env)
    bd=out/'baseline-daily.csv'; bs=out/'baseline-summary.json'; shutil.copy2(engine/'daily.csv',bd); shutil.copy2(engine/'summary.json',bs)
    if sha(bd.read_bytes())!=base_daily_hash or sha(bs.read_bytes())!=base_summary_hash: raise RuntimeError('100k baseline parity failure')
    bf=pd.read_csv(bd); bm=metrics(bf.shadow_equity,bf.date)
    if abs(bm['cagr']-base_cagr)>1e-12: raise RuntimeError('100k CAGR parity failure')
    buffered=patch(baseline); assert_contract(buffered)
    if assert_one_session_dividend_lag(buffered)!=1: raise RuntimeError('dividend semantics changed')
    psrc=out/'buffer-generated.py'; psrc.write_text(buffered); subprocess.run([sys.executable,'-m','py_compile',str(psrc)],check=True)
    for p in (engine/'daily.csv',engine/'summary.json',engine/'transactions.csv'):
        if p.exists(): p.unlink()
    run_source(psrc,Path.cwd(),env)
    for src,dst in ((engine/'daily.csv',out/'buffer-daily.csv'),(engine/'summary.json',out/'buffer-summary.json'),(engine/'transactions.csv',out/'transactions.csv')): shutil.copy2(src,dst)
    f=pd.read_csv(engine/'daily.csv'); m=metrics(f.shadow_equity,f.date); sm=json.loads((engine/'summary.json').read_text()); bt=sm['wealth_core_cash_buffer']; scale=sm['wealth_core_capital_scale']; tx=pd.read_csv(engine/'transactions.csv')
    cols=['Transaction date','Buy or sell','Ticker','Ticker name','Amount of shares']
    if list(tx.columns)!=cols: raise RuntimeError('transaction columns changed')
    bq=pd.to_numeric(tx.loc[tx['Buy or sell'].eq('BUY'),'Amount of shares'],errors='raise').to_numpy()
    if not np.allclose(bq,np.round(bq),atol=1e-9): raise RuntimeError('fractional BUY detected')
    excess=bt['minimum_post_buy_cash_excess_over_buffer']; status='PASS' if excess is not None and float(excess)>=-1e-8 else 'FAIL_BUFFER_BREACH'
    result={'schema':'research.wealth-core-v1-buffer-100k/1','status':status,'economic_scope':'WEALTH_CORE_V1_ONLY','sentinel_metrics_used':False,'initial_capital':CAPITAL,'cash_buffer_fraction':BUFFER,'cash_buffer_basis_points':10.0,'fractional_share_buys':False,'dataset_sha256':ds,
      'baseline_authority':{'run_id':34267327656,'artifact_id':10073578819,'source_sha256':base_src_hash,'daily_sha256':base_daily_hash,'summary_sha256':base_summary_hash},'v1_100k':bm,'buffer_10bp_integer_shares':m,'delta_vs_v1':{'cagr_percentage_points':(m['cagr']-bm['cagr'])*100,'ending_equity':m['end_equity']-bm['end_equity']},'buffer_telemetry':bt,'entry_telemetry':scale,'transaction_ledger':{'rows':int(len(tx)),'buys':int(tx['Buy or sell'].eq('BUY').sum()),'sells':int(tx['Buy or sell'].eq('SELL').sum()),'all_buy_share_amounts_integer':True},'buffer_source_sha256':sha(buffered.encode())}
    (out/'RESULT.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n'); print('[WEALTH_CORE_V1_BUFFER_100K] '+json.dumps(result,sort_keys=True),flush=True)
    if status!='PASS': raise RuntimeError(f'cash buffer invariant failed: {excess}')
    return 0
if __name__=='__main__': raise SystemExit(main())
