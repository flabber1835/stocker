"""Generic immutable ordinary activation source and original cash observer binding.

Hydration is hosted only. Selection and metadata checks are pure DATA. Financial
calls remain inside the unchanged original ActualEvents delegating observer.
"""
import ast
from copy import deepcopy
from dataclasses import asdict,is_dataclass
import inspect
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

from system_campaign_financial_compound_input_v2 import sha,digest,encoded,need

HERE=Path(__file__).parent
MATERIAL='hydrated-compound-v2-ordinary-input.json'
SCHEMA='research.generic-original-ordinary-activation/1'
BRANCH_SHA='b19a93be7b6887c1b92a5a676fefecc5477addfaf99efcf1f18f45eafb6140ef'
OBSERVER_FILE='system_campaign_financial_ordinary_observer_v1.py'
OBSERVER_SHA='a09361056879e891d831daec06686895a6cbb20dca0b1a0a9cded8dae1c650a3'
PREFLIGHT_SHA='0145e6ce84048faf80f49ae20095f29eaf8dc479be4dfd932ec648326d5cf68c'


def select_original(record):
    plan=record['ordinary_activation'];raw=(HERE/plan['catalog_file']).read_bytes()
    need(sha(raw)==plan['catalog_sha256'] and sha((HERE/plan['validator_file']).read_bytes())==plan['validator_sha256'],
         'COMPOUND_V2_ORIGINAL_ORDINARY_CATALOG_AND_VALIDATOR_BYTES')
    full=json.loads(raw);wanted=plan['selected_tickers'];selected=[deepcopy(t) for t in full['terms'] if t['ticker'] in wanted]
    need(wanted and len(set(wanted))==len(wanted) and len(selected)==len(wanted)
         and {t['ticker'] for t in selected}==set(wanted)
         and all(t['recognition_rule'] in ('CONFIRMED_PREOPEN_COMPLETION','RETAINED_NEXT_SESSION_AFTER_CONFIRMED_LAST_TRADING_DAY')
                 and t['added']['kind']=='CASH_MERGER' and t['mandatory_common_share_completion_confirmed'] is True for t in selected),
         'COMPOUND_V2_GENUINE_NONEMPTY_ORIGINAL_MANDATORY_CASH_SUBSET')
    from system_campaign_cash_calendar import CashCalendar
    subset=dict(deepcopy(full),terms=selected);codec=CashCalendar(subset)
    return codec,full,subset


def original_parent(spec):
    a=spec['root_admission']
    return dict(sha256=spec['outer_sha256'],source_cursor=spec['selected_session'],base=deepcopy(spec['base']),
        run=dict(checkpoint_sha256=spec['inner_sha256'],input_sha256=spec['input_sha256']),repairs=deepcopy(a['repairs']))


def require_parent(cp,record,origin):
    need((origin['sha256'],origin['source_cursor'],origin['run']['checkpoint_sha256'],origin['run']['input_sha256'])
         ==(record['parent_outer_sha256'],record['parent_cursor'],record['parent_inner_sha256'],record['parent_input_sha256'])
         and cp['base']==origin['base'] and cp['source_cursor']>=origin['source_cursor']
         and cp['repairs'][:len(origin['repairs'])]==origin['repairs']
         and (cp['source_cursor']!=origin['source_cursor'] or cp['sha256']==origin['sha256']),
         'COMPOUND_V2_ORDINARY_ORIGINAL_OWN_PARENT_AND_RETAINED_INPUT_PREFIX')


def inherited_proof(cp,root,subset,*,branch_validator):
    root=Path(root);targets={t['security_id'] for t in subset['terms']};rows=[];branches=[]
    def selected(value):
        if isinstance(value,dict):
            return any(k in ('security_id','parent_security_id','child_security_id','delivered_security_id') and isinstance(v,str) and v in targets
                       for k,v in value.items()) or any(selected(v) for v in value.values())
        return isinstance(value,(tuple,list)) and any(selected(v) for v in value)
    for descriptor in cp['repairs']:
        raw=(root/'book/repairs'/descriptor['filename']).read_bytes();value=json.loads(raw)
        need(descriptor['filename']==descriptor['sha256']+'.json' and sha(raw)==descriptor['sha256']
             and value['schema'] in ('terminal-repair/1','research.leadership-branch-uncertainty-input/1'),
             'COMPOUND_V2_ALL_INHERITED_ORDINARY_AND_BRANCH_BYTES')
        need(not selected(value),'COMPOUND_V2_GENUINE_ORDINARY_TARGET_NOT_PREVIOUSLY_ADOPTED')
        rows.append(dict(descriptor=deepcopy(descriptor),schema=value['schema']))
        if value['schema']=='research.leadership-branch-uncertainty-input/1':branches.append(descriptor['sha256'])
    need(len(branches)==1 and branch_validator(root,cp)==branches[0],
         'COMPOUND_V2_EXACT_B19_VALIDATED_BEFORE_ORIGINAL_COLLISION_SKIP')
    return dict(all_original_input_bytes_verified=True,ordinary_targets_unadopted=True,
        original_branch_validated=True,original_branch_source_sha256=BRANCH_SHA,retained_inputs=rows)


