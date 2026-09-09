#!/usr/bin/env python3
"""Run pure Median-5 Wealth Core with a 10bp NAV cash reserve on frozen canonical PIT data."""
from __future__ import annotations

import argparse, hashlib, json, os, subprocess, sys, types
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
if str(HERE) not in sys.path: sys.path.insert(0,str(HERE))
from experiment_overlay import ARMS, apply_arm, arm_dimensions, median5_only, BASE_MEDIAN5_RAW_SHA256
from backtester import champion_full_classification_control as control
from backtester.production_equivalent_economic_overlay import install, assert_contract, assert_one_session_dividend_lag
from backtester.champion_economic_prefix_audit import EXPECTED_CORPUS, PROFILE, PROFILE_HASH, RUNTIME, SOURCE, normalized_ast

BASELINE_MEDIAN5_RUN_ID=34160387335
BASELINE_MEDIAN5_ARTIFACT_ID=10032942751
BASELINE_MEDIAN5_HEAD='1c66096c1e3bd650233c630d4e9f71104ac8fc32'
BASELINE_DAILY_SHA256='4be426c1f92c6684d0227bf613d474ee335aeef71c6b87ac112dfffdb743f66e'
BASELINE_20Y={'cagr':0.16074252765555608,'ending_multiple':19.712627583637513,'max_drawdown':-0.4883977810220498,'sharpe_daily_252':0.8065779073622603}
BASELINE_NORMALIZED_SHA256='435d42ac56f160a665588a997335a923c25110404972e262aa6e47058b3befde'
EXPECTED_PACKAGE='ghcr.io/flabber1835/stocker-canonical-pit@sha256:f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c'
EXPECTED_SECURITY_COUNTS={'auto_common':6143427,'manual_common':0,'manual_non_common':2,'unknown_ineligible':1082978}
EXPECTED_CANDIDATE_COVERAGE={'base_candidates':7226407,'known_classifications':6143429,'unknown_classifications':1082978,'sessions':5050,'sessions_with_unknown':5050}

def sha(b:bytes)->str: return hashlib.sha256(b).hexdigest()

def metrics(frame:pd.DataFrame,col:str)->dict:
    nav=frame[col].astype(float)
    if len(nav)<2 or not np.isfinite(nav).all() or (nav<=0).any(): raise RuntimeError(f'invalid NAV {col}')
    years=(frame.date.iloc[-1]-frame.date.iloc[0]).days/365.2425
    multiple=float(nav.iloc[-1]/nav.iloc[0]); rets=nav.pct_change().dropna(); vol=float(rets.std(ddof=1))
    return {'start':str(frame.date.iloc[0].date()),'end':str(frame.date.iloc[-1].date()),'sessions':int(len(frame)),
            'cagr':multiple**(1.0/years)-1.0,'ending_multiple':multiple,'max_drawdown':float((nav/nav.cummax()-1).min()),
            'sharpe_daily_252':float(rets.mean()/vol*np.sqrt(252)) if vol>0 else None}

