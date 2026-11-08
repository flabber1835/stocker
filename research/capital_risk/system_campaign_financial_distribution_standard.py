"""Generic source-bound continuing-parent inputs for standard ordinary books.

Pure selection and DATA postconditions; actual input hydration is hosted only.
The activated P07 v2 generation and protected financial source remain immutable.
"""
import ast
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict,is_dataclass
from fractions import Fraction
import inspect
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace

from system_campaign_financial_compound_input_v2 import (
    sha,digest,encoded,need,hash_value,build_terms,actual_role,EventSessionProjection,consideration)
from system_campaign_financial_compound_v2_support import (
    primary_binding,activation_descriptor,qualified_loaded_view,
    spin_postcondition as original_spin_postcondition)

HERE=Path(__file__).parent
CATALOG_FILE='system-campaign-standard-distribution-input-facts.json'
CATALOG_SHA='28f6b556fcf63f15f3a5392239315fd12daf83b36c3bf9405bfca25b9790b6f6'
MATERIAL='hydrated-standard-distribution-ordinary-input.json'
SCHEMA='research.generic-standard-original-ordinary-activation/1'
SOURCE_FILE='system_campaign_financial_distribution_source_v2.py'
ORDINARY_V2_FILE='system_campaign_financial_compound_ordinary_v2.py'
ORDINARY_V2_SHA='67f7511fd7ac17d69ba1db1286d334dc9e513b8d210aa5558d516805de2200e8'
OBSERVER_FILE='system_campaign_financial_ordinary_observer_v1.py'
OBSERVER_SHA='a09361056879e891d831daec06686895a6cbb20dca0b1a0a9cded8dae1c650a3'
PREFLIGHT_SHA='0145e6ce84048faf80f49ae20095f29eaf8dc479be4dfd932ec648326d5cf68c'


def delegate_nodes(path,expected,names,namespace):
    """Delegate exact frozen nonfinancial framework ASTs with explicit bindings."""
    raw=Path(path).read_bytes();need(sha(raw)==expected,'STANDARD_FROZEN_FRAMEWORK_SOURCE')
    nodes=[n for n in ast.parse(raw).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    need({n.name for n in nodes}==set(names),'STANDARD_EXACT_FROZEN_FRAMEWORK_AST_SURFACE')
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),
                 '<source-bound-standard-input-framework>','exec'),namespace)


delegate_nodes(HERE/ORDINARY_V2_FILE,ORDINARY_V2_SHA,
    {'select_original','original_parent','require_parent','original_observer','bound_observer_type'},globals())
_select_original=select_original


