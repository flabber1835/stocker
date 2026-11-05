"""Own-book neutral input boundaries and the existing certified sensor gateway."""
from copy import deepcopy
from contextlib import nullcontext
import ast
import gzip
import json
from pathlib import Path

from full_system_benchmark import need, save
from full_system_core import hosted
from system_campaign_facts import digest, sha
from system_campaign_pxd_pause import adoption

HERE = Path(__file__).parent
DATE_OVERLAY = 'alder-date-financial-overlay.json'
DATE_ADOPTION = 'date-input-adoption'
MODEL_ADOPTION = 'input-adoption'
ORDINARY_ADOPTION = 'ordinary-input-adoption'
OWN_POLICY_CATALOG = 'system-campaign-qualified-own-uncertainty-input-facts.json'
OWN_SOURCE_CATALOG = 'system-campaign-qualified-own-uncertainty-source-data.json'
OWN_POLICY_SHA = '54e98d2adf23bf9b51e8561e66375f991f9d5faeb138dfa439cc3d2f250f3158'
OWN_SOURCE_SHA = '758d53f593aab9fa411f652ea362f6cfde1c4144bda175edc3244a7a7e8b0c7e'
OWN_POLICY_CLOSED_GENERATIONS = {'fadb3f24477ed70b04d4241f0ed61258a1d477e58ef50e9de3b49096fd9ea089': ('2dfc5b30f486d40f97ab4f93c21ae75862714f0d0b410bd56228b137370329d0', '532e1e4ca1317d3631235cb0316860112a355ab1b4cf4f61704f5583245540fd', 'bd698ea48738875baa59796f671ccf7439885976a5b439bf4d9bd4cddeb9164f'), '75639e35fe4ed78b15eacdc808347c1932aa6e2cdbc4d7733cd836d1e532defc': ('bd698ea48738875baa59796f671ccf7439885976a5b439bf4d9bd4cddeb9164f',), '6a867f721b31cd5fb71d1b965820facf2b48939158ed8d35432257eabd0d0ff1': ('2dfc5b30f486d40f97ab4f93c21ae75862714f0d0b410bd56228b137370329d0', 'bd698ea48738875baa59796f671ccf7439885976a5b439bf4d9bd4cddeb9164f')}
INTEGRATION = 'system-campaign-uncertainty-integration-request.json'
BRANCH_SHA = 'b19a93be7b6887c1b92a5a676fefecc5477addfaf99efcf1f18f45eafb6140ef'
POINT_RETURN_SEEDS = frozenset({'75e0e1cfee3007e1ff47a638e62597ed49820c1ecc8a7c1cfc7675c9db800719', '532e1e4ca1317d3631235cb0316860112a355ab1b4cf4f61704f5583245540fd', 'ad8b330eaed295dac664c4ea7392e8eb38956cb78765f51a2f4e05d6515a1c95', '3cbfc7cce74b9c9401b4ca06ca685f7fc1b2fd19e4a6ae16fc4829c4d6ba1ec0', '6abf375981b345fcdfebc5db1f68664a1f401783a7e13f6a3cf2e9c8bd6a2a22', '99c02d182abd329b1e94bde8a8ec1d1ad2f7a9883220fb2e79a9e9766f96300b', '8b3bbe1f16e0daa175d031ca9a95fab95755dea50b33b66c36061af4ba77a998', '672a0a0a7560d1b3d4658e6c0e79c3f4259391ac4a7f2d3ecb58e505f5132ef3', 'f7f86bf917f7d2718c8e360a4e1d1de2c2d90d6dd94406e581c6712201a8b776'})
POINT_WITNESS_SHA = '177d5906b9ecd6b33512999ef8408704d5814ba5f69a4d8284fb22b62b7f5cf1'
UNCHANGED_INPUT_SEEDS = frozenset({'ad8b330eaed295dac664c4ea7392e8eb38956cb78765f51a2f4e05d6515a1c95', 'f7f86bf917f7d2718c8e360a4e1d1de2c2d90d6dd94406e581c6712201a8b776'})
UNCHANGED_INPUT = 'retained-proof-admission/unchanged-input.json'
RETAINED_PROOF_SEEDS = {
    '75e0e1cfee3007e1ff47a638e62597ed49820c1ecc8a7c1cfc7675c9db800719': {'completed': 1196, 'source_cursor': '2022-09-30', 'rows': 742, 'new_rows': 149, 'retained_rows': 593},
    '532e1e4ca1317d3631235cb0316860112a355ab1b4cf4f61704f5583245540fd': {'completed': 1047, 'source_cursor': '2022-02-28', 'rows': 593, 'new_rows': 19, 'retained_rows': 574},
    'ad8b330eaed295dac664c4ea7392e8eb38956cb78765f51a2f4e05d6515a1c95': {'completed': 1028, 'source_cursor': '2022-01-31', 'rows': 574, 'new_rows': 42, 'retained_rows': 532},
    '3cbfc7cce74b9c9401b4ca06ca685f7fc1b2fd19e4a6ae16fc4829c4d6ba1ec0': {'completed': 1028, 'source_cursor': '2022-01-31', 'rows': 574, 'new_rows': 42, 'retained_rows': 532},
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
    from system_campaign_financial_additional_sensor import phase as additional_phase
    if additional_phase(spec) is not None:
        from system_campaign_ordinary_augmentation_router import run as additional
        return additional(cp, out, args, rows, observer, execution, spec, old)
    phase = own_policy_phase(spec)
    if phase is not None:
        if phase['mode'] == 'INITIAL':
            return run_own_initial(cp, out, args, rows, observer, execution, spec, old)
        return run_retained(cp, out, args, observer, execution, spec, old)
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
    from system_campaign_financial_additional_sensor import phase as additional_phase
    if additional_phase(spec) is not None:
        from system_campaign_ordinary_augmentation_router import review as additional
        return additional(cp, evidence_root, out, spec, old)
    phase = own_policy_phase(spec)
    if phase is not None:
        if phase['mode'] == 'INITIAL':
            return review_own_initial(cp, evidence_root, out, spec, old)
        return review_retained(cp, evidence_root, out, spec, old)
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
    from system_campaign_financial_additional_sensor import unchanged_phase, validate_admission_metadata
    if unchanged_phase(spec):
        return validate_admission_metadata(spec)
    cp = dict(sha256=spec['outer_sha256'], completed=spec['measured_closes'],
              source_cursor=spec['selected_session'], base=spec['base'])
    retained_contract(cp, spec)
    phase = retained_phase(spec)
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
    if own_retained_phase(spec) is None:
        need(phase['completed'] < 756 or point_return_phase(spec),
             'FINANCIAL_RETAINED_ADMISSION_EXACT_POINT_RETURN_REGISTRATION')
    else:
        need(phase['proof_growth'] == 'INTERVAL', 'OWN_POLICY_RETAINED_EXACT_EXISTING_INTERVAL_PROOF')
    return phase


def retained_contract(cp, spec):
    if own_retained_phase(spec) is not None:
        return own_retained_contract(cp, spec)
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
    phase = retained_phase(spec)
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
    arm = spec['arm']
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
    compound = selected(cp, arm)
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
    unchanged = unchanged_input_phase(spec) or own_unchanged_input_phase(spec)
    if unchanged:
        save(out / UNCHANGED_INPUT, own_unchanged_input_receipt(cp, spec) if own_unchanged_input_phase(spec) else unchanged_input_receipt(cp, spec))
        path, loaded, gate, events = None, None, nullcontext(), nullcontext()
    else:
        path, loaded = prepare(cp, out, arm)
        gate = AdoptionGate(cp, out / 'book', out / MODEL_ADOPTION, loaded.sha256, loaded.earliest_affected_session)
        if compound is not None:
            need(hasattr(compound, 'ordinary_events'), 'FINANCIAL_RETAINED_COMPOUND_EXTERNAL_GATE_CAPABILITY')
            events = compound.ordinary_events(out, cp)
            compound_scope = compound.initial_context(cp, out, spec, loaded)
        else:
            events = ActualEvents(out, arm, cp=cp)
    certificate = Certificate(out, codec, alder.native, hashes, seed=rows, event_source=source)
    save(directory / 'seed.json', dict(parent_sha256=cp['sha256'], rows=len(rows),
        chain_sha256=rows[-1]['chain_sha256'], possible_after=rows[-1]['possible_after'],
        prior_qualification_reexecuted=False, prior_proof_rows_reexecuted=0,
        financial_source_changed=False, new_date_or_model_adoption=False))
    extra = [] if unchanged else ['--repair-overlay', str(path)]
    from system_campaign_financial_projection import initial_context, qualify_initial
    with initial_context(cp, out, arm) as projection:
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
    arm = spec['arm']
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
    if own_unchanged_input_phase(spec):
        review_own_unchanged_input(parent, cp, evidence_root, spec)
    elif unchanged_input_phase(spec):
        review_unchanged_input(parent, cp, evidence_root, spec)
    else:
        earliest = review_input(parent, evidence_root, arm)
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


def policy_encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def own_policy_catalog():
    raw = (HERE / OWN_POLICY_CATALOG).read_bytes()
    need(sha(raw) == OWN_POLICY_SHA, 'OWN_POLICY_EXACT_QUALIFIED_RECORD_BYTES')
    value = json.loads(raw)
    need(value['schema'] == 'research.qualified-own-uncertainty-input-facts/1'
         and all(value[k] is False for k in ('canonical_financial_source_changed', 'production_contacted', 'provider_metadata_upgraded'))
         and value['phases'] and all(key == phase['root_admission_sha256'] for key, phase in value['phases'].items()),
         'OWN_POLICY_EXPLICIT_PHASE_CATALOG_SCOPE')
    for previous, roots in OWN_POLICY_CLOSED_GENERATIONS.items():
        need(all(root in value['phases'] for root in roots)
             and sha(policy_encoded(dict(value, phases={root: value['phases'][root] for root in roots}))) == previous,
             'OWN_POLICY_CLOSED_GENERATION_RECORD_BYTES')
    return value


def own_policy_phase(spec):
    if not isinstance(spec, dict) or spec.get('arm') == 'P07':
        return None
    phases = own_policy_catalog()['phases']
    phase = phases.get(spec.get('root_admission_sha256'))
    if phase is None:
        need(not (spec.get('arm') in {p['arm'] for p in phases.values()}
                  and spec.get('retained_uncertainty_model') is not None),
             'OWN_POLICY_NO_UNREGISTERED_MODEL_BEARING_ROOT')
        return None
    need(phase['mode'] in ('INITIAL', 'RETAINED') and phase['arm'] == spec['arm']
         and phase['outer_sha256'] == spec['outer_sha256']
         and phase['completed'] == spec['measured_closes']
         and phase['source_cursor'] == spec['selected_session']
         and phase['financial_authority'] is False and phase['source_DATA_qualified'] is True,
         'OWN_POLICY_EXACT_DECLARED_ARM_ROOT_AXIS_AND_MODE')
    return phase


def uncertainty_phase(spec):
    return isinstance(spec, dict) and (spec.get('arm') == 'P07' or own_policy_phase(spec) is not None)


def own_policy_source_names():
    catalog = own_policy_catalog()
    return sorted({OWN_POLICY_CATALOG, OWN_SOURCE_CATALOG,
                   *(name for phase in catalog['phases'].values() for name in phase['policy_source_files'])})


def own_model_declaration(phase, *, policy_catalog_sha256=None):
    selected_sha = OWN_POLICY_SHA if policy_catalog_sha256 is None else policy_catalog_sha256
    need(selected_sha == OWN_POLICY_SHA or phase['root_admission_sha256'] in OWN_POLICY_CLOSED_GENERATIONS.get(selected_sha, ()),
         'OWN_POLICY_MODEL_DECLARATION_EXACT_RETAINED_CATALOG_GENERATION')
    return dict(input_schema='research.leadership-branch-uncertainty-input/1',
        root_admission_sha256=phase['root_admission_sha256'], origin_root_admission_sha256=phase.get('origin_root_admission_sha256', phase['root_admission_sha256']),
        policy_catalog_sha256=selected_sha, source_payload_sha256=phase['source_payload_sha256'],
        source_review_sha256=phase['source_review_sha256'], source_qualification_sha256=phase['source_qualification_sha256'],
        contract_sha256=phase['policy_source_files']['system-campaign-financial-branch-contract.json'],
        every_reachable_canonical_decision_must_match=True, original_strict_guard_unchanged=True)


def own_source_binding(cp, phase):
    """Read closed source/input facts; actual event ownership remains guarded later."""
    need(cp['sha256'] == phase['outer_sha256'] and cp['completed'] == phase['completed']
         and cp['source_cursor'] == phase['source_cursor'], 'OWN_POLICY_EXACT_CURRENT_CANONICAL_PARENT')
    need(all(sha((HERE / name).read_bytes()) == expected for name, expected in phase['policy_source_files'].items())
         and phase['policy_source_files']['system_campaign_financial_branches.py'] == BRANCH_SHA,
         'OWN_POLICY_ALL_UNCHANGED_FACT_CONTRACT_AND_BRANCH_SOURCES')
    raw = (HERE / OWN_SOURCE_CATALOG).read_bytes()
    need(sha(raw) == OWN_SOURCE_SHA, 'OWN_POLICY_EXACT_CLOSED_SOURCE_CATALOG_BYTES')
    catalog = json.loads(raw)
    need(catalog['schema'] == 'research.qualified-own-uncertainty-source-data/1'
         and phase['source_data_file'] == OWN_SOURCE_CATALOG,
         'OWN_POLICY_DECLARED_SOURCE_CATALOG')
    source = catalog['sources'][phase['source_payload_sha256']]
    payload, review, qualification = (source[k] for k in ('payload', 'review', 'qualification'))
    need(sha(policy_encoded(payload)) == phase['source_payload_sha256']
         and sha(policy_encoded(review)) == phase['source_review_sha256']
         and sha(policy_encoded(qualification)) == phase['source_qualification_sha256']
         and review['passed'] is qualification['passed'] is True
         and review['source_identity_qualified_for_separate_future_input_review'] is True
         and review['source_value_or_settlement_timing_qualified'] is False
         and qualification['review_sha256'] == phase['source_review_sha256']
         and qualification['source_identity_only'] is True,
         'OWN_POLICY_EXACT_INDEPENDENT_SOURCE_DATA_AND_QUALIFICATION')
    clock = phase['source_clock']
    need((review['run_id'], review['head'], review['artifact_id']) == (clock['run_id'], clock['head'], clock['artifact_id'])
         and payload['arm'] == review['arm'] == phase['arm']
         and payload['producer_sha256'] == phase['source_producer_sha256']
         and payload['parent_outer_sha256'] == review['parent_outer_sha256'] == cp['sha256']
         and payload['parent_cursor'] == cp['source_cursor']
         and review['parent_root_admission_sha256'] == phase['root_admission_sha256']
         and payload['scope_sha256'] == review['scope_sha256'] == phase['source_scope_sha256']
         and payload['archive_sha256'] == cp['base']['archive_sha256']
         and payload['bundle_sha256'] == cp['base']['bundle_sha256']
         and payload['financial_authority'] is payload['input_adopted'] is payload['production_contacted'] is payload['provider_metadata_upgraded'] is False
         and type(payload['financial_sessions_advanced']) is int and payload['financial_sessions_advanced'] == 0,
         'OWN_POLICY_EXACT_FRESH_SOURCE_CLOCK_ROOT_HISTORY_AND_ZERO_AUTHORITY')
    from system_campaign_financial_future import registered_scope
    need(payload['scope'] == registered_scope(phase['source_scope_sha256']), 'OWN_POLICY_EXACT_REGISTERED_SOURCE_SCOPE')
    positions = lambda sid: [dict(slot_id=e['slot_id'], ticker=e['ticker'], quantity=e['current_shares'], entry_date=e['entry_date'])
        for _, e in sorted(cp['run']['state']['wealth_core']['episodes'].items(), key=lambda pair: int(pair[0])) if e['security_id'] == sid]
    need(len(payload['terms']) == len(payload['scope']['terms']) == len(review['terms'])
         and len(payload['additional_rows']) == len(payload['scope']['additional_rows']) == len(review['additional_rows']),
         'OWN_POLICY_COMPLETE_SOURCE_MEMBER_COUNTS')
    for actual, declared, closed in zip(payload['terms'] + payload['additional_rows'],
                                      payload['scope']['terms'] + payload['scope']['additional_rows'],
                                      review['terms'] + review['additional_rows'], strict=True):
        row, witness, sid = actual['source_row'], actual['identity_witness'], declared['security_id']
        expected = {k: row[k] for k in ('session', 'security_id', 'ticker', 'issuer_id', 'listing_first_session', 'security_type_eligible')}
        expected['source_observation_sha256'] = digest(row)
        need(witness == closed['identity_witness'] == expected and (row['session'], sid, row['ticker']) ==
             (declared['session'], row['security_id'], declared['ticker'])
             and positions(sid) == actual['parent_positions'] == declared['parent_positions'] == closed['parent_positions']
             and not any(p['security_id'] == sid for p in cp['run']['state']['pending'])
             and review['parent_pending_context'][sid] == []
             and review['parent_selected'][sid] == (sid in cp['run']['state']['median5']['selected']),
             'OWN_POLICY_EVERY_FROZEN_IDENTITY_AND_CURRENT_PARENT_ROLE')
        if 'native_term' in actual:
            need(actual['native_term'] == closed['native_term']
                 and digest(actual['native_term']) == declared['native_term_sha256']
                 and actual['native_term']['session'] == declared['native_session'],
                 'OWN_POLICY_EVERY_EXACT_SOURCE_NATIVE_PREIMAGE')
    event = phase['event']
    date_policy = json.loads((HERE / 'system-campaign-alder-unresolved-date.json').read_bytes())
    need(all(event[k] == date_policy[k] for k in ('security_id', 'ticker', 'native_session',
             'effective_session', 'native_term_sha256', 'known_cash_leg', 'maximum_conditional_later_cash'))
         and event['rights_per_share'] == date_policy['contingent_rights_per_share']
         and date_policy['preserve_unresolved_consideration'] is True,
         'OWN_POLICY_EXACT_ORIGINAL_UNRESOLVED_DATE_AND_CONSIDERATION_CONTRACT')
    actual, = [t for t in payload['terms'] if t['native_term']['security_id'] == event['security_id']]
    need(event['known_cash_leg'] == '18.00' and event['rights_per_share'] == '1' and event['maximum_conditional_later_cash'] == '2.00'
         and actual['native_term'] == event['native_term'] and digest(actual['native_term']) == event['native_term_sha256']
         and actual['identity_witness'] == event['identity_witness']
         and actual['parent_positions'] == event['parent_positions'] == [] and event['parent_pending'] == []
         and review['parent_selected'][event['security_id']] == event['parent_selected'] is True,
         'OWN_POLICY_EXACT_UNOWNED_UNORDERED_SELECTED_SENSOR_NOT_CASH_VALUATION')
    hashes = json.loads((HERE / INTEGRATION).read_bytes())['canonical_controller_sources']
    need(len(hashes) == 6 and all(cp['base']['sources'].get(name) == value for name, value in hashes.items()),
         'OWN_POLICY_UNCHANGED_SIX_CANONICAL_CONTROLLER_SOURCES')
    return payload, hashes


def own_initial_for_parent(cp, arm):
    phases = [p for p in own_policy_catalog()['phases'].values()
              if p['arm'] == arm and p['mode'] == 'INITIAL' and p['outer_sha256'] == cp['sha256']]
    need(len(phases) <= 1, 'OWN_POLICY_UNIQUE_INITIAL_PARENT_BINDING')
    if not phases:
        return None
    phase = phases[0]
    from system_campaign_financial_partial import root_spec
    spec = root_spec(arm, phase['root_admission_sha256'])
    need(own_policy_phase(spec) == phase, 'OWN_POLICY_INITIAL_SOURCE_USES_ITS_OWN_ADMITTED_ROOT')
    payload, _ = own_source_binding(cp, phase)
    return phase, payload


def paused_own_adoption(cp, out, args, rows, path, earliest, directory):
    """Use existing canonical pause/gate and verify one exact neutral boundary."""
    hosted()
    from research.pooled_vacancy_funding import backtest, journal
    from system_campaign_financial_resume import AdoptionGate
    from system_campaign_uncertainty_integration import AdmissionPause
    from system_campaign_factual_run import SeededObservation
    names = {ORDINARY_ADOPTION: 'future-financial-overlay.json', DATE_ADOPTION: DATE_OVERLAY,
             MODEL_ADOPTION: 'branch-uncertainty-input.json'}
    need(directory in names and path == out / names[directory] and earliest > cp['source_cursor']
         and not (out / directory).exists(), 'OWN_POLICY_DISTINCT_FRESH_ADOPTION_DIRECTORY')
    gate = AdoptionGate(cp, out / 'book', out / directory, sha(path.read_bytes()), earliest)
    capture = out / (directory + '-correlation-inputs.jsonl.gz')
    with gate, SeededObservation(capture, rows), AdmissionPause() as pause:
        code = backtest.main(args + ['--repair-overlay', str(path)])
    need(code == 0 and pause.paused and pause.calls == 0 and gate.accepted,
         'OWN_POLICY_CANONICAL_ZERO_SESSION_ADOPTION_REQUIRED')
    current = boundary(out, directory, cp, path.name, earliest)
    need(journal.read_checkpoint(out / 'book/checkpoint.json.gz') == current
         and gzip.decompress(capture.read_bytes()) == b''.join(rows),
         'OWN_POLICY_EXACT_NEUTRAL_BOOK_AND_NO_NEW_OBSERVATION_ROWS')
    return current


def reconstruct_own_date(parent, evidence_root, output):
    from system_campaign_uncertainty_facts import hydrate
    output.mkdir()
    alder, _ = prepare_date(parent, output)
    hydrate(alder.native, output / 'hydrated-uncertainty-event.json')
    for name in ('hydrated-alder-unresolved-date.json', DATE_OVERLAY, 'hydrated-uncertainty-event.json'):
        need((output / name).read_bytes() == (evidence_root / name).read_bytes(),
             'OWN_POLICY_INDEPENDENT_EXACT_DATE_AND_EVENT_INPUT_BYTES')
    return alder


def run_own_initial(cp, out, args, rows, observer, execution, spec, old):
    hosted()
    from research.pooled_vacancy_funding import backtest, journal
    from system_campaign_financial_future import prepare, review_input, ActualEvents, hydration_name
    from system_campaign_p02_retained_run import idempotent_dispatch, qualify_dispatch
    from system_campaign_uncertainty_facts import hydrate
    from system_campaign_financial_branches import overlay, evidence, Codec, Certificate, qualify, parse, validate_input
    phase = own_policy_phase(spec)
    need(phase is not None and phase['mode'] == 'INITIAL', 'OWN_POLICY_ONLY_EXACT_INITIAL_PHASE')
    _, hashes = own_source_binding(cp, phase)
    qualify(out, hashes)
    ordinary, loaded = prepare(cp, out, spec['arm'])
    need([t['ticker'] for t in json.loads((out / hydration_name(cp)).read_bytes())['terms']]
         == phase['ordinary_expected_tickers'], 'OWN_POLICY_COMPLETE_DECLARED_ORDINARY_BATCH_BEFORE_ADOPTION')
    current = paused_own_adoption(cp, out, args, rows, ordinary, loaded.earliest_affected_session, ORDINARY_ADOPTION)
    need(review_input(cp, out, spec['arm']) == loaded.earliest_affected_session,
         'OWN_POLICY_ORDINARY_RECONSTRUCTION_BEFORE_DATE_BOUNDARY')
    events = ActualEvents(out, spec['arm'], cp=cp)
    alder, date_loaded = prepare_date(current, out)
    event_source = hydrate(alder.native, out / 'hydrated-uncertainty-event.json')
    with alder, idempotent_dispatch(alder):
        qualify_dispatch(alder, date_loaded, out)
        dated = paused_own_adoption(current, out, args, rows, out / DATE_OVERLAY,
                                   phase['event']['native_session'], DATE_ADOPTION)
        reconstruction = out / 'own-policy-input-reconstruction'
        reconstruct_own_date(current, out, reconstruction)
        path = overlay(dated, out)
        codec = Codec(evidence(out))
        with codec:
            for cursor, predecessor in ((dated['source_cursor'], '0' * 64),
                                        (phase['event']['effective_session'], dated['run']['checkpoint_sha256'])):
                try:
                    backtest.load_repair(path, resume_session=cursor, predecessor_checkpoint_sha256=predecessor)
                except ValueError:
                    pass
                else:
                    raise ValueError('REFUSED_OWN_POLICY_TYPED_PARSER_FALSIFIER')
            backtest.load_repair(path, resume_session=dated['source_cursor'], predecessor_checkpoint_sha256=dated['run']['checkpoint_sha256'])
            modeled = paused_own_adoption(dated, out, args, rows, path, phase['event']['effective_session'], MODEL_ADOPTION)
            reconstructed = overlay(dated, reconstruction)
            need(reconstructed.read_bytes() == path.read_bytes(), 'OWN_POLICY_MODEL_RECONSTRUCTION_BEFORE_FINANCIAL_ADVANCE')
            parse(reconstructed, resume_session=dated['source_cursor'], predecessor_checkpoint_sha256=dated['run']['checkpoint_sha256'], expected_evidence=evidence(reconstruction))
            validate_input(out, modeled)
            certificate = Certificate(out, codec, alder.native, hashes, event_source=event_source)
            save(out / 'own-uncertainty-admission.json', dict(arm=spec['arm'], root_parent_sha256=cp['sha256'],
                ordinary_input_successor_sha256=current['sha256'], date_input_successor_sha256=dated['sha256'],
                model_input_successor_sha256=modeled['sha256'], qualified_policy_record_sha256=OWN_POLICY_SHA,
                qualified_controller_sources=hashes, reused_frozen_controller_and_math_sources=True,
                new_branch_observer_qualification=True, diagnostic_state_adopted=False,
                proof_kind='EXHAUSTIVE_REACHABLE_CANONICAL_DECISION_INVARIANCE',
                owned_or_ordered_right_valuation_authorized=False, representative_is_not_a_valuation=True,
                original_parent_selected=phase['event']['parent_selected']))
            with certificate, observer, execution, events:
                code = backtest.main(args)
            actual = journal.read_checkpoint(out / 'book/checkpoint.json.gz')
            need(actual['base'] == cp['base'] and actual['repairs'] == modeled['repairs']
                 and actual['run']['input_sha256'] == modeled['run']['input_sha256'],
                 'OWN_POLICY_FINANCE_ONLY_AFTER_THREE_EXACT_INPUT_BOUNDARIES')
    return code


def review_own_initial(cp, evidence_root, out, spec, old):
    hosted()
    from system_campaign_financial_future import review_input, OVERLAY
    from system_campaign_financial_branches import overlay, evidence, Codec, parse, review as review_certificate
    from system_campaign_financial_resume import seed_rows
    phase = own_policy_phase(spec)
    need(phase is not None and phase['mode'] == 'INITIAL', 'OWN_POLICY_REVIEW_ONLY_EXACT_INITIAL_PHASE')
    own_source_binding(cp, phase)
    earliest = review_input(cp, evidence_root, spec['arm'])
    ordinary = boundary(evidence_root, ORDINARY_ADOPTION, cp, OVERLAY, earliest)
    reconstruct_own_date(ordinary, evidence_root, out / 'own-policy-input-reconstruction')
    dated = boundary(evidence_root, DATE_ADOPTION, ordinary, DATE_OVERLAY, phase['event']['native_session'])
    target = out / 'own-policy-input-reconstruction'
    path = overlay(dated, target)
    need(path.read_bytes() == (evidence_root / path.name).read_bytes(), 'OWN_POLICY_REVIEW_EXACT_TYPED_MODEL_BYTES')
    parse(path, resume_session=dated['source_cursor'], predecessor_checkpoint_sha256=dated['run']['checkpoint_sha256'], expected_evidence=evidence(target))
    modeled = boundary(evidence_root, MODEL_ADOPTION, dated, path.name, phase['event']['effective_session'])
    original_rows = b''.join(seed_rows(old, cp, spec))
    for name in (ORDINARY_ADOPTION, DATE_ADOPTION, MODEL_ADOPTION):
        need(gzip.decompress((evidence_root / (name + '-correlation-inputs.jsonl.gz')).read_bytes()) ==
             original_rows,
             'OWN_POLICY_REVIEW_ZERO_OBSERVATIONS_AT_EACH_NEUTRAL_BOUNDARY')
    actual = json.loads(gzip.decompress((evidence_root / 'book/checkpoint.json.gz').read_bytes()))
    need(actual['base'] == cp['base'] and actual['repairs'] == modeled['repairs']
         and actual['run']['input_sha256'] == modeled['run']['input_sha256'],
         'OWN_POLICY_REVIEW_FINAL_INPUT_IS_EXACT_THIRD_NEUTRAL_SUCCESSOR')
    with Codec(evidence(evidence_root)):
        review_certificate(evidence_root, out / 'uncertainty-certificate-review.json')
    save(out / 'own-uncertainty-input-boundaries-review.json', dict(passed=True, arm=spec['arm'],
        root_parent_sha256=cp['sha256'], ordinary_successor_sha256=ordinary['sha256'],
        date_successor_sha256=dated['sha256'], model_successor_sha256=modeled['sha256'],
        all_three_actual_gzip_boundaries_neutral=True, complete_input_bytes_independently_reconstructed=True,
        no_qualifier_state_adopted=True, financial_sessions_reexecuted=0))


def own_retained_phase(spec):
    phase = own_policy_phase(spec)
    return phase if phase is not None and phase['mode'] == 'RETAINED' else None


def own_unchanged_input_phase(spec):
    phase = own_retained_phase(spec)
    if phase is None:
        return False
    need(phase['ordinary_input_mode'] in ('UNCHANGED', 'NEW_QUALIFIED_ORDINARY'),
         'OWN_POLICY_EXPLICIT_REGISTERED_ORDINARY_INPUT_MODE')
    return phase['ordinary_input_mode'] == 'UNCHANGED'


def own_unchanged_input_receipt(cp, spec):
    phase = own_retained_phase(spec)
    need(phase is not None and own_unchanged_input_phase(spec)
         and cp['sha256'] == phase['outer_sha256'] and cp['completed'] == phase['completed']
         and cp['source_cursor'] == phase['source_cursor'],
         'OWN_POLICY_UNCHANGED_INPUT_EXACT_REGISTERED_PARENT')
    return dict(schema='research.own-retained-interval-input/1', arm=spec['arm'],
        parent_outer_sha256=cp['sha256'], root_admission_sha256=spec['root_admission_sha256'],
        completed=cp['completed'], source_cursor=cp['source_cursor'], input_sha256=cp['run']['input_sha256'],
        repairs=deepcopy(cp['repairs']), proof_growth='RETAINED_OUTWARD_ROUNDED_INTERVAL_STATE_SET',
        origin_root_admission_sha256=phase['origin_root_admission_sha256'],
        source_payload_sha256=phase['source_payload_sha256'], new_factual_overlay=False,
        financial_source_changed=False)


def review_own_unchanged_input(parent, current, evidence_root, spec):
    expected = own_unchanged_input_receipt(parent, spec)
    need((evidence_root / UNCHANGED_INPUT).read_bytes() == policy_encoded(expected)
         and current['base'] == parent['base'] and current['repairs'] == parent['repairs']
         and current['run']['input_sha256'] == parent['run']['input_sha256']
         and not (evidence_root / MODEL_ADOPTION).exists()
         and not (evidence_root / 'future-financial-overlay.json').exists(),
         'OWN_POLICY_RETAINED_INTERVAL_EXACT_UNCHANGED_INPUT')


def retained_phase(spec):
    phase = own_retained_phase(spec)
    return phase if phase is not None else RETAINED_PROOF_SEEDS[spec['root_admission_sha256']]


def own_retained_contract(cp, spec):
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec)
    phase = own_retained_phase(spec)
    need(phase is not None, 'OWN_POLICY_EXACT_REGISTERED_RETAINED_PHASE')
    origin = own_policy_catalog()['phases'][phase['origin_root_admission_sha256']]
    need(origin['mode'] == 'INITIAL' and origin['arm'] == phase['arm'] == spec['arm']
         and sha(policy_encoded(origin)) == phase['origin_record_sha256']
         and phase['policy_source_files'] == origin['policy_source_files']
         and all(phase[k] == origin[k] for k in ('policy', 'source_payload_sha256', 'source_review_sha256',
                    'source_qualification_sha256', 'source_producer_sha256', 'source_scope_sha256', 'source_clock', 'event'))
         and phase['proof_growth'] == 'INTERVAL'
         and phase['ordinary_input_mode'] in ('UNCHANGED', 'NEW_QUALIFIED_ORDINARY')
         and cp['sha256'] == spec['outer_sha256'] == phase['outer_sha256']
         and cp['completed'] == spec['measured_closes'] == phase['completed']
         and cp['source_cursor'] == spec['selected_session'] == phase['source_cursor']
         and cp['base'] == spec['base'], 'OWN_POLICY_RETAINED_EXACT_ORIGIN_AND_CURRENT_ROOT')
    need(all(sha((HERE / name).read_bytes()) == value for name, value in phase['policy_source_files'].items())
         and sha((HERE / 'system_campaign_financial_branches.py').read_bytes()) == BRANCH_SHA,
         'OWN_POLICY_RETAINED_UNCHANGED_POLICY_AND_BRANCH_IMPLEMENTATION')
    hashes = json.loads((HERE / INTEGRATION).read_bytes())['canonical_controller_sources']
    need(len(hashes) == 6 and all(cp['base']['sources'].get(name) == value for name, value in hashes.items()),
         'OWN_POLICY_RETAINED_UNCHANGED_CANONICAL_CONTROLLER_SOURCES')
    return hashes


