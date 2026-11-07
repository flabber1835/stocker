"""Hosted-only P06 initial 8→9→10 neutral input admission and independent proof."""
from contextlib import contextmanager,ExitStack
from copy import deepcopy
import ast,gzip,json
from pathlib import Path
from system_campaign_bounded_sensor_input import InputCodec,parse,need,sha,digest
from system_campaign_abmd_bounded_catalog import encoded,document,evidence
from system_campaign_abmd_bounded_hydration import hydrate
from system_campaign_abmd_bounded_preparation import write_exact
import system_campaign_p06_abmd_lifecycle_data as data

HERE=Path(__file__).parent
SOURCE='hydrated-abmd-bounded-event.json'

def controller_sources(cp):
    hashes=json.loads((HERE/'system-campaign-uncertainty-integration-request.json').read_bytes())['canonical_controller_sources']
    need(len(hashes)==6 and all(cp['base']['sources'].get(n)==h for n,h in hashes.items()),
         'P06_INITIAL_EXACT_SIX_CONTROLLER_SOURCES');return hashes

def require_preparation(root,catalog,hashes):
    root=Path(root);expected=data.expected_preparation(catalog,hashes)
    need((root/'abmd-zero-transition-preparation.json').read_bytes()==encoded(expected)
         and (root/'abmd-preparation-input.json').read_bytes()==encoded(document(catalog))
         and (root/'abmd-preparation-event-source.json').read_bytes()==encoded(catalog['market_source'])
         and sha((root/'abmd-synthetic-cloud/branch-controller-qualification.json').read_bytes())==expected['cloud_qualification_sha256'],
         'P06_INITIAL_EXACT_POSITIVE_ZERO_TRANSITION_PREPARATION')

def preflight_entry(old,out,spec,legacy):
    from full_system_core import hosted
    hosted();legacy(old,out,spec)
    if not data.selected(spec):return
    from system_campaign_abmd_bounded_preparation import prepare
    from system_campaign_financial_resume import strict_parent
    parent=strict_parent(json.loads(gzip.decompress((Path(old)/spec['selected_checkpoint']).read_bytes())),spec)
    return prepare(parent,out,spec,catalog_path=HERE/data.CATALOG,catalog_sha256=data.CATALOG_SHA)

def paused_adoption(*args):
    import system_campaign_financial_uncertainty as original
    raw=(HERE/'system_campaign_financial_uncertainty.py').read_bytes()
    scope=dict(vars(original));exec(compile(ast.Module(body=[data.adoption_tree(raw)],type_ignores=[]),
        '<whole-original-pause-with-additive-ABMD-filename>','exec'),scope)
    return scope['paused_own_adoption'](*args)

def stage_origin(old,out,spec,parent,source_plan):
    import system_campaign_p06_abmd_models as models
    need(parent['repairs']==source_plan['old_descriptors'] and parent['sha256']==source_plan['parent_outer_sha256'],
         'P06_INITIAL_EXACT_ORIGINAL_FULL_EIGHT_AND_RESOURCE_PLAN')
    target=Path(out)/models.DIRECTORY;target.mkdir()
    raw=(Path(old)/spec['selected_checkpoint']).read_bytes()
    need(dict(bytes=len(raw),sha256=sha(raw))==source_plan['parent_file']==spec['selected_file'],
         'P06_INITIAL_ACTUAL_AUTHENTIC_PARENT_GZIP_ONLY')
    write_exact(target/models.PARENT,raw)
    resources=target/'prior-resources';resources.mkdir()
    for name,raw in data.checked_resources(old,source_plan).items():write_exact(resources/name,raw)
    return target

