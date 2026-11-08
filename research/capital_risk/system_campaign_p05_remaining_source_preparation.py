"""Finite SOURCE-only hosted packet preparation; no financial entry authority."""
import gzip,json,os,shutil
from pathlib import Path
from types import FunctionType
from contextlib import contextmanager
import system_campaign_p05_remaining_batch_data as data
import system_campaign_p05_remaining_batch_api as batch

HERE=Path(__file__).parent
FIELD='selected_p05_retained18_source_preparations'
PROOF='P05-retained18-source-preparation.json'
QUAL='P05-retained18-data-API-qualification.json'
QUAL_SHA='058ab93b6ad968075424d5432be576e5027446f15be5036212e292db260d552e'
MODE='READONLY_FROZEN_SOURCE_WITNESSES'
need,sha=data.need,data.sha

def source_names():
    return tuple(sorted(set((Path(__file__).name,QUAL,*data.source_names()))))

def validate_spec(spec):
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec)
    need((spec['arm'],spec['root_admission_sha256'],spec['outer_sha256'],spec['measured_closes'],spec['selected_session'],len(spec['repairs']))==
        ('P05',data.own.ROOT,data.own.OUTER,1175,'2022-08-31',19),'P05_SOURCE18_ONLY_ACTUAL1175_FULL19_AUTHORITY')

def declaration(spec):
    validate_spec(spec)
    raw=(HERE/QUAL).read_bytes();need(sha(raw)==QUAL_SHA,'P05_SOURCE18_ENTIRE_CLOSED_DATA_API_QUALIFICATION')
    q=json.loads(raw)
    need(q['passed'] is True and q['financial_authority'] is q['financial_input_selected'] is q['input_adopted'] is False
        and type(q['financial_sessions_advanced']) is int and q['financial_sessions_advanced']==0,
        'P05_SOURCE18_DATA_API_IS_NOT_FINANCIAL_AUTHORITY')
    return dict(schema='research.P05-own1175-retained18-source-preparation-declaration/1',arm='P05',
        root_admission_sha256=data.own.ROOT,parent_outer_sha256=data.own.OUTER,parent_completed=1175,full_parent_inputs=19,
        data_API_qualification_sha256=QUAL_SHA,terms=18,packet_checks=36,financial_sessions_advanced=0,
        canonical_checkpoint_or_root_written=False,financial_request_authorized=False,
        original_provider_sha256='db67132dca8cf38107ca4bcaea7276ea5d0e8f77254f6556802caad6efa91b02')

def selected_request(request,spec):
    declared=request.get(FIELD,{})
    if not declared:return False
    validate_spec(spec)
    need(request.get('execution_mode')==MODE and request.get('readonly_source_witnesses') is True
        and request.get('financial_resume_authorized') is request.get('readonly_partial_review') is False
        and declared=={'P05':declaration(spec)},'P05_SOURCE18_ONLY_EXPLICIT_SOURCE_REQUEST_AND_EXACT_DECLARATION')
    return True

def expected_request(original,*,execution_mode,selected_arms,root_lookup):
    result=original()
    need(FIELD not in result,'P05_SOURCE18_NO_REPLACEMENT_OF_EXISTING_DECLARATION')
    result[FIELD]={}
    if execution_mode==MODE and 'P05' in selected_arms:
        spec=root_lookup('P05')
        if spec.get('root_admission_sha256')==data.own.ROOT:
            result[FIELD]['P05']=declaration(spec)
    for name in source_names():
        pin=sha((HERE/name).read_bytes())
        need(name not in result['sources'] or result['sources'][name]==pin,'P05_SOURCE18_NO_FROZEN_SOURCE_PIN_REPLACEMENT')
        result['sources'][name]=pin
    if result[FIELD]:selected_request(result,root_lookup('P05'))
    return result

