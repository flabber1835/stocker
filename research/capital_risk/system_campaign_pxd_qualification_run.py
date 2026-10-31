"""Hosted PXD input-adoption qualification on a disposable copy; zero sessions."""
import argparse
from contextlib import ExitStack,contextmanager
import json
import os
from pathlib import Path
import shutil

from full_system_core import hosted,arguments
from full_system_benchmark import need,save
from system_campaign_facts import sha,digest
from system_campaign_close_scope import SCHEMA as CLOSE,InputCodec as CloseCodec
from system_campaign_close_facts import expected_repair as close_body,evidence as close_evidence
from system_campaign_outcome_input import InputCodec as OutcomeCodec
from system_campaign_outcome_facts import retained as outcome_retained,evidence as outcome_evidence
from system_campaign_q4_cash_context import CashRegistry
from system_campaign_pxd_scope import SCHEMA,InputCodec
from system_campaign_pxd_facts import build,expected_repair,evidence,PRIVATE,OVERLAY
from system_campaign_pxd_basis import basis,validate_all,require_exact_delta
from system_campaign_pxd_gate import qualify
from system_campaign_pxd_materialize import descriptor_for,materialized
from system_campaign_pxd_pause import PauseAfterAdoption
from system_campaign_phase_timing import PhaseTiming

OUTER='1f42c8345ac1df9cb1cbddff84cb2624a6fb9087ee5d3d663f528fd13ca341f0'


