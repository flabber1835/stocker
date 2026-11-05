"""Hosted, source-bound distribution-only input and delegating child observer.

Generation1 and canonical financial implementations remain unchanged. This
module may reconstruct inputs locally only through pure synthetic test APIs;
all real frozen-source or financial entry points require hosted().
"""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction
import gzip
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

from full_system_benchmark import save
from full_system_core import hosted
from system_campaign_financial_compound_input_v2 import (
    sha, digest, encoded, need, build_terms, actual_role, EventSessionProjection, consideration)
from system_campaign_financial_compound_v2_support import (
    qualified_record, primary_binding, activation_descriptor, qualified_loaded_view,
    spin_postcondition, retained_payload_proof)
from system_campaign_financial_compound_ordinary_v2 import (
    ordinary_input, verify_ordinary, ordinary_document, ordinary_events, original_parent,
    select_original, MATERIAL, OBSERVER_SHA, OBSERVER_FILE)

HERE=Path(__file__).parent
PAYLOAD='hydrated-compound-input-v2.json'
PREFIX='compound-v2-retained-certificate-prefix.jsonl'
CERTIFICATE='uncertainty-certificate.jsonl'
OVERLAY='future-financial-overlay.json'
QUALIFICATION='compound-input-v2-qualification.json'
ORDINARY_QUALIFICATION='compound-v2-ordinary-qualification.json'
ACTUAL='actual-compound-event-v2.json'
CATALOG_REF='research.compound-distribution-input/catalog/2'
RUNTIME_REF='research.compound-distribution-input/runtime/2'
MODEL_REF='research.compound-distribution-input/model/2'
SUPPORT_REF='research.compound-distribution-input/support/2'
ORDINARY_REF='research.compound-distribution-input/ordinary/2'
OBSERVER_REF='research.compound-distribution-input/original-ordinary-observer-source/2'
PAYLOAD_REF='research.compound-distribution-input/payload/2'
SOURCE_REF='research.compound-distribution-input/closed-source-producer/2'
DATA_REF='research.compound-distribution-input/source-DATA/2'
ORIGINAL_COMPILER_REF='research.compound-distribution-input/original-distribution-compiler/2'
APHA_SHA='2165e64a961bf0ee44c8f19ac2d6ec65059cc92a2b4154ad735685d29e120777'
BRANCH_SHA='b19a93be7b6887c1b92a5a676fefecc5477addfaf99efcf1f18f45eafb6140ef'


def applies(cp,arm):
    from system_campaign_financial_compound_v2_support import CATALOG_FILE
    catalog=json.loads((HERE/CATALOG_FILE).read_bytes())
    return any((r['arm'],r['parent_outer_sha256'],r['parent_cursor'])
               ==(arm,cp['sha256'],cp['source_cursor']) for r in catalog['records'])


def source_parent(r):
    from system_campaign_financial_partial import root_spec
    spec=root_spec(r['arm'],r['parent_root_admission_sha256'])
    need((spec['outer_sha256'],spec['inner_sha256'],spec['input_sha256'],spec['selected_session'])
         ==(r['parent_outer_sha256'],r['parent_inner_sha256'],r['parent_input_sha256'],r['parent_cursor']),
         'COMPOUND_V2_SEPARATE_ORIGINAL_OWN_ADMITTED_PARENT')
    return spec


