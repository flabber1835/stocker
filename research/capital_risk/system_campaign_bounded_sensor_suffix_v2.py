"""The complete frozen suffix induction with an exact new/retained-event resolver."""
from copy import deepcopy
import gzip,json
from pathlib import Path
from types import FunctionType
from system_campaign_bounded_sensor_input import need,sha,digest
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
import system_campaign_bounded_sensor_event_review as original

def actual_archive(root,row,catalog):
    root=Path(root);day=catalog['event']['effective_session'];matches=[]
    for path in (root/'book/pre-event').glob(day+'-*.json.gz'):
        raw=path.read_bytes();cp=strict_json(raw)
        need(cp['sha256']==digest({k:v for k,v in cp.items() if k!='sha256'}) and path.name==day+'-'+cp['sha256']+'.json.gz',
             'BOUNDED_SUFFIX_ORIGINAL_PRODUCER_FILENAME_AND_FULL_OUTER')
        if cp['run']['state_sha256']==row['prior_state_sha256'] and cp['run']['input_sha256']==row['input_sha256']:
            matches.append((path,raw,cp))
    need(len(matches)==1,'BOUNDED_SUFFIX_ONE_ACTUAL_PRIOR_EVENT_ARCHIVE')
    path,raw,cp=matches[0]
    original.locate(root,row,catalog,input_descriptors=cp['repairs'])
    return path,raw,cp

def preserve(root,current,out,catalog):
    from full_system_core import hosted
    hosted()
    day=catalog['event']['effective_session']
    if current['source_cursor']<day:return None
    from system_campaign_financial_branches import seed
    rows=seed(Path(root),current);event=[r for r in rows if r['session']==day]
    need(len(event)==1,'BOUNDED_SUFFIX_EXACT_ONE_ALREADY_COMMITTED_EVENT_ROW')
    path,raw,cp=actual_archive(root,event[0],catalog)
    exact(Path(out)/'book/pre-event'/path.name,raw)
    return dict(actual=path.name,gzip_sha256=sha(raw),outer_sha256=cp['sha256'],historical_input_sha256=cp['run']['input_sha256'])

def event_permissions(root,parent,retained,rows,catalog,*,through,input_descriptors):
    day=catalog['event']['effective_session']
    if parent['source_cursor']<day:
        return original.permissions(root,rows,catalog,through=through,input_descriptors=input_descriptors)
    need(not any(row['session']==day for row in rows),'BOUNDED_SUFFIX_OLD_EVENT_NOT_REPLAYED_AS_NEW')
    old=[row for row in retained if row['session']==day]
    need(len(old)==1,'BOUNDED_SUFFIX_EVENT_PROOF_MUST_BE_IN_ADMITTED_PRIOR_PREFIX')
    path,raw,cp=actual_archive(root,old[0],catalog)
    _,resolution=original.locate(root,old[0],catalog,input_descriptors=cp['repairs'])
    return {},[dict(resolution,prior_event_basis_revalidated=True,prior_transition_reexecuted=False)]

def bind_suffix(parent,retained):
    def permissions(root,rows,catalog,*,through,input_descriptors):
        return event_permissions(root,parent,retained,rows,catalog,through=through,input_descriptors=input_descriptors)
    need(original.suffix.__closure__ is None,'BOUNDED_SUFFIX_NO_HIDDEN_ORIGINAL_CLOSURE')
    fn=FunctionType(original.suffix.__code__,dict(original.suffix.__globals__,permissions=permissions),
        original.suffix.__name__,original.suffix.__defaults__);fn.__kwdefaults__=deepcopy(original.suffix.__kwdefaults__)
    need(fn.__code__ is original.suffix.__code__,'BOUNDED_SUFFIX_ENTIRE_ORIGINAL_INDUCTION_CODE_OBJECT')
    return fn

def suffix(root,parent,current,retained,rows,financial,catalog,*,growth):
    from full_system_core import hosted
    hosted()
    return bind_suffix(parent,retained)(root,parent,current,retained,rows,financial,catalog,growth=growth)
