"""Stopped suffix accounting; reuse admitted own438 history by exact content."""
from copy import deepcopy
import json
from pathlib import Path

from full_system_benchmark import need,save
from system_campaign_facts import sha,digest
from system_campaign_readonly import reader
from system_campaign_discovery_context import require_strict_checkpoint
from system_campaign_p01_discovery_inputs import retained_inputs
from p01_clock_input_codec import InputCodec,parse,document,PARENT,INNER,STATE,NEXT_STATES
from p01_clock_input_run import native,input_objects,END,MAXIMUM


def review(old,evidence,out,spec):
    from research.pooled_vacancy_funding import backtest,runtime,journal
    from research.pooled_input_support.bundle import axis
    from core_window_review import reconcile,factor,near
    old,evidence,out=Path(old),Path(evidence),Path(out)
    original=journal.read_checkpoint(old/spec['selected_checkpoint'])
    need(original['sha256']==PARENT and original['repairs']==spec['repairs'],
         'P01_CLOCK_INPUT_REVIEW_ORIGINAL_ADMITTED_PARENT')
    current=require_strict_checkpoint(journal.read_checkpoint(evidence/'book/checkpoint.json.gz'))
    full=axis();dates=full[full.index(backtest.START)-425:full.index(backtest.END)+1]
    backtest.validate_checkpoint(current,original['base'],dates)
    need(current['base']['sources']==backtest.source_files() and 438<=current['completed']<=475
         and current['source_cursor']<=END,'P01_CLOCK_INPUT_REVIEW_SOURCE_AND_BOUNDED_CURSOR')
    loaded=parse(evidence/'clock-input.json',resume_session='2019-09-27',predecessor_checkpoint_sha256=INNER)
    descriptor=dict(filename=loaded.sha256+'.json',sha256=loaded.sha256,resume_session='2019-09-27',
        predecessor_checkpoint_sha256=INNER)
    need(current['repairs']==[*original['repairs'],descriptor],
         'P01_CLOCK_INPUT_REVIEW_ONLY_NINTH_ADMITTED_DESCRIPTOR')
    qualified=json.loads((evidence/'qualification/qualification-summary.json').read_bytes())
    need(qualified['new_input_document_sha256']==loaded.sha256
         and qualified['successor_input_sha256']==current['run']['input_sha256']
         and qualified['financial_predecessor_authorized'] is False,
         'P01_CLOCK_INPUT_REVIEW_IDENTICAL_ACTUALLY_QUALIFIED_DOCUMENT_AND_INPUT_IDENTITY')
    with retained_inputs(old,original,out/'contexts'),InputCodec(native()):
        input_objects(evidence,current,backtest)
        restored=runtime.restore(current['run'],policy=current['base']['policy'],
            input_sha256=backtest.input_hash(current['base'],current['repairs']))
        need(runtime.checkpoint(restored)==current['run'],'P01_CLOCK_INPUT_REVIEW_ACTUAL_NINE_INPUT_RESTORE')
    stream=reader(journal.Journal,evidence/'book',journal.STREAMS)
    try:
        stream.verify(current['journals'])
        checked=[]
        paths=[*sorted((evidence/'book/month-end').glob('*.json.gz')),
               *sorted((evidence/'book/pre-event').glob('*.json.gz')),
               *sorted((evidence/'book/predecessor-checkpoints').glob('*.json.gz'))]
        for path in paths:
            value=journal.read_checkpoint(path)
            if value['sha256']==PARENT:
                need(sha(path.read_bytes())==spec['selected_file']['sha256'],
                     'P01_CLOCK_INPUT_REVIEW_ORIGINAL_PARENT_GZIP_NOT_RESERIALIZED')
            else:
                backtest.validate_checkpoint(value,original['base'],dates)
                r=runtime.restore(value['run'],policy=value['base']['policy'],
                    input_sha256=backtest.input_hash(value['base'],value['repairs']))
                need(runtime.checkpoint(r)==value['run'],'P01_CLOCK_INPUT_REVIEW_EACH_NEW_CANONICAL_CHECKPOINT')
                stream.verify(value['journals'])
            checked.append(path.relative_to(evidence).as_posix())
    finally:stream.close()
    proof=json.loads((evidence/'clock-input-preflight.json').read_bytes())
    for name,entry in proof['original_checkpoint_files'].items():
        path=evidence/'lineage/original-checkpoints'/name
        need(path.stat().st_size==entry['bytes'] and sha(path.read_bytes())==entry['sha256'],
             'P01_CLOCK_INPUT_REVIEW_ALL_ORIGINAL_GZIP_BYTES')
    prefix_checks={};suffixes={}
    for name,commit in original['journals'].items():
        before=(old/f'book/{name}.jsonl').read_bytes();after=(evidence/f'book/{name}.jsonl').read_bytes()
        need(len(before)==commit['bytes'] and sha(before)==commit['prefix_sha256']
             and after[:commit['bytes']]==before,'P01_CLOCK_INPUT_REVIEW_OWN438_ALL_PREFIX_BYTES_UNCHANGED')
        suffix=after[commit['bytes']:current['journals'][name]['bytes']]
        suffixes[name]=[json.loads(line) for line in suffix.splitlines()]
        prefix_checks[name]=dict(admitted_prefix=commit,suffix_rows=len(suffixes[name]),
            current_uncommitted_tail_bytes=len(after)-current['journals'][name]['bytes'])
    event=dict(schema='research.pooled-action-successor/1',predecessor_checkpoint_sha256=INNER,
        unchanged_through='2019-09-27',earliest_affected_session='2019-09-30',state_sha256=STATE,
        overlay=descriptor,predecessor_input_sha256=original['run']['input_sha256'],
        successor_input_sha256=current['run']['input_sha256'])
    need([v for v in suffixes['watch'] if v.get('schema')=='research.pooled-action-successor/1']==[event],
         'P01_CLOCK_INPUT_REVIEW_EXACT_SINGLE_CANONICAL_INPUT_BOUNDARY')
    expected=[d for d in dates if original['source_cursor']<d<=current['source_cursor']]
    need(not suffixes['formation'] and [r['session'] for r in suffixes['daily']]==expected
         and len(expected)==current['completed']-438,'P01_CLOCK_INPUT_REVIEW_EXACT_COMMITTED_SUFFIX_AXIS')
    events=current['run']['state']['ledger']['events'];prior=deepcopy(original['economics'])
    chain=digest(dict(previous=original['chain'],event=event));snapshots=0
    for row in suffixes['daily']:
        need(row['phase']=='MEASURED' and row['input_sha256']==current['run']['input_sha256'],
             'P01_CLOCK_INPUT_REVIEW_NEW_ROW_INPUT_AND_PHASE')
        if row['session'] in NEXT_STATES:
            need(row['state_sha256']==NEXT_STATES[row['session']],
                 'P01_CLOCK_INPUT_REVIEW_FIRST_TWO_FULL_STATES_MATCH_QUALIFICATION')
        audit=row['evidence']['research_entry_audit']
        for key,valuation in [('opening_accounting','parent_core_open_equity'),
                              ('closing_accounting','parent_core_close_equity')]:
            snapshot=deepcopy(audit[key]);n=snapshot['ledger'].pop('event_count')
            need(type(n) is int and 0<=n<=len(events),'P01_CLOCK_INPUT_REVIEW_NEW_LEDGER_PREFIX_COUNT')
            snapshot['ledger']['events']=events[:n]
            reconcile(snapshot);near(snapshot['resolved_equity'],row['economics'][valuation],
                                     'P01_CLOCK_INPUT_REVIEW_NEW_RAW_VALUATION')
            snapshots+=1
        factor(prior,row);prior=row['economics']
        chain=digest(dict(previous=chain,session=row['session'],state_sha256=row['state_sha256'],economics=row['economics']))
        need(chain==row['chain_sha256'],'P01_CLOCK_INPUT_REVIEW_EVERY_NEW_FINANCIAL_CHAIN')
    need(chain==current['chain'],'P01_CLOCK_INPUT_REVIEW_FINAL_NEW_CHAIN')
    from system_campaign_factual_run import verify_correlation,preserve_tails
    verify_correlation(evidence);tails=preserve_tails(evidence/'book',proof)
    outcome=json.loads((evidence/'clock-input-outcome.json').read_bytes())
    need(outcome['source_cursor']==current['source_cursor'] and outcome['completed']==current['completed']
         and outcome['qualification_state_adopted'] is False,'P01_CLOCK_INPUT_REVIEW_ACTUAL_FRESH_FINANCIAL_OUTCOME')
    save(out/'clock-input-financial-review.json',dict(schema='research.p01-economic-clock-suffix-review/1',
        status='CLOCK_INPUT_COMMITTED_SUFFIX_REVIEWED_PENDING_CLIENT',checkpoint_sha256=current['sha256'],
        source_cursor=current['source_cursor'],completed=current['completed'],new_financial_rows=len(expected),
        new_accounting_snapshots=snapshots,old_accounting_audit_reused_sha256=spec['independent_review_sha256'],
        old_accounting_snapshots_recomputed=0,all_original_prefixes_and_checkpoint_bytes_preserved=True,
        checked_current_book_checkpoints=checked,
        canonical_ninth_input_identity_boundary_verified=True,all_new_factors_accounting_and_chains_verified=True,
        first_two_full_state_hashes_match_qualification=True,source515_unchanged=True,
        prefixes=prefix_checks,recovered_tails=tails,full_p01_comparison_complete=False,
        qualification_state_adopted=False,production_contacted=False))
