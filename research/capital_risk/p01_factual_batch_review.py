"""Hosted stopped suffix review, reusing admitted OWN526 historical audits."""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from fractions import Fraction
import gzip
import json
import math
from pathlib import Path

from full_system_benchmark import save
from p01_epoch_parent import ROOT_ADMISSION
from p01_epoch_resume import historical_epoch
from p01_factual_batch_contract import (END,MAXIMUM,INPUT,HERE,document,facts,need,digest,sha,term)
from p01_factual_batch_codec import InputCodec,source_terms
from p01_factual_batch_accounting import reconcile,action_flows
from system_campaign_pxd_pause import adoption


def read(path):
    raw=Path(path).read_bytes()
    return json.loads(gzip.decompress(raw) if str(path).endswith('.gz') else raw)


def source_event_count(rows):
    return sum(row.get('schema')=='pooled-source-boundary/1' for row in rows)


def component_proof(value,configuration,records,source_map):
    """Inspect actual saved component wires; do not execute their transitions."""
    need(value['schema']=='research.p01-grouped-synthetic-canonical-components/1'
         and value['status']=='SYNTHETIC_CANONICAL_COMPONENTS_PASSED_NOT_FINANCIAL_ADMISSION'
         and value['configuration']==configuration
         and value['source_map_identity_sha256']==digest(source_map)
         and value['source_files'] and all(source_map['successor_financial_sources'].get(n)==h
             ==source_map['successor_all_sources'].get(n) for n,h in value['source_files'].items())
         and all(value[k] is True for k in ('target_independence_qualified','ordinary_representation_qualified',
             'held_target_holding_qualified','canonical_module_global_hooks_unchanged',
             'actual_allocation_guard_removal_accepts_bad_fixture'))
         and all(value[k] is False for k in ('held_source_with_target_pending_qualified',
             'financial_authority','qualification_state_adopted','actual_future_own_roles_claimed')),
         'REVIEW_ACTUAL_COMPONENT_SCOPE_SOURCE_AND_PARENT_CONFIGURATION')
    targets=value['target_cases'];wires=[]
    need(set(targets)=={'TARGET_HELD','TARGET_CLOSE_PENDING','TARGET_DOLLAR_BUY_PENDING'},
         'REVIEW_ALL_THREE_TARGET_INDEPENDENCE_CASES')
    for role,row in targets.items():
        need(row['before']==row['canonical_without_term_state']==row['canonical_with_term_state']
             and row['source_unheld'] is True and row['all_source_pending_absent'] is True
             and row['full_state_roundtrip'] is True,
             'REVIEW_ENTIRE_TARGET_CONTROL_STATE_AND_LEDGER_EQUAL')
        if role!='TARGET_HELD':
            need(row['source_vs_target_mutation_detected'] is True and row['actual_mutated_state']!=row['before'],
                 'REVIEW_TARGET_IDENTITY_MUTATION_ACTUALLY_DETECTED')
        wires.append(row['before'])
    stocks={a['source_ticker']:a for a in records if a['exchange_ratio'] is not None}
    need(set(value['stock_cases'])==set(stocks)=={'WLH','VSLR','BMCH','WPX'}, 'REVIEW_ALL_FOUR_HELD_STOCK_COMPONENTS')
    for ticker,row in value['stock_cases'].items():
        a=stocks[ticker];before=row['before'];after=row['after']
        need(row['terms']==term(a) and row['preexisting_target_quantity']==7
             and row['preexisting_target_episode_unchanged'] is True and row['no_CIL_rate_supplied'] is True,
             'REVIEW_COMPONENT_EXACT_LEGAL_TERMS_AND_EXISTING_TARGET')
        action_scope(before,a,True,True)
        prior=before['ledger']['events'];events=after['ledger']['events']
        need(events[:len(prior)]==prior, 'REVIEW_COMPONENT_OLD_LEDGER_PREFIX')
        flows=action_flows(events[len(prior):],[a])
        need(len(flows)==1 and len(events)-len(prior)==len(row['synthetic_quantities']['current']),
             'REVIEW_COMPONENT_ALL_SOURCE_LOTS_EXACT_POSTINGS')
        target=[(slot,e) for slot,e in before['wealth_core']['episodes'].items()
                if e['security_id']==a['delivered_security_id']]
        need(len(target)==1 and after['wealth_core']['episodes'][target[0][0]]==target[0][1]
             and row['canonical_report']['aggregate_by_security'][a['delivered_security_id']]['shares']
                 ==Fraction(flows[0]['delivered_shares_exact'])+7,
             'REVIEW_FULL_EXISTING_TARGET_EPISODE_PRESERVED_AND_AGGREGATE_REPORT')
        wires.extend([before,after])
    need({r['case'] for r in value['negative_cases']}=={'HOLDER_FRACTION_WITHOUT_CIL','INITIAL_REFERENCE_ROUNDING',
         'INEXACT_EPISODE_BINARY64','SOURCE_EPISODE_EXIT_FLAG_WITHOUT_PENDING','SOURCE_PENDING_DOLLAR_BUY'}
         and len(value['negative_cases'])==5
         and all(r['caller_full_state_and_ledger_unchanged'] is True and r['error'] for r in value['negative_cases']),
         'REVIEW_ACTUAL_COMPONENT_REFUSALS_PRESERVED_WHOLE_CALLER')
    return wires