def run(cp,out,args,rows,observer,execution,*,spec=None,old=None):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    import system_campaign_financial_future as future
    import system_campaign_financial_uncertainty as original
    import system_campaign_financial_branches as branches
    import system_campaign_p06_abmd_models as models
    from system_campaign_p06_abmd_initial_certificate import seed_reader,certificate_class
    from system_campaign_p06_abmd_gateway import qualify as qualify_gateway
    from system_campaign_retained_forward_cash import merge_terms
    need(data.selected(spec) and old is not None,'P06_INITIAL_EXACT_REGISTERED_SOURCE_ROOT_ONLY')
    out,old=Path(out),Path(old);catalog=data.catalog();source_plan=data.plan();hashes=controller_sources(cp)
    need(models.validate_full(old,cp,catalog)['full_inputs']==8 and seed_reader(inherited_root=HERE)(old,cp)==[],
         'P06_INITIAL_COMPLETE_EIGHT_WITHOUT_PRIOR_CERTIFICATE')
    require_preparation(out/'parent-preflight',catalog,hashes)
    origin=stage_origin(old,out,spec,cp,source_plan)
    branches.qualify(out,hashes)
    ordinary,loaded=future.prepare(cp,out,'P06')
    ordinary_material=json.loads((out/future.hydration_name(cp)).read_bytes())
    need(len(ordinary_material['terms'])==1 and ordinary_material['terms'][0]['ticker']=='TRQ'
         and ordinary_material['terms'][0]['added']['cash_per_share']==31.575855485386988,
         'P06_INITIAL_TRQ_EXACT_ORIGINAL_NORMALIZATION_AND_BATCH')
    ninth=original.paused_own_adoption(cp,out,args,rows,ordinary,loaded.earliest_affected_session,original.ORDINARY_ADOPTION)
    write_exact(origin/models.ORDINARY,(out/original.ORDINARY_ADOPTION/'checkpoint.json.gz').read_bytes())
    need(models.validate_full(out,ninth,catalog)['full_inputs']==9
         and future.review_input(cp,out,'P06')==loaded.earliest_affected_session,
         'P06_INITIAL_TRQ_REAL_NEUTRAL_REVIEW_BEFORE_TYPED_ADOPTION')
    events=future.ActualEvents(out,'P06',cp=cp);merge_terms(events,data.forward_terms(source_plan))
    native,event_source=hydrate(catalog,out/SOURCE)
    path=out/data.BOUND_DOCUMENT;write_exact(path,encoded(document(catalog,predecessor_checkpoint_sha256=ninth['run']['checkpoint_sha256'])))
    with InputCodec(catalog['event'],evidence(catalog),native) as codec:
        typed=parse(path,resume_session=ninth['source_cursor'],predecessor_checkpoint_sha256=ninth['run']['checkpoint_sha256'],
            expected_event=catalog['event'],expected_evidence=evidence(catalog))
        active=backtest.load_repair(path,resume_session=ninth['source_cursor'],predecessor_checkpoint_sha256=ninth['run']['checkpoint_sha256'])
        need(active in codec.objects and active.sha256==typed.sha256 and active.earliest_affected_session==catalog['event']['native_session'],
             'P06_INITIAL_ACTUAL_TYPED_PARSER_NATIVE_DAY_BOUNDARY')
        tenth=paused_adoption(ninth,out,args,rows,path,active.earliest_affected_session,data.BOUND_DIRECTORY)
        write_exact(origin/models.TYPED,(out/data.BOUND_DIRECTORY/'checkpoint.json.gz').read_bytes())
        need(models.validate_full(out,tenth,catalog)['full_inputs']==10,'P06_INITIAL_FULL_ACTUAL_TEN_BEFORE_FINANCE')
        qualify_gateway(out,catalog,codec,native,hashes,inherited_root=HERE)
        certificate=certificate_class(catalog['event'],event_source,codec,native,inherited_root=HERE)(out,codec,native,hashes,event_source=event_source)
        write_exact(out/'own-uncertainty-admission.json',encoded(dict(arm='P06',root_parent_sha256=cp['sha256'],
            ordinary_input_successor_sha256=ninth['sha256'],model_input_successor_sha256=tenth['sha256'],
            qualified_controller_sources=hashes,reused_frozen_controller_and_math_sources=True,
            new_branch_observer_qualification=True,diagnostic_state_adopted=False,prior_seed_rows=0,
            genuine_neutral_input_counts=[8,9,10],proof_kind='EXHAUSTIVE_REACHABLE_CANONICAL_DECISION_INVARIANCE',
            owned_or_ordered_right_valuation_authorized=False,representative_is_not_a_valuation=True)))
        with certificate,observer,execution,events:code=backtest.main(args)
        actual=journal.read_checkpoint(out/'book/checkpoint.json.gz');models.validate_full(out,actual,catalog)
    return code

def verify_origin(old,evidence_root,spec,parent):
    import system_campaign_p06_abmd_models as models
    source_plan=data.plan();origin=Path(evidence_root)/models.DIRECTORY
    need((origin/models.PARENT).read_bytes()==(Path(old)/spec['selected_checkpoint']).read_bytes(),
         'P06_INITIAL_REVIEW_ACTUAL_ORIGINAL_PARENT_BYTES')
    expected=data.checked_resources(old,source_plan)
    for name,raw in expected.items():need((origin/'prior-resources'/name).read_bytes()==raw,'P06_INITIAL_REVIEW_OLD_RESOURCES_UNCHANGED')
    need(parent['repairs']==source_plan['old_descriptors'],'P06_INITIAL_REVIEW_ALL_EIGHT_ORIGINAL_DESCRIPTORS')
    return source_plan

