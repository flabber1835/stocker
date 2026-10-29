"""Bounded classification of merger consideration recipients; no settlement."""
from datetime import date
from decimal import Decimal
import hashlib
from pydantic import BaseModel,ConfigDict,Field
from alpaca_fit_inputs import need
from alpaca_fit_identity_repair import digest


class StockMerger(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(min_length=1,max_length=128)
    acquiree_symbol:str=Field(min_length=1,max_length=32)
    acquirer_symbol:str=Field(min_length=1,max_length=32)
    acquiree_cusip:str=Field(pattern='^[A-Z0-9]{9}$')
    acquirer_cusip:str=Field(pattern='^[A-Z0-9]{9}$')
    acquiree_rate:Decimal=Field(gt=0,allow_inf_nan=False)
    acquirer_rate:Decimal=Field(gt=0,allow_inf_nan=False)
    effective_date:date
    process_date:date
    payable_date:date|None=None


def apply(data,descriptor,*,source_manifest_sha256):
    from sentinel.feed import calendar
    from sentinel.feed.alpaca_identity import action_sources
    from sentinel.feed.alpaca_observation import structural_action_date
    need(descriptor['schema']=='research.alpaca-recipient-role-registry/1'
         and descriptor['kind']=='STOCK_MERGER_ACQUIRER_ONLY'
         and descriptor['source_manifest_sha256']==source_manifest_sha256,'ROLE_REGISTRY_SCOPE')
    entries=descriptor['events'];hashes=[e['record_sha256'] for e in entries]
    need(0<len(entries)<=1000 and len(set(hashes))==len(hashes) and digest(sorted(hashes))==descriptor['records_sha256'],
         'ROLE_REGISTRY_RECORD_SET')
    stocks={digest(r):(key,r) for key,(kind,r) in data.actions.items() if kind=='stock_mergers'}
    structural={}
    for key,(kind,r) in data.actions.items():
        if kind=='cash_dividends':continue
        for symbol in action_sources(kind,r):structural.setdefault(symbol,[]).append((key,kind,r))
    receipts=[]
    for expected in entries:
        need(expected['effective_session']>descriptor['predecessor']['checkpoint']['session'],'ROLE_FUTURE_ONLY')
        need(expected['record_sha256'] in stocks,'EXACT_STOCK_MERGER_RECORD')
        key,record=stocks[expected['record_sha256']];event=StockMerger.model_validate(record)
        buyer,target=event.acquirer_symbol,event.acquiree_symbol;day=str(event.effective_date)
        need(buyer!=target and event.acquirer_cusip!=event.acquiree_cusip and day==expected['effective_session']
             and calendar.previous_sessions(day,1)==[day],'ROLE_SYMBOL_CUSIP_DATE')
        need(buyer in data.by_ticker and hashlib.sha256(data.by_ticker[buyer].encode()).hexdigest()==expected['permanent_id_sha256'],
             'ROLE_ACQUIRER_ID')
        need(any(p['file']==expected['response_file'] and p['raw_sha256']==expected['raw_response_sha256']
             and p['sha256']==expected['compressed_response_sha256'] for p in data.action_proofs[key]),'ROLE_EXACT_RAW_PREIMAGE')
        for other_id,kind,other in structural.get(buyer,[]):
            if other_id==key:continue
            when=structural_action_date(kind,other)
            need(when is not None and when!=day,'ROLE_CONFLICTING_ACQUIRER_ACTION')
        reset=(day,key,'stock_mergers');before=list(data.resets.get(buyer,[]))
        need(before.count(reset)==1,'ROLE_EXACT_ACQUIRER_RESET')
        target_before=list(data.resets.get(target,[]))
        need(target not in data.by_ticker or reset in target_before,'ROLE_ACQUIREE_RESET_REQUIRED')
        data.resets[buyer]=[v for v in before if v!=reset]
        need(data.resets.get(target,[])==target_before,'ROLE_ACQUIREE_UNCHANGED')
        receipts.append({'record_sha256':expected['record_sha256'],'permanent_id_sha256':expected['permanent_id_sha256'],
            'effective_session':day,'acquiree_reset_unchanged':True,'no_quantity_or_cash_operation':True})
    return {'schema':'research.alpaca-recipient-role-admission/1','descriptor_sha256':digest(descriptor),
        'records_sha256':descriptor['records_sha256'],'events':receipts,'provider_rows_or_financial_state_modified':False}
