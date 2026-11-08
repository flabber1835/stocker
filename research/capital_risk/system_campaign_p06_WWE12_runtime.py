"""Exact admitted1426/full11 through genuine ordinary12, with173 committed rows."""
import ast,gzip,json,shutil,stat,tempfile
from contextlib import contextmanager,ExitStack
from pathlib import Path
from types import SimpleNamespace
import system_campaign_financial_uncertainty as legacy
import system_campaign_p06_abmd_retained as retained
import system_campaign_p06_abmd_lifecycle_data as initial
import system_campaign_p06_BBIG_runtime as prior
import system_campaign_p06_WWE12_data as data
import system_campaign_p06_WWE12_models as models
import system_campaign_p06_WWE12_api as api
import system_campaign_p06_WWE173_seed as seeds
import system_campaign_p06_WWE12_observer as observations
import system_campaign_p06_WWE12_resources as resources
import system_campaign_p06_FIN339_requalified_parent as loader
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
from system_campaign_pxd_pause import adoption
HERE=Path(__file__).parent
FIELD=loader.FIELD
MODE=loader.MODE
PROVENANCE=models.PROVENANCE
BOUNDARY='p06-WWE-genuine-neutral12-boundary-review.json'
RECEIPT='p06-WWE-ordinary12-adopted-input-receipt.json'
QUALIFICATION='P06-WWE12-dependency-closure-profile-qualification.json'
FULL_PROOF='actual-old-full179-uncertainty-certificate.jsonl'
PRIOR_RUNTIME_SHA='50a0a43d00a3818e89b3fb750c13615fdff215281eba9955853e7818d2bfe90a'

def candidate(spec):return loader.applies(spec)

def qualification():
    data.need((HERE/QUALIFICATION).is_file(),'P06_WWE12_SEPARATE_WHOLE_SOURCE_PROFILE_NOT_CLOSED')
    raw=(HERE/QUALIFICATION).read_bytes();value=json.loads(raw)
    data.need(value['passed'] is True and value['root_admission_sha256']==data.ROOT
        and value['financial_authority'] is value['canonical_runtime_executed'] is value['actual_neutral12_known'] is False,
        'P06_WWE12_ONLY_SEPARATELY_CLOSED_WHOLE_SOURCE_PROFILE')
    for n,pin in value['files'].items():
        b=(HERE/n).read_bytes();data.need(dict(bytes=len(b),sha256=data.sha(b))==pin,'P06_WWE12_FROZEN_WHOLE_PROFILE_SOURCE:'+n)
    return data.sha(raw)

def declaration(spec):
    data.authority.require(spec);loader.validated(spec)
    return dict(schema='research.P06-WWE12-retained173-financial-declaration/1',root_admission_sha256=data.ROOT,
        selected_parent_outer_sha256=data.OUTER,actual_parent_inputs=11,required_genuine_neutral_inputs=12,
        committed_seed_rows=173,committed_seed_sha256=seeds.PREFIX['sha256'],raw_proof_rows=179,excluded_tail_rows=6,
        held_WWE_shares=27,profile_qualification_sha256=qualification(),genuine_neutral12_known=False,
        future12_root_restart_selected=False,financial_source_changed=False)

def selected(spec,request):
    return candidate(spec) and request.get('execution_mode')==MODE and request.get('financial_resume_authorized') is True \
        and request.get('readonly_partial_review') is request.get('readonly_source_witnesses') is False \
        and request.get(FIELD)=={'P06':declaration(spec)}

def request_financial(request,spec):
    data.need(selected(spec,request),'P06_WWE12_ONLY_EXACT_ACTIVE_FINANCIAL_DECLARATION')
    api.asset.request_binding(request)
    data.need(request['admitted_checkpoints']['P06']==data.OUTER
        and all(request['sources'].get(n)==data.sha((HERE/n).read_bytes()) for n in source_names()),
        'P06_WWE12_EXACT_ADMITTED_ROOT_AND_ALL_CURRENT_REQUEST_SOURCE_PINS')
    return True

