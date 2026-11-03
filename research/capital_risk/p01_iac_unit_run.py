"""Hosted own628 zero/input boundary, unit components, and fresh continuation."""
import argparse
from contextlib import contextmanager
from copy import deepcopy
import gzip
import json
from pathlib import Path
import shutil

from full_system_core import hosted,arguments
from full_system_benchmark import save
from p01_iac_unit_parent import validate_contents,OUTER,ROOT_ADMISSION
from p01_iac_unit_epoch import historical_epoch
from p01_iac_unit_contract import (HERE,SPEC,INPUT,END,MAXIMUM,FIRST,EVENT,ORIGINAL_INPUT,
    specification,document,encoded,sha,digest,need,reused_qualification)
from p01_iac_unit_codec import InputCodec,source_rows
from p01_iac_unit_guard import UnitGuard,source_contract
from p01_iac_unit_component import qualify_components
from p01_factual_batch_pause import EpochPause
from system_campaign_pxd_pause import PauseAfterAdoption,adoption
from system_campaign_discovery_context import require_strict_checkpoint
from system_campaign_factual_run import (copy_repair_archive,correlation_seed,SeededObservation,preserve_tails)
from system_campaign_acceleration import Execution


def prepare(old,out):
    spec=specification();parent=validate_contents(old,spec);out.mkdir(parents=True,exist_ok=True)
    from research.pooled_input_support.bundle import axis
    wanted=[day for day in axis() if parent['source_cursor']<day<=END]
    need(len(wanted)==MAXIMUM and wanted[:2]==list(FIRST) and wanted[-1]==END,'EXACT251_SOURCE_AXIS_FROM_ACTUAL628')
    book=out/'book';book.mkdir();(book/'predecessor-checkpoints').mkdir()
    shutil.copyfile(old/spec['selected_checkpoint'],book/'checkpoint.json.gz')
    shutil.copyfile(old/spec['selected_checkpoint'],book/'predecessor-checkpoints'/(parent['sha256']+'.json.gz'))
    shutil.copyfile(old/'book/identity.json',book/'identity.json');copy_repair_archive(old,book)
    original={}
    for base in ('book','lineage'):
        for path in (old/base).rglob('*.json.gz'):
            rel=path.relative_to(old);dest=out/'lineage/original-checkpoints'/rel
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
            original[rel.as_posix()]=dict(bytes=path.stat().st_size,sha256=sha(path.read_bytes()))
    need(original==spec['retained_checkpoint_files'],'EVERY38_ORIGINAL_GZIP_PRESERVED')
    if (old/'book/source-successors').exists():shutil.copytree(old/'book/source-successors',book/'source-successors')
    tails={}
    for name,c in parent['journals'].items():
        raw=(old/f'book/{name}.jsonl').read_bytes()
        need(len(raw)==c['bytes'] and sha(raw)==c['prefix_sha256'],'ORIGINAL628_EXACT_PREFIX_NO_TAIL')
        (book/(name+'.jsonl')).write_bytes(raw);tails[name]=dict(bytes=0,sha256=sha(b''))
    for name in ('source-successor.json','hydrated-factual-catalog.json','hydrated-distribution-catalog.json'):
        if (old/name).exists():shutil.copyfile(old/name,out/name)
    entry=spec['reused_action_component'];raw=(old/entry['member']).read_bytes()
    need(len(raw)==entry['bytes'] and sha(raw)==entry['sha256'],'RETAINED_ADMITTED_ACTION_COMPONENT_BYTES')
    target=out/'retained-qualification/target-independence-component.json.gz';target.parent.mkdir();target.write_bytes(raw)
    proof=dict(schema='research.p01-iac-unit-preflight/1',original_outer_sha256=parent['sha256'],
        root_admission_descriptor_sha256=ROOT_ADMISSION,original_checkpoint_files=original,tails_to_preserve=tails,
        next_session=EVENT,processing_endpoint=END,maximum_transitions=MAXIMUM,original_inputs=11,
        financial_source_epoch_unchanged=True,old_financial_and_accounting_audits_reused=True,
        old_financial_audits_repeated=False,qualification_state_adopted=False,
        retained_action_component=dict(member=target.relative_to(out).as_posix(),bytes=len(raw),sha256=sha(raw),financial_authority=False))
    save(out/'iac-unit-preflight.json',proof)
    return parent,wanted,proof


