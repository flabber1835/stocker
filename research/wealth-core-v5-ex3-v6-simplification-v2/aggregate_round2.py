"""Dual-comparator analysis, permanent source publication and GitHub reporting."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.request
from round2_arms import VARIANTS, SOURCE_SHA, build
from run_round2 import verify_artifact
import aggregate as first_round

REPO='flabber1835/stocker'
BRANCH='research/wealth-core-v5-ex3-v6-simplification-v1'
ORIGINAL_RUN='34436432038'
ORIGINAL_HEAD='f769623e86e949c35a0ddf7dc7df29744c298eae'
ORIGINAL_SOURCE='335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d'


def api(path, data=None, method=None):
    req=urllib.request.Request('https://api.github.com/repos/'+REPO+path,
        data=None if data is None else json.dumps(data).encode(),method=method,
        headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json',
                 'Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.urlopen(req,timeout=60) as response:return json.load(response)


def verify_completed(root):
    for v in VARIANTS:
        p=root/f'simplification-{v}'
        if not (p/'RESULT.json').exists():continue
        r=json.loads((p/'RESULT.json').read_text())
        if r['status']!='PASS_FRESH_CAUSAL_PIT_REPLAY' or r['variant']!=v:raise RuntimeError('arm result mismatch')
        if r['source']['experiment_head']!=os.environ['GITHUB_SHA'] or str(r['source']['run_id'])!=os.environ['GITHUB_RUN_ID']:
            raise RuntimeError('arm provenance mismatch')
        checks=json.loads((p/'SHA256.json').read_text())
        for relative,sha in checks.items():
            file=(p/relative).resolve()
            if not file.is_relative_to(p.resolve()):raise RuntimeError('invalid checksum path')
            if hashlib.sha256(file.read_bytes()).hexdigest()!=sha:raise RuntimeError('arm evidence checksum mismatch')
        for relative in ('RESULT.json','engine/daily.csv','generated.py','SLOT_CLAIM.json'):
            if relative not in checks:raise RuntimeError('required evidence checksum missing')
        if (p/'generated.py').read_text()!=build(v):raise RuntimeError('generated arm source mismatch')
        claim=json.loads((p/'SLOT_CLAIM.json').read_text())
        expected=f'refs/heads/research-budget/simplification-v2/slot-{VARIANTS.index(v)+1:02d}'
        if claim['ref']!=expected or claim['sha']!=os.environ['GITHUB_SHA']:raise RuntimeError('slot claim mismatch')


def publish_files(out):
    run=os.environ['GITHUB_RUN_ID'];attempt=os.environ.get('GITHUB_RUN_ATTEMPT','1')
    prefix=f'research/wealth-core-v5-ex3-v6-simplification-v2/results/{run}-{attempt}'
    parent=api('/git/ref/heads/'+BRANCH)['object']['sha']
    tree=api('/git/commits/'+parent)['tree']['sha']
    elements=[{'path':prefix+'/'+str(p.relative_to(out)),'mode':'100644','type':'blob','content':p.read_text()}
              for p in sorted(out.rglob('*')) if p.is_file()]
    newtree=api('/git/trees',{'base_tree':tree,'tree':elements},'POST')['sha']
    commit=api('/git/commits',{'message':f'research: preserve round-2 results and strategy sources ({run}-{attempt})',
                            'tree':newtree,'parents':[parent]},'POST')['sha']
    api('/git/refs/heads/'+BRANCH,{'sha':commit,'force':False},'PATCH')
    return {'commit':commit,'directory_url':f'https://github.com/{REPO}/tree/{commit}/{prefix}'}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True)
    ap.add_argument('--original',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--publish',action='store_true');args=ap.parse_args()
    verify_completed(args.root)
    original=verify_artifact(args.original,'baseline',ORIGINAL_RUN,ORIGINAL_HEAD,ORIGINAL_SOURCE)
    first_round.VARIANTS=VARIANTS
    report=first_round.aggregate(args.root)
    report['original_baseline']=original
    report['comparison_reference']='Stored simplified candidate, freshly qualified in slot 1'
    report['original_screening']={}
    for v,r in report['results'].items():
        deltas={y:first_round.screen_window(r['windows'][y],original['windows'][y]) for y in ('5','10','15','20')}
        report['original_screening'][v]={'verdict':'PASS_PRESERVATION_SCREEN' if all(x['pass'] for x in deltas.values()) else 'FAIL_PRESERVATION_SCREEN','window_deltas':deltas}
    body=first_round.markdown(report).replace('# V5 / EX3 V6 simplification results','# Simplification round 2 results',1)
    body=body.replace('research-budget/simplification-v1/slot-*','research-budget/simplification-v2/slot-*')
    body=body.replace('## All-window deltas','## All-window deltas against the simplified candidate',1)
    body += '\n## Original V5/V6 comparison\n\nThe table above screens against the simplified candidate. Original-strategy preservation is reported separately below. The stored candidate already exceeds the original symmetric CAGR tolerance. Both criteria retain their preregistered thresholds.\n\n'
    body += '| Arm | Simplified-candidate screen | Original V5/V6 screen |\n|---|---|---|\n'
    for v in VARIANTS:
        current=report['screening'].get(v,{}).get('verdict','INCOMPLETE')
        old=report['original_screening'].get(v,{}).get('verdict','INCOMPLETE')
        body+=f'| {v} | {current} | {old} |\n'
    body+='\nComplete original-comparator window deltas are retained in SUMMARY.json.\n\n## Stored generated source\n\n'
    args.out.mkdir(parents=True,exist_ok=True);(args.out/'sources').mkdir(exist_ok=True)
    source_manifest={}
    for v in VARIANTS:
        generated=args.root/f'simplification-{v}'/'generated.py'
        if generated.exists():
            source=generated.read_text()
            if source!=build(v):raise RuntimeError('source snapshot differs from preregistration')
            (args.out/'sources'/f'{v}.py').write_text(source)
            source_manifest[v]={'sha256':hashlib.sha256(source.encode()).hexdigest(),
                                'completed':v in report['results']}
            body+=f'- [{v}](sources/{v}.py)\n'
    manifest={'run_id':os.environ['GITHUB_RUN_ID'],'attempt':os.environ.get('GITHUB_RUN_ATTEMPT','1'),
              'source_head':os.environ['GITHUB_SHA'],'reference_source_sha256':SOURCE_SHA,
              'round_budget':10,'sources':source_manifest}
    (args.out/'SOURCE_MANIFEST.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    (args.out/'SUMMARY.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    (args.out/'RESULTS.md').write_text(body)
    if args.publish:
        published=publish_files(args.out)
        body=body.replace('](sources/',']('+published['directory_url'].replace('/tree/','/blob/')+'/sources/')
        body+='\nPermanent report and all available generated strategies: [saved evidence]('+published['directory_url']+').\n'
        response=api('/issues/349/comments',{'body':body},'POST')
        published['comment_url']=response['html_url']
        (args.out/'PUBLISHED.json').write_text(json.dumps(published,indent=2)+'\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write(body)
    print(body)


if __name__=='__main__':main()
