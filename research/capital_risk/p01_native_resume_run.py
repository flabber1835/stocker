"""Hosted unchanged OWN627 epoch, one actual closing session, fresh finance."""
import argparse
from copy import deepcopy
import gzip
import json
from pathlib import Path
import shutil

from full_system_core import hosted,arguments
from full_system_benchmark import save
from p01_native_resume_parent import validate_contents,OUTER,INPUT
from p01_native_resume_epoch import historical_epoch
from p01_native_resume_contract import (HERE,SPEC,END,MAXIMUM,FIRST,SOURCE,
    specification,reused_qualification,source_rows,need,sha,digest)
from p01_native_resume_guard import NativeGuard,SourceObserver,native_seam_scope,source_contract
from p01_factual_batch_pause import EpochPause
from system_campaign_discovery_context import require_strict_checkpoint
from system_campaign_factual_run import (copy_repair_archive,correlation_seed,SeededObservation,preserve_tails)
from system_campaign_acceleration import Execution

FALSIFIERS=('source_holding','source_exit_flag','source_future_buy','source_close_intent',
    'source_receivable','source_unresolved_terminal','source_pending_term','source_pending_session')


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'


def prepare(old,out):
    """Verbatim copies only; no canonical financial restore occurs here."""
    spec=specification();cp=validate_contents(old,spec)
    from research.pooled_input_support.bundle import axis
    wanted=[d for d in axis() if cp['source_cursor']<d<=END]
    need(wanted==list(FIRST) and len(wanted)==MAXIMUM,'EXACT_ONLY_JUNE30_SOURCE_AXIS')
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
    need(original==spec['retained_checkpoint_files'],'ALL34_ORIGINAL_GZIP_COMMITMENTS')
    if (old/'book/source-successors').exists():
        shutil.copytree(old/'book/source-successors',book/'source-successors')
    tails={}
    for name,c in cp['journals'].items():
        raw=(old/f'book/{name}.jsonl').read_bytes()
        need(len(raw)==c['bytes'] and sha(raw)==c['prefix_sha256'],'EXACT_ADMITTED_PREFIX_NO_TAIL')
        (book/(name+'.jsonl')).write_bytes(raw);tails[name]=dict(bytes=0,sha256=sha(b''))
    for name in ('source-successor.json','hydrated-factual-catalog.json','hydrated-distribution-catalog.json'):
        if (old/name).exists():shutil.copyfile(old/name,out/name)
    retained=spec['reused_action_component'];raw=(old/retained['member']).read_bytes()
    need(len(raw)==retained['bytes'] and sha(raw)==retained['sha256'],'EXACT_ADMITTED_COMPONENT_BYTES_RETAINED')
    component_path=out/'retained-qualification/target-independence-component.json.gz'
    component_path.parent.mkdir();component_path.write_bytes(raw)
    proof=dict(schema='research.p01-native-resume-preflight/1',original_outer_sha256=cp['sha256'],
        root_admission_descriptor_sha256=spec['root_admission_descriptor_sha256'],
        original_checkpoint_files=original,tails_to_preserve=tails,next_session=wanted[0],
        processing_endpoint=END,maximum_transitions=MAXIMUM,original_inputs=11,
        financial_source_epoch_unchanged=True,old_financial_and_accounting_audits_reused=True,
        old_financial_audits_repeated=False,qualification_state_adopted=False,
        retained_action_component=dict(member=component_path.relative_to(out).as_posix(),
            bytes=len(raw),sha256=sha(raw),financial_authority=False))
    save(out/'native-resume-preflight.json',proof)
    return cp,wanted,proof


def zero_resume(old,out,binding):
    from research.pooled_vacancy_funding import backtest,journal
    parent=binding.parent
    need(parent['sha256']==OUTER and parent['completed']==627 and parent['run']['input_sha256']==INPUT,
         'OWN627_BEFORE_GENERIC_PAUSE')
    args=arguments(out/'book',True);args[args.index('--policy')+1]=parent['base']['policy']
    pause=EpochPause(parent,out/'book/checkpoint.json.gz')
    with pause:code=backtest.main(args+binding.source_args)
    need(code==0,'ACTUAL_OWN627_NORMAL_ZERO_SESSION_STARTUP')
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    need(current==parent,'FULL_OWN627_ZERO_SESSION_CHECKPOINT_EXACT')
    inherited=pause.proof();prefixes={}
    for name,c in parent['journals'].items():
        before=(old/f'book/{name}.jsonl').read_bytes();after=(out/f'book/{name}.jsonl').read_bytes()
        need(before==after and len(after)==c['bytes'] and sha(after)==c['prefix_sha256'],
             'ZERO_SESSION_ALL_PREFIX_AND_BOUNDARY_EVENT_BYTES_UNCHANGED')
        prefixes[name]=dict(before=c,after=current['journals'][name])
    # The generic helper's historical label is retained as provenance, not used
    # as a substitute identity or gate. Every saved mapping is actual OWN627.
    source=dict(inherited, inherited_generic_status=inherited['status'],
        status='OWN627_RETAINED_EPOCH_CANONICAL_STARTUP_ZERO_SESSIONS',
        generic_pause_source_sha256=sha((HERE/'p01_factual_batch_pause.py').read_bytes()))
    proof=dict(schema='research.p01-native-epoch-zero/1',source=source,epoch_checkpoint=current,
        prefixes=prefixes,input_sha256=INPUT,source_epoch_boundary_reemitted=False,
        input_boundary_reemitted=False,financial_authority=False,financial_predecessor_authorized=False)
    save(out/'zero-session-resume.json',proof)
    return proof


