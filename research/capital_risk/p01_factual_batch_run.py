"""Hosted current-epoch zero resume, grouped input qualification and own continuation."""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import gzip
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

from full_system_core import hosted,arguments
from full_system_benchmark import save
from p01_epoch_parent import validate_contents
from p01_epoch_resume import historical_epoch
from p01_factual_batch_contract import (HERE,SPEC,INPUT,END,MAXIMUM,specification,document,encoded,
    digest,sha,need,term)
from p01_factual_batch_codec import InputCodec,source_terms
from p01_factual_batch_guard import ActionGuard,require_scope
from p01_factual_batch_pause import EpochPause
from system_campaign_pxd_pause import PauseAfterAdoption,adoption
from system_campaign_discovery_context import material,require_strict_checkpoint
from system_campaign_factual_run import (copy_repair_archive,correlation_seed,SeededObservation,preserve_tails)
from system_campaign_acceleration import Execution


def prepare(old,out):
    """Copy the immutable admitted book; metadata admission never decodes state."""
    spec=specification();cp=validate_contents(old,spec)
    from research.pooled_input_support.bundle import axis
    dates=axis();wanted=[d for d in dates if cp['source_cursor']<d<=END]
    need(len(wanted)==MAXIMUM and wanted[:2]==['2020-02-05','2020-02-06'] and wanted[-1]==END,
         'EXACT_FROZEN_101_SESSION_SUFFIX_BEFORE_MTCH2')
    book=out/'book';book.mkdir();(book/'predecessor-checkpoints').mkdir()
    shutil.copyfile(old/spec['selected_checkpoint'],book/'checkpoint.json.gz')
    shutil.copyfile(old/spec['selected_checkpoint'],book/'predecessor-checkpoints'/(cp['sha256']+'.json.gz'))
    shutil.copyfile(old/'book/identity.json',book/'identity.json');copy_repair_archive(old,book)
    original={}
    for base in ('book','lineage'):
        for path in (old/base).rglob('*.json.gz'):
            rel=path.relative_to(old);dest=out/'lineage/original-checkpoints'/rel
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
            original[rel.as_posix()]=dict(bytes=path.stat().st_size,sha256=sha(path.read_bytes()))
    for folder in ('source-successors',):
        if (old/'book'/folder).exists():shutil.copytree(old/'book'/folder,book/folder)
    tails={}
    for name,c in cp['journals'].items():
        raw=(old/f'book/{name}.jsonl').read_bytes()
        need(len(raw)==c['bytes'] and sha(raw)==c['prefix_sha256'],'EXACT_ADMITTED_PREFIX_NO_TAIL')
        (book/(name+'.jsonl')).write_bytes(raw);tails[name]=dict(bytes=0,sha256=sha(b''))
    # Keep the original source metadata as inherited evidence, without relabeling it.
    for name in ('source-successor.json','hydrated-factual-catalog.json','hydrated-distribution-catalog.json'):
        if (old/name).exists():shutil.copyfile(old/name,out/name)
    proof=dict(schema='research.p01-factual-batch-preflight/1',original_outer_sha256=cp['sha256'],
        root_admission_descriptor_sha256=spec['root_admission_descriptor_sha256'],
        original_checkpoint_files=original,tails_to_preserve=tails,next_session=wanted[0],
        processing_endpoint=END,maximum_transitions=len(wanted),original_inputs=10,
        financial_source_epoch_unchanged=True,old_financial_and_accounting_audits_reused=True,
        old_financial_audits_repeated=False,qualification_state_adopted=False)
    save(out/'batch-preflight.json',proof)
    return cp,wanted,proof


def exact_prefixes(old,book,parent,current,events):
    checks={}
    for name,c in parent['journals'].items():
        before=(old/f'book/{name}.jsonl').read_bytes();after=(book/(name+'.jsonl')).read_bytes()
        need(after[:c['bytes']]==before,'ZERO_BOUNDARY_ALL_ADMITTED_PREFIX_BYTES_EXACT')
        suffix=[json.loads(v) for v in after[c['bytes']:].splitlines()]
        need(suffix==(events if name=='watch' else []),'ZERO_BOUNDARY_ONLY_ONE_INPUT_WATCH_NO_SOURCE_EVENT')
        checks[name]=dict(before=c,after=current['journals'][name])
    return checks


