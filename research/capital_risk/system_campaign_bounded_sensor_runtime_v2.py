"""Hosted P03 typed adoption, original retained run, and independent suffix review."""
import ast
from contextlib import contextmanager,nullcontext
from copy import deepcopy
import gzip,json
from pathlib import Path

import system_campaign_financial_uncertainty as legacy
from system_campaign_bounded_sensor_input import InputCodec,need,sha,digest
from system_campaign_bounded_sensor_catalog import encoded
from system_campaign_bounded_sensor_lifecycle_data import DOCUMENT,SOURCE,DIRECTORY,evidence,validate_document,document
from system_campaign_bounded_sensor_origin_v2 import exact
import system_campaign_bounded_sensor_origin_v2 as origins
import system_campaign_bounded_sensor_full_models_v2 as models
import system_campaign_bounded_sensor_observers_v2 as observations

HERE=Path(__file__).parent
CATALOG='P03-own462-DOVA-source-bound-input-catalog-v1.json'
CATALOG_SHA='a74c1f8c928be7b0dca35ee2c51aee803509c84024378bf2897a862a67b3d2a7'
INITIAL='2dfc5b30f486d40f97ab4f93c21ae75862714f0d0b410bd56228b137370329d0'
LEGACY_SHA='3ec636f898e9c3918047da18150660be37fd08f680818ec93064dfa355a1f6a8'

def catalog():
    raw=(HERE/CATALOG).read_bytes();need(sha(raw)==CATALOG_SHA,'BOUNDED_RUNTIME_EXACT_QUALIFIED_CATALOG');return json.loads(raw)

def metadata():
    from system_campaign_financial_partial import root_spec
    from system_campaign_bounded_sensor_observer_data import records
    plan,_=records();return dict(root_spec('P03',INITIAL),bounded_input_resource_pins=plan['original_resource_pins'])

def initial(spec):
    return isinstance(spec,dict) and spec.get('arm')=='P03' and spec.get('root_admission_sha256')==INITIAL

def selected(spec):
    if not isinstance(spec,dict) or spec.get('arm')!='P03':return False
    if initial(spec):return True
    value=catalog();repairs=spec.get('repairs',[])
    return (len(repairs)>=16 and repairs[:15]==value['parent_descriptors']
        and repairs[15]==dict(filename=models.TYPED_SHA+'.json',sha256=models.TYPED_SHA,
            resume_session=value['parent_cursor'],predecessor_checkpoint_sha256=value['parent_inner_sha256']))

def declaration(spec):
    need(selected(spec),'BOUNDED_RUNTIME_ONLY_EXACT_SELECTED_INPUT_FAMILY')
    return dict(schema='research.bounded-contingent-runtime-declaration/2',arm='P03',
        initial_root_admission_sha256=INITIAL,root_admission_sha256=spec.get('root_admission_sha256'),
        catalog_sha256=CATALOG_SHA,typed_document_sha256=models.TYPED_SHA,
        original_B19_model_retained=True,complete_input_history_required=True,
        representative_is_not_a_valuation=True,owned_or_ordered_right_valuation_authorized=False)

def report_declaration(request,arm):
    declared=request.get('selected_bounded_models',{}).get(arm)
    if declared is None:return None
    from system_campaign_financial_partial import root_spec
    need(arm=='P03' and request['execution_mode']=='OWN_ADMITTED_FINANCIAL_CONTINUATION'
         and request['financial_resume_authorized'] is True and request['financial_source_changed'] is False,
         'BOUNDED_RUNTIME_REPORT_ONLY_EXACT_ORIGINAL_FINANCIAL_DECLARATION')
    seed=root_spec(arm,declared['root_admission_sha256'])
    need(declared==declaration(seed) and request['admitted_checkpoints'][arm]==seed['outer_sha256']
         and request['sources']['system_campaign_bounded_sensor_runtime_v2.py']==sha(Path(__file__).read_bytes()),
         'BOUNDED_RUNTIME_REPORT_EXACT_ORIGINAL_SEED_SOURCE_AND_MODEL')
    return dict(retained_uncertainty_model='research.leadership-branch-uncertainty-input/1')