def retained_model_scope(root, parent, spec):
    """Scope first reporting to its exact original request, later runs to registered roots."""
    if spec['arm'] == 'P07':
        return True
    phase = own_retained_phase(spec) if 'root_admission' in spec else None
    if phase is not None:
        return True
    raw = (Path(root) / 'request.json').read_bytes()
    request = json.loads(raw)
    need(sha(raw) == spec['request_sha256'] and request['execution_mode'] == 'OWN_ADMITTED_FINANCIAL_CONTINUATION'
         and request['financial_resume_authorized'] is True and request['financial_source_changed'] is False,
         'OWN_POLICY_REPORT_EXACT_ORIGINAL_FINANCIAL_REQUEST')
    declared = request['selected_research_models'].get(spec['arm'])
    need(type(declared) is dict, 'OWN_POLICY_REPORT_REQUIRES_EXPLICIT_ORIGINAL_MODEL_DECLARATION')
    record = own_policy_catalog()['phases'].get(declared['root_admission_sha256'])
    need(record is not None and record['arm'] == spec['arm']
         and declared['policy_catalog_sha256'] == request['sources'][OWN_POLICY_CATALOG]
         and declared == own_model_declaration(record, policy_catalog_sha256=declared['policy_catalog_sha256'])
         and request['admitted_checkpoints'][spec['arm']] == record['outer_sha256']
         and spec['monthly_seed_root_admission_sha256'] == record['root_admission_sha256']
         and parent['completed'] == spec['measured_closes'] > record['completed']
         and parent['sha256'] == spec['outer_sha256']
         and spec['retained_uncertainty_model'] == 'research.leadership-branch-uncertainty-input/1',
         'OWN_POLICY_REPORT_EXACT_QUALIFIED_SEED_SAVED_PREFIX_AND_MODEL')
    return True


def typed_reporting_declaration(request, arm):
    """Expose only the declaration needed by an exact captured financial target."""
    from system_campaign_financial_additional_sensor import report_declaration
    additional = report_declaration(request, arm)
    if additional is not None:
        return additional
    declared = request['selected_research_models'].get(arm)
    need(type(declared) is dict and request['execution_mode'] == 'OWN_ADMITTED_FINANCIAL_CONTINUATION'
         and request['financial_resume_authorized'] is True and request['financial_source_changed'] is False,
         'OWN_POLICY_TYPED_REPORT_REQUIRES_ORIGINAL_QUALIFIED_FINANCIAL_PHASE')
    phase = own_policy_catalog()['phases'].get(declared['root_admission_sha256'])
    need(phase is not None and phase['arm'] == arm
         and request['sources'][OWN_POLICY_CATALOG] == declared['policy_catalog_sha256']
         and declared == own_model_declaration(phase, policy_catalog_sha256=declared['policy_catalog_sha256'])
         and request['admitted_checkpoints'][arm] == phase['outer_sha256'],
         'OWN_POLICY_TYPED_REPORT_EXACT_DECLARED_MODEL_SOURCE_AND_ADMITTED_SEED')
    return dict(retained_uncertainty_model=declared['input_schema'])
