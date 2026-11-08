"""Full annual absent-quote verification before hosted ABMD input qualification."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import zipfile
from system_campaign_abmd_bounded_catalog import validate,encoded,SID
from system_campaign_bounded_sensor_input import need,digest,sha

def witness(catalog,native,rows,*,scanned,security_rows,last_source_session):
    market=catalog['market_source'];by_day={}
    for row in rows:
        need(row['security_id']==SID and row['session'] not in by_day,'ABMD_HYDRATE_UNIQUE_COMPLETE_SOURCE_ROWS')
        by_day[row['session']]=row
    need(native==catalog['native'] and digest(native)==catalog['event']['native_term_sha256']
         and native['session']=='2022-12-21' and native['cash_per_share'] is None,
         'ABMD_HYDRATE_EXACT_ACTUAL_INCOMPLETE_NATIVE')
    need(type(scanned) is type(security_rows) is int and scanned==2080223 and security_rows==245
         and last_source_session=='2022-12-21' and set(by_day)=={'2022-12-20','2022-12-21'}
         and by_day['2022-12-20']==market['raw_identity_row'] and by_day['2022-12-21']==market['raw_prior_row']
         and market['source_quote_present'] is False and market['raw_event_row'] is None,
         'ABMD_HYDRATE_FULL_ANNUAL_SCAN_NO_DEC22_QUOTE')
    need(market['split_ratio']=='1' and market['split_rule']=='CANONICAL_NO_EVENT_BAR_UNIT_SPLIT'
         and market['event_contract_sha256']==digest(catalog['event']), 'ABMD_HYDRATE_ABSENCE_BASIS_AND_EVENT')
    return deepcopy(market)

def hydrate(catalog,out):
    from full_system_core import hosted
    hosted()
    from system_campaign_financial_partial import root_spec
    from research.pooled_input_support import inputs
    validate(catalog,root_lookup=root_spec)
    actions=inputs.load_actions(Path('/frozen/bundle'))
    native,=[t for t in actions.terminal.get('2022-12-21',()) if t.security_id==SID]
    need(not any(t.security_id==SID for t in actions.terminal.get('2022-12-22',())),
         'ABMD_HYDRATE_NO_EFFECTIVE_DAY_BASE_TERM_COLLISION')
    scanned=security_rows=0;last=None;rows=[]
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        raw=archive.read('observations-2022.csv.gz')
        need(sha(raw)==catalog['market_source']['annual_member_sha256'],'ABMD_HYDRATE_ENTIRE_ANNUAL_MEMBER_BEFORE_PARSE')
        for row in inputs._archive_rows(archive,'observations-2022.csv.gz'):
            scanned+=1
            if row['security_id']!=SID:continue
            security_rows+=1;last=row['session'] if last is None or row['session']>last else last
            if row['session'] in ('2022-12-20','2022-12-21','2022-12-22'):rows.append(row)
    source=witness(catalog,asdict(native),rows,scanned=scanned,security_rows=security_rows,last_source_session=last)
    raw=encoded(source);need(sha(raw)==catalog['market_source_sha256'],'ABMD_HYDRATE_EXACT_SOURCE_BYTES')
    out=Path(out)
    if out.exists():need(out.read_bytes()==raw,'ABMD_HYDRATE_EXISTING_EXACT_SOURCE')
    else:
        with out.open('xb') as stream:stream.write(raw)
    return native,source
