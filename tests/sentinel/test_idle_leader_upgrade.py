"""The idle scheduler repair is one closed, authenticated executable successor."""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from sentinel import idle_leader_upgrade as upgrade, runtime_admission as admission
from tests.sentinel.test_retained_source_compatibility import closure
from tests.sentinel.test_paper_composition_upgrade import _execution_closure, _refresh_current
from tests.sentinel.test_clock_sampling_upgrade import _prior_binding
from tests.sentinel.test_operational_liveness_upgrade import (
    test_complete_historical_source_manifest_is_admitted as _historical)


def test_scope_predecessors_and_current_bytes_are_exact():
    value = upgrade.profile()
    assert upgrade.SCOPE == {
        'automation/service.py', 'automation_runtime.py', 'alert_service.py',
        'runtime_admission.py', 'clock_sampling_upgrade.py'}
    assert upgrade.ADDITIONS == {'idle_leader_upgrade.py'}
    assert value['authority_effect'] == 'NONE'
    assert value['base_revision'] == 'c0be72ed708b20cc8fff25b0cd8e1796889377f0'
    for name, record in value['files'].items():
        actual = hashlib.sha256((upgrade.PROFILE.parent / name).read_bytes()).hexdigest()
        from sentinel import opening_latency_upgrade
        assert actual == record['after'] or opening_latency_upgrade.source_allowed(name, record['after'], actual)
        assert upgrade.BASE_FILES[name] in record['before']
        assert all(upgrade.source_allowed(name, previous, actual)
                   for previous in record['before'])
        assert not upgrade.source_allowed(name, 'f' * 64, actual)
        assert not upgrade.source_allowed(name, record['before'][0], 'f' * 64)
    assert not upgrade.source_allowed('execution/guarded.py', 'f' * 64, 'f' * 64)
    assert upgrade.additions_allowed({'idle_leader_upgrade.py': 'f' * 64}) == set()


@pytest.mark.parametrize('name,previous', [
    (name, previous) for name, record in upgrade.profile()['files'].items()
    for previous in record['before']])
def test_each_predecessor_has_authenticated_complete_source_closure(closure, name, previous):
    _, checkpoint, context, manifest, source = _execution_closure(
        closure, name, source_profile=upgrade)
    manifest['files'][name] = previous
    _prior_binding(checkpoint, manifest, source)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source)


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_adjacent_current_source_change_refuses_even_in_retained_manifest(closure, name):
    root, checkpoint, context, manifest, source = _execution_closure(
        closure, name, source_profile=upgrade)
    path = root / name
    path.write_bytes(path.read_bytes() + b'\nUNREVIEWED = True\n')
    manifest['files'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    _refresh_current(root, context, source)
    _prior_binding(checkpoint, manifest, source)
    with pytest.raises(admission.Refused, match='RETAINED_SOURCE_CLOSURE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


def test_missing_checker_cannot_keep_a_complete_current_closure(closure):
    root, checkpoint, context, manifest, source = closure
    (root / 'idle_leader_upgrade.py').unlink()
    _refresh_current(root, context, source)
    with pytest.raises(admission.Refused, match='RETAINED_SOURCE_CLOSURE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


@pytest.mark.parametrize('defect', [
    'raw_profile', 'module', 'retained_profile', 'authority', 'extra_file',
    'missing_file', 'extra_addition', 'predecessor'])
def test_profile_cannot_widen_even_if_its_new_digest_is_supplied(tmp_path, monkeypatch, defect):
    for name in (*upgrade.RETAINED_PROFILES, upgrade.PROFILE.name):
        (tmp_path / name).write_bytes(upgrade.PROFILE.with_name(name).read_bytes())
    path = tmp_path / upgrade.PROFILE.name
    if defect == 'raw_profile':
        path.write_bytes(path.read_bytes() + b' ')
    elif defect == 'module':
        module = tmp_path / 'idle_leader_upgrade.py'
        module.write_bytes(Path(upgrade.__file__).read_bytes() + b'\nUNREVIEWED = True\n')
        monkeypatch.setattr(upgrade, '__file__', str(module))
    elif defect == 'retained_profile':
        retained = tmp_path / next(iter(upgrade.RETAINED_PROFILES))
        retained.write_bytes(retained.read_bytes() + b' ')
    else:
        value = deepcopy(json.loads(path.read_bytes()))
        if defect == 'authority':
            value['authority_effect'] = 'LIVE'
        elif defect == 'extra_file':
            value['files']['execution/guarded.py'] = value['files']['alert_service.py']
        elif defect == 'missing_file':
            del value['files']['alert_service.py']
        elif defect == 'extra_addition':
            value['additions']['unreviewed.py'] = 'f' * 64
        else:
            value['files']['alert_service.py']['before'] = ['f' * 64]
        raw = json.dumps(value).encode()
        path.write_bytes(raw)
        monkeypatch.setattr(upgrade, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(upgrade, 'PROFILE', path)
    with pytest.raises(ValueError, match='IDLE_LEADER_'):
        upgrade.profile()


def test_clock_checker_successor_is_exact_and_authenticated():
    value = upgrade.profile()
    upgrade.require_clock_checker_successor(value['clock_checker_normalized_sha256'])
    with pytest.raises(ValueError, match='CLOCK_SAMPLING_IMPLEMENTATION_CHANGED'):
        upgrade.require_clock_checker_successor('f' * 64)


def test_predecessor_guard_has_behavioral_falsifier(monkeypatch):
    source = inspect.getsource(upgrade.source_allowed)
    needle = "previous in record['before']"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'True'), 'idle-predecessor-falsifier', 'exec'),
         upgrade.__dict__, namespace)
    monkeypatch.setattr(upgrade, 'source_allowed', namespace['source_allowed'])
    with pytest.raises(AssertionError):
        test_scope_predecessors_and_current_bytes_are_exact()


def test_checker_presence_guard_has_behavioral_falsifier(closure, monkeypatch):
    source = inspect.getsource(admission.prove_compatibility)
    needle = '            or idle_leader_upgrade.ADDITIONS - set(actual)\n'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, ''), 'idle-addition-falsifier', 'exec'),
         admission.__dict__, namespace)
    monkeypatch.setattr(admission, 'prove_compatibility', namespace['prove_compatibility'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_missing_checker_cannot_keep_a_complete_current_closure(closure)


def test_current_source_guard_has_behavioral_falsifier(closure, monkeypatch):
    source = inspect.getsource(admission.prove_compatibility)
    needle = ("any(name in actual and actual[name] != record['after']\n"
              "                   and not source_allowed(name, record['after'], actual[name], (opening_latency_profile,))\n"
              "                   for name, record in idle_leader_profile['files'].items())")
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'False'), 'idle-current-source-falsifier', 'exec'),
         admission.__dict__, namespace)
    monkeypatch.setattr(admission, 'prove_compatibility', namespace['prove_compatibility'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_adjacent_current_source_change_refuses_even_in_retained_manifest(closure, 'alert_service.py')


def test_installed_predecessor_complete_source_manifest_is_authenticated(closure, monkeypatch):
    fixture = Path(__file__).parent / 'fixtures/retained-source-history/c0be72ed.json'
    value = json.loads(fixture.read_bytes())
    assert value['revision'] == upgrade.BASE_REVISION and len(value['files']) == 344
    _historical(closure, monkeypatch, 'c0be72ed',
                'a76df4344a915fda5f598db4b663636602aea4a5319b212dee60ba6cc17c2231')


__all__ = ['closure']
