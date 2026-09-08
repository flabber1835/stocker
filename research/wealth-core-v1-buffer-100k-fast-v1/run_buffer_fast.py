#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path
import numpy as np, pandas as pd

CAPITAL=100_000.0
BASELINE_METRICS={
  'start':'2006-07-31','end':'2026-07-31','sessions':5032,
  'cagr':0.1454603836086088,'ending_multiple':15.122573069642186,
  'max_drawdown':-0.4901142196226078,'sharpe_daily_252':0.7649936149589806,
  'start_equity':92399.478103788,'end_equity':1397317.8592213374,
}

def load(path):
    ns={'__name__':f'loaded_{path.stem}','__file__':str(path)}
    exec(compile(path.read_text(),str(path),'exec'),ns); return ns

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--candidate-root',type=Path,required=True); ap.add_argument('--engine',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args()
    from backtester import champion_full_classification_control as control
    from backtester.production_equivalent_economic_overlay import install,assert_contract,assert_one_session_dividend_lag
    from backtester.champion_economic_prefix_audit import normalized_ast
    here=Path(__file__).resolve().parents[1]
    buf=load(here/'wealth-core-v1-buffer-100k-v1'/'run_buffer_100k.py')
    clean=load(here/'wealth-core-v1-clean-100k-v1'/'run_clean_100k.py')
    cap=load(here/'wealth-core-v1-capital-scale-v1'/'run_capital_scale.py')
    sha=clean['sha']; metrics=clean['metrics']; run_source=clean['run_source']
    ds=clean['DATASET_SHA256']; src_hash=clean['CONTROL_SOURCE_SHA256']; ast_hash=clean['CONTROL_NORMALIZED_AST_SHA256']; base_src_hash=clean['BASELINE_SOURCE_SHA256']
    engine=a.engine.resolve(); out=a.output.resolve(); engine.mkdir(parents=True,exist_ok=True); out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((Path(os.environ['CANONICAL_PIT_DATASET'])/'manifest.json').read_text())
    if manifest.get('dataset_hash')!=ds: raise RuntimeError('canonical PIT mismatch')
    _,_,raw=control.build_source(engine,a.candidate_root.resolve()); v1=install(raw); assert_contract(v1)
    if assert_one_session_dividend_lag(v1)!=1: raise RuntimeError('dividend authority mismatch')
    if sha(v1.encode())!=src_hash or sha(normalized_ast(v1).encode())!=ast_hash: raise RuntimeError('V1 source authority mismatch')
    baseline=cap['patch_source'](v1,CAPITAL); assert_contract(baseline)
    if sha(baseline.encode())!=base_src_hash: raise RuntimeError('100k source authority mismatch')
    buffered=buf['patch'](baseline); assert_contract(buffered)
    if assert_one_session_dividend_lag(buffered)!=1: raise RuntimeError('buffer patch changed dividend semantics')
    psrc=out/'buffer-generated.py'; psrc.write_text(buffered); subprocess.run([sys.executable,'-m','py_compile',str(psrc)],check=True)
    env=os.environ.copy(); env['RESEARCH_REPLAY_MODE']='fullpit'
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
    result={'schema':'research.wealth-core-v1-buffer-100k-fast/1','status':status,'economic_scope':'WEALTH_CORE_V1_ONLY','sentinel_metrics_used':False,'initial_capital':CAPITAL,'cash_buffer_fraction':0.001,'cash_buffer_basis_points':10.0,'fractional_share_buys':False,'dataset_sha256':ds,
      'baseline_authority':{'run_id':34267327656,'artifact_id':10073578819,'source_sha256':clean['BASELINE_SOURCE_SHA256'],'daily_sha256':clean['BASELINE_DAILY_SHA256'],'summary_sha256':clean['BASELINE_SUMMARY_SHA256']},
      'v1_100k':BASELINE_METRICS,'buffer_10bp_integer_shares':m,'delta_vs_v1':{'cagr_percentage_points':(m['cagr']-BASELINE_METRICS['cagr'])*100,'ending_equity':m['end_equity']-BASELINE_METRICS['end_equity']},'buffer_telemetry':bt,'entry_telemetry':scale,
      'transaction_ledger':{'rows':int(len(tx)),'buys':int(tx['Buy or sell'].eq('BUY').sum()),'sells':int(tx['Buy or sell'].eq('SELL').sum()),'all_buy_share_amounts_integer':True},'buffer_source_sha256':sha(buffered.encode()),'baseline_replay_skipped':True}
    (out/'RESULT.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n'); print('[WEALTH_CORE_V1_BUFFER_100K_FAST] '+json.dumps(result,sort_keys=True),flush=True)
    if status!='PASS': raise RuntimeError(f'cash buffer invariant failed: {excess}')
    return 0
if __name__=='__main__': raise SystemExit(main())
