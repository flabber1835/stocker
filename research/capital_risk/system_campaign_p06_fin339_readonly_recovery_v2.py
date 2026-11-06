"""Exact failed FIN339 transport plus new readonly monthly/whole review context."""
import ast,json,os
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import FunctionType,MappingProxyType
import system_campaign_p06_BBIG_data as data
import system_campaign_p06_BBIG_models as models
import system_campaign_p06_BBIG_runtime as runtime
import system_campaign_p06_abmd_lifecycle_data as initial
import system_campaign_p06_BBIG_accounting_review as accounting

HERE=Path(__file__).parent
FACT=accounting.FACT
FACT_SHA=accounting.FACT_SHA
REQUEST='P06-FIN339-captured-financial-request.json'
REQUEST_SHA='6672860c06e73047952b7b08bed1c69d81ec37ff894edddc7b09d90fe70cf101'
FIELD='selected_p06_fin339_readonly_review_recoveries'
MARKER='p06_fin339_readonly_review_recovery'
FLAG='readonly_failed_review_requalification'
MODE='READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION'
ORIGIN=data.ROOT
OUTER='3157c9a6b1eae175a87d0c282c68a5516ea4cb312068da4b43ee80feea4d93e4'
RUN=42257537761
HEAD='6b1c59e2938655b528e62aa77ef40b37a3b15044'
ARTIFACT=13525611349
STATUS='FINANCIAL_REVIEW_REFUSED_PRESERVED'
ARM='P06'
LEGACY_SHA='9d4d9e938685926838e229f05f064803137f47d53bfdacf406bee7a1bffcfa5e'
RUNTIME_SHA='50a0a43d00a3818e89b3fb750c13615fdff215281eba9955853e7818d2bfe90a'
need,sha,encoded=data.need,data.sha,data.encoded

# Capture definitions before context installs dispatch hooks on the module.
import system_campaign_financial_review_repair as _legacy_source
need(sha(Path(_legacy_source.__file__).read_bytes())==LEGACY_SHA,
    'P06_REVIEW339_V2_EXACT_ORIGINAL_QUARANTINE_BEFORE_FUNCTION_CAPTURE')
_LEGACY_ORIGINALS=MappingProxyType({name:getattr(_legacy_source,name) for name in ('public_names','admit')})
need(all(fn.__closure__ is None and fn.__module__==_legacy_source.__name__ for fn in _LEGACY_ORIGINALS.values()),
    'P06_REVIEW339_V2_CAPTURE_ONLY_COMPLETE_ORIGINAL_CLOSURE_FREE_FUNCTIONS')
def fact():
    value=accounting.fact();raw=(HERE/REQUEST).read_bytes()
    need(sha(raw)==REQUEST_SHA,'P06_REVIEW339_EXACT_CAPTURED_FINANCIAL_REQUEST_BYTES')
    request=json.loads(raw)
    need(request['schema']=='research.system-campaign-accurate-resume-request/205' and len(request['sources'])==613
        and request['execution_mode']=='OWN_ADMITTED_FINANCIAL_CONTINUATION' and request['financial_resume_authorized'] is True
        and request['selected_p06_BBIG_ordinary11_retained130']['P06']['root_admission_sha256']==ORIGIN,
        'P06_REVIEW339_ORIGINAL_FINANCIAL_PROVENANCE_NOT_NEW_FINANCIAL_PERMISSION')
    return value
def applies(spec):return isinstance(spec,dict) and spec.get(MARKER) is True
def validate_target(spec):
    need(applies(spec) and encoded(spec)==encoded(fact()['target']),
        'P06_REVIEW339_ONLY_EXACT_UNADMITTED1426_FULL11_FAILED_TRANSPORT')
    need(spec.get(FLAG) is True and 'root_admission' not in spec and 'root_admission_sha256' not in spec
        and 'reuse_closed_hosted_prefix_review' not in spec and spec['review_sha256'] is None
        and spec['financial_authority'] is spec['financial_predecessor_admitted'] is False
        and spec['receipt_status']==STATUS and spec['review_refusal']=='COMPACT_ACCOUNTING_LEDGER_EVENTS'
        and (spec['measured_closes'],spec['selected_session'],len(spec['repairs']))==(1426,'2023-08-31',11)
        and spec['zip_bytes']==377108971 and spec['manifest']==dict(member_count=281,raw_member_bytes=550185887)
        and all(spec['prior_stops'][role]['stopped'] is True and type(spec['prior_stops'][role]['exit_code']) is int
            and spec['prior_stops'][role]['exit_code']==code and spec['prior_stops'][role]['oom_killed'] is False
            for role,code in (('preflight',0),('worker',1),('reviewer',1))),
        'P06_REVIEW339_ORIGINAL_FAILED_STOPS_STATUS_AND_NO_AUTHORITY_PRESERVED')
    return True
