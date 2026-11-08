"""Fresh frozen native and quote witnesses for a separately typed sensor input."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import zipfile

from system_campaign_bounded_sensor_input import need,digest,sha
from system_campaign_bounded_sensor_catalog import validate,encoded
from system_campaign_bounded_sensor_semantics import verify as verify_semantics

def witness(catalog,native,rows):
    event=catalog['event'];source=catalog['market_source']
    need(native==catalog['native'] and digest(native)==event['native_term_sha256']
         and native['cash_per_share'] is None and native['session']==event['native_session'],
         'BOUNDED_HYDRATE_EXACT_ACTUAL_INCOMPLETE_NATIVE')
    expected=[source['raw_prior_row'],source['raw_event_row']]
    need(len(rows)==len(expected)==2 and sorted(rows,key=lambda row:row['session'])==sorted(expected,key=lambda row:row['session'])
         and len({(row['session'],row['security_id']) for row in rows})==2,
         'BOUNDED_HYDRATE_COMPLETE_ACTUAL_FROZEN_PRIOR_AND_EVENT_ROWS')
    need(source['source_quote_present'] is True and source['split_ratio']==source['raw_event_row']['split_ratio']
         and source['source_observation_sha256']==digest(source['raw_event_row'])
         and source['event_contract_sha256']==digest(event), 'BOUNDED_HYDRATE_EXACT_EVENT_QUOTE_SPLIT_AND_CONTRACT')
    return deepcopy(source)

def hydrate(catalog,out):
    from full_system_core import hosted
    hosted()
    from system_campaign_financial_partial import root_spec
    from research.pooled_input_support import inputs
    validate(catalog,root_lookup=root_spec);verify_semantics(catalog)
    event=catalog['event'];sid=event['security_id']
    natives=[v for v in inputs.load_actions(Path('/frozen/bundle')).terminal.get(event['native_session'],()) if v.security_id==sid]
    need(len(natives)==1,'BOUNDED_HYDRATE_ONE_ACTUAL_SOURCE_NATIVE')
    rows=[]
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for row in inputs._archive_rows(archive,'observations-'+event['effective_session'][:4]+'.csv.gz'):
            if row['security_id']==sid and row['session'] in (event['prior_session'],event['effective_session']):rows.append(row)
    native,=natives;source=witness(catalog,asdict(native),rows);raw=encoded(source)
    need(sha(raw)==catalog['market_source_sha256'],'BOUNDED_HYDRATE_EXACT_COMPLETE_MARKET_SOURCE_BYTES')
    out=Path(out)
    if out.exists():need(out.read_bytes()==raw,'BOUNDED_HYDRATE_EXISTING_EXACT_SOURCE_BYTES')
    else:
        with out.open('xb') as stream:stream.write(raw)
    return native,source
