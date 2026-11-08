"""Finite initial19/new20 lifecycle around complete original financial bodies."""
import ast,gzip,json,os
from copy import deepcopy
from contextlib import contextmanager,nullcontext
from pathlib import Path
from types import FunctionType,CodeType
import system_campaign_p05_remaining_source_preparation_v2 as preparation
import system_campaign_p05_remaining_origin_data as origin
import system_campaign_p05_remaining_observer_data as observer
import system_campaign_retained_cash_v2 as cash
import system_campaign_retained_forward_cash as prior
import system_campaign_pending_cash_api as pending

HERE=Path(__file__).parent
FIELD='selected_p05_retained18_financial_inputs'
MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION'
GATE_AST='90b75c2165958da9a7ffe97db60f639d9199d8d43a876e01ed07398c87ecc2f6'
Q_PINS={'P05-retained18-data-API-qualification.json':'058ab93b6ad968075424d5432be576e5027446f15be5036212e292db260d552e',
    'P05-retained18-source-preparation-qualification.json':'b703f44d56d4b83d093b30a43806724a6451b966665fa5f48814d2cfe5ac4d0e',
    'P05-retained18-source-preparation-v2-qualification.json':'e07ba5b60ef7caee51acb3f059b4e0d61a22233d5bfdadd3bcb435aa10553cb6',
    'P05-retained18-origin-inventory-DATA-preparation.json':'35b1a903790db3c95691e03a12df25e54b120704b50e28fdde8439ebe72b3625',
    'P05-retained18-single-observer-DATA-preparation.json':'94c1912514845d377a5ac6e6fa0b3c12b6b27840ddd95b4df18bdadbced2ac57'}
need,sha,encoded=origin.need,origin.sha,origin.encoded

def source_names():
    return tuple(sorted(set((Path(__file__).name,'system_campaign_p05_remaining_origin_data.py',
        'system_campaign_p05_remaining_observer_data.py',*preparation.source_names(),*Q_PINS))))

def initial(spec):
    return isinstance(spec,dict) and spec.get('arm')=='P05' and spec.get('root_admission_sha256')==origin.data.own.ROOT

def family(spec):
    if initial(spec):return True
    if not isinstance(spec,dict) or spec.get('arm')!='P05' or len(spec.get('repairs',[]))!=20:return False
    from system_campaign_financial_partial import root_spec
    return spec['repairs'][:19]==root_spec('P05',origin.data.own.ROOT)['repairs']

def prerequisites():
    for name,pin in Q_PINS.items():
        raw=(HERE/name).read_bytes();need(sha(raw)==pin,'P05_RUNTIME18_ENTIRE_CLOSED_PREREQUISITE:'+name)
        value=json.loads(raw)
        need(value['passed'] is True and value['financial_authority'] is False
            and type(value['financial_sessions_advanced']) is int and value['financial_sessions_advanced']==0,
            'P05_RUNTIME18_DATA_PREREQUISITES_NOT_FINANCIAL_STATE_AUTHORITY')

def declaration(spec):
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec);need(family(spec),'P05_RUNTIME18_ONE_EXACT_ORIGIN_OR_ACTUAL20_ROOT_FAMILY')
    if initial(spec):preparation.validate_spec(spec)
    else:
        need(spec['measured_closes']>=1175 and spec['selected_session']>='2022-08-31'
            and spec['root_admission_sha256']!=origin.data.own.ROOT,'P05_RUNTIME18_RETAINED_REAL_CURRENT20_ROOT_NEVER_ORIGIN_SEED')
    prerequisites()
    return dict(schema='research.P05-retained18-financial-lifecycle-declaration/1',arm='P05',
        current_root_admission_sha256=spec['root_admission_sha256'],current_outer_sha256=spec['outer_sha256'],
        current_input_sha256=spec['input_sha256'],current_full_inputs=len(spec['repairs']),
        origin_root_admission_sha256=origin.data.own.ROOT,initial_adoption_required=initial(spec),
        selected_terms=18,all94_original_observation_terms_retained=True,actual20_origin_required=not initial(spec),
        original_canonical_financial_source_unchanged=True,original128_evidence_limit_unchanged=True,
        prerequisites=dict(Q_PINS))

def selected(spec,request):
    declared=request.get(FIELD,{})
    if not declared or not family(spec):return False
    need(request.get('execution_mode')==MODE and request.get('financial_resume_authorized') is True
        and request.get('readonly_partial_review') is request.get('readonly_source_witnesses') is False
        and declared=={'P05':declaration(spec)},'P05_RUNTIME18_ONLY_SEPARATELY_DECLARED_EXACT_FINANCIAL_PHASE')
    return True

