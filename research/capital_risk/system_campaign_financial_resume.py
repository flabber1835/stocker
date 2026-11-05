"""Shared own-checkpoint financial resume using the existing hosted engine."""
import argparse
import base64
from contextlib import nullcontext
from copy import deepcopy
import gzip
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import traceback
import zipfile

from full_system_benchmark import need, save
from full_system_core import arguments, hosted
from full_system_trials_job import command, seal
from alpaca_fit_job import stopped_run, StopUnknown
from probe import check_context, memory_bytes, FORBIDDEN_CREDENTIALS
from stage import SECRET
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file
from system_campaign_facts import sha
from system_campaign_pxd_pause import adoption
from system_campaign_discovery_context import require_strict_checkpoint
from system_campaign_parallel_discovery import check_parent
from system_campaign_parallel_discovery_parent import admit as transport_admit
from system_campaign_parallel_discovery_run import retained_inputs
from system_campaign_parallel_discovery_job import stage_valid
from system_campaign_variants import build
from system_campaign_factual_run import (
    correlation_seed, SeededObservation, preserve_tails, verify_correlation,
)
from system_campaign_readonly import reader, review as readonly_review
from system_campaign_acceleration import Execution
import system_campaign_factual_admit as crypto
from system_campaign_financial_partial import (
    admit as admit_partial, monthly_reproduction, ROOTS, root_spec, validate_root_spec,
    financial_inputs,
    ADMISSIONS, COMPLETED_ADMISSIONS, FRESH_FORMAT, FRESH_REQUEST, initial_reporting_seed, review_name, full_target,
    INITIAL_PREFIX_TARGETS, initial_prefix_seed,
)

HERE = Path(__file__).parent
REQUEST = 'system-campaign-factual-request.json'
PARENTS = 'system-campaign-parallel-discovery-parents.json'
PRIOR = 'system-campaign-parallel-discovery-request-001.json'
PRIOR_SHA = '863f6c7983fc2cdc1a86bd58a9c4987744d180e8bb56568608eda77d29f85fcd'
ARMS = ('P00', 'P03', 'P04', 'P05', 'P06', 'P07', 'P09', 'P10', 'P11')
SELECTED_ARMS = ('P05',)
PARTIALS = 'system-campaign-financial-partials.json'
PREFIX = 'system-campaign-financial-correlation-prefix.json'
P10_QUALIFICATION = 'system-campaign-p10-ahl2-retained-qualification-001.json'
P10_QUALIFICATION_SHA = '006ad9813c20b2dba14ee4acf2ad8219b59d1a63a2d0a4f220f43a1c68e3d180'
SCHEMA = 'research.system-campaign-accurate-resume-request/161'
EXECUTION_MODE = 'OWN_ADMITTED_FINANCIAL_CONTINUATION'
WORKFLOW = '.github/workflows/capital-system-campaign-factual-suffix.yml'


def factual_overlay_needed(spec):
    from system_campaign_financial_additional_sensor import unchanged_phase
    if unchanged_phase(spec):
        return False
    from system_campaign_financial_uncertainty import unchanged_input_phase, own_unchanged_input_phase
    if own_unchanged_input_phase(spec):
        return False
    return not (spec['arm'] == 'P07' and unchanged_input_phase(spec)) and (
        'root_admission' in spec or spec['arm'] in ('P07', 'P10'))


