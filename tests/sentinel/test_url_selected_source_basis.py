"""Complete reviewed source compatibility never grants financial authority."""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from sentinel import runtime_admission as admission
from sentinel import structural_refactor_source_basis as structural
from sentinel import transition_registry
from sentinel import url_selected_source_basis as basis
from tests.sentinel.test_backed_paper_source import (  # noqa: F401
    handover, owner_mode, _rebind_origin,
)


def _actual():
    return admission._source_files(Path(basis.__file__).parent)


def test_sealed_successor_and_all_original_witnesses_have_exact_bytes():
    assert basis.PROFILE_SHA256 != '0' * 64
    actual = _actual()
    before = deepcopy(actual)
    profile = basis._profile()
    predecessor = basis.predecessor_view(actual)
    assert predecessor is not actual
    assert actual == before
    assert len(predecessor) == 422
    assert admission.source_closure(predecessor) == basis.BASE_SOURCE_SHA256
    assert predecessor == profile['base_files']
    assert profile['authority_effect'] == 'NONE'
    assert set(profile['retained_predecessors']) == set(basis.RETAINED_PREDECESSORS)
    for revision, (count, sha) in basis.RETAINED_PREDECESSORS.items():
        retained = profile['retained_predecessors'][revision]
        assert len(retained['files']) == count
        assert admission.source_closure(retained['files']) == sha
    assert structural.historical_view(actual) is actual
    historical = structural.historical_view(predecessor)
    assert len(historical) == 364
    assert admission.source_closure(historical) == (
        '56890ee50268961357faf2f6a8c2dc66ca76eb74c7440c832ba3a7bd06a09e15')
    assert len(transition_registry.load().profiles) == 20


def _all_unknown_sources_refuse():
    actual = _actual()
    for name in actual:
        changed = {**actual, name: hashlib.sha256((actual[name] + 'foreign').encode()).hexdigest()}
        assert basis.predecessor_view(changed) is changed, name
    for name in actual:
        missing = {key: value for key, value in actual.items() if key != name}
        assert basis.predecessor_view(missing) is missing, name
    extra = {**actual, 'execution/unknown.py': 'f' * 64}
    assert basis.predecessor_view(extra) is extra


def test_every_tampered_missing_or_extra_current_file_keeps_actual_identity():
    _all_unknown_sources_refuse()


def test_complete_source_guard_has_a_behavioral_falsifier(monkeypatch):
    source = inspect.getsource(basis.predecessor_view)
    needle = 'if actual != expected:'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'if False:'), 'open-source-successor', 'exec'),
         basis.__dict__, namespace)
    monkeypatch.setattr(basis, 'predecessor_view', namespace['predecessor_view'])
    with pytest.raises(AssertionError):
        _all_unknown_sources_refuse()


def test_missing_seal_grants_no_compatibility(monkeypatch):
    actual = _actual()
    monkeypatch.setattr(basis, 'PROFILE_SHA256', '0' * 64)
    assert basis.predecessor_view(actual) is actual


def test_changed_checker_or_original_structural_witness_refuses(tmp_path, monkeypatch):
    checker = tmp_path / 'url_selected_source_basis.py'
    checker.write_bytes(Path(basis.__file__).read_bytes() + b'\n# unknown checker bytes\n')
    with monkeypatch.context() as changed:
        changed.setattr(basis, '__file__', str(checker))
        with pytest.raises(ValueError, match='URL_SOURCE_PROFILE_SHAPE_CHANGED'):
            basis._profile()
    witness = tmp_path / 'structural-refactor-transition.json'
    witness.write_bytes(structural.TRANSITION.read_bytes() + b' ')
    monkeypatch.setattr(structural, 'TRANSITION', witness)
    with pytest.raises(ValueError, match='STRUCTURAL_TRANSITION_PROFILE_CHANGED'):
        basis._profile()


@pytest.mark.parametrize('defect', ['raw_bytes', 'authority', 'base_revision',
    'base_hash', 'base_neighbor', 'base_missing', 'base_extra', 'self_pin',
    'path', 'module', 'structural', 'retained_revision', 'retained_hash',
    'retained_neighbor', 'retained_missing', 'retained_extra'])
