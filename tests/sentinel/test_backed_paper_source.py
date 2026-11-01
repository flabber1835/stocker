"""Actual retained-origin composition and fresh backed-PAPER account boundaries.

The origin manifest is an immutable Git witness. Book/configuration/environment
objects below are explicitly synthetic; source readers, reviewed source policy,
mechanical decision comparison, SQL fences/binding and HMAC receipts stay real.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import ast
import hashlib
import inspect
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import backed_paper_source as backed
from sentinel import backup_runtime_authority, binding, identity, local_paper
from sentinel import rolling_checkpoint as origin, rolling_daily_checkpoint as daily
from sentinel import rolling_runtime, runtime_admission as admission, schema, shadow_runtime
from sentinel import structural_refactor_source_basis as structural
from sentinel.feed.rolling_contract import canonical_json, digest
from tests.sentinel.test_retained_binding_reuse import proof_scope
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401


ORIGIN = '90a960547b58bb245c998ae3f70d0baed1fe95d0'
ORIGIN_SOURCE = 'c2950194bf6ea20bbac66d5bcf356c118e8518d4e9c9d3dda17b08ff10080003'
ORIGIN_MANIFEST_SHA = 'f8476bfe8eb8736c40604035522ada091800ad5415131137d6f38d4aafd76226'
ACCOUNT = 'PABACKEDSOURCETEST'
ORIGIN_WEALTH_SOURCE = '8395c6af9c82c0c54e339d199edc3becdb80b4179d639319ef0b1570a7753b71'
PERFORMANCE_WEALTH_SOURCE = 'a744170c805095ab1f1f19a1b7fb89984edc33648f123cfa390d23f5163ea96a'


@pytest.fixture
def owner_mode(monkeypatch):
    monkeypatch.setenv(local_paper.MODE_ENV, local_paper.MODE)
    monkeypatch.setenv(local_paper.ACCOUNT_ENV, ACCOUNT)
    monkeypatch.setenv(local_paper.BACKUP_POLICY_ENV, local_paper.BACKUP_POLICY)
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')


def _environment_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _rebind_origin(case, *, wealth_core_hash=None):
    """Keep origin/authentication consistent when testing the policy itself."""
    previous = deepcopy(case.source['environment'])
    previous['sentinel_source'].update(
        files=len(case.manifest['files']), hash=admission.source_closure(case.manifest['files']))
    if wealth_core_hash is not None:
        previous['wealth_core_source']['hash'] = wealth_core_hash
    value = _environment_hash(previous)
    case.checkpoint.runtime_identity.update(
        git_commit=case.manifest['revision'],
        sentinel_source_sha256=previous['sentinel_source']['hash'],
        wealth_core_source_sha256=previous['wealth_core_source']['hash'],
        environment_identity_sha256=value, validated_source_identity_sha256=value)
    reviewed = case.checkpoint.runtime_identity['reviewed_shadow_config']
    reviewed['validated_source_identity_sha256'] = value
    case.checkpoint.runtime_identity['validated_shadow_config_sha256'] = digest(reviewed)


def _rebind_current(case, root):
    """A changed candidate declares its real bytes, rather than a stale hash."""
    actual = admission._source_files(root)
    case.source['environment']['sentinel_source'].update(
        path=str(root), files=len(actual), hash=admission.source_closure(actual))
    value = _environment_hash(case.source['environment'])
    case.source['identity_hash'] = value
    case.context['runtime'].update(
        sentinel_source_sha256=admission.source_closure(actual),
        environment_identity_sha256=value, validated_source_identity_sha256=value)
    reviewed = case.context['runtime']['reviewed_shadow_config']
    reviewed['validated_source_identity_sha256'] = value
    case.context['runtime']['validated_shadow_config_sha256'] = digest(reviewed)
    return actual


@pytest.fixture
def handover(owner_mode):
    raw = (Path(__file__).parent / 'fixtures/retained-source-history/90a96054.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGIN_MANIFEST_SHA
    manifest = json.loads(raw)
    assert manifest['revision'] == ORIGIN
    assert len(manifest['files']) == 338
    assert admission.source_closure(manifest['files']) == ORIGIN_SOURCE
    root = identity._imported_package_root('sentinel')
    assert root == Path(admission.__file__).parent
    actual = admission._source_files(root)
    environment = {
        'compatible': True,
        'sentinel_source': {'root': 'sentinel', 'path': str(root),
            'files': len(actual), 'hash': admission.source_closure(actual)},
        'wealth_core_source': {'hash': '2' * 64},
        'dependencies': 'explicit synthetic unchanged environment',
    }
    source_hash = _environment_hash(environment)
    reviewed = {'schema': 'sentinel.shadow-reviewed-config/1',
        'observation_id': 'backed-source-boundary', 'starting_cash': '50000',
        'execution_model': shadow_runtime.SHADOW_EXECUTION_MODEL,
        'cutoff_policy': shadow_runtime.SHADOW_CUTOFF_POLICY,
        'publication_timing_policy': shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY,
        'validated_source_identity_sha256': source_hash}
    runtime = {'schema': 'sentinel.shadow-runtime-identity/1',
        'git_commit': '6' * 40, 'runtime_image_digest': 'sha256:' + '7' * 64,
        'sentinel_source_sha256': admission.source_closure(actual),
        'wealth_core_source_sha256': '2' * 64,
        'environment_identity_sha256': source_hash,
        'validated_source_identity_sha256': source_hash,
        'validated_shadow_config_sha256': digest(reviewed),
        'validated_data_publication_sha256': '3' * 64,
        'reviewed_shadow_config': reviewed}
    strategy = {'strategy': 'synthetic unchanged source-boundary setting'}
    context = {'observation_id': reviewed['observation_id'], 'starting_cash': '50000',
        'controller': shadow_runtime._strategy()[0], 'strategy': strategy, 'runtime': runtime}
    checkpoint = origin.Checkpoint(observation_id=reviewed['observation_id'], starting_cash='50000',
        strategy_identity=deepcopy(strategy), runtime_identity=deepcopy(runtime), session='2026-10-16',
        snapshot={'snapshot_id': '4' * 64}, publication={'version': 1},
        genesis_sha256='5' * 64, record_sha256='8' * 64, state_sha256='9' * 64,
        input_value={'synthetic_source_boundary': True}, warmup_input_identity={},
        precommit_timing={}, pitr={})
    source = {'environment': environment, 'identity_hash': source_hash,
        'deployment_artifacts': {'schema': 'sentinel.runtime-artifacts/1',
            'git_commit': runtime['git_commit'], 'runtime_image_digest': runtime['runtime_image_digest'],
            'test_image_digest': runtime['runtime_image_digest']}}
    case = SimpleNamespace(root=root, actual=actual, manifest=manifest,
        checkpoint=checkpoint, context=context, source=source)
    _rebind_origin(case)
    return case


@pytest.fixture
def performance_handover(handover, tmp_path, monkeypatch):
    """Real unequal complete package commitments, synthetic book/account only."""
    from sentinel import performance_source_basis as performance
    case = handover
    package_reader = identity._imported_package_root
    root = tmp_path / 'wealth_core'
    shutil.copytree(package_reader('stock_strategy_shared.wealth_core'), root,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    actual = admission._source_files(root)
    profile = performance._profile()
    member = profile['modules']['stock_strategy_shared.wealth_core.feed']
    assert len(actual) == 28
    assert actual['feed.py'] == member['after']
    assert member['before'] == 'afa9324811921271a139500764aee19b85dec96f9a499d392c12f25f97e6ee32'
    predecessor = {**actual, 'feed.py': member['before']}
    # Both complete-package constants were independently exported from Git.
    assert admission.source_closure(predecessor) == ORIGIN_WEALTH_SOURCE
    assert admission.source_closure(actual) == PERFORMANCE_WEALTH_SOURCE
    assert performance.wealth_core_source_hash(root)['hash'] == ORIGIN_WEALTH_SOURCE
    monkeypatch.setattr(identity, '_imported_package_root', lambda name:
        root if name == 'stock_strategy_shared.wealth_core' else package_reader(name))
    case.wealth_root = root
    case.source['environment']['wealth_core_source'] = identity.source_hash(root)
    case.context['runtime']['wealth_core_source_sha256'] = PERFORMANCE_WEALTH_SOURCE
    _rebind_current(case, case.root)
    _rebind_origin(case, wealth_core_hash=ORIGIN_WEALTH_SOURCE)
    return case


def _prove(case):
    return admission.prove_compatibility(case.manifest, case.checkpoint,
        case.context, source=case.source)


def test_actual_unequal_wealth_package_composes_without_rewriting_attestations(performance_handover):
    case = performance_handover
    before = deepcopy((case.source, case.context, case.checkpoint.model_dump(by_alias=True)))
    assert _prove(case) == digest(admission.SourceManifest.model_validate(
        case.manifest).model_dump(by_alias=True))
    assert (case.source, case.context, case.checkpoint.model_dump(by_alias=True)) == before
    assert identity.source_hash(case.wealth_root)['hash'] == PERFORMANCE_WEALTH_SOURCE
    assert case.source['environment']['wealth_core_source']['hash'] == PERFORMANCE_WEALTH_SOURCE
    assert case.context['runtime']['wealth_core_source_sha256'] == PERFORMANCE_WEALTH_SOURCE
    assert case.checkpoint.runtime_identity['wealth_core_source_sha256'] == ORIGIN_WEALTH_SOURCE


def _rebind_changed_wealth(case):
    actual = identity.source_hash(case.wealth_root)
    case.source['environment']['wealth_core_source'] = actual
    case.context['runtime']['wealth_core_source_sha256'] = actual['hash']
    _rebind_current(case, case.root)


@pytest.mark.parametrize('defect', ['neighbor', 'missing', 'extra'])
def test_unknown_complete_wealth_package_refuses_even_with_actual_attestation(performance_handover, defect):
    case = performance_handover
    path = case.wealth_root / 'engine.py'
    assert path.is_file()
    if defect == 'neighbor':
        path.write_bytes(path.read_bytes() + b'\nUNREVIEWED = True\n')
    elif defect == 'missing':
        path.unlink()
    else:
        (case.wealth_root / 'unreviewed_member.py').write_text('UNREVIEWED = True\n')
    _rebind_changed_wealth(case)
    with pytest.raises(admission.Refused, match='^RETAINED_SOURCE_CLOSURE_CHANGED$'):
        _prove(case)


@pytest.mark.parametrize('defect', ['attestation', 'context'])
def test_wealth_projection_requires_fresh_actual_raw_bindings(performance_handover, defect):
    case = performance_handover
    if defect == 'attestation':
        case.source['environment']['wealth_core_source']['hash'] = 'f' * 64
    else:
        case.context['runtime']['wealth_core_source_sha256'] = 'f' * 64
    with pytest.raises(admission.Refused, match='^RETAINED_SOURCE_CLOSURE_CHANGED$'):
        _prove(case)


def test_wealth_attestation_cannot_substitute_the_historical_hash(performance_handover):
    case = performance_handover
    # The old literal must not skip the unequal-package proof while the actual
    # current process still declares the reviewed candidate's different hash.
    case.source['environment']['wealth_core_source']['hash'] = ORIGIN_WEALTH_SOURCE
    assert case.context['runtime']['wealth_core_source_sha256'] == PERFORMANCE_WEALTH_SOURCE
    with pytest.raises(admission.Refused, match='^RETAINED_SOURCE_CLOSURE_CHANGED$'):
        _prove(case)


def test_wealth_projection_cannot_choose_another_historical_package(performance_handover):
    case = performance_handover
    _rebind_origin(case, wealth_core_hash='f' * 64)
    with pytest.raises(admission.Refused, match='^RETAINED_SOURCE_CLOSURE_CHANGED$'):
        _prove(case)


@pytest.mark.parametrize('defect', ['attestation_count', 'comparison_count', 'missing_root'])
def test_wealth_projection_requires_nonempty_matching_package_counts(
        performance_handover, monkeypatch, defect):
    from sentinel import performance_source_basis as performance
    case = performance_handover
    if defect == 'attestation_count':
        case.source['environment']['wealth_core_source']['files'] = 27
    elif defect == 'comparison_count':
        compare = performance.wealth_core_source_hash
        monkeypatch.setattr(performance, 'wealth_core_source_hash',
            lambda root: {**compare(root), 'files': 0})
    else:
        package_reader = identity._imported_package_root
        monkeypatch.setattr(identity, '_imported_package_root', lambda name:
            None if name == 'stock_strategy_shared.wealth_core' else package_reader(name))
    with pytest.raises(admission.Refused, match='^RETAINED_SOURCE_CLOSURE_CHANGED$'):
        _prove(case)


def test_wealth_projection_rejects_altered_performance_witness(
        performance_handover, tmp_path, monkeypatch):
    from sentinel import performance_source_basis as performance
    path = tmp_path / 'altered-performance-witness.json'
    path.write_bytes(performance.PROFILE.read_bytes() + b'\n')
    monkeypatch.setattr(performance, 'PROFILE', path)
    with pytest.raises(admission.Refused, match='^RETAINED_SOURCE_CLOSURE_CHANGED$'):
        _prove(performance_handover)


@pytest.mark.parametrize('defect', ['ordinary', 'live', 'legacy_backup', 'origin', 'manifest'])
def test_wealth_projection_requires_the_exact_backed_owner_edge(performance_handover, monkeypatch, defect):
    case = performance_handover
    if defect == 'ordinary':
        monkeypatch.delenv(local_paper.MODE_ENV)
    elif defect == 'live':
        monkeypatch.setenv('ALPACA_BASE_URL', 'https://api.alpaca.markets')
    elif defect == 'legacy_backup':
        monkeypatch.delenv(local_paper.BACKUP_POLICY_ENV)
    else:
        if defect == 'origin':
            case.manifest['revision'] = 'f' * 40
        else:
            case.manifest['files']['core/kernel.py'] = 'f' * 64
        _rebind_origin(case, wealth_core_hash=ORIGIN_WEALTH_SOURCE)
    with pytest.raises(admission.Refused):
        _prove(case)


def test_wealth_projection_keeps_the_complete_predecessor_environment_guard(performance_handover):
    case = performance_handover
    case.source['environment']['dependencies'] = 'unreviewed computational dependency'
    _rebind_current(case, case.root)
    with pytest.raises(admission.Refused, match='^RETAINED_COMPUTATIONAL_ENVIRONMENT_CHANGED$'):
        _prove(case)


@pytest.mark.parametrize('guard,defect', [
    ("or actual_wealth['hash'] != env['wealth_core_source']['hash']", 'attestation'),
    ("or actual_wealth['hash'] != context['runtime']['wealth_core_source_sha256']", 'context'),
])
def test_removed_wealth_raw_binding_guards_are_detected(performance_handover, monkeypatch, guard, defect):
    text = inspect.getsource(admission.prove_compatibility)
    dispatch_guard = ("or env['wealth_core_source']['hash'] != "
                      "context['runtime']['wealth_core_source_sha256']")
    assert text.count(guard) == 1 and text.count(dispatch_guard) == 1
    # Pre-dispatch equality and the direct fresh-byte comparison jointly guard
    # each claimed hash. Remove both checks of that claim, not just a redundant
    # comparison protected by the other, to execute its falsifier independently.
    namespace = {}
    mutated = text.replace(guard, 'or False').replace(dispatch_guard, 'or False')
    exec(compile(mutated, '<wealth-raw-binding-falsifier>', 'exec'),
        admission.__dict__, namespace)
    monkeypatch.setattr(admission, 'prove_compatibility', namespace['prove_compatibility'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_wealth_projection_requires_fresh_actual_raw_bindings(performance_handover, defect)


def test_removed_wealth_dispatch_binding_guard_is_detected(performance_handover, monkeypatch):
    text = inspect.getsource(admission.prove_compatibility)
    guard = ("or env['wealth_core_source']['hash'] != "
             "context['runtime']['wealth_core_source_sha256']")
    assert text.count(guard) == 1
    namespace = {}
    exec(compile(text.replace(guard, 'or False'), '<wealth-dispatch-binding-falsifier>', 'exec'),
        admission.__dict__, namespace)
    monkeypatch.setattr(admission, 'prove_compatibility', namespace['prove_compatibility'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_wealth_attestation_cannot_substitute_the_historical_hash(performance_handover)


def test_removed_wealth_historical_package_guard_is_detected(performance_handover, monkeypatch):
    text = inspect.getsource(admission.prove_compatibility)
    guard = "or historical_wealth['hash'] != old['wealth_core_source_sha256']"
    assert text.count(guard) == 1
    namespace = {}
    exec(compile(text.replace(guard, 'or False'), '<wealth-package-falsifier>', 'exec'),
        admission.__dict__, namespace)
    monkeypatch.setattr(admission, 'prove_compatibility', namespace['prove_compatibility'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_unknown_complete_wealth_package_refuses_even_with_actual_attestation(
            performance_handover, 'neighbor')


def _scope(case):
    result = backed.scope_for(revision=case.manifest['revision'],
        source_sha256=admission.source_closure(case.manifest['files']), actual=case.actual)
    assert result is not None
    return result


def test_actual_origin_composes_with_unpatched_current_source_and_real_admission(handover):
    assert structural.historical_view(handover.actual) is not handover.actual
    assert admission._source_files(handover.root) == handover.actual
    assert _scope(handover).matches_manifest(ORIGIN, handover.manifest['files'])
    assert admission.prove_compatibility(handover.manifest, handover.checkpoint,
        handover.context, source=handover.source) == digest(
            admission.SourceManifest.model_validate(handover.manifest).model_dump(by_alias=True))


def _use_current_strategy_with_synthetic_prior_semantics(case):
    # The old semantics digest is explicit synthetic evidence, not a claim
    # about the production book. All actual selected financial settings stay.
    current = deepcopy(shadow_runtime._strategy()[1])
    assert 'data_semantics_source_sha256' in current
    assert 'controller_rule_sha256' in current
    previous = {**current, 'data_semantics_source_sha256': 'd' * 64}
    assert previous != current
    case.context['strategy'] = current
    case.checkpoint = case.checkpoint.model_copy(update={'strategy_identity': previous})


def test_actual_source_composition_accepts_only_the_existing_strategy_migration(handover):
    from sentinel.economic_migration import compatible
    _use_current_strategy_with_synthetic_prior_semantics(handover)
    assert compatible(handover.checkpoint.strategy_identity, handover.context['strategy'])
    assert admission.prove_compatibility(handover.manifest, handover.checkpoint,
        handover.context, source=handover.source) == digest(
            admission.SourceManifest.model_validate(handover.manifest).model_dump(by_alias=True))
    handover.context['strategy']['controller_rule_sha256'] = 'f' * 64
    assert not compatible(handover.checkpoint.strategy_identity, handover.context['strategy'])
    with pytest.raises(admission.Refused, match='^RETAINED_BOOK_CONFIGURATION_CHANGED$'):
        admission.prove_compatibility(handover.manifest, handover.checkpoint,
            handover.context, source=handover.source)


@pytest.mark.parametrize('defect', ['revision', 'hash', 'missing', 'extra'])
def test_rebound_unknown_origin_cannot_borrow_the_backed_edge(handover, defect):
    case = handover
    if defect == 'revision':
        case.manifest['revision'] = 'f' * 40
    elif defect == 'hash':
        case.manifest['files']['core/kernel.py'] = 'f' * 64
    elif defect == 'missing':
        del case.manifest['files']['core/kernel.py']
    else:
        case.manifest['files']['unreviewed_origin.py'] = 'f' * 64
    _rebind_origin(case)
    with pytest.raises(admission.Refused):
        admission.prove_compatibility(case.manifest, case.checkpoint,
            case.context, source=case.source)


@pytest.mark.parametrize('defect', ['neighbor', 'economic', 'missing', 'extra'])
def test_internally_attested_current_neighbor_still_refuses(handover, tmp_path, monkeypatch, defect):
    case = handover
    root = tmp_path / 'candidate'
    shutil.copytree(case.root, root, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    if defect == 'missing':
        (root / 'panel/model.py').unlink()
    elif defect == 'extra':
        (root / 'unreviewed_candidate.py').write_text('UNREVIEWED = True\n')
    else:
        path = root / ('core/decision.py' if defect == 'economic' else 'panel/model.py')
        path.write_bytes(path.read_bytes() + b'\nUNREVIEWED = True\n')
    actual = _rebind_current(case, root)
    _rebind_origin(case)
    assert admission.source_closure(actual) == case.context['runtime']['sentinel_source_sha256']
    monkeypatch.setattr(identity, '_imported_package_root', lambda _: root)
    with pytest.raises(admission.Refused, match='^OWNER_PAPER_CURRENT_SOURCE_UNSEALED$'):
        admission.prove_compatibility(case.manifest, case.checkpoint,
            case.context, source=case.source)


@pytest.mark.parametrize('defect', ['ordinary', 'live', 'legacy_backup', 'unknown_backup', 'foreign_mode'])
def test_backed_source_edge_requires_its_actual_operating_policy(handover, monkeypatch, defect):
    # Scope identification must survive withdrawn permission so retained/cached
    # admissions can still enforce that permission at the deployment boundary.
    scope = _scope(handover)
    if defect == 'ordinary':
        monkeypatch.delenv(local_paper.MODE_ENV)
    elif defect == 'live':
        monkeypatch.setenv('ALPACA_BASE_URL', 'https://api.alpaca.markets')
    elif defect == 'legacy_backup':
        monkeypatch.delenv(local_paper.BACKUP_POLICY_ENV)
    elif defect == 'unknown_backup':
        monkeypatch.setenv(local_paper.BACKUP_POLICY_ENV, 'UNREVIEWED')
    else:
        monkeypatch.setenv(local_paper.MODE_ENV, 'UNREVIEWED')
    assert backed.scope_for(revision=ORIGIN, source_sha256=ORIGIN_SOURCE,
        actual=handover.actual) is not None
    with pytest.raises(backed.Refused):
        scope.require_mode()
    with pytest.raises(admission.Refused):
        admission.prove_compatibility(handover.manifest, handover.checkpoint,
            handover.context, source=handover.source)


def test_mechanical_decision_edge_accepts_only_the_reviewed_complete_ast(handover):
    scope = _scope(handover)
    old = handover.manifest['seam_sources']['core/decision.py'].encode()
    current = (handover.root / 'core/decision.py').read_bytes()
    assert scope.decision_compatible(old, current)
    changes = [
        (b'if negative:', b'if False:'),
        (b'retained_targets: Mapping[str, Decimal] | None = None,',
         b'retained_targets: Mapping[str, Decimal] | None = {},'),
        (b'targets=retained_targets,', b'targets=None,'),
        (b'identity(schema=DATA_SEMANTICS_IDENTITY_SCHEMA)', b'identity(schema="unreviewed")'),
        (b'wealth_core_source_hash(package_root)', b'wealth_core_source_hash(None)'),
    ]
    for old_bytes, new_bytes in changes:
        assert current.count(old_bytes) == 1
        assert not scope.decision_compatible(old, current.replace(old_bytes, new_bytes))
    assert not scope.decision_compatible(old + b'\n# changed original bytes\n', current)
    assert not scope.decision_compatible(old, b'not valid Python (')


def test_mechanical_decision_guard_removal_is_detected(handover, monkeypatch):
    scope = _scope(handover)
    monkeypatch.setattr(type(scope), 'decision_compatible', lambda *_: True)
    with pytest.raises(AssertionError):
        test_mechanical_decision_edge_accepts_only_the_reviewed_complete_ast(handover)


def test_isolated_mechanical_ast_reversal_keeps_every_other_statement(handover):
    # Deliberately exercise the mechanical checker below its raw-hash fences.
    # The composed candidate-byte mutants above independently exercise those
    # fences; they cannot serve as evidence that this AST comparison ran.
    old = handover.manifest['seam_sources']['core/decision.py'].encode()
    current = (handover.root / 'core/decision.py').read_bytes()
    assert backed._reverse_decision(old, current)
    held_member = b'    "sentinel.execution.held_targets",\n'
    retained = b'        retained_targets: Mapping[str, Decimal] | None = None,\n'
    application = (b'    from sentinel.execution import held_targets\n'
        b'    sized = held_targets.apply(sized, targets=retained_targets,\n'
        b'        canonical_target=target, marks=current_marks)\n')
    basket = b'    basket = desired_basket(sized)\n'
    performance_import = (b'    from sentinel.performance_source_basis import '
                          b'wealth_core_source_hash\n')
    performance_call = b'    source = wealth_core_source_hash(package_root)\n'
    performance = performance_import + performance_call
    changes = [
        (held_member, b''),
        (held_member, held_member * 2),
        (b'    "sentinel.execution.numeric",\n    "sentinel.feed.action_source",\n',
         b'    "sentinel.feed.action_source",\n    "sentinel.execution.numeric",\n'),
        (retained, b''),
        (retained, retained * 2),
        (retained, retained.replace(b'= None', b'= {}')),
        (b'        rollout_state: RolloutState | None = None,\n' + retained,
         retained + b'        rollout_state: RolloutState | None = None,\n'),
        (application, application * 2),
        (application + basket, basket + application),
        (b'targets=retained_targets,', b'targets=None,'),
        (b'identity(schema=DATA_SEMANTICS_IDENTITY_SCHEMA)', b'identity(schema="unreviewed")'),
        (b'if negative:', b'if False:'),
        (basket, b'    basket = {}\n'),
        (b'def data_semantics_source_identity() -> dict[str, object]:',
         b'def data_semantics_source_identity(argument=None) -> dict[str, object]:'),
        (performance_import, b''),
        (performance, performance * 2),
        (performance_import, performance_import.replace(
            b'performance_source_basis', b'unreviewed_source_basis')),
        (performance_import, performance_import.replace(
            b'wealth_core_source_hash', b'wealth_core_source_hash as unchecked')),
        (performance_call, b'    source = identity.source_hash(package_root)\n'),
        (performance_call, performance_call.replace(b'package_root', b'None')),
        (performance_call, performance_call.replace(
            b'package_root)', b'package_root, _contribution=None)')),
        (performance_call, performance_call * 2),
        (performance, performance_call + performance_import),
        (performance, performance + b'    source = {}\n'),
    ]
    for needle, replacement in changes:
        assert current.count(needle) == 1, needle
        assert not backed._reverse_decision(old, current.replace(needle, replacement)), needle
    assert old.count(b'if negative:') == 1
    assert not backed._reverse_decision(old.replace(b'if negative:', b'if False:'), current)


def test_isolated_ast_guard_removal_is_detected(handover, monkeypatch):
    monkeypatch.setattr(backed, '_reverse_decision', lambda *_: True)
    with pytest.raises(AssertionError):
        test_isolated_mechanical_ast_reversal_keeps_every_other_statement(handover)


def test_mode_guard_removal_is_detected(handover, monkeypatch):
    scope = _scope(handover)
    monkeypatch.setattr(type(scope), 'require_mode', lambda *_: None)
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_backed_source_edge_requires_its_actual_operating_policy(
            handover, monkeypatch, 'legacy_backup')


def test_exact_origin_and_successor_pairs_never_widen(handover):
    scope = _scope(handover)
    previous = handover.manifest['files']
    comparison = structural.historical_view(handover.actual)
    assert scope.matches_manifest(ORIGIN, previous)
    assert not scope.matches_manifest('f' * 40, previous)
    assert not scope.matches_manifest(ORIGIN, {**previous, 'core/kernel.py': 'f' * 64})
    changed = [name for name, old in previous.items()
        if comparison[name] != old and name not in admission.SEAMS]
    assert changed
    for name in changed:
        assert scope.source_allowed(name, previous[name], comparison[name])
        assert not scope.source_allowed(name, 'f' * 64, comparison[name])
        assert not scope.source_allowed(name, previous[name], 'f' * 64)
    assert not scope.source_allowed('core/unreviewed.py', 'f' * 64, 'f' * 64)
    for name in admission.SEAMS:
        assert not scope.source_allowed(name, previous[name], comparison[name])


def test_closed_manifest_guard_removal_is_detected(handover, monkeypatch):
    monkeypatch.setattr(type(_scope(handover)), 'matches_manifest', lambda *_: True)
    with pytest.raises(AssertionError):
        test_exact_origin_and_successor_pairs_never_widen(handover)


@pytest.mark.parametrize('defect', ['raw_bytes', 'authority', 'origin_revision',
    'origin_hash', 'missing_origin', 'extra_baseline'])
def test_new_profile_digest_cannot_widen_the_independent_policy(tmp_path, monkeypatch, defect):
    raw = backed.PROFILE.read_bytes()
    if defect == 'raw_bytes':
        changed = raw + b' '
    else:
        value = json.loads(raw)
        if defect == 'authority':
            value['authority_effect'] = 'LIVE'
        elif defect == 'origin_revision':
            value['origin_revision'] = 'f' * 40
        elif defect == 'origin_hash':
            value['origin_files']['core/kernel.py'] = 'f' * 64
        elif defect == 'missing_origin':
            del value['origin_files']['core/kernel.py']
        else:
            value['baseline_files']['unreviewed.py'] = 'f' * 64
        changed = json.dumps(value, sort_keys=True).encode()
        monkeypatch.setattr(backed, 'PROFILE_SHA256', hashlib.sha256(changed).hexdigest())
    path = tmp_path / 'source-policy.json'
    path.write_bytes(changed)
    monkeypatch.setattr(backed, 'PROFILE', path)
    with pytest.raises(backed.Refused, match='^OWNER_PAPER_SOURCE_PROFILE_CHANGED$'):
        backed._profile()


@pytest.fixture
def boundary(conn, handover, monkeypatch, request):
    """Synthetic book/attestation inputs, actual origin/HMAC and database rows."""
    schema.ensure_schema(conn)
    selected = getattr(request, 'param', False)
    if selected == 'performance':
        handover = request.getfixturevalue('performance_handover')
    elif selected:
        _use_current_strategy_with_synthetic_prior_semantics(handover)
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'backed-source-boundary-test-key-' * 4)
    monkeypatch.setenv('SENTINEL_SHADOW_OBSERVATION_ID', handover.context['observation_id'])
    monkeypatch.setenv('SENTINEL_SHADOW_STARTING_CASH', handover.context['starting_cash'])
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', handover.context['runtime']['git_commit'])
    monkeypatch.setenv('SENTINEL_IMAGE_SOURCE_REVISION', handover.context['runtime']['git_commit'])
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', handover.context['runtime']['runtime_image_digest'])
    monkeypatch.setattr(admission, 'current_context', lambda **_: deepcopy(handover.context))
    monkeypatch.setattr(identity, 'rehearsal_identity', lambda: deepcopy(handover.source))
    # Durability has its own real backup qualification. Supply its explicit
    # interface here so journal.writer_lock's earlier backup/account check
    # cannot stand in for the exact admission/account guard under test.
    monkeypatch.setattr(backup_runtime_authority, 'require',
        lambda *_args, **_kwargs: {'synthetic_account_boundary': True})
    origin.write(conn, handover.checkpoint)
    conn.commit()
    handover.conn = conn
    return handover


def _bind(case, account=ACCOUNT):
    return binding.bind(case.conn, deployment_id='10000000-0000-4000-8000-000000000001',
        broker='alpaca', broker_account_id=account)


def _foreign_binding(case):
    # This committed deployment change is outside the checkpoint/cache inventory.
    with psycopg.connect(case.conn.info.dsn) as other:
        other.execute("UPDATE sentinel_account_binding SET broker_account_id='PAFOREIGN' WHERE id=1")
        other.commit()


def _append_receipt(case):
    cls, extra = admission.Admission, {}
    if case.checkpoint.strategy_identity != case.context['strategy']:
        from sentinel.economic_migration import PROFILE_SHA256
        cls, extra = admission.EconomicAdmission, {
            'migration_profile_sha256': PROFILE_SHA256,
            'origin_strategy_sha256': digest(case.checkpoint.strategy_identity)}
    value = cls(**extra, observation_id=case.context['observation_id'],
        origin_sha256=digest(case.checkpoint.model_dump(by_alias=True)),
        book_runtime_sha256=digest(case.checkpoint.runtime_identity),
        process_sha256=digest(admission.process_binding(case.context['runtime'])),
        strategy_sha256=digest(case.context['strategy']),
        manifest_sha256=digest(admission.SourceManifest.model_validate(case.manifest).model_dump(by_alias=True)),
        pitr={})
    payload = value.model_dump(by_alias=True)
    case.conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) '
        'VALUES (%s,%s,%s::jsonb)', (admission._key(case.context), case.checkpoint.session,
            canonical_json({'admission': payload, 'hmac_sha256': admission._signature(payload)})))
    case.conn.commit()
    return value


class BookBoundaryReached(Exception):
    pass


def _book_tripwire(monkeypatch):
    def reached(*_args, **_kwargs):
        raise BookBoundaryReached
    monkeypatch.setattr(rolling_runtime, '_closure', reached)


@pytest.mark.parametrize('boundary', ['performance'], indirect=True)
def test_real_wealth_package_admission_commits_and_authenticates_without_rewriting_origin(
        boundary, monkeypatch):
    case = boundary
    _bind(case)
    before_origin = origin.read(case.conn).model_dump(by_alias=True)
    before_context = deepcopy(case.context)
    calls = []
    def synthetic_book(_conn, context):
        # Book formation and physical durability have their own qualifications.
        # Only those explicit fixture interfaces are synthetic; source proof,
        # disabled/killed control, account, writer, CAS, SQL and HMAC stay native.
        assert context['runtime']['wealth_core_source_sha256'] == ORIGIN_WEALTH_SOURCE
        calls.append(context['runtime']['sentinel_source_sha256'])
    monkeypatch.setattr(rolling_runtime, '_closure', synthetic_book)
    monkeypatch.setattr(admission.publication, '_publication_recovery_target', lambda _: {})
    value = admission.admit(case.conn, context=case.context, manifest=case.manifest)
    assert calls == [ORIGIN_SOURCE]
    assert value.process_sha256 == digest(admission.process_binding(case.context['runtime']))
    checkpoint = origin.read(case.conn)
    assert checkpoint.model_dump(by_alias=True) == before_origin
    assert admission.read(case.conn, case.context, checkpoint) == value
    stored = case.conn.execute('SELECT state FROM sentinel_processed_sessions '
        'WHERE cursor_name=%s', (admission._key(case.context),)).fetchone()[0]
    assert stored['admission'] == value.model_dump(by_alias=True)
    assert stored['hmac_sha256'] == admission._signature(stored['admission'])
    assert case.context == before_context
    assert case.context['runtime']['wealth_core_source_sha256'] == PERFORMANCE_WEALTH_SOURCE
    assert checkpoint.runtime_identity['wealth_core_source_sha256'] == ORIGIN_WEALTH_SOURCE


@pytest.mark.parametrize('boundary', ['performance'], indirect=True)
def test_real_wealth_package_persisted_admission_rechecks_the_current_account(boundary, monkeypatch):
    case = boundary
    _bind(case)
    # Explicit synthetic book/recovery interfaces match the existing boundary
    # tests; the unequal package proof and native durable admission remain real.
    monkeypatch.setattr(rolling_runtime, '_closure', lambda *_: None)
    monkeypatch.setattr(admission.publication, '_publication_recovery_target', lambda _: {})
    value = admission.admit(case.conn, context=case.context, manifest=case.manifest)
    assert admission.read(case.conn, case.context, origin.read(case.conn)) == value
    case.conn.rollback()
    _foreign_binding(case)
    with pytest.raises(admission.Refused, match='^BACKED_PAPER_ACCOUNT_BINDING_REQUIRED$'):
        admission.read(case.conn, case.context, origin.read(case.conn))
    assert case.conn.execute('SELECT count(*) FROM sentinel_processed_sessions '
        'WHERE cursor_name=%s', (admission._key(case.context),)).fetchone()[0] == 1
    assert binding.require(case.conn).broker_account_id == 'PAFOREIGN'
    assert case.context['runtime']['wealth_core_source_sha256'] == PERFORMANCE_WEALTH_SOURCE
    assert origin.read(case.conn).runtime_identity['wealth_core_source_sha256'] == ORIGIN_WEALTH_SOURCE


@pytest.mark.parametrize('existing', [False, True], ids=['new', 'existing'])
@pytest.mark.parametrize('boundary', [False, True], indirect=True, ids=['same-strategy', 'migration'])
def test_matching_durable_owner_reaches_the_book_boundary(boundary, monkeypatch, existing):
    _bind(boundary)
    if existing:
        _append_receipt(boundary)
    _book_tripwire(monkeypatch)
    with pytest.raises(BookBoundaryReached):
        admission.admit(boundary.conn, context=boundary.context, manifest=boundary.manifest)
    assert binding.require(boundary.conn).broker_account_id == ACCOUNT


@pytest.mark.parametrize('existing', [False, True], ids=['new', 'existing'])
@pytest.mark.parametrize('defect', ['missing', 'foreign', 'changed'])
def test_new_and_existing_admission_require_a_fresh_durable_owner(
        boundary, monkeypatch, existing, defect):
    if defect != 'missing':
        _bind(boundary, 'PAFOREIGN' if defect == 'foreign' else ACCOUNT)
    if existing:
        _append_receipt(boundary)
    if defect == 'changed':
        assert local_paper.bound_account(boundary.conn).broker_account_id == ACCOUNT
        boundary.conn.rollback()
        _foreign_binding(boundary)
    _book_tripwire(monkeypatch)
    with pytest.raises(admission.Refused, match='^BACKED_PAPER_ACCOUNT_BINDING_REQUIRED$'):
        admission.admit(boundary.conn, context=boundary.context, manifest=boundary.manifest)
    assert boundary.conn.execute('SELECT count(*) FROM sentinel_processed_sessions '
        'WHERE cursor_name=%s', (admission._key(boundary.context),)).fetchone()[0] == int(existing)


def test_durable_account_guard_removal_is_detected(boundary, monkeypatch):
    monkeypatch.setattr(admission, '_require_backed_owner_scope', lambda *_: None)
    with pytest.raises(BookBoundaryReached):
        test_new_and_existing_admission_require_a_fresh_durable_owner(
            boundary, monkeypatch, True, 'changed')


def _cached_foreign_owner(case, monkeypatch):
    _bind(case)
    _append_receipt(case)
    calls = []
    original = origin.read
    def counted(connection):
        calls.append(connection.info.backend_pid)
        return original(connection)
    monkeypatch.setattr(origin, 'read', counted)
    with proof_scope(case.conn) as scope:
        assert admission._retained_checkpoint(case.conn)[0].state_sha256 == case.checkpoint.state_sha256
        record = scope.values['retained-runtime-checkpoint']
        before = len(calls)
        _foreign_binding(case)
        with pytest.raises(admission.Refused, match='^BACKED_PAPER_ACCOUNT_BINDING_REQUIRED$'):
            admission._retained_checkpoint(case.conn)
        assert len(calls) == before, 'case must exercise the actual structural cache hit'
        assert scope.values['retained-runtime-checkpoint'] is record


def test_cached_retained_material_never_caches_the_account_permission(boundary, monkeypatch):
    _cached_foreign_owner(boundary, monkeypatch)


def test_cache_hit_account_guard_removal_is_detected(boundary, monkeypatch):
    source = inspect.getsource(admission._retained_checkpoint)
    needle = '_require_backed_owner_scope(conn, retained.runtime_identity, context)'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'pass'), 'removed cache-hit account guard', 'exec'),
        admission.__dict__, namespace)
    monkeypatch.setattr(admission, '_retained_checkpoint', namespace['_retained_checkpoint'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        _cached_foreign_owner(boundary, monkeypatch)


def test_signed_receipt_read_rechecks_the_durable_owner(boundary):
    _bind(boundary)
    expected = _append_receipt(boundary)
    assert admission.read(boundary.conn, boundary.context, boundary.checkpoint) == expected
    boundary.conn.rollback()
    _foreign_binding(boundary)
    with pytest.raises(admission.Refused, match='^BACKED_PAPER_ACCOUNT_BINDING_REQUIRED$'):
        admission.read(boundary.conn, boundary.context, boundary.checkpoint)


def test_receipt_account_guard_removal_is_detected(boundary, monkeypatch):
    source = inspect.getsource(admission.read)
    needle = '_require_backed_owner_scope(conn, checkpoint.runtime_identity, context)'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'pass'), 'removed receipt account guard', 'exec'),
        admission.__dict__, namespace)
    monkeypatch.setattr(admission, 'read', namespace['read'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_signed_receipt_read_rechecks_the_durable_owner(boundary)


def _commit_binding_change(case, monkeypatch):
    _bind(case)
    # This test owns only account/SQL/receipt behavior. It supplies explicit
    # synthetic book and durability interfaces, not a backup readiness claim.
    monkeypatch.setattr(rolling_runtime, '_closure', lambda *_: None)
    monkeypatch.setattr(admission.publication, '_publication_recovery_target', lambda _: {})
    operations = []
    def durability(_conn, *, operation):
        operations.append(operation)
        if operation == 'compatible retained runtime admission commit':
            _foreign_binding(case)
        return {'synthetic_account_boundary': True}
    monkeypatch.setattr(backup_runtime_authority, 'require', durability)
    with pytest.raises(admission.Refused, match='^BACKED_PAPER_ACCOUNT_BINDING_REQUIRED$'):
        admission.admit(case.conn, context=case.context, manifest=case.manifest)
    assert operations == [
        'plan/execution writer mutation',  # Cold preflight precedes ownership.
        'plan/execution writer mutation',  # Fresh inner guard remains mandatory.
        'compatible retained runtime admission',
        'compatible retained runtime admission commit',
    ]
    assert case.conn.execute('SELECT count(*) FROM sentinel_processed_sessions '
        'WHERE cursor_name=%s', (admission._key(case.context),)).fetchone()[0] == 0
    assert binding.require(case.conn).broker_account_id == 'PAFOREIGN'


def test_account_is_rechecked_before_admission_commit_and_receipt_is_rolled_back(boundary, monkeypatch):
    _commit_binding_change(boundary, monkeypatch)


def test_precommit_account_guard_removal_is_detected(boundary, monkeypatch):
    source = inspect.getsource(admission.admit)
    needle = '_require_backed_owner_scope(conn, checkpoint.runtime_identity, context)'
    assert source.count(needle) == 3
    head, _, tail = source.rpartition(needle)
    namespace = {}
    exec(compile(head + 'pass' + tail, 'removed precommit account guard', 'exec'),
        admission.__dict__, namespace)
    monkeypatch.setattr(admission, 'admit', namespace['admit'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        _commit_binding_change(boundary, monkeypatch)


def _without_owner_guard(function, *, index, expected):
    """Remove one exact boundary call, preserving all other real guards."""
    tree = ast.parse(inspect.getsource(function))
    calls = sorted([node for node in ast.walk(tree) if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and (getattr(node.value.func, 'id', None) == '_require_backed_owner_scope'
             or getattr(node.value.func, 'attr', None) == '_require_backed_owner_scope')],
        key=lambda node: node.lineno)
    assert len(calls) == expected
    target = calls[index]
    class Remove(ast.NodeTransformer):
        def visit_Expr(self, node):
            return ast.copy_location(ast.Pass(), node) if node is target else self.generic_visit(node)
    tree = ast.fix_missing_locations(Remove().visit(tree))
    namespace = {}
    exec(compile(tree, 'removed exact account boundary call', 'exec'), function.__globals__, namespace)
    return namespace[function.__name__]


def _existing_return_binding_change(case, monkeypatch):
    _bind(case)
    _append_receipt(case)
    calls = []
    def closure(*_):
        calls.append('authenticated synthetic book')
        _foreign_binding(case)
    monkeypatch.setattr(rolling_runtime, '_closure', closure)
    with pytest.raises(admission.Refused, match='^BACKED_PAPER_ACCOUNT_BINDING_REQUIRED$'):
        admission.admit(case.conn, context=case.context, manifest=case.manifest)
    assert calls == ['authenticated synthetic book']


def test_existing_admission_rechecks_owner_after_the_book_boundary(boundary, monkeypatch):
    _existing_return_binding_change(boundary, monkeypatch)


def test_existing_return_account_guard_removal_is_detected(boundary, monkeypatch):
    monkeypatch.setattr(admission, 'admit', _without_owner_guard(admission.admit, index=1, expected=3))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        _existing_return_binding_change(boundary, monkeypatch)


@dataclass(frozen=True)
class _SyntheticAttestation:
    def model_dump(self, **_):
        return {'synthetic_attested_material': True}


def _rolling_cache_permission(case, monkeypatch, route, defect):
    _bind(case)
    calls = []
    state = SimpleNamespace(last_processed_session=case.checkpoint.session, data_version=1,
        strategy_identity=deepcopy(case.checkpoint.strategy_identity), last_decision={},
        concordance_witness_origin=None)
    result = SimpleNamespace(session=case.checkpoint.session, state=state, record_sha256='a' * 64)
    attested = _SyntheticAttestation()
    def load(_conn, context, *, status_only):
        assert status_only is True
        calls.append('synthetic authenticated book')
        # The real loader binds the caller to retained provenance. The fresh
        # post-cache guard must therefore keep the original executable context.
        context['runtime'] = case.checkpoint.runtime_identity
        context['strategy'] = case.checkpoint.strategy_identity
        return case.checkpoint, None, result, attested, None
    monkeypatch.setattr(rolling_runtime, '_load_closure', load)
    monkeypatch.setattr(rolling_runtime.initial, '_context', lambda *_: deepcopy(case.context))
    @contextmanager
    def pinned(_conn):
        # Real SQL corpus/writer locks and token are held by proof_scope.
        # Publication-content/readiness are explicit synthetic seams here.
        yield SimpleNamespace(to_dict=lambda: deepcopy(case.checkpoint.publication))
    monkeypatch.setattr(rolling_runtime.inputs, 'pinned', pinned)
    monkeypatch.setattr(rolling_runtime.inputs, 'is_rolling', lambda _: True)
    monkeypatch.setattr(rolling_runtime, '_current', lambda *_: None)
    def read():
        if route == 'status':
            return rolling_runtime._closure(case.conn, deepcopy(case.context), status_only=True)
        return rolling_runtime._guard_status_owned(case.conn,
            observation_id=case.context['observation_id'], starting_cash=case.context['starting_cash'])
    with proof_scope(case.conn) as scope:
        assert read() is not None
        record = scope.values['rolling-checkpoint']
        if defect == 'foreign':
            _foreign_binding(case)
            reason = '^BACKED_PAPER_ACCOUNT_BINDING_REQUIRED$'
        elif defect == 'mode':
            monkeypatch.delenv(local_paper.MODE_ENV)
            reason = '^OWNER_PAPER_SOURCE_MODE_REQUIRED$'
        else:
            monkeypatch.delenv(local_paper.BACKUP_POLICY_ENV)
            reason = '^OWNER_PAPER_SOURCE_MODE_REQUIRED$'
        with pytest.raises(admission.Refused, match=reason):
            read()
        assert calls == ['synthetic authenticated book'], 'case must exercise an actual cache hit'
        assert scope.values['rolling-checkpoint'] is record


@pytest.mark.parametrize('route', ['status', 'projection'])
@pytest.mark.parametrize('defect', ['foreign', 'mode', 'backup'])
def test_rolling_material_cache_rechecks_account_and_mode(boundary, monkeypatch, route, defect):
    _rolling_cache_permission(boundary, monkeypatch, route, defect)


@pytest.mark.parametrize('route', ['status', 'projection'])
def test_rolling_cache_account_guard_removal_is_detected(boundary, monkeypatch, route):
    function = rolling_runtime._closure if route == 'status' else rolling_runtime._guard_status_owned
    monkeypatch.setattr(rolling_runtime, function.__name__,
        _without_owner_guard(function, index=0, expected=1))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        _rolling_cache_permission(boundary, monkeypatch, route, 'foreign')
