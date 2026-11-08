"""Separate qualified financial route; frozen SOURCE335 guards retain their defaults."""
import ast,json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import FunctionType
import system_campaign_p07_fin326_requalified_parent as composite
import system_campaign_p07_abmd_lifecycle as lifecycle
import system_campaign_financial_uncertainty as uncertainty
import system_campaign_financial_additional_sensor as additional
import system_campaign_p07_vivo_data as data
import system_campaign_p07_vivo_runtime as runtime
import system_campaign_p07_vivo_retained as retained

COMPOSITE_SHA='ca981e5bc69446730cc390093aaf59ed5eec310ac15e950feacb68d4bdb6f680'
HERE=Path(__file__).parent

def request_only_financial(request,spec):return runtime.require_request(spec,request)

def frozen_source():
    raw=Path(composite.__file__).read_bytes()
    data.need(data.sha(raw)==COMPOSITE_SHA,'VIVO_FROZEN_SOURCE_ONLY_COMPOSITE_REMAINS_BYTE_IDENTICAL')
    return raw

def finance_admit(spec,*args,**kwargs):
    frozen_source();original=composite.admit
    data.need(original.__closure__ is None,'VIVO_WHOLE_COMPOSITE_AUTHENTICATION_HAS_NO_HIDDEN_CLOSURE')
    bound=FunctionType(original.__code__,dict(original.__globals__,request_only_source=request_only_financial),original.__name__,original.__defaults__)
    bound.__kwdefaults__=deepcopy(original.__kwdefaults__)
    data.need(bound.__code__ is original.__code__,'VIVO_WHOLE_COMPOSITE_CRYPTO_PUBLIC_SOURCE_AND_FAILED_STOP_GUARDS')
    return bound(spec,*args,**kwargs)

