"""One hash-bound issuer-proven name-only correction; no financial state edits."""
import gzip
import hashlib
import json
from pathlib import Path

from alpaca_fit_inputs import need


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def apply(data,descriptor,*,source_manifest_sha256):
    """Remove only the exact dated reset; keep every source record and bar."""
    from sentinel.feed.alpaca_identity import NameChange,action_sources
    from sentinel.feed.alpaca_observation import structural_action_date
    from sentinel.feed import calendar
    need(descriptor['schema']=='research.alpaca-sparse-factual-identity/1'
         and descriptor['kind']=='SAME_CUSIP_NAME_ONLY' and descriptor['record_kind']=='name_changes'
         and descriptor['source_manifest_sha256']==source_manifest_sha256,'FACTUAL_REPAIR_SCOPE')
    matches=[(key,record) for key,(kind,record) in data.actions.items()
        if kind=='name_changes' and digest(record)==descriptor['record_sha256']]
    need(len(matches)==1,'EXACT_NAME_RECORD_NOT_UNIQUE')
    key,record=matches[0];event=NameChange.model_validate(record)
    day=str(event.process_date);old,new=event.old_symbol,event.new_symbol
    need(event.old_cusip==event.new_cusip and old!=new
         and day==descriptor['effective_session'] and calendar.previous_sessions(day,1)==[day],
         'NAME_ONLY_CUSIP_SYMBOL_DATE')
    need(new in data.by_ticker and old not in data.by_ticker,'UNIQUE_NAME_TARGET_LISTING')
    sid=data.by_ticker[new]
    need(hashlib.sha256(sid.encode()).hexdigest()==descriptor['permanent_id_sha256'],'NAME_PERMANENT_ID')
    need(any(p['file']==descriptor['response_file'] and p['raw_sha256']==descriptor['raw_response_sha256']
             and p['sha256']==descriptor['compressed_response_sha256'] for p in data.action_proofs[key]),'EXACT_ACTION_PREIMAGE')
    for other_id,(kind,other) in data.actions.items():
        if other_id==key or kind=='cash_dividends' or not ({old,new}&action_sources(kind,other)):continue
        when=structural_action_date(kind,other)
        need(when is not None and when!=day,'CONFLICTING_NAME_ACTION')
    target=(day,key,'name_changes');resets=data.resets.get(new,[])
    need(resets.count(target)==1,'EXACT_NAME_RESET_NOT_UNIQUE')
    data.resets[new]=[r for r in resets if r!=target]
    return {'schema':'research.alpaca-name-fact-admission/1','descriptor_sha256':digest(descriptor),
        'record_sha256':descriptor['record_sha256'],'effective_session':day,'permanent_id_sha256':descriptor['permanent_id_sha256'],
        'removed_reset_sha256':digest(target),'primary_extraction_sha256':descriptor['primary_extraction_sha256'],
        'all_other_resets_retained':True,'provider_rows_or_financial_state_modified':False}


def predecessor(previous,descriptor,request_continuation):
    """The bound factual anchor must remain in this book's exact own prefix."""
    previous=Path(previous);basis=descriptor['predecessor'];cp=basis['checkpoint'];path=previous/cp['file']
    need(path.stat().st_size==cp['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==cp['sha256'],
         'FACTUAL_OWN_PREDECESSOR_FILE')
    value=json.loads(gzip.decompress(path.read_bytes()))
    need(value['canonical']['sha256']==basis['inner_sha256']
         and value['canonical']['state_sha256']==basis['state_sha256']==cp['state_sha256']
         and value['canonical']['plan']['source_sha256']==basis['original_source_sha256']
         and value['source_sha256']==basis['execution_source_sha256'] and value['journal']==cp['journal']
         and value['dataset_sha256']==descriptor['dataset_sha256']
         and value['protocol_sha256']==descriptor['protocol_sha256'],'FACTUAL_OWN_PREDECESSOR_CONTENT')
    need(cp['session']<descriptor['effective_session']
         and cp['journal']['bytes']<=request_continuation['checkpoint']['journal']['bytes'],'FACTUAL_ANCHOR_CURSOR')
    with (previous/'canonical.jsonl').open('rb') as f:
        prefix=f.read(cp['journal']['bytes'])
    need(len(prefix)==cp['journal']['bytes'] and hashlib.sha256(prefix).hexdigest()==cp['journal']['sha256'],
         'FACTUAL_ANCHOR_JOURNAL')
    last=json.loads(prefix.splitlines()[-1])
    need(last['state_sha256']==basis['state_sha256'] and last['input_sha256']==basis['input_sha256']
         and last['session']==cp['session'],'FACTUAL_ANCHOR_INPUT_STATE')
    return {'exact_original_anchor_retained':True,'anchor_checkpoint_sha256':cp['sha256'],
        'anchor_state_sha256':basis['state_sha256'],'anchor_input_sha256':basis['input_sha256'],
        'latest_predecessor_sha256':request_continuation['checkpoint']['sha256'],'no_state_conversion':True}
