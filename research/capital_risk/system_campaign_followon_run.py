"""Resume own pre-December checkpoint with common verified merger inputs."""
import argparse,json
from pathlib import Path
from full_system_core import arguments,hosted
from full_system_benchmark import need,save
from system_campaign_acceleration import Execution
from system_campaign_facts import FactualInputs,sha
from system_campaign_factual_run import preflight,correlation_seed,SeededObservation,preserve_tails,review as canonical_review
from system_campaign_yearend_run import retained_eight,YEAREND
from system_campaign_yearend_facts import YearendFacts
from system_campaign_followon_facts import FollowonFacts
from system_campaign_parsley_facts import ParsleyFacts
from system_campaign_terminal_run import merge_future_documents
from system_campaign_own_origin import qualify as qualify_origin

FOLLOWON='research:system-optimization-002/followon-terminal-catalog/1'


def run(out,old,spec):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    from research.pooled_vacancy_funding.repair import load_repair
    cp=preflight(spec,old,out,before='2018-12-19')
    need(cp['source_cursor']=='2018-11-30' and spec['arm'] in ('P01','P02','P04','P07'),
         'FOLLOWON_OWN_EXACT_PRE_EVENT_BOUNDARY')
    need(json.loads((old/'source-bindings.json').read_bytes())['parameters']['family']=='CORE',
         'FOLLOWON_ONLY_UNCHANGED_CORE_PARAMETERS')
    qualify_origin(out,cp,out/'own-origin-qualification.json')
    refs=[]
    for descriptor in cp['repairs']:
        raw=(old/'book/repairs'/descriptor['filename']).read_bytes()
        need(sha(raw)==descriptor['sha256'],'FOLLOWON_RETAINED_REPAIR_BYTES')
        refs.extend(json.loads(raw)['source_evidence'])
    need(not any(v['reference'] in (YEAREND,FOLLOWON) for v in refs),
         'FOLLOWON_EXACT_EIGHT_GROUP_PREDECESSOR')
    retained_eight(refs,old,out)
    v1=FactualInputs('/driver/system-campaign-factual-catalog.json');v1.hydrate(out/'independent-v1-hydration.json')
    need(sha((out/'independent-v1-hydration.json').read_bytes())==sha((out/'hydrated-factual-catalog.json').read_bytes()),
         'FOLLOWON_IDENTICAL_RETAINED_V1_HYDRATION')
    yearend=YearendFacts('/driver/system-campaign-yearend-terminal-facts.json')
    yearend.hydrate(out/'hydrated-yearend-terminal-catalog.json')
    need((out/'hydrated-yearend-terminal-catalog.json').read_bytes()==(old/'hydrated-yearend-terminal-catalog.json').read_bytes(),
         'FOLLOWON_EXACT_ALREADY_QUALIFIED_YEAREND_FACTS')
    yearend.overlay(cp,out/'yearend-component.json')
    facts=FollowonFacts('/driver/system-campaign-followon-terminal-facts.json')
    facts.hydrate(out/'hydrated-followon-terminal-catalog.json');facts.overlay(cp,out/'followon-component.json')
    parsley=ParsleyFacts('/driver/system-campaign-parsley-terminal-facts.json')
    parsley.hydrate(out/'hydrated-parsley-terminal-catalog.json');parsley.overlay(cp,out/'parsley-component.json')
    overlay=out/'followon-input-overlay.json'
    document=merge_future_documents(json.loads((out/'yearend-component.json').read_bytes()),
                                    json.loads((out/'followon-component.json').read_bytes()))
    save(overlay,merge_future_documents(document,json.loads((out/'parsley-component.json').read_bytes())))
    loaded=load_repair(overlay,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    for cursor,predecessor in ((cp['source_cursor'],'0'*64),(loaded.earliest_affected_session,cp['run']['checkpoint_sha256'])):
        try:load_repair(overlay,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
        except ValueError:pass
        else:raise ValueError('REFUSED_FOLLOWON_PARSER_FALSIFIER')
    save(out/'followon-overlay-admission.json',{'own_predecessor':cp['run']['checkpoint_sha256'],
        'overlay_sha256':loaded.sha256,'prior_components_retained_exactly':8,'components_added':3,
        'wrong_predecessor_and_consumed_session_refused':True,'source_conversion':False,'new_origin':False})
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
    args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
    with v1:
        yearend.qualify(loaded,out/'yearend-input-qualification.json')
        facts.qualify(loaded,out/'followon-input-qualification.json')
        parsley.qualify(loaded,out/'parsley-input-qualification.json')
        with observer:
            with Execution('FAST',signal_closes=1) as execution:code=backtest.main(args+['--repair-overlay',str(overlay)])
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    save(out/'followon-outcome.json',{'session':current['source_cursor'],'completed':current['completed'],
        'complete':current['source_cursor']==backtest.END and current['completed']==2156,
        'new_origin':False,'financial_source_changed':False,'production_contacted':False})
    need(code==0,'FOLLOWON_REFUSED_PREFIX_PRESERVED')


def review(out,evidence,old,spec):
    canonical_review(out,evidence,old,spec)
    from research.pooled_vacancy_funding import journal
    selected=journal.read_checkpoint(old/spec['selected_checkpoint'])
    qualify_origin(evidence,selected,out/'independent-own-origin-qualification.json')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True);p.add_argument('--spec',type=Path,required=True)
    a=p.parse_args();hosted();spec=json.loads(a.spec.read_bytes())
    if a.mode=='economic':run(Path('/out'),Path('/old'),spec)
    else:review(Path('/out'),Path('/evidence'),Path('/old'),spec)
