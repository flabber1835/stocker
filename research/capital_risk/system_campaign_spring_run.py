"""Same own book after an authenticated spring factual boundary."""
import argparse,json
from contextlib import nullcontext
from pathlib import Path
from full_system_core import arguments,hosted
from full_system_benchmark import need,save
from system_campaign_acceleration import Execution
from system_campaign_facts import FactualInputs,sha
from system_campaign_factual_run import preflight,correlation_seed,SeededObservation,preserve_tails,review
from system_campaign_spring_facts import SpringFacts
SPRING='research:system-optimization-002/spring-terminal-catalog/1'
WINTER='research:system-optimization-002/corrected-winter-cash-catalog/1'


def prepare_overlay(cp,old,out,facts):
    from research.pooled_vacancy_funding.repair import load_repair
    references=[]
    for descriptor in cp['repairs']:
        raw=(old/'book/repairs'/descriptor['filename']).read_bytes()
        need(sha(raw)==descriptor['sha256'],'SPRING_RETAINED_REPAIR_BYTES')
        references.extend(json.loads(raw)['source_evidence'])
    need(not any(v['reference'] in (SPRING,'research:system-optimization-002/march-cash-catalog/1')
                 for v in references),'SPRING_NO_DUPLICATE_OR_SUPERSEDED_INPUT')
    winter_sha=sha(Path('/driver/system-campaign-corrected-winter-facts.json').read_bytes())
    need([v['sha256'] for v in references if v['reference']==WINTER]==[winter_sha],
         'SPRING_RETAINS_CORRECTED_WINTER_FACTS')
    overlay=out/'spring-terminal-overlay.json';loaded=facts.overlay(cp,overlay)
    for cursor,predecessor in ((cp['source_cursor'],'0'*64),
                               (loaded.earliest_affected_session,cp['run']['checkpoint_sha256'])):
        try:load_repair(overlay,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
        except ValueError:pass
        else:raise ValueError('REFUSED_SPRING_CASH_PARSER_FALSIFIER')
    save(out/'spring-overlay-admission.json',{'own_predecessor':cp['run']['checkpoint_sha256'],
         'overlay_sha256':loaded.sha256,'wrong_predecessor_and_consumed_session_refused':True,
         'retained_repairs_unchanged':True,'source_conversion':False,'new_origin':False})
    return overlay,loaded


def run(out,old,spec):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    cp=preflight(spec,old,out,before='2018-04-24')
    v1=FactualInputs('/driver/system-campaign-factual-catalog.json')
    need(v1.catalog['archive_sha256']==cp['base']['archive_sha256'],'SPRING_SAME_FROZEN_ARCHIVE')
    v1.hydrate(out/'hydrated-factual-catalog.json')
    # The retained additional hydration is immutable provenance, not recomputed
    # by a changed compiler. Keep it at the current evidence root for comparison.
    retained=old/'hydrated-additional-terminal-catalog.json'
    need(retained.is_file(),'SPRING_RETAINED_ADDITIONAL_HYDRATION')
    (out/'hydrated-additional-terminal-catalog.json').write_bytes(retained.read_bytes())
    retained=old/'hydrated-corrected-winter-cash-catalog.json'
    need(retained.is_file(),'SPRING_RETAINED_WINTER_HYDRATION')
    (out/retained.name).write_bytes(retained.read_bytes())
    facts=SpringFacts('/driver/system-campaign-spring-terminal-facts.json')
    facts.hydrate(out/'hydrated-spring-terminal-catalog.json');overlay,loaded=prepare_overlay(cp,old,out,facts)
    parameters=json.loads((old/'source-bindings.json').read_bytes()).get('parameters',{})
    family=parameters.get('family','CORE');keep=parameters['v_horizon'] if family=='V' else 21 if family=='C' else 1
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp)) if spec['arm'].startswith('P') else None
    args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
    with v1:
        facts.qualify(loaded,out/'spring-input-qualification.json')
        with observer if observer is not None else nullcontext():
            with Execution('REFERENCE' if spec['arm']=='B0' else 'FAST',signal_closes=keep) as execution:
                code=backtest.main(args+['--repair-overlay',str(overlay)])
    save(out/'acceleration-proof.json',execution.proof())
    if observer is not None:save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    save(out/'spring-terminal-outcome.json',{'session':current['source_cursor'],'completed':current['completed'],
         'complete':current['source_cursor']==backtest.END and current['completed']==2156,
         'new_origin':False,'financial_source_changed':False,'production_contacted':False})
    need(code==0,'SPRING_CASH_REFUSED_PREFIX_PRESERVED')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True)
    p.add_argument('--spec',type=Path,required=True);a=p.parse_args();hosted();spec=json.loads(a.spec.read_bytes())
    if a.mode=='economic':run(Path('/out'),Path('/old'),spec)
    else:review(Path('/out'),Path('/evidence'),Path('/old'),spec)
