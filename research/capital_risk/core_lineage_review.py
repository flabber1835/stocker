"""Read-only review of an admitted old-source predecessor and exact successor."""
import json
from pathlib import Path


def require(value,code):
    if not value:raise ValueError(code)


def review_lineage(root,lineage,backtest,runtime,axis):
    from research.pooled_vacancy_funding.journal import Journal,read_checkpoint
    require(lineage.resolve().parent==root.resolve().parent,'REFUSED_LINEAGE_ROOT')
    require({p.name for p in lineage.iterdir()}=={'predecessor.json.gz','preflight.json',
        'unsent-failed-canonical-state.json.gz','source-successor.json','successor-start.json.gz',
        'qualification-source-bindings.json','qualification-admission.json'},'REFUSED_LINEAGE_INVENTORY')
    request=json.loads(Path('/driver/core-window-suffix-request.json').read_bytes())
    window={'2021-01-04':'stress2021','2025-01-02':'recent2025'}[backtest.START]
    spec=request['windows'][window];admission=json.loads((lineage/'qualification-admission.json').read_bytes())
    require(admission['qualification']==spec and admission['qualification_run_id']==request['qualification_run_id']
        and admission['qualification_source_commit']==request['qualification_source_commit']
        and admission['original_request_sha256']==request['qualification_request_sha256'],'REFUSED_LINEAGE_ADMISSION')
    bridge=json.loads((lineage/'source-successor.json').read_bytes())
    pre=json.loads((lineage/'preflight.json').read_bytes());old=read_checkpoint(lineage/'predecessor.json.gz')
    start=read_checkpoint(lineage/'successor-start.json.gz');oldspec=bridge['receipt']['predecessor']
    require(backtest.file_sha(lineage/'source-successor.json')==spec['bridge_sha256']
        and backtest.file_sha(lineage/'qualification-source-bindings.json')==spec['source_bindings_sha256']
        and backtest.file_sha(lineage/'successor-start.json.gz')==spec['candidate_file_sha256']
        and start['sha256']==spec['candidate_outer_sha256'],'REFUSED_QUALIFIED_LINEAGE_BYTES')
    require(backtest.file_sha(lineage/'predecessor.json.gz')==oldspec['file_sha256']
        and backtest.file_sha(lineage/'preflight.json')==bridge['receipt']['preflight_sha256']
        and old['sha256']==oldspec['outer_sha256'] and old['run']['checkpoint_sha256']==oldspec['inner_sha256']
        and old['run']['state_sha256']==oldspec['state_sha256'],'REFUSED_PREDECESSOR_LINEAGE_BYTES')
    require(old['sha256']==runtime._hash({k:v for k,v in old.items() if k!='sha256'})
        and old['run']['checkpoint_sha256']==runtime._hash({k:v for k,v in old['run'].items() if k!='checkpoint_sha256'})
        and old['run']['state_sha256']==runtime._hash(old['run']['state']),'REFUSED_OLD_LINEAGE_COMMITMENTS')
    require(pre['status']=='WARMUP_PREFLIGHT_PASSED' and pre['predecessor']==oldspec and pre['sessions_advanced']==0
        and pre['canonical_restore_exact'] and pre['old_source_bytes_verified']
        and pre['frozen_input_and_reference_bindings_verified'],'REFUSED_EXACT_OLD_CANONICAL_PROOF')
    require(backtest.file_sha(lineage/'unsent-failed-canonical-state.json.gz')==pre['unsent_state_sha256'],
        'REFUSED_UNSENT_STATE_ARCHIVE')
    require(runtime._hash(bridge['receipt'])==bridge['receipt_sha256'] and bridge['sessions_advanced']==0
        and bridge['status']=='WARMUP_BRIDGE_QUALIFIED','REFUSED_SOURCE_SUCCESSOR_RECEIPT')
    oldstate,newstate=old['run']['state'],start['run']['state']
    require({k:v for k,v in oldstate.items() if k!='strategy_identity'}==
        {k:v for k,v in newstate.items() if k!='strategy_identity'},'REFUSED_LINEAGE_FINANCIAL_MUTATION')
    a,b=oldstate['strategy_identity'],newstate['strategy_identity']
    require({k for k in set(a)|set(b) if a.get(k)!=b.get(k)}=={'research_implementation_sha256'},
        'REFUSED_LINEAGE_STRATEGY_CHANGE')
    changed={k for k in set(old['base']['sources'])|set(start['base']['sources'])
        if old['base']['sources'].get(k)!=start['base']['sources'].get(k)}
    require(changed=={'research/pooled_vacancy_funding/retries.py'}
        and {k:v for k,v in old['base'].items() if k!='sources'}==
            {k:v for k,v in start['base'].items() if k!='sources'},'REFUSED_LINEAGE_SOURCE_CHANGE')
    selected=axis();selected=selected[selected.index(backtest.START)-425:selected.index(backtest.END)+1]
    require(old['source_cursor']==start['source_cursor']==selected[298] and pre['next_session']==selected[299],
        'REFUSED_LINEAGE_ADJACENCY')
    for key in ('economics','retries','stats','spy_base','repairs','completed','source_cursor'):
        require(old[key]==start[key],'REFUSED_LINEAGE_REPORTING_CHANGE')
    backtest.validate_checkpoint(start,start['base'],selected)
    require(start['base']['sources']==backtest.source_files(),'REFUSED_LINEAGE_CURRENT_SOURCE')
    restored=runtime.restore(start['run'],policy=start['base']['policy'],input_sha256=backtest.input_hash(start['base'],start['repairs']))
    require(runtime.checkpoint(restored)==start['run'],'REFUSED_SUCCESSOR_START_CANONICAL_RESTORE')
    require(start['chain']==runtime._hash(dict(previous=old['chain'],event=bridge['event'])),
        'REFUSED_LINEAGE_CHAIN')
    journal=Journal(root,resume=True)
    try:journal.verify(old['journals']);journal.verify(start['journals'])
    finally:journal.close()
    origin=json.loads((root/'identity.json').read_bytes())
    require(origin['base']==old['base'] and origin['strategy']==oldstate['strategy_identity'],
        'REFUSED_ORIGIN_IDENTITY_REWRITE')
    return dict(committed_historical_checkpoints=2,old_source_restore_reused_from_exact_authenticated_preflight=True,
        old_source_preflight_sha256=backtest.file_sha(lineage/'preflight.json'),successor_start_roundtrip_rechecked=True,
        all_old_and_successor_prefixes_verified=True,financial_controller_reporting_state_unchanged=True,
        predecessor_file_sha256=oldspec['file_sha256'],successor_file_sha256=spec['candidate_file_sha256'])
