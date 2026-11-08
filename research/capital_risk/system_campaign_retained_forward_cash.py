"""Authenticated ordinary cash observations; canonical inputs are never rewritten."""
import ast
from contextlib import contextmanager
from copy import deepcopy
import gzip,json
from pathlib import Path

from system_campaign_facts import sha,digest
from full_system_benchmark import need

HERE=Path(__file__).parent
PLAN='system-campaign-p05-retained-cash-observer-plans.json'
PLAN_SHA='d2f68ad306ea74a42319ef77fa79c719c37c2c2cae4e76329fe1f5702a4ad827'
DIRECTORY='retained-forward-cash'
PARENT='observer-origin.json.gz'

def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def source_names():
    return ('system_campaign_retained_forward_cash.py',PLAN,
        'system_campaign_qualified_explicit_cash.py','system-campaign-msp-common-cash-primary-fact.json')

def plans():
    raw=(HERE/PLAN).read_bytes();need(sha(raw)==PLAN_SHA,'RETAINED_CASH_EXACT_PLAN_BYTES')
    value=json.loads(raw)
    need(value['schema']=='research.retained-ordinary-cash-observer-plans/1'
         and value['financial_authority'] is value['canonical_financial_source_changed'] is False
         and len(value['plans'])==1,'RETAINED_CASH_ONLY_QUALIFIED_PLAN')
    return value['plans']

def selected(cp,spec):
    return [p for p in plans() if p['arm']==spec.get('arm') and p['descriptor'] in cp['repairs']]

def namespace(plan):return DIRECTORY+'/'+plan['descriptor']['sha256']

def checked_resources(root,cp,plan):
    """Read and authenticate metadata only; never restore or serialize a book."""
    root=Path(root);directory=root/namespace(plan)
    if directory.exists():
        paths={plan['ordinary_overlay']:directory/plan['ordinary_overlay'],
               plan['material_file']:directory/plan['material_file'],PARENT:directory/PARENT}
    else:
        paths={plan['ordinary_overlay']:root/plan['ordinary_overlay'],
               plan['material_file']:root/plan['material_file'],
               PARENT:root/'book/predecessor-checkpoints'/(plan['origin_outer_sha256']+'.json.gz')}
    resources={name:path.read_bytes() for name,path in paths.items()}
    raw=resources[PARENT]
    need(dict(bytes=len(raw),sha256=sha(raw))==plan['parent_gzip'],'RETAINED_CASH_EXACT_AUTHENTIC_ORIGIN_GZIP')
    origin=json.loads(gzip.decompress(raw))
    need(origin['sha256']==plan['origin_outer_sha256'] and origin['base']==cp['base']
         and cp['repairs'][:plan['current_parent_inputs']]==origin['repairs']+[plan['descriptor']]
         and cp['source_cursor']>=origin['source_cursor'],'RETAINED_CASH_FULL_ORIGINAL_DESCRIPTOR_PREFIX')
    overlay=resources[plan['ordinary_overlay']];material_raw=resources[plan['material_file']]
    need(sha(overlay)==plan['descriptor']['sha256']
         and overlay==(root/'book/repairs'/plan['descriptor']['filename']).read_bytes()
         and sha(material_raw)==plan['material_sha256'],'RETAINED_CASH_EXACT_ADOPTED_SOURCE_RESOURCES')
    doc,material=json.loads(overlay),json.loads(material_raw)
    need(material['arm']==plan['arm'] and material['parent_outer_sha256']==origin['sha256']
         and len(material['terms'])==plan['terms_count']
         and doc['add']==[t['added'] for t in material['terms']]
         and all(t['added']['kind']=='CASH_MERGER' and not t.get('require_unowned_and_unordered',False)
                 for t in material['terms']),'RETAINED_CASH_ALL_ORDINARY_CASH_TERMS')
    return resources,origin,material['terms']

def observer_class(plan):
    import system_campaign_financial_future as future
    tree=ast.parse(Path(future.__file__).read_bytes())
    actual={n.name:sha(ast.dump(n,include_attributes=False).encode()) for n in tree.body
            if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in plan['original_observer_ast']}
    need(actual==plan['original_observer_ast'],'RETAINED_CASH_WHOLE_ORIGINAL_OBSERVER_AND_HELPERS')
    return future.ActualEvents

def merge_terms(event,terms):
    for term in terms:
        added=term['added'];key=added['session'],added['security_id']
        need(added['kind']=='CASH_MERGER' and (key not in event.terms or event.terms[key]==added),
             'RETAINED_CASH_NO_CONFLICTING_OBSERVATION_TERM')
        event.terms[key]=deepcopy(added)
    need(event.scopes==[],'RETAINED_CASH_NO_SOURCE_ONLY_AUTHORITY_UPGRADE')
    return event

def committed_logs(root,cp,plan):
    root=Path(root);result={}
    for directory in (root/namespace(plan),root):
        for path in directory.glob('actual-future-event-20*.json'):
            day=path.stem.removeprefix('actual-future-event-')
            if day>cp['source_cursor']:continue
            raw=path.read_bytes()
            need(day not in result or result[day]==raw,'RETAINED_CASH_NO_CONFLICTING_COMMITTED_LOG')
            result[day]=raw
    return result

def write_exact(path,raw):
    path=Path(path)
    if path.exists():need(path.read_bytes()==raw,'RETAINED_CASH_EXISTING_RESOURCE_BYTES')
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(raw)

