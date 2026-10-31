"""Exact warmup source succession; canonical operations run only inside hosted fences."""
from __future__ import annotations

import argparse
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import shutil

COUNTER='research/pooled_vacancy_funding/retries.py'
IDENTITY='research_implementation_sha256'


def require(value,code):
    if not value:raise ValueError(code)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',', ':'),allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind_checkpoint(saved,spec,path):
    expected=dict(file_sha256=sha(path),outer_sha256=saved['sha256'],
        inner_sha256=saved['run']['checkpoint_sha256'],state_sha256=saved['run']['state_sha256'],
        input_sha256=saved['run']['input_sha256'],base_sha256=digest(saved['base']),
        sources_sha256=digest(saved['base']['sources']),source_cursor=saved['source_cursor'])
    require(expected==spec,'REFUSED_EXACT_WARMUP_PREDECESSOR')
    require(saved['sha256']==digest({k:v for k,v in saved.items() if k!='sha256'}),'REFUSED_PREDECESSOR_OUTER')
    require(saved['run']['state_sha256']==digest(saved['run']['state']),'REFUSED_PREDECESSOR_STATE')
    require(saved['run']['checkpoint_sha256']==digest({k:v for k,v in saved['run'].items() if k!='checkpoint_sha256'}),
        'REFUSED_PREDECESSOR_INNER')
    require(saved['completed']==0 and saved['stats'] is None and saved['spy_base'] is None and not saved['repairs'],
        'REFUSED_NOT_INITIAL_WARMUP')
    require(saved['retries']['transitions']==0 and saved['retries']['last_session'] is None,'REFUSED_COMMITTED_FORMATION')
    require(all(v['bytes']==0 for v in saved['journals'].values()),'REFUSED_NONEMPTY_ORIGIN_PREFIX')


def unchanged_financial_state(before,after):
    require({k:v for k,v in before.items() if k!='strategy_identity'}==
            {k:v for k,v in after.items() if k!='strategy_identity'},'REFUSED_FINANCIAL_STATE_MUTATION')
    a,b=before['strategy_identity'],after['strategy_identity']
    require({k for k in set(a)|set(b) if a.get(k)!=b.get(k)}=={IDENTITY},'REFUSED_NONDIAGNOSTIC_IDENTITY_CHANGE')


def successor_base(old,current_sources):
    changed={k for k in set(old['sources'])|set(current_sources) if old['sources'].get(k)!=current_sources.get(k)}
    require(changed=={COUNTER},'REFUSED_NONDIAGNOSTIC_SOURCE_CHANGE')
    return {**old,'sources':current_sources}


def selected_axis(backtest,axis):
    full=axis();return full[full.index(backtest.START)-425:full.index(backtest.END)+1]


def inventory(root):
    return {p.relative_to(root).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p))
        for p in sorted(root.rglob('*')) if p.is_file()}


