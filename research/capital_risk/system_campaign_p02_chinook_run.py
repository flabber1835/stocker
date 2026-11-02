"""One own July suffix with the fourth certified unowned terminal sensor."""
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
from system_campaign_chinook_sensor import SensorCertificate, admit_parent_extension
from system_campaign_abiomed_input import InputCodec as AbiomedCodec
from system_campaign_abiomed_facts import evidence as abiomed_evidence, PRIVATE, retained_completion
from system_campaign_chinook_basis import basis, validate as validate_chinook
from system_campaign_p02_abiomed_run import unadvanced_parent
from system_campaign_chinook_review import preserve_parent, review as review_certificate
from system_campaign_spring2023_review import retained_abiomed
from system_campaign_chinook_gate import qualify
from system_campaign_chinook_input import InputCodec as ChinookCodec
from system_campaign_chinook_facts import hydrate as hydrate_chinook, overlay as build_chinook, evidence as chinook_evidence, PRIVATE as CPRIVATE



def run(out, old, spec, request, timing):
    hosted()
    from research.pooled_vacancy_funding import backtest, journal
    need(spec['arm'] == 'P02' and spec['run_id'] == 41183110747
         and spec['selected_session'] == '2023-07-31'
         and request['execution_mode'] == 'FOURTH_CERTIFIED_CHINOOK_SENSOR_SUFFIX',
         'CHINOOK_EXACT_OWN_ADMITTED_JULY_PREFIX')
    cp = timing.call('old_prefix_preflight', preflight, spec, old, out, before='2023-08-10')
    need(cp['completed'] == 1403 and len(cp['repairs']) == 31
         and cp['base']['sources'][PACKET_SOURCE_PATH] == request['qualified_packet_source_sha256'],
         'CHINOOK_ACTUAL_FULL_PARENT_AND_PACKET_SOURCE')
    timing.call('own_origin_qualification', qualify_origin, out, cp, out / 'own-origin-qualification.json')
    v1, spin, alder, _ = timing.call('retained_fact_contexts', retained, cp, old, out)
    (out / 'hydrated-uncertainty-event.json').write_bytes((old / 'hydrated-uncertainty-event.json').read_bytes())
    need(validate_input_commitment(old, cp) == request['uncertainty_input_descriptor_sha256'],
         'CHINOOK_EXACT_RETAINED_ALDER_MODEL')
    seed = preserve_and_seed(old, out, cp)
    need(len(seed) == request['parent_certificate_rows'], 'CHINOOK_EXACT_COMMITTED_CERTIFICATE_SEED')
    preserve_event_archive(old, out)
    timing.call('all_original_event_proofs', preserve_parent, old, out, cp, spec)
    for function in (preserve_prior_facts, preserve_sprint, preserve_spring_cash, preserve_autumn_cash,
                     preserve_completions2021, preserve_following, preserve_registered):
        function(cp, old, out)
    znative = retained_zogenix(old, out)
    completion = timing.call('retained_completion_context', retained_completion, old, cp, out)
    native, amodel = timing.call('retained_abiomed_context', retained_abiomed, old, cp, out)
    amendment = timing.call('original_amendment_boundary', retained_amendment, old, out)
    old_hash, _ = timing.call('retained_actual_common_basis', basis, out, cp, amendment=amendment)
    need(old_hash == request['predecessor_common_basis_sha256'], 'CHINOOK_EXACT_ADMITTED_PARENT_BASIS')
    acodec = AbiomedCodec(abiomed_evidence(out), native)
    zcodec = ZogenixCodec(zogenix_evidence(out), znative)
    codec = InputCodec(evidence(out))
    cnative = timing.call('new_chinook_source_hydration', hydrate_chinook, old, out)
    ccodec = ChinookCodec(chinook_evidence(out), cnative)
    certificate = SensorCertificate(out, codec, alder.native, request['canonical_controller_sources'],
        seed=seed, event_source=json.loads((out / 'hydrated-uncertainty-event.json').read_bytes()),
        zogenix_codec=zcodec, zogenix_native=znative, zogenix_source=json.loads((out / ZPRIVATE).read_bytes()),
        abiomed_codec=acodec, abiomed_native=native, abiomed_source=json.loads((out / PRIVATE).read_bytes()),
        parent_checkpoint=cp, parent_certificate_raw=(old / 'uncertainty-certificate.jsonl').read_bytes(),
        parent_review_raw=(old / 'uncertainty-certificate-review.json').read_bytes(),
        parent_spec=spec, abiomed_model=amodel,
        chinook_codec=ccodec, chinook_native=cnative,
        chinook_source=json.loads((out / CPRIVATE).read_bytes()))
    save(out / 'chinook-inherited-constructor-admission.json', certificate.continuation_admission)
    save(out / 'chinook-constructor-admission.json', certificate.chinook_admission)
    observer = SeededObservation(out / 'correlation-inputs.jsonl.gz', correlation_seed(old, cp))
    args = arguments(out / 'book', True)
    args[args.index('--policy') + 1] = cp['base']['policy']
    with v1, spin, alder, idempotent_dispatch(alder), zcodec, codec, amendment, completion, acodec, ccodec:
        path = timing.call('new_chinook_typed_input', build_chinook, cp, out)
        loaded = backtest.load_repair(path, resume_session=cp['source_cursor'],
            predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
        objects = [backtest.load_repair(out / 'book/repairs' / item['filename'],
            resume_session=item['resume_session'], predecessor_checkpoint_sha256=item['predecessor_checkpoint_sha256'])
            for item in cp['repairs']]
        need(amendment.active, 'CHINOOK_ORIGINAL_FUTURE_AMENDMENT_ACTUALLY_ACTIVATED')
        timing.call('actual_chinook_packets_and_four_event_gate', qualify, out, cp, objects, loaded, ccodec, request)
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
         'CHINOOK_EXACT_OWN_SUCCESSOR_ALL_31_RETAINED_INPUTS_PRESERVED')
    save(out / 'chinook-economic-outcome.json', dict(session=current['source_cursor'],
        completed=current['completed'], complete=current['source_cursor'] == backtest.END and current['completed'] == 2156,
        only_candidate='P02', new_origin=False, new_overlay=True, source_conversion=False, production_contacted=False))
    need(code == 0, 'CHINOOK_FINANCIAL_REFUSAL_PREFIX_PRESERVED')