def provider_stage_function():
    original=batch.original
    need(sha(Path(original.__file__).read_bytes())==data.own.FUTURE_SHA,'P05_SOURCE18_ENTIRE_ORIGINAL_PROVIDER_HOST_STAGE_SOURCE')
    fn=original.stage_selected_sources
    need(fn.__closure__ is None,'P05_SOURCE18_ORIGINAL_STAGE_HAS_NO_HIDDEN_CLOSURE')
    phase=('P05','2022-08-31')
    tables=dict(SINGLE_PHASES={('P07','2020-02-28'):original.SINGLE_PHASES['P07','2020-02-28'],phase:('EXACT_P05_SOURCE_ONLY',)},
        FOLLOWING_PHASES={},ADDITIONAL_SENSOR_ALIAS_PHASES={},ROOT_BOUND_ALIAS_SOURCE_PHASES={phase:(data.own.ROOT,data.own.OUTER,1175)})
    bound=FunctionType(fn.__code__,dict(vars(original),**tables),fn.__name__,fn.__defaults__)
    bound.__kwdefaults__=fn.__kwdefaults__
    need(bound.__code__ is fn.__code__,'P05_SOURCE18_WHOLE_PROVIDER_HOST_STAGE_FUNCTION')
    return bound

def stage_provider(spec,old,out):
    from probe import check_context
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','P05_SOURCE18_NO_HOST_RERUN')
    validate_spec(spec)
    old,out=Path(old),Path(out)
    selected=(old/spec['selected_checkpoint']).read_bytes()
    need(dict(bytes=len(selected),sha256=sha(selected))==spec['selected_file'],'P05_SOURCE18_HOST_ACTUAL_AUTHENTICATED_PARENT_BEFORE_PROVIDER_STAGE')
    need(not (out/'provider-source').exists(),'P05_SOURCE18_ONE_ORIGINAL_PROVIDER_STAGE')
    provider_stage_function()(spec,old,out)
    proof=data.validate_provider(out/'provider-source/SHARADAR_ACTIONS.zip')
    batch.original.save(out/'P05-retained18-provider-stage.json',dict(proof,original_stage_code_unchanged=True,
        metadata_authority_upgraded=False,financial_sessions_advanced=0))

def file_members(root):
    return sorted(p.relative_to(root).as_posix() for p in Path(root).rglob('*') if p.is_file())

def reject_canonical_output(out):
    names=file_members(out)
    need(not any(n.split('/')[0] in ('book','input-adoption') or Path(n).name in ('checkpoint.json.gz','proof.json')
        for n in names),'P05_SOURCE18_NO_NEW_CANONICAL_BOOK_CHECKPOINT_OR_ADOPTION')
    return names

def prepare_after_preflight(old,out,spec):
    batch.original.hosted()
    validate_spec(spec)
    old,out=Path(old),Path(out)
    proof=json.loads((out/'strict-parent-preflight.json').read_bytes())
    need(proof['passed'] is True and proof['outer_sha256']==data.own.OUTER and proof['root_admission_sha256']==data.own.ROOT
        and type(proof['financial_sessions_advanced']) is int and proof['financial_sessions_advanced']==0,
        'P05_SOURCE18_WHOLE_ORIGINAL_STRICT_PREFLIGHT_MUST_PASS_FIRST')
    reject_canonical_output(out)
    before_members=file_members(old);selected=old/spec['selected_checkpoint'];raw=selected.read_bytes()
    need(dict(bytes=len(raw),sha256=sha(raw))==spec['selected_file'],'P05_SOURCE18_ACTUAL_AUTHENTICATED_PARENT_GZIP_BYTES')
    parent=json.loads(gzip.decompress(raw));data.own.parent_contract(parent);before_json=data.encoded(parent)
    api=batch.api(parent,provider_root=out)
    path,loaded=api.prepare(parent,out,'P05')
    q=json.loads((out/batch.QUALIFICATION).read_bytes())
    need(q['passed'] is True and q['packet_checks']==36 and type(q['financial_sessions_advanced']) is int and q['financial_sessions_advanced']==0
        and all(q[k] is True for k in ('only_terminal_field_changed','complete_terms_and_canonical_notional_verified',
            'original_incomplete_guard_retained','wrong_predecessor_and_consumed_date_refused','wrong_native_and_delivery_witness_refused')),
        'P05_SOURCE18_ENTIRE_ORIGINAL_36_PACKET_CHECKS_WITH_ALL_GUARDS')
    need(path==out/batch.original.OVERLAY and loaded.sha256==sha(path.read_bytes()) and loaded.earliest_affected_session=='2022-09-29',
        'P05_SOURCE18_ACTUAL_ORDINARY_INPUT_PARSER_AND_FIRST_UNCONSUMED_SESSION')
    need(selected.read_bytes()==raw and data.encoded(parent)==before_json and file_members(old)==before_members,
        'P05_SOURCE18_PARENT_GZIP_JSON_AND_ARCHIVE_MEMBERSHIP_UNCHANGED')
    names=reject_canonical_output(out)
    need(PROOF not in names,'P05_SOURCE18_ONE_PREPARATION_PROOF')
    resources={n:dict(bytes=(out/n).stat().st_size,sha256=sha((out/n).read_bytes())) for n in names}
    result=dict(schema='research.P05-own1175-retained18-source-preparation/1',passed=True,
        root_admission_sha256=data.own.ROOT,parent_outer_sha256=data.own.OUTER,parent_completed=1175,full_parent_inputs=19,
        declaration=declaration(spec),packet_checks=36,terms=18,financial_sessions_advanced=0,
        canonical_checkpoint_or_root_written=False,canonical_parent_unchanged=True,financial_request_authorized=False,
        original_future_prepare_and_qualify_code_unchanged=True,resources=resources)
    batch.original.save(out/PROOF,result)
    return result

