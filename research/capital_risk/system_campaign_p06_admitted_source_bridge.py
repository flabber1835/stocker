"""Exact admitted1383/full10 source-only retention; no financial continuation."""
from contextlib import contextmanager
from pathlib import Path
from types import FunctionType
import system_campaign_p06_retained_reporting as original
from system_campaign_bounded_sensor_input import need,sha

ROOT='28c768af0d50047f04ddd6924c1500bf768cc138f41808cd1c0a0b5321eb64b8'
OUTER='bd3e5c6b01942efedf344756dd2a52a7a616fbf81b4d76c73f1397b9498a3e08'
ORIGINAL_SHA='2faa1a5c3af0a36fc8ea51d813bcb1ed264de3dbbdf53890d45dde365209ae9f'
MODE='READONLY_FROZEN_SOURCE_WITNESSES'
FIELD='selected_p06_admitted_source_bridges'

def selected(spec):
    return isinstance(spec,dict) and spec.get('arm')=='P06' and spec.get('root_admission_sha256')==ROOT

def declaration(spec):
    from system_campaign_financial_partial import validate_root_spec
    need(selected(spec),'P06_SOURCE_ONLY_EXACT_ADMITTED1383_ROOT')
    validate_root_spec(spec)
    need(spec['outer_sha256']==OUTER and spec['measured_closes']==1383 and spec['selected_session']=='2023-06-30'
        and len(spec['repairs'])==10 and spec['financial_authority'] is False
        and spec['root_admission']['independent_review_sha256']=='f4a0f3a36aa5855a8cc36e1b0a9bb8eb62586c266480fff0cdd27a1b82c72747'
        and spec['root_admission']['parent_root_admission_sha256']==original.ROOT,
        'P06_SOURCE_ONLY_REAL_DATA_ADMITTED_FULL10_AND_CLOSED_PARENT')
    proof=spec['root_admission']['branch_uncertainty_proof']
    need(proof['passed'] is True and (proof['retained_rows'],proof['rows'])==(6,124),
        'P06_SOURCE_ONLY_EXACT130_COMMITTED_PROOFS_NO_NEW_SEED')
    return dict(schema='research.P06-admitted-full10-readonly-source-bridge/1',arm='P06',
        root_admission_sha256=ROOT,outer_sha256=OUTER,completed=1383,source_cursor='2023-06-30',full_inputs=10,
        original_retention_context_sha256=ORIGINAL_SHA,source_only=True,financial_authority=False,
        new_input_adopted=False,financial_transitions_reexecuted=0,old_B19_codec_installed=False)

def request_declaration(spec,request):
    expected=declaration(spec)
    need(request.get('execution_mode')==MODE and request.get('readonly_source_witnesses') is True
        and request.get('financial_resume_authorized') is False and request.get('readonly_partial_review') is False
        and type(request.get('maximum_parallel_financial_workers')) is int and request['maximum_parallel_financial_workers']==0
        and request.get(FIELD,{}).get('P06')==expected,'P06_SOURCE_ONLY_EXPLICIT_ZERO_FINANCIAL_SOURCE_REQUEST')
    return expected

def selected_request(spec,request):
    return selected(spec) and isinstance(request,dict) and request.get('execution_mode')==MODE and request.get(FIELD,{}).get('P06')==declaration(spec)

def bound_context():
    need(sha(Path(original.__file__).read_bytes())==ORIGINAL_SHA,'P06_SOURCE_ONLY_WHOLE_QUALIFIED_RETENTION_CONTEXT_SOURCE')
    fn=original.entry_context.__wrapped__
    need(fn.__closure__ is None,'P06_SOURCE_ONLY_ORIGINAL_CONTEXT_HAS_NO_HIDDEN_CLOSURE')
    namespace=dict(fn.__globals__,selected=selected,request_declaration=request_declaration)
    whole=FunctionType(fn.__code__,namespace,fn.__name__,fn.__defaults__)
    need(whole.__code__ is fn.__code__,'P06_SOURCE_ONLY_WHOLE_RETENTION_CONTEXT_CODE_UNCHANGED')
    return contextmanager(whole)

@contextmanager
def entry_context(spec,*,old,out,request):
    request_declaration(spec,request)
    with bound_context()(spec,old=old,out=out,request=request):yield

def source_names():return (Path(__file__).name,)

def expected_request(original_request,*,execution_mode,selected_arms,root_lookup):
    result=original_request();declared={}
    if execution_mode==MODE:
        for arm in selected_arms:
            spec=root_lookup(arm)
            if selected(spec):declared[arm]=declaration(spec)
    result[FIELD]=declared
    path=Path(__file__);pin=sha(path.read_bytes())
    need(path.name not in result['sources'] or result['sources'][path.name]==pin,'P06_SOURCE_ONLY_NO_SOURCE_PIN_REPLACEMENT')
    result['sources'][path.name]=pin
    return result
