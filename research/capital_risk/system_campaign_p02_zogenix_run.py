"""Exact own February28 P02 suffix with a joint unowned sensor proof."""
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
from system_campaign_uncertainty_review import preserve_and_seed,validate_input_commitment
from system_campaign_uncertainty_archive import review as review_old_certificate,preserve as preserve_event_archive
from system_campaign_zogenix_sensor import SensorCertificate
from system_campaign_zogenix_input import InputCodec as ZogenixCodec
from system_campaign_zogenix_facts import hydrate,overlay,evidence as zogenix_evidence,PRIVATE
from system_campaign_zogenix_gate import qualify
from system_campaign_zogenix_review import review as review_certificate
from system_campaign_zogenix_basis import basis
from system_campaign_sprint_facts import preserve_prior_facts,PACKET_SOURCE_PATH
from system_campaign_spring2020_cash_facts import preserve_sprint
from system_campaign_autumn2020_cash_facts import preserve_spring_cash
from system_campaign_2021_completions_facts import preserve_autumn_cash
from system_campaign_following_completions_facts import preserve_completions2021
from system_campaign_amendment_build import preserve_following
from system_campaign_future_amendment import FutureProjection,OUTER,PAYLOAD_NAME,OVERLAY_NAME,PROJECTION_NAME
from system_campaign_ordinary_registry import preserve as preserve_registered
from system_campaign_phase_timing import PhaseTiming
from system_campaign_replay_timing import ReplayTiming
from system_campaign_p02_calendar_run import retained_amendment


