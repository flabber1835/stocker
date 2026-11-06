"""Hosted genuine16-to17 ordinary adoption around the complete typed runtime."""
import ast,gzip,json,shutil,tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import FunctionType
import system_campaign_financial_uncertainty as uncertainty
import system_campaign_bounded_sensor_runtime_v2 as typed
import system_campaign_p03_thor_data as data
import system_campaign_p03_thor_api as api_module
from system_campaign_bounded_sensor_origin_v2 import exact,strict_json
from system_campaign_pxd_pause import adoption

HERE=Path(__file__).parent
U_SHA='3ec636f898e9c3918047da18150660be37fd08f680818ec93064dfa355a1f6a8'
TYPED_SHA='4a261717829b227a29d01bd2c746c88554467645608a7b4476dd4f523b161096'
FIELD='selected_p03_thor_ordinary17'
MODE='OWN_ADMITTED_FINANCIAL_CONTINUATION'
RAW_PROOF='p03-thor-ordinary17-origin/entire-prior-certificate.jsonl'
SELECTED='p03-thor-ordinary17-origin/actual-selected-parent16.json.gz'
PRIOR_REVIEW='p03-thor-ordinary17-origin/prior-hosted-branch-review.json'
VIEW_RECEIPT='p03-thor-ordinary17-origin/temporary-seed-view-receipt.json'
VIEW_CLEANUP='p03-thor-ordinary17-origin/temporary-seed-view-cleanup.json'
BOUNDARY_REVIEW='p03-thor-ordinary17-neutral-boundary-review.json'
def selected(spec):
    return isinstance(spec,dict) and spec.get('arm')=='P03' and spec.get('root_admission_sha256')==data.ROOT
def declaration(spec):
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec)
    data.need(selected(spec) and (spec['measured_closes'],spec['selected_session'],len(spec['repairs']))==(503,'2019-12-31',16),
        'THOR_RUNTIME_EXACT_ACTUAL_ADMITTED_INITIAL_ENTRY_ONLY')
    value=data.catalog()
    return dict(schema='research.P03-THOR2-genuine-ordinary17-declaration/1',arm='P03',
        original_root_admission_sha256=data.ROOT,original_outer_sha256=data.OUTER,original_inputs=16,
        required_actual_neutral_inputs=17,old_committed_proof_rows=49,catalog_file=data.CATALOG,catalog_sha256=data.sha(data.encoded(value)),
        financial_source_changed=False,provider_metadata_upgraded=False,genuine_neutral_adoption_required=True,
        actual_future_neutral_checkpoint_known=False,future17_root_restart_selected=False)
def request_selected(spec,request):
    return (selected(spec) and request.get('execution_mode')==MODE and request.get('financial_resume_authorized') is True
        and request.get('readonly_partial_review') is request.get('readonly_source_witnesses') is False
        and request.get(FIELD,{}).get('P03')==declaration(spec))
def entry_authority(spec,request):
    financial=request.get('execution_mode')==MODE and request.get('financial_resume_authorized') is True
    if not financial:return False
    if selected(spec):
        data.need(request_selected(spec,request),'THOR_RUNTIME_EXPLICIT_ORIGINAL16_FINANCIAL_DECLARATION_REQUIRED')
        return True
    data.need(not (typed.selected(spec) and len(spec.get('repairs',[]))>=17),
        'THOR_RUNTIME_FUTURE17_ROOT_RESTART_REQUIRES_SEPARATE_QUALIFICATION')
    return False