def declaration(spec):
    validate_target(spec)
    return dict(schema='research.P06-FIN339-readonly-review-recovery-declaration/1',arm='P06',original_root_admission_sha256=ORIGIN,
        target_outer_sha256=OUTER,target_completed=1426,target_inputs=11,original_financial_artifact_id=ARTIFACT,
        original_financial_run_id=RUN,original_financial_head=HEAD,fact_file=FACT,fact_sha256=FACT_SHA,
        expected_new_rows=43,expected_retained_rows=130,expected_total_proof_rows=173,financial_workers=0,
        financial_resume_authorized=False,input_adopted=False,financial_root_admitted=False,original_failed_stops_preserved=True,
        original_source_record_and_history_guards_preserved=True)
def request_only_readonly(request,spec):
    validate_target(spec)
    need(request['execution_mode']==MODE and request['arms']==['P06'] and request['financial_resume_authorized'] is False
        and request['readonly_partial_review'] is True and request['readonly_source_witnesses'] is False
        and type(request['maximum_parallel_financial_workers']) is int and request['maximum_parallel_financial_workers']==0
        and type(request['maximum_parallel_readonly_workers']) is int and request['maximum_parallel_readonly_workers']==1
        and request.get(FIELD)=={'P06':declaration(spec)},'P06_REVIEW339_ONLY_EXPLICIT_ZERO_FINANCIAL_READONLY_REQUEST')
def target():return json.loads((HERE/'system-campaign-financial-partials.json').read_bytes())['arms']['P06']
def selected_request(request):
    if request.get(FIELD,{}).get('P06') is None:return False
    request_only_readonly(request,target());return True
def source_names():
    return tuple(sorted(set((Path(__file__).name,REQUEST,*accounting.source_names(),*runtime.source_names(),'system_campaign_financial_review_repair.py'))))
def expected_request(original,*,execution_mode,selected_arms,target_lookup):
    result=original();declared={}
    if execution_mode==MODE and list(selected_arms)==['P06']:
        candidate=target_lookup('P06')
        if applies(candidate):declared['P06']=declaration(candidate);result['arm_inputs']['P06']['new_factual_overlay']=False
    result[FIELD]=declared
    for name in source_names():
        pin=sha((HERE/name).read_bytes());need(name not in result['sources'] or result['sources'][name]==pin,'P06_REVIEW339_NO_REQUEST_SOURCE_PIN_REPLACEMENT')
        result['sources'][name]=pin
    return result
def bind(fn,**changes):
    need(fn.__closure__ is None,'P06_REVIEW339_WHOLE_BOUND_FUNCTION_HAS_NO_HIDDEN_CLOSURE')
    result=FunctionType(fn.__code__,dict(fn.__globals__,**changes),fn.__name__,fn.__defaults__);result.__kwdefaults__=fn.__kwdefaults__
    need(result.__code__ is fn.__code__,'P06_REVIEW339_COMPLETE_ORIGINAL_FUNCTION_CODE_OBJECT')
    return result
def legacy(name):
    import system_campaign_financial_review_repair as original
    need(sha(Path(original.__file__).read_bytes())==LEGACY_SHA,'P06_REVIEW339_WHOLE_FROZEN_FAILED_REVIEW_QUARANTINE_SOURCE')
    fn=_LEGACY_ORIGINALS[name]
    return bind(fn,validate_target=validate_target,request_only_readonly=request_only_readonly,
        public_names=public_names,prove_refusal=prove_refusal,ORIGIN=ORIGIN,OUTER=OUTER,RUN=RUN,HEAD=HEAD,ARM=ARM,ARTIFACT=ARTIFACT,STATUS=STATUS)
