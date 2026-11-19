"""The public install phase exists only while its real host owner holds the lock."""
import fcntl
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

import sentinel_deploy_progress as progress
from sentinel import install_progress as panel


@pytest.fixture
def record(tmp_path, monkeypatch):
    path = tmp_path / 'operator-progress' / 'current'
    monkeypatch.setattr(panel, '_FILE', path)
    return path


def test_host_and_panel_observe_only_the_active_owner(tmp_path, record):
    assert panel.current() is None
    previous = os.umask(0o077)
    try:
        with progress.reporting(tmp_path, 'install'):
            assert stat.S_IMODE(record.parent.stat().st_mode) == 0o711
            assert stat.S_IMODE(record.stat().st_mode) == 0o644
            assert panel.current() == 'Software installation · checking the release'
            progress.phase('installation: create dormant exact financial services')
            assert panel.current() == 'Software installation · creating fenced services'
            inode = record.stat().st_ino
        assert panel.current() is None
        with pytest.raises(InterruptedError), progress.reporting(tmp_path, 'activate'):
            assert record.stat().st_ino != inode
            parser = progress.GoStages()
            parser.consume('[RUN]  verify database backup health (dea')
            assert panel.current().endswith('checking the release')
            parser.consume('dline 300.0s)\n')
            assert panel.current() == 'Activation · checking backup health'
            parser.consume('private' * 300 + '=== PHASE C - CERTIFIED FINANCIAL PREPARATION ===\n')
            assert panel.current().endswith('checking backup health')
            parser.consume('=== PHASE D2 - MARKET DATA READINESS ===\r\n')
            assert panel.current() == 'Activation · checking market data'
            parser.consume('\x1b[36m\x1b[1m\n=== PHASE D1 - WEALTH CORE PARITY ===\x1b[0m\n')
            assert panel.current() == 'Activation · verifying strategy parity'
            parser.consume('\x1b[36m[RUN]  verify database backup health (deadline 23s)\x1b[0m\n')
            assert panel.current() == 'Activation · checking backup health'
            raise InterruptedError
        assert panel.current() is None
    finally:
        os.umask(previous)


def test_abrupt_owner_exit_releases_observation(tmp_path, record):
    process = subprocess.run([sys.executable, '-c',
        'import os, sys; import sentinel_deploy_progress as p\n'
        'with p.reporting(sys.argv[1], "activate"):\n'
        ' p.publish("validation"); os._exit(7)', str(tmp_path)],
        env=dict(os.environ, PYTHONPATH=str(Path(progress.__file__).parent)))
    assert process.returncode == 7 and record.is_file()
    assert panel.current() is None


def test_stream_attributes_only_allowlisted_go_stdout(tmp_path, record):
    from sentinel_autonomous_deploy import Runner
    script = 'scripts/sentinel-go-validate.sh'
    (tmp_path/'scripts').mkdir()
    (tmp_path/script).write_text("echo '=== PHASE D2 - MARKET DATA READINESS ==='\n"
                                 "echo '=== PHASE D3 - DATABASE FINANCIAL HEALTH ===' >&2\n")
    runner = Runner(os.environ, tmp_path/'commands.log')
    with progress.reporting(tmp_path, 'activate'):
        for command in (['bash', './' + script], ['bash', script]):
            output = runner.run(command, cwd=tmp_path, capture=True, stream=True, timeout=5)
            assert 'MARKET DATA' in output.stdout and 'DATABASE' in output.stderr
            expected = 'checking market data' if command[1] == script else 'checking the release'
            assert panel.current() == 'Activation · ' + expected


@pytest.mark.parametrize('raw', [b'activate ready'.ljust(64), b'other preflight'.ljust(64),
                                 b'activate preflight', b'activate preflight'.ljust(65), b'\xff'*64])
def test_unrecognized_even_under_real_exclusive_lock(record, raw):
    record.parent.mkdir()
    with record.open('wb') as stream:
        stream.write(raw)
        stream.flush()
        fcntl.flock(stream, fcntl.LOCK_EX)
        assert panel.current() is None


def test_symlinks_and_fifo_cannot_supply_public_progress(tmp_path, record):
    target = tmp_path / 'private'
    target.mkdir()
    record.parent.symlink_to(target, target_is_directory=True)
    with progress.reporting(tmp_path, 'install'):
        assert not record.exists() and panel.current() is None
    record.parent.unlink()
    record.parent.mkdir()
    record.symlink_to(target)
    assert panel.current() is None
    record.unlink()
    os.mkfifo(record)
    assert panel.current() is None
