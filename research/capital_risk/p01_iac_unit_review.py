"""Stopped OWN628 input12 suffix review; canonical restore is hosted-only."""
from copy import deepcopy
from decimal import Decimal
import gzip
import io
import json
import math
from pathlib import Path

from p01_iac_unit_parent import OUTER,INNER,STATE,INPUT as ORIGINAL_INPUT,ROOT_ADMISSION,need,sha,digest
from p01_iac_unit_contract import EVENT,FIRST,END,MAXIMUM
from p01_native_resume_review import prefix,journal_suffixes,role_rows,held_quotes


def read(path):
    path=Path(path);raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.name.endswith('.gz') else raw)


def same_resume_identity(parent,adopted,current):
    need(parent['sha256']==OUTER and parent['completed']==628 and parent['source_cursor']=='2020-06-30'
         and parent['run']['checkpoint_sha256']==INNER and parent['run']['state_sha256']==STATE
         and parent['run']['input_sha256']==ORIGINAL_INPUT and len(parent['repairs'])==11,
         'REVIEW_ONLY_EXACT_ADMITTED628_PARENT')
    need(adopted['base']==current['base']==parent['base'] and len(adopted['repairs'])==12
         and adopted['repairs'][:11]==parent['repairs'] and current['repairs']==adopted['repairs']
         and adopted['run']['input_sha256']==current['run']['input_sha256']
         ==digest(dict(base=current['base'],repairs=current['repairs'])),
         'REVIEW_CURRENT516_OLD_ELEVEN_AND_EXACT_TWELFTH_INPUT')
    need(type(current['completed']) is int and 628<=current['completed']<=628+MAXIMUM
         and parent['source_cursor']<=current['source_cursor']<=END,
         'REVIEW_BOUNDED_ACTUAL_COMMITTED_CURSOR')


def boundary_counts(old_rows,suffix,event):
    source='pooled-source-boundary/1';input_kind='research.pooled-action-successor/1'
    need(type(event) is dict and event.get('schema')==input_kind
         and [r for r in suffix if r.get('schema') in (source,input_kind)]==[event],
         'REVIEW_UNCHANGED_SOURCE_AND_ONE_ACTUAL_CANONICAL_INPUT_EVENT')
    return dict(source_before=sum(r.get('schema')==source for r in old_rows),
        source_after=sum(r.get('schema')==source for r in [*old_rows,*suffix]),
        inputs_before=sum(r.get('schema')==input_kind for r in old_rows),
        inputs_after=sum(r.get('schema')==input_kind for r in [*old_rows,*suffix]))


def financial_chain(parent,zero,daily,current):
    event=zero['input_event'];adopted=zero['input_checkpoint']
    need(type(parent['chain']) is str and len(parent['chain'])==64 and type(event) is dict
         and event.get('schema')=='research.pooled-action-successor/1'
         and event['predecessor_checkpoint_sha256']==parent['run']['checkpoint_sha256']
         and event['predecessor_input_sha256']==parent['run']['input_sha256']
         and event['successor_input_sha256']==adopted['run']['input_sha256']
         and event['unchanged_through']==parent['source_cursor']
         and event['earliest_affected_session']==EVENT,
         'REVIEW_REAL_PARENT628_AND_ACTUAL_INPUT_EVENT_CHAIN_ORIGIN')
    chain=digest(dict(previous=parent['chain'],event=event))
    need(chain==adopted['chain'],'REVIEW_CANONICAL_INPUT_ZERO_CHAIN')
    for row in daily:
        need(row['phase']=='MEASURED' and row['input_sha256']==adopted['run']['input_sha256'],
             'REVIEW_EVERY_NEW_ROW_TWELFTH_INPUT_IDENTITY')
        chain=digest(dict(previous=chain,session=row['session'],state_sha256=row['state_sha256'],
            economics=row['economics']))
        need(chain==row['chain_sha256'],'REVIEW_NEW_DAILY_CHAIN_FROM_ACTUAL_INPUT_ZERO')
    need(chain==current['chain'],'REVIEW_COMPLETE_CURRENT_COMMITTED_CHAIN')
    return chain


def committed_attempts(actual,attempted,cursor,next_session,allowed_uncommitted=None):
    need(type(actual) is list and type(attempted) is list
         and all(type(r) is dict and type(r.get('session')) is str for r in attempted),
         'REVIEW_ATTEMPT_RECORD_SCHEMA')
    days=[r['session'] for r in attempted]
    allowed={next_session} if allowed_uncommitted is None else set(allowed_uncommitted)
    need(days==sorted(days) and all(EVENT<=d<=END and (d<=cursor or d in allowed) for d in days)
         and actual==[r for r in attempted if r['session']<=cursor],
         'REVIEW_EXACT_COMMITTED_FILTER_OF_ALL_RETAINED_ATTEMPTS')
    return [r for r in attempted if r['session']>cursor]


def first_two(adopted,qualified,financial,current,next_session,allowed_uncommitted=None):
    path=qualified['actual_components'];reference=qualified['reference_components']
    need(set(qualified)=={'schema','reference_components','actual_components','reference_qualifier_checkpoint',
         'qualifier_checkpoint','action_checks','inherited_native_scope_checks','source_unit_scope_checks',
         'unit_window_anchor_checks','pre_event_checkpoints','financial_authority','qualification_state_adopted'}
         and qualified['schema']=='research.p01-iac-unit-actual-two-session-component/1'
         and path==reference and [r['session'] for r in path]==list(FIRST)
         and qualified['financial_authority'] is False and qualified['qualification_state_adopted'] is False,
         'REVIEW_ALL_REFERENCE_FAST_COMPONENT_FIELDS_EXACT_TWO_SESSIONS')
    previous=adopted['run']
    for row in path:
        need(set(row)=={'session','prior_checkpoint','publication','checkpoint'}
             and row['prior_checkpoint']==previous and row['publication']['session']==row['session']
             and row['checkpoint']['state']['last_processed_session']==row['session'],
             'REVIEW_FULL_QUALIFIER_PRIOR_PUBLICATION_AND_NEXT_STATE_ADJACENCY')
        previous=row['checkpoint']
    need(qualified['reference_qualifier_checkpoint']==qualified['qualifier_checkpoint']
         and qualified['qualifier_checkpoint']['run']==path[-1]['checkpoint']
         and qualified['qualifier_checkpoint']['completed']==630
         and qualified['qualifier_checkpoint']['source_cursor']==FIRST[-1],
         'REVIEW_REFERENCE_FAST_FULL_OUTER_QUALIFIER_CHECKPOINTS')
    actual,attempted=financial['actual_components'],financial['attempted_components']
    need(set(financial)=={'actual_components','attempted_components','financial_authority','qualification_state_adopted'}
         and actual==path[:len(actual)] and len(actual)==min(2,current['completed']-628)
         and attempted==path[:len(attempted)] and len(attempted)<=2
         and financial['financial_authority'] is False and financial['qualification_state_adopted'] is False,
         'REVIEW_FRESH628_ENTIRE_FIRST_TWO_PATH_NO_QUALIFIER_ADOPTION_OR_FIELD_EXCLUSION')
    return committed_attempts(actual,attempted,current['source_cursor'],next_session,allowed_uncommitted)


def complete_lines(raw,label):
    """A trailing fragment is evidence, never an attempted JSON record."""
    cut=raw.rfind(b'\n')+1;records=[]
    from p01_iac_unit_contract import unique
    def invalid(value):raise ValueError('REFUSED_P01_IAC628_NONFINITE_TAIL_JSON')
    for line in raw[:cut].splitlines(keepends=True):
        value=json.loads(line,object_pairs_hook=unique,parse_constant=invalid)
        need(type(value) is dict,'REVIEW_COMPLETE_TAIL_RECORD_OBJECT:'+label);records.append(value)
    fragment=raw[cut:]
    return records,dict(bytes=len(raw),sha256=sha(raw),complete_bytes=cut,complete_records=len(records),
        incomplete_bytes=len(fragment),incomplete_sha256=sha(fragment),incomplete_bytes_parsed=False)


