"""Phase-record parsing and durable publication with isolated storage faults."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT', Path(__file__).resolve().parents[2]))
spec = importlib.util.spec_from_file_location('phase_record_fault_contract', ROOT / 'scripts/sentinel_phase_records.py')
records = importlib.util.module_from_spec(spec)
spec.loader.exec_module(records)


@pytest.mark.parametrize('raw', ['null', '[]', 'true', '1', '"text"', '{',
    '{"identity":1,"identity":2}', '{"nested":{"x":1,"x":2}}',
    '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e999}'])
def test_phase_reader_rejects_ambiguous_or_malformed_json(tmp_path, raw):
    path = tmp_path / 'record.json'
    path.write_text(raw)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        records.read_document(path)
    assert path.read_bytes() == original


def test_phase_reader_enforces_utf8_and_returns_finite_values(tmp_path):
    path = tmp_path / 'record.json'
    path.write_bytes(b'\xff')
    with pytest.raises(UnicodeDecodeError):
        records.read_document(path)
    path.write_text('{"ratio":1.25,"nested":{"count":2},"text":"\u00e9"}', encoding='utf-8')
    assert records.read_document(path) == {'ratio': 1.25, 'nested': {'count': 2}, 'text': '\u00e9'}


@pytest.mark.parametrize('value', [None, [], False, 1, {'ratio': float('nan')}, {'ratio': float('inf')}])
def test_writer_refuses_invalid_values_before_any_publication(tmp_path, value):
    path = tmp_path / 'record.json'
    with pytest.raises(ValueError):
        records.write_document(path, value)
    assert not path.exists()
    assert list(tmp_path.glob('.record.json*')) == []


def test_mutable_status_replaces_atomically_and_completion_is_immutable(tmp_path):
    directory = tmp_path / 'private-records'
    directory.mkdir()
    mutable = directory / 'status.json'
    records.write_document(mutable, {'status': 'PENDING'})
    records.write_document(mutable, {'status': 'COMPLETE'})
    assert records.read_document(mutable) == {'status': 'COMPLETE'}
    immutable = directory / 'receipt.json'
    records.publish_immutable(immutable, {'identity': 'original'})
    original = immutable.read_bytes()
    with pytest.raises(FileExistsError):
        records.publish_immutable(immutable, {'identity': 'replacement'})
    assert immutable.read_bytes() == original
    assert sorted(p.name for p in directory.iterdir()) == ['receipt.json', 'status.json']


@pytest.mark.parametrize('stage', ['file-fsync', 'replace', 'link', 'directory-open', 'directory-fsync'])
def test_storage_failure_cleans_temporary_and_never_reports_success(tmp_path, monkeypatch, stage):
    directory = tmp_path / 'private-records'
    directory.mkdir()
    path = directory / 'record.json'
    original = b'{"identity":"prior"}\n'
    immutable = stage == 'link'
    if not immutable:
        path.write_bytes(original)
    fault = OSError('synthetic durable storage fault')
    def fail(*_a, **_k): raise fault
    if stage == 'file-fsync': monkeypatch.setattr(records.os, 'fsync', fail)
    elif stage == 'replace': monkeypatch.setattr(records.os, 'replace', fail)
    elif stage == 'link': monkeypatch.setattr(records.os, 'link', fail)
    elif stage == 'directory-open':
        open_file = records.os.open
        def open_or_fail(target, *args, **kwargs):
            if Path(target) == directory: raise fault
            return open_file(target, *args, **kwargs)
        monkeypatch.setattr(records.os, 'open', open_or_fail)
    else:
        fsync = records.os.fsync
        synced = []
        def fsync_or_fail(fd):
            synced.append(fd)
            if len(synced) == 2: raise fault
            return fsync(fd)
        monkeypatch.setattr(records.os, 'fsync', fsync_or_fail)
    with pytest.raises(OSError) as caught:
        records.write_document(path, {'identity': 'new'}, immutable=immutable)
    assert caught.value is fault
    assert list(directory.glob('.record.json*')) == []
    if immutable: assert not path.exists()
    elif stage in {'file-fsync', 'replace'}: assert path.read_bytes() == original
    else: assert records.read_document(path) == {'identity': 'new'}


def test_immutable_link_cleanup_tolerates_already_removed_temporary(tmp_path, monkeypatch):
    directory = tmp_path / 'private-records'
    directory.mkdir()
    path = directory / 'receipt.json'
    link = records.os.link
    def publish_then_remove(source, target):
        link(source, target)
        Path(source).unlink()
    monkeypatch.setattr(records.os, 'link', publish_then_remove)
    records.publish_immutable(path, {'identity': 'original'})
    assert records.read_document(path) == {'identity': 'original'}
    assert list(directory.iterdir()) == [path]
