"""Exact own39 LBPH suffix; original canonical financial call unchanged."""
import argparse
import json
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import need
from system_campaign_pxd_financial_body import function
from system_campaign_lbph_cash_parent import reference,PATH
from system_campaign_lbph_cash_context import CashRegistry
from system_campaign_lbph_cash_facts import build,hydrate,validate,qualify,factual_delta,CATALOG
from system_campaign_q4_cash_review import actual_cash
from system_campaign_phase_timing import PhaseTiming
import system_campaign_p02_unconsumed_cash_run as retained
import system_campaign_p02_morf_cash_run as admitted

ECONOMIC={
    41200949097:41246680594,'2023-09-29':'2024-10-31','2023-10-04':'2024-11-29',
    1446:1720,34:39,992:1266,
    'RETAINED_SIX_MODEL_Q4_CASH_BATCH_SUFFIX':'RETAINED_EIGHT_MODEL_LBPH_PREOPEN_CASH_SUFFIX',
    'q4-cash-constructor-admission.json':'lbph-cash-constructor-admission.json',
    'q4-cash-economic-outcome.json':'lbph-cash-economic-outcome.json',
    'Q4_CASH_EXACT_OWN_34_INPUT_SEPTEMBER_PARENT':'LBPH_EXACT_OWN39_OCTOBER_FINANCIAL_PARENT',
    'Q4_CASH_ALL_SIX_ORIGINAL_MODEL_SEMANTICS_UNCHANGED':'LBPH_ALL_EIGHT_ORIGINAL_MODELS_UNCHANGED',
    'Q4_CASH_EXACT_OWN_SUCCESSOR_ALL34_INPUTS_AND_ONE_FACTUAL_CASH_CALENDAR':'LBPH_EXACT_OWN39_AND_ONE_ORDINARY_CASH_FACT',
    'Q4_CASH_FINANCIAL_REFUSAL_PREFIX_PRESERVED':'LBPH_FINANCIAL_REFUSAL_PREFIX_PRESERVED',
}
REVIEW={
    'q4-cash-constructor-admission.json':'lbph-cash-constructor-admission.json',
    'q4-2023-cash-calendar-overlay.json':'lbph-preopen-cash-overlay.json',
    'q4-cash-actual-entitlements-review.json':'lbph-cash-actual-entitlements-review.json',
    'q4-cash-lineage-review.json':'lbph-cash-lineage-review.json',
}
REVIEW_KEYS={'all34_old_descriptors_preserved':'all39_old_descriptors_preserved',
             'all_six_original_model_semantics_unchanged':'all_eight_original_model_semantics_unchanged'}
MORF_GATES=('morf-cash-packet-qualification.json','morf-cash-canonical-qualification.json',
            'morf-quote-coexistence-canonical-qualification.json')


def preserve_archives(old,out):
    retained.preserve_all_checkpoints(old,out)
    for name in MORF_GATES:retained.exact_copy(old/name,out/name)


def namespace():
    value=admitted.namespace()
    value.update(build=build,qualify=qualify,hydrate_facts=hydrate,validate=validate,CATALOG=CATALOG,
        reference=reference,REFERENCE_PATH=PATH,factual_delta=factual_delta,preserve_all_checkpoints=preserve_archives)
    return value