def bounded_tail(current,books,old_correlation,new_correlation,committed_rows,outcome,axis):
    """Source-bound actual attempts bound a contiguous, unadmitted tail."""
    cursor=current['source_cursor'];selected=[d for d in axis if EVENT<=d<=END];start=selected.index(cursor)+1 if cursor>=EVENT else 0
    parsed={};proofs={}
    for name,raw in books.items():
        cut=current['journals'][name]['bytes'];prefix(raw,current['journals'][name])
        parsed[name],proofs[name]=complete_lines(raw[cut:],name)
    need(not parsed['formation'],'REVIEW_NO_UNCOMMITTED_FORMATION_REPLAY')
    applications=outcome['actual_codec_applications'];refusals=outcome['actual_codec_refusals']
    preparations=outcome['attempted_unit_preparations'];guard_refusals=outcome['unit_guard_refusals']
    arrays=(applications,refusals,preparations,guard_refusals)
    for values in arrays:
        days=[v['session'] for v in values]
        need(days==sorted(set(days)) and all(d in selected for d in days),'REVIEW_ACTUAL_ATTEMPT_RECORD_ORDER_AND_BOUNDED_SOURCE_AXIS')
    compiled=[v['session'] for v in applications+refusals]
    need(len(compiled)==len(set(compiled)),'REVIEW_ONE_ACTUAL_APPLICATION_OR_REFUSAL_PER_SOURCE_DAY')
    all_days=[v['session'] for values in arrays for v in values];last=max(all_days) if all_days else None
    expected=None
    if last is not None:
        need(sorted(compiled)==selected[:selected.index(last)+1],
             'REVIEW_ACTUAL_COMPILER_ATTEMPTS_CONTIGUOUS_FROM_EVENT_NOT_ARBITRARY_FUTURE_DATE')
        fields=('codec_application_sha256','codec_refusal_sha256','prepared_window_sha256','guard_refusal_sha256')
        expected=dict(schema='research.p01-iac-unit-last-observed-attempt/1',session=last,financial_authority=False)
        for key,values in zip(fields,arrays):
            matches=[v for v in values if v['session']==last];expected[key]=digest(matches[0]) if matches else None
    need(outcome['last_observed_attempt']==expected,'REVIEW_EXACT_LAST_OBSERVED_ATTEMPT_FULL_PREIMAGES_NO_INFERRED_FAILURE')
    daily=parsed['daily'];days=[r['session'] for r in daily]
    need(days==selected[start:start+len(days)],'REVIEW_COMPLETE_DAILY_TAIL_CONTIGUOUS_NO_GAP_DUPLICATE_OR_REORDER')
    last_closed=days[-1] if days else cursor
    if last is not None:
        li=selected.index(last);ci=selected.index(last_closed) if last_closed>=EVENT else -1
        need(ci<=li<=ci+1,'REVIEW_LAST_OBSERVED_ATTEMPT_ONLY_CLOSED_TAIL_OR_ONE_NEXT_DAY')
        allowed=selected[start:li+1]
    else:
        need(not daily and not committed_rows,'REVIEW_NO_FINANCIAL_ROW_WITHOUT_OBSERVED_SOURCE_ATTEMPT');allowed=[]
    need(not days or days==allowed[:len(days)],'REVIEW_DAILY_TAIL_BOUND_BY_OBSERVED_ATTEMPT')
    chain=current['chain'];state=current['run']['state_sha256'];input_sha=current['run']['input_sha256']
    for row in daily:
        need(row['phase']=='MEASURED' and row['input_sha256']==input_sha
             and type(row['state_sha256']) is str and len(row['state_sha256'])==64,
             'REVIEW_UNCOMMITTED_DAILY_INPUT_AND_STATE_IDENTITY')
        chain=digest(dict(previous=chain,session=row['session'],state_sha256=row['state_sha256'],economics=row['economics']))
        need(row['chain_sha256']==chain,'REVIEW_EVERY_UNCOMMITTED_DAILY_CHAIN_FROM_CURRENT_COMMIT')
        state=row['state_sha256']
    for row in parsed['watch']:
        day=row.get('session');need(day in allowed,'REVIEW_WATCH_STRING_CANNOT_EXTEND_ACTUAL_ATTEMPT_BOUND')
        if row.get('schema')=='research.pooled-pre-event/1':
            need(set(row)=={'schema','session','predecessor','events'} and row['predecessor']==axis[axis.index(day)-1]
                 and type(row['events']) is dict,'REVIEW_EXACT_FROZEN_PRE_EVENT_WATCH_SCHEMA')
        else:
            need(set(row)=={'session','terminal_state','warnings'} and type(row['terminal_state']) is dict
                 and type(row['warnings']) is list,'REVIEW_EXACT_FROZEN_POST_ADVANCE_WATCH_SCHEMA')
    watch_days=[r['session'] for r in parsed['watch']]
    need(watch_days==sorted(watch_days),'REVIEW_UNCOMMITTED_WATCH_ORDER')
    tags=[(r['session'],'pre' if 'schema' in r else 'post') for r in parsed['watch']]
    need(len(tags)==len(set(tags)),'REVIEW_NO_DUPLICATE_UNCOMMITTED_WATCH_PHASE')
    for row in parsed['monthly']:
        need(set(row)=={'schema','session','measurement_start','elapsed_calendar_days','cagr_calendar_year_days',
             'primary','series','targets','scope','slot_retries'}
             and row['schema']=='sentinel.behavior-integrity-monthly/1' and row['session'] in days
             and axis[axis.index(row['session'])+1][:7]!=row['session'][:7],
             'REVIEW_UNCOMMITTED_MONTHLY_RECORD_REQUIRES_ACTUAL_CLOSED_TAIL_MONTH_END')
    month_days=[r['session'] for r in parsed['monthly']]
    month_axis=[d for d in days if axis[axis.index(d)+1][:7]!=d[:7]]
    need(month_days==month_axis[:len(month_days)],'REVIEW_UNCOMMITTED_MONTHLY_ORDER_NO_DUPLICATE_OR_SKIP')
    need(new_correlation.startswith(old_correlation) and (not old_correlation or old_correlation.endswith(b'\n')),
         'REVIEW_ENTIRE_OLD_CORRELATION_RAW_PREFIX')
    correlations,corrproof=complete_lines(new_correlation[len(old_correlation):],'correlation')
    old=old_correlation.splitlines();corrchain=json.loads(old[-1])['chain_sha256'] if old else digest('system-optimization-002/raw-correlation/1')
    actual_rows={r['session']:r for r in [*committed_rows,*daily]};expected_days=[r['session'] for r in committed_rows]+allowed
    corr_days=[r['session'] for r in correlations]
    need(corr_days==expected_days[:len(corr_days)] and set(actual_rows)<=set(corr_days),
         'REVIEW_CORRELATION_AXIS_CONTIGUOUS_ALL_CLOSED_ROWS_AND_ONLY_BOUNDED_ATTEMPT')
    previous=STATE;unavailable=[]
    for row in correlations:
        need(set(row)=={'schema','session','publication_version','input_sha256','prior_state_sha256','next_state_sha256','material','chain_sha256'}
             and row['schema']=='research.system-campaign-correlation-input/1'
             and row['input_sha256']==input_sha and type(row['publication_version']) is int and type(row['material']) is dict,
             'REVIEW_COMPLETE_CORRELATION_RECORD_SOURCE_SCHEMA_AND_INPUT')
        body=dict(row);actual=body.pop('chain_sha256');corrchain=digest(dict(previous=corrchain,record=body))
        need(corrchain==actual and row['prior_state_sha256']==previous,
             'REVIEW_EVERY_NEW_COMMITTED_AND_UNCOMMITTED_CORRELATION_CHAIN_AND_STATE_ADJACENCY')
        if row['session'] in actual_rows:
            need(row['next_state_sha256']==actual_rows[row['session']]['state_sha256'],
                 'REVIEW_CORRELATION_EXACT_COMPLETE_DAILY_STATE')
        else:unavailable.append(dict(session=row['session'],status='UNADMITTED_ATTEMPTED_FULL_STATE_NOT_EXPORTED'))
        previous=row['next_state_sha256']
    return dict(allowed_uncommitted_sessions=allowed,complete_daily_tail_rows=daily,stream_fragments=proofs,
        last_observed_attempt=expected,uncommitted_full_states=unavailable,
        correlation=dict(new_committed_records=len(committed_rows),uncommitted_records=[r for r in correlations if r['session']>cursor],
            entire_old_prefix_unchanged=True,old_record_arithmetic_recomputed=0,raw_tail=corrproof),
        attempted_financial_authority='UNADMITTED',tail_rows_promoted_to_financial_predecessor=False)


def normalization_records(records,rows,normalizer,native_bars):
    """Verify only actually used records against the accepted scalar order."""
    need(type(records) is list and all(type(r) is dict and type(r.get('session')) is str for r in records),
         'REVIEW_NORMALIZER_ACTUAL_RECORD_SCHEMA')
    if not records:return dict(records=0,source_days=[],all_raw_fields_unchanged=True)
    days=[r['session'] for r in records];last=max(days)
    need(days==sorted(days),'REVIEW_NORMALIZER_ACTUAL_APPLICATION_ORDER')
    native=float.fromhex(normalizer['initial_native_factor_hex'])
    combined=float.fromhex(normalizer['initial_combined_factor_hex'])
    multiplier=float.fromhex(normalizer['original_signal_multiplier_hex'])
    need(native==combined==multiplier==1.,'REVIEW_EXACT_ADMITTED_FORWARD_UNIT_ORIGIN')
    need(all(rows[i]['session']<rows[i+1]['session'] for i in range(len(rows)-1)),
         'REVIEW_ORIGINAL_SOURCE_ROW_ORDER_NOT_SORTED_OR_DEDUPLICATED')
    expected={};first=True
    for row in rows:
        day=row['session']
        if day<EVENT:continue
        if day>last:break
        need(row['security_id']=='984687283821901795' and day>=EVENT and day not in expected
             and (not first or day==EVENT),'REVIEW_UNIQUE_FIRST_EVENT_SOURCE_DOMAIN')
        split=float(row['split_ratio']);need(math.isfinite(split) and split>0
            and (day!=EVENT or split==1.),'REVIEW_FINITE_EXACT_NATIVE_SPLIT_BASIS')
        native*=split;combined*=split
        if day==EVENT:combined*=float('2.1584')
        raw=None if row['raw_close']=='' else float(row['raw_close'])
        signal=None if row['signal_close']=='' else float(row['signal_close'])
        if raw is None or signal is None:
            need(day!=EVENT and raw is signal is None,'REVIEW_NO_MIXED_OR_EVENT_MISSING_UNIT_PRICE')
            logical=None
        else:
            need(math.isfinite(raw) and raw>=0 and math.isfinite(signal) and signal>=0
                 and signal*multiplier==raw*native,'REVIEW_EXACT_NATIVE_SIGNAL_RAW_CUMULATIVE_FACTOR')
            logical=raw*combined
        expected[day]=dict(session=day,native_factor_hex=native.hex(),combined_factor_hex=combined.hex(),
            logical_signal_close=logical,effective_split_ratio=split*float('2.1584') if day==EVENT else split,
            raw_row_sha256=digest(row),native_basis_exact=True,canonical_factor_then_raw_order=True,
            legal_factor_insertions=1)
        first=False
    extra={'native_bar','logical_bar','native_source_metadata','child_or_cash_value_added',
        'all_raw_price_volume_and_other_fields_unchanged','source_preimage_authenticated','derivation_before_buffer_append'}
    for record in records:
        day=record['session'];need(day in expected and day in native_bars,'REVIEW_USED_SOURCE_ROW_PRESENT')
        entry=expected[day];before=native_bars[day]
        need(set(record)==set(entry)|extra and all(record[k]==v for k,v in entry.items())
             and record['native_bar']==before
             and record['logical_bar']==dict(before,signal_close=entry['logical_signal_close'],
                 split_ratio=entry['effective_split_ratio'])
             and record['child_or_cash_value_added'] is False
             and all(record[k] is True for k in ('all_raw_price_volume_and_other_fields_unchanged',
                 'source_preimage_authenticated','derivation_before_buffer_append')),
             'REVIEW_ENTIRE_ACTUAL_NATIVE_LOGICAL_RECORD_ONLY_TWO_FIELDS_AND_NO_CHILD_VALUE')
    return dict(records=len(records),source_days=sorted(set(days)),all_raw_fields_unchanged=True,
        exact_canonical_factor_then_raw_order=True,child_value_added=False)


def no_source_entitlement_posting(path):
    event=next((r for r in path if r['session']==EVENT),None)
    if event is None:return dict(event_observed=False,source_entitlement_events=0)
    before=event['prior_checkpoint']['state']['ledger']['events']
    after=event['checkpoint']['state']['ledger']['events']
    need(after[:len(before)]==before,'REVIEW_UNIT_EVENT_ENTIRE_OLD_LEDGER_PREFIX')
    need(not any(r.get('security_id')=='984687283821901795'
        or (r.get('detail') or {}).get('parent_security_id')=='984687283821901795'
        for r in after[len(before):]),'REVIEW_UNHELD_UNIT_PACKAGE_CANNOT_CREATE_PROXY_CASH_OR_ENTITLEMENT')
    return dict(event_observed=True,source_entitlement_events=0,ordinary_target_events_filtered=False)


