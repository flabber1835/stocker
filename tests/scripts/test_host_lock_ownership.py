"""Descriptor ownership contracts on disposable Linux files; no deployment."""
import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import sentinel_backup_lock as backup
import sentinel_go_lock as go
import sentinel_lock_ownership as ownership


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


def test_inherited_owner_still_verifies_after_original_process_exits(tmp_path):
    # Parent and child synchronize over pipes; no arbitrary sleep determines
    # ownership. Only disposable file operations occur in the child.
    path = tmp_path / 'lock'
    parent_code = """
import fcntl,os,subprocess,sys
path,scripts=sys.argv[1:]
with open(path,'a+') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    code='''import json,sys
sys.path.insert(0,sys.argv[1])
from sentinel_lock_ownership import owns_exclusive_flock
fd=int(sys.argv[2])
print('ready',flush=True)
sys.stdin.readline()
print(json.dumps({'owned_after_parent_exit':owns_exclusive_flock(fd)}),flush=True)
sys.stdin.readline()
'''
    subprocess.Popen([sys.executable,'-c',code,scripts,str(lock.fileno())],pass_fds=(lock.fileno(),))
"""
    parent = subprocess.Popen([sys.executable, '-c', parent_code, str(path), str(SCRIPTS)],
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
