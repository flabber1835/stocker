"""Descriptor ownership contracts on disposable Linux files; no deployment."""
import fcntl
import errno
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

# The CI image keeps inspection scripts under /work/repo, separately from
# /work/tests. Child processes must receive that same explicit source root.
SCRIPTS = Path(os.environ.get('SENTINEL_REPO_ROOT',
                             Path(__file__).resolve().parents[2])) / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import sentinel_backup_lock as backup
import sentinel_go_lock as go
import sentinel_lock_ownership as ownership


@pytest.fixture(params=['modern', 'legacy'], autouse=True)
def procfs_mode(monkeypatch, request):
    original = Path.open
    if request.param == 'legacy':
        def old_procfs(path, *args, **kwargs):
            if str(path).startswith('/proc/self/fdinfo/'):
                # Exact field availability reported by the Linux 3.10 NAS.
                return io.BytesIO(b'pos:\t0\nflags:\t02500002\n')
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'open', old_procfs)
    return request.param


@pytest.fixture(params=['backup', 'go'])
def verifier(tmp_path, monkeypatch, request):
    path = tmp_path / 'lock'
    path.touch()
    if request.param == 'backup':
        monkeypatch.setattr(backup, '_lock_path', lambda env: path)
        module, check = backup, backup.lock_is_held
    else:
        monkeypatch.setattr(go, 'LOCK', path)
        module, check = go, go.lifecycle_lock_is_held
    def verify(fd):
        return check({module.LOCK_HELD_ENV: '1', module.LOCK_FD_ENV: str(fd)})
    return path, verify


def test_exclusive_owner_and_duplicate_are_accepted_without_unlocking(verifier):
    path, verify = verifier
    with path.open('a+') as owner, path.open('a+') as contender:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        duplicate = os.dup(owner.fileno())
        try:
            assert verify(owner.fileno())
            assert verify(duplicate)
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(duplicate)


