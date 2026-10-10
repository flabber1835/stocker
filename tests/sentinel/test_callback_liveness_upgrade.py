"""Closed source upgrades preserve the authenticated formed financial book."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from sentinel import callback_liveness_upgrade as upgrade, runtime_admission as admission
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_retained_source_compatibility import closure
from tests.sentinel.test_paper_composition_upgrade import _execution_closure, _refresh_current
from tests.sentinel.test_rolling_retained_runtime_activation import (
    conn, pg, source, ready, operational_source, executable)
from tests.sentinel.test_operational_liveness_upgrade import (
    test_actual_formed_book_upgrade_restarts_without_reformation_or_reacquisition as _formed_upgrade)


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_callback_transition_is_exact_and_neighbor_change_refuses(closure, name):
    record = upgrade.profile()['files'][name]
    actual = hashlib.sha256((Path(upgrade.__file__).parent/name).read_bytes()).hexdigest()
    assert actual == record['after']
    assert all(upgrade.source_allowed(name, previous, actual) for previous in record['before'])
    assert not upgrade.source_allowed(name, 'f'*64, actual)
    assert not upgrade.source_allowed(name, record['before'][0], 'f'*64)
    assert not upgrade.source_allowed('core/kernel.py', record['before'][0], actual)
    root, checkpoint, context, manifest, value = _execution_closure(closure, name, source_profile=upgrade)
    proof, refusal = None, None
    try:
        proof = admission.prove_compatibility(manifest, checkpoint, context, source=value)
    except admission.Refused as error:
        refusal = str(error)
    assert proof == digest(admission.SourceManifest.model_validate(manifest).model_dump(by_alias=True)), refusal
    path = root/name
    path.write_bytes(path.read_bytes()+b'\nUNREVIEWED_NEIGHBOR = True\n')
    _refresh_current(root, context, value)
    with pytest.raises(admission.Refused, match='RETAINED_ECONOMIC_SOURCE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=value)


def test_complete_preceding_release_source_is_authenticated(closure, monkeypatch):
    _, checkpoint, context, _, value = closure
    raw = (Path(__file__).parent/'fixtures/retained-source-history/f52301f2.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == 'a3607d47a07375793f771a118b502a2abde3bc2330acb63ff8cf09deb9a027d7'
    manifest = json.loads(raw)
    assert manifest['revision'] == 'f52301f25f483e40ac860efa027f52acc4193482'
    root = Path(upgrade.__file__).parent
    actual = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in root.rglob('*.py') if '__pycache__' not in path.parts}
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
    foreign = deepcopy(manifest)
    foreign['files']['automation/health.py'] = 'f'*64
    with pytest.raises(admission.Refused, match='RETAINED_SOURCE_MANIFEST_ORIGIN_MISMATCH'):
        admission.prove_compatibility(foreign, checkpoint, context, source=value)
    value['environment']['dependencies'] = 'changed'
    with pytest.raises(admission.Refused, match='RETAINED_COMPUTATIONAL_ENVIRONMENT_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=value)


@pytest.mark.parametrize('kind', ['profile', 'module'])
def test_callback_profile_and_reader_are_authenticated(tmp_path, monkeypatch, kind):
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
@pytest.mark.parametrize('executable', ['callback_liveness', 'preceding_release'], indirect=True)
def test_formed_book_callback_upgrade_does_not_reform_or_reacquire(
        conn, ready, executable, operational_source, monkeypatch):
    _formed_upgrade(conn, ready, executable, operational_source, monkeypatch)


__all__ = ['closure', 'conn', 'pg', 'source', 'ready', 'operational_source', 'executable']
