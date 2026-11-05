"""Own-book neutral input boundaries and the existing certified sensor gateway."""
from copy import deepcopy
from contextlib import nullcontext
import ast
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
BRANCH_SHA = 'b19a93be7b6887c1b92a5a676fefecc5477addfaf99efcf1f18f45eafb6140ef'
POINT_RETURN_SEEDS = frozenset({'6abf375981b345fcdfebc5db1f68664a1f401783a7e13f6a3cf2e9c8bd6a2a22', '99c02d182abd329b1e94bde8a8ec1d1ad2f7a9883220fb2e79a9e9766f96300b', '8b3bbe1f16e0daa175d031ca9a95fab95755dea50b33b66c36061af4ba77a998', '672a0a0a7560d1b3d4658e6c0e79c3f4259391ac4a7f2d3ecb58e505f5132ef3', 'f7f86bf917f7d2718c8e360a4e1d1de2c2d90d6dd94406e581c6712201a8b776'})
POINT_WITNESS_SHA = '177d5906b9ecd6b33512999ef8408704d5814ba5f69a4d8284fb22b62b7f5cf1'
UNCHANGED_INPUT_SEEDS = frozenset({'f7f86bf917f7d2718c8e360a4e1d1de2c2d90d6dd94406e581c6712201a8b776'})
UNCHANGED_INPUT = 'retained-proof-admission/unchanged-input.json'
RETAINED_PROOF_SEEDS = {
    '6abf375981b345fcdfebc5db1f68664a1f401783a7e13f6a3cf2e9c8bd6a2a22': dict(completed=986, source_cursor='2021-11-30', rows=532, new_rows=148, retained_rows=384),
    '99c02d182abd329b1e94bde8a8ec1d1ad2f7a9883220fb2e79a9e9766f96300b': dict(completed=838, source_cursor='2021-04-30', rows=384, new_rows=21, retained_rows=363),
    '8b3bbe1f16e0daa175d031ca9a95fab95755dea50b33b66c36061af4ba77a998': dict(completed=817, source_cursor='2021-03-31', rows=363, new_rows=42, retained_rows=321),
    '672a0a0a7560d1b3d4658e6c0e79c3f4259391ac4a7f2d3ecb58e505f5132ef3': dict(completed=775, source_cursor='2021-01-29', rows=321, new_rows=19, retained_rows=302),
    'f7f86bf917f7d2718c8e360a4e1d1de2c2d90d6dd94406e581c6712201a8b776': dict(completed=756, source_cursor='2020-12-31', rows=302, new_rows=128, retained_rows=174),
    '2293655ea9e4c520c66e016a33c9d33b78f12ceb09c50a371bc84b76c0eef543':
        dict(completed=628, source_cursor='2020-06-30', rows=174, new_rows=63, retained_rows=111),
    '30552e338938b213e0dcfe5ef06ca6defcca8d0627126cf39cfd63b2982c9e03':
        dict(completed=565, source_cursor='2020-03-31', rows=111, new_rows=22, retained_rows=89),
    'c3b3695de955721404aa8b1eb04f2f272efa4f3bd01c8bdd5fac10b92995811c':
        dict(completed=503, source_cursor='2019-12-31', rows=49, new_rows=49, retained_rows=0),
    '46fd68cb0d747c8c5ca004e979f49f89c02d505ef69069af7e086bd18b18268d':
        dict(completed=543, source_cursor='2020-02-28', rows=89, new_rows=40, retained_rows=49),
}


def point_return_phase(spec):
    return isinstance(spec, dict) and spec.get('root_admission_sha256') in POINT_RETURN_SEEDS


def unchanged_input_phase(spec):
    return isinstance(spec, dict) and spec.get('root_admission_sha256') in UNCHANGED_INPUT_SEEDS


def proof_scope(cp, spec):
    if not point_return_phase(spec):
        return nullcontext()
    from system_campaign_point_growth import point_growth_scope
    name = 'sentinel/controller/median5.py'
    need(cp['base']['sources'].get(name) == POINT_WITNESS_SHA,
         'FINANCIAL_POINT_PROOF_SAME_FROZEN_WITNESS')
    return point_growth_scope((Path('/variant') / name).read_bytes(), POINT_WITNESS_SHA)


