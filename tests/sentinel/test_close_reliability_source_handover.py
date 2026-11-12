"""A backed close patch retains the exact signed predecessor and source guards."""
import hashlib
import json

import pytest

from sentinel import runtime_admission as admission, url_selected_source_basis as basis
from tests.support.source_history import encoded_profile, expanded_profile, pre_market_history


REVISION = '1692c0421084198e3cba03d098d2d0f92adbb79d'
CLOSURE = '9b7907bf1bbd7080607802f329604e7c554d3d5da6ae005cfa2532ca7129ef43'


def test_exact_close_successor_retains_every_historical_map():
    profile = basis._profile()
    assert basis.CLOSE_RELIABILITY_PREDECESSOR_REVISION == REVISION
    assert profile['authority_effect'] == 'NONE'
    records = profile['retained_predecessors']
    predecessor = records[REVISION]['files']
    assert len(predecessor) == 471
    assert admission.source_closure(predecessor) == CLOSURE

    market = basis.MARKET_BUY_PREDECESSOR_REVISION
    history = {**pre_market_history(profile), market: records[market]}
    assert len(history) == 44
    payload = json.dumps(history, sort_keys=True, separators=(',', ':')).encode()
    assert hashlib.sha256(payload).hexdigest() == (
        '5cf6e2e47cbee12020fc50665bff704010909a3601074a276af27748909186e5')

    actual = admission._source_files(basis.PROFILE.parent)
    assert set(predecessor) <= set(actual)
    assert basis.predecessor_view(actual, previous=predecessor) == predecessor


@pytest.mark.parametrize('fault', ['changed', 'missing', 'extra'])
def test_close_source_transition_rejects_unreviewed_current_bytes(fault):
    current = admission._source_files(basis.PROFILE.parent)
    previous = basis._profile()['retained_predecessors'][REVISION]['files']
    if fault == 'changed':
        current['panel/verification_service.py'] = '0' * 64
    elif fault == 'missing':
        del current['panel/verification_service.py']
    else:
        current['unreviewed.py'] = '0' * 64
    assert basis.predecessor_view(current, previous=previous) is current


def test_repinning_the_profile_cannot_relabel_the_signed_predecessor(tmp_path, monkeypatch):
    profile = expanded_profile()
    predecessor = profile['retained_predecessors'][REVISION]
    predecessor['files']['panel/verification_service.py'] = 'f' * 64
    predecessor['source_sha256'] = basis._closure(predecessor['files'])
    payload = encoded_profile(profile)
    path = tmp_path / 'mutated-profile.json'
    path.write_bytes(payload)
    monkeypatch.setattr(basis, 'PROFILE', path)
    monkeypatch.setattr(basis, 'PROFILE_SHA256', hashlib.sha256(payload).hexdigest())
    with pytest.raises(ValueError, match='RETAINED_PREDECESSOR_CHANGED'):
        basis._profile()


def test_opening_recovery_preserves_installed_source_and_earlier_maps():
    revision = 'fad555c0ea0449a9225b01c8f6d96e22140b35b3'
    assert basis.OPENING_RECOVERY_PREDECESSOR_REVISION == revision
    profile = basis._profile()
    assert profile['authority_effect'] == 'NONE'
    history = dict(profile['retained_predecessors'])
    installed = history.pop(revision)['files']
    assert len(installed) == 475
    assert admission.source_closure(installed) == '129def6620017e734a6733dd9cfc541f8fd9a12f52f8227c9f3737e444d5f1fe'
    assert len(history) == 47
    payload = json.dumps(history, sort_keys=True, separators=(',', ':')).encode()
    assert hashlib.sha256(payload).hexdigest() == '7a33e9f3400eac8f49a6a131c7b42d8ab646dce9f759fa349105f364db7852cb'

    actual = admission._source_files(basis.PROFILE.parent)
    assert basis.predecessor_view(actual, previous=installed) == installed
    actual['paper/recovery.py'] = '0' * 64
    assert basis.predecessor_view(actual, previous=installed) is actual
