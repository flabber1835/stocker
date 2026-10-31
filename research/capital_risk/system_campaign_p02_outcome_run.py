"""Own saved P02 suffix; proof refinement changes no financial or event rule."""
import argparse
import json
from pathlib import Path

from full_system_core import arguments, hosted
from full_system_benchmark import need, save
from system_campaign_facts import sha
import system_campaign_p02_chinook_run as prior
from system_campaign_chinook_basis import validate as validate_chinook
from system_campaign_chinook_facts import hydrate as hydrate_chinook
from system_campaign_outcome_archive import preserve_and_seed
from system_campaign_outcome_basis import basis, validate_all, require_exact_delta
from system_campaign_outcome_facts import boundary, build, evidence, retained
from system_campaign_outcome_input import InputCodec
from system_campaign_outcome_sensor import SensorCertificate
from system_campaign_outcome_review import preserve_parent, review as review_certificate, parent_admission
from system_campaign_outcome_integration_gate import qualify
from system_campaign_phase_timing import PhaseTiming


def run(out, old, spec, request, timing):
    hosted()
    from research.pooled_vacancy_funding import backtest, journal
    from research.pooled_input_support.bundle import axis
    need(spec['arm'] == 'P02' and spec['run_id'] == 41187704006
         and spec['selected_session'] == '2023-07-31'
         and request['execution_mode'] == 'COMPLETE_CONTROLLER_OUTCOME_REFINEMENT_SUFFIX',
         'OUTCOME_EXACT_OWN_32_INPUT_JULY_PARENT')
    cp = timing.call('old_prefix_preflight', prior.preflight, spec, old, out, before='2023-08-01')
    need(cp['completed'] == 1403 and len(cp['repairs']) == 32
         and cp['base']['sources'][prior.PACKET_SOURCE_PATH] == request['qualified_packet_source_sha256'],
         'OUTCOME_ACTUAL_FULL_ADMITTED_PARENT_AND_PACKET_SOURCE')
    bound = boundary(cp, (old / spec['selected_checkpoint']).read_bytes(), axis())
    timing.call('own_origin_qualification', prior.qualify_origin, out, cp, out / 'own-origin-qualification.json')
    v1, spin, alder, _ = timing.call('retained_fact_contexts', prior.retained, cp, old, out)
    (out / 'hydrated-uncertainty-event.json').write_bytes((old / 'hydrated-uncertainty-event.json').read_bytes())
    need(prior.validate_input_commitment(old, cp) == request['uncertainty_input_descriptor_sha256'],
         'OUTCOME_ORIGINAL_ALDER_TYPED_INPUT_UNCHANGED')
    seed = preserve_and_seed(old, out, cp)
    need(len(seed) == request['parent_certificate_rows'], 'OUTCOME_EXACT_COMMITTED_949_ROW_SEED')
    prior.preserve_event_archive(old, out)
    timing.call('all_original_event_proofs', preserve_parent, old, out, cp, spec)
    for function in (prior.preserve_prior_facts, prior.preserve_sprint, prior.preserve_spring_cash,
                     prior.preserve_autumn_cash, prior.preserve_completions2021,
                     prior.preserve_following, prior.preserve_registered):
        function(cp, old, out)
    znative = prior.retained_zogenix(old, out)
    completion = timing.call('retained_completion_context', prior.retained_completion, old, cp, out)
    native, amodel = timing.call('retained_abiomed_context', prior.retained_abiomed, old, cp, out)
    amendment = timing.call('original_amendment_boundary', prior.retained_amendment, old, out)
    cnative = timing.call('retained_chinook_source_hydration', hydrate_chinook, old, out)
    need((out / prior.CPRIVATE).read_bytes() == (old / prior.CPRIVATE).read_bytes(),
         'OUTCOME_RETAINED_CHINOOK_PRIVATE_INPUT_BYTES_IDENTICAL')
    old_hash, _ = timing.call('retained_actual_common_basis', basis, out, cp, amendment=amendment)
    need(old_hash == request['predecessor_common_basis_sha256'], 'OUTCOME_ALL_FIVE_EVENT_MODEL_SEMANTICS_UNCHANGED')
    cmodel, = validate_chinook(old, cp)
    codec = prior.InputCodec(prior.evidence(out))
    zcodec = prior.ZogenixCodec(prior.zogenix_evidence(out), znative)
    acodec = prior.AbiomedCodec(prior.abiomed_evidence(out), native)
    ccodec = prior.ChinookCodec(prior.chinook_evidence(out), cnative)
    ocodec = InputCodec(evidence(), bound)
    certificate = SensorCertificate(out, codec, alder.native, request['canonical_controller_sources'],
        seed=seed, event_source=json.loads((out / 'hydrated-uncertainty-event.json').read_bytes()),
        zogenix_codec=zcodec, zogenix_native=znative, zogenix_source=json.loads((out / prior.ZPRIVATE).read_bytes()),
        abiomed_codec=acodec, abiomed_native=native, abiomed_source=json.loads((out / prior.PRIVATE).read_bytes()),
        parent_checkpoint=cp, parent_certificate_raw=(old / 'uncertainty-certificate.jsonl').read_bytes(),
        parent_review_raw=(old / 'uncertainty-certificate-review.json').read_bytes(), parent_spec=spec,
        abiomed_model=amodel, chinook_codec=ccodec, chinook_native=cnative,
        chinook_source=json.loads((out / prior.CPRIVATE).read_bytes()), chinook_model=cmodel)
    save(out / 'outcome-constructor-admission.json', certificate.continuation_admission)
    observer = prior.SeededObservation(out / 'correlation-inputs.jsonl.gz', prior.correlation_seed(old, cp))
    args = arguments(out / 'book', True)
    args[args.index('--policy') + 1] = cp['base']['policy']
    with v1, spin, alder, prior.idempotent_dispatch(alder), zcodec, codec, amendment, completion, acodec, ccodec, ocodec:
        path = timing.call('new_proof_only_typed_input', build, cp, out, bound)
        loaded = backtest.load_repair(path, resume_session=cp['source_cursor'],
            predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
        objects = [backtest.load_repair(out / 'book/repairs' / item['filename'],
            resume_session=item['resume_session'], predecessor_checkpoint_sha256=item['predecessor_checkpoint_sha256'])
            for item in cp['repairs']]
        certificate.proof_model = loaded
        need(amendment.active, 'OUTCOME_ORIGINAL_FUTURE_AMENDMENT_ACTUALLY_ACTIVE')
        timing.call('six_input_capture_and_frame_gate', qualify, out, old, cp, objects,
                    loaded, ocodec, bound, certificate, request)
        with certificate, observer, prior.Execution('FAST', signal_closes=1) as execution, prior.ReplayTiming(out):
            code = timing.call('financial_driver_total', backtest.main, args + ['--repair-overlay', str(path)])
    if completion.guard.failure is not None:
        save(out / 'completion-position-refusal.json', completion.guard.failure)
    save(out / 'acceleration-proof.json', execution.proof())
    save(out / 'correlation-capture-proof.json', observer.proof())
    save(out / 'recovered-tail-proof.json', prior.preserve_tails(out / 'book',
         json.loads((out / 'factual-preflight.json').read_bytes())))
    current = journal.read_checkpoint(out / 'book/checkpoint.json.gz')
    need(current['base'] == cp['base'] and current['repairs'][:-1] == cp['repairs']
         and current['repairs'][-1]['sha256'] == loaded.sha256
         and current['run']['input_sha256'] == backtest.input_hash(current['base'], current['repairs']),
         'OUTCOME_EXACT_OWN_SUCCESSOR_ALL32_INPUTS_AND_ONE_IDENTITY_PROOF')
    save(out / 'outcome-economic-outcome.json', dict(session=current['source_cursor'], completed=current['completed'],
        complete=current['source_cursor'] == backtest.END and current['completed'] == 2156,
        only_candidate='P02', new_origin=False, source_conversion=False, production_contacted=False))
    need(code == 0, 'OUTCOME_FINANCIAL_REFUSAL_PREFIX_PRESERVED')


def review(out, root, old, spec, timing):
    hosted()
    from research.pooled_vacancy_funding import journal
    from system_campaign_factual_run import review as review_financial
    from research.pooled_input_support.bundle import axis
    cp = journal.read_checkpoint(root / 'book/checkpoint.json.gz')
    previous = journal.read_checkpoint(old / spec['selected_checkpoint'])
    if cp['repairs'] == previous['repairs']:
        prior.unadvanced_parent(out, root, old, spec, cp, previous)
        return
    model, bound = retained(root, cp)
    need(model is not None and cp['base'] == previous['base'] and cp['repairs'][:-1] == previous['repairs']
         and cp['repairs'][-1]['sha256'] == model.sha256
         == sha((root / 'controller-outcome-proof-input.json').read_bytes()),
         'OUTCOME_INDEPENDENT_ALL32_PRIOR_DESCRIPTORS_AND_ONE_PROOF_INPUT')
    admission, _ = parent_admission(old, previous, spec)
    need(json.loads((root / 'outcome-constructor-admission.json').read_bytes()) == admission,
         'OUTCOME_INDEPENDENT_EXACT_CONSTRUCTOR_ADMISSION')
    validate_all(root, cp)
    boundary_cp = journal.read_checkpoint(root / 'book/predecessor-checkpoints' / (prior.OUTER + '.json.gz'))
    amendment = prior.FutureProjection(root, boundary_cp)
    znative = prior.retained_zogenix(root, out)
    native, _ = prior.retained_abiomed(root, cp, out)
    completion = prior.retained_completion(root, cp)
    cnative = timing.call('independent_chinook_source_hydration', hydrate_chinook, old, out)
    need((out / prior.CPRIVATE).read_bytes() == (root / prior.CPRIVATE).read_bytes(),
         'OUTCOME_INDEPENDENT_RETAINED_CHINOOK_HYDRATION_IDENTICAL')
    with prior.ZogenixCodec(prior.zogenix_evidence(root), znative), prior.InputCodec(prior.evidence(root)), completion, \
            prior.AbiomedCodec(prior.abiomed_evidence(root), native), \
            prior.ChinookCodec(prior.chinook_evidence(root), cnative), InputCodec(evidence(), bound):
        timing.call('canonical_all_history_financial_review', review_financial, out, root, old, spec)
        timing.call('own_origin_review', prior.qualify_origin, root, previous, out / 'independent-own-origin-qualification.json')
        timing.call('complete_input_and_outcome_review', review_certificate, root, old, spec,
                    out / 'uncertainty-certificate-review.json')
        value_hash, value = timing.call('common_basis_review', basis, root, cp, amendment=amendment)
    before = json.loads((old / 'common-factual-and-uncertainty-basis.json').read_bytes())
    require_exact_delta(before['value'], value, model)
    save(out / 'common-factual-and-uncertainty-basis.json', dict(sha256=value_hash, value=value))
    for name in (prior.PAYLOAD_NAME, prior.OVERLAY_NAME, prior.PROJECTION_NAME):
        need((root / name).read_bytes() == (old / name).read_bytes(), 'OUTCOME_ORIGINAL_AMENDMENT_BYTES')
    save(out / 'outcome-lineage-review.json', dict(status='EXACT_OWN_PROOF_REFINEMENT_SUFFIX_REVIEWED',
        all32_old_descriptors_preserved=True, original_five_models_and_factual_semantics_unchanged=True,
        exact_latest_predecessor_and_original_proof_boundary_preserved=True,
        source_parameters_and_trading_rules_unchanged=True, exactly_one_identity_proof_input=True,
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