def test_changed_or_supplied_profile_digest_cannot_widen_independent_policy(
        tmp_path, monkeypatch, defect):
    raw = basis.PROFILE.read_bytes()
    value = json.loads(raw)
    if defect == 'raw_bytes':
        changed = raw + b' '
    else:
        if defect == 'authority':
            value['authority_effect'] = 'LIVE'
        elif defect == 'base_revision':
            value['base_revision'] = 'f' * 40
        elif defect == 'base_hash':
            value['base_source_sha256'] = 'f' * 64
        elif defect == 'base_neighbor':
            value['base_files']['core/decision.py'] = 'f' * 64
        elif defect == 'base_missing':
            value['base_files'].pop('core/decision.py')
        elif defect == 'base_extra':
            value['base_files']['unknown.py'] = 'f' * 64
        elif defect == 'self_pin':
            value['candidate_files']['url_selected_source_basis.py'] = 'f' * 64
        elif defect == 'path':
            value['candidate_files']['../unknown.py'] = 'f' * 64
        elif defect == 'module':
            value['module_sha256'] = 'f' * 64
        elif defect == 'structural':
            value['structural_profile_sha256'] = 'f' * 64
        elif defect == 'retained_revision':
            value['retained_predecessors']['f' * 40] = value['retained_predecessors'].pop(basis.RETAINED_REVISION)
        else:
            retained = value['retained_predecessors'][basis.RETAINED_REVISION]
            if defect == 'retained_hash':
                retained['source_sha256'] = 'f' * 64
            elif defect == 'retained_neighbor':
                retained['files']['core/decision.py'] = 'f' * 64
            elif defect == 'retained_missing':
                retained['files'].pop('core/decision.py')
            else:
                retained['files']['unknown.py'] = 'f' * 64
        changed = json.dumps(value, sort_keys=True).encode()
        monkeypatch.setattr(basis, 'PROFILE_SHA256', hashlib.sha256(changed).hexdigest())
    path = tmp_path / 'changed-profile.json'
    path.write_bytes(changed)
    monkeypatch.setattr(basis, 'PROFILE', path)
    with pytest.raises(ValueError, match='URL_SOURCE_'):
        basis._profile()


def test_no_authority_effect_guard_has_a_behavioral_falsifier(tmp_path, monkeypatch):
    source = inspect.getsource(basis._profile)
    needle = "value['authority_effect'] != 'NONE'"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'False'), 'authority-effect-successor', 'exec'),
         basis.__dict__, namespace)
    monkeypatch.setattr(basis, '_profile', namespace['_profile'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_changed_or_supplied_profile_digest_cannot_widen_independent_policy(
            tmp_path, monkeypatch, 'authority')


def test_retained_predecessor_hash_guard_has_a_behavioral_falsifier(tmp_path, monkeypatch):
    source = inspect.getsource(basis._profile)
    needle = "_closure(record['files']) != expected_sha"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'False'), 'open-retained-predecessor', 'exec'),
         basis.__dict__, namespace)
    monkeypatch.setattr(basis, '_profile', namespace['_profile'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_changed_or_supplied_profile_digest_cannot_widen_independent_policy(
            tmp_path, monkeypatch, 'retained_neighbor')


@pytest.mark.parametrize('revision', sorted(basis.RETAINED_PREDECESSORS))
def test_exact_predecessor_pair_is_the_only_new_registry_edge(revision):
    actual = _actual()
    predecessor = basis.predecessor_view(actual)
    registry = transition_registry.load()
    assert registry.closure_allowed(predecessor, actual, admission.ADDITIONS)
    assert transition_registry.historical_view(predecessor, actual) == predecessor
    for changed in ({**predecessor, 'unknown.py': 'f' * 64},
                    {**predecessor, 'core/decision.py': 'f' * 64}):
        assert not registry.closure_allowed(changed, actual, admission.ADDITIONS)
    assert not registry.source_allowed('execution/live_order_policy.py', 'f' * 64,
                                       actual['execution/live_order_policy.py'])
    retained = basis._profile()['retained_predecessors'][revision]['files']
    assert basis.predecessor_view(actual, previous=retained) == retained
    assert registry.closure_allowed(retained, actual, admission.ADDITIONS)
    assert transition_registry.historical_view(retained, actual) == retained
    for changed in ({**retained, 'unknown.py': 'f' * 64},
                    {**retained, 'core/decision.py': 'f' * 64},
                    {name: digest for name, digest in retained.items() if name != 'backup_guard.py'}):
        assert basis.predecessor_view(actual, previous=changed) == predecessor
        assert not registry.closure_allowed(changed, actual, admission.ADDITIONS)
    unknown = {**actual, 'execution/foreign.py': 'f' * 64}
    assert basis.predecessor_view(unknown, previous=retained) is unknown


def test_direct_retained_selection_guard_has_a_behavioral_falsifier(monkeypatch):
    source = inspect.getsource(basis.predecessor_view)
    needle = 'if previous == retained:'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'if previous is not None:'), 'open-direct-predecessor', 'exec'),
         basis.__dict__, namespace)
    monkeypatch.setattr(basis, 'predecessor_view', namespace['predecessor_view'])
    with pytest.raises(AssertionError):
        test_exact_predecessor_pair_is_the_only_new_registry_edge(basis.RETAINED_REVISION)