def public_names(spec,archive):return legacy('public_names')(spec,archive)
def prove_refusal(spec,inventory,root):
    from system_campaign_financial_partial import root_spec
    validate_target(spec);root=Path(root);raw=(root/'stopped-review/worker.log').read_bytes()
    need(sha(raw)==fact()['original_failed_review_log_sha256']==inventory['stopped-review/worker.log']['sha256']
        and b'source_record' in raw and b'require_source_scope' in raw and b"KeyError: 'events'" in raw
        and 'stopped-review/core-review.json' not in inventory,'P06_REVIEW339_EXACT_DIAGNOSED_COMPACT_LEDGER_REFUSAL')
    origin=root_spec('P06',ORIGIN)
    need(json.loads((root/'spec.json').read_bytes())==origin,'P06_REVIEW339_EXACT_ORIGINAL_ADMITTED1383_REVIEW_PARENT')
    old=json.loads((root/'old-prefix-canonical-review.json').read_bytes())
    need(old['checkpoint_sha256']==origin['outer_sha256'] and old['counts']==dict(formation=126,daily=1383)
        and old['all_prefixes_verified'] is old['all_daily_factors_and_chains_verified'] is True,
        'P06_REVIEW339_ONLY_PRIOR1383_ACCOUNTING_REVIEW_EXISTS')
def launcher_guard():
    from probe import check_context
    check_context(os.environ)
def admit(spec,root,key,inspector):launcher_guard();return legacy('admit')(spec,root,key,inspector)
def require_requalified_review(root,spec):
    validate_target(spec);root=Path(root)
    core=json.loads((root/'core-review.json').read_bytes());branch=json.loads((root/'uncertainty-certificate-review.json').read_bytes())
    source=json.loads((root/'p06-BBIG-combined-observation-review.json').read_bytes())
    need(core['checkpoint_sha256']==branch['checkpoint_sha256']==OUTER and core['schema']=='research.full-system-core-review/1'
        and core['status']=='PARTIAL_CORE_PREFIX_REVIEWED' and core['counts']==dict(formation=126,daily=1426)
        and core['all_prefixes_verified'] is core['all_daily_factors_and_chains_verified'] is True and core['complete'] is False
        and branch['schema']=='research.retained-leadership-branch-suffix-review/1' and branch['passed'] is True
        and type(branch['rows']) is type(branch['retained_rows']) is int and (branch['rows'],branch['retained_rows'])==(43,130)
        and branch['parent_sha256']==fact()['actual_neutral11_outer_sha256'] and branch['through']=='2023-08-31'
        and branch['all_financial_watch_and_proof_identities_verified'] is branch['every_reachable_decision_identical'] is True
        and type(branch['prior_proof_rows_reexecuted']) is int and branch['prior_proof_rows_reexecuted']==0
        and branch['prior_qualification_reexecuted'] is False and branch['full_period_complete'] is False
        and type(branch['exhaustive_leaves']) is type(branch['maximum_possible_states']) is int
        and (branch['exhaustive_leaves'],branch['maximum_possible_states'])==(43,1),
        'P06_REVIEW339_NEW_COMPLETE_ORIGINAL_CORE_AND_43_PLUS130_BRANCH_REVIEW_REQUIRED')
    need(source==dict(passed=True,cash_events=[],source_events=[dict(ticker='BBIG',session='2023-07-27',actual_noop=True,
        original_kernel_source_delegated=True,portfolio_completion_authorized=False,actual_settlement_claimed=False)],
        all_committed_dates_and_calls_accounted=True,original_TRQ_MYOV_preserved=True,original_observer_methods_unchanged=True,
        financial_sessions_reexecuted=0),'P06_REVIEW339_NEW_FULL_BBIG_NOOP_AND_COMBINED_OBSERVER_REVIEW_REQUIRED')
    return dict(passed=True,financial_sessions_advanced=0,financial_authority=False,original_financial_artifact_id=ARTIFACT,
        original_failed_receipt_sha256=spec['receipt_sha256'],original_failed_stops_preserved=True,checkpoint_sha256=OUTER,
        core_review_sha256=sha((root/'core-review.json').read_bytes()),branch_review_sha256=sha((root/'uncertainty-certificate-review.json').read_bytes()),
        source_review_sha256=sha((root/'p06-BBIG-combined-observation-review.json').read_bytes()))
def original_parent_selected(spec,request):
    from system_campaign_financial_partial import root_spec
    request_only_readonly(request,target())
    return spec==root_spec('P06',ORIGIN)