def expected_request(original,*,execution_mode,selected_arms,root_lookup):
    value=original();declared={}
    if execution_mode==MODE and 'P03' in selected_arms:
        spec=root_lookup('P03')
        data.need(selected(spec) or not (typed.selected(spec) and len(spec.get('repairs',[]))>=17),
            'THOR_RUNTIME_FUTURE17_ROOT_RESTART_REQUIRES_SEPARATE_QUALIFICATION')
        if selected(spec):
            declared['P03']=declaration(spec)
            data.need(value['admitted_checkpoints']['P03']==data.OUTER,'THOR_RUNTIME_REQUEST_ORIGINAL_FINANCIAL_SEED16')
            value['arm_inputs']['P03']['new_factual_overlay']=True
    value[FIELD]=declared
    for name in source_names():
        pin=data.sha((HERE/name).read_bytes());data.need(name not in value['sources'] or value['sources'][name]==pin,'THOR_RUNTIME_NO_REPLACED_REQUEST_SOURCE_PIN')
        value['sources'][name]=pin
    return value
def source_names():
    return (Path(__file__).name,*api_module.source_names())
def adoption_tree(raw):
    data.need(data.sha(raw)==U_SHA,'THOR_RUNTIME_WHOLE_ORIGINAL_NEUTRAL_ADOPTION_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption']
    node,=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names'];mapping=node.value
    data.need(isinstance(mapping,ast.Dict) and [ast.unparse(k) for k in mapping.keys]==['ORDINARY_ADOPTION','DATE_ADOPTION','MODEL_ADOPTION']
        and [ast.unparse(v) for v in mapping.values]==["'future-financial-overlay.json'",'DATE_OVERLAY',"'branch-uncertainty-input.json'"],
        'THOR_RUNTIME_ONE_EXACT_ORIGINAL_FILENAME_MAP')
    mapping.keys.append(ast.Constant(api_module.DIRECTORY));mapping.values.append(ast.Constant(api_module.OVERLAY))
    return ast.fix_missing_locations(fn)
def adopter():
    fn=adoption_tree(Path(uncertainty.__file__).read_bytes());namespace=dict(vars(uncertainty))
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-original-adoption-one-THOR17-filename-entry>','exec'),namespace)
    return namespace['paused_own_adoption']
def boundary_relation(parent,neutral,spec,member,rows):
    """Only reads two actual checkpoints and their actual producer resources."""
    data.parent_contract(parent,spec);raw=member(api_module.OVERLAY);doc=json.loads(raw)
    value=data.catalog();term,=value['terms']
    data.need(doc['schema']=='terminal-repair/1' and doc['predecessor_checkpoint_sha256']==parent['run']['checkpoint_sha256']
        and doc['add']==[term['added']] and doc['suppress']==[dict(session=term['native_session'],security_id=data.SID,term_sha256=term['native_term_sha256'])]
        and len(doc['source_evidence'])<=128,'THOR_RUNTIME_ONE_EXACT_ORDINARY_PATCH_ORIGINAL_EVIDENCE_CAP')
    event=adoption(neutral,parent,data.sha(raw),term['native_session'])
    neutral_raw=member(api_module.DIRECTORY+'/checkpoint.json.gz')
    data.need(strict_json(neutral_raw)==neutral and len(neutral['repairs'])==17
        and neutral['repairs'][:16]==parent['repairs'] and neutral['run']['state']==parent['run']['state'],
        'THOR_RUNTIME_ACTUAL_NEUTRAL17_GZIP_FULL_STATE_AND_HISTORY')
    proof=json.loads(member(api_module.DIRECTORY+'/proof.json'))
    data.need(proof==dict(event=event,actual_checkpoint_gzip_sha256=data.sha(neutral_raw),original_outer_sha256=parent['sha256'],
        financial_state_unchanged=True,financial_sessions_advanced=0)
        and gzip.decompress(member(api_module.DIRECTORY+'-correlation-inputs.jsonl.gz'))==b''.join(rows),
        'THOR_RUNTIME_COMPLETE_ACTUAL_ZERO_SESSION_PROOF_AND_ZERO_NEW_CORRELATION')
    watch=member('book/watch.jsonl');a,b=parent['journals']['watch'],neutral['journals']['watch']
    data.need(data.sha(watch[:a['bytes']])==a['prefix_sha256'] and data.sha(watch[:b['bytes']])==b['prefix_sha256']
        and [json.loads(v) for v in watch[a['bytes']:b['bytes']].splitlines()]==[event],
        'THOR_RUNTIME_ONLY_ONE_REAL_CANONICAL_SUCCESSOR_WATCH_NO_FINANCIAL_RECORD')
    q=json.loads(member(api_module.QUALIFICATION))
    data.need(q['passed'] is True and type(q['packet_checks']) is int and q['packet_checks']>0
        and q['only_terminal_field_changed'] is q['complete_terms_and_canonical_notional_verified']
        is q['original_incomplete_guard_retained'] is q['wrong_predecessor_and_consumed_date_refused']
        is q['wrong_native_and_delivery_witness_refused'] is True
        and type(q['financial_sessions_advanced']) is int and q['financial_sessions_advanced']==0,
        'THOR_RUNTIME_ACTUAL_WHOLE_ORIGINAL_CANONICAL_PACKET_QUALIFICATION')
    return dict(passed=True,original_parent_outer_sha256=parent['sha256'],actual_neutral_outer_sha256=neutral['sha256'],
        neutral_gzip_sha256=data.sha(neutral_raw),original_inputs=16,current_inputs=17,input_successor=event,
        original_root_admission_sha256=data.ROOT,financial_sessions_advanced=0,canonical_financial_source_changed=False,
        all_original_state_journals_and_stats_unchanged=True,zero_new_correlation=True)
