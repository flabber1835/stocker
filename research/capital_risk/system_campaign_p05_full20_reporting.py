"""Exact saved1196/full20 report-only visitor before legacy cash inventory."""
import ast,json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import system_campaign_p05_remaining_origin_data as origin

HERE=Path(__file__).parent
FACT='P05-FIN340-full20-readonly-reporting-fact.json'
FACT_SHA='7c41266e13bbeecb3c5f192e946ce75a12d36ce9c652d7eb4d727b3cfb5af8c7'
REQUEST='P05-FIN340-full20-reporting-source-request.json'
REQUEST_SHA='67ca5a6e9cff7df93afa1e7445b6f8412551b8e64e2da4445058d22b2df3dbb2'
OUTER='1b8c9db2c883cd1e5a0ad8e19b4642548c29877e5a93cef7ef0c61fbb3aee443'
MODE='READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION'
MARKER='p05_full20_readonly_reporting_bridge'
FIELD='selected_p05_full20_readonly_reporting_bridges'
need,sha,encoded=origin.need,origin.sha,origin.encoded
def source_names():
    from system_campaign_p05_remaining_source_preparation_v2 import source_names as prior
    return tuple(sorted(set((Path(__file__).name,FACT,REQUEST,*prior(),'system_campaign_p05_remaining_origin_data.py'))))
def fact():
    raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'P05_REPORT20_EXACT_SAVED1196_REPORTING_FACT')
    value=json.loads(raw);request_raw=(HERE/REQUEST).read_bytes()
    need(sha(request_raw)==REQUEST_SHA==value['captured_request_sha256'],'P05_REPORT20_EXACT_CAPTURED_FIN340_SOURCE_REQUEST')
    request=json.loads(request_raw)
    need(request['schema']=='research.system-campaign-accurate-resume-request/206'
        and request['execution_mode']=='OWN_ADMITTED_FINANCIAL_CONTINUATION' and request['financial_resume_authorized'] is True
        and request['selected_p05_retained18_financial_inputs']['P05']==value['captured_financial_declaration']
        and value['captured_financial_declaration']['current_root_admission_sha256']==origin.data.own.ROOT
        and value['captured_financial_declaration']['current_full_inputs']==19
        and value['genuine20_origin_positive'] is value['whole112_observer_review_positive'] is True
        and value['scope']==dict(readonly_reporting_only=True,financial_resume_authorized=False,financial_workers=0,
            root_admitted=False,financial_transitions_reexecuted=0,actual_state_serialized=False,new_factual_overlay=False,
            diagnostic_Oct3_5_tail_seeded=False),
        'P05_REPORT20_CAPTURED_FINANCIAL_PROVENANCE_GRANTS_ONLY_READONLY_REPORTING')
    return value
def selected(spec):
    return isinstance(spec,dict) and spec.get('arm')=='P05' and spec.get('outer_sha256')==OUTER \
        and spec.get('monthly_seed_root_admission_sha256')==origin.data.own.ROOT
def validate_target(spec):
    need(selected(spec),'P05_REPORT20_ONLY_EXACT_SAVED1196_TARGET')
    value=fact();expected=value['target'];keys=(set(expected)-{'base_sha256'})|{'base'}
    need(set(spec) in (keys,keys|{MARKER}) and 'root_admission' not in spec and 'root_admission_sha256' not in spec
        and spec['financial_authority'] is spec['financial_predecessor_admitted'] is False
        and spec['archive_format']=='FINANCIAL_RESUME_FIVE_MEMBER_ZIP/1'
        and spec.get('retained_uncertainty_model') is None and len(spec['repairs'])==20
        and origin.digest(spec['base'])==expected['base_sha256'],
        'P05_REPORT20_REAL_UNADMITTED_FULL20_TRANSPORT_WITHOUT_MODEL_TAG_OR_FINANCIAL_PERMISSION')
    for key,wanted in expected.items():
        if key!='base_sha256':need(encoded(spec[key])==encoded(wanted),'P05_REPORT20_EXACT_ACTUAL_TARGET_FIELD:'+key)
    return value
def declaration(spec):
    value=validate_target(spec)
    return dict(schema='research.P05-full20-readonly-monthly-reporting-declaration/1',arm='P05',target_outer_sha256=OUTER,
        target_completed=1196,target_cursor='2022-09-30',full_inputs=20,monthly_seed_root_admission_sha256=origin.data.own.ROOT,
        fact_file=FACT,fact_sha256=FACT_SHA,captured_request_sha256=REQUEST_SHA,
        actual_origin_manifest_sha256=value['actual_origin_manifest_sha256'],actual112_observer_review_sha256=value['actual_observer_review_sha256'],
        original_monthly_implementation_unchanged=True,full20_origin_visitor_before_cash_inventory=True,
        compatibility_model_tag_added=False,financial_runtime_route_selected=False,readonly_reporting_only=True,
        financial_resume_authorized=False,financial_transitions_reexecuted=0)
def qualify_target(spec):
    expected=declaration(spec)
    need(MARKER not in spec or spec[MARKER]==expected,'P05_REPORT20_NO_FOREIGN_EXISTING_REPORTING_MARKER')
    return dict(deepcopy(spec),**{MARKER:expected})
