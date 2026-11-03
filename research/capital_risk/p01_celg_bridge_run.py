"""Hosted OWN475 source/input zero-session bridge and bounded actual continuation."""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict,replace
import gzip
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

from full_system_core import hosted,arguments
from full_system_benchmark import save
from p01_celg_bridge_gate import (SourceGate,specification,parent_identity,receipt,need,digest,sha,HERE,SPEC)
from p01_celg_bridge_source import verify_rendered_modules
from p01_celg_bridge_codec import InputCodec,RoleGuard,document,NATIVE,OLD,NEW,SID
from p01_celg_bridge_pause import SourcePause
from system_campaign_pxd_pause import PauseAfterAdoption,adoption
from system_campaign_discovery_context import material,require_strict_checkpoint
from system_campaign_factual_run import (copy_repair_archive,correlation_seed,SeededObservation,
                                         preserve_tails)
from system_campaign_acceleration import Execution

END='2020-02-04'
MAXIMUM=51
FACTS='p01_celg_bridge_facts.json'


def native(day,sid):
    from research.pooled_input_support.inputs import load_actions
    values=[t for t in load_actions(Path('/frozen/bundle')).terminal.get(day,()) if t.security_id==sid]
    need(len(values)==1,'EXACT_ONE_FROZEN_NATIVE_EVENT');return values[0]


@contextmanager
def old_inputs(old,cp,out):
    from system_campaign_p01_discovery_inputs import retained_inputs
    from p01_clock_input_codec import InputCodec as OldClockCodec,SCHEMA as OLD_SCHEMA
    from p01_clock_input_run import native as old_native
    need(len(cp['repairs'])==9 and cp['repairs']==specification()['repairs'],
         'EXACT_ORIGINAL_NINE_DESCRIPTORS_NOT_OTHER_ARM')
    ninth=cp['repairs'][-1];raw=(old/'book/repairs'/ninth['filename']).read_bytes()
    need(sha(raw)==ninth['sha256'] and json.loads(raw)['schema']==OLD_SCHEMA,'EXACT_ORIGINAL_NINTH_CLOCK_BYTES')
    # The existing hydration contract owns only the first eight terminal inputs.
    # Its unchanged schema check must not be broadened for the ninth clock input.
    with retained_inputs(old,{**cp,'repairs':cp['repairs'][:8]},out),OldClockCodec(old_native()):
        yield


def authenticated_quote():
    from p01_celg_input_transport import load_authenticated_input
    raw=Path('/celg-input-descriptor.json').read_bytes()
    need(raw==(HERE/'p01_celg_bridge_quote_descriptor.json').read_bytes(),
         'EXACT_REQUEST_BOUND_PRIVATE_QUOTE_CAPSULE_DESCRIPTOR')
    descriptor=json.loads(raw)
    actual=load_authenticated_input(Path('/celg-input'),descriptor)
    q=actual.quote.model_dump(mode='json')
    q.update(authority='AUTHENTICATED_RETAINED_ALPACA_RAW_SIP_INPUT',observed_market_data=True,
        capture_sha256=actual.capture_sha256,manifest_sha256=actual.manifest_sha256,
        ciphertext_sha256=actual.ciphertext_sha256,input_identity_sha256=actual.input_identity_sha256)
    from stock_strategy_shared.wealth_core import merger_rights
    merger_rights.bind_market_quote(q,expected_sha256=digest(q))
    need(merger_rights.quote()==q,'ACTUAL_PRIVATE_QUOTE_REGISTERED_EXACTLY_ONCE')
    return q,descriptor


