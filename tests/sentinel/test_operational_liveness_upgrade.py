"""Operational source admission preserves the book and refuses unknown bytes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from sentinel import operational_liveness_upgrade as upgrade, runtime_admission as admission
from sentinel import operational_runtime_upgrade as subsequent
from sentinel import callback_liveness_upgrade as callback_upgrade
from sentinel import startup_contention_upgrade as startup_upgrade
from sentinel import rolling_checkpoint as origin, rolling_initialization as initial
from sentinel import rolling_runtime as runtime, shadow_runtime
from sentinel.feed import rolling_go_inputs as inputs
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_retained_source_compatibility import closure
from tests.sentinel.test_paper_composition_upgrade import _execution_closure, _refresh_current
from tests.sentinel.test_rolling_retained_runtime_activation import (
    conn, pg, source, ready, operational_source, executable, _start, OBS)


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_only_exact_operational_source_transitions_are_allowed(name):
    record = upgrade.profile()['files'][name]
    actual = hashlib.sha256((Path(upgrade.__file__).parent/name).read_bytes()).hexdigest()
    if actual != record['after']:
        assert (subsequent.source_allowed(name, record['after'], actual)
                or callback_upgrade.source_allowed(name, record['after'], actual)
                or startup_upgrade.source_allowed(name, record['after'], actual))
    assert upgrade.source_allowed(name, record['before'][0], record['after'])
    assert not upgrade.source_allowed(name, 'f'*64, actual)
    assert not upgrade.source_allowed(name, record['before'][0], 'f'*64)
    assert not upgrade.source_allowed('core/kernel.py', record['before'][0], actual)


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_exact_transition_requires_authenticated_origin_and_environment(closure, name):
    _, checkpoint, context, manifest, source_value = _execution_closure(
        closure, name, source_profile=upgrade)
    proof = None
    try:
        proof = admission.prove_compatibility(manifest, checkpoint, context, source=source_value)
    except admission.Refused:
        pass
    assert proof == digest(admission.SourceManifest.model_validate(manifest).model_dump(by_alias=True))


@pytest.mark.parametrize('revision,fixture_sha', [
    ('368669bb', '9e8fcb27383f98e2991835d766dd83506a916f0cee1f617fc6f8a51d05345f66'),
    ('bf4009dc', '835f2fd3d4f3024fc739df5e2734c3359f5dc03ad06f9fbcbde53827ba989a34'),
    ('241da1f7', 'b03c7d3b02673034705b4bc7818d955639763896f29a3d47c96fa87b34c4671c'),
    ('4c9f8769', '020ea190598072c53e7c806ad1da72fc54a0a58de7298467b3469e9c070dcca9'),
    ('eb7b4d0c', '481cd8997974621f9204979e0d6f63a995460a5871d9952c2a4d8f1e4f85f0a7'),
    ('f52301f2', 'a3607d47a07375793f771a118b502a2abde3bc2330acb63ff8cf09deb9a027d7'),
    ('609f4a22', '49bc719a480bfe2e8e52f430fa0ce07b082adf9ea8069f47d97ef4a06ecde0c6'),
    ('35cc92a1', '3f85702f0265e52ea2460f45bc6d804ade6088d7f6e2b700752b121c05531286'),
])
def test_complete_historical_source_manifest_is_admitted(closure, monkeypatch, revision, fixture_sha):
    _, checkpoint, context, _, source_value = closure
    raw = (Path(__file__).parent/'fixtures/retained-source-history'/(revision+'.json')).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == fixture_sha
    manifest = json.loads(raw)
    root = Path(upgrade.__file__).parent
    actual = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in root.rglob('*.py') if '__pycache__' not in path.parts}
    current_env = source_value['environment']
    current_env['sentinel_source'].update(path=str(root), files=len(actual),
        hash=admission.source_closure(actual))
    previous_env = deepcopy(current_env)
    previous_env['sentinel_source'].update(files=len(manifest['files']),
        hash=admission.source_closure(manifest['files']))
    old_sha = hashlib.sha256(json.dumps(previous_env, sort_keys=True).encode()).hexdigest()
    checkpoint.runtime_identity.update(git_commit=manifest['revision'],
        sentinel_source_sha256=previous_env['sentinel_source']['hash'], environment_identity_sha256=old_sha)
    checkpoint.runtime_identity['reviewed_shadow_config']['validated_source_identity_sha256'] = old_sha
    context['runtime']['sentinel_source_sha256'] = current_env['sentinel_source']['hash']
    monkeypatch.setattr(admission.identity, '_imported_package_root', lambda _: root)
    proof, refusal = None, None
    try:
        proof = admission.prove_compatibility(manifest, checkpoint, context, source=source_value)
    except admission.Refused as error:
        refusal = str(error)
    assert proof == digest(admission.SourceManifest.model_validate(manifest).model_dump(by_alias=True)), refusal


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_neighbor_change_in_operational_file_refuses_full_admission(closure, name):
    root, checkpoint, context, manifest, source_value = _execution_closure(
        closure, name, source_profile=upgrade)
    path = root/name
    path.write_bytes(path.read_bytes()+b'\nUNREVIEWED_OPERATIONAL_CHANGE = True\n')
    _refresh_current(root, context, source_value)
    with pytest.raises(admission.Refused, match='RETAINED_ECONOMIC_SOURCE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source_value)


@pytest.mark.parametrize('kind', ['profile', 'module'])
def test_upgrade_profile_and_reader_tamper_refuse(tmp_path, monkeypatch, kind):
    if kind == 'profile':
        path = tmp_path/'profile.json'
        path.write_bytes(upgrade.PROFILE.read_bytes()+b' ')
        monkeypatch.setattr(upgrade, 'PROFILE', path)
        expected = 'PROFILE_CHANGED'
    else:
        path = tmp_path/'reader.py'
        original = Path(upgrade.__file__).read_bytes()
        changed = original.replace(b'previous in record', b'previous not in record')
        assert changed != original
        path.write_bytes(changed)
        monkeypatch.setattr(upgrade, '__file__', str(path))
        expected = 'MODULE_CHANGED'
    with pytest.raises(ValueError, match=expected):
        upgrade.profile()


@pytest.mark.parametrize('ready', [{'formed': True}], indirect=True)
@pytest.mark.parametrize('executable', ['operational', 'operational_runtime', 'installed', 'recovery_preceding', 'dashboard_preceding'], indirect=True)
def test_actual_formed_book_upgrade_restarts_without_reformation_or_reacquisition(
        conn, ready, executable, operational_source, monkeypatch):
    first = _start(conn, executable)
    before = origin.read(conn).model_dump(by_alias=True)
    records = dict(conn.execute('SELECT cursor_name,state FROM sentinel_processed_sessions').fetchall())
    conn.rollback()
    _, current, manifest = executable
    retained_manifest = deepcopy(manifest)
    admitted, refusal = None, None
    try:
        admitted = admission.admit(conn, context=current, manifest=manifest)
    except admission.Refused as exc:
        refusal = str(exc)
    assert admitted is not None, refusal
    assert admitted.authority_effect == 'NONE'
    assert manifest == retained_manifest
    assert origin.read(conn).model_dump(by_alias=True) == before
    conn.rollback()
    monkeypatch.setattr(shadow_runtime, '_validated_runtime_identity', lambda **kw: current['runtime'])
    monkeypatch.setattr(initial, 'initialize', lambda *a, **kw: pytest.fail('book reformed'))
    monkeypatch.setattr(inputs, 'prepare', lambda *a, **kw: pytest.fail('source reacquired'))
    monkeypatch.setattr(inputs, '_prepare', lambda *a, **kw: pytest.fail('source reacquired'))
    after = runtime.advance(conn, through=first.session, observation_id=OBS, starting_cash=50000)
    conn.rollback()
    assert after.state.state_hash == first.state.state_hash
    assert not after.appended
    assert admission.admit(conn, context=current, manifest=manifest) == admitted
    assert origin.read(conn).model_dump(by_alias=True) == before
    current_records = dict(conn.execute('SELECT cursor_name,state FROM sentinel_processed_sessions').fetchall())
    assert all(current_records[key] == value for key, value in records.items())
    assert set(current_records) - set(records) == {admission._key(current)}
    receipt = current_records[admission._key(current)]
    assert receipt == {'admission': admitted.model_dump(by_alias=True),
                       'hmac_sha256': admission._signature(admitted.model_dump(by_alias=True))}
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0
    conn.rollback()


@pytest.mark.parametrize('name', sorted(subsequent.SCOPE))
def test_operational_runtime_transition_is_exact_and_authenticated(closure, name):
    record = subsequent.profile()['files'][name]
    actual = hashlib.sha256((Path(subsequent.__file__).parent/name).read_bytes()).hexdigest()
    if actual != record['after']:
        assert (callback_upgrade.source_allowed(name, record['after'], actual)
                or startup_upgrade.source_allowed(name, record['after'], actual))
    for previous in record['before']:
        assert (subsequent.source_allowed(name, previous, actual)
                or callback_upgrade.source_allowed(name, previous, actual)
                or startup_upgrade.source_allowed(name, previous, actual))
        assert not subsequent.source_allowed(name, previous, 'f'*64)
    assert not subsequent.source_allowed(name, 'f'*64, actual)
    root, checkpoint, context, manifest, source_value = _execution_closure(
        closure, name, source_profile=subsequent)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source_value)
    path = root/name
    path.write_bytes(path.read_bytes()+b'\nUNREVIEWED_NEIGHBOR = True\n')
    _refresh_current(root, context, source_value)
    # The observer is also an authenticated addition: its exact-pin closure
    # guard rejects tampering before individual economic-source comparison.
    expected = ('RETAINED_SOURCE_CLOSURE_CHANGED' if name in subsequent.ADDITIONS
                else 'RETAINED_ECONOMIC_SOURCE_CHANGED')
    with pytest.raises(admission.Refused, match=expected):
        admission.prove_compatibility(manifest, checkpoint, context, source=source_value)


@pytest.mark.parametrize('already_present', [False, True])
def test_new_observer_requires_exact_pin_even_in_a_retained_manifest(closure, already_present):
    root, checkpoint, context, manifest, source_value = closure
    name = 'panel/authority_reader.py'
    path = root/name
    path.parent.mkdir()
    path.write_bytes((Path(subsequent.__file__).parent/name).read_bytes())
    _refresh_current(root, context, source_value)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source_value)
    path.write_bytes(path.read_bytes()+b'\nUNREVIEWED_OBSERVER = True\n')
    _refresh_current(root, context, source_value)
    if already_present:
        # An internally consistent manifest is still not a source waiver.
        manifest['files'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
        old_env = deepcopy(source_value['environment'])
        old_env['sentinel_source'].update(files=len(manifest['files']),
            hash=admission.source_closure(manifest['files']))
        old_hash = hashlib.sha256(json.dumps(old_env, sort_keys=True).encode()).hexdigest()
        checkpoint.runtime_identity.update(sentinel_source_sha256=old_env['sentinel_source']['hash'],
            environment_identity_sha256=old_hash)
        checkpoint.runtime_identity['reviewed_shadow_config']['validated_source_identity_sha256'] = old_hash
    with pytest.raises(admission.Refused, match='RETAINED_SOURCE_CLOSURE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source_value)


@pytest.mark.parametrize('kind', ['profile', 'module'])
def test_operational_runtime_profile_and_reader_are_authenticated(tmp_path, monkeypatch, kind):
    if kind == 'profile':
        path = tmp_path/'profile.json'
        path.write_bytes(subsequent.PROFILE.read_bytes()+b' ')
        monkeypatch.setattr(subsequent, 'PROFILE', path)
    else:
        path = tmp_path/'reader.py'
        original = Path(subsequent.__file__).read_bytes()
        changed = original.replace(b'actual.get(name) == sha', b'actual.get(name) != sha')
        assert changed != original
        path.write_bytes(changed)
        monkeypatch.setattr(subsequent, '__file__', str(path))
    with pytest.raises(ValueError, match='PROFILE_CHANGED|MODULE_CHANGED'):
        subsequent.profile()


__all__ = ['closure', 'conn', 'pg', 'source', 'ready', 'operational_source', 'executable']
