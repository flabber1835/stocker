"""Finite hosted actual1383/full10 -> genuine11, with130 committed proof rows."""
import ast,gzip,json,shutil,stat,tempfile
from contextlib import contextmanager,ExitStack
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import system_campaign_financial_uncertainty as legacy
import system_campaign_p06_abmd_retained as retained
import system_campaign_p06_abmd_lifecycle_data as initial
import system_campaign_p06_abmd_models as oldmodels
import system_campaign_p06_BBIG_data as data
import system_campaign_p06_BBIG_models as models
import system_campaign_p06_BBIG_api as api_module
import system_campaign_p06_BBIG_seed as seeds
import system_campaign_p06_BBIG_observer as observations
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
from system_campaign_pxd_pause import adoption

HERE=Path(__file__).parent
RETAINED_SHA='978c3106655cb45dd91f14967f4fe42962cf1a0f3eae42cb353fb6b0086c2ac4'
FIELD='selected_p06_BBIG_ordinary11_retained130'
MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION'
PROVENANCE='p06-BBIG-ordinary11-origin'
BOUNDARY='p06-BBIG-genuine-neutral11-boundary-review.json'
RECEIPT='p06-BBIG-ordinary11-adopted-input-receipt.json'
def candidate(spec):return isinstance(spec,dict) and spec.get('arm')=='P06' and spec.get('root_admission_sha256')==data.ROOT
def declaration(spec):
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec)
    data.need(candidate(spec) and (spec['outer_sha256'],spec['measured_closes'],spec['selected_session'],len(spec['repairs']))==
        (data.OUTER,1383,'2023-06-30',10),'P06_BBIG_FINITE_ACTUAL1383_FINANCIAL_ENTRY')
    data.catalog()
    return dict(schema='research.P06-BBIG-genuine11-retained130-declaration/1',arm='P06',root_admission_sha256=data.ROOT,
        selected_parent_outer_sha256=data.OUTER,actual_parent_inputs=10,actual_neutral_inputs_required=11,
        committed_seed_rows=130,committed_seed_sha256=seeds.PREFIX['sha256'],catalog_file=data.CATALOG,catalog_sha256=data.CATALOG_SHA,
        source_DATA_qualification_sha256=data.QUALIFICATION_SHA,financial_source_changed=False,
        genuine_neutral_adoption_required=True,actual_neutral_checkpoint_known=False,
        never_held_source_exit_only=True,held_settlement_authorized=False,future11_root_restart_selected=False)
def selected(spec,request):
    return candidate(spec) and request.get('execution_mode')==MODE and request.get('financial_resume_authorized') is True \
        and request.get('readonly_partial_review') is request.get('readonly_source_witnesses') is False \
        and request.get(FIELD,{}).get('P06')==declaration(spec)
def expected_request(original,*,execution_mode,selected_arms,root_lookup):
    result=original();declared={}
    if execution_mode==MODE and 'P06' in selected_arms:
        spec=root_lookup('P06')
        data.need(candidate(spec) or len(spec.get('repairs',[]))<11,'P06_BBIG_FUTURE11_ROOT_RESTART_NEEDS_SEPARATE_QUALIFICATION')
        if candidate(spec):
            declared['P06']=declaration(spec)
            data.need(result['admitted_checkpoints']['P06']==data.OUTER,'P06_BBIG_REQUEST_SELECTS_REAL1383_PARENT10')
            result['arm_inputs']['P06']['new_factual_overlay']=True
    result[FIELD]=declared
    for name in source_names():
        pin=data.sha((HERE/name).read_bytes());data.need(name not in result['sources'] or result['sources'][name]==pin,'P06_BBIG_NO_REQUEST_SOURCE_REPLACEMENT')
        result['sources'][name]=pin
    return result