def committed_attempts(actual,attempted,cursor,next_session):
    """Retain failed-attempt records without promoting them to committed rows."""
    need(type(actual) is list and type(attempted) is list
         and all(type(row) is dict and type(row.get('session')) is str for row in attempted),
         'REVIEW_ATTEMPTED_RECORD_SCHEMA')
    sessions=[row['session'] for row in attempted]
    need(sessions==sorted(sessions) and all('2020-02-04'<day<=cursor or day==next_session for day in sessions)
         and actual==[row for row in attempted if row['session']<=cursor],
         'REVIEW_COMMITTED_RECORDS_EXACTLY_FILTER_ENTIRE_RETAINED_ATTEMPTED_RECORDS')
    return [row for row in attempted if row['session']>cursor]


def pre_event_receipts(rows,checkpoints,files):
    for row in rows:
        name='book/pre-event/'+row['path']
        need(name in checkpoints, 'REVIEW_LOGGED_PRE_EVENT_CANONICAL_CHECKPOINT_EXISTS')
        cp=checkpoints[name]
        need(row['outer_sha256']==cp['sha256'] and row['inner_sha256']==cp['run']['checkpoint_sha256']
             and row['state_sha256']==cp['run']['state_sha256'] and row['prior_session']==cp['source_cursor']
             and row['current_saved_identical_before_guard'] is True
             and row['current_file']==files[name],
             'REVIEW_ACTUAL_CANONICAL_CURRENT_SAVE_BEFORE_OUTSIDE_GUARD')


