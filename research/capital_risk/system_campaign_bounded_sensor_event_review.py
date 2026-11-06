"""Independent one-event basis permission, with whole original B19 induction."""
import ast
from copy import deepcopy
from fractions import Fraction
import gzip,json
from pathlib import Path
from types import SimpleNamespace

from system_campaign_bounded_sensor_input import Event,need,digest,sha,require_no_position

def event_basis(row,before,catalog):
    event=Event.model_validate(catalog['event']).model_dump();source=catalog['market_source']
    sid,day=event['security_id'],event['effective_session']
    require_no_position(SimpleNamespace(wealth_core=before['wealth_core'],pending=before['pending']),sid)
    need(before['last_processed_session']==event['prior_session'] and row['session']==day,
         'BOUNDED_REVIEW_ACTUAL_EVENT_CLOCK')
    names=[item['security_id'] for item in row['material']['rows']]
    need(names==before['median5']['selected'] and len(set(names))==len(names)
         and all(item['prior']==before['median5']['selected_closes'][item['security_id']] for item in row['material']['rows']),
         'BOUNDED_REVIEW_COMPLETE_ACTUAL_PRIOR_WITNESS_PREIMAGE')
    basis=row['bounded_event_basis'];selected=sid in names
    expected=dict(session=day,security_id=sid,selected=selected,event_contract_sha256=digest(event),
        source_term_sha256=digest(dict(catalog['native'],session=day)),source_event_sha256=digest(source))
    interval=None
    if selected:
        anchor=before['feed']['series'][sid]['signal_basis_anchor'];prior=source['raw_prior_row']
        need(anchor[0]==event['prior_session'] and anchor[1]==float(prior['raw_close'])
             and anchor[2]==float(prior['signal_close']), 'BOUNDED_REVIEW_EXACT_FROZEN_RAW_SIGNAL_ANCHOR')
        raw,signal=map(lambda v:Fraction(str(v)),anchor[1:]);split=Fraction(source['split_ratio'])
        need(raw>0 and signal>0 and split>0,'BOUNDED_REVIEW_POSITIVE_RAW_SIGNAL_SPLIT')
        interval=[float((Fraction(event['upfront_cash_per_share'])+Fraction(event[k]))*split*signal/raw)
                  for k in ('right_lower_per_share','right_upper_per_share')]
        expected.update(prior_session=event['prior_session'],raw_anchor=str(anchor[1]),signal_anchor=str(anchor[2]),
            split=str(split),signal_consideration_interval=interval)
        item,=[item for item in row['material']['rows'] if item['security_id']==sid]
        need(item['current']==interval, 'BOUNDED_REVIEW_ENTIRE_EXACT_LEGAL_ENDPOINT_RANGE')
    need(basis==expected, 'BOUNDED_REVIEW_EXACT_ONE_EVENT_SOURCE_AND_LEGAL_BASIS')
    return (day,sid,interval) if selected else None

def locate(root,row,catalog,*,input_descriptors):
    """Read actual producer gzip bytes; create no aliases or checkpoint objects."""
    event=catalog['event'];root=Path(root);matches=[]
    for path in (root/'book/pre-event').glob(event['effective_session']+'-*.json.gz'):
        raw=path.read_bytes();cp=json.loads(gzip.decompress(raw))
        need(cp['sha256']==digest({k:v for k,v in cp.items() if k!='sha256'})
             and path.name==event['effective_session']+'-'+cp['sha256']+'.json.gz',
             'BOUNDED_REVIEW_ORIGINAL_PRODUCER_NAME_AND_OUTER_DIGEST')
        if cp['source_cursor']==event['prior_session'] and cp['run']['state_sha256']==row['prior_state_sha256']:
            need(cp['repairs']==input_descriptors and cp['run']['input_sha256']==row['input_sha256'],
                 'BOUNDED_REVIEW_PRE_EVENT_FULL_ADOPTED_INPUT_IDENTITY')
            permission=event_basis(row,cp['run']['state'],catalog)
            matches.append((permission,dict(actual=path.relative_to(root).as_posix(),gzip_sha256=sha(raw),
                outer_sha256=cp['sha256'],state_sha256=cp['run']['state_sha256'],input_sha256=cp['run']['input_sha256'])))
    need(len(matches)==1,'BOUNDED_REVIEW_ONE_EXACT_ACTUAL_PRE_EVENT_GZIP')
    return matches[0]

def permissions(root,rows,catalog,*,through,input_descriptors):
    day=catalog['event']['effective_session'];found=[r for r in rows if r['session']==day]
    need(len(found)==(1 if through>=day else 0),'BOUNDED_REVIEW_REQUIRED_COMMITTED_EVENT_PROOF')
    allowed={};resolutions=[]
    for row in found:
        permission,resolution=locate(root,row,catalog,input_descriptors=input_descriptors)
        if permission is not None:allowed[digest(row)]=permission
        resolutions.append(resolution)
    return allowed,resolutions

def original_suffix_tree():
    # This function already qualifies the complete B19 source and adapts only
    # the iterator offset plus the single explicit extra-event permission.
    import system_campaign_financial_additional_sensor as original
    return original.suffix_tree()

def suffix(root,parent,current,retained,rows,financial,catalog,*,growth):
    from full_system_core import hosted
    hosted()
    import system_campaign_financial_branches as original
    from system_campaign_uncertainty_math import RollingWitnessBounds
    from sentinel.controller import median5,champion_config
    need(retained and rows is not retained and len(rows)==current['completed']-parent['completed']
         and [row['session'] for row in rows]==sorted(financial)
         and all(parent['source_cursor']<row['session']<=current['source_cursor'] for row in rows),
         'BOUNDED_REVIEW_EXACT_COMMITTED_FINANCIAL_SUFFIX')
    allowed,resolutions=permissions(root,rows,catalog,through=current['source_cursor'],input_descriptors=current['repairs'])
    def allows(row,item):
        expected=allowed.get(digest(row))
        return expected is not None and (row['session'],item['security_id'],item['current'])==expected
    namespace=dict(vars(original),rows=rows,retained_count=len(retained),cp=current,financial=financial,
        math_state=RollingWitnessBounds.restore(retained[-1]['math']),possible=deepcopy(retained[-1]['possible_after']),
        representative=original.discrete(parent['run']['state']['median5']),median5=median5,champion_config=champion_config,
        total=0,maximum=len(retained[-1]['possible_after']),growth=growth,additional_event_allows=allows)
    exec(compile(original_suffix_tree(),'<whole-original-B19-induction-with-one-source-bound-event>','exec'),namespace)
    return dict(rows=len(rows),retained_rows=len(retained),exhaustive_leaves=namespace['total'],
        maximum_possible_states=namespace['maximum'],event_resolution=resolutions,
        prior_proof_rows_reexecuted=0,every_reachable_decision_identical=True)