@contextmanager
def retained_contexts(root,checkpoint,scratch):
    hosted()
    import system_campaign_p02_close_run as original
    from research.pooled_vacancy_funding import backtest,journal
    prior=original.prior
    v1,spin,alder,_=prior.retained(checkpoint,root,scratch)
    znative=prior.retained_zogenix(root,scratch)
    native,_=prior.retained_abiomed(root,checkpoint,scratch)
    completion=prior.retained_completion(root,checkpoint)
    cnative=prior.hydrate_chinook(root,scratch)
    need((scratch/prior.CPRIVATE).read_bytes()==(root/prior.CPRIVATE).read_bytes(),
         'PXD_QUALIFICATION_EXACT_RETAINED_CHINOOK_WITNESS')
    model,bound=outcome_retained(root,checkpoint)
    need(model is not None and bound['session']=='2023-07-31',
         'PXD_QUALIFICATION_ORIGINAL_PROOF_BOUNDARY_NOT_REBOUND')
    boundary=journal.read_checkpoint(root/'book/predecessor-checkpoints'/(prior.OUTER+'.json.gz'))
    amendment=prior.FutureProjection(root,boundary)
    closing=descriptor_for(root,checkpoint,CLOSE)
    close=CloseCodec(close_body(root,closing['predecessor_checkpoint_sha256']),close_evidence(root))
    with ExitStack() as stack:
        for context in (v1,spin,alder,prior.idempotent_dispatch(alder),
            prior.ZogenixCodec(prior.zogenix_evidence(root),znative),prior.InputCodec(prior.evidence(root)),
            amendment,completion,prior.AbiomedCodec(prior.abiomed_evidence(root),native),
            prior.ChinookCodec(prior.chinook_evidence(root),cnative),OutcomeCodec(outcome_evidence(),bound)):
            stack.enter_context(context)
        stack.enter_context(materialized(close,root,closing,schema=CLOSE))
        objects=[backtest.load_repair(root/'book/repairs'/d['filename'],resume_session=d['resume_session'],
            predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']) for d in checkpoint['repairs']]
        need(len(objects)==36 and [o.sha256 for o in objects]==[d['sha256'] for d in checkpoint['repairs']],
             'PXD_QUALIFICATION_ALL36_ORIGINAL_CANONICAL_INPUTS_LOADED')
        yield dict(amendment=amendment,objects=objects,closing=close)


def prefixes_and_tails(before,after,checkpoint,adopted,event):
    checks={}
    for name,old in checkpoint['journals'].items():
        raw=(before/(name+'.jsonl')).read_bytes();current=(after/(name+'.jsonl')).read_bytes()
        need(len(raw)>=old['bytes'] and sha(raw[:old['bytes']])==old['prefix_sha256']
             and current[:old['bytes']]==raw[:old['bytes']],
             'PXD_QUALIFICATION_EVERY_ORIGINAL_COMMITTED_PREFIX_EXACT')
        extra=current[old['bytes']:]
        if name=='watch':need([json.loads(v) for v in extra.splitlines()]==[event],
                             'PXD_QUALIFICATION_ONLY_ACTUAL_INPUT_ADOPTION_WATCH')
        else:need(extra==b'','PXD_QUALIFICATION_NO_NEW_FINANCIAL_FORMATION_OR_MONTHLY_ROWS')
        tail=raw[old['bytes']:];new_files=[]
        if tail:
            old_names={p.name for p in before.glob('interrupted-'+name+'-*.jsonl')}
            new_files=[p for p in after.glob('interrupted-'+name+'-*.jsonl') if p.name not in old_names]
            need(len(new_files)==1 and new_files[0].read_bytes()==tail,
                 'PXD_QUALIFICATION_ACTUAL_JOURNAL_RECOVER_PRESERVED_EVERY_UNSENT_TAIL')
        checks[name]=dict(old_prefix=old,current_prefix=adopted['journals'][name],tail_bytes=len(tail),
            tail_sha256=sha(tail),actual_new_tail_paths=[p.name for p in new_files])
    return dict(status='ZERO_SESSION_ALL_PREFIXES_AND_RECOVERED_TAILS_VERIFIED',checks=checks)


def main(request_path):
    hosted()
    from research.pooled_vacancy_funding import backtest,journal,runtime
    request=json.loads(request_path.read_bytes())
    need(request['schema']=='research.p02-pxd-zero-session-qualification-request/1'
         and request['financial_replay_authorized'] is False
         and request['financial_resume_from_qualification_copy_authorized'] is False,
         'PXD_QUALIFICATION_ONLY_DECLARED_ZERO_SESSION_SCOPE')
    old,review=Path('/old'),Path('/evidence');work=Path('/out/work');proof=Path('/out/proof')
    work.mkdir();proof.mkdir(exist_ok=True)
    checkpoint=journal.read_checkpoint(old/'book/checkpoint.json.gz')
    need(checkpoint['sha256']==OUTER and checkpoint['source_cursor']=='2024-04-30'
         and checkpoint['completed']==1592 and len(checkpoint['repairs'])==36,
         'PXD_QUALIFICATION_EXACT_ORIGINAL_STOPPED_TARGET_NO_RESTART')
    candidate=work/'candidate';shutil.copytree(old,candidate,copy_function=shutil.copyfile)
    for path in candidate.rglob('*'):os.chmod(path,0o700 if path.is_dir() else 0o600)
    os.chmod(candidate,0o700);scratch=work/'contexts';scratch.mkdir()
    with PhaseTiming(proof,'pxd-zero-session-input-startup-qualification') as timing,CashRegistry():
        with retained_contexts(candidate,checkpoint,scratch) as contexts:
            old_hash,old_value=timing.call('seven_model_actual_input_basis',basis,candidate,checkpoint,
                                         amendment=contexts['amendment'])
            need(json.loads((review/'common-factual-and-uncertainty-basis.json').read_bytes())
                 ==dict(sha256=old_hash,value=old_value),
                 'PXD_QUALIFICATION_ALL_SEVEN_PRIOR_MODELS_MATCH_CORRECTED_REVIEW')
            _,parsed,path=timing.call('new_source_and_own_input_compiler',build,checkpoint,candidate,candidate)
            codec=InputCodec(expected_repair(candidate,checkpoint['run']['checkpoint_sha256']),evidence(candidate))
            with codec:
                loaded=backtest.load_repair(path,resume_session=checkpoint['source_cursor'],
                    predecessor_checkpoint_sha256=checkpoint['run']['checkpoint_sha256'])
                need(loaded.sha256==parsed.sha256,'PXD_QUALIFICATION_ACTUAL_TYPED_AND_NESTED_INPUT')
                old_financial_request=json.loads((old/'request.json').read_bytes())
                timing.call('actual_packets_and_unheld_operation',qualify,candidate,checkpoint,loaded,
                            contexts['objects'],old_financial_request)
                args=arguments(candidate/'book',True)
                args[args.index('--policy')+1]=checkpoint['base']['policy']
                pause=PauseAfterAdoption(checkpoint,candidate/'book/checkpoint.json.gz',loaded.sha256,
                                         loaded.earliest_affected_session)
                with pause:
                    code=timing.call('canonical_zero_session_resume_startup',backtest.main,
                                    args+['--repair-overlay',str(path)])
                need(code==0,'PXD_QUALIFICATION_CANONICAL_STARTUP_PAUSE_SUCCEEDED')
                zero=pause.proof();current=journal.read_checkpoint(candidate/'book/checkpoint.json.gz')
                need(current==pause.saved and current['sha256']==zero['qualification_checkpoint_sha256'],
                     'PXD_QUALIFICATION_ACTUAL_PERSISTED_STARTUP_CHECKPOINT')
                restored=runtime.restore(current['run'],policy=current['base']['policy'],
                    input_sha256=backtest.input_hash(current['base'],current['repairs']))
                need(runtime.checkpoint(restored)==current['run'],'PXD_QUALIFICATION_EIGHT_INPUT_CANONICAL_ROUNDTRIP')
                handle=journal.Journal(candidate/'book',resume=True)
                try:handle.verify(current['journals'])
                finally:handle.close()
                inputs,_=validate_all(candidate,current)
                need(len(inputs)==8,'PXD_QUALIFICATION_ALL_EIGHT_ACTUAL_TYPED_PARSERS')
                new_hash,new_value=basis(candidate,current,amendment=contexts['amendment'])
                require_exact_delta(old_value,new_value,loaded,candidate)
                tails=prefixes_and_tails(old/'book',candidate/'book',checkpoint,current,pause.event)
                need((candidate/'uncertainty-certificate.jsonl').read_bytes()
                     ==(old/'uncertainty-certificate.jsonl').read_bytes(),
                     'PXD_QUALIFICATION_NO_FINANCIAL_SENSOR_OR_UNSENT_CERTIFICATE_CHANGE')
                save(proof/'zero-session-startup-proof.json',zero)
                save(proof/'prefix-and-tail-proof.json',tails)
                save(proof/'common-factual-and-uncertainty-basis.json',dict(sha256=new_hash,value=new_value))
                for name in (PRIVATE,OVERLAY,'pxd-canonical-qualification.json','pxd-collision-preflight.json'):
                    shutil.copyfile(candidate/name,proof/name)
                shutil.copyfile(candidate/'book/checkpoint.json.gz',proof/'qualification-checkpoint.json.gz')
                save(proof/'qualification-summary.json',dict(status='PXD_ZERO_SESSION_STARTUP_CANONICALLY_QUALIFIED',
                    source_checkpoint_sha256=OUTER,qualification_checkpoint_sha256=current['sha256'],
                    source_session='2024-04-30',completed=1592,typed_inputs=8,
                    actual_new_input_sha256=loaded.sha256,common_basis_sha256=new_hash,
                    canonical_backtest_startup_invoked=True,financial_sessions_advanced=0,
                    actual_canonical_roundtrip=True,actual_all_prefixes_and_tails_verified=True,
                    all_seven_prior_models_unchanged=True,financial_admission=False,
                    financial_resume_from_this_copy_authorized=False,production_contacted=False))
    need(journal.read_checkpoint(old/'book/checkpoint.json.gz')==checkpoint,
         'PXD_QUALIFICATION_ORIGINAL_READONLY_BOOK_UNCHANGED')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True)
    main(parser.parse_args().request)
