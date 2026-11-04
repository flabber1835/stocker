"""Own-book neutral input boundaries and the existing certified sensor gateway."""
from copy import deepcopy
import gzip
import json
from pathlib import Path

from full_system_benchmark import need, save
from full_system_core import hosted
from system_campaign_facts import sha
from system_campaign_pxd_pause import adoption

HERE = Path(__file__).parent
DATE_OVERLAY = 'alder-date-financial-overlay.json'
DATE_ADOPTION = 'date-input-adoption'
MODEL_ADOPTION = 'input-adoption'
INTEGRATION = 'system-campaign-uncertainty-integration-request.json'


def source_contract(cp):
    """Qualification is reusable only for the exact same six actual sources."""
    hashes = json.loads((HERE / INTEGRATION).read_bytes())['canonical_controller_sources']
    need(len(hashes) == 6 and all(cp['base']['sources'].get(n) == h for n, h in hashes.items()),
         'FINANCIAL_UNCERTAINTY_EXACT_SIX_QUALIFIED_CONTROLLER_SOURCES')
    need(cp['source_cursor'] == '2019-09-30' and cp['completed'] == 439
         and cp['sha256'] == '3c083bb55c27f611859cafcc9ad4868fb9d06039a71e3d1e2d698d5172aac68d',
         'FINANCIAL_UNCERTAINTY_EXACT_OWN_ROOT_PARENT')
    return hashes


def prepare_date(cp, out):
    from system_campaign_alder_date_v2 import AlderDateV2
    alder = AlderDateV2(HERE / 'system-campaign-alder-unresolved-date.json')
    alder.hydrate(out / 'hydrated-alder-unresolved-date.json')
    loaded = alder.overlay(cp, out / DATE_OVERLAY)
    return alder, loaded


def boundary(root, name, original, overlay, earliest):
    raw = (root / name / 'checkpoint.json.gz').read_bytes()
    cp = json.loads(gzip.decompress(raw))
    event = adoption(cp, original, sha((root / overlay).read_bytes()), earliest)
    need(json.loads((root / name / 'proof.json').read_bytes()) == dict(event=event,
         actual_checkpoint_gzip_sha256=sha(raw), original_outer_sha256=original['sha256'],
         financial_state_unchanged=True, financial_sessions_advanced=0),
         'FINANCIAL_UNCERTAINTY_EXACT_ACTUAL_NEUTRAL_BOUNDARY')
    return cp


