"""Exact current-checkpoint continuation; no source or factual input changes."""
import argparse,json
from contextlib import nullcontext
from pathlib import Path
from full_system_benchmark import need,save
from full_system_core import arguments,hosted
from system_campaign_acceleration import Execution
from system_campaign_facts import FactualInputs,sha
from system_campaign_factual_run import preflight,correlation_seed,SeededObservation,preserve_tails,review


def selected_current(spec,current):
    need(spec['selected_checkpoint']=='book/checkpoint.json.gz'
         and spec['outer_sha256']==current['sha256']
         and spec['selected_session']==current['source_cursor']
         and current['source_cursor']<'2026-07-31' and current['completed']<2156,
         'FINISH_ONLY_EXACT_INCOMPLETE_CURRENT_CHECKPOINT')


def run(out,old,spec):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    current=journal.read_checkpoint(old/'book/checkpoint.json.gz');selected_current(spec,current)
    cp=preflight(spec,old,out,before='2026-08-01')
    catalog=FactualInputs('/driver/system-campaign-factual-catalog.json')
    catalog.hydrate(out/'hydrated-factual-catalog.json')
    need(sha((out/'hydrated-factual-catalog.json').read_bytes())==sha((old/'hydrated-factual-catalog.json').read_bytes()),
         'FINISH_UNCHANGED_ACTUAL_FACTUAL_HYDRATION')
    preserved={}
    for name in ('hydrated-additional-terminal-catalog.json','hydrated-march-cash-catalog.json',
                 'hydrated-corrected-winter-cash-catalog.json','hydrated-spring-terminal-catalog.json',
                 'hydrated-followup-terminal-catalog.json','hydrated-tgi-cash-catalog.json',
                 'hydrated-midyear-terminal-catalog.json','hydrated-late-terminal-catalog.json'):
        if (old/name).is_file():
            raw=(old/name).read_bytes();(out/name).write_bytes(raw);preserved[name]=sha(raw)
    parameters=json.loads((old/'source-bindings.json').read_bytes()).get('parameters',{})
    family=parameters.get('family','CORE');keep=parameters['v_horizon'] if family=='V' else 21 if family=='C' else 1
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp)) if spec['arm'].startswith('P') else None
    args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
    with catalog:
        with observer if observer is not None else nullcontext():
            with Execution('REFERENCE' if spec['arm']=='B0' else 'FAST',signal_closes=keep) as execution:
                code=backtest.main(args)
    save(out/'acceleration-proof.json',execution.proof())
    if observer is not None:save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    after=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    need(after['base']==cp['base'] and after['repairs']==cp['repairs'],'FINISH_NO_INPUT_OR_SOURCE_SUCCESSOR')
    save(out/'finish-outcome.json',{'session':after['source_cursor'],'completed':after['completed'],
        'complete':after['source_cursor']==backtest.END and after['completed']==2156,
        'starting_current_outer_sha256':cp['sha256'],'immutable_hydrations_preserved':preserved,
        'fresh_origin':False,'source_conversion':False,'input_successor':False,'production_contacted':False})
    need(code==0,'FINISH_REFUSED_PREFIX_PRESERVED')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True)
    p.add_argument('--spec',type=Path,required=True);a=p.parse_args();hosted();spec=json.loads(a.spec.read_bytes())
    if a.mode=='economic':run(Path('/out'),Path('/old'),spec)
    else:review(Path('/out'),Path('/evidence'),Path('/old'),spec)
