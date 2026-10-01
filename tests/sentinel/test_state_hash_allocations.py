"""Independent canonical bytes, mutation sensitivity and allocation budget."""
import gc
import hashlib
import json
import subprocess
import sys
import tracemalloc
import weakref

import pytest

from sentinel.core import session as session_module
from sentinel.core.session import SessionState
from tests.sentinel.test_production_state import _fresh


@pytest.mark.parametrize('operation', ['hash', 'validate', 'close'])
def test_canonical_encoder_lifetime_does_not_depend_on_cyclic_gc(monkeypatch, operation):
    value = {'scalars': {'k' + str(i): i / 3 for i in range(100)},
             'nested': [None, True, -0.0, 'unicode: \u03bb', {'a': [1, 2]}]}
    expected = independent_hash(value)
    original = json.JSONEncoder
    references = []

    class TrackedEncoder(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            references.append(weakref.ref(self))

    monkeypatch.setattr(json, 'JSONEncoder', TrackedEncoder)
    enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(20):
            if operation == 'hash':
                assert session_module._hash(value) == expected
            elif operation == 'validate':
                session_module._validate_json(value)
            else:
                stream = session_module._canonical_chunks(value)
                # Reach an encoded scalar before closing the active traversal.
                for chunk in stream:
                    if chunk == 'null':
                        break
                stream.close()
                del stream
            assert references and all(reference() is None for reference in references)
    finally:
        if enabled:
            gc.enable()


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


def test_hash_still_rejects_non_json_after_single_pass_validation():
    _, state = _fresh()
    state.shadow_nav_history = [float('nan')]
    with pytest.raises(ValueError):
        _ = state.state_hash


@pytest.mark.parametrize('length', [0, 1, 260, 300, 301])
def test_bounded_record_native_encoding_preserves_exact_bytes(length):
    record = {'z': [1.25, -0.0, '\u03bb', None, False] * length,
              'a': list(range(length)), 'escaped': '\n"\\'}
    assert session_module._hash(record) == independent_hash(record)
    if length:
        record['a'][-1] = float('inf')
        with pytest.raises(ValueError):
            session_module._hash(record)


def test_bounded_record_encoding_does_not_admit_oversized_strings(monkeypatch):
    original = json.JSONEncoder.encode
    record = {'a': ['x' * 1000000]}
    expected = independent_hash(record)
    def encode(self, value):
        assert value is not record, 'unbounded record reached native encoder'
        return original(self, value)
    monkeypatch.setattr(json.JSONEncoder, 'encode', encode)
    assert session_module._hash(record) == expected


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