def source_contract(module,partial):
    value=fact()
    for source,expected in ((Path(module.__file__).read_bytes(),value['original4_financial_AST']),
        (Path(partial.__file__).read_bytes(),value['original_partial_AST'])):
        actual={n.name:sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name in expected}
        need(actual==expected,'P06_REVIEW339_WHOLE_ORIGINAL_FINANCIAL_AND_PARTIAL_INPUT_MONTHLY_BODIES')
@contextmanager
def preflight_context(module,spec,*,out):
    from system_campaign_bounded_sensor_input import InputCodec
    from system_campaign_abmd_bounded_hydration import hydrate
    from system_campaign_abmd_bounded_catalog import evidence
    import system_campaign_financial_partial as partial
    source_contract(module,partial);saved=partial.retained_models,partial.model_context
    def full(root,current,target):
        if not applies(target):return saved[0](root,current,target)
        validate_target(target)
        need(current['sha256']==OUTER and current['repairs']==target['repairs'] and current['run']['input_sha256']==target['input_sha256'],
            'P06_REVIEW339_ONLY_ACTUAL1426_FULL11_READONLY_PREFLIGHT')
        return models.full(root,current)['full_inputs']==11
    @contextmanager
    def codec(root,current,target):
        if not applies(target):
            with saved[1](root,current,target):yield
            return
        full(root,current,target);value=initial.catalog();native,_=hydrate(value,Path(out)/'p06-FIN339-readonly-codec-source.json')
        with InputCodec(value['event'],evidence(value),native):yield
    partial.retained_models,partial.model_context=full,codec
    try:yield
    finally:partial.retained_models,partial.model_context=saved
@contextmanager
def review_context(module,spec,request,*,old,out,evidence):
    need(sha(Path(runtime.__file__).read_bytes())==RUNTIME_SHA,'P06_REVIEW339_ENTIRE_FROZEN_FINANCIAL_RUNTIME_BYTES')
    need(original_parent_selected(spec,request),'P06_REVIEW339_FRESH_REVIEW_ONLY_GENUINE_ORIGINAL1383_PARENT')
    bound_retained=bind(runtime.bind_retained,selected=original_parent_selected)
    whole_review=bind(runtime.review,selected=original_parent_selected,bind_retained=bound_retained)
    # MODE is truthfully readonly in this separate namespace; run stays closed.
    whole_entry=bind(runtime.entry_context.__wrapped__,MODE=MODE,selected=original_parent_selected,review=whole_review)
    original_review=accounting.original.review;accounting.original.review=accounting.review_function()
    try:
        with contextmanager(whole_entry)(module,spec,mode='review',old=old,out=out,request=request,evidence=evidence):yield
    finally:accounting.original.review=original_review
@contextmanager
def context(request,*,spec=None,mode,module=None,old=None,out=None,evidence=None):
    if mode=='launch':launcher_guard()
    else:
        from full_system_core import hosted
        hosted()
    need(mode in ('launch','preflight','review'),'P06_REVIEW339_ECONOMIC_MODE_FORBIDDEN')
    need(selected_request(request),'P06_REVIEW339_EXACT_ACTIVE_READONLY_REQUEST_REQUIRED')
    import system_campaign_financial_review_repair as original
    from system_campaign_financial_partial import root_spec
    parent=root_spec('P06',ORIGIN)
    if spec is not None:validate_target(spec) if applies(spec) else need(spec==parent,'P06_REVIEW339_ONLY_EXACT_TARGET_OR_ORIGINAL_PARENT')
    saved={n:getattr(original,n) for n in ('applies','admit','ORIGIN','require_requalified_review')}
    original.applies=lambda value:applies(value) or saved['applies'](value)
    original.admit=lambda value,*a,**k:admit(value,*a,**k) if applies(value) else saved['admit'](value,*a,**k)
    original.ORIGIN=ORIGIN
    original.require_requalified_review=lambda root,value:require_requalified_review(root,value) if applies(value) else saved['require_requalified_review'](root,value)
    try:
        if mode=='preflight':
            with preflight_context(module,spec,out=out):yield
        elif mode=='review':
            with review_context(module,spec,request,old=old,out=out,evidence=evidence):yield
        else:yield
    finally:
        for name,value in saved.items():setattr(original,name,value)
def bind_launch(original):
    def launch(args):
        launcher_guard();request=json.loads(Path(args.request).read_bytes())
        if not selected_request(request):return original(args)
        need(args.arm=='P06','P06_REVIEW339_ONLY_EXACT_SELECTED_READONLY_ARM')
        with context(request,mode='launch'):return original(args)
    return launch
