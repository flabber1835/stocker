"""Capacity observer failures must refuse before any storage allocation."""
import base64
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import sentinel_storage_capacity as capacity


@pytest.mark.parametrize('code', [0, 1])
def test_observer_uses_its_existing_bounded_process_contract(monkeypatch, code):
    calls = []

    def bounded(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=code, stdout='  4096\n')

    monkeypatch.setattr(capacity, 'run_bounded', bounded)
    if code:
        with pytest.raises(capacity.Refused, match='capacity observation failed: observer'):
            capacity.run(['observer', 'disk-metadata'])
    else:
        assert capacity.run(['observer', 'disk-metadata']) == '4096'
    assert calls == [(['observer', 'disk-metadata'],
                      {'timeout': 30, 'private_group': False})]


@pytest.mark.parametrize('free', [None, [], {'C:': True}, {'C:': -1}, {'C:': '999'}])
def test_windows_observation_requires_integer_free_bytes(monkeypatch, free):
    monkeypatch.setenv('WSL_DISTRO_NAME', 'Ubuntu')
    monkeypatch.setattr(capacity.shutil, 'which', lambda _: '/resolved/powershell.exe')
    calls = []

    def runner(argv):
        calls.append(argv)
        script = base64.b64decode(argv[-1]).decode('utf-16le')
        assert "$distro = 'Ubuntu'" in script
        return json.dumps({'distro_path': r'C:\Ubuntu',
                          'docker_path': r'C:\Docker\disk.vhdx', 'free': free})

    with pytest.raises(capacity.Refused, match='physical free-space observation is invalid'):
        capacity.windows_storage(runner)
    assert calls[0][0] == '/resolved/powershell.exe'
    assert calls[0][1:4] == ['-NoProfile', '-NonInteractive', '-EncodedCommand']


def test_wsl_fallback_executable_is_used_only_for_validated_distribution(monkeypatch):
    monkeypatch.setenv('WSL_DISTRO_NAME', 'Ubuntu')
    monkeypatch.setattr(capacity.shutil, 'which', lambda _: None)
    calls = []

    def runner(argv):
        calls.append(argv)
        return json.dumps({'distro_path': r'C:\Ubuntu',
                          'docker_path': r'D:\Docker\disk.vhdx',
                          'free': {'C:': 32 * capacity.GIB, 'D:': 64 * capacity.GIB}})

    result = capacity.windows_storage(runner)
    assert result['free']['D:'] == 64 * capacity.GIB
    assert calls[0][0] == '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'


@pytest.mark.parametrize('value', ['1', '9223372036854775807'])
def test_copy_size_accepts_only_positive_bounded_integer_bytes(value):
    assert capacity.size_bytes(value) == int(value)


@pytest.mark.parametrize('value', ['', '1' * 21, ' 1', '1.0'])
def test_copy_size_never_guesses_a_malformed_observation(value):
    with pytest.raises(capacity.Refused, match='invalid physical copy size'):
        capacity.size_bytes(value)


@pytest.mark.parametrize('name', [None, '', '../base-20261009T010000Z', 'base-wrong'])
def test_invalid_restore_identity_never_queries_the_database(name):
    with pytest.raises(capacity.Refused, match='invalid restore base identity'):
        capacity.check('restore', '/backup', name,
                       runner=lambda _: pytest.fail('bad identity reached observer'))


@pytest.mark.parametrize('info', ['relative|Linux', '/var/lib/docker', '/root|Linux|extra'])
def test_unresolved_daemon_metadata_cannot_choose_a_restore_disk(monkeypatch, info):
    calls = []
    monkeypatch.setattr(capacity, 'destinations',
                        lambda *a, **k: pytest.fail('unknown daemon reached disk observer'))

    def runner(argv):
        calls.append(argv)
        return info if argv[:2] == ['docker', 'info'] else '4096'

    with pytest.raises(capacity.Refused, match='Docker backing filesystem unavailable'):
        capacity.check('base', '/backup', runner=runner)
    assert len(calls) == 2


