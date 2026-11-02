"""Hosted registered-input qualification, fresh own438 finance, and suffix review."""
import argparse
from copy import deepcopy
from dataclasses import replace
import gzip
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

from full_system_core import hosted,arguments
from full_system_benchmark import need,save
from system_campaign_facts import sha,digest
from system_campaign_discovery_context import material,require_strict_checkpoint
from system_campaign_p01_discovery_inputs import retained_inputs
from system_campaign_factual_run import copy_repair_archive,correlation_seed,SeededObservation,preserve_tails,verify_correlation
from system_campaign_acceleration import Execution
from system_campaign_pxd_pause import PauseAfterAdoption,adoption
from p01_action_clock_parent import specification,reference,SPEC
from p01_clock_input_codec import (SCHEMA,FACTS,InputCodec,RoleGuard,document,parse,require_roles,
    SID,OLD,NEW,PARENT,INNER,STATE,INPUT,NEXT_STATES)

END='2019-11-19'
MAXIMUM=37


def native():
    from research.pooled_input_support.inputs import load_actions
    values=[t for t in load_actions(Path('/frozen/bundle')).terminal.get(OLD,()) if t.security_id==SID]
    need(len(values)==1,'P01_CLOCK_INPUT_ONE_ACTUAL_NATIVE_TERM');return values[0]


def preflight(old,out,spec):
    from research.pooled_vacancy_funding import journal,runtime,backtest
    from research.pooled_input_support.bundle import axis
    from system_campaign_readonly import reader
    cp=require_strict_checkpoint(journal.read_checkpoint(old/spec['selected_checkpoint']))
    full=axis();dates=full[full.index(backtest.START)-425:full.index(backtest.END)+1]
    backtest.validate_checkpoint(cp,cp['base'],dates)
    need(cp['sha256']==PARENT and cp['run']['checkpoint_sha256']==INNER
         and cp['run']['state_sha256']==STATE and cp['run']['input_sha256']==INPUT
         and cp['base']==spec['base'] and cp['base']['sources']==backtest.source_files()
         and cp['completed']==438 and cp['source_cursor']=='2019-09-27' and cp['repairs']==spec['repairs'],
         'P01_CLOCK_INPUT_EXACT_OWN438_SOURCE_EIGHT_INPUTS')
    run=runtime.restore(cp['run'],policy=cp['base']['policy'],input_sha256=backtest.input_hash(cp['base'],cp['repairs']))
    need(runtime.checkpoint(run)==cp['run'],'P01_CLOCK_INPUT_FULL_PARENT_CANONICAL_RESTORE')
    stream=reader(journal.Journal,old/'book',journal.STREAMS)
    try:stream.verify(cp['journals'])
    finally:stream.close()
    days=[d for d in dates if cp['source_cursor']<d<=END]
    need(len(days)==MAXIMUM and days[:2]==[OLD,NEW] and days[-1]==END,'P01_CLOCK_INPUT_EXACT_NEXT37_SESSION_AXIS')
    book=out/'book';book.mkdir(parents=True);(book/'predecessor-checkpoints').mkdir()
    for dest in (book/'checkpoint.json.gz',book/'predecessor-checkpoints'/(PARENT+'.json.gz')):
        shutil.copyfile(old/spec['selected_checkpoint'],dest)
    shutil.copyfile(old/'book/identity.json',book/'identity.json');copy_repair_archive(old,book)
    originals={}
    for base in ('book','lineage'):
        for path in (old/base).rglob('*.json.gz'):
            rel=path.relative_to(old);dest=out/'lineage/original-checkpoints'/rel
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
            originals[rel.as_posix()]=dict(bytes=path.stat().st_size,sha256=sha(path.read_bytes()))
    tails={}
    for name,commit in cp['journals'].items():
        raw=(old/f'book/{name}.jsonl').read_bytes();(book/(name+'.jsonl')).write_bytes(raw)
        tail=raw[commit['bytes']:];tails[name]=dict(bytes=len(tail),sha256=sha(tail))
        need(not tail,'P01_CLOCK_INPUT_ADMITTED_OWN438_HAS_NO_CURRENT_TAIL')
    proof=dict(schema='research.p01-economic-clock-preflight/1',parent_reference=reference(spec),
        own438_exact_restore=True,old_accounting_admission_reused=True,old_accounting_replayed=False,
        tails_to_preserve=tails,original_checkpoint_files=originals,source515_unchanged=True,
        original_eight_inputs_unchanged=True,next_session=OLD,processing_endpoint=END,maximum_transitions=MAXIMUM)
    save(out/'clock-input-preflight.json',proof)
    return cp,proof