def review(out, root, old, spec, timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    from system_campaign_factual_run import review as review_financial
    from system_campaign_chinook_basis import require_exact_delta
    cp = journal.read_checkpoint(root / 'book/checkpoint.json.gz')
    previous = journal.read_checkpoint(old / spec['selected_checkpoint'])
    request = json.loads((root / 'request.json').read_bytes())
    if cp['repairs'] == previous['repairs']:
        unadvanced_parent(out, root, old, spec, cp, previous)
        return
    model, = validate_chinook(root, cp)
    need(cp['base'] == previous['base'] and cp['repairs'][:-1] == previous['repairs']
         and cp['repairs'][-1]['sha256'] == model.sha256
         == sha((root / 'chinook-sensor-input.json').read_bytes()),
         'CHINOOK_REVIEW_EXACT_ALL31_PRIOR_INPUTS_AND_ONE_ADDITIONAL_MODEL')
    from system_campaign_uncertainty_review import seed as committed_seed
    from system_campaign_spring2023_sensor import require_committed_parent
    constructor_admission = require_committed_parent(committed_seed(old, previous), previous,
        (old / 'uncertainty-certificate.jsonl').read_bytes(),
        (old / 'uncertainty-certificate-review.json').read_bytes(), spec)
    need(json.loads((root / 'chinook-inherited-constructor-admission.json').read_bytes())
         == constructor_admission, 'CHINOOK_INDEPENDENT_EXACT_CONSTRUCTOR_ADMISSION')
    save(out / 'chinook-independent-inherited-constructor-admission.json', constructor_admission)
    extension = admit_parent_extension(previous, (old / 'uncertainty-certificate-review.json').read_bytes(),
        None, sha((Path(__file__).parent / 'system_campaign_chinook_sensor.py').read_bytes()))
    need(json.loads((root / 'chinook-constructor-admission.json').read_bytes()) == extension,
         'CHINOOK_INDEPENDENT_FIRST_INPUT_CONSTRUCTOR_ADMISSION')
    save(out / 'chinook-independent-constructor-admission.json', extension)
    boundary = journal.read_checkpoint(root / 'book/predecessor-checkpoints' / (OUTER + '.json.gz'))
    amendment = FutureProjection(root, boundary)
    znative = retained_zogenix(root, out)
    native, _ = retained_abiomed(root, cp, out)
    completion = retained_completion(root, cp)
    cnative = timing.call('independent_new_chinook_source_hydration', hydrate_chinook, old, out)
    need((out / CPRIVATE).read_bytes() == (root / CPRIVATE).read_bytes(),
         'CHINOOK_INDEPENDENT_FROZEN_SOURCE_HYDRATION_IDENTICAL')
    with ZogenixCodec(zogenix_evidence(root), znative), InputCodec(evidence(root)), completion, \
            AbiomedCodec(abiomed_evidence(root), native), ChinookCodec(chinook_evidence(root), cnative):
        timing.call('canonical_all_history_financial_review', review_financial, out, root, old, spec)
        timing.call('own_origin_review', qualify_origin, root, previous, out / 'independent-own-origin-qualification.json')
        timing.call('continued_four_sensor_review', review_certificate, root, old, spec,
                    out / 'uncertainty-certificate-review.json')
        h, value = timing.call('common_basis_review', basis, root, cp, amendment=amendment)
    before = json.loads((old / 'common-factual-and-uncertainty-basis.json').read_bytes())
    declared_model = model.model_dump(by_alias=True)
    declared_model.pop('predecessor_checkpoint_sha256')
    require_exact_delta(before['value'], value, declared_model)
    save(out / 'common-factual-and-uncertainty-basis.json', dict(sha256=h, value=value))
    for name in (PAYLOAD_NAME, OVERLAY_NAME, PROJECTION_NAME):
        need((root / name).read_bytes() == (old / name).read_bytes(), 'CHINOOK_ORIGINAL_AMENDMENT_BYTES')
    need((root / 'book/predecessor-checkpoints' / (OUTER + '.json.gz')).read_bytes()
         == (old / 'book/predecessor-checkpoints' / (OUTER + '.json.gz')).read_bytes(),
         'CHINOOK_ORIGINAL_AMENDMENT_BOUNDARY_GZIP')
    save(out / 'chinook-lineage-review.json', dict(status='EXACT_OWN_FOURTH_SENSOR_SUFFIX_REVIEWED',
        original_amendment_boundary_and_bytes_preserved=True, all_31_old_descriptors_preserved=True,
        exact_latest_predecessor_preserved=True, source_and_parameters_unchanged=True,
        all_four_retained_model_semantics_unchanged=True, all_old_factual_semantics_unchanged=True,
        exactly_one_new_chinook_model_adopted=True, production_contacted=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=('economic', 'review'), required=True)
    p.add_argument('--spec', type=Path, required=True)
    p.add_argument('--request', type=Path, required=True)
    args = p.parse_args()
    spec = json.loads(args.spec.read_bytes())
    request = json.loads(args.request.read_bytes())
    with PhaseTiming(Path('/out'), args.mode) as timing:
        if args.mode == 'economic':
            run(Path('/out'), Path('/old'), spec, request, timing)
        else:
            review(Path('/out'), Path('/evidence'), Path('/old'), spec, timing)
