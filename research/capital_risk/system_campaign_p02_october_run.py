"""Own September P02 continuation with one fully qualified guarded batch."""
import argparse
import json
from pathlib import Path

from full_system_core import arguments, hosted
from full_system_benchmark import need, save
from system_campaign_facts import sha
from system_campaign_factual_run import preflight, correlation_seed, SeededObservation, preserve_tails
from system_campaign_p02_retained_run import idempotent_dispatch
from system_campaign_own_origin import qualify as qualify_origin
from system_campaign_acceleration import Execution
from system_campaign_uncertainty_support import retained
from system_campaign_uncertainty_facts import evidence
from system_campaign_uncertainty_input import InputCodec
from system_campaign_uncertainty_review import preserve_and_seed, validate_input_commitment
from system_campaign_uncertainty_archive import preserve as preserve_event_archive
from system_campaign_zogenix_sensor import SensorCertificate
from system_campaign_zogenix_input import InputCodec as ZogenixCodec, NATIVE as ZNATIVE, SID as ZSID
from system_campaign_zogenix_facts import evidence as zogenix_evidence, PRIVATE as ZPRIVATE, CONTRACT as ZCONTRACT
from system_campaign_sprint_facts import preserve_prior_facts, PACKET_SOURCE_PATH
from system_campaign_spring2020_cash_facts import preserve_sprint
from system_campaign_autumn2020_cash_facts import preserve_spring_cash
from system_campaign_2021_completions_facts import preserve_autumn_cash
from system_campaign_following_completions_facts import preserve_completions2021
from system_campaign_amendment_build import preserve_following
from system_campaign_future_amendment import FutureProjection, OUTER, PAYLOAD_NAME, OVERLAY_NAME, PROJECTION_NAME
from system_campaign_ordinary_registry import preserve as preserve_registered
from system_campaign_phase_timing import PhaseTiming
from system_campaign_replay_timing import ReplayTiming
from system_campaign_p02_calendar_run import retained_amendment
from system_campaign_completion_facts import build, hydrate, expected_repair, evidence as completion_evidence, PRIVATE, OVERLAY
from system_campaign_completion_scope import InputCodec as CompletionCodec
from system_campaign_completion_gate import qualify
from system_campaign_completion_review import preserve_parent_event, review as review_certificate
from system_campaign_completion_basis import basis
from system_campaign_mixed_preflight import verify_unchanged_attempt


HERE = Path(__file__).resolve().parent


def retained_zogenix(old, out):
    """Reuse the authenticated parent's hydration, checking its source identity."""
    from dataclasses import asdict
    from research.pooled_input_support import inputs
    c = json.loads((HERE / ZCONTRACT).read_bytes()); raw = (old / ZPRIVATE).read_bytes(); payload = json.loads(raw)
    native, = [t for t in inputs.load_actions(Path('/frozen/bundle')).terminal.get(ZNATIVE, ()) if t.security_id == ZSID]
    need(payload['contract'] == c and payload['actual_native'] == asdict(native) == c['native'],
         'OCTOBER_RETAINED_ZOGENIX_EXACT_HYDRATION_AND_FROZEN_NATIVE')
    (out / ZPRIVATE).write_bytes(raw)
    return native