def review_cash(evidence_root,out,parent,current,source_plan):
    from system_campaign_retained_forward_cash import verify_records
    from system_campaign_uncertainty_review import committed_rows
    import system_campaign_financial_future as future
    terms=json.loads((evidence_root/future.hydration_name(parent)).read_bytes())['terms']+data.forward_terms(source_plan)
    observed={}
    for path in evidence_root.glob('actual-future-event-20*.json'):
        day=path.stem.removeprefix('actual-future-event-')
        if parent['source_cursor']<day<=current['source_cursor']:observed[day]=json.loads(path.read_bytes())
    checked=verify_records(committed_rows(evidence_root/'book',current,'daily'),current['run']['state']['ledger']['events'],
        observed,terms,current['source_cursor'])
    write_exact(out/'p06-original-cash-observer-review.json',encoded(dict(passed=True,events=checked,
        original_observer_methods_unchanged=True,old_event_resources_preserved=8,financial_sessions_reexecuted=0)))

def review(cp,evidence_root,out,*,spec=None,old=None):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import journal
    from sentinel.controller import median5,champion_config
    from system_campaign_uncertainty_math import RollingWitnessBounds
    import system_campaign_financial_branches as branches
    import system_campaign_financial_future as future
    import system_campaign_financial_uncertainty as original
    import system_campaign_p06_abmd_models as models
    from system_campaign_p06_abmd_initial_certificate import seed_reader
    from system_campaign_bounded_sensor_event_review import locate,event_basis
    need(data.selected(spec) and old is not None,'P06_INITIAL_REVIEW_EXACT_SOURCE_ROOT_ONLY')
    evidence_root,out=Path(evidence_root),Path(out);catalog=data.catalog();hashes=controller_sources(cp)
    source_plan=verify_origin(old,evidence_root,spec,cp)
    actual=journal.read_checkpoint(evidence_root/'book/checkpoint.json.gz')
    need(models.validate_full(evidence_root,actual,catalog)['full_inputs']==10,'P06_INITIAL_REVIEW_COMPLETE_TEN')
    earliest=future.review_input(cp,evidence_root,'P06')
    ninth=original.boundary(evidence_root,original.ORDINARY_ADOPTION,cp,future.OVERLAY,earliest)
    tenth=original.boundary(evidence_root,data.BOUND_DIRECTORY,ninth,data.BOUND_DOCUMENT,catalog['event']['native_session'])
    origin=evidence_root/models.DIRECTORY
    for name,directory in ((models.ORDINARY,original.ORDINARY_ADOPTION),(models.TYPED,data.BOUND_DIRECTORY)):
        need((origin/name).read_bytes()==(evidence_root/directory/'checkpoint.json.gz').read_bytes(),
             'P06_INITIAL_REVIEW_ORIGINAL_ACTUAL_NEUTRAL_GZIP_BYTES')
    from system_campaign_financial_resume import seed_rows
    original_rows=b''.join(seed_rows(Path(old),cp,spec))
    for directory in (original.ORDINARY_ADOPTION,data.BOUND_DIRECTORY):
        need(gzip.decompress((evidence_root/(directory+'-correlation-inputs.jsonl.gz')).read_bytes())==original_rows,
             'P06_INITIAL_REVIEW_ZERO_NEW_OBSERVATIONS_IN_BOTH_NEUTRAL_GATES')
    native,event_source=hydrate(catalog,out/'independent-abmd-bounded-event.json')
    need((out/'independent-abmd-bounded-event.json').read_bytes()==(evidence_root/SOURCE).read_bytes(),
         'P06_INITIAL_REVIEW_INDEPENDENT_FULL_ANNUAL_SOURCE_AND_ABSENCE')
    require_preparation(evidence_root/'parent-preflight',catalog,hashes)
    expected=data.expected_preparation(catalog,hashes)
    need((evidence_root/'branch-controller-qualification.json').read_bytes()==
         (evidence_root/'parent-preflight/abmd-synthetic-cloud/branch-controller-qualification.json').read_bytes(),
         'P06_INITIAL_REVIEW_EXACT_POSITIVE_ORIGINAL_CLOUD_QUALIFICATION')
    branches.qualify_surface(Path('/variant/sentinel/controller/champion_frozen.py').read_bytes(),Path('/variant/sentinel/controller/champion.py').read_bytes())
    need(all(sha((Path('/variant')/name).read_bytes())==h for name,h in hashes.items()),'P06_INITIAL_REVIEW_PHYSICAL_SIX_CONTROLLER_SOURCES')
    rows=seed_reader(inherited_root=HERE)(evidence_root,actual)
    review_cash(evidence_root,out,cp,actual,source_plan)
    if not rows:
        need(actual['source_cursor']<catalog['event']['effective_session'],'P06_INITIAL_REVIEW_UNPROVED_EVENT_NOT_ADMITTED')
        result=dict(status='PRE_EVENT_PREFIX_ONLY',rows=0,economic_invariance_established=False)
    else:
        permission,resolution=locate(evidence_root,rows[0],catalog,input_descriptors=actual['repairs'])
        before=journal.read_checkpoint(evidence_root/resolution['actual'])['run']['state']
        def qualified_initial_event(row,preimage):
            need(row['event_basis']==row['bounded_event_basis'],'P06_INITIAL_REVIEW_ORIGINAL_AND_NEW_BASIS_IDENTICAL')
            return event_basis(row,preimage,catalog)
        namespace=dict(vars(branches),rows=rows,before=before,cp=actual,
            DAY=catalog['event']['effective_session'],SID=catalog['event']['security_id'],
            math_state=RollingWitnessBounds(before['median5']['witness_nav']),possible=[branches.discrete(before['median5'])],
            representative=branches.discrete(before['median5']),median5=median5,champion_config=champion_config,
            financial={r['session']:r for n in ('formation','daily') for r in branches.committed_rows(evidence_root/'book',actual,n)},
            total=0,maximum=1,qualified_initial_event=qualified_initial_event)
        exec(compile(data.initial_review_tree((HERE/'system_campaign_financial_branches.py').read_bytes()),
            '<whole-original-B19-initial-induction-with-qualified-ABMD-preimage>','exec'),namespace)
        result=dict(schema='research.leadership-branch-uncertainty-independent-review/1',
            status='COMMITTED_PREFIX_ALL_REACHABLE_DECISIONS_IDENTICAL',rows=len(rows),exhaustive_leaves=namespace['total'],
            maximum_possible_states=namespace['maximum'],checkpoint_sha256=actual['sha256'],through=actual['source_cursor'],
            every_actual_financial_watch_and_proof_identity_bound=True,every_reachable_decision_identical=True,
            all_possible_controller_states_retained=True,representative_is_not_a_valuation=True,
            full_period_complete=actual['completed']==2156)
        write_exact(out/'branch-uncertainty-archive-resolution.json',encoded(resolution))
    write_exact(out/'uncertainty-certificate-review.json',encoded(result))
    write_exact(out/'own-uncertainty-input-boundaries-review.json',encoded(dict(passed=True,arm='P06',
        root_parent_sha256=cp['sha256'],ordinary_successor_sha256=ninth['sha256'],model_successor_sha256=tenth['sha256'],
        both_actual_gzip_boundaries_neutral=True,complete_input_bytes_independently_reconstructed=True,
        no_qualifier_state_adopted=True,prior_seed_rows=0,financial_sessions_reexecuted=0)))

