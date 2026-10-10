"""Recovery can publish slow verified work without renewing its whole deadline."""
import json
import sys
from types import SimpleNamespace

import pytest

from lab import ROOT
from test_shell_lifecycle import ShellLab

sys.path.insert(0, str(ROOT / 'scripts'))
import sentinel_backup_deadlines as budgets
import sentinel_install_backup as install
import sentinel_maintenance_process as process


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setenv(install.LOCK_ROOT_ENV, '/backups')
    monkeypatch.setattr(install, 'lock_is_held', lambda: True)
    return '/backups/base/base-20261010T194840Z'


@pytest.mark.parametrize('mode', ['full', 'physical'])
def test_slow_copy_then_publication_fits_host_budget(owner, monkeypatch, mode):
    # Scale seconds, preserving the real 600/900-second relationship. The
    # verified child still needs time to publish its exact path afterward.
    monkeypatch.setattr(install, 'BASE_COMMAND_SECONDS', install.BASE_COMMAND_SECONDS * .004)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if 'base-backup' in argv[1]:
            code = ("import time,sys; time.sleep(2.1); "
                    "print('copy verified',file=sys.stderr,flush=True); "
                    "time.sleep(.5); print(%r,flush=True)" % ('verified_base_backup:' + owner))
        else:
            code = "print('phase verified')"
        return process.run_bounded([sys.executable, '-c', code], **kwargs)

    assert install.milestone(mode, runner=run) == owner
    assert len(calls) == 3
    assert ('--physical-only' in calls[-1]) == (mode == 'physical')


def test_every_phase_receives_only_remaining_whole_budget(owner, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(install.time, 'monotonic', lambda: clock[0])
    calls = []

    def run(argv, **kwargs):
        calls.append(kwargs['timeout'])
        clock[0] += [800, 500, 100][len(calls) - 1]
        return SimpleNamespace(returncode=0, stderr='', stdout='verified_base_backup:' + owner)

    assert install.milestone('full', runner=run) == owner
    assert calls == [900, 600, 2100]

    clock[0], calls[:] = 0, []
    monkeypatch.setattr(install, 'INVOCATION_SECONDS', 1400)
    with pytest.raises(RuntimeError, match='deadline exhausted'):
        install.milestone('full', runner=run)
    assert calls == [900, 600, 100]


@pytest.mark.parametrize('expire_at', [1, 3])
def test_exhaustion_cannot_publish_receipt_or_start_later_phase(owner, monkeypatch, capsys, expire_at):
    clock = [0.0]
    monkeypatch.setattr(install.time, 'monotonic', lambda: clock[0])
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if len(calls) == expire_at:
            clock[0] = budgets.INVOCATION_SECONDS
        return SimpleNamespace(returncode=0, stderr='', stdout='verified_base_backup:' + owner)

    with pytest.raises(RuntimeError, match='deadline exhausted'):
        install.milestone('full', runner=run)
    assert len(calls) == expire_at
    assert 'verified_installation_backup:' not in capsys.readouterr().out


@pytest.mark.parametrize('close_pipes', [False, True])
def test_deadline_retains_both_streams_on_live_or_closed_pipes(close_pipes):
    code = ("import os,time; os.write(1,b'base-copy-progress\\n'); "
            "os.write(2,b'verification-progress\\n'); " +
            ("os.close(1); os.close(2); " if close_pipes else "") + "time.sleep(20)")
    result = process.run_bounded([sys.executable, '-c', code], timeout=.5)
    assert result.returncode == 124
    assert 'base-copy-progress' in result.stdout
    assert 'verification-progress' in result.stderr
    assert 'MAINTENANCE_DEADLINE_EXCEEDED' in result.stdout


def test_shell_restore_worker_lives_through_host_and_cleanup(tmp_path):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    base = lab.base / 'base-20260910T120000Z'
    result = lab.run('sentinel-restore-drill.sh', '--backup', str(base), '--physical-only')
    # This shell boundary executes the real copy/verification snippets, then
    # deliberately refuses simulated PostgreSQL startup. Physical recovery is
    # qualified by the separate actual-PostgreSQL harness.
    assert result.returncode == 79, result.stderr
    events = [json.loads(line) for line in (tmp_path / 'events.jsonl').read_text().splitlines()]
    start = next(row for row in events if row['stage'] == 'restore-copy')
    args = start['argv']
    worker_seconds = int(args[args.index('--kill-after=30s') + 1])
    assert worker_seconds >= budgets.RESTORE_COMMAND_SECONDS + 60
    assert worker_seconds <= budgets.INVOCATION_SECONDS
    assert 'physical_wal_replay_ready:true' not in result.stdout
    assert 'cleanup' in lab.events()