def qualified_record(arm):
    raw=(HERE/CATALOG_FILE).read_bytes()
    need(hash_value(CATALOG_SHA) and sha(raw)==CATALOG_SHA,'STANDARD_CLOSED_SELECTED_CATALOG')
    catalog=json.loads(raw)
    need(catalog['schema']=='research.selected-standard-distribution-input/1'
         and catalog['canonical_financial_source_changed'] is catalog['production_contacted'] is False,
         'STANDARD_SELECTED_INPUT_ONLY')
    found=[r for r in catalog['records'] if r['arm']==arm];need(len(found)==1,'STANDARD_ONE_EXACT_RECORD')
    r,=found;p=r['source_proof'];profile=r['canonical_profile']
    need(r['status']=='CLOSED_SOURCE_DATA_QUALIFIED_INPUT' and r['input_kind']=='DISTRIBUTION_ONLY'
         and r['inheritance_policy']=='STANDARD_ORDINARY_ONLY_NO_CONDITIONAL_CONTEXT'
         and type(r['inherited_ordinary_count']) is int and r['inherited_ordinary_count']>0
         and p['independent_DATA_passed'] is p['independent_qualification_passed'] is True
         and type(p['run_id']) is int and p['run_id']>0 and type(p['artifact_id']) is int and p['artifact_id']>0
         and type(p['head']) is str and len(p['head'])==40 and set(p['head'])<=set('0123456789abcdef')
         and all(hash_value(p[k]) for k in ('zip_sha256','payload_sha256','payload_digest','producer_sha256',
             'distribution_producer_sha256','scope_sha256','independent_data_review_sha256','independent_qualification_sha256'))
         and p['scope_sha256']==digest(r['source_scope'])
         and r['source_scope']['parent_outer_sha256']==r['parent_outer_sha256']
         and r['source_scope']['parent_cursor']==r['parent_cursor']<r['research_assumption']['recognition_session']
         and r['source_module_file']==SOURCE_FILE
         and sha((HERE/SOURCE_FILE).read_bytes())==p['distribution_producer_sha256']
         and all(hash_value(r[k]) for k in ('parent_outer_sha256','parent_inner_sha256','parent_input_sha256',
                                           'parent_root_admission_sha256','source_bindings_sha256')),
         'STANDARD_CLOSED_SOURCE_AND_OWN_PARENT_PINS')
    need(profile['schema']=='research.bound-canonical-reference-rebase/1'
         and profile['floor_rule']=='ORIGINAL_NONEMPTY_RESEARCH_STOP_FLOOR_TIMES_ORIGINAL_REFERENCE_SCALE'
         and profile['derivation']['text_transforms_only'] is True
         and all(hash_value(profile[k]) for k in ('spinoffs_sha256','capital_risk_sha256','rebase_floor_AST_sha256'))
         and profile['spinoffs_sha256']==profile['derivation']['spinoffs_after_sha256']
         and profile['capital_risk_sha256']==profile['derivation']['capital_risk_after_sha256']
         and profile['rebase_floor_AST_sha256']==profile['derivation']['rebase_floor_AST_sha256']
         and profile['independent_derivation_sha256']==sha(encoded(profile['derivation']))
         and profile['derivation']['source_DATA_review_sha256']==p['independent_data_review_sha256']
         and sha((HERE/'build_core_variants.py').read_bytes())==profile['derivation']['original_build_compiler_sha256']
         and sha((HERE/'system_campaign_variants.py').read_bytes())==profile['derivation']['variant_compiler_sha256']
         and profile['derivation']['canonical_financial_code_executed'] is profile['derivation']['canonical_financial_code_saved'] is False,
         'STANDARD_EXACT_ORIGINAL_VARIANT_REFERENCE_REBASE_PROFILE')
    primary_binding(r);return r


@contextmanager
def registry_context(record):
    """Add one qualified group around originals, preserving the protected seven."""
    import system_campaign_ordinary_registry as registry
    need(record==qualified_record(record['arm']),'STANDARD_REGISTRY_ONLY_EXACT_CLOSED_SELECTED_RECORD')
    plan=record['ordinary_activation'];extension=plan['registry_extension']
    base_raw=(HERE/registry.REGISTRY).read_bytes();base=json.loads(base_raw);catalog_raw=(HERE/plan['catalog_file']).read_bytes()
    group=json.loads(catalog_raw)['commitment_group']
    need(sha(base_raw)==extension['original_registry_sha256']
         and sha(Path(registry.__file__).read_bytes())==extension['original_registry_module_sha256']
         and len(base['groups'])==extension['original_group_count']==7
         and sha(catalog_raw)==plan['catalog_sha256'] and extension['group']==group
         and group['catalog_file']==plan['catalog_file'] and group['loader_file']==plan['validator_file']
         and sha((HERE/plan['validator_file']).read_bytes())==plan['validator_sha256'],
         'STANDARD_EXACT_PROTECTED_REGISTRY_AND_SOURCE_BOUND_ADDITIVE_GROUP')
    proof=dict(schema='research.qualified-additive-ordinary-registry-view/1',
        original_registry_sha256=sha(base_raw),original_registry_module_sha256=extension['original_registry_module_sha256'],
        original_groups_sha256=digest(base['groups']),original_group_count=7,extension=deepcopy(group),
        selected_catalog_sha256=plan['catalog_sha256'],selected_validator_sha256=plan['validator_sha256'],
        record_sha256=digest(record),financial_authority=False,input_adopted=False)
    original=registry.registrations
    if getattr(original,'_standard_registry_proof',None)is not None:
        need(original._standard_registry_proof==proof,'STANDARD_NO_FOREIGN_NESTED_REGISTRY_GENERATION')
        yield deepcopy(proof);return
    def qualified(driver=HERE):
        inherited=original(driver)
        need((Path(driver)/registry.REGISTRY).read_bytes()==base_raw and inherited==base['groups'],
             'STANDARD_ALL_SEVEN_ORIGINAL_REGISTRY_ENTRIES_EXACT_UNCHANGED')
        identities=('reference_stem','catalog_file','private_file','overlay_file')
        need(group not in inherited and not any(any(old[k]==group[k]for k in identities)for old in inherited),
             'STANDARD_NO_DUPLICATE_SHADOW_OR_UNKNOWN_REGISTRY_GROUP')
        return deepcopy(inherited)+[deepcopy(group)]
    qualified._standard_registry_proof=proof
    registry.registrations=qualified
    try:yield deepcopy(proof)
    finally:registry.registrations=original


