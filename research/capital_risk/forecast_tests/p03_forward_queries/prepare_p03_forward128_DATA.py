"""Read authentic DATA only and freeze one128-record source-query generation."""
import ast,gzip,hashlib,json
from copy import deepcopy
from datetime import date
from pathlib import Path

ROOT='4c56c4240f1e5f36c91e76f5033ba9748d1217879043885e415727894b67fad1'
OUTER='7bd2591e0e34b22e9800bd8df50a5773e26ddbc4052b015b7a9e17eaec7fe567'
INVENTORY_SHA='7b834fbe86faad5b70b8e718b2b2bd83033fb3a5e25c636bb8606c2d4eddb2dc'
OLD_MODULE_SHA='49bc2a501b377d087b6c60d09231efb994067d5852aa2e4d6fd791c227f0b17c'
CATALOG='system-campaign-p03-own503-forward-source-queries-batch1.json'
MODULE='system_campaign_p03_forward_source_queries.py'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(value):return sha(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def need(value,label):
    if not value:raise ValueError('P03_FORWARD128_DATA_'+label)

def actual_parent(parent,spec):
    from system_campaign_financial_partial import validate_root_spec,root_spec
    validate_root_spec(spec)
    need(spec==root_spec('P03',ROOT) and spec['root_admission_sha256']==ROOT and spec['arm']=='P03'
         and spec['financial_authority'] is False and spec['root_admission']['financial_continuation_authorized'] is True,
         'ONLY_ACTUAL_SEPARATELY_ADMITTED_OWN503_ROOT')
    run=parent['run']
    need(parent['sha256']==OUTER==spec['outer_sha256']==digest({k:v for k,v in parent.items() if k!='sha256'})
         and (parent['completed'],parent['source_cursor'],len(parent['repairs']))==(503,'2019-12-31',16)
         and parent['base']==spec['base'] and parent['repairs']==spec['repairs']
         and run['state_sha256']==spec['state_sha256']==digest(run['state'])
         and run['checkpoint_sha256']==spec['inner_sha256']==digest({k:v for k,v in run.items() if k!='checkpoint_sha256'})
         and run['input_sha256']==spec['input_sha256']==digest(dict(base=parent['base'],repairs=parent['repairs']))
         and run['state']['last_processed_session']==parent['source_cursor'],
         'FULL_ACTUAL503_STATE_INPUT_AND_CLOCK_COMMITMENTS')

def covered_inputs(parent,member):
    covered=set();resources=[]
    for d in parent['repairs']:
        need(d['filename']==d['sha256']+'.json' and Path(d['filename']).name==d['filename'],'SAFE_CURRENT_INPUT_FILENAME_BEFORE_READ')
        name='book/repairs/'+d['filename'];raw=member(name)
        need(sha(raw)==d['sha256'],'EVERY_ACTUAL_FULL16_INPUT_BYTES')
        doc=json.loads(raw);schema=doc['schema']
        need(schema in ('terminal-repair/1','research.leadership-branch-uncertainty-input/1','research.bounded-contingent-sensor-input/1'),
             'ONLY_EXACT_EXISTING_INPUT_SCHEMAS')
        for key in ('suppress','add'):
            for term in doc.get(key,[]):covered.add((term['session'],term['security_id']))
        if schema=='research.bounded-contingent-sensor-input/1':
            event=doc['event'];covered.add((event['native_session'],event['security_id']))
        resources.append(dict(descriptor=deepcopy(d),bytes=len(raw),schema=schema))
    return covered,resources

def positions(parent,sid):
    return [dict(slot_id=e['slot_id'],ticker=e['ticker'],quantity=e['current_shares'],entry_date=e['entry_date'])
        for _,e in sorted(parent['run']['state']['wealth_core']['episodes'].items(),key=lambda item:int(item[0])) if e['security_id']==sid]

def selection(parent,inventory_raw,covered):
    need(sha(inventory_raw)==INVENTORY_SHA,'WHOLE_ORIGINAL_INVENTORY_BEFORE_PARSE')
    records=[json.loads(line) for line in inventory_raw.splitlines() if line]
    candidates=[r for r in records if r.get('type')=='TERMINAL_SCHEDULE' and r['native_session']>parent['source_cursor']
        and r['native']['kind']=='CASH_MERGER' and r['native']['cash_per_share'] is None
        and r['native']['reference'].startswith('actions/acquisitionby') and (r['native_session'],r['security_id']) not in covered]
    candidates.sort(key=lambda r:(r['native_session'],r['security_id'],r['native_term_sha256']))
    need(len(candidates)>128,'MORE_REMAINING_RECORDS_NOT_CLAIMED_COMPLETE')
    selected=candidates[:128];terms=[]
    for record in selected:
        native=record['native'];before=record['anchors']['before'];row=before['identity']
        need(native['session']==record['native_session'] and native['security_id']==record['security_id']
             and digest(native)==record['native_term_sha256'] and row['security_id']==record['security_id'] and row['ticker']==record['ticker']
             and parent['source_cursor']<row['session']<record['native_session']
             and date.fromisoformat(row['listing_first_session'])<=date.fromisoformat(row['session'])
             and row['security_type_eligible'] in ('0','1') and type(row['issuer_id']) is str
             and len(before['fullrow_sha256'])==64,'EXACT_ORIGINAL_NATIVE_AND_FUTURE_SOURCE_BEFORE_IDENTITY')
        terms.append(dict(ticker=record['ticker'],security_id=record['security_id'],session=row['session'],native_session=record['native_session'],
            native_term_sha256=record['native_term_sha256'],parent_positions=positions(parent,record['security_id'])))
    need(len({t['security_id'] for t in terms})==len(terms)==128,'EXACT_FIRST128_UNIQUE_NATIVE_IDENTITIES')
    thor=[t for t in terms if t['security_id']=='731910459224080858']
    need(len(thor)==1 and thor[0]['ticker']=='THOR2' and thor[0]['native_session']=='2020-01-23' and thor[0]['session']=='2020-01-22',
         'ACTUAL_NEXT_THOR2_BLOCKER_INCLUDED_WITH_ORIGINAL_SOURCE_CLOCK')
    return terms,selected,candidates

def prepare(parent,spec,member,inventory_raw):
    actual_parent(parent,spec);covered,resources=covered_inputs(parent,member)
    terms,selected,candidates=selection(parent,inventory_raw,covered)
    catalog=dict(schema='research.explicit-own-forward-source-queries/1',financial_authority=False,input_adopted=False,
        queries=[dict(arm='P03',root_admission_sha256=ROOT,parent_completed=503,parent_input_count=16,
            scope=dict(parent_outer_sha256=parent['sha256'],parent_cursor=parent['source_cursor'],terms=terms,additional_rows=[]))])
    proof=dict(schema='research.P03-first128-forward-source-query-preparation/1',arm='P03',root_admission_sha256=ROOT,
        parent_outer_sha256=parent['sha256'],parent_cursor=parent['source_cursor'],parent_completed=503,full_input_count=16,
        current_input_resources=resources,whole_original_inventory_sha256=INVENTORY_SHA,total_uncovered_acquisition_native_records=len(candidates),
        selected_records=128,remaining_records=len(candidates)-128,selection_order=['native_session','security_id','native_term_sha256'],
        selected_inventory_record_sha256=[digest(r) for r in selected],selected_original_source_before_sha256=[r['anchors']['before']['fullrow_sha256'] for r in selected],
        query_catalog_sha256=sha(encoded(catalog)),query_scope_sha256=digest(catalog['queries'][0]['scope']),
        current_held_queries=[t for t in terms if t['parent_positions']],future_roles_predicted=False,uncommitted_january_state_used=False,
        monetary_consideration_or_policy_qualified=False,input_adopted=False,financial_authority=False,financial_sessions_advanced=0)
    return catalog,proof,selected

def specialize_module(raw,catalog_sha):
    need(sha(raw)==OLD_MODULE_SHA and len(catalog_sha)==64,'WHOLE_CLOSED_P05_FORWARD_MODULE_BYTES')
    text=raw.decode()
    replacements=[("CATALOG='system-campaign-p05-own1152-forward-source-queries.json'","CATALOG='"+CATALOG+"'"),
        ("CATALOG_SHA='8c42192d198c63d74c81d11afbe60c0c383d6d9595cd8bb3e9c73e2889e60115'","CATALOG_SHA='"+catalog_sha+"'"),
        ("arm:Literal['P05']","arm:Literal['P03']")]
    for old,new in replacements:need(text.count(old)==1,'EXACT_THREE_CATALOG_AND_ARM_SPECIALIZATION_SITES');text=text.replace(old,new)
    ast.parse(text,filename=MODULE)
    return text.encode()
