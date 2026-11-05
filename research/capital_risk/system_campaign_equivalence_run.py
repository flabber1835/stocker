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
from system_campaign_spring_facts import SpringFacts
from system_campaign_followup_facts import FollowupFacts
from system_campaign_tgi_facts import TgiCash
from system_campaign_midyear_facts import MidyearFacts
from system_campaign_terminal_run import merge_future_documents
from system_campaign_factual_run import preflight,correlation_seed,SeededObservation,preserve_tails,qualify_inputs,review as canonical_review
from system_campaign_equivalence import compare_buffers,compare_cutoff,compare_records
from system_campaign_basis import basis

CUTOFF='2019-04-30'


def observed_buffer_type(original,instances):
    class ObservedBuffer(original):
        def __init__(self):
            super().__init__();instances.append(self)
    return ObservedBuffer


def read(root,name):
    from research.pooled_vacancy_funding import journal
    return journal.read_checkpoint(root/name)


def own_snapshot(root,day,base,descriptors,inner=None):
    """Resolve actual nested lineage by identity, never by date alone."""
    from research.pooled_vacancy_funding import backtest,runtime
    from research.pooled_input_support.bundle import axis
    full=axis();wanted=full[full.index(backtest.START)-425:full.index(backtest.END)+1];found={}
    for path in root.rglob('*.json.gz'):
        if not (path.name.startswith(day) or path.parent.name=='predecessor-checkpoints'):continue
        cp=read(path.parent,path.name)
        if cp['source_cursor']!=day or cp['base']!=base or cp['repairs']!=descriptors:continue
        if inner is not None and cp['run']['checkpoint_sha256']!=inner:continue
        backtest.validate_checkpoint(cp,base,wanted)
        state=runtime.restore(cp['run'],policy=base['policy'],input_sha256=backtest.input_hash(base,descriptors))
        need(runtime.checkpoint(state)==cp['run'],'BASIS_PROOF_NESTED_OWN_CANONICAL_ROUNDTRIP')
        found.setdefault(cp['sha256'],(cp,path))
    need(len(found)==1,'BASIS_PROOF_UNIQUE_EXACT_NESTED_OWN_SNAPSHOT')
    return next(iter(found.values()))


