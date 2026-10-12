"""Exact source scope and actual retained-book upgrade, with refusal neighbors."""
from pathlib import Path
import hashlib

import pytest
from sentinel import open_time_upgrade

from sentinel import dashboard_monitor_upgrade as upgrade, runtime_admission as admission
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_retained_source_compatibility import closure
from tests.sentinel.test_paper_composition_upgrade import _execution_closure, _refresh_current
from tests.sentinel.test_rolling_retained_runtime_activation import (
    conn, pg, source, ready, operational_source, executable)
from tests.sentinel.test_operational_liveness_upgrade import (
    test_actual_formed_book_upgrade_restarts_without_reformation_or_reacquisition as _formed,
    test_complete_historical_source_manifest_is_admitted as _historical)


@pytest.mark.parametrize('name',sorted(upgrade.SCOPE))
def test_exact_transition_and_neighbor_refusal(closure,name):
    record=upgrade.profile()['files'][name]
    actual=hashlib.sha256((Path(upgrade.__file__).parent/name).read_bytes()).hexdigest()
    assert actual==record['after'] or open_time_upgrade.source_allowed(name, record['after'], actual)
    assert all(upgrade.source_allowed(name,previous,record['after']) for previous in record['before'])
    assert not upgrade.source_allowed(name,'f'*64,actual)
    assert not upgrade.source_allowed('core/kernel.py',record['before'][0],actual)
    root,checkpoint,context,manifest,value=_execution_closure(closure,name,source_profile=upgrade)
    assert admission.prove_compatibility(manifest,checkpoint,context,source=value)==digest(
        admission.SourceManifest.model_validate(manifest).model_dump(by_alias=True))
    path=root/name;path.write_bytes(path.read_bytes()+b'\nUNREVIEWED_DASHBOARD_CHANGE=True\n')
    _refresh_current(root,context,value)
    with pytest.raises(admission.Refused):admission.prove_compatibility(manifest,checkpoint,context,source=value)


@pytest.mark.parametrize('name',sorted(upgrade.ADDITIONS))
def test_addition_requires_exact_pin_even_in_an_old_manifest(closure,name):
    root,checkpoint,context,manifest,value=closure
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes((Path(upgrade.__file__).parent/name).read_bytes())
    _refresh_current(root,context,value)
    assert admission.prove_compatibility(manifest,checkpoint,context,source=value)
    path.write_bytes(path.read_bytes()+b'\nUNREVIEWED_MONITOR=True\n')
    _refresh_current(root,context,value)
    with pytest.raises(admission.Refused,match='CLOSURE_CHANGED'):
        admission.prove_compatibility(manifest,checkpoint,context,source=value)


@pytest.mark.parametrize('kind',['profile','module'])
def test_profile_and_module_authentication(tmp_path,monkeypatch,kind):
    if kind=='profile':
        path=tmp_path/'profile.json';path.write_bytes(upgrade.PROFILE.read_bytes()+b' ')
        monkeypatch.setattr(upgrade,'PROFILE',path)
    else:
        path=tmp_path/'module.py';path.write_bytes(Path(upgrade.__file__).read_bytes()+b'\nUNREVIEWED=True\n')
        monkeypatch.setattr(upgrade,'__file__',str(path))
    with pytest.raises(ValueError,match='PROFILE_CHANGED|MODULE_CHANGED'):upgrade.profile()


def test_complete_verified_main_closure_is_preserved(closure,monkeypatch):
    _historical(closure,monkeypatch,'0b1f8c2f','29ec8ee16abc7036e8e82d212cd4e95b1d2d44800a3b2ea566182fb2dca4be9a')


@pytest.mark.parametrize('executable',[(upgrade,'panel/authority_reader.py')],indirect=True)
@pytest.mark.parametrize('ready',[{'formed':True}],indirect=True)
def test_actual_formed_book_preserved(conn,ready,operational_source,executable,monkeypatch):
    _formed(conn,ready,executable,operational_source,monkeypatch)
