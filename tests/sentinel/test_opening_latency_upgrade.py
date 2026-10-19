"""Closed reviewed source transitions preserve retained book provenance."""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from sentinel import opening_latency_upgrade as upgrade, runtime_admission as admission
from tests.sentinel.test_retained_source_compatibility import closure
from tests.sentinel.test_paper_composition_upgrade import _execution_closure, _refresh_current
from tests.sentinel.test_clock_sampling_upgrade import _prior_binding
from tests.sentinel.test_operational_liveness_upgrade import (
    test_complete_historical_source_manifest_is_admitted as _historical)


def test_profile_scope_predecessors_and_current_bytes_are_exact():
    value = upgrade.profile()
    assert value['authority_effect'] == 'NONE'
    assert value['base_revision'] == upgrade.BASE_REVISION
    for name, record in value['files'].items():
        actual = hashlib.sha256((upgrade.PROFILE.parent / name).read_bytes()).hexdigest()
        assert actual == record['after']
        assert upgrade.BASE_FILES[name] in record['before']
        assert all(upgrade.source_allowed(name, previous, actual) for previous in record['before'])
        assert not upgrade.source_allowed(name, 'f' * 64, actual)
        assert not upgrade.source_allowed(name, record['before'][0], 'f' * 64)
    assert not upgrade.source_allowed('core/kernel.py', 'f' * 64, 'f' * 64)


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_reviewed_base_transition_has_complete_authenticated_source_closure(closure, name):
    _, checkpoint, context, manifest, source = _execution_closure(closure, name, source_profile=upgrade)
    manifest['files'][name] = upgrade.BASE_FILES[name]
    _prior_binding(checkpoint, manifest, source)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source)


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_adjacent_current_source_tamper_refuses_even_in_manifest(closure, name):
    root, checkpoint, context, manifest, source = _execution_closure(closure, name, source_profile=upgrade)
    path = root / name
    path.write_bytes(path.read_bytes() + b'\nUNREVIEWED = True\n')
    manifest['files'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    _refresh_current(root, context, source)
    _prior_binding(checkpoint, manifest, source)
    with pytest.raises(admission.Refused, match='RETAINED_SOURCE_CLOSURE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


def test_missing_checker_cannot_keep_a_current_source_closure(closure):
    root, checkpoint, context, manifest, source = closure
    (root / 'opening_latency_upgrade.py').unlink()
    _refresh_current(root, context, source)
    with pytest.raises(admission.Refused, match='RETAINED_SOURCE_CLOSURE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


@pytest.mark.parametrize('defect', ['profile', 'module', 'retained_profile', 'predecessor', 'authority', 'witness'])
def test_new_digest_cannot_widen_profile(tmp_path, monkeypatch, defect):
    for name in (*upgrade.RETAINED_PROFILES, upgrade.PROFILE.name):
        (tmp_path / name).write_bytes(upgrade.PROFILE.with_name(name).read_bytes())
    path = tmp_path / upgrade.PROFILE.name
    if defect == 'profile':
        path.write_bytes(path.read_bytes() + b' ')
    elif defect == 'module':
        module = tmp_path / 'opening_latency_upgrade.py'
        module.write_bytes(Path(upgrade.__file__).read_bytes() + b'\nUNREVIEWED = True\n')
        monkeypatch.setattr(upgrade, '__file__', str(module))
    elif defect == 'retained_profile':
        prior = tmp_path / next(iter(upgrade.RETAINED_PROFILES))
        prior.write_bytes(prior.read_bytes() + b' ')
    else:
        value = deepcopy(json.loads(path.read_bytes()))
        if defect == 'predecessor':
            value['files']['rolling_runtime.py']['before'] = ['f' * 64]
        elif defect == 'authority':
            value['authority_effect'] = 'LIVE'
        else:
            value['predecessor_witnesses'][0]['manifest_sha256'] = 'f' * 64
        raw = json.dumps(value).encode()
        path.write_bytes(raw)
        monkeypatch.setattr(upgrade, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(upgrade, 'PROFILE', path)
    with pytest.raises(ValueError, match='OPENING_LATENCY_'):
        upgrade.profile()


def test_complete_predecessor_manifests_are_independently_pinned(closure, monkeypatch):
    for witness in upgrade.profile()['predecessor_witnesses']:
        revision = witness['revision'][:8]
        fixture = Path(__file__).parent / 'fixtures/retained-source-history' / (revision + '.json')
        raw = fixture.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == witness['manifest_sha256']
        value = json.loads(raw)
        assert {name: value['files'][name] for name in upgrade.SCOPE if name in value['files']} == witness['files']
        _historical(closure, monkeypatch, revision, witness['manifest_sha256'])


def test_required_checker_has_behavioral_falsifier(closure, monkeypatch):
    source = inspect.getsource(admission.prove_compatibility)
    needle = '            or opening_latency_upgrade.ADDITIONS - set(actual)\n'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, ''), 'opening-checker-falsifier', 'exec'), admission.__dict__, namespace)
    monkeypatch.setattr(admission, 'prove_compatibility', namespace['prove_compatibility'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_missing_checker_cannot_keep_a_current_source_closure(closure)


__all__ = ['closure']
