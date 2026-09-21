"""Independent canonical bytes, mutation sensitivity and allocation budget."""
import hashlib
import json
import subprocess
import sys
import tracemalloc

import pytest

from sentinel.core.session import SessionState
from tests.sentinel.test_production_state import _fresh


def wide_state(size=1000, length=260):
    _, state = _fresh()
    state.feed = {'history_sessions': 260, 'session_index': length - 1,
                  'seen_sessions': {}, 'series': {}}
    for index in range(size):
        sid = str(index)
        state.feed['series'][sid] = dict(security_id=sid, ticker='S' + sid, issuer_id=sid,
            split_factor=1., sessions=[f'S{i:04}' for i in range(length)],
            session_indices=list(range(length)), signal_closes=[1.25]*length,
            raw_closes=[2.5]*length, volumes=[1000000.]*length)
    return state


def independent_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode('ascii')).hexdigest()


def _assert_hash_allocation():
    state = wide_state()
    expected = independent_hash(state.to_dict())
    tracemalloc.start()
    try:
        actual = state.state_hash
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert actual == expected
    assert peak < 4 * 1024 * 1024, peak
    state.feed['series']['999']['signal_closes'][-1] = 2.25
    assert state.state_hash != expected
    assert state.state_hash == independent_hash(state.to_dict())


def test_state_hash_has_no_universe_sized_feed_array_copy():
    # tracemalloc measures the entire interpreter, including other tests' live
    # threads and tracing state. Keep the exact same budget in a fresh process.
    result = subprocess.run([sys.executable, '-c',
        'from tests.sentinel.test_state_hash_allocations import _assert_hash_allocation; '
        '_assert_hash_allocation()'], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('length', [260, 300])
def test_private_canonical_view_preserves_trimming_and_public_ownership(length):
    state = wide_state(size=2, length=length)
    detached = state.to_dict()
    borrowed = state._canonical_mapping(_copy_feed=False)
    assert borrowed == detached
    assert len(borrowed['feed']['series']['1']['sessions']) == 260
    ordinary = SessionState.from_dict(detached)
    owned = SessionState.from_dict(detached, _copy_feed=False)
    assert ordinary.to_dict() == owned.to_dict() == detached
    detached['feed']['series']['1']['signal_closes'][-1] = 44.0
    assert state.feed['series']['1']['signal_closes'][-1] == 1.25
    assert ordinary.feed['series']['1']['signal_closes'][-1] == 1.25
    # The private status view is deliberately owned by its decoded mapping.
    assert owned.feed['series']['1']['signal_closes'][-1] == 44.0
    exported = owned.to_dict()
    exported['feed']['series']['1']['signal_closes'][-1] = 99.0
    assert owned.feed['series']['1']['signal_closes'][-1] == 44.0
