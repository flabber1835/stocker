"""Fresh frozen-oracle replay with controller-only transformations and budget claims."""
import argparse
import hashlib
import json
import os
import platform
import sys
import time
import types
import urllib.request
from pathlib import Path
import numpy as np
import pandas as pd
from treatments import VARIANTS, SOURCE_SHA, build

DATASET_SHA = '5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993'
CORE_SHA = '3b40a23a7e499e0314f1d6e86b767fba648136758fdd106cdfd0ff27620b545f'
TX_SHA = '0e4828229c323ab029a5dfe49f258a3e2e379aee6b5e18169e72f9edc88652da'
CLOSE_SHA = 'd1f557bd139e3445538e3f94bce90fe296eba19450d939c4160fe0880e067724'
CORE_COLUMNS = ['date','shadow_equity','open_equity','wc_dd','damaged','green',
    'eligible_count','leadership_population','held_count','research_eligible_universe',
    'research_ranking_count','research_ranking_sha256','research_selected_positions_sha256',
    'research_selected_positions']
ECONOMIC_COLUMNS = [x for x in CORE_COLUMNS if x not in ('damaged','green')]


def digest(data): return hashlib.sha256(data).hexdigest()


def frame_hash(frame, columns):
    return digest(frame[columns].to_csv(index=False,float_format='%.17g',na_rep='').encode())


def metrics(frame):
    x=frame.A_nav.astype(float); r=x.pct_change().dropna(); dd=x/x.cummax()-1
    years=(frame.date.iloc[-1]-frame.date.iloc[0]).days/365.2425
    longest=current=0
    for underwater in dd < -1e-12:
        current=current+1 if underwater else 0; longest=max(longest,current)
    return dict(start=str(frame.date.iloc[0].date()),end=str(frame.date.iloc[-1].date()),sessions=len(frame),
        cagr=float((x.iloc[-1]/x.iloc[0])**(1/years)-1),max_drawdown=float(dd.min()),
        ending_multiple=float(x.iloc[-1]/x.iloc[0]),sharpe_daily_252=float(r.mean()/r.std(ddof=1)*np.sqrt(252)),
        longest_underwater_sessions=longest,worst_daily_return=float(r.min()),
        expected_shortfall_5pct=float(r.nsmallest(max(1,int(np.ceil(len(r)*.05)))).mean()),
        allocation_turnover=float(frame.A_allocation.diff().abs().sum()))


