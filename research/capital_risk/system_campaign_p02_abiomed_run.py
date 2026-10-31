"""Own November P02 suffix, preserving every adopted input and joint proof."""
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
from system_campaign_zogenix_input import InputCodec as ZogenixCodec
from system_campaign_zogenix_facts import evidence as zogenix_evidence, PRIVATE as ZPRIVATE
from system_campaign_p02_october_run import retained_zogenix
from system_campaign_sprint_facts import preserve_prior_facts, PACKET_SOURCE_PATH
from system_campaign_spring2020_cash_facts import preserve_sprint
from system_campaign_autumn2020_cash_facts import preserve_spring_cash
from system_campaign_2021_completions_facts import preserve_autumn_cash
from system_campaign_following_completions_facts import preserve_completions2021
from system_campaign_amendment_build import preserve_following
from system_campaign_ordinary_registry import preserve as preserve_registered
from system_campaign_future_amendment import FutureProjection, OUTER, PAYLOAD_NAME, OVERLAY_NAME, PROJECTION_NAME
from system_campaign_p02_calendar_run import retained_amendment
from system_campaign_phase_timing import PhaseTiming
from system_campaign_replay_timing import ReplayTiming
from system_campaign_abiomed_sensor import SensorCertificate
from system_campaign_abiomed_input import InputCodec as AbiomedCodec
from system_campaign_abiomed_facts import hydrate, overlay, evidence as abiomed_evidence, PRIVATE, retained_completion
from system_campaign_abiomed_review import review as review_certificate, preserve_parent
from system_campaign_abiomed_basis import basis
from system_campaign_abiomed_gate import qualify