def context_tree(raw):
    data.need(data.sha(raw)==COMPOSITE_SHA,'VIVO_WHOLE_FROZEN_COMPOSITE_CONTEXT_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='context']
    retained.models.replace_count(fn,"('launch', 'preflight')","('launch', 'preflight', 'economic', 'review')",1,'VIVO_ONE_FINANCIAL_TRANSPORT_ALLOWED_MODE_SITE')
    return ast.fix_missing_locations(fn)

@contextmanager
def transport_context(spec,*,mode,request):
    runtime.require_request(spec,request)
    data.need(mode in ('launch','preflight','economic','review'),'VIVO_EXPLICIT_TRUTHFUL_FINANCIAL_TRANSPORT_MODE')
    scope=dict(vars(composite),admit=finance_admit)
    exec(compile(ast.Module(body=[context_tree(frozen_source())],type_ignores=[]),
        '<whole-composite-context-separate-qualified-financial-modes>','exec'),scope)
    with scope['context'](spec,mode=mode):yield

def metadata_tree(raw):
    data.need(data.sha(raw)==retained.U_SHA,'VIVO_WHOLE_ORIGINAL_RETAINED_ADMISSION_METADATA_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='validate_retained_admission_metadata']
    imports=[n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_additional_sensor']
    data.need(len(imports)==1 and [(n.name,n.asname) for n in imports[0].names]==[('unchanged_phase',None),('validate_admission_metadata',None)],
        'VIVO_ONE_EXACT_RETAINED_ADMISSION_DISPATCH_IMPORT')
    fn.body.remove(imports[0]);return ast.fix_missing_locations(fn)

def validate_retained_metadata(spec):
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec);runtime.declaration(spec)
    data.need(runtime.selected(spec),'VIVO_METADATA_BINDING_ONLY_EXACT_NEW_FINANCIAL_ROOT')
    def contract(cp,target):
        data.need(target==spec and cp==dict(sha256=data.OUTER,completed=1259,source_cursor='2022-12-30',base=spec['base'])
             and (spec['measured_closes'],spec['selected_session'],len(spec['repairs']))==(1259,'2022-12-30',24),
             'VIVO_METADATA_ACTUAL1259_FULL24_ROOT_NO_SYNTHETIC_FINANCIAL_CHECKPOINT')
        hashes=json.loads((Path(uncertainty.__file__).parent/uncertainty.INTEGRATION).read_bytes())['canonical_controller_sources']
        data.need(len(hashes)==6 and all(cp['base']['sources'].get(n)==h for n,h in hashes.items())
             and data.sha((Path(uncertainty.__file__).parent/'system_campaign_financial_branches.py').read_bytes())==uncertainty.BRANCH_SHA,
             'VIVO_METADATA_ALL_ORIGINAL_SIX_CONTROLLER_AND_B19_IMPLEMENTATION_GUARDS')
        return hashes
    phase=dict(completed=1259,source_cursor='2022-12-30',rows=805,new_rows=21,retained_rows=784)
    def point(spec):
        data.need(spec['base']['sources']['sentinel/controller/median5.py']==retained.WITNESS_SHA,
             'VIVO_METADATA_EXACT_ORIGINAL_PHYSICAL_POINT_WITNESS')
        return True
    scope=dict(vars(uncertainty),unchanged_phase=lambda spec:False,validate_admission_metadata=additional.validate_admission_metadata,
        retained_contract=contract,retained_phase=lambda target:deepcopy(phase),point_return_phase=point)
    exec(compile(ast.Module(body=[metadata_tree(Path(uncertainty.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-admission-metadata-exact-full24-805-point-bindings>','exec'),scope)
    return scope['validate_retained_admission_metadata'](spec)

@contextmanager
def request_metadata_context(*,execution_mode,selected_arms):
    if execution_mode!=runtime.MODE or 'P07' not in selected_arms:yield;return
    from system_campaign_financial_partial import root_spec
    spec=root_spec('P07')
    if not runtime.selected(spec):yield;return
    runtime.declaration(spec);original=uncertainty.validate_retained_admission_metadata
    uncertainty.validate_retained_admission_metadata=lambda target:validate_retained_metadata(target) if runtime.selected(target) else original(target)
    try:yield
    finally:uncertainty.validate_retained_admission_metadata=original

def bind_expected_request(module):
    original=module.expected_request
    def expected():
        with request_metadata_context(execution_mode=module.EXECUTION_MODE,selected_arms=module.SELECTED_ARMS):return original()
    return expected

def expected_request(original,*,execution_mode,selected_arms,root_lookup,source_bytes=None):
    if execution_mode!=runtime.MODE or 'P07' not in selected_arms or not runtime.selected(root_lookup('P07')):
        result=composite.expected_request(original,execution_mode=execution_mode,selected_arms=selected_arms,root_lookup=root_lookup)
        result[runtime.FIELD]={}
        return result
    spec=root_lookup('P07');decl=runtime.declaration(spec);frozen_source();result=original()
    data.need(result['execution_mode']==runtime.MODE and result['financial_resume_authorized'] is True
         and result['readonly_source_witnesses'] is result['readonly_partial_review'] is False,
         'VIVO_REQUEST_ROUTE_PRESERVES_TRUTHFUL_FINANCIAL_EXECUTION_MODE')
    result[composite.SOURCE_FIELD]={};result[runtime.FIELD]={'P07':decl}
    result['arm_inputs']['P07']['new_factual_overlay']=True
    reader=(lambda name:(HERE/name).read_bytes()) if source_bytes is None else source_bytes
    for name in (*composite.source_names(),*source_names()):
        raw=reader(name);pin=data.sha(raw)
        data.need(name not in result['sources'] or result['sources'][name]==pin,'VIVO_REQUEST_NO_SOURCE_PIN_REPLACEMENT')
        result['sources'][name]=pin
    runtime.require_request(spec,result)
    return result

def bind_launch(original):
    frozen_source()
    expected=composite.bind_launch(lambda args:None)
    data.need(original.__code__ is expected.__code__ and original.__code__.co_freevars==('original',)
         and original.__globals__ is vars(composite),'VIVO_LATE_BIND_ONLY_COMPLETE_FROZEN_COMPOSITE_LAUNCH_WRAPPER')
    def launch(args):
        request=json.loads(Path(args.request).read_bytes())
        if args.arm!='P07' or request.get('execution_mode')!=runtime.MODE:return original(args)
        from system_campaign_financial_partial import root_spec
        spec=root_spec('P07')
        if not runtime.selected(spec):return original(args)
        runtime.require_request(spec,request)
        def context(target,*,mode):return transport_context(target,mode=mode,request=request)
        bound=FunctionType(original.__code__,dict(original.__globals__,request_only_source=request_only_financial,context=context),
            original.__name__,original.__defaults__,original.__closure__)
        data.need(bound.__code__ is original.__code__ and bound.__closure__ is original.__closure__,
             'VIVO_WHOLE_ORIGINAL_LAUNCH_BODY_AND_INNER_CLOSURE_UNCHANGED')
        return bound(args)
    return launch

@contextmanager
def entry_context(module,spec,*,mode,request):
    from full_system_core import hosted
    hosted()
    runtime.require_request(spec,request)
    data.need(mode in ('preflight','economic','review'),'VIVO_FINANCIAL_ENTRY_EXPLICIT_PRELIGHT_ECONOMIC_REVIEW')
    old_api,old_overlay=lifecycle.api,module.factual_overlay_needed
    lifecycle.api=lambda root,cp,target:runtime.api(root,cp,target) if runtime.selected(target) else old_api(root,cp,target)
    module.factual_overlay_needed=lambda target:True if runtime.selected(target) else old_overlay(target)
    try:
        with transport_context(spec,mode=mode,request=request):yield
    finally:lifecycle.api,module.factual_overlay_needed=old_api,old_overlay

def source_names():return (Path(__file__).name,*runtime.source_names())