def expected_request(original,*,execution_mode,selected_arms,root_lookup):
    result=original();need(FIELD not in result,'P05_RUNTIME18_NO_EXISTING_FINANCIAL_DECLARATION_REPLACEMENT')
    result[FIELD]={}
    if execution_mode==MODE and 'P05' in selected_arms:
        spec=root_lookup('P05')
        if family(spec):
            result[FIELD]['P05']=declaration(spec)
            need(type(result['arm_inputs']['P05']['new_factual_overlay']) is bool,'P05_RUNTIME18_EXISTING_EXPLICIT_INPUT_FLAG_REQUIRED')
            result['arm_inputs']['P05']['new_factual_overlay']=initial(spec)
    for name in source_names():
        pin=sha((HERE/name).read_bytes());need(name not in result['sources'] or result['sources'][name]==pin,'P05_RUNTIME18_NO_OLD_SOURCE_PIN_REPLACEMENT')
        result['sources'][name]=pin
    return result

def exact(path,raw):
    return origin.old_batch.exact(path,raw)

def preserve_origin(root,current,out):
    from full_system_core import hosted
    hosted()
    root,out=Path(root),Path(out);raw=(root/origin.MANIFEST).read_bytes()
    result=origin.origin(json.loads(raw),current,lambda n:(root/n).read_bytes())
    for name,value in result['resources'].items():exact(out/name,value)
    exact(out/origin.MANIFEST,raw)
    return result

def copy_provider_from_preflight(out):
    out=Path(out)
    for name in ('provider-source/SHARADAR_ACTIONS.zip','P05-retained18-provider-stage.json'):
        exact(out/name,(out/'parent-preflight'/name).read_bytes())
    origin.data.validate_provider(out/'provider-source/SHARADAR_ACTIONS.zip')

def record_origin(out,parent,spec,neutral):
    from full_system_core import hosted
    hosted()
    out=Path(out)
    parent_raw=(out/'book/predecessor-checkpoints'/(parent['sha256']+'.json.gz')).read_bytes()
    need(dict(bytes=len(parent_raw),sha256=sha(parent_raw))==spec['selected_file'],'P05_RUNTIME18_REAL_RETAINED_ORIGINAL_PARENT_BYTES')
    exact(out/origin.PARENT,parent_raw)
    exact(out/origin.NEUTRAL,(out/'input-adoption/checkpoint.json.gz').read_bytes())
    exact(out/origin.ADOPTION_PROOF,(out/'input-adoption/proof.json').read_bytes())
    resources={n:dict(bytes=(out/n).stat().st_size,sha256=sha((out/n).read_bytes())) for n in origin.required_resources()}
    value=dict(schema='research.P05-own1175-retained18-actual-neutral-origin/1',passed=True,
        origin_root_admission_sha256=origin.data.own.ROOT,origin_parent_is_financial_seed=False,
        financial_state_unchanged=True,canonical_financial_source_changed=False,financial_sessions_advanced=0,
        parent_outer_sha256=parent['sha256'],neutral_outer_sha256=neutral['sha256'],descriptor=deepcopy(neutral['repairs'][-1]),resources=resources)
    origin.origin(value,neutral,lambda n:(out/n).read_bytes())
    exact(out/origin.MANIFEST,encoded(value))
    return value

def code_shape(code):
    return (code.co_code,code.co_argcount,code.co_posonlyargcount,code.co_kwonlyargcount,code.co_flags,
        code.co_names,code.co_varnames,code.co_freevars,code.co_cellvars,
        tuple(code_shape(v) if isinstance(v,CodeType) else v for v in code.co_consts))

def original_gate(Original,module_path):
    tree=ast.parse(Path(module_path).read_bytes())
    cls,=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AdoptionGate']
    need(sha(ast.dump(cls,include_attributes=False).encode())==GATE_AST,'P05_RUNTIME18_WHOLE_ORIGINAL_ADOPTION_GATE_AST')
    namespace={}
    exec(compile(ast.Module(body=[cls],type_ignores=[]),'<whole-original-gate-source-method-identity>','exec',dont_inherit=True),namespace)
    original=namespace['AdoptionGate']
    need(all(code_shape(getattr(Original,n).__code__)==code_shape(getattr(original,n).__code__)
        for n in ('__init__','write','advance','__enter__','__exit__')),'P05_RUNTIME18_ALL_FIVE_REAL_ORIGINAL_GATE_METHOD_CODE_SHAPES')
    return Original

