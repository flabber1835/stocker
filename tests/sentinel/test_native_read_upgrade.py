from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import native_read_upgrade as upgrade, runtime_admission as admission
from sentinel import clock_sampling_upgrade, idle_leader_upgrade
from tests.sentinel.test_retained_source_compatibility import closure
from tests.sentinel.test_paper_composition_upgrade import _execution_closure, _refresh_current


def test_successor_keeps_historical_descriptor_and_authority_unchanged():
    value = upgrade.profile()
    assert value['authority_effect'] == 'NONE'
    assert set(value['files']) == {'runtime_admission.py', 'autonomy_runtime_upgrade.py'}
    assert set(value['additions']) == upgrade.ADDITIONS
    assert hashlib.sha256(upgrade.PROFILE.with_name('autonomy-runtime-upgrade.json').read_bytes()).hexdigest() == upgrade.ORIGINAL_PROFILE
    for name, record in value['files'].items():
        actual = hashlib.sha256((upgrade.PROFILE.parent / name).read_bytes()).hexdigest()
        assert (actual == record['after']
                or clock_sampling_upgrade.source_allowed(name, record['after'], actual)
                or idle_leader_upgrade.source_allowed(name, record['after'], actual))
        assert all(upgrade.source_allowed(name, before, record['after']) for before in record['before'])
        assert not upgrade.source_allowed(name, 'f' * 64, record['after'])
        assert not upgrade.source_allowed(name, record['before'][0], 'f' * 64)


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_prior_source_upgrade_has_exact_closure_and_rejects_neighbor(closure, name):
    root, checkpoint, context, manifest, source = _execution_closure(closure, name, source_profile=upgrade)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source)
    (root / name).write_bytes((root / name).read_bytes() + b'\nUNREVIEWED=True\n')
    _refresh_current(root, context, source)
    with pytest.raises(admission.Refused):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


@pytest.mark.parametrize('name', sorted(upgrade.ADDITIONS))
@pytest.mark.parametrize('already_present', [False, True])
def test_each_addition_requires_exact_bytes_even_if_already_present(closure, name, already_present):
    root, checkpoint, context, manifest, source = closure
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((upgrade.PROFILE.parent / name).read_bytes())
    if already_present:
        manifest['files'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
        previous_env = deepcopy(source['environment'])
        previous_env['sentinel_source'].update(files=len(manifest['files']), hash=admission.source_closure(manifest['files']))
        checkpoint.runtime_identity.update(
            sentinel_source_sha256=previous_env['sentinel_source']['hash'],
            environment_identity_sha256=hashlib.sha256(json.dumps(previous_env, sort_keys=True).encode()).hexdigest())
        checkpoint.runtime_identity['reviewed_shadow_config']['validated_source_identity_sha256'] = checkpoint.runtime_identity['environment_identity_sha256']
    _refresh_current(root, context, source)
    assert upgrade.additions_allowed({name: hashlib.sha256(path.read_bytes()).hexdigest()}) == {name}
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source)
    path.write_bytes(path.read_bytes() + b'\nUNREVIEWED=True\n')
    _refresh_current(root, context, source)
    with pytest.raises(admission.Refused):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


