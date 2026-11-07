"""Own-pre-event canonical suffix with separately versioned terminal facts."""
import argparse,json
from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path
from full_system_core import arguments,hosted
from full_system_benchmark import need,save
from system_campaign_acceleration import Execution
from system_campaign_facts import FactualInputs,CATALOG_REF,sha
from system_campaign_factual_run import preflight,correlation_seed,SeededObservation,preserve_tails,qualify_inputs,review
from system_campaign_terminal_facts import TerminalFacts


def merge_future_documents(additional,prior):
    need(additional['schema']==prior['schema']=='terminal-repair/1' and
         additional['predecessor_checkpoint_sha256']==prior['predecessor_checkpoint_sha256'],
         'ADDITIONAL_COMPOSITION_SAME_OWN_PREDECESSOR')
    document=deepcopy(additional)
    for name in ('source_evidence','suppress','add'):document[name]=deepcopy(prior[name])+document[name]
    for name in ('suppress','add'):
        keys=[(v['session'],v['security_id']) for v in document[name]]
        need(len(keys)==len(set(keys)),'ADDITIONAL_NO_DUPLICATE_FACTS')
    return document


def compose(cp,old,out,v1,new):
    from research.pooled_vacancy_funding.repair import load_repair
    retained=False
    for descriptor in cp['repairs']:
        path=old/'book/repairs'/descriptor['filename'];raw=path.read_bytes()
        need(sha(raw)==descriptor['sha256'],'ADDITIONAL_RETAINED_REPAIR_ARCHIVE')
        document=json.loads(raw)
        retained|=any(v['reference']==CATALOG_REF for v in document['source_evidence'])
    new_path=out/'additional-terminal-overlay.json';new.overlay(cp,new_path)
    document=json.loads(new_path.read_bytes())
    if not retained:
        origin=None
        if not cp['repairs']:
            candidates=[json.loads(p.read_bytes()) for p in old.rglob('campaign-own-facts.json')]
            candidates=[v for v in candidates if v['predecessor_checkpoint_sha256']==cp['run']['checkpoint_sha256']]
            need(candidates and all(v==candidates[0] for v in candidates),'ADDITIONAL_OWN_ZERO_ORIGIN_FUTURE_FACTS')
            origin=candidates[0]
        v1_path=out/'unchanged-v1-future-facts.json';v1.overlay(cp,v1_path,origin)
        prior=json.loads(v1_path.read_bytes())
        document=merge_future_documents(document,prior)
        # Preserve the separately prepared component documents; write a new
        # composed successor instead of overwriting either of their bytes.
        new_path=out/'composed-future-terminal-overlay.json';save(new_path,document)
    loaded=load_repair(new_path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    for cursor,predecessor in ((cp['source_cursor'],'0'*64),(loaded.earliest_affected_session,cp['run']['checkpoint_sha256'])):
        try:load_repair(new_path,resume_session=cursor,predecessor_checkpoint_sha256=predecessor)
        except ValueError:pass
        else:raise ValueError('REFUSED_ADDITIONAL_PARSER_FALSIFIER')
    save(out/'additional-overlay-admission.json',{'selected_own_predecessor':cp['run']['checkpoint_sha256'],
        'retained_v1_repair_reused':retained,'unchanged_future_v1_facts_rebound':not retained,
        'wrong_predecessor_and_consumed_session_refused':True,'overlay_sha256':loaded.sha256,
        'financial_source_changed':False,'new_origin':False})
    return new_path,loaded,retained


def run(out,old,spec):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    cp=preflight(spec,old,out)
    v1=FactualInputs('/driver/system-campaign-factual-catalog.json')
    need(v1.catalog['archive_sha256']==cp['base']['archive_sha256'],'ADDITIONAL_SAME_FROZEN_ARCHIVE')
    v1.hydrate(out/'hydrated-factual-catalog.json')
    new=TerminalFacts('/driver/system-campaign-additional-terminal-facts.json')
    new.hydrate(out/'hydrated-additional-terminal-catalog.json')
    overlay,loaded,retained=compose(cp,old,out,v1,new)
    parameters=json.loads((old/'source-bindings.json').read_bytes()).get('parameters',{})
    family=parameters.get('family','CORE');keep=parameters['v_horizon'] if family=='V' else 21 if family=='C' else 1
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp)) if spec['arm'].startswith('P') else None
    args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
    with v1:
        if not retained:qualify_inputs(v1,loaded,out/'composed-v1-input-qualification.json')
        new.qualify(loaded,out/'additional-input-qualification.json')
        with observer if observer is not None else nullcontext():
            with Execution('REFERENCE' if spec['arm']=='B0' else 'FAST',signal_closes=keep) as execution:
                code=backtest.main(args+['--repair-overlay',str(overlay)])
    save(out/'acceleration-proof.json',execution.proof())
    if observer is not None:save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    save(out/'additional-terminal-outcome.json',{'session':current['source_cursor'],'completed':current['completed'],
        'complete':current['source_cursor']==backtest.END and current['completed']==2156,
        'production_contacted':False,'new_origin':False,'financial_source_changed':False})
    need(code==0,'ADDITIONAL_TERMINAL_PREFIX_REFUSED_PRESERVED')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=('economic','review'),required=True)
    parser.add_argument('--spec',type=Path,required=True);args=parser.parse_args();hosted();spec=json.loads(args.spec.read_bytes())
    if args.mode=='economic':run(Path('/out'),Path('/old'),spec)
    else:review(Path('/out'),Path('/evidence'),Path('/old'),spec)