def action_scope(state, action, target_qualified, held_target_qualified=False):
    sid=action['source_security_id']
    held=[e for _,e in sorted(state['wealth_core']['episodes'].items(),key=lambda item:int(item[0])) if e['security_id']==sid]
    need(not any(p['security_id']==sid for p in state['pending']), 'REVIEW_ALL_SOURCE_PENDING_INTENTS_ABSENT')
    need(not any(e.get('exit_pending',False) for e in held), 'REVIEW_SOURCE_EPISODE_EXIT_FLAG_UNSUPPORTED')
    if action['clock_scope']=='DAILY_MARKET_UNHELD_SOURCE':
        need(not held, 'REVIEW_DAILY_MARKET_SOURCE_SCOPE_MUST_BE_UNHELD')
    if held and action['exchange_ratio'] is not None:
        ratio=Fraction(action['exchange_ratio'])
        quantities=[Fraction(str(e['current_shares'])) for e in held]
        total=sum(quantities,Fraction());whole=total*ratio;so_far=0.0
        need(total>0 and whole.denominator==1 and Fraction.from_float(float(whole))==whole,
             'REVIEW_UNSUPPORTED_HOLDER_FRACTION_WITHOUT_CIL')
        for index,(episode,q) in enumerate(zip(held,quantities)):
            actual=float(whole)-so_far if index==len(held)-1 else float(whole*q/total)
            reference=Fraction(str(episode['initial_shares']))*ratio
            need(math.isfinite(actual) and actual>0 and Fraction.from_float(actual)==q*ratio
                 and reference>0 and reference.denominator==1
                 and max(1,int(round(float(episode['initial_shares'])*float(ratio))))==reference,
                 'REVIEW_UNSUPPORTED_CANONICAL_ALLOCATION_OR_INITIAL_REFERENCE')
            so_far+=actual
        need(Fraction.from_float(so_far)==whole, 'REVIEW_EXACT_CANONICAL_HOLDER_ALLOCATION_CONSERVATION')
    target=action['delivered_security_id']
    present=target is not None and (any(e['security_id']==target for e in state['wealth_core']['episodes'].values())
        or any(p['security_id']==target for p in state['pending']))
    if present:
        if held:
            need(not any(p['security_id']==target for p in state['pending']),
                 'REVIEW_UNQUALIFIED_HELD_SOURCE_TARGET_PENDING_REFUSES')
            need(not any(e['security_id']==target and e.get('exit_pending',False)
                         for e in state['wealth_core']['episodes'].values()),
                 'REVIEW_UNQUALIFIED_HELD_SOURCE_TARGET_EXIT_FLAG_REFUSES')
            need(held_target_qualified is True, 'REVIEW_HELD_SOURCE_TARGET_HOLDING_COMPONENT_REQUIRED')
        else:
            need(target_qualified is True, 'REVIEW_ACTUAL_TARGET_INDEPENDENCE_QUALIFICATION_REQUIRED')
    return dict(action_id=action['action_id'],session=action['economic_session'],source_held=bool(held),
        source_pending=False,source_selected=sid in state['median5']['selected'],
        target_existing_role=present,clock_scope=action['clock_scope'])


def advance_retry(memory,row):
    day=row['session'];counts=row['retry_diagnostics']['counts']
    need(set(counts)==set(memory['month_counts']) and all(type(v) is int and v>=0 for v in counts.values()),
         'REVIEW_NEW_RETRY_COUNTER_DOMAIN')
    if memory['month']!=day[:7]:memory['month']=day[:7];memory['month_counts']=dict.fromkeys(counts,0)
    for k,v in counts.items():
        for target in (memory['totals']['MEASURED'],memory['month_counts']):
            target[k]=max(target[k],v) if k=='longest_zero_failure_streak' else target[k]+v
    memory['last_skip_ids']=[]
    for event in row['retry_diagnostics']['events']:
        if event['outcome']=='FILLED':memory['failed_slots'].pop(str(event['slot_id']),None)
        elif event['outcome']=='ZERO_SHARES':
            memory['failed_slots'][str(event['slot_id'])]=dict(security_id=event['security_id'],
                streak=event['consecutive_failed_attempts'],phase='MEASURED',last_session=day)
        elif event['outcome']=='CLOSE_AFFORDABILITY_SKIPS':
            memory['last_skip_ids']=sorted({e['security_id'] for e in event['candidates']})
    memory['last_session']=day;memory['transitions']+=1
    return dict(month=memory['month'],monthly=deepcopy(memory['month_counts']),
        cumulative_measured=deepcopy(memory['totals']['MEASURED']),formation=deepcopy(memory['totals']['FORMATION']))