def expected_request(original,*,execution_mode,selected_arms,root_lookup):
    # The old profile intentionally refuses future full11 roots. Only this exact
    # separately qualified successor omits P06 from that old profile's selection.
    active=execution_mode==MODE and 'P06' in selected_arms and candidate(root_lookup('P06'))
    result=original(selected_arms=tuple(a for a in selected_arms if a!='P06') if active else selected_arms)
    data.need(FIELD not in result,'P06_WWE12_NO_REPLACED_REQUEST_DECLARATION')
    result[FIELD]={'P06':declaration(root_lookup('P06'))} if active else {}
    result[api.asset.FIELD]={'P06':api.asset.declaration()} if active else {}
    if active:
        data.need(result['admitted_checkpoints']['P06']==data.OUTER,'P06_WWE12_REQUEST_REAL_ACTUAL1426_PARENT11')
        result['arm_inputs']['P06']['new_factual_overlay']=True
    for n in source_names():
        pin=data.sha((HERE/n).read_bytes());data.need(n not in result['sources'] or result['sources'][n]==pin,'P06_WWE12_NO_SOURCE_PIN_REPLACEMENT')
        result['sources'][n]=pin
    return result

def boundary_relation(parent,neutral,spec,member,rows):
    data.parent_contract(parent,spec);raw=member(models.OVERLAY)
    data.need(json.loads(raw)==models.document(parent,member),'P06_WWE12_COMPLETE_ACTUAL_STOCK_INPUT_DOCUMENT')
    event=adoption(neutral,parent,data.sha(raw),'2023-09-11');neutral_raw=member(models.DIRECTORY+'/checkpoint.json.gz')
    data.need(strict_json(neutral_raw)==neutral and len(neutral['repairs'])==12 and neutral['repairs'][:11]==parent['repairs']
        and neutral['run']['state']==parent['run']['state'],'P06_WWE12_REAL_NEUTRAL12_GZIP_STATE_AND_FULL_HISTORY')
    proof=json.loads(member(models.DIRECTORY+'/proof.json'))
    data.need(proof==dict(event=event,actual_checkpoint_gzip_sha256=data.sha(neutral_raw),original_outer_sha256=parent['sha256'],
        financial_state_unchanged=True,financial_sessions_advanced=0)
        and gzip.decompress(member(models.DIRECTORY+'-correlation-inputs.jsonl.gz'))==b''.join(rows),
        'P06_WWE12_COMPLETE_ZERO_SESSION_PROOF_AND_ZERO_NEW_CORRELATION')
    watch=member('book/watch.jsonl');a,b=parent['journals']['watch'],neutral['journals']['watch']
    data.need(data.sha(watch[:a['bytes']])==a['prefix_sha256'] and data.sha(watch[:b['bytes']])==b['prefix_sha256']
        and [json.loads(v) for v in watch[a['bytes']:b['bytes']].splitlines()]==[event],
        'P06_WWE12_ONLY_REAL_ONE_CANONICAL_INPUT_SUCCESSOR_WATCH')
    return dict(passed=True,parent11_sha256=parent['sha256'],actual_neutral12_sha256=neutral['sha256'],
        neutral_gzip_sha256=data.sha(neutral_raw),original_root_admission_sha256=data.ROOT,original_inputs=11,current_inputs=12,
        input_successor=event,financial_sessions_advanced=0,all_original_financial_state_journals_and_stats_unchanged=True,zero_new_correlation=True)

def boundary(root,parent,spec,rows):
    root=Path(root);neutral=strict_json((root/models.DIRECTORY/'checkpoint.json.gz').read_bytes())
    proof=boundary_relation(parent,neutral,spec,lambda n:(root/n).read_bytes(),rows)
    api.receipt(parent,spec,root)
    data.need(models.full(root,neutral)['full_inputs']==12,'P06_WWE12_COMPLETE_GENUINE_FULL_HISTORY')
    return neutral,proof

def adoption_tree(raw):
    # Entire original adopter, using the previously qualified one-filename lift.
    fn=prior.adoption_tree(raw)
    mapping,=[n for n in ast.walk(fn) if isinstance(n,ast.Dict) and any(isinstance(k,ast.Constant) and k.value==prior.models.DIRECTORY for k in n.keys)]
    site,=[i for i,k in enumerate(mapping.keys) if isinstance(k,ast.Constant) and k.value==prior.models.DIRECTORY]
    mapping.keys[site]=ast.Constant(models.DIRECTORY);mapping.values[site]=ast.Constant(models.OVERLAY)
    return ast.fix_missing_locations(fn)