def run(out,old,spec,request,timing):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    need(spec['arm']=='P02' and spec['run_id']==41147701200 and spec['selected_session']=='2022-02-28'
         and request['execution_mode']=='JOINT_CERTIFIED_ZOGENIX_SENSOR_SUFFIX','ZOGENIX_EXACT_LATEST_OWN_PREFIX')
    cp=timing.call('old_prefix_preflight',preflight,spec,old,out,before='2022-03-04')
    need(cp['base']['sources'][PACKET_SOURCE_PATH]==request['qualified_packet_source_sha256'],'ZOGENIX_PACKET_SOURCE_IDENTITY')
    timing.call('own_origin_qualification',qualify_origin,out,cp,out/'own-origin-qualification.json')
    v1,spin,alder,_=timing.call('retained_fact_hydration',retained,cp,old,out)
    (out/'hydrated-uncertainty-event.json').write_bytes((old/'hydrated-uncertainty-event.json').read_bytes())
    need(validate_input_commitment(old,cp)==request['uncertainty_input_descriptor_sha256'],'ZOGENIX_EXACT_OLD_MODEL')
    seed=preserve_and_seed(old,out,cp)
    timing.call('old_interval_certificate_review',review_old_certificate,old,out/'old-uncertainty-certificate-review.json')
    preserve_event_archive(old,out)
    for fn in (preserve_prior_facts,preserve_sprint,preserve_spring_cash,preserve_autumn_cash,preserve_completions2021,preserve_following,preserve_registered):fn(cp,old,out)
    amendment=timing.call('retained_amendment_canonical_boundary',retained_amendment,old,out)
    old_hash,_=timing.call('old_effective_common_basis',basis,out,cp,amendment=amendment)
    need(old_hash==request['predecessor_common_basis_sha256'],'ZOGENIX_EXACT_RETAINED_COMMON_BASIS')
    native=timing.call('zogenix_frozen_source_hydration',hydrate,old,out)
    path=overlay(cp,out);zcodec=ZogenixCodec(zogenix_evidence(out),native);codec=InputCodec(evidence(out))
    source=json.loads((out/'hydrated-uncertainty-event.json').read_bytes());zsource=json.loads((out/PRIVATE).read_bytes())
    certificate=SensorCertificate(out,codec,alder.native,request['canonical_controller_sources'],seed=seed,event_source=source,
        zogenix_codec=zcodec,zogenix_native=native,zogenix_source=zsource)
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
    args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
    with v1,spin,alder,idempotent_dispatch(alder),zcodec,codec,amendment:
        objects=[backtest.load_repair(out/'book/repairs'/d['filename'],resume_session=d['resume_session'],
            predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']) for d in cp['repairs']]
        loaded=backtest.load_repair(path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
        need(amendment.active,'ZOGENIX_ORIGINAL_AMENDMENT_ACTUALLY_ACTIVATED')
        timing.call('zogenix_actual_canonical_qualification',qualify,out,cp,objects,loaded,zcodec,request)
        # Qualify against the unwrapped canonical terminal/recovery functions;
        # only then install the certificate and enter actual market replay.
        with certificate,observer,Execution('FAST',signal_closes=1) as execution,ReplayTiming(out):
            code=timing.call('financial_driver_total',backtest.main,args+['--repair-overlay',str(path)])
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    need(current['base']==cp['base'] and current['repairs'][:-1]==cp['repairs']
         and current['repairs'][-1]['sha256']==loaded.sha256
         and current['run']['input_sha256']==backtest.input_hash(current['base'],current['repairs']),
         'ZOGENIX_OWN_EXACT_TYPED_INPUT_SUCCESSOR')
    save(out/'uncertainty-economic-outcome.json',dict(session=current['source_cursor'],completed=current['completed'],
        complete=current['source_cursor']==backtest.END and current['completed']==2156,
        only_candidate='P02',new_origin=False,new_overlay=True,production_contacted=False))
    need(code==0,'ZOGENIX_FINANCIAL_REFUSAL_PREFIX_PRESERVED')


def review(out,root,old,spec,timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    from system_campaign_factual_run import review as review_financial
    cp=journal.read_checkpoint(root/'book/checkpoint.json.gz');previous=journal.read_checkpoint(old/spec['selected_checkpoint'])
    boundary=journal.read_checkpoint(root/'book/predecessor-checkpoints'/(OUTER+'.json.gz'))
    amendment=FutureProjection(root,boundary)
    native=timing.call('independent_zogenix_source_hydration',hydrate,old,out)
    need((out/PRIVATE).read_bytes()==(root/PRIVATE).read_bytes(),'ZOGENIX_INDEPENDENT_HYDRATION_BYTES')
    with ZogenixCodec(zogenix_evidence(root),native),InputCodec(evidence(root)):
        timing.call('canonical_financial_review',review_financial,out,root,old,spec)
        qualify_origin(root,previous,out/'independent-own-origin-qualification.json')
        timing.call('joint_interval_certificate_review',review_certificate,root,old,spec,out/'uncertainty-certificate-review.json')
        h,v=timing.call('common_basis_review',basis,root,cp,amendment=amendment)
    save(out/'common-factual-and-uncertainty-basis.json',dict(sha256=h,value=v))
    need(cp['base']==previous['base'] and cp['repairs'][:-1]==previous['repairs']
         and cp['repairs'][-1]['sha256']==sha((root/'zogenix-sensor-input.json').read_bytes()),
         'ZOGENIX_REVIEW_ALL_26_OLD_DESCRIPTORS_UNCHANGED')
    for name in (PAYLOAD_NAME,OVERLAY_NAME,PROJECTION_NAME):
        need((root/name).read_bytes()==(old/name).read_bytes(),'ZOGENIX_ORIGINAL_AMENDMENT_BYTES')
    need((root/'book/predecessor-checkpoints'/(OUTER+'.json.gz')).read_bytes()==
         (old/'book/predecessor-checkpoints'/(OUTER+'.json.gz')).read_bytes(),'ZOGENIX_ORIGINAL_BOUNDARY_GZIP')
    save(out/'joint-sensor-lineage-review.json',dict(status='EXACT_OWN_SUFFIX_REVIEWED',
        original_amendment_boundary_and_bytes_preserved=True,all_old_descriptors_preserved=True,
        exact_latest_predecessor_preserved=True,source_and_parameters_unchanged=True,
        original_math_and_comparison_sources_unchanged=True,production_contacted=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True)
    p.add_argument('--spec',type=Path,required=True);p.add_argument('--request',type=Path,required=True)
    a=p.parse_args();spec=json.loads(a.spec.read_bytes())
    with PhaseTiming(Path('/out'),a.mode) as timing:
        if a.mode=='economic':run(Path('/out'),Path('/old'),spec,json.loads(a.request.read_bytes()),timing)
        else:review(Path('/out'),Path('/evidence'),Path('/old'),spec,timing)
