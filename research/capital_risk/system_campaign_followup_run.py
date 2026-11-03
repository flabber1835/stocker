"""Own factual suffix with unchanged Spring/TGI components and three new facts."""
import argparse,json
from pathlib import Path
from full_system_core import arguments,hosted
from full_system_benchmark import need,save
from system_campaign_acceleration import Execution
from system_campaign_facts import FactualInputs,sha
from system_campaign_factual_run import preflight,correlation_seed,SeededObservation,preserve_tails,review
from system_campaign_spring_facts import SpringFacts
from system_campaign_tgi_facts import TgiCash,CATALOG as TGI
from system_campaign_followup_facts import FollowupFacts
from system_campaign_terminal_run import merge_future_documents

SPRING='research:system-optimization-002/spring-terminal-catalog/1'
WINTER='research:system-optimization-002/corrected-winter-cash-catalog/1'
FOLLOWUP='research:system-optimization-002/followup-terminal-catalog/1'


def spring_retained(refs,old,driver=Path('/driver')):
    values=[v['sha256'] for v in refs if v['reference']==SPRING]
    if not values:return False
    expected={SPRING:driver/'system-campaign-spring-terminal-facts.json',
        'research:system-optimization-002/spring-terminal-compiler/1':driver/'system_campaign_spring_facts.py',
        'research:system-optimization-002/spring-private-terminal-catalog/1':old/'hydrated-spring-terminal-catalog.json'}
    need(all(p.is_file() and [v['sha256'] for v in refs if v['reference']==r]==[sha(p.read_bytes())]
        for r,p in expected.items()),'FOLLOWUP_EXACT_RETAINED_SPRING')
    return True


def prepare_overlay(cp,old,out,facts):
    from research.pooled_vacancy_funding.repair import load_repair
    refs=[]
    for d in cp['repairs']:
        raw=(old/'book/repairs'/d['filename']).read_bytes();need(sha(raw)==d['sha256'],'FOLLOWUP_RETAINED_REPAIR_BYTES')
        refs.extend(json.loads(raw)['source_evidence'])
    need([v['sha256'] for v in refs if v['reference']==WINTER]==[
         sha(Path('/driver/system-campaign-corrected-winter-facts.json').read_bytes())],
         'FOLLOWUP_CORRECTED_WINTER_RETAINED')
    need(not any(v['reference'] in (FOLLOWUP,TGI,'research:system-optimization-002/march-cash-catalog/1') for v in refs),
         'FOLLOWUP_NO_DUPLICATE_OR_SUPERSEDED_INPUT')
    facts.overlay(cp,out/'followup-component.json');doc=json.loads((out/'followup-component.json').read_bytes())
    retained_spring=spring_retained(refs,old);spring=None
    if retained_spring:
        (out/'hydrated-spring-terminal-catalog.json').write_bytes((old/'hydrated-spring-terminal-catalog.json').read_bytes())
    else:
        spring=SpringFacts('/driver/system-campaign-spring-terminal-facts.json')
        spring.hydrate(out/'hydrated-spring-terminal-catalog.json');spring.overlay(cp,out/'spring-component.json')
        doc=merge_future_documents(json.loads((out/'spring-component.json').read_bytes()),doc)
    tgi=TgiCash('/driver/system-campaign-tgi-cash-facts.json');tgi.hydrate(out/'hydrated-tgi-cash-catalog.json')
    tgi.overlay(cp,out/'tgi-component.json');doc=merge_future_documents(json.loads((out/'tgi-component.json').read_bytes()),doc)
    path=out/'followup-merged-overlay.json';save(path,doc)
    loaded=load_repair(path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    for cursor,predecessor in ((cp['source_cursor'],'0'*64),(loaded.earliest_affected_session,cp['run']['checkpoint_sha256'])):
        try:load_repair(path,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
        except ValueError:pass
        else:raise ValueError('REFUSED_FOLLOWUP_PARSER_FALSIFIER')
    save(out/'followup-overlay-admission.json',{'selected_own_predecessor':cp['run']['checkpoint_sha256'],
        'spring_retained_exactly':retained_spring,'unchanged_spring_added_as_future':not retained_spring,
        'tgi_same_future_component':True,'wrong_predecessor_and_consumed_session_refused':True,
        'overlay_sha256':loaded.sha256,'source_conversion':False,'new_origin':False})
    return path,loaded,spring,tgi


def run(out,old,spec):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    cp=preflight(spec,old,out,before='2018-05-15')
    v1=FactualInputs('/driver/system-campaign-factual-catalog.json');v1.hydrate(out/'hydrated-factual-catalog.json')
    for name in ('hydrated-additional-terminal-catalog.json','hydrated-corrected-winter-cash-catalog.json'):
        need((old/name).is_file(),'FOLLOWUP_RETAINED_HYDRATION');(out/name).write_bytes((old/name).read_bytes())
    facts=FollowupFacts('/driver/system-campaign-followup-terminal-facts.json')
    facts.hydrate(out/'hydrated-followup-terminal-catalog.json');overlay,loaded,spring,tgi=prepare_overlay(cp,old,out,facts)
    parameters=json.loads((old/'source-bindings.json').read_bytes())['parameters']
    need(parameters['family']=='CORE','FOLLOWUP_ONLY_FROZEN_CORE_ARMS')
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
    args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
    with v1:
        facts.qualify(loaded,out/'followup-input-qualification.json');tgi.qualify(loaded,out/'tgi-input-qualification.json')
        if spring is not None:spring.qualify(loaded,out/'spring-input-qualification.json')
        with observer:
            with Execution('FAST',signal_closes=1) as execution:
                code=backtest.main(args+['--repair-overlay',str(overlay)])
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    save(out/'followup-outcome.json',{'session':current['source_cursor'],'completed':current['completed'],
        'complete':current['source_cursor']==backtest.END and current['completed']==2156,
        'new_origin':False,'financial_source_changed':False,'production_contacted':False})
    need(code==0,'FOLLOWUP_REFUSED_PREFIX_PRESERVED')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True)
    p.add_argument('--spec',type=Path,required=True);a=p.parse_args();hosted();spec=json.loads(a.spec.read_bytes())
    if a.mode=='economic':run(Path('/out'),Path('/old'),spec)
    else:review(Path('/out'),Path('/evidence'),Path('/old'),spec)
