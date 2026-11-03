"""Exact own40 suffix; original financial call and all older scopes retained."""
import argparse
import json
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_pxd_financial_body import function
from system_campaign_winter2025_cash_parent import reference, PATH
from system_campaign_winter2025_cash_context import CashRegistry
from system_campaign_winter2025_cash_facts import build, hydrate, validate, qualify, factual_delta, CATALOG
from system_campaign_q4_cash_review import actual_cash
from system_campaign_phase_timing import PhaseTiming
import system_campaign_p02_unconsumed_cash_run as retained
import system_campaign_p02_lbph_cash_run as admitted

ECONOMIC = {
    41200949097: 41250116694, '2023-09-29': '2025-01-31', '2023-10-04': '2025-02-04',
    1446: 1781, 34: 40, 992: 1327,
    'RETAINED_SIX_MODEL_Q4_CASH_BATCH_SUFFIX': 'RETAINED_EIGHT_MODEL_WINTER2025_CASH_BATCH_SUFFIX',
    'q4-cash-constructor-admission.json': 'winter2025-cash-constructor-admission.json',
    'q4-cash-economic-outcome.json': 'winter2025-cash-economic-outcome.json',
    'Q4_CASH_EXACT_OWN_34_INPUT_SEPTEMBER_PARENT': 'WINTER2025_EXACT_OWN40_JANUARY_FINANCIAL_PARENT',
    'Q4_CASH_ALL_SIX_ORIGINAL_MODEL_SEMANTICS_UNCHANGED': 'WINTER2025_ALL_EIGHT_ORIGINAL_MODELS_UNCHANGED',
    'Q4_CASH_EXACT_OWN_SUCCESSOR_ALL34_INPUTS_AND_ONE_FACTUAL_CASH_CALENDAR': 'WINTER2025_EXACT_OWN40_AND_ONE_CASH_FACT_GROUP',
    'Q4_CASH_FINANCIAL_REFUSAL_PREFIX_PRESERVED': 'WINTER2025_FINANCIAL_REFUSAL_PREFIX_PRESERVED',
}
REVIEW = {
    'q4-cash-constructor-admission.json': 'winter2025-cash-constructor-admission.json',
    'q4-2023-cash-calendar-overlay.json': 'winter2025-cash-overlay.json',
    'q4-cash-actual-entitlements-review.json': 'winter2025-cash-actual-entitlements-review.json',
    'q4-cash-lineage-review.json': 'winter2025-cash-lineage-review.json',
}
REVIEW_KEYS = {'all34_old_descriptors_preserved': 'all40_old_descriptors_preserved',
               'all_six_original_model_semantics_unchanged': 'all_eight_original_model_semantics_unchanged'}
RETAINED_GATES = (*admitted.MORF_GATES, 'lbph-cash-packet-qualification.json',
    'lbph-cash-canonical-qualification.json', 'lbph-positive-cash-canonical-qualification.json')
BOUNDARIES = {
    'morf': ('system-campaign-p02-morf-cash-predecessor.json',
             'system-campaign-morf-preopen-cash-terminal-facts.json',
             'retained_morf_original_spec_sha256', '2024-07-31'),
    'lbph': ('system-campaign-p02-lbph-cash-predecessor.json',
             'system-campaign-lbph-preopen-cash-terminal-facts.json',
             'retained_lbph_original_spec_sha256', '2024-10-31'),
}


def preserve_archives(old, out):
    retained.preserve_all_checkpoints(old, out)
    for name in RETAINED_GATES:
        retained.exact_copy(old / name, out / name)


def namespace():
    value = admitted.namespace()
    value.update(build=build, qualify=qualify, hydrate_facts=hydrate, validate=validate,
        CATALOG=CATALOG, reference=reference, REFERENCE_PATH=PATH,
        factual_delta=factual_delta, preserve_all_checkpoints=preserve_archives)
    return value


