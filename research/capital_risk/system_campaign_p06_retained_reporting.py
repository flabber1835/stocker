"""Exact FIN330 P06 full10 readonly reporting bridge; no financial authority."""
import ast,json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from system_campaign_bounded_sensor_input import need,sha,digest,InputCodec,SCHEMA
from system_campaign_abmd_bounded_catalog import load,evidence
from system_campaign_abmd_bounded_hydration import hydrate

HERE=Path(__file__).parent
FACT='P06-FIN330-retained-reporting-fact-v1.json'
FACT_SHA='ffb6f2a56a4ba3f810ca42861264539a29a6be91b42ffb432be8f9ca5f49e1f9'
REQUEST='P06-FIN330-retained-reporting-source-request.json'
REQUEST_SHA='07117246937878afff108930bf077d3181d2fafcbfcad690ca2af34f32a41940'
ROOT='41520825b51f125272ed44bb01ca58905fe7b170005fc1a1c4a72856bf01263f'
OUTER='bd3e5c6b01942efedf344756dd2a52a7a616fbf81b4d76c73f1397b9498a3e08'
MODE='READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION'
TAG='research.leadership-branch-uncertainty-input/1'
MARKER='p06_retained_readonly_reporting_bridge'
FIELD='selected_p06_retained_reporting_bridges'

def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def source_names():
    from system_campaign_p06_abmd_lifecycle_data import source_names as original
    return tuple(sorted(set(original())|{Path(__file__).name,FACT,REQUEST}))

def fact():
    raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'P06_REPORT_EXACT_ACTUAL1383_BRIDGE_METADATA_FACT')
    value=json.loads(raw);raw=(HERE/REQUEST).read_bytes()
    need(sha(raw)==REQUEST_SHA==value['captured_request_sha256'],'P06_REPORT_EXACT_CAPTURED_FIN330_REQUEST196')
    request=json.loads(raw)
    need(request['schema']=='research.system-campaign-accurate-resume-request/196'
         and request['execution_mode']=='OWN_ADMITTED_FINANCIAL_CONTINUATION'
         and request['financial_resume_authorized'] is True
         and request['selected_p06_admitted_point_continuations']['P06']==value['captured_P06_declaration']
         and value['captured_P06_declaration']['financial_seed_root_admission_sha256']==ROOT
         and value['captured_P06_declaration']['committed_seed_rows']==6
         and value['scope']['readonly_reporting_only'] is True
         and value['scope']['financial_resume_authorized'] is value['scope']['root_admitted']
             is value['scope']['prior_B19_seed_created'] is value['scope']['actual_state_serialized'] is False,
         'P06_REPORT_ACTUAL_RETAINED_SEED_DECLARATION_NO_NEW_SEED_OR_STATE')
    return value

def selected(spec):
    return (isinstance(spec,dict) and spec.get('arm')=='P06' and spec.get('outer_sha256')==OUTER
        and spec.get('monthly_seed_root_admission_sha256')==ROOT)

def validate_target(spec):
    need(selected(spec),'P06_REPORT_ONLY_EXACT_SAVED1383_MONTHLY_TARGET')
    value=fact();target=value['target']
    need('root_admission' not in spec and 'root_admission_sha256' not in spec
         and spec['financial_authority'] is False and spec['financial_predecessor_admitted'] is False
         and spec['archive_format']=='FINANCIAL_RESUME_FIVE_MEMBER_ZIP/1'
         and len(spec['repairs'])==10 and digest(spec['base'])==target['base_sha256'],
         'P06_REPORT_READONLY_UNADMITTED_FULL10_TRANSPORT_SCOPE')
    for key,expected in target.items():
        if key=='base_sha256':continue
        need(encoded(spec[key])==encoded(expected),'P06_REPORT_EXACT_CAPTURED_TARGET_FIELD:'+key)
    need(spec.get('retained_uncertainty_model') in (None,TAG),
         'P06_REPORT_ONLY_EXPLICIT_COMPATIBILITY_ROUTING_TAG')
    return value

def declaration(spec):
    value=validate_target(spec)
    return dict(schema='research.p06-retained-full10-readonly-reporting-bridge/1',arm='P06',
        target_outer_sha256=OUTER,target_completed=1383,target_cursor='2023-06-30',
        monthly_seed_root_admission_sha256=ROOT,fact_file=FACT,fact_sha256=FACT_SHA,
        captured_financial_request_sha256=REQUEST_SHA,catalog_file=value['catalog_file'],catalog_sha256=value['catalog_sha256'],
        actual_input_schema=SCHEMA,compatibility_routing_tag=TAG,old_B19_codec_installed=False,prior_seed_rows=6,
        readonly_reporting_only=True,financial_resume_authorized=False,financial_transitions_reexecuted=0)