def qualified_collision_parent(origin,inherited):
    """A descriptor view for original collision analysis, never a checkpoint."""
    rows=inherited['retained_inputs']
    branch=[v for v in rows if v['schema']=='research.leadership-branch-uncertainty-input/1']
    ordinary=[deepcopy(v['descriptor']) for v in rows if v['schema']=='terminal-repair/1']
    need(inherited['all_original_input_bytes_verified'] is inherited['original_branch_validated'] is True
         and inherited['ordinary_targets_unadopted'] is True
         and inherited['original_branch_source_sha256']==BRANCH_SHA
         and [v['descriptor'] for v in rows]==origin['repairs']
         and len(branch)==1 and len(ordinary)+1==len(rows),
         'COMPOUND_V2_COLLISION_VIEW_ONLY_AFTER_COMPLETE_EXACT_B19_VALIDATION')
    view=dict(deepcopy(origin),repairs=ordinary)
    proof=dict(schema='research.qualified-ordinary-collision-descriptor-view/1',
        parent_outer_sha256=origin['sha256'],parent_cursor=origin['source_cursor'],
        parent_inner_sha256=origin['run']['checkpoint_sha256'],parent_input_sha256=origin['run']['input_sha256'],
        parent_base_sha256=digest(origin['base']),all_original_descriptors_sha256=digest(origin['repairs']),
        retained_ordinary_descriptors_sha256=digest(ordinary),retained_ordinary_count=len(ordinary),
        omitted_validated_branch_sha256=branch[0]['descriptor']['sha256'],original_branch_source_sha256=BRANCH_SHA,
        collision_analysis_only=True,financial_authority=False,input_adopted=False)
    need({k:v for k,v in view.items() if k!='repairs'}=={k:v for k,v in origin.items() if k!='repairs'},
         'COMPOUND_V2_COLLISION_VIEW_PRESERVES_EVERY_OTHER_PARENT_FIELD')
    return view,proof


def ordinary_document(material):
    plan=material['ordinary_activation'];subset=material['selected_catalog'];private=material['original_private_payload'];group=subset['commitment_group']
    refs={'research.compound-distribution-input/original-ordinary-catalog/2':plan['catalog_sha256'],
        'research.compound-distribution-input/original-ordinary-validator/2':plan['validator_sha256'],
        'research.compound-distribution-input/ordinary-selected-subset/2':sha(encoded(subset)),
        'research.compound-distribution-input/ordinary-private-payload/2':sha(encoded(private)),
        'research.compound-distribution-input/ordinary-material/2':sha(encoded(material)),
        'research.compound-distribution-input/original-ordinary-observer/2':OBSERVER_SHA}
    evidence={k:dict(reference=k,sha256=h,description='Original nonempty mandatory cash activation and full frozen source witness; financial engine unchanged.') for k,h in refs.items()}
    for term in subset['terms']:
        for key in ('primary_source','timing_source'):
            evidence[term[key]]=dict(reference=term[key],sha256=None,description=term['description'])
    return dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=material['original_parent']['run']['checkpoint_sha256'],
        source_evidence=[evidence[k] for k in sorted(evidence)],
        suppress=[dict(session=t['native_session'],security_id=t['security_id'],term_sha256=t['native_term_sha256']) for t in subset['terms']],
        add=[deepcopy(t['added']) for t in subset['terms']])


def ordinary_input(cp,record,root):
    from full_system_core import hosted
    hosted()
    from system_campaign_financial_partial import root_spec
    import system_campaign_cash_calendar as calendar
    import system_campaign_action_preflight as preflight
    import system_campaign_financial_branches as branch
    from research.pooled_input_support import inputs
    need(sha(Path(branch.__file__).read_bytes())==BRANCH_SHA
         and sha(Path(preflight.__file__).read_bytes())==PREFLIGHT_SHA,
         'COMPOUND_V2_ORIGINAL_ORDINARY_AND_BRANCH_PREFLIGHT_SOURCES')
    spec=root_spec(record['arm'],record['parent_root_admission_sha256']);origin=original_parent(spec)
    require_parent(cp,record,origin);codec,full,subset=select_original(record)
    need(Path(calendar.__file__).name==record['ordinary_activation']['validator_file']
         and sha(Path(calendar.__file__).read_bytes())==record['ordinary_activation']['validator_sha256'],
         'COMPOUND_V2_ACTUAL_ORIGINAL_ORDINARY_VALIDATOR_MODULE')
    inherited=inherited_proof(origin,root,subset,branch_validator=branch.validate_input)
    collision_parent,collision_view=qualified_collision_parent(origin,inherited)
    # The unchanged original hydrator verifies native, axis, collisions and fullrow.
    with tempfile.TemporaryDirectory(prefix='compound-ordinary-source-',dir='/tmp') as temp:
        private=codec.hydrate(collision_parent,Path(root),Path(temp))
        collision=json.loads((Path(temp)/'cash-calendar-collision-preflight.json').read_bytes())
    material=dict(schema=SCHEMA,arm=record['arm'],record_sha256=digest(record),
        ordinary_activation=deepcopy(record['ordinary_activation']),selected_catalog=subset,
        full_catalog_sha256=sha(encoded(full)),original_private_payload=private,original_parent=origin,
        inherited_input_proof=inherited,ordinary_collision_view=collision_view,original_collision_preflight=collision,terms=deepcopy(subset['terms']),
        original_observer_sha256=OBSERVER_SHA,financial_sessions_advanced=0,financial_authority=False,
        source_metadata_unchanged=True)
    return material,ordinary_document(material),inputs.load_actions(Path('/frozen/bundle'))


