"""Hosted standard-book distribution route; all economics delegate originals."""
from contextlib import contextmanager,ExitStack
from copy import deepcopy
from dataclasses import asdict,replace
from fractions import Fraction
import gzip
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

from full_system_benchmark import save
from full_system_core import hosted
from system_campaign_financial_distribution_standard import (
    sha,digest,encoded,need,build_terms,actual_role,EventSessionProjection,consideration,qualified_record,
    primary_binding,activation_descriptor,qualified_loaded_view,spin_postcondition,review_spin_result,
    verify_primitive_sources,ordinary_input,verify_ordinary,ordinary_document,ordinary_events,original_parent,
    select_original,MATERIAL,OBSERVER_SHA,OBSERVER_FILE,delegate_nodes,registry_context)

HERE=Path(__file__).parent
PAYLOAD='hydrated-standard-distribution-input.json'
OVERLAY='future-financial-overlay.json'
QUALIFICATION='standard-distribution-input-qualification.json'
ORDINARY_QUALIFICATION='standard-distribution-ordinary-qualification.json'
ACTUAL='actual-standard-distribution-event.json'
RETAINED_OBSERVATION='standard-distribution-retained-ordinary-observation'
CATALOG_REF='research.standard-distribution-input/catalog/1'
RUNTIME_REF='research.standard-distribution-input/runtime/1'
MODEL_REF='research.standard-distribution-input/model/1'
SUPPORT_REF='research.standard-distribution-input/support/1'
ORDINARY_REF='research.standard-distribution-input/original-ordinary-framework/1'
OBSERVER_REF='research.standard-distribution-input/original-ordinary-observer/1'
PAYLOAD_REF='research.standard-distribution-input/payload/1'
SOURCE_REF='research.standard-distribution-input/closed-source-producer/1'
DATA_REF='research.standard-distribution-input/source-DATA/1'
ORIGINAL_COMPILER_REF='research.standard-distribution-input/original-distribution-compiler/1'
FROZEN_V2_FILE='system_campaign_financial_compound_runtime_v2.py'
FROZEN_V2_SHA='0b4ade1d380b395098f057dd9a8b65cd73ae8697f364640f05118326da25bd74'

# Only branch-independent framework operations; their financial calls are still
# hosted/delegating. No canonical engine or financial state implementation copied.
delegate_nodes(HERE/FROZEN_V2_FILE,FROZEN_V2_SHA,
    {'source_parent','reconstruct_source','ProjectionContext','no_proxy_cash','Observer','qualify'},globals())
_Observer=Observer
_qualify=qualify


def applies(cp,arm):
    from system_campaign_financial_distribution_standard import CATALOG_FILE
    catalog=json.loads((HERE/CATALOG_FILE).read_bytes())
    return any((r['arm'],r['parent_outer_sha256'],r['parent_cursor'])==(arm,cp['sha256'],cp['source_cursor'])
               for r in catalog['records'])


def input_payload(r,spec,source,material):
    binding=build_terms(r['research_assumption'],source,child_security_id=r['child_security_id'],reference=r['reference'],source_proof=r['source_proof'])
    binding['canonical_profile']=deepcopy(r['canonical_profile'])
    return dict(schema='research.hydrated-standard-distribution-input/1',record_sha256=digest(r),source_payload=source,
        binding=binding,ordinary_material=material,base=deepcopy(spec['base']),original_parent=original_parent(spec),
        financial_state_changed=False,production_contacted=False)


def hydrate(cp,arm,root):
    hosted();r=qualified_record(arm);spec=source_parent(r);origin=original_parent(spec)
    need(cp['sha256']==origin['sha256'] and cp['source_cursor']==origin['source_cursor']
         and cp['run']['checkpoint_sha256']==origin['run']['checkpoint_sha256']
         and cp['run']['input_sha256']==origin['run']['input_sha256'] and cp['base']==origin['base']
         and cp['repairs']==origin['repairs']
         and sha((Path(root)/'source-bindings.json').read_bytes())==r['source_bindings_sha256'],
         'STANDARD_EXACT_ORIGINAL_OWN_ROOT_INPUTS_AND_SOURCE_BINDING')
    source,actions,spins=reconstruct_source(r,spec);material,_,_=ordinary_input(cp,r,root)
    p=input_payload(r,spec,source,material);actual_role(cp['run']['state'],cp['run']['state']['pending'],p['binding'])
    parent=p['binding']['spin']['parent_security_id']
    floors=[dict(slot_id=e['slot_id'],floor=e.get('research_stop_floor'),cursor=e.get('research_stop_cursor'))
            for e in cp['run']['state']['wealth_core']['episodes'].values()if e['security_id']==parent]
    need(floors==r['parent_reference_values'],'STANDARD_EXACT_ADMITTED_PARENT_REFERENCE_VALUES')
    return p,actions,spins


