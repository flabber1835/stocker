"""File/directory durability stays real without a host-wide sync dependency."""
import errno
import inspect
import os
from pathlib import Path
import shlex
import shutil

import pytest

import fsync_adapter as adapter
from lab import Archive

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='private POSIX file/directory fsync')


def test_real_fsync_targets_exact_file_and_directory(tmp_path, monkeypatch):
    path = tmp_path / 'payload'
    path.write_bytes(b'unchanged archive evidence')
    expected = [(value.stat().st_dev, value.stat().st_ino) for value in (path, tmp_path)]
    actual = []
    fsync = os.fsync
    def observed(descriptor):
        value = os.fstat(descriptor)
        actual.append((value.st_dev, value.st_ino))
        fsync(descriptor)
    monkeypatch.setattr(os, 'fsync', observed)
    monkeypatch.setattr(os, 'sync', lambda: pytest.fail('global sync is forbidden'))
    assert adapter.main([str(path), str(tmp_path)]) == 0
    assert actual == expected
    assert path.read_bytes() == b'unchanged archive evidence'


def test_real_fsync_error_and_missing_operand_never_become_success(tmp_path):
    fifo = tmp_path / 'private-fifo'
    os.mkfifo(fifo)
    assert adapter.main([str(fifo)]) == 1  # A pipe cannot provide fsync durability.
    assert adapter.main([str(tmp_path / 'absent')]) == 1
    assert adapter.main([]) == 1
    assert not (tmp_path / 'absent').exists()


def test_fsync_failure_closes_descriptor_and_preserves_bytes(tmp_path, monkeypatch):
    path = tmp_path / 'payload'
    path.write_bytes(b'preserve')
    opened = []
    def failed(descriptor):
        opened.append(descriptor)
        raise OSError(errno.EIO, 'injected private media failure')
    monkeypatch.setattr(os, 'fsync', failed)
    assert adapter.main([str(path)]) == 1
    assert len(opened) == 1
    with pytest.raises(OSError) as closed:
        os.fstat(opened[0])
    assert closed.value.errno == errno.EBADF
    assert path.read_bytes() == b'preserve'


def _archive_with_broken_ambient(tmp_path, monkeypatch):
    poison = tmp_path / 'broken-ambient'
    poison.mkdir()
    invoked = tmp_path / 'ambient-sync-invoked'
    command = poison / 'sync'
    command.write_text('#!/bin/sh\nprintf invoked > ' + shlex.quote(str(invoked)) + '\nexit 79\n')
    command.chmod(0o700)
    baseline = adapter.install(tmp_path / 'explicit-fsync', str(poison) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('PATH', baseline)
    lab = Archive(tmp_path / 'archive-case')
    selected = Path(shutil.which('sync', path=lab.env['PATH']))
    assert selected == tmp_path / 'explicit-fsync/sync'
    assert lab.run().returncode == 0
    lab.assert_exact()
    lab.fault('sync', 'temporary', 'fail-before')
    # A new archive name reaches the injected temporary-file durability fault.
    lab.name = '000000010000000000000004'
    assert lab.run().returncode != 0
    lab.clear()
    assert Path(shutil.which('sync', path=lab.env['PATH'])) == selected
    assert lab.run().returncode == 0
    assert not invoked.exists()


def test_archive_and_fault_recovery_never_fall_back_to_broken_ambient_sync(tmp_path, monkeypatch):
    _archive_with_broken_ambient(tmp_path, monkeypatch)


def test_removed_file_fsync_is_detected(tmp_path, monkeypatch):
    source = inspect.getsource(adapter.synchronize)
    assert source.count('os.fsync(descriptor)') == 1
    namespace = dict(adapter.__dict__)
    exec(compile(source.replace('os.fsync(descriptor)', 'None'), '<missing-fsync>', 'exec'), namespace)
    monkeypatch.setattr(adapter, 'synchronize', namespace['synchronize'])
    with pytest.raises(AssertionError):
        test_real_fsync_targets_exact_file_and_directory(tmp_path, monkeypatch)


def test_removed_private_adapter_selection_is_detected(tmp_path, monkeypatch):
    install = adapter.install
    def without_selection(directory, ambient_path):
        install(directory, ambient_path)
        return ambient_path
    monkeypatch.setattr(adapter, 'install', without_selection)
    with pytest.raises(AssertionError):
        _archive_with_broken_ambient(tmp_path, monkeypatch)
