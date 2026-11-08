"""Authenticate inherited P03 observation resources, without any book staging."""
from copy import deepcopy
import gzip,json
from pathlib import Path
from system_campaign_facts import digest,sha
from full_system_benchmark import need

HERE=Path(__file__).parent
PLAN='P03-own462-DOVA-full-lifecycle-plan.json'
PLAN_SHA='24c7d503336c84a7be151f77810e1ff865aa7fa585ac479d318a5e98de531284'
INVENTORY='P03-own462-inherited-observer-inventory.json'
INVENTORY_SHA='cb2bc9121564530c186a12c62d8535709a18d89cfb77f85d839cf098290806d3'
LEGACY={'362949419836618645':'MYOV','498918945550351909':'TGI','272838527679530510':'ZAYO'}

def records():
    p=(HERE/PLAN).read_bytes();i=(HERE/INVENTORY).read_bytes()
    need(sha(p)==PLAN_SHA and sha(i)==INVENTORY_SHA,'BOUNDED_OBSERVER_EXACT_CLOSED_PLAN_AND_INVENTORY')
    return json.loads(p),json.loads(i)

def inventory(cp,plan,expected,member):
    run=cp['run']
    need(cp['sha256']==plan['outer_sha256']==digest({k:v for k,v in cp.items() if k!='sha256'})
         and (cp['completed'],cp['source_cursor'])==(462,'2019-10-31')
         and run['input_sha256']==digest(dict(base=cp['base'],repairs=cp['repairs']))
         and cp['repairs']==plan['original_descriptor_prefix'] and len(cp['repairs'])==15,
         'BOUNDED_OBSERVER_FULL_ACTUAL_OWN462_INPUT_IDENTITY')
    future=[];resources={}
    for descriptor in cp['repairs']:
        name='book/repairs/'+descriptor['filename'];raw=member(name)
        need(descriptor['filename']==descriptor['sha256']+'.json' and sha(raw)==descriptor['sha256'],
             'BOUNDED_OBSERVER_EVERY_ORIGINAL_INPUT_FILE')
        doc=json.loads(raw);terms=[t for t in doc.get('add',[]) if t['session']>cp['source_cursor']]
        if terms:
            need(doc['schema']=='terminal-repair/1' and all(t['kind'] in ('CASH_MERGER','CASH_PLUS_STOCK','CONVERSION') for t in terms),
                 'BOUNDED_OBSERVER_ONLY_DECLARED_ORDINARY_FORWARD_TERMS')
            future.append(dict(descriptor=deepcopy(descriptor),future_terms=deepcopy(terms),schema=doc['schema'],source_evidence=doc['source_evidence']))
    need(future==expected['future_inputs'] and sum(len(v['future_terms']) for v in future)==expected['future_term_count']==17,
         'BOUNDED_OBSERVER_ALL17_FORWARD_TERMS_NO_OMISSIONS')
    raw=member(plan['ordinary_observer_origin_gzip'])
    need(dict(bytes=len(raw),sha256=sha(raw))==plan['ordinary_observer_origin_gzip_pin'],
         'BOUNDED_OBSERVER_AUTHENTIC_OLD_ORIGIN_BYTES_BEFORE_PARSE')
    origin=json.loads(gzip.decompress(raw))
    need(origin['sha256']==plan['ordinary_observer_origin_outer']==digest({k:v for k,v in origin.items() if k!='sha256'})
         and origin['base']==cp['base'] and origin['repairs']+[expected['ordinary_descriptor']]==cp['repairs'][:13]
         and (origin['completed'],origin['source_cursor'])==(439,'2019-09-30'),
         'BOUNDED_OBSERVER_AUTHENTIC_OLD_ORIGIN_IS_METADATA_ONLY')
    resources['observer-origin.json.gz']=raw
    ordinary=member('book/repairs/'+expected['ordinary_descriptor']['filename']);material_raw=member(plan['ordinary_material'])
    need(sha(ordinary)==expected['ordinary_descriptor']['sha256'] and sha(material_raw)==plan['ordinary_material_sha256'],
         'BOUNDED_OBSERVER_AUTHENTIC_ORDINARY_MATERIAL_BYTES_BEFORE_PARSE')
    material=json.loads(material_raw);doc=json.loads(ordinary)
    need(material['parent_outer_sha256']==origin['sha256'] and material['arm']=='P03'
         and len(material['terms'])==15 and [t['added'] for t in material['terms']]==doc['add']
         and all(not t.get('require_unowned_and_unordered',False) for t in material['terms']),
         'BOUNDED_OBSERVER_EXACT_ORIGINAL_ORDINARY_MATERIAL')
    resources.update({'ordinary-overlay.json':ordinary,plan['ordinary_material']:material_raw})
    for name,pin in {**plan['original_resource_pins'],**{n:v['sha256'] for n,v in plan['original_branch_event_archives'].items()}}.items():
        raw=member(name);need(sha(raw)==pin,'BOUNDED_OBSERVER_ALL_ORIGINAL_PROOF_AND_SOURCE_RESOURCES');resources[name]=raw
    legacy=[t for entry in future if entry['descriptor']!=expected['ordinary_descriptor'] for t in entry['future_terms']]
    need({t['security_id'] for t in legacy}==set(LEGACY) and len(legacy)==3
         and all(t['kind']=='CASH_MERGER' for t in legacy),'BOUNDED_OBSERVER_THREE_EXACT_LEGACY_CASH_TERMS')
    terms=deepcopy(material['terms'])+[dict(ticker=LEGACY[t['security_id']],security_id=t['security_id'],added=deepcopy(t)) for t in legacy]
    keys=[(t['added']['session'],t['security_id']) for t in terms]
    need(len(keys)==len(set(keys))==18 and sum(day>cp['source_cursor'] for day,sid in keys)==17
         and {t['ticker'] for t in terms if t['added']['kind']=='CONVERSION'}=={'S2'}
         and {t['ticker'] for t in terms if t['added']['kind']=='CASH_PLUS_STOCK'}=={'WLH','BMCH'},
         'BOUNDED_OBSERVER_COMPLETE_UNION_WITH_CONVERSION_AND_MIXED')
    return dict(terms=terms,resources=resources,origin_metadata=origin,
        full_input_count=15,forward_terms=17,observation_terms=18,
        financial_sessions_advanced=0,financial_seed_is_current_own462=True,old_origin_is_financial_seed=False,
        conversion_review_required=True,mixed_consideration_review_required=True)