def reconstruct_source(r,spec):
    hosted()
    import system_campaign_financial_distribution_source_v2 as source
    from research.pooled_input_support import inputs
    from research.bounded_20y import run
    proof=r['source_proof'];scope=r['source_scope'];primary_binding(r)
    need(sha(Path(source.__file__).read_bytes())==proof['distribution_producer_sha256']
         and sha(Path(run.__file__).read_bytes())==source.PARSER_SHA,
         'COMPOUND_V2_EXACT_CLOSED_PRODUCER_AND_ORIGINAL_PARSER')
    source.distribution_only_scope(scope)
    keys={(v['session'],v['security_id']) for v in scope['additional_rows']};rows=[]
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        raw=archive.read('actions.csv.gz')
        need(len(raw)==source.ACTIONS_BYTES and sha(raw)==source.ACTIONS_SHA,
             'COMPOUND_V2_EXACT_FROZEN_ACTION_MEMBER')
        raw_actions=list(inputs._archive_rows(archive,'actions.csv.gz'))
        raw_spins=source.distribution_only_native_rows(scope,raw_actions)
        for year in sorted({day[:4] for day,_ in keys}):
            rows.extend(v for v in inputs._archive_rows(archive,'observations-'+year+'.csv.gz')
                        if (v['session'],v['security_id']) in keys)
    typed=run.distributions(raw_spins)
    pairs=source.distribution_only_pairing(scope,raw_spins,[asdict(v) for values in typed.values() for v in values])
    positions={v['security_id']:deepcopy(v['parent_positions']) for v in scope['additional_rows']}
    material=source.distribution_only_material(scope,rows,pairs,positions)
    value=source.distribution_only_payload(spec,scope,material,proof['producer_sha256'])
    source.distribution_only_validate(value,spec,scope,proof['producer_sha256'])
    need(sha(encoded(value))==proof['payload_sha256'] and digest(value)==proof['payload_digest'],
         'COMPOUND_V2_EXACT_CLOSED_RECEIPT_RECONSTRUCTION')
    return value,inputs.load_actions(Path('/frozen/bundle')),run.distributions(raw_actions)


def committed_prefix(raw,cursor):
    lines=raw.splitlines(keepends=True);rows=[json.loads(v) for v in lines]
    selected=[(line,row) for line,row in zip(lines,rows) if row['session']<=cursor]
    need(len(selected)==384 and [r['session'] for _,r in selected]==sorted(r['session'] for _,r in selected)
         and all(r['session']<=cursor for _,r in selected)
         and lines[:len(selected)]==[v for v,_ in selected]
         and all(v.endswith(b'\n') for v,_ in selected),
         'COMPOUND_V2_EXACT384_COMMITTED_BRANCH_PREFIX_NO_TAIL')
    return b''.join(v for v,_ in selected)


def input_payload(r,spec,source,material,prefix):
    binding=build_terms(r['research_assumption'],source,child_security_id=r['child_security_id'],
                        reference=r['reference'],source_proof=r['source_proof'])
    origin=original_parent(spec)
    return dict(schema='research.hydrated-compound-distribution-input/2',record_sha256=digest(r),
        source_payload=source,binding=binding,ordinary_material=material,base=deepcopy(spec['base']),
        original_parent=origin,retained_certificate=dict(rows=384,sha256=sha(prefix)),
        financial_state_changed=False,production_contacted=False)


def hydrate(cp,arm,root):
    hosted();r=qualified_record(arm);spec=source_parent(r);origin=original_parent(spec)
    need(cp['sha256']==origin['sha256'] and cp['source_cursor']==origin['source_cursor']
         and cp['run']['checkpoint_sha256']==origin['run']['checkpoint_sha256']
         and cp['run']['input_sha256']==origin['run']['input_sha256'] and cp['base']==origin['base']
         and cp['repairs']==origin['repairs']
         and sha((Path(root)/'source-bindings.json').read_bytes())==r['source_bindings_sha256'],
         'COMPOUND_V2_EXACT_OWN_ROOT_GENERATION_REPAIRS_AND_BINDING')
    source,actions,spins=reconstruct_source(r,spec)
    material,_,_=ordinary_input(cp,r,root)
    prefix=committed_prefix((Path(root)/CERTIFICATE).read_bytes(),cp['source_cursor'])
    p=input_payload(r,spec,source,material,prefix)
    actual_role(cp['run']['state'],cp['run']['state']['pending'],p['binding'])
    return p,actions,spins,prefix


def refs(raw,r):
    from system_campaign_financial_compound_v2_support import CATALOG_SHA
    files={RUNTIME_REF:Path(__file__),MODEL_REF:HERE/'system_campaign_financial_compound_input_v2.py',
        SUPPORT_REF:HERE/'system_campaign_financial_compound_v2_support.py',
        ORDINARY_REF:HERE/'system_campaign_financial_compound_ordinary_v2.py',
        OBSERVER_REF:HERE/OBSERVER_FILE,
        ORIGINAL_COMPILER_REF:HERE/'system_campaign_distribution_facts.py'}
    return dict({key:sha(path.read_bytes()) for key,path in files.items()},**{
        CATALOG_REF:CATALOG_SHA,PAYLOAD_REF:sha(raw),SOURCE_REF:r['source_proof']['distribution_producer_sha256'],
        DATA_REF:r['source_proof']['independent_data_review_sha256']})


