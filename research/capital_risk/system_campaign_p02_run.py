"""Only P02's exact June2019 suffix; all financial parameters remain frozen."""
import argparse,json
from pathlib import Path
from full_system_core import arguments,hosted
from full_system_benchmark import need,save
from system_campaign_acceleration import Execution
from system_campaign_facts import FactualInputs,sha
from system_campaign_distribution_facts import DistributionFacts,CATALOG as DISTRIBUTION
from system_campaign_array_facts import ArrayFacts,CATALOG as ARRAY
from system_campaign_distribution_run import retained_twelve
from system_campaign_factual_run import preflight,correlation_seed,SeededObservation,preserve_tails,review as canonical_review
from system_campaign_own_origin import qualify as qualify_origin


def retained_thirteen(refs,old,out,driver=Path('/driver')):
    retained_twelve(refs,old,out,driver)
    for ref,path in (
        (DISTRIBUTION,driver/'system-campaign-distribution-facts.json'),
        ('research:system-optimization-002/distribution-compiler/1',driver/'system_campaign_distribution_facts.py'),
        ('research:system-optimization-002/distribution-private-catalog/1',old/'hydrated-distribution-catalog.json')):
        need(path.is_file() and [v['sha256'] for v in refs if v['reference']==ref]==[sha(path.read_bytes())],
             'P02_EXACT_THIRTEEN_PRIOR_COMPONENTS')
    name='hydrated-distribution-catalog.json';(out/name).write_bytes((old/name).read_bytes())


def run(out,old,spec):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    from research.pooled_vacancy_funding.repair import load_repair
    cp=preflight(spec,old,out,before='2019-07-30')
    need(spec['arm']=='P02' and cp['source_cursor']=='2019-06-28' and cp['completed']==375,
         'P02_ONLY_OWN_EXACT_JUNE_CHECKPOINT')
    need(json.loads((old/'source-bindings.json').read_bytes())['parameters']['family']=='CORE','P02_UNCHANGED_CORE_PARAMETERS')
    qualify_origin(out,cp,out/'own-origin-qualification.json');refs=[]
    for d in cp['repairs']:
        raw=(old/'book/repairs'/d['filename']).read_bytes();need(sha(raw)==d['sha256'],'P02_OLD_REPAIR_BYTES')
        refs.extend(json.loads(raw)['source_evidence'])
    need(not any(v['reference']==ARRAY for v in refs),'P02_NO_DUPLICATE_ARRAY_INPUT')
    retained_thirteen(refs,old,out)
    v1=FactualInputs('/driver/system-campaign-factual-catalog.json');v1.hydrate(out/'independent-v1-hydration.json')
    need(sha((out/'independent-v1-hydration.json').read_bytes())==sha((out/'hydrated-factual-catalog.json').read_bytes()),'P02_IDENTICAL_V1_HYDRATION')
    spin=DistributionFacts('/driver/system-campaign-distribution-facts.json');spin.hydrate(out/'independent-distribution-hydration.json')
    need(sha((out/'independent-distribution-hydration.json').read_bytes())==sha((out/'hydrated-distribution-catalog.json').read_bytes()),
         'P02_IDENTICAL_DISTRIBUTION_HYDRATION')
    facts=ArrayFacts('/driver/system-campaign-array-terminal-facts.json');facts.hydrate(out/'hydrated-array-terminal-catalog.json')
    overlay=out/'array-input-overlay.json';loaded=facts.overlay(cp,overlay)
    for cursor,predecessor in ((cp['source_cursor'],'0'*64),('2019-07-30',cp['run']['checkpoint_sha256'])):
        try:load_repair(overlay,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
        except ValueError:pass
        else:raise ValueError('REFUSED_P02_ARRAY_PARSER_FALSIFIER')
    save(out/'array-overlay-admission.json',{'own_predecessor':cp['run']['checkpoint_sha256'],'overlay_sha256':loaded.sha256,
        'prior_components_retained_exactly':13,'components_added':1,'wrong_predecessor_and_consumed_session_refused':True,
        'source_conversion':False,'new_origin':False,'only_candidate':'P02'})
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
    args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
    with v1,spin:
        facts.qualify(loaded,out/'array-input-qualification.json')
        with observer:
            with Execution('FAST',signal_closes=1) as execution:code=backtest.main(args+['--repair-overlay',str(overlay)])
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    save(out/'p02-outcome.json',{'session':current['source_cursor'],'completed':current['completed'],
        'complete':current['source_cursor']==backtest.END and current['completed']==2156,
        'new_origin':False,'financial_source_changed':False,'production_contacted':False,'only_candidate':'P02'})
    need(code==0,'P02_REFUSED_PREFIX_PRESERVED')


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