def run(out, old, spec, request, timing):
    hosted()
    from research.pooled_vacancy_funding import backtest, journal
    need(spec['arm'] == 'P02' and spec['run_id'] == 41151496224 and spec['selected_session'] == '2022-09-30'
         and request['execution_mode'] == 'GUARDED_COMPLETION_BATCH_EXACT_SUFFIX', 'OCTOBER_EXACT_OWN_ADMITTED_PREFIX')
    if 'prior_unadvanced_equivalence_sha256' in request:
        save(out / 'unadvanced-attempt-equivalence-admission.json',
             verify_unchanged_attempt(old, spec, request))
    cp = timing.call('old_prefix_preflight', preflight, spec, old, out, before='2022-10-04')
    need(cp['completed'] == 1196 and len(cp['repairs']) == 27
         and cp['base']['sources'][PACKET_SOURCE_PATH] == request['qualified_packet_source_sha256'],
         'OCTOBER_ACTUAL_PARENT_COUNT_AND_PACKET_SOURCE')
    timing.call('own_origin_qualification', qualify_origin, out, cp, out / 'own-origin-qualification.json')
    v1, spin, alder, _ = timing.call('retained_fact_contexts', retained, cp, old, out)
    (out / 'hydrated-uncertainty-event.json').write_bytes((old / 'hydrated-uncertainty-event.json').read_bytes())
    need(validate_input_commitment(old, cp) == request['uncertainty_input_descriptor_sha256'],
         'OCTOBER_EXACT_OLD_UNCERTAINTY_COMMITMENT')
    seed = preserve_and_seed(old, out, cp)
    need(len(seed) == 742, 'OCTOBER_EXACT_742_ROW_COMMITTED_PARENT_SEED')
    preserve_event_archive(old, out); preserve_parent_event(old, out, cp, spec)
    for fn in (preserve_prior_facts, preserve_sprint, preserve_spring_cash, preserve_autumn_cash,
               preserve_completions2021, preserve_following, preserve_registered):
        fn(cp, old, out)
    native = retained_zogenix(old, out)
    amendment = timing.call('original_amendment_boundary', retained_amendment, old, out)
    old_hash, _ = timing.call('old_actual_common_basis', basis, out, cp, amendment=amendment)
    need(old_hash == request['predecessor_common_basis_sha256'], 'OCTOBER_EXACT_REVIEWED_PARENT_COMMON_BASIS')
    cash, prepared, path = timing.call('new_batch_source_hydration', build, cp, old, out)
    zcodec = ZogenixCodec(zogenix_evidence(out), native); codec = InputCodec(evidence(out))
    completion = CompletionCodec(prepared.canonical_repair, completion_evidence(out))
    certificate = SensorCertificate(out, codec, alder.native, request['canonical_controller_sources'], seed=seed,
        event_source=json.loads((out / 'hydrated-uncertainty-event.json').read_bytes()),
        zogenix_codec=zcodec, zogenix_native=native, zogenix_source=json.loads((out / ZPRIVATE).read_bytes()))
    observer = SeededObservation(out / 'correlation-inputs.jsonl.gz', correlation_seed(old, cp))
    args = arguments(out / 'book', True); args[args.index('--policy') + 1] = cp['base']['policy']
    with v1, spin, alder, idempotent_dispatch(alder), zcodec, codec, amendment, completion:
        objects = [backtest.load_repair(out / 'book/repairs' / d['filename'], resume_session=d['resume_session'],
                    predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']) for d in cp['repairs']]
        loaded = backtest.load_repair(path, resume_session=cp['source_cursor'],
                                     predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
        need(amendment.active, 'OCTOBER_ORIGINAL_FUTURE_AMENDMENT_ACTUALLY_ACTIVATED')
        timing.call('actual_merged_batch_canonical_gate', qualify, out, cp, objects, loaded, completion, cash, request)
        # Guard installed first; the unchanged certificate wraps it and both
        # commit through the same actual canonical watch/financial journals.
        with certificate, observer, Execution('FAST', signal_closes=1) as execution, ReplayTiming(out):
            code = timing.call('financial_driver_total', backtest.main, args + ['--repair-overlay', str(path)])
    if completion.guard.failure is not None:
        save(out / 'completion-position-refusal.json', completion.guard.failure)
    save(out / 'acceleration-proof.json', execution.proof())
    save(out / 'correlation-capture-proof.json', observer.proof())
    save(out / 'recovered-tail-proof.json', preserve_tails(out / 'book', json.loads((out / 'factual-preflight.json').read_bytes())))
    current = journal.read_checkpoint(out / 'book/checkpoint.json.gz')
    need(current['base'] == cp['base'] and current['repairs'][:-1] == cp['repairs']
         and current['repairs'][-1]['sha256'] == loaded.sha256
         and current['run']['input_sha256'] == backtest.input_hash(current['base'], current['repairs']),
         'OCTOBER_EXACT_OWN_TYPED_INPUT_SUCCESSOR_ALL_27_OLD_INPUTS_PRESERVED')
    save(out / 'uncertainty-economic-outcome.json', dict(session=current['source_cursor'], completed=current['completed'],
        complete=current['source_cursor'] == backtest.END and current['completed'] == 2156,
        only_candidate='P02', new_origin=False, new_overlay=True, production_contacted=False))
    need(code == 0, 'OCTOBER_FINANCIAL_REFUSAL_PREFIX_PRESERVED')


def review(out, root, old, spec, timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    from system_campaign_factual_run import review as review_financial
    cp = journal.read_checkpoint(root / 'book/checkpoint.json.gz')
    previous = journal.read_checkpoint(old / spec['selected_checkpoint'])
    request = json.loads((root / 'request.json').read_bytes())
    if 'prior_unadvanced_equivalence_sha256' in request:
        checked = verify_unchanged_attempt(old, spec, request)
        need(json.loads((root / 'unadvanced-attempt-equivalence-admission.json').read_bytes()) == checked,
             'OCTOBER_INDEPENDENT_UNADVANCED_SOURCE_EQUIVALENCE')
    boundary = journal.read_checkpoint(root / 'book/predecessor-checkpoints' / (OUTER + '.json.gz'))
    amendment = FutureProjection(root, boundary)
    native = retained_zogenix(root, out)
    timing.call('independent_new_scope_hydration', hydrate, old, out)
    need((out / PRIVATE).read_bytes() == (root / PRIVATE).read_bytes(), 'OCTOBER_INDEPENDENT_NEW_SOURCE_HYDRATION_BYTES')
    completion = CompletionCodec(expected_repair(root, previous['run']['checkpoint_sha256']), completion_evidence(root))
    with ZogenixCodec(zogenix_evidence(root), native), InputCodec(evidence(root)), completion:
        timing.call('canonical_all_history_financial_review', review_financial, out, root, old, spec)
        timing.call('own_origin_review', qualify_origin, root, previous, out / 'independent-own-origin-qualification.json')
        timing.call('joint_certificate_and_scope_review', review_certificate, root, old, spec,
                    out / 'uncertainty-certificate-review.json')
        h, value = timing.call('common_basis_review', basis, root, cp, amendment=amendment)
    save(out / 'common-factual-and-uncertainty-basis.json', dict(sha256=h, value=value))
    adopted = len(cp['repairs']) == len(previous['repairs']) + 1
    need(cp['base'] == previous['base'] and (cp['repairs'][:-1] if adopted else cp['repairs']) == previous['repairs'],
         'OCTOBER_REVIEW_EXACT_OLD_BASE_AND_ALL_27_DESCRIPTORS')
    if adopted:
        need(cp['repairs'][-1]['sha256'] == sha((root / OVERLAY).read_bytes()), 'OCTOBER_REVIEW_EXACT_NEW_TYPED_COMMITMENT')
    for name in (PAYLOAD_NAME, OVERLAY_NAME, PROJECTION_NAME):
        need((root / name).read_bytes() == (old / name).read_bytes(), 'OCTOBER_ORIGINAL_AMENDMENT_BYTES')
    need((root / 'book/predecessor-checkpoints' / (OUTER + '.json.gz')).read_bytes()
         == (old / 'book/predecessor-checkpoints' / (OUTER + '.json.gz')).read_bytes(),
         'OCTOBER_ORIGINAL_AMENDMENT_BOUNDARY_GZIP')
    save(out / 'joint-sensor-lineage-review.json', dict(status='EXACT_OWN_SUFFIX_REVIEWED',
        original_amendment_boundary_and_bytes_preserved=True, all_old_descriptors_preserved=True,
        exact_latest_predecessor_preserved=True, source_and_parameters_unchanged=True,
        original_math_and_comparison_sources_unchanged=True, new_typed_input_adopted=adopted,
        production_contacted=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--mode', choices=('economic', 'review'), required=True)
    p.add_argument('--spec', type=Path, required=True); p.add_argument('--request', type=Path, required=True)
    a = p.parse_args(); spec = json.loads(a.spec.read_bytes())
    with PhaseTiming(Path('/out'), a.mode) as timing:
        if a.mode == 'economic': run(Path('/out'), Path('/old'), spec, json.loads(a.request.read_bytes()), timing)
        else: review(Path('/out'), Path('/evidence'), Path('/old'), spec, timing)