def refs(raw,r):
    from system_campaign_financial_distribution_standard import CATALOG_SHA
    files={RUNTIME_REF:Path(__file__),MODEL_REF:HERE/'system_campaign_financial_compound_input_v2.py',
        SUPPORT_REF:HERE/'system_campaign_financial_distribution_standard.py',ORDINARY_REF:HERE/'system_campaign_financial_compound_ordinary_v2.py',
        OBSERVER_REF:HERE/OBSERVER_FILE,ORIGINAL_COMPILER_REF:HERE/'system_campaign_distribution_facts.py',
        'research.standard-distribution-input/frozen-runtime-framework/1':HERE/FROZEN_V2_FILE,
        'research.standard-distribution-input/frozen-v2-support/1':HERE/'system_campaign_financial_compound_v2_support.py',
        'research.standard-distribution-input/published-base-compiler/1':HERE/'build_core_variants.py',
        'research.standard-distribution-input/published-variant-compiler/1':HERE/'system_campaign_variants.py'}
    return dict({k:sha(v.read_bytes())for k,v in files.items()},**{CATALOG_REF:CATALOG_SHA,PAYLOAD_REF:sha(raw),
        SOURCE_REF:r['source_proof']['distribution_producer_sha256'],DATA_REF:r['source_proof']['independent_data_review_sha256'],
        'research.standard-distribution-input/immutable-variant-text-derivation/1':r['canonical_profile']['independent_derivation_sha256']})


def document(p,raw):
    r=qualified_record(p['ordinary_material']['arm']);doc=ordinary_document(p['ordinary_material'])
    added=[dict(reference=k,sha256=v,description='Source-bound standard-book distribution input; canonical financial source unchanged.')
           for k,v in sorted(refs(raw,r).items())]
    need(not({v['reference']for v in added}&{v['reference']for v in doc['source_evidence']}),'STANDARD_DISTINCT_SOURCE_REFERENCES')
    doc['source_evidence']=sorted(doc['source_evidence']+added,key=lambda v:v['reference']);return doc


def verify_payload(root):
    hosted();root=Path(root);raw=(root/PAYLOAD).read_bytes();p=json.loads(raw);r=qualified_record(p['ordinary_material']['arm'])
    spec=source_parent(r);source,_,_=reconstruct_source(r,spec);verify_ordinary(p['ordinary_material'],original_parent(spec),r,root)
    need(p==input_payload(r,spec,source,p['ordinary_material']),'STANDARD_COMPLETE_INPUT_RECONSTRUCTION_NO_OTHER_BOOK')
    return p,raw


def verify_actual_primitive_modules(p,api=None):
    hosted()
    if api is None:
        from sentinel.core import spinoffs
        from stock_strategy_shared.wealth_core import capital_risk
        api=SimpleNamespace(spinoffs=spinoffs,capital_risk=capital_risk)
    return verify_primitive_sources(p['binding']['canonical_profile'],p['base']['sources'],
        spinoffs_raw=Path(api.spinoffs.__file__).read_bytes(),capital_risk_raw=Path(api.capital_risk.__file__).read_bytes())


class Observer(_Observer):
    def __enter__(self):
        # Verify both actual primitive modules before installing financial hooks.
        verify_actual_primitive_modules(self.payload,None if self.api is None else self.api)
        return super().__enter__()


def qualify(cp,out,p,actions,spins):
    with registry_context(qualified_record(p['ordinary_material']['arm'])):
        verify_actual_primitive_modules(p)
        return _qualify(cp,out,p,actions,spins)