def prepare(old,out):
    from research.pooled_vacancy_funding import journal,backtest
    from research.pooled_input_support.bundle import axis
    spec=specification();cp=parent_identity(require_strict_checkpoint(journal.read_checkpoint(old/spec['selected_checkpoint'])))
    need((old/spec['selected_checkpoint']).stat().st_size==spec['selected_file']['bytes']
         and sha((old/spec['selected_checkpoint']).read_bytes())==spec['selected_file']['sha256'],
         'MOUNTED_ORIGINAL_OWN475_GZIP_NOT_QUALIFIER_STATE')
    source_map=json.loads((out/'source-map.json').read_bytes())
    files={p.relative_to('/variant').as_posix():p.read_bytes() for p in Path('/variant').rglob('*') if p.is_file()}
    need({n:sha(v) for n,v in files.items()}==source_map['successor_all_sources']
         and backtest.source_files()==source_map['successor_financial_sources'],
         'ACTUAL_ALL516_AND224_CANONICAL_SUCCESSOR_SOURCE_BYTES')
    verify_rendered_modules(files,source_map)
    dates=axis();dates=dates[dates.index(backtest.START)-425:dates.index(backtest.END)+1]
    wanted=[d for d in dates if cp['source_cursor']<d<=END]
    need(len(wanted)==MAXIMUM and wanted[:2]==[OLD,NEW] and wanted[-1]==END,
         'EXACT_FROZEN_BOUNDED_SUFFIX_AXIS')
    book=out/'book';book.mkdir();(book/'predecessor-checkpoints').mkdir()
    shutil.copyfile(old/spec['selected_checkpoint'],book/'predecessor-checkpoints'/(cp['sha256']+'.json.gz'))
    shutil.copyfile(old/'book/identity.json',book/'identity.json');copy_repair_archive(old,book)
    originals={}
    for base in ('book','lineage'):
        for path in (old/base).rglob('*.json.gz'):
            rel=path.relative_to(old);dest=out/'lineage/original-checkpoints'/rel
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
            originals[rel.as_posix()]=dict(bytes=path.stat().st_size,sha256=sha(path.read_bytes()))
    tails={}
    for name,c in cp['journals'].items():
        raw=(old/f'book/{name}.jsonl').read_bytes()
        need(len(raw)==c['bytes'] and sha(raw)==c['prefix_sha256'],'EXACT_ADMITTED_PARENT_PREFIX_NO_TAIL')
        (book/(name+'.jsonl')).write_bytes(raw);tails[name]=dict(bytes=0,sha256=sha(b''))
    proof=dict(schema='research.p01-celg-bridge-preflight/1',original_outer_sha256=cp['sha256'],
        old_source_canonical_restore_reused=spec['reused_hosted_old_source_proofs'],
        old_accounting_review_reused_sha256=spec['independent_review_sha256'],old_financial_audits_repeated=False,
        original_checkpoint_files=originals,tails_to_preserve=tails,
        next_session=OLD,processing_endpoint=END,maximum_transitions=len(wanted),original_inputs=9)
    save(out/'bridge-preflight.json',proof)
    return cp,source_map,wanted,proof


def exact_prefixes(old,book,original,current,events):
    checks={}
    for name,c in original['journals'].items():
        before=(old/f'book/{name}.jsonl').read_bytes();after=(book/(name+'.jsonl')).read_bytes()
        need(after[:c['bytes']]==before,'ZERO_BOUNDARY_ALL_ADMITTED_PREFIX_BYTES_EXACT')
        suffix=[json.loads(v) for v in after[c['bytes']:].splitlines()]
        need(suffix==(events if name=='watch' else []),'ZERO_BOUNDARY_ONLY_EXACT_ORDERED_WATCH_EVENTS')
        checks[name]=dict(before=c,after=current['journals'][name])
    return checks