def economic(out,old,spec,request,timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    parent=journal.read_checkpoint(old/spec['selected_checkpoint'])
    need(parent['sha256']==spec['outer_sha256'] and len(parent['repairs'])==39,
         'LBPH_ACTUAL_ORIGINAL_OWN39_BEFORE_RESUME')
    with retained.retained_scopes(old,parent,out):
        function('system_campaign_p02_q4_cash_run.py','economic',ECONOMIC,namespace(),
                 insert_after='actual_packets_and_own_cash_gate')(out,old,spec,request,timing)


def morf_boundary(root,old,cp):
    from research.pooled_vacancy_funding import journal
    raw=(old/'spec.json').read_bytes();spec=json.loads(raw)
    old_request=json.loads((old/'request.json').read_bytes())
    need(retained.original.sha(raw)==old_request['predecessor_sha256'],'LBPH_RETAINED_MORF_EXACT_OWN38_SPEC')
    catalog=json.loads((Path(__file__).parent/'system-campaign-morf-preopen-cash-terminal-facts.json').read_bytes())
    descriptor,=[d for d in cp['repairs'] if json.loads((root/'book/repairs'/d['filename']).read_bytes()).get('add')
                  ==[v['added'] for v in catalog['terms']]]
    boundary=journal.read_checkpoint(root/'book/predecessor-checkpoints'/(spec['outer_sha256']+'.json.gz'))
    need(boundary['run']['checkpoint_sha256']==descriptor['predecessor_checkpoint_sha256']
         and boundary['source_cursor']==descriptor['resume_session']=='2024-07-31',
         'LBPH_RETAINED_MORF_ORIGINAL_OWN38_NOT_REBOUND')
    return boundary,catalog


def five_cash_boundary(root,cp,request):
    from research.pooled_vacancy_funding import journal
    raw=(Path(__file__).parent/'system-campaign-p02-unconsumed2024-cash-predecessor.json').read_bytes()
    need(retained.original.sha(raw)==request['retained_five_cash_original_spec_sha256'],
         'LBPH_RETAINED_FIVE_CASH_ORIGINAL_OWN37_PUBLIC_SPEC')
    spec=json.loads(raw)
    catalog=json.loads((Path(__file__).parent/'system-campaign-unconsumed2024-cash-calendar-terminal-facts.json').read_bytes())
    descriptor,=[d for d in cp['repairs'] if json.loads((root/'book/repairs'/d['filename']).read_bytes()).get('add')
                  ==[v['added'] for v in catalog['terms']]]
    boundary=journal.read_checkpoint(root/'book/predecessor-checkpoints'/(spec['outer_sha256']+'.json.gz'))
    need(boundary['sha256']==spec['outer_sha256']
         and boundary['run']['checkpoint_sha256']==descriptor['predecessor_checkpoint_sha256']
         and boundary['source_cursor']==descriptor['resume_session']=='2024-04-30',
         'LBPH_RETAINED_FIVE_CASH_UNREBOUND_OWN37_ENTITLEMENT_BOUNDARY')
    return boundary,catalog


def review(out,root,old,spec,request,timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    import system_campaign_close_review as closing_review
    import system_campaign_pxd_review as pxd_review
    from types import FunctionType
    cp=journal.read_checkpoint(root/'book/checkpoint.json.gz')
    with retained.retained_scopes(root,cp,out):
        function('system_campaign_p02_q4_cash_run.py','review',REVIEW,namespace(),
                 keywords=REVIEW_KEYS)(out,root,old,spec,timing)
        if cp['repairs']!=spec['repairs']:
            closing=closing_review.review
            checked=FunctionType(closing.__code__,dict(closing.__globals__,validate=retained.validate_closing),
                                 closing.__name__,closing.__defaults__)
            timing.call('retained_hostess_scope_and_actual_event',checked,root,cp,out/'retained-close-position-and-event-review.json')
            timing.call('retained_pxd_scope_and_actual_event',pxd_review.review,root,cp,out/'retained-pxd-position-and-event-review.json')
            boundary=retained.cash_boundary(root,old,request)
            q4=json.loads((Path(__file__).parent/'system-campaign-q4-2023-cash-calendar-terminal-facts.json').read_bytes())
            timing.call('retained_original_q4_cash_entitlements',actual_cash,root,cp,boundary,q4,out/'q4-cash-actual-entitlements-review.json')
            boundary,five=five_cash_boundary(root,cp,request)
            timing.call('retained_five_cash_entitlements',actual_cash,root,cp,boundary,five,out/'unconsumed2024-cash-actual-entitlements-review.json')
            boundary,morf=morf_boundary(root,old,cp)
            timing.call('retained_morf_cash_entitlement',actual_cash,root,cp,boundary,morf,out/'morf-cash-actual-entitlements-review.json')
            for name in MORF_GATES:
                need((root/name).read_bytes()==(old/name).read_bytes(),'LBPH_ALL_ORIGINAL_MORF_CANONICAL_GATES_EXACT')
            timing.call('all_archived_original_checkpoints',retained.review_archived_checkpoints,root,old,out)
    need(journal.read_checkpoint(root/'book/checkpoint.json.gz')==cp,'LBPH_REVIEW_NEVER_MUTATES_STOPPED_BOOK')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=('economic','review'),required=True)
    parser.add_argument('--spec',type=Path,required=True);parser.add_argument('--request',type=Path,required=True)
    args=parser.parse_args();spec=json.loads(args.spec.read_bytes());request=json.loads(args.request.read_bytes())
    with PhaseTiming(Path('/out'),args.mode) as timing,CashRegistry():
        if args.mode=='economic':economic(Path('/out'),Path('/old'),spec,request,timing)
        else:review(Path('/out'),Path('/evidence'),Path('/old'),spec,request,timing)
