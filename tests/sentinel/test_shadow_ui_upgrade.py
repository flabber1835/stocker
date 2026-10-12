"""Exact retained-source recovery admission; neighboring edits still refuse."""
from copy import deepcopy
import hashlib
import json
import inspect
import textwrap
from pathlib import Path

import pytest
from sentinel import open_time_upgrade

from sentinel import shadow_ui_upgrade as upgrade, runtime_admission as admission
from sentinel import dashboard_monitor_upgrade as subsequent
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_retained_source_compatibility import closure
from tests.sentinel.test_paper_composition_upgrade import _execution_closure, _refresh_current
from tests.sentinel.test_rolling_retained_runtime_activation import (
    conn, pg, source, ready, operational_source, executable)
from tests.sentinel.test_operational_liveness_upgrade import (
    test_actual_formed_book_upgrade_restarts_without_reformation_or_reacquisition
    as _qualify_formed_book)


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_shadow_ui_upgrade_pins_exact_predecessor_and_target_and_rejects_neighbor(closure, name):
    record = upgrade.profile()['files'][name]
    actual = hashlib.sha256((Path(upgrade.__file__).parent/name).read_bytes()).hexdigest()
    assert (actual == record['after']
            or subsequent.source_allowed(name, record['after'], actual)
            or open_time_upgrade.source_allowed(name, record['after'], actual))
    assert all(upgrade.source_allowed(name, before, record['after']) for before in record['before'])
    assert not upgrade.source_allowed(name, 'f'*64, actual)
    assert not upgrade.source_allowed(name, record['before'][0], 'f'*64)
    root, checkpoint, context, manifest, source = _execution_closure(closure, name, source_profile=upgrade)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source) == digest(
        admission.SourceManifest.model_validate(manifest).model_dump(by_alias=True))
    path = root/name
    path.write_bytes(path.read_bytes()+b'\nUNREVIEWED_CHANGE = True\n')
    _refresh_current(root, context, source)
    with pytest.raises(admission.Refused, match='RETAINED_ECONOMIC_SOURCE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


def test_new_recovery_module_is_admitted_only_at_exact_reviewed_bytes(closure):
    root, checkpoint, context, manifest, source = closure
    name = 'shadow_service_status.py'
    path = root/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((Path(upgrade.__file__).parent/name).read_bytes())
    _refresh_current(root, context, source)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source)
    path.write_bytes(path.read_bytes()+b'\nUNREVIEWED_CHANGE = True\n')
    _refresh_current(root, context, source)
    with pytest.raises(admission.Refused, match='RETAINED_SOURCE_CLOSURE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


def test_removing_exact_supervisor_admission_is_detected(closure, monkeypatch):
    source = textwrap.dedent(inspect.getsource(admission.prove_compatibility))
    needle = '((ADMINISTRATIVE-ui_upgrade.SCOPE-open_time_upgrade.SCOPE) | ADDITIONS)'
    assert needle in source
    namespace = {}; exec(compile(source.replace(needle, '(ADMINISTRATIVE | ADDITIONS)'),
        'supervisor-source-falsifier', 'exec'), admission.__dict__, namespace)
    monkeypatch.setattr(admission, 'prove_compatibility', namespace['prove_compatibility'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_shadow_ui_upgrade_pins_exact_predecessor_and_target_and_rejects_neighbor(closure, 'shadow_supervisor.py')


def test_complete_installed_release_manifest_is_independently_pinned_and_admitted(closure):
    raw = (Path(__file__).parent/'fixtures/retained-source-history/00f3ef09.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '7f0cbc9ec13abdd39bda38d1c57d831a5699bd62ba8f621ae4bfcdf5d5d3d5c1'
    previous = json.loads(raw)
    assert previous['revision'] == '00f3ef0922688704b7c144b88ed914118d883883'
    root, checkpoint, context, manifest, source = closure
    actual_root = Path(upgrade.__file__).parent
    for name, sha in previous['files'].items():
        path = root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((actual_root/name).read_bytes())
        manifest['files'][name] = sha
    for name in ('shadow_service_status.py', 'shadow_ui_upgrade.py'):
        (root/name).write_bytes((actual_root/name).read_bytes())
    manifest['seam_sources'] = previous['seam_sources']
    _refresh_current(root, context, source)
    env = deepcopy(source['environment'])
    env['sentinel_source'].update(files=len(manifest['files']), hash=admission.source_closure(manifest['files']))
    old_environment = hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()
    checkpoint.runtime_identity.update(sentinel_source_sha256=env['sentinel_source']['hash'],
        environment_identity_sha256=old_environment)
    checkpoint.runtime_identity['reviewed_shadow_config']['validated_source_identity_sha256'] = old_environment
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source)


@pytest.mark.parametrize('kind', ['profile', 'module'])
def test_recovery_profile_and_verifier_tampering_refuse(tmp_path, monkeypatch, kind):
    if kind == 'profile':
        path = tmp_path/'changed.json'
        path.write_bytes(upgrade.PROFILE.read_bytes()+b' ')
        monkeypatch.setattr(upgrade, 'PROFILE', path)
    else:
        path = tmp_path/'changed.py'
        path.write_bytes(Path(upgrade.__file__).read_bytes().replace(b'previous in record', b'previous not in record'))
        monkeypatch.setattr(upgrade, '__file__', str(path))
    with pytest.raises(ValueError, match='PROFILE_CHANGED|MODULE_CHANGED'):
        upgrade.profile()


@pytest.mark.parametrize('ready', [{'formed': True}], indirect=True)
@pytest.mark.parametrize('executable', ['shadow_ui_preceding', 'unsent_recovery_preceding'], indirect=True)
def test_current_installed_formed_book_recovers_without_reformation_or_reacquisition(
        conn, ready, executable, operational_source, monkeypatch):
    _qualify_formed_book(conn, ready, executable, operational_source, monkeypatch)
