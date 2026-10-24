"""Exact retained-source recovery admission; neighboring edits still refuse."""
from sentinel import protected_cohort_upgrade
from copy import deepcopy
import hashlib
import json
import inspect
import textwrap
from pathlib import Path

import pytest
from sentinel import autonomy_runtime_upgrade as autonomy_upgrade
from sentinel import open_time_upgrade, close_cycle_upgrade, idle_leader_upgrade

from sentinel import shadow_ui_upgrade as upgrade, runtime_admission as admission
from sentinel import dashboard_monitor_upgrade as subsequent
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_retained_source_compatibility import closure
from tests.support import historical_transition_fixture as historical
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
    historical.require_current_source(name, actual)
    reviewed = historical.target()[name]
    assert (reviewed == record['after'] or historical.transition_registry.load().source_allowed(
        name, record['after'], reviewed))
    if actual != record['after']:
        assert not upgrade.source_allowed(name, record['before'][0], actual)
    assert all(upgrade.source_allowed(name, before, record['after']) for before in record['before'])
    assert not upgrade.source_allowed(name, 'f'*64, actual)
    assert not upgrade.source_allowed(name, record['before'][0], 'f'*64)
    root, checkpoint, context, manifest, source = _execution_closure(closure, name, source_profile=upgrade)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source) == digest(
        admission.SourceManifest.model_validate(manifest).model_dump(by_alias=True))
    path = root/name
    path.write_bytes(path.read_bytes()+b'\nUNREVIEWED_CHANGE = True\n')
    _refresh_current(root, context, source)
    # A reviewed addition is checked by the complete closure before ordinary
    # predecessor transitions; a neighboring edit must retain that refusal.
    reason = ('RETAINED_SOURCE_CLOSURE_CHANGED' if name in upgrade.ADDITIONS | idle_leader_upgrade.SCOPE | protected_cohort_upgrade.SCOPE
              else 'RETAINED_ECONOMIC_SOURCE_CHANGED:' + name)
    with pytest.raises(admission.Refused) as refused:
        admission.prove_compatibility(manifest, checkpoint, context, source=source)
    assert str(refused.value) == reason


@pytest.mark.parametrize('name', sorted(upgrade.ADDITIONS))
def test_new_recovery_module_is_admitted_only_at_exact_reviewed_bytes(closure, name):
    root, checkpoint, context, manifest, source = closure
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
    registry = historical.transition_registry
    source = textwrap.dedent(inspect.getsource(registry.Transitions.administrative))
    needle = "for key in ('ui', 'open_time', 'close_cycle'):"
    assert needle in source
    namespace = {}; exec(compile(source.replace(needle, 'for key in ():'),
        'supervisor-source-falsifier', 'exec'), registry.__dict__, namespace)
    monkeypatch.setattr(registry.Transitions, 'administrative', namespace['administrative'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_shadow_ui_upgrade_pins_exact_predecessor_and_target_and_rejects_neighbor(closure, 'shadow_supervisor.py')


def test_complete_installed_release_manifest_is_independently_pinned_and_admitted(closure, monkeypatch):
    raw = (Path(__file__).parent/'fixtures/retained-source-history/00f3ef09.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '7f0cbc9ec13abdd39bda38d1c57d831a5699bd62ba8f621ae4bfcdf5d5d3d5c1'
    previous = json.loads(raw)
    assert previous['revision'] == '00f3ef0922688704b7c144b88ed914118d883883'
    fixture_root, checkpoint, context, _, source = closure
    actual_root = Path(upgrade.__file__).parent
    actual = {p.relative_to(actual_root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in actual_root.rglob('*.py') if '__pycache__' not in p.parts}
    historical.require_current_release(observed=actual)
    root = fixture_root / 'complete-shadow-ui-historical-target'
    historical.complete_target(root)
    manifest = deepcopy(previous)
    source['environment']['sentinel_source'].update(path=str(root))
    _refresh_current(root, context, source)
    env = deepcopy(source['environment'])
    env['sentinel_source'].update(files=len(manifest['files']), hash=admission.source_closure(manifest['files']))
    old_environment = hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()
    checkpoint.runtime_identity.update(git_commit=manifest['revision'],
        sentinel_source_sha256=env['sentinel_source']['hash'],
        environment_identity_sha256=old_environment)
    checkpoint.runtime_identity['reviewed_shadow_config']['validated_source_identity_sha256'] = old_environment
    monkeypatch.setattr(admission.identity, '_imported_package_root', lambda _: root)
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