def publication_metadata(records,path):
    publications={r['session']:r['publication'] for r in path};checked=[]
    for record in records:
        day=record['session']
        if day not in publications:continue
        need(record['native_source_metadata']==publications[day]['meta']['984687283821901795'],
             'REVIEW_ENTIRE_UNCHANGED_NATIVE_METADATA_EQUALS_ACTUAL_PUBLICATION')
        checked.append(day)
    need(sorted(set(checked))==[r['session'] for r in path],
         'REVIEW_EVERY_ACTUAL_COMPONENT_NATIVE_METADATA_PREIMAGE')
    return dict(actual_full_publication_sessions=sorted(set(checked)),
        later_native_metadata_preserved_by_source_pinned_nonbar_object_identity=True,
        rawrow_classifier_shortcut_used=False)


def input_zero_receipt(rows,adopted,encoder):
    need(rows and rows[0]['session']==EVENT,'REVIEW_FIRST_QUALIFIER_PRE_EVENT_UNIT_BOUNDARY')
    output=io.BytesIO()
    with gzip.GzipFile(filename='',fileobj=output,mode='wb',compresslevel=1,mtime=0) as zipped:
        zipped.write(encoder(adopted))
    raw=output.getvalue()
    expected=dict(session=EVENT,path=EVENT+'-'+adopted['sha256']+'.json.gz',outer_sha256=adopted['sha256'],
        inner_sha256=adopted['run']['checkpoint_sha256'],state_sha256=adopted['run']['state_sha256'],
        prior_session='2020-06-30',current_saved_identical_before_guard=True,current_file=dict(bytes=len(raw),sha256=sha(raw)))
    need(rows[0]==expected,'REVIEW_ENTIRE_ACTUAL_QUALIFIER_INPUT_ZERO_GZIP_RECEIPT')


def source_scope(state,day):
    """Only the unsupported pre-event source unit is excluded."""
    if day!=EVENT:return []
    sid='984687283821901795';wealth=state['wealth_core'];pending=state['pending'];ledger=state['ledger']
    need(type(wealth['episodes']) is dict and type(wealth['slots']) is dict and type(pending) is list
         and all(type(p) is dict and type(p.get('security_id')) is str for p in pending),
         'REVIEW_FULL_SOURCE_SCOPE_ROLES_AND_PENDING')
    need(not any(e['security_id']==sid for e in wealth['episodes'].values())
         and not any(p['security_id']==sid for p in pending),'REVIEW_PRE_EVENT_OLD_SOURCE_ROLES_UNSUPPORTED')
    ticker=state['feed']['series'].get(sid,{}).get('ticker')
    need(not any(s.get('reserved_for')==sid or s.get('reserved_for') is None
         and ticker and s.get('reserved_ticker')==ticker for s in wealth['slots'].values()),
         'REVIEW_PRE_EVENT_SOURCE_RESERVATION_OR_ORPHAN_RESERVATION')
    need(set(ledger)=={'events','receivables'} and type(ledger['receivables']) is list
         and all(type(r) is dict and type(r.get('security_id')) is str for r in ledger['receivables'])
         and not any(r['security_id']==sid for r in ledger['receivables']),
         'REVIEW_PRE_EVENT_SOURCE_LEDGER_CLAIMS')
    need(all(type(wealth.get(k,{})) is dict and sid not in wealth.get(k,{}) for k in
         ('unresolved_terminals','terminal_pending_terms','terminal_pending_sessions','terminal_carry_audit')),
         'REVIEW_PRE_EVENT_SOURCE_UNRESOLVED_OR_CARRY_CLAIMS')
    targets={target:dict(episodes={k:deepcopy(e) for k,e in wealth['episodes'].items() if e['security_id']==target},
        pending=[deepcopy(p) for p in pending if p['security_id']==target],
        reservations=[deepcopy(s) for s in wealth['slots'].values() if s.get('reserved_for')==target],
        receivables=[deepcopy(r) for r in ledger['receivables'] if r['security_id']==target])
        for target in ('517224929580411308','369995575874917058')}
    return [dict(session=day,source_security_id=sid,source_unheld=True,source_any_pending_absent=True,
        source_exit_flags_absent=True,source_reservations_absent=True,source_claims_absent=True,
        source_selected=sid in state['median5']['selected'],independent_target_roles=targets)]


def unit_window(record,rows,normalizer,window_length,*,checkpoint=None,publication=None,axis=None,prepared=False):
    """Exact native rows and forward domains; no synthetic ideal-ratio check."""
    day=record['session'];sid='984687283821901795'
    need(type(record.get('source_present')) is bool and (prepared or type(record.get('source_series_retained')) is bool),
         'REVIEW_ACTUAL_WINDOW_AND_RETAINED_SERIES_FLAGS')
    retained=False if prepared else record['source_series_retained']
    need(not prepared or checkpoint is None,'REVIEW_PREPARATION_IS_NOT_A_RETAINED_RUNTIME_CLAIM')
    if checkpoint is not None:
        need(record['source_series_retained']==(sid in checkpoint['state']['feed']['series']),
             'REVIEW_ACTUAL_RETAINED_OR_PRUNED_SOURCE')
    base={'session','source_present'}| (set() if prepared else {'source_series_retained'})
    if not record['source_present']:
        need(set(record)==base|{'unit_factor_not_applied_to_other_ids'}
             and record['unit_factor_not_applied_to_other_ids'] is True,
             'REVIEW_ABSENT_SOURCE_PUBLICATION_NO_INVENTED_WINDOW')
        if publication is not None:
            need(not any(s['security_id']==sid for s in publication['window_features']['signals']),
                 'REVIEW_ACTUAL_SOURCE_ABSENT_FROM_PUBLICATION')
        return
    keys=base|{'window_length','indices','sessions','logical_signal_closes','raw_closes','raw_compatible_volumes',
        'native_row_sha256','actual_publication_signal','full_window_before_feature_bound','raw_liquidity_domain_unchanged'}
    if retained:keys.add('actual_retained_basis')
    need(set(record)==keys and record['window_length']==window_length and type(window_length) is int
         and len(record['sessions'])==window_length and record['sessions']==sorted(set(record['sessions']))
         and record['sessions'][-1]==day and len(record['indices'])==window_length
         and record['indices']==sorted(set(record['indices']))
         and record['full_window_before_feature_bound'] is True and record['raw_liquidity_domain_unchanged'] is True,
         'REVIEW_ENTIRE_CAUSAL_FEATURE_WINDOW_SCHEMA_AXIS_AND_SOURCE_LENGTH')
    if axis is not None:
        first=axis.index(record['sessions'][0]);start=record['indices'][0]
        need([v-start for v in record['indices']]==[axis.index(d)-first for d in record['sessions']],
             'REVIEW_EVERY_WINDOW_INDEX_MATCHES_EXACT_CANONICAL_CALENDAR')
    source={r['session']:r for r in rows};logical={};n=float.fromhex(normalizer['initial_native_factor_hex'])
    c=float.fromhex(normalizer['initial_combined_factor_hex']);m=float.fromhex(normalizer['original_signal_multiplier_hex'])
    need(n==c==m==1. and all(rows[i]['session']<rows[i+1]['session'] for i in range(len(rows)-1)),
         'REVIEW_WINDOW_ADMITTED_ORIGIN_AND_NATIVE_ORDER')
    value=lambda v:None if v=='' or v is None else float(v)
    for row in rows:
        date=row['session']
        if date>day:break
        if date<EVENT:logical[date]=value(row['signal_close']);continue
        split=value(row['split_ratio']);n*=split;c*=split
        if date==EVENT:c*=float('2.1584')
        raw=value(row['raw_close']);signal=value(row['signal_close'])
        need(raw is signal is None or raw is not None and signal is not None and signal*m==raw*n,
             'REVIEW_WINDOW_EXACT_NATIVE_BASIS')
        logical[date]=None if raw is None else raw*c
    expected=[source[d] for d in record['sessions']]
    need(record['logical_signal_closes']==[logical[r['session']] for r in expected]
         and record['raw_closes']==[value(r['raw_close']) for r in expected]
         and record['raw_compatible_volumes']==[value(r['raw_compatible_volume']) for r in expected]
         and record['native_row_sha256']==[digest(r) for r in expected],
         'REVIEW_EVERY_WINDOW_RAW_LOGICAL_VOLUME_AND_PREIMAGE')
    signal=record['actual_publication_signal']
    need(signal['security_id']==sid and signal['closes'][-1]==record['logical_signal_closes'][-1]
         and signal['raw_close']==record['raw_closes'][-1],
         'REVIEW_CURRENT_CERTIFIED_SIGNAL_PRICE_DOMAINS')
    if publication is not None:
        need([s for s in publication['window_features']['signals'] if s['security_id']==sid]==[signal],
             'REVIEW_ENTIRE_ACTUAL_PUBLICATION_SIGNAL')
    if retained:
        basis=record['actual_retained_basis'];raw=record['raw_closes'][-1];close=record['logical_signal_closes'][-1]
        need(set(basis)=={'split_factor','signal_basis_multiplier','vendor_basis_multiplier','signal_basis_anchor'}
             and basis['signal_basis_multiplier']==basis['vendor_basis_multiplier']==1.
             and basis['signal_basis_anchor']==[day,raw,close]
             and (raw is None or raw<=0 or basis['split_factor']==close*1./raw),
             'REVIEW_EXACT_CANONICAL_PUBLISHED_QUOTIENT_AND_RETAINED_ANCHOR')
    if checkpoint is not None:
        series=checkpoint['state']['feed']['series'].get(sid)
        need(record['source_series_retained']==(series is not None),'REVIEW_ACTUAL_RETAINED_OR_PRUNED_SOURCE')
        if series is not None:
            need(series['signal_closes'][-1]==record['logical_signal_closes'][-1]
                 and record['actual_retained_basis']==dict(split_factor=series['split_factor'],
                    signal_basis_multiplier=series.get('signal_basis_multiplier',1.),
                    vendor_basis_multiplier=series.get('vendor_basis_multiplier',1.),
                    signal_basis_anchor=series['signal_basis_anchor']),
                 'REVIEW_FULL_RUNTIME_RETAINED_SOURCE_BASIS')


def source_proof(value,contract,origin,members):
    need(set(value)=={'schema','source_contract','origin_basis','source_members','reference_applications',
         'fast_applications','reference_refusals','fast_refusals','financial_authority'}
         and value['schema']=='research.p01-iac-unit-normalization-source-proof/1'
         and value['source_contract']==contract
         and value['origin_basis']==dict(source_series=origin,source_series_sha256=digest(origin),original_outer_sha256=OUTER)
         and value['source_members']==members and value['financial_authority'] is False,
         'REVIEW_WHOLE_SOURCE_PROOF_EXACT_516_ORIGIN_AND_ORIGINAL_MEMBER_ORDER')


