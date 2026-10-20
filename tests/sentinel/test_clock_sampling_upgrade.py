from copy import deepcopy
import ast
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from sentinel import clock_sampling_upgrade as upgrade, runtime_admission as admission
from sentinel import native_read_upgrade, idle_leader_upgrade
from tests.sentinel.test_retained_source_compatibility import closure
from tests.sentinel.test_paper_composition_upgrade import _execution_closure, _refresh_current
from tests.sentinel.test_rolling_retained_runtime_activation import (
    conn, pg, source, ready, operational_source, executable)
from tests.sentinel.test_operational_liveness_upgrade import (
    test_actual_formed_book_upgrade_restarts_without_reformation_or_reacquisition as _formed,
    test_complete_historical_source_manifest_is_admitted as _historical)


PRE_FIX_REVISION = '18a4c8b732b50eace554cd3da53e909c27baaada'
PRE_FIX_MANIFEST_SHA256 = '3823592c1618be7a304c60de2f390d80630afa29eab02c81d8629a9c07237c3f'


def _without_profile_pins(source, profiles):
    """Isolate one historical guard from independently tested later guards."""
    removed = set()
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == 'any' and len(node.args) == 1
                and isinstance(node.args[0], ast.GeneratorExp)):
            continue
        iterator = node.args[0].generators[0].iter
        if (isinstance(iterator, ast.Call) and isinstance(iterator.func, ast.Attribute)
                and iterator.func.attr == 'items'
                and isinstance(iterator.func.value, ast.Subscript)
                and isinstance(iterator.func.value.value, ast.Name)
                and iterator.func.value.value.id in profiles):
            name = iterator.func.value.value.id
            assert name not in removed
            removed.add(name)
            source = source.replace(ast.get_source_segment(source, node), 'False', 1)
            # AST offsets describe the original source; restart after each edit.
            return _without_profile_pins(source, set(profiles) - removed)
    assert not profiles
    return source


def _prior_binding(checkpoint, manifest, source):
    previous_env = deepcopy(source['environment'])
    previous_env['sentinel_source'].update(
        files=len(manifest['files']), hash=admission.source_closure(manifest['files']))
    previous_hash = hashlib.sha256(json.dumps(previous_env, sort_keys=True).encode()).hexdigest()
    checkpoint.runtime_identity.update(sentinel_source_sha256=previous_env['sentinel_source']['hash'],
        environment_identity_sha256=previous_hash)
    checkpoint.runtime_identity['reviewed_shadow_config']['validated_source_identity_sha256'] = previous_hash


def _profile_copy(tmp_path):
    for name in (*upgrade.RETAINED_PROFILES, 'native_read_upgrade.py', upgrade.PROFILE.name):
        (tmp_path / name).write_bytes(upgrade.PROFILE.with_name(name).read_bytes())
    return tmp_path / upgrade.PROFILE.name


def test_scope_and_retained_profiles_remain_exact_and_have_no_authority_effect():
    value = upgrade.profile()
    assert upgrade.SCOPE == {'automation/service.py', 'runtime_admission.py', 'autonomy_runtime_upgrade.py'}
    assert upgrade.ADDITIONS == {'clock_sampling_upgrade.py'}
    assert value['authority_effect'] == 'NONE'
    assert len(value['files']['automation/service.py']['before']) == 8
    assert len(value['files']['runtime_admission.py']['before']) == 16
    for name, sha in upgrade.RETAINED_PROFILES.items():
        assert hashlib.sha256(upgrade.PROFILE.with_name(name).read_bytes()).hexdigest() == sha
    assert hashlib.sha256(Path(native_read_upgrade.__file__).read_bytes()).hexdigest() == upgrade.NATIVE_CHECKER_SHA256
    for name, record in value['files'].items():
        actual = hashlib.sha256((upgrade.PROFILE.parent / name).read_bytes()).hexdigest()
        assert (actual == record['after']
                or idle_leader_upgrade.source_allowed(name, record['after'], actual))
        assert all(upgrade.source_allowed(name, previous, record['after']) for previous in record['before'])
        assert not upgrade.source_allowed(name, 'f' * 64, actual)
        assert not upgrade.source_allowed(name, record['before'][0], 'f' * 64)
    assert not upgrade.source_allowed('automation/store.py', 'f' * 64, 'f' * 64)