def bind_preflight(original):
    def preflight(old,out,spec):
        request=json.loads((HERE/'system-campaign-factual-request.json').read_bytes())
        selected=selected_request(request,spec)
        value=original(old,out,spec)
        if selected:prepare_after_preflight(old,out,spec)
        return value
    return preflight

def preflight_worker_old(values,name,output,*,run_id,runner_temp):
    suffix=['-B','-u','/driver/system_campaign_financial_resume.py','--mode','preflight','--spec','/out/spec.json']
    need(values.count('-B')==1 and values[values.index('-B'):]==suffix
        and name=='capital-system-resume-p05-preflight-'+run_id+'-1',
        'P05_SOURCE18_ONLY_EXACT_PREFLIGHT_WORKER_NO_ECONOMIC_OR_REVIEW')
    need(Path(output).resolve()==(Path(runner_temp)/'financial-resume-preflight-P05').resolve(),
        'P05_SOURCE18_EXACT_ORIGINAL_PREFLIGHT_OUTPUT')
    mounts=[v for v in values if isinstance(v,str) and v.startswith('type=bind,source=') and ',target=/old' in v]
    need(len(mounts)==1 and mounts[0].endswith(',target=/old,readonly') and len(mounts[0].split(','))==4,
        'P05_SOURCE18_ONE_REAL_READONLY_AUTHENTICATED_OLD_MOUNT')
    old=Path(mounts[0].split('source=',1)[1].split(',target=',1)[0])
    need(old.resolve().is_relative_to(Path(runner_temp).resolve()),'P05_SOURCE18_OLD_MOUNT_WITHIN_ACTUAL_HOSTED_TEMP')
    return old

@contextmanager
def launch_context(module,request,*,arm):
    from probe import check_context
    check_context(os.environ)
    spec=module.root_spec(arm)
    need(selected_request(request,spec) and arm=='P05','P05_SOURCE18_ONLY_DECLARED_HOST_LAUNCH')
    original=module.stopped_run
    def stopped(values,name,output,*a,**k):
        if '/driver/system_campaign_financial_resume.py' in values:
            old=preflight_worker_old(values,name,output,run_id=os.environ['GITHUB_RUN_ID'],runner_temp=os.environ['RUNNER_TEMP'])
            stage_provider(spec,old,Path(output))
        return original(values,name,output,*a,**k)
    module.stopped_run=stopped
    try:yield
    finally:module.stopped_run=original

def bind_launch(original,module):
    def launch(args):
        from probe import check_context
        check_context(os.environ)
        request=json.loads(Path(args.request).read_bytes())
        if not request.get(FIELD) or args.arm!='P05':return original(args)
        with launch_context(module,request,arm=args.arm):return original(args)
    return launch
