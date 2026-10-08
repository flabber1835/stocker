"""Exact execution upgrade admission never becomes a general source waiver."""
import hashlib
import json
from pathlib import Path

import pytest

from sentinel import execution_upgrade as upgrade, runtime_admission as admission
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_retained_source_compatibility import closure


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_exact_execution_upgrade_sources_are_pinned(name):
    record = upgrade.profile()['files'][name]
    actual = hashlib.sha256((Path(upgrade.__file__).parent/name).read_bytes()).hexdigest()
    if actual != record['after']:
        from sentinel import retained_readiness_upgrade as subsequent
        from sentinel import dual_plan_renewal_upgrade as renewal
        assert (subsequent.source_allowed(name, record['after'], actual)
                or renewal.source_allowed(name, record['after'], actual))
    reviewed = record['after']
    for previous in record['before']:
        assert upgrade.source_allowed(name, previous, reviewed)
        assert not upgrade.source_allowed(name, previous, 'f'*64)
    assert not upgrade.source_allowed(name, '0'*64, actual)


@pytest.mark.parametrize('name', ['core/kernel.py', 'feed/repair.py', 'paper/new_boundary.py'])
def test_execution_upgrade_never_admits_unlisted_paths(name):
    assert not upgrade.source_allowed(name, '0'*64, 'f'*64)


def test_execution_upgrade_profile_tamper_refuses(tmp_path, monkeypatch):
    path = tmp_path/'profile.json'
    path.write_text(upgrade.PROFILE.read_text()+' ')
    monkeypatch.setattr(upgrade, 'PROFILE', path)
    with pytest.raises(ValueError, match='EXECUTION_UPGRADE_PROFILE_CHANGED'):
        upgrade.profile()


def test_execution_upgrade_module_tamper_refuses(tmp_path, monkeypatch):
    path = tmp_path/'execution_upgrade.py'
    source = Path(upgrade.__file__).read_text()
    assert 'previous in record' in source
    path.write_text(source.replace('previous in record', 'previous not in record'))
    monkeypatch.setattr(upgrade, '__file__', str(path))
    with pytest.raises(ValueError, match='EXECUTION_UPGRADE_MODULE_CHANGED'):
        upgrade.profile()


def _execution_closure(closure, name, *, source_profile=upgrade):
    root, checkpoint, context, manifest, source = closure
    actual_root = Path(upgrade.__file__).parent
    path = root/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((actual_root/name).read_bytes())
    manifest['files'][name] = source_profile.profile()['files'][name]['before'][0]
    _refresh_current(root, context, source)
    prior_env = dict(source['environment'])
    prior_env['sentinel_source'] = {**prior_env['sentinel_source'],
        'files': len(manifest['files']), 'hash': admission.source_closure(manifest['files'])}
    previous_hash = hashlib.sha256(json.dumps(prior_env, sort_keys=True).encode()).hexdigest()
    checkpoint.runtime_identity.update(sentinel_source_sha256=prior_env['sentinel_source']['hash'],
        environment_identity_sha256=previous_hash)
    checkpoint.runtime_identity['reviewed_shadow_config']['validated_source_identity_sha256'] = previous_hash
    return root, checkpoint, context, manifest, source


def _refresh_current(root, context, source):
    files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in root.rglob('*.py')}
    actual = admission.source_closure(files)
    context['runtime']['sentinel_source_sha256'] = actual
    source['environment']['sentinel_source'].update(files=len(files), hash=actual)


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_exact_execution_upgrade_has_authenticated_source_and_environment_proof(closure, name):
    _, checkpoint, context, manifest, source = _execution_closure(closure, name)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source) == digest(
        admission.SourceManifest.model_validate(manifest).model_dump(by_alias=True))


def test_unreviewed_neighbor_guard_change_still_refuses_full_admission(closure):
    root, checkpoint, context, manifest, source = _execution_closure(closure, 'paper/inspection.py')
    path = root/'paper/inspection.py'
    raw = path.read_text()
    needle = 'identity.wrapper_kind != expected_wrapper_kind'
    assert needle in raw
    path.write_text(raw.replace(needle, 'False'))
    _refresh_current(root, context, source)
    with pytest.raises(admission.Refused, match='RETAINED_ECONOMIC_SOURCE_CHANGED:paper/inspection.py'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


__all__ = ['closure']
