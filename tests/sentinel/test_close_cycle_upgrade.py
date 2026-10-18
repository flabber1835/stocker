"""Exact close-cycle upgrade and an actual retained-book restart."""
import hashlib
from pathlib import Path

import pytest

from sentinel import close_cycle_upgrade as upgrade, runtime_admission as admission
from sentinel import autonomy_runtime_upgrade, economic_migration, idle_leader_upgrade
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_retained_source_compatibility import closure
from tests.sentinel.test_paper_composition_upgrade import _execution_closure, _refresh_current
from tests.sentinel.test_rolling_retained_runtime_activation import (
    conn, pg, source, ready, operational_source, executable)
from tests.sentinel.test_operational_liveness_upgrade import (
    test_actual_formed_book_upgrade_restarts_without_reformation_or_reacquisition as _formed,
    test_complete_historical_source_manifest_is_admitted as _historical)


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_exact_transition_and_neighbor_refusal(closure, name):
    record = upgrade.profile()['files'][name]
    actual = hashlib.sha256((Path(upgrade.__file__).parent/name).read_bytes()).hexdigest()
    assert (actual == record['after']
            or autonomy_runtime_upgrade.source_allowed(name, record['after'], actual)
            or economic_migration.source_allowed(name, record['after'], actual)
            or idle_leader_upgrade.source_allowed(name, record['after'], actual))
    assert all(upgrade.source_allowed(name, p, record['after']) for p in record['before'])
    assert not upgrade.source_allowed(name, 'f'*64, actual)
    assert not upgrade.source_allowed('feed/repair.py', record['before'][0], actual)
    root, checkpoint, context, manifest, value = _execution_closure(closure, name, source_profile=upgrade)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=value) == digest(
        admission.SourceManifest.model_validate(manifest).model_dump(by_alias=True))
    path = root/name
    path.write_bytes(path.read_bytes()+b'\nUNREVIEWED_CHANGE=True\n')
    _refresh_current(root, context, value)
    with pytest.raises(admission.Refused):
        admission.prove_compatibility(manifest, checkpoint, context, source=value)


@pytest.mark.parametrize('kind', ['profile', 'module'])
def test_profile_and_module_authentication(tmp_path, monkeypatch, kind):
    if kind == 'profile':
        path = tmp_path/'profile.json'; path.write_bytes(upgrade.PROFILE.read_bytes()+b' ')
        monkeypatch.setattr(upgrade, 'PROFILE', path)
    else:
        path = tmp_path/'module.py'; path.write_bytes(Path(upgrade.__file__).read_bytes()+b'\nUNREVIEWED=True\n')
        monkeypatch.setattr(upgrade, '__file__', str(path))
    with pytest.raises(ValueError, match='PROFILE_CHANGED|MODULE_CHANGED'): upgrade.profile()


@pytest.mark.parametrize('name', sorted(upgrade.ADDITIONS))
def test_identity_addition_is_exactly_pinned(name):
    actual=hashlib.sha256((Path(upgrade.__file__).parent/name).read_bytes()).hexdigest()
    assert upgrade.additions_allowed({name:actual})=={name}
    assert upgrade.additions_allowed({name:'f'*64})==set()
    assert upgrade.additions_allowed({'feed/unreviewed_identity.py':actual})==set()


def test_complete_verified_installed_main_is_admitted(closure, monkeypatch):
    _historical(closure, monkeypatch, '0a5e5e51', '68b0a58c77cd0c7b0e49a62ae4b306a679c2c6b3b9938ab4e2fe7e9013a3542d')


@pytest.mark.parametrize('executable', ['close_cycle_preceding'], indirect=True)
@pytest.mark.parametrize('ready', [{'formed': True}], indirect=True)
def test_actual_formed_book_preserved(conn, ready, operational_source, executable, monkeypatch):
    _formed(conn, ready, executable, operational_source, monkeypatch)