def zero_proof(value,parent,event,input_sha,pause_sha):
    adopted=value['input_checkpoint'];source=value['source'];paused=value['input']
    need(set(value)=={'schema','source','epoch_checkpoint','input','input_checkpoint','input_event','prefixes',
         'input_document_sha256','successor_input_sha256','financial_authority','financial_predecessor_authorized',
         'source_epoch_boundary_reemitted','input_adoptions','old_eleven_input_bytes_unchanged'}
         and value['schema']=='research.p01-iac-unit-zero-boundaries/1' and value['epoch_checkpoint']==parent
         and value['input_event']==event and value['input_document_sha256']==input_sha
         and value['successor_input_sha256']==adopted['run']['input_sha256']
         and value['financial_authority'] is value['financial_predecessor_authorized'] is False
         and value['source_epoch_boundary_reemitted'] is False
         and type(value['input_adoptions']) is int and value['input_adoptions']==1
         and value['old_eleven_input_bytes_unchanged'] is True
         and value['prefixes']=={n:dict(before=c,after=adopted['journals'][n]) for n,c in parent['journals'].items()},
         'REVIEW_ENTIRE_ACTUAL_EPOCH_AND_INPUT_ZERO_ENVELOPE')
    need(source==dict(status='OWN628_RETAINED_EPOCH_CANONICAL_STARTUP_ZERO_SESSIONS',
        inherited_generic_status='OWN526_RETAINED_EPOCH_CANONICAL_STARTUP_ZERO_SESSIONS',generic_pause_source_sha256=pause_sha,
        outer_sha256=OUTER,inner_sha256=INNER,state_sha256=STATE,input_sha256=ORIGINAL_INPUT,checkpoint_writes=3,
        financial_sessions_advanced=0,attempted_financial_transitions=0,full_checkpoint_and_journals_unchanged=True,
        source_boundary_reemitted=False,financial_predecessor_authorized=False),
        'REVIEW_EXACT_ACTUAL628_GENERIC_ZERO_SOURCE_PROVENANCE')
    need(paused==dict(status='CANONICAL_INPUT_STARTUP_PAUSED_WITH_ZERO_FINANCIAL_SESSIONS',
        canonical_backtest_startup_invoked=True,financial_sessions_advanced=0,attempted_financial_transitions=0,
        input_adoptions=1,canonical_adoption_checkpoint_writes=2,original_checkpoint_sha256=OUTER,
        qualification_checkpoint_sha256=adopted['sha256'],checkpoint_session='2020-06-30',completed=628,
        exact_canonical_boundary_event=event,all_financial_and_controller_state_unchanged=True,
        financial_resume_from_this_copy_authorized=False,production_contacted=False),
        'REVIEW_EXACT_CANONICAL_PAUSE_WITH_ONE_INPUT_AND_ZERO_FINANCIAL_ADVANCE')


def complete_status(outcome,current,new_rows,tails,correlation_tails):
    complete=current['source_cursor']==END and current['completed']==628+MAXIMUM and new_rows==MAXIMUM
    need((outcome['status']=='COMPLETE_IAC_UNIT_SEGMENT_PENDING_REVIEW')==complete
         and (complete or outcome['status']=='IAC_UNIT_PARTIAL_OR_REFUSAL_PRESERVED'),
         'REVIEW_NO_COMPLETE_STATUS_FOR_PARTIAL_FINANCIAL_PREFIX')
    need(not complete or outcome['canonical_return_code']==0 and all(t['bytes']==0 for t in tails.values())
         and not correlation_tails,'REVIEW_COMPLETE251_ONLY_RETURN_ZERO_AND_ZERO_ALL_CURRENT_TAILS')
    return complete


def qualification_report(value,expected):
    need(set(value)=={'schema','reference','fast','reference_equals_fast','financial_authority','qualification_state_adopted'}
         and value['schema']=='research.p01-iac-unit-actual-accounting-and-report/1'
         and value['reference']==value['fast']==expected and value['reference_equals_fast'] is True
         and value['financial_authority'] is False and value['qualification_state_adopted'] is False,
         'REVIEW_ENTIRE_REFERENCE_FAST_CURRENT_REPORT_AND_INDEPENDENT_RAW_ACCOUNTING')


def financial_report(value,expected,new_rows):
    status='ACTUAL_CURRENT_UNIT_ACCOUNTING_AND_REPORT_VERIFIED' if new_rows else 'NO_NEW_COMMITTED_ACCOUNTING_REPORT_OLD_ADMISSION_REUSED'
    need(set(value)=={'schema','status','new_committed_transitions','current','financial_authority','qualification_state_adopted'}
         and value['schema']=='research.p01-iac-unit-current-accounting-and-report/1' and value['status']==status
         and type(value['new_committed_transitions']) is int and value['new_committed_transitions']==new_rows
         and value['current']==expected and (new_rows>0 or expected is None)
         and value['financial_authority'] is False and value['qualification_state_adopted'] is False,
         'REVIEW_ACTUAL_SAVED_CURRENT_REPORT_ONLY_OR_ZERO_OLD_ADMISSION_REUSE')


def current_report(checkpoint,policy,quote,actions):
    """Read-only canonical report and unchanged whole-ledger evaluator, hosted."""
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import runtime
    from stock_strategy_shared.wealth_core import terminal,ledger
    from stock_strategy_shared.wealth_core.state import PortfolioState
    from stock_strategy_shared.wealth_core.marks import Mark,MarkStatus
    from stock_strategy_shared.wealth_core.funding import config
    from p01_factual_batch_accounting import reconcile
    run=runtime.restore(checkpoint,policy=policy,input_sha256=checkpoint['input_sha256'])
    need(runtime.checkpoint(run)==checkpoint,'REVIEW_CURRENT_REPORT_FULL_RUNTIME_RESTORE')
    before=runtime.checkpoint(run);actual=deepcopy(run.state.ledger)
    closing=deepcopy(run.state.last_evidence['research_entry_audit']['closing_accounting'])
    need(closing['ledger'].pop('event_count')==len(actual['events']),
         'REVIEW_CURRENT_REPORT_ACTUAL_ENTIRE_LEDGER_COUNT')
    closing['ledger']['events']=deepcopy(actual['events']);independent=reconcile(closing,quote,actions)
    marks={}
    for sid,value in closing['prices'].items():
        status=MarkStatus(value['status']);params={}
        if status is MarkStatus.CURRENT:params['raw_mark_close']=value['raw_price']
        elif status is MarkStatus.PENDING_TERMS_CARRIED:params['carried_raw_close']=value['raw_price']
        marks[sid]=Mark(security_id=sid,status=status,**params)
    report=terminal.final_report(session=run.state.last_processed_session,
        state=PortfolioState.from_dict(closing['wealth_core']),marks=marks,ledger=ledger.Ledger.from_dict(actual),
        cfg=config(policy)).to_dict()
    need(runtime.checkpoint(run)==before,'REVIEW_CURRENT_REPORT_COMPLETE_STATE_UNMUTATED')
    return dict(canonical_report=report,independent_accounting=independent,actual_ledger=actual,
        full_state_unchanged_by_report=True)