def validate_request_spec(spec):
    """Use actual admitted metadata; no checkpoint or retained phase is invented."""
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec)
    need(selected(spec) and spec['base']==metadata()['base']
         and spec['input_sha256']==digest(dict(base=spec['base'],repairs=spec['repairs'])),
         'BOUNDED_RUNTIME_REQUEST_ACTUAL_ADMITTED_FULL_INPUT_COMMITMENT')
    if initial(spec):
        need(spec['repairs']==catalog()['parent_descriptors'],'BOUNDED_RUNTIME_REQUEST_EXACT_INITIAL15')
    else:
        proof=spec['root_admission']['branch_uncertainty_proof'];phase=retained_phase(spec)
        need(type(proof['rows']) is type(proof.get('retained_rows',0)) is int
             and proof['rows']>0 and proof.get('retained_rows',0)>=0 and phase['rows']>0
             and proof['all_comparisons_and_state_sets_verified'] is proof['all_math_watch_financial_chains_verified'] is True,
             'BOUNDED_RUNTIME_REQUEST_ACTUAL_ADMITTED_PROOF_COUNTS_AND_COMPLETENESS')
    return declaration(spec)

@contextmanager
def request_context(module):
    """Run the whole existing request generator with exact family routing."""
    original=module.expected_request
    def expected_request():
        from system_campaign_financial_partial import root_spec
        financial=module.EXECUTION_MODE=='OWN_ADMITTED_FINANCIAL_CONTINUATION'
        specs={arm:root_spec(arm) for arm in module.SELECTED_ARMS}
        bounded={arm:validate_request_spec(spec) for arm,spec in specs.items() if financial and selected(spec)}
        old_policy,old_unchanged=legacy.own_policy_phase,legacy.own_unchanged_input_phase
        def policy(target):
            if selected(target) and not initial(target):validate_request_spec(target);return None
            return old_policy(target)
        def unchanged(target):
            if selected(target):validate_request_spec(target);return not initial(target)
            return old_unchanged(target)
        try:
            legacy.own_policy_phase,legacy.own_unchanged_input_phase=policy,unchanged
            result=original()
        finally:
            legacy.own_policy_phase,legacy.own_unchanged_input_phase=old_policy,old_unchanged
        need(result['financial_resume_authorized'] is financial and result['financial_source_changed'] is False
             and all(result['admitted_checkpoints'][a]==specs[a]['outer_sha256'] for a in bounded)
             and ('selected_bounded_models' not in result or result['selected_bounded_models']==bounded),
             'BOUNDED_RUNTIME_WHOLE_ORIGINAL_REQUEST_AUTHORITY_AND_SELECTED_SEEDS')
        sources=dict(result['sources'])
        for name in source_names():
            pin=sha((HERE/name).read_bytes())
            need(name not in sources or sources[name]==pin,'BOUNDED_RUNTIME_REQUEST_NO_REPLACED_SOURCE_PIN')
            sources[name]=pin
        return dict(result,sources=sources,selected_bounded_models=bounded)
    module.expected_request=expected_request
    try:yield
    finally:module.expected_request=original

def reporting_contract(root,cp,spec):
    if 'root_admission' in spec:return validate_request_spec(spec)
    raw=(Path(root)/'request.json').read_bytes();request=json.loads(raw)
    need(sha(raw)==spec['request_sha256'],'BOUNDED_RUNTIME_REPORT_ORIGINAL_REQUEST_BYTES')
    declared=report_declaration(request,spec['arm'])
    need(declared is not None and spec.get('retained_uncertainty_model')==declared['retained_uncertainty_model']
         and spec['monthly_seed_root_admission_sha256']==request['selected_bounded_models'][spec['arm']]['root_admission_sha256']
         and cp['sha256']==spec['outer_sha256'] and cp['completed']==spec['measured_closes']
         and cp['source_cursor']==spec['selected_session'] and cp['repairs']==spec['repairs']
         and cp['run']['input_sha256']==spec['input_sha256'],
         'BOUNDED_RUNTIME_REPORT_EXACT_CAPTURED_PREFIX_SEED_CLOCK_AND_MODEL')
    return declared

def source_names():
    return (CATALOG,'system_campaign_bounded_sensor_adoption.py','system_campaign_bounded_sensor_observer_data.py',
        'P03-own462-DOVA-full-lifecycle-plan.json','P03-own462-inherited-observer-inventory.json',
        'system_campaign_bounded_sensor_seed_binding.py','system_campaign_bounded_sensor_origin_v2.py',
        'system_campaign_bounded_sensor_full_models_v2.py','system_campaign_bounded_sensor_observers_v2.py',
        'system_campaign_bounded_sensor_suffix_v2.py','system_campaign_bounded_sensor_runtime_v2.py')

def typed(root):return validate_document(Path(root)/DOCUMENT,catalog(),root_lookup=lambda arm,pin:metadata())

def full_models(root,cp):return models.validate_full(root,cp,catalog(),evidence(catalog()),root_metadata=metadata())