def claim_slot(variant):
    if os.environ.get('GITHUB_REPOSITORY') != 'flabber1835/stocker':
        raise RuntimeError('full replay requires the authorized GitHub repository')
    slot=VARIANTS.index(variant)+1
    ref=f'refs/heads/research-budget/simplification-v1/slot-{slot:02d}'
    data=json.dumps({'ref':ref,'sha':os.environ['GITHUB_SHA']}).encode()
    request=urllib.request.Request('https://api.github.com/repos/flabber1835/stocker/git/refs',data=data,method='POST',
        headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json',
                 'Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.urlopen(request,timeout=30) as response:
        if response.status != 201: raise RuntimeError('budget reference not created')
        record=json.load(response)
    return {'slot':slot,'ref':ref,'sha':record['object']['sha'],'run_id':os.environ['GITHUB_RUN_ID']}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--variant',choices=VARIANTS,required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--baseline',type=Path)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    engine=out/'engine';engine.mkdir()
    source=build(args.variant);generated=out/'generated.py';generated.write_text(source)
    from backtester.production_equivalent_economic_overlay import assert_contract,assert_one_session_dividend_lag
    assert_contract(source)
    if assert_one_session_dividend_lag(source)!=1: raise RuntimeError('dividend lag contract')
    manifest=json.loads((Path(os.environ['CANONICAL_PIT_DATASET'])/'manifest.json').read_text())
    if manifest.get('dataset_hash')!=DATASET_SHA: raise RuntimeError('dataset hash mismatch')
    baseline=None
    if args.variant!='baseline':
        if args.baseline is None: raise RuntimeError('treatment requires baseline artifact')
        baseline=json.loads((args.baseline/'RESULT.json').read_text())
        if baseline['status']!='PASS_FRESH_CAUSAL_PIT_REPLAY' or baseline['variant']!='baseline':
            raise RuntimeError('baseline did not pass')
        if baseline['source']['experiment_head']!=os.environ['GITHUB_SHA']: raise RuntimeError('baseline from different head')
    (Path(os.environ['GITHUB_WORKSPACE'])/'final-output').mkdir(exist_ok=True)
    os.environ['RESEARCH_REPLAY_MODE']='fullpit'
    module=types.ModuleType('simplification_'+args.variant);module.__file__=str(generated)
    sys.modules[module.__name__]=module
    exec(compile(source,str(generated),'exec'),module.__dict__)
    if module.MODE!='fullpit' or module.PIT_MODE is not True: raise RuntimeError('full PIT required')
    module.OUT=engine
    identity={'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,
        'oracle_sha256':SOURCE_SHA,'candidate_sha256':digest(source.encode()),'experiment_head':os.environ['GITHUB_SHA'],
        'run_id':os.environ['GITHUB_RUN_ID'],'variant':args.variant}
    (out/'IDENTITY.json').write_text(json.dumps(identity,indent=2)+'\n')
    claim=claim_slot(args.variant)
    (out/'SLOT_CLAIM.json').write_text(json.dumps(claim,indent=2)+'\n')
    print('BACKTEST_SLOT_CLAIMED '+json.dumps(claim),flush=True)
    started=time.monotonic();module.run();elapsed=time.monotonic()-started
    frame=pd.read_csv(engine/'daily.csv',parse_dates=['date'])
    if len(frame)!=5032 or str(frame.date.iloc[0].date())!='2006-07-31' or str(frame.date.iloc[-1].date())!='2026-07-31':
        raise RuntimeError('measurement horizon mismatch')
    if frame.date.duplicated().any() or not frame.date.is_monotonic_increasing: raise RuntimeError('date order failure')
    for col in ['A_nav','shadow_equity','A_allocation']:
        if not np.isfinite(frame[col]).all(): raise RuntimeError('nonfinite tape: '+col)
    if (frame.A_nav<=0).any(): raise RuntimeError('nonpositive NAV')
    summary=json.loads((engine/'summary.json').read_text());telemetry=json.loads((engine/'open-sizing-telemetry.json').read_text())
    if summary.get('canonical_pit_dataset_hash')!=DATASET_SHA or summary.get('financial_grade_dividend_lag_sessions')!=1:
        raise RuntimeError('summary economic identity mismatch')
    if telemetry.get('close_admission_rule_cash_basis')!='TOTAL_CASH' or telemetry.get('fractional_shares_allowed') is not False:
        raise RuntimeError('V5 sizing mismatch')
    if digest((engine/'transactions.csv').read_bytes())!=TX_SHA: raise RuntimeError('Core transactions changed')
    if digest((engine/'close-decisions.csv').read_bytes())!=CLOSE_SHA: raise RuntimeError('Core close decisions changed')
    core_hash=frame_hash(frame,CORE_COLUMNS);economic_hash=frame_hash(frame,ECONOMIC_COLUMNS)
    if args.variant not in ('no_peers','combined') and core_hash!=CORE_SHA: raise RuntimeError('full Core tape changed')
    if baseline and economic_hash!=baseline['core_economic_sha256']: raise RuntimeError('Core economic projection changed')
    allocations=frame.A_allocation.to_numpy()
    if not np.isin(allocations,[0.,.55,.65,1.]).all(): raise RuntimeError('invalid allocation')
    counts={str(x):int((allocations==x).sum()) for x in (0.,.55,.65,1.)}
    transitions=int((frame.A_allocation.diff().abs()>1e-12).sum())
    windows={str(y):metrics(frame.loc[frame.date>=frame.date.iloc[-1]-pd.DateOffset(years=y)]) for y in (5,10,15,20)}
    exact=None
    if args.variant=='baseline':
        if counts!={'0.0':634,'0.55':252,'0.65':20,'1.0':4126} or transitions!=28:
            raise RuntimeError('baseline allocation topology mismatch')
        if summary['candidate_A_episodes']!=8 or summary['candidate_A_concordance_releases']!=2:
            raise RuntimeError('baseline episode topology mismatch')
        for key,value,tol in [('cagr',.215572,.0000005),('max_drawdown',-.273755,.0000005),
                              ('sharpe_daily_252',1.1211,.00005),('ending_multiple',49.6193,.00005)]:
            if abs(windows['20'][key]-value)>tol: raise RuntimeError('baseline rounded published metric mismatch: '+key)
    elif args.variant in ('selective_peers','bounded_counters'):
        bf=pd.read_csv(args.baseline/'engine'/'daily.csv',parse_dates=['date'])
        cols=['date','A_allocation','A_nav','A_reason','native_close_target','effective_native','fast_signal','slow_signal']
        exact=frame_hash(frame,cols)==frame_hash(bf,cols)
        if not exact: raise RuntimeError('exact simplification path diverged')
    result={'schema':'research.v5-ex3-v6-simplification/1','status':'PASS_FRESH_CAUSAL_PIT_REPLAY',
        'variant':args.variant,'experiment_slot':VARIANTS.index(args.variant)+1,'experiment_budget':10,
        'dataset_sha256':DATASET_SHA,'source':identity,'core_economic_sha256':economic_hash,'core_full_sha256':core_hash,
        'transactions_sha256':TX_SHA,'close_decisions_sha256':CLOSE_SHA,'windows':windows,
        'allocation_counts':counts,'transitions':transitions,'exact_simplification_path':exact,
        'elapsed_seconds':elapsed,'peer_stats':summary.get('correlation_peer_stats'),
        'episodes':summary['candidate_A_episodes'],'cross_surface_releases':summary['candidate_A_concordance_releases']}
    (out/'RESULT.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    (out/'SHA256.json').write_text(json.dumps({str(p.relative_to(out)):digest(p.read_bytes())
        for p in sorted(out.rglob('*')) if p.is_file() and p.name!='SHA256.json'},indent=2)+'\n')
    print('SIMPLIFICATION_RESULT '+json.dumps(result,sort_keys=True),flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
            f.write(f"## {args.variant}\n\nReplay and Core invariants passed. Slot {result['experiment_slot']}/10.\n\n")
            f.write('| Window | CAGR | Max DD | Sharpe | Multiple |\n|---|---:|---:|---:|---:|\n')
            for y,w in windows.items():
                f.write(f"| {y}y | {w['cagr']:.4%} | {w['max_drawdown']:.4%} | {w['sharpe_daily_252']:.4f} | {w['ending_multiple']:.4f} |\n")


if __name__=='__main__': main()
