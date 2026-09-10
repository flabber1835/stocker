import argparse
import json
import os
import urllib.request
from pathlib import Path
import pandas as pd
from aggregate import screen_window, CRISES
from run_experiment import metrics
from candidate_followup import verify_baseline, BASELINE_RUN, BASELINE_HEAD


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--candidate',type=Path,required=True)
    ap.add_argument('--baseline',type=Path,required=True);ap.add_argument('--publish',action='store_true')
    args=ap.parse_args();out=args.candidate;out.mkdir(parents=True,exist_ok=True)
    run=os.environ.get('GITHUB_RUN_ID','local')
    lines=['# Combined simplification candidate','',f'[Follow-up run {run}](https://github.com/flabber1835/stocker/actions/runs/{run}). One additional replay authorized.','']
    report={'status':'INCOMPLETE','baseline_run':BASELINE_RUN,'baseline_head':BASELINE_HEAD,
            'candidate_head':os.environ.get('GITHUB_SHA'),'run_id':run,'additional_budget':1}
    if (out/'RESULT.json').exists():
        r=json.loads((out/'RESULT.json').read_text());b=verify_baseline(args.baseline)
        if r['variant']!='candidate' or r['status']!='PASS_FRESH_CAUSAL_PIT_REPLAY':raise RuntimeError('invalid candidate result')
        if r['source']['experiment_head']!=os.environ['GITHUB_SHA']:raise RuntimeError('candidate head mismatch')
        cf=pd.read_csv(out/'engine/daily.csv',parse_dates=['date'])
        bf=pd.read_csv(args.baseline/'engine/daily.csv',parse_dates=['date'])
        if not cf.date.equals(bf.date):raise RuntimeError('tape dates differ')
        if r['core_economic_sha256']!=b['core_economic_sha256']:raise RuntimeError('Core parity failed')
        if not cf.A_allocation.isin([0.,.55,1.]).all():raise RuntimeError('candidate has unexpected exposure level')
        deltas={y:screen_window(r['windows'][y],b['windows'][y]) for y in ('5','10','15','20')}
        verdict='PASS_PRESERVATION_SCREEN' if all(d['pass'] for d in deltas.values()) else 'FAIL_PRESERVATION_SCREEN'
        report.update(status='COMPLETE',verdict=verdict,baseline=b,candidate=r,window_deltas=deltas,
            changed_allocation_sessions=int(((cf.A_allocation-bf.A_allocation).abs()>1e-12).sum()),
            maximum_absolute_nav_path_difference_pct=float((cf.A_nav/bf.A_nav-1).abs().max()*100),
            crisis_diagnostics={name:{'candidate':metrics(cf.loc[(cf.date>=start)&(cf.date<=end)]),
                                     'baseline':metrics(bf.loc[(bf.date>=start)&(bf.date<=end)])}
                                for name,(start,end) in CRISES.items()})
        lines += [f'**{verdict}**. Core economic projection, transactions and close decisions match the verified baseline.','',
            '| Window | Baseline CAGR | Candidate CAGR | Baseline max DD | Candidate max DD | Multiple change | Pass |',
            '|---|---:|---:|---:|---:|---:|---|']
        for y,d in deltas.items():
            bw=b['windows'][y];cw=r['windows'][y]
            lines.append(f"| {y}y | {bw['cagr']:.4%} | {cw['cagr']:.4%} | {bw['max_drawdown']:.4%} | {cw['max_drawdown']:.4%} | {d['ending_multiple_change_pct']:+.3f}% | {d['pass']} |")
        lines += ['',f"Changed allocation sessions: {report['changed_allocation_sessions']}. Maximum absolute NAV path difference: {report['maximum_absolute_nav_path_difference_pct']:.3f}%.",
            f"20y multiple: {r['windows']['20']['ending_multiple']:.4f}x. Allocation transitions: {r['transitions']} (baseline {b['transitions']}).",
            f"Peer pair calculations: {r['peer_stats']['pair_correlations']:,} (baseline {b['peer_stats']['pair_correlations']:,})."]
    else:lines+=['**INCOMPLETE**. Candidate evidence is missing. Inspect the replay log and slot claim.']
    lines+=['','Candidate: selective peers + bounded counters + one-stage 55%-to-100% recovery after ten healthy closes + removal of SPY rebound release. Cross-surface recovery retained.',
        '', 'Acceptance in every 5/10/15/20y window: absolute CAGR delta <= 0.25 pp/year, drawdown deterioration <= 1 pp, absolute multiple change <= 5%. Detailed JSON includes tail returns, underwater periods, turnover and crisis diagnostics. Historical screening precedes a separately reviewed production implementation.','']
    body='\n'.join(lines)
    (out/'FOLLOWUP_SUMMARY.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    (out/'FOLLOWUP_RESULTS.md').write_text(body)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write(body)
    if args.publish:
        req=urllib.request.Request('https://api.github.com/repos/flabber1835/stocker/issues/349/comments',
            data=json.dumps({'body':body}).encode(),method='POST',
            headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=30) as response:published=json.load(response)
        (out/'PUBLISHED.json').write_text(json.dumps({'url':published['html_url']})+'\n')
    print(body)


if __name__=='__main__':main()