def gate_class(Original,out,parent,spec,*,module_path=None):
    original_gate(Original,Path(module_path) if module_path is not None else HERE/'system_campaign_financial_resume.py')
    class Gate(Original):
        def write(self,path,saved):
            before=self.accepted
            result=super().write(path,saved)
            if not before and self.accepted:record_origin(out,parent,spec,saved)
            return result
    need(Gate.advance is Original.advance and Gate.__enter__ is Original.__enter__ and Gate.__exit__ is Original.__exit__,
        'P05_RUNTIME18_WHOLE_ORIGINAL_GATE_ADVANCE_AND_CONTEXT_METHODS')
    return Gate

@contextmanager
def old_entry(module,spec,request):
    old=origin.old_batch.entry_context.__wrapped__
    need(sha(Path(origin.old_batch.__file__).read_bytes())==origin.BATCH_SHA and old.__closure__ is None,
        'P05_RUNTIME18_ENTIRE_OLD_BATCH_ENTRY_SOURCE_AND_NO_HIDDEN_CLOSURE')
    def entry_need(value,label):
        if label=='P05_BATCH_FINANCIAL_ENTRY_INITIAL_OWN1152_ONLY_FUTURE_GENERATION_UNQUALIFIED':
            return need(value or selected(spec,request),label)
        return need(value,label)
    bound=FunctionType(old.__code__,dict(old.__globals__,need=entry_need),old.__name__,old.__defaults__)
    bound.__kwdefaults__=old.__kwdefaults__
    need(bound.__code__ is old.__code__,'P05_RUNTIME18_WHOLE_ORIGINAL_BATCH_ENTRY_CODE_OBJECT')
    with contextmanager(bound)(module,spec):yield

def review_observations(evidence,out,spec,current):
    from full_system_core import hosted
    hosted()
    evidence,out=Path(evidence),Path(out)
    value=origin.origin(json.loads((evidence/origin.MANIFEST).read_bytes()),current,lambda n:(evidence/n).read_bytes())
    plan,=prior.selected(current,spec);_,_,old=prior.checked_resources(evidence,current,plan)
    inventory=origin.inventory_function()(current,plan,
        {p.relative_to(evidence).as_posix() for p in evidence.rglob('*') if p.is_file()},lambda n:(evidence/n).read_bytes())
    terms=cash.union_terms(old,inventory['terms'],value['material']['terms'])
    need(len(terms)==112,'P05_RUNTIME18_ALL94_OLD_PLUS18_NEW_OBSERVATION_TERMS')
    from system_campaign_uncertainty_review import committed_rows
    observed={day:json.loads(raw) for day,raw in prior.committed_logs(evidence,current,plan).items()}
    need(sha((Path('/variant')/observer.stock.TERMINAL_SOURCE).read_bytes())==observer.stock.TERMINAL_SHA,
        'P05_RUNTIME18_ORIGINAL_PHYSICAL_TERMINAL_SOURCE_UNCHANGED')
    result=observer.review_data(current,committed_rows(evidence/'book',current,'daily'),observed,terms,value['scopes'])
    exact(out/'P05-retained18-observation-review.json',encoded(result))
    return result