def exact_prefixes(old,book,parent,current,events):
    result={}
    for name,c in parent['journals'].items():
        before=(old/f'book/{name}.jsonl').read_bytes();after=(book/(name+'.jsonl')).read_bytes()
        need(after[:c['bytes']]==before,'ZERO_FULL_ORIGINAL628_PREFIX_BYTES')
        suffix=[json.loads(v) for v in after[c['bytes']:].splitlines()]
        need(suffix==(events if name=='watch' else []),'ZERO_ONLY_ACTUAL_TWELFTH_INPUT_EVENT_NO_SOURCE_BOUNDARY')
        result[name]=dict(before=c,after=current['journals'][name])
    return result


@contextmanager
def boundaries(old,out,binding,rows):
    from research.pooled_vacancy_funding import backtest,runtime,journal
    parent=binding.parent;args=arguments(out/'book',True);args[args.index('--policy')+1]=parent['base']['policy']
    pause=EpochPause(parent,out/'book/checkpoint.json.gz')
    with pause:code=backtest.main(args+binding.source_args)
    need(code==0,'ACTUAL_ORIGINAL628_UNCHANGED_ZERO_STARTUP')
    epoch=journal.read_checkpoint(out/'book/checkpoint.json.gz');need(epoch==parent,'WHOLE628_ZERO_CHECKPOINT_EXACT')
    source=pause.proof();source=dict(source,inherited_generic_status=source['status'],
        status='OWN628_RETAINED_EPOCH_CANONICAL_STARTUP_ZERO_SESSIONS',
        generic_pause_source_sha256=sha((HERE/'p01_factual_batch_pause.py').read_bytes()))
    exact_prefixes(old,out/'book',parent,epoch,[])
    raw=(HERE/INPUT).read_bytes();need(raw==encoded(document()),'EXACT_STATIC_PUBLIC_TWELFTH_INPUT_BYTES')
    path=out/'iac-unit-input.json';path.write_bytes(raw)
    with InputCodec(rows,parent) as codec:
        loaded=backtest.load_repair(path,resume_session=parent['source_cursor'],
            predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'])
        input_pause=PauseAfterAdoption(parent,out/'book/checkpoint.json.gz',loaded.sha256,EVENT)
        with input_pause:code=backtest.main(args+binding.source_args+['--repair-overlay',str(path)])
        need(code==0,'ACTUAL_CANONICAL_TWELFTH_INPUT_ZERO_STARTUP')
        current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
        event=binding.source_gate.allow_input(current,loaded.sha256,EVENT)
        need(event==adoption(current,parent,loaded.sha256,EVENT),'EXACT_ACTUAL_CANONICAL_INPUT_EVENT_AND_CHAIN')
        prefixes=exact_prefixes(old,out/'book',parent,current,[event])
        restored=runtime.restore(current['run'],policy=current['base']['policy'],input_sha256=current['run']['input_sha256'])
        need(runtime.checkpoint(restored)==current['run'],'WHOLE_NEW_INPUT_ZERO_CANONICAL_RESTORE')
        value=dict(schema='research.p01-iac-unit-zero-boundaries/1',source=source,epoch_checkpoint=epoch,
            input=input_pause.proof(),input_checkpoint=current,input_event=event,prefixes=prefixes,
            input_document_sha256=loaded.sha256,successor_input_sha256=current['run']['input_sha256'],
            financial_authority=False,financial_predecessor_authorized=False,source_epoch_boundary_reemitted=False,
            input_adoptions=1,old_eleven_input_bytes_unchanged=True)
        save(out/'zero-session-boundaries.json',value)
        yield codec,loaded,value


def report(run,quote,guard):
    from stock_strategy_shared.wealth_core import terminal,ledger
    from stock_strategy_shared.wealth_core.state import PortfolioState
    from stock_strategy_shared.wealth_core.marks import Mark,MarkStatus
    from stock_strategy_shared.wealth_core.funding import config
    from research.pooled_vacancy_funding import runtime
    from p01_factual_batch_accounting import reconcile
    actual=deepcopy(run.state.ledger)
    closing=deepcopy(run.state.last_evidence['research_entry_audit']['closing_accounting'])
    need(closing['ledger'].pop('event_count')==len(actual['events']),'FULL_CURRENT_RAW_LEDGER_EVENT_PREFIX')
    closing['ledger']['events']=deepcopy(actual['events']);independent=reconcile(closing,quote,actions=guard.records)
    marks={}
    for sid,value in closing['prices'].items():
        status=MarkStatus(value['status']);params={}
        if status is MarkStatus.CURRENT:params['raw_mark_close']=value['raw_price']
        elif status is MarkStatus.PENDING_TERMS_CARRIED:params['carried_raw_close']=value['raw_price']
        marks[sid]=Mark(security_id=sid,status=status,**params)
    before=runtime.checkpoint(run)
    canonical=terminal.final_report(session=run.state.last_processed_session,state=PortfolioState.from_dict(closing['wealth_core']),
        marks=marks,ledger=ledger.Ledger.from_dict(actual),cfg=config(run.policy)).to_dict()
    need(runtime.checkpoint(run)==before,'REPORT_DOES_NOT_MUTATE_FULL_FINANCIAL_OR_CONTROLLER_STATE')
    return dict(canonical_report=canonical,independent_accounting=independent,actual_ledger=actual,full_state_unchanged_by_report=True)


def refusal_rows(codec):return [deepcopy(value) for value in codec.refusals.values()]


def last_attempt(applications,refusals,prepared,guard_refusals):
    streams=(applications,refusals,prepared,guard_refusals)
    sessions=[row['session'] for rows in streams for row in rows]
    if not sessions:return None
    day=max(sessions)
    keys=('codec_application_sha256','codec_refusal_sha256','prepared_window_sha256','guard_refusal_sha256')
    value=dict(schema='research.p01-iac-unit-last-observed-attempt/1',session=day,financial_authority=False)
    for key,rows in zip(keys,streams):
        matching=[row for row in rows if row['session']==day]
        value[key]=digest(matching[-1]) if matching else None
    return value


def branch(old,out,rows,mode,*,qualified=None,proof_dir=None):
    from research.pooled_vacancy_funding import backtest,runtime,journal
    parent,wanted,pre=prepare(old,out)
    with historical_epoch(old,out,specification()) as binding,boundaries(old,out,binding,rows) as values:
        codec,loaded,zero=values;contract=source_contract(binding);reused=reused_qualification(old,binding.source_map)
        component=None
        if proof_dir is not None:
            initial=runtime.restore(zero['input_checkpoint']['run'],policy=parent['base']['policy'],
                input_sha256=zero['successor_input_sha256'])
        guard=UnitGuard(out/'book',codec,contract,qualified=qualified,reused=reused)
        args=arguments(out/'book',True,2);args[args.index('--policy')+1]=parent['base']['policy']
        with guard,Execution(mode,signal_closes=1) as execution:code=backtest.main(args+binding.source_args)
        final=journal.read_checkpoint(out/'book/checkpoint.json.gz')
        need(code==0 and final['completed']==630 and final['source_cursor']==FIRST[-1]
             and [r['session'] for r in guard.observed]==list(FIRST),'TWO_ACTUAL_COMPLETE_CANONICAL_QUALIFIER_SESSIONS')
        run=runtime.restore(final['run'],policy=final['base']['policy'],input_sha256=final['run']['input_sha256'])
        need(runtime.checkpoint(run)==final['run'],'FULL_QUALIFIER_CURRENT_CANONICAL_ROUNDTRIP')
        if proof_dir is not None:
            first=runtime.restore(guard.components[0]['checkpoint'],policy=parent['base']['policy'],
                input_sha256=zero['successor_input_sha256'])
            component=qualify_components(binding,initial.state,codec,contract,proof_dir,post_event_state=first.state)
            need(all(component[k] is True for k in ('normalizer_qualified','unit_target_independence_qualified',
                'source_scope_falsifiers_qualified')),'ACTUAL_NEW_HOSTED_UNIT_COMPONENT_GATE')
        actual_report=report(run,binding.quote,guard)
        return dict(parent=parent,preflight=pre,zero=zero,component=component,contract=contract,reused=reused,
            codec_applications=deepcopy(codec.applied),codec_refusals=refusal_rows(codec),origin=deepcopy(codec.origin),
            components=deepcopy(guard.components),roles=deepcopy(guard.observed),action_checks=deepcopy(guard.action_checks),
            native_checks=deepcopy(guard.native_checks),source_checks=deepcopy(guard.source_checks),unit_checks=deepcopy(guard.unit_checks),
            pre_events=deepcopy(guard.pre_events),prepared=deepcopy(guard.prepared),guard_refusals=deepcopy(guard.refusals),
            final=final,report=actual_report,execution=execution.proof())


def qualify(old,out):
    rows,members=source_rows();proof=out/'proof';proof.mkdir()
    reference=branch(old,out/'reference',rows,'REFERENCE',proof_dir=proof)
    fast=branch(old,out/'fast',rows,'FAST',qualified=reference['roles'])
    need(reference['zero']==fast['zero'] and reference['preflight']==fast['preflight']
         and reference['components']==fast['components'] and reference['final']==fast['final']
         and reference['report']==fast['report'] and reference['codec_applications']==fast['codec_applications']
         and reference['unit_checks']==fast['unit_checks'],'WHOLE_REFERENCE_FAST_ZERO_PATH_CURRENT_REPORT_AND_UNIT_PROOFS')
    for name in ('zero-session-boundaries.json','iac-unit-input.json','iac-unit-preflight.json'):
        shutil.copyfile(out/'fast'/name,proof/name)
    source=dict(schema='research.p01-iac-unit-normalization-source-proof/1',source_contract=reference['contract'],
        origin_basis=dict(source_series=reference['origin'],source_series_sha256=digest(reference['origin']),original_outer_sha256=OUTER),
        source_members=members,reference_applications=reference['codec_applications'],fast_applications=fast['codec_applications'],
        reference_refusals=reference['codec_refusals'],fast_refusals=fast['codec_refusals'],financial_authority=False)
    save(proof/'unit-normalization-source-proof.json',source)
    with gzip.open(proof/'actual-two-session-component.json.gz','wb') as stream:
        stream.write(encoded(dict(schema='research.p01-iac-unit-actual-two-session-component/1',
            reference_components=reference['components'],actual_components=fast['components'],
            reference_qualifier_checkpoint=reference['final'],qualifier_checkpoint=fast['final'],
            action_checks=fast['action_checks'],inherited_native_scope_checks=fast['native_checks'],
            source_unit_scope_checks=fast['source_checks'],unit_window_anchor_checks=fast['unit_checks'],
            pre_event_checkpoints=fast['pre_events'],financial_authority=False,qualification_state_adopted=False)))
    save(proof/'actual-unit-accounting-and-report.json',dict(schema='research.p01-iac-unit-actual-accounting-and-report/1',
        reference=reference['report'],fast=fast['report'],reference_equals_fast=True,
        financial_authority=False,qualification_state_adopted=False))
    component=reference['component'];zero=reference['zero']
    save(proof/'qualification-summary.json',dict(status='OWN628_IAC_UNIT_INPUT_AND_TWO_SESSION_FAST_REFERENCE_QUALIFIED',
        financial_authority=False,financial_predecessor_authorized=False,qualification_state_adopted=False,
        component_transitions=2,qualified_through=FIRST[-1],epoch_zero_outer_sha256=OUTER,
        input_zero_outer_sha256=zero['input_checkpoint']['sha256'],input_document_sha256=zero['input_document_sha256'],
        successor_input_sha256=zero['successor_input_sha256'],original_inputs=11,successor_inputs=12,
        source_epoch_boundary_reemitted=False,input_adoptions=1,actual_fast_reference_full_components_equal=True,
        unit_normalization_qualified=component['normalizer_qualified'],unit_target_independence_qualified=component['unit_target_independence_qualified'],
        source_scope_falsifiers_qualified=component['source_scope_falsifiers_qualified'],
        actual_role_and_full_state_checks=len(fast['roles']),actual_role_and_full_state_records=fast['roles'],
        reused_action_qualification=reference['reused'],
        processing_endpoint=END,maximum_transitions=MAXIMUM))


def economic(old,out):
    from research.pooled_vacancy_funding import backtest,runtime,journal
    from p01_iac_unit_job import check_qualification,expected_request
    qualified=json.loads(Path('/evidence/proof/qualification-summary.json').read_bytes())
    check_qualification(qualified,expected_request(),specification())
    parent,wanted,pre=prepare(old,out);rows,members=source_rows()
    with historical_epoch(old,out,specification()) as binding,boundaries(old,out,binding,rows) as values:
        codec,loaded,zero=values;contract=source_contract(binding);reused=reused_qualification(old,binding.source_map)
        need(zero==json.loads(Path('/evidence/proof/zero-session-boundaries.json').read_bytes())
             and reused==qualified['reused_action_qualification'],'FRESH628_ENTIRE_QUALIFIED_ZEROS_AND_CAPABILITY_REUSE')
        guard=UnitGuard(out/'book',codec,contract,qualified=qualified['actual_role_and_full_state_records'],reused=reused)
        observation=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,parent))
        args=arguments(out/'book',True,len(wanted));args[args.index('--policy')+1]=parent['base']['policy']
        with guard,observation,Execution('FAST',signal_closes=1) as execution:code=backtest.main(args+binding.source_args)
        current=require_strict_checkpoint(journal.read_checkpoint(out/'book/checkpoint.json.gz'))
        saved_run=runtime.restore(current['run'],policy=current['base']['policy'],input_sha256=current['run']['input_sha256'])
        need(runtime.checkpoint(saved_run)==current['run'],'ACTUAL_SAVED_FINANCIAL_CURRENT_CANONICAL_RESTORE')
        transitions=current['completed']-628
        save(out/'actual-unit-accounting-and-report.json',dict(schema='research.p01-iac-unit-current-accounting-and-report/1',
            status='ACTUAL_CURRENT_UNIT_ACCOUNTING_AND_REPORT_VERIFIED' if transitions else 'NO_NEW_COMMITTED_ACCOUNTING_REPORT_OLD_ADMISSION_REUSED',
            new_committed_transitions=transitions,current=report(saved_run,binding.quote,guard) if transitions else None,
            financial_authority=False,qualification_state_adopted=False))
        source=json.loads(Path('/evidence/proof/unit-normalization-source-proof.json').read_bytes())
        need(source['source_contract']==contract and source['origin_basis']['source_series']==codec.origin,
             'EXACT_SAME_UNIT_COMPILER_SOURCE_AND_ORIGINAL_BASIS')
        source.update(source_members=members,fast_applications=deepcopy(codec.applied),fast_refusals=refusal_rows(codec))
        save(out/'unit-normalization-source-proof.json',source)
        save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observation.proof())
        save(out/'recovered-tail-proof.json',preserve_tails(out/'book',pre))
        committed=lambda values:[v for v in values if v['session']<=current['source_cursor']]
        with gzip.open(out/'actual-financial-first-two-component.json.gz','wb') as stream:
            stream.write(encoded(dict(actual_components=committed(guard.components),attempted_components=guard.components,
                financial_authority=False,qualification_state_adopted=False)))
        complete=code==0 and current['completed']==879 and current['source_cursor']==END
        result=dict(status='COMPLETE_IAC_UNIT_SEGMENT_PENDING_REVIEW' if complete else 'IAC_UNIT_PARTIAL_OR_REFUSAL_PRESERVED',
            canonical_return_code=code,source_cursor=current['source_cursor'],completed=current['completed'],new_transitions=transitions,
            processing_endpoint=END,maximum_transitions=MAXIMUM,input_document_sha256=loaded.sha256,
            successor_input_sha256=current['run']['input_sha256'],original_inputs=11,successor_inputs=12,
            fresh_from_original628=True,qualification_state_adopted=False,source_epoch_boundary_reemitted=False,input_adoptions=1,
            actual_codec_applications=deepcopy(codec.applied),actual_codec_refusals=refusal_rows(codec),
            actual_pre_event_checkpoints=guard.pre_events,attempted_unit_preparations=guard.prepared,unit_guard_refusals=guard.refusals,
            last_observed_attempt=last_attempt(codec.applied,refusal_rows(codec),guard.prepared,guard.refusals),
            full_measurement_end='2026-07-31',production_contacted=False)
        for name,values in (('role_and_full_state_checks',guard.observed),('action_scope_checks',guard.action_checks),
            ('inherited_native_scope_guards',guard.native_checks),('source_unit_scope_checks',guard.source_checks),
            ('unit_window_anchor_checks',guard.unit_checks)):
            result['actual_'+name]=committed(values);result['attempted_'+name]=deepcopy(values)
        save(out/'iac-unit-outcome.json',result)


def main(args):
    hosted();need(json.loads(args.spec.read_bytes())==specification(),'EXACT_MOUNTED_PUBLIC_OWN628_SPEC')
    if args.mode=='qualify':qualify(Path('/old'),Path('/out'))
    elif args.mode=='economic':economic(Path('/old'),Path('/out'))
    else:
        from p01_iac_unit_review import review
        review(specification(),Path('/out'),Path('/evidence'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('qualify','economic','review'),required=True)
    p.add_argument('--spec',type=Path,required=True);main(p.parse_args())
