"""Exact own pre-event suffixes with unchanged canonical financial machinery."""
import argparse,json
from pathlib import Path
from full_system_core import arguments,hosted
from full_system_benchmark import need,save
from system_campaign_acceleration import Execution
from system_campaign_facts import FactualInputs,sha
from system_campaign_factual_run import preflight,correlation_seed,SeededObservation,preserve_tails,review as canonical_review
from system_campaign_early2019_run import retained_eleven
from system_campaign_early2019_facts import Early2019Facts
from system_campaign_distribution_facts import DistributionFacts,CATALOG
from system_campaign_own_origin import qualify as qualify_origin


def retained_twelve(refs,old,out,driver=Path('/driver')):
    retained_eleven(refs,old,out,driver)
    for suffix,path in (
        ('terminal-catalog',driver/'system-campaign-early2019-terminal-facts.json'),
        ('terminal-compiler',driver/'system_campaign_early2019_facts.py'),
        ('private-terminal-catalog',old/'hydrated-early2019-terminal-catalog.json')):
        ref='research:system-optimization-002/early2019-'+suffix+'/1'
        need(path.is_file() and [v['sha256'] for v in refs if v['reference']==ref]==[sha(path.read_bytes())],
             'DISTRIBUTION_EXACT_TWELVE_PRIOR_COMPONENTS')
    name='hydrated-early2019-terminal-catalog.json';(out/name).write_bytes((old/name).read_bytes())


def run(out,old,spec):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    from research.pooled_vacancy_funding.repair import load_repair
    extra=spec['arm']=='P04';cp=preflight(spec,old,out,before='2019-01-25' if extra else '2019-04-09')
    need(spec['arm'] in ('P01','P02','P04','P07') and cp['source_cursor']==('2018-12-31' if extra else '2019-03-29'),
         'DISTRIBUTION_OWN_EXACT_PRE_EVENT_BOUNDARY')
    need(json.loads((old/'source-bindings.json').read_bytes())['parameters']['family']=='CORE',
         'DISTRIBUTION_UNCHANGED_CORE_PARAMETERS')
    qualify_origin(out,cp,out/'own-origin-qualification.json');refs=[]
    for d in cp['repairs']:
        raw=(old/'book/repairs'/d['filename']).read_bytes();need(sha(raw)==d['sha256'],'DISTRIBUTION_OLD_REPAIR_BYTES')
        refs.extend(json.loads(raw)['source_evidence'])
    need(not any(v['reference']==CATALOG for v in refs),'DISTRIBUTION_NO_DUPLICATE_INPUT')
    (retained_eleven if extra else retained_twelve)(refs,old,out)
    v1=FactualInputs('/driver/system-campaign-factual-catalog.json');v1.hydrate(out/'independent-v1-hydration.json')
    need(sha((out/'independent-v1-hydration.json').read_bytes())==sha((out/'hydrated-factual-catalog.json').read_bytes()),
         'DISTRIBUTION_IDENTICAL_V1_HYDRATION')
    facts=DistributionFacts('/driver/system-campaign-distribution-facts.json')
    facts.hydrate(out/'hydrated-distribution-catalog.json');overlay=out/'distribution-input-overlay.json';loaded=facts.overlay(cp,overlay)
    early=None
    if extra:
        early=Early2019Facts('/driver/system-campaign-early2019-terminal-facts.json')
        early.hydrate(out/'hydrated-early2019-terminal-catalog.json');path=out/'early2019-component.json';early.overlay(cp,path)
        merged=json.loads(overlay.read_bytes());other=json.loads(path.read_bytes())
        need(merged['predecessor_checkpoint_sha256']==other['predecessor_checkpoint_sha256'],'DISTRIBUTION_SAME_OWN_PREDECESSOR')
        for name in ('source_evidence','suppress','add'):merged[name]+=other[name]
        save(overlay,merged);loaded=load_repair(overlay,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    need(facts._bound(loaded),'DISTRIBUTION_FINAL_OWN_COMPOUND_BINDING')
    for cursor,predecessor in ((cp['source_cursor'],'0'*64),(loaded.earliest_affected_session,cp['run']['checkpoint_sha256'])):
        try:load_repair(overlay,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
        except ValueError:pass
        else:raise ValueError('REFUSED_DISTRIBUTION_TERMINAL_PARSER_FALSIFIER')
    save(out/'distribution-overlay-admission.json',{'own_predecessor':cp['run']['checkpoint_sha256'],
        'overlay_sha256':loaded.sha256,'prior_components_retained_exactly':11 if extra else 12,
        'components_added':2 if extra else 1,'wrong_predecessor_and_consumed_terminal_refused':True,
        'compound_first_spin_boundary':'2019-04-09','source_conversion':False,'new_origin':False})
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
    args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
    with v1,facts:
        facts.qualify(loaded,out/'distribution-input-qualification.json')
        if early:early.qualify(loaded,out/'early2019-input-qualification.json')
        with observer:
            with Execution('FAST',signal_closes=1) as execution:code=backtest.main(args+['--repair-overlay',str(overlay)])
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    save(out/'distribution-outcome.json',{'session':current['source_cursor'],'completed':current['completed'],
        'complete':current['source_cursor']==backtest.END and current['completed']==2156,
        'new_origin':False,'financial_source_changed':False,'production_contacted':False})
    need(code==0,'DISTRIBUTION_REFUSED_PREFIX_PRESERVED')


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