def overlay(out):
    path=out/'clock-input.json';save(path,document())
    loaded=parse(path,resume_session='2019-09-27',predecessor_checkpoint_sha256=INNER)
    return path,loaded


def input_objects(root,cp,backtest):
    objects=[backtest.load_repair(root/'book/repairs'/d['filename'],resume_session=d['resume_session'],
        predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']) for d in cp['repairs']]
    need([o.sha256 for o in objects]==[d['sha256'] for d in cp['repairs']],
         'P01_CLOCK_INPUT_ALL_RETAINED_TYPED_INPUTS_EXACT')
    return objects


def expect_refusal(call,label):
    try:call()
    except ValueError:return
    raise ValueError('REFUSED_P01_CLOCK_INPUT_MISSING_'+label)


def qualify(old,out,spec):
    from research.pooled_vacancy_funding import journal,backtest,runtime
    from system_campaign_discovery_replay import source_iterator
    work=out/'work';work.mkdir();proof=out/'proof';proof.mkdir()
    cp,pre=preflight(old,work,spec)
    path,loaded=overlay(work)
    codec=InputCodec(native())
    with retained_inputs(old,cp,work/'contexts'),codec:
        objects=input_objects(old,cp,backtest);need(len(objects)==8,'P01_CLOCK_INPUT_ORIGINAL_EIGHT_ONLY')
        typed=backtest.load_repair(path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=INNER)
        need(typed.sha256==loaded.sha256,'P01_CLOCK_INPUT_ACTUAL_REGISTERED_NINTH_SCHEMA')
        pause=PauseAfterAdoption(cp,work/'book/checkpoint.json.gz',typed.sha256,OLD)
        args=arguments(work/'book',True);args[args.index('--policy')+1]=cp['base']['policy']
        with pause:
            code=backtest.main(args+['--repair-overlay',str(path)])
        need(code==0,'P01_CLOCK_INPUT_ZERO_SESSION_CANONICAL_STARTUP')
        zero=pause.proof();current=journal.read_checkpoint(work/'book/checkpoint.json.gz')
        event=adoption(current,cp,typed.sha256,OLD)
        prefix={}
        for name,c in cp['journals'].items():
            before=(old/f'book/{name}.jsonl').read_bytes();after=(work/f'book/{name}.jsonl').read_bytes()
            need(after[:c['bytes']]==before,'P01_CLOCK_INPUT_ZERO_SESSION_OLD_PREFIX_EXACT')
            extra=after[c['bytes']:]
            need([json.loads(v) for v in extra.splitlines()]==([event] if name=='watch' else []),
                 'P01_CLOCK_INPUT_ZERO_SESSION_ONLY_INPUT_BOUNDARY_EVENT')
            prefix[name]=dict(old_commitment=c,new_commitment=current['journals'][name])
        need(current['run']['state_sha256']==STATE and len(current['repairs'])==9,
             'P01_CLOCK_INPUT_ZERO_SESSION_STATE_UNCHANGED_NINTH_DESCRIPTOR')
        restored=runtime.restore(current['run'],policy=current['base']['policy'],
            input_sha256=backtest.input_hash(current['base'],current['repairs']))
        need(runtime.checkpoint(restored)==current['run'],'P01_CLOCK_INPUT_NINE_INPUT_CANONICAL_ROUNDTRIP')
        run,buffer,packets,repaired,wanted=source_iterator(current,work)
        observed=[];guard=RoleGuard()
        with guard,Execution('FAST',signal_closes=1):
            for day in (OLD,NEW):
                raw=next(packets);need(raw.day==day,'P01_CLOCK_INPUT_COMPONENT_SOURCE_AXIS')
                # Actual codec falsifiers act on raw packets before any canonical transition.
                if day==OLD:
                    expect_refusal(lambda:codec.apply(replace(raw,terminal=()),typed),'SOURCE_PREIMAGE_GUARD')
                    altered=replace(codec.native,cash_per_share=0.0)
                    expect_refusal(lambda:codec.apply(replace(raw,terminal=(altered,)),typed),'CHANGED_NATIVE_GUARD')
                    unknown=deepcopy(typed)
                    expect_refusal(lambda:codec.apply(raw,unknown),'REGISTERED_INSTANCE_GUARD')
                else:
                    expect_refusal(lambda:codec.apply(replace(raw,terminal=(replace(codec.native,session=NEW),)),typed),
                                   'EFFECTIVE_DAY_COLLISION_GUARD')
                packet=repaired(raw);buffer.append(packet)
                published=buffer.prepare(run.state,run.state.data_version+1,formation=False)
                previous=runtime.checkpoint(run);run=runtime.advance(run,published)
                actual=runtime.checkpoint(run)
                observed.append(dict(session=day,prior_state_sha256=previous['state_sha256'],
                    publication=material(published),checkpoint=actual))
        need([v['session'] for v in guard.observed]==[OLD,NEW],'P01_CLOCK_INPUT_BOTH_ACTUAL_ROLE_AND_STATE_GATES')
    save(proof/'clock-input.json',document())
    save(proof/'zero-session-startup-proof.json',zero)
    save(proof/'prefix-and-tail-proof.json',dict(all_original_prefix_bytes_preserved=True,checks=prefix))
    with gzip.open(proof/'actual-codec-component-path.json.gz','wb') as stream:
        stream.write((json.dumps(observed,sort_keys=True,allow_nan=False)+'\n').encode())
    save(proof/'qualification-input-checkpoint.json',dict(schema='research.p01-nonfinancial-input-adoption-proof/1',
        financial_authority=False,financial_predecessor_authorized=False,checkpoint=current))
    save(proof/'qualification-summary.json',dict(status='REGISTERED_CLOCK_INPUT_CANONICALLY_QUALIFIED',
        financial_authority=False,financial_predecessor_authorized=False,source_outer_sha256=PARENT,
        source515_unchanged=True,old_eight_inputs_unchanged=True,typed_inputs=9,
        new_input_document_sha256=loaded.sha256,successor_input_sha256=current['run']['input_sha256'],
        zero_financial_sessions_in_startup=True,component_transitions=2,role_and_full_state_checks=guard.observed,
        actual_source_preimage_collision_and_instance_falsifiers=True,original_worker_failure_rewritten=False))


def economic(old,out,spec):
    from research.pooled_vacancy_funding import backtest,journal
    cp,proof=preflight(old,out,spec);path,loaded=overlay(out)
    codec=InputCodec(native());guard=RoleGuard()
    with retained_inputs(old,cp,out/'contexts'),codec,guard:
        input_objects(old,cp,backtest)
        for name in ('hydrated-factual-catalog.json','hydrated-distribution-catalog.json'):
            shutil.copyfile(old/name,out/name)
        observation=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
        args=arguments(out/'book',True,MAXIMUM);args[args.index('--policy')+1]=cp['base']['policy']
        with observation,Execution('FAST',signal_closes=1) as execution:
            code=backtest.main(args+['--repair-overlay',str(path)])
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observation.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',proof))
    current=require_strict_checkpoint(journal.read_checkpoint(out/'book/checkpoint.json.gz'))
    expected=dict(filename=loaded.sha256+'.json',sha256=loaded.sha256,resume_session=cp['source_cursor'],
        predecessor_checkpoint_sha256=INNER)
    need(current['repairs']==[*cp['repairs'],expected] and current['base']==cp['base'],
         'P01_CLOCK_INPUT_EXACT_NINTH_INPUT_IDENTITY_NO_SOURCE_CONVERSION')
    complete=code==0 and current['source_cursor']==END and current['completed']==475
    save(out/'clock-input-outcome.json',dict(status='COMPLETE_CLOCK_INPUT_FINANCIAL_SEGMENT_PENDING_REVIEW' if complete
        else 'CLOCK_INPUT_PARTIAL_OR_REFUSAL_PRESERVED',canonical_return_code=code,
        source_cursor=current['source_cursor'],completed=current['completed'],new_transitions=current['completed']-438,
        processing_endpoint=END,full_measurement_end='2026-07-31',full_p01_comparison_complete=False,
        source515_unchanged=True,own438_resumed_fresh=True,qualification_state_adopted=False,
        new_input_document_sha256=loaded.sha256,actual_role_and_full_state_checks=guard.observed,
        actual_registered_packet_applications=codec.applied,production_contacted=False))
    need(complete,'P01_CLOCK_INPUT_FINANCIAL_PARTIAL_OR_REFUSAL_PRESERVED')


def main(args):
    hosted();spec=specification()
    need(json.loads(args.spec.read_bytes())==spec,'P01_CLOCK_INPUT_EXACT_MOUNTED_SPEC')
    if args.mode=='qualify':qualify(Path('/old'),Path('/out'),spec)
    elif args.mode=='economic':economic(Path('/old'),Path('/out'),spec)
    else:
        from p01_clock_input_review import review
        review(Path('/old'),Path('/evidence'),Path('/out'),spec)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('qualify','economic','review'),required=True)
    p.add_argument('--spec',type=Path,required=True);main(p.parse_args())
