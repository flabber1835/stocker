#!/usr/bin/env python3
"""Execute the single final Production-equivalent Champion replay and certify its path."""
from __future__ import annotations
import argparse, hashlib, json, os, sys, types
from pathlib import Path
import pandas as pd
import numpy as np
from backtester import champion_full_classification_control as control
from backtester.production_equivalent_economic_overlay import install, assert_contract
from backtester.champion_economic_prefix_audit import EXPECTED_CORPUS, PROFILE, PROFILE_HASH, RUNTIME, SOURCE, normalized_ast


def sha(b: bytes) -> str: return hashlib.sha256(b).hexdigest()

def metrics(frame, col):
    nav=frame[col].astype(float)
    if len(nav)<2 or not np.isfinite(nav).all() or (nav<=0).any(): raise RuntimeError('invalid NAV path')
    years=(frame.date.iloc[-1]-frame.date.iloc[0]).days/365.2425
    multiple=float(nav.iloc[-1]/nav.iloc[0]); r=nav.pct_change().dropna(); vol=float(r.std(ddof=1))
    return {'start':str(frame.date.iloc[0].date()),'end':str(frame.date.iloc[-1].date()),'sessions':len(frame),
            'cagr':multiple**(1/years)-1,'ending_multiple':multiple,
            'max_drawdown':float((nav/nav.cummax()-1).min()),
            'sharpe_daily_252':float(r.mean()/vol*np.sqrt(252)) if vol>0 else None}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--candidate-root',required=True,type=Path); p.add_argument('--output',required=True,type=Path); a=p.parse_args()
    out=a.output.resolve(); out.mkdir(parents=True,exist_ok=False); engine=out/'engine'; engine.mkdir()
    manifest=json.loads((Path(os.environ['CANONICAL_PIT_DATASET'])/'manifest.json').read_text())
    if manifest.get('dataset_hash')!=EXPECTED_CORPUS: raise RuntimeError('canonical corpus identity mismatch')
    import subprocess
    cand=subprocess.check_output(['git','-C',str(a.candidate_root),'rev-parse','HEAD'],text=True).strip()
    if cand!=SOURCE['candidate']: raise RuntimeError('candidate source pin mismatch')
    baseline, capacity_off, prior=control.build_source(engine,a.candidate_root)
    final=install(prior); assert_contract(final)
    if '_research_capacity_guard(' in final: raise RuntimeError('capacity guard remains')
    raw_source_sha=sha(final.encode())
    normalized_source_sha=sha(normalized_ast(final).encode())
    expected_normalized=os.environ.get('EXPECTED_FINAL_NORMALIZED_SHA256','').strip()
    if not expected_normalized:
        raise RuntimeError('missing EXPECTED_FINAL_NORMALIZED_SHA256 preflight identity')
    if normalized_source_sha != expected_normalized:
        raise RuntimeError(f'normalized generated source identity mismatch: {normalized_source_sha} != {expected_normalized}')
    (out/'production-equivalent-generated.py').write_text(final)
    os.environ['RESEARCH_REPLAY_MODE']='fullpit'
    module=types.ModuleType('champion_production_equivalent_final'); sys.modules[module.__name__]=module
    exec(compile(final,str(out/'production-equivalent-generated.py'),'exec'),module.__dict__)
    if getattr(module,'MODE',None) != 'fullpit' or getattr(module,'PIT_MODE',None) is not True:
        raise RuntimeError(f'generated replay runtime mode is not fullpit: MODE={getattr(module,"MODE",None)!r} PIT_MODE={getattr(module,"PIT_MODE",None)!r}')
    module.run()
    daily=engine/'daily.csv'
    if not daily.exists():
        cands=list(engine.rglob('daily.csv'))
        if not cands: raise RuntimeError('daily.csv not found')
        daily=max(cands,key=lambda x:x.stat().st_size)
    frame=pd.read_csv(daily,parse_dates=['date'])
    if len(frame)!=5032 or str(frame.date.iloc[0].date())!='2006-07-31' or str(frame.date.iloc[-1].date())!='2026-07-31' or frame.date.duplicated().any() or not frame.date.is_monotonic_increasing:
        raise RuntimeError('full-horizon witness mismatch')
    windows={}
    for y in (5,10,15,20):
        start=frame.date.iloc[-1]-pd.DateOffset(years=y); part=frame[frame.date>=start]
        windows[str(y)]={'strategy':metrics(part,'A_nav'),'spy':metrics(part,'spy_nav')}
    report={'schema':'champion.production-equivalent-certificate/2','status':'PRODUCTION_EQUIVALENT_CERTIFIED',
            'formal_source_sha':SOURCE['certified'],'candidate_source_sha':cand,'runtime_sha':RUNTIME,
            'profile':PROFILE,'profile_sha256':PROFILE_HASH,'corpus_hash':EXPECTED_CORPUS,
            'measurement_start':'2006-07-31','end_session':'2026-07-31','sessions':len(frame),
            'replay_mode':'fullpit','capacity_participation_cap':None,'dividend_lag_sessions':1,
            'final_truth_classifier':'champion_final_security_truth','performance_target_used':False,
            'generated_source_sha256':raw_source_sha,
            'generated_source_normalized_ast_sha256':normalized_source_sha,
            'preflight_normalized_ast_sha256':expected_normalized,
            'windows':windows}
    (out/'CERTIFICATE.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    (out/'SHA256.json').write_text(json.dumps({p.name:sha(p.read_bytes()) for p in sorted(out.iterdir()) if p.is_file() and p.name!='SHA256.json'},indent=2,sort_keys=True)+'\n')
    print('[PRODUCTION_EQUIVALENT_CERTIFICATE] '+json.dumps(report,sort_keys=True),flush=True)
    return 0
if __name__=='__main__': raise SystemExit(main())
