"""Whole prepared lifecycle plus resource-bound preflight and closed gate failure."""
import json
from contextlib import contextmanager
from pathlib import Path,PurePosixPath
from types import FunctionType
import system_campaign_p05_remaining_runtime as original

HERE=Path(__file__).parent
BASE_Q='P05-retained18-financial-lifecycle-preparation.json'
BASE_SHA='ebf8f627595d5df822afade6b2e46e2984229f91c0958ac5966976e2c35c93c0'
FIELD,MODE=original.FIELD,original.MODE
need,sha,encoded=original.need,original.sha,original.encoded
GATE='P05-retained18-preflight-packet-gate.json'
GATE_SCHEMA='research.P05-retained18-preflight-packet-gate/2'
QUALIFICATION='P05-retained18-financial-runtime-v2-preparation.json'
initial,family=original.initial,original.family

def source_names():
    return tuple(sorted(set((Path(__file__).name,BASE_Q,QUALIFICATION,*original.source_names()))))

def qualified_base():
    raw=(HERE/BASE_Q).read_bytes();need(sha(raw)==BASE_SHA,'P05_RUNTIME18_V2_ENTIRE_FROZEN_BASE_QUALIFICATION')
    q=json.loads(raw);name=Path(original.__file__).name
    need(q['passed'] is q['prepared'] is True and q['financial_authority'] is False
        and q['files'][name]==dict(bytes=Path(original.__file__).stat().st_size,sha256=sha(Path(original.__file__).read_bytes())),
        'P05_RUNTIME18_V2_WHOLE_FROZEN_BASE_RUNTIME_BYTES')

def declaration(spec):
    qualified_base()
    return dict(original.declaration(spec),actual_hosted36_packet_checks_required_before_financial_entry=True,
        preflight_packet_gate_schema=GATE_SCHEMA,origin_gate_validation_failure_keeps_advance_closed=True)

def bind_function(fn,**changes):
    need(fn.__closure__ is None,'P05_RUNTIME18_V2_NO_HIDDEN_ORIGINAL_FUNCTION_CLOSURE')
    bound=FunctionType(fn.__code__,dict(fn.__globals__,**changes),fn.__name__,fn.__defaults__)
    bound.__kwdefaults__=fn.__kwdefaults__
    need(bound.__code__ is fn.__code__,'P05_RUNTIME18_V2_WHOLE_ORIGINAL_FUNCTION_CODE_OBJECT')
    return bound

def selected(spec,request):
    return bind_function(original.selected,declaration=declaration)(spec,request)

def expected_request(*a,**k):
    return bind_function(original.expected_request,declaration=declaration,source_names=source_names)(*a,**k)