def expected_request():
    from system_campaign_financial_additional_sensor import unchanged_phase as additional_unchanged_phase
    from system_campaign_financial_future import WITNESS_SCOPES, OWN_CASH_CATALOG, ORIGINAL_ORDINARY_SOURCES, ORIGINAL_DELIVERY_SOURCES, ORIGINAL_DELIVERY_PHASES, ORIGINAL_ORDINARY_PHASES, COMBINED_PHASES, FUTURE_LITERAL_PHASES, CASH_PHASES, SUPPLEMENTAL_PHASES, original_composite_source_names
    from system_campaign_financial_uncertainty import unchanged_input_phase, validate_retained_admission_metadata, own_policy_source_names, own_policy_phase, own_model_declaration, own_unchanged_input_phase
    financial = EXECUTION_MODE == 'OWN_ADMITTED_FINANCIAL_CONTINUATION'
    reporting = EXECUTION_MODE == 'READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION'
    witnesses = EXECUTION_MODE == 'READONLY_FROZEN_SOURCE_WITNESSES'
    need(sum((financial, reporting, witnesses)) == 1, 'RESUME_ONE_EXPLICIT_REQUEST_EXECUTION_MODE')
    need(not any(a in COMPLETED_ADMISSIONS for a in SELECTED_ARMS), 'RESUME_CLOSED_COMPLETE_ARM_CANNOT_BE_REEXECUTED')
    if witnesses:
        need(all(a in WITNESS_SCOPES for a in SELECTED_ARMS), 'RESUME_ONLY_DECLARED_ACTIVE_SOURCE_QUERIES')
    if financial and 'P07' in SELECTED_ARMS:
        retained = root_spec('P07')
        if retained['measured_closes'] >= 503:
            validate_retained_admission_metadata(retained)
    if financial:
        for arm in SELECTED_ARMS:
            own = own_policy_phase(root_spec(arm))
            if own is not None and own['mode'] == 'RETAINED':
                validate_retained_admission_metadata(root_spec(arm))
    origins = {}
    if reporting:
        targets = json.loads((HERE / PARTIALS).read_bytes())['arms']
        for arm in SELECTED_ARMS:
            target = targets[arm]
            full_target(target)
            if arm in INITIAL_PREFIX_TARGETS and arm not in ADMISSIONS:
                origins[arm] = initial_prefix_seed(target)
            elif arm == 'P00' and arm not in ADMISSIONS:
                origins[arm] = initial_reporting_seed(target)
            else:
                seed = root_spec(arm)
                need(target['measured_closes'] > seed['measured_closes']
                     and target['monthly_seed_root_admission_sha256'] == seed['root_admission_sha256'],
                     'RESUME_ONLY_NEW_SUFFIX_FROM_CURRENT_ADMITTED_REPORTING_SEED')
    need(sha256_file(HERE / PRIOR) == PRIOR_SHA, 'RESUME_FROZEN_PRIOR_REQUEST')
    prior = json.loads((HERE / PRIOR).read_bytes())['sources']
    need(len(prior) == 383 and all(sha256_file(HERE / n) == h for n, h in prior.items()),
         'RESUME_ALL383_OLD_DRIVER_BYTES_UNCHANGED')
    names = (*prior, 'system_campaign_financial_resume.py', 'ephemeral_runner_capacity.py',
             'system_campaign_stage_transport.py', 'stage-request.json',
             'transfer-requirements.lock', 'wwe-transfer-requirements.lock', PREFIX,
             'system_campaign_p10_ahl2_input.py', 'system_campaign_p10_ahl2_contract.py',
             'system-campaign-p10-ahl2-predecessor-001.json', P10_QUALIFICATION,
             'system_campaign_financial_partial.py', PARTIALS, ROOTS, 'system_campaign_financial_future.py',
             'system_campaign_financial_uncertainty.py', 'system_campaign_financial_branches.py',
             'system_campaign_financial_additional_sensor.py', 'system_campaign_financial_additional_sensor_runtime.py',
             'system_campaign_financial_projection.py', 'system-campaign-own-future-projection.json',
             'system_campaign_financial_distribution_source.py', 'system-campaign-compound-source-witness-scopes.json',
             'system_campaign_financial_distribution_source_v1.py', 'system_campaign_financial_compound_input.py',
             'system_campaign_financial_compound_runtime.py', 'system-campaign-compound-input-facts.json',
             'system_campaign_financial_compound_dispatch.py', 'system_campaign_financial_compound_runtime_v2.py',
             'system_campaign_financial_compound_input_v2.py', 'system_campaign_financial_compound_v2_support.py',
             'system_campaign_financial_compound_ordinary_v2.py', 'system_campaign_financial_ordinary_observer_v1.py',
             'system_campaign_financial_distribution_source_v2.py', 'system-campaign-compound-input-v2-facts.json',
             'system_campaign_financial_distribution_standard.py',
             'system_campaign_financial_distribution_standard_runtime.py',
             'system-campaign-standard-distribution-input-facts.json',
             'system-campaign-unconsumed2024-cash-calendar-terminal-facts.json',
             'system-campaign-array-terminal-facts.json', 'system_campaign_array_facts.py',
             'system-campaign-tableau-terminal-facts.json', 'system_campaign_tableau_facts.py',
             'system-campaign-distribution-facts.json', 'system_campaign_distribution_facts.py',
             'system-campaign-tgi-cash-facts.json', 'system_campaign_tgi_facts.py',
             'system_campaign_point_growth.py',
             'system-campaign-financial-branch-contract.json', OWN_CASH_CATALOG, FRESH_REQUEST,
             *own_policy_source_names(), *original_composite_source_names(),
             *(term['retained_original_legal_record']['catalog_file']
               for term in json.loads((HERE / OWN_CASH_CATALOG).read_bytes())['terms']
               if 'retained_original_legal_record' in term),
             *(name for registry in (ORIGINAL_ORDINARY_SOURCES, ORIGINAL_DELIVERY_SOURCES, ORIGINAL_DELIVERY_PHASES, ORIGINAL_ORDINARY_PHASES, COMBINED_PHASES)
               for plans in registry.values() for plan in plans for name in (plan[0]+'.py',plan[2])),
             *(plan[2] for plan in FUTURE_LITERAL_PHASES.values()), *(plan[0] for plan in CASH_PHASES.values()),
             *(name for plans in SUPPLEMENTAL_PHASES.values() for plan in plans
               for name in (plan[0] + '.py', plan[3])))
    models = {'P07': dict(input_schema='research.leadership-branch-uncertainty-input/1',
        contract_sha256=sha256_file(HERE / 'system-campaign-financial-branch-contract.json'),
        every_reachable_canonical_decision_must_match=True, original_strict_guard_unchanged=True)}
    if financial:
        for arm in SELECTED_ARMS:
            own = own_policy_phase(root_spec(arm))
            if own is not None:
                models[arm] = own_model_declaration(own)
    if financial:
        from system_campaign_financial_additional_sensor import phase as additional_phase, declaration
        for arm in SELECTED_ARMS:
            additional = additional_phase(root_spec(arm))
            if additional is not None:
                models[arm] = declaration(additional, sha256_file(HERE / 'system-campaign-qualified-own-uncertainty-input-facts.json'))
    return dict(schema=SCHEMA, campaign='system-optimization-002', arms=list(SELECTED_ARMS),
                execution_mode=EXECUTION_MODE, new_origin=False,
                financial_resume_authorized=financial, readonly_partial_review=reporting,
                readonly_source_witnesses=witnesses,
                source_witness_scopes={a: deepcopy(WITNESS_SCOPES[a]) for a in SELECTED_ARMS} if witnesses else {},
                diagnostic_state_adopted=False,
                arm_inputs={a: dict(new_factual_overlay=financial and not (
                    a == 'P07' and unchanged_input_phase(root_spec(a)) or own_unchanged_input_phase(root_spec(a)) or additional_unchanged_phase(root_spec(a))), restored_correlation=False) for a in SELECTED_ARMS},
                financial_source_changed=False, full_measurement_start='2018-01-02',
                full_measurement_end='2026-07-31', full_measured_closes=2156,
                predecessors_sha256=sha256_file(HERE / PARENTS),
                selected_partials_sha256=sha256_file(HERE / PARTIALS),
                admitted_financial_parents_sha256=sha256_file(HERE / ROOTS),
                admitted_checkpoints={a: root_spec(a)['outer_sha256'] for a in SELECTED_ARMS if a not in origins},
                initial_reporting_origins=origins,
                selected_research_models=models,
                protocol_sha256=sha256_file(HERE / 'system-campaign-search-protocol.json'),
                workflow_sha256=sha256_file(HERE.parent.parent / WORKFLOW),
                sources={n: sha256_file(HERE / n) for n in sorted(set(names))},
                financial_wait_seconds=10800, preflight_wait_seconds=1200,
                review_wait_seconds=2700, artifact_retention_days=7,
                maximum_parallel_financial_workers=len(SELECTED_ARMS) if financial else 0,
                maximum_parallel_readonly_workers=0 if financial else len(SELECTED_ARMS),
                production_contacted=False)


def request_authority(request):
    flags = tuple(request.get(k, False) for k in
                  ('financial_resume_authorized', 'readonly_partial_review', 'readonly_source_witnesses'))
    modes = {
        (True, False, False): 'OWN_ADMITTED_FINANCIAL_CONTINUATION',
        (False, True, False): 'READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION',
        (False, False, True): 'READONLY_FROZEN_SOURCE_WITNESSES',
    }
    return all(type(v) is bool for v in flags) and flags in modes and request['execution_mode'] == modes[flags]


def source_request_bindings(request, spec):
    """Workflow bytes were verified by the host, outside this immutable mount."""
    from system_campaign_financial_future import WITNESS_SCOPES
    need(request_authority(request) and request['readonly_source_witnesses'] is True
         and request['schema'] == SCHEMA and request['arms'] == list(SELECTED_ARMS)
         and request['source_witness_scopes'] == {a: WITNESS_SCOPES[a] for a in SELECTED_ARMS}
         and spec['arm'] in SELECTED_ARMS
         and request['admitted_checkpoints'][spec['arm']] == spec['outer_sha256']
             == WITNESS_SCOPES[spec['arm']]['parent_outer_sha256']
         and request['admitted_financial_parents_sha256'] == sha256_file(HERE / ROOTS)
         and request['sources']['system_campaign_financial_resume.py'] == sha256_file(Path(__file__))
         and request['sources']['system_campaign_financial_future.py']
             == sha256_file(HERE / 'system_campaign_financial_future.py'),
         'RESUME_SOURCE_WITNESS_EXACT_WORKER_REQUEST_BINDINGS')


class SeedPaths:
    """Change only the observation lookup; financial journals stay with the parent."""
    def __init__(self, old, capture):
        self.old, self.capture = old, capture

    def __truediv__(self, name):
        return self.capture if name == 'correlation-inputs.jsonl.gz' else self.old / name


def prefix_descriptor():
    value = json.loads((HERE / PREFIX).read_bytes())
    need(value['schema'] == 'research.system-campaign-correlation-prefix-source/1'
         and value['arm'] == 'P04' and value['auxiliary_observations_only'] is True
         and value['auxiliary_financial_state_adopted'] is False,
         'RESUME_AUXILIARY_OBSERVATIONS_ONLY')
    return value


def prefix_rows(old, cp, capture, descriptor):
    need(cp['sha256'] == descriptor['financial_parent_outer_sha256']
         and cp['completed'] == descriptor['financial_parent_completed']
         and cp['source_cursor'] == descriptor['financial_parent_cursor']
         and cp['base'] == descriptor['transport']['base']
         and sha256_file(old / 'source-bindings.json') == descriptor['transport']['source_binding_sha256'],
         'RESUME_PREFIX_EXACT_CURRENT_FINANCIAL_PARENT_AND_SOURCE')
    rows = correlation_seed(SeedPaths(old, capture), cp)
    expected = descriptor['prefix']
    need(len(rows) == expected['rows'] and sha(b''.join(rows)) == expected['raw_sha256']
         and json.loads(rows[-1])['session'] == expected['through'] == cp['source_cursor'],
         'RESUME_EXACT_COMMITTED_OBSERVATION_PREFIX')
    return rows


