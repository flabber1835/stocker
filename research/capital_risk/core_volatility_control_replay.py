"""Align the existing control's own financial prefix to the shared inputs."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import time

from core_volatility_source import need, identity
from full_system_core import hosted, arguments
from full_system_benchmark import save
from core_volatility_control_equivalence import SOURCES, compiler, historical_spec, fork

PARENT = '0f2dbfe6ee37ea47e6d0240b2cf0713a95474712e5648b1cab574198252be815'
ORIGINAL = 'cf357b04513897586d869646cb0bdf850b5e051b4c847a75507a99e452ba847b'
MODELS = ('AAAP', 'SODA', 'SONC', 'BEL')


def own_scope(cp, arm, model, name=None):
    need(arm == 'CONTROL' and cp['sha256'] == PARENT and cp['completed'] == 21
         and cp['source_cursor'] == '2018-01-31' and model in MODELS and name in (None, model),
         'EXACT_FINANCIAL_CONTROL_REPLAY_PREDECESSOR')
    sid = SOURCES[model][3]
    state = cp['run']['state']
    need(not any(e['security_id'] == sid for e in state['wealth_core']['episodes'].values())
         and not any(p.get('security_id') == sid for p in state['pending']), 'CONTROL_REPLAY_OWN_UNHELD_UNORDERED_SCOPE')
    return []


def entrypoints(model):
    # Reuse source bodies only. No diagnostic book can initialize this replay.
    window = 'DECEMBER' if model in ('SODA', 'SONC') else model
    prepare, observe = compiler(model, PARENT, window)
    namespace = prepare.__globals__
    need(namespace is observe.__globals__, 'EXACT_REUSED_MODEL_NAMESPACE')
    namespace[SOURCES[model][2]] = lambda cp, arm, name=None: own_scope(cp, arm, model, name)
    namespace['__file__'] = __file__
    return prepare, observe


def combined_input(cp, root):
    from research.pooled_input_support import inputs
    from research.pooled_vacancy_funding.repair import load_repair
    import system_campaign_financial_future as original
    documents, terms, observers = [], [], []
    for model in MODELS:
        own_scope(cp, 'CONTROL', model)
        folder = root/model
        folder.mkdir()
        prepare, observe = entrypoints(model)
        extra, material = prepare(cp, folder, 'CONTROL', model) if model == 'BEL' else prepare(cp, folder, 'CONTROL')
        need(len(extra) == 2 and extra[0] == '--repair-overlay' and material['parent_outer_sha256'] == PARENT,
             'OWN_TYPED_REPLAY_MODEL_INPUT')
        documents.append(json.loads(Path(extra[1]).read_bytes()))
        terms.extend(material['terms'])
        observers.append(observe(folder, cp, material))
    document = dict(schema='terminal-repair/1', predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],
        source_evidence=[v for d in documents for v in d['source_evidence']],
        suppress=[v for d in documents for v in d['suppress']], add=[v for d in documents for v in d['add']])
    need(len(document['add']) == len(document['suppress']) == 4
         and {v['security_id'] for v in document['add']} == {SOURCES[m][3] for m in MODELS}, 'EXACT_FOUR_SHARED_REPLAY_TERMS')
    overlay = root/'shared-control-overlay.json'
    save(overlay, document)
    loaded = load_repair(overlay, resume_session=cp['source_cursor'], predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    audit = root/'combined-qualification'
    audit.mkdir()
    original.qualify(cp, {'terms': terms}, {}, inputs.load_actions(Path('/frozen/bundle')), loaded, overlay, audit)
    merged = {}
    for observer in observers:
        need(observer.arm == 'CONTROL' and not observer.scopes and not observer.saved and observer.current is None
             and type(observer).advance is original.ActualEvents.advance
             and type(observer).terminal is original.ActualEvents.terminal
             and not set(merged).intersection(observer.terms), 'UNCHANGED_SINGLE_REPLAY_OBSERVER_DELEGATE')
        merged.update(deepcopy(observer.terms))
    observed = observers[0]
    observed.terms, observed.out = merged, root
    need(set(merged) == {(v['session'], v['security_id']) for v in document['add']}, 'EXACT_REPLAY_OBSERVER_SCOPE')
    return overlay, observed


def inventory(root):
    from seal import sha256_file
    need(not any(p.is_symlink() for p in root.rglob('*')), 'REGULAR_IMMUTABLE_FINANCIAL_PARENT_ONLY')
    return {p.relative_to(root).as_posix(): dict(bytes=p.stat().st_size, sha256=sha256_file(p))
            for p in sorted(root.rglob('*')) if p.is_file()}


def run(previous, arm, maximum):
    hosted()
    need(previous == Path('/previous') and arm == 'CONTROL' and maximum == 1621, 'EXACT_BOUNDED_CONTROL_INPUT_REPLAY')
    from research.pooled_vacancy_funding import backtest
    from research.pooled_vacancy_funding.journal import read_checkpoint
    from system_campaign_readonly import review
    from system_campaign_acceleration import Execution
    from core_volatility_worker import qualify
    from system_campaign_space import DEFAULT
    request = json.loads(Path('/out/request.json').read_bytes())
    binding = json.loads(Path('/out/source-bindings.json').read_bytes())
    evidence = json.loads(Path('/out/input-equivalence-admission.json').read_bytes())
    need(evidence['diagnostic_only'] and evidence['exact_noop'] is False
         and evidence['whole_cipher_authenticated_before_parsing'] and not evidence['financial_continuation_authorized'],
         'AUTHENTICATED_NEGATIVE_CHECK_IS_EVIDENCE_ONLY')
    need(binding == json.loads((previous/'source-bindings.json').read_bytes())
         and binding['experiment'] == identity('CONTROL') and binding['parameters'] == DEFAULT, 'EXACT_ORIGINAL_CONTROL_REPLAY_SOURCE')
    original = read_checkpoint(previous/'book/checkpoint.json.gz')
    need(original['sha256'] == ORIGINAL and original['completed'] == 1642 and original['source_cursor'] == '2024-07-12',
         'FINANCIAL_PARENT_NOT_A_DIAGNOSTIC_BOOK')
    started = time.monotonic()
    save(Path('/out/canonical-qualification.json'), qualify('CONTROL'))
    qualified = time.monotonic()
    review(previous/'book', Path('/out/parent-preflight.json'))
    before = inventory(previous)
    selected, cp = historical_spec(previous, request['selected_history'], 'AAAP')
    for model in MODELS:
        own_scope(cp, arm, model)
    lineage = Path('/out/lineage')
    lineage.mkdir()
    shutil.copyfile(previous/'book/checkpoint.json.gz', lineage/'original-financial-parent-1642.json.gz')
    shutil.copyfile(selected, lineage/'selected-own-parent-21.json.gz')
    shutil.copyfile(previous/'source-bindings.json', lineage/'parent-source-bindings.json')
    save(lineage/'immutable-original-input-inventory.json', dict(members=before, original_parent=ORIGINAL,
        selected_parent=PARENT, retained_readonly_original_artifact=request['parents']['CONTROL'],
        original_committed_suffix_not_labelled_uncommitted=True, diagnostic_book_authority_used=False))
    book = Path('/out/book')
    fork(previous, book, selected, cp)
    material = Path('/out/common-input-replay')
    material.mkdir()
    overlay, observed = combined_input(cp, material)
    warmed = time.monotonic()
    with Execution('FAST', signal_closes=1) as execution:
        with observed:
            code = backtest.main(arguments(book, True, maximum)+['--repair-overlay', str(overlay)])
    save(Path('/out/acceleration-proof.json'), execution.proof())
    need(inventory(previous) == before, 'ENTIRE_ORIGINAL_FINANCIAL_INPUT_UNCHANGED')
    current = read_checkpoint(book/'checkpoint.json.gz')
    save(Path('/out/experiment-outcome.json'), dict(arm=arm, complete=False, completed=current['completed'],
        session=current['source_cursor'], checkpoint_sha256=current['sha256'], maximum_requested=maximum,
        qualification_seconds=qualified-started, warmup_seconds=warmed-qualified,
        financial_seconds=time.monotonic()-warmed, new_financial_transitions=current['completed']-21,
        input_alignment_replay=True, selected_financial_parent_sha256=PARENT, common_models=list(MODELS),
        production_contacted=False, diagnostic_book_authority_used=False))
    need(code == 0, 'CONTROL_REPLAY_REFUSAL_PRESERVED')


def review(previous, evidence, output):
    hosted()
    from research.pooled_vacancy_funding.journal import read_checkpoint
    from system_campaign_readonly import review as canonical_review
    from seal import sha256_file
    request = json.loads((evidence/'request.json').read_bytes())
    saved = json.loads((evidence/'lineage/immutable-original-input-inventory.json').read_bytes())
    need(saved['members'] == inventory(previous) and saved['original_parent'] == ORIGINAL
         and saved['selected_parent'] == PARENT and not saved['diagnostic_book_authority_used'], 'REPLAY_ORIGINAL_INPUT_REVIEW')
    selected, cp = historical_spec(previous, request['selected_history'], 'AAAP')
    need(sha256_file(selected) == sha256_file(evidence/'lineage/selected-own-parent-21.json.gz')
         and read_checkpoint(previous/'book/checkpoint.json.gz')['sha256'] == ORIGINAL, 'EXACT_OWN_FINANCIAL_HISTORY_REVIEW')
    for stream, commitment in cp['journals'].items():
        with (evidence/'book'/(stream+'.jsonl')).open('rb') as f:
            raw = f.read(commitment['bytes'])
        from core_volatility_source import sha
        need(len(raw) == commitment['bytes'] and sha(raw) == commitment['prefix_sha256'], 'REPLAY_ORIGINAL_SELECTED_PREFIX_UNCHANGED')
    material = output/'independent-common-input-qualification'
    material.mkdir()
    overlay, _ = combined_input(cp, material)
    need(overlay.read_bytes() == (evidence/'common-input-replay/shared-control-overlay.json').read_bytes(),
         'INDEPENDENT_EXACT_FOUR_MODEL_REQUALIFICATION')
    canonical_review(evidence/'book', output/'core-review.json')
    proof = json.loads((output/'core-review.json').read_bytes())
    save(output/'core-review.json', dict(proof, common_input_replay_verified=True,
        original_financial_parent_sha256=ORIGINAL, selected_financial_parent_sha256=PARENT,
        common_models=list(MODELS), diagnostic_book_authority_used=False))