def review(spec, out, evidence):
    """Only the hosted worker calls this; local tests exercise pure helpers/stubs."""
    out,evidence,old=Path(out),Path(evidence),Path('/old')
    with historical_epoch(old,out,spec,checkpoint_path=evidence/'book/checkpoint.json.gz') as binding:
        from research.pooled_vacancy_funding import backtest,runtime,journal
        from research.pooled_input_support.bundle import axis
        from research.pooled_input_support.adapter import Packet
        from research.pooled_vacancy_funding.monthly import MonthlyStats
        from sentinel.core.session import SessionState
        from stock_strategy_shared.wealth_core.funding import config
        from system_campaign_readonly import reader
        from system_campaign_factual_run import verify_correlation,preserve_tails
        from core_window_review import factor,near
        parent=binding.parent;zero=read(evidence/'zero-session-boundaries.json')
        need(zero['epoch_checkpoint']==parent and zero['source']['full_checkpoint_and_journals_unchanged'] is True
             and zero['source']['financial_sessions_advanced']==0 and zero['source']['attempted_financial_transitions']==0,
             'REVIEW_ACTUAL_EPOCH_ZERO_ENTIRELY_EQUALS_ADMITTED526')
        need(read(evidence/'qualification/zero-session-boundaries.json')==zero,
             'REVIEW_FRESH_FINANCE_ENTIRE_ZERO_BOUNDARIES_EQUALS_QUALIFIER')
        native=source_terms();records=facts()['records']
        with InputCodec(native) as codec:
            raw=(evidence/'batch-input.json').read_bytes()
            need(raw==(HERE/INPUT).read_bytes() and json.loads(raw)==document(), 'REVIEW_EXACT_PUBLIC_ELEVENTH_INPUT_BYTES')
            loaded=backtest.load_repair(evidence/'batch-input.json',resume_session=parent['source_cursor'],
                predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'])
            adopted=zero['input_checkpoint'];event=binding.source_gate.allow_input(adopted,loaded.sha256,'2020-02-05')
            need(event==zero['input_event']==adoption(adopted,parent,loaded.sha256,'2020-02-05'), 'REVIEW_ONE_CANONICAL_INPUT_BOUNDARY')
            current=journal.read_checkpoint(evidence/'book/checkpoint.json.gz')
            need(current['base']==parent['base'] and current['repairs']==adopted['repairs']
                 and len(current['repairs'])==11 and current['repairs'][:10]==parent['repairs']
                 and current['base']['sources']==backtest.source_files(), 'REVIEW_UNCHANGED224_SOURCE_OLD10_AND_ONE_INPUT')
            objects=[]
            for d in current['repairs']:
                path=evidence/'book/repairs'/d['filename']
                need(sha(path.read_bytes())==d['sha256'], 'REVIEW_ALL_ELEVEN_ARCHIVED_DOCUMENT_BYTES')
                obj=backtest.load_repair(path,resume_session=d['resume_session'],
                    predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'])
                need(obj.sha256==d['sha256'], 'REVIEW_ALL_ELEVEN_REGISTERED_CODECS');objects.append(obj)
            qualified=read(evidence/'qualification/qualification-summary.json')
            need(qualified['status']=='OWN526_GROUPED_FACTUAL_INPUT_AND_RUNTIME_QUALIFIED'
                 and qualified['input_document_sha256']==loaded.sha256
                 and qualified['input_zero_outer_sha256']==adopted['sha256']
                 and qualified['successor_input_sha256']==current['run']['input_sha256']
                 and qualified['epoch_zero_outer_sha256']==parent['sha256']
                 and qualified['financial_predecessor_authorized'] is False, 'REVIEW_ACTUAL_QUALIFIED_BOUNDARIES')
            cfg=config(parent['base']['policy'])
            wires=component_proof(read(evidence/'qualification/target-independence-component.json.gz'),
                dict(policy=parent['base']['policy'],fields=asdict(cfg),config_hash=cfg.config_hash()),
                records,binding.source_map)
            for wire in wires:
                need(len(wire['wealth_core']['slots'])==cfg.n_slots
                     and SessionState.from_dict(wire).to_dict()==wire,
                     'REVIEW_ALL_ACTUAL_COMPONENT_FULL_SESSIONSTATE_WIRES_CANONICAL_ROUNDTRIP')
            full=axis();dates=full[full.index(backtest.START)-425:full.index(backtest.END)+1]
            need(parent['source_cursor']<=current['source_cursor']<=END and 526<=current['completed']<=627,
                 'REVIEW_ACTUAL_BOUNDED_COMMITTED_CURSOR')
            next_session=dates[dates.index(current['source_cursor'])+1] if current['source_cursor']<END else None
            stream=reader(journal.Journal,evidence/'book',journal.STREAMS);checked=[];checkpoints={};checkpoint_files={}
            def restore(label,cp,verify_journal=True):
                backtest.validate_checkpoint(cp,parent['base'],dates)
                restored=runtime.restore(cp['run'],policy=cp['base']['policy'],
                    input_sha256=backtest.input_hash(cp['base'],cp['repairs']))
                need(runtime.checkpoint(restored)==cp['run'], 'REVIEW_NEW_CANONICAL_CHECKPOINT_FULL_ROUNDTRIP')
                if verify_journal:stream.verify(cp['journals'])
                checked.append(label)
            try:
                restore('input-zero',adopted);restore('current',current)
                for path in [*sorted((evidence/'book/pre-event').glob('*.json.gz')),
                             *sorted((evidence/'book/month-end').glob('*.json.gz'))]:
                    cp=journal.read_checkpoint(path);restore(path.relative_to(evidence).as_posix(),cp)
                    checkpoints[path.relative_to(evidence).as_posix()]=cp
                    checkpoint_files[path.relative_to(evidence).as_posix()]=dict(bytes=path.stat().st_size,sha256=sha(path.read_bytes()))
                component=read(evidence/'qualification/actual-two-session-component.json.gz')
                qpath=component['actual_components']
                need([p['session'] for p in qpath]==['2020-02-05','2020-02-06'] and component['financial_authority'] is False,
                     'REVIEW_TWO_ACTUAL_QUALIFIER_SESSIONS')
                previous=adopted['run']
                for item in qpath:
                    need(item['prior_checkpoint']==previous and item['publication']['session']==item['session'],
                         'REVIEW_FULL_QUALIFIER_PUBLICATION_AND_PRIOR_ADJACENCY')
                    restored=runtime.restore(item['checkpoint'],policy=parent['base']['policy'],
                        input_sha256=current['run']['input_sha256'])
                    need(runtime.checkpoint(restored)==item['checkpoint'], 'REVIEW_TWO_QUALIFIER_FULL_RUNTIME_RESTORES')
                    checked.append('qualifier-'+item['session']);previous=item['checkpoint']
                financial=read(evidence/'actual-financial-first-two-component.json.gz')
                need(financial['actual_components']==qpath[:len(financial['actual_components'])]
                     and len(financial['actual_components'])==min(2,current['completed']-526)
                     and financial['attempted_components']==qpath[:len(financial['attempted_components'])]
                     and financial['financial_authority'] is False
                     and financial['qualification_state_adopted'] is False,
                     'REVIEW_FRESH_FINANCE_ENTIRE_FIRST_TWO_PUBLICATION_AND_RUNTIME_PATH')
                committed_attempts(financial['actual_components'],financial['attempted_components'],
                                   current['source_cursor'],next_session)
            finally:stream.close()
            prefixes={};suffixes={};tails={};books={}
            for name,c in parent['journals'].items():
                before=(old/f'book/{name}.jsonl').read_bytes();after=(evidence/f'book/{name}.jsonl').read_bytes()
                need(len(before)==c['bytes'] and sha(before)==c['prefix_sha256'] and after[:c['bytes']]==before,
                     'REVIEW_ALL_ADMITTED526_PREFIX_BYTES')
                end=current['journals'][name]['bytes'];books[name]=after
                suffixes[name]=[json.loads(v) for v in after[c['bytes']:end].splitlines()]
                tails[name]=dict(bytes=len(after)-end,sha256=sha(after[end:]))
                prefixes[name]=dict(old=c,current=current['journals'][name],new_rows=len(suffixes[name]))
            before_watch=[json.loads(v) for v in (old/'book/watch.jsonl').read_bytes().splitlines()]
            after_watch=[json.loads(v) for v in books['watch'][:current['journals']['watch']['bytes']].splitlines()]
            need(source_event_count(before_watch)==source_event_count(after_watch)
                 and [v for v in suffixes['watch'] if v.get('schema') in
                      ('pooled-source-boundary/1','research.pooled-action-successor/1')]==[event],
                 'REVIEW_ACTUAL_SOURCE_EVENT_COUNT_UNCHANGED_AND_ONE_INPUT_EVENT')
            wanted=[d for d in dates if parent['source_cursor']<d<=current['source_cursor']]
            need(not suffixes['formation'] and [r['session'] for r in suffixes['daily']]==wanted
                 and len(wanted)==current['completed']-526, 'REVIEW_EXACT_COMMITTED_NEW_SESSION_AXIS')
            pre=read(evidence/'batch-preflight.json')
            original={p.relative_to(old).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p.read_bytes()))
                for base in ('book','lineage') for p in (old/base).rglob('*.json.gz')}
            need(pre['original_checkpoint_files']==original,
                 'REVIEW_COMPLETE_INHERITED_CHECKPOINT_INVENTORY_WITHOUT_OMISSION')
            for name,entry in pre['original_checkpoint_files'].items():
                raw=(evidence/'lineage/original-checkpoints'/name).read_bytes()
                need(raw==(old/name).read_bytes() and dict(bytes=len(raw),sha256=sha(raw))==entry,
                     'REVIEW_EVERY_INHERITED_515_AND516_CHECKPOINT_GZIP_PRESERVED')
            ledger=current['run']['state']['ledger']['events']
            need(ledger[:len(parent['run']['state']['ledger']['events'])]==parent['run']['state']['ledger']['events'],
                 'REVIEW_OLD_LEDGER_PREFIX_IMMUTABLE')
            prior=deepcopy(parent['economics']);chain=digest(dict(previous=parent['chain'],event=event))
            stats=MonthlyStats.from_dict(parent['stats']);retries=deepcopy(parent['retries']);monthly=[];snapshots=0
            states={r['session']:r['state_sha256'] for r in qualified['actual_role_and_full_state_checks']}
            checks=[];native_checks=[];prior_state=parent['run']['state'];prior_hash=adopted['run']['state_sha256']
            scopes={}
            for row in json.loads(Path('/frozen/bundle/supplements.json').read_bytes()):
                if row.get('security_id') not in {a['source_security_id'] for a in records} and (
                    'UNHELD' in row.get('disposition','').upper() or 'unheld' in row.get('reference','').lower()):
                    scopes[(row['effective_session'],row['security_id'])]=digest(row)
            for row in suffixes['daily']:
                day=row['session'];need(row['phase']=='MEASURED' and row['input_sha256']==current['run']['input_sha256'], 'REVIEW_NEW_PHASE_AND_INPUT')
                if day in states:need(row['state_sha256']==states[day], 'REVIEW_FRESH_FINANCIAL_FULL_STATE_EQUALS_QUALIFIER')
                active=[a for a in records if a['economic_session']==day]
                if active:
                    candidates=[cp for name,cp in checkpoints.items() if name.startswith('book/pre-event/'+day+'-')
                        and cp['run']['state_sha256']==prior_hash and cp['source_cursor']==dates[dates.index(day)-1]]
                    need(len(candidates)==1, 'REVIEW_ACTUAL_PRE_EVENT_FULL_PRIOR_STATE_FOR_EVERY_GROUPED_ACTION')
                    for a in active:
                        checks.append(action_scope(candidates[0]['run']['state'],a,
                            qualified['target_independence_qualified'],qualified['held_target_holding_qualified']))
                packet=Packet(day,(),{},{},1.,{},tuple(native.get(day,())),())
                codec.control=True
                for obj in objects:packet=backtest.apply_repair(packet,obj)
                for t in packet.terminal:
                    if (day,t.security_id) in scopes:
                        need(not any(e['security_id']==t.security_id for e in prior_state['wealth_core']['episodes'].values())
                             and not any(p['security_id']==t.security_id for p in prior_state['pending']),
                             'REVIEW_INHERITED_NATIVE_SCOPE_ALL_SOURCE_ROLES_ABSENT')
                        native_checks.append(dict(session=day,security_id=t.security_id,unheld=True,
                            all_source_pending_absent=True,source_record_sha256=scopes[(day,t.security_id)]))
                audit=row['evidence']['research_entry_audit'];work=deepcopy(row)
                for key,valuation in [('opening_accounting','parent_core_open_equity'),('closing_accounting','parent_core_close_equity')]:
                    snapshot=deepcopy(audit[key]);n=snapshot['ledger'].pop('event_count')
                    need(type(n) is int and 0<=n<=len(ledger), 'REVIEW_NEW_LEDGER_PREFIX_COUNT')
                    snapshot['ledger']['events']=ledger[:n];reconcile(snapshot,binding.quote,records)
                    near(snapshot['resolved_equity'],row['economics'][valuation], 'REVIEW_NEW_RAW_ACCOUNT_EQUITY')
                    work['evidence']['research_entry_audit'][key]=snapshot;snapshots+=1
                factor(prior,work);prior=row['economics']
                chain=digest(dict(previous=chain,session=day,state_sha256=row['state_sha256'],economics=row['economics']))
                need(chain==row['chain_sha256'], 'REVIEW_EVERY_NEW_FUNDED_FACTOR_AND_CHAIN')
                retry_summary=advance_retry(retries,row)
                report=stats.advance(day,{k:Decimal(v) for k,v in row['comparison_navs'].items()},
                    core_target=str(row['decision']['target_core_exposure']),month_end=dates[dates.index(day)+1][:7]!=day[:7])
                if report:report['slot_retries']=retry_summary;monthly.append(report)
                prior_state=dict(wealth_core=audit['closing_accounting']['wealth_core'],pending=audit['closing_accounting']['pending'])
                prior_hash=row['state_sha256']
            need(chain==current['chain'] and prior==current['economics']
                 and prior_hash==current['run']['state_sha256']
                 and stats.to_dict()==current['stats'] and retries==current['retries']
                 and monthly==suffixes['monthly'], 'REVIEW_ALL_NEW_REPORT_FACTOR_RETRY_AND_CHECKPOINT_STATE')
            outcome=read(evidence/'batch-outcome.json')
            need(outcome['source_cursor']==current['source_cursor'] and outcome['completed']==current['completed']
                 and outcome['original_own526_resumed_fresh'] is True and outcome['qualification_state_adopted'] is False
                 and outcome['actual_action_scope_checks']==checks
                 and outcome['actual_inherited_native_scope_guards']==native_checks
                 and outcome['actual_role_and_full_state_checks']==qualified['actual_role_and_full_state_checks'][:min(2,len(wanted))],
                 'REVIEW_FRESH_ORIGINAL526_ACTUAL_ROLES_AND_COMPLETE_SCOPE_PROOFS')
            attempted={}
            for actual,key in [('actual_role_and_full_state_checks','attempted_role_and_full_state_checks'),
                               ('actual_action_scope_checks','attempted_action_scope_checks'),
                               ('actual_inherited_native_scope_guards','attempted_inherited_native_scope_guards')]:
                attempted[key]=committed_attempts(outcome[actual],outcome[key],current['source_cursor'],next_session)
            need(outcome['attempted_role_and_full_state_checks']==qualified['actual_role_and_full_state_checks']
                 [:len(outcome['attempted_role_and_full_state_checks'])],
                 'REVIEW_ALL_ATTEMPTED_FIRST_TWO_FULL_STATE_AND_ROLES_RETAINED')
            for row in attempted['attempted_action_scope_checks']:
                matches=[a for a in records if a['action_id']==row['action_id'] and a['economic_session']==row['session']]
                need(len(matches)==1 and row==action_scope(current['run']['state'],matches[0],
                     qualified['target_independence_qualified'],qualified['held_target_holding_qualified']),
                     'REVIEW_UNCOMMITTED_ACTION_SCOPE_USES_ACTUAL_SAVED_PRIOR_STATE')
            for row in attempted['attempted_inherited_native_scope_guards']:
                sid=row['security_id'];key=(row['session'],sid)
                need(key in scopes and row==dict(session=row['session'],security_id=sid,unheld=True,
                     all_source_pending_absent=True,source_record_sha256=scopes[key])
                     and not any(e['security_id']==sid for e in current['run']['state']['wealth_core']['episodes'].values())
                     and not any(p['security_id']==sid for p in current['run']['state']['pending']),
                     'REVIEW_UNCOMMITTED_NATIVE_SCOPE_RETAINED_WITH_ACTUAL_SAVED_PRIOR_ROLES')
            pre_event_receipts(outcome['actual_pre_event_checkpoints'],checkpoints,checkpoint_files)
            complete=current['source_cursor']==END and current['completed']==526+MAXIMUM and len(wanted)==MAXIMUM
            need((outcome['status']=='COMPLETE_FACTUAL_BATCH_SEGMENT_PENDING_REVIEW')==complete,
                 'REVIEW_NO_GREEN_COMPLETE_STATUS_FOR_PARTIAL_PREFIX')
            need(not complete or (outcome['canonical_return_code']==0
                 and all(v['bytes']==0 for v in tails.values())), 'REVIEW_COMPLETE101_ONLY_WITH_ZERO_CURRENT_TAILS')
            recovered=preserve_tails(evidence/'book',pre);verify_correlation(evidence)
            result=dict(schema='research.p01-factual-batch-suffix-review/1',
                status='FACTUAL_BATCH_ACTUAL_COMMITTED_SUFFIX_REVIEWED_PENDING_CLIENT',checkpoint_sha256=current['sha256'],
                source_cursor=current['source_cursor'],completed=current['completed'],new_financial_rows=len(wanted),
                segment_complete=complete,new_accounting_snapshots=snapshots,new_monthly_reports=len(monthly),
                all_new_monthly_and_retry_checkpoint_state_exact=True,old_financial_admission_reused_sha256=ROOT_ADMISSION,
                old_accounting_snapshots_recomputed=0,old_audits_repeated=False,source_epoch_boundary_reemitted=False,
                actual_old_source_event_count=source_event_count(before_watch),actual_current_source_event_count=source_event_count(after_watch),
                old10_inputs_unchanged=True,new_input_sha256=loaded.sha256,checked_new_source_checkpoints=checked,
                all_historical_checkpoint_gzip_bytes_preserved=True,all_new_accounting_factors_and_chains_verified=True,
                grouped_action_checks=checks,inherited_native_scope_checks=native_checks,
                attempted_records_preserved_and_committed_subsets_exact=True,uncommitted_attempts=attempted,
                actual_pre_event_checkpoint_receipts=outcome['actual_pre_event_checkpoints'],
                actual_grouped_action_flows=action_flows(ledger,records),prefixes=prefixes,current_tails=tails,
                synthetic_component_full_state_wires_restored=len(wires),
                recovered_tails=recovered,qualification_state_adopted=False,financial_predecessor_admitted=False,
                full_p01_comparison_complete=False,production_contacted=False)
            save(out/'factual-batch-financial-review.json',result)
            return result


main=review