@pytest.mark.parametrize('name,previous', [
    (name, previous) for name, record in upgrade.profile()['files'].items() for previous in record['before']])
def test_each_reviewed_predecessor_preserves_full_authenticated_closure(closure, name, previous):
    _, checkpoint, context, manifest, source = _execution_closure(closure, name, source_profile=upgrade)
    manifest['files'][name] = previous
    _prior_binding(checkpoint, manifest, source)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source)


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_adjacent_current_source_change_refuses_even_when_already_in_manifest(closure, name):
    root, checkpoint, context, manifest, source = _execution_closure(closure, name, source_profile=upgrade)
    path = root / name
    path.write_bytes(path.read_bytes() + b'\nUNREVIEWED=True\n')
    manifest['files'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    _refresh_current(root, context, source)
    _prior_binding(checkpoint, manifest, source)
    with pytest.raises(admission.Refused, match='RETAINED_SOURCE_CLOSURE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_unreviewed_predecessor_refuses_even_with_matching_origin(closure, name):
    _, checkpoint, context, manifest, source = _execution_closure(closure, name, source_profile=upgrade)
    manifest['files'][name] = 'f' * 64
    _prior_binding(checkpoint, manifest, source)
    with pytest.raises(admission.Refused, match='RETAINED_ECONOMIC_SOURCE_CHANGED:' + name):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


def test_checker_cannot_be_deleted_from_current_closure(closure):
    root, checkpoint, context, manifest, source = closure
    (root / 'clock_sampling_upgrade.py').unlink()
    _refresh_current(root, context, source)
    with pytest.raises(admission.Refused, match='RETAINED_SOURCE_CLOSURE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


@pytest.mark.parametrize('already_present', [False, True])
def test_checker_requires_exact_bytes_in_both_new_and_retained_closure(closure, already_present):
    root, checkpoint, context, manifest, source = closure
    path = root / 'clock_sampling_upgrade.py'
    assert upgrade.additions_allowed({path.name: hashlib.sha256(path.read_bytes()).hexdigest()}) == {path.name}
    if already_present:
        manifest['files'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        _prior_binding(checkpoint, manifest, source)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source)
    path.write_bytes(path.read_bytes() + b'\nUNREVIEWED=True\n')
    _refresh_current(root, context, source)
    with pytest.raises(admission.Refused, match='RETAINED_SOURCE_CLOSURE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


@pytest.mark.parametrize('defect', ['profile', 'module', 'legacy', 'native_checker', 'extra_file',
                                   'missing_file', 'extra_addition', 'predecessor', 'authority'])
def test_authentication_cannot_be_relaxed_by_a_new_profile_digest(tmp_path, monkeypatch, defect):
    path = _profile_copy(tmp_path)
    if defect == 'module':
        changed = tmp_path / 'clock_sampling_upgrade.py'
        changed.write_bytes(Path(upgrade.__file__).read_bytes() + b'\nUNREVIEWED=True\n')
        monkeypatch.setattr(upgrade, '__file__', str(changed))
    elif defect in {'legacy', 'native_checker'}:
        changed = tmp_path / ('native-read-runtime-upgrade.json' if defect == 'legacy' else 'native_read_upgrade.py')
        changed.write_bytes(changed.read_bytes() + b' ')
    elif defect == 'profile':
        path.write_bytes(path.read_bytes() + b' ')
    else:
        value = json.loads(path.read_bytes())
        if defect == 'extra_file':
            value['files']['automation/store.py'] = value['files']['automation/service.py']
        elif defect == 'missing_file':
            del value['files']['automation/service.py']
        elif defect == 'extra_addition':
            value['additions']['foreign.py'] = 'f' * 64
        elif defect == 'predecessor':
            value['files']['automation/service.py']['before'] = ['f' * 64]
        else:
            value['authority_effect'] = 'LIVE'
        raw = json.dumps(value).encode()
        path.write_bytes(raw)
        monkeypatch.setattr(upgrade, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(upgrade, 'PROFILE', path)
    with pytest.raises(ValueError, match='CLOCK_SAMPLING_'):
        upgrade.profile()


@pytest.mark.parametrize('field', ['module_sha', 'admission_sha', 'original_module',
                                  'original_admission', 'original_profile'])
def test_historical_autonomy_checker_requires_exact_authenticated_successor(field):
    value = upgrade.profile()
    arguments = {'module_sha': value['autonomy_checker_normalized_sha256'],
        'admission_sha': value['files']['runtime_admission.py']['after'],
        'original_module': native_read_upgrade.ORIGINAL_NORMALIZED_CHECKER,
        'original_admission': native_read_upgrade.ORIGINAL_ADMISSION,
        'original_profile': native_read_upgrade.ORIGINAL_PROFILE}
    upgrade.require_autonomy_successor(**arguments)
    arguments[field] = 'f' * 64
    with pytest.raises(ValueError, match='AUTONOMY_RUNTIME_IMPLEMENTATION_CHANGED'):
        upgrade.require_autonomy_successor(**arguments)


def test_predecessor_guard_has_an_assertion_falsifier(monkeypatch):
    source = inspect.getsource(upgrade.source_allowed)
    needle = "previous in record['before']"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'True'), 'clock-predecessor-falsifier', 'exec'), upgrade.__dict__, namespace)
    monkeypatch.setattr(upgrade, 'source_allowed', namespace['source_allowed'])
    with pytest.raises(AssertionError):
        test_scope_and_retained_profiles_remain_exact_and_have_no_authority_effect()


def test_addition_presence_guard_has_an_assertion_falsifier(closure, monkeypatch):
    source = inspect.getsource(admission.prove_compatibility)
    needle = '            or clock_sampling_upgrade.ADDITIONS - set(actual)\n'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, ''), 'clock-addition-falsifier', 'exec'), admission.__dict__, namespace)
    monkeypatch.setattr(admission, 'prove_compatibility', namespace['prove_compatibility'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_checker_cannot_be_deleted_from_current_closure(closure)


def test_current_source_guard_has_an_assertion_falsifier(closure, monkeypatch):
    source = inspect.getsource(admission.prove_compatibility)
    needle = ("any(name in actual and actual[name] != record['after']\n"
              "                   and not source_allowed(name, record['after'], actual[name], (idle_leader_profile, opening_latency_profile, protected_cohort_profile))\n"
              "                   for name, record in clock_sampling_profile['files'].items())")
    assert source.count(needle) == 1
    # The new exact idle pin also covers the service. Isolate the historical
    # clock boundary only inside this in-memory mutant, and prove it still
    # refuses before removing that boundary. The new pin has its own separate
    # falsifier using alert_service.py, outside the historical clock scope.
    idle_pin = ("any(name in actual and actual[name] != record['after']\n"
                "                   and not source_allowed(name, record['after'], actual[name], (opening_latency_profile, protected_cohort_profile))\n"
                "                   for name, record in idle_leader_profile['files'].items())")
    assert source.count(idle_pin) == 1
    isolated = _without_profile_pins(source, {
        'idle_leader_profile', 'opening_latency_profile', 'protected_cohort_profile'})
    namespace = {}
    exec(compile(isolated, 'clock-boundary-isolated', 'exec'), admission.__dict__, namespace)
    monkeypatch.setattr(admission, 'prove_compatibility', namespace['prove_compatibility'])
    test_adjacent_current_source_change_refuses_even_when_already_in_manifest(closure, 'automation/service.py')
    namespace = {}
    exec(compile(isolated.replace(needle, 'False'), 'clock-current-source-falsifier', 'exec'), admission.__dict__, namespace)
    monkeypatch.setattr(admission, 'prove_compatibility', namespace['prove_compatibility'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_adjacent_current_source_change_refuses_even_when_already_in_manifest(closure, 'automation/service.py')


def test_pre_fix_complete_source_manifest_is_authenticated(closure, monkeypatch):
    fixture = Path(__file__).parent / 'fixtures/retained-source-history/18a4c8b7.json'
    value = json.loads(fixture.read_bytes())
    assert value['revision'] == PRE_FIX_REVISION and len(value['files']) == 343
    _historical(closure, monkeypatch, '18a4c8b7', PRE_FIX_MANIFEST_SHA256)


@pytest.mark.parametrize('ready', [{'formed': True}], indirect=True)
@pytest.mark.parametrize('executable', ['clock_sampling_preceding'], indirect=True)
def test_actual_formed_book_survives_clock_repair_without_reformation_or_reacquisition(
        conn, ready, executable, operational_source, monkeypatch):
    _formed(conn, ready, executable, operational_source, monkeypatch)


__all__ = ['closure', 'conn', 'pg', 'source', 'ready', 'operational_source', 'executable']
