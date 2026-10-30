"""Hosted sequential reconstruction probes; never select an economic predecessor."""
from contextlib import nullcontext
from copy import copy
from array import array
from collections import deque
import hashlib,json,math,time
from pathlib import Path

from full_system_core import hosted,arguments
from full_system_benchmark import need,save
from system_campaign_facts import sha
from system_campaign_resume_window import Reconstruction,exact_buffer,plain,compare,source_contract
from system_campaign_factual_run import preflight,correlation_seed,SeededObservation,preserve_tails
from system_campaign_p02_retained_run import idempotent_dispatch
from system_campaign_uncertainty_support import retained
from system_campaign_uncertainty_input import InputCodec
from system_campaign_uncertainty_facts import evidence
from system_campaign_uncertainty_context import SensorCertificate
from system_campaign_uncertainty_review import preserve_and_seed
from system_campaign_uncertainty_archive import review as review_certificate,preserve as preserve_event_archive
from system_campaign_p02_calendar_run import retained_amendment
from system_campaign_sprint_facts import preserve_prior_facts
from system_campaign_spring2020_cash_facts import preserve_sprint
from system_campaign_autumn2020_cash_facts import preserve_spring_cash
from system_campaign_2021_completions_facts import preserve_autumn_cash
from system_campaign_following_completions_facts import preserve_completions2021
from system_campaign_amendment_build import preserve_following
from system_campaign_ordinary_registry import preserve as preserve_registered
from system_campaign_acceleration import Execution
from system_campaign_replay_timing import ReplayTiming


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def expect_refusal(fn,reason):
    try:fn()
    except ValueError:return
    raise ValueError('REFUSED_RECONSTRUCTION_FALSIFIER_DID_NOT_REFUSE:'+reason)


def require_predecessor(cp,spec):
    need(cp['sha256']==spec['outer_sha256'] and cp['source_cursor']==spec['selected_session']
         and cp['base']==spec['base'] and cp['repairs']==spec['repairs'] and cp['journals']==spec['journals']
         and cp['run']['checkpoint_sha256']==spec['inner_sha256']
         and cp['run']['state_sha256']==spec['state_sha256'] and cp['run']['input_sha256']==spec['input_sha256'],
         'RECONSTRUCTION_EXACT_OWN_PREDECESSOR_BINDINGS')


def falsify(buffer):
    hosted();checks=[]
    bad=copy(buffer);bad.index+=1
    expect_refusal(lambda:compare(buffer,bad),'absolute_index');checks.append('absolute_index')
    bad=copy(buffer);bad.axis=deque(buffer.axis,maxlen=300);bad.axis[-1]='0000-00-00'
    expect_refusal(lambda:compare(buffer,bad),'axis');checks.append('axis')
    bad=copy(buffer);bad.metadata=dict(buffer.metadata);bad.metadata['bad_unregistered_identity']=None
    expect_refusal(lambda:compare(buffer,bad),'metadata');checks.append('metadata')
    bad=copy(buffer);bad.rings=dict(buffer.rings);changed=False
    for sid,ring in buffer.rings.items():
        for field,values in ring.values.items():
            offset=next((i for i,v in enumerate(values) if math.isfinite(v)),None)
            if offset is None:continue
            candidate=copy(ring);candidate.values=dict(ring.values);candidate.values[field]=array(values.typecode,values)
            candidate.values[field][offset]=math.nextafter(values[offset],math.inf)
            bad.rings[sid]=candidate;changed=True;break
        if changed:break
    need(changed,'RECONSTRUCTION_ACTUAL_FINITE_PRICE_FALSIFIER_AVAILABLE')
    expect_refusal(lambda:compare(buffer,bad),'packed_price');checks.append('packed_price')
    bad=copy(buffer);bad.current=None
    expect_refusal(lambda:require_packet_change(buffer,bad),'current_packet');checks.append('current_packet')
    return checks


def require_packet_change(original,bad):
    # Avoid an AttributeError being counted as a successful guard falsifier.
    need(bad.current is not None,'RECONSTRUCTION_EXACT_CURRENT_PACKET_PRESENT')
    return compare(original,bad)