def request_declaration(spec,request):
    need(encoded(spec)==encoded(qualify_target(spec)),'P05_REPORT20_EXPLICIT_QUALIFIED_FULL20_TARGET_REQUIRED')
    expected=declaration(spec)
    need(request['execution_mode']==MODE and request['financial_resume_authorized'] is False
        and request['readonly_partial_review'] is True and request['readonly_source_witnesses'] is False
        and type(request['maximum_parallel_financial_workers']) is int and request['maximum_parallel_financial_workers']==0
        and request.get(FIELD,{}).get('P05')==expected,'P05_REPORT20_EXPLICIT_REPORT_ONLY_ZERO_FINANCIAL_WORKER_REQUEST')
    return expected
def expected_request(original,*,execution_mode,selected_arms,target_lookup):
    result=original();declared={}
    if execution_mode==MODE:
        for arm in selected_arms:
            target=target_lookup(arm)
            if selected(target):
                need(encoded(target)==encoded(qualify_target(target)),'P05_REPORT20_TARGET_QUALIFIED_BEFORE_REQUEST')
                declared[arm]=declaration(target);result['arm_inputs'][arm]['new_factual_overlay']=False
    result[FIELD]=declared
    for name in source_names():
        pin=sha((HERE/name).read_bytes());need(name not in result['sources'] or result['sources'][name]==pin,'P05_REPORT20_NO_REQUEST_SOURCE_PIN_REPLACEMENT')
        result['sources'][name]=pin
    return result
def full20(root,current,spec):
    value=validate_target(spec);root=Path(root)
    need((current['sha256'],current['completed'],current['source_cursor'],len(current['repairs']))==(OUTER,1196,'2022-09-30',20)
        and current['base']==spec['base'] and current['repairs']==spec['repairs']
        and current['run']['input_sha256']==spec['input_sha256'] and current['run']['state_sha256']==spec['state_sha256'],
        'P05_REPORT20_ONLY_ACTUAL_CURRENT1196_FULL20_NO_PROJECTION_OR_TAIL_SEED')
    manifest_raw=(root/origin.MANIFEST).read_bytes()
    need(sha(manifest_raw)==value['actual_origin_manifest_sha256'],'P05_REPORT20_EXACT_GENUINE20_ORIGIN_MANIFEST')
    result=origin.origin(json.loads(manifest_raw),current,lambda n:(root/n).read_bytes())
    observer=(root/'stopped-review/P05-retained18-observation-review.json').read_bytes()
    need(sha(observer)==value['actual_observer_review_sha256'] and json.loads(observer)['passed'] is True
        and json.loads(observer)['observation_terms']==112,'P05_REPORT20_ACTUAL_POSITIVE_WHOLE112_OBSERVER_REVIEW')
    need(len(result['material']['terms'])==18 and len(result['cash_terms'])==14 and len(result['scopes'])==1,
        'P05_REPORT20_COMPLETE18_COMPOSITE_BEFORE14_CASH_EXTRACTION')
    return result
def source_contract(partial,module):
    value=fact()
    actual={n.name:sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse(Path(partial.__file__).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name in value['original_partial_AST']}
    need(actual==value['original_partial_AST'],'P05_REPORT20_WHOLE_ORIGINAL_INPUT_AND_MONTHLY_SOURCE_AST')
    methods={n.name:sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse(Path(module.__file__).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name in value['original4_financial_AST']}
    need(methods==value['original4_financial_AST'],'P05_REPORT20_ALL_FOUR_ORIGINAL_FINANCIAL_FUNCTIONS_UNCHANGED')
@contextmanager
def entry_context(module,spec,*,mode,old,out,request):
    from full_system_core import hosted
    hosted()
    if not selected(spec):yield;return
    request_declaration(spec,request)
    need(mode=='preflight','P05_REPORT20_ONLY_HOSTED_READONLY_PREFLIGHT_ENTRY')
    import system_campaign_financial_partial as partial
    source_contract(partial,module)
    old=Path(old);prior_partial,prior_module=partial.financial_inputs,module.financial_inputs
    old_inventory=origin.old_materials.inventory
    need(prior_partial is prior_module,'P05_REPORT20_ONLY_UNWRAPPED_ORIGINAL_INPUT_CONTEXT_ALIAS')
    @contextmanager
    def financial_inputs(root,current,target_out,target_spec):
        if not selected(target_spec):
            with prior_partial(root,current,target_out,target_spec):yield
            return
        need(Path(root)==old and encoded(target_spec)==encoded(spec),'P05_REPORT20_EXACT_READONLY_CURRENT_SOURCE_ROOT_AND_TARGET')
        full20(root,current,target_spec)
        with prior_partial(root,current,target_out,target_spec):yield
    partial.financial_inputs=module.financial_inputs=financial_inputs
    origin.old_materials.inventory=origin.inventory_function()
    try:yield
    finally:
        partial.financial_inputs,module.financial_inputs=prior_partial,prior_module
        origin.old_materials.inventory=old_inventory
