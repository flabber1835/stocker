"""Exact latest own P02 continuation with a data-driven ordinary cash calendar."""
import argparse,json
from pathlib import Path
from full_system_core import hosted,arguments
from full_system_benchmark import need,save
from system_campaign_facts import sha
from system_campaign_factual_run import preflight,correlation_seed,SeededObservation,preserve_tails
from system_campaign_p02_retained_run import idempotent_dispatch
from system_campaign_own_origin import qualify as qualify_origin
from system_campaign_acceleration import Execution
from system_campaign_uncertainty_support import retained
from system_campaign_uncertainty_facts import evidence
from system_campaign_uncertainty_input import InputCodec
from system_campaign_uncertainty_context import SensorCertificate
from system_campaign_uncertainty_review import preserve_and_seed,validate_input_commitment
from system_campaign_uncertainty_archive import review as review_certificate,preserve as preserve_event_archive
from system_campaign_uncertainty_basis import basis
from system_campaign_sprint_facts import preserve_prior_facts,PACKET_SOURCE_PATH
from system_campaign_spring2020_cash_facts import preserve_sprint
from system_campaign_autumn2020_cash_facts import preserve_spring_cash
from system_campaign_2021_completions_facts import preserve_autumn_cash
from system_campaign_following_completions_facts import preserve_completions2021
from system_campaign_amendment_build import preserve_following
from system_campaign_future_amendment import FutureProjection,OUTER,INNER,INPUT,CUTOVER,PAYLOAD_NAME,OVERLAY_NAME,PROJECTION_NAME
from system_campaign_ordinary_registry import preserve as preserve_registered
from system_campaign_cash_calendar import build as build_calendar
from system_campaign_phase_timing import PhaseTiming
from system_campaign_replay_timing import ReplayTiming


def retained_amendment(old,out):
    from research.pooled_vacancy_funding import journal,runtime,backtest
    boundary=journal.read_checkpoint(old/'book/predecessor-checkpoints'/(OUTER+'.json.gz'))
    need((boundary['sha256'],boundary['run']['checkpoint_sha256'],boundary['run']['input_sha256'],boundary['source_cursor'])==
         (OUTER,INNER,INPUT,CUTOVER),'CALENDAR_ORIGINAL_AMENDMENT_BOUNDARY_RETAINED')
    restored=runtime.restore(boundary['run'],policy=boundary['base']['policy'],input_sha256=backtest.input_hash(boundary['base'],boundary['repairs']))
    need(runtime.checkpoint(restored)==boundary['run'],'CALENDAR_ORIGINAL_AMENDMENT_BOUNDARY_ROUNDTRIP')
    archive=out/'book/predecessor-checkpoints'/(OUTER+'.json.gz')
    if archive.exists():need(archive.read_bytes()==(old/'book/predecessor-checkpoints'/(OUTER+'.json.gz')).read_bytes(),'CALENDAR_EXISTING_BOUNDARY_BYTES')
    else:archive.write_bytes((old/'book/predecessor-checkpoints'/(OUTER+'.json.gz')).read_bytes())
    for name in (PAYLOAD_NAME,OVERLAY_NAME,PROJECTION_NAME):
        with (out/name).open('xb') as target:target.write((old/name).read_bytes())
    return FutureProjection(out,boundary)


