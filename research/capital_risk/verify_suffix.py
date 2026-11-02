"""Offline pre/post suffix qualification of the actual fresh canonical book."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.pooled_vacancy_funding import backtest,runtime,repair
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
    for descriptor in saved['repairs']:
        value=repair.load_repair(root/'repairs'/descriptor['filename'],resume_session=descriptor['resume_session'],
            predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'])
        require(value.sha256==descriptor['sha256'] and descriptor['filename']==value.sha256+'.json',
                'REFUSED_RETAINED_REPAIR_BINDING')
    journal=Journal(root,resume=True)
    try: journal.verify(saved['journals'])
    finally: journal.close()


def review(actual,expected,request,phase):
    validate_request(request);p=request['predecessor']
    before={f.name:backtest.file_sha(f) for f in actual.glob('*.jsonl')}
    saved=read_checkpoint(actual/'checkpoint.json.gz')
    base=saved['base'];full=bundle.axis();axis=full[full.index(backtest.START)-425:]
    parent=read_checkpoint(actual.parent/'lineage/checkpoints'/(p['outer_sha256']+'.json.gz'))
    require((parent['sha256'],parent['run']['checkpoint_sha256'],parent['run']['state_sha256'],
             parent['run']['input_sha256'],backtest.hash_value(parent['base']))==
            (p['outer_sha256'],p['inner_sha256'],p['state_sha256'],p['input_sha256'],p['base_sha256']),
            'REFUSED_SUFFIX_PREDECESSOR_BINDING')
    require(parent['source_cursor']==p['session'] and parent['completed']==p.get('measured_closes',0)
            and len(parent['repairs'])==p.get('repair_count',0),
            'REFUSED_SUFFIX_PREDECESSOR_AXIS')
    validate_saved(parent,actual,base,axis)
    if phase=='preflight':
        require(saved==parent,'REFUSED_PRE_RESUME_FINANCIAL_CHANGE')
        count,day=p['formation_records'],p['session']
        measured,repairs,input_sha=p.get('measured_closes',0),p.get('repair_count',0),p['input_sha256']
    else:
        count,day=request['target_formation_records'],request['target_session']
        measured,repairs=request.get('target_measured_closes',0),request.get('expected_repair_count',0)
        input_sha=request.get('expected_input_sha256',p['input_sha256'])
    require(saved['completed']==measured and len(saved['repairs'])==repairs
            and saved['run']['input_sha256']==input_sha,'REFUSED_SUFFIX_PHASE_OR_REPAIR')
    require(saved['source_cursor']==day,'REFUSED_SUFFIX_FINAL_CURSOR')
    prefix_sha=compare_prefix(actual/'formation.jsonl',expected/'formation.jsonl',count)
    daily_sha=compare_prefix(actual/'daily.jsonl',expected/'daily.jsonl',measured,phase='MEASURED')
    retained=sorted(actual.parent.rglob('*.json.gz'))
    for path in retained: validate_saved(read_checkpoint(path),actual,base,axis)
    for name,c in saved['journals'].items():
        require((actual/(name+'.jsonl')).stat().st_size==c['bytes'],'REFUSED_SUFFIX_TAIL')
    require(before=={f.name:backtest.file_sha(f) for f in actual.glob('*.jsonl')},'REFUSED_SUFFIX_REVIEW_MUTATION')
    dade=None
    if phase=='postflight' and 'repair' in request:
        events=[e for e in saved['run']['state']['ledger']['events'] if e.get('ticker')=='DADE' and e['event_type']=='CASH_MERGER']
        require(len(events)==1 and events[0]['session']=='2007-11-06' and events[0]['cash_delta']==2541
                and events[0]['price']==77 and events[0]['shares_delta']==-33,'REFUSED_DADE_ACTUAL_PAYMENT')
        core=saved['run']['state']['wealth_core']
        require(not any(e['security_id']=='262420210501636253' for e in core['episodes'].values())
                and '262420210501636253' not in core['terminal_pending_terms']
                and not any(o['security_id']=='262420210501636253' for o in saved['run']['state']['pending']),
                'REFUSED_DADE_RESIDUAL_OR_PENDING')
        dade=dict(actual_payments=1,cash_delta=2541,position_removed=True,pending_removed=True)
    return dict(schema='research.capital-risk-suffix-review/1',status='SUFFIX_'+phase.upper()+'_PASSED',
        formation_records=count,measured_closes=measured,session=day,checkpoint_sha256=saved['sha256'],
        inner_sha256=saved['run']['checkpoint_sha256'],state_sha256=saved['run']['state_sha256'],
        exact_records_sha256=prefix_sha,exact_daily_sha256=daily_sha,historical_checkpoints_verified=len(retained),
        all_journal_prefixes_verified=True,tails=0,canonical_roundtrip=True,
        predecessor_preserved=True,dade_replay=dade,retained_repairs=len(saved['repairs']),full_baseline_gate_satisfied=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('actual','expected','request','output'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--phase',required=True,choices=['preflight','postflight']);args=parser.parse_args()
    result=review(args.actual,args.expected,json.loads(args.request.read_bytes()),args.phase)
    args.output.write_text(json.dumps(result,indent=2)+'\n');print(result['status'])