def test_linux_paths_use_actual_filesystem_identity_and_capacity(tmp_path, monkeypatch):
    backup, docker = tmp_path / 'backup', tmp_path / 'daemon'
    backup.mkdir()
    docker.mkdir()
    real_read = Path.read_text
    monkeypatch.setattr(Path, 'read_text', lambda p, *a, **k:
        'ordinary-linux' if str(p) == '/proc/sys/kernel/osrelease' else real_read(p, *a, **k))
    probes = []

    def usage(path):
        probes.append(path)
        return SimpleNamespace(free=64 * capacity.GIB)

    monkeypatch.setattr(capacity.shutil, 'disk_usage', usage)
    allocation, restore, free = capacity.destinations(backup, docker, 'Linux')
    assert allocation == str(backup.stat().st_dev)
    assert restore == str(docker.stat().st_dev)
    assert free == {allocation: 64 * capacity.GIB, restore: 64 * capacity.GIB}
    assert probes == [backup.resolve(), docker.resolve()]
    with pytest.raises(FileNotFoundError):
        capacity.destinations(backup, tmp_path / 'remote-daemon', 'Linux')
    assert len(probes) == 2


def test_wsl_native_daemon_uses_distro_drive_instead_of_docker_desktop_disk(monkeypatch):
    real_read, real_exists = Path.read_text, Path.exists
    monkeypatch.setattr(Path, 'read_text', lambda p, *a, **k:
        'microsoft-standard-WSL2' if str(p) == '/proc/sys/kernel/osrelease'
        else real_read(p, *a, **k))
    monkeypatch.setattr(Path, 'exists', lambda p:
        False if str(p) == '/.dockerenv' else real_exists(p))
    monkeypatch.setattr(Path, 'stat', lambda p, **k: SimpleNamespace(st_dev=1))
    monkeypatch.setattr(capacity, 'windows_storage', lambda runner:
        {'distro_path': r'C:\Ubuntu', 'docker_path': r'D:\Docker\disk.vhdx',
         'free': {'C:': 64 * capacity.GIB, 'D:': 128 * capacity.GIB}})
    monkeypatch.setattr(capacity.shutil, 'disk_usage',
                        lambda _: pytest.fail('WSL virtual capacity was used'))
    allocation, restore, free = capacity.destinations('/home/operator/backup',
                                                      '/var/lib/docker', 'Linux')
    assert (allocation, restore) == ('C:', 'C:')
    assert free['C:'] == 64 * capacity.GIB


@pytest.mark.parametrize('error', [None, capacity.Refused('no physical proof'),
                                  OSError('backing path disappeared'),
                                  ValueError('bad observer JSON'),
                                  KeyError('free'), TypeError('invalid free')])
def test_cli_reports_admission_or_typed_refusal_without_allocating(monkeypatch, capsys, error):
    calls = []

    def check(*args):
        calls.append(args)
        if error is not None:
            raise error
        return {'storage_capacity_ready': True, 'required_bytes': {'C:': 1024}}

    monkeypatch.setattr(capacity, 'check', check)
    result = capacity.main(['base', '--backup-root', '/private/backup'])
    output = capsys.readouterr()
    assert calls == [('base', '/private/backup', None)]
    if error is None:
        assert result == 0 and output.err == ''
        assert json.loads(output.out)['required_bytes'] == {'C:': 1024}
    else:
        assert result == 4 and output.out == ''
        assert output.err.startswith('SENTINEL_STORAGE_REASON=PHYSICAL_CAPACITY_UNAVAILABLE\nREFUSED: ')


def test_cli_entrypoint_rejects_malformed_restore_identity_before_external_commands(monkeypatch, capsys):
    source = Path(capacity.__file__)
    monkeypatch.setattr(sys, 'argv', [str(source), 'restore', '--backup-root', '/unused',
                                    '--base-name', 'not-a-base'])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(source), run_name='__main__')
    output = capsys.readouterr()
    assert result.value.code == 4 and output.out == ''
    assert 'invalid restore base identity' in output.err
