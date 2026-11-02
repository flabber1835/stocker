"""Own dated factual continuation; complete the physically uniform default too."""
import argparse,json
from pathlib import Path
from full_system_core import arguments,hosted
from full_system_benchmark import need,save
from system_campaign_acceleration import Execution
from system_campaign_facts import FactualInputs,sha
from system_campaign_factual_run import preflight,correlation_seed,SeededObservation,preserve_tails,review as canonical_review
from system_campaign_late_run import retained as retained_seven
from system_campaign_late_facts import LateFacts
from system_campaign_yearend_facts import YearendFacts
from system_campaign_terminal_run import merge_future_documents
from system_campaign_own_origin import qualify as qualify_origin

YEAREND='research:system-optimization-002/yearend-terminal-catalog/1'
LATE='research:system-optimization-002/late-terminal-catalog/1'


def retained_eight(refs,old,out,driver=Path('/driver')):
    retained_seven(refs,old,out,driver)
    for reference,path in (
        ('late-terminal-catalog',driver/'system-campaign-late-terminal-facts.json'),
        ('late-terminal-compiler',driver/'system_campaign_late_facts.py'),
        ('late-private-terminal-catalog',old/'hydrated-late-terminal-catalog.json')):
        need(path.is_file() and [v['sha256'] for v in refs if v['reference']=='research:system-optimization-002/'+reference+'/1']==[sha(path.read_bytes())],
             'YEAREND_EXACT_EIGHTH_RETAINED_COMPONENT')
    name='hydrated-late-terminal-catalog.json';(out/name).write_bytes((old/name).read_bytes())


def run(out,old,spec):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    from research.pooled_vacancy_funding.repair import load_repair
    default=spec['arm']=='P00';cp=preflight(spec,old,out,before='2018-11-28' if default else '2018-12-19')
    need(cp['source_cursor']==('2018-10-31' if default else '2018-11-30'),'YEAREND_OWN_EXACT_SELECTED_BOUNDARY')
    need(json.loads((old/'source-bindings.json').read_bytes())['parameters']['family']=='CORE','YEAREND_ONLY_FROZEN_CORE_ARMS')
    qualify_origin(out,cp,out/'own-origin-qualification.json')
    refs=[]
    for descriptor in cp['repairs']:
        raw=(old/'book/repairs'/descriptor['filename']).read_bytes();need(sha(raw)==descriptor['sha256'],'YEAREND_RETAINED_REPAIR_BYTES')
        refs.extend(json.loads(raw)['source_evidence'])
    need(not any(v['reference']==YEAREND for v in refs),'YEAREND_NO_DUPLICATE_INPUT')
    if default:
        need(not any(v['reference']==LATE for v in refs),'YEAREND_DEFAULT_OWN_SEVEN_COMPONENT_PREDECESSOR')
        retained_seven(refs,old,out)
    else:retained_eight(refs,old,out)
    v1=FactualInputs('/driver/system-campaign-factual-catalog.json');v1.hydrate(out/'independent-v1-hydration.json')
    need(sha((out/'independent-v1-hydration.json').read_bytes())==sha((out/'hydrated-factual-catalog.json').read_bytes()),
         'YEAREND_IDENTICAL_RETAINED_V1_HYDRATION')
    facts=YearendFacts('/driver/system-campaign-yearend-terminal-facts.json')
    facts.hydrate(out/'hydrated-yearend-terminal-catalog.json');component=out/'yearend-component.json';facts.overlay(cp,component)
    document=json.loads(component.read_bytes());late=None
    if default:
        late=LateFacts('/driver/system-campaign-late-terminal-facts.json');late.hydrate(out/'hydrated-late-terminal-catalog.json')
        path=out/'late-component.json';late.overlay(cp,path);document=merge_future_documents(json.loads(path.read_bytes()),document)
    overlay=out/'yearend-input-overlay.json';save(overlay,document)
    loaded=load_repair(overlay,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    for cursor,predecessor in ((cp['source_cursor'],'0'*64),(loaded.earliest_affected_session,cp['run']['checkpoint_sha256'])):
        try:load_repair(overlay,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
        except ValueError:pass
        else:raise ValueError('REFUSED_YEAREND_PARSER_FALSIFIER')
    save(out/'yearend-overlay-admission.json',{'own_predecessor':cp['run']['checkpoint_sha256'],'overlay_sha256':loaded.sha256,
        'prior_components_retained_exactly':7 if default else 8,'components_added':2 if default else 1,
        'wrong_predecessor_and_consumed_session_refused':True,'source_conversion':False,'new_origin':False})
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
    args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
    with v1:
        facts.qualify(loaded,out/'yearend-input-qualification.json')
        if late is not None:late.qualify(loaded,out/'late-input-qualification.json')
        with observer:
            with Execution('FAST',signal_closes=1) as execution:code=backtest.main(args+['--repair-overlay',str(overlay)])
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    save(out/'yearend-outcome.json',{'session':current['source_cursor'],'completed':current['completed'],
        'complete':current['source_cursor']==backtest.END and current['completed']==2156,
        'new_origin':False,'financial_source_changed':False,'production_contacted':False})
    need(code==0,'YEAREND_REFUSED_PREFIX_PRESERVED')


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