def boundary(root,parent,spec,rows):
    from full_system_core import hosted
    hosted()
    root=Path(root);neutral=strict_json((root/api_module.DIRECTORY/'checkpoint.json.gz').read_bytes())
    proof=boundary_relation(parent,neutral,spec,lambda name:(root/name).read_bytes(),rows)
    api=api_module.api(parent,spec)
    data.need(api.review_input(parent,root,'P03')=='2020-01-23','THOR_RUNTIME_FULL_SOURCE_AND_DOCUMENT_RECONSTRUCTION')
    # The exact original name is data-only; no alternative hydration namespace.
    import system_campaign_financial_future as future
    material=json.loads((root/future.hydration_name(parent)).read_bytes())
    data.need(material['terms']==data.catalog()['terms'],'THOR_RUNTIME_NO_UNDECLARED_REMAINING_ORDINARY_TERMS')
    return neutral,proof
def cleanup_observed(owned):
    data.need(not Path(owned).exists(),'THOR_RUNTIME_TEMPORARY_OWNED_SEED_VIEW_CLEANUP_OBSERVED')
    return True
@contextmanager
def seed_view(old,out,parent,neutral,spec,evidence,rows):
    from full_system_core import hosted
    hosted()
    import system_campaign_financial_future as future
    old,out,evidence=Path(old),Path(out),Path(evidence)
    original=(old/spec['selected_checkpoint']).read_bytes()
    data.need(dict(bytes=len(original),sha256=data.sha(original))==spec['selected_file'] and strict_json(original)==parent,
        'THOR_RUNTIME_SELECTED_PARENT16_GZIP_NEVER_SUBSTITUTED')
    proof=boundary_relation(parent,neutral,spec,lambda name:(evidence/name).read_bytes(),rows)
    with tempfile.TemporaryDirectory(prefix='p03-thor-owned-seed-view-',dir=out) as owned:
        view=Path(owned)/'view';shutil.copytree(old,view)
        files=[api_module.OVERLAY,api_module.QUALIFICATION,data.CATALOG,data.PRIMARY,
            api_module.DIRECTORY+'/checkpoint.json.gz',api_module.DIRECTORY+'/proof.json',
            api_module.DIRECTORY+'-correlation-inputs.jsonl.gz',future.hydration_name(parent),
            'book/repairs/'+neutral['repairs'][16]['filename']]
        added={}
        for name in files:
            raw=(evidence/name).read_bytes();exact(view/name,raw);added[name]=dict(bytes=len(raw),sha256=data.sha(raw))
        watch=(evidence/'book/watch.jsonl').read_bytes()
        data.need(data.sha(watch[:neutral['journals']['watch']['bytes']])==neutral['journals']['watch']['prefix_sha256'],
            'THOR_RUNTIME_VIEW_REAL_NEUTRAL_WATCH_IDENTITY')
        neutral_watch=watch[:neutral['journals']['watch']['bytes']]
        (view/'book/watch.jsonl').write_bytes(neutral_watch)
        data.need((view/spec['selected_checkpoint']).read_bytes()==original,'THOR_RUNTIME_VIEW_STILL_SELECTS_ORIGINAL16_GZIP')
        exact(out/SELECTED,original);exact(out/RAW_PROOF,(old/'uncertainty-certificate.jsonl').read_bytes())
        exact(out/PRIOR_REVIEW,(old/'stopped-review/uncertainty-certificate-review.json').read_bytes())
        receipt=dict(schema='research.P03-actual-neutral17-temporary-seed-view/1',passed=True,
            selected_parent16_file_sha256=data.sha(original),actual_neutral17_file_sha256=proof['neutral_gzip_sha256'],
            original_full_watch_sha256=data.sha((old/'book/watch.jsonl').read_bytes()),actual_neutral_watch_sha256=data.sha(neutral_watch),
            source_watch_file_sha256=data.sha(watch),neutral_committed_watch_bytes=len(neutral_watch),
            original_full_proof_sha256=data.sha((old/'uncertainty-certificate.jsonl').read_bytes()),actual_added_files=added,
            financial_sessions_advanced=0,selected_checkpoint_replaced=False,temporary_view_cleanup_on_scope_exit_required=True)
        exact(out/VIEW_RECEIPT,data.encoded(receipt))
        yield view
    cleanup_observed(owned)
    exact(out/VIEW_CLEANUP,data.encoded(dict(passed=True,temporary_owned_view_removal_observed=True,
        selected_original_and_actual_neutral_archives_preserved=True,financial_sessions_advanced=0)))