@contextmanager
def boundaries(old,out,cp,source_map,q,descriptor):
    from research.pooled_vacancy_funding import backtest,runtime,journal,source_successor
    from stock_strategy_shared.wealth_core import terminal,merger_rights
    _,identity=runtime.strategy(cp['base']['policy'])
    raw_receipt=receipt(cp,source_map,identity);path=out/'source-successor.json';save(path,raw_receipt)
    base={**cp['base'],'sources':source_map['successor_financial_sources']}
    with SourceGate(cp,source_map,path,out/'book/checkpoint.json.gz') as gate:
        base,binding=gate.load(path,base);bridge=source_successor.make_bridge(binding,base)
        event=source_successor.boundary_event(binding)
        journal.write_checkpoint(out/'book/checkpoint.json.gz',bridge)
        initial=runtime.restore(bridge['run'],policy=base['policy'],input_sha256=backtest.input_hash(base,bridge['repairs']))
        need(runtime.checkpoint(initial)==bridge['run'],'ACTUAL_NEW_SOURCE_ZERO_CHECKPOINT_CANONICAL_ROUNDTRIP')
        pause=SourcePause(cp,bridge,event,out/'book/checkpoint.json.gz')
        args=arguments(out/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
        with pause:code=backtest.main(args+['--source-successor',str(path)])
        need(code==0,'ACTUAL_ZERO_SESSION_SOURCE_STARTUP')
        source=journal.read_checkpoint(out/'book/checkpoint.json.gz');source_proof=pause.proof()
        gate.allow_source(source,bridge)
        exact_prefixes(old,out/'book',cp,source,[event])
        term=terminal.MergerRightTerms(session=NEW,security_id=SID,kind=terminal.TerminalKind.CASH_PLUS_STOCK,
            cash_per_share=50.0,delivered_security_id=merger_rights.DELIVERED,delivered_ticker='BMY',
            delivered_issuer_id='SEC_CIK:14272',exchange_ratio='1',reference=merger_rights.REFERENCE)
        evidence=json.loads((HERE/FACTS).read_bytes())
        doc=document(source,sha(path.read_bytes()),source_map,q,descriptor,asdict(term),evidence)
        input_path=out/'celg-clock-input.json';save(input_path,doc)
        with InputCodec(native(OLD,SID),doc) as codec:
            loaded=backtest.load_repair(input_path,resume_session=cp['source_cursor'],
                                       predecessor_checkpoint_sha256=source['run']['checkpoint_sha256'])
            pause_input=PauseAfterAdoption(source,out/'book/checkpoint.json.gz',loaded.sha256,OLD)
            with pause_input:code=backtest.main(args+['--source-successor',str(path),'--repair-overlay',str(input_path)])
            need(code==0,'ACTUAL_ZERO_SESSION_TENTH_INPUT_STARTUP')
            current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
            input_event=adoption(current,source,loaded.sha256,OLD);gate.allow_input(current,source,loaded.sha256)
            prefix=exact_prefixes(old,out/'book',cp,current,[event,input_event])
            restored=runtime.restore(current['run'],policy=base['policy'],
                input_sha256=backtest.input_hash(base,current['repairs']))
            need(runtime.checkpoint(restored)==current['run'],'ACTUAL_NEW_SOURCE_TENTH_INPUT_ZERO_ROUNDTRIP')
            proof=dict(source=source_proof,input=pause_input.proof(),prefixes=prefix,
                source_checkpoint=source,input_checkpoint=current,source_event=event,input_event=input_event,
                input_document_sha256=loaded.sha256,successor_input_sha256=current['run']['input_sha256'],
                financial_authority=False,financial_predecessor_authorized=False)
            save(out/'zero-session-boundaries.json',proof)
            yield current,codec,loaded,path,proof


def refuse(call,label):
    try:call()
    except (ValueError,TypeError):return
    raise ValueError('REFUSED_P01_CELG_BRIDGE_MISSING_'+label)


def qualify(old,out):
    from research.pooled_vacancy_funding import runtime,backtest
    from research.pooled_input_support.adapter import Packet
    from stock_strategy_shared.wealth_core import terminal,ledger
    from p01_celg_bridge_gate import verify_receipt
    from p01_celg_bridge_codec import pending_before,SCOPES
    from system_campaign_discovery_replay import source_iterator
    cp,source_map,wanted,pre=prepare(old,out);q,descriptor=authenticated_quote()
    proof_dir=out/'proof';proof_dir.mkdir()
    with old_inputs(old,cp,out/'contexts'),boundaries(old,out,cp,source_map,q,descriptor) as values:
        current,codec,loaded,path,zero=values
        run,buffer,packets,repaired,_=source_iterator(current,out)
        objects=[backtest.load_repair(out/'book/repairs'/d['filename'],resume_session=d['resume_session'],
            predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']) for d in current['repairs']]
        scope_sources=[]
        for scope in SCOPES:
            actual=native(scope['session'],scope['security_id'])
            need(material(actual)==scope['native_term'] and digest(material(actual))==scope['native_term_sha256'],
                 'ACTUAL_FROZEN_NATIVE_SCOPE_SOURCE_PREIMAGE')
            # Source-term-only control packet: no quote or publication is fabricated.
            control=Packet(scope['session'],(),{},{},1.,{},(actual,),())
            changed=control
            for obj in objects:changed=backtest.apply_repair(changed,obj)
            need(material(changed)==material(control),'ALL_TEN_TYPED_CODECS_PRESERVE_EXISTING_SCOPED_NATIVE_TERM')
            scope_sources.append(dict(session=scope['session'],security_id=scope['security_id'],
                native_term_sha256=scope['native_term_sha256'],all_ten_codecs_preserve_native_preimage=True,
                control_packet_has_no_market_observations=True,financial_session_advanced=False))
        negatives=[]
        source_receipt=json.loads(path.read_bytes());_,identity=runtime.strategy(cp['base']['policy'])
        source_base={**cp['base'],'sources':source_map['successor_financial_sources']}
        wrong=deepcopy(cp);wrong['sha256']='0'*64
        refuse(lambda:verify_receipt(source_receipt,wrong,source_base,source_map,identity),'WRONG_OWN475_PREDECESSOR')
        negatives.append('wrong_own475_predecessor')
        changed=deepcopy(cp);changed['run']['state']['pending'].append({'security_id':SID})
        refuse(lambda:verify_receipt(source_receipt,changed,source_base,source_map,identity),'FINANCIAL_STATE_MUTATION')
        negatives.append('financial_state_mutation')
        extra=deepcopy(source_base);extra['sources']['unsupported-extra.py']='0'*64
        refuse(lambda:verify_receipt(source_receipt,cp,extra,source_map,identity),'EXTRA_CANONICAL_SOURCE_EDIT')
        negatives.append('extra_canonical_source_edit')
        missing=deepcopy(loaded.terms);missing.pop('right_units_per_source')
        refuse(lambda:terminal.terminal_terms_from_dict(missing),'MISSING_RIGHTS_CANNOT_DEFAULT')
        negatives.append('missing_rights_cannot_default')
        future=deepcopy(loaded.terms);future['right_quote']['session']=OLD
        refuse(lambda:terminal.terminal_terms_from_dict(future),'FUTURE_QUOTE_CANNOT_BACKDATE')
        negatives.append('future_quote_cannot_backdate')
        changed_quote=deepcopy(loaded.terms);changed_quote['right_quote']['raw_sha256']='0'*64
        refuse(lambda:terminal.terminal_terms_from_dict(changed_quote),'CHANGED_QUOTE_SOURCE_HASH')
        negatives.append('changed_quote_source_hash')
        for sid in (SID,'578964201416671255'):
            pending=SimpleNamespace(wealth_core=deepcopy(run.state.wealth_core),median5=deepcopy(run.state.median5),
                pending=[{'security_id':sid,'operation':'OPEN_SLOT_POSITION','signal_session':'2019-11-20'}])
            refuse(lambda:pending_before(pending),'FULL_FUTURE_OPEN_PENDING_SCOPE')
            negatives.append('future_open_pending_'+sid)
        guard=RoleGuard(q,book=out/'book');observed=[]
        with guard,Execution('FAST',signal_closes=1):
            for day in (OLD,NEW):
                raw=next(packets);need(raw.day==day,'TWO_SESSION_ACTUAL_SOURCE_AXIS')
                if day==OLD:
                    refuse(lambda:codec.apply(replace(raw,terminal=()),loaded),'MISSING_SOURCE_PREIMAGE_FALSIFIER')
                    altered=replace(codec.native,cash_per_share=0.0)
                    refuse(lambda:codec.apply(replace(raw,terminal=(altered,)),loaded),'CHANGED_SOURCE_PREIMAGE_FALSIFIER')
                    refuse(lambda:codec.apply(raw,deepcopy(loaded)),'UNREGISTERED_INPUT_INSTANCE_FALSIFIER')
                else:
                    refuse(lambda:codec.apply(replace(raw,terminal=(replace(codec.native,session=NEW),)),loaded),
                           'COLLIDING_EFFECTIVE_TERM_FALSIFIER')
                packet=repaired(raw);buffer.append(packet)
                publication=buffer.prepare(run.state,run.state.data_version+1,formation=False)
                previous=runtime.checkpoint(run);run=runtime.advance(run,publication)
                actual=runtime.checkpoint(run)
                observed.append(dict(session=day,prior_checkpoint=previous,publication=material(publication),checkpoint=actual))
        need([r['session'] for r in guard.observed]==[OLD,NEW],'ACTUAL_TWO_FULL_ROLE_AND_STATE_GATES')
        actual_ledger=deepcopy(run.state.ledger)
        need(ledger.Ledger.from_dict(actual_ledger).to_dict()==actual_ledger,
             'ACTUAL_FULL_LEDGER_NEW_SOURCE_RESTORE_AFTER_TWO_SESSIONS')
        rights=[v for v in actual_ledger['events'] if v['event_type']=='MERGER_RIGHT_RECEIPT']
        if rights:
            omitted=deepcopy(actual_ledger)
            omitted['events']=[v for v in omitted['events'] if v['event_type']!='MERGER_RIGHT_LIQUIDATION']
            refuse(lambda:ledger.Ledger.from_dict(omitted),'UNSOLD_RIGHT_CANNOT_DISAPPEAR_IN_RESTORE')
            negatives.append('actual_unsold_right_cannot_disappear_in_restore')
        from stock_strategy_shared.wealth_core.state import PortfolioState
        from stock_strategy_shared.wealth_core.marks import Mark,MarkStatus
        from stock_strategy_shared.wealth_core.funding import config
        from p01_celg_bridge_accounting import reconcile
        closing=deepcopy(run.state.last_evidence['research_entry_audit']['closing_accounting'])
        need(closing['ledger'].pop('event_count')==len(actual_ledger['events']),
             'ACTUAL_TWO_DAY_FINAL_CLOSING_ACCOUNTING_FULL_LEDGER_COUNT')
        closing['ledger']['events']=deepcopy(actual_ledger['events'])
        independent=reconcile(closing,q)
        marks={}
        for sid,value in closing['prices'].items():
            status=MarkStatus(value['status']);params={}
            if status is MarkStatus.CURRENT:params['raw_mark_close']=value['raw_price']
            elif status is MarkStatus.PENDING_TERMS_CARRIED:params['carried_raw_close']=value['raw_price']
            marks[sid]=Mark(security_id=sid,status=status,**params)
        before_report=runtime.checkpoint(run)
        report=terminal.final_report(session=NEW,state=PortfolioState.from_dict(closing['wealth_core']),
            marks=marks,ledger=ledger.Ledger.from_dict(actual_ledger),cfg=config(run.policy)).to_dict()
        need(len(report.get('merger_rights_received_and_liquidated',[]))==len(rights)
             and runtime.checkpoint(run)==before_report,'ACTUAL_TYPED_RIGHT_CANONICAL_REPORT_WITHOUT_BOOK_MUTATION')
        save(proof_dir/'actual-right-accounting-and-report.json',dict(independent_accounting=independent,
            canonical_report=report,actual_ledger=actual_ledger,full_state_unchanged_by_report=True,
            financial_predecessor_authorized=False))
    for name in ('celg-clock-input.json','source-successor.json','zero-session-boundaries.json','bridge-preflight.json'):
        shutil.copyfile(out/name,proof_dir/name)
    with gzip.open(proof_dir/'actual-two-session-component.json.gz','wb') as stream:
        stream.write((json.dumps(observed,sort_keys=True,allow_nan=False)+'\n').encode())
    save(proof_dir/'qualification-summary.json',dict(status='OWN475_CELG_SOURCE_INPUT_AND_TWO_SESSIONS_QUALIFIED',
        financial_authority=False,financial_predecessor_authorized=False,
        source_outer_sha256=cp['sha256'],source_map_sha256=digest(source_map),
        source_receipt_sha256=sha((out/'source-successor.json').read_bytes()),
        input_document_sha256=zero['input_document_sha256'],successor_input_sha256=zero['successor_input_sha256'],
        source_zero_inner_sha256=zero['source_checkpoint']['run']['checkpoint_sha256'],
        input_zero_outer_sha256=current['sha256'],actual_role_and_full_state_checks=guard.observed,
        quote_input_identity_sha256=q['input_identity_sha256'],component_transitions=2,
        actual_hosted_falsifiers=negatives,
        actual_inherited_scope_source_packets=scope_sources,
        qualification_checkpoint_is_financial_authority=False,processing_endpoint=END,maximum_transitions=len(wanted)))


def economic(old,out):
    from research.pooled_vacancy_funding import backtest,journal
    cp,source_map,wanted,pre=prepare(old,out);q,descriptor=authenticated_quote()
    qualified=json.loads(Path('/evidence/proof/qualification-summary.json').read_bytes())
    need(qualified['financial_predecessor_authorized'] is False
         and qualified['quote_input_identity_sha256']==q['input_identity_sha256'],
         'ACTUAL_STOPPED_NONFINANCIAL_QUALIFIER_SAME_AUTHENTICATED_QUOTE')
    with old_inputs(old,cp,out/'contexts'),boundaries(old,out,cp,source_map,q,descriptor) as values:
        current,codec,loaded,path,zero=values
        need(loaded.sha256==qualified['input_document_sha256']
             and current['sha256']==qualified['input_zero_outer_sha256']
             and current['run']['input_sha256']==qualified['successor_input_sha256']
             and zero['source_checkpoint']['run']['checkpoint_sha256']==qualified['source_zero_inner_sha256'],
             'FRESH_ORIGINAL_OWN475_REPRODUCES_QUALIFIED_SOURCE_THEN_INPUT_BOUNDARIES')
        for name in ('hydrated-factual-catalog.json','hydrated-distribution-catalog.json'):
            shutil.copyfile(old/name,out/name)
        guard=RoleGuard(q,qualified=qualified['actual_role_and_full_state_checks'],book=out/'book')
        observation=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
        args=arguments(out/'book',True,len(wanted));args[args.index('--policy')+1]=cp['base']['policy']
        with guard,observation,Execution('FAST',signal_closes=1) as execution:
            code=backtest.main(args+['--source-successor',str(path)])
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observation.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',pre))
    current=require_strict_checkpoint(journal.read_checkpoint(out/'book/checkpoint.json.gz'))
    complete=code==0 and current['source_cursor']==END and current['completed']==475+len(wanted)
    save(out/'celg-bridge-outcome.json',dict(status='COMPLETE_CELG_BRIDGE_SEGMENT_PENDING_REVIEW' if complete else
        'CELG_BRIDGE_PARTIAL_OR_REFUSAL_PRESERVED',canonical_return_code=code,
        source_cursor=current['source_cursor'],completed=current['completed'],new_transitions=current['completed']-475,
        processing_endpoint=END,maximum_transitions=len(wanted),original_own475_resumed_fresh=True,
        qualification_state_adopted=False,input_document_sha256=loaded.sha256,
        actual_role_and_full_state_checks=guard.observed,actual_codec_applications=codec.applied,
        actual_inherited_native_scope_guards=guard.scope_observed,
        full_measurement_end='2026-07-31',production_contacted=False))


def main(args):
    hosted();need(json.loads(args.spec.read_bytes())==specification(),'EXACT_MOUNTED_OWN475_SPEC')
    if args.mode=='qualify':qualify(Path('/old'),Path('/out'))
    elif args.mode=='economic':economic(Path('/old'),Path('/out'))
    else:
        from p01_celg_bridge_review import review
        review(Path('/old'),Path('/evidence'),Path('/out'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('qualify','economic','review'),required=True)
    p.add_argument('--spec',type=Path,required=True);main(p.parse_args())