def run(out, old, spec, request, timing):
    hosted()
    from research.pooled_vacancy_funding import backtest, journal
    need(spec['arm'] == 'P02' and spec['run_id'] == 41166283025
         and spec['selected_session'] == '2022-11-30'
         and request['execution_mode'] == 'THIRD_CERTIFIED_ABIOMED_SENSOR_SUFFIX',
         'ABIOMED_EXACT_OWN_NOVEMBER_PREFIX')
    cp = timing.call('old_prefix_preflight', preflight, spec, old, out, before='2022-12-21')
    need(cp['completed'] == 1238 and len(cp['repairs']) == 28
         and cp['base']['sources'][PACKET_SOURCE_PATH] == request['qualified_packet_source_sha256'],
         'ABIOMED_ACTUAL_PARENT_AND_PACKET_SOURCE')
    timing.call('own_origin_qualification', qualify_origin, out, cp, out / 'own-origin-qualification.json')
    v1, spin, alder, _ = timing.call('retained_fact_contexts', retained, cp, old, out)
    (out / 'hydrated-uncertainty-event.json').write_bytes((old / 'hydrated-uncertainty-event.json').read_bytes())
    need(validate_input_commitment(old, cp) == request['uncertainty_input_descriptor_sha256'],
         'ABIOMED_EXACT_ORIGINAL_ALDER_MODEL')
    seed = preserve_and_seed(old, out, cp)
    need(len(seed) == request['parent_certificate_rows'] == 784, 'ABIOMED_EXACT_COMMITTED_PARENT_SEED')
    preserve_event_archive(old, out)
    preserve_parent(old, out, cp, spec)
    for function in (preserve_prior_facts, preserve_sprint, preserve_spring_cash, preserve_autumn_cash,
                     preserve_completions2021, preserve_following, preserve_registered):
        function(cp, old, out)
    znative = retained_zogenix(old, out)
    completion = timing.call('retained_completion_context', retained_completion, old, cp, out)
    amendment = timing.call('original_amendment_boundary', retained_amendment, old, out)
    old_hash, _ = timing.call('retained_actual_common_basis', basis, out, cp, amendment=amendment)
    need(old_hash == request['predecessor_common_basis_sha256'], 'ABIOMED_EXACT_REVIEWED_PARENT_BASIS')
    native = timing.call('abiomed_source_hydration', hydrate, old, out)
    path = overlay(cp, out)
    acodec = AbiomedCodec(abiomed_evidence(out), native)
    zcodec = ZogenixCodec(zogenix_evidence(out), znative)
    codec = InputCodec(evidence(out))
    certificate = SensorCertificate(out, codec, alder.native, request['canonical_controller_sources'],
        seed=seed, event_source=json.loads((out / 'hydrated-uncertainty-event.json').read_bytes()),
        zogenix_codec=zcodec, zogenix_native=znative, zogenix_source=json.loads((out / ZPRIVATE).read_bytes()),
        abiomed_codec=acodec, abiomed_native=native, abiomed_source=json.loads((out / PRIVATE).read_bytes()))
    observer = SeededObservation(out / 'correlation-inputs.jsonl.gz', correlation_seed(old, cp))
    args = arguments(out / 'book', True)
    args[args.index('--policy') + 1] = cp['base']['policy']
    with v1, spin, alder, idempotent_dispatch(alder), zcodec, codec, amendment, completion, acodec:
        objects = [backtest.load_repair(out / 'book/repairs' / item['filename'],
            resume_session=item['resume_session'],
            predecessor_checkpoint_sha256=item['predecessor_checkpoint_sha256']) for item in cp['repairs']]
        loaded = backtest.load_repair(path, resume_session=cp['source_cursor'],
                                     predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
        need(amendment.active, 'ABIOMED_ORIGINAL_FUTURE_AMENDMENT_ACTUALLY_ACTIVATED')
        timing.call('actual_merged_abiomed_canonical_gate', qualify, out, cp, objects, loaded, acodec, request)
        with certificate, observer, Execution('FAST', signal_closes=1) as execution, ReplayTiming(out):
            code = timing.call('financial_driver_total', backtest.main, args + ['--repair-overlay', str(path)])
    if completion.guard.failure is not None:
        save(out / 'completion-position-refusal.json', completion.guard.failure)
    save(out / 'acceleration-proof.json', execution.proof())
    save(out / 'correlation-capture-proof.json', observer.proof())
    save(out / 'recovered-tail-proof.json', preserve_tails(out / 'book',
         json.loads((out / 'factual-preflight.json').read_bytes())))
    current = journal.read_checkpoint(out / 'book/checkpoint.json.gz')
    need(current['base'] == cp['base'] and current['repairs'][:-1] == cp['repairs']
         and current['repairs'][-1]['sha256'] == loaded.sha256
         and current['run']['input_sha256'] == backtest.input_hash(current['base'], current['repairs']),
         'ABIOMED_EXACT_OWN_TYPED_INPUT_SUCCESSOR_ALL_28_INPUTS_PRESERVED')
    save(out / 'uncertainty-economic-outcome.json', dict(session=current['source_cursor'],
        completed=current['completed'], complete=current['source_cursor'] == backtest.END and current['completed'] == 2156,
        only_candidate='P02', new_origin=False, new_overlay=True, production_contacted=False))
    need(code == 0, 'ABIOMED_FINANCIAL_REFUSAL_PREFIX_PRESERVED')


def unadvanced_parent(out, root, old, spec, cp, previous):
    """Reuse old proof ONLY after full actual state/journal bytes are identical."""
    need(cp == previous and cp['sha256'] == spec['outer_sha256'], 'ABIOMED_UNADVANCED_EXACT_PARENT_OBJECT')
    names = ['book/checkpoint.json.gz', 'book/identity.json', 'source-bindings.json',
             *['book/' + name + '.jsonl' for name in previous['journals']]]
    checked = {}
    for name in names:
        before, after = (old / name).read_bytes(), (root / name).read_bytes()
        need(after == before, 'ABIOMED_UNADVANCED_COMPLETE_ORIGINAL_BYTES')
        checked[name] = dict(bytes=len(after), sha256=sha(after))
    for name, expected in (('core-review.json', spec['review_sha256']),
                           ('uncertainty-certificate-review.json', spec['interval_review_sha256'])):
        raw = (old / name).read_bytes()
        need(sha(raw) == expected, 'ABIOMED_UNADVANCED_HASH_BOUND_PARENT_PROOF')
        (out / name).write_bytes(raw)
    for name in ('completion-position-guard-review.json', 'common-factual-and-uncertainty-basis.json'):
        (out / name).write_bytes((old / name).read_bytes())
    save(out / 'unadvanced-parent-review.json', dict(status='ACTUAL_UNADVANCED_PARENT_FULL_BYTES_PROVEN',
        checkpoint_sha256=cp['sha256'], checked=checked, actual_new_financial_rows=0,
        abiomed_gate_or_model_adoption_claimed=False, production_contacted=False))


def review(out, root, old, spec, timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    from system_campaign_factual_run import review as review_financial
    cp = journal.read_checkpoint(root / 'book/checkpoint.json.gz')
    previous = journal.read_checkpoint(old / spec['selected_checkpoint'])
    if cp['repairs'] == previous['repairs']:
        unadvanced_parent(out, root, old, spec, cp, previous)
        return
    need(cp['base'] == previous['base'] and cp['repairs'][:-1] == previous['repairs'],
         'ABIOMED_REVIEW_EXACT_OLD_BASE_AND_ALL_28_INPUTS')
    boundary = journal.read_checkpoint(root / 'book/predecessor-checkpoints' / (OUTER + '.json.gz'))
    amendment = FutureProjection(root, boundary)
    znative = retained_zogenix(root, out)
    native = timing.call('independent_abiomed_source_hydration', hydrate, old, out)
    need((out / PRIVATE).read_bytes() == (root / PRIVATE).read_bytes(), 'ABIOMED_INDEPENDENT_HYDRATION_BYTES')
    completion = retained_completion(root, cp)
    with ZogenixCodec(zogenix_evidence(root), znative), InputCodec(evidence(root)), completion, \
            AbiomedCodec(abiomed_evidence(root), native):
        timing.call('canonical_all_history_financial_review', review_financial, out, root, old, spec)
        timing.call('own_origin_review', qualify_origin, root, previous, out / 'independent-own-origin-qualification.json')
        timing.call('joint_three_sensor_review', review_certificate, root, old, spec,
                    out / 'uncertainty-certificate-review.json')
        h, value = timing.call('common_basis_review', basis, root, cp, amendment=amendment)
    save(out / 'common-factual-and-uncertainty-basis.json', dict(sha256=h, value=value))
    need(cp['repairs'][-1]['sha256'] == sha((root / 'abiomed-sensor-input.json').read_bytes()),
         'ABIOMED_REVIEW_EXACT_NEW_TYPED_COMMITMENT')
    for name in (PAYLOAD_NAME, OVERLAY_NAME, PROJECTION_NAME):
        need((root / name).read_bytes() == (old / name).read_bytes(), 'ABIOMED_ORIGINAL_AMENDMENT_BYTES')
    need((root / 'book/predecessor-checkpoints' / (OUTER + '.json.gz')).read_bytes()
         == (old / 'book/predecessor-checkpoints' / (OUTER + '.json.gz')).read_bytes(),
         'ABIOMED_ORIGINAL_AMENDMENT_BOUNDARY_GZIP')
    save(out / 'joint-sensor-lineage-review.json', dict(status='EXACT_OWN_SUFFIX_REVIEWED',
        original_amendment_boundary_and_bytes_preserved=True, all_old_descriptors_preserved=True,
        exact_latest_predecessor_preserved=True, source_and_parameters_unchanged=True,
        original_math_and_comparison_sources_unchanged=True, new_typed_input_adopted=True,
        production_contacted=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('economic', 'review'), required=True)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_bytes())
    request = json.loads(args.request.read_bytes())
    with PhaseTiming(Path('/out'), args.mode) as timing:
        if args.mode == 'economic':
            run(Path('/out'), Path('/old'), spec, request, timing)
        else:
            review(Path('/out'), Path('/evidence'), Path('/old'), spec, timing)