def synthetic_component(value,contract,origin,rows,configuration,source_map,post_event_state,normalize_state):
    """Read complete saved wires and scalar results; never run their phases."""
    need(set(value)=={'schema','status','source_contract','source_files','origin_basis_sha256','configuration',
        'normalizer_cases','target_cases','post_event_new_unit_case','negative_cases','source_scope_falsifiers','normalizer_qualified',
        'unit_target_independence_qualified','source_scope_falsifiers_qualified','positions_and_orders_synthetic',
        'normalization_observations_from_authenticated_frozen_input','actual_future_roles_claimed',
        'financial_authority','qualification_state_adopted'}
        and value['schema']=='research.p01-iac-unit-synthetic-canonical-component/1'
        and value['status']=='UNIT_NORMALIZATION_AND_TARGET_SCOPE_QUALIFIED'
        and value['source_contract']==contract and value['origin_basis_sha256']==digest(origin)
        and value['configuration']==configuration and len(value['source_files'])==6
        and set(value['source_files'])=={'shared/stock_strategy_shared/wealth_core/'+n+'.py'
            for n in ('engine','ledger','funding','prices','marks','v5')}
        and all(source_map['successor_all_sources'].get(n)==h for n,h in value['source_files'].items())
        and all(value[k] is True for k in ('normalizer_qualified','unit_target_independence_qualified',
            'source_scope_falsifiers_qualified','positions_and_orders_synthetic',
            'normalization_observations_from_authenticated_frozen_input'))
        and all(value[k] is False for k in ('actual_future_roles_claimed','financial_authority','qualification_state_adopted')),
        'REVIEW_COMPLETE_SYNTHETIC_COMPONENT_SOURCE_SCOPE_AND_ACTUAL_PARENT_CONFIGURATION')
    cases=value['normalizer_cases'];need(set(cases)=={'observed_forward','feature_order','native_composition'},'REVIEW_ALL_THREE_NORMALIZER_COMPONENTS')
    selected=[r for r in rows if EVENT<=r['session']<=FIRST[-1]];factor=1.;reference=[]
    need([r['session'] for r in selected]==list(FIRST),'REVIEW_COMPONENT_ONLY_ACTUAL_FIRST_TWO_NATIVE_ROWS')
    for row in selected:
        factor*=float(row['split_ratio'])
        if row['session']==EVENT:factor*=float('2.1584')
        price=None if row['raw_close']=='' else float(row['raw_close'])
        reference.append(None if price is None else (price*factor).hex())
    need(cases['observed_forward']==dict(observations=len(selected),source_sessions=[r['session'] for r in selected],
        source_raw_row_sha256=[digest(r) for r in selected],reference_signal_hex=reference,
        published_path_exact=True,split_only_falsifier_rejected=True),
        'REVIEW_ENTIRE_ACTUAL_SOURCE_FORWARD_HEX_SERIES_AND_SPLIT_ONLY_FALSIFIER')
    raw,split=next((a,b) for a in (1.3,7.1,13.7,23.2,101.3) for b in (1.1,1.3,1.7,3.3)
        if (a*b)*float('2.1584')!=a*(float('2.1584')*b))
    toy=[dict(session=FIRST[0],security_id='984687283821901795',raw_close='10',raw_open='9',
              signal_close='10',split_ratio='1',raw_compatible_volume='99'),
         dict(session=FIRST[1],security_id='984687283821901795',raw_close=str(raw),raw_open=str(raw),
              signal_close=str(raw*split),split_ratio=str(split),raw_compatible_volume='99')]
    canonical=[10.*float('2.1584'),raw*(float('2.1584')*split)];wrong=(raw*split)*float('2.1584')
    need(canonical[-1]!=wrong and cases['native_composition']==dict(synthetic_rows=toy,
        canonical_signal_hex=[v.hex() for v in canonical],published_times_ratio_wrong_hex=wrong.hex(),
        associativity_falsifier_rejected=True,raw_factor_chronology_exact=True),
        'REVIEW_EXACT_NATIVE_COMPOSITION_FACTOR_THEN_RAW_AND_ASSOCIATIVITY_FALSIFIER')
    feature=cases['feature_order'];length=contract['window_length'];raw=[10.+i*.01 for i in range(length)]
    raw[-2:]=[8.,8.1];correct=raw[:-2]+[v*float('2.1584') for v in raw[-2:]]
    need(set(feature)=={'reference_signal','fast_signal','late_unadjusted_certified_signals',
         'late_multiplier_falsifier_rejected','full_synthetic_signal_window','synthetic_raw_closes'}
         and feature['reference_signal']==feature['fast_signal']
         and feature['reference_signal']['closes'][-1]==correct[-1]
         and feature['reference_signal']['certified_signals'] is not None
         and feature['reference_signal']['certified_signals']!=feature['late_unadjusted_certified_signals']
         and feature['late_multiplier_falsifier_rejected'] is True
         and feature['full_synthetic_signal_window']==correct and feature['synthetic_raw_closes']==raw,
         'REVIEW_FULL_FAST_REFERENCE_FEATURE_AND_LATE_MULTIPLIER_DIFFERENCE')
    targets=('517224929580411308','369995575874917058');roles=('HELD','CLOSE_PENDING','DOLLAR_BUY_PENDING','EXIT_FLAG_ONLY')
    need(set(value['target_cases'])=={sid+'/'+role for sid in targets for role in roles},
         'REVIEW_ALL_EIGHT_INDEPENDENT_TARGET_ROLES')
    wires=[]
    for name,row in value['target_cases'].items():
        sid,role=name.split('/');before=row['before'];after=row['actual']
        need(set(row)=={'before','baseline','actual','audit','target_role','entire_full_state_and_fill_result_equal'}
             and after==row['baseline'] and row['target_role']==role and row['entire_full_state_and_fill_result_equal'] is True
             and source_scope(before,EVENT) and source_scope(after,EVENT)
             and after['ledger']['events'][:len(before['ledger']['events'])]==before['ledger']['events'],
             'REVIEW_COMPLETE_TARGET_BASELINE_UNIT_STATE_AND_LEDGER_EQUALITY')
        prior=[e for e in before['wealth_core']['episodes'].values() if e['security_id']==sid]
        actual=[e for e in after['wealth_core']['episodes'].values() if e['security_id']==sid]
        if role=='DOLLAR_BUY_PENDING':
            need(not prior and len(actual)==1 and actual[0]['current_shares']>0 and before['pending']
                 and not after['pending'],'REVIEW_ACTUAL_ORDINARY_TARGET_BUY_NOT_SKIPPED')
        elif role=='CLOSE_PENDING':
            need(len(prior)==1 and prior[0]['current_shares']==7 and not actual and before['pending']
                 and not after['pending'],'REVIEW_ACTUAL_ORDINARY_TARGET_CLOSE_NOT_SKIPPED')
        else:
            need(len(prior)==len(actual)==1 and prior[0]['current_shares']==actual[0]['current_shares']==7
                 and not before['pending'] and not after['pending']
                 and (role!='EXIT_FLAG_ONLY' or prior[0]['exit_pending'] is actual[0]['exit_pending'] is True),
                 'REVIEW_TARGET_HOLDING_OR_INDEPENDENT_EXIT_FLAG_PRESERVED')
        added=after['ledger']['events'][len(before['ledger']['events']):]
        need(not any(e.get('security_id')=='984687283821901795'
             or (e.get('detail') or {}).get('parent_security_id')=='984687283821901795' for e in added),
             'REVIEW_SYNTHETIC_UNIT_CANNOT_CREATE_SOURCE_OR_CHILD_PACKAGE_VALUE')
        need(row['audit']==dict(prefix=dict(resolved_open_equity=after['wealth_core']['cash']+
             sum(e['current_shares']*10. for e in actual)),spinoff_audit=[]),
             'REVIEW_FULL_ORDINARY_TARGET_FILL_AUDIT_WITHOUT_ENTITLEMENT')
        from core_window_review import reconcile
        for wire in (before,after):
            held=[e for e in wire['wealth_core']['episodes'].values() if e['current_shares']]
            need(all(e['security_id']==sid for e in held),'REVIEW_SYNTHETIC_TARGET_ONLY_POSITION_FIXTURE')
            snapshot=dict(wealth_core=wire['wealth_core'],ledger=wire['ledger'],
                prices={sid:dict(raw_price=10.,status='CURRENT')},
                resolved_equity=wire['wealth_core']['cash']+sum(e['current_shares']*10. for e in held))
            reconcile(snapshot)
        wires.extend((before,after))
    post=value['post_event_new_unit_case'];sid='984687283821901795';before=post['before'];after=post['after']
    expected_before=deepcopy(post_event_state)
    expected_before.update({k:deepcopy(before[k]) for k in ('wealth_core','ledger','pending','last_known')})
    need(set(post)=={'before','after','prefix','raw_price','logical_price','actual_qualifier_clock_state_sha256',
         'raw_execution_and_whole_quantity_canonical','logical_reference_peak_canonical',
         'no_old_package_or_double_split_posted','full_canonical_roundtrip'}
         and post['actual_qualifier_clock_state_sha256']==digest(post_event_state)
         and post_event_state['last_processed_session']==before['last_processed_session']==EVENT
         and before==normalize_state(expected_before)
         and len(before['pending'])==1 and before['pending'][0]['security_id']==sid
         and before['pending'][0]['signal_session']==EVENT and not after['pending']
         and source_scope(before,FIRST[1])==[]
         and all(post[k] is True for k in ('raw_execution_and_whole_quantity_canonical','logical_reference_peak_canonical',
             'no_old_package_or_double_split_posted','full_canonical_roundtrip')),
         'REVIEW_ACTUAL_QUALIFIER_CLOCK_AND_NEW_UNIT_INTENT_AFTER_PRE_EVENT_BOUNDARY')
    episodes=[e for e in after['wealth_core']['episodes'].values() if e['security_id']==sid]
    prior=before['ledger']['events'];events=after['ledger']['events'];added=events[len(prior):]
    need(post['raw_price']==10. and post['logical_price']==post['raw_price']*float('2.1584')
         and events[:len(prior)]==prior and len(episodes)==len(added)==1
         and episodes[0]['current_shares']==episodes[0]['initial_shares']>0
         and float(episodes[0]['current_shares']).is_integer()
         and episodes[0]['episode_peak_split_adjusted_close']==post['logical_price']
         and added[0]['event_type']=='BUY' and added[0]['security_id']==sid
         and added[0]['session']==FIRST[1] and added[0]['price']==post['raw_price']
         and post['prefix']==dict(resolved_open_equity=after['wealth_core']['cash']+episodes[0]['current_shares']*post['raw_price']),
         'REVIEW_ORDINARY_POST_EVENT_RAW_FILL_LOGICAL_PEAK_AND_NO_DOUBLE_SPLIT')
    for wire in (before,after):
        held=[e for e in wire['wealth_core']['episodes'].values() if e['current_shares']]
        need(all(e['security_id']==sid for e in held),'REVIEW_POST_EVENT_SOURCE_ONLY_SYNTHETIC_POSITIONS')
        reconcile(dict(wealth_core=wire['wealth_core'],ledger=wire['ledger'],prices={sid:dict(raw_price=10.,status='CURRENT')},
            resolved_equity=wire['wealth_core']['cash']+sum(e['current_shares']*10. for e in held)))
    wires.extend((before,after))
    negatives=value['negative_cases']
    need(negatives==[dict(case='SPLIT_ONLY',rejected=True),dict(case='LATE_MULTIPLIER',rejected=True)],
         'REVIEW_BOTH_OPERATION_ORDER_FALSIFIERS_RETAINED')
    reasons={'source_holding':'HOLDING_UNSUPPORTED','source_exit_flag':'HOLDING_UNSUPPORTED',
        'source_future_buy':'ANY_PENDING_UNSUPPORTED','source_close':'ANY_PENDING_UNSUPPORTED',
        'source_reservation':'RESERVATION_OR_ORPHAN_RESERVATION_UNSUPPORTED',
        'source_orphan_reservation':'RESERVATION_OR_ORPHAN_RESERVATION_UNSUPPORTED',
        'source_receivable':'RECEIVABLE_UNSUPPORTED','source_unresolved':'UNRESOLVED_OR_CARRY_CLAIM',
        'source_pending_terms':'UNRESOLVED_OR_CARRY_CLAIM','source_pending_session':'UNRESOLVED_OR_CARRY_CLAIM',
        'source_carry_claim':'UNRESOLVED_OR_CARRY_CLAIM'}
    falsifiers=value['source_scope_falsifiers']
    need(len(falsifiers)==len(reasons) and {r['case'] for r in falsifiers}==set(reasons)
         and all(set(r)=={'case','error','caller_unchanged'} and r['caller_unchanged'] is True
            and r['error'].endswith(reasons[r['case']]) for r in falsifiers),
         'REVIEW_ALL_ELEVEN_EXACT_SOURCE_REFUSALS_WITH_CALLER_UNCHANGED')
    return wires