@contextmanager
def entry_context(spec,*,evidence_root=None,out=None):
    """Exact initial-root routing around unchanged worker bodies; codec spans final review."""
    from full_system_core import hosted
    hosted()
    if not data.selected(spec):yield;return
    import system_campaign_financial_uncertainty as original
    prior_phase,prior_run,prior_review=original.uncertainty_phase,original.run,original.review
    original.uncertainty_phase=lambda value:data.selected(value) or prior_phase(value)
    original.run=lambda *a,spec=None,**k:run(*a,spec=spec,**k) if data.selected(spec) else prior_run(*a,spec=spec,**k)
    original.review=lambda *a,spec=None,**k:review(*a,spec=spec,**k) if data.selected(spec) else prior_review(*a,spec=spec,**k)
    try:
        with ExitStack() as stack:
            if evidence_root is not None:
                need(out is not None,'P06_INITIAL_REVIEW_CODEC_REQUIRES_INDEPENDENT_OUTPUT')
                catalog=data.catalog();native,_=hydrate(catalog,Path(out)/'entry-abmd-bounded-source.json')
                stack.enter_context(InputCodec(catalog['event'],evidence(catalog),native))
            yield
    finally:original.uncertainty_phase,original.run,original.review=prior_phase,prior_run,prior_review
