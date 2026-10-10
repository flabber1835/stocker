"""Startup waiting admits only the pinned source repair and preserves the book."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from sentinel import startup_contention_upgrade as upgrade, runtime_admission as admission
from sentinel import operational_runtime_upgrade as subsequent
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_retained_source_compatibility import closure
from tests.sentinel.test_paper_composition_upgrade import _execution_closure, _refresh_current
from tests.sentinel.test_rolling_retained_runtime_activation import (
    conn, pg, source, ready, operational_source, executable)
from tests.sentinel.test_operational_liveness_upgrade import (
    test_actual_formed_book_upgrade_restarts_without_reformation_or_reacquisition as _formed_upgrade)


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_only_exact_reviewed_service_upgrade_is_allowed(closure, name):
    record = upgrade.profile()['files'][name]
    actual = hashlib.sha256((Path(upgrade.__file__).parent/name).read_bytes()).hexdigest()
    if actual != record['after']:
        assert subsequent.source_allowed(name, record['after'], actual)
    assert all(upgrade.source_allowed(name, prior, record['after']) for prior in record['before'])
    assert not upgrade.source_allowed(name, 'f'*64, actual)
    assert not upgrade.source_allowed(name, record['before'][0], 'f'*64)
    assert not upgrade.source_allowed('automation/store.py', record['before'][0], actual)
    root, checkpoint, context, manifest, value = _execution_closure(closure, name, source_profile=upgrade)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=value) == digest(
        admission.SourceManifest.model_validate(manifest).model_dump(by_alias=True))
    path = root/name
    path.write_bytes(path.read_bytes()+b'\nUNREVIEWED_CHANGE = True\n')
    _refresh_current(root, context, value)
    with pytest.raises(admission.Refused, match='RETAINED_ECONOMIC_SOURCE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=value)


def test_complete_previous_release_is_bound_to_verified_git_manifest(closure, monkeypatch):
    _, checkpoint, context, _, value = closure
    raw = (Path(__file__).parent/'fixtures/retained-source-history/4c9f8769.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '020ea190598072c53e7c806ad1da72fc54a0a58de7298467b3469e9c070dcca9'
    manifest = json.loads(raw)
    assert manifest['revision'] == '4c9f8769a53dc1dd924348f21a357616209e41c4'
    root = Path(upgrade.__file__).parent
    actual = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in root.rglob('*.py') if '__pycache__' not in p.parts}
    current_env = value['environment']
    current_env['sentinel_source'].update(path=str(root), files=len(actual), hash=admission.source_closure(actual))
    old_env = deepcopy(current_env)
    old_env['sentinel_source'].update(files=len(manifest['files']), hash=admission.source_closure(manifest['files']))
    old_sha = hashlib.sha256(json.dumps(old_env, sort_keys=True).encode()).hexdigest()
    checkpoint.runtime_identity.update(git_commit=manifest['revision'],
        sentinel_source_sha256=old_env['sentinel_source']['hash'], environment_identity_sha256=old_sha)
    checkpoint.runtime_identity['reviewed_shadow_config']['validated_source_identity_sha256'] = old_sha
    context['runtime']['sentinel_source_sha256'] = current_env['sentinel_source']['hash']
    monkeypatch.setattr(admission.identity, '_imported_package_root', lambda _: root)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=value) == digest(
        admission.SourceManifest.model_validate(manifest).model_dump(by_alias=True))
    changed = deepcopy(manifest)
    changed['files']['automation/store.py'] = 'f'*64
    with pytest.raises(admission.Refused, match='RETAINED_SOURCE_MANIFEST_ORIGIN_MISMATCH'):
        admission.prove_compatibility(changed, checkpoint, context, source=value)


@pytest.mark.parametrize('kind', ['profile', 'module'])
def test_profile_or_implementation_tampering_refuses(tmp_path, monkeypatch, kind):
    if kind == 'profile':
        path = tmp_path/'profile.json'
        path.write_bytes(upgrade.PROFILE.read_bytes()+b' ')
        monkeypatch.setattr(upgrade, 'PROFILE', path)
    else:
        path = tmp_path/'reader.py'
        raw = Path(upgrade.__file__).read_bytes()
        changed = raw.replace(b'previous in record', b'previous not in record')
        assert changed != raw
        path.write_bytes(changed)
        monkeypatch.setattr(upgrade, '__file__', str(path))
    with pytest.raises(ValueError, match='PROFILE_CHANGED|MODULE_CHANGED'):
        upgrade.profile()


@pytest.mark.parametrize('ready', [{'formed': True}], indirect=True)
@pytest.mark.parametrize('executable', ['startup_preceding', 'idle_preceding'], indirect=True)
def test_formed_book_startup_upgrade_does_not_reform_or_reacquire(
        conn, ready, executable, operational_source, monkeypatch):
    _formed_upgrade(conn, ready, executable, operational_source, monkeypatch)


def test_complete_pr500_manifest_is_pinned_to_verified_release():
    raw = (Path(__file__).parent/'fixtures/retained-source-history/eb7b4d0c.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '481cd8997974621f9204979e0d6f63a995460a5871d9952c2a4d8f1e4f85f0a7'
    value = json.loads(raw)
    assert value['schema'] == 'sentinel.retained-source-manifest/1'
    assert value['revision'] == 'eb7b4d0c2e8cd78da3e95b6b583e546a09821c86'
    for name in ('automation_runtime.py', 'panel/model.py', 'panel/sources.py'):
        assert value['files'][name] in upgrade.profile()['files'][name]['before']


__all__ = ['closure', 'conn', 'pg', 'source', 'ready', 'operational_source', 'executable']
