"""Publish measured headlines and reusable tapes through atomic Git commits."""
import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.request

import numpy as np
import pandas as pd

import variants as v

BRANCH='research/wealth-core-v5-ex3-v6-simplification-v1'
REPO='flabber1835/stocker'
CASES=('baseline','loo_0','loo_1','loo_2','drop_29','drop_47','drop_83')


def api(path,data=None,method=None):
    body=None if data is None else json.dumps(data).encode()
    request=urllib.request.Request('https://api.github.com/repos/'+REPO+path,data=body,
        method=method or ('GET' if data is None else 'POST'),headers={
            'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json',
            'X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=60) as response:
        return json.load(response)


def preservation(candidate,baseline):
    windows={}
    for year,m in candidate.items():
        b=baseline[year]
        cagr=m['cagr']-b['cagr']; dd=m['max_drawdown']-b['max_drawdown']
        wealth=m['ending_multiple']/b['ending_multiple']-1
        windows[year]={'cagr_delta_pp':100*cagr,'drawdown_delta_pp':100*dd,
                       'wealth_delta_pct':100*wealth,
                       'pass':abs(cagr)<=.0025+1e-12 and dd>=-.01-1e-12 and abs(wealth)<=.05+1e-12}
    return {'pass':all(x['pass'] for x in windows.values()),'windows':windows}


def divergence(baseline,fault,name):
    assert np.array_equal(baseline.date.to_numpy(),fault.date.to_numpy())
    delta=np.abs(fault[name+'_allocation'].to_numpy(float)-baseline[name+'_allocation'].to_numpy(float))
    assert np.isfinite(delta).all()
    indices=np.flatnonzero(delta>1e-12)
    return {'absolute_area':float(delta.sum()),'different_sessions':int(len(indices)),
            'first':None if not len(indices) else str(fault.date.iloc[indices[0]].date()),
            'last':None if not len(indices) else str(fault.date.iloc[indices[-1]].date()),
            'terminal_equal':bool(delta[-1]<=1e-12),
            'terminal_equal_tail_sessions':len(delta) if not len(indices) else int(len(delta)-1-indices[-1])}


def build_report(root,out):
    out.mkdir(parents=True,exist_ok=True)
    folders={}; results={}; frames={}; receipts=[]
    for path in root.rglob('SLOT.json'):
        receipt=json.loads(path.read_text()); case=receipt['case']
        assert case in CASES and case not in folders, 'duplicate/unknown case'
        folders[case]=path.parent; receipts.append(receipt)
    assert len({x['slot'] for x in receipts})==len(receipts)<=7
    for case,folder in folders.items():
        target=out/'cases'/case; target.mkdir(parents=True,exist_ok=True)
        for filename in ('SLOT.json','PROVENANCE.json','RESULT.json','CORE_RESULT.json',
                         'FAULT_SELECTION.json','PEER_CHECKS.json','SHA256.json'):
            if (folder/filename).exists(): shutil.copyfile(folder/filename,target/filename)
        for name,options in {
            'observations.csv':['observations.csv','core/engine/ablation-observations.csv'],
            'daily-tracks.csv':['daily-tracks.csv'],
            'engine-daily.csv':['core/engine/daily.csv']}.items():
            source=next((folder/p for p in options if (folder/p).exists()),None)
            if source: (target/(name+'.gz')).write_bytes(gzip.compress(source.read_bytes(),mtime=0))
        if (folder/'RESULT.json').exists():
            result=json.loads((folder/'RESULT.json').read_text())
            assert result['status']=='PASS' and result['case']==case
            checks=json.loads((folder/'SHA256.json').read_text())
            for filename in ('RESULT.json','daily-tracks.csv','observations.csv','SLOT.json'):
                assert hashlib.sha256((folder/filename).read_bytes()).hexdigest()==checks[filename]
            results[case]=result
            frames[case]=pd.read_csv(folder/'daily-tracks.csv',parse_dates=['date'],float_precision='round_trip')
    if 'baseline' in results:
        baseline=results['baseline']; baselines=baseline['tracks']
    else:
        baseline=None; baselines={}
    fault_results={}; robustness={}; preservation_results={}
    if baseline:
        for case,result in results.items():
            if case=='baseline': continue
            fault_results[case]={}
            for name in v.TRACKS:
                m=result['tracks'][name]['metrics']['20']; b=baselines[name]['metrics']['20']
                fault_results[case][name]={**divergence(frames['baseline'],frames[case],name),
                    'headline':m,'cagr_delta_pp':100*(m['cagr']-b['cagr']),
                    'drawdown_delta_pp':100*(m['max_drawdown']-b['max_drawdown']),
                    'wealth_delta_pct':100*(m['ending_multiple']/b['ending_multiple']-1)}
        for name in v.TRACKS:
            preservation_results[name]={parent:preservation(baselines[name]['metrics'],baselines[parent]['metrics'])
                                        for parent in ('original','simplified')}
            robustness[name]={}
            for parent in ('original','simplified'):
                reductions=[1-f[name]['absolute_area']/f[parent]['absolute_area']
                            for f in fault_results.values() if f[parent]['absolute_area']>1e-12]
                zero_regressions=[case for case,f in fault_results.items()
                                  if f[parent]['absolute_area']<=1e-12 and f[name]['absolute_area']>1e-12]
                rows=[f[name] for f in fault_results.values()]
                median=None if not reductions else float(np.median(reductions))
                baseline_loss=baselines[parent]['metrics']['20']['cagr']-baselines[name]['metrics']['20']['cagr']
                complete=len(fault_results)==6
                robustness[name][parent]={
                    'fault_cases_completed':len(rows),'comparator_affected_cases':len(reductions),
                    'median_individual_area_reduction':median,'new_divergences_on_zero_comparator':zero_regressions,
                    'baseline_cagr_loss_pp':100*baseline_loss,
                    'formal_screen':None if not complete or median is None else median>=.5 and baseline_loss<=.01,
                    'terminal_equal_cases':sum(r['terminal_equal'] for r in rows),
                    'median_abs_cagr_delta_pp':None if not rows else float(np.median([abs(r['cagr_delta_pp']) for r in rows])),
                    'worst_abs_cagr_delta_pp':None if not rows else max(abs(r['cagr_delta_pp']) for r in rows),
                    'median_abs_drawdown_delta_pp':None if not rows else float(np.median([abs(r['drawdown_delta_pp']) for r in rows])),
                    'worst_abs_drawdown_delta_pp':None if not rows else max(abs(r['drawdown_delta_pp']) for r in rows)}
    report={'status':'COMPLETE' if len(results)==7 else 'INCOMPLETE','completed_cases':list(results),
            'missing_cases':[case for case in CASES if case not in results],
            'claimed_slots':receipts,'slot_ceiling':7,'run_id':os.environ['GITHUB_RUN_ID'],
            'experiment_head':os.environ['GITHUB_SHA'],'baseline_tracks':baselines,
            'economic_preservation':preservation_results,'fault_results':fault_results,'robustness':robustness,
            'prior_campaign_cases_pooled':False,'production_promotion_authorized':False}
    (out/'SUMMARY.json').write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
    lines=['# Ramp removal follow-up results','',f"Status: **{report['status']}**; {len(results)}/7 Core cases complete; {len(receipts)}/7 slots claimed.",'',
           'Measurement: 2006-07-31 to 2026-07-31, 5,032 sessions. Ending wealth is a multiple of starting wealth.','',
           '| Strategy experiment | CAGR | Max drawdown | Sharpe | Ending wealth | Preservation vs original / simplified |',
           '|---|---:|---:|---:|---:|---|']
    for name,t in baselines.items():
        m=t['metrics']['20']; gates=preservation_results[name]
        gate=' / '.join('PASS' if gates[p]['pass'] else 'FAIL' for p in ('original','simplified'))
        lines.append(f"| {name} | {m['cagr']:.2%} | {m['max_drawdown']:.2%} | {m['sharpe_daily_252']:.3f} | {m['ending_multiple']:.4f}x | {gate} |")
    lines+=['','## Each perturbation and strategy','',
            'Allocation area is the sum of absolute allocation differences from that strategy’s own baseline. Economic deltas also use its own baseline.','',
            '| Fault | Strategy | CAGR | Max DD | Sharpe | Wealth | Area | Different sessions | CAGR delta pp |',
            '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for case,fault in fault_results.items():
        for name,r in fault.items():
            m=r['headline']
            lines.append(f"| {case} | {name} | {m['cagr']:.2%} | {m['max_drawdown']:.2%} | {m['sharpe_daily_252']:.3f} | {m['ending_multiple']:.4f}x | {r['absolute_area']:.2f} | {r['different_sessions']} | {r['cagr_delta_pp']:+.3f} |")
    lines+=['','## Robustness versus original','',
            '| Strategy | Median area reduction | Affected comparator cases | Worst abs CAGR fault delta pp | Formal screen |',
            '|---|---:|---:|---:|---|']
    for name,comparisons in robustness.items():
        r=comparisons['original']; med=r['median_individual_area_reduction']; tail=r['worst_abs_cagr_delta_pp']
        screen='PENDING' if r['formal_screen'] is None else ('PASS' if r['formal_screen'] else 'FAIL')
        lines.append(f"| {name} | {'—' if med is None else format(med,'.1%')} | {r['comparator_affected_cases']} | {'—' if tail is None else format(tail,'.3f')} | {screen} |")
    lines+=['','The formal robustness gate requires at least 50% median individual fault-area reduction and no more than 1pp baseline CAGR loss. Economic preservation is a separate four-window gate. Exact compact/reference and restart comparisons are recorded per case.',
            '', 'These six new faults extend the earlier hardening study on the same historical dataset. Prior cases are not pooled. No production promotion or merge follows from this report.','']
    (out/'SUMMARY.md').write_text('\n'.join(lines))
    (out/'SHA256.json').write_text(json.dumps({str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
                                            for p in sorted(out.rglob('*')) if p.is_file() and p.name!='SHA256.json'},indent=2,sort_keys=True)+'\n')
    return report


def publish(out,report):
    run=os.environ['GITHUB_RUN_ID']; attempt=os.environ['GITHUB_RUN_ATTEMPT']
    prefix=f'research/{v.HERE.name}/results/{run}-{attempt}'
    head=api('/git/ref/heads/'+BRANCH)['object']['sha']
    tree=api('/git/commits/'+head)['tree']['sha']
    entries=[]
    for path in sorted(out.rglob('*')):
        if not path.is_file(): continue
        entry={'path':prefix+'/'+str(path.relative_to(out)),'mode':'100644','type':'blob'}
        if path.suffix=='.gz':
            entry['sha']=api('/git/blobs',{'encoding':'base64','content':base64.b64encode(path.read_bytes()).decode()})['sha']
        else: entry['content']=path.read_text()
        entries.append(entry)
    newtree=api('/git/trees',{'base_tree':tree,'tree':entries})['sha']
    commit=api('/git/commits',{'message':f"Document ramp follow-up {len(report['completed_cases'])}/7 results ({run})",
                             'tree':newtree,'parents':[head]})['sha']
    api('/git/refs/heads/'+BRANCH,{'sha':commit,'force':False},'PATCH')
    assert api('/git/ref/heads/'+BRANCH)['object']['sha']==commit
    url=f'https://github.com/{REPO}/blob/{commit}/{prefix}/SUMMARY.md'
    message=f"Ramp follow-up: **{len(report['completed_cases'])}/7 cases complete**, {len(report['claimed_slots'])}/7 slots claimed. [All measured headlines, per-fault results and checks]({url}). Sources and reusable tapes are stored on this research branch. No promotion/merge."
    api('/issues/349/comments',{'body':message})
    print(json.dumps({'published_commit':commit,'summary_url':url,'status':report['status']}),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--root',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True); ap.add_argument('--publish',action='store_true')
    args=ap.parse_args(); report=build_report(args.root,args.out)
    print((args.out/'SUMMARY.md').read_text(),flush=True)
    if args.publish: publish(args.out,report)