def prefix_provenance(descriptor):
    return dict(schema='research.restored-correlation-observations/1',
        source_descriptor_sha256=sha256_file(HERE / PREFIX),
        financial_parent_outer_sha256=descriptor['financial_parent_outer_sha256'],
        auxiliary_artifact_id=descriptor['transport']['artifact_id'],
        prefix=descriptor['prefix'], auxiliary_financial_state_adopted=False,
        future_observations_included=False, financial_sessions_advanced=0)


def prepare_prefix(old, auxiliary, capsule):
    descriptor = prefix_descriptor()
    cp = json.loads(gzip.decompress((old / 'book/checkpoint.json.gz').read_bytes()))
    member = descriptor['observation_member']
    capture = auxiliary / member['name']
    need(capture.stat().st_size == member['bytes'] and sha256_file(capture) == member['sha256']
         and (auxiliary / 'source-bindings.json').read_bytes() == (old / 'source-bindings.json').read_bytes(),
         'RESUME_AUTHENTICATED_OWN_AUXILIARY_OBSERVATION_MEMBER')
    rows = prefix_rows(old, cp, capture, descriptor)
    capsule.mkdir(mode=0o700)
    (capsule / 'correlation-inputs.jsonl.gz').write_bytes(gzip.compress(b''.join(rows), mtime=0))
    save(capsule / 'provenance.json', prefix_provenance(descriptor))
    return capsule


def seed_rows(old, cp, spec, capsule=Path('/correlation-prefix')):
    if spec['arm'] != 'P04' or spec.get('archive_format') == 'FINANCIAL_RESUME_FIVE_MEMBER_ZIP/1':
        return correlation_seed(old, cp)
    descriptor = prefix_descriptor()
    need({p.name for p in capsule.iterdir()} == {'correlation-inputs.jsonl.gz', 'provenance.json'}
         and json.loads((capsule / 'provenance.json').read_bytes()) == prefix_provenance(descriptor),
         'RESUME_EXACT_OBSERVATION_CAPSULE_PROVENANCE')
    capture = capsule / 'correlation-inputs.jsonl.gz'
    rows = prefix_rows(old, cp, capture, descriptor)
    need(gzip.decompress(capture.read_bytes()) == b''.join(rows), 'RESUME_NO_FUTURE_OBSERVATIONS_IN_CAPSULE')
    return rows


class AdoptionGate:
    """Observe the actual neutral input boundary before permitting an advance."""
    def __init__(self, cp, book, out, overlay_sha256, earliest):
        self.original = deepcopy(cp)
        self.path, self.out = (book / 'checkpoint.json.gz').resolve(), out
        self.overlay_sha256, self.earliest = overlay_sha256, earliest
        self.accepted = False

    def write(self, path, saved):
        if not self.accepted:
            need(Path(path).resolve() == self.path, 'RESUME_ADOPTION_ONLY_CURRENT_CHECKPOINT')
            if saved == self.original:
                return self.original_write(path, saved)
            event = adoption(saved, self.original, self.overlay_sha256, self.earliest)
            self.original_write(path, saved)
            raw = Path(path).read_bytes()
            need(json.loads(gzip.decompress(raw)) == saved, 'RESUME_ACTUAL_ADOPTION_GZIP')
            self.out.mkdir()
            (self.out / 'checkpoint.json.gz').write_bytes(raw)
            save(self.out / 'proof.json', dict(event=event, actual_checkpoint_gzip_sha256=sha(raw),
                original_outer_sha256=self.original['sha256'], financial_state_unchanged=True,
                financial_sessions_advanced=0))
            self.accepted = True
            return
        return self.original_write(path, saved)

    def advance(self, *args, **kwargs):
        need(self.accepted, 'RESUME_NEUTRAL_ADOPTION_REQUIRED_BEFORE_ADVANCE')
        return self.original_advance(*args, **kwargs)

    def __enter__(self):
        hosted()
        from research.pooled_vacancy_funding import backtest, runtime
        self.backtest, self.runtime = backtest, runtime
        self.original_write, self.original_advance = backtest.write_checkpoint, runtime.advance
        backtest.write_checkpoint, runtime.advance = self.write, self.advance
        return self

    def __exit__(self, *args):
        self.backtest.write_checkpoint, self.runtime.advance = self.original_write, self.original_advance


def p10_document(cp):
    from system_campaign_p10_ahl2_contract import specification
    from system_campaign_p10_ahl2_input import expected_document
    retained = specification()
    need(cp['base'] == retained['base'] and cp['source_cursor'] < '2019-02-14'
         and sha256_file(HERE / P10_QUALIFICATION) == P10_QUALIFICATION_SHA,
         'RESUME_P10_EXACT_OWN_BASE_AND_RETAINED_INPUT_QUALIFICATION')
    document = expected_document(retained)
    document['predecessor_checkpoint_sha256'] = cp['run']['checkpoint_sha256']
    return document, retained


