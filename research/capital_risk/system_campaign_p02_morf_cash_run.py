"""Own38 factual MORF suffix; the canonical financial call remains unchanged."""
import argparse
import json
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import need
from system_campaign_pxd_financial_body import function
from system_campaign_morf_cash_parent import reference,PATH
from system_campaign_morf_cash_context import CashRegistry
from system_campaign_morf_cash_facts import build,hydrate,validate,qualify,factual_delta,CATALOG
from system_campaign_q4_cash_review import actual_cash
from system_campaign_phase_timing import PhaseTiming
import system_campaign_p02_unconsumed_cash_run as admitted

ECONOMIC={
    41200949097:41239118150,'2023-09-29':'2024-07-31','2023-10-04':'2024-08-16',
    1446:1655,34:38,992:1201,
    'RETAINED_SIX_MODEL_Q4_CASH_BATCH_SUFFIX':'RETAINED_EIGHT_MODEL_MORF_PREOPEN_CASH_SUFFIX',
    'q4-cash-constructor-admission.json':'morf-cash-constructor-admission.json',
    'q4-cash-economic-outcome.json':'morf-cash-economic-outcome.json',
    'Q4_CASH_EXACT_OWN_34_INPUT_SEPTEMBER_PARENT':'MORF_EXACT_OWN38_JULY_FINANCIAL_PARENT',
    'Q4_CASH_ALL_SIX_ORIGINAL_MODEL_SEMANTICS_UNCHANGED':'MORF_ALL_EIGHT_ORIGINAL_MODELS_UNCHANGED',
    'Q4_CASH_EXACT_OWN_SUCCESSOR_ALL34_INPUTS_AND_ONE_FACTUAL_CASH_CALENDAR':'MORF_EXACT_OWN38_AND_ONE_ORDINARY_CASH_FACT',
    'Q4_CASH_FINANCIAL_REFUSAL_PREFIX_PRESERVED':'MORF_FINANCIAL_REFUSAL_PREFIX_PRESERVED',
}
REVIEW={
    'q4-cash-constructor-admission.json':'morf-cash-constructor-admission.json',
    'q4-2023-cash-calendar-overlay.json':'morf-preopen-cash-overlay.json',
    'q4-cash-actual-entitlements-review.json':'morf-cash-actual-entitlements-review.json',
    'q4-cash-lineage-review.json':'morf-cash-lineage-review.json',
}
REVIEW_KEYS={'all34_old_descriptors_preserved':'all38_old_descriptors_preserved',
             'all_six_original_model_semantics_unchanged':'all_eight_original_model_semantics_unchanged'}


def namespace():
    value=admitted.namespace()
    value.update(build=build,qualify=qualify,hydrate_facts=hydrate,validate=validate,CATALOG=CATALOG,
        reference=reference,REFERENCE_PATH=PATH,factual_delta=factual_delta,
        preserve_all_checkpoints=admitted.preserve_all_checkpoints)
    return value


def economic(out,old,spec,request,timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    parent=journal.read_checkpoint(old/spec['selected_checkpoint'])
    need(parent['sha256']==spec['outer_sha256'] and len(parent['repairs'])==38,
         'MORF_ACTUAL_ORIGINAL_OWN38_BEFORE_RESUME')
    with admitted.retained_scopes(old,parent,out):
        function('system_campaign_p02_q4_cash_run.py','economic',ECONOMIC,namespace(),
                 insert_after='actual_packets_and_own_cash_gate')(out,old,spec,request,timing)


def retained_five_cash_boundary(root,old,cp):
    from research.pooled_vacancy_funding import journal
    prior_request=json.loads((old/'request.json').read_bytes())
    prior_spec_raw=(old/'spec.json').read_bytes();prior_spec=json.loads(prior_spec_raw)
    need(admitted.original.sha(prior_spec_raw)==prior_request['predecessor_sha256'],
         'MORF_RETAINED_FIVE_CASH_ORIGINAL_OWN37_SPEC')
    catalog=json.loads((Path(__file__).parent/'system-campaign-unconsumed2024-cash-calendar-terminal-facts.json').read_bytes())
    descriptor,=[d for d in cp['repairs'] if json.loads((root/'book/repairs'/d['filename']).read_bytes()).get('add')
                  ==[v['added'] for v in catalog['terms']]]
    boundary=journal.read_checkpoint(root/'book/predecessor-checkpoints'/(prior_spec['outer_sha256']+'.json.gz'))
    need(boundary['run']['checkpoint_sha256']==descriptor['predecessor_checkpoint_sha256']
         and boundary['source_cursor']==descriptor['resume_session']=='2024-04-30',
         'MORF_RETAINED_FIVE_CASH_UNREBOUND_ORIGINAL_BOUNDARY')
    return boundary,catalog


def review(out,root,old,spec,request,timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    import system_campaign_close_review as closing_review
    import system_campaign_pxd_review as pxd_review
    from types import FunctionType
    cp=journal.read_checkpoint(root/'book/checkpoint.json.gz')
    with admitted.retained_scopes(root,cp,out):
        function('system_campaign_p02_q4_cash_run.py','review',REVIEW,namespace(),
                 keywords=REVIEW_KEYS)(out,root,old,spec,timing)
        if cp['repairs']!=spec['repairs']:
            closing=closing_review.review
            checked=FunctionType(closing.__code__,dict(closing.__globals__,validate=admitted.validate_closing),
                                 closing.__name__,closing.__defaults__)
            timing.call('retained_hostess_scope_and_actual_event',checked,root,cp,
                        out/'retained-close-position-and-event-review.json')
            timing.call('retained_pxd_scope_and_actual_event',pxd_review.review,root,cp,
                        out/'retained-pxd-position-and-event-review.json')
            boundary=admitted.cash_boundary(root,old,request)
            q4=json.loads((Path(__file__).parent/'system-campaign-q4-2023-cash-calendar-terminal-facts.json').read_bytes())
            timing.call('retained_original_q4_cash_entitlements',actual_cash,root,cp,boundary,q4,
                        out/'q4-cash-actual-entitlements-review.json')
            boundary,five=retained_five_cash_boundary(root,old,cp)
            timing.call('retained_five_cash_entitlements',actual_cash,root,cp,boundary,five,
                        out/'unconsumed2024-cash-actual-entitlements-review.json')
            timing.call('all_archived_original_checkpoints',admitted.review_archived_checkpoints,root,old,out)
    need(journal.read_checkpoint(root/'book/checkpoint.json.gz')==cp,'MORF_REVIEW_NEVER_MUTATES_STOPPED_BOOK')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=('economic','review'),required=True)
    parser.add_argument('--spec',type=Path,required=True);parser.add_argument('--request',type=Path,required=True)
    args=parser.parse_args();spec=json.loads(args.spec.read_bytes());request=json.loads(args.request.read_bytes())
    with PhaseTiming(Path('/out'),args.mode) as timing,CashRegistry():
        if args.mode=='economic':economic(Path('/out'),Path('/old'),spec,request,timing)
        else:review(Path('/out'),Path('/evidence'),Path('/old'),spec,request,timing)