def stage(root,cp,out,plan):
    from full_system_core import hosted
    hosted()
    resources,origin,terms=checked_resources(root,cp,plan)
    target=Path(out)/namespace(plan)
    for name,raw in resources.items():write_exact(target/name,raw)
    for day,raw in committed_logs(root,cp,plan).items():write_exact(target/('actual-future-event-'+day+'.json'),raw)
    return terms

@contextmanager
def context(root,cp,out,spec):
    chosen=selected(cp,spec)
    if not chosen:yield;return
    from full_system_core import hosted
    hosted()
    need(len(chosen)==1,'RETAINED_CASH_ONE_EXPLICIT_OBSERVER_FAMILY')
    plan,=chosen;Original=observer_class(plan);terms=stage(root,cp,out,plan)
    import system_campaign_financial_future as future
    class ObservedCash(Original):
        def __init__(self,target,arm,*,cp=None):
            Original.__init__(self,target,arm,cp=cp)
            need(arm==plan['arm'] and Path(target)==Path(out),'RETAINED_CASH_EXACT_ACTIVE_OBSERVER_OUTPUT')
            merge_terms(self,terms)
    need(ObservedCash.advance is Original.advance and ObservedCash.terminal is Original.terminal,
         'RETAINED_CASH_ORIGINAL_CALLER_FRAME_METHODS')
    future.ActualEvents=ObservedCash
    try:yield
    finally:future.ActualEvents=Original

def verify_records(rows,events,observed,terms,through):
    """Validate the entire per-date set before the unchanged per-term reviewer."""
    from system_campaign_ordinary_augmentation_data import cash_tree
    raw=(HERE/'system_campaign_ordinary_augmentation_cash_v1.py').read_bytes()
    need(sha(raw)=='50136003e25cd8f63190d68c81eb2b3f402c7f25858361db19400f5d80de4683',
         'RETAINED_CASH_ORIGINAL_CASH_REVIEW_SOURCE')
    from decimal import Decimal
    scope=dict(D=Decimal,need=need)
    exec(compile(ast.Module(body=[cash_tree(raw)],type_ignores=[]),'<original-independent-cash-review>', 'exec'),scope)
    expected={}
    for term in terms:
        day=term['added']['session']
        if day<=through:expected.setdefault(day,[]).append(term)
    need(set(observed)==set(expected),'RETAINED_CASH_COMPLETE_COMMITTED_EVENT_AXIS')
    checked=[]
    for day,group in expected.items():
        record=observed[day];ids={t['security_id'] for t in group}
        need(len(ids)==len(group) and record['source']==record['stock']==record['risk']==[]
             and record['engine_calls']==0 and len(record['cash'])==len(group)
             and {c['security_id'] for c in record['cash']}==ids
             and len(record['order'])==len(group)
             and set(record['order'])=={'CASH:'+sid for sid in ids},'RETAINED_CASH_EXACT_WHOLE_DAILY_CALL_SET')
        indexes=[i for i,r in enumerate(rows) if r['session']==day]
        need(len(indexes)==1 and indexes[0]>0,'RETAINED_CASH_ACTUAL_ADJACENT_ACCOUNTING')
        i=indexes[0];before=rows[i-1]['evidence']['research_entry_audit']['closing_accounting']
        opened=rows[i]['evidence']['research_entry_audit']['opening_accounting']
        for term in group:
            sid=term['security_id'];one=deepcopy(record)
            one['cash']=[c for c in record['cash'] if c['security_id']==sid];one['order']=['CASH:'+sid]
            checked.append(scope['verify_event'](one,term,before,opened,events))
    return checked

def review(evidence,out,spec,cp):
    chosen=selected(cp,spec)
    if not chosen:return
    need(len(chosen)==1,'RETAINED_CASH_ONE_REVIEW_FAMILY');plan,=chosen
    _,_,terms=checked_resources(evidence,cp,plan)
    import system_campaign_financial_future as future
    material=Path(evidence)/('hydrated-future-financial-terminal-catalog-'+spec['outer_sha256']+'.json')
    if material.exists():
        new=json.loads(material.read_bytes())['terms']
        need(all(t['added']['kind']=='CASH_MERGER' for t in new),'RETAINED_CASH_NEW_OBSERVER_CASH_ONLY')
        terms=deepcopy(terms)
        for term in new:
            key=(term['added']['session'],term['security_id'])
            old=[t for t in terms if (t['added']['session'],t['security_id'])==key]
            need(not old or old==[term],'RETAINED_CASH_REVIEW_NO_CONFLICTING_TERM')
            if not old:terms.append(term)
    from system_campaign_uncertainty_review import committed_rows
    logs=committed_logs(evidence,cp,plan)
    observed={day:json.loads(raw) for day,raw in logs.items()}
    result=verify_records(committed_rows(Path(evidence)/'book',cp,'daily'),
        cp['run']['state']['ledger']['events'],observed,terms,cp['source_cursor'])
    write_exact(Path(out)/'retained-forward-cash-review.json',encoded(dict(passed=True,
        events=result,financial_sessions_reexecuted=0,retained_terms=plan['terms_count'],
        original_observer_methods_unchanged=True,all_committed_logs_required=True)))

def review_entry(evidence,out,spec,legacy):
    from full_system_core import hosted
    hosted()
    # The legacy body performs all original canonical read-only checks first.
    legacy(evidence,out,spec)
    cp=json.loads(gzip.decompress((Path(evidence)/'book/checkpoint.json.gz').read_bytes()))
    review(evidence,out,spec,cp)