def seed_resolver(old,view,parent,neutral,spec,evidence,rows,baseline):
    from full_system_core import hosted
    hosted()
    from system_campaign_bounded_sensor_seed_binding import bind_seed
    old,view,evidence=Path(old),Path(view),Path(evidence)
    def contract(actual,target):
        data.need(actual==neutral and target==spec,'THOR_RUNTIME_SEED_BRIDGE_ONLY_ACTUAL_NEUTRAL_AND_ORIGINAL_SPEC')
        boundary_relation(parent,actual,spec,lambda name:(evidence/name).read_bytes(),rows)
        return typed.retained_contract(parent,target,old)
    whole=bind_seed(validate_input=lambda where,current:typed.full_models(where,current),
        retained_contract=contract,retained_phase=typed.retained_phase)
    def seed(where,current,target):
        data.need(Path(where)==view and current==neutral and target==spec,'THOR_RUNTIME_ONLY_INVENTORIED_REAL_SEED_VIEW')
        checked=whole(view,current,target)
        data.need(checked==baseline and len(checked[1])==49,'THOR_RUNTIME_WHOLE_NEUTRAL17_SEED_EQUALS_INDEPENDENT_PARENT16_SEED')
        return checked
    return seed
def bound_runtime(name,seed):
    raw=Path(typed.__file__).read_bytes();data.need(data.sha(raw)==TYPED_SHA,'THOR_RUNTIME_ENTIRE_EXISTING_TYPED_RUNTIME_SOURCE')
    fn=getattr(typed,name)
    data.need(name in ('run','review') and fn.__closure__ is None,'THOR_RUNTIME_COMPLETE_CLOSED_TYPED_FUNCTION')
    bound=FunctionType(fn.__code__,dict(fn.__globals__,seed=seed),fn.__name__,fn.__defaults__)
    bound.__kwdefaults__=deepcopy(fn.__kwdefaults__)
    data.need(bound.__code__ is fn.__code__,'THOR_RUNTIME_TYPED_BODY_CODE_OBJECT_UNCHANGED')
    return bound