def select_original(record):
    with registry_context(record):return _select_original(record)


def inherited_proof(cp,root,subset,*,expected_count):
    """Every descriptor stays in original collision analysis; unknown schemas refuse."""
    root=Path(root);targets={t['security_id'] for t in subset['terms']};rows=[]
    def selected(value):
        if isinstance(value,dict):
            return any(k in ('security_id','parent_security_id','child_security_id','delivered_security_id')
                       and isinstance(v,str) and v in targets for k,v in value.items()) or any(selected(v) for v in value.values())
        return isinstance(value,(tuple,list)) and any(selected(v) for v in value)
    need(len(cp['repairs'])==expected_count,'STANDARD_ALL_ORIGINAL_ORDINARY_DESCRIPTOR_COUNT')
    for d in cp['repairs']:
        raw=(root/'book/repairs'/d['filename']).read_bytes();value=json.loads(raw)
        need(d['filename']==d['sha256']+'.json' and sha(raw)==d['sha256']
             and value['schema']=='terminal-repair/1','STANDARD_ALL_ORDINARY_BYTES_NO_BRANCH_OR_UNKNOWN_SCHEMA')
        need(not selected(value),'STANDARD_GENUINE_ORDINARY_TARGET_NOT_ALREADY_ADOPTED')
        rows.append(dict(descriptor=deepcopy(d),schema=value['schema']))
    return dict(all_original_input_bytes_verified=True,ordinary_targets_unadopted=True,
                standard_ordinary_only=True,retained_inputs=rows)


def ordinary_document(material):
    plan=material['ordinary_activation'];subset=material['selected_catalog'];private=material['original_private_payload']
    refs={'catalog':plan['catalog_sha256'],'validator':plan['validator_sha256'],
          'selected-subset':sha(encoded(subset)),'private-payload':sha(encoded(private)),
          'material':sha(encoded(material)),'original-observer':OBSERVER_SHA,
          'original-registry':plan['registry_extension']['original_registry_sha256'],
          'original-registry-module':plan['registry_extension']['original_registry_module_sha256'],
          'registry-extension':digest(plan['registry_extension']['group'])}
    evidence={key:dict(reference='research.standard-distribution-input/ordinary/'+key+'/1',sha256=value,
        description='Genuine original mandatory cash input; unchanged financial engine.') for key,value in refs.items()}
    for t in subset['terms']:
        for key in ('primary_source','timing_source'):
            evidence[t[key]]=dict(reference=t[key],sha256=None,description=t['description'])
    return dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=material['original_parent']['run']['checkpoint_sha256'],
        source_evidence=sorted(evidence.values(),key=lambda v:v['reference']),
        suppress=[dict(session=t['native_session'],security_id=t['security_id'],term_sha256=t['native_term_sha256']) for t in subset['terms']],
        add=[deepcopy(t['added']) for t in subset['terms']])


