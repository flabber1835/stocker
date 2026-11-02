"""Own June2018 suffix; unchanged retained facts and new sourced FMI/COL."""
import argparse,json
from pathlib import Path
from full_system_core import arguments,hosted
from full_system_benchmark import need,save
from system_campaign_acceleration import Execution
from system_campaign_facts import FactualInputs,sha
from system_campaign_factual_run import preflight,correlation_seed,SeededObservation,preserve_tails,review
from system_campaign_midyear_facts import MidyearFacts

MIDYEAR='research:system-optimization-002/midyear-terminal-catalog/1'


def retained(refs,old,out,driver=Path('/driver')):
    groups=[('common-factual-catalog','system-campaign-factual-catalog.json','system_campaign_facts.py','hydrated-factual-catalog.json',
        'factual-input-compiler','private-hydrated-factual-catalog'),
        ('additional-terminal-catalog','system-campaign-additional-terminal-facts.json','system_campaign_terminal_facts.py','hydrated-additional-terminal-catalog.json',
        'additional-terminal-compiler','additional-private-terminal-catalog'),
        ('corrected-winter-cash-catalog','system-campaign-corrected-winter-facts.json','system_campaign_winter_facts.py','hydrated-corrected-winter-cash-catalog.json',
        'corrected-winter-cash-compiler','corrected-winter-private-cash-catalog'),
        ('spring-terminal-catalog','system-campaign-spring-terminal-facts.json','system_campaign_spring_facts.py','hydrated-spring-terminal-catalog.json',
        'spring-terminal-compiler','spring-private-terminal-catalog'),
        ('followup-terminal-catalog','system-campaign-followup-terminal-facts.json','system_campaign_followup_facts.py','hydrated-followup-terminal-catalog.json',
        'followup-terminal-compiler','followup-private-terminal-catalog'),
        ('tgi-cash-catalog','system-campaign-tgi-cash-facts.json','system_campaign_tgi_facts.py','hydrated-tgi-cash-catalog.json',
        'tgi-cash-compiler','tgi-private-cash-catalog')]
    for catalog,data,compiler,hydration,compiler_ref,hydrated_ref in groups:
        for name,path in ((catalog,driver/data),(compiler_ref,driver/compiler),(hydrated_ref,old/hydration)):
            reference='research:system-optimization-002/'+name+'/1'
            need(path.is_file() and [v['sha256'] for v in refs if v['reference']==reference]==[sha(path.read_bytes())],
                 'MIDYEAR_EXACT_ALL_RETAINED_FACT_COMPONENTS')
        (out/hydration).write_bytes((old/hydration).read_bytes())


def run(out,old,spec):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    from research.pooled_vacancy_funding.repair import load_repair
    cp=preflight(spec,old,out,before='2018-07-31')
    need(cp['source_cursor']=='2018-06-29','MIDYEAR_OWN_EXACT_JUNE_BOUNDARY')
    need(json.loads((old/'source-bindings.json').read_bytes())['parameters']['family']=='CORE',
         'MIDYEAR_ONLY_FROZEN_CORE_ARMS')
    refs=[]
    for descriptor in cp['repairs']:
        raw=(old/'book/repairs'/descriptor['filename']).read_bytes()
        need(sha(raw)==descriptor['sha256'],'MIDYEAR_RETAINED_REPAIR_BYTES')
        refs.extend(json.loads(raw)['source_evidence'])
    need(not any(v['reference']==MIDYEAR for v in refs),'MIDYEAR_NO_DUPLICATE_INPUT')
    retained(refs,old,out)
    v1=FactualInputs('/driver/system-campaign-factual-catalog.json')
    v1.hydrate(out/'independent-v1-hydration.json')
    need(sha((out/'independent-v1-hydration.json').read_bytes())==sha((out/'hydrated-factual-catalog.json').read_bytes()),
         'MIDYEAR_IDENTICAL_RETAINED_V1_HYDRATION')
    facts=MidyearFacts('/driver/system-campaign-midyear-terminal-facts.json')
    facts.hydrate(out/'hydrated-midyear-terminal-catalog.json');overlay=out/'midyear-input-overlay.json'
    loaded=facts.overlay(cp,overlay)
    for cursor,predecessor in ((cp['source_cursor'],'0'*64),(loaded.earliest_affected_session,cp['run']['checkpoint_sha256'])):
        try:load_repair(overlay,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
        except ValueError:pass
        else:raise ValueError('REFUSED_MIDYEAR_PARSER_FALSIFIER')
    save(out/'midyear-overlay-admission.json',{'own_predecessor':cp['run']['checkpoint_sha256'],
        'overlay_sha256':loaded.sha256,'all_six_prior_components_retained_exactly':True,
        'wrong_predecessor_and_consumed_session_refused':True,'source_conversion':False,'new_origin':False})
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
    args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
    with v1:
        facts.qualify(loaded,out/'midyear-input-qualification.json')
        with observer:
            with Execution('FAST',signal_closes=1) as execution:code=backtest.main(args+['--repair-overlay',str(overlay)])
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    save(out/'midyear-outcome.json',{'session':current['source_cursor'],'completed':current['completed'],
        'complete':current['source_cursor']==backtest.END and current['completed']==2156,
        'new_origin':False,'financial_source_changed':False,'production_contacted':False})
    need(code==0,'MIDYEAR_REFUSED_PREFIX_PRESERVED')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True)
    p.add_argument('--spec',type=Path,required=True);a=p.parse_args();hosted();spec=json.loads(a.spec.read_bytes())
    if a.mode=='economic':run(Path('/out'),Path('/old'),spec)
    else:review(Path('/out'),Path('/evidence'),Path('/old'),spec)