def adopter():
    scope=dict(vars(legacy));exec(compile(ast.Module(body=[adoption_tree(Path(legacy.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-canonical-adopter-one-WWE-filename>','exec'),scope);return scope['paused_own_adoption']

def retained_tree(raw,name):
    data.need(data.sha(raw)==prior.RETAINED_SHA,'P06_WWE12_ENTIRE_ORIGINAL_RETAINED_WORKER_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
    data.need(name in ('run','review'),'P06_WWE12_ONLY_COMPLETE_ORIGINAL_RETAINED_RUN_OR_REVIEW')
    module='system_campaign_p06_abmd_point_continuation' if name=='run' else 'system_campaign_p06_abmd_retained_suffix'
    imp,=[n for n in ast.walk(fn) if isinstance(n,ast.ImportFrom) and n.module==module]
    data.need([(v.name,v.asname) for v in imp.names]==([('certificate_class',None)] if name=='run' else [('review','suffix')]),
        'P06_WWE12_ONE_EXACT_FACTORY_OR_SUFFIX_IMPORT')
    imp.module='system_campaign_p06_WWE173_seed'
    if name=='review':imp.names[0].name='suffix'
    sites=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and type(n.value)is int and n.value==6]
    data.need(len(sites)==(1 if name=='run' else 5),'P06_WWE12_EXACT_ORIGINAL_RETAINED_ROW_COUNT_SITES')
    for n in sites:n.value=173
    if name=='run':
        block,=[n for n in fn.body if isinstance(n,ast.With)
            and [ast.unparse(i.context_expr) for i in n.items]==['certificate','observer','execution','events']]
        fn.body.insert(fn.body.index(block),ast.parse('constructor_canary(parent,out,certificate,events)').body[0])
    return ast.fix_missing_locations(fn)

def genuine_receipt(neutral,spec,root,rows):
    parent=strict_json((Path(root)/models.PARENT).read_bytes())
    return boundary_relation(parent,neutral,spec,lambda n:(Path(root)/n).read_bytes(),rows)

def bind_retained(name,seed,request,financial_parent,rows):
    scope_root=[None];target=[None];old_root=[None];resolutions=[]
    def checked_seed(*a,**k):
        value=seed(*a,**k);resolutions[:]=[value[3]];return value
    facade=SimpleNamespace(selected=lambda spec,req:selected(spec,req),UNCHANGED=RECEIPT,
        receipt=lambda current,spec:genuine_receipt(current,spec,scope_root[0],rows),PROVENANCE=PROVENANCE,
        FULL_PROOF=FULL_PROOF,encoded=data.encoded,OBSERVATIONS=observations.DIRECTORY)
    def review_adopted(neutral,current,evidence,spec):
        boundary(evidence,financial_parent,spec,rows)
        data.need(current['base']==neutral['base'] and current['repairs']==neutral['repairs']
            and current['run']['input_sha256']==neutral['run']['input_sha256']
            and json.loads((Path(evidence)/RECEIPT).read_bytes())==genuine_receipt(neutral,spec,evidence,rows),
            'P06_WWE12_FINANCIAL_SEGMENT_USES_GENUINE_NEUTRAL12_AND_ALL_PRIOR_INPUTS')
    facade.review_unchanged=review_adopted
    def preserved(root,out,current,proof,resolution):
        resources.verify_preserved(lambda n:(Path(root)/n).read_bytes(),lambda n:(Path(out)/n).read_bytes(),resolutions=(resolution,))
        data.need(len(proof)==173 and (Path(out)/models.OLD_PROOF).read_bytes()==(Path(root)/'uncertainty-certificate.jsonl').read_bytes()
            and (Path(out)/resolution['actual']).read_bytes()==(Path(root)/resolution['actual']).read_bytes(),
            'P06_WWE12_WHOLE_PRESERVATION_DONE_BEFORE_REAL_ADOPTION')
    def constructor_canary(current,out,certificate,events):
        out=Path(out);old=Path(old_root[0])
        resources.verify_preserved(lambda n:(old/n).read_bytes(),lambda n:(out/n).read_bytes(),resolutions=tuple(resolutions))
        models.full(out,current)
        exact(out/'continuation-constructor-canary.json',data.encoded(dict(passed=True,
            actual_certificate_and_original_observer_constructed=True,all_referenced_archives_preserved=True,
            current_checkpoint_sha256=current['sha256'],financial_sessions_advanced=0)))
    scope=dict(vars(retained),data=facade,seed=checked_seed,full=models.full,preserve=preserved,constructor_canary=constructor_canary,
        prior_event=lambda root,current,proof:seeds.prior_event(root,current,proof,financial_parent)[1][0],
        ordinary_observer=lambda root,out,current:observations.observer(root,out,current,financial_parent,target[0],request),
        review_cash=lambda neutral,current,evidence,out:observations.review(financial_parent,current,evidence,out,spec=target[0],old=old_root[0],resolutions=tuple(resolutions)))
    exec(compile(ast.Module(body=[retained_tree(Path(retained.__file__).read_bytes(),name)],type_ignores=[]),
        '<whole-original-retained-worker-exact173-and-original-ABMD-factory>','exec'),scope)
    whole=scope[name]
    def bound(*args,**kwargs):
        scope_root[0]=Path(args[1]);target[0]=kwargs['spec'];old_root[0]=kwargs['old']
        return whole(*args,**kwargs,request=request)
    return bound

def permissions_tree():
    data.need(data.sha(Path(prior.__file__).read_bytes())==PRIOR_RUNTIME_SHA,'P06_WWE12_WHOLE_PRIOR_PERMISSION_SOURCE')
    fn,=[n for n in ast.parse(Path(prior.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='owned_view_permissions']
    sites=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and n.value=='p06-BBIG-real-neutral-seed-view-']
    data.need(len(sites)==1,'P06_WWE12_ONE_ORIGINAL_OWNED_VIEW_PERMISSION_PREFIX')
    sites[0].value='p06-WWE-real-neutral-seed-view-';return ast.fix_missing_locations(fn)

def owned_view_permissions(view,owned,output):
    scope=dict(vars(prior));exec(compile(ast.Module(body=[permissions_tree()],type_ignores=[]),'<whole-original-owned-view-permissions-one-WWE-prefix>','exec'),scope)
    return scope['owned_view_permissions'](view,owned,output)

@contextmanager
def seed_view(old, out, parent, neutral, spec, evidence, rows):
    from full_system_core import hosted
    hosted()
    old, out, evidence = (Path(old), Path(out), Path(evidence))
    original = (old / spec['selected_checkpoint']).read_bytes()
    data.need(dict(bytes=len(original), sha256=data.sha(original)) == spec['selected_file'] and strict_json(original) == parent, 'P06_WWE12_REAL_SELECTED_PARENT11_GZIP_NEVER_SUBSTITUTED')
    proof = boundary_relation(parent, neutral, spec, lambda n: (evidence / n).read_bytes(), rows)
    try:
        with tempfile.TemporaryDirectory(prefix='p06-WWE-real-neutral-seed-view-', dir=out) as owned:
            view = Path(owned) / 'view'
            shutil.copytree(old, view)
            permissions = owned_view_permissions(view, owned, out)
            files = [models.OVERLAY, models.PRIVATE, models.PARENT, api.PACKETS, api.CANONICAL, models.DIRECTORY + '/checkpoint.json.gz', models.DIRECTORY + '/proof.json', models.DIRECTORY + '-correlation-inputs.jsonl.gz', 'book/repairs/' + neutral['repairs'][11]['filename']]
            inventory = {}
            for n in files:
                raw = (evidence / n).read_bytes()
                exact(view / n, raw)
                inventory[n] = dict(bytes=len(raw), sha256=data.sha(raw))
            watch = (evidence / 'book/watch.jsonl').read_bytes()
            committed = neutral['journals']['watch']
            data.need(data.sha(watch[:committed['bytes']]) == committed['prefix_sha256'], 'P06_WWE12_REAL_NEUTRAL_WATCH_COMMITMENT')
            (view / 'book/watch.jsonl').write_bytes(watch[:committed['bytes']])
            data.need((view / spec['selected_checkpoint']).read_bytes() == original, 'P06_WWE12_VIEW_ORIGINAL_FINANCIAL_PARENT11_UNMODIFIED')
            exact(out / PROVENANCE / 'temporary-seed-view-receipt.json', data.encoded(dict(passed=True, selected_parent11_file_sha256=data.sha(original), actual_neutral12_file_sha256=proof['neutral_gzip_sha256'], real_neutral_watch_sha256=data.sha(watch[:committed['bytes']]), neutral_committed_watch_bytes=committed['bytes'], actual_added_files=inventory, selected_checkpoint_replaced=False, owned_copy_permissions=permissions, financial_sessions_advanced=0, temporary_view_cleanup_on_scope_exit_required=True)))
            yield view
    finally:
        data.need(not Path(owned).exists(), 'P06_WWE12_OWNED_TEMPORARY_VIEW_REMOVAL_OBSERVED')
        exact(out / PROVENANCE / 'temporary-seed-view-cleanup.json', data.encoded(dict(passed=True, temporary_owned_view_removal_observed=True, original_selected_and_genuine_neutral_archives_preserved=True, financial_sessions_advanced=0)))

def neutral_seed(old,view,parent,neutral,spec,evidence,rows,baseline):
    old,view,evidence=Path(old),Path(view),Path(evidence)
    def contract(current,target):
        data.need(current==neutral and target==spec,'P06_WWE12_SEED_BRIDGE_ONLY_REAL_NEUTRAL12_AND_ORIGINAL_SPEC11')
        boundary_relation(parent,current,target,lambda n:(evidence/n).read_bytes(),rows)
        return seeds.contract(parent,target,old)
    whole=seeds.bind_seed(contract=contract)
    def seed(root,current,target):
        data.need(Path(root)==view and current==neutral and target==spec,'P06_WWE12_ONLY_ACTUAL_INVENTORIED_SEED_VIEW')
        actual=whole(view,current,target)
        data.need(actual==baseline[:3] and len(actual[1])==173,'P06_WWE12_WHOLE_NEUTRAL12_SEED_EQUALS_ACTUAL_PARENT11_173')
        return (*actual,baseline[3])
    return seed

def run(parent,out,args,rows,observer,execution,*,spec,old,request):
    from full_system_core import hosted
    hosted();request_financial(request,spec);old,out=Path(old),Path(out)
    baseline=seeds.original_seed(old,parent,spec);resources.preserve(old,out,parent,spec,resolutions=(baseline[3],))
    exact(out/api.CANARY,(out/'parent-preflight'/api.CANARY).read_bytes())
    exact(out/models.PARENT,(old/spec['selected_checkpoint']).read_bytes())
    oracle=(old/'stopped-review/uncertainty-certificate-review.json').read_bytes()
    data.need(data.sha(oracle)=='190de5015b174b76f42786943f87ac5e3100555b660e0e116d7d305a18b71bf8','P06_WWE12_ORIGINAL_FIN339_PHYSICAL_ORACLE')
    exact(out/PROVENANCE/'original-FIN339-branch-oracle.json',oracle)
    path,loaded=api.prepare(parent,old,out,request,spec=spec)
    neutral=adopter()(parent,out,args,rows,path,loaded.earliest_affected_session,models.DIRECTORY)
    actual,proof=boundary(out,parent,spec,rows);data.need(actual==neutral,'P06_WWE12_ACTUAL_NEUTRAL_BEFORE_FINANCIAL_MAIN')
    exact(out/BOUNDARY,data.encoded(proof))
    with seed_view(old,out,parent,neutral,spec,out,rows) as view:
        worker=bind_retained('run',neutral_seed(old,view,parent,neutral,spec,out,rows,baseline),request,parent,rows)
        return worker(neutral,out,args,rows,observer,execution,spec=spec,old=view)

def review(parent,evidence,out,*,spec,old,request):
    from full_system_core import hosted
    hosted()
    from system_campaign_financial_resume import seed_rows
    from research.pooled_vacancy_funding import journal
    request_financial(request,spec);old,evidence,out=Path(old),Path(evidence),Path(out)
    rows=seed_rows(old,parent,spec);baseline=seeds.original_seed(old,parent,spec)
    neutral,proof=boundary(evidence,parent,spec,rows)
    data.need(json.loads((evidence/BOUNDARY).read_bytes())==proof,'P06_WWE12_INDEPENDENT_COMPLETE_NEUTRAL12_BOUNDARY')
    api.review_input(parent,spec,evidence,out,request)
    with seed_view(old,out,parent,neutral,spec,evidence,rows) as view:
        bind_retained('review',neutral_seed(old,view,parent,neutral,spec,evidence,rows,baseline),request,parent,rows)(neutral,evidence,out,spec=spec,old=view)
    current=journal.read_checkpoint(evidence/'book/checkpoint.json.gz')
    api.roles.bound('actual_conversion')(evidence,current,parent,out/'p06-WWE-actual-conversion-review.json')
    data.need((evidence/PROVENANCE/'original-FIN339-branch-oracle.json').read_bytes()==(old/'stopped-review/uncertainty-certificate-review.json').read_bytes(),
        'P06_WWE12_ORIGINAL_FIN339_ORACLE_PRESERVED_SEPARATELY')
    exact(out/BOUNDARY,data.encoded(proof))

@contextmanager
def entry_context(module,spec,*,mode,old,out,request,evidence=None):
    from full_system_core import hosted
    hosted();request_financial(request,spec)
    data.need(mode in ('preflight','economic','review'),'P06_WWE12_ONLY_EXPLICIT_HOSTED_PROCESS_MODES')
    import system_campaign_financial_partial as partial
    from system_campaign_registry_extension import RegistryExtension
    names=('retained_models','model_context');saved_partial={n:getattr(partial,n) for n in names}
    saved_legacy={n:getattr(legacy,n) for n in ('uncertainty_phase','run','review')}
    saved_module={n:getattr(module,n) for n in ('factual_overlay_needed','prepare_composite_before_finance','require_composite_preparation')}
    def retained_models(root,current,target):
        return models.full(root,current)['full_inputs'] in (11,12) if candidate(target) else saved_partial['retained_models'](root,current,target)
    @contextmanager
    def model_context(root,current,target):
        if not candidate(target):
            with saved_partial['model_context'](root,current,target):yield
            return
        from system_campaign_bounded_sensor_input import InputCodec
        from system_campaign_abmd_bounded_hydration import hydrate
        from system_campaign_abmd_bounded_catalog import evidence as event_evidence
        models.full(root,current);value=initial.catalog();native,_=hydrate(value,Path(out)/'p06-WWE-retained-codec-source.json')
        with InputCodec(value['event'],event_evidence(value),native):yield
    partial.retained_models,partial.model_context=retained_models,model_context
    legacy.uncertainty_phase=lambda target:candidate(target) or saved_legacy['uncertainty_phase'](target)
    legacy.run=lambda *a,spec=None,old=None,**k:run(*a,spec=spec,old=old,request=request,**k) if candidate(spec) else saved_legacy['run'](*a,spec=spec,old=old,**k)
    legacy.review=lambda *a,spec=None,old=None,**k:review(*a,spec=spec,old=old,request=request,**k) if candidate(spec) else saved_legacy['review'](*a,spec=spec,old=old,**k)
    module.factual_overlay_needed=lambda target:True if candidate(target) else saved_module['factual_overlay_needed'](target)
    module.prepare_composite_before_finance=lambda cp,folder,target:api.preflight(cp,folder,target,old,request) if candidate(target) else saved_module['prepare_composite_before_finance'](cp,folder,target)
    module.require_composite_preparation=lambda cp,target,proof,folder:api.require_preflight(cp,target,proof,folder) if candidate(target) else saved_module['require_composite_preparation'](cp,target,proof,folder)
    try:
        with ExitStack() as stack:
            stack.enter_context(loader.context(spec,request,mode=mode,profile_validator=request_financial))
            stack.enter_context(RegistryExtension())
            if mode=='review':
                data.need(evidence is not None,'P06_WWE12_REVIEW_REQUIRES_ACTUAL_EVIDENCE')
                current=strict_json((Path(evidence)/'book/checkpoint.json.gz').read_bytes())
                scratch=Path(out)/'p06-WWE-review-codecs';scratch.mkdir()
                stack.enter_context(partial.financial_inputs(Path(evidence),current,scratch,spec))
            yield
    finally:
        for n,v in saved_partial.items():setattr(partial,n,v)
        for n,v in saved_legacy.items():setattr(legacy,n,v)
        for n,v in saved_module.items():setattr(module,n,v)

def source_names():
    extra=tuple(json.loads((HERE/QUALIFICATION).read_bytes())['files']) if (HERE/QUALIFICATION).is_file() else ()
    data.need(all(Path(n).name==n and '/' not in n and '\\' not in n and n not in ('.','..') for n in extra),
        'P06_WWE12_ONLY_PLAIN_WHOLE_PROFILE_SOURCE_FILENAMES')
    return tuple(sorted(set((Path(__file__).name,QUALIFICATION,'system_campaign_p06_WWE12_stage.py',*extra,*api.source_names(),*seeds.source_names(),*observations.source_names(),*loader.source_names()))))
