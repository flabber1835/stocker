"""Exact initial-root routing and whole original gate/induction AST bindings."""
import ast,json
from copy import deepcopy
from pathlib import Path
from system_campaign_bounded_sensor_input import need,sha,digest
from system_campaign_abmd_bounded_catalog import encoded,load,document

HERE=Path(__file__).parent
ROOT='947662b7b86089285e5d7360221ff3a6d931173bccbce6ac8884341d396c763e'
CATALOG='P06-own1238-ABMD-bounded-catalog-v2.json'
CATALOG_SHA='dc1f6fe12216fca27f79165a29a03b1b88c490344b727ea51f207e97970e1e90'
PLAN='P06-own1238-ABMD-initial-source-plan.json'
PLAN_SHA='b0f3a450766cec498d5bb4326d14c59b220c34696ca637ed5014e9a8bd443fa4'
GATE_SOURCE='3ec636f898e9c3918047da18150660be37fd08f680818ec93064dfa355a1f6a8'
BRANCH_SOURCE='b19a93be7b6887c1b92a5a676fefecc5477addfaf99efcf1f18f45eafb6140ef'
BOUND_DIRECTORY='abmd-bounded-input-adoption'
BOUND_DOCUMENT='abmd-bounded-sensor-input.json'

def selected(spec):
    return isinstance(spec,dict) and spec.get('arm')=='P06' and spec.get('root_admission_sha256')==ROOT

def catalog():
    raw=(HERE/CATALOG).read_bytes();need(sha(raw)==CATALOG_SHA,'P06_LIFECYCLE_EXACT_FROZEN_CATALOG')
    return load(HERE/CATALOG)

def plan():
    raw=(HERE/PLAN).read_bytes();need(sha(raw)==PLAN_SHA,'P06_LIFECYCLE_EXACT_SOURCE_PLAN');return json.loads(raw)

def source_names():
    from system_campaign_abmd_bounded_sources import source_names as shared
    return tuple(sorted(set(shared(('P06',)))|{PLAN,'system_campaign_p06_abmd_lifecycle_data.py',
        'system_campaign_p06_abmd_lifecycle.py','system_campaign_p06_abmd_gateway.py',
        'system_campaign_bounded_sensor_event_review.py','system_campaign_retained_forward_cash.py',
        'system_campaign_ordinary_augmentation_data.py','system_campaign_ordinary_augmentation_cash_v1.py'}))

def checked_resources(root,source_plan):
    root=Path(root);result={}
    for name,identity in source_plan['old_resources'].items():
        raw=(root/name).read_bytes()
        need(dict(bytes=len(raw),sha256=sha(raw))==identity,'P06_LIFECYCLE_ALL_OLD_SOURCE_AND_EVENT_BYTES')
        result[name]=raw
    need(len(result)==18,'P06_LIFECYCLE_COMPLETE_ORIGINAL_RESOURCE_SET')
    return result

def forward_terms(source_plan):
    result=[]
    for term in source_plan['forward_terms']:
        added=term['added']
        need(term['descriptor'] in source_plan['old_descriptors'] and added['kind']=='CASH_MERGER'
             and added['security_id']=='362949419836618645' and added['session']=='2023-03-10'
             and added['cash_per_share']==27.,'P06_LIFECYCLE_ONLY_ORIGINAL_ADOPTED_FORWARD_MYOV')
        result.append(dict(added=deepcopy(added),security_id=added['security_id'],ticker='MYOV'))
    need(len(result)==1,'P06_LIFECYCLE_ONE_EXISTING_FORWARD_TERM');return result

def adoption_tree(raw):
    need(sha(raw)==GATE_SOURCE,'P06_LIFECYCLE_ENTIRE_ORIGINAL_PAUSE_HELPER')
    fn=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption')
    mapping=[n.value for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names']
    need(len(mapping)==1 and isinstance(mapping[0],ast.Dict)
         and [ast.unparse(n) for n in mapping[0].keys]==['ORDINARY_ADOPTION','DATE_ADOPTION','MODEL_ADOPTION'],
         'P06_LIFECYCLE_ONE_EXACT_ORIGINAL_FILENAME_MAP')
    mapping[0].keys.append(ast.Constant(BOUND_DIRECTORY));mapping[0].values.append(ast.Constant(BOUND_DOCUMENT))
    return ast.fix_missing_locations(fn)

def initial_review_tree(raw):
    need(sha(raw)==BRANCH_SOURCE,'P06_REVIEW_ENTIRE_ORIGINAL_B19_SOURCE')
    fn=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='review')
    loop,=[n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.target)=='(index, row)']
    need(ast.unparse(loop.iter)=='enumerate(rows)','P06_REVIEW_ORIGINAL_ZERO_BASED_FIRST_PROOF_ITERATOR')
    first,=[n for n in loop.body if isinstance(n,ast.If) and ast.unparse(n.test)=='index == 0']
    first.body=ast.parse('qualified_initial_event(row,before)').body
    current,=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='BRANCH_EXACT_CURRENT_REPRESENTATIVE_STATE' for v in n.value.args)]
    return ast.fix_missing_locations(ast.Module(body=[loop,current],type_ignores=[]))

def expected_preparation(catalog,hashes):
    cloud=dict(passed=True,exact_controller_sources=hashes,ambiguous_comparisons_exhaustively_partitioned=True,
        all_possible_counters_retained_and_later_merged=True,actual_divergent_decisions_refused=True,historical_financial_sessions_advanced=0)
    return dict(schema='research.abmd-zero-transition-parser-packet-cloud-preparation/1',passed=True,arm='P06',
        root_admission_sha256=ROOT,parent_outer_sha256=catalog['parent_outer_sha256'],catalog_sha256=CATALOG_SHA,
        document_sha256=sha(encoded(document(catalog))),market_source_sha256=catalog['market_source_sha256'],
        packets=dict(actual_packet_checks=2,actual_selected_signal_range=[380.,415.],unselected_has_no_right_value=True,
            native_day_bar_preserved=True,effective_day_quote_absent=True,original_incomplete_guard_retained=True,
            wrong_predecessor_and_consumed_native_cursor_refused=True,no_financial_transition=True),
        cloud_qualification_sha256=sha(encoded(cloud)),old_descriptors_preserved=8,
        financial_sessions_advanced=0,checkpoint_adopted=False,financial_authority=False,cash_or_right_price_created=False)