def economic(out, old, spec, request, timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    parent = journal.read_checkpoint(old / spec['selected_checkpoint'])
    need(parent['sha256'] == spec['outer_sha256'] and len(parent['repairs']) == 40,
         'WINTER2025_ACTUAL_ORIGINAL_OWN40_BEFORE_RESUME')
    with retained.retained_scopes(old, parent, out):
        function('system_campaign_p02_q4_cash_run.py', 'economic', ECONOMIC, namespace(),
                 insert_after='actual_packets_and_own_cash_gate')(out, old, spec, request, timing)


def original_cash_boundary(root, cp, request, which):
    hosted()
    from research.pooled_vacancy_funding import journal
    specname, catalogname, requestkey, original_session = BOUNDARIES[which]
    raw = (Path(__file__).parent / specname).read_bytes()
    need(sha(raw) == request[requestkey], 'WINTER2025_RETAINED_ORIGINAL_PUBLIC_CASH_SPEC')
    spec = json.loads(raw)
    catalog = json.loads((Path(__file__).parent / catalogname).read_bytes())
    descriptor, = [d for d in cp['repairs']
        if json.loads((root / 'book/repairs' / d['filename']).read_bytes()).get('add')
        == [v['added'] for v in catalog['terms']]]
    path = root / 'book/predecessor-checkpoints' / (spec['outer_sha256'] + '.json.gz')
    need(sha(path.read_bytes()) == spec['selected_file']['sha256'],
         'WINTER2025_RETAINED_ORIGINAL_CASH_GZIP_BYTES')
    boundary = journal.read_checkpoint(path)
    need(boundary['sha256'] == spec['outer_sha256']
         and boundary['run']['checkpoint_sha256'] == descriptor['predecessor_checkpoint_sha256']
         and boundary['source_cursor'] == descriptor['resume_session'] == original_session,
         'WINTER2025_RETAINED_ORIGINAL_CASH_ENTITLEMENT_NOT_REBOUND')
    return boundary, catalog


def review(out, root, old, spec, request, timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    import system_campaign_close_review as closing_review
    import system_campaign_pxd_review as pxd_review
    from types import FunctionType
    cp = journal.read_checkpoint(root / 'book/checkpoint.json.gz')
    with retained.retained_scopes(root, cp, out):
        function('system_campaign_p02_q4_cash_run.py', 'review', REVIEW, namespace(),
                 keywords=REVIEW_KEYS)(out, root, old, spec, timing)
        if cp['repairs'] != spec['repairs']:
            closing = closing_review.review
            checked = FunctionType(closing.__code__, dict(closing.__globals__, validate=retained.validate_closing),
                                   closing.__name__, closing.__defaults__)
            timing.call('retained_hostess_scope_and_actual_event', checked,
                        root, cp, out / 'retained-close-position-and-event-review.json')
            timing.call('retained_pxd_scope_and_actual_event', pxd_review.review,
                        root, cp, out / 'retained-pxd-position-and-event-review.json')
            boundary = retained.cash_boundary(root, old, request)
            q4 = json.loads((Path(__file__).parent / 'system-campaign-q4-2023-cash-calendar-terminal-facts.json').read_bytes())
            timing.call('retained_original_q4_cash_entitlements', actual_cash,
                        root, cp, boundary, q4, out / 'q4-cash-actual-entitlements-review.json')
            boundary, five = admitted.five_cash_boundary(root, cp, request)
            timing.call('retained_five_cash_entitlements', actual_cash,
                        root, cp, boundary, five, out / 'unconsumed2024-cash-actual-entitlements-review.json')
            for which in BOUNDARIES:
                boundary, catalog = original_cash_boundary(root, cp, request, which)
                timing.call('retained_' + which + '_cash_entitlements', actual_cash,
                            root, cp, boundary, catalog, out / (which + '-cash-actual-entitlements-review.json'))
            for name in RETAINED_GATES:
                need((root / name).read_bytes() == (old / name).read_bytes(),
                     'WINTER2025_ALL_ORIGINAL_MORF_AND_LBPH_CANONICAL_GATES_EXACT')
            timing.call('all_archived_original_checkpoints', retained.review_archived_checkpoints, root, old, out)
    need(journal.read_checkpoint(root / 'book/checkpoint.json.gz') == cp,
         'WINTER2025_REVIEW_NEVER_MUTATES_STOPPED_BOOK')


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