@contextmanager
def entry_context(module,spec,*,request,mode,out,evidence=None):
    from full_system_core import hosted
    hosted()
    need(selected(spec,request) and mode in ('preflight','economic','review'),'P05_RUNTIME18_EXACT_DECLARED_WORKER_ENTRY')
    out=Path(out);saved=[];prepared=[None];expected_scopes=[None]
    def patch(owner,name,value):saved.append((owner,name,getattr(owner,name)));setattr(owner,name,value)
    with old_entry(module,spec,request):
        try:
            patch(origin.old_materials,'inventory',origin.inventory_function())
            original_inputs=module.financial_inputs
            @contextmanager
            def financial_inputs(root,current,target_out,target_spec):
                if not initial(target_spec):preserve_origin(root,current,target_out)
                with original_inputs(root,current,target_out,target_spec):yield
            patch(module,'financial_inputs',financial_inputs)
            original_preflight=module.preflight
            def preflight(root,target_out,target_spec):
                result=original_preflight(root,target_out,target_spec)
                if initial(target_spec):
                    preparation.prepare_after_preflight(root,target_out,target_spec)
                return result
            patch(module,'preflight',preflight)
            original_parent=pending.for_parent
            def for_parent(current,arm):
                if arm=='P05' and current['sha256']==origin.data.own.OUTER:return origin.api_module.api(current,provider_root=out)
                return original_parent(current,arm)
            patch(pending,'for_parent',for_parent)
            def qualified_overlay(current,target_out,target_spec):
                target_out=Path(target_out)
                if initial(target_spec):
                    copy_provider_from_preflight(target_out)
                    api=origin.api_module.api(current,provider_root=target_out)
                    path,loaded=api.prepare(current,target_out,'P05')
                    material=json.loads((target_out/origin.api_module.original.hydration_name(current)).read_bytes())
                    expected_scopes[0]=api.source_scopes(current,material,sha(path.read_bytes()),
                        sha((target_out/origin.api_module.original.hydration_name(current)).read_bytes()))
                    Gate=gate_class(module.AdoptionGate,target_out,current,target_spec)
                    return ['--repair-overlay',str(path)],Gate(current,target_out/'book',target_out/'input-adoption',loaded.sha256,loaded.earliest_affected_session)
                value=preserve_origin(Path('/old'),current,target_out);prepared[0]=value;expected_scopes[0]=value['scopes']
                return [],nullcontext()
            patch(module,'qualified_overlay',qualified_overlay)
            original_initializer=cash.observer_initializer
            def initialize(constructor,current,arm):
                if initial(spec):return original_initializer(constructor,current,arm)
                need(prepared[0] is not None and arm=='P05' and current['repairs']==spec['repairs']
                    and current['sha256']==spec['outer_sha256'],'P05_RUNTIME18_OBSERVER_USES_REAL_CURRENT20_FINANCIAL_PARENT')
                parent=prepared[0]['parent'];api=origin.api_module.api(parent,provider_root=out)
                need(constructor.__code__ is pending.ORIGINAL_OBSERVER_INITIALIZER.__code__ and constructor.__closure__ is None,
                    'P05_RUNTIME18_RETAINED_WHOLE_ORIGINAL_OBSERVER_CONSTRUCTOR')
                bound=FunctionType(constructor.__code__,dict(constructor.__globals__,source_scopes=api.source_scopes),constructor.__name__,constructor.__defaults__)
                bound.__kwdefaults__=constructor.__kwdefaults__
                def construct(event,target,target_arm,*,cp=None):
                    need(cp is current and Path(target)==out and target_arm==arm,'P05_RUNTIME18_RETAINED_CONSTRUCTOR_METADATA_ONLY_EXACT_CURRENT_CONTEXT')
                    return bound(event,target,target_arm,cp=parent)
                return construct
            patch(cash,'observer_initializer',initialize)
            def allowed(event):
                need(expected_scopes[0] is not None,'P05_RUNTIME18_SCOPE_ONLY_AFTER_REAL_INPUT_PREPARATION')
                return observer.exact_scope(event,expected_scopes[0])
            patch(prior,'merge_terms',observer.merge_function(allowed))
            original_adoption=module.review_adoption
            def review_adoption(target,parent,target_spec):
                if initial(target_spec):original_adoption(target,parent,target_spec)
                current=origin.actual_json((Path(target)/'book/checkpoint.json.gz').read_bytes())
                value=origin.origin(json.loads((Path(target)/origin.MANIFEST).read_bytes()),current,lambda n:(Path(target)/n).read_bytes())
                need(origin.api_module.api(value['parent'],provider_root=Path(target)).review_input(value['parent'],Path(target),'P05')=='2022-09-29',
                    'P05_RUNTIME18_WHOLE_ORIGINAL_INDEPENDENT_RETAINED_INPUT_RECONSTRUCTION')
            patch(module,'review_adoption',review_adoption)
            original_review=cash.review
            patch(cash,'review',lambda target,target_out,target_spec,current:review_observations(target,target_out,target_spec,current)
                if family(target_spec) and len(current['repairs'])==20 else original_review(target,target_out,target_spec,current))
            original_needed=module.factual_overlay_needed
            patch(module,'factual_overlay_needed',lambda target:initial(target) if family(target) else original_needed(target))
            yield
        finally:
            for owner,name,value in reversed(saved):setattr(owner,name,value)

@contextmanager
def launch_context(module,request,*,arm):
    from probe import check_context
    check_context(os.environ);spec=module.root_spec(arm)
    need(selected(spec,request) and arm=='P05','P05_RUNTIME18_EXACT_SELECTED_HOST_LAUNCH')
    original=module.stopped_run
    def stopped(values,name,output,*a,**k):
        if '/driver/system_campaign_financial_resume.py' in values and values[values.index('--mode')+1]=='preflight':
            old=preparation.preflight_worker_old(values,name,output,run_id=os.environ['GITHUB_RUN_ID'],runner_temp=os.environ['RUNNER_TEMP'])
            if initial(spec):preparation.stage_provider(spec,old,Path(output))
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