def run(cp, out, args, rows, observer, execution):
    hosted()
    from research.pooled_vacancy_funding import backtest, journal
    from system_campaign_financial_resume import AdoptionGate
    from system_campaign_factual_run import SeededObservation
    from system_campaign_p02_retained_run import idempotent_dispatch, qualify_dispatch
    from system_campaign_uncertainty_facts import hydrate
    from system_campaign_financial_branches import overlay, evidence, Codec, Certificate, qualify
    from system_campaign_uncertainty_integration import AdmissionPause
    hashes = source_contract(cp)
    qualify(out, hashes)
    alder, loaded = prepare_date(cp, out)
    event_source = hydrate(alder.native, out / 'hydrated-uncertainty-event.json')
    date_gate = AdoptionGate(cp, out / 'book', out / DATE_ADOPTION, loaded.sha256, '2019-10-21')
    paused_observer = SeededObservation(out / 'admission-correlation-inputs.jsonl.gz', rows)
    with alder, idempotent_dispatch(alder):
        qualify_dispatch(alder, loaded, out)
        with date_gate, paused_observer, AdmissionPause() as pause:
            code = backtest.main(args + ['--repair-overlay', str(out / DATE_OVERLAY)])
        need(code == 0 and pause.paused and pause.calls == 0 and date_gate.accepted,
             'FINANCIAL_UNCERTAINTY_DATE_INPUT_ZERO_SESSION_ADMISSION')
        current = boundary(out, DATE_ADOPTION, cp, DATE_OVERLAY, '2019-10-21')
        need(journal.read_checkpoint(out / 'book/checkpoint.json.gz') == current,
             'FINANCIAL_UNCERTAINTY_ACTUAL_DATE_SUCCESSOR')
        need(gzip.decompress((out / 'admission-correlation-inputs.jsonl.gz').read_bytes()) == b''.join(rows),
             'FINANCIAL_UNCERTAINTY_ZERO_NEW_OBSERVATIONS_AT_PAUSE')
        path = overlay(current, out)
        codec = Codec(evidence(out))
        with codec:
            for cursor, predecessor in ((current['source_cursor'], '0' * 64),
                                        ('2019-10-22', current['run']['checkpoint_sha256'])):
                try:
                    backtest.load_repair(path, resume_session=cursor, predecessor_checkpoint_sha256=predecessor)
                except ValueError:
                    pass
                else:
                    raise ValueError('REFUSED_FINANCIAL_UNCERTAINTY_TYPED_PARSER_FALSIFIER')
            model = backtest.load_repair(path, resume_session=current['source_cursor'],
                                        predecessor_checkpoint_sha256=current['run']['checkpoint_sha256'])
            gate = AdoptionGate(current, out / 'book', out / MODEL_ADOPTION, model.sha256, '2019-10-22')
            certificate = Certificate(out, codec, alder.native, hashes, event_source=event_source)
            save(out / 'own-uncertainty-admission.json', dict(arm='P07', root_parent_sha256=cp['sha256'],
                date_input_successor_sha256=current['sha256'], qualified_controller_sources=hashes,
                reused_frozen_controller_and_math_sources=True, new_branch_observer_qualification=True,
                diagnostic_state_adopted=False,
                proof_kind='EXHAUSTIVE_REACHABLE_CANONICAL_DECISION_INVARIANCE',
                owned_or_ordered_right_valuation_authorized=False, representative_is_not_a_valuation=True))
            with gate, certificate, observer, execution:
                code = backtest.main(args + ['--repair-overlay', str(path)])
            boundary(out, MODEL_ADOPTION, current, path.name, '2019-10-22')
    return code


def review(cp, evidence_root, out):
    hosted()
    from system_campaign_uncertainty_facts import hydrate
    from system_campaign_financial_branches import overlay, evidence, Codec, parse, review as review_certificate
    source_contract(cp)
    alder, _ = prepare_date(cp, out)
    hydrate(alder.native, out / 'hydrated-uncertainty-event.json')
    for name in ('hydrated-alder-unresolved-date.json', DATE_OVERLAY, 'hydrated-uncertainty-event.json'):
        need((out / name).read_bytes() == (evidence_root / name).read_bytes(),
             'FINANCIAL_UNCERTAINTY_INDEPENDENT_EXACT_DATE_AND_EVENT_INPUT_BYTES')
    current = boundary(evidence_root, DATE_ADOPTION, cp, DATE_OVERLAY, '2019-10-21')
    path = overlay(current, out)
    need(path.read_bytes() == (evidence_root / path.name).read_bytes(),
         'FINANCIAL_UNCERTAINTY_INDEPENDENT_EXACT_OWN_TYPED_INPUT')
    parse(path, resume_session=current['source_cursor'], predecessor_checkpoint_sha256=current['run']['checkpoint_sha256'],
          expected_evidence=evidence(out))
    model_cp = boundary(evidence_root, MODEL_ADOPTION, current, path.name, '2019-10-22')
    with Codec(evidence(evidence_root)):
        review_certificate(evidence_root, out / 'uncertainty-certificate-review.json')
    save(out / 'own-uncertainty-input-boundaries-review.json', dict(passed=True,
        root_parent_sha256=cp['sha256'], date_successor_sha256=current['sha256'], model_successor_sha256=model_cp['sha256'],
        both_actual_gzip_boundaries_neutral=True, complete_input_bytes_independently_reconstructed=True,
        no_qualifier_state_adopted=True, financial_sessions_reexecuted=0))
