"""Same P02 checkpoint/input suffix; idempotent unresolved date dispatch only."""
import argparse,json
from contextlib import contextmanager
from dataclasses import asdict,replace
from pathlib import Path
from full_system_core import arguments,hosted
from full_system_benchmark import need,save
from system_campaign_facts import FactualInputs,sha
from system_campaign_distribution_facts import DistributionFacts
from system_campaign_alder_date_v2 import AlderDateV2
from system_campaign_p02_continue_run import COMPONENTS,retained_components,review
from system_campaign_factual_run import preflight,SeededObservation,preserve_tails
from system_campaign_correlation_prefix import seed
from system_campaign_acceleration import Execution
from system_campaign_own_origin import qualify as qualify_origin


@contextmanager
def idempotent_dispatch(alder):
    from research.pooled_vacancy_funding import backtest
    original=backtest.apply_repair;expected=replace(alder.native,session=alder.catalog['effective_session'])
    def apply(packet,loaded):
        if packet.day==expected.session:
            existing=[t for t in packet.terminal if t.security_id==expected.security_id]
            need(not existing or len(existing)==1 and asdict(existing[0])==asdict(expected),
                 'P02_EXACT_ALREADY_INJECTED_UNRESOLVED_TERM')
            if existing:packet=replace(packet,terminal=tuple(t for t in packet.terminal if t.security_id!=expected.security_id))
        return original(packet,loaded)
    backtest.apply_repair=apply
    try:yield
    finally:backtest.apply_repair=original


def qualify_dispatch(alder,loaded,out):
    from research.pooled_input_support.adapter import Packet
    from research.pooled_vacancy_funding import backtest
    alder.qualify(loaded,out/'alder-input-qualification.json')
    packet=Packet(alder.catalog['effective_session'],(),{},{},1.,{},(),())
    first=backtest.apply_repair(packet,loaded);second=backtest.apply_repair(first,loaded)
    need(asdict(first)==asdict(second) and packet.terminal==() and len(first.terminal)==1
         and first.terminal[0].cash_per_share is None and not first.terminal[0].completeness(0)[0],
         'P02_ACTUAL_REPEATED_PACKET_IDEMPOTENCE')
    save(out/'repeated-dispatch-qualification.json',{'actual_repeated_calls':2,'exact_packet_idempotence':True,
        'unresolved_consideration_preserved':True,'original_packet_unchanged':True,'financial_sessions_advanced':0})


def run(out,old,spec):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal
    from research.pooled_vacancy_funding.repair import load_repair
    need(spec['arm']=='P02' and spec['execution_mode']=='RETAINED_EXACT_SUFFIX','P02_ONLY_RETAINED_MODE')
    cp=preflight(spec,old,out,before='2019-10-22');qualify_origin(out,cp,out/'own-origin-qualification.json');refs=[];alder_descriptor=None
    for d in cp['repairs']:
        raw=(old/'book/repairs'/d['filename']).read_bytes();need(sha(raw)==d['sha256'],'P02_ALL_RETAINED_REPAIR_BYTES')
        doc=json.loads(raw);refs.extend(doc['source_evidence'])
        if any(x['reference']=='research:system-optimization-002/alder-terminal-catalog/1' for x in doc['source_evidence']):
            need(alder_descriptor is None,'P02_ONE_RETAINED_ALDER_DESCRIPTOR');alder_descriptor=(d,doc)
    need(alder_descriptor is not None,'P02_RETAINED_ALDER_BOUND_INPUT');retained_components(refs,old,out,len(COMPONENTS))
    v1=FactualInputs('/driver/system-campaign-factual-catalog.json');v1.hydrate(out/'independent-v1-hydration.json')
    spin=DistributionFacts('/driver/system-campaign-distribution-facts.json');spin.hydrate(out/'independent-distribution-hydration.json')
    alder=AlderDateV2('/driver/system-campaign-alder-unresolved-date.json');alder.hydrate(out/'independent-alder-hydration.json')
    for a,b in [('independent-v1-hydration.json','hydrated-factual-catalog.json'),
                ('independent-distribution-hydration.json','hydrated-distribution-catalog.json'),
                ('independent-alder-hydration.json','hydrated-alder-unresolved-date.json')]:
        need(sha((out/a).read_bytes())==sha((out/b).read_bytes()),'P02_IDENTICAL_RETAINED_HYDRATIONS')
    d,doc=alder_descriptor
    loaded=load_repair(old/'book/repairs'/d['filename'],resume_session=cp['source_cursor'],
                       predecessor_checkpoint_sha256=doc['predecessor_checkpoint_sha256'])
    rows=seed(old,cp,old/'derived-correlation-prefix/prefix.jsonl.gz')
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',rows);args=arguments(out/'book',True)
    args[args.index('--policy')+1]=cp['base']['policy']
    save(out/'retained-input-admission.json',{'only_candidate':'P02','prior_components_retained_exactly':16,'components_added':0,
        'own_predecessor':cp['run']['checkpoint_sha256'],'input_sha256':cp['run']['input_sha256'],'source_conversion':False,
        'new_origin':False,'new_overlay':False,'restored_observer_prefix_rows':len(rows)})
    with v1,spin,alder,idempotent_dispatch(alder):
        qualify_dispatch(alder,loaded,out)
        with observer:
            with Execution('FAST',signal_closes=1) as execution:code=backtest.main(args)
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    need(current['base']==cp['base'] and current['repairs']==cp['repairs']
         and current['run']['input_sha256']==cp['run']['input_sha256'],'P02_RETAINED_FINANCIAL_INPUT_IDENTITY_UNCHANGED')
    save(out/'p02-retained-outcome.json',{'session':current['source_cursor'],'completed':current['completed'],
        'complete':current['source_cursor']==backtest.END and current['completed']==2156,'new_origin':False,
        'new_overlay':False,'financial_source_changed':False,'production_contacted':False,'only_candidate':'P02'})
    need(code==0,'P02_RETAINED_REFUSED_PREFIX_PRESERVED')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True);p.add_argument('--spec',type=Path,required=True)
    a=p.parse_args();hosted();spec=json.loads(a.spec.read_bytes())
    if a.mode=='economic':run(Path('/out'),Path('/old'),spec)
    else:review(Path('/out'),Path('/evidence'),Path('/old'),spec)
