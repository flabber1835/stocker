"""Offline pre/post suffix qualification of the actual fresh canonical book."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.pooled_vacancy_funding import backtest,runtime
from research.pooled_vacancy_funding.journal import Journal,read_checkpoint
from research.pooled_input_support import bundle
from suffix_contract import validate_request
from verify_prefix import compare_prefix,require,POLICY


def validate_saved(saved,root,base,axis):
    backtest.validate_checkpoint(saved,base,axis)
    require(saved['base']['sources']==backtest.source_files(),'REFUSED_SUFFIX_FROZEN_SOURCES')
    restored=runtime.restore(saved['run'],policy=POLICY,
        input_sha256=backtest.input_hash(base,saved['repairs']))
    require(runtime.checkpoint(restored)==saved['run'],'REFUSED_SUFFIX_ROUNDTRIP')
    journal=Journal(root,resume=True)
    try: journal.verify(saved['journals'])
    finally: journal.close()


def review(actual,expected,request,phase):
    validate_request(request);p=request['predecessor']
    before={f.name:backtest.file_sha(f) for f in actual.glob('*.jsonl')}
    saved=read_checkpoint(actual/'checkpoint.json.gz')
    base=saved['base'];full=bundle.axis();axis=full[full.index(backtest.START)-425:]
    parent=read_checkpoint(actual.parent/'lineage/predecessor-checkpoint.json.gz')
    require((parent['sha256'],parent['run']['checkpoint_sha256'],parent['run']['state_sha256'],
             parent['run']['input_sha256'],backtest.hash_value(parent['base']))==
            (p['outer_sha256'],p['inner_sha256'],p['state_sha256'],p['input_sha256'],p['base_sha256']),
            'REFUSED_SUFFIX_PREDECESSOR_BINDING')
    require(parent['source_cursor']==p['session'] and parent['completed']==0 and parent['repairs']==[],
            'REFUSED_SUFFIX_PREDECESSOR_AXIS')
    validate_saved(parent,actual,base,axis)
    require(saved['completed']==0 and saved['repairs']==[],'REFUSED_SUFFIX_PHASE_OR_REPAIR')
    if phase=='preflight':
        require(saved==parent,'REFUSED_PRE_RESUME_FINANCIAL_CHANGE')
        count,day=p['formation_records'],p['session']
    else:
        count,day=request['target_formation_records'],request['target_session']
    require(saved['source_cursor']==day,'REFUSED_SUFFIX_FINAL_CURSOR')
    prefix_sha=compare_prefix(actual/'formation.jsonl',expected/'formation.jsonl',count)
    retained=sorted(actual.parent.rglob('*.json.gz'))
    for path in retained: validate_saved(read_checkpoint(path),actual,base,axis)
    for name,c in saved['journals'].items():
        require((actual/(name+'.jsonl')).stat().st_size==c['bytes'],'REFUSED_SUFFIX_TAIL')
    require(before=={f.name:backtest.file_sha(f) for f in actual.glob('*.jsonl')},'REFUSED_SUFFIX_REVIEW_MUTATION')
    return dict(schema='research.capital-risk-suffix-review/1',status='SUFFIX_'+phase.upper()+'_PASSED',
        formation_records=count,measured_closes=0,session=day,checkpoint_sha256=saved['sha256'],
        inner_sha256=saved['run']['checkpoint_sha256'],state_sha256=saved['run']['state_sha256'],
        exact_records_sha256=prefix_sha,historical_checkpoints_verified=len(retained),
        all_journal_prefixes_verified=True,tails=0,canonical_roundtrip=True,
        predecessor_preserved=True,full_baseline_gate_satisfied=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('actual','expected','request','output'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--phase',required=True,choices=['preflight','postflight']);args=parser.parse_args()
    result=review(args.actual,args.expected,json.loads(args.request.read_bytes()),args.phase)
    args.output.write_text(json.dumps(result,indent=2)+'\n');print(result['status'])