class Capture:
    def __init__(self,cursor,next_session):self.cursor=cursor;self.next_session=next_session;self.buffers={};self.published=[]
    def __enter__(self):
        hosted()
        from research.pooled_input_support.adapter import Buffer
        self.Buffer=Buffer;self.append=Buffer.append;self.prepare=Buffer.prepare
        def append(buffer,packet):
            value=self.append(buffer,packet)
            if packet.day in (self.cursor,self.next_session):
                need(packet.day not in self.buffers,'RECONSTRUCTION_ONE_CAPTURE_PER_SOURCE_BOUNDARY')
                self.buffers[packet.day]=fingerprint(exact_buffer(buffer))
                if packet.day==self.cursor:self.falsifiers=falsify(buffer)
            return value
        def prepare(buffer,prior,*args,**kwargs):
            value=self.prepare(buffer,prior,*args,**kwargs)
            need(value.session==self.next_session and not self.published,'RECONSTRUCTION_ONLY_ONE_NEXT_PUBLICATION')
            self.published.append(fingerprint(plain(value)));return value
        Buffer.append=append;Buffer.prepare=prepare;return self
    def __exit__(self,*args):self.Buffer.append=self.append;self.Buffer.prepare=self.prepare


def probe(out,old,spec,controller_sources,mode):
    hosted()
    from research.pooled_input_support.bundle import axis
    from research.pooled_vacancy_funding import backtest,journal
    need(mode in ('COLD','BOUNDED'),'RECONSTRUCTION_EXPLICIT_PROBE_MODE')
    began=time.perf_counter();cp=preflight(spec,old,out,before='9999-12-31')
    require_predecessor(cp,spec)
    expect_refusal(lambda:require_predecessor(cp,{**spec,'outer_sha256':'0'*64}),'predecessor')
    need(cp['completed']>0 and cp['source_cursor']<backtest.END,'RECONSTRUCTION_MEASURED_OWN_PREFIX_ONLY')
    dates=axis();full=dates[dates.index(backtest.START)-425:dates.index(backtest.END)+1]
    next_session=full[full.index(cp['source_cursor'])+1]
    v1,spin,alder,_=retained(cp,old,out)
    (out/'hydrated-uncertainty-event.json').write_bytes((old/'hydrated-uncertainty-event.json').read_bytes())
    seed=preserve_and_seed(old,out,cp);preserve_event_archive(old,out)
    for fn in (preserve_prior_facts,preserve_sprint,preserve_spring_cash,preserve_autumn_cash,
               preserve_completions2021,preserve_following,preserve_registered):fn(cp,old,out)
    amendment=retained_amendment(old,out)
    observer=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
    codec=InputCodec(evidence(out));source=json.loads((out/'hydrated-uncertainty-event.json').read_bytes())
    certificate=SensorCertificate(out,codec,alder.native,controller_sources,seed=seed,event_source=source)
    args=arguments(out/'book',True,maximum=1);args[args.index('--policy')+1]=cp['base']['policy']
    source_hash=cp['base']['sources']['research/pooled_input_support/inputs.py']
    adapter_hash=cp['base']['sources']['research/pooled_input_support/adapter.py']
    from research.pooled_input_support import inputs
    raw_source=Path(inputs.__file__).read_bytes();source_contract(raw_source,source_hash)
    expect_refusal(lambda:source_contract(raw_source,'0'*64),'input_source_hash')
    acceleration=Reconstruction(full,cp['source_cursor'],input_source_sha256=source_hash,adapter_source_sha256=adapter_hash) if mode=='BOUNDED' else nullcontext()
    capture=Capture(cp['source_cursor'],next_session)
    with v1,spin,alder,idempotent_dispatch(alder),codec,amendment,certificate,observer:
        with Execution('FAST',signal_closes=1) as execution,ReplayTiming(out),capture,acceleration:
            start=time.perf_counter();code=backtest.main(args);elapsed=time.perf_counter()-start
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observer.proof())
    need(code==0,'RECONSTRUCTION_ORIGINAL_FINANCIAL_PROBE_REFUSED')
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    need(current['source_cursor']==next_session and current['completed']==cp['completed']+1
         and current['base']==cp['base'] and current['repairs']==cp['repairs'],
         'RECONSTRUCTION_ONE_ADJACENT_SESSION_SAME_ORIGIN_SOURCE_INPUTS')
    need(set(capture.buffers)=={cp['source_cursor'],next_session} and len(capture.published)==1,
         'RECONSTRUCTION_ALL_ACTUAL_BUFFER_AND_PUBLICATION_CAPTURES')
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',json.loads((out/'factual-preflight.json').read_bytes())))
    from system_campaign_factual_run import review as financial_review
    audit=out/'independent-review';audit.mkdir()
    with InputCodec(evidence(out)):
        financial_review(audit,out,old,spec)
        review_certificate(out,audit/'interval-review.json')
    proof=dict(schema='research.exact-reconstruction-one-transition-probe/1',mode=mode,
        original_checkpoint_sha256=cp['sha256'],checkpoint_sha256=current['sha256'],next_session=next_session,
        original_completed=cp['completed'],completed=current['completed'],buffer_fingerprints=capture.buffers,
        published_fingerprint=capture.published[0],actual_material_falsifiers=capture.falsifiers+['predecessor','input_source_hash'],
        financial_driver_seconds=elapsed,total_seconds=time.perf_counter()-began,
        qualification_only_not_economic_predecessor=True,production_contacted=False)
    save(out/'reconstruction-probe.json',proof);return proof


