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


@pytest.mark.parametrize('option', ['-f', '--file-system'])
def test_explicit_filesystem_mode_performs_real_syncfs_on_the_named_filesystem(tmp_path, monkeypatch, option):
    actual = []
    syncfs = adapter._syncfs
    def observed(descriptor):
        value = os.fstat(descriptor)
        actual.append((value.st_dev, value.st_ino))
        syncfs(descriptor)
    monkeypatch.setattr(adapter, '_syncfs', observed)
    monkeypatch.setattr(os, 'fsync', lambda _: pytest.fail('filesystem sync was weakened to fsync'))
    monkeypatch.setattr(os, 'sync', lambda: pytest.fail('global sync is forbidden'))
    assert adapter.main([option, str(tmp_path)]) == 0
    assert actual == [(tmp_path.stat().st_dev, tmp_path.stat().st_ino)]


def test_file_and_filesystem_modes_are_distinct(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(adapter, '_syncfs', lambda _: calls.append('filesystem'))
    monkeypatch.setattr(os, 'fsync', lambda _: calls.append('file'))
    assert adapter.main(['-f', str(tmp_path)]) == 0
    assert adapter.main(['--', str(tmp_path)]) == 0
    assert calls == ['filesystem', 'file']


def test_weakened_filesystem_mode_has_an_executed_falsifier(tmp_path, monkeypatch):
    source = inspect.getsource(adapter.synchronize)
    assert source.count('if filesystem:') == 1
    namespace = dict(adapter.__dict__)
    exec(compile(source.replace('if filesystem:', 'if False:'), '<weakened-syncfs>', 'exec'), namespace)
    monkeypatch.setattr(adapter, 'synchronize', namespace['synchronize'])
    with pytest.raises(AssertionError):
        test_file_and_filesystem_modes_are_distinct(tmp_path, monkeypatch)


def test_filesystem_sync_failure_closes_descriptor_and_never_falls_back(tmp_path, monkeypatch):
    opened = []
    def failed(descriptor):
        opened.append(descriptor)
        raise OSError(errno.EIO, 'injected private filesystem failure')
    monkeypatch.setattr(adapter, '_syncfs', failed)
    monkeypatch.setattr(os, 'fsync', lambda _: pytest.fail('syncfs failure fell back to fsync'))
    assert adapter.main(['-f', str(tmp_path)]) == 1
    with pytest.raises(OSError) as closed:
        os.fstat(opened[0])
    assert closed.value.errno == errno.EBADF


@pytest.mark.parametrize('args', [[], ['-f'], ['--file-system'], ['-d'], ['--unknown']])
def test_missing_operands_or_unknown_modes_never_fall_back_to_global_sync(args, monkeypatch):
    monkeypatch.setattr(os, 'sync', lambda: pytest.fail('global sync is forbidden'))
    assert adapter.main(args) == 1


def _archive_with_broken_ambient(tmp_path, monkeypatch):
    poison = tmp_path / 'broken-ambient'
    poison.mkdir()
    invoked = tmp_path / 'ambient-sync-invoked'
    command = poison / 'sync'
    command.write_text('#!/bin/sh\nprintf invoked > ' + shlex.quote(str(invoked)) + '\nexit 79\n')
    command.chmod(0o700)
    ambient = str(poison) + os.pathsep + os.environ['PATH']
    monkeypatch.setenv('PATH', ambient)
    lab = Archive(tmp_path / 'archive-case')
    selected = Path(shutil.which('sync', path=lab.env['PATH']))
    assert selected == tmp_path / 'archive-case/native-fsync/sync'
    assert os.environ['PATH'] == ambient  # No suite-wide or host PATH mutation.
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


def test_archive_adapter_does_not_intercept_other_backup_lifecycle_commands(tmp_path, monkeypatch):
    ambient = os.environ['PATH']
    selected = shutil.which('sync', path=ambient)
    assert tmp_path not in Path(selected).resolve().parents
    lab = Archive(tmp_path / 'archive-case')
    assert lab.env['PATH'] != ambient
    assert shutil.which('sync', path=lab.env['PATH']) != selected
    assert os.environ['PATH'] == ambient
    assert shutil.which('sync') == selected


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