def unchanged_input_receipt(cp, spec):
    need(unchanged_input_phase(spec), 'FINANCIAL_NO_NEW_INPUT_EXACT_REGISTERED_PHASE')
    return dict(schema='research.unchanged-retained-financial-input/1',
        parent_outer_sha256=cp['sha256'], root_admission_sha256=spec['root_admission_sha256'],
        completed=cp['completed'], source_cursor=cp['source_cursor'],
        input_sha256=cp['run']['input_sha256'], repairs=deepcopy(cp['repairs']),
        witness_sha256=POINT_WITNESS_SHA, proof_growth='CPYTHON312_BUILTIN_SUM_POINT_RETURNS',
        new_factual_overlay=False, financial_source_changed=False)


def review_unchanged_input(parent, current, evidence_root, spec):
    expected = unchanged_input_receipt(parent, spec)
    raw = (evidence_root / UNCHANGED_INPUT).read_bytes()
    need(raw == (json.dumps(expected, sort_keys=True, indent=2) + '\n').encode()
         and current['base'] == parent['base'] and current['repairs'] == parent['repairs']
         and current['run']['input_sha256'] == parent['run']['input_sha256']
         and not (evidence_root / MODEL_ADOPTION).exists()
         and not (evidence_root / 'future-financial-overlay.json').exists(),
         'FINANCIAL_RETAINED_PROOF_EXACT_UNCHANGED_INPUT')


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


def run(cp, out, args, rows, observer, execution, *, spec=None, old=None):
    hosted()
    if spec is not None and cp['completed'] >= 503:
        return run_retained(cp, out, args, observer, execution, spec, old)
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


def review(cp, evidence_root, out, *, spec=None, old=None):
    hosted()
    if spec is not None and cp['completed'] >= 503:
        return review_retained(cp, evidence_root, out, spec, old)
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


def validate_retained_admission_metadata(spec):
    """Check the existing registered retained root before any hosted work."""
    cp = dict(sha256=spec['outer_sha256'], completed=spec['measured_closes'],
              source_cursor=spec['selected_session'], base=spec['base'])
    retained_contract(cp, spec)
    phase = RETAINED_PROOF_SEEDS[spec['root_admission_sha256']]
    proof = spec['root_admission']['branch_uncertainty_proof']
    need(proof['passed'] is True
         and type(proof['rows']) is type(proof.get('retained_rows', 0)) is int
         and proof['rows'] == phase['new_rows']
         and proof.get('retained_rows', 0) == phase['retained_rows']
         and phase['rows'] == phase['new_rows'] + phase['retained_rows']
         and proof['all_comparisons_and_state_sets_verified'] is True
         and proof['all_math_watch_financial_chains_verified'] is True,
         'FINANCIAL_RETAINED_ADMISSION_EXACT_CURRENT_SUFFIX_PROOF_COUNTS')
    # Existing point-return proof epochs start at own756; earlier registered
    # interval epochs retain their unchanged path.
    need(phase['completed'] < 756 or point_return_phase(spec),
         'FINANCIAL_RETAINED_ADMISSION_EXACT_POINT_RETURN_REGISTRATION')
    return phase


def retained_contract(cp, spec):
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec)
    hashes = json.loads((HERE / INTEGRATION).read_bytes())['canonical_controller_sources']
    phase = RETAINED_PROOF_SEEDS.get(spec['root_admission_sha256'])
    need(spec['arm'] == 'P07' and cp['sha256'] == spec['outer_sha256']
         and phase is not None and cp['completed'] == spec['measured_closes'] == phase['completed']
         and cp['source_cursor'] == spec['selected_session'] == phase['source_cursor']
         and cp['base'] == spec['base'], 'FINANCIAL_RETAINED_PROOF_EXACT_OWN_ADMITTED_PARENT')
    need(len(hashes) == 6 and all(cp['base']['sources'].get(n) == h for n, h in hashes.items())
         and sha((HERE / 'system_campaign_financial_branches.py').read_bytes()) == BRANCH_SHA,
         'FINANCIAL_RETAINED_PROOF_UNCHANGED_CONTROLLER_AND_IMPLEMENTATION')
    return hashes