@contextmanager
def boundaries(old,out,binding):
    from research.pooled_vacancy_funding import backtest,runtime,journal
    parent=binding.parent;args=arguments(out/'book',True)
    args[args.index('--policy')+1]=parent['base']['policy']
    pause=EpochPause(parent,out/'book/checkpoint.json.gz')
    with pause:code=backtest.main(args+binding.source_args)
    need(code==0,'ACTUAL_RETAINED_EPOCH_ZERO_RESUME')
    epoch=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    need(epoch==parent,'CURRENT_EPOCH_FULL_ZERO_CHECKPOINT_EXACT')
    epoch_proof=pause.proof();exact_prefixes(old,out/'book',parent,epoch,[])
    raw=(HERE/INPUT).read_bytes()
    need(raw==encoded(document()),'STATIC_PUBLIC_INPUT_BYTES_NOT_REENCODED_PRIVATE_DOCUMENT')
    path=out/'batch-input.json';path.write_bytes(raw)
    with InputCodec(source_terms()) as codec:
        loaded=backtest.load_repair(path,resume_session=parent['source_cursor'],
            predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'])
        pause_input=PauseAfterAdoption(parent,out/'book/checkpoint.json.gz',loaded.sha256,'2020-02-05')
        with pause_input:code=backtest.main(args+binding.source_args+['--repair-overlay',str(path)])
        need(code==0,'ACTUAL_ELEVENTH_INPUT_ZERO_SESSION_STARTUP')
        current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
        event=binding.source_gate.allow_input(current,loaded.sha256,'2020-02-05')
        need(event==adoption(current,parent,loaded.sha256,'2020-02-05'),'EXACT_CANONICAL_ELEVENTH_INPUT_EVENT')
        prefix=exact_prefixes(old,out/'book',parent,current,[event])
        restored=runtime.restore(current['run'],policy=current['base']['policy'],input_sha256=current['run']['input_sha256'])
        need(runtime.checkpoint(restored)==current['run'],'NEW_INPUT_ZERO_FULL_CANONICAL_RESTORE')
        proof=dict(source=epoch_proof,epoch_checkpoint=epoch,input=pause_input.proof(),
            input_checkpoint=current,input_event=event,prefixes=prefix,input_document_sha256=loaded.sha256,
            successor_input_sha256=current['run']['input_sha256'],financial_authority=False,
            source_epoch_boundary_reemitted=False,financial_predecessor_authorized=False)
        save(out/'zero-session-boundaries.json',proof)
        yield current,codec,loaded,proof


def refuse(call,label):
    try:call()
    except (ValueError,TypeError):return label
    raise ValueError('REFUSED_P01_FACTUAL_BATCH_MISSING_FALSIFIER_'+label)


def codec_proof(codec,loaded,out):
    """Exercise source-bound dates without inventing observations or future state."""
    from research.pooled_input_support.adapter import Packet
    negatives=[];rows=[];codec.control=True
    try:
        for a in codec.records:
            dates=sorted({a['economic_session'],*[n['session'] for n in a['native_events']]})
            for day in dates:
                packet=Packet(day,(),{},{},1.,{},tuple(codec.native.get(day,())),())
                before=material(packet);changed=codec.apply(packet,loaded)
                source=[material(t) for t in changed.terminal if t.security_id==a['source_security_id']]
                need(source==([term(a)] if day==a['economic_session'] else []),
                     'CONTROL_EXACT_ECONOMIC_DATE_AND_NO_DUPLICATE_ENTITLEMENT')
                after=material(changed)
                need({k:v for k,v in before.items() if k!='terminal'}=={k:v for k,v in after.items() if k!='terminal'},
                     'CONTROL_QUOTES_WINDOW_CASH_SPINS_ALL_UNCHANGED')
                rows.append(dict(action_id=a['action_id'],session=day,source_preimages_bound=True,
                    only_terminal_field_changed=True,economic_term_present=day==a['economic_session'],
                    no_market_observations_fabricated=True,financial_sessions_advanced=0))
            native_day=a['native_events'][0]['session']
            source=next(t for t in codec.native[native_day] if t.security_id==a['source_security_id'])
            raw=Packet(native_day,(),{},{},1.,{},tuple(codec.native[native_day]),())
            without=replace(raw,terminal=tuple(t for t in raw.terminal if t.security_id!=a['source_security_id']))
            negatives.append(refuse(lambda:codec.apply(without,loaded),'missing_preimage_'+a['action_id']))
            mutated=replace(source,reference=str(source.reference)+'#mutated')
            changed=replace(raw,terminal=tuple(mutated if t is source else t for t in raw.terminal))
            negatives.append(refuse(lambda:codec.apply(changed,loaded),'mutated_preimage_'+a['action_id']))
            negatives.append(refuse(lambda:codec.apply(raw,deepcopy(loaded)),'unregistered_input_'+a['action_id']))
            pending=SimpleNamespace(wealth_core={'episodes':{}},median5={'selected':[]},
                pending=[dict(security_id=a['source_security_id'],operation='OPEN_SLOT_POSITION',
                              intended_dollars='100',signal_session='2020-02-04')])
            negatives.append(refuse(lambda:require_scope(pending,a),'source_future_open_pending_'+a['action_id']))
        need(len(rows)>=18,'EVERY_REGISTERED_ACTION_DATED_CONTROL_PROOF')
    finally:codec.control=False
    value=dict(schema='research.p01-group-action-codec-proof/1',actions=18,dated_controls=rows,
        falsifiers=negatives,old_ten_input_bytes_unchanged=True,financial_authority=False)
    save(out/'group-action-codec-proof.json',value);return value


def action_report(run,quote,out,guard):
    from stock_strategy_shared.wealth_core import terminal,ledger
    from stock_strategy_shared.wealth_core.state import PortfolioState
    from stock_strategy_shared.wealth_core.marks import Mark,MarkStatus
    from stock_strategy_shared.wealth_core.funding import config
    from research.pooled_vacancy_funding import runtime
    from p01_factual_batch_accounting import reconcile
    actual=deepcopy(run.state.ledger);closing=deepcopy(run.state.last_evidence['research_entry_audit']['closing_accounting'])
    need(closing['ledger'].pop('event_count')==len(actual['events']),'FULL_CURRENT_CLOSING_LEDGER_COUNT')
    closing['ledger']['events']=deepcopy(actual['events'])
    independent=reconcile(closing,quote,actions=guard.records)
    marks={}
    for sid,value in closing['prices'].items():
        status=MarkStatus(value['status']);params={}
        if status is MarkStatus.CURRENT:params['raw_mark_close']=value['raw_price']
        elif status is MarkStatus.PENDING_TERMS_CARRIED:params['carried_raw_close']=value['raw_price']
        marks[sid]=Mark(security_id=sid,status=status,**params)
    before=runtime.checkpoint(run)
    report=terminal.final_report(session=run.state.last_processed_session,state=PortfolioState.from_dict(closing['wealth_core']),
        marks=marks,ledger=ledger.Ledger.from_dict(actual),cfg=config(run.policy)).to_dict()
    need(runtime.checkpoint(run)==before,'REPORT_DOES_NOT_MUTATE_ANY_FINANCIAL_OR_CONTROLLER_FIELD')
    save(out/'action-accounting-and-report.json',dict(independent_accounting=independent,canonical_report=report,
        actual_ledger=actual,full_state_unchanged_by_report=True,financial_authority=False))


def qualify(old,out):
    from research.pooled_vacancy_funding import runtime,backtest,journal
    from p01_factual_batch_component import qualify_components
    cp,wanted,pre=prepare(old,out);proof_dir=out/'proof';proof_dir.mkdir()
    with historical_epoch(old,out,specification()) as binding,boundaries(old,out,binding) as values:
        current,codec,loaded,zero=values
        codec_proof(codec,loaded,proof_dir)
        run=runtime.restore(current['run'],policy=current['base']['policy'],input_sha256=current['run']['input_sha256'])
        component=qualify_components(binding,run.state,proof_dir)
        need(component['target_independence_qualified'] is True
             and component['ordinary_representation_qualified'] is True
             and component['held_target_holding_qualified'] is True,
             'ACTUAL_CANONICAL_TARGET_ROLE_INDEPENDENCE_QUALIFICATION')
        guard=ActionGuard(out/'book',target_independence_qualified=True,held_target_holding_qualified=True)
        args=arguments(out/'book',True,2);args[args.index('--policy')+1]=cp['base']['policy']
        with guard,Execution('FAST',signal_closes=1):code=backtest.main(args+binding.source_args)
        need(code==0 and [r['session'] for r in guard.observed]==wanted[:2],
             'ACTUAL_TWO_COMPLETE_CANONICAL_SESSIONS_NOT_MANUAL_STATE')
        final=journal.read_checkpoint(out/'book/checkpoint.json.gz')
        need(final['completed']==528 and final['source_cursor']=='2020-02-06','ACTUAL_TWO_DAY_QUALIFIER_CURSOR')
        run=runtime.restore(final['run'],policy=final['base']['policy'],input_sha256=final['run']['input_sha256'])
        action_report(run,binding.quote,proof_dir,guard)
        with gzip.open(proof_dir/'actual-two-session-component.json.gz','wb') as stream:
            stream.write(encoded(dict(actual_components=guard.components,action_checks=guard.action_checks,
                pre_event_checkpoints=guard.pre_events,inherited_native_scope_checks=guard.native_checks,
                qualifier_checkpoint=final,financial_authority=False)))
        for name in ('batch-input.json','zero-session-boundaries.json','batch-preflight.json'):
            shutil.copyfile(out/name,proof_dir/name)
        save(proof_dir/'qualification-summary.json',dict(status='OWN526_GROUPED_FACTUAL_INPUT_AND_RUNTIME_QUALIFIED',
            financial_authority=False,financial_predecessor_authorized=False,
            input_document_sha256=loaded.sha256,successor_input_sha256=zero['successor_input_sha256'],
            epoch_zero_outer_sha256=cp['sha256'],input_zero_outer_sha256=current['sha256'],
            actual_role_and_full_state_checks=guard.observed,component_transitions=2,
            source_epoch_boundary_reemitted=False,target_independence_qualified=True,held_target_holding_qualified=True,
            processing_endpoint=END,maximum_transitions=len(wanted),qualification_state_adopted=False))


def economic(old,out):
    from research.pooled_vacancy_funding import backtest,journal
    cp,wanted,pre=prepare(old,out)
    qualified=json.loads(Path('/evidence/proof/qualification-summary.json').read_bytes())
    need(qualified['status']=='OWN526_GROUPED_FACTUAL_INPUT_AND_RUNTIME_QUALIFIED'
         and qualified['financial_predecessor_authorized'] is False
         and qualified['source_epoch_boundary_reemitted'] is False
         and qualified['epoch_zero_outer_sha256']==cp['sha256'],'ACTUAL_STOPPED_QUALIFIER_NOT_FINANCIAL_AUTHORITY')
    with historical_epoch(old,out,specification()) as binding,boundaries(old,out,binding) as values:
        current,codec,loaded,zero=values
        need(loaded.sha256==qualified['input_document_sha256']
             and current['sha256']==qualified['input_zero_outer_sha256']
             and current['run']['input_sha256']==qualified['successor_input_sha256'],
             'FRESH_ORIGINAL_OWN526_REPRODUCES_QUALIFIED_EPOCH_AND_INPUT_ZERO')
        guard=ActionGuard(out/'book',qualified=qualified['actual_role_and_full_state_checks'],
                          target_independence_qualified=qualified['target_independence_qualified'],
                          held_target_holding_qualified=qualified['held_target_holding_qualified'])
        observation=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
        args=arguments(out/'book',True,len(wanted));args[args.index('--policy')+1]=cp['base']['policy']
        with guard,observation,Execution('FAST',signal_closes=1) as execution:
            code=backtest.main(args+binding.source_args)
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observation.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',pre))
    current=require_strict_checkpoint(journal.read_checkpoint(out/'book/checkpoint.json.gz'))
    committed=lambda rows:[r for r in rows if r['session']<=current['source_cursor']]
    with gzip.open(out/'actual-financial-first-two-component.json.gz','wb') as stream:
        stream.write(encoded(dict(actual_components=committed(guard.components),attempted_components=guard.components,
                                  financial_authority=False,
                                  qualification_state_adopted=False)))
    complete=code==0 and current['source_cursor']==END and current['completed']==526+len(wanted)
    save(out/'batch-outcome.json',dict(status='COMPLETE_FACTUAL_BATCH_SEGMENT_PENDING_REVIEW' if complete else
        'FACTUAL_BATCH_PARTIAL_OR_REFUSAL_PRESERVED',canonical_return_code=code,source_cursor=current['source_cursor'],
        completed=current['completed'],new_transitions=current['completed']-526,processing_endpoint=END,
        maximum_transitions=len(wanted),original_own526_resumed_fresh=True,qualification_state_adopted=False,
        input_document_sha256=loaded.sha256,actual_role_and_full_state_checks=committed(guard.observed),
        attempted_role_and_full_state_checks=guard.observed,actual_codec_applications=codec.applied,
        actual_action_scope_checks=committed(guard.action_checks),attempted_action_scope_checks=guard.action_checks,
        actual_pre_event_checkpoints=guard.pre_events,actual_inherited_native_scope_guards=committed(guard.native_checks),
        attempted_inherited_native_scope_guards=guard.native_checks,
        source_epoch_boundary_reemitted=False,full_measurement_end='2026-07-31',production_contacted=False))


def main(args):
    hosted();need(json.loads(args.spec.read_bytes())==specification(),'EXACT_MOUNTED_OWN526_SPEC')
    if args.mode=='qualify':qualify(Path('/old'),Path('/out'))
    elif args.mode=='economic':economic(Path('/old'),Path('/out'))
    else:
        from p01_factual_batch_review import review
        review(specification(),Path('/out'),Path('/evidence'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('qualify','economic','review'),required=True)
    p.add_argument('--spec',type=Path,required=True);main(p.parse_args())
