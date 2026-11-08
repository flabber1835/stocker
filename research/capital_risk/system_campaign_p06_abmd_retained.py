"""Actual admitted1259 P06 continuation; whole legacy worker bodies remain external."""
import ast,gzip,json
from contextlib import contextmanager,ExitStack
from copy import deepcopy
from pathlib import Path
from system_campaign_bounded_sensor_input import InputCodec,need,sha,digest
from system_campaign_abmd_bounded_catalog import evidence
from system_campaign_abmd_bounded_hydration import hydrate
import system_campaign_p06_abmd_models as models
import system_campaign_p06_abmd_lifecycle_data as initial
import system_campaign_p06_abmd_retained_data as data

HERE=Path(__file__).parent

def write_exact(path,raw):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():need(path.read_bytes()==raw,'P06_RETAINED_EXISTING_RESOURCE_BYTES')
    else:
        with path.open('xb') as stream:stream.write(raw)

def full(root,current):
    return models.validate_full(Path(root),current,initial.catalog())

def arithmetic():
    from full_system_core import hosted
    hosted()
    import system_campaign_p06_abmd_point_continuation as point
    import system_campaign_point_growth as growth
    import system_campaign_financial_additional_sensor as mixed
    result=point.arithmetic_sources(Path('/variant/sentinel/controller/median5.py').read_bytes(),
        Path(growth.__file__).read_bytes(),Path(mixed.__file__).read_bytes())
    growth.point_growth(());return result

def prior_event(root,current,rows):
    from system_campaign_bounded_sensor_event_review import permissions
    value=initial.catalog();allowed,resolutions=permissions(Path(root),rows,value,
        through=current['source_cursor'],input_descriptors=current['repairs'])
    need(allowed=={} and len(resolutions)==1 and rows[0]['bounded_event_basis']['selected'] is False,
         'P06_RETAINED_ONE_PRIOR_UNSELECTED_ABMD_EVENT_NO_NEW_PERMISSION')
    return resolutions[0]

def seed(root,current,spec):
    from full_system_core import hosted
    hosted()
    import system_campaign_p06_abmd_point_continuation as point
    from system_campaign_p06_abmd_initial_certificate import seed_reader
    data.admitted(spec);root=Path(root);full(root,current);arithmetic()
    need(current['sha256']==spec['outer_sha256'] and current['base']==spec['base']
         and current['repairs']==spec['repairs'],'P06_RETAINED_FINANCIAL_SEED_IS_ACTUAL_ADMITTED1259')
    initial.checked_resources(root/models.DIRECTORY/'prior-resources',initial.plan())
    raw=(root/'uncertainty-certificate.jsonl').read_bytes()
    need(sha(raw)==data.FULL_SHA and len(raw)==point.ENTIRE_OLD_PROOF['bytes'],
         'P06_RETAINED_WHOLE_OLD18_FILE_PRESERVED_NOT_USED_AS_SEED')
    rows=seed_reader(inherited_root=HERE)(root,current)
    resolution=prior_event(root,current,rows);archive=(root/resolution['actual']).read_bytes()
    hashes=json.loads((HERE/'system-campaign-uncertainty-integration-request.json').read_bytes())['canonical_controller_sources']
    point.qualify_seed_metadata(current,spec,rows,rows,[resolution],{},archive,hashes,hashes)
    qualified=(root/'branch-controller-qualification.json').read_bytes()
    expected=dict(passed=True,exact_controller_sources=hashes,ambiguous_comparisons_exhaustively_partitioned=True,
        all_possible_counters_retained_and_later_merged=True,actual_divergent_decisions_refused=True,historical_financial_sessions_advanced=0)
    need(qualified==data.encoded(expected) and len(hashes)==6
         and all(current['base']['sources'].get(n)==h and sha((Path('/variant')/n).read_bytes())==h for n,h in hashes.items()),
         'P06_RETAINED_ORIGINAL_QUALIFICATION_AND_ALL_SIX_PHYSICAL_SOURCES')
    oracle=(root/'stopped-review/uncertainty-certificate-review.json').read_bytes()
    need(sha(oracle)==spec['root_admission']['branch_uncertainty_proof']['hosted_canonical_transition_oracle_sha256'],
         'P06_RETAINED_ACTUAL_ADMITTED_PRIOR_HOSTED_ORACLE_BYTES')
    return hashes,rows,qualified,resolution