def _prepare(cp,out,arm,source_root=Path('/old')):
    hosted();out=Path(out);p,actions,spins=hydrate(cp,arm,source_root);raw=encoded(p)
    save(out/PAYLOAD,p);save(out/MATERIAL,p['ordinary_material']);path=out/OVERLAY;save(path,document(p,raw))
    from research.pooled_vacancy_funding.repair import load_repair
    ordinary=load_repair(path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    proof=qualified_record(arm)['source_proof'];activation=activation_descriptor(ordinary,p['binding'],proof)
    loaded=qualified_loaded_view(ordinary,p['binding'],proof,activation)
    qualify(cp,out,p,actions,spins);return path,loaded


def prepare(cp,out,arm,source_root=Path('/old')):
    with registry_context(qualified_record(arm)):return _prepare(cp,out,arm,source_root)


@contextmanager
def initial_context(cp,out,spec,loaded):
    from system_campaign_financial_resume import AdoptionGate
    with ExitStack()as stack:
        stack.enter_context(registry_context(qualified_record(spec['arm'])))
        projection=stack.enter_context(ProjectionContext(out))
        need(loaded.earliest_affected_session==projection.payload['binding']['spin']['session'],
             'STANDARD_GATE_EXACT_QUALIFIED_DISTRIBUTION_BOUNDARY')
        stack.enter_context(AdoptionGate(cp,Path(out)/'book',Path(out)/'input-adoption',loaded.sha256,loaded.earliest_affected_session))
        stack.enter_context(Observer(out,projection.payload));stack.enter_context(ordinary_events(out,cp));yield


def review_actual(p,evidence,current):
    evidence=Path(evidence);day=p['binding']['spin']['session'];actual=evidence/ACTUAL
    need(current['source_cursor']<day or actual.is_file(),'STANDARD_COMMITTED_EVENT_REQUIRES_ACTUAL_CHILD_PROOF')
    if current['source_cursor']>=day:
        value=json.loads(actual.read_bytes())
        need(value['passed']is True and value['session']==day and value['order']==['SPINOFF']
             and value['proxy_cash']==dict(parent_proxy_cash_accrued=False,parent_proxy_cash_paid=False,child_retained=False),
             'STANDARD_ACTUAL_ONE_CHILD_AND_NO_DUPLICATE_PROXY')
        review_spin_result(p['binding'],value['spin'])
    for term in p['ordinary_material']['terms']:
        date_=term['added']['session'];sid=term['security_id']
        if current['source_cursor']<date_:continue
        found=[];name='actual-future-event-'+date_+'.json'
        for path in (evidence/name,evidence/RETAINED_OBSERVATION/name):
            if not path.is_file():continue
            value=json.loads(path.read_bytes());selected=[v for v in value['cash']if v['security_id']==sid and v['session']==date_]
            if selected:found.append((value,selected))
        need(found,'STANDARD_COMMITTED_ORDINARY_EVENT_REQUIRES_ACTUAL_PROOF')
        for value,selected in found:
            need(value['passed']is True and value['session']==date_ and len(selected)==1
                 and selected[0]['actual_context_call']is True and selected[0]['source_only_noop']is False
                 and selected[0]['postcondition']['nominal_cash']==selected[0]['postcondition']['quantity']*term['added']['cash_per_share'],
                 'STANDARD_ORIGINAL_ORDINARY_ACTUAL_CASH_POSTCONDITION')


def retained_activation(root,cp):
    hosted();root=Path(root);found=[]
    for d in cp['repairs']:
        raw=(root/'book/repairs'/d['filename']).read_bytes();need(sha(raw)==d['sha256'],'STANDARD_ALL_RETAINED_REPAIR_BYTES')
        if any(v['reference']==CATALOG_REF for v in json.loads(raw).get('source_evidence',[])):found.append(d)
    if not found:
        need(not any((root/name).exists()for name in(PAYLOAD,MATERIAL)), 'STANDARD_NO_UNCOMMITTED_MATERIAL');return None
    need(len(found)==1,'STANDARD_ONE_COMMITTED_ACTIVATION');d,=found;p,raw=verify_payload(root);origin=p['original_parent']
    r=qualified_record(p['ordinary_material']['arm'])
    need(cp['base']==origin['base'] and origin['source_cursor']<=cp['source_cursor']
         and cp['repairs'][:len(origin['repairs'])]==origin['repairs']
         and d['resume_session']==origin['source_cursor'] and d['predecessor_checkpoint_sha256']==origin['run']['checkpoint_sha256']
         and sha((root/'source-bindings.json').read_bytes())==r['source_bindings_sha256']
         and (root/MATERIAL).read_bytes()==encoded(p['ordinary_material']), 'STANDARD_RETAINED_OWN_PREFIX_SOURCE_AND_MATERIAL')
    return ProjectionContext(root,'book/repairs/'+d['filename'],payload=(p,raw))


def retained_observation_files(p,root,cp):
    root=Path(root);names=[]
    if p['binding']['spin']['session']<=cp['source_cursor']:names.append(Path(ACTUAL))
    for t in p['ordinary_material']['terms']:
        if t['added']['session']>cp['source_cursor']:continue
        name='actual-future-event-'+t['added']['session']+'.json'
        for relative in(Path(name),Path(RETAINED_OBSERVATION)/name):
            if(root/relative).is_file()and relative not in names:names.append(relative)
    return tuple(names)


@contextmanager
def retained_context(root,cp,out):
    projection=retained_activation(root,cp)
    if projection is None:yield;return
    review_actual(projection.payload,root,cp)
    for name in(PAYLOAD,MATERIAL,QUALIFICATION,ORDINARY_QUALIFICATION,*retained_observation_files(projection.payload,root,cp)):
        source=Path(root)/name;target=Path(out)/name
        if not source.exists():continue
        if target.exists():need(target.read_bytes()==source.read_bytes(),'STANDARD_RETAINED_INPUT_BYTE_EQUALITY')
        else:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes())
    with ExitStack()as stack:
        stack.enter_context(registry_context(qualified_record(projection.payload['ordinary_material']['arm'])))
        stack.enter_context(projection)
        if cp['source_cursor']<projection.payload['binding']['spin']['session']:stack.enter_context(Observer(out,projection.payload))
        terms=projection.payload['ordinary_material']['terms']
        if cp['source_cursor']<max(t['added']['session']for t in terms):
            event=ordinary_events(root,cp,overlay_name=str(projection.overlay.relative_to(root)))
            event.out=Path(out)/RETAINED_OBSERVATION;event.out.mkdir(exist_ok=True);stack.enter_context(event)
        yield


