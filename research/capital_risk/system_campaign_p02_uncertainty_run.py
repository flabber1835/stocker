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
from system_campaign_spring2020_cash_facts import CashCompletionFacts, preserve_sprint
from system_campaign_facts import sha


def run(out, old, spec, request):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    need(spec['arm']=='P02' and spec['run_id']==41097856043 and spec['selected_session']=='2020-03-31'
         and request['execution_mode']=='SPRING2020_CASH_FACTUAL_SUFFIX','UNCERTAINTY_EXACT_SPRING2020_CASH_PREFIX')
    cp = preflight(spec,old,out,before='2020-04-16')
    need(cp['base']['sources'][PACKET_SOURCE_PATH]==request['qualified_packet_source_sha256'],
         'UNCERTAINTY_PACKET_SOURCE_BOUND_TO_SELECTED_CANONICAL_BASE')
    qualify_origin(out,cp,out/'own-origin-qualification.json')
    v1,spin,alder,_ = retained(cp,old,out)
    (out/'hydrated-uncertainty-event.json').write_bytes((old/'hydrated-uncertainty-event.json').read_bytes())
    model = validate_input_commitment(old,cp)
    need(model==request['uncertainty_input_descriptor_sha256'], 'UNCERTAINTY_EXACT_ADMITTED_INPUT_MODEL')
    prefix = preserve_and_seed(old,out,cp)
    review_certificate(old,out/'old-uncertainty-certificate-review.json')
    preserve_event_archive(old,out)
    preserve_prior_facts(cp,old,out)
    preserve_sprint(cp,old,out)
    old_hash,old_basis=basis(old,cp)
    need(dict(sha256=old_hash,value=old_basis)==json.loads((old/'common-factual-and-uncertainty-basis.json').read_bytes()),'SPRING2020_CASH_EXACT_RETAINED_COMMON_BASIS')
    facts=CashCompletionFacts('/driver/system-campaign-spring2020-cash-terminal-facts.json')
    facts.hydrate(out/'hydrated-spring2020-cash-terminal-catalog.json')
    overlay=out/'spring2020-cash-input-overlay.json'
    loaded=facts.overlay(cp,overlay)
    from research.pooled_vacancy_funding.repair import load_repair
    for cursor,predecessor in ((cp['source_cursor'],'0'*64),(facts.first_native,cp['run']['checkpoint_sha256'])):
        try:load_repair(overlay,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
        except ValueError:pass
        else:raise ValueError('REFUSED_SPRING2020_CASH_WRONG_PREDECESSOR_OR_CONSUMED_SESSION')
    observer = SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
    codec = InputCodec(evidence(out))
    event_source = json.loads((out/'hydrated-uncertainty-event.json').read_bytes())
    certificate = SensorCertificate(out,codec,alder.native,request['canonical_controller_sources'],seed=prefix,event_source=event_source)
    args = arguments(out/'book',True);args[args.index('--policy')+1] = cp['base']['policy']
    save(out/'uncertainty-economic-admission.json',dict(only_candidate='P02',predecessor_outer_sha256=cp['sha256'],
        input_sha256=cp['run']['input_sha256'],uncertainty_input_descriptor_sha256=model,
        historical_financial_source_changed=False,new_origin=False,new_overlay=True,
        actual_selected_cursor=cp['source_cursor'],original_packet_components_retained=19))
    with v1,spin,alder,idempotent_dispatch(alder),codec,certificate,observer:
        facts.qualify(loaded,out/'spring2020-cash-input-qualification.json',packet_source_sha256=request['qualified_packet_source_sha256'])
        with Execution('FAST',signal_closes=1) as execution:
            code = backtest.main(args+['--repair-overlay',str(overlay)])
    save(out/'acceleration-proof.json',execution.proof())
    save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    need(current['base']==cp['base'] and current['repairs'][:-1]==cp['repairs']
         and current['repairs'][-1]['sha256']==loaded.sha256
         and current['run']['input_sha256']==backtest.input_hash(current['base'],current['repairs']),
         'UNCERTAINTY_EXACT_OWN_SPRING2020_CASH_INPUT_SUCCESSOR')
    save(out/'uncertainty-economic-outcome.json',dict(session=current['source_cursor'],completed=current['completed'],
        complete=current['source_cursor']==backtest.END and current['completed']==2156,
        only_candidate='P02',new_origin=False,new_overlay=True,production_contacted=False))
    need(code==0,'UNCERTAINTY_FINANCIAL_REFUSAL_PREFIX_PRESERVED')


def review(out, root, old, spec):
    hosted()
    from research.pooled_vacancy_funding import journal
    from system_campaign_factual_run import review as review_financial
    cp=journal.read_checkpoint(root/'book/checkpoint.json.gz')
    with InputCodec(evidence(root)):
        review_financial(out,root,old,spec)
        qualify_origin(root,journal.read_checkpoint(old/spec['selected_checkpoint']),out/'independent-own-origin-qualification.json')
        review_certificate(root,out/'uncertainty-certificate-review.json')
        value_hash,value=basis(root,cp)
    save(out/'common-factual-and-uncertainty-basis.json',dict(sha256=value_hash,value=value))
    need(sha((root/'book/predecessor-checkpoints'/(spec['outer_sha256']+'.json.gz')).read_bytes())==spec['selected_file']['sha256'],
         'UNCERTAINTY_EXACT_QUALIFIED_PREDECESSOR_GZIP')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True)
    p.add_argument('--spec',type=Path,required=True);p.add_argument('--request',type=Path,required=True)
    a=p.parse_args();spec=json.loads(a.spec.read_bytes())
    if a.mode=='economic':run(Path('/out'),Path('/old'),spec,json.loads(a.request.read_bytes()))
    else:review(Path('/out'),Path('/evidence'),Path('/old'),spec)
