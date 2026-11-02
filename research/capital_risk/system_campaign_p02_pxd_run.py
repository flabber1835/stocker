"""Exact OWN36 suffix through the unchanged canonical financial driver."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
from types import FunctionType,SimpleNamespace

from full_system_core import hosted
from full_system_benchmark import need,save
from system_campaign_facts import sha
from system_campaign_pxd_financial_body import function,ECONOMIC,REVIEW,REVIEW_KEYWORDS
from system_campaign_pxd_financial_parent import reference,PATH as REFERENCE_PATH
from system_campaign_pxd_facts import build,hydrate,expected_repair,evidence,PRIVATE,OVERLAY
from system_campaign_pxd_basis import basis,validate_all,require_exact_delta,validate_closing
from system_campaign_pxd_scope import InputCodec,SCHEMA
from system_campaign_pxd_gate import qualify
from system_campaign_pxd_review import review as review_pxd
from system_campaign_pxd_materialize import descriptor_for,materialized
from system_campaign_close_scope import InputCodec as CloseCodec,SCHEMA as CLOSE
from system_campaign_close_facts import expected_repair as close_body,evidence as close_evidence
from system_campaign_phase_timing import PhaseTiming
from system_campaign_q4_cash_context import CashRegistry

HERE=Path(__file__).resolve().parent


def exact_copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():need(target.read_bytes()==source.read_bytes(),'PXD_OLD_ARCHIVE_COLLISION_EXACT_BYTES')
    else:shutil.copyfile(source,target)


def preserve_all_checkpoints(old,out):
    hosted()
    from research.pooled_vacancy_funding import journal
    selected=journal.read_checkpoint(old/'book/checkpoint.json.gz')
    records=[]
    for folder in ('pre-event','month-end','predecessor-checkpoints'):
        for source in (old/'book'/folder).glob('*.json.gz'):
            cp=journal.read_checkpoint(source)
            committed=(cp['completed']<=selected['completed'] and cp['source_cursor']<=selected['source_cursor']
                and cp['journals'].keys()==selected['journals'].keys()
                and all(value['bytes']<=selected['journals'][name]['bytes'] for name,value in cp['journals'].items()))
            destination=(out/'book'/folder/source.name if committed else
                         out/'lineage/original-uncommitted-checkpoints'/folder/source.name)
            exact_copy(source,destination)
            records.append(dict(source=source.relative_to(old).as_posix(),
                destination=destination.relative_to(out).as_posix(),file_sha256=sha(source.read_bytes()),
                outer_sha256=cp['sha256'],committed_through_selected_parent=committed))
    need(records,'PXD_ALL_ACTUAL_OLD_CHECKPOINT_ARCHIVES_PRESERVED')
    save(out/'pxd-old-checkpoint-preservation.json',dict(files=len(records),records=records,all_exact_gzip_bytes=True,
        no_old_checkpoint_relabelled=True,production_contacted=False))


def review_archived_checkpoints(root,old,out):
    hosted()
    from research.pooled_vacancy_funding import journal,runtime,backtest
    from system_campaign_readonly import reader
    proof=json.loads((root/'pxd-old-checkpoint-preservation.json').read_bytes())
    handle=reader(journal.Journal,old/'book',journal.STREAMS)
    try:
        for entry in proof['records']:
            raw=(root/entry['destination']).read_bytes()
            need(raw==(old/entry['source']).read_bytes() and sha(raw)==entry['file_sha256'],
                 'PXD_REVIEW_EVERY_OLD_GZIP_CHECKPOINT_EXACT')
            cp=journal.read_checkpoint(root/entry['destination'])
            need(cp['sha256']==entry['outer_sha256'],'PXD_REVIEW_ORIGINAL_CHECKPOINT_IDENTITY')
            handle.verify(cp['journals'])
            restored=runtime.restore(cp['run'],policy=cp['base']['policy'],
                                     input_sha256=backtest.input_hash(cp['base'],cp['repairs']))
            need(runtime.checkpoint(restored)==cp['run'],'PXD_REVIEW_EVERY_OLD_CANONICAL_STATE_ROUNDTRIP')
    finally:handle.close()
    save(out/'pxd-retained-checkpoint-lineage-review.json',dict(files=proof['files'],
        all_old_gzip_bytes_and_original_prefixes_verified=True,
        all_canonical_old_states_verified=True,no_uncommitted_predecessor_selected=True,production_contacted=False))


def preflight(spec,old,out,*,before):
    hosted()
    from system_campaign_factual_run import preflight as original
    cp=original(spec,old,out,before=before)
    for name in ('hydrated-twnk-close-fact.json','twnk-guarded-close-input.json'):
        exact_copy(old/name,out/name)
    return cp


def cash_boundary(root,old,request):
    hosted()
    from research.pooled_vacancy_funding import journal
    raw=(HERE/'system-campaign-p02-q4-cash-predecessor.json').read_bytes()
    need(sha(raw)==request['retained_cash_original_spec_sha256'],'PXD_ORIGINAL_Q4_PUBLIC_SPEC_NOT_LATEST_PARENT')
    spec=json.loads(raw);path=root/'book/predecessor-checkpoints'/(spec['outer_sha256']+'.json.gz')
    need(sha(path.read_bytes())==spec['selected_file']['sha256'],'PXD_ORIGINAL_Q4_ENTITLEMENT_GZIP')
    cp=journal.read_checkpoint(path)
    need(cp['sha256']==spec['outer_sha256'] and cp['source_cursor']=='2023-09-29'
         and cp['completed']==1446 and len(cp['repairs'])==34,'PXD_ORIGINAL_Q4_ENTITLEMENT_BOUNDARY')
    return cp


def preserve_cash_boundary(old,out,request):
    cp=cash_boundary(old,old,request)
    name=Path('book/predecessor-checkpoints')/(cp['sha256']+'.json.gz')
    exact_copy(old/name,out/name)
    return cp


@contextmanager
def retained_closing(root,cp):
    descriptor=descriptor_for(root,cp,CLOSE)
    codec=CloseCodec(close_body(root,descriptor['predecessor_checkpoint_sha256']),close_evidence(root))
    with materialized(codec,root,descriptor,schema=CLOSE):yield codec


def economic(out,old,spec,request,timing):
    hosted()
    import system_campaign_p02_close_run as original
    from research.pooled_vacancy_funding import journal
    parent=journal.read_checkpoint(old/spec['selected_checkpoint'])
    need(parent['sha256']==spec['outer_sha256'] and len(parent['repairs'])==36,
         'PXD_FINANCIAL_ORIGINAL_APRIL36_ONLY_NEVER_QUALIFICATION_COPY')
    namespace=dict(vars(original),prior=SimpleNamespace(**{**vars(original.prior),'preflight':preflight}),
        build=build,hydrate=hydrate,expected_repair=expected_repair,close_evidence=evidence,
        CloseCodec=InputCodec,OVERLAY=OVERLAY,PRIVATE=PRIVATE,qualify=qualify,basis=basis,
        validate_all=validate_all,preserve_cash_boundary=preserve_cash_boundary,
        preserve_all_checkpoints=preserve_all_checkpoints)
    with retained_closing(old,parent) as closing:
        try:
            function('system_campaign_p02_close_run.py','economic',ECONOMIC,namespace,
                insert_after='actual_packets_and_own_unheld_close_gate')(out,old,spec,request,timing)
        finally:
            if closing.guard.failure is not None:save(out/'retained-close-position-refusal.json',closing.guard.failure)
    current=journal.read_checkpoint(out/'book/checkpoint.json.gz')
    need(current['repairs'][-1]['sha256']==request['qualified_pxd_overlay_sha256'],
         'PXD_FINANCIAL_EXACT_ALREADY_QUALIFIED_INPUT_ADOPTED')


def review(out,root,old,spec,request,timing):
    hosted()
    import system_campaign_p02_close_run as original
    import system_campaign_close_review as retained_review
    from system_campaign_close_review_materialization import codec_factory
    from research.pooled_vacancy_funding import journal
    cp=journal.read_checkpoint(root/'book/checkpoint.json.gz')
    previous=journal.read_checkpoint(old/spec['selected_checkpoint'])
    report=dict(schema='research.pxd-financial-review-materialization/1',checkpoint_sha256=cp['sha256'],
                financial_sessions_advanced=0,production_contacted=False)
    if cp['repairs']==previous['repairs']:
        factory=InputCodec
    else:
        descriptor=descriptor_for(root,cp,SCHEMA)
        need(descriptor==cp['repairs'][-1],'PXD_REVIEW_LAST_DESCRIPTOR_EXPLICITLY_SCHEMA_VERIFIED')
        factory=codec_factory(InputCodec,root,cp,report)
    namespace=dict(vars(original),reference=reference,REFERENCE_PATH=REFERENCE_PATH,
        CloseCodec=factory,expected_repair=expected_repair,close_evidence=evidence,
        OVERLAY=OVERLAY,PRIVATE=PRIVATE,hydrate=hydrate,validate_all=validate_all,
        review_close=review_pxd,basis=basis,require_exact_delta=require_exact_delta,cash_boundary=cash_boundary)
    with retained_closing(root,cp):
        function('system_campaign_p02_close_run.py','review',REVIEW,namespace,
                 keywords=REVIEW_KEYWORDS)(out,root,old,spec,request,timing)
        fn=retained_review.review
        retained=FunctionType(fn.__code__,dict(fn.__globals__,validate=validate_closing),fn.__name__,fn.__defaults__)
        retained(root,cp,out/'retained-close-position-and-event-review.json')
        review_archived_checkpoints(root,old,out)
    need(journal.read_checkpoint(root/'book/checkpoint.json.gz')==cp,'PXD_REVIEW_STOPPED_BOOK_UNCHANGED')
    save(out/'pxd-review-materialization.json',report)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=('economic','review'),required=True)
    parser.add_argument('--spec',type=Path,required=True)
    parser.add_argument('--request',type=Path,required=True)
    args=parser.parse_args();spec=json.loads(args.spec.read_bytes());request=json.loads(args.request.read_bytes())
    with PhaseTiming(Path('/out'),args.mode) as timing,CashRegistry():
        if args.mode=='economic':economic(Path('/out'),Path('/old'),spec,request,timing)
        else:review(Path('/out'),Path('/evidence'),Path('/old'),spec,request,timing)
