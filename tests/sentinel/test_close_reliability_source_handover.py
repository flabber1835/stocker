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
    history.pop(basis.OPENING_OUTCOMES_PREDECESSOR_REVISION)
    history.pop(basis.NATIVE_FEE_POSTING_DELAY_PREDECESSOR_REVISION)
    history.pop(basis.ROLLING_GO_INDEX_PREDECESSOR_REVISION)
    history.pop(basis.OPEN_CLOSE_DASHBOARD_PREDECESSOR_REVISION)
    history.pop(basis.CASH_CORRECTION_PREDECESSOR_REVISION)
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


def test_cash_correction_preserves_installed_source_and_earlier_maps():
    revision = '509b66c5f50ffbe4b22331a471c1d021c9dde99d'
    assert basis.CASH_CORRECTION_PREDECESSOR_REVISION == revision
    profile = basis._profile()
    assert profile['authority_effect'] == 'NONE'
    history = dict(profile['retained_predecessors'])
    history.pop(basis.OPENING_OUTCOMES_PREDECESSOR_REVISION)
    history.pop(basis.NATIVE_FEE_POSTING_DELAY_PREDECESSOR_REVISION)
    history.pop(basis.ROLLING_GO_INDEX_PREDECESSOR_REVISION)
    history.pop(basis.OPEN_CLOSE_DASHBOARD_PREDECESSOR_REVISION)
    installed = history.pop(revision)['files']
    assert len(installed) == 475
    assert admission.source_closure(installed) == 'f95dd91f021b25965c8307ed90f636edc6bb66fe4f5a1c65e2591933bc98ea11'
    assert len(history) == 48
    payload = json.dumps(history, sort_keys=True, separators=(',', ':')).encode()
    assert hashlib.sha256(payload).hexdigest() == 'b2c1337a775c6bfc0267ab420bb8a5b5858c8d7374580d5d32a4baa41dbc15ad'

    actual = admission._source_files(basis.PROFILE.parent)
    assert basis.predecessor_view(actual, previous=installed) == installed
    actual['execution/cash_corrections.py'] = '0' * 64
    assert basis.predecessor_view(actual, previous=installed) is actual


def test_dashboard_handoff_preserves_installed_source_and_all_earlier_maps():
    revision = '35761cbbb2232c0fcb51cd37c97cdf5c3851ca17'
    assert basis.OPEN_CLOSE_DASHBOARD_PREDECESSOR_REVISION == revision
    profile = basis._profile()
    assert profile['authority_effect'] == 'NONE'
    history = dict(profile['retained_predecessors'])
    history.pop(basis.OPENING_OUTCOMES_PREDECESSOR_REVISION)
    history.pop(basis.NATIVE_FEE_POSTING_DELAY_PREDECESSOR_REVISION)
    history.pop(basis.ROLLING_GO_INDEX_PREDECESSOR_REVISION)
    installed = history.pop(revision)['files']
    assert len(installed) == 475
    assert admission.source_closure(installed) == '5d85fbb62053aca94a44a3db971876efd826b6ed8027b98da14826e3b3f8100c'
    assert len(history) == 49
    payload = json.dumps(history, sort_keys=True, separators=(',', ':')).encode()
    assert hashlib.sha256(payload).hexdigest() == 'c278edcc5e1a6a220d281b9bf18c7d531f3d336a3977b1df847625270f38791a'

    actual = admission._source_files(basis.PROFILE.parent)
    assert basis.predecessor_view(actual, previous=installed) == installed
    actual['panel/readiness_handoff.py'] = '0' * 64
    assert basis.predecessor_view(actual, previous=installed) is actual


def test_rolling_index_proof_preserves_the_certified_source_and_all_earlier_maps():
    revision = '5ebacfb46d8fbc15e3b698b11bb610d951565d92'
    assert basis.ROLLING_GO_INDEX_PREDECESSOR_REVISION == revision
    profile = basis._profile()
    assert profile['authority_effect'] == 'NONE'
    history = dict(profile['retained_predecessors'])
    history.pop(basis.OPENING_OUTCOMES_PREDECESSOR_REVISION)
    history.pop(basis.NATIVE_FEE_POSTING_DELAY_PREDECESSOR_REVISION)
    installed = history.pop(revision)['files']
    assert len(installed) == 475
    assert admission.source_closure(installed) == 'a2b9ae096cb8bb52ea61491fc793cdabddf3d0a52b4b2a6ce42222b0b0d31e72'
    assert len(history) == 50
    payload = json.dumps(history, sort_keys=True, separators=(',', ':')).encode()
    assert hashlib.sha256(payload).hexdigest() == 'ca71c7291652f634cda53c7cf5bfd64a8c2ed9d0b8068dc867ffa37938889156'

    actual = admission._source_files(basis.PROFILE.parent)
    assert basis.predecessor_view(actual, previous=installed) == installed
    actual['feed/rolling_go_health.py'] = '0' * 64
    assert basis.predecessor_view(actual, previous=installed) is actual


def test_native_fee_posting_delay_retains_certified_source_and_all_earlier_maps():
    revision = 'e9ef8b51259898a84f4b2c21f8e601e9ed9a5922'
    assert basis.NATIVE_FEE_POSTING_DELAY_PREDECESSOR_REVISION == revision
    profile = basis._profile()
    assert profile['authority_effect'] == 'NONE'
    history = dict(profile['retained_predecessors'])
    history.pop(basis.OPENING_OUTCOMES_PREDECESSOR_REVISION)
    certified = history.pop(revision)['files']
    assert len(certified) == 475
    assert admission.source_closure(certified) == (
        '9b8784f7b1a97757c100fc3ece7fee0969712b8d5e4badd1bf726ff1cf345f28')
    assert len(history) == 51
    payload = json.dumps(history, sort_keys=True, separators=(',', ':')).encode()
    assert hashlib.sha256(payload).hexdigest() == (
        '2bed28aba37f1f347d47ddb2023ebfee9d1bb57f6bd09da9f43fe0e174b46795')

    actual = admission._source_files(basis.PROFILE.parent)
    assert basis.predecessor_view(actual, previous=certified) == certified
    actual['paper/cash.py'] = '0' * 64
    assert basis.predecessor_view(actual, previous=certified) is actual


def test_opening_outcomes_preserves_signed_predecessor_and_earlier_source_maps():
    revision = 'aed1a26c335281169c6d8067b1ce2e7de1632053'
    assert basis.OPENING_OUTCOMES_PREDECESSOR_REVISION == revision
    profile = basis._profile()
    assert profile['authority_effect'] == 'NONE'
    history = dict(profile['retained_predecessors'])
    installed = history.pop(revision)['files']
    assert len(installed) == 476
    assert admission.source_closure(installed) == (
        'a765d57aaee204f0e5b734fd6d34ef8092ce4c4c4d0ca29b7f9fdf9b158551d2')
    assert len(history) == 52
    assert hashlib.sha256(json.dumps(history, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == (
        '82eda6e7d726f9675a1648a03b7d534fe3e6a28141690258c03e48036849c257')
    actual = admission._source_files(basis.PROFILE.parent)
    assert basis.predecessor_view(actual, previous=installed) == installed
    actual['automation/outbox.py'] = '0' * 64
    assert basis.predecessor_view(actual, previous=installed) is actual