def future_successors(old,complete,selected):
    from research.pooled_vacancy_funding import backtest
    from research.pooled_vacancy_funding.repair import load_repair
    from full_system_core import committed_watch
    count=len(selected['repairs']);extra=complete['repairs'][count:]
    need(complete['repairs'][:count]==selected['repairs'],'BASIS_PROOF_RETAINED_REPAIR_PREFIX')
    ids={d['sha256'] for d in extra}
    events=[e for e in committed_watch(old/'book',complete)
        if e.get('schema')=='research.pooled-action-successor/1' and e['overlay']['sha256'] in ids]
    need([e['overlay'] for e in events]==extra,'BASIS_PROOF_ACTUAL_FUTURE_SUCCESSOR_AXIS')
    documents=[];proofs=[]
    for n,(descriptor,event) in enumerate(zip(extra,events),count):
        raw=(old/'book/repairs'/descriptor['filename']).read_bytes()
        need(sha(raw)==descriptor['sha256'],'BASIS_PROOF_FUTURE_REPAIR_ACTUAL_BYTES')
        document=json.loads(raw);day=descriptor['resume_session']
        parsed=load_repair(old/'book/repairs'/descriptor['filename'],resume_session=day,
            predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'])
        need(parsed.sha256==descriptor['sha256'] and parsed.earliest_affected_session>day,
             'BASIS_PROOF_CANONICAL_FUTURE_INPUT_PARSER')
        need(day>=selected['source_cursor'] and event['unchanged_through']==day,
             'BASIS_PROOF_ACTUAL_INPUT_SUCCESSOR_BOUNDARY')
        cp,path=own_snapshot(old,day,complete['base'],complete['repairs'][:n],descriptor['predecessor_checkpoint_sha256'])
        need(event['predecessor_checkpoint_sha256']==cp['run']['checkpoint_sha256']
             and event['state_sha256']==cp['run']['state_sha256']
             and event['predecessor_input_sha256']==backtest.input_hash(complete['base'],complete['repairs'][:n])
             and event['successor_input_sha256']==backtest.input_hash(complete['base'],complete['repairs'][:n+1]),
             'BASIS_PROOF_ACTUAL_UNCHANGED_STATE_INPUT_REBIND')
        documents.append(document);proofs.append({'overlay_sha256':descriptor['sha256'],
            'predecessor_outer_sha256':cp['sha256'],'predecessor_gzip_sha256':sha(path.read_bytes()),
            'unchanged_state_sha256':event['state_sha256'],'session':day})
    return documents,proofs


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
         and selected['source_cursor']=='2017-07-17','BASIS_PROOF_COMPLETE_AND_PRE_EVENT_OWN_BOOK')
    old_prefix=[d for d in complete['repairs'] if d['resume_session']<=CUTOFF]
    old_cutoff,old_path=own_snapshot(old,CUTOFF,complete['base'],old_prefix)
    new=read(out,'book/checkpoint.json.gz')
    document=json.loads((out/'basis-input-overlay.json').read_bytes())
    future,bindings=future_successors(old,complete,selected)
    proof=compare_cutoff(old_cutoff,new,complete,selected,document,CUTOFF,future_documents=future)
    proof['actual_future_input_bindings']=bindings
    proof['old_cutoff_gzip_sha256']=sha(old_path.read_bytes())
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
    need(spec['arm']=='P00' and complete['completed']==2156 and complete['source_cursor']=='2026-07-31',
         'BASIS_PROOF_ONLY_COMPLETE_STOPPED_BOOK')
    cp=preflight(spec,old,out,before='2017-08-28')
    need(cp['source_cursor']=='2017-07-17' and complete['repairs'][:len(cp['repairs'])]==cp['repairs'],
         'BASIS_PROOF_FIXED_OWN_BOUNDARY_RETAINED_REPAIRS')
    v1=FactualInputs('/driver/system-campaign-factual-catalog.json');v1.hydrate(out/'hydrated-factual-catalog.json')
    v1.overlay(cp,out/'v1-component.json')
    additional=TerminalFacts('/driver/system-campaign-additional-terminal-facts.json')
    additional.hydrate(out/'hydrated-additional-terminal-catalog.json');additional.overlay(cp,out/'additional-component.json')
    winter=WinterCash('/driver/system-campaign-corrected-winter-facts.json')
    winter.hydrate(out/'hydrated-corrected-winter-cash-catalog.json');winter.overlay(cp,out/'winter-component.json')
    merged=merge_future_documents(json.loads((out/'additional-component.json').read_bytes()),
                                  json.loads((out/'winter-component.json').read_bytes()))
    merged=merge_future_documents(json.loads((out/'v1-component.json').read_bytes()),merged)
    spring=SpringFacts('/driver/system-campaign-spring-terminal-facts.json')
    spring.hydrate(out/'hydrated-spring-terminal-catalog.json');spring.overlay(cp,out/'spring-component.json')
    merged=merge_future_documents(json.loads((out/'spring-component.json').read_bytes()),merged)
    followup=FollowupFacts('/driver/system-campaign-followup-terminal-facts.json')
    followup.hydrate(out/'hydrated-followup-terminal-catalog.json');followup.overlay(cp,out/'followup-component.json')
    merged=merge_future_documents(json.loads((out/'followup-component.json').read_bytes()),merged)
    midyear=MidyearFacts('/driver/system-campaign-midyear-terminal-facts.json')
    midyear.hydrate(out/'hydrated-midyear-terminal-catalog.json');midyear.overlay(cp,out/'midyear-component.json')
    merged=merge_future_documents(json.loads((out/'midyear-component.json').read_bytes()),merged)
    tgi=TgiCash('/driver/system-campaign-tgi-cash-facts.json')
    tgi.hydrate(out/'hydrated-tgi-cash-catalog.json');tgi.overlay(cp,out/'tgi-component.json')
    merged=merge_future_documents(json.loads((out/'tgi-component.json').read_bytes()),merged)
    path=out/'basis-input-overlay.json';save(path,merged)
    from research.pooled_vacancy_funding.repair import load_repair
    loaded=load_repair(path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    full=axis();first=full[full.index(backtest.START)-425];transitions=full.index(CUTOFF)-full.index(cp['source_cursor'])
    original_packets=inputs.packets;original_buffer=adapter.Buffer;old_buffer=original_buffer();new_buffers=[]
    old_repairs=repairs(old/'book',complete)
    def packets(*args,**kwargs):
        for packet in original_packets(*args,**kwargs):
            if first<=packet.day<=CUTOFF:
                value=packet
                for term in old_repairs:value=backtest.apply_repair(value,term)
                old_buffer.append(value)
            yield packet
    observed=observed_buffer_type(original_buffer,new_buffers)
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
    args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
    with v1:
        qualify_inputs(v1,loaded,out/'v1-input-qualification.json')
        additional.qualify(loaded,out/'additional-input-qualification.json');winter.qualify(loaded,out/'winter-input-qualification.json')
        spring.qualify(loaded,out/'spring-input-qualification.json')
        followup.qualify(loaded,out/'followup-input-qualification.json');tgi.qualify(loaded,out/'tgi-input-qualification.json')
        midyear.qualify(loaded,out/'midyear-input-qualification.json')
        inputs.packets=packets;adapter.Buffer=observed
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
    with v1:buffer_sha=qualify_buffers(old,evidence,read(old,'book/checkpoint.json.gz'),new)
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
