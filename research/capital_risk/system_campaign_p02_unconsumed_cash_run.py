"""Exact own37 ordinary-cash suffix; canonical financial implementation unchanged."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_pxd_financial_body import function
from system_campaign_unconsumed_cash_parent import reference, PATH
from system_campaign_unconsumed_cash_context import CashRegistry, CashPreflight
from system_campaign_unconsumed_cash_facts import build, hydrate, validate, qualify, CATALOG
from system_campaign_pxd_basis import basis, validate_all, validate_closing
from system_campaign_pxd_scope import InputCodec as PxdCodec, SCHEMA as PXD
from system_campaign_pxd_facts import expected_repair as pxd_body, evidence as pxd_evidence
from system_campaign_pxd_materialize import descriptor_for, materialized
from system_campaign_p02_pxd_run import (retained_closing, exact_copy, preserve_all_checkpoints,
                                        review_archived_checkpoints, cash_boundary)
from system_campaign_q4_cash_review import actual_cash
from system_campaign_phase_timing import PhaseTiming
import system_campaign_p02_q4_cash_run as original

ECONOMIC = {
    41200949097: 41233199484, '2023-09-29': '2024-04-30', '2023-10-04': '2024-05-17',
    1446: 1592, 34: 37, 992: 1138,
    'RETAINED_SIX_MODEL_Q4_CASH_BATCH_SUFFIX': 'RETAINED_EIGHT_MODEL_UNCONSUMED2024_CASH_SUFFIX',
    'q4-cash-constructor-admission.json': 'unconsumed2024-cash-constructor-admission.json',
    'q4-cash-economic-outcome.json': 'unconsumed2024-cash-economic-outcome.json',
    'Q4_CASH_EXACT_OWN_34_INPUT_SEPTEMBER_PARENT': 'UNCONSUMED_CASH_EXACT_OWN37_APRIL_PARENT',
    'Q4_CASH_ALL_SIX_ORIGINAL_MODEL_SEMANTICS_UNCHANGED': 'UNCONSUMED_CASH_ALL_EIGHT_ORIGINAL_MODELS_UNCHANGED',
    'Q4_CASH_EXACT_OWN_SUCCESSOR_ALL34_INPUTS_AND_ONE_FACTUAL_CASH_CALENDAR': 'UNCONSUMED_CASH_EXACT_OWN37_AND_ONE_ORDINARY_CALENDAR',
    'Q4_CASH_FINANCIAL_REFUSAL_PREFIX_PRESERVED': 'UNCONSUMED_CASH_FINANCIAL_REFUSAL_PREFIX_PRESERVED',
}
REVIEW = {
    'q4-cash-constructor-admission.json': 'unconsumed2024-cash-constructor-admission.json',
    'q4-2023-cash-calendar-overlay.json': 'unconsumed2024-cash-calendar-overlay.json',
    'q4-cash-actual-entitlements-review.json': 'unconsumed2024-cash-actual-entitlements-review.json',
    'q4-cash-lineage-review.json': 'unconsumed2024-cash-lineage-review.json',
}
REVIEW_KEYS = {'all34_old_descriptors_preserved': 'all37_old_descriptors_preserved',
               'all_six_original_model_semantics_unchanged': 'all_eight_original_model_semantics_unchanged'}


@contextmanager
def retained_scopes(root, cp, output):
    hosted()
    descriptor = descriptor_for(root, cp, PXD)
    codec = PxdCodec(pxd_body(root, descriptor['predecessor_checkpoint_sha256']), pxd_evidence(root))
    with retained_closing(root, cp) as closing, materialized(codec, root, descriptor, schema=PXD):
        try:
            yield
        finally:
            for name, guard in [('retained-close-position-refusal.json', closing.guard),
                                ('retained-pxd-position-refusal.json', codec.guard)]:
                if guard.failure is not None:
                    save(output/name, guard.failure)


def preflight(spec, old, out, *, before):
    from system_campaign_factual_run import preflight as exact_preflight
    cp = exact_preflight(spec, old, out, before=before)
    for name in ('hydrated-twnk-close-fact.json', 'twnk-guarded-close-input.json',
                 'hydrated-pxd-preopen-fact.json', 'pxd-unowned-preopen-input.json'):
        exact_copy(old/name, out/name)
    return cp


def namespace(**extra):
    prior = SimpleNamespace(**{**vars(original.prior), 'preflight': preflight})
    return dict(vars(original), prior=prior, basis=basis, validate_all=validate_all,
                CashPreflight=CashPreflight, build=build, qualify=qualify,
                hydrate_facts=hydrate, validate=validate, CATALOG=CATALOG,
                reference=reference, REFERENCE_PATH=PATH,
                preserve_all_checkpoints=preserve_all_checkpoints, **extra)


def economic(out, old, spec, request, timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    parent = journal.read_checkpoint(old/spec['selected_checkpoint'])
    need(parent['sha256'] == spec['outer_sha256'] and len(parent['repairs']) == 37,
         'UNCONSUMED_CASH_ACTUAL_ORIGINAL_OWN37_BEFORE_RESUME')
    with retained_scopes(old, parent, out):
        function('system_campaign_p02_q4_cash_run.py', 'economic', ECONOMIC, namespace(),
                 insert_after='actual_packets_and_own_cash_gate')(out, old, spec, request, timing)


def review(out, root, old, spec, request, timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    import system_campaign_close_review as closing_review
    import system_campaign_pxd_review as pxd_review
    from types import FunctionType
    cp = journal.read_checkpoint(root/'book/checkpoint.json.gz')
    with retained_scopes(root, cp, out):
        function('system_campaign_p02_q4_cash_run.py', 'review', REVIEW, namespace(),
                 keywords=REVIEW_KEYS)(out, root, old, spec, timing)
        if cp['repairs'] != spec['repairs']:
            closing = closing_review.review
            checked = FunctionType(closing.__code__, dict(closing.__globals__, validate=validate_closing),
                                   closing.__name__, closing.__defaults__)
            timing.call('retained_hostess_scope_and_actual_event', checked, root, cp,
                        out/'retained-close-position-and-event-review.json')
            timing.call('retained_pxd_scope_and_actual_event', pxd_review.review, root, cp,
                        out/'retained-pxd-position-and-event-review.json')
            boundary = cash_boundary(root, old, request)
            catalog = json.loads((Path(__file__).parent/'system-campaign-q4-2023-cash-calendar-terminal-facts.json').read_bytes())
            timing.call('retained_original_q4_cash_entitlements', actual_cash, root, cp, boundary, catalog,
                        out/'q4-cash-actual-entitlements-review.json')
            timing.call('all_archived_original_checkpoints', review_archived_checkpoints, root, old, out)
    need(journal.read_checkpoint(root/'book/checkpoint.json.gz') == cp,
         'UNCONSUMED_CASH_INDEPENDENT_REVIEW_NEVER_MUTATES_STOPPED_BOOK')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('economic', 'review'), required=True)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_bytes()); request = json.loads(args.request.read_bytes())
    with PhaseTiming(Path('/out'), args.mode) as timing, CashRegistry():
        if args.mode == 'economic':
            economic(Path('/out'), Path('/old'), spec, request, timing)
        else:
            review(Path('/out'), Path('/evidence'), Path('/old'), spec, request, timing)