def _ordinary_input(cp,record,root):
    from full_system_core import hosted
    hosted()
    from system_campaign_financial_partial import root_spec
    import system_campaign_cash_calendar as calendar
    import system_campaign_action_preflight as preflight
    from research.pooled_input_support import inputs
    need(sha(Path(preflight.__file__).read_bytes())==PREFLIGHT_SHA,'STANDARD_ORIGINAL_COLLISION_PREFLIGHT_SOURCE')
    spec=root_spec(record['arm'],record['parent_root_admission_sha256']);origin=original_parent(spec)
    require_parent(cp,record,origin);codec,full,subset=select_original(record)
    need(sha(Path(calendar.__file__).read_bytes())==record['ordinary_activation']['validator_sha256'],
         'STANDARD_ORIGINAL_CASH_CALENDAR_VALIDATOR')
    proof=inherited_proof(origin,root,subset,expected_count=record['inherited_ordinary_count'])
    # Full original parent, no B19 filtering or checkpoint view.
    with tempfile.TemporaryDirectory(prefix='standard-distribution-source-',dir='/tmp') as temp:
        private=codec.hydrate(origin,Path(root),Path(temp))
        collision=json.loads((Path(temp)/'cash-calendar-collision-preflight.json').read_bytes())
    material=dict(schema=SCHEMA,arm=record['arm'],record_sha256=digest(record),ordinary_activation=deepcopy(record['ordinary_activation']),
        selected_catalog=subset,full_catalog_sha256=sha(encoded(full)),original_private_payload=private,original_parent=origin,
        inherited_input_proof=proof,original_collision_preflight=collision,terms=deepcopy(subset['terms']),
        original_observer_sha256=OBSERVER_SHA,financial_sessions_advanced=0,financial_authority=False,source_metadata_unchanged=True)
    return material,ordinary_document(material),inputs.load_actions(Path('/frozen/bundle'))


def ordinary_input(cp,record,root):
    with registry_context(record)as proof:
        material,_,actions=_ordinary_input(cp,record,root)
        material['qualified_registry_view']=proof
        return material,ordinary_document(material),actions


def verify_ordinary(material,cp,record,root):
    expected,document,actions=ordinary_input(cp,record,root)
    need(material==expected,'STANDARD_COMPLETE_ORIGINAL_ORDINARY_RECONSTRUCTION');return document,actions


def ordinary_events(out,cp,overlay_name='future-financial-overlay.json'):
    from full_system_core import hosted
    hosted();out=Path(out);material=json.loads((out/MATERIAL).read_bytes());record=qualified_record(material['arm'])
    expected,_=verify_ordinary(material,cp,record,out);actual=json.loads((out/overlay_name).read_bytes())
    need(actual['suppress']==expected['suppress'] and actual['add']==expected['add']
         and all(e in actual['source_evidence'] for e in expected['source_evidence']), 'STANDARD_ORIGINAL_NONEMPTY_ACTIVATION_OBSERVER')
    original=original_observer();cls=bound_observer_type(original,material,cp,overlay_name=overlay_name)
    return cls(out,material['arm'],cp=cp)


def verify_primitive_sources(profile,sources,*,spinoffs_raw,capital_risk_raw):
    need(sha(spinoffs_raw)==profile['spinoffs_sha256']==sources['sentinel/core/spinoffs.py']
         and sha(capital_risk_raw)==profile['capital_risk_sha256']==sources['shared/stock_strategy_shared/wealth_core/capital_risk.py'],
         'STANDARD_ACTUAL_ORIGINAL_VARIANT_PRIMITIVE_SOURCES')
    fn,=[n for n in ast.parse(capital_risk_raw).body if isinstance(n,ast.FunctionDef)and n.name=='rebase_floor']
    need(sha(ast.dump(fn,include_attributes=False).encode())==profile['rebase_floor_AST_sha256'],
         'STANDARD_EXACT_ORIGINAL_REBASE_FLOOR_AST')
    return True