def retained_seed(old, cp, spec):
    from system_campaign_financial_branches import validate_input, seed, discrete, digest
    from system_campaign_uncertainty_math import RollingWitnessBounds
    hashes = retained_contract(cp, spec)
    validate_input(old, cp)
    rows = seed(old, cp)
    proof = spec['root_admission']['branch_uncertainty_proof']
    phase = RETAINED_PROOF_SEEDS[spec['root_admission_sha256']]
    need(proof['passed'] is True and len(rows) == phase['rows']
         and proof['rows'] == phase['new_rows'] and proof.get('retained_rows', 0) == phase['retained_rows']
         and len(rows) == proof['rows'] + proof.get('retained_rows', 0)
         and proof['all_comparisons_and_state_sets_verified'] is proof['all_math_watch_financial_chains_verified'] is True
         and rows[-1]['session'] == cp['source_cursor']
         and rows[-1]['after'] == discrete(cp['run']['state']['median5'])
         and rows[-1]['next_state_sha256'] == cp['run']['state_sha256']
         and digest(rows[-1]['after']) in {digest(v) for v in rows[-1]['possible_after']}
         and RollingWitnessBounds.restore(rows[-1]['math']).absolute.contains(
             cp['run']['state']['median5']['witness_nav'][-1]), 'FINANCIAL_RETAINED_PROOF_EXACT_COMMITTED_SEED')
    need(sha((old / 'stopped-review/uncertainty-certificate-review.json').read_bytes())
         == proof['hosted_canonical_transition_oracle_sha256'], 'FINANCIAL_RETAINED_PROOF_PRIOR_REVIEW_IDENTITY')
    raw = (old / 'branch-controller-qualification.json').read_bytes()
    qualified = json.loads(raw)
    need(qualified['passed'] is True and qualified['exact_controller_sources'] == hashes
         and qualified['ambiguous_comparisons_exhaustively_partitioned'] is True
         and qualified['all_possible_counters_retained_and_later_merged'] is True
         and qualified['actual_divergent_decisions_refused'] is True
         and qualified['historical_financial_sessions_advanced'] == 0,
         'FINANCIAL_RETAINED_PROOF_EXACT_PRIOR_QUALIFICATION')
    return hashes, rows, raw


