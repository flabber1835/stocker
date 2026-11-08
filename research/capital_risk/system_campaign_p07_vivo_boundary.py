"""Read the genuine full24-to25 neutral boundary; never manufacture a checkpoint."""
import gzip,json
from pathlib import Path
import system_campaign_p07_vivo_data as data
from system_campaign_bounded_sensor_origin_v2 import strict_json
from system_campaign_pxd_pause import adoption

OVERLAY='p07-vivo-ordinary25-terminal-overlay.json'
DIRECTORY='p07-vivo-ordinary25-adoption'
QUALIFICATION='p07-vivo-ordinary25-input-qualification.json'
ORIGIN='p07-vivo-ordinary25-origin'
SELECTED=ORIGIN+'/actual-selected-parent24.json.gz'
RAW_PROOF=ORIGIN+'/entire-prior-certificate.jsonl'

def strict_current(cp,input_hash):
    run=cp['run']
    data.need(cp['sha256']==data.digest({k:v for k,v in cp.items() if k!='sha256'})
         and run['checkpoint_sha256']==data.digest({k:v for k,v in run.items() if k!='checkpoint_sha256'})
         and run['state_sha256']==data.digest(run['state'])
         and cp['source_cursor']==run['state']['last_processed_session']
         and run['input_sha256']==input_hash(cp['base'],cp['repairs']),
         'VIVO_FULL_CURRENT25_CANONICAL_INPUT_INNER_STATE_OUTER_COMMITMENTS')

def relation(parent,neutral,spec,member,rows=None):
    data.parent_contract(parent,spec);catalog=data.catalog();raw=member(OVERLAY);doc=json.loads(raw)
    terms=catalog['terms']
    data.need(doc['schema']=='terminal-repair/1' and doc['predecessor_checkpoint_sha256']==parent['run']['checkpoint_sha256']
         and doc['add']==[t['added'] for t in terms]
         and doc['suppress']==[dict(session=t['native_session'],security_id=t['security_id'],term_sha256=t['native_term_sha256']) for t in terms]
         and 1<=len(doc['source_evidence'])<=128,
         'VIVO_EXACT23_TERM_ORDINARY_DOCUMENT_ORIGINAL128_EVIDENCE_CAP')
    earliest=min(t['native_session'] for t in terms)
    event=adoption(neutral,parent,data.sha(raw),earliest)
    neutral_raw=member(DIRECTORY+'/checkpoint.json.gz')
    data.need(strict_json(neutral_raw)==neutral and len(neutral['repairs'])==25
         and neutral['repairs'][:24]==parent['repairs'] and neutral['run']['state']==parent['run']['state']
         and member('book/repairs/'+neutral['repairs'][24]['filename'])==raw,
         'VIVO_ACTUAL_NEUTRAL25_GZIP_ALL24_UNCHANGED_DESCRIPTORS_AND_STATE')
    proof=json.loads(member(DIRECTORY+'/proof.json'))
    data.need(proof==dict(event=event,actual_checkpoint_gzip_sha256=data.sha(neutral_raw),original_outer_sha256=parent['sha256'],
         financial_state_unchanged=True,financial_sessions_advanced=0),
         'VIVO_WHOLE_ORIGINAL_ZERO_FINANCIAL_ADOPTION_PROOF')
    if rows is not None:
        data.need(gzip.decompress(member(DIRECTORY+'-correlation-inputs.jsonl.gz'))==b''.join(rows),
             'VIVO_GENUINE_NEUTRAL_ADOPTION_ZERO_NEW_CORRELATION_ROWS')
    watch=member('book/watch.jsonl');before,after=parent['journals']['watch'],neutral['journals']['watch']
    data.need(data.sha(watch[:before['bytes']])==before['prefix_sha256']
         and data.sha(watch[:after['bytes']])==after['prefix_sha256']
         and [json.loads(v) for v in watch[before['bytes']:after['bytes']].splitlines()]==[event],
         'VIVO_ONE_REAL_SUCCESSOR_WATCH_EVENT_ALL_ORIGINAL_WATCH_BYTES')
    q=json.loads(member(QUALIFICATION))
    data.need(q['passed'] is True and type(q['packet_checks']) is int and q['packet_checks']>0
         and q['only_terminal_field_changed'] is q['complete_terms_and_canonical_notional_verified']
         is q['original_incomplete_guard_retained'] is q['wrong_predecessor_and_consumed_date_refused']
         is q['wrong_native_and_delivery_witness_refused'] is True
         and type(q['financial_sessions_advanced']) is int and q['financial_sessions_advanced']==0,
         'VIVO_ACTUAL_ORIGINAL_WHOLE_PACKET_QUALIFICATION_NOT_DRAFT_AUTHORITY')
    return dict(passed=True,parent=parent,neutral=neutral,event=event,descriptor=neutral['repairs'][24],
        neutral_gzip_sha256=data.sha(neutral_raw),financial_sessions_advanced=0)

def validate_members(current,member,*,input_hash):
    from system_campaign_financial_partial import root_spec
    spec=root_spec('P07',data.ROOT);parent_raw=member(SELECTED)
    data.need(dict(bytes=len(parent_raw),sha256=data.sha(parent_raw))==spec['selected_file'],
         'VIVO_ORIGINAL_SELECTED24_GZIP_AUTHENTICATED_BEFORE_PARSE')
    parent=strict_json(parent_raw);neutral=strict_json(member(DIRECTORY+'/checkpoint.json.gz'))
    result=relation(parent,neutral,spec,member)
    strict_current(current,input_hash)
    data.need(current['base']==parent['base'] and current['repairs']==neutral['repairs'] and len(current['repairs'])==25
         and current['completed']>=neutral['completed'] and current['source_cursor']>=neutral['source_cursor'],
         'VIVO_FULL25_CURRENT_REAL_HISTORY_NO_PROJECTION_OR_INPUT_HASH_SUBSTITUTION')
    return result

def validate(root,current,*,input_hash):
    return validate_members(current,lambda name:(Path(root)/name).read_bytes(),input_hash=input_hash)
