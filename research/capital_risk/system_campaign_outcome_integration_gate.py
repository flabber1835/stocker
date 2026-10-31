"""Hosted six-input and capture integration; zero financial sessions."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import digest, sha
from system_campaign_uncertainty_math import Interval
from system_campaign_outcome_input import MODE, parse
from system_campaign_outcome_facts import evidence
from system_campaign_outcome_frame import qualify as qualify_frame
from system_campaign_outcome_proof import commitment
from system_campaign_outcome_sensor import SensorCertificate
from system_campaign_chinook_sensor import SensorCertificate as OldSensor


def must_refuse(function, label):
    try:
        function()
    except ValueError:
        return
    raise ValueError('REFUSED_OUTCOME_INTEGRATION_MISSING_' + label)


def qualify(out, old, cp, objects, loaded, codec, bound, certificate, request):
    hosted()
    from research.pooled_input_support import inputs
    from research.pooled_input_support.inputs import Packet
    from research.pooled_vacancy_funding import backtest
    from sentinel.controller import median5, champion_config
    need(loaded is certificate.proof_model and loaded.proof_mode == MODE
         and loaded.sha256 in {v.sha256 for v in codec.objects},
         'OUTCOME_ACTUAL_LOADED_MODEL_AND_CAPTURE_ADAPTER')
    for name in ('witness', 'values', 'advance', 'append', 'relevant', '__enter__'):
        need(getattr(SensorCertificate, name) is getattr(OldSensor, name),
             'OUTCOME_ALL_ORIGINAL_VALUE_WITNESS_POSITION_JOURNAL_RUNTIME_METHODS')
    actions = inputs.load_actions(Path('/frozen/bundle'))
    count = 0
    for day in (bound['next_session'], '2023-08-11'):
        packet = Packet(day, (), {}, {}, 1., {}, tuple(actions.terminal.get(day, ())), ())
        before = digest(asdict(packet))
        value = packet
        for obj in objects:
            value = backtest.apply_repair(value, obj)
        fixed = backtest.apply_repair(value, loaded)
        need(fixed is value and digest(asdict(packet)) == before,
             'OUTCOME_ACTUAL_FROZEN_PACKET_IDENTITY_AND_ORIGINAL_IMMUTABILITY')
        count += 1
    for cursor, inner in ((bound['session'], '0' * 64), (bound['next_session'], bound['inner_sha256'])):
        must_refuse(lambda: parse(out / 'controller-outcome-proof-input.json',
            resume_session=cursor, predecessor_checkpoint_sha256=inner,
            expected_evidence=evidence(), boundary=bound), 'WRONG_PREDECESSOR_OR_CONSUMED_SESSION')
    raw = (old / 'uncertainty-refusal.json').read_bytes()
    need(sha(raw) == request['actual_refusal_sha256'], 'OUTCOME_INTEGRATION_EXACT_AUTHENTICATED_REFUSAL')
    refusal = json.loads(raw)
    state = median5.fresh(champion=True)
    state.update(refusal['before'])
    state['last_session'] = refusal['session']
    kwargs = dict(refusal['scalar_inputs'], state=state)
    bounds = {name: Interval(*value) if value is not None else None
              for name, value in refusal['intervals'].items()}
    qualify_frame(request['canonical_controller_sources'], out / 'outcome-frame-qualification.json', kwargs, bounds)
    probe = SensorCertificate.__new__(SensorCertificate)
    probe.original_recover, probe.proof_model = champion_config.recover, loaded
    probe.bounds, probe.material = bounds, deepcopy(refusal['material'])
    probe.math = SimpleNamespace(snapshot=lambda: dict(component_only=True, financial_checkpoint=False))
    probe.pending, probe.out = None, out
    result = probe.recover(**kwargs)
    need(probe.pending['proof_input_sha256'] == loaded.sha256
         and probe.pending['proof_mode'] == MODE
         and probe.pending['complete_recovery_inputs'] == kwargs
         and probe.pending['comparisons']['input_sha256'] == commitment(kwargs)
         and probe.pending['comparisons']['ordinary_result_sha256'] == commitment(result)
         and probe.pending['comparisons']['all_complete_results_equal'] is True,
         'OUTCOME_ACTUAL_NEW_CAPTURE_ADAPTER_FULL_INPUT_AND_RESULT')
    save(out / 'outcome-integration-qualification.json', dict(
        status='ACTUAL_SIX_INPUT_CAPTURE_AND_FRAME_INTEGRATION_PASSED',
        actual_identity_packets=count, all_original_methods_inherited=True,
        actual_typed_model_and_full_call_capture=True, actual_wrong_predecessor_and_consumed_refusals=True,
        actual_canonical_frame_dependency_qualified=True,
        parent_checkpoint_sha256=cp['sha256'], proof_input_sha256=loaded.sha256,
        constructed_component_state_not_a_financial_checkpoint=True,
        financial_sessions_advanced=0, production_contacted=False))
