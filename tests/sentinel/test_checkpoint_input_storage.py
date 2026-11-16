from base64 import b64decode, b64encode
import bz2
import hashlib
import inspect

import pytest

from sentinel import checkpoint_input_storage as storage


def test_canonical_input_round_trips_without_numeric_or_unicode_changes():
    value = {'price': [-0.0, 12.42, 1e-16], 'nested': {'issuer': 'Société'}}
    archive = storage.encode(value)
    assert storage.decode(archive, expected_sha256=archive['sha256']) == value


def test_payload_limit_controls_the_actual_decompression(monkeypatch):
    archive = storage.encode({'value': 'a' * 1024})
    monkeypatch.setattr(storage, 'MAX_PAYLOAD_BYTES', 128)
    with pytest.raises(ValueError, match='stream changed'):
        storage.decode(archive, expected_sha256=archive['sha256'])
    with pytest.raises(ValueError, match='uncompressed archive limit'):
        storage.encode({'value': 'a' * 1024})


def test_compressed_archive_limit_applies_to_both_ends(monkeypatch):
    archive = storage.encode({'value': 'exact'})
    monkeypatch.setattr(storage, 'MAX_COMPRESSED_BYTES', 8)
    with pytest.raises(ValueError, match='compressed archive size changed'):
        storage.decode(archive, expected_sha256=archive['sha256'])
    with pytest.raises(ValueError, match='compressed archive limit'):
        storage.encode({'value': 'exact'})


def test_trailing_stream_is_rejected_and_guard_is_observable():
    archive = storage.encode({'value': 'exact'})
    archive['content'] = b64encode(b64decode(archive['content']) + bz2.compress(b'extra')).decode()
    with pytest.raises(ValueError, match='stream changed'):
        storage.decode(archive, expected_sha256=archive['sha256'])
    namespace = vars(storage).copy()
    code = inspect.getsource(storage.decode)
    assert 'or stream.unused_data' in code
    exec(code.replace('or stream.unused_data', ''), namespace)
    assert namespace['decode'](archive, expected_sha256=archive['sha256']) == {'value': 'exact'}


def test_truncated_stream_is_rejected_before_accepting_complete_output():
    archive = storage.encode({'value': 'exact'})
    archive['content'] = b64encode(b64decode(archive['content'])[:-1]).decode()
    with pytest.raises(ValueError, match='stream changed'):
        storage.decode(archive, expected_sha256=archive['sha256'])
    namespace = vars(storage).copy()
    code = inspect.getsource(storage.decode)
    assert 'or not stream.eof' in code
    exec(code.replace('or not stream.eof', ''), namespace)
    assert namespace['decode'](archive, expected_sha256=archive['sha256']) == {'value': 'exact'}


def test_noncanonical_json_refuses_even_with_matching_archive_digest():
    raw = b'{"value":0,"value":1}'
    sha = hashlib.sha256(raw).hexdigest()
    archive = {'schema': storage.SCHEMA, 'sha256': sha, 'content': b64encode(bz2.compress(raw)).decode()}
    with pytest.raises(ValueError, match='JSON changed'):
        storage.decode(archive, expected_sha256=sha)