def preserve(root,out,current,rows,resolution):
    from full_system_core import hosted
    hosted();root,out=Path(root),Path(out)
    paths=[models.DIRECTORY+'/'+name for name in (models.PARENT,models.ORDINARY,models.TYPED)]
    paths += [models.DIRECTORY+'/prior-resources/'+name for name in initial.plan()['old_resources']]
    paths += [initial.BOUND_DOCUMENT,'hydrated-abmd-bounded-event.json','own-uncertainty-admission.json',
        'p06-abmd-initial-synthetic-gateway.json','future-input-qualification.json']
    for directory,doc in (('ordinary-input-adoption','future-financial-overlay.json'),(initial.BOUND_DIRECTORY,initial.BOUND_DOCUMENT)):
        paths += [directory+'/checkpoint.json.gz',directory+'/proof.json',directory+'-correlation-inputs.jsonl.gz']
    for name in paths:write_exact(out/name,(root/name).read_bytes())
    # The full visitor needs the genuine TRQ hydration at root, but the old
    # overlay is observation metadata and must not become a new root overlay.
    from research.pooled_vacancy_funding import journal
    import system_campaign_financial_future as future
    original=journal.read_checkpoint(root/models.DIRECTORY/models.PARENT)
    material=future.hydration_name(original);write_exact(out/material,(root/material).read_bytes())
    write_exact(out/resolution['actual'],(root/resolution['actual']).read_bytes())
    full_proof=(root/'uncertainty-certificate.jsonl').read_bytes()
    need(sha(full_proof)==data.FULL_SHA,'P06_RETAINED_OLD_WHOLE_PROOF_PROVENANCE')
    write_exact(out/data.PROVENANCE/data.FULL_PROOF,full_proof)
    for name in ('actual-future-event-2022-12-16.json','uncertainty-capture.json','p06-abmd-initial-synthetic-gateway.json'):
        write_exact(out/data.PROVENANCE/name,(root/name).read_bytes())
    write_exact(out/data.PROVENANCE/'prior-hosted-branch-review.json',(root/'stopped-review/uncertainty-certificate-review.json').read_bytes())
    write_exact(out/data.PROVENANCE/'prefix-preservation.json',data.encoded(dict(passed=True,
        parent_outer_sha256=current['sha256'],whole_old_proof_sha256=sha(full_proof),whole_old_proof_rows=18,
        active_committed_seed_rows=len(rows),active_committed_seed_sha256=sha(b''.join(
            json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n' for row in rows)),
        unadmitted_tail_rows_used=0,prior_transition_reexecuted=False)))

def ordinary_observer(root,out,current):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import journal
    import system_campaign_financial_future as future
    from system_campaign_retained_forward_cash import merge_terms
    root,out=Path(root),Path(out);catalog=initial.catalog()
    original=journal.read_checkpoint(root/models.DIRECTORY/models.PARENT)
    need(original['sha256']==catalog['parent_outer_sha256'] and original['sha256']!=current['sha256']
         and original['completed']==1238 and current['completed']==1259,
         'P06_RETAINED_OLD8_ONLY_OBSERVATION_METADATA_NOT_FINANCIAL_SEED')
    d=current['repairs'][8]
    doc,material=models.ordinary_material(root,original,d,lambda name:(root/name).read_bytes())
    folder=out/data.OBSERVATIONS;folder.mkdir(parents=True,exist_ok=True)
    raw=(root/'book/repairs'/d['filename']).read_bytes();write_exact(folder/future.OVERLAY,raw)
    name=future.hydration_name(original);write_exact(folder/name,(root/name).read_bytes())
    events=future.ActualEvents(folder,'P06',cp=original);merge_terms(events,initial.forward_terms(initial.plan()))
    need(events.scopes==[],'P06_RETAINED_ORIGINAL_ORDINARY_CASH_NO_SOURCE_ONLY_UPGRADE')
    write_exact(folder/'observer-origin.json',data.encoded(dict(schema='research.p06-existing-cash-observation-origin/1',
        actual_financial_seed=current['sha256'],observation_parent_only=original['sha256'],original_inputs=8,current_financial_inputs=10,
        original_TRQ_cash_per_share='31.575855485386988',overlay_sha256=sha(raw),material_sha256=sha((folder/name).read_bytes()),
        financial_checkpoint_adopted=False,original_observer_methods_unchanged=True)))
    return events

def run(parent,out,args,rows,observer,execution,*,spec,old,request):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    from system_campaign_p06_abmd_point_continuation import certificate_class
    need(data.selected(spec,request),'P06_RETAINED_EXPLICIT_ACTUAL_ADMITTED_FINANCIAL_REQUEST')
    old,out=Path(old),Path(out);hashes,retained,qualified,resolution=seed(old,parent,spec)
    preserve(old,out,parent,retained,resolution)
    write_exact(out/'branch-controller-qualification.json',qualified)
    write_exact(out/data.UNCHANGED,data.encoded(data.receipt(parent,spec)))
    value=initial.catalog();native,source=hydrate(value,out/'hydrated-abmd-bounded-event.json')
    codec=getattr(backtest.load_repair,'__self__',None)
    need(isinstance(codec,InputCodec) and codec.event==value['event'] and codec.evidence==evidence(value),
         'P06_RETAINED_ONLY_ACTUAL_ACTIVE_ABMD_CODEC_NO_OLD_B19_CODEC')
    typed=parent['repairs'][9]
    backtest.load_repair(out/'book/repairs'/typed['filename'],resume_session=typed['resume_session'],
        predecessor_checkpoint_sha256=typed['predecessor_checkpoint_sha256'])
    cls=certificate_class(value['event'],source,codec,native,inherited_root=HERE,retained_root=old,
        current_checkpoint=parent,admitted_spec=spec)
    certificate=cls(out,codec,native,hashes,seed=retained,event_source=source)
    events=ordinary_observer(old,out,parent)
    write_exact(out/'retained-proof-admission/seed.json',data.encoded(dict(parent_sha256=parent['sha256'],rows=6,
        chain_sha256=retained[-1]['chain_sha256'],possible_after=retained[-1]['possible_after'],
        prior_qualification_reexecuted=False,prior_proof_rows_reexecuted=0,financial_source_changed=False,new_date_or_model_adoption=False)))
    with certificate,observer,execution,events:code=backtest.main(args)
    actual=journal.read_checkpoint(out/'book/checkpoint.json.gz');full(out,actual)
    need(actual['base']==parent['base'] and actual['repairs']==parent['repairs']
         and actual['run']['input_sha256']==parent['run']['input_sha256'],'P06_RETAINED_FINANCE_USES_SAME_ACTUAL_FULL10_INPUT')
    return code

def review(parent,evidence_root,out,*,spec,old,request):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import journal
    from sentinel.controller import median5,champion_config
    import system_campaign_financial_branches as branches
    from system_campaign_p06_abmd_initial_certificate import seed_reader
    from system_campaign_p06_abmd_retained_suffix import review as suffix
    from system_campaign_uncertainty_review import committed_rows
    need(data.selected(spec,request),'P06_RETAINED_REVIEW_EXPLICIT_ACTUAL_ADMITTED_SEED')
    old,evidence_root,out=Path(old),Path(evidence_root),Path(out)
    hashes,retained,qualified,resolution=seed(old,parent,spec)
    need((evidence_root/'branch-controller-qualification.json').read_bytes()==qualified
         and (evidence_root/data.PROVENANCE/data.FULL_PROOF).read_bytes()==(old/'uncertainty-certificate.jsonl').read_bytes(),
         'P06_RETAINED_PRIOR_QUALIFICATION_AND_WHOLE18_PROVENANCE_BYTES')
    current=journal.read_checkpoint(evidence_root/'book/checkpoint.json.gz');full(evidence_root,current)
    data.review_unchanged(parent,current,evidence_root,spec)
    current_rows=seed_reader(inherited_root=HERE)(evidence_root,current)
    compact=lambda row:json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'
    need(len(current_rows)>=6 and b''.join(map(compact,current_rows[:6]))==b''.join(map(compact,retained)),
         'P06_RETAINED_WHOLE_LITERAL_SIX_PREFIX_NO_OLD_TAIL_SEED')
    following=prior_event(evidence_root,current,current_rows[:6])
    need(following['actual']==resolution['actual'] and (evidence_root/following['actual']).read_bytes()==(old/resolution['actual']).read_bytes(),
         'P06_RETAINED_ORIGINAL_DEC22_ARCHIVE_NAME_AND_BYTES_UNCHANGED')
    branches.qualify_surface(Path('/variant/sentinel/controller/champion_frozen.py').read_bytes(),Path('/variant/sentinel/controller/champion.py').read_bytes())
    financial={r['session']:r for r in committed_rows(evidence_root/'book',current,'daily') if r['session']>parent['source_cursor']}
    result=suffix(parent,current,retained,current_rows[6:],financial,median5=median5,champion_config=champion_config)
    from system_campaign_financial_compound_dispatch import review_retained as compound_review
    compound_review(evidence_root,current)
    write_exact(out/'uncertainty-certificate-review.json',data.encoded(dict(result,
        schema='research.retained-leadership-branch-suffix-review/1',passed=True,checkpoint_sha256=current['sha256'],
        parent_sha256=parent['sha256'],retained_rows=6,through=current['source_cursor'],prior_qualification_reexecuted=False,
        all_financial_watch_and_proof_identities_verified=True,full_period_complete=current['completed']==2156)))
    review_cash(parent,current,evidence_root,out)

def review_cash(parent,current,evidence_root,out):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import journal
    import system_campaign_financial_future as future
    from system_campaign_retained_forward_cash import verify_records
    from system_campaign_uncertainty_review import committed_rows
    original=journal.read_checkpoint(evidence_root/models.DIRECTORY/models.PARENT)
    _,material=models.ordinary_material(evidence_root,original,current['repairs'][8],lambda name:(evidence_root/name).read_bytes())
    folder=evidence_root/data.OBSERVATIONS
    need((folder/future.OVERLAY).read_bytes()==(evidence_root/'book/repairs'/current['repairs'][8]['filename']).read_bytes()
         and (folder/future.hydration_name(original)).read_bytes()==(evidence_root/future.hydration_name(original)).read_bytes(),
         'P06_RETAINED_OBSERVATION_ONLY_GENUINE_TRQ_RESOURCES')
    terms=material['terms']+initial.forward_terms(initial.plan());observed={}
    for path in folder.glob('actual-future-event-20*.json'):
        day=path.stem.removeprefix('actual-future-event-')
        if parent['source_cursor']<day<=current['source_cursor']:observed[day]=json.loads(path.read_bytes())
    rows=committed_rows(evidence_root/'book',current,'daily')
    # The TRQ event is before this segment. Its old proof remains provenance;
    # future cash events alone require a new actual original observer record.
    active=[t for t in terms if t['added']['session']>parent['source_cursor']]
    checked=verify_records(rows,current['run']['state']['ledger']['events'],observed,active,current['source_cursor'])
    write_exact(out/'p06-retained-original-cash-review.json',data.encoded(dict(passed=True,events=checked,
        original_TRQ_overlay_preserved_as_observation_metadata=True,financial_seed_is_actual_admitted1259=True,
        original_observer_methods_unchanged=True,financial_sessions_reexecuted=0)))

def expected_request(original,*,execution_mode,selected_arms,root_lookup):
    result=original();declared={}
    if execution_mode==data.MODE:
        for arm in selected_arms:
            spec=root_lookup(arm)
            if data.candidate(spec):
                declared[arm]=data.declaration(spec)
                need(result['admitted_checkpoints'][arm]==spec['outer_sha256'],
                     'P06_RETAINED_REQUEST_ACTUAL_ADMITTED_FINANCIAL_SEED')
                result['arm_inputs'][arm]['new_factual_overlay']=False
    result[data.FIELD]=declared
    for name in data.source_names():
        pin=sha((HERE/name).read_bytes());need(name not in result['sources'] or result['sources'][name]==pin,
            'P06_RETAINED_NO_SOURCE_PIN_REPLACEMENT');result['sources'][name]=pin
    return result

@contextmanager
def entry_context(module,spec,*,mode,old,out,request,evidence=None):
    from full_system_core import hosted
    hosted()
    if not data.selected(spec,request):yield;return
    need(mode in ('preflight','economic','review'),'P06_RETAINED_EXACT_LEGACY_MODE')
    import system_campaign_financial_partial as partial
    import system_campaign_financial_uncertainty as legacy
    import system_campaign_p06_abmd_reporting as reporting
    reporting.retained_source_contract(partial)
    old_models,old_context=partial.retained_models,partial.model_context
    old_phase,old_run,old_review=legacy.uncertainty_phase,legacy.run,legacy.review
    old_overlay=module.factual_overlay_needed
    def retained_models(root,current,target):
        if not data.candidate(target):return old_models(root,current,target)
        data.admitted(target);return full(root,current)['full_inputs']==10
    @contextmanager
    def model_context(root,current,target):
        if not data.candidate(target):
            with old_context(root,current,target):yield
            return
        data.admitted(target);value=initial.catalog()
        need(current['base']==target['base'] and current['repairs']==target['repairs']
             and current['run']['input_sha256']==target['input_sha256'],
             'P06_RETAINED_ONLY_FULL10_ACTUAL_SOURCE_EPOCH_CODEC')
        native,_=hydrate(value,Path(out)/'p06-retained-codec-source.json')
        with InputCodec(value['event'],evidence_for(value),native):yield
    partial.retained_models,partial.model_context=retained_models,model_context
    legacy.uncertainty_phase=lambda target:data.candidate(target) or old_phase(target)
    legacy.run=lambda *a,spec=None,old=None,**k:run(*a,spec=spec,old=old,request=request,**k) if data.candidate(spec) else old_run(*a,spec=spec,old=old,**k)
    legacy.review=lambda *a,spec=None,old=None,**k:review(*a,spec=spec,old=old,request=request,**k) if data.candidate(spec) else old_review(*a,spec=spec,old=old,**k)
    module.factual_overlay_needed=lambda target:False if data.candidate(target) else old_overlay(target)
    try:
        with ExitStack() as stack:
            if mode=='review':
                need(evidence is not None,'P06_RETAINED_REVIEW_REQUIRES_ACTUAL_EVIDENCE_ROOT')
                from research.pooled_vacancy_funding import journal
                current=journal.read_checkpoint(Path(evidence)/'book/checkpoint.json.gz')
                scratch=Path(out)/'p06-retained-review-codecs';scratch.mkdir()
                stack.enter_context(partial.financial_inputs(Path(evidence),current,scratch,spec))
            yield
    finally:
        partial.retained_models,partial.model_context=old_models,old_context
        legacy.uncertainty_phase,legacy.run,legacy.review=old_phase,old_run,old_review
        module.factual_overlay_needed=old_overlay

def evidence_for(value):return evidence(value)
