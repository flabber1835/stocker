"""P02-only ordinary factual suffixes with an explicit frozen component registry."""
import argparse,json
from pathlib import Path
from full_system_core import arguments,hosted
from full_system_benchmark import need,save
from system_campaign_acceleration import Execution
from system_campaign_facts import FactualInputs,sha,digest
from system_campaign_distribution_facts import DistributionFacts
from system_campaign_array_facts import ArrayFacts
from system_campaign_tableau_facts import TableauFacts
from system_campaign_p02_run import retained_thirteen
from system_campaign_factual_run import preflight,correlation_seed,SeededObservation,preserve_tails,review as canonical_review
from system_campaign_own_origin import qualify as qualify_origin

COMPONENTS=(
    {'name':'array','class':ArrayFacts,'catalog':'system-campaign-array-terminal-facts.json',
     'compiler':'system_campaign_array_facts.py','hydrated':'hydrated-array-terminal-catalog.json',
     'earliest':'2019-07-30','reference_prefix':'array','packet_checks':1},
    {'name':'tableau','class':TableauFacts,'catalog':'system-campaign-tableau-terminal-facts.json',
     'compiler':'system_campaign_tableau_facts.py','hydrated':'hydrated-tableau-terminal-catalog.json',
     'earliest':'2019-07-31','reference_prefix':'tableau','packet_checks':10})


def component(name):
    matches=[(i,c) for i,c in enumerate(COMPONENTS) if c['name']==name]
    need(len(matches)==1,'P02_EXPLICIT_COMPONENT_REGISTRY');return matches[0]


def registry_commitment():return digest([{k:v for k,v in c.items() if k!='class'} for c in COMPONENTS])


def retained_components(refs,old,out,index,driver=Path('/driver')):
    retained_thirteen(refs,old,out,driver)
    for c in COMPONENTS[:index]:
        for suffix,path in (('terminal-catalog',driver/c['catalog']),('terminal-compiler',driver/c['compiler']),
                            ('private-terminal-catalog',old/c['hydrated'])):
            ref='research:system-optimization-002/'+c['reference_prefix']+'-'+suffix+'/1'
            need(path.is_file() and [v['sha256'] for v in refs if v['reference']==ref]==[sha(path.read_bytes())],
                 'P02_ALL_ORDINARY_COMPONENTS_RETAINED_EXACTLY')
        (out/c['hydrated']).write_bytes((old/c['hydrated']).read_bytes())


def run(out,old,spec):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    from research.pooled_vacancy_funding.repair import load_repair
    need(spec['arm']=='P02','P02_ONLY_OWNER_PRIORITY');index,c=component(spec['new_component'])
    need(index>=1,'P02_CONTINUATION_HAS_REVIEWED_PRIOR_COMPONENT')
    cp=preflight(spec,old,out,before=c['earliest'])
    need(cp['source_cursor']==spec['selected_session'] and json.loads((old/'source-bindings.json').read_bytes())['parameters']['family']=='CORE',
         'P02_OWN_EXACT_UNCHANGED_CORE_PREDECESSOR')
    qualify_origin(out,cp,out/'own-origin-qualification.json');refs=[]
    for d in cp['repairs']:
        raw=(old/'book/repairs'/d['filename']).read_bytes();need(sha(raw)==d['sha256'],'P02_RETAINED_ORDINARY_REPAIR_BYTES')
        refs.extend(json.loads(raw)['source_evidence'])
    new_ref='research:system-optimization-002/'+c['reference_prefix']+'-terminal-catalog/1'
    need(not any(v['reference']==new_ref for v in refs),'P02_NEW_COMPONENT_NOT_CONSUMED')
    retained_components(refs,old,out,index)
    v1=FactualInputs('/driver/system-campaign-factual-catalog.json');v1.hydrate(out/'independent-v1-hydration.json')
    need(sha((out/'independent-v1-hydration.json').read_bytes())==sha((out/'hydrated-factual-catalog.json').read_bytes()),'P02_IDENTICAL_V1_HYDRATION')
    spin=DistributionFacts('/driver/system-campaign-distribution-facts.json');spin.hydrate(out/'independent-distribution-hydration.json')
    need(sha((out/'independent-distribution-hydration.json').read_bytes())==sha((out/'hydrated-distribution-catalog.json').read_bytes()),
         'P02_IDENTICAL_DISTRIBUTION_HYDRATION')
    facts=c['class'](Path('/driver')/c['catalog']);facts.hydrate(out/c['hydrated'])
    overlay=out/(c['name']+'-input-overlay.json');loaded=facts.overlay(cp,overlay)
    for cursor,predecessor in ((cp['source_cursor'],'0'*64),(c['earliest'],cp['run']['checkpoint_sha256'])):
        try:load_repair(overlay,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
        except ValueError:pass
        else:raise ValueError('REFUSED_P02_CONTINUATION_PARSER_FALSIFIER')
    save(out/'p02-component-admission.json',{'only_candidate':'P02','new_component':c['name'],
        'own_predecessor':cp['run']['checkpoint_sha256'],'overlay_sha256':loaded.sha256,'prior_components_retained_exactly':13+index,
        'components_added':1,'wrong_predecessor_and_consumed_session_refused':True,'source_conversion':False,'new_origin':False,
        'registry_sha256':registry_commitment()})
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp));args=arguments(out/'book',True)
    args[args.index('--policy')+1]=cp['base']['policy']
    with v1,spin:
        facts.qualify(loaded,out/(c['name']+'-input-qualification.json'))
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
    qualify_origin(evidence,journal.read_checkpoint(old/spec['selected_checkpoint']),out/'independent-own-origin-qualification.json')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True);p.add_argument('--spec',type=Path,required=True)
    a=p.parse_args();hosted();spec=json.loads(a.spec.read_bytes())
    if a.mode=='economic':run(Path('/out'),Path('/old'),spec)
    else:review(Path('/out'),Path('/evidence'),Path('/old'),spec)