def retained_contract(cp,spec,root):
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec)
    need(selected(spec) and not initial(spec) and cp['sha256']==spec['outer_sha256']
         and cp['completed']==spec['measured_closes'] and cp['source_cursor']==spec['selected_session']
         and cp['repairs']==spec['repairs'] and cp['base']==metadata()['base']
         and spec.get('retained_uncertainty_model')=='research.leadership-branch-uncertainty-input/1',
         'BOUNDED_RUNTIME_ACTUAL_ADMITTED_RETAINED_ROOT_FULL_IDENTITY')
    full_models(root,cp);origins.load(root,cp,catalog(),typed(root),metadata())
    from system_campaign_bounded_sensor_semantics import verify
    verify(catalog())
    hashes=json.loads((HERE/legacy.INTEGRATION).read_bytes())['canonical_controller_sources']
    need(len(hashes)==6 and all(cp['base']['sources'].get(n)==h for n,h in hashes.items()),
         'BOUNDED_RUNTIME_UNCHANGED_SIX_CANONICAL_CONTROLLER_SOURCES')
    return hashes

def retained_phase(spec):
    proof=spec['root_admission']['branch_uncertainty_proof']
    need(selected(spec) and not initial(spec) and proof['passed'] is True,
         'BOUNDED_RUNTIME_COUNTS_FROM_ACTUAL_ADMITTED_BRANCH_PROOF_ONLY')
    return dict(rows=proof['rows']+proof.get('retained_rows',0),new_rows=proof['rows'],retained_rows=proof.get('retained_rows',0))

def seed(root,cp,spec):
    from full_system_core import hosted
    hosted()
    if initial(spec):return legacy.retained_seed(Path(root),cp,spec)
    from system_campaign_bounded_sensor_seed_binding import bind_seed
    fn=bind_seed(validate_input=lambda where,current:full_models(where,current),
        retained_contract=lambda current,target:retained_contract(current,target,root),retained_phase=retained_phase)
    return fn(Path(root),cp,spec)

def body_tree(name):
    raw=Path(legacy.__file__).read_bytes();need(sha(raw)==LEGACY_SHA,'BOUNDED_RUNTIME_ENTIRE_ORIGINAL_RETAINED_SOURCE')
    fn=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name)
    required={'run_retained':{'system_campaign_financial_branches':['Certificate'],
                              'system_campaign_uncertainty_archive':['preserve']},
              'review_retained':{'system_campaign_financial_branches':['validate_input']}}[name]
    for module,names in required.items():
        imports=[n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module==module]
        need(len(imports)==1 and all(any(a.name==v and a.asname is None for a in imports[0].names) for v in names),
             'BOUNDED_RUNTIME_EXACT_DECLARED_IMPORT_BINDINGS')
        statement=imports[0];statement.names=[a for a in statement.names if a.name not in names]
        if not statement.names:fn.body.remove(statement)
    return ast.fix_missing_locations(fn)

def bound_body(name,bindings):
    allowed={'run_retained':{'Certificate','preserve','retained_seed','active_codec','unchanged_input_phase','own_unchanged_input_phase','unchanged_input_receipt'},
             'review_retained':{'validate_input','retained_seed','own_unchanged_input_phase','unchanged_input_phase','review_unchanged_input','review_new_rows'}}
    need(set(bindings)==allowed[name] and all(callable(v) for v in bindings.values()),
         'BOUNDED_RUNTIME_ONLY_COMPLETE_EXPLICIT_BINDING_SET')
    fn=body_tree(name);namespace=dict(vars(legacy),**bindings)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-original-'+name+'-bounded-input-bindings>','exec'),namespace)
    return namespace[name]

def receipt(cp,spec):
    need(selected(spec),'BOUNDED_RUNTIME_EXACT_INPUT_STAGE_SCOPE')
    return dict(schema='research.bounded-input-post-adoption-stage/1',parent_outer_sha256=cp['sha256'],
        financial_seed_root_admission_sha256=spec['root_admission_sha256'],input_sha256=cp['run']['input_sha256'],
        repairs=deepcopy(cp['repairs']),completed=cp['completed'],source_cursor=cp['source_cursor'],
        no_further_input_adoption_in_run_segment=True,financial_source_changed=False)