def p10_overlay(cp, out):
    from research.pooled_input_support import inputs
    from research.pooled_input_support.adapter import Packet
    from research.pooled_vacancy_funding import backtest
    from system_campaign_discovery_context import material
    from system_campaign_p10_ahl2_input import source_witness, packet_change
    document, retained = p10_document(cp)
    witness = source_witness(retained)
    save(out / 'ahl2-source-subset.json', witness)
    path = out / 'ahl2-terminal-overlay.json'
    save(path, document)
    loaded = backtest.load_repair(path, resume_session=cp['source_cursor'],
        predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    actions = inputs.load_actions(Path('/frozen/bundle'))
    probes = []
    for day in ('2019-02-14', '2019-02-15'):
        packet = Packet(day, (), {}, {}, 1., {}, tuple(actions.terminal.get(day, ())), ())
        original = deepcopy(packet)
        changed = backtest.apply_repair(packet, loaded)
        probes.append(packet_change(packet, changed, spec=retained, material=material))
        need(packet == original, 'RESUME_P10_ORIGINAL_NATIVE_PACKET_UNCHANGED')
        if day == '2019-02-14':
            bad = deepcopy(document)
            bad['suppress'][0]['term_sha256'] = '0' * 64
            falsifier = out / 'ahl2-wrong-native-falsifier.json'
            save(falsifier, bad)
            wrong = backtest.load_repair(falsifier, resume_session=cp['source_cursor'],
                predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
            try:
                backtest.apply_repair(packet, wrong)
            except ValueError as error:
                need(str(error).startswith('suppressed original terminal differs:') and packet == original,
                     'RESUME_P10_ACTUAL_NATIVE_FALSIFIER_AND_IMMUTABILITY')
            else:
                raise ValueError('REFUSED_RESUME_P10_NATIVE_FALSIFIER_ACCEPTED')
        else:
            term, = [v for v in changed.terminal if v.security_id == retained['native_term']['security_id']]
            need(term.completeness(1)[0], 'RESUME_P10_COMPLETE_ORDINARY_CASH_REPLACEMENT')
    save(out / 'ahl2-input-qualification.json', dict(terminal_only_packet_probes=probes,
        source_subset_sha256=sha256_file(out / 'ahl2-source-subset.json'),
        retained_qualification_descriptor_sha256=P10_QUALIFICATION_SHA,
        wrong_native_preimage_refused=True, no_diagnostic_state_adopted=True,
        financial_sessions_advanced=0, financial_source_changed=False))
    return path, loaded


def overlay_contract(arm):
    return {'P07': ('p07-reviewed-terminal-overlay.json', '2019-07-30'),
            'P10': ('ahl2-terminal-overlay.json', '2019-02-14')}[arm]


def combine_documents(documents, cp):
    need(documents and all(set(d) == {'schema', 'predecessor_checkpoint_sha256', 'source_evidence', 'suppress', 'add'}
         and d['schema'] == 'terminal-repair/1'
         and d['predecessor_checkpoint_sha256'] == cp['run']['checkpoint_sha256'] for d in documents),
         'RESUME_COMPOSE_ONLY_EXACT_OWN_ORDINARY_DOCUMENTS')
    combined = dict(schema='terminal-repair/1', predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    for field in ('source_evidence', 'suppress', 'add'):
        combined[field] = [deepcopy(row) for d in documents for row in d[field]]
    need(all(len({(r['session'], r['security_id']) for r in combined[field]}) == len(combined[field])
         for field in ('suppress', 'add')), 'RESUME_NO_DUPLICATE_TERMINAL_INPUT_KEYS')
    return combined


def p07_overlay(cp, out):
    from system_campaign_array_facts import ArrayFacts
    from system_campaign_tableau_facts import TableauFacts
    from research.pooled_vacancy_funding.repair import load_repair
    facts = []
    documents = []
    for name, cls, catalog in (
            ('array', ArrayFacts, 'system-campaign-array-terminal-facts.json'),
            ('tableau', TableauFacts, 'system-campaign-tableau-terminal-facts.json')):
        codec = cls('/driver/' + catalog)
        codec.hydrate(out / ('hydrated-' + name + '-terminal-catalog.json'))
        path = out / (name + '-terminal-overlay.json')
        codec.overlay(cp, path)
        documents.append(json.loads(path.read_bytes()))
        facts.append((name, codec))
    path = out / overlay_contract('P07')[0]
    save(path, combine_documents(documents, cp))
    loaded = load_repair(path, resume_session=cp['source_cursor'],
                         predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    for name, codec in facts:
        codec.qualify(loaded, out / (name + '-input-qualification.json'))
    return path, loaded


def qualified_overlay(cp, out, spec):
    from system_campaign_financial_compound_dispatch import selected, initial_context
    compound = selected(cp, spec['arm']) if 'root_admission' in spec else None
    if compound is not None:
        overlay, loaded = compound.prepare(cp, out, spec['arm'])
        return ['--repair-overlay', str(overlay)], initial_context(cp, out, spec, loaded)
    if 'root_admission' in spec:
        from system_campaign_financial_future import prepare
        overlay, loaded = prepare(cp, out, spec['arm'])
        return ['--repair-overlay', str(overlay)], AdoptionGate(cp, out / 'book',
            out / 'input-adoption', loaded.sha256, loaded.earliest_affected_session)
    if spec['arm'] not in ('P07', 'P10'):
        return [], nullcontext()
    from research.pooled_vacancy_funding.repair import load_repair
    name, earliest = overlay_contract(spec['arm'])
    overlay = out / name
    if spec['arm'] == 'P07':
        actual, loaded = p07_overlay(cp, out)
        need(actual == overlay, 'RESUME_P07_EXACT_OVERLAY_PATH')
    else:
        actual, loaded = p10_overlay(cp, out)
        need(actual == overlay, 'RESUME_P10_EXACT_OVERLAY_PATH')
    need(loaded.earliest_affected_session == earliest, 'RESUME_FIRST_AFFECTED_PUBLICATION')
    for cursor, predecessor in ((cp['source_cursor'], '0' * 64),
                                (earliest, cp['run']['checkpoint_sha256'])):
        try:
            load_repair(overlay, resume_session=cursor, predecessor_checkpoint_sha256=predecessor)
        except ValueError:
            pass
        else:
            raise ValueError('REFUSED_RESUME_ORDINARY_INPUT_PARSER_FALSIFIER')
    return ['--repair-overlay', str(overlay)], AdoptionGate(cp, out / 'book',
        out / 'input-adoption', loaded.sha256, earliest)


def review_adoption(evidence, cp, spec):
    root = evidence / 'input-adoption'
    raw = (root / 'checkpoint.json.gz').read_bytes()
    saved = json.loads(gzip.decompress(raw))
    if 'root_admission' in spec:
        from system_campaign_financial_future import OVERLAY, review_input
        name, earliest = OVERLAY, review_input(cp, evidence, spec['arm'])
    else:
        name, earliest = overlay_contract(spec['arm'])
    event = adoption(saved, cp, sha256_file(evidence / name), earliest)
    if spec['arm'] == 'P07' and 'root_admission' not in spec:
        documents = [json.loads((evidence / (n + '-terminal-overlay.json')).read_bytes()) for n in ('array', 'tableau')]
        need(json.loads((evidence / name).read_bytes()) == combine_documents(documents, cp),
             'RESUME_REVIEW_EXACT_P07_COMBINED_ORDINARY_INPUT')
    if spec['arm'] == 'P10' and 'root_admission' not in spec:
        need(json.loads((evidence / name).read_bytes()) == p10_document(cp)[0],
             'RESUME_REVIEW_EXACT_P10_ORDINARY_INPUT_REBINDING')
    need(json.loads((root / 'proof.json').read_bytes()) == dict(event=event,
         actual_checkpoint_gzip_sha256=sha(raw), original_outer_sha256=cp['sha256'],
         financial_state_unchanged=True, financial_sessions_advanced=0),
         'RESUME_INDEPENDENT_NEUTRAL_ADOPTION_REVIEW')


def strict_parent(value, spec):
    require_strict_checkpoint(value)
    complete = full_target(spec)
    need(spec['arm'] in ARMS and (0 < spec['measured_closes'] < 2156 or
         (complete and EXECUTION_MODE == 'READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION')),
         'RESUME_ONLY_OWN_UNFINISHED_FINANCIAL_PARENT')
    check_parent(value, spec)
    return value


def following_session(cp, spec, wanted):
    index = wanted.index(cp['source_cursor'])
    if index + 1 < len(wanted):
        need(not full_target(spec), 'RESUME_COMPLETE_TARGET_ONLY_AT_AXIS_END')
        return wanted[index + 1]
    need(full_target(spec) and cp['completed'] == 2156 and cp['source_cursor'] == '2026-07-31'
         and EXECUTION_MODE == 'READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION',
         'RESUME_ONLY_READONLY_COMPLETE_REPORTING_BOUNDARY')
    return '2026-08-03'


def successful_stop(value):
    return (value.get('stopped') is True and type(value.get('exit_code')) is int
            and value['exit_code'] == 0 and value.get('oom_killed') is False)


def complete_review(worker, reviewer, proof):
    return (successful_stop(worker) and successful_stop(reviewer) and proof.get('complete') is True
            and proof.get('counts') == {'formation': 126, 'daily': 2156}
            and proof.get('all_prefixes_verified') is True
            and proof.get('all_daily_factors_and_chains_verified') is True)


def actual_parent(old, spec):
    from research.pooled_vacancy_funding import backtest, journal, runtime
    from research.pooled_input_support.bundle import axis
    cp = strict_parent(journal.read_checkpoint(old / spec['selected_checkpoint']), spec)
    full = axis()
    wanted = full[full.index(backtest.START) - 425:full.index(backtest.END) + 1]
    need(backtest.START == '2018-01-02' and backtest.END == '2026-07-31', 'RESUME_UNCHANGED_FULL_AXIS')
    backtest.validate_checkpoint(cp, cp['base'], wanted)
    need(cp['base']['sources'] == backtest.source_files(), 'RESUME_IDENTICAL_FINANCIAL_SOURCE')
    run = runtime.restore(cp['run'], policy=cp['base']['policy'],
                          input_sha256=backtest.input_hash(cp['base'], cp['repairs']))
    need(runtime.checkpoint(run) == cp['run'], 'RESUME_CANONICAL_PARENT_ROUNDTRIP')
    stream = reader(journal.Journal, old / 'book', journal.STREAMS)
    try:
        stream.verify(cp['journals'])
    finally:
        stream.close()
    return cp, following_session(cp, spec, wanted)


def composite_preparation_receipt(cp, spec, module, overlay, loaded, out):
    """Bind input-only preparation; the admitted financial parent stays unchanged."""
    overlay, out = Path(overlay), Path(out)
    need(overlay == out / module.OVERLAY and loaded.sha256 == sha256_file(overlay)
         and loaded.earliest_affected_session > cp['source_cursor'],
         'RESUME_COMPOSITE_PREPARED_EXACT_OVERLAY_AND_UNCONSUMED_BOUNDARY')
    names = [module.QUALIFICATION]
    if hasattr(module, 'ORDINARY_QUALIFICATION'):
        names.append(module.ORDINARY_QUALIFICATION)
    for name in names:
        qualifier = json.loads((out / name).read_bytes())
        need(qualifier['financial_sessions_advanced'] == 0
             and qualifier.get('passed', True) is True
             and qualifier.get('loaded_minimum_boundary', loaded.earliest_affected_session)
                 == loaded.earliest_affected_session,
             'RESUME_COMPOSITE_PREPARATION_ZERO_SESSION_QUALIFIERS')
    return dict(schema='research.zero-financial-composite-preparation/1', passed=True,
        arm=spec['arm'], parent_outer_sha256=cp['sha256'],
        parent_inner_sha256=cp['run']['checkpoint_sha256'],
        parent_input_sha256=cp['run']['input_sha256'], parent_cursor=cp['source_cursor'],
        root_admission_sha256=spec.get('root_admission_sha256'),
        runtime_source_sha256=sha256_file(Path(module.__file__)),
        overlay_sha256=loaded.sha256, earliest_affected_session=loaded.earliest_affected_session,
        artifacts={name: sha256_file(out / name) for name in [module.OVERLAY, *names]},
        parent_unchanged=True, checkpoint_adopted=False, financial_sessions_advanced=0)


def prepare_composite_before_finance(cp, out, spec):
    """Exercise the actual composite path in the existing retained loader context."""
    if EXECUTION_MODE != 'OWN_ADMITTED_FINANCIAL_CONTINUATION':
        return None
    from system_campaign_financial_compound_dispatch import selected
    module = selected(cp, spec['arm'])
    if module is None:
        return None
    from research.pooled_vacancy_funding import backtest, runtime
    out = Path(out)
    parent_bytes = json.dumps(cp, sort_keys=True, separators=(',', ':'), allow_nan=False)
    forbidden = [out / 'book/checkpoint.json.gz', out / 'input-adoption/checkpoint.json.gz']
    need(not any(path.exists() for path in forbidden),
         'RESUME_COMPOSITE_PREPARATION_STARTS_WITHOUT_FINANCIAL_CHECKPOINT')
    def no_financial_advance(*args, **kwargs):
        raise ValueError('RESUME_COMPOSITE_PREPARATION_CANNOT_RUN_FINANCIAL_TRANSITIONS')
    original_main, original_advance = backtest.main, runtime.advance
    try:
        backtest.main = runtime.advance = no_financial_advance
        overlay, loaded = module.prepare(cp, out, spec['arm'])
    finally:
        backtest.main, runtime.advance = original_main, original_advance
    need(json.dumps(cp, sort_keys=True, separators=(',', ':'), allow_nan=False) == parent_bytes
         and not any(path.exists() for path in forbidden),
         'RESUME_COMPOSITE_PREPARATION_NO_PARENT_MUTATION_OR_CHECKPOINT_ADOPTION')
    return composite_preparation_receipt(cp, spec, module, overlay, loaded, out)


def require_composite_preparation(cp, spec, proof, root):
    """A stopped parent preflight must have prepared this exact input generation."""
    from system_campaign_financial_compound_dispatch import selected
    module = selected(cp, spec['arm'])
    if module is None:
        need(proof.get('composite_preparation') is None,
             'RESUME_NO_FOREIGN_COMPOSITE_PREPARATION_RECEIPT')
        return
    value = proof['composite_preparation'];root = Path(root)
    overlay = root / module.OVERLAY
    expected = composite_preparation_receipt(cp, spec, module, overlay,
        type('PreparedInput', (), dict(sha256=sha256_file(overlay),
            earliest_affected_session=value['earliest_affected_session']))(), root)
    need(value == expected,
         'RESUME_EXACT_STOPPED_ZERO_FINANCIAL_COMPOSITE_PREPARATION_REQUIRED')


def preflight(old, out, spec):
    hosted()
    if 'root_admission' in spec:
        validate_root_spec(spec)
    with financial_inputs(old, strict_parent(json.loads(gzip.decompress(
            (old / spec['selected_checkpoint']).read_bytes())), spec), out, spec):
        cp, following = actual_parent(old, spec)
        preparation = prepare_composite_before_finance(cp, out, spec)
        seed_rows(old, cp, spec)
        if 'reuse_closed_hosted_prefix_review' in spec:
            need(spec['reuse_closed_hosted_prefix_review'] is True, 'RESUME_EXACT_CLOSED_PREFIX_REUSE_DECLARATION')
        if 'root_admission' in spec or spec.get('reuse_closed_hosted_prefix_review') is True:
            # Reuse this exact positively stopped accounting review; root authority is separate.
            need(sha256_file(old / review_name(spec)) == spec['review_sha256'],
                 'RESUME_CLOSED_ROOT_ACCOUNTING_REVIEW_BYTES')
            shutil.copyfile(old / review_name(spec), out / 'old-prefix-canonical-review.json')
        else:
            readonly_review(old / 'book', out / 'old-prefix-canonical-review.json')
    proof = json.loads((out / 'old-prefix-canonical-review.json').read_bytes())
    need(proof['all_prefixes_verified'] and proof['all_daily_factors_and_chains_verified']
         and proof['checkpoint_sha256'] == cp['sha256']
         and proof['counts'] == dict(formation=126, daily=cp['completed']), 'RESUME_PARENT_ACCOUNTING_REVIEW_REQUIRED')
    if spec.get('archive_format') in ('FINANCIAL_RESUME_FIVE_MEMBER_ZIP/1', FRESH_FORMAT) and 'root_admission' not in spec:
        monthly_reproduction(old, out, spec, cp)
    save(out / 'strict-parent-preflight.json', dict(passed=True, arm=spec['arm'],
         outer_sha256=cp['sha256'], selected_file=spec['selected_file'], next_session=following,
         canonical_roundtrip=True, original_journal_commitments_verified=True,
         diagnostic_state_adopted=False, financial_sessions_advanced=0,
         root_admission_sha256=spec.get('root_admission_sha256'),
         composite_preparation=preparation,
         accounting_review_sha256=sha256_file(out / 'old-prefix-canonical-review.json')))
    request = json.loads((HERE / REQUEST).read_bytes())
    if request.get('readonly_source_witnesses') is True:
        source_request_bindings(request, spec)
        shutil.copyfile(HERE / REQUEST, out / 'source-witness-request.json')
        from system_campaign_financial_future import capture_source_witnesses
        capture_source_witnesses(cp, out, spec['arm'], request['source_witness_scopes'][spec['arm']])


def preserve_originals(old, out, spec):
    """Keep every archived gzip by content, with a lossless original-name index."""
    dest = out / 'lineage/original-checkpoints'
    dest.mkdir(parents=True)
    inventory = {}
    for base in ('book', 'lineage'):
        for path in sorted((old / base).rglob('*.json.gz')):
            raw = path.read_bytes()
            h = sha(raw)
            target = dest / (h + '.json.gz')
            if target.exists():
                need(target.read_bytes() == raw, 'RESUME_IDENTICAL_ARCHIVED_GZIP')
            else:
                target.write_bytes(raw)
            inventory[path.relative_to(old).as_posix()] = dict(bytes=len(raw), sha256=h,
                stored=target.relative_to(out).as_posix())
    for path in (old / 'book').glob('interrupted-*.jsonl'):
        target = out / 'lineage/prior-interrupted-tails' / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    save(out / 'lineage/original-checkpoint-inventory.json', inventory)
    save(out / 'lineage/strict-financial-parent-reference.json', spec)


def verify_originals(old, evidence):
    inventory = json.loads((evidence / 'lineage/original-checkpoint-inventory.json').read_bytes())
    original = {p.relative_to(old).as_posix(): p for base in ('book', 'lineage')
                for p in (old / base).rglob('*.json.gz')}
    need(original and set(inventory) == set(original), 'RESUME_NO_ORIGINAL_GZIP_OMISSIONS')
    for name, value in inventory.items():
        need(value['sha256'] == sha256_file(original[name])
             and value['bytes'] == original[name].stat().st_size
             and value['stored'] == 'lineage/original-checkpoints/' + value['sha256'] + '.json.gz',
             'RESUME_EXACT_ORIGINAL_GZIP_REFERENCE')
        path = evidence / value['stored']
        need(path.stat().st_size == value['bytes'] and sha256_file(path) == value['sha256'],
             'RESUME_ALL_ORIGINAL_ARCHIVED_GZIP_BYTES')


def economic(old, out, spec):
    hosted()
    from system_campaign_financial_uncertainty import uncertainty_phase
    need(EXECUTION_MODE == 'OWN_ADMITTED_FINANCIAL_CONTINUATION' and not full_target(spec),
         'RESUME_ECONOMIC_ENTRY_REQUIRES_UNFINISHED_FINANCIAL_MODE')
    if 'root_admission' in spec:
        validate_root_spec(spec)
    proof = json.loads((out / 'strict-parent-preflight.json').read_bytes())
    need(proof['passed'] is True and proof['arm'] == spec['arm']
         and proof['outer_sha256'] == spec['outer_sha256']
         and proof['diagnostic_state_adopted'] is False and proof['financial_sessions_advanced'] == 0
         and proof['accounting_review_sha256'] == sha256_file(out / 'old-prefix-canonical-review.json')
         and proof.get('root_admission_sha256') == spec.get('root_admission_sha256'),
         'RESUME_POSITIVELY_PASSED_PARENT_PREFLIGHT')
    cp = strict_parent(json.loads(gzip.decompress((old / spec['selected_checkpoint']).read_bytes())), spec)
    require_composite_preparation(cp, spec, proof, out / 'parent-preflight')
    book = out / 'book'
    with financial_inputs(old, cp, out, spec):
        cp, following = actual_parent(old, spec)
        need(following == proof['next_session'], 'RESUME_EXACT_NEXT_SESSION')
        for name in ('checkpoint.json.gz', 'identity.json'):
            shutil.copyfile(old / 'book' / name, book / name)
        shutil.copyfile(old / spec['selected_checkpoint'],
                        book / 'predecessor-checkpoints' / (cp['sha256'] + '.json.gz'))
        tails = {}
        for name, entry in cp['journals'].items():
            raw = (old / 'book' / (name + '.jsonl')).read_bytes()
            (book / (name + '.jsonl')).write_bytes(raw)
            tail = raw[entry['bytes']:]
            tails[name] = dict(bytes=len(tail), sha256=sha(tail))
        save(out / 'resume-tail-preflight.json', dict(tails_to_preserve=tails))
        for path in old.glob('hydrated-*.json'):
            target = out / path.name
            if target.exists():
                need(target.read_bytes() == path.read_bytes(), 'RESUME_RETAINED_HYDRATION_UNCHANGED')
            else:
                shutil.copyfile(path, target)
        preserve_originals(old, out, spec)
        from research.pooled_vacancy_funding import backtest
        params = json.loads((old / 'source-bindings.json').read_bytes())['parameters']
        family = params['family']
        keep = params['v_horizon'] if family == 'V' else 21 if family == 'C' else 1
        args = arguments(book, True)
        args[args.index('--policy') + 1] = cp['base']['policy']
        rows = seed_rows(old, cp, spec)
        if spec['arm'] == 'P04' and spec.get('archive_format') != 'FINANCIAL_RESUME_FIVE_MEMBER_ZIP/1':
            shutil.copytree('/correlation-prefix', out / 'restored-correlation-prefix')
        observation = SeededObservation(out / 'correlation-inputs.jsonl.gz', rows)
        execution = Execution('FAST', signal_closes=keep)
        try:
            if 'root_admission' in spec and uncertainty_phase(spec):
                from system_campaign_financial_uncertainty import run
                code = run(cp, out, args, rows, observation, execution, spec=spec, old=old)
            else:
                extra, gate = qualified_overlay(cp, out, spec)
                from system_campaign_financial_compound_dispatch import selected
                if 'root_admission' in spec and selected(cp, spec['arm']) is None:
                    from system_campaign_financial_future import ActualEvents
                    events = ActualEvents(out, spec['arm'], cp=cp)
                else:
                    events = nullcontext()
                with gate, observation, execution, events:
                    code = backtest.main(args + extra)
        finally:
            if hasattr(execution, 'scope'):
                save(out / 'acceleration-proof.json', execution.proof())
            save(out / 'correlation-capture-proof.json', observation.proof())
        save(out / 'recovered-tail-proof.json', preserve_tails(book, dict(tails_to_preserve=tails)))
        current = json.loads(gzip.decompress((book / 'checkpoint.json.gz').read_bytes()))
        complete = code == 0 and current['completed'] == 2156 and current['source_cursor'] == '2026-07-31'
        save(out / 'accurate-outcome.json', dict(arm=spec['arm'], complete=complete,
            completed=current['completed'], session=current['source_cursor'],
            new_transitions=current['completed'] - cp['completed'], diagnostic_state_adopted=False,
            financial_source_changed=False, new_factual_overlay=factual_overlay_needed(spec), production_contacted=False))
        need(complete, 'RESUME_INCOMPLETE_FINANCIAL_PREFIX_PRESERVED')


def review(evidence, out, spec):
    hosted()
    from system_campaign_financial_additional_sensor import phase as additional_phase
    if additional_phase(spec) is not None:
        from system_campaign_financial_additional_sensor_runtime import review_driver
        return review_driver(evidence, out, spec)
    from system_campaign_financial_uncertainty import uncertainty_phase
    old = Path('/old')
    cp = strict_parent(json.loads(gzip.decompress((old / spec['selected_checkpoint']).read_bytes())), spec)
    if spec['arm'] == 'P04' and spec.get('archive_format') != 'FINANCIAL_RESUME_FIVE_MEMBER_ZIP/1':
        need(seed_rows(old, cp, spec) == seed_rows(old, cp, spec, evidence / 'restored-correlation-prefix'),
             'RESUME_EXACT_RETAINED_OBSERVATION_CAPSULE')
    if 'root_admission' in spec and uncertainty_phase(spec):
        from system_campaign_financial_uncertainty import review as review_uncertainty
        review_uncertainty(cp, evidence, out, spec=spec, old=old)
    elif 'root_admission' in spec or spec['arm'] in ('P07', 'P10'):
        review_adoption(evidence, cp, spec)
    readonly_review(evidence / 'book', out / 'core-review.json')
    verify_correlation(evidence)
    preserve_tails(evidence / 'book', json.loads((evidence / 'resume-tail-preflight.json').read_bytes()))
    verify_originals(old, evidence)
    need(sha256_file(evidence / 'book/predecessor-checkpoints' / (spec['outer_sha256'] + '.json.gz'))
         == spec['selected_file']['sha256'], 'RESUME_SELECTED_ORIGINAL_GZIP')


def export_probe(root, request, arm, key):
    root.mkdir(mode=0o700)
    marker = b'{"synthetic_marker":"financial-resume-export-only","financial_sessions":0}\n'
    (root / 'marker.json').write_bytes(marker)
    path = root.parent / ('resume-export-probe-' + arm + '.crseal')
    asset = seal(root, path, key, request, arm, stage='campaign-factual-suffix',
                 protocol_sha256=json.loads(request.read_bytes())['protocol_sha256'])
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.write(path, asset['name'])
    archive.seek(0)
    with zipfile.ZipFile(archive) as z:
        header, tag = crypto.authenticate(z, asset, key)
        with z.open(asset['name']) as source:
            plain = crypto.AuthenticatedStream(source, asset, key, header, tag)
            with tarfile.open(fileobj=plain, mode='r|gz') as tar:
                items = iter(tar)
                first = next(items)
                need(first.name == 'manifest.json', 'RESUME_REAL_EXPORT_MANIFEST')
                manifest = tar.extractfile(first).read()
                need(sha(manifest) == asset['manifest_sha256'], 'RESUME_REAL_EXPORT_MANIFEST_HASH')
                item = next(items)
                need(item.name == 'marker.json' and tar.extractfile(item).read() == marker
                     and next(items, None) is None, 'RESUME_REAL_EXPORT_MARKER_ROUNDTRIP')
            while plain.read(1024**2):
                pass
    return dict(status='REAL_SYNTHETIC_ENCRYPTED_EXPORT_ROUNDTRIP_PASSED', arm=arm,
                financial_sessions_advanced=0, credentials_saved=False)


def inspect(name, identity=None, *, value=None, run_id=None, user=None, correlation_prefix=None):
    match = re.fullmatch(r'capital-system-resume-(p[0-9]{2})-(preflight|worker|review)-([0-9]+)-1', name)
    need(match is not None and match[1].upper() in ARMS
         and match[3] == (run_id if run_id is not None else os.environ['GITHUB_RUN_ID']), 'RESUME_EXACT_WORKER_NAME')
    if value is None:
        value = json.loads(subprocess.run(['docker', 'inspect', name], capture_output=True,
                                         check=True, timeout=20).stdout)[0]
    h, c = value['HostConfig'], value['Config']
    mode = 'economic' if match[2] == 'worker' else match[2]
    mounts = {v['Destination']: v for v in value['Mounts'] if v['Type'] == 'bind'}
    expected = {'/variant', '/frozen', '/driver', '/old', '/out'} | ({'/evidence'} if mode == 'review' else set())
    use_prefix = correlation_prefix if correlation_prefix is not None else match[1] == 'p04'
    if use_prefix:
        expected.add('/correlation-prefix')
    expected_user = user if user is not None else f'{os.getuid()}:{os.getgid()}'
    need(re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*', expected_user) is not None, 'RESUME_POSITIVE_UID_GID')
    need(value['Name'] == '/' + name and value['Image'] == EXECUTION_IMAGE
         and (identity is None or value['Id'] == identity), 'RESUME_WORKER_IDENTITY')
    need(h['NetworkMode'] == 'none' and h['Memory'] == h['MemorySwap'] == 8 * 1024**3
         and h['NanoCpus'] == 2000000000 and h['PidsLimit'] == 64 and h['ReadonlyRootfs']
         and h['CapDrop'] == ['ALL'] and any(v.startswith('no-new-privileges') for v in h['SecurityOpt']),
         'RESUME_OFFLINE_NO_SWAP_FENCES')
    need(set(mounts) == expected and mounts['/out']['RW']
         and all(not v['RW'] for k, v in mounts.items() if k != '/out')
         and c['WorkingDir'] == '/variant' and c['User'] == expected_user
         and c['Labels']['research.study'] == 'full-system-search-20261029'
         and c['Labels']['research.role'] == ('review' if mode == 'review' else 'worker')
         and c['Entrypoint'] == ['python']
         and c['Cmd'] == ['-B', '-u', '/driver/system_campaign_financial_resume.py', '--mode', mode,
                          '--spec', '/out/spec.json'], 'RESUME_MOUNTS_AND_EXACT_ENTRYPOINT')
    forbidden = set(FORBIDDEN_CREDENTIALS) | {SECRET, 'GITHUB_TOKEN', 'GH_TOKEN'}
    need(not any(k in forbidden and v for k, _, v in (s.partition('=') for s in c['Env'])),
         'RESUME_NO_WORKER_CREDENTIALS')
    return value


def launch(args):
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'RESUME_NO_BLIND_RERUN')
    request = json.loads(args.request.read_bytes())
    need(request == expected_request() and args.arm in SELECTED_ARMS, 'RESUME_EXACT_REQUEST_AND_SELECTED_ARM')
    need(request_authority(request),
         'RESUME_EXACT_FINANCIAL_OR_READONLY_AUTHORITY')
    stage_valid(json.loads(args.staging.read_bytes()))
    from ephemeral_runner_capacity import validate_prepared_receipt
    validate_prepared_receipt(json.loads(args.capacity.read_bytes()), head=os.environ['GITHUB_SHA'],
        run_id=os.environ['GITHUB_RUN_ID'], source_sha256=request['sources']['ephemeral_runner_capacity.py'])
    spec = (json.loads((HERE / PARTIALS).read_bytes())['arms'][args.arm] if request['readonly_partial_review']
            else root_spec(args.arm))
    temp = Path(os.environ['RUNNER_TEMP'])
    key = base64.b64decode(os.environ.pop(SECRET, ''), validate=True)
    need(len(key) == 32, 'RESUME_SEPARATE_KEY')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    receipt = dict(schema='research.system-campaign-accurate-resume-receipt/1', arm=args.arm,
        run_id=os.environ['GITHUB_RUN_ID'], head=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(args.request), protocol_sha256=request['protocol_sha256'],
        predecessor_outer_sha256=spec['outer_sha256'], performance_admitted=False,
        financial_resume_authorized=request['financial_resume_authorized'],
        readonly_partial_review=request['readonly_partial_review'],
        readonly_source_witnesses=request.get('readonly_source_witnesses', False),
        production_contacted=False, status='EXPORT_PROBE_PENDING')

    def public():
        target = args.output.with_suffix('.tmp')
        save(target, receipt)
        os.replace(target, args.output)

    public()
    out = temp / ('financial-resume-output-' + args.arm)
    out.mkdir(mode=0o700)
    finance_stopped = False
    stopped_snapshot = False
    try:
        marker = export_probe(temp / ('financial-resume-probe-' + args.arm), args.request, args.arm, key)
        save(args.output.parent / ('resume-export-qualification-' + args.arm + '.json'), marker)
        receipt['status'] = 'EXPORT_PROBE_PASSED_PARENT_NOT_FETCHED'
        public()
        need(shutil.disk_usage(temp).free >= 12 * 1024**3, 'RESUME_INITIAL_DISK_RESERVE')
        transfer = temp / ('campaign-factual-transfer-financial-' + args.arm.lower())
        old = admit_partial(spec, transfer, key, inspect)
        capsule = None
        if args.arm == 'P04' and spec.get('archive_format') != 'FINANCIAL_RESUME_FIVE_MEMBER_ZIP/1':
            auxiliary = crypto.admit(prefix_descriptor()['transport'],
                temp / 'campaign-factual-transfer-correlation-p04', key, max_zip_bytes=512 * 1024**2)
            capsule = prepare_prefix(old, auxiliary, temp / 'financial-correlation-prefix-P04')
        os.environ.pop('GH_TOKEN', None)
        frozen = temp / 'capital-risk-stage-001/inputs'
        source = temp / ('financial-resume-source-' + args.arm)
        binding = json.loads((old / 'source-bindings.json').read_bytes())
        need(build(frozen / 'source-fixed', source, binding['parameters']) == binding,
             'RESUME_WHOLE_ORIGINAL_FINANCIAL_SOURCE_IDENTICAL')
        for directory in (source, old, *((capsule,) if capsule is not None else ())):
            for path in directory.rglob('*'):
                os.chmod(path, 0o555 if path.is_dir() else 0o444)
            os.chmod(directory, 0o555)
        shutil.copyfile(old / 'source-bindings.json', out / 'source-bindings.json')
        shutil.copyfile(args.request, out / 'request.json')
        save(out / 'spec.json', spec)

        def worker(mode, output, evidence=None):
            need(memory_bytes()['MemAvailable'] >= 10 * 1024**3
                 and shutil.disk_usage(temp).free >= 10 * 1024**3, 'RESUME_ONE_WORKER_CAPACITY')
            role = 'worker' if mode == 'economic' else mode
            name = f'capital-system-resume-{args.arm.lower()}-{role}-' + os.environ['GITHUB_RUN_ID'] + '-1'
            values = command(name, source, frozen, output, 'review' if mode == 'review' else 'economic')
            i = values.index('--entrypoint')
            mounts = ['--mount', f'type=bind,source={old},target=/old,readonly']
            if capsule is not None:
                mounts += ['--mount', f'type=bind,source={capsule},target=/correlation-prefix,readonly']
            if evidence is not None:
                mounts += ['--mount', f'type=bind,source={evidence},target=/evidence,readonly']
            values[i:i] = mounts
            values[values.index('-B'):] = ['-B', '-u', '/driver/system_campaign_financial_resume.py',
                                          '--mode', mode, '--spec', '/out/spec.json']
            return stopped_run(values, name, output,
                deadline=request['financial_wait_seconds' if mode == 'economic' else mode + '_wait_seconds'],
                inspector=lambda n, identity=None: inspect(n, identity, correlation_prefix=capsule is not None))

        parent_review = temp / ('financial-resume-preflight-' + args.arm)
        parent_review.mkdir(mode=0o700)
        save(parent_review / 'spec.json', spec)
        receipt['status'] = 'STRICT_FINANCIAL_PARENT_PREFLIGHT_RUNNING'
        public()
        receipt['preflight'] = worker('preflight', parent_review)
        shutil.copytree(parent_review, out / 'parent-preflight')
        stopped_snapshot = True
        need(successful_stop(receipt['preflight']),
             'RESUME_PARENT_PREFLIGHT_REFUSED_NO_FINANCIAL_LAUNCH')
        for name in ('strict-parent-preflight.json', 'old-prefix-canonical-review.json'):
            shutil.copyfile(parent_review / name, out / name)
        if request.get('readonly_source_witnesses') is True:
            need(request['financial_resume_authorized'] is request['readonly_partial_review'] is False,
                 'RESUME_SOURCE_WITNESSES_CANNOT_LAUNCH_FINANCE_OR_REPORTING')
            need((parent_review / 'source-witness-request.json').read_bytes() == args.request.read_bytes(),
                 'RESUME_SOURCE_WITNESS_ACTUAL_WORKER_REQUEST_BYTES')
            from system_campaign_financial_future import SOURCE_WITNESS_FILE, validate_witness_capture
            payload = json.loads((parent_review / SOURCE_WITNESS_FILE).read_bytes())
            validate_witness_capture(payload, spec, request['source_witness_scopes'][args.arm])
            shutil.copyfile(parent_review / SOURCE_WITNESS_FILE, out / SOURCE_WITNESS_FILE)
            receipt['status'] = 'SOURCE_WITNESSES_HOSTED_CAPTURED_PENDING_DATA'
        elif request['readonly_partial_review']:
            need(request['financial_resume_authorized'] is False, 'RESUME_READONLY_CANNOT_ADVANCE_FINANCIAL_STATE')
            monthly = json.loads((parent_review / 'monthly-reproduction.json').read_bytes())
            need(monthly['passed'] is True and monthly['checkpoint_sha256'] == spec['outer_sha256']
                 and monthly['completed'] == spec['measured_closes']
                 and monthly['all_new_monthly_reports_exact'] is True
                 and monthly['all_monthly_checkpoint_state_exact'] is True
                 and monthly['financial_transitions_reexecuted'] == 0,
                 'RESUME_COMPLETE_STOPPED_MONTHLY_REPRODUCTION_REQUIRED')
            shutil.copyfile(parent_review / 'monthly-reproduction.json', out / 'monthly-reproduction.json')
            receipt['status'] = 'READONLY_PARTIAL_REVIEW_PASSED_PENDING_ROOT'
        else:
            need(request['financial_resume_authorized'] is True, 'RESUME_FINANCIAL_AUTHORITY_REQUIRED')
            from system_campaign_financial_future import stage_selected_sources
            stage_selected_sources(spec, old, out)
            receipt['status'] = 'ACCURATE_FINANCIAL_RUNNING'
            public()
            stopped_snapshot = False
            receipt['worker'] = worker('economic', out)
            finance_stopped = stopped_snapshot = True
            receipt['status'] = 'FINANCIAL_STOPPED_PENDING_REVIEW'
            public()
            audit = temp / ('financial-resume-review-' + args.arm)
            audit.mkdir(mode=0o700)
            save(audit / 'spec.json', spec)
            receipt['reviewer'] = worker('review', audit, out)
            shutil.copytree(audit, out / 'stopped-review')
            proof_path = audit / 'core-review.json'
            proof = json.loads(proof_path.read_bytes()) if proof_path.exists() else {}
            passed = successful_stop(receipt['reviewer'])
            complete = complete_review(receipt['worker'], receipt['reviewer'], proof)
            receipt['status'] = ('COMPLETE_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT' if complete
                                 else 'PARTIAL_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT' if passed
                                 else 'FINANCIAL_REVIEW_REFUSED_PRESERVED')
    except StopUnknown:
        receipt['status'] = 'REVIEW_UNKNOWN_STOPPED_FINANCIAL_PRESERVED' if finance_stopped else 'WRITER_UNKNOWN_NO_MUTABLE_EXPORT'
    except Exception:
        receipt['status'] = 'REFUSED_STOPPED_EVIDENCE_PRESERVED' if stopped_snapshot else 'REFUSED_NO_NEW_FINANCIAL_ADMISSION'
        if stopped_snapshot:
            (out / 'driver-failure.txt').write_text(traceback.format_exc())
    if stopped_snapshot:
        receipt['encrypted_output'] = seal(out, args.output.parent / ('campaign-factual-' + args.arm + '.tar.crseal'),
            key, args.request, args.arm, stage='campaign-factual-suffix', protocol_sha256=request['protocol_sha256'])
    key = None
    public()
    print(json.dumps(receipt), flush=True)
    return 0 if receipt['status'] in ('COMPLETE_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT',
                                      'READONLY_PARTIAL_REVIEW_PASSED_PENDING_ROOT',
                                      'SOURCE_WITNESSES_HOSTED_CAPTURED_PENDING_DATA') else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--mode', choices=('preflight', 'economic', 'review'))
    parser.add_argument('--spec', type=Path)
    for name in ('request', 'staging', 'capacity', 'output'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--arm', choices=ARMS)
    args = parser.parse_args()
    if args.probe:
        need(args.request is not None and json.loads(args.request.read_bytes()) == expected_request(),
             'RESUME_IMPORT_PROBE_EXACT_REQUEST')
        print(json.dumps(dict(status='LAUNCHER_IMPORT_AND_EXACT_REQUEST_PROBE_PASSED',
                              financial_runtime_executed=False, financial_sessions_advanced=0)))
    elif args.mode:
        hosted()
        spec = json.loads(args.spec.read_bytes())
        if args.mode == 'preflight':
            preflight(Path('/old'), Path('/out'), spec)
        elif args.mode == 'economic':
            economic(Path('/old'), Path('/out'), spec)
        else:
            review(Path('/evidence'), Path('/out'), spec)
    else:
        raise SystemExit(launch(args))