def _review(cp,evidence,arm):
    hosted();evidence=Path(evidence);p,_,_=hydrate(cp,arm,Path('/old'));raw=encoded(p)
    need((evidence/PAYLOAD).read_bytes()==raw and(evidence/MATERIAL).read_bytes()==encoded(p['ordinary_material'])
         and json.loads((evidence/OVERLAY).read_bytes())==document(p,raw),'STANDARD_COMPLETE_INPUT_REVIEW')
    proof=json.loads((evidence/QUALIFICATION).read_bytes());day=p['binding']['spin']['session']
    need(proof['passed']is True and proof['financial_sessions_advanced']==0
         and proof['source_payload_sha256']==sha(encoded(p['source_payload']))and proof['binding_sha256']==digest(p['binding'])
         and proof['loaded_minimum_boundary']==day,'STANDARD_HOSTED_ZERO_CLOSE_QUALIFICATION')
    review_spin_result(p['binding'],proof['spin'])
    r=qualified_record(arm)
    need([dict(slot_id=v['slot_id'],floor=v['before'],cursor=v['cursor_unchanged'])for v in proof['spin']['canonical_reference_rebase']]
         ==r['parent_reference_values'],'STANDARD_QUALIFICATION_FROM_EXACT_ORIGINAL_OWN_FLOOR')
    ordinary=json.loads((evidence/ORDINARY_QUALIFICATION).read_bytes())
    need(ordinary['schema']=='research.factual-cash-calendar-qualification/1'
         and ordinary['actual_cash_mergers']==ordinary['original_incomplete_guards']==len(p['ordinary_material']['terms'])
         and ordinary['financial_sessions_advanced']==0
         and ordinary['canonical_notional_cash_verified']is ordinary['original_packets_unchanged']is True,
         'STANDARD_ORIGINAL_ORDINARY_PACKET_QUALIFICATION')
    current=json.loads(gzip.decompress((evidence/'book/checkpoint.json.gz').read_bytes()));review_actual(p,evidence,current);return day


def review(cp,evidence,arm):
    with registry_context(qualified_record(arm)):return _review(cp,evidence,arm)


def review_retained(root,cp):
    projection=retained_activation(root,cp)
    if projection is not None:review_actual(projection.payload,root,cp)