def original_seed(old,parent,spec):
    baseline=typed.seed(Path(old),parent,spec);raw=(Path(old)/'uncertainty-certificate.jsonl').read_bytes();lines=raw.splitlines(keepends=True)
    data.need(len(baseline[1])==49 and len(lines)==63 and all(json.loads(v)['session']>parent['source_cursor'] for v in lines[49:])
        and b''.join(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n' for v in baseline[1])==b''.join(lines[:49]),
        'THOR_RUNTIME_ALL49_ADMITTED_PREFIX_BYTES_PRESERVE14_UNADMITTED_TAILS')
    return baseline
def run(parent,out,args,rows,observer,execution,*,spec,old):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import journal
    data.parent_contract(parent,spec);old,out=Path(old),Path(out);baseline=original_seed(old,parent,spec)
    api=api_module.api(parent,spec)
    exact(out/data.CATALOG,data.encoded(data.catalog()));exact(out/data.PRIMARY,data.encoded(data.primary_fact()))
    path,loaded=api.prepare(parent,out,'P03')
    data.need(path==out/api_module.OVERLAY and loaded.earliest_affected_session=='2020-01-23',
        'THOR_RUNTIME_REAL_PREPARED_UNCONSUMED_ORDINARY17_INPUT')
    neutral=adopter()(parent,out,args,rows,path,loaded.earliest_affected_session,api_module.DIRECTORY)
    actual,proof=boundary(out,parent,spec,rows);data.need(actual==neutral,'THOR_RUNTIME_ACTUAL_CANONICAL_NEUTRAL_BEFORE_FINANCIAL_MAIN')
    exact(out/BOUNDARY_REVIEW,data.encoded(proof))
    with seed_view(old,out,parent,neutral,spec,out,rows) as view:
        seed=seed_resolver(old,view,parent,neutral,spec,out,rows,baseline)
        code=bound_runtime('run',seed)(neutral,out,args,rows,observer,execution,spec=spec,old=view)
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    data.need(current['repairs']==neutral['repairs'] and current['run']['input_sha256']==neutral['run']['input_sha256'],
        'THOR_RUNTIME_FINANCIAL_SEGMENT_FULL17_UNCHANGED_AFTER_REAL_ADOPTION')
    return code
def review(parent,evidence,out,*,spec,old):
    from full_system_core import hosted
    hosted()
    from system_campaign_financial_resume import seed_rows
    old,evidence,out=Path(old),Path(evidence),Path(out);rows=seed_rows(old,parent,spec)
    baseline=original_seed(old,parent,spec);neutral,proof=boundary(evidence,parent,spec,rows)
    data.need(json.loads((evidence/BOUNDARY_REVIEW).read_bytes())==proof,'THOR_RUNTIME_INDEPENDENT_COMPLETE_NEUTRAL_BOUNDARY_REVIEW')
    with seed_view(old,out,parent,neutral,spec,evidence,rows) as view:
        seed=seed_resolver(old,view,parent,neutral,spec,evidence,rows,baseline)
        bound_runtime('review',seed)(neutral,evidence,out,spec=spec,old=view)
    exact(out/BOUNDARY_REVIEW,data.encoded(proof))
@contextmanager
def entry_context(module,spec,request):
    from full_system_core import hosted
    hosted()
    if not entry_authority(spec,request):yield;return
    old_run,old_review,old_overlay=uncertainty.run,uncertainty.review,module.factual_overlay_needed
    uncertainty.run=lambda *a,**k:run(*a,**k) if selected(k.get('spec')) else old_run(*a,**k)
    uncertainty.review=lambda *a,**k:review(*a,**k) if selected(k.get('spec')) else old_review(*a,**k)
    module.factual_overlay_needed=lambda target:True if selected(target) else old_overlay(target)
    try:yield
    finally:uncertainty.run,uncertainty.review,module.factual_overlay_needed=old_run,old_review,old_overlay