def source_names():return tuple(sorted(set((Path(__file__).name,*api_module.source_names(),*seeds.source_names(),*observations.source_names()))))
def adoption_tree(raw):
    data.need(data.sha(raw)==seeds.U_SHA,'P06_BBIG_WHOLE_ORIGINAL_CANONICAL_ADOPTION_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption']
    node,=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names']
    mapping=node.value
    data.need(isinstance(mapping,ast.Dict) and [ast.unparse(v) for v in mapping.keys]==['ORDINARY_ADOPTION','DATE_ADOPTION','MODEL_ADOPTION']
        and [ast.unparse(v) for v in mapping.values]==["'future-financial-overlay.json'",'DATE_OVERLAY',"'branch-uncertainty-input.json'"],
        'P06_BBIG_ONE_EXACT_ORIGINAL_ADOPTION_FILENAME_MAP')
    mapping.keys.append(ast.Constant(models.DIRECTORY));mapping.values.append(ast.Constant(models.OVERLAY))
    return ast.fix_missing_locations(fn)
def adopter():
    namespace=dict(vars(legacy));exec(compile(ast.Module(body=[adoption_tree(Path(legacy.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-canonical-adoption-one-BBIG-filename>','exec'),namespace);return namespace['paused_own_adoption']
def boundary_relation(parent,neutral,spec,member,rows):
    data.parent_contract(parent,spec);raw=member(models.OVERLAY);doc=json.loads(raw);term=data.catalog()['terms'][-1]
    data.need(doc['schema']=='terminal-repair/1' and doc['predecessor_checkpoint_sha256']==parent['run']['checkpoint_sha256']
        and doc['add']==[term['added']] and doc['suppress']==[dict(session='2023-07-27',security_id=data.SID,term_sha256=term['native_term_sha256'])]
        and len(doc['source_evidence'])<=128,'P06_BBIG_ONE_SOURCE_ONLY_ORDINARY_PATCH_AND_ORIGINAL_EVIDENCE_CAP')
    event=adoption(neutral,parent,data.sha(raw),'2023-07-27');neutral_raw=member(models.DIRECTORY+'/checkpoint.json.gz')
    data.need(strict_json(neutral_raw)==neutral and len(neutral['repairs'])==11 and neutral['repairs'][:10]==parent['repairs']
        and neutral['run']['state']==parent['run']['state'],'P06_BBIG_REAL_NEUTRAL11_GZIP_STATE_AND_FULL_HISTORY')
    proof=json.loads(member(models.DIRECTORY+'/proof.json'))
    data.need(proof==dict(event=event,actual_checkpoint_gzip_sha256=data.sha(neutral_raw),original_outer_sha256=parent['sha256'],
        financial_state_unchanged=True,financial_sessions_advanced=0)
        and gzip.decompress(member(models.DIRECTORY+'-correlation-inputs.jsonl.gz'))==b''.join(rows),
        'P06_BBIG_COMPLETE_ACTUAL_ZERO_SESSION_PROOF_AND_ZERO_NEW_CORRELATION')
    watch=member('book/watch.jsonl');a,b=parent['journals']['watch'],neutral['journals']['watch']
    data.need(data.sha(watch[:a['bytes']])==a['prefix_sha256'] and data.sha(watch[:b['bytes']])==b['prefix_sha256']
        and [json.loads(v) for v in watch[a['bytes']:b['bytes']].splitlines()]==[event],
        'P06_BBIG_ONLY_ACTUAL_ONE_CANONICAL_INPUT_SUCCESSOR_WATCH')
    q=json.loads(member(models.QUALIFICATION))
    data.need(q['passed'] is True and type(q['packet_checks']) is int and q['packet_checks']>0
        and q['only_terminal_field_changed'] is q['complete_terms_and_canonical_notional_verified']
        is q['original_incomplete_guard_retained'] is q['wrong_predecessor_and_consumed_date_refused']
        is q['wrong_native_and_delivery_witness_refused'] is True and type(q['financial_sessions_advanced']) is int
        and q['financial_sessions_advanced']==0,'P06_BBIG_ACTUAL_WHOLE_ORIGINAL_PACKET_QUALIFICATION')
    return dict(passed=True,parent10_sha256=parent['sha256'],actual_neutral11_sha256=neutral['sha256'],
        neutral_gzip_sha256=data.sha(neutral_raw),original_root_admission_sha256=data.ROOT,original_inputs=10,current_inputs=11,
        input_successor=event,financial_sessions_advanced=0,all_original_financial_state_journals_and_stats_unchanged=True,
        zero_new_correlation=True,source_exit_does_not_authorize_portfolio_settlement=True)
def boundary(root,parent,spec,rows):
    root=Path(root);neutral=strict_json((root/models.DIRECTORY/'checkpoint.json.gz').read_bytes())
    proof=boundary_relation(parent,neutral,spec,lambda n:(root/n).read_bytes(),rows)
    data.need(api_module.api(parent,spec).review_input(parent,root,'P06')=='2023-07-27','P06_BBIG_COMPLETE_SOURCE_DOCUMENT_SCOPE_REVIEW')
    data.need(models.full(root,neutral)['full_inputs']==11,'P06_BBIG_COMPLETE_GENUINE_8_9_10_11_VISITOR')
    return neutral,proof
def retained_tree(raw,name):
    data.need(data.sha(raw)==RETAINED_SHA,'P06_BBIG_ENTIRE_ORIGINAL_RETAINED_WORKER_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
    if name=='preserve':
        sites=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and type(n.value)is int and n.value==18]
        data.need(len(sites)==1,'P06_BBIG_ONE_ORIGINAL_FULL_PROOF_ROW_LABEL');sites[0].value=147
    elif name in ('run','review'):
        module='system_campaign_p06_abmd_point_continuation' if name=='run' else 'system_campaign_p06_abmd_retained_suffix'
        imp,=[n for n in ast.walk(fn) if isinstance(n,ast.ImportFrom) and n.module==module]
        data.need([(v.name,v.asname) for v in imp.names]==([('certificate_class',None)] if name=='run' else [('review','suffix')]),
            'P06_BBIG_ONE_EXACT_FACTORY_OR_SUFFIX_IMPORT')
        imp.module='system_campaign_p06_BBIG_seed'
        if name=='review':imp.names[0].name='suffix'
        sites=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and type(n.value)is int and n.value==6]
        data.need(len(sites)==(1 if name=='run' else 5),'P06_BBIG_EXACT_ORIGINAL_RETAINED_COUNT_SITES')
        for n in sites:n.value=130
    else:raise ValueError('P06_BBIG_UNDECLARED_RETAINED_FUNCTION')
    return ast.fix_missing_locations(fn)
def preserve(root,out,parent,rows,resolution):
    facade=SimpleNamespace(PROVENANCE=PROVENANCE,FULL_PROOF='old-full-uncertainty-certificate.jsonl',FULL_SHA=seeds.FULL['sha256'],encoded=data.encoded)
    namespace=dict(vars(retained),data=facade)
    exec(compile(ast.Module(body=[retained_tree(Path(retained.__file__).read_bytes(),'preserve')],type_ignores=[]),
        '<entire-original-preserve-actual147-provenance>','exec'),namespace)
    namespace['preserve'](root,out,parent,rows,resolution)
    for p in (Path(root)/retained.data.OBSERVATIONS).rglob('*'):
        if p.is_file():exact(Path(out)/PROVENANCE/'prior-ordinary-observation'/p.relative_to(Path(root)/retained.data.OBSERVATIONS),p.read_bytes())
def read_parent(root):return strict_json((Path(root)/models.PARENT).read_bytes())
def genuine_receipt(neutral,spec,root,rows):return boundary_relation(read_parent(root),neutral,spec,lambda n:(Path(root)/n).read_bytes(),rows)
def bind_retained(name,seed,request,financial_parent,rows):
    def receipt(current,spec):return genuine_receipt(current,spec,current_root[0],rows)
    # The binding is finite and each caller supplies its actual scope root explicitly.
    current_root=[None]
    facade=SimpleNamespace(selected=lambda spec,req:selected(spec,req),UNCHANGED=RECEIPT,receipt=receipt,
        PROVENANCE=PROVENANCE,FULL_PROOF='old-full-uncertainty-certificate.jsonl',encoded=data.encoded,OBSERVATIONS=observations.DIRECTORY)
    def review_adopted(neutral,current,evidence,spec):
        boundary(evidence,financial_parent,spec,rows)
        data.need(current['base']==neutral['base'] and current['repairs']==neutral['repairs']
            and current['run']['input_sha256']==neutral['run']['input_sha256']
            and json.loads((Path(evidence)/RECEIPT).read_bytes())==genuine_receipt(neutral,spec,evidence,rows),
            'P06_BBIG_RETAINED_FULL11_SEGMENT_AFTER_GENUINE_NEUTRAL_ADOPTION')
    facade.review_unchanged=review_adopted
    def prior_event(root,current,proof):return seeds.prior_event(root,current,proof,financial_parent)[1][0]
    def already_preserved(root,out,current,proof,resolution):
        data.need(len(proof)==130 and (Path(out)/PROVENANCE/'old-full-uncertainty-certificate.jsonl').read_bytes()==
            (Path(root)/'uncertainty-certificate.jsonl').read_bytes()
            and (Path(out)/resolution['actual']).read_bytes()==(Path(root)/resolution['actual']).read_bytes(),
            'P06_BBIG_WHOLE_PRESERVATION_ALREADY_COMPLETED_BEFORE_NEUTRAL_ADOPTION')
    namespace=dict(vars(retained),data=facade,seed=seed,full=models.full,preserve=already_preserved,prior_event=prior_event,
        ordinary_observer=lambda root,out,current:observations.observer(root,out,current,financial_parent,request_spec[0],api_module.api(financial_parent,request_spec[0])),
        review_cash=lambda neutral,current,evidence,out:observations.review(financial_parent,current,evidence,out))
    request_spec=[None]
    exec(compile(ast.Module(body=[retained_tree(Path(retained.__file__).read_bytes(),name)],type_ignores=[]),
        '<entire-original-retained-worker-finite130-import-binding>','exec'),namespace)
    whole=namespace[name]
    def bound(*args,**kwargs):
        current_root[0]=Path(args[1]);request_spec[0]=kwargs['spec']
        return whole(*args,**kwargs,request=request)
    return bound
def owned_view_permissions(view,owned,output):
    """Only the owned copy's directories and authentic copied watch gain writes."""
    view,owned,output=Path(view),Path(owned),Path(output)
    root,owner,parent=view.resolve(),owned.resolve(),output.resolve()
    data.need(not view.is_symlink() and not owned.is_symlink() and view.is_dir()
        and root==owner/'view' and owner.parent==parent and owner.name.startswith('p06-BBIG-real-neutral-seed-view-'),
        'P06_BBIG_PERMISSION_TARGET_ONLY_EXPLICIT_OWNED_OUTPUT_VIEW')
    members=[view,*view.rglob('*')]
    data.need(all(not p.is_symlink() and p.resolve().is_relative_to(root) for p in members),
        'P06_BBIG_ALL_PERMISSION_TARGETS_WITHIN_OWNED_VIEW_NO_SYMLINKS')
    directories=[p for p in members if p.is_dir()];watch=view/'book/watch.jsonl'
    data.need(watch.is_file() and not watch.is_symlink() and watch.resolve().is_relative_to(root),
        'P06_BBIG_ONLY_ACTUAL_COPIED_NEUTRAL_WATCH_FILE_WRITABLE')
    for p in directories:p.chmod(stat.S_IMODE(p.stat().st_mode)|stat.S_IWUSR|stat.S_IXUSR)
    watch.chmod(stat.S_IMODE(watch.stat().st_mode)|stat.S_IWUSR)
    return dict(owned_directories=len(directories),only_owner_write_search_added=True,
        only_copied_neutral_watch_file_write_added=True,original_source_permissions_changed=False)
@contextmanager
def seed_view(old,out,parent,neutral,spec,evidence,rows):
    from full_system_core import hosted
    hosted()
    import system_campaign_financial_future as future
    old,out,evidence=Path(old),Path(out),Path(evidence);original=(old/spec['selected_checkpoint']).read_bytes()
    data.need(dict(bytes=len(original),sha256=data.sha(original))==spec['selected_file'] and strict_json(original)==parent,
        'P06_BBIG_REAL_SELECTED_PARENT10_GZIP_NEVER_SUBSTITUTED')
    proof=boundary_relation(parent,neutral,spec,lambda n:(evidence/n).read_bytes(),rows)
    with tempfile.TemporaryDirectory(prefix='p06-BBIG-real-neutral-seed-view-',dir=out) as owned:
        view=Path(owned)/'view';shutil.copytree(old,view)
        permissions=owned_view_permissions(view,owned,out)
        files=[models.OVERLAY,models.QUALIFICATION,models.PARENT,data.CATALOG,data.SOURCE,data.FACT,
            models.DIRECTORY+'/checkpoint.json.gz',models.DIRECTORY+'/proof.json',models.DIRECTORY+'-correlation-inputs.jsonl.gz',
            future.hydration_name(parent),future.SOURCE_SCOPES,'book/repairs/'+neutral['repairs'][10]['filename']]
        inventory={}
        for n in files:
            raw=(evidence/n).read_bytes();exact(view/n,raw);inventory[n]=dict(bytes=len(raw),sha256=data.sha(raw))
        watch=(evidence/'book/watch.jsonl').read_bytes();committed=neutral['journals']['watch']
        data.need(data.sha(watch[:committed['bytes']])==committed['prefix_sha256'],'P06_BBIG_REAL_NEUTRAL_WATCH_COMMITMENT')
        (view/'book/watch.jsonl').write_bytes(watch[:committed['bytes']])
        data.need((view/spec['selected_checkpoint']).read_bytes()==original,'P06_BBIG_VIEW_ORIGINAL_FINANCIAL_SEED10_UNMODIFIED')
        exact(out/PROVENANCE/'temporary-seed-view-receipt.json',data.encoded(dict(passed=True,selected_parent10_file_sha256=data.sha(original),
            actual_neutral11_file_sha256=proof['neutral_gzip_sha256'],real_neutral_watch_sha256=data.sha(watch[:committed['bytes']]),
            neutral_committed_watch_bytes=committed['bytes'],actual_added_files=inventory,selected_checkpoint_replaced=False,
            owned_copy_permissions=permissions,
            financial_sessions_advanced=0,temporary_view_cleanup_on_scope_exit_required=True)))
        yield view
    data.need(not Path(owned).exists(),'P06_BBIG_OWNED_TEMPORARY_VIEW_REMOVAL_OBSERVED')
    exact(out/PROVENANCE/'temporary-seed-view-cleanup.json',data.encoded(dict(passed=True,temporary_owned_view_removal_observed=True,
        original_selected_and_genuine_neutral_archives_preserved=True,financial_sessions_advanced=0)))
def neutral_seed(old,view,parent,neutral,spec,evidence,rows,baseline):
    old,view,evidence=Path(old),Path(view),Path(evidence)
    def contract(current,target):
        data.need(current==neutral and target==spec,'P06_BBIG_SEED_BRIDGE_ONLY_GENUINE_NEUTRAL11_AND_ORIGINAL_SPEC10')
        boundary_relation(parent,current,target,lambda n:(evidence/n).read_bytes(),rows)
        return seeds.contract(parent,target,old)
    whole=seeds.bind_seed(contract=contract)
    def seed(root,current,target):
        data.need(Path(root)==view and current==neutral and target==spec,'P06_BBIG_ONLY_ACTUAL_INVENTORIED_SEED_VIEW')
        actual=whole(view,current,target)
        data.need(actual==baseline[:3] and len(actual[1])==130,'P06_BBIG_WHOLE_NEUTRAL11_SEED_EQUALS_INDEPENDENT_PARENT10_130')
        return (*actual,baseline[3])
    return seed
def run(parent,out,args,rows,observer,execution,*,spec,old,request):
    from full_system_core import hosted
    hosted()
    data.need(selected(spec,request),'P06_BBIG_EXPLICIT_FINANCIAL_DECLARATION')
    old,out=Path(old),Path(out);baseline=seeds.original_seed(old,parent,spec)
    preserve(old,out,parent,baseline[1],baseline[3])
    exact(out/models.PARENT,(old/spec['selected_checkpoint']).read_bytes())
    for n in (data.CATALOG,data.SOURCE,data.FACT):exact(out/n,(HERE/n).read_bytes())
    api=api_module.api(parent,spec);path,loaded=api.prepare(parent,out,'P06')
    data.need(path==out/models.OVERLAY and loaded.earliest_affected_session=='2023-07-27','P06_BBIG_REAL_PREPARED_UNCONSUMED_ELEVENTH_INPUT')
    neutral=adopter()(parent,out,args,rows,path,loaded.earliest_affected_session,models.DIRECTORY)
    actual,proof=boundary(out,parent,spec,rows);data.need(actual==neutral,'P06_BBIG_ACTUAL_NEUTRAL_BEFORE_FINANCIAL_MAIN')
    exact(out/BOUNDARY,data.encoded(proof))
    with seed_view(old,out,parent,neutral,spec,out,rows) as view:
        seed=neutral_seed(old,view,parent,neutral,spec,out,rows,baseline)
        # preserve already executed before adoption; retain the exact worker's call as a guarded identity check.
        worker=bind_retained('run',seed,request,parent,rows)
        return worker(neutral,out,args,rows,observer,execution,spec=spec,old=view)
def review(parent,evidence,out,*,spec,old,request):
    from full_system_core import hosted
    hosted()
    from system_campaign_financial_resume import seed_rows
    data.need(selected(spec,request),'P06_BBIG_EXPLICIT_REVIEW_DECLARATION')
    old,evidence,out=Path(old),Path(evidence),Path(out);rows=seed_rows(old,parent,spec);baseline=seeds.original_seed(old,parent,spec)
    neutral,proof=boundary(evidence,parent,spec,rows)
    data.need(json.loads((evidence/BOUNDARY).read_bytes())==proof,'P06_BBIG_INDEPENDENT_COMPLETE_NEUTRAL11_BOUNDARY')
    with seed_view(old,out,parent,neutral,spec,evidence,rows) as view:
        bind_retained('review',neutral_seed(old,view,parent,neutral,spec,evidence,rows,baseline),request,parent,rows)(neutral,evidence,out,spec=spec,old=view)
    exact(out/BOUNDARY,data.encoded(proof))
@contextmanager
def entry_context(module,spec,*,mode,old,out,request,evidence=None):
    from full_system_core import hosted
    hosted()
    if not candidate(spec):
        data.need(not (spec.get('arm')=='P06' and len(spec.get('repairs',[]))>=11 and request.get('execution_mode')==MODE),
            'P06_BBIG_FUTURE11_ROOT_RESTART_REQUIRES_SEPARATE_PROFILE')
        yield;return
    if request.get('execution_mode')!=MODE:yield;return
    data.need(selected(spec,request) and mode in ('preflight','economic','review'),'P06_BBIG_EXPLICIT_INITIAL1383_FINANCIAL_CONTEXT')
    import system_campaign_financial_partial as partial
    import system_campaign_p06_abmd_reporting as reporting
    reporting.retained_source_contract(partial)
    saved=(partial.retained_models,partial.model_context,legacy.uncertainty_phase,legacy.run,legacy.review,module.factual_overlay_needed)
    old_models,old_context,old_phase,old_run,old_review,old_overlay=saved
    def retained_models(root,current,target):return models.full(root,current)['full_inputs'] in (10,11) if candidate(target) else old_models(root,current,target)
    @contextmanager
    def model_context(root,current,target):
        if not candidate(target):
            with old_context(root,current,target):yield
            return
        from system_campaign_bounded_sensor_input import InputCodec
        from system_campaign_abmd_bounded_hydration import hydrate
        from system_campaign_abmd_bounded_catalog import evidence as event_evidence
        models.full(root,current);value=initial.catalog();native,_=hydrate(value,Path(out)/'p06-BBIG-retained-codec-source.json')
        with InputCodec(value['event'],event_evidence(value),native):yield
    partial.retained_models,partial.model_context=retained_models,model_context
    legacy.uncertainty_phase=lambda target:candidate(target) or old_phase(target)
    legacy.run=lambda *a,spec=None,old=None,**k:run(*a,spec=spec,old=old,request=request,**k) if candidate(spec) else old_run(*a,spec=spec,old=old,**k)
    legacy.review=lambda *a,spec=None,old=None,**k:review(*a,spec=spec,old=old,request=request,**k) if candidate(spec) else old_review(*a,spec=spec,old=old,**k)
    module.factual_overlay_needed=lambda target:True if candidate(target) else old_overlay(target)
    try:
        with ExitStack() as stack:
            if mode=='review':
                data.need(evidence is not None,'P06_BBIG_REVIEW_ACTUAL_EVIDENCE_REQUIRED')
                current=strict_json((Path(evidence)/'book/checkpoint.json.gz').read_bytes())
                scratch=Path(out)/'p06-BBIG-review-codecs';scratch.mkdir()
                stack.enter_context(partial.financial_inputs(Path(evidence),current,scratch,spec))
            yield
    finally:
        partial.retained_models,partial.model_context,legacy.uncertainty_phase,legacy.run,legacy.review,module.factual_overlay_needed=saved