def test_independent_descriptor_is_not_the_owner(verifier):
    path, verify = verifier
    with path.open('a+') as owner, path.open('a+') as other:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not verify(other.fileno())
        assert verify(owner.fileno())
        with pytest.raises(BlockingIOError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_shared_lock_is_not_exclusive_and_is_not_upgraded(verifier):
    path, verify = verifier
    with path.open('a+') as owner, path.open('a+') as other:
        fcntl.flock(owner, fcntl.LOCK_SH | fcntl.LOCK_NB)
        assert not verify(owner.fileno())
        fcntl.flock(other, fcntl.LOCK_SH | fcntl.LOCK_NB)


def test_released_lock_is_not_reacquired_by_verification(verifier):
    path, verify = verifier
    with path.open('a+') as owner, path.open('a+') as other:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(owner, fcntl.LOCK_UN)
        assert not verify(owner.fileno())
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize('payload', [b'', b'lock: malformed\n', b'\xff', b'x' * 4097,
    b'lock: 1: FLOCK ADVISORY WRITE 1 00:00:0 0 EOF\n',
    b'lock: 1: FLOCK ADVISORY WRITE 1 00:00:0 0 EOF\n' * 2])
def test_unavailable_or_invalid_descriptor_evidence_refuses(tmp_path, monkeypatch, payload):
    with (tmp_path / 'lock').open('a+') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setattr(ownership.Path, 'open', lambda *a, **k: io.BytesIO(payload))
        assert not ownership.owns_exclusive_flock(owner.fileno())


def test_unreadable_procfs_refuses(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise PermissionError('test-only procfs refusal')
    with (tmp_path / 'lock').open('a+') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setattr(ownership.Path, 'open', unavailable)
        assert not ownership.owns_exclusive_flock(owner.fileno())


def test_valid_lock_record_cannot_hide_oversized_descriptor_evidence(tmp_path, monkeypatch):
    with (tmp_path / 'lock').open('a+') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        valid = Path('/proc/self/fdinfo/%d' % owner.fileno()).read_bytes()
        payload = valid + b'x' * (4097 - len(valid))
        monkeypatch.setattr(ownership.Path, 'open', lambda *a, **k: io.BytesIO(payload))
        assert not ownership.owns_exclusive_flock(owner.fileno())


def test_descriptor_lock_record_must_match_its_actual_inode(tmp_path, monkeypatch):
    with (tmp_path / 'lock').open('a+') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        payload = b'lock: 1: FLOCK ADVISORY WRITE 1 00:00:0 0 EOF\n'
        monkeypatch.setattr(ownership.Path, 'open', lambda *a, **k: io.BytesIO(payload))
        assert not ownership.owns_exclusive_flock(owner.fileno())


def test_inherited_owner_still_verifies_after_original_process_exits(tmp_path, procfs_mode):
    # Parent and child synchronize over pipes; no arbitrary sleep determines
    # ownership. Only disposable file operations occur in the child.
    path = tmp_path / 'lock'
    parent_code = """
import fcntl,os,subprocess,sys
path,scripts,mode=sys.argv[1:]
with open(path,'a+') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    code='''import io,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from sentinel_lock_ownership import owns_exclusive_flock
if sys.argv[3]=='legacy':
    Path.open=lambda *a,**k: io.BytesIO(('pos: 0'+chr(10)+'flags: 02500002'+chr(10)).encode())
fd=int(sys.argv[2])
print('ready',flush=True)
sys.stdin.readline()
print(json.dumps({'owned_after_parent_exit':owns_exclusive_flock(fd)}),flush=True)
sys.stdin.readline()
'''
    subprocess.Popen([sys.executable,'-c',code,scripts,str(lock.fileno()),mode],pass_fds=(lock.fileno(),))
"""
    parent = subprocess.Popen([sys.executable, '-c', parent_code, str(path), str(SCRIPTS), procfs_mode],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
    try:
        assert parent.stdout.readline().strip() == 'ready'
        assert parent.wait(timeout=5) == 0
        parent.stdin.write('verify\n')
        parent.stdin.flush()
        assert json.loads(parent.stdout.readline()) == {'owned_after_parent_exit': True}
        with path.open('a+') as contender:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        parent.stdin.write('exit\n')
        parent.stdin.flush()
        assert parent.stdout.read() == ''
        with path.open('a+') as next_owner:
            fcntl.flock(next_owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        parent.stdin.close()
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=5)


@pytest.mark.parametrize('error', [errno.ENOLCK, errno.EIO, errno.EBADF])
def test_probe_errors_never_authorize_work(tmp_path, monkeypatch, error):
    with (tmp_path / 'lock').open('a+') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX)
        monkeypatch.setattr(Path, 'open', lambda *a, **k: io.BytesIO(b'pos: 0\nflags: 02\n'))
        def broken(*args):
            raise OSError(error, 'injected probe error')
        monkeypatch.setattr(ownership.fcntl, 'flock', broken)
        assert not ownership.owns_exclusive_flock(owner.fileno())


@pytest.mark.parametrize('replacement', [False, True])
def test_owner_exit_between_probes_requires_actual_exclusive_acquisition(tmp_path, monkeypatch, replacement):
    with (tmp_path / 'lock').open('a+') as first, (tmp_path / 'lock').open('a+') as supplied, (tmp_path / 'lock').open('a+') as next_owner:
        real_flock = fcntl.flock
        real_flock(first, fcntl.LOCK_EX)
        monkeypatch.setattr(Path, 'open', lambda *a, **k: io.BytesIO(b'pos: 0\nflags: 02\n'))
        def race(fd, operation):
            if operation == fcntl.LOCK_SH | fcntl.LOCK_NB:
                try:
                    real_flock(fd, operation)
                except BlockingIOError:
                    real_flock(first, fcntl.LOCK_UN)
                    if replacement:
                        real_flock(next_owner, fcntl.LOCK_EX)
                    raise
            else:
                return real_flock(fd, operation)
        monkeypatch.setattr(ownership.fcntl, 'flock', race)
        assert ownership.owns_exclusive_flock(supplied.fileno()) is (not replacement)
        with open(tmp_path / 'lock', 'a+') as contender:
            with pytest.raises(BlockingIOError):
                real_flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize('kind', ['backup', 'go'])
def test_real_launcher_and_child_accept_legacy_procfs_without_recursion(tmp_path, kind):
    # sitecustomize changes only fdinfo availability in both real interpreters.
    # Kernel locks, descriptor inheritance and subprocess launch remain real.
    (tmp_path / 'sitecustomize.py').write_text('''import io
from pathlib import Path
original = Path.open
def legacy(path, *args, **kwargs):
    if str(path).startswith('/proc/self/fdinfo/'):
        return io.BytesIO(b'pos: 0\\nflags: 02500002\\n')
    return original(path, *args, **kwargs)
Path.open = legacy
''')
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(tmp_path), str(SCRIPTS)]))
    if kind == 'backup':
        env[backup.LOCK_ROOT_ENV] = str(tmp_path)
        child = 'import sentinel_backup_lock as m; assert m.lock_is_held(); print("child-owned")'
        command = [sys.executable, str(SCRIPTS / 'sentinel_backup_lock.py'), 'hold', sys.executable, '-c', child]
    else:
        child = ('import os; from pathlib import Path; import sentinel_go_lock as m; '
                 'm.LOCK=Path(os.environ["TEST_GO_LOCK"]); '
                 'assert m.lifecycle_lock_is_held(); assert m.current_run_token(); print("child-owned")')
        env['TEST_GO_LOCK'] = str(tmp_path / 'go.lock')
        launcher = ('import os,sys; from pathlib import Path; import sentinel_go_lock as m; '
                    'm.LOCK=Path(os.environ["TEST_GO_LOCK"]); sys.exit(m.main(sys.argv[1:]))')
        command = [sys.executable, '-c', launcher, sys.executable, '-c', child]
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'child-owned'


