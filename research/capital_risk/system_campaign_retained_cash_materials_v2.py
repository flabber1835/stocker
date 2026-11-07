"""Authenticate every later cash material through its full adopted descriptor."""
from copy import deepcopy
import json
from pathlib import PurePosixPath
from system_campaign_facts import digest,sha
from full_system_benchmark import need

REFERENCE='research:system-optimization-002/selected-future-ordinary-input/1'
DIRECTORY='retained-cash-materials-v2'
RULES=frozenset(('CONFIRMED_PREOPEN_COMPLETION','RESEARCH_COMPLETION_DATE_OPEN_AVAILABILITY'))

def inventory(cp,plan,names,member):
    """DATA only: read committed input documents; never restore or stage a book."""
    need(cp['run']['input_sha256']==digest(dict(base=cp['base'],repairs=cp['repairs'])),
         'RETAINED_CASH_V2_FULL_CANONICAL_INPUT_HASH')
    count=plan['current_parent_inputs']
    need(count==14 and len(cp['repairs'])>=count and cp['repairs'][count-1]==plan['descriptor'],
         'RETAINED_CASH_V2_EXACT_ORIGINAL_OBSERVER_BOUNDARY')
    resources={};terms=[];entries=[];keys=set()
    for descriptor in cp['repairs'][count:]:
        name='book/repairs/'+descriptor['filename'];raw=member(name)
        need(descriptor['filename']==descriptor['sha256']+'.json' and sha(raw)==descriptor['sha256'],
             'RETAINED_CASH_V2_EXACT_FULL_TAIL_DESCRIPTOR_BYTES')
        doc=json.loads(raw)
        need(doc['schema']=='terminal-repair/1' and doc['add']
             and all(t['kind']=='CASH_MERGER' for t in doc['add']), 'RETAINED_CASH_V2_ONLY_DECLARED_ORDINARY_CASH_TAIL')
        pins=[r['sha256'] for r in doc['source_evidence'] if r['reference']==REFERENCE+'/hydrated']
        need(len(pins)==1 and type(pins[0]) is str and len(pins[0])==64,'RETAINED_CASH_V2_ONE_COMMITTED_MATERIAL_PIN')
        candidates=[]
        for candidate in sorted(names):
            path=PurePosixPath(candidate)
            if path.name.startswith('hydrated-future-financial-terminal-catalog-') and path.suffix=='.json':
                value=member(candidate)
                if sha(value)==pins[0]:candidates.append((candidate,value))
        need(candidates and all(value==candidates[0][1] for _,value in candidates),
             'RETAINED_CASH_V2_ALL_COMMITTED_MATERIALS_PRESENT_AND_EXACT')
        material_raw=candidates[0][1];material=json.loads(material_raw)
        filename='hydrated-future-financial-terminal-catalog-'+material['parent_outer_sha256']+'.json'
        need(all(PurePosixPath(name).name==filename for name,_ in candidates)
             and material['arm']=='P05' and material['financial_source_changed'] is material['provider_metadata_upgraded'] is False
             and [t['added'] for t in material['terms']]==doc['add']
             and all(t['recognition_rule'] in RULES and not t.get('require_unowned_and_unordered',False)
                     and t['added']['kind']=='CASH_MERGER' for t in material['terms']),
             'RETAINED_CASH_V2_EXACT_ORDINARY_TERMS_NO_SOURCE_ONLY_UPGRADE')
        for term in material['terms']:
            key=term['added']['session'],term['security_id']
            need(key not in keys,'RETAINED_CASH_V2_UNIQUE_CASH_TERMS_ACROSS_FULL_TAIL');keys.add(key)
            terms.append(deepcopy(term))
        prefix=DIRECTORY+'/'+descriptor['sha256']+'/'
        resources[prefix+'overlay.json']=raw;resources[prefix+filename]=material_raw
        entries.append(dict(descriptor=deepcopy(descriptor),material_file=prefix+filename,material_sha256=pins[0],
            overlay_file=prefix+'overlay.json',selected_terms=len(material['terms'])))
    return dict(entries=entries,terms=terms,resources=resources,full_input_count=len(cp['repairs']),
        financial_state_changed=False,financial_sessions_advanced=0)