def document(p,raw):
    r=qualified_record(p['ordinary_material']['arm']);doc=ordinary_document(p['ordinary_material'])
    added=[dict(reference=key,sha256=value,description='Qualified compound distribution input; unchanged canonical financial engine.')
           for key,value in sorted(refs(raw,r).items())]
    need(not ({v['reference'] for v in added}&{v['reference'] for v in doc['source_evidence']}),
         'COMPOUND_V2_NO_AMBIGUOUS_ORDINARY_OR_COMPOUND_REFERENCE')
    doc['source_evidence']=sorted(doc['source_evidence']+added,key=lambda v:v['reference'])
    return doc


def verify_payload(root):
    hosted();root=Path(root);raw=(root/PAYLOAD).read_bytes();p=json.loads(raw)
    r=qualified_record(p['ordinary_material']['arm']);spec=source_parent(r);source,_,_=reconstruct_source(r,spec)
    material=p['ordinary_material'];verify_ordinary(material,original_parent(spec),r,root)
    prefix=(root/PREFIX).read_bytes()
    need(prefix==committed_prefix(prefix,r['parent_cursor']), 'COMPOUND_V2_RETAINED_PREFIX_EXACT_ORIGINAL_BOUNDARY')
    expected=input_payload(r,spec,source,material,prefix)
    need(p==expected,'COMPOUND_V2_COMPLETE_INPUT_RECONSTRUCTION_NO_OTHER_BOOK')
    return p,raw