@pytest.mark.parametrize('defect', ['descriptor', 'module', 'legacy', 'neighbor', 'predecessor'])
def test_profile_authentication_is_closed(tmp_path, monkeypatch, defect):
    if defect == 'module':
        changed = tmp_path / 'native_read_upgrade.py'
        changed.write_bytes(Path(upgrade.__file__).read_bytes() + b'\nBAD=True\n')
        monkeypatch.setattr(upgrade, '__file__', str(changed))
    else:
        raw = upgrade.PROFILE.read_bytes()
        if defect in {'neighbor', 'predecessor'}:
            value = json.loads(raw)
            if defect == 'neighbor':
                value['files']['core/kernel.py'] = value['files']['runtime_admission.py']
            else:
                value['files']['runtime_admission.py']['before'] = ['f' * 64]
            raw = json.dumps(value).encode()
            monkeypatch.setattr(upgrade, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
        path = tmp_path / upgrade.PROFILE.name
        path.write_bytes(raw + (b' ' if defect == 'descriptor' else b''))
        legacy = upgrade.PROFILE.with_name('autonomy-runtime-upgrade.json').read_bytes()
        (tmp_path / 'autonomy-runtime-upgrade.json').write_bytes(legacy + (b' ' if defect == 'legacy' else b''))
        monkeypatch.setattr(upgrade, 'PROFILE', path)
    with pytest.raises(ValueError):
        upgrade.profile()


def test_historical_checker_refuses_an_unrecognized_successor():
    value = upgrade.profile()
    arguments = {'original_module': upgrade.ORIGINAL_NORMALIZED_CHECKER,
                 'original_admission': upgrade.ORIGINAL_ADMISSION,
                 'original_profile': upgrade.ORIGINAL_PROFILE}
    upgrade.require_autonomy_successor(value['autonomy_checker_normalized_sha256'],
        value['files']['runtime_admission.py']['after'], **arguments)
    with pytest.raises(ValueError, match='IMPLEMENTATION_CHANGED'):
        upgrade.require_autonomy_successor('f' * 64,
            value['files']['runtime_admission.py']['after'], **arguments)


def test_successor_predecessor_guard_has_a_falsifier(monkeypatch):
    source = inspect.getsource(upgrade.source_allowed)
    needle = "previous in record['before']"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'True'), 'native-upgrade-falsifier', 'exec'), upgrade.__dict__, namespace)
    monkeypatch.setattr(upgrade, 'source_allowed', namespace['source_allowed'])
    with pytest.raises(AssertionError):
        test_successor_keeps_historical_descriptor_and_authority_unchanged()


def test_admission_predecessor_is_not_a_wildcard_administrative_module(closure):
    root, checkpoint, context, manifest, source = _execution_closure(
        closure, 'runtime_admission.py', source_profile=upgrade)
    manifest['files']['runtime_admission.py'] = 'f' * 64
    prior_env = deepcopy(source['environment'])
    prior_env['sentinel_source'].update(files=len(manifest['files']), hash=admission.source_closure(manifest['files']))
    prior_hash = hashlib.sha256(json.dumps(prior_env, sort_keys=True).encode()).hexdigest()
    checkpoint.runtime_identity.update(sentinel_source_sha256=prior_env['sentinel_source']['hash'],
                                       environment_identity_sha256=prior_hash)
    checkpoint.runtime_identity['reviewed_shadow_config']['validated_source_identity_sha256'] = prior_hash
    with pytest.raises(admission.Refused, match='ECONOMIC_SOURCE_CHANGED:runtime_admission.py'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


def test_removing_admission_predecessor_scope_has_a_falsifier(closure, monkeypatch):
    source = inspect.getsource(admission.prove_compatibility)
    needle = ' - native_read_upgrade.SCOPE - clock_sampling_upgrade.SCOPE - idle_leader_upgrade.SCOPE - opening_latency_upgrade.SCOPE - protected_cohort_upgrade.SCOPE'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, ''), 'admission-scope-falsifier', 'exec'), admission.__dict__, namespace)
    monkeypatch.setattr(admission, 'prove_compatibility', namespace['prove_compatibility'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_admission_predecessor_is_not_a_wildcard_administrative_module(closure)


@pytest.mark.parametrize('name', sorted(upgrade.ADDITIONS))
def test_exact_native_addition_set_cannot_be_partially_removed(closure, name):
    root, checkpoint, context, manifest, source = closure
    (root / name).unlink()
    _refresh_current(root, context, source)
    with pytest.raises(admission.Refused, match='SOURCE_CLOSURE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


@pytest.mark.parametrize('previous', upgrade.ADMISSION_PREDECESSORS)
def test_exact_published_admission_predecessors_keep_their_upgrade_path(closure, previous):
    descriptor = deepcopy(upgrade.profile())
    descriptor['files']['runtime_admission.py']['before'] = [previous]
    source_profile = SimpleNamespace(profile=lambda: descriptor)
    _, checkpoint, context, manifest, source = _execution_closure(
        closure, 'runtime_admission.py', source_profile=source_profile)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source)
