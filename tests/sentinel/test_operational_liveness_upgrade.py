"""Operational source admission preserves the book and refuses unknown bytes."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from sentinel import operational_liveness_upgrade as upgrade, runtime_admission as admission
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
    assert actual == record['after']
    assert upgrade.source_allowed(name, record['before'][0], actual)
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
@pytest.mark.parametrize('executable', ['operational'], indirect=True)
def test_actual_formed_book_upgrade_restarts_without_reformation_or_reacquisition(
        conn, ready, executable, operational_source, monkeypatch):
    first = _start(conn, executable)
    before = origin.read(conn).model_dump(by_alias=True)
    records = dict(conn.execute('SELECT cursor_name,state FROM sentinel_processed_sessions').fetchall())
    conn.rollback()
    _, current, manifest = executable
    retained_manifest = deepcopy(manifest)
    admitted = None
    try:
        admitted = admission.admit(conn, context=current, manifest=manifest)
    except admission.Refused:
        pass
    assert admitted is not None
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


__all__ = ['closure', 'conn', 'pg', 'source', 'ready', 'operational_source', 'executable']