class ProjectionContext:
    def __init__(self,root,overlay=OVERLAY,*,payload=None,api=None):
        self.root=Path(root);self.overlay=self.root/overlay
        self.payload,self.raw=verify_payload(root) if payload is None else payload
        self.document=json.loads(self.overlay.read_bytes());self.overlay_sha=sha(self.overlay.read_bytes())
        need(self.document==document(self.payload,self.raw),'COMPOUND_V2_EXACT_ACTIVATED_NONEMPTY_ORDINARY_DOCUMENT')
        self.api=api;self.bound_objects=[];self.changed_packets=0;self.active=False

    def __enter__(self):
        hosted()
        if self.api is None:
            from research.pooled_vacancy_funding import backtest,repair
            from research.bounded_20y.run import vendor
            from sentinel.core.spinoffs import SpinoffDistribution
            self.api=SimpleNamespace(backtest=backtest,repair=repair,vendor=vendor,spin_factory=SpinoffDistribution)
        a=self.api;b=self.payload['binding'];rows=b['original_rows']
        self.projection=EventSessionProjection(b,parent_bar=a.vendor(rows[b['spin']['parent_security_id']]),
            child_bar=a.vendor(rows[b['spin']['child_security_id']]),source_raw=Path(a.repair.__file__).read_bytes(),
            source_namespace=vars(a.repair),spin_factory=a.spin_factory)
        self.original_load=a.backtest.load_repair;self.original_apply=a.backtest.apply_repair
        a.backtest.load_repair=self.load;a.backtest.apply_repair=self.apply;self.active=True
        return self

    def load(self,path,*,resume_session,predecessor_checkpoint_sha256):
        obj=self.original_load(path,resume_session=resume_session,predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        rows=[e for e in getattr(obj,'source_evidence',()) if e.reference==CATALOG_REF]
        if not rows:return obj
        origin=self.payload['original_parent'];record=qualified_record(self.payload['ordinary_material']['arm'])
        need(len(rows)==1 and Path(path).read_bytes()==self.overlay.read_bytes()
             and sha(Path(path).read_bytes())==self.overlay_sha and rows[0].sha256==refs(self.raw,record)[CATALOG_REF]
             and resume_session==origin['source_cursor']
             and predecessor_checkpoint_sha256==origin['run']['checkpoint_sha256'],
             'COMPOUND_V2_LOADER_EXACT_ACTIVATION_BYTES_AND_ORIGINAL_PARENT')
        activation=activation_descriptor(obj,self.payload['binding'],record['source_proof'])
        view=qualified_loaded_view(obj,self.payload['binding'],record['source_proof'],activation)
        self.bound_objects.append(view);return view

    def apply(self,packet,obj):
        fixed=self.original_apply(packet,obj)
        rows=[e for e in getattr(obj,'source_evidence',()) if e.reference==CATALOG_REF]
        if not rows:return fixed
        need(any(obj is value for value in self.bound_objects) and obj.sha256==self.overlay_sha,
             'COMPOUND_V2_APPLY_REQUIRES_ACTUAL_QUALIFIED_LOADED_OBJECT')
        changed=self.projection.apply(fixed,self.projection.descriptor)
        if changed!=fixed:self.changed_packets+=1
        return changed

    def __exit__(self,*args):
        self.api.backtest.load_repair=self.original_load;self.api.backtest.apply_repair=self.original_apply;self.active=False


def no_proxy_cash(binding,before_ledger,after_ledger,after_core):
    old=before_ledger['events'];events=after_ledger['events'][len(old):];parent=binding['spin']['parent_security_id']
    need(after_ledger['events'][:len(old)]==old
         and not any(v['security_id']==parent and v['event_type'] in ('DIVIDEND_ACCRUED','DIVIDEND_PAID') for v in events)
         and not any(v['security_id']==binding['spin']['child_security_id'] for v in after_core['episodes'].values()),
         'COMPOUND_V2_NO_DUPLICATE_IN_KIND_PROXY_CASH_OR_RETAINED_CHILD')
    return dict(parent_proxy_cash_accrued=False,parent_proxy_cash_paid=False,child_retained=False)


class Observer:
    def __init__(self,root,payload,*,api=None):
        self.root=Path(root);self.payload=payload;self.binding=payload['binding'];self.api=api;self.saved=[];self.current=None

    def patch(self,owner,name,fn):
        old=getattr(owner,name);self.saved.append((owner,name,old));setattr(owner,name,fn);return old

    def __enter__(self):
        hosted()
        if self.api is None:
            from research.pooled_vacancy_funding import runtime
            from sentinel.core import kernel,spinoffs
            self.api=SimpleNamespace(runtime=runtime,kernel=kernel,spinoffs=spinoffs)
        a=self.api
        for owner,key in ((a.runtime,'research/pooled_vacancy_funding/runtime.py'),
                          (a.kernel,'sentinel/core/kernel.py'),(a.spinoffs,'sentinel/core/spinoffs.py')):
            need(sha(Path(owner.__file__).read_bytes())==self.payload['base']['sources'][key],
                 'COMPOUND_V2_UNCHANGED_ACTUAL_FINANCIAL_SURFACE')
        self.kernel_code=a.kernel.advance_session.__code__
        self.advance_original=self.patch(a.runtime,'advance',self.advance)
        self.spin_original=self.patch(a.spinoffs,'apply_supported_entitlements',self.spin)
        return self

    def __exit__(self,*args):
        for owner,name,old in reversed(self.saved):setattr(owner,name,old)

    def advance(self,run,publication):
        if publication.session!=self.binding['spin']['session']:return self.advance_original(run,publication)
        need(self.current is None,'COMPOUND_V2_SINGLE_ACTUAL_ADVANCE')
        self.current=dict(session=publication.session,order=[],spin=None,proxy_cash=None)
        try:
            actual_role(dict(wealth_core=run.state.wealth_core,ledger=run.state.ledger),run.state.pending,self.binding)
            parent=[v for v in publication.bars if v.security_id==self.binding['spin']['parent_security_id']]
            selected=[v for v in publication.spinoff_distributions if v.parent_security_id==self.binding['spin']['parent_security_id']]
            need(len(parent)==len(selected)==1 and parent[0].dividend_per_share==0.
                 and asdict(selected[0])==self.binding['spin'],'COMPOUND_V2_ACTUAL_ONE_CHILD_AND_ZERO_PROXY_PUBLICATION')
            result=self.advance_original(run,publication)
            need(self.current['order']==['SPINOFF'] and self.current['spin'] is not None,
                 'COMPOUND_V2_ACTUAL_CANONICAL_CHILD_CALL_BEFORE_COMMIT')
            self.current['proxy_cash']=no_proxy_cash(self.binding,run.state.ledger,result.state.ledger,result.state.wealth_core)
            save(self.root/ACTUAL,dict(self.current,passed=True,financial_source_changed=False))
            return result
        except BaseException as error:
            save(self.root/'compound-event-v2-refusal.json',dict(self.current,passed=False,error=str(error),financial_source_changed=False));raise
        finally:self.current=None

    def spin(self,state,distributions,*,bars,ledger,config):
        selected=[v for v in distributions if v.source_row_id==self.binding['spin']['source_row_id']]
        if not selected:return self.spin_original(state,distributions,bars=bars,ledger=ledger,config=config)
        caller=inspect.currentframe().f_back
        need(self.current is not None and caller.f_code is self.kernel_code and len(selected)==1
             and asdict(selected[0])==self.binding['spin'],'COMPOUND_V2_ACTUAL_KERNEL_CHILD_CALL_ONLY')
        before=deepcopy(state.to_dict());lb=deepcopy(ledger.to_dict())
        pending=[v.to_dict() if hasattr(v,'to_dict') else asdict(v) for v in caller.f_locals['pending']]
        actual_role(dict(wealth_core=before,ledger=lb),pending,self.binding)
        # Preserve every unrelated distribution; isolate the same child source
        # audit only. The original source primitive still receives the full set.
        result=self.spin_original(state,distributions,bars=bars,ledger=ledger,config=config)
        self.current['spin']=spin_postcondition(self.binding,before,state.to_dict(),lb,ledger.to_dict(),result,config.transaction_cost_bps)
        self.current['order'].append('SPINOFF');return result


def retained_activation(root,cp):
    root=Path(root);found=[]
    for d in cp['repairs']:
        raw=(root/'book/repairs'/d['filename']).read_bytes()
        need(sha(raw)==d['sha256'],'COMPOUND_V2_ALL_RETAINED_REPAIR_BYTES')
        if any(v['reference']==CATALOG_REF for v in json.loads(raw).get('source_evidence',[])):found.append(d)
    if not found:
        need(not any((root/name).exists() for name in (PAYLOAD,PREFIX,MATERIAL)),
             'COMPOUND_V2_NO_UNCOMMITTED_RETAINED_INPUT_MATERIAL');return None
    need(len(found)==1,'COMPOUND_V2_ONE_COMMITTED_RETAINED_ACTIVATION')
    d,=found;p,raw=verify_payload(root);r=qualified_record(p['ordinary_material']['arm']);origin=p['original_parent']
    descriptor=dict(parent_outer_sha256=origin['sha256'],parent_cursor=origin['source_cursor'],payload_sha256=sha(raw),
        APHA_projection_source_sha256=APHA_SHA,branch_source_sha256=BRANCH_SHA,retained_certificate_rows=384)
    prefix=(root/PREFIX).read_bytes();need(sha(prefix)==p['retained_certificate']['sha256'], 'COMPOUND_V2_EXACT_PREFIX_HASH')
    retained_payload_proof(origin,cp,payload_raw=raw,descriptor=descriptor,prior_certificate_raw=prefix,
                           current_certificate_raw=(root/CERTIFICATE).read_bytes())
    need(d['resume_session']==origin['source_cursor'] and d['predecessor_checkpoint_sha256']==origin['run']['checkpoint_sha256']
         and sha((root/'source-bindings.json').read_bytes())==r['source_bindings_sha256']
         and (root/MATERIAL).read_bytes()==encoded(p['ordinary_material']),
         'COMPOUND_V2_RETAINED_ORIGINAL_CURSOR_BINDING_AND_MATERIAL')
    return ProjectionContext(root,'book/repairs/'+d['filename'],payload=(p,raw))


@contextmanager
def retained_context(root,cp,out):
    projection=retained_activation(root,cp)
    if projection is None:yield;return
    review_actual(projection.payload,root,cp)
    for name in (PAYLOAD,PREFIX,MATERIAL,QUALIFICATION,ORDINARY_QUALIFICATION,*retained_observation_files(projection.payload,root,cp)):
        source=Path(root)/name;target=Path(out)/name
        if not source.exists():continue
        if target.exists():need(target.read_bytes()==source.read_bytes(),'COMPOUND_V2_RETAINED_INPUT_BYTE_EQUALITY')
        else:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes())
    with ExitStack() as stack:
        stack.enter_context(projection)
        if cp['source_cursor']<projection.payload['binding']['spin']['session']:
            stack.enter_context(Observer(out,projection.payload))
        material=projection.payload['ordinary_material']
        if cp['source_cursor']<max(t['added']['session'] for t in material['terms']):
            event=ordinary_events(root,cp,overlay_name=str(projection.overlay.relative_to(root)))
            event.out=Path(out)/'compound-v2-retained-ordinary-observation';event.out.mkdir(exist_ok=True)
            stack.enter_context(event)
        yield


