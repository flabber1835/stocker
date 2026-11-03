"""Own October2018 suffix; unchanged retained facts and new sourced AET/OCLR/APTI."""
import argparse,json
from pathlib import Path
from full_system_core import arguments,hosted
from full_system_benchmark import need,save
from system_campaign_acceleration import Execution
from system_campaign_facts import FactualInputs,sha
from system_campaign_factual_run import preflight,correlation_seed,SeededObservation,preserve_tails,review
from system_campaign_late_facts import LateFacts

LATE='research:system-optimization-002/late-terminal-catalog/1'


def retained(refs,old,out,driver=Path('/driver')):
    from system_campaign_midyear_run import retained as prior_six
    prior_six(refs,old,out,driver)
    for reference,path in (
        ('midyear-terminal-catalog',driver/'system-campaign-midyear-terminal-facts.json'),
        ('midyear-terminal-compiler',driver/'system_campaign_midyear_facts.py'),
        ('midyear-private-terminal-catalog',old/'hydrated-midyear-terminal-catalog.json')):
        need(path.is_file() and [v['sha256'] for v in refs if v['reference']=='research:system-optimization-002/'+reference+'/1']==[sha(path.read_bytes())],
             'LATE_EXACT_SEVENTH_RETAINED_COMPONENT')
    name='hydrated-midyear-terminal-catalog.json';(out/name).write_bytes((old/name).read_bytes())


def run(out,old,spec):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    from research.pooled_vacancy_funding.repair import load_repair
    cp=preflight(spec,old,out,before='2018-11-28')
    need(cp['source_cursor']=='2018-10-31','LATE_OWN_EXACT_OCTOBER_BOUNDARY')
    need(json.loads((old/'source-bindings.json').read_bytes())['parameters']['family']=='CORE',
         'LATE_ONLY_FROZEN_CORE_ARMS')
    refs=[]
    for descriptor in cp['repairs']:
        raw=(old/'book/repairs'/descriptor['filename']).read_bytes()
        need(sha(raw)==descriptor['sha256'],'LATE_RETAINED_REPAIR_BYTES')
        refs.extend(json.loads(raw)['source_evidence'])
    need(not any(v['reference']==LATE for v in refs),'LATE_NO_DUPLICATE_INPUT')
    retained(refs,old,out)
    v1=FactualInputs('/driver/system-campaign-factual-catalog.json')
    v1.hydrate(out/'independent-v1-hydration.json')
    need(sha((out/'independent-v1-hydration.json').read_bytes())==sha((out/'hydrated-factual-catalog.json').read_bytes()),
         'LATE_IDENTICAL_RETAINED_V1_HYDRATION')
    facts=LateFacts('/driver/system-campaign-late-terminal-facts.json')
    facts.hydrate(out/'hydrated-late-terminal-catalog.json');overlay=out/'late-input-overlay.json'
    loaded=facts.overlay(cp,overlay)
    for cursor,predecessor in ((cp['source_cursor'],'0'*64),(loaded.earliest_affected_session,cp['run']['checkpoint_sha256'])):
        try:load_repair(overlay,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
        except ValueError:pass
        else:raise ValueError('REFUSED_LATE_PARSER_FALSIFIER')
    save(out/'late-overlay-admission.json',{'own_predecessor':cp['run']['checkpoint_sha256'],
        'overlay_sha256':loaded.sha256,'all_seven_prior_components_retained_exactly':True,
        'wrong_predecessor_and_consumed_session_refused':True,'source_conversion':False,'new_origin':False})
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
    args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
    with v1:
        facts.qualify(loaded,out/'late-input-qualification.json')
        with observer:
            with Execution('FAST',signal_closes=1) as execution:code=backtest.main(args+['--repair-overlay',str(overlay)])
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    save(out/'late-outcome.json',{'session':current['source_cursor'],'completed':current['completed'],
        'complete':current['source_cursor']==backtest.END and current['completed']==2156,
        'new_origin':False,'financial_source_changed':False,'production_contacted':False})
    need(code==0,'LATE_REFUSED_PREFIX_PRESERVED')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True)
    p.add_argument('--spec',type=Path,required=True);a=p.parse_args();hosted();spec=json.loads(a.spec.read_bytes())
    if a.mode=='economic':run(Path('/out'),Path('/old'),spec)
    else:review(Path('/out'),Path('/evidence'),Path('/old'),spec)