def main()->int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--arm',required=True,choices=ARMS); p.add_argument('--candidate-root',required=True,type=Path); p.add_argument('--output',required=True,type=Path); a=p.parse_args()
    out=a.output.resolve(); out.mkdir(parents=True,exist_ok=False); engine=out/'engine'; engine.mkdir(); build=out/'engine-build'; build.mkdir()
    dataset=Path(os.environ['CANONICAL_PIT_DATASET']); manifest=json.loads((dataset/'manifest.json').read_text())
    if manifest.get('dataset_hash')!=EXPECTED_CORPUS: raise RuntimeError('canonical PIT hash mismatch')
    candidate=subprocess.check_output(['git','-C',str(a.candidate_root),'rev-parse','HEAD'],text=True).strip()
    if candidate!=SOURCE['candidate']: raise RuntimeError(f'candidate pin mismatch {candidate}')
    baseline,capacity_off,prior=control.build_source(build,a.candidate_root)
    certified=install(prior); assert_contract(certified)
    if assert_one_session_dividend_lag(certified)!=1: raise RuntimeError('base dividend lag is not one')
    base_norm=sha(normalized_ast(certified).encode())
    if base_norm!=BASELINE_NORMALIZED_SHA256: raise RuntimeError(f'base normalized identity mismatch {base_norm}')
    median=median5_only(certified); median_raw=sha(median.encode())
    if median_raw!=BASE_MEDIAN5_RAW_SHA256: raise RuntimeError(f'Median-5 control source mismatch {median_raw}')
    variant=apply_arm(certified,a.arm); assert_contract(variant)
    if assert_one_session_dividend_lag(variant)!=1: raise RuntimeError('variant dividend lag changed')
    (out/'certified-base-generated.py').write_text(certified); (out/'median5-control-generated.py').write_text(median); (out/'experiment-generated.py').write_text(variant)
    os.environ['RESEARCH_REPLAY_MODE']='fullpit'
    module=types.ModuleType('median5_10bp_pure'); sys.modules[module.__name__]=module; exec(compile(variant,str(out/'experiment-generated.py'),'exec'),module.__dict__)
    if getattr(module,'MODE',None)!='fullpit' or getattr(module,'PIT_MODE',None) is not True: raise RuntimeError('variant not fullpit')
    module.OUT=engine; module.run()
    daily=engine/'daily.csv'; summ=engine/'summary.json'; trades=engine/'transactions.csv'
    if not (daily.exists() and summ.exists() and trades.exists()): raise RuntimeError('required outputs missing')
    frame=pd.read_csv(daily,parse_dates=['date']); summary=json.loads(summ.read_text()); tx=pd.read_csv(trades)
    if len(frame)!=5032 or str(frame.date.iloc[0].date())!='2006-07-31' or str(frame.date.iloc[-1].date())!='2026-07-31': raise RuntimeError('measurement witness mismatch')
    if summary.get('replay_mode')!='fullpit' or summary.get('canonical_pit_dataset_hash')!=EXPECTED_CORPUS: raise RuntimeError('summary PIT authority mismatch')
    if summary.get('financial_grade_dividend_lag_sessions')!=1: raise RuntimeError('summary dividend lag mismatch')
    if summary.get('strict_security_type_counts')!=EXPECTED_SECURITY_COUNTS: raise RuntimeError('security-type traversal changed')
    cov=summary.get('strict_candidate_security_type_coverage') or {}
    for k,v in EXPECTED_CANDIDATE_COVERAGE.items():
        if cov.get(k)!=v: raise RuntimeError(f'candidate coverage changed {k}: {cov.get(k)} != {v}')
    if summary.get('sentinel_metrics_used') is not False or summary.get('ex3_metrics_used') is not False: raise RuntimeError('controller metrics unexpectedly used')
    if summary.get('cash_buffer_basis_points')!=10.0 or summary.get('cash_buffer_fraction')!=0.001: raise RuntimeError('buffer contract mismatch')
    tele=summary.get('buffer_telemetry') or {}
    if int(tele.get('reserve_violations',-1))!=0: raise RuntimeError(f"reserve violation {tele}")
    if float(tele.get('minimum_cash',-1)) < -1e-8: raise RuntimeError(f"negative cash {tele}")
    if tele.get('minimum_post_buy_cash_excess_over_buffer') is not None and float(tele['minimum_post_buy_cash_excess_over_buffer']) < -1e-8: raise RuntimeError(f"post-buy buffer breach {tele}")
    buys=tx[tx['Buy or sell'].eq('BUY')]
    if not np.allclose(buys['Amount of shares'].astype(float),np.round(buys['Amount of shares'].astype(float)),atol=1e-10): raise RuntimeError('fractional buy detected')
    windows={}
    for years in (5,10,15,20):
        part=frame[frame.date>=frame.date.iloc[-1]-pd.DateOffset(years=years)]
        windows[str(years)]={'strategy':metrics(part,'shadow_equity'),'spy':metrics(part,'spy_nav')}
    result={'schema':'research.median5-10bp-pure/1','status':'PASS_FRESH_CAUSAL_PIT_REPLAY','arm':a.arm,'dimensions':arm_dimensions(a.arm),
            'economic_scope':'PURE_WEALTH_CORE_MEDIAN5_10BP_NO_EX3_NO_SENTINEL','baseline_reference':{'run_id':BASELINE_MEDIAN5_RUN_ID,'artifact_id':BASELINE_MEDIAN5_ARTIFACT_ID,'head':BASELINE_MEDIAN5_HEAD,'daily_sha256':BASELINE_DAILY_SHA256,'generated_source_sha256':BASE_MEDIAN5_RAW_SHA256,'pure_wealth_core_20y':BASELINE_20Y},
            'source':{'formal_source_sha':SOURCE['certified'],'candidate_source_sha':candidate,'runtime_sha':RUNTIME,'profile':PROFILE,'profile_sha256':PROFILE_HASH,'experiment_code_sha':os.environ.get('GITHUB_SHA'),'base_generated_normalized_ast_sha256':base_norm,'median5_control_generated_sha256':median_raw,'variant_generated_sha256':sha(variant.encode()),'variant_generated_normalized_ast_sha256':sha(normalized_ast(variant).encode())},
            'data':{'canonical_pit_dataset_hash':EXPECTED_CORPUS,'canonical_pit_package':EXPECTED_PACKAGE,'measurement_start':'2006-07-31','measurement_end':'2026-07-31','sessions':5032,'pit':True,'prerecorded_decisions_used':False},
            'economics':{'slots':20,'entry_weight':0.05,'median5_lookback_sessions':5,'median5_hardened_front':3,'cash_buffer_basis_points':10.0,'whole_share_buys':True,'dividend_lag_sessions':1,'ex3':False,'sentinel':False},
            'classification':{'strict_security_type_counts':summary['strict_security_type_counts'],'candidate_coverage':cov,'classification_expansion_required':False},
            'windows':windows,'engine':{'buys':summary.get('buys'),'sells':summary.get('sells'),'buffer_telemetry':tele,'transaction_rows':int(len(tx)),'all_buy_share_amounts_integer':True},'performance_target_used':False}
    b=BASELINE_20Y; n=windows['20']['strategy']; result['delta_vs_median5_control_20y']={'cagr_percentage_points':(n['cagr']-b['cagr'])*100,'max_drawdown_percentage_points':(n['max_drawdown']-b['max_drawdown'])*100,'sharpe':n['sharpe_daily_252']-b['sharpe_daily_252'],'ending_multiple':n['ending_multiple']-b['ending_multiple']}
    (out/'RESULT.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    (out/'SHA256.json').write_text(json.dumps({p.name:sha(p.read_bytes()) for p in sorted(out.iterdir()) if p.is_file() and p.name!='SHA256.json'},indent=2,sort_keys=True)+'\n')
    print('[MEDIAN5_10BP_RESULT] '+json.dumps(result,sort_keys=True),flush=True); return 0
if __name__=='__main__': raise SystemExit(main())