def validate_preflight_packet(parent,spec,proof,member):
    original.preparation.validate_spec(spec);original.origin.data.own.parent_contract(parent)
    expected_header=dict(schema='research.P05-own1175-retained18-source-preparation/1',passed=True,
        root_admission_sha256=original.origin.data.own.ROOT,parent_outer_sha256=parent['sha256'],parent_completed=1175,full_parent_inputs=19,
        declaration=original.preparation.declaration(spec),packet_checks=36,terms=18,financial_sessions_advanced=0,
        canonical_checkpoint_or_root_written=False,canonical_parent_unchanged=True,financial_request_authorized=False,
        original_future_prepare_and_qualify_code_unchanged=True)
    need({k:v for k,v in proof.items() if k!='resources'}==expected_header
        and type(proof['financial_sessions_advanced']) is type(proof['packet_checks']) is type(proof['terms']) is int,
        'P05_RUNTIME18_V2_EXACT_ACTUAL_PARENT_ZERO_ADVANCE_HOSTED36_PREPARATION_HEADER')
    pins=proof['resources']
    need(isinstance(pins,dict) and pins and original.preparation.PROOF not in pins
        and all(isinstance(n,str) and not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts
            and ':' not in n and '\\' not in n and isinstance(pin,dict) and set(pin)=={'bytes','sha256'}
            and type(pin['bytes']) is int and pin['bytes']>=0 and isinstance(pin['sha256'],str) and len(pin['sha256'])==64
            and all(c in '0123456789abcdef' for c in pin['sha256']) for n,pin in pins.items()),
        'P05_RUNTIME18_V2_FULL_SAFE_ACTUAL_PREFLIGHT_RESOURCE_INVENTORY_BEFORE_READ')
    blobs={n:member(n) for n in pins}
    need(all(dict(bytes=len(raw),sha256=sha(raw))==pins[n] for n,raw in blobs.items()),'P05_RUNTIME18_V2_ALL_ACTUAL_PREFLIGHT_PREPARATION_RESOURCE_BYTES')
    api_module=original.origin.api_module;data=original.origin.data
    hydrated=api_module.original.hydration_name(parent)
    required={data.CATALOG,hydrated,api_module.original.OVERLAY,api_module.original.SOURCE_SCOPES,api_module.QUALIFICATION,
        'strict-parent-preflight.json','old-prefix-canonical-review.json','provider-source/SHARADAR_ACTIONS.zip','P05-retained18-provider-stage.json'}
    need(required<=set(blobs),'P05_RUNTIME18_V2_NO_OMITTED_MANDATORY_PACKET_PARENT_OR_PROVIDER_PROOF')
    material=original.origin.material(parent)
    need(blobs[data.CATALOG]==encoded(data.catalog(parent)) and blobs[hydrated]==encoded(material),
        'P05_RUNTIME18_V2_COMPLETE_PREFLIGHT18_SELECTION_AND_HYDRATION_NOT_PARTIAL')
    api=api_module.api(parent)
    doc=api.document(parent,material,sha(blobs[hydrated]))
    need(blobs[api_module.original.OVERLAY]==encoded(doc) and len(doc['source_evidence'])<=128,
        'P05_RUNTIME18_V2_WHOLE_ORIGINAL_PREFLIGHT_OVERLAY_AND128_EVIDENCE_LIMIT')
    scopes=api.source_scopes(parent,material,sha(blobs[api_module.original.OVERLAY]),sha(blobs[hydrated]))
    need(blobs[api_module.original.SOURCE_SCOPES]==encoded(scopes) and len(scopes)==1,
        'P05_RUNTIME18_V2_ONE_WHOLE_ORIGINAL_PREFLIGHT_CTXS_SCOPE')
    original.origin.qualification(json.loads(blobs[api_module.QUALIFICATION]))
    strict=json.loads(blobs['strict-parent-preflight.json'])
    need(strict['passed'] is True and strict['root_admission_sha256']==spec['root_admission_sha256']
        and strict['outer_sha256']==parent['sha256'] and strict['financial_sessions_advanced']==0
        and type(strict['financial_sessions_advanced']) is int
        and strict['accounting_review_sha256']==sha(blobs['old-prefix-canonical-review.json']),
        'P05_RUNTIME18_V2_ACTUAL_STRICT_PARENT_AND_ACCOUNTING_REVIEW_BOUND_TO_PACKET_PREPARATION')
    provider=blobs['provider-source/SHARADAR_ACTIONS.zip']
    need(len(provider)==9855560 and sha(provider)=='db67132dca8cf38107ca4bcaea7276ea5d0e8f77254f6556802caad6efa91b02',
        'P05_RUNTIME18_V2_WHOLE_ACTUAL_PREFLIGHT_FROZEN_PROVIDER_OBJECT')
    need(json.loads(blobs['P05-retained18-provider-stage.json'])==dict(passed=True,
        provider_sha256='db67132dca8cf38107ca4bcaea7276ea5d0e8f77254f6556802caad6efa91b02',original_provider_rows_verified=9,
        financial_sessions_advanced=0,original_stage_code_unchanged=True,metadata_authority_upgraded=False),
        'P05_RUNTIME18_V2_ALL_NINE_ORIGINAL_PROVIDER_ROWS_AND_NO_METADATA_UPGRADE')
    return dict(schema=GATE_SCHEMA,passed=True,parent_outer_sha256=parent['sha256'],root_admission_sha256=spec['root_admission_sha256'],
        whole_preflight_preparation_sha256=sha(encoded(proof)),packet_checks=36,financial_sessions_advanced=0,
        complete_original_overlay_scope_and_provider_verified=True)

def copy_provider_from_preflight(out):
    original.origin.api_module.original.hosted()
    out=Path(out);spec=json.loads((out/'spec.json').read_bytes())
    parent_raw=(out/'book/predecessor-checkpoints'/(original.origin.data.own.OUTER+'.json.gz')).read_bytes()
    need(dict(bytes=len(parent_raw),sha256=sha(parent_raw))==spec['selected_file'],'P05_RUNTIME18_V2_ACTUAL_SELECTED_PARENT_GZIP_BEFORE_PACKET_GATE')
    parent=original.origin.actual_json(parent_raw);root=out/'parent-preflight'
    proof=json.loads((root/original.preparation.PROOF).read_bytes())
    result=validate_preflight_packet(parent,spec,proof,lambda n:(root/n).read_bytes())
    need((out/'strict-parent-preflight.json').read_bytes()==(root/'strict-parent-preflight.json').read_bytes(),
        'P05_RUNTIME18_V2_PACKET_AND_ORIGINAL_ECONOMIC_ENTRY_SHARE_EXACT_STRICT_PREFLIGHT')
    original.exact(out/GATE,encoded(result))
    return original.copy_provider_from_preflight(out)

def gate_class(Original,*a,**k):
    Base=original.gate_class(Original,*a,**k)
    class Gate(Base):
        def write(self,*args,**kwargs):
            try:return super().write(*args,**kwargs)
            except BaseException:
                self.accepted=False
                raise
    need(Gate.advance is Original.advance and Gate.__enter__ is Original.__enter__ and Gate.__exit__ is Original.__exit__,
        'P05_RUNTIME18_V2_ORIGINAL_ADVANCE_AND_CONTEXT_METHODS_UNCHANGED')
    return Gate

def old_entry(*a,**k):
    return contextmanager(bind_function(original.old_entry.__wrapped__,selected=selected))(*a,**k)

def entry_context(*a,**k):
    fn=bind_function(original.entry_context.__wrapped__,selected=selected,old_entry=old_entry,
        copy_provider_from_preflight=copy_provider_from_preflight,gate_class=gate_class)
    return contextmanager(fn)(*a,**k)

def launch_context(*a,**k):
    return contextmanager(bind_function(original.launch_context.__wrapped__,selected=selected))(*a,**k)

def bind_launch(*a,**k):
    return bind_function(original.bind_launch,launch_context=launch_context)(*a,**k)
