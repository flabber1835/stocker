"""An exact source proof resolves both authenticated views once."""
import hashlib
import json

import pytest

from sentinel import runtime_admission, structural_refactor_source_basis as structural
from sentinel import transition_registry as registry, url_selected_source_basis as basis
from tests.support.source_history import pre_market_history


REVISION = 'd75e75a01051662e8948254ebbd562a15c8fac3e'
CLOSURE = '6e5c9464b95d991f8af2887e22cddaf3f3348b0c5deb0ade7dd960208f811772'


def test_exact_deployed_predecessor_and_retained_history():
    profile = basis._profile()
    assert basis.SIMPLIFICATION_PREDECESSOR_REVISION == REVISION
    assert profile['authority_effect'] == 'NONE'
    records = profile['retained_predecessors']
    predecessor = records[REVISION]['files']
    assert len(predecessor) == 473
    assert runtime_admission.source_closure(predecessor) == CLOSURE
    market = basis.MARKET_BUY_PREDECESSOR_REVISION
    close = basis.CLOSE_RELIABILITY_PREDECESSOR_REVISION
    previous = {**pre_market_history(profile), market: records[market], close: records[close]}
    assert len(previous) == 45
    payload = json.dumps(previous, sort_keys=True, separators=(',', ':')).encode()
    assert hashlib.sha256(payload).hexdigest() == (
        '6ef6fff831b1054f638acbd5bded4b02fa0e031e6747eae5d27b5d98e25a7fc6')


@pytest.mark.parametrize('exact', [True, False])
def test_one_url_profile_resolution_feeds_closure_and_file_comparison(monkeypatch, exact):
    profile = basis._profile()
    actual = runtime_admission._source_files(basis.PROFILE.parent)
    previous = (profile['retained_predecessors'][REVISION]['files'] if exact
                else {**profile['base_files'], 'foreign.py': 'a' * 64})
    calls = []
    historical = structural.historical_view

    def load():
        calls.append('url')
        return profile

    def normalize(value):
        calls.append('structural')
        return historical(value)

    monkeypatch.setattr(basis, '_profile', load)
    monkeypatch.setattr(structural, 'historical_view', normalize)
    comparison = registry.compare_sources(previous, actual)
    assert comparison.exact_predecessor is exact
    assert comparison.backed_base == profile['base_files']
    allowed = registry.load().comparison_allowed(previous, comparison, runtime_admission.ADDITIONS)
    assert allowed is exact
    assert calls == (['url'] if exact else ['url', 'structural'])


def test_unsealed_source_cannot_gain_either_historical_view():
    profile = basis._profile()
    previous = profile['retained_predecessors'][REVISION]['files']
    actual = runtime_admission._source_files(basis.PROFILE.parent)
    actual['transition_registry.py'] = 'f' * 64
    comparison = registry.compare_sources(previous, actual)
    assert not comparison.exact_predecessor
    assert comparison.backed_base is actual
    assert comparison.historical is actual