def retained_observation_files(p,root,cp):
    """Carry committed proof bytes, never promote a failed/uncommitted tail."""
    root=Path(root);names=[]
    if p['binding']['spin']['session']<=cp['source_cursor']:names.append(ACTUAL)
    for term in p['ordinary_material']['terms']:
        day=term['added']['session']
        if day>cp['source_cursor']:continue
        name='actual-future-event-'+day+'.json'
        for relative in (Path(name),Path('compound-v2-retained-ordinary-observation')/name):
            if (root/relative).is_file() and relative not in names:names.append(relative)
    return tuple(names)


@contextmanager
def initial_context(cp,out,spec,loaded):
    # P07 owns its existing gate/certificate/ordinary observer. No second gate.
    with ExitStack() as stack:
        projection=stack.enter_context(ProjectionContext(out))
        ordinary=projection.payload['ordinary_material']['terms']
        earliest=min([projection.payload['binding']['spin']['session']]+[v for t in ordinary for v in (t['native_session'],t['added']['session'])])
        need(loaded.earliest_affected_session==earliest,
             'COMPOUND_V2_INITIAL_GATE_USES_QUALIFIED_MINIMUM_VIEW')
        stack.enter_context(Observer(out,projection.payload));yield


def prepare(cp,out,arm,source_root=Path('/old')):
    hosted();out=Path(out);p,actions,spins,prefix=hydrate(cp,arm,source_root);raw=encoded(p)
    save(out/PAYLOAD,p);(out/PREFIX).write_bytes(prefix);save(out/MATERIAL,p['ordinary_material'])
    path=out/OVERLAY;save(path,document(p,raw))
    from research.pooled_vacancy_funding.repair import load_repair
    ordinary=load_repair(path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    proof=qualified_record(arm)['source_proof'];activation=activation_descriptor(ordinary,p['binding'],proof)
    loaded=qualified_loaded_view(ordinary,p['binding'],proof,activation)
    qualify(cp,out,p,actions,spins);return path,loaded


def qualify(cp,out,p,actions,spins):
    hosted()
    from research.pooled_vacancy_funding import backtest,repair
    from research.pooled_input_support.adapter import Packet
    from research.bounded_20y.run import vendor
    from stock_strategy_shared.wealth_core.state import PortfolioState
    from stock_strategy_shared.wealth_core.ledger import Ledger
    from stock_strategy_shared.wealth_core.funding import config
    from sentinel.core.spinoffs import apply_supported_entitlements
    from system_campaign_sprint_facts import qualify_packet_schema
    qualify_packet_schema(Packet,cp['base']['sources']['research/pooled_input_support/adapter.py'])
    b=p['binding'];day=b['spin']['session'];fixed=None
    with ProjectionContext(out,payload=(p,encoded(p))) as ctx:
        loaded=backtest.load_repair(out/OVERLAY,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
        for date_ in (b['prior_parent_identity']['session'],day,day[:4]+'-12-31'):
            bars=tuple(vendor(row) for row in b['original_rows'].values()) if date_==day else ()
            packet=Packet(date_,bars,{},{},1.,{},tuple(actions.terminal.get(date_,())),tuple(spins.get(date_,())))
            before=digest(asdict(packet));changed=backtest.apply_repair(packet,loaded)
            need(digest(asdict(packet))==before,'COMPOUND_V2_QUALIFY_ORIGINAL_PACKET_IMMUTABLE')
            if date_==day:fixed=changed;original_packet=packet
            else:need(changed==packet,'COMPOUND_V2_QUALIFY_OTHER_DATE_UNCHANGED')
        need(ctx.changed_packets==1,'COMPOUND_V2_EXACTLY_ONE_DISTRIBUTION_PACKET_CHANGE')
        # Reuse the unchanged registered ordinary qualifier on the same actual
        # parsed input stack. Source witness metadata is the reconstructed
        # original hydrator's metadata, never financial state.
        record=qualified_record(p['ordinary_material']['arm']);codec,_,_=select_original(record)
        private=p['ordinary_material']['original_private_payload']
        codec.rows={(v['session'],v['security_id']):deepcopy(v) for v in private['source_witnesses']}
        codec.alias_rows=private['actual_alias_rows']
        old=[]
        for d in cp['repairs']:
            old.append(backtest.load_repair(out/'book/repairs'/d['filename'],resume_session=d['resume_session'],
                predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']))
        codec.qualify(loaded,old,out/ORDINARY_QUALIFICATION,
                      packet_source_sha256=cp['base']['sources']['research/pooled_input_support/adapter.py'])
    state=PortfolioState.from_dict(deepcopy(cp['run']['state']['wealth_core']));ledger=Ledger.from_dict(deepcopy(cp['run']['state']['ledger']))
    cfg=config(cp['base']['policy']);before=deepcopy(state.to_dict());lb=deepcopy(ledger.to_dict())
    need(cfg.transaction_cost_bps==10,'COMPOUND_V2_ORIGINAL_SALE_COST_CONVENTION')
    try:apply_supported_entitlements(state,ctx.projection.originals,bars=original_packet.bars,ledger=ledger,config=cfg)
    except ValueError as error:
        need('SPINOFF_CHILD_OWNERSHIP_REQUIRED' in str(error) and state.to_dict()==before and ledger.to_dict()==lb,
             'COMPOUND_V2_UNREVIEWED_NATIVE_REFUSAL_ATOMICITY')
    else:raise ValueError('COMPOUND_V2_UNREVIEWED_NATIVE_GUARD_FALSIFIER')
    selected=tuple(v for v in fixed.spins if v.source_row_id==b['spin']['source_row_id'])
    audit=apply_supported_entitlements(state,selected,bars=fixed.bars,ledger=ledger,config=cfg)
    spin=spin_postcondition(b,before,state.to_dict(),lb,ledger.to_dict(),audit,cfg.transaction_cost_bps)
    for corrupt in ('quote','proxy','native'):
        bad=original_packet
        if corrupt=='quote':bad=replace(bad,bars=tuple(replace(v,raw_open=v.raw_open+.01) if v.security_id==b['spin']['child_security_id'] else v for v in bad.bars))
        elif corrupt=='proxy':bad=replace(bad,bars=tuple(replace(v,dividend_per_share=0.) if v.security_id==b['spin']['parent_security_id'] else v for v in bad.bars))
        else:bad=replace(bad,spins=bad.spins+bad.spins[:1])
        try:ctx.projection.apply(bad,ctx.projection.descriptor)
        except ValueError:pass
        else:raise ValueError('COMPOUND_V2_'+corrupt.upper()+'_FALSIFIER')
    ordinary_min=min(t['native_session'] for t in p['ordinary_material']['terms'])
    for cursor,pred in ((cp['source_cursor'],'0'*64),(ordinary_min,cp['run']['checkpoint_sha256'])):
        try:repair.load_repair(out/OVERLAY,resume_session=cursor,predecessor_checkpoint_sha256=pred)
        except ValueError:pass
        else:raise ValueError('COMPOUND_V2_ORIGINAL_PARSER_PREDECESSOR_OR_CONSUMED_FALSIFIER')
    wrong=deepcopy(cp['run']['state']);own=next(v for v in wrong['wealth_core']['episodes'].values() if v['security_id']==b['spin']['parent_security_id']);own['current_shares']+=1
    try:actual_role(wrong,wrong['pending'],b)
    except ValueError:pass
    else:raise ValueError('COMPOUND_V2_ACTUAL_ROLE_FALSIFIER')
    save(out/QUALIFICATION,dict(passed=True,financial_sessions_advanced=0,binding_sha256=digest(b),
        source_payload_sha256=sha(encoded(p['source_payload'])),spin=spin,canonical_primitives_delegated=True,
        original_financial_source_changed=False,original_native_quote_proxy_duplicate_role_falsifiers=True,
        original_ordinary_packet_notional_and_parser_falsifiers=True,
        loaded_minimum_boundary=loaded.earliest_affected_session))


def review(cp,evidence,arm):
    hosted();evidence=Path(evidence);p,actions,spins,prefix=hydrate(cp,arm,Path('/old'));raw=encoded(p)
    need((evidence/PAYLOAD).read_bytes()==raw and (evidence/PREFIX).read_bytes()==prefix
         and (evidence/MATERIAL).read_bytes()==encoded(p['ordinary_material'])
         and json.loads((evidence/OVERLAY).read_bytes())==document(p,raw),
         'COMPOUND_V2_INDEPENDENT_COMPLETE_SOURCE_INPUT_OVERLAY_REVIEW')
    proof=json.loads((evidence/QUALIFICATION).read_bytes());day=p['binding']['spin']['session']
    need(proof['passed'] is True and proof['financial_sessions_advanced']==0
         and proof['source_payload_sha256']==sha(encoded(p['source_payload'])) and proof['binding_sha256']==digest(p['binding'])
         and proof['loaded_minimum_boundary']==day,
         'COMPOUND_V2_HOSTED_ZERO_SESSION_QUALIFICATION_REVIEW')
    ordinary=json.loads((evidence/ORDINARY_QUALIFICATION).read_bytes())
    need(ordinary['schema']=='research.factual-cash-calendar-qualification/1'
         and ordinary['actual_cash_mergers']==len(p['ordinary_material']['terms'])
         and ordinary['original_incomplete_guards']==len(p['ordinary_material']['terms'])
         and ordinary['financial_sessions_advanced']==0
         and ordinary['canonical_notional_cash_verified'] is ordinary['original_packets_unchanged'] is True,
         'COMPOUND_V2_UNCHANGED_GENUINE_ORDINARY_QUALIFICATION_REVIEW')
    current=json.loads(gzip.decompress((evidence/'book/checkpoint.json.gz').read_bytes()))
    review_actual(p,evidence,current)
    return day


def review_actual(p,evidence,current):
    evidence=Path(evidence);day=p['binding']['spin']['session'];actual=evidence/ACTUAL
    need(current['source_cursor']<day or actual.is_file(),'COMPOUND_V2_POST_EVENT_REQUIRES_ACTUAL_CHILD_OBSERVER')
    if current['source_cursor']>=day:
        value=json.loads(actual.read_bytes());quantity=sum((Fraction(str(v['quantity'])) for v in p['binding']['parent_positions']),Fraction(0))
        need(value['passed'] is True and value['session']==day and value['order']==['SPINOFF']
             and value['spin']==consideration(p['binding'],quantity,10)
             and value['proxy_cash']==dict(parent_proxy_cash_accrued=False,parent_proxy_cash_paid=False,child_retained=False),
             'COMPOUND_V2_ACTUAL_CHILD_RATIO_SALE_FRACTION_NO_DOUBLE_PROXY_REVIEW')
    for term in p['ordinary_material']['terms']:
        date_=term['added']['session'];sid=term['security_id']
        if current['source_cursor']<date_:continue
        candidates=[evidence/('actual-future-event-'+date_+'.json'),
                    evidence/'compound-v2-retained-ordinary-observation'/('actual-future-event-'+date_+'.json')]
        found=[]
        for path in candidates:
            if not path.is_file():continue
            value=json.loads(path.read_bytes())
            selected=[v for v in value['cash'] if v['security_id']==sid and v['session']==date_]
            if selected:found.append((value,selected))
        need(len(found)>=1,'COMPOUND_V2_GENUINE_ORDINARY_COMPLETION_REQUIRES_ACTUAL_OBSERVER')
        for value,selected in found:
            need(value['passed'] is True and value['session']==date_ and len(selected)==1
                 and selected[0]['actual_context_call'] is True and selected[0]['source_only_noop'] is False
                 and selected[0]['postcondition']['nominal_cash']==selected[0]['postcondition']['quantity']*term['added']['cash_per_share'],
                 'COMPOUND_V2_ORIGINAL_MANDATORY_CASH_ACTUAL_POSTCONDITION_REVIEW')


def review_retained(root,cp):
    activation=retained_activation(root,cp)
    if activation is not None:review_actual(activation.payload,root,cp)
