"""Actual financial continuation of strict own P01; never discovery state."""
import argparse,gzip,json,shutil
from pathlib import Path
from full_system_core import hosted,arguments
from full_system_benchmark import need,save
from system_campaign_facts import sha,digest
from system_campaign_p01_discovery_parent import scope,reference
from system_campaign_p01_discovery_inputs import retained_inputs
from system_campaign_discovery_context import require_strict_checkpoint
from system_campaign_factual_run import (copy_repair_archive,correlation_seed,SeededObservation,
    preserve_tails,verify_correlation)
from system_campaign_acceleration import Execution

def preflight(old,out,spec):
    from research.pooled_vacancy_funding import journal,runtime,backtest
    from research.pooled_input_support.bundle import axis
    from system_campaign_readonly import reader
    cp=require_strict_checkpoint(journal.read_checkpoint(old/spec['selected_checkpoint']))
    dates=axis();all_dates=dates[dates.index(backtest.START)-425:dates.index(backtest.END)+1]
    backtest.validate_checkpoint(cp,cp['base'],all_dates)
    need(cp['sha256']==spec['outer_sha256'] and cp['run']['checkpoint_sha256']==spec['inner_sha256']
         and cp['run']['state_sha256']==spec['state_sha256'] and cp['run']['input_sha256']==spec['input_sha256']
         and cp['base']==spec['base'] and cp['base']['sources']==backtest.source_files()
         and cp['source_cursor']=='2019-08-30' and cp['completed']==419 and len(cp['repairs'])==8,
         'P01_ACCURATE_EXACT_OWN_STRICT419_SOURCE_INPUT_PARENT')
    run=runtime.restore(cp['run'],policy=cp['base']['policy'],input_sha256=backtest.input_hash(cp['base'],cp['repairs']))
    need(runtime.checkpoint(run)==cp['run'],'P01_ACCURATE_ACTUAL_CANONICAL_PARENT_ROUNDTRIP')
    stream=reader(journal.Journal,old/'book',journal.STREAMS)
    try:stream.verify(cp['journals'])
    finally:stream.close()
    wanted=[d for d in all_dates if cp['source_cursor']<d<='2019-09-27']
    need(len(wanted)==19 and wanted[0]=='2019-09-03' and wanted[-1]=='2019-09-27',
         'P01_ACCURATE_EXACT_NEXT19_FINANCIAL_DATES')
    book=out/'book';book.mkdir();preserved=book/'predecessor-checkpoints';preserved.mkdir()
    for p in (book/'checkpoint.json.gz',preserved/(cp['sha256']+'.json.gz')):
        shutil.copyfile(old/spec['selected_checkpoint'],p)
    shutil.copyfile(old/'book/identity.json',book/'identity.json');copy_repair_archive(old,book)
    original_cps=out/'lineage/original-checkpoints';original_cps.mkdir(parents=True)
    snapshots={}
    for p in (old/'book').rglob('*.json.gz'):
        relative=p.relative_to(old/'book');target=original_cps/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(p,target);snapshots[relative.as_posix()]=dict(bytes=p.stat().st_size,sha256=sha(p.read_bytes()))
    tails={}
    for name,c in cp['journals'].items():
        raw=(old/'book'/(name+'.jsonl')).read_bytes();(book/(name+'.jsonl')).write_bytes(raw)
        tail=raw[c['bytes']:];tails[name]=dict(bytes=len(tail),sha256=sha(tail))
        need(tails[name]==spec['full_client_admission']['unsent_tails_preserved'][name],
             'P01_ACCURATE_EXACT_OLD_UNSENT_TAIL')
    proof=dict(schema='research.p01-accurate-preflight/1',canonical_roundtrip=True,
        old_journal_commitments_verified=True,selected_outer_sha256=cp['sha256'],
        selected_inner_sha256=cp['run']['checkpoint_sha256'],tails_to_preserve=tails,
        original_checkpoint_files=snapshots,prior_full_accounting_admission_reused=reference(spec),
        financial_source_changed=False,input_conversion=False,new_origin=False,
        next_session=wanted[0],processing_endpoint=wanted[-1],maximum_transitions=len(wanted),
        original_full_measurement_end=backtest.END,diagnostic_state_adopted=False)
    save(out/'accurate-preflight.json',proof)
    return cp,proof