def spin_postcondition(binding,before,after,ledger_before,ledger_after,result,cost_bps):
    """Prove original floor rebase, then reuse all original receipt/lot predicates."""
    profile=binding['canonical_profile'];s=binding['spin'];parent=s['parent_security_id']
    need(profile['floor_rule']=='ORIGINAL_NONEMPTY_RESEARCH_STOP_FLOOR_TIMES_ORIGINAL_REFERENCE_SCALE',
         'STANDARD_SOURCE_BOUND_FLOOR_RULE')
    parent_open=float(binding['original_rows'][parent]['raw_open']);child_open=float(s['cash_in_lieu_price'])
    scale=parent_open/(parent_open+float(Fraction(s['child_shares_per_parent'])*Fraction(str(child_open))))
    clean=deepcopy(after);proof=[]
    for key,old in before['episodes'].items():
        if old['security_id']!=parent:continue
        current=after['episodes'][key];floor=old.get('research_stop_floor');expected=None if floor is None else floor*scale
        need(current['source_lots'][-1]['reference_scale']==scale
             and ('research_stop_floor' in old)==('research_stop_floor' in current)
             and (expected is None or math.isfinite(expected) and expected>0)
             and current.get('research_stop_floor')==expected
             and current.get('research_stop_cursor')==old.get('research_stop_cursor'),
             'STANDARD_EXACT_ORIGINAL_FLOOR_TIMES_OBSERVED_REFERENCE_SCALE')
        if 'research_stop_floor' in old:clean['episodes'][key]['research_stop_floor']=floor
        else:clean['episodes'][key].pop('research_stop_floor',None)
        proof.append(dict(slot_id=old['slot_id'],before=floor,reference_scale=scale,after=expected,
                          cursor_unchanged=old.get('research_stop_cursor')))
    need(proof,'STANDARD_NONEMPTY_PARENT_REFERENCE_REBASE_PROOF')
    result_=original_spin_postcondition(binding,before,clean,ledger_before,ledger_after,result,cost_bps)
    return dict(result_,canonical_reference_rebase=proof)


def review_spin_result(binding,value,cost_bps=10):
    quantity=sum((Fraction(str(v['quantity'])) for v in binding['parent_positions']),Fraction(0))
    need({k:v for k,v in value.items()if k!='canonical_reference_rebase'}==consideration(binding,quantity,cost_bps),
         'STANDARD_EXACT_CHILD_CONSIDERATION')
    proof=value['canonical_reference_rebase'];slots={v['slot_id'] for v in binding['parent_positions']}
    need(len(proof)==len(slots) and {v['slot_id'] for v in proof}==slots,'STANDARD_EXACT_ALL_PARENT_FLOOR_PROOFS')
    parent=binding['spin']['parent_security_id'];s=binding['spin']
    scale=float(binding['original_rows'][parent]['raw_open'])/(float(binding['original_rows'][parent]['raw_open'])+
        float(Fraction(s['child_shares_per_parent'])*Fraction(s['cash_in_lieu_price'])))
    for row in proof:
        expected=None if row['before'] is None else row['before']*scale
        need(set(row)=={'slot_id','before','reference_scale','after','cursor_unchanged'}
             and (row['cursor_unchanged'] is None or type(row['cursor_unchanged'])is str and row['cursor_unchanged']<=s['session'])
             and row['reference_scale']==scale and row['after']==expected
             and (expected is None or math.isfinite(expected)and expected>0), 'STANDARD_RETAINED_EXACT_FLOOR_REBASE')
    return True