def run(out,old,spec,request,timing):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    need(spec['arm']=='P02' and spec['run_id']==41129012614 and spec['selected_session']=='2021-08-31'
         and request['execution_mode']=='RETAINED_AMENDMENT_CASH_CALENDAR_SUFFIX','CALENDAR_EXACT_LATEST_OWN_PREFIX')
    cp=timing.call('old_prefix_preflight',preflight,spec,old,out,before='2021-09-14')
    need(cp['base']['sources'][PACKET_SOURCE_PATH]==request['qualified_packet_source_sha256'],'CALENDAR_PACKET_SOURCE_IDENTITY')
    timing.call('own_origin_qualification',qualify_origin,out,cp,out/'own-origin-qualification.json')
    v1,spin,alder,_=timing.call('retained_fact_hydration',retained,cp,old,out)
    (out/'hydrated-uncertainty-event.json').write_bytes((old/'hydrated-uncertainty-event.json').read_bytes())
    model=validate_input_commitment(old,cp)
    need(model==request['uncertainty_input_descriptor_sha256'],'CALENDAR_EXACT_OLD_MODEL_INPUT')
    seed=preserve_and_seed(old,out,cp)
    timing.call('old_interval_certificate_review',review_certificate,old,out/'old-uncertainty-certificate-review.json')
    preserve_event_archive(old,out)
    for fn in (preserve_prior_facts,preserve_sprint,preserve_spring_cash,preserve_autumn_cash,preserve_completions2021,preserve_following,preserve_registered):fn(cp,old,out)
    amendment=timing.call('retained_amendment_canonical_boundary',retained_amendment,old,out)
    old_hash,_=timing.call('old_effective_common_basis',basis,out,cp,amendment=amendment)
    need(old_hash==request['predecessor_common_basis_sha256'],'CALENDAR_EXACT_RETAINED_COMMON_BASIS')
    cash,loaded,overlay=timing.call('cash_calendar_hydration_and_canonical_load',build_calendar,cp,old,out,
        Path('/driver/system-campaign-cash-calendar-terminal-facts.json'))
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
    codec=InputCodec(evidence(out));source=json.loads((out/'hydrated-uncertainty-event.json').read_bytes())
    certificate=SensorCertificate(out,codec,alder.native,request['canonical_controller_sources'],seed=seed,event_source=source)
    args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
    with v1,spin,alder,idempotent_dispatch(alder),codec,amendment,certificate,observer:
        objects=[backtest.load_repair(out/'book/repairs'/d['filename'],resume_session=d['resume_session'],
            predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']) for d in cp['repairs']]
        need(amendment.active,'CALENDAR_RETAINED_AMENDMENT_ACTUALLY_ACTIVATED')
        timing.call('cumulative_canonical_cash_calendar_qualification',cash.qualify,loaded,objects,
            out/'cash-calendar-input-qualification.json',packet_source_sha256=request['qualified_packet_source_sha256'])
        descriptor=dict(filename=loaded.sha256+'.json',sha256=loaded.sha256,resume_session=cp['source_cursor'],
            predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
        (out/'book/repairs'/descriptor['filename']).write_bytes(overlay.read_bytes())
        h,v=timing.call('prospective_effective_common_basis',basis,out,{**cp,'repairs':[*cp['repairs'],descriptor]},amendment=amendment)
        save(out/'prospective-effective-common-basis.json',dict(sha256=h,value=v,not_a_committed_checkpoint_or_result=True))
        with Execution('FAST',signal_closes=1) as execution,ReplayTiming(out):
            code=timing.call('financial_driver_total',backtest.main,args+['--repair-overlay',str(overlay)])
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    need(current['base']==cp['base'] and current['repairs'][:-1]==cp['repairs']
         and current['repairs'][-1]['sha256']==loaded.sha256
         and current['run']['input_sha256']==backtest.input_hash(current['base'],current['repairs']),
         'CALENDAR_OWN_EXACT_ORDINARY_INPUT_SUCCESSOR')
    save(out/'uncertainty-economic-outcome.json',dict(session=current['source_cursor'],completed=current['completed'],
        complete=current['source_cursor']==backtest.END and current['completed']==2156,
        only_candidate='P02',new_origin=False,new_overlay=True,production_contacted=False))
    need(code==0,'CALENDAR_FINANCIAL_REFUSAL_PREFIX_PRESERVED')


def review(out,root,old,spec,timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    from system_campaign_factual_run import review as review_financial
    cp=journal.read_checkpoint(root/'book/checkpoint.json.gz')
    boundary=journal.read_checkpoint(root/'book/predecessor-checkpoints'/(OUTER+'.json.gz'))
    previous=journal.read_checkpoint(old/spec['selected_checkpoint'])
    amendment=FutureProjection(root,boundary)
    with InputCodec(evidence(root)):
        timing.call('canonical_financial_review',review_financial,out,root,old,spec)
        qualify_origin(root,previous,out/'independent-own-origin-qualification.json')
        timing.call('interval_certificate_review',review_certificate,root,out/'uncertainty-certificate-review.json')
        h,v=timing.call('common_basis_review',basis,root,cp,amendment=amendment)
    save(out/'common-factual-and-uncertainty-basis.json',dict(sha256=h,value=v))
    need(cp['base']==previous['base'] and cp['repairs'][:-1]==previous['repairs']
         and cp['repairs'][-1]['sha256']==sha((root/'cash-calendar-overlay.json').read_bytes()),
         'CALENDAR_REVIEW_ALL_OLD_DESCRIPTORS_UNCHANGED')
    for name in (PAYLOAD_NAME,OVERLAY_NAME,PROJECTION_NAME):
        need((root/name).read_bytes()==(old/name).read_bytes(),'CALENDAR_REVIEW_ORIGINAL_AMENDMENT_BYTES')
    need((root/'book/predecessor-checkpoints'/(OUTER+'.json.gz')).read_bytes()==
         (old/'book/predecessor-checkpoints'/(OUTER+'.json.gz')).read_bytes(),'CALENDAR_REVIEW_ORIGINAL_BOUNDARY_GZIP')
    save(out/'cash-calendar-lineage-review.json',dict(status='EXACT_OWN_SUFFIX_REVIEWED',
        original_amendment_boundary_and_bytes_preserved=True,all_old_descriptors_preserved=True,
        exact_latest_predecessor_preserved=True,source_and_parameters_unchanged=True,production_contacted=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True)
    p.add_argument('--spec',type=Path,required=True);p.add_argument('--request',type=Path,required=True)
    a=p.parse_args();spec=json.loads(a.spec.read_bytes())
    with PhaseTiming(Path('/out'),a.mode) as timing:
        if a.mode=='economic':run(Path('/out'),Path('/old'),spec,json.loads(a.request.read_bytes()),timing)
        else:review(Path('/out'),Path('/evidence'),Path('/old'),spec,timing)