def compare_books(cold,bounded):
    """Pure byte/JSON comparison of stopped qualification evidence."""
    import gzip
    def cp(root):return json.loads(gzip.decompress((root/'book/checkpoint.json.gz').read_bytes()))
    left,right=cp(cold),cp(bounded)
    need(left==right,'RECONSTRUCTION_EVERY_NEXT_CANONICAL_CHECKPOINT_FIELD')
    for name,c in left['journals'].items():
        a=(cold/f'book/{name}.jsonl').read_bytes();b=(bounded/f'book/{name}.jsonl').read_bytes()
        need(a[:c['bytes']]==b[:c['bytes']] and len(a)==len(b)==c['bytes'],
             'RECONSTRUCTION_EVERY_COMMITTED_JOURNAL_BYTE_NO_NEW_TAIL')
    for name in ('correlation-inputs.jsonl.gz','uncertainty-certificate.jsonl'):
        a=(cold/name).read_bytes();b=(bounded/name).read_bytes()
        if name.endswith('.gz'):a,b=gzip.decompress(a),gzip.decompress(b)
        need(a==b,'RECONSTRUCTION_ALL_OBSERVATION_AND_INTERVAL_ROWS')
    return dict(next_checkpoint_sha256=left['sha256'],completed=left['completed'],all_next_checkpoint_fields_and_journal_bytes_equal=True)


def qualify(out,old,spec,controller_sources):
    hosted();need(spec['arm']=='P02','RECONSTRUCTION_ONLY_SELECTED_P02_QUALIFICATION')
    proofs={}
    for mode in ('COLD','BOUNDED'):
        root=out/mode.lower();root.mkdir();proofs[mode]=probe(root,old,spec,controller_sources,mode)
    left,right=proofs['COLD'],proofs['BOUNDED']
    need(left['original_checkpoint_sha256']==right['original_checkpoint_sha256']==spec['outer_sha256']
         and left['buffer_fingerprints']==right['buffer_fingerprints']
         and left['published_fingerprint']==right['published_fingerprint'],'RECONSTRUCTION_ACTUAL_BUFFER_AND_PUBLICATION_EQUAL')
    result=compare_books(out/'cold',out/'bounded')
    proof=dict(schema='research.exact-reconstruction-hosted-qualification/1',status='EXACT_NEXT_TRANSITION_EQUAL',
        predecessor=spec['outer_sha256'],probes=proofs,comparison=result,
        financial_candidate_or_parameters_changed=False,selected_for_economic_use=False,production_contacted=False)
    save(out/'reconstruction-qualification.json',proof);return proof