def scope_falsifiers(state):
    """Noncanonical role dictionaries only; the actual state is never changed."""
    before=deepcopy(state if isinstance(state,dict) else state.__dict__)
    need(native_seam_scope(before,END),'ACTUAL_PRE_EVENT_SOURCE_SCOPE_BEFORE_PURE_FALSIFIERS')
    tested=[]
    for name in FALSIFIERS:
        bad=deepcopy(before)
        if name in ('source_holding','source_exit_flag'):
            bad['wealth_core']['episodes']['qualification-only']=dict(security_id=SOURCE,
                exit_pending=name=='source_exit_flag')
        elif name in ('source_future_buy','source_close_intent'):
            bad['pending'].append(dict(security_id=SOURCE,operation='OPEN_SLOT_POSITION' if name=='source_future_buy'
                else 'CLOSE_POSITION',intended_dollars='1',signal_session=END))
        elif name=='source_receivable':bad['ledger']['receivables'].append(dict(security_id=SOURCE))
        else:
            key={'source_unresolved_terminal':'unresolved_terminals','source_pending_term':'terminal_pending_terms',
                 'source_pending_session':'terminal_pending_sessions'}[name]
            bad['wealth_core'].setdefault(key,{})[SOURCE]='qualification-only'
        snapshot=deepcopy(bad)
        try:native_seam_scope(bad,END)
        except ValueError:pass
        else:raise ValueError('REFUSED_P01_NATIVE_MISSING_SCOPE_FALSIFIER_'+name)
        need(bad==snapshot,'PURE_FALSIFIER_DOES_NOT_MUTATE_INPUT');tested.append(name)
    need((state if isinstance(state,dict) else state.__dict__)==before,'ACTUAL_ORIGINAL_STATE_NOT_MUTATED')
    return dict(schema='research.p01-native-scope-refusal-falsifiers/1',status='ALL_SCOPED_FALSIFIERS_REFUSED',
        tested=tested,financial_authority=False,actual_original_state_unchanged=True)


def source_proof(binding,observer,reused,contract):
    need(len(observer.records)==1,'ONE_ACTUAL_POST_ALL11_SOURCE_OBSERVATION')
    return dict(schema='research.p01-native-closing-source-proof/1',records=observer.records,
        source_clock_qualification=specification()['source_clock_qualification'],
        reused_action_qualification=reused,source_contract=contract,source_financial_files_unchanged=True)


def one_session_args(book,parent):
    args=arguments(book,True,MAXIMUM);args[args.index('--policy')+1]=parent['base']['policy']
    return args


def qualify(old,out):
    from research.pooled_vacancy_funding import runtime,backtest,journal
    cp,wanted,pre=prepare(old,out);proof=out/'proof';proof.mkdir()
    with historical_epoch(old,out,specification()) as binding:
        reused=reused_qualification(old,binding.source_map);contract=source_contract(binding)
        zero=zero_resume(old,out,binding)
        initial=runtime.restore(cp['run'],policy=cp['base']['policy'],input_sha256=INPUT)
        save(proof/'scope-refusal-falsifiers.json',scope_falsifiers(initial.state))
        rows=source_rows();observer=SourceObserver(binding,rows);guard=NativeGuard(out/'book',reused=reused)
        with observer,guard,Execution('FAST',signal_closes=1):
            code=backtest.main(one_session_args(out/'book',cp)+binding.source_args)
        need(code==0 and [r['session'] for r in guard.observed]==wanted,'ACTUAL_ONE_COMPLETE_CANONICAL_SESSION')
        final=journal.read_checkpoint(out/'book/checkpoint.json.gz')
        need(final['completed']==628 and final['source_cursor']==END
             and final['repairs']==cp['repairs'] and final['base']==cp['base']
             and final['run']['input_sha256']==INPUT,'ACTUAL_ONE_DAY_QUALIFIER_SAME_EPOCH_INPUT')
        run=runtime.restore(final['run'],policy=final['base']['policy'],input_sha256=INPUT)
        need(runtime.checkpoint(run)==final['run'],'ENTIRE_QUALIFIER_CHECKPOINT_CANONICAL_RESTORE')
        save(proof/'native-scope-source-proof.json',source_proof(binding,observer,reused,contract))
        with gzip.open(proof/'actual-one-session-component.json.gz','wb') as stream:
            stream.write(encoded(dict(actual_components=guard.components,action_checks=guard.action_checks,
                pre_event_checkpoints=guard.pre_events,inherited_native_scope_checks=guard.native_checks,
                native_seam_scope_checks=guard.native_seam_checks,closing_proofs=guard.closing_proofs,
                qualifier_checkpoint=final,financial_authority=False,qualification_state_adopted=False)))
        for name in ('zero-session-resume.json','native-resume-preflight.json'):
            shutil.copyfile(out/name,proof/name)
        save(proof/'qualification-summary.json',dict(status='OWN627_NATIVE_EPOCH_AND_ONE_SESSION_QUALIFIED',
            financial_authority=False,financial_predecessor_authorized=False,component_transitions=1,
            qualified_through=END,epoch_zero_outer_sha256=cp['sha256'],original_input_sha256=INPUT,
            original_inputs=11,source_epoch_boundary_reemitted=False,input_boundary_reemitted=False,
            actual_role_and_full_state_checks=guard.observed,reused_action_qualification=reused,
            target_independence_qualified=True,held_target_holding_qualified=True,
            processing_endpoint=END,maximum_transitions=MAXIMUM,qualification_state_adopted=False))


