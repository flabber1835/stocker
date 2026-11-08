"""Exact own-input P02 suffix with certified uncertain sensor consideration."""
import argparse
import json
from pathlib import Path

from full_system_core import hosted, arguments
from full_system_benchmark import need, save
from system_campaign_factual_run import preflight, correlation_seed, SeededObservation, preserve_tails
from system_campaign_p02_retained_run import idempotent_dispatch
from system_campaign_own_origin import qualify as qualify_origin
from system_campaign_acceleration import Execution
from system_campaign_uncertainty_support import retained
from system_campaign_uncertainty_facts import evidence
from system_campaign_uncertainty_input import InputCodec
from system_campaign_uncertainty_context import SensorCertificate
from system_campaign_uncertainty_review import preserve_and_seed, validate_input_commitment
from system_campaign_uncertainty_archive import review as review_certificate, preserve as preserve_event_archive
from system_campaign_uncertainty_basis import basis
from system_campaign_sprint_facts import preserve_prior_facts, PACKET_SOURCE_PATH
from system_campaign_spring2020_cash_facts import preserve_sprint
from system_campaign_autumn2020_cash_facts import preserve_spring_cash
from system_campaign_2021_completions_facts import preserve_autumn_cash
from system_campaign_following_completions_facts import preserve_completions2021
from system_campaign_amendment_build import build as build_amendment,preserve_following
from system_campaign_amendment_gate import qualify as qualify_amendment
from system_campaign_future_amendment import FutureProjection,OVERLAY_NAME
from system_campaign_facts import sha
from system_campaign_phase_timing import PhaseTiming
from system_campaign_replay_timing import ReplayTiming


