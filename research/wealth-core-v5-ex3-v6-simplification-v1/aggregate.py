"""Preservation screening and documented diagnostics; no additional backtests."""
import argparse
import json
import os
import urllib.request
from pathlib import Path
import numpy as np
import pandas as pd
from treatments import VARIANTS
from run_experiment import metrics

CRISES={'gfc':('2007-07-01','2009-12-31'),'euro_2011':('2011-01-01','2012-12-31'),
        '2015_16':('2015-01-01','2016-12-31'),'covid':('2020-01-01','2020-12-31'),
        '2022':('2022-01-01','2022-12-31'),'2026':('2026-01-01','2026-07-31')}


def screen_window(candidate, baseline):
    dc=candidate['cagr']-baseline['cagr']
    dd=candidate['max_drawdown']-baseline['max_drawdown']
    ratio=candidate['ending_multiple']/baseline['ending_multiple']-1
    ok=abs(dc)<=.0025+1e-12 and dd>=-.01-1e-12 and abs(ratio)<=.05+1e-12
    return {'cagr_delta_pp':dc*100,'max_dd_delta_pp':dd*100,
            'ending_multiple_change_pct':ratio*100,'pass':ok}


def aggregate(root):
    results={};frames={};missing=[];claims=[]
    for v in VARIANTS:
        d=root/f'simplification-{v}'
        if (d/'SLOT_CLAIM.json').exists(): claims.append(json.loads((d/'SLOT_CLAIM.json').read_text()))
        if not (d/'RESULT.json').exists() or not (d/'engine/daily.csv').exists():
            missing.append(v);continue
        result=json.loads((d/'RESULT.json').read_text())
        if result['variant']!=v or result['status']!='PASS_FRESH_CAUSAL_PIT_REPLAY':
            missing.append(v);continue
        results[v]=result;frames[v]=pd.read_csv(d/'engine/daily.csv',parse_dates=['date'])
    report={'status':'COMPLETE' if not missing else 'INCOMPLETE','missing_or_failed':missing,
            'claims_in_artifacts':claims,'results':results,'screening':{},'crisis_diagnostics':{}}
    if 'baseline' not in results: return report
    base=results['baseline']; bf=frames['baseline']
    for v,result in results.items():
        if result['source']['experiment_head']!=base['source']['experiment_head']:
            raise RuntimeError('mixed experiment heads')
        if result['core_economic_sha256']!=base['core_economic_sha256']:
            raise RuntimeError('Core economic projection mismatch')
        if not frames[v].date.equals(bf.date): raise RuntimeError('misaligned daily dates')
        deltas={};passes=True
        for y in ('5','10','15','20'):
            w=result['windows'][y]; b=base['windows'][y]
            deltas[y]=screen_window(w,b)
            passes=passes and deltas[y]['pass']
        f=frames[v];ratio=f.A_nav/bf.A_nav-1
        report['screening'][v]={'verdict':'PASS_PRESERVATION_SCREEN' if passes else 'FAIL_PRESERVATION_SCREEN',
            'window_deltas':deltas,'changed_allocation_sessions':int((abs(f.A_allocation-bf.A_allocation)>1e-12).sum()),
            'maximum_absolute_nav_path_divergence_pct':float(abs(ratio).max()*100),
            'terminal_nav_change_pct':float(ratio.iloc[-1]*100)}
        report['crisis_diagnostics'][v]={}
        for name,(start,end) in CRISES.items():
            mask=(f.date>=start)&(f.date<=end)
            report['crisis_diagnostics'][v][name]=metrics(f.loc[mask])
    return report


def markdown(report):
    run=os.environ.get('GITHUB_RUN_ID','local');sha=os.environ.get('GITHUB_SHA','local')
    lines=['# V5 / EX3 V6 simplification results','',f"Status: **{report['status']}**. [Run {run}](https://github.com/flabber1835/stocker/actions/runs/{run}). Source `{sha}`.",'',
        'Ten replay starts maximum. Slot claims are permanent repository refs under `research-budget/simplification-v1/slot-*`. Failed starts remain charged. Artifact claims below count retained evidence; repository refs are the budget authority.','',
        f"Claims represented in artifacts: {len(report['claims_in_artifacts'])}/10. Missing or failed arms: {', '.join(report['missing_or_failed']) or 'none'}.",'',
        '| Arm | Preservation | 20y CAGR | 20y max DD | 20y multiple | Changed allocation sessions | Max NAV path difference |',
        '|---|---|---:|---:|---:|---:|---:|']
    for v in VARIANTS:
        if v not in report['screening']:
            lines.append(f'| {v} | INCOMPLETE | | | | | |');continue
        r=report['results'][v];s=report['screening'][v];w=r['windows']['20']
        lines.append(f"| {v} | {s['verdict'].replace('_PRESERVATION_SCREEN','')} | {w['cagr']:.4%} | {w['max_drawdown']:.4%} | {w['ending_multiple']:.4f} | {s['changed_allocation_sessions']} | {s['maximum_absolute_nav_path_divergence_pct']:.3f}% |")
    lines+=['','## All-window deltas','',
        'Pass requires every window: absolute CAGR delta <= 0.25 pp/year, drawdown deterioration <= 1 pp, absolute terminal-multiple change <= 5%. Higher returns beyond the symmetric preservation limit fail.','',
        '| Arm | Window | CAGR delta (pp) | Max DD delta (pp; positive improves) | Multiple change | Pass |',
        '|---|---|---:|---:|---:|---|']
    for v,s in report['screening'].items():
        for y,w in s['window_deltas'].items():
            lines.append(f"| {v} | {y}y | {w['cagr_delta_pp']:+.4f} | {w['max_dd_delta_pp']:+.4f} | {w['ending_multiple_change_pct']:+.3f}% | {w['pass']} |")
    lines+=['','Full JSON includes runtime, peer work counts, turnover, tail returns, underwater durations and fixed crisis windows. Per-arm artifacts retain daily tapes, Core parity evidence, generated sources and logs for 90 days. Screening is historical evidence; production implementation and certification require separate review.','']
    return '\n'.join(lines)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--publish',action='store_true');args=ap.parse_args()
    report=aggregate(args.root);args.out.mkdir(parents=True,exist_ok=True)
    (args.out/'SUMMARY.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    text=markdown(report);(args.out/'RESULTS.md').write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write(text)
    if args.publish:
        request=urllib.request.Request('https://api.github.com/repos/flabber1835/stocker/issues/349/comments',
            data=json.dumps({'body':text}).encode(),method='POST',
            headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=30) as response:
            published=json.load(response)
        (args.out/'PUBLISHED.json').write_text(json.dumps({'url':published['html_url']},indent=2)+'\n')
    print(text)


if __name__=='__main__':main()