def economic(old,out):
    from research.pooled_vacancy_funding import backtest,journal
    from p01_native_resume_export import qualification
    cp,wanted,pre=prepare(old,out)
    qualified=json.loads(Path('/evidence/proof/qualification-summary.json').read_bytes());qualification(qualified)
    with historical_epoch(old,out,specification()) as binding:
        reused=reused_qualification(old,binding.source_map);contract=source_contract(binding)
        need(reused==qualified['reused_action_qualification'],'EXACT_SAME_ADMITTED_ACTION_COMPONENT_METADATA')
        zero=zero_resume(old,out,binding)
        need(zero==json.loads(Path('/evidence/proof/zero-session-resume.json').read_bytes()),
             'FRESH_ORIGINAL_OWN627_REPRODUCES_ENTIRE_QUALIFIED_ZERO_RESUME')
        rows=source_rows();observer=SourceObserver(binding,rows)
        guard=NativeGuard(out/'book',qualified=qualified['actual_role_and_full_state_checks'],reused=reused)
        observation=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
        with observer,guard,observation,Execution('FAST',signal_closes=1) as execution:
            code=backtest.main(one_session_args(out/'book',cp)+binding.source_args)
        # Refusal evidence may contain no completed source observation. It is
        # preserved exactly rather than manufacturing the successful proof.
        save(out/'native-scope-source-proof.json',dict(schema='research.p01-native-closing-source-proof/1',
            records=observer.records,source_clock_qualification=specification()['source_clock_qualification'],
            reused_action_qualification=reused,source_contract=contract,source_financial_files_unchanged=True))
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observation.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',pre))
    current=require_strict_checkpoint(journal.read_checkpoint(out/'book/checkpoint.json.gz'))
    committed=lambda records:[r for r in records if r['session']<=current['source_cursor']]
    with gzip.open(out/'actual-financial-first-one-component.json.gz','wb') as stream:
        stream.write(encoded(dict(actual_components=committed(guard.components),attempted_components=guard.components,
            financial_authority=False,qualification_state_adopted=False)))
    complete=code==0 and current['source_cursor']==END and current['completed']==628
    save(out/'native-resume-outcome.json',dict(status='COMPLETE_NATIVE_RESUME_SEGMENT_PENDING_REVIEW' if complete else
        'NATIVE_RESUME_PARTIAL_OR_REFUSAL_PRESERVED',canonical_return_code=code,source_cursor=current['source_cursor'],
        completed=current['completed'],new_transitions=current['completed']-627,processing_endpoint=END,
        maximum_transitions=MAXIMUM,original_own627_resumed_fresh=True,qualification_state_adopted=False,
        original_input_sha256=INPUT,original_inputs=11,
        actual_role_and_full_state_checks=committed(guard.observed),attempted_role_and_full_state_checks=guard.observed,
        actual_action_scope_checks=committed(guard.action_checks),attempted_action_scope_checks=guard.action_checks,
        actual_native_seam_scope_checks=committed(guard.native_seam_checks),attempted_native_seam_scope_checks=guard.native_seam_checks,
        actual_inherited_native_scope_guards=committed(guard.native_checks),attempted_inherited_native_scope_guards=guard.native_checks,
        actual_closing_sensor_proofs=committed(guard.closing_proofs),attempted_closing_sensor_proofs=guard.closing_proofs,
        actual_pre_event_checkpoints=guard.pre_events,source_epoch_boundary_reemitted=False,input_boundary_reemitted=False,
        full_measurement_end='2026-07-31',production_contacted=False))


def main(args):
    hosted();need(json.loads(args.spec.read_bytes())==specification(),'EXACT_MOUNTED_OWN627_SPEC')
    if args.mode=='qualify':qualify(Path('/old'),Path('/out'))
    elif args.mode=='economic':economic(Path('/old'),Path('/out'))
    else:
        from p01_native_resume_review import review
        review(specification(),Path('/out'),Path('/evidence'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=('qualify','economic','review'),required=True)
    parser.add_argument('--spec',type=Path,required=True);main(parser.parse_args())