@pytest.mark.parametrize('predecessor', ['current_main', *sorted(basis.RETAINED_PREDECESSORS)])
def test_exact_current_main_manifest_uses_the_new_edge_without_rewriting_identities(handover, predecessor):
    case = handover
    revision, files = basis.BASE_REVISION, basis.predecessor_view(case.actual)
    if predecessor != 'current_main':
        revision = predecessor
        files = basis._profile()['retained_predecessors'][revision]['files']
    case.manifest = {"schema": "sentinel.retained-source-manifest/1",
        "revision": revision, "files": dict(files),
        "seam_sources": {}}
    _rebind_origin(case)
    before = deepcopy((case.source, case.context, case.checkpoint.model_dump(by_alias=True)))
    assert admission.prove_compatibility(case.manifest, case.checkpoint,
                                        case.context, source=case.source)
    assert (case.source, case.context, case.checkpoint.model_dump(by_alias=True)) == before


def test_backed_owner_scope_keeps_actual_current_identity_and_operating_guards(handover, monkeypatch):
    case = handover
    scope = admission._backed_owner_scope(case.checkpoint.runtime_identity,
                                         case.context, actual=case.actual)
    assert dict(scope.current_files) == case.actual
    assert scope.current_source_sha256 == admission.source_closure(case.actual)
    before = deepcopy((case.source, case.context, case.checkpoint.model_dump(by_alias=True)))
    assert admission.prove_compatibility(case.manifest, case.checkpoint,
                                        case.context, source=case.source)
    assert (case.source, case.context, case.checkpoint.model_dump(by_alias=True)) == before
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://api.alpaca.markets')
    with pytest.raises(admission.Refused, match='OWNER_PAPER_SOURCE_MODE_REQUIRED'):
        admission._backed_owner_scope(case.checkpoint.runtime_identity,
                                     case.context, actual=case.actual)


@pytest.mark.parametrize('revision', sorted(basis.RETAINED_PREDECESSORS))
@pytest.mark.parametrize('defect', ['hash', 'neighbor', 'missing', 'extra', 'absent'])
def test_each_retained_snapshot_requires_its_independent_complete_closure(
        tmp_path, monkeypatch, revision, defect):
    value = json.loads(basis.PROFILE.read_bytes())
    record = value['retained_predecessors'][revision]
    if defect == 'hash':
        record['source_sha256'] = 'f' * 64
    elif defect == 'neighbor':
        record['files']['core/decision.py'] = 'f' * 64
    elif defect == 'missing':
        del record['files']['core/decision.py']
    elif defect == 'extra':
        record['files']['unreviewed.py'] = 'f' * 64
    else:
        del value['retained_predecessors'][revision]
    raw = json.dumps(value, sort_keys=True).encode()
    path = tmp_path / 'retained-profile.json'
    path.write_bytes(raw)
    monkeypatch.setattr(basis, 'PROFILE', path)
    monkeypatch.setattr(basis, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='URL_SOURCE_RETAINED_PREDECESSOR_CHANGED'):
        basis._profile()


@pytest.mark.parametrize('revision', sorted(basis.RETAINED_PREDECESSORS))
def test_each_retained_closure_guard_has_a_behavioral_falsifier(tmp_path, monkeypatch, revision):
    source = inspect.getsource(basis._profile)
    guard = "_closure(record['files']) != expected_sha"
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'False'), '<removed-retained-closure-guard>', 'exec'),
         basis.__dict__, namespace)
    monkeypatch.setattr(basis, '_profile', namespace['_profile'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_each_retained_snapshot_requires_its_independent_complete_closure(
            tmp_path, monkeypatch, revision, 'neighbor')