def active_codec(backtest, old, cp):
    from system_campaign_financial_branches import Codec, INPUT, evidence
    from system_campaign_financial_projection import branch_loader_owner
    codec = branch_loader_owner(backtest.load_repair)
    need(isinstance(codec, Codec) and codec.evidence == evidence(old),
         'FINANCIAL_RETAINED_PROOF_SAME_ACTIVE_INPUT_CODEC')
    descriptors = [d for d in cp['repairs']
                   if json.loads((old / 'book/repairs' / d['filename']).read_bytes())['schema'] == INPUT]
    need(len(descriptors) == 1, 'FINANCIAL_RETAINED_PROOF_ONE_COMMITTED_MODEL')
    d, = descriptors
    loaded = backtest.load_repair(old / 'book/repairs' / d['filename'],
        resume_session=d['resume_session'], predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'])
    need(loaded.sha256 == d['sha256'] and any(loaded is obj for obj in codec.objects),
         'FINANCIAL_RETAINED_PROOF_ACTUAL_BOUND_MODEL_OBJECT')
    return codec


def run_retained(cp, out, args, observer, execution, spec, old):
    hosted()
    from research.pooled_vacancy_funding import backtest
    from system_campaign_alder_date_v2 import AlderDateV2
    from system_campaign_p02_retained_run import idempotent_dispatch
    from system_campaign_uncertainty_archive import preserve
    from system_campaign_financial_branches import Certificate
    from system_campaign_financial_future import prepare, ActualEvents
    from system_campaign_financial_resume import AdoptionGate
    hashes, rows, qualified = retained_seed(old, cp, spec)
    codec = active_codec(backtest, old, cp)
    from system_campaign_financial_compound_dispatch import selected
    compound = selected(cp, 'P07')
    compound_scope = nullcontext()
    with (out / 'branch-controller-qualification.json').open('xb') as stream:
        stream.write(qualified)
    preserve(old, out)
    directory = out / 'retained-proof-admission'
    directory.mkdir()
    alder = AlderDateV2(HERE / 'system-campaign-alder-unresolved-date.json')
    target = directory / 'alder-source.json'
    alder.hydrate(target)
    need(target.read_bytes() == (old / 'hydrated-alder-unresolved-date.json').read_bytes(),
         'FINANCIAL_RETAINED_PROOF_SAME_UNRESOLVED_NATIVE')
    source = json.loads((old / 'hydrated-uncertainty-event.json').read_bytes())
    unchanged = unchanged_input_phase(spec)
    if unchanged:
        save(out / UNCHANGED_INPUT, unchanged_input_receipt(cp, spec))
        path, loaded, gate, events = None, None, nullcontext(), nullcontext()
    else:
        path, loaded = prepare(cp, out, 'P07')
        gate = AdoptionGate(cp, out / 'book', out / MODEL_ADOPTION, loaded.sha256, loaded.earliest_affected_session)
        if compound is not None:
            need(hasattr(compound, 'ordinary_events'), 'FINANCIAL_RETAINED_COMPOUND_EXTERNAL_GATE_CAPABILITY')
            events = compound.ordinary_events(out, cp)
            compound_scope = compound.initial_context(cp, out, spec, loaded)
        else:
            events = ActualEvents(out, 'P07', cp=cp)
    certificate = Certificate(out, codec, alder.native, hashes, seed=rows, event_source=source)
    save(directory / 'seed.json', dict(parent_sha256=cp['sha256'], rows=len(rows),
        chain_sha256=rows[-1]['chain_sha256'], possible_after=rows[-1]['possible_after'],
        prior_qualification_reexecuted=False, prior_proof_rows_reexecuted=0,
        financial_source_changed=False, new_date_or_model_adoption=False))
    extra = [] if unchanged else ['--repair-overlay', str(path)]
    from system_campaign_financial_projection import initial_context, qualify_initial
    with initial_context(cp, out, 'P07') as projection:
        qualify_initial(projection, out, cp)
        with compound_scope, proof_scope(cp, spec), alder, idempotent_dispatch(alder), gate, certificate, observer, execution, events:
            code = backtest.main(args + extra)
    if not unchanged:
        boundary(out, MODEL_ADOPTION, cp, path.name, loaded.earliest_affected_session)
    return code


def suffix_review_tree():
    raw = (HERE / 'system_campaign_financial_branches.py').read_bytes()
    need(sha(raw) == BRANCH_SHA, 'FINANCIAL_RETAINED_PROOF_FROZEN_REVIEW_LOOP_SOURCE')
    fn, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'review']
    loop, = [n for n in fn.body if isinstance(n, ast.For) and ast.unparse(n.target) == '(index, row)']
    need(ast.unparse(loop.iter) == 'enumerate(rows)', 'FINANCIAL_RETAINED_PROOF_EXACT_REVIEW_ITERATOR')
    loop.iter = ast.parse('enumerate(rows, start=retained_count)', mode='eval').body
    current, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        and any(isinstance(a, ast.Constant) and a.value == 'BRANCH_EXACT_CURRENT_REPRESENTATIVE_STATE' for a in n.value.args)]
    return ast.fix_missing_locations(ast.Module(body=[loop, current], type_ignores=[]))