def preflight(root,spec,output):
    from research.pooled_vacancy_funding import backtest,runtime
    from research.pooled_vacancy_funding.journal import Journal,read_checkpoint
    from research.pooled_input_support.bundle import axis
    before=inventory(root);saved=read_checkpoint(root/'checkpoint.json.gz')
    bind_checkpoint(saved,spec,root/'checkpoint.json.gz')
    require(saved['base']['sources']==backtest.source_files(),'REFUSED_OLD_SOURCE_BYTES')
    selected=selected_axis(backtest,axis)
    require(saved['source_cursor']==selected[298],'REFUSED_WARMUP_AXIS')
    manifest=json.loads(Path('/frozen/bundle/manifest.json').read_bytes())
    require(saved['base']['bundle_sha256']==manifest['bundle_commitment_sha256']
        and saved['base']['archive_sha256']==manifest['base_archive']['sha256']
        and saved['base']['start']==backtest.START and saved['base']['end']==backtest.END
        and saved['base']['capital']=='50000' and saved['base']['policy']=='wealth-core-v5-zero-share-fixed-2008-v1',
        'REFUSED_WARMUP_INPUT_BASE')
    _,_,comparisons=backtest.comparisons(Path('/frozen/references/owned55'),
        Path('/frozen/references/compact/champion-daily.csv'),selected[425:])
    require(saved['base']['comparison_files']==comparisons,'REFUSED_WARMUP_REFERENCE_BYTES')
    backtest.validate_checkpoint(saved,saved['base'],selected)
    restored=runtime.restore(saved['run'],policy=saved['base']['policy'],input_sha256=saved['run']['input_sha256'])
    require(runtime.checkpoint(restored)==saved['run'],'REFUSED_OLD_CANONICAL_ROUNDTRIP')
    journal=Journal(root,resume=True)
    try:journal.verify(saved['journals'])
    finally:journal.close()
    tails={}
    for name,commitment in saved['journals'].items():
        raw=(root/(name+'.jsonl')).read_bytes()[commitment['bytes']:]
        tails[name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    failure=root/'failed-canonical-state.json.gz'
    require(failure.is_file(),'REFUSED_MISSING_UNSENT_CANONICAL_STATE')
    value=json.loads(gzip.decompress(failure.read_bytes()))
    from sentinel.core.session import SessionState
    require(SessionState.from_dict(value['state']).to_dict()==value['state'],'REFUSED_UNSENT_STATE_ROUNDTRIP')
    require(value['state']['last_processed_session']==selected[299],'REFUSED_UNSENT_ADJACENCY')
    require(before==inventory(root),'REFUSED_PREFLIGHT_MUTATION')
    proof=dict(schema='research.capital-risk-warmup-preflight/1',status='WARMUP_PREFLIGHT_PASSED',
        predecessor=spec,next_session=selected[299],all_prefixes=saved['journals'],tails=tails,
        original_inventory=before,canonical_restore_exact=True,old_source_bytes_verified=True,
        frozen_input_and_reference_bindings_verified=True,
        unsent_state_roundtrip=True,unsent_state_sha256=sha(failure),sessions_advanced=0)
    output.write_text(json.dumps(proof,indent=2)+'\n')


def bridge(root,spec,preflight_path,candidate,lineage,output):
    from research.pooled_vacancy_funding import backtest,runtime
    from research.pooled_vacancy_funding.journal import Journal,read_checkpoint,write_checkpoint
    from research.pooled_input_support.bundle import axis
    from sentinel.core.session import SessionState
    before=inventory(root);saved=read_checkpoint(root/'checkpoint.json.gz')
    bind_checkpoint(saved,spec,root/'checkpoint.json.gz')
    proof=json.loads(preflight_path.read_bytes())
    require(proof['schema']=='research.capital-risk-warmup-preflight/1' and proof['status']=='WARMUP_PREFLIGHT_PASSED'
        and proof['predecessor']==spec and proof['original_inventory']==before and proof['sessions_advanced']==0
        and proof['canonical_restore_exact'] and proof['old_source_bytes_verified']
        and proof['frozen_input_and_reference_bindings_verified'],'REFUSED_OLD_PREFLIGHT')
    selected=selected_axis(backtest,axis);require(saved['source_cursor']==selected[298]
        and proof['next_session']==selected[299],'REFUSED_BRIDGE_AXIS')
    base=successor_base(saved['base'],backtest.source_files())
    _,identity=runtime.strategy(saved['base']['policy'])
    state=deepcopy(saved['run']['state']);state['strategy_identity']=identity
    unchanged_financial_state(saved['run']['state'],state)
    # Actual falsifiers exercise the same guards before any candidate is written.
    wrong={**spec,'outer_sha256':'0'*64}
    try:bind_checkpoint(saved,wrong,root/'checkpoint.json.gz')
    except ValueError:pass
    else:raise ValueError('REFUSED_WRONG_PREDECESSOR_FALSIFIER_MISSED')
    wrong_state=deepcopy(state);wrong_state['wealth_core']['cash']+=1
    try:unchanged_financial_state(saved['run']['state'],wrong_state)
    except ValueError:pass
    else:raise ValueError('REFUSED_FINANCIAL_MUTATION_FALSIFIER_MISSED')
    require(not candidate.exists() and not lineage.exists(),'REFUSED_CANDIDATE_OVERWRITE')
    canonical=SessionState.from_dict(state)
    run=runtime.ResearchRun(saved['run']['policy'],backtest.input_hash(base,[]),canonical)
    inner=runtime.checkpoint(run)
    require(inner['state']==state,'REFUSED_BRIDGE_CANONICAL_STATE_DIFFERENCE')
    lineage.mkdir(parents=True)
    (lineage/'predecessor.json.gz').write_bytes((root/'checkpoint.json.gz').read_bytes())
    (lineage/'preflight.json').write_bytes(preflight_path.read_bytes())
    shutil.copytree(root,candidate)
    failure=candidate/'failed-canonical-state.json.gz'
    (lineage/'unsent-failed-canonical-state.json.gz').write_bytes(failure.read_bytes())
    require(sha(failure)==proof['unsent_state_sha256'],'REFUSED_UNSENT_PRESERVATION')
    failure.unlink()  # Its exact immutable copy is retained outside checkpoint discovery.
    receipt=dict(schema='research.capital-risk-diagnostic-source-successor/1',
        predecessor=spec,preflight_sha256=sha(preflight_path),source_change=COUNTER,
        before_source=saved['base']['sources'][COUNTER],after_source=base['sources'][COUNTER],
        old_identity=saved['run']['state']['strategy_identity'],new_identity=identity,
        financial_state_unchanged=True,next_session=selected[299],sessions_advanced=0)
    receipt_sha=digest(receipt)
    event=dict(schema='research.capital-risk-source-boundary/1',source_successor_sha256=receipt_sha,
        predecessor_checkpoint_sha256=saved['run']['checkpoint_sha256'],unchanged_through=saved['source_cursor'],
        predecessor_state_sha256=saved['run']['state_sha256'],successor_state_sha256=inner['state_sha256'])
    journal=Journal(candidate,resume=True)
    try:
        journal.verify(saved['journals']);journal.recover(saved['journals'])
        journal.append('watch',event);commitments=journal.commitment()
    finally:journal.close()
    for name,t in proof['tails'].items():
        if t['bytes']:
            matches=[p for p in candidate.rglob('*') if p.is_file() and p.stat().st_size==t['bytes'] and sha(p)==t['sha256']]
            require(matches,'REFUSED_RECOVERED_TAIL_PRESERVATION')
    successor={**deepcopy(saved),'base':base,'run':inner,'journals':commitments,
        'chain':digest(dict(previous=saved['chain'],event=event))}
    successor.pop('sha256');successor['sha256']=digest(successor)
    backtest.validate_checkpoint(successor,base,selected)
    restored=runtime.restore(inner,policy=base['policy'],input_sha256=backtest.input_hash(base,[]))
    require(runtime.checkpoint(restored)==inner,'REFUSED_NEW_CANONICAL_ROUNDTRIP')
    unchanged_financial_state(saved['run']['state'],restored.state.to_dict())
    for key in ('economics','retries','stats','spy_base','repairs','completed','source_cursor'):
        require(saved[key]==successor[key],'REFUSED_REPORTING_STATE_MUTATION')
    write_checkpoint(candidate/'checkpoint.json.gz',successor)
    require(read_checkpoint(candidate/'checkpoint.json.gz')==successor,'REFUSED_SUCCESSOR_FILE_ROUNDTRIP')
    journal=Journal(candidate,resume=True)
    try:journal.verify(saved['journals']);journal.verify(successor['journals'])
    finally:journal.close()
    require(before==inventory(root),'REFUSED_PREDECESSOR_ARTIFACT_MUTATION')
    require(sha(lineage/'predecessor.json.gz')==spec['file_sha256'],'REFUSED_PREDECESSOR_FILE_PRESERVATION')
    result=dict(schema='research.capital-risk-warmup-bridge/1',status='WARMUP_BRIDGE_QUALIFIED',
        receipt=receipt,receipt_sha256=receipt_sha,event=event,successor_outer=successor['sha256'],
        successor_file_sha256=sha(candidate/'checkpoint.json.gz'),successor_inner=inner['checkpoint_sha256'],
        old_and_new_canonical_roundtrips=True,all_prefixes_verified=True,tails_preserved=proof['tails'],
        financial_state_unchanged=True,reporting_state_unchanged=True,
        falsifiers=['wrong_predecessor','financial_state_mutation'],sessions_advanced=0)
    (lineage/'source-successor.json').write_text(json.dumps(result,indent=2)+'\n')
    output.write_text(json.dumps(result,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=['preflight','bridge'],required=True)
    p.add_argument('--request',type=Path,required=True);p.add_argument('--window',required=True)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();spec=json.loads(a.request.read_bytes())['windows'][a.window]['baseline_predecessor']
    require(str(Path(__file__).resolve()).startswith('/driver/'),'REFUSED_NONHOSTED_DRIVER_PATH')
    if a.phase=='preflight':preflight(a.root,spec,a.output)
    else:bridge(a.root,spec,Path('/out/preflight.json'),Path('/out/candidate-B/run-001'),
        Path('/out/candidate-B/lineage'),a.output)
    print('WARMUP_'+a.phase.upper()+'_PASSED_NO_SESSIONS_ADVANCED')


if __name__=='__main__':main()