def test_disposable_host_diagnostic(capsys):
    assert ownership.main() == 0
    assert 'host flock compatibility: PASS' in capsys.readouterr().out


def test_backup_wait_does_not_acquire_after_deadline(tmp_path, monkeypatch):
    path = tmp_path / 'bounded-backup.lock'
    monkeypatch.setattr(backup, '_lock_path', lambda env: path)
    clock = [0.]
    monkeypatch.setattr(backup.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(backup.time, 'sleep', lambda delay: clock.__setitem__(0, 2.))
    attempts = []
    def busy_then_available(fd, operation):
        attempts.append(operation)
        if len(attempts) == 1:
            raise BlockingIOError()
    monkeypatch.setattr(backup.fcntl, 'flock', busy_then_available)
    entered = []
    monkeypatch.setattr(backup, 'owns_exclusive_flock', lambda fd: True)
    monkeypatch.setattr(backup.subprocess, 'run', lambda *a, **k: entered.append(a))
    assert backup._hold(['never-run'], wait_seconds=1) == 2
    assert len(attempts) == 1
    assert entered == []


def test_deployment_wait_covers_complete_maintenance_invocation(monkeypatch):
    import sentinel_maintenance_process as maintenance
    timeouts = []

    def bounded(argv, *, timeout):
        timeouts.append(timeout)
        return maintenance.Result(0, '')

    monkeypatch.setattr(maintenance, 'run_bounded', bounded)
    monkeypatch.setattr(maintenance, 'emit_result', lambda result: True)
    assert maintenance.main([]) == 0
    assert len(timeouts) == 1
    assert backup.MAX_WAIT_SECONDS >= timeouts[0] + 60


@pytest.mark.parametrize('kind', ['owned', 'unrelated', 'shared', 'unlocked'])
def test_deployment_shell_verifies_exact_lock_before_git(tmp_path, procfs_mode, kind):
    source = (SCRIPTS / 'sentinel-autonomous-deploy.sh').read_text()
    boundary = source.split('"$PYTHON" - "$SENTINEL_DEPLOY_LOCK_FD" <<\'PY\'\n')[1].split('\nPY\n')[0]
    path = tmp_path / 'deploy.lock'
    path.touch()
    selected = tmp_path / 'unrelated' if kind == 'unrelated' else path
    boundary = boundary.replace('"/tmp/sentinel-autonomous-deploy.lock"', repr(str(path)))
    boundary = boundary.replace('"scripts"', repr(str(SCRIPTS)))
    if procfs_mode == 'legacy':
        boundary = ('import io\nfrom pathlib import Path\n'
                    'Path.open=lambda *a,**k: io.BytesIO(b"pos: 0\\nflags: 02\\n")\n' + boundary)
    with selected.open('a+') as handle:
        if kind != 'unlocked':
            fcntl.flock(handle, fcntl.LOCK_SH if kind == 'shared' else fcntl.LOCK_EX)
        result = subprocess.run([sys.executable, '-c', boundary, str(handle.fileno())],
                                pass_fds=(handle.fileno(),), capture_output=True, text=True, timeout=5)
        assert result.returncode == (0 if kind == 'owned' else 2), result.stderr
