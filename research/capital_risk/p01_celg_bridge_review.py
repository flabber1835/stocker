"""Stopped new-source suffix review; all already admitted old audits are reused."""
from copy import deepcopy
from decimal import Decimal
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

from full_system_benchmark import save
from p01_celg_bridge_gate import (specification,parent_identity,verify_receipt,source_adoption,
                                  need,digest,sha,HERE)
from p01_celg_bridge_run import authenticated_quote,old_inputs,native,END
from p01_celg_bridge_codec import InputCodec,OLD,SID,SCOPES
from p01_celg_bridge_accounting import reconcile,right_flow
from system_campaign_pxd_pause import adoption


def review(old,evidence,out):
    from research.pooled_vacancy_funding import backtest,runtime,journal,source_successor
    from research.pooled_input_support.bundle import axis
    from research.pooled_vacancy_funding.monthly import MonthlyStats
    from research.pooled_vacancy_funding.retries import RetryStats,COUNTERS
    from system_campaign_readonly import reader
    from system_campaign_factual_run import verify_correlation,preserve_tails
    from core_window_review import factor,near
    spec=specification();original=parent_identity(journal.read_checkpoint(old/spec['selected_checkpoint']))
    current=journal.read_checkpoint(evidence/'book/checkpoint.json.gz')
    zero=json.loads((evidence/'zero-session-boundaries.json').read_bytes())
    source,adopted=zero['source_checkpoint'],zero['input_checkpoint']
    source_map=json.loads((evidence/'source-map.json').read_bytes())
    raw_receipt=json.loads((evidence/'source-successor.json').read_bytes())
    _,identity=runtime.strategy(original['base']['policy'])
    verify_receipt(raw_receipt,original,{k:v for k,v in source['base'].items() if k!='source_successor_sha256'},
                   source_map,identity)
    binding=dict(receipt=SimpleNamespace(**raw_receipt),predecessor=original,
                 receipt_sha256=sha((evidence/'source-successor.json').read_bytes()))
    bridge=source_successor.make_bridge(binding,source['base'])
    event=source_successor.boundary_event(binding)
    source_adoption(source,bridge,original,event)
    q,descriptor=authenticated_quote()
    doc=json.loads((evidence/'celg-clock-input.json').read_bytes())
    need(doc['quote_capsule']==descriptor and doc['quote_input_sha256']==digest(q),
         'STOPPED_REVIEW_EXACT_PRIVATE_INPUT_CAPSULE_AND_QUOTE')
    qualified=json.loads((evidence/'qualification/qualification-summary.json').read_bytes())
    need(qualified['input_document_sha256']==sha((evidence/'celg-clock-input.json').read_bytes())
         and qualified['source_zero_inner_sha256']==source['run']['checkpoint_sha256']
         and qualified['input_zero_outer_sha256']==adopted['sha256']
         and qualified['successor_input_sha256']==current['run']['input_sha256']
         and qualified['source_map_sha256']==digest(source_map)
         and qualified['financial_predecessor_authorized'] is False,'STOPPED_REVIEW_EXACT_ACTUALLY_QUALIFIED_BOUNDARIES')
    with old_inputs(old,original,out/'contexts'),InputCodec(native(OLD,SID),doc):
        loaded=backtest.load_repair(evidence/'celg-clock-input.json',resume_session='2019-11-19',
                                   predecessor_checkpoint_sha256=source['run']['checkpoint_sha256'])
        input_event=adoption(adopted,source,loaded.sha256,OLD)
        need(current['base']==adopted['base'] and current['repairs']==adopted['repairs']
             and len(current['repairs'])==10 and current['repairs'][:9]==original['repairs']
             and current['base']['sources']==backtest.source_files(),'STOPPED_REVIEW_SOURCE224_OLD9_AND_EXACT_TENTH_INPUT')
        for d in current['repairs']:
            raw=(evidence/'book/repairs'/d['filename']).read_bytes()
            need(sha(raw)==d['sha256'],'STOPPED_REVIEW_ALL_TEN_DOCUMENT_BYTES')
            obj=backtest.load_repair(evidence/'book/repairs'/d['filename'],resume_session=d['resume_session'],
                                    predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'])
            need(obj.sha256==d['sha256'],'STOPPED_REVIEW_ALL_TEN_REGISTERED_CODECS')
        full=axis();dates=full[full.index(backtest.START)-425:full.index(backtest.END)+1]
        need('2019-11-19'<=current['source_cursor']<=END,'STOPPED_REVIEW_BOUNDED_ACTUAL_CURSOR')
        stream=reader(journal.Journal,evidence/'book',journal.STREAMS)
        checked=[]
        try:
            for name,value in [('source-zero',source),('input-zero',adopted),('current',current)]:
                backtest.validate_checkpoint(value,source['base'],dates)
                restored=runtime.restore(value['run'],policy=value['base']['policy'],
                    input_sha256=backtest.input_hash(value['base'],value['repairs']))
                need(runtime.checkpoint(restored)==value['run'],'STOPPED_REVIEW_NEW_BOUNDARY_AND_CURRENT_CANONICAL_RESTORE')
                stream.verify(value['journals']);checked.append(name)
            for path in [*sorted((evidence/'book/pre-event').glob('*.json.gz')),
                         *sorted((evidence/'book/month-end').glob('*.json.gz'))]:
                value=journal.read_checkpoint(path);backtest.validate_checkpoint(value,source['base'],dates)
                restored=runtime.restore(value['run'],policy=value['base']['policy'],
                    input_sha256=backtest.input_hash(value['base'],value['repairs']))
                need(runtime.checkpoint(restored)==value['run'],'STOPPED_REVIEW_EVERY_NEW_CANONICAL_CHECKPOINT')
                stream.verify(value['journals']);checked.append(path.relative_to(evidence).as_posix())
        finally:stream.close()
    pre=json.loads((evidence/'bridge-preflight.json').read_bytes())
    for name,entry in pre['original_checkpoint_files'].items():
        path=evidence/'lineage/original-checkpoints'/name
        need(path.stat().st_size==entry['bytes'] and sha(path.read_bytes())==entry['sha256'],
             'STOPPED_REVIEW_OLD_SOURCE_EPOCH_GZIP_BYTES_PRESERVED_NOT_RESTORED_UNDER_NEW_SOURCE')
    suffixes={};prefixes={}
    for name,c in original['journals'].items():
        before=(old/f'book/{name}.jsonl').read_bytes();after=(evidence/f'book/{name}.jsonl').read_bytes()
        need(len(before)==c['bytes'] and sha(before)==c['prefix_sha256'] and after[:c['bytes']]==before,
             'STOPPED_REVIEW_ALL_OLD_COMMITTED_PREFIX_BYTES')
        suffixes[name]=[json.loads(v) for v in after[c['bytes']:current['journals'][name]['bytes']].splitlines()]
        prefixes[name]=dict(old=c,current=current['journals'][name],suffix_rows=len(suffixes[name]))
    events=[v for v in suffixes['watch'] if v.get('schema') in
            ('pooled-source-boundary/1','research.pooled-action-successor/1')]
    need(events==[event,input_event],'STOPPED_REVIEW_ONE_SOURCE_THEN_ONE_INPUT_BOUNDARY_IN_ORDER')
    wanted=[d for d in dates if original['source_cursor']<d<=current['source_cursor']]
    need(not suffixes['formation'] and [r['session'] for r in suffixes['daily']]==wanted
         and len(wanted)==current['completed']-475,'STOPPED_REVIEW_EXACT_COMMITTED_NEW_AXIS')
    ledger=current['run']['state']['ledger']['events'];prior=deepcopy(original['economics'])
    chain=digest(dict(previous=original['chain'],event=event));chain=digest(dict(previous=chain,event=input_event))
    states={r['session']:r['state_sha256'] for r in qualified['actual_role_and_full_state_checks']}
    stats=MonthlyStats.from_dict(original['stats']);retries=RetryStats.from_dict(original['retries'])
    monthly=[];snapshots=0;scope_checks=[]
    prior_role=dict(wealth_core=original['run']['state']['wealth_core'],pending=original['run']['state']['pending'])
    for row in suffixes['daily']:
        need(row['phase']=='MEASURED' and row['input_sha256']==current['run']['input_sha256'],
             'STOPPED_REVIEW_NEW_FINANCIAL_PHASE_AND_INPUT')
        if row['session'] in states:need(row['state_sha256']==states[row['session']],
                                       'STOPPED_REVIEW_FINANCIAL_FULL_STATE_EQUALS_ACTUAL_QUALIFICATION')
        audit=row['evidence']['research_entry_audit']
        for scope in SCOPES:
            if row['session']==scope['session']:
                need(not any(ep['security_id']==scope['security_id'] for ep in prior_role['wealth_core']['episodes'].values())
                     and not any(p['security_id']==scope['security_id'] for p in prior_role['pending']),
                     'STOPPED_REVIEW_INDEPENDENT_ALL_PENDING_AND_HELD_NATIVE_PROXY_SCOPE')
                scope_checks.append(dict(session=scope['session'],security_id=scope['security_id'],
                    source_term_sha256=scope['native_term_sha256'],scope_record_sha256=scope['scope_record_sha256'],
                    unheld=True,all_pending_absent=True))
        for key,valuation in [('opening_accounting','parent_core_open_equity'),
                              ('closing_accounting','parent_core_close_equity')]:
            snapshot=deepcopy(audit[key]);n=snapshot['ledger'].pop('event_count')
            need(type(n) is int and 0<=n<=len(ledger),'STOPPED_REVIEW_EXACT_NEW_LEDGER_PREFIX_COUNT')
            snapshot['ledger']['events']=ledger[:n];reconcile(snapshot,q)
            near(snapshot['resolved_equity'],row['economics'][valuation],'STOPPED_REVIEW_NEW_RAW_ACCOUNT_EQUITY')
            snapshots+=1
        prior_role=dict(wealth_core=audit['closing_accounting']['wealth_core'],
                        pending=audit['closing_accounting']['pending'])
        factor(prior,row);prior=row['economics']
        chain=digest(dict(previous=chain,session=row['session'],state_sha256=row['state_sha256'],economics=row['economics']))
        need(chain==row['chain_sha256'],'STOPPED_REVIEW_EVERY_NEW_FUNDED_FACTOR_AND_CHAIN')
        # Reconstruct report metrics and exact retry summary from retained actual counts.
        if retries.month!=row['session'][:7]:
            retries.month=row['session'][:7];retries.month_counts=dict.fromkeys(COUNTERS,0)
        counts=row['retry_diagnostics']['counts']
        need(set(counts)==set(COUNTERS) and all(type(v) is int and v>=0 for v in counts.values()),
             'STOPPED_REVIEW_EXACT_NEW_RETRY_COUNTER_DOMAIN')
        for k,v in counts.items():
            for target in (retries.totals['MEASURED'],retries.month_counts):
                target[k]=max(target[k],v) if k=='longest_zero_failure_streak' else target[k]+v
        idx=dates.index(row['session']);end=dates[idx+1][:7]!=row['session'][:7]
        report=stats.advance(row['session'],{k:Decimal(v) for k,v in row['comparison_navs'].items()},
            core_target=str(row['decision']['target_core_exposure']),month_end=end)
        if report:report['slot_retries']=retries.summary();monthly.append(report)
    need(chain==current['chain'] and stats.to_dict()==current['stats'],
         'STOPPED_REVIEW_FINAL_CHAIN_AND_ALL_REPORT_STATE_EXACT')
    need(monthly==suffixes['monthly'],'STOPPED_REVIEW_EVERY_NEW_MONTHLY_REPORT_EXACT')
    need(retries.totals==current['retries']['totals'] and retries.month_counts==current['retries']['month_counts'],
         'STOPPED_REVIEW_ALL_NEW_RETRY_REPORT_COUNTERS_EXACT')
    rights=right_flow(ledger,q);verify_correlation(evidence);tails=preserve_tails(evidence/'book',pre)
    outcome=json.loads((evidence/'celg-bridge-outcome.json').read_bytes())
    need(outcome['source_cursor']==current['source_cursor'] and outcome['completed']==current['completed']
         and outcome['original_own475_resumed_fresh'] is True and outcome['qualification_state_adopted'] is False,
         'STOPPED_REVIEW_FRESH_ACTUAL_FINANCIAL_OUTCOME')
    need(outcome['actual_inherited_native_scope_guards']==scope_checks,
         'STOPPED_REVIEW_ACTUAL_NATIVE_SCOPE_GUARDS_MATCH_INDEPENDENT_PRIOR_ROLES')
    stopped_scope=None
    if outcome['status']=='CELG_BRIDGE_PARTIAL_OR_REFUSAL_PRESERVED':
        result=json.loads((evidence/'book/result.json').read_bytes())
        candidates=[s for s in SCOPES if s['session']==result.get('failed_session')]
        if candidates and 'NATIVE_UNHELD_LEADERSHIP_PROXY_CANNOT_BROADEN_TO_HELD_OR_PENDING' in result.get('error',''):
            scope=candidates[0]
            need(current['source_cursor']==scope['prior_session'] and (
                any(ep['security_id']==scope['security_id'] for ep in prior_role['wealth_core']['episodes'].values())
                or any(p['security_id']==scope['security_id'] for p in prior_role['pending'])),
                'STOPPED_REVIEW_ACTUAL_UNSUPPORTED_NATIVE_ROLE_BEFORE_FINANCIAL_TRANSITION')
            paths=list((evidence/'book/pre-event').glob(scope['session']+'-*.json.gz'))
            matches=[p for p in paths if journal.read_checkpoint(p)['run']==current['run']]
            need(len(matches)==1,'STOPPED_REVIEW_DURABLE_ACTUAL_PRE_EVENT_CANONICAL_PRIOR_CHECKPOINT')
            stopped_scope=dict(session=scope['session'],prior_session=scope['prior_session'],
                               checkpoint=matches[0].relative_to(evidence).as_posix())
    save(out/'celg-bridge-financial-review.json',dict(schema='research.p01-celg-bridge-suffix-review/1',
        status='CELG_BRIDGE_ACTUAL_COMMITTED_SUFFIX_REVIEWED_PENDING_CLIENT',checkpoint_sha256=current['sha256'],
        source_cursor=current['source_cursor'],completed=current['completed'],new_financial_rows=len(wanted),
        new_accounting_snapshots=snapshots,new_monthly_reports=len(monthly),all_new_monthly_report_state_exact=True,
        old_source_canonical_restore_proofs_reused=spec['reused_hosted_old_source_proofs'],
        old_accounting_review_reused_sha256=spec['independent_review_sha256'],old_audits_repeated=False,
        source_then_input_boundary_exact=True,old9_inputs_unchanged=True,new_input_sha256=qualified['input_document_sha256'],
        checked_new_source_checkpoints=checked,old_source_checkpoint_bytes_preserved=True,
        all_new_accounting_factors_and_chains_verified=True,actual_right_flow=rights,
        inherited_native_scope_checks=scope_checks,unsupported_native_scope_stop=stopped_scope,
        prefixes=prefixes,recovered_tails=tails,qualification_state_adopted=False,financial_predecessor_admitted=False,
        full_p01_comparison_complete=False,production_contacted=False))
