"""Exact actual1259 admission and proof-only continuation metadata; no registry."""
import ast,json
from copy import deepcopy
from pathlib import Path
from system_campaign_bounded_sensor_input import need,sha,digest
import system_campaign_p06_abmd_lifecycle_data as initial
import system_campaign_p06_abmd_reporting as reporting

HERE=Path(__file__).parent
MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION'
FIELD='selected_p06_admitted_point_continuations'
FACTORY='system_campaign_p06_abmd_point_continuation.py'
FACTORY_SHA='02135148c5f5f60b503332b4fbbe60ffaa4c6c06c9a9340db7c7e35f59b32f9a'
LEGACY_SHA='3ec636f898e9c3918047da18150660be37fd08f680818ec93064dfa355a1f6a8'
PROVENANCE='p06-point-retained-origin'
OBSERVATIONS='p06-retained-ordinary-observation'
UNCHANGED='retained-proof-admission/unchanged-input.json'
FULL_PROOF='old-full-uncertainty-certificate.jsonl'
SIX_SHA='46db300cbb9267683b62148711f14db1bb2b9452680cba18fbee29e2af3927f7'
FULL_SHA='fa575114e290733777eeaba5f1e2724e6a233d40844cbd71d8b33ae5c0ae74b0'

def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def source_names():
    return tuple(sorted(set(initial.source_names())|set(reporting.source_names())|{Path(__file__).name,
        'system_campaign_p06_abmd_retained.py','system_campaign_p06_abmd_retained_suffix.py',FACTORY,
        'system_campaign_point_growth.py','system_campaign_financial_additional_sensor.py'}))

def candidate(spec):
    return (isinstance(spec,dict) and spec.get('arm')=='P06' and spec.get('outer_sha256')==reporting.OUTER
        and spec.get('artifact_id')==13478656632 and spec.get('measured_closes')==1259
        and spec.get('selected_session')=='2022-12-30' and len(spec.get('repairs',[]))==10)

def admitted(spec):
    from system_campaign_financial_partial import validate_root_spec
    need(candidate(spec) and 'root_admission' in spec and spec.get('root_admission_sha256') not in (None,initial.ROOT),
         'P06_RETAINED_ACTUAL_NEW1259_ROOT_ADMISSION_REQUIRED')
    validate_root_spec(spec)
    need(spec.get('retained_uncertainty_model')==reporting.TAG,
         'P06_RETAINED_EXPLICIT_FULL10_COMPATIBILITY_TAG_WITHOUT_B19_CODEC')
    fact=reporting.fact();target=fact['target']
    for key,expected in target.items():
        if key=='base_sha256':
            need(digest(spec['base'])==expected,'P06_RETAINED_SAME_ACTUAL_FINANCIAL_SOURCE_BASE')
        else:need(encoded(spec[key])==encoded(expected),'P06_RETAINED_EXACT_ADMITTED_TARGET_FIELD:'+key)
    proof=spec['root_admission']['branch_uncertainty_proof']
    need(proof['passed'] is proof['all_comparisons_and_state_sets_verified'] is proof['all_math_watch_financial_chains_verified'] is True
         and type(proof['rows']) is type(proof.get('retained_rows',0)) is int
         and proof['rows']==6 and proof.get('retained_rows',0)==0,
         'P06_RETAINED_ONLY_ACTUAL_ADMITTED_SIX_ROW_PROOF_SCOPE')
    need(sha((HERE/FACTORY).read_bytes())==FACTORY_SHA,'P06_RETAINED_EXACT_SEPARATE_POINT_FACTORY_SOURCE')
    return fact

def declaration(spec):
    fact=admitted(spec)
    return dict(schema='research.p06-admitted-six-proof-point-continuation/1',arm='P06',
        financial_seed_root_admission_sha256=spec['root_admission_sha256'],financial_seed_outer_sha256=spec['outer_sha256'],
        completed=1259,source_cursor='2022-12-30',full_inputs=10,committed_seed_rows=6,committed_seed_sha256=SIX_SHA,
        original_initial_root_admission_sha256=initial.ROOT,catalog_sha256=fact['catalog_sha256'],
        point_factory_file=FACTORY,point_factory_sha256=FACTORY_SHA,point_growth_sha256='1da8862ccc64dd990c25359d5f1ca03f3e964fa0423df17d9d4865218213a7a0',
        witness_sha256='177d5906b9ecd6b33512999ef8408704d5814ba5f69a4d8284fb22b62b7f5cf1',
        financial_source_changed=False,new_input_adoption=False,old_B19_codec_or_fake_seed=False,
        future_proof_point_operation_order_qualified=True,Jan20_failure_cause_proven=False)

def selected(spec,request=None):
    if not candidate(spec) or 'root_admission' not in spec or request is None:return False
    expected=declaration(spec)
    return (request.get('execution_mode')==MODE and request.get('financial_resume_authorized') is True
        and request.get('readonly_partial_review') is False and request.get('readonly_source_witnesses') is False
        and request.get(FIELD,{}).get('P06')==expected)

def receipt(parent,spec):
    declaration(spec)
    need(parent['sha256']==spec['outer_sha256'] and parent['repairs']==spec['repairs']
         and parent['run']['input_sha256']==spec['input_sha256'],'P06_RETAINED_UNCHANGED_RECEIPT_ACTUAL_FINANCIAL_PARENT')
    return dict(schema='research.p06-unchanged-full10-admitted-point-continuation/1',
        parent_outer_sha256=parent['sha256'],root_admission_sha256=spec['root_admission_sha256'],
        completed=parent['completed'],source_cursor=parent['source_cursor'],input_sha256=parent['run']['input_sha256'],
        repairs=deepcopy(parent['repairs']),committed_seed_rows=6,committed_seed_sha256=SIX_SHA,
        new_factual_overlay=False,financial_source_changed=False,financial_input_adopted=False)

def unchanged_review_tree(raw):
    need(sha(raw)==LEGACY_SHA,'P06_RETAINED_WHOLE_ORIGINAL_UNCHANGED_REVIEW_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='review_unchanged_input']
    return fn

def review_unchanged(parent,current,root,spec):
    import system_campaign_financial_uncertainty as legacy
    scope=dict(vars(legacy),unchanged_input_receipt=receipt)
    exec(compile(ast.Module(body=[unchanged_review_tree(Path(legacy.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-unchanged-input-review-explicit-P06-receipt>','exec'),scope)
    return scope['review_unchanged_input'](parent,current,Path(root),spec)