def run(cp,out,args,rows,observer,execution,*,spec,old):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    from system_campaign_bounded_sensor_hydration import hydrate
    from system_campaign_bounded_sensor_binding import certificate_class
    from system_campaign_uncertainty_archive import preserve as original_preserve
    need(selected(spec) and 'root_admission' in spec,'BOUNDED_RUNTIME_ONLY_ACTUAL_ADMITTED_FINANCIAL_ENTRY')
    value=catalog();old,out=Path(old),Path(out);hashes,prior,qualified=seed(old,cp,spec)
    from system_campaign_financial_projection import branch_loader_owner
    owner=getattr(backtest.load_repair,'__self__',None)
    installed=isinstance(owner,InputCodec)
    branch_codec=branch_loader_owner(owner.original_load if installed else backtest.load_repair)
    need(branch_codec is not None,'BOUNDED_RUNTIME_ORIGINAL_ACTIVE_BRANCH_CODEC')
    native,source=hydrate(value,out/SOURCE);exact(out/DOCUMENT,encoded(document(value,root_lookup=lambda arm,pin:metadata())))
    obj=typed(out)
    if installed:
        need(owner.event==value['event'] and owner.evidence==evidence(value),'BOUNDED_RUNTIME_SAME_RETAINED_TYPED_CODEC')
    with (nullcontext(owner) if installed else InputCodec(value['event'],evidence(value),native)) as codec:
        if initial(spec):
            from system_campaign_bounded_sensor_adoption import adopt
            from system_campaign_bounded_sensor_preparation import qualify_packets
            loaded=backtest.load_repair(out/DOCUMENT,resume_session=cp['source_cursor'],
                predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
            packet=qualify_packets(cp,out/DOCUMENT,loaded,codec,native,value,out)
            exact(out/'bounded-runtime-input-qualification.json',encoded(dict(passed=True,packet=packet,
                typed_document_sha256=obj.sha256,market_source_sha256=sha((out/SOURCE).read_bytes()),financial_sessions_advanced=0)))
            current=adopt(cp,out,args,rows,value,codec)
            observation_files=observations.stage_initial(old,cp,out)
        else:
            current=cp;full_models(old,current);origins.preserve(old,current,out,value,obj,metadata())
            observations.stage_retained(old,current,out);observation_files=[]
        full_models(out,current)
        Certificate=certificate_class(value['event'],source,codec,native,inherited_root=HERE)
        def checked_seed(where,actual,target):
            need(where==old and target==spec and actual==current,'BOUNDED_RUNTIME_EXACT_ACTUAL_POST_ADOPTION_RUN_PARENT')
            full_models(out,actual)
            return hashes,prior,qualified
        def active(backtest_module,where,actual):
            need(backtest_module is backtest and where==old and actual==current
                 and getattr(backtest.load_repair,'__self__',None) is codec
                 and getattr(codec.original_load,'__self__',None) is branch_codec,
                 'BOUNDED_RUNTIME_FULL_INSTALLED_TYPED_AND_ORIGINAL_CODEC_CHAIN')
            return branch_codec
        def preserve(where,target):
            original_preserve(where,target)
            from system_campaign_bounded_sensor_suffix_v2 import preserve as preserve_event
            preserve_event(where,cp,target,value)
            if initial(spec):origins.create(old,out,cp,current,value,obj,spec,root_metadata=metadata(),extra_files=observation_files)
            else:origins.load(out,current,value,obj,metadata())
        fn=bound_body('run_retained',dict(Certificate=Certificate,preserve=preserve,retained_seed=checked_seed,active_codec=active,
            unchanged_input_phase=selected,own_unchanged_input_phase=lambda target:False,unchanged_input_receipt=receipt))
        with observations.observer(out,current):code=fn(current,out,args,observer,execution,spec,old)
        actual=journal.read_checkpoint(out/'book/checkpoint.json.gz');full_models(out,actual)
        need(actual['repairs']==current['repairs'] and actual['run']['input_sha256']==current['run']['input_sha256'],
             'BOUNDED_RUNTIME_FINANCIAL_SEGMENT_FULL_INPUT_IDENTITY_UNCHANGED')
        return code

def review(parent,evidence_root,out,*,spec,old):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import journal
    from system_campaign_bounded_sensor_hydration import hydrate
    from system_campaign_bounded_sensor_suffix_v2 import suffix
    from system_campaign_uncertainty_math import growth
    need(selected(spec),'BOUNDED_RUNTIME_EXACT_INDEPENDENT_REVIEW_FAMILY')
    evidence_root,out,old=Path(evidence_root),Path(out),Path(old);value=catalog();current=journal.read_checkpoint(evidence_root/'book/checkpoint.json.gz')
    hydrate(value,evidence_root/SOURCE);obj=typed(evidence_root)
    origin,original_parent,neutral=origins.load(evidence_root,current,value,obj,metadata())
    need(not initial(spec) or original_parent==parent,'BOUNDED_RUNTIME_REVIEW_EXACT_ORIGINAL_FINANCIAL_PARENT')
    def unchanged(original,current,where,target):
        begin=neutral if initial(spec) else original
        need(original==parent and target==spec and where==evidence_root
             and (where/legacy.UNCHANGED_INPUT).read_bytes()==encoded(receipt(begin,target))
             and current['base']==begin['base'] and current['repairs']==begin['repairs']
             and current['run']['input_sha256']==begin['run']['input_sha256']
             and not (where/legacy.MODEL_ADOPTION).exists(), 'BOUNDED_RUNTIME_REVIEW_ACTUAL_NEUTRAL_THEN_UNCHANGED_SEGMENT')
    def new_rows(before,after,retained,rows,financial,**canonical):
        return suffix(evidence_root,before,after,retained,rows,financial,value,growth=growth)
    fn=bound_body('review_retained',dict(validate_input=lambda where,actual:full_models(where,actual),
        retained_seed=seed,own_unchanged_input_phase=lambda target:False,unchanged_input_phase=selected,
        review_unchanged_input=unchanged,review_new_rows=new_rows))
    fn(parent,evidence_root,out,spec,old);observations.review(evidence_root,current,out)

@contextmanager
def review_codecs(root,spec):
    """Keep original and typed codecs across the complete unchanged m.review."""
    from full_system_core import hosted
    hosted()
    import system_campaign_financial_partial as partial
    root=Path(root);current=origins.strict_json((root/'book/checkpoint.json.gz').read_bytes())
    need(selected(spec) and len(current['repairs'])>=16,'BOUNDED_RUNTIME_REVIEW_ACTUAL_FULL_TYPED_EVIDENCE')
    with partial.model_context(root,current,spec):
        full_models(root,current);origins.load(root,current,catalog(),typed(root),metadata())
        yield current

@contextmanager
def entry_context(module,spec):
    """Use around existing worker entry functions; their four bodies stay intact."""
    if not selected(spec):yield;return
    import system_campaign_financial_partial as partial
    saved=[]
    def patch(owner,name,fn):saved.append((owner,name,getattr(owner,name)));setattr(owner,name,fn)
    old_run,old_review,old_phase=legacy.run,legacy.review,legacy.uncertainty_phase
    old_models,old_context=partial.retained_models,partial.model_context
    old_inputs=module.financial_inputs
    old_worker_review,old_overlay=module.review,module.factual_overlay_needed
    patch(legacy,'uncertainty_phase',lambda target:selected(target) or old_phase(target))
    patch(legacy,'run',lambda *a,**k:run(*a,**k) if selected(k.get('spec')) else old_run(*a,**k))
    patch(legacy,'review',lambda *a,**k:review(*a,**k) if selected(k.get('spec')) else old_review(*a,**k))
    def retained_models(root,parent,target):
        if not selected(target) or len(parent['repairs'])==15:return old_models(root,parent,target)
        reporting_contract(root,parent,target)
        full_models(root,parent);origins.load(root,parent,catalog(),typed(root),metadata());return True
    patch(partial,'retained_models',retained_models)
    @contextmanager
    def model_context(root,parent,target):
        if selected(target) and len(parent['repairs'])>=16:reporting_contract(root,parent,target)
        with old_context(root,parent,target):
            if not selected(target) or len(parent['repairs'])==15:yield;return
            from system_campaign_bounded_sensor_hydration import hydrate
            native,_=hydrate(catalog(),Path(root)/SOURCE)
            with InputCodec(catalog()['event'],evidence(catalog()),native):yield
    patch(partial,'model_context',model_context)
    @contextmanager
    def financial_inputs(root,parent,out,target):
        if selected(target) and len(parent['repairs'])>=16:
            origins.preserve(root,parent,out,catalog(),typed(root),metadata());observations.stage_retained(root,parent,out)
        with old_inputs(root,parent,out,target):yield
    patch(module,'financial_inputs',financial_inputs)
    def worker_review(evidence,out,target):
        if not selected(target):return old_worker_review(evidence,out,target)
        with review_codecs(evidence,target):return old_worker_review(evidence,out,target)
    patch(module,'review',worker_review)
    patch(module,'factual_overlay_needed',lambda target:initial(target) if selected(target) else old_overlay(target))
    try:yield
    finally:
        for owner,name,fn in reversed(saved):setattr(owner,name,fn)
