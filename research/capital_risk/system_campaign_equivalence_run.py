"""Hosted bounded canonical proof; never adopts an unknown or running book."""
import argparse,gzip,hashlib,json
from contextlib import nullcontext
from pathlib import Path
from full_system_core import arguments,hosted
from full_system_benchmark import need,save
from system_campaign_acceleration import Execution
from system_campaign_facts import FactualInputs,CATALOG_REF,sha
from system_campaign_terminal_facts import TerminalFacts
from system_campaign_winter_facts import WinterCash
from system_campaign_terminal_run import merge_future_documents
from system_campaign_factual_run import preflight,correlation_seed,SeededObservation,preserve_tails,review as canonical_review
from system_campaign_equivalence import compare_buffers,compare_cutoff,compare_records
from system_campaign_basis import basis

CUTOFF='2019-04-30'


def read(root,name):
    from research.pooled_vacancy_funding import journal
    return journal.read_checkpoint(root/name)


def repairs(book,cp):
    from research.pooled_vacancy_funding.repair import load_repair
    result=[]
    for d in cp['repairs']:
        p=book/'repairs'/d['filename'];need(sha(p.read_bytes())==d['sha256'],'BASIS_PROOF_EXACT_REPAIR_BYTES')
        result.append(load_repair(p,resume_session=d['resume_session'],predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']))
    return result


def compare_capture(old,new):
    values=[]
    for root in (old,new):
        rows=[]
        with gzip.open(root/'correlation-inputs.jsonl.gz','rb') as stream:
            for raw in stream:
                value=json.loads(raw)
                if value['session']>CUTOFF:break
                for key in ('input_sha256','chain_sha256'):
                    need(key in value,'BASIS_PROOF_CAPTURE_IDENTITY_PRESENT');value.pop(key)
                rows.append(value)
        values.append(rows)
    need(values[0]==values[1],'BASIS_PROOF_ALL_CAUSAL_CAPTURE_MATERIAL_EXACT')
    return len(values[0])


def endpoints(old,out,spec):
    complete=read(old,'book/checkpoint.json.gz');selected=read(old,spec['selected_checkpoint'])
    need(complete['completed']==2156 and complete['source_cursor']=='2026-07-31'
         and selected['source_cursor']=='2017-07-31','BASIS_PROOF_COMPLETE_AND_PRE_EVENT_OWN_BOOK')
    targets=list((old/'book/month-end').glob(CUTOFF+'*.json.gz'));need(len(targets)==1,'BASIS_PROOF_OWN_CUTOFF_CHECKPOINT')
    old_cutoff=read(targets[0].parent,targets[0].name);new=read(out,'book/checkpoint.json.gz')
    document=json.loads((out/'basis-input-overlay.json').read_bytes())
    proof=compare_cutoff(old_cutoff,new,complete,selected,document,CUTOFF)
    proof['financial_record_counts']=compare_records(old/'book',out/'book',old_cutoff,new)
    proof['causal_capture_records_exact']=compare_capture(old,out)
    return proof,new,selected


def qualify_buffers(old,out,cp,new_cp):
    """Reconstruct both packet buffers without advancing any Core/account state."""
    from research.pooled_input_support import inputs,adapter
    from research.pooled_input_support.bundle import axis
    from research.pooled_vacancy_funding import backtest
    full=axis();first=full[full.index(backtest.START)-425]
    old_repairs=repairs(old/'book',cp);new_repairs=repairs(out/'book',new_cp)
    left=adapter.Buffer();right=adapter.Buffer()
    for packet in inputs.packets(Path('/frozen/bundle'),Path('/frozen/archive/corpus.zip')):
        if packet.day<first:continue
        if packet.day>CUTOFF:break
        a=b=packet
        for overlay in old_repairs:a=backtest.apply_repair(a,overlay)
        for overlay in new_repairs:b=backtest.apply_repair(b,overlay)
        left.append(a);right.append(b)
    need(left.current.day==right.current.day==CUTOFF,'BASIS_PROOF_COMPLETE_BUFFER_AXIS')
    return compare_buffers(left,right)


def run(out,old,spec):
    hosted()
    from research.pooled_input_support import inputs,adapter
    from research.pooled_input_support.bundle import axis
    from research.pooled_vacancy_funding import backtest,journal
    complete=read(old,'book/checkpoint.json.gz')
    need(complete['completed']==2156 and complete['source_cursor']=='2026-07-31',
         'BASIS_PROOF_ONLY_COMPLETE_STOPPED_BOOK')
    cp=preflight(spec,old,out,before='2017-08-28')
    need(cp['source_cursor']=='2017-07-31' and complete['repairs']==cp['repairs'],
         'BASIS_PROOF_FIXED_OWN_BOUNDARY_NO_LATER_SUCCESSOR')
    retained=[json.loads((old/'book/repairs'/d['filename']).read_bytes()) for d in cp['repairs']]
    need(any(v['reference']==CATALOG_REF for d in retained for v in d['source_evidence']),
         'BASIS_PROOF_RETAINED_V1_FACTS')
    v1=FactualInputs('/driver/system-campaign-factual-catalog.json');v1.hydrate(out/'hydrated-factual-catalog.json')
    additional=TerminalFacts('/driver/system-campaign-additional-terminal-facts.json')
    additional.hydrate(out/'hydrated-additional-terminal-catalog.json');additional.overlay(cp,out/'additional-component.json')
    winter=WinterCash('/driver/system-campaign-corrected-winter-facts.json')
    winter.hydrate(out/'hydrated-corrected-winter-cash-catalog.json');winter.overlay(cp,out/'winter-component.json')
    merged=merge_future_documents(json.loads((out/'additional-component.json').read_bytes()),
                                  json.loads((out/'winter-component.json').read_bytes()))
    path=out/'basis-input-overlay.json';save(path,merged)
    from research.pooled_vacancy_funding.repair import load_repair
    loaded=load_repair(path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    full=axis();first=full[full.index(backtest.START)-425];transitions=full.index(CUTOFF)-full.index(cp['source_cursor'])
    original_packets=inputs.packets;original_buffer=adapter.Buffer;old_buffer=original_buffer();new_buffers=[]
    old_repairs=repairs(old/'book',cp)
    def packets(*args,**kwargs):
        for packet in original_packets(*args,**kwargs):
            if first<=packet.day<=CUTOFF:
                value=packet
                for term in old_repairs:value=backtest.apply_repair(value,term)
                old_buffer.append(value)
            yield packet
    def construct():
        value=original_buffer();new_buffers.append(value);return value
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
    args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
    with v1:
        additional.qualify(loaded,out/'additional-input-qualification.json');winter.qualify(loaded,out/'winter-input-qualification.json')
        inputs.packets=packets;adapter.Buffer=construct
        try:
            with observer:
                with Execution('FAST',signal_closes=1) as execution:
                    code=backtest.main(args+['--repair-overlay',str(path),'--max-transitions',str(transitions)])
        finally:inputs.packets=original_packets;adapter.Buffer=original_buffer
    need(code==0 and len(new_buffers)==1 and new_buffers[0].current.day==old_buffer.current.day==CUTOFF,
         'BASIS_PROOF_ACTUAL_BOUNDED_CANONICAL_REPLAY')
    buffer_sha=compare_buffers(old_buffer,new_buffers[0])
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observer.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    proof,new,_=endpoints(old,out,spec);common_sha,common=basis(out,new)
    save(out/'common-factual-basis.json',common)
    save(out/'basis-equivalence-worker.json',{'schema':'research.system-campaign-basis-equivalence/1',
         **proof,'complete_buffer_sha256':buffer_sha,'common_factual_basis_sha256':common_sha,
         'actual_replayed_transitions':transitions,'new_origin':False,'production_contacted':False,
         'old_complete_physical_lineage_unchanged':True,'independent_review_required':True})


def review(out,evidence,old,spec):
    hosted();canonical_review(out,evidence,old,spec)
    proof,new,selected=endpoints(old,evidence,spec)
    v1=FactualInputs('/driver/system-campaign-factual-catalog.json')
    # Qualify the same immutable frozen hydration independently in the reader.
    v1.hydrate(out/'review-hydrated-v1.json')
    with v1:buffer_sha=qualify_buffers(old,evidence,selected,new)
    worker=json.loads((evidence/'basis-equivalence-worker.json').read_bytes())
    need(worker['complete_buffer_sha256']==buffer_sha and all(worker[k]==v for k,v in proof.items()),
         'BASIS_PROOF_INDEPENDENT_FULL_EQUIVALENCE')
    common_sha,common=basis(evidence,new)
    need(worker['common_factual_basis_sha256']==common_sha
         and json.loads((evidence/'common-factual-basis.json').read_bytes())==common,'BASIS_PROOF_INDEPENDENT_SEMANTIC_INPUTS')
    save(out/'basis-equivalence-review.json',{**worker,'independent_review_required':False,
         'independent_review_passed':True,'source_file_sha256':sha(Path(__file__).read_bytes())})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True)
    p.add_argument('--spec',type=Path,required=True);a=p.parse_args();hosted();spec=json.loads(a.spec.read_bytes())
    if a.mode=='economic':run(Path('/out'),Path('/old'),spec)
    else:review(Path('/out'),Path('/evidence'),Path('/old'),spec)