def economic(old,out,spec):
    from research.pooled_vacancy_funding import backtest,journal
    cp,proof=preflight(old,out,spec)
    with retained_inputs(old,cp,out):
        for name in ('hydrated-factual-catalog.json','hydrated-distribution-catalog.json'):
            shutil.copyfile(old/name,out/name)
        observation=SeededObservation(out/'correlation-inputs.jsonl.gz',correlation_seed(old,cp))
        args=arguments(out/'book',True,proof['maximum_transitions'])
        args[args.index('--policy')+1]=cp['base']['policy']
        with observation,Execution('FAST',signal_closes=1) as execution:
            code=backtest.main(args)
    save(out/'acceleration-proof.json',execution.proof());save(out/'correlation-capture-proof.json',observation.proof())
    save(out/'recovered-tail-proof.json',preserve_tails(out/'book',proof))
    current=require_strict_checkpoint(journal.read_checkpoint(out/'book/checkpoint.json.gz'))
    complete=(code==0 and current['source_cursor']=='2019-09-27' and current['completed']==438)
    save(out/'accurate-outcome.json',dict(status='COMPLETE_ACCURATE_SEGMENT_PENDING_REVIEW' if complete else 'ACCURATE_PARTIAL_OR_REFUSAL_PRESERVED',
        source_cursor=current['source_cursor'],completed=current['completed'],new_transitions=current['completed']-419,
        full_p01_comparison_complete=False,processing_endpoint='2019-09-27',original_measurement_end='2026-07-31',
        new_origin=False,financial_source_changed=False,repairs_unchanged=current['repairs']==cp['repairs'],
        source_input_identity_unchanged=current['base']==cp['base'] and current['run']['input_sha256']==cp['run']['input_sha256'],
        production_contacted=False))
    need(complete,'P01_ACCURATE_SEGMENT_REFUSED_OR_INCOMPLETE_PRESERVED')

def review(evidence,out,spec):
    from system_campaign_readonly import review as readonly_review
    readonly_review(evidence/'book',out/'canonical-accounting-review.json')
    proof=json.loads((evidence/'accurate-preflight.json').read_bytes())
    need(proof['selected_outer_sha256']==spec['outer_sha256'] and proof['diagnostic_state_adopted'] is False,
         'P01_ACCURATE_REVIEW_SAME_STRICT_PREDECESSOR')
    verify_correlation(evidence)
    tails=preserve_tails(evidence/'book',proof)
    for name,s in proof['original_checkpoint_files'].items():
        p=evidence/'lineage/original-checkpoints'/name
        need(p.stat().st_size==s['bytes'] and sha(p.read_bytes())==s['sha256'],
             'P01_ACCURATE_REVIEW_ALL_ORIGINAL_CHECKPOINT_BYTES_UNCHANGED')
    selected=evidence/'book/predecessor-checkpoints'/(spec['outer_sha256']+'.json.gz')
    need(sha(selected.read_bytes())==spec['selected_file']['sha256'],'P01_ACCURATE_REVIEW_EXACT_ORIGINAL_GZIP')
    save(out/'accurate-lineage-review.json',dict(schema='research.p01-accurate-lineage-review/1',
        actual_canonical_and_accounting_review='canonical-accounting-review.json',
        all_original_gzip_and_prefix_bytes_preserved=True,recovered_tails=tails,
        old_accounting_admission_reused=spec['full_client_admission'],
        financial_source_changed=False,new_origin=False,diagnostic_state_adopted=False,production_contacted=False))

def main(args):
    hosted();spec=scope(json.loads(args.spec.read_bytes()))
    if args.mode=='economic':economic(Path('/old'),Path('/out'),spec)
    else:review(Path('/evidence'),Path('/out'),spec)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('economic','review'),required=True)
    p.add_argument('--spec',type=Path,required=True);main(p.parse_args())