def review(spec,out,evidence):
    """Hosted-only canonical restores; never startup, adoption, or advance."""
    from full_system_core import hosted
    hosted()
    from p01_iac_unit_contract import specification,INPUT,HERE,document
    from p01_iac_unit_epoch import historical_epoch
    from p01_iac_unit_codec import InputCodec,source_rows
    need(spec==specification(),'REVIEW_ENTIRE_EXACT_SOURCE_BOUND_OWN628_SPECIFICATION')
    out,evidence,old=Path(out),Path(evidence),Path('/old')
    with historical_epoch(old,out,spec,checkpoint_path=evidence/'book/checkpoint.json.gz') as binding:
        # Historical quote and every original codec have authenticated before
        # this context can import/restore the new input-bearing SessionState.
        rows,members=source_rows(through=END)
        with InputCodec(rows,binding.parent) as codec:
            from research.pooled_vacancy_funding import backtest
            raw=(evidence/'iac-unit-input.json').read_bytes()
            need(raw==(HERE/INPUT).read_bytes() and json.loads(raw)==document(),
                 'REVIEW_WHOLE_EXACT_TWELFTH_DOCUMENT_PREIMAGE')
            current=read(evidence/'book/checkpoint.json.gz');objects=[]
            need(current['repairs'][:11]==binding.parent['repairs'] and len(current['repairs'])==12,
                 'REVIEW_ALL_TWELVE_ARCHIVES_REQUIRED_BEFORE_ANY_RESTORE')
            for index,descriptor in enumerate(current['repairs']):
                path=evidence/'book/repairs'/descriptor['filename'];archive=path.read_bytes()
                need(sha(archive)==descriptor['sha256']
                     and (index==11 or archive==(old/'book/repairs'/descriptor['filename']).read_bytes()),
                     'REVIEW_EXACT_ORIGINAL_PROVENANCE_ALL_TWELVE_DOCUMENT_BYTES')
                obj=backtest.load_repair(path,resume_session=descriptor['resume_session'],
                    predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'])
                need(obj.sha256==descriptor['sha256'],'REVIEW_ALL_TWELVE_REGISTERED_BEFORE_CANONICAL_RESTORE')
                objects.append(obj)
            need(objects[-1].sha256==sha(raw),'REVIEW_ACTUAL_ARCHIVED_TWELFTH_EQUALS_DECLARED_DOCUMENT')
            return review_loaded(spec,out,evidence,old,binding,codec,objects,rows,members,current)


def review_loaded(spec,out,evidence,old,binding,codec,objects,rows,members,current):
    from full_system_core import hosted
    hosted()
    from full_system_benchmark import save
    from dataclasses import asdict
    from research.pooled_vacancy_funding import backtest,runtime,journal
    from research.pooled_input_support.bundle import axis
    from research.pooled_input_support.adapter import Packet
    from research.pooled_vacancy_funding.monthly import MonthlyStats
    from system_campaign_readonly import reader
    from system_campaign_factual_run import preserve_tails
    from system_campaign_pxd_pause import adoption
    from p01_iac_unit_contract import facts,reused_qualification
    from p01_iac_unit_guard import source_contract
    from p01_iac_unit_accounting import AccountingCursor
    from p01_factual_batch_contract import facts as historical_facts
    from p01_factual_batch_codec import source_terms
    from p01_factual_batch_review import action_scope,advance_retry,pre_event_receipts
    from core_window_review import factor,near
    from research.bounded_20y.run import vendor
    from system_campaign_discovery_context import material
    from stock_strategy_shared.wealth_core.funding import config
    from sentinel.core.session import SessionState
    parent=binding.parent;zero=read(evidence/'zero-session-boundaries.json');adopted=zero['input_checkpoint']
    same_resume_identity(parent,adopted,current)
    need(parent['base']['sources']==backtest.source_files()==binding.source_map['successor_financial_sources']
         and len(parent['base']['sources'])==224 and len(binding.source_map['successor_all_sources'])==516,
         'REVIEW_ACTUAL_UNCHANGED_CURRENT516_AND_CANONICAL224_EPOCH')
    zero_proof(zero,parent,adoption(adopted,parent,objects[-1].sha256,EVENT),objects[-1].sha256,
        sha((Path(__file__).parent/'p01_factual_batch_pause.py').read_bytes()))
    need(read(evidence/'qualification/zero-session-boundaries.json')==zero,
         'REVIEW_FRESH_FINANCE_ENTIRE_ZERO_PROOF_EQUALS_REFERENCE_FAST')
    need((evidence/'book/identity.json').read_bytes()==(old/'book/identity.json').read_bytes(),
         'REVIEW_ORIGINAL_OWN628_BOOK_IDENTITY_BYTES')
    qualified=read(evidence/'qualification/qualification-summary.json')
    from p01_iac_unit_export import qualification
    qualification(qualified)
    need(qualified['input_zero_outer_sha256']==adopted['sha256']
         and qualified['input_document_sha256']==objects[-1].sha256
         and qualified['successor_input_sha256']==current['run']['input_sha256']
         and all(qualified[k] is True for k in ('unit_normalization_qualified',
             'unit_target_independence_qualified','source_scope_falsifiers_qualified')),
         'REVIEW_ACTUAL_QUALIFIER_BOUND_TO_THIS_INPUT_ZERO')
    contract=source_contract(binding);normalizer=facts()['normalizer']
    cfg=config(parent['base']['policy'])
    synthetic=read(evidence/'qualification/unit-normalization-component.json.gz')
    qsource=read(evidence/'qualification/unit-normalization-source-proof.json')
    fsource=read(evidence/'unit-normalization-source-proof.json')
    for value in (qsource,fsource):source_proof(value,contract,codec.origin,members)
    need(qsource['reference_applications']==qsource['fast_applications']
         and qsource['reference_refusals']==qsource['fast_refusals']==[]
         and fsource['reference_applications']==qsource['reference_applications']
         and fsource['reference_refusals']==qsource['reference_refusals'],
         'REVIEW_ENTIRE_REFERENCE_FAST_SOURCE_RECORDS_AND_FRESH_REFERENCE_PREIMAGE')
    bars={r['session']:material(vendor(r)) for r in rows if r['session']>=EVENT}
    qnormal=normalization_records(qsource['reference_applications'],rows,normalizer,bars)
    fnormal=normalization_records(fsource['fast_applications'],rows,normalizer,bars)
    need(qnormal['source_days']==list(FIRST),'REVIEW_BOTH_QUALIFIED_DAYS_HAVE_ACTUAL_SOURCE_APPLICATIONS')
    full=axis();dates=full[full.index(backtest.START)-425:full.index(backtest.END)+1]
    wanted=[day for day in dates if parent['source_cursor']<day<=current['source_cursor']]
    need(len(wanted)==current['completed']-628 and len(wanted)<=MAXIMUM,'REVIEW_EXACT_FROZEN_COMMITTED_SESSION_AXIS')
    next_session=dates[dates.index(current['source_cursor'])+1] if current['source_cursor']<END else None
    need([d for d in fnormal['source_days'] if d<=current['source_cursor']]==wanted,
         'REVIEW_EVERY_COMMITTED_SOURCE_APPLICATION')
    old_streams={n:(old/f'book/{n}.jsonl').read_bytes() for n in parent['journals']}
    new_streams={n:(evidence/f'book/{n}.jsonl').read_bytes() for n in parent['journals']}
    suffixes,tails,prefixes=journal_suffixes(parent,current,old_streams,new_streams)
    need(not suffixes['formation'] and [r['session'] for r in suffixes['daily']]==wanted,
         'REVIEW_ALL_NEW_DAILY_ROWS_NO_FORMATION_OR_SKIPPED_SESSION')
    boundaries=boundary_counts([json.loads(r) for r in old_streams['watch'].splitlines()],suffixes['watch'],zero['input_event'])
    financial_chain(parent,zero,suffixes['daily'],current)
    outcome=read(evidence/'iac-unit-outcome.json')
    need(outcome['actual_codec_applications']==fsource['fast_applications']
         and outcome['actual_codec_refusals']==fsource['fast_refusals'],
         'REVIEW_ATTEMPT_BOUND_SOURCE_RECORDS_ARE_ENTIRE_AUTHENTICATED_COMPILER_PROOF')
    tail=bounded_tail(current,new_streams,gzip.decompress((old/'correlation-inputs.jsonl.gz').read_bytes()),
        gzip.decompress((evidence/'correlation-inputs.jsonl.gz').read_bytes()),suffixes['daily'],outcome,dates)
    allowed=tail['allowed_uncommitted_sessions']
    qrecord=read(evidence/'qualification/actual-two-session-component.json.gz')
    financial=read(evidence/'actual-financial-first-two-component.json.gz')
    qtail=first_two(adopted,qrecord,financial,current,next_session,allowed);qpath=qrecord['actual_components']
    need(qualified['actual_role_and_full_state_records']==role_rows(qpath),
         'REVIEW_PRIVATE_FULL_ROLE_RECORDS_DISTINCT_FROM_PUBLIC_QUALIFIED_COUNT')
    wires=synthetic_component(synthetic,contract,codec.origin,rows,
        dict(policy=parent['base']['policy'],fields=asdict(cfg),config_hash=cfg.config_hash()),binding.source_map,
        qpath[0]['checkpoint']['state'],lambda wire:SessionState.from_dict(wire).to_dict())
    for wire in wires:
        need(len(wire['wealth_core']['slots'])==cfg.n_slots and SessionState.from_dict(deepcopy(wire)).to_dict()==wire,
             'REVIEW_ALL_SYNTHETIC_FULL_STATE_WIRES_CANONICAL_ROUNDTRIP_NOT_ADOPTION')
    metadata=publication_metadata(qsource['reference_applications'],qpath)
    publication_metadata(qsource['fast_applications'],qpath)
    publication_metadata(fsource['fast_applications'],financial['attempted_components'])
    stream=reader(journal.Journal,evidence/'book',journal.STREAMS);checked=[];checkpoints={};files={}
    def restore(label,checkpoint,verify=True,original=False):
        if not original:same_resume_identity(parent,adopted,checkpoint)
        else:need(checkpoint==parent,'REVIEW_ONLY_ORIGINAL628_BEFORE_INPUT12')
        backtest.validate_checkpoint(checkpoint,parent['base'],dates)
        run=runtime.restore(checkpoint['run'],policy=parent['base']['policy'],
            input_sha256=backtest.input_hash(checkpoint['base'],checkpoint['repairs']))
        need(runtime.checkpoint(run)==checkpoint['run'],'REVIEW_NEW_ENTIRE_CANONICAL_CHECKPOINT_ROUNDTRIP')
        if verify:stream.verify(checkpoint['journals'])
        checked.append(label);return run
    try:
        restore('epoch-zero',parent,original=True);restore('input-zero',adopted);restore('current',current)
        for folder in ('pre-event','month-end'):
            for path in sorted((evidence/'book'/folder).glob('*.json.gz')):
                cp=journal.read_checkpoint(path);name=path.relative_to(evidence).as_posix();restore(name,cp)
                checkpoints[name]=cp;raw=path.read_bytes();files[name]=dict(bytes=len(raw),sha256=sha(raw))
        for label in ('reference_qualifier_checkpoint','qualifier_checkpoint'):
            restore(label,qrecord[label],False)
        for family in ('reference_components','actual_components'):
            for row in qrecord[family]:
                for key in ('prior_checkpoint','checkpoint'):
                    cp=row[key];restored=runtime.restore(cp,policy=parent['base']['policy'],input_sha256=current['run']['input_sha256'])
                    need(runtime.checkpoint(restored)==cp,'REVIEW_ALL_REFERENCE_FAST_PRIOR_AND_NEXT_FULL_RESTORES')
                    checked.append(family+'/'+row['session']+'/'+key)
        for row in financial['attempted_components']:
            for key in ('prior_checkpoint','checkpoint'):
                cp=row[key];restored=runtime.restore(cp,policy=parent['base']['policy'],input_sha256=current['run']['input_sha256'])
                need(runtime.checkpoint(restored)==cp,'REVIEW_ALL_FRESH_FINANCE_ATTEMPTED_FIRST_TWO_FULL_RESTORES')
        if len(wanted)<=2:
            need(current['run']==(financial['actual_components'][-1]['checkpoint'] if wanted else adopted['run']),
                 'REVIEW_ACTUAL_CURRENT_FULL_RUNTIME_MATCHES_FRESH_COMPONENT_PREFIX')
    finally:stream.close()
    pre=read(evidence/'iac-unit-preflight.json')
    originals={p.relative_to(old).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p.read_bytes()))
        for folder in ('book','lineage') for p in (old/folder).rglob('*.json.gz')}
    need(pre['original_checkpoint_files']==originals and len(originals)==38,
         'REVIEW_ALL_THIRTY_EIGHT_INHERITED_GZIP_DESCRIPTORS')
    for name,entry in originals.items():
        raw=(evidence/'lineage/original-checkpoints'/name).read_bytes()
        need(raw==(old/name).read_bytes() and dict(bytes=len(raw),sha256=sha(raw))==entry,
             'REVIEW_EVERY_ORIGINAL_GZIP_VERBATIM')
    need(set(pre)=={'schema','original_outer_sha256','root_admission_descriptor_sha256','original_checkpoint_files',
         'tails_to_preserve','next_session','processing_endpoint','maximum_transitions','original_inputs',
         'financial_source_epoch_unchanged','old_financial_and_accounting_audits_reused',
         'old_financial_audits_repeated','qualification_state_adopted','retained_action_component'}
         and pre['schema']=='research.p01-iac-unit-preflight/1'
         and pre['original_outer_sha256']==OUTER and pre['root_admission_descriptor_sha256']==ROOT_ADMISSION
         and pre['next_session']==EVENT and pre['processing_endpoint']==END and pre['maximum_transitions']==MAXIMUM
         and pre['original_inputs']==11 and pre['old_financial_audits_repeated'] is False
         and pre['qualification_state_adopted'] is False
         and pre['financial_source_epoch_unchanged'] is True and pre['old_financial_and_accounting_audits_reused'] is True
         and pre['tails_to_preserve']=={n:dict(bytes=0,sha256=sha(b'')) for n in parent['journals']},
         'REVIEW_EXACT_OWN628_PREFLIGHT_ENDPOINT_OLD_INPUTS_AND_ZERO_OLD_TAILS')
    reused=reused_qualification(old,binding.source_map)
    retained=pre['retained_action_component'];rr=(evidence/'retained-qualification/target-independence-component.json.gz').read_bytes()
    need(retained['member']=='retained-qualification/target-independence-component.json.gz'
         and retained['bytes']==len(rr)==spec['reused_action_component']['bytes']
         and retained['sha256']==sha(rr)==spec['reused_action_component']['sha256']
         and rr==(old/spec['reused_action_component']['member']).read_bytes()
         and retained['financial_authority'] is False,'REVIEW_RETAINED_QUALIFIED_COMPONENT_VERBATIM_NOT_FINANCIAL_CP')
    ledger=current['run']['state']['ledger']['events'];old_ledger=parent['run']['state']['ledger']['events']
    need(ledger[:len(old_ledger)]==old_ledger,'REVIEW_ENTIRE_ADMITTED628_LEDGER_PREFIX')
    last_old=json.loads(old_streams['daily'].splitlines()[-1]);anchor=last_old['evidence']['research_entry_audit']['closing_accounting']
    need(last_old['session']==parent['source_cursor'] and last_old['state_sha256']==parent['run']['state_sha256']
         and last_old['economics']==parent['economics'] and anchor['wealth_core']==parent['run']['state']['wealth_core']
         and anchor['pending']==parent['run']['state']['pending'] and anchor['ledger']['event_count']==len(old_ledger)
         and anchor['ledger']['receivables']==parent['run']['state']['ledger']['receivables'],
         'REVIEW_ADMITTED628_RAW_CLOSING_ANCHOR_REUSED_WITHOUT_OLD_ACCOUNTING')
    records=historical_facts()['records'];native=source_terms();scopes={}
    for row in read('/frozen/bundle/supplements.json'):
        if row.get('security_id') not in {a['source_security_id'] for a in records} and (
            'UNHELD' in row.get('disposition','').upper() or 'unheld' in row.get('reference','').lower()):
            scopes[(row['effective_session'],row['security_id'])]=digest(row)
    def scope_records(path):
        actions=[];inherited=[];unit=[]
        for row in path:
            day=row['session'];state=row['prior_checkpoint']['state'];unit.extend(source_scope(state,day))
            actions.extend(action_scope(state,a,True,True) for a in records if a['economic_session']==day)
            for terms in row['publication']['terminal_events']:
                key=(day,terms['security_id']);sid=terms['security_id']
                if key in scopes:
                    need(not any(e['security_id']==sid for e in state['wealth_core']['episodes'].values())
                         and not any(p['security_id']==sid for p in state['pending']),
                         'REVIEW_ACTUAL_QUALIFIER_INHERITED_SOURCE_SCOPE')
                    inherited.append(dict(session=day,security_id=sid,unheld=True,all_source_pending_absent=True,source_record_sha256=scopes[key]))
        return actions,inherited,unit
    qa,qn,qu=scope_records(qpath)
    need(qrecord['action_checks']==qa and qrecord['inherited_native_scope_checks']==qn
         and qrecord['source_unit_scope_checks']==qu,'REVIEW_ALL_QUALIFIER_SCOPE_RECORDS_FROM_FULL_PRIOR_STATES')
    need([r['session'] for r in qrecord['unit_window_anchor_checks']]==list(FIRST),
         'REVIEW_BOTH_ACTUAL_QUALIFIER_UNIT_WINDOWS_AND_ANCHORS')
    for row,window in zip(qpath,qrecord['unit_window_anchor_checks']):
        unit_window(window,rows,normalizer,contract['window_length'],checkpoint=row['checkpoint'],
            publication=row['publication'],axis=dates)
    no_source_entitlement_posting(qpath)
    input_zero_receipt(qrecord['pre_event_checkpoints'],adopted,journal._encoded)
    cursor=AccountingCursor(parent,binding.quote,records);prior=deepcopy(parent['economics'])
    stats=MonthlyStats.from_dict(parent['stats']);retries=deepcopy(parent['retries']);reports=[];quotes=[]
    actions=[];inherited=[];unit=[];prior_state=parent['run']['state'];prior_hash=parent['run']['state_sha256']
    for row in suffixes['daily']:
        day=row['session'];work=deepcopy(row);active=[a for a in records if a['economic_session']==day]
        candidates=[cp for name,cp in checkpoints.items() if name.startswith('book/pre-event/'+day+'-')
            and cp['run']['state_sha256']==prior_hash and cp['source_cursor']==dates[dates.index(day)-1]]
        if active or day==EVENT:
            need(len(candidates)==1,'REVIEW_FULL_ACTUAL_PRIOR_CANONICAL_PRE_EVENT_FOR_EVERY_AFFECTED_DAY')
            state=candidates[0]['run']['state'];actions.extend(action_scope(state,a,True,True) for a in active)
            unit.extend(source_scope(state,day))
        packet=Packet(day,(),{},{},1.,{},tuple(native.get(day,())),())
        # Only original eleven compiler objects act on this term-only control.
        # The twelfth quote-domain compiler is never asked to fabricate bars.
        for obj in objects[:11]:packet=backtest.apply_repair(packet,obj)
        for term in packet.terminal:
            key=(day,term.security_id);sid=term.security_id
            if key in scopes:
                need(not any(e['security_id']==sid for e in prior_state['wealth_core']['episodes'].values())
                     and not any(p['security_id']==sid for p in prior_state['pending']),
                     'REVIEW_EVERY_INHERITED_UNHELD_SCOPE_ACTUAL_PRIOR_ROLES')
                inherited.append(dict(session=day,security_id=sid,unheld=True,all_source_pending_absent=True,source_record_sha256=scopes[key]))
        for key,phase,valuation in (('opening_accounting','OPEN_BEFORE_FILLS','parent_core_open_equity'),
                                   ('closing_accounting','CLOSE_AFTER_DECISION','parent_core_close_equity')):
            snapshot=deepcopy(row['evidence']['research_entry_audit'][key]);count=snapshot['ledger'].pop('event_count')
            need(type(count) is int and len(old_ledger)<=count<=len(ledger) and snapshot['session']==day
                 and snapshot['phase']==phase,'REVIEW_NEW_FULL_SNAPSHOT_PHASE_AND_LEDGER_PREFIX')
            snapshot['ledger']['events']=ledger[:count];cursor.reconcile(snapshot)
            near(snapshot['resolved_equity'],row['economics'][valuation],'REVIEW_NEW_RAW_ACCOUNT_EQUITY_EQUALS_SENSOR')
            for episode in snapshot['wealth_core']['episodes'].values():
                if episode['current_shares']:
                    mark=snapshot['prices'][episode['security_id']]
                    need(mark['status'] in ('RAW_OPEN','CURRENT'),'REVIEW_NO_UNEXPLAINED_NEW_HELD_CARRY')
                    quotes.append(((day,episode['security_id']),'raw_open' if mark['status']=='RAW_OPEN' else 'raw_close',mark['raw_price']))
            work['evidence']['research_entry_audit'][key]=snapshot
        factor(prior,work);prior=row['economics'];prior_hash=row['state_sha256']
        retry=advance_retry(retries,row)
        report=stats.advance(day,{k:Decimal(v) for k,v in row['comparison_navs'].items()},
            core_target=str(row['decision']['target_core_exposure']),month_end=dates[dates.index(day)+1][:7]!=day[:7])
        if report:report['slot_retries']=retry;reports.append(report)
        closing=row['evidence']['research_entry_audit']['closing_accounting']
        prior_state=dict(wealth_core=closing['wealth_core'],pending=closing['pending'])
    need(prior==current['economics'] and prior_hash==current['run']['state_sha256']
         and stats.to_dict()==current['stats'] and retries==current['retries'] and reports==suffixes['monthly'],
         'REVIEW_ALL_NEW_FACTORS_STRICT_MONTHLY_RETRY_AND_CURRENT_STATE')
    quarter_ends=[d for d in wanted if d[5:7] in ('03','06','09','12') and dates[dates.index(d)+1][:7]!=d[:7]]
    need(all(any(n.startswith('book/month-end/'+d+'-') and cp['source_cursor']==d for n,cp in checkpoints.items())
         for d in quarter_ends),'REVIEW_ALL_CANONICAL_QUARTER_BOUNDARY_CHECKPOINTS')
    need(outcome['source_cursor']==current['source_cursor'] and outcome['completed']==current['completed']
         and outcome['fresh_from_original628'] is True and outcome['qualification_state_adopted'] is False
         and outcome['source_epoch_boundary_reemitted'] is False and outcome['input_adoptions']==1
         and outcome['input_document_sha256']==objects[-1].sha256
         and outcome['successor_input_sha256']==current['run']['input_sha256']
         and outcome['original_inputs']==11 and outcome['successor_inputs']==12
         and outcome['actual_action_scope_checks']==actions and outcome['actual_inherited_native_scope_guards']==inherited
         and outcome['actual_source_unit_scope_checks']==unit,
         'REVIEW_ENTIRE_FRESH_OWN628_FINANCIAL_OUTCOME_AND_ACTUAL_SCOPE_BINDINGS')
    attempted={}
    for name in ('role_and_full_state_checks','action_scope_checks','inherited_native_scope_guards',
                 'source_unit_scope_checks','unit_window_anchor_checks'):
        attempted['attempted_'+name]=committed_attempts(outcome['actual_'+name],outcome['attempted_'+name],
            current['source_cursor'],next_session,allowed)
    need(outcome['actual_role_and_full_state_checks']==role_rows(financial['actual_components'])
         and outcome['attempted_role_and_full_state_checks']==role_rows(financial['attempted_components'])
         and outcome['actual_codec_applications']==fsource['fast_applications']
         and outcome['actual_codec_refusals']==fsource['fast_refusals'],
         'REVIEW_ALL_FIRST_TWO_FULL_ROLES_AND_ENTIRE_ATTEMPTED_COMPILER_RECORDS')
    need([r['session'] for r in outcome['actual_unit_window_anchor_checks']]==wanted,
         'REVIEW_ONE_UNIT_WINDOW_AND_ANCHOR_RECORD_FOR_EVERY_COMMITTED_SESSION')
    first_map={r['session']:r for r in financial['attempted_components']}
    runtime_states={cp['run']['state_sha256']:cp['run'] for cp in checkpoints.values()}
    runtime_states[current['run']['state_sha256']]=current['run']
    runtime_states.update({r['checkpoint']['state_sha256']:r['checkpoint'] for r in financial['attempted_components']})
    attempted_states={r['session']:r['state_sha256'] for r in tail['complete_daily_tail_rows']}
    attempted_states.update({r['session']:r['next_state_sha256'] for r in tail['correlation']['uncommitted_records']})
    tail['uncommitted_full_states']=[dict(session=day,state_sha256=h,full_state_exported=h in runtime_states,
        status='UNADMITTED_ATTEMPTED_FULL_STATE_EXPORTED' if h in runtime_states else 'UNADMITTED_ATTEMPTED_FULL_STATE_NOT_EXPORTED')
        for day,h in sorted(attempted_states.items())]
    unadmitted=[]
    for record in outcome['attempted_unit_window_anchor_checks']:
        component=first_map.get(record['session']);cp=component['checkpoint'] if component else None
        if record['session']==current['source_cursor']:cp=current['run']
        if cp is None and record['session'] in attempted_states:cp=runtime_states.get(attempted_states[record['session']])
        unit_window(record,rows,normalizer,contract['window_length'],checkpoint=cp,
            publication=component['publication'] if component else None,axis=dates)
        if cp is None and record['session']>current['source_cursor']:
            unadmitted.append(dict(kind='unit_window_retained_state',session=record['session'],
                status='UNADMITTED_ATTEMPTED_FULL_STATE_NOT_EXPORTED',record=record))
    prepared=outcome['attempted_unit_preparations'];prepared_days=[r['session'] for r in prepared]
    need(prepared_days==sorted(set(prepared_days)) and [d for d in prepared_days if d<=current['source_cursor']]==wanted
         and all(d<=current['source_cursor'] or d in allowed for d in prepared_days),
         'REVIEW_ALL_ACTUAL_PREPARE_WINDOWS_COMMITTED_OR_NEXT_UNCOMMITTED_ATTEMPT')
    prepared_by_day={r['session']:r for r in prepared}
    for record in prepared:unit_window(record,rows,normalizer,contract['window_length'],axis=dates,prepared=True)
    need(all({k:v for k,v in r.items() if k not in ('source_series_retained','actual_retained_basis')}
         ==prepared_by_day[r['session']] for r in outcome['attempted_unit_window_anchor_checks']),
         'REVIEW_ENTIRE_ACTUAL_PREPARE_WINDOW_TO_POST_ADVANCE_ANCHOR_LINK')
    for record in outcome['unit_guard_refusals']:
        need(set(record)=={'session','stage','reason','current_saved_before_refusal','financial_advance_authorized'}
             and record['session']==next_session and record['stage']=='BEFORE_BUFFER_PREPARE'
             and type(record['reason']) is str and record['current_saved_before_refusal'] is True
             and record['financial_advance_authorized'] is False
             and any(cp==current and name.startswith('book/pre-event/'+next_session+'-') for name,cp in checkpoints.items()),
             'REVIEW_UNIT_PREPARE_REFUSAL_HAS_ACTUAL_IDENTICAL_DURABLE_PRE_EVENT_CURRENT')
    for record in attempted['attempted_action_scope_checks']:
        matched=[a for a in records if a['action_id']==record['action_id'] and a['economic_session']==record['session']]
        need(len(matched)==1,'REVIEW_UNCOMMITTED_ACTION_EXACT_REGISTRY_IDENTITY')
        candidates=[cp for n,cp in checkpoints.items() if n.startswith('book/pre-event/'+record['session']+'-')
            and cp['source_cursor']==dates[dates.index(record['session'])-1]]
        state=candidates[0]['run']['state'] if len(candidates)==1 else current['run']['state'] if record['session']==next_session else None
        if state is not None:
            need(record==action_scope(state,matched[0],True,True),'REVIEW_UNCOMMITTED_ACTION_EXPORTED_CANONICAL_PRIOR_SCOPE')
        else:unadmitted.append(dict(kind='action_scope',record=record,status='UNADMITTED_ATTEMPTED_FULL_STATE_NOT_EXPORTED'))
    for record in attempted['attempted_source_unit_scope_checks']:
        need(record['session']==EVENT and record==source_scope(adopted['run']['state'],EVENT)[0],
             'REVIEW_UNCOMMITTED_EVENT_SCOPE_ACTUAL_EXPORTED_INPUT_ZERO')
    for record in attempted['attempted_inherited_native_scope_guards']:
        sid=record['security_id'];key=(record['session'],sid)
        need(key in scopes and record==dict(session=record['session'],security_id=sid,unheld=True,
             all_source_pending_absent=True,source_record_sha256=scopes[key]),'REVIEW_UNCOMMITTED_NATIVE_SCOPE_REGISTRY_IDENTITY')
        candidates=[cp for n,cp in checkpoints.items() if n.startswith('book/pre-event/'+record['session']+'-')
            and cp['source_cursor']==dates[dates.index(record['session'])-1]]
        state=candidates[0]['run']['state'] if len(candidates)==1 else current['run']['state'] if record['session']==next_session else None
        if state is not None:
            need(not any(e['security_id']==sid for e in state['wealth_core']['episodes'].values())
                 and not any(p['security_id']==sid for p in state['pending']),
                 'REVIEW_UNCOMMITTED_NATIVE_SCOPE_ACTUAL_EXPORTED_PRIOR')
        else:unadmitted.append(dict(kind='inherited_native_scope',record=record,status='UNADMITTED_ATTEMPTED_FULL_STATE_NOT_EXPORTED'))
    pre_event_receipts(outcome['actual_pre_event_checkpoints'],checkpoints,files)
    # A failed prepare may precede an action/scope receipt. Its archived full CP
    # and unchanged source packet remain evidence; it is not a committed day.
    for refusal in fsource['fast_refusals']:
        need(refusal['session'] in allowed and refusal['packet_left_unchanged'] is True
             and refusal['financial_advance_authorized'] is False and type(refusal['reason']) is str,
             'REVIEW_NATIVE_COMPILER_REFUSAL_ONLY_NEXT_UNCOMMITTED_SESSION')
    corr=tail['correlation']
    complete=complete_status(outcome,current,len(wanted),tails,corr['uncommitted_records'])
    qreport=read(evidence/'qualification/actual-unit-accounting-and-report.json')
    expected_report=current_report(qrecord['qualifier_checkpoint']['run'],parent['base']['policy'],binding.quote,records)
    qualification_report(qreport,expected_report)
    freport=read(evidence/'actual-unit-accounting-and-report.json')
    current_expected=current_report(current['run'],parent['base']['policy'],binding.quote,records) if wanted else None
    financial_report(freport,current_expected,len(wanted))
    result=dict(schema='research.p01-iac-unit-suffix-review/1',status='IAC_UNIT_ACTUAL_COMMITTED_SUFFIX_REVIEWED_PENDING_CLIENT',
        checkpoint_sha256=current['sha256'],source_cursor=current['source_cursor'],completed=current['completed'],
        new_financial_rows=len(wanted),segment_complete=complete,new_accounting_snapshots=2*len(wanted),accounting=cursor.result(),
        new_monthly_reports=len(reports),all_new_monthly_and_retry_checkpoint_state_exact=True,
        all_new_accounting_factors_and_chains_verified=True,old_financial_admission_reused_sha256=ROOT_ADMISSION,
        old_accounting_snapshots_recomputed=0,old_audits_repeated=False,source_epoch_boundary_reemitted=False,
        old_eleven_inputs_unchanged=True,successor_inputs=12,input_document_sha256=objects[-1].sha256,
        input_sha256=current['run']['input_sha256'],original_chain_sha256=parent['chain'],input_event=zero['input_event'],
        watch_boundary_counts=boundaries,checked_new_source_checkpoints=checked,
        all_historical_checkpoint_gzip_bytes_preserved=True,actual_quarter_boundary_checkpoints=quarter_ends,
        grouped_action_checks=actions,inherited_native_scope_checks=inherited,source_unit_scope_checks=unit,
        attempted_records_preserved_and_committed_subsets_exact=True,uncommitted_attempts=attempted,
        attempted_unit_preparations=prepared,actual_unit_guard_refusals=outcome['unit_guard_refusals'],
        bounded_uncommitted_evidence=tail,unadmitted_attempted_scope_records=unadmitted,
        qualifier_uncommitted_first_two_records=qtail,actual_pre_event_checkpoint_receipts=outcome['actual_pre_event_checkpoints'],
        reference_fast_full_components_equal=True,fresh_finance_first_two_full_components_equal=True,
        qualified_normalization=qnormal,financial_normalization=fnormal,source_contract=contract,
        actual_publication_native_metadata=metadata,
        synthetic_component_full_state_wires_restored=len(wires),actual_qualified_accounting_and_report=qreport,
        actual_financial_current_accounting_and_report=freport,
        retained_action_component=retained,reused_action_qualification=reused,prefixes=prefixes,current_tails=tails,
        raw_quotes=held_quotes(quotes,spec['frozen_observation_members']),correlation=corr,
        recovered_tails=preserve_tails(evidence/'book',pre),qualification_state_adopted=False,
        financial_predecessor_admitted=False,full_p01_comparison_complete=False,production_contacted=False)
    save(out/'iac-unit-financial-review.json',result);return result


main=review