def review_new_rows(parent, cp, retained, rows, financial, *, median5, champion_config):
    import system_campaign_financial_branches as b
    from system_campaign_uncertainty_math import RollingWitnessBounds
    need(retained and rows is not retained and len(rows) == cp['completed'] - parent['completed']
         and all(parent['source_cursor'] < r['session'] <= cp['source_cursor'] for r in rows)
         and [r['session'] for r in rows] == sorted(financial), 'FINANCIAL_RETAINED_PROOF_EXACT_NEW_ROW_SCOPE')
    scope = dict(vars(b), rows=rows, retained_count=len(retained), cp=cp, financial=financial,
        math_state=RollingWitnessBounds.restore(retained[-1]['math']),
        possible=deepcopy(retained[-1]['possible_after']), representative=b.discrete(parent['run']['state']['median5']),
        median5=median5, champion_config=champion_config, total=0, maximum=len(retained[-1]['possible_after']))
    exec(compile(suffix_review_tree(), '<frozen-branch-new-suffix-review>', 'exec'), scope)
    return dict(rows=len(rows), exhaustive_leaves=scope['total'], maximum_possible_states=scope['maximum'],
                prior_proof_rows_reexecuted=0, every_reachable_decision_identical=True)


def review_retained(parent, evidence_root, out, spec, old):
    hosted()
    from research.pooled_vacancy_funding import journal
    from sentinel.controller import median5, champion_config
    from system_campaign_financial_branches import seed, validate_input, encoded, qualify_surface
    from system_campaign_financial_future import review_input, OVERLAY
    from system_campaign_uncertainty_archive import resolve
    hashes, retained, qualified = retained_seed(old, parent, spec)
    need((evidence_root / 'branch-controller-qualification.json').read_bytes() == qualified,
         'FINANCIAL_RETAINED_PROOF_QUALIFICATION_BYTES_PRESERVED')
    need(all(sha((Path('/variant') / n).read_bytes()) == h for n, h in hashes.items()),
         'FINANCIAL_RETAINED_PROOF_PHYSICAL_CONTROLLER_SOURCES')
    qualify_surface(Path('/variant/sentinel/controller/champion_frozen.py').read_bytes(),
                    Path('/variant/sentinel/controller/champion.py').read_bytes())
    original, _ = resolve(old)
    actual, _ = resolve(evidence_root)
    need(actual.name == original.name and actual.read_bytes() == original.read_bytes(),
         'FINANCIAL_RETAINED_PROOF_EVENT_GZIP_NAME_AND_BYTES_PRESERVED')
    cp = journal.read_checkpoint(evidence_root / 'book/checkpoint.json.gz')
    from system_campaign_financial_compound_dispatch import review_retained as compound_review_retained
    compound_review_retained(evidence_root, cp)
    if unchanged_input_phase(spec):
        review_unchanged_input(parent, cp, evidence_root, spec)
    else:
        earliest = review_input(parent, evidence_root, 'P07')
        adopted = boundary(evidence_root, MODEL_ADOPTION, parent, OVERLAY, earliest)
        need(cp['base'] == parent['base'] and cp['repairs'] == adopted['repairs']
             and cp['run']['input_sha256'] == adopted['run']['input_sha256'],
             'FINANCIAL_RETAINED_PROOF_ONLY_NEUTRAL_ORDINARY_SUCCESSOR')
    validate_input(evidence_root, cp)
    current = seed(evidence_root, cp)
    need(len(current) >= len(retained) and b''.join(encoded(r) + b'\n' for r in current[:len(retained)])
         == b''.join(encoded(r) + b'\n' for r in retained), 'FINANCIAL_RETAINED_PROOF_ENTIRE_PRIOR_PREFIX_UNCHANGED')
    from system_campaign_uncertainty_review import committed_rows
    financial = {r['session']: r for r in committed_rows(evidence_root / 'book', cp, 'daily')
                 if r['session'] > parent['source_cursor']}
    with proof_scope(parent, spec):
        result = review_new_rows(parent, cp, retained, current[len(retained):], financial,
                                 median5=median5, champion_config=champion_config)
    save(out / 'uncertainty-certificate-review.json', dict(result,
        schema='research.retained-leadership-branch-suffix-review/1', passed=True,
        checkpoint_sha256=cp['sha256'], parent_sha256=parent['sha256'], retained_rows=len(retained),
        through=cp['source_cursor'], prior_qualification_reexecuted=False,
        all_financial_watch_and_proof_identities_verified=True, full_period_complete=cp['completed'] == 2156))