def qualify_target(spec):
    expected=declaration(spec)
    need(MARKER not in spec or spec[MARKER]==expected,'P06_REPORT_NO_FOREIGN_EXISTING_BRIDGE_MARKER')
    return dict(deepcopy(spec),retained_uncertainty_model=TAG,**{MARKER:expected})

def request_declaration(spec,request):
    need(encoded(spec)==encoded(qualify_target(spec)),'P06_REPORT_TARGET_EXPLICITLY_QUALIFIED_BEFORE_USE')
    expected=declaration(spec)
    need(request['execution_mode']==MODE and request['financial_resume_authorized'] is False
         and request['readonly_partial_review'] is True and request['readonly_source_witnesses'] is False
         and type(request['maximum_parallel_financial_workers']) is int and request['maximum_parallel_financial_workers']==0
         and request.get(FIELD,{}).get('P06')==expected,'P06_REPORT_EXPLICIT_READONLY_REQUEST_DECLARATION')
    return expected

def expected_request(original,*,execution_mode,selected_arms,target_lookup):
    result=original();declared={}
    if execution_mode==MODE:
        for arm in selected_arms:
            target=target_lookup(arm)
            if selected(target):
                need(encoded(target)==encoded(qualify_target(target)),'P06_REPORT_TARGET_QUALIFIED_BEFORE_REQUEST')
                declared[arm]=declaration(target)
    result[FIELD]=declared
    for name in source_names():
        pin=sha((HERE/name).read_bytes())
        need(name not in result['sources'] or result['sources'][name]==pin,'P06_REPORT_NO_SOURCE_PIN_REPLACEMENT')
        result['sources'][name]=pin
    return result

def retained_source_contract(partial):
    raw=Path(partial.__file__).read_bytes();expected=fact()['original_partial_retention_AST']
    actual={n.name:sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse(raw).body
        if isinstance(n,ast.FunctionDef) and n.name in expected}
    need(actual==expected,'P06_REPORT_WHOLE_ORIGINAL_PARTIAL_RETENTION_SEAMS_AND_BODIES')

@contextmanager
def entry_context(spec,*,old,out,request):
    from full_system_core import hosted
    hosted()
    if not selected(spec):yield;return
    request_declaration(spec,request)
    import system_campaign_financial_partial as partial
    import system_campaign_p06_abmd_models as models
    retained_source_contract(partial)
    old_models,old_context=partial.retained_models,partial.model_context
    def retained_models(root,parent,target):
        if not selected(target):return old_models(root,parent,target)
        need(encoded(target)==encoded(spec),'P06_REPORT_ONLY_CURRENT_EXPLICIT_TARGET_MODEL_VISITOR')
        need(Path(root)==Path(old) and parent['sha256']==spec['outer_sha256']
             and parent['repairs']==spec['repairs'],'P06_REPORT_ACTUAL_READONLY_FULL10_PARENT_ONLY')
        catalog=load(HERE/fact()['catalog_file'])
        return models.validate_full(root,parent,catalog)['full_inputs']==10
    @contextmanager
    def model_context(root,parent,target):
        if not selected(target):
            with old_context(root,parent,target):yield
            return
        need(encoded(target)==encoded(spec),'P06_REPORT_ONLY_CURRENT_EXPLICIT_TARGET_CODEC')
        need(Path(root)==Path(old) and parent['sha256']==spec['outer_sha256']
             and parent['repairs']==spec['repairs'],'P06_REPORT_ACTUAL_READONLY_FULL10_CODEC_PARENT_ONLY')
        catalog=load(HERE/fact()['catalog_file'])
        native,_=hydrate(catalog,Path(out)/'p06-reporting-abmd-source.json')
        # The old common INPUT tag selects this separately qualified seam; the
        # actual model remains bounded input/1 and there is no B19 codec or seed.
        with InputCodec(catalog['event'],evidence(catalog),native):yield
    partial.retained_models,partial.model_context=retained_models,model_context
    try:yield
    finally:partial.retained_models,partial.model_context=old_models,old_context