def verify_ordinary(material,cp,record,root):
    expected,document,actions=ordinary_input(cp,record,root)
    need(material==expected,'COMPOUND_V2_COMPLETE_ORIGINAL_ORDINARY_SOURCE_RECONSTRUCTION')
    return document,actions


def original_observer():
    """Load unchanged delegating observer ASTs without old selector module effects."""
    from full_system_core import hosted
    from full_system_benchmark import save
    path=HERE/OBSERVER_FILE;raw=path.read_bytes()
    need(sha(raw)==OBSERVER_SHA,'COMPOUND_V2_IMMUTABLE_ORIGINAL_ORDINARY_ACTUAL_EVENTS_SOURCE')
    names={'ActualEvents','cash_postcondition','actual_terminal_call','cash_before_v',
        'actual_cash_phase','actual_stock_phase','actual_source_phase','unheld_stock_postcondition',
        'actual_source_call','require_source_scope','risk_diagnostic_value'}
    nodes=[n for n in ast.parse(raw).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    need({n.name for n in nodes}==names,'COMPOUND_V2_COMPLETE_EXACT_ORIGINAL_ORDINARY_OBSERVER_AST_SET')
    namespace=dict(__name__='source_bound_original_ordinary_observer',__file__=str(path),
        need=need,save=save,hosted=hosted,deepcopy=deepcopy,asdict=asdict,is_dataclass=is_dataclass,
        inspect=inspect,json=json,Path=Path,sha=sha,digest=digest)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),
        '<unchanged-source-bound-original-ordinary-observer>','exec'),namespace)
    return SimpleNamespace(**namespace)


def bound_observer_type(original,material,cp,*,overlay_name):
    raw=Path(original.__file__).read_bytes()
    need(sha(raw)==OBSERVER_SHA,'COMPOUND_V2_IMMUTABLE_ORIGINAL_ORDINARY_ACTUAL_EVENTS_SOURCE')
    node=next(n for n in ast.parse(raw).body if isinstance(n,ast.ClassDef) and n.name=='ActualEvents')
    constructor=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    def scopes(actual_cp,actual_material,overlay_sha,hydrated_sha):
        need(actual_cp is cp and actual_material==material and material['schema']==SCHEMA
             and material['financial_sessions_advanced']==0 and material['financial_authority'] is False
             and material['terms']==material['selected_catalog']['terms'] and material['terms']
             and all(t['recognition_rule'] in ('CONFIRMED_PREOPEN_COMPLETION','RETAINED_NEXT_SESSION_AFTER_CONFIRMED_LAST_TRADING_DAY')
                     and t['added']['kind']=='CASH_MERGER' and t['mandatory_common_share_completion_confirmed'] is True for t in material['terms'])
             and hydrated_sha==sha(encoded(material)),
             'COMPOUND_V2_ORDINARY_OBSERVER_EXPLICIT_MANDATORY_CASH_ONLY_NOT_SOURCE_ONLY')
        return []
    namespace=dict(vars(original),OVERLAY=overlay_name,hydration_name=lambda actual_cp:MATERIAL,source_scopes=scopes)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[constructor],type_ignores=[])),
        '<unchanged-original-ordinary-observer-constructor>','exec'),namespace)
    class BoundOriginalOrdinaryEvents(original.ActualEvents):pass
    BoundOriginalOrdinaryEvents.__init__=namespace['__init__']
    return BoundOriginalOrdinaryEvents


def ordinary_events(out,cp,overlay_name='future-financial-overlay.json'):
    from full_system_core import hosted
    hosted()
    out=Path(out);material=json.loads((out/MATERIAL).read_bytes())
    from system_campaign_financial_compound_v2_support import qualified_record
    record=qualified_record(material['arm']);expected,_=verify_ordinary(material,cp,record,out)
    actual=json.loads((out/overlay_name).read_bytes())
    need(actual['suppress']==expected['suppress'] and actual['add']==expected['add']
         and all(e in actual['source_evidence'] for e in expected['source_evidence']),
         'COMPOUND_V2_ORDINARY_OBSERVER_EXACT_ORIGINAL_NONEMPTY_ACTIVATION')
    need(sha((HERE/OBSERVER_FILE).read_bytes())==OBSERVER_SHA,
         'COMPOUND_V2_ORIGINAL_ORDINARY_OBSERVER_BYTES_AT_USE')
    original=original_observer()
    cls=bound_observer_type(original,material,cp,overlay_name=overlay_name)
    return cls(out,material['arm'],cp=cp)