def run(out, old, spec, request, timing):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    need(spec['arm']=='P02' and spec['run_id']==41120539423 and spec['selected_session']=='2021-03-31'
         and request['execution_mode']=='FUTURE_INPUT_AMENDMENT_CASH_BATCH_SUFFIX','UNCERTAINTY_EXACT_FUTURE_AMENDMENT_PREFIX')
    cp = timing.call('old_prefix_preflight',preflight,spec,old,out,before='2021-04-15')
    need(cp['base']['sources'][PACKET_SOURCE_PATH]==request['qualified_packet_source_sha256'],
         'UNCERTAINTY_PACKET_SOURCE_BOUND_TO_SELECTED_CANONICAL_BASE')
    timing.call('own_origin_qualification',qualify_origin,out,cp,out/'own-origin-qualification.json')
    v1,spin,alder,_ = timing.call('retained_fact_hydration',retained,cp,old,out)
    (out/'hydrated-uncertainty-event.json').write_bytes((old/'hydrated-uncertainty-event.json').read_bytes())
    model = validate_input_commitment(old,cp)
    need(model==request['uncertainty_input_descriptor_sha256'], 'UNCERTAINTY_EXACT_ADMITTED_INPUT_MODEL')
    prefix = preserve_and_seed(old,out,cp)
    timing.call('old_interval_certificate_review',review_certificate,old,out/'old-uncertainty-certificate-review.json')
    preserve_event_archive(old,out)
    preserve_prior_facts(cp,old,out)
    preserve_sprint(cp,old,out)
    preserve_spring_cash(cp,old,out)
    preserve_autumn_cash(cp,old,out)
    preserve_completions2021(cp,old,out)
    preserve_following(cp,old,out)
    try:timing.call('original_strict_common_basis_refusal',basis,old,cp)
    except ValueError as error:
        need(str(error)=='REFUSED_FULL_SYSTEM_COMMON_BASIS_NO_CONFLICTING_TERM',
             'AMENDMENT_ONLY_EXACT_EXPECTED_OLD_COMMON_BASIS_REFUSAL')
        save(out/'original-common-basis-refusal.json',dict(original_error=str(error),
             old_basis_passed=False,financial_prefix_admission_only=True,production_contacted=False))
    else:raise ValueError('REFUSED_AMENDMENT_ORIGINAL_CONFLICT_FALSIFIER_DID_NOT_REFUSE')
    cash,loaded,amendment=timing.call('new_cash_hydration_and_canonical_input_load',build_amendment,cp,old,out)
    overlay=out/OVERLAY_NAME
    observer = SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
    codec = InputCodec(evidence(out))
    event_source = json.loads((out/'hydrated-uncertainty-event.json').read_bytes())
    certificate = SensorCertificate(out,codec,alder.native,request['canonical_controller_sources'],seed=prefix,event_source=event_source)
    args = arguments(out/'book',True);args[args.index('--policy')+1] = cp['base']['policy']
    save(out/'uncertainty-economic-admission.json',dict(only_candidate='P02',predecessor_outer_sha256=cp['sha256'],
        input_sha256=cp['run']['input_sha256'],uncertainty_input_descriptor_sha256=model,
        historical_financial_source_changed=False,new_origin=False,new_overlay=True,
        actual_selected_cursor=cp['source_cursor'],original_packet_components_retained=len(cp['repairs']),
        old_global_basis_refused=True,new_explicit_future_projection=True))
    with v1,spin,alder,idempotent_dispatch(alder),codec,amendment,certificate,observer:
        loaded=timing.call('cumulative_canonical_amendment_and_cash_qualification',qualify_amendment,
            cp,out,cash,amendment,request['qualified_packet_source_sha256'])
        # Derived semantic proof only: no checkpoint, state or old journal edit.
        descriptor=dict(filename=loaded.sha256+'.json',sha256=loaded.sha256,
            resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
        (out/'book/repairs'/descriptor['filename']).write_bytes(overlay.read_bytes())
        prospective={**cp,'repairs':[*cp['repairs'],descriptor]}
        h,v=timing.call('prospective_effective_common_basis',basis,out,prospective,amendment=amendment)
        save(out/'prospective-effective-common-basis.json',dict(sha256=h,value=v,
             not_a_committed_checkpoint_or_result=True))
        with Execution('FAST',signal_closes=1) as execution,ReplayTiming(out):
            code = timing.call('financial_driver_total',backtest.main,args+['--repair-overlay',str(overlay)])
    save(out/'acceleration-proof.json',execution.proof())
    save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    need(current['base']==cp['base'] and current['repairs'][:-1]==cp['repairs']
         and current['repairs'][-1]['sha256']==loaded.sha256
         and current['run']['input_sha256']==backtest.input_hash(current['base'],current['repairs']),
         'UNCERTAINTY_EXACT_OWN_FUTURE_AMENDMENT_INPUT_SUCCESSOR')
    save(out/'uncertainty-economic-outcome.json',dict(session=current['source_cursor'],completed=current['completed'],
        complete=current['source_cursor']==backtest.END and current['completed']==2156,
        only_candidate='P02',new_origin=False,new_overlay=True,production_contacted=False))
    need(code==0,'UNCERTAINTY_FINANCIAL_REFUSAL_PREFIX_PRESERVED')


def review(out, root, old, spec, timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    from system_campaign_factual_run import review as review_financial
    cp=journal.read_checkpoint(root/'book/checkpoint.json.gz')
    boundary=journal.read_checkpoint(old/spec['selected_checkpoint'])
    amendment=FutureProjection(root,boundary)
    with InputCodec(evidence(root)):
        timing.call('canonical_financial_review',review_financial,out,root,old,spec)
        qualify_origin(root,journal.read_checkpoint(old/spec['selected_checkpoint']),out/'independent-own-origin-qualification.json')
        timing.call('interval_certificate_review',review_certificate,root,out/'uncertainty-certificate-review.json')
        value_hash,value=timing.call('common_basis_review',basis,root,cp,amendment=amendment)
    save(out/'common-factual-and-uncertainty-basis.json',dict(sha256=value_hash,value=value))
    need(sha((root/'book/predecessor-checkpoints'/(spec['outer_sha256']+'.json.gz')).read_bytes())==spec['selected_file']['sha256'],
         'UNCERTAINTY_EXACT_QUALIFIED_PREDECESSOR_GZIP')
    need(cp['base']==boundary['base'] and cp['repairs'][:-1]==boundary['repairs']
         and cp['repairs'][-1]['sha256']==amendment.activation_sha,'AMENDMENT_REVIEW_OLD_DESCRIPTORS_AND_NEW_EXPLICIT_INPUT')
    save(out/'future-input-amendment-lineage-review.json',dict(original_archived_inputs_unchanged=True,
        exact_own_predecessor_preserved=True,source_and_parameters_unchanged=True,
        prospective_only_future_APHA_projection=True,old_global_basis_refusal_retained=True,
        new_effective_basis_sha256=value_hash,production_contacted=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True)
    p.add_argument('--spec',type=Path,required=True);p.add_argument('--request',type=Path,required=True)
    a=p.parse_args();spec=json.loads(a.spec.read_bytes())
    with PhaseTiming(Path('/out'),a.mode) as timing:
        if a.mode=='economic':run(Path('/out'),Path('/old'),spec,json.loads(a.request.read_bytes()),timing)
        else:review(Path('/out'),Path('/evidence'),Path('/old'),spec,timing)
