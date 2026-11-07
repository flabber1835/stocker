"""Real lightweight observers, original deadlines, ownership and falsifiers."""
from datetime import datetime, timedelta, timezone
import inspect
import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import textwrap
import time
from types import SimpleNamespace

import pytest

from sentinel import shadow_service_probe as probe, shadow_service_status as status
from sentinel.panel import model, sources
from tests.sentinel.test_shadow_worker_monitoring import A, DSN, state  # noqa: F401

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='deployed probe uses Linux parent-death supervision')


def current(state):
    status.publish(state/status.CRITICAL_NAME, A)
    return probe.observe(state)


def alive(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return fields[0] not in {'Z', 'X', 'x'}
    except FileNotFoundError:
        return False


def fault_child(monkeypatch, program):
    children = []
    def launch(*_):
        child = subprocess.Popen([sys.executable, '-B', '-c', program],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        children.append(child)
        return child
    monkeypatch.setattr(probe, '_launch', launch)
    return children


def test_actual_native_child_preserves_bytes_and_excludes_all_credentials(state, monkeypatch):
    original = current(state)
    for key in ('SENTINEL_DATABASE_URL', 'SENTINEL_PUBLICATION_RECEIPT_KEY',
                'ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY'):
        monkeypatch.setenv(key, 'private-canary-not-for-the-observer')
    real_popen = subprocess.Popen
    observed = []
    def owned(*args, **kwargs):
        environment = kwargs['env']
        assert set(environment) == {'PATH', 'LANG', 'PYTHONPATH',
            'PYTHONDONTWRITEBYTECODE', 'PYTHONUNBUFFERED'}
        assert 'private-canary' not in json.dumps(environment)
        process = real_popen(*args, **kwargs)
        observed.append(process)
        return process
    monkeypatch.setattr(probe.subprocess, 'Popen', owned)
    assert probe.read(state) == original
    assert len(observed) == 1 and observed[0].poll() == 0 and observed[0].stdout.closed


def test_twenty_actual_observations_read_each_update_then_persistent_negative(state):
    elapsed = []
    observed = []
    for _ in range(20):
        stamp = datetime.now(timezone.utc)
        status.publish(state/status.CRITICAL_NAME, A, now=stamp)
        started = time.monotonic()
        worker = sources._shadow_worker_row(state, DSN)
        elapsed.append(time.monotonic()-started)
        assert worker.status == model.OK, worker.detail
        assert worker.as_of == stamp and worker.valid_until == stamp+timedelta(seconds=60)
        assert 0 <= elapsed[-1] < 2, 'native observation exceeded its original budget'
        observed.append(worker.as_of)
    assert len(set(observed)) == 20, 'a current-looking observation was cached'
    (state/status.CRITICAL_NAME).write_text('persistent integrity refusal')
    started = time.monotonic()
    failed = sources._shadow_worker_row(state, DSN)
    negative_elapsed = time.monotonic()-started
    assert failed.status == model.FAIL and failed.value == 'HALTED · INTEGRITY FENCE'
    assert negative_elapsed < 2 and (state/status.CRITICAL_NAME).exists()
    quota = Path('/sys/fs/cgroup/cpu.max')
    print(json.dumps({'native_shadow_observations':len(elapsed),
        'max_elapsed_seconds':round(max(elapsed),6),
        'negative_elapsed_seconds':round(negative_elapsed,6),
        'cpu_quota':quota.read_text().strip() if quota.exists() else None}),flush=True)


def test_largest_allowed_files_do_not_deadlock_while_the_child_sends(state):
    for name in (status.NAME, status.PENDING_NAME):
        (state/name).write_bytes(b'x'*probe.MAX_BYTES)
    expected = probe.observe(state)
    assert probe.read(state) == expected


def test_fifo_timeout_reaps_exact_child_and_next_read_can_recover(state, monkeypatch):
    os.mkfifo(state/status.NAME)
    launch = probe._launch
    children = []
    def owned(*args):
        process = launch(*args)
        children.append(process)
        return process
    monkeypatch.setattr(probe, '_launch', owned)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        probe.read(state, timeout=.25)
    assert time.monotonic()-started < 1.75
    assert len(children) == 1 and children[0].poll() is not None and not alive(children[0].pid)
    (state/status.NAME).unlink()
    current(state)
    assert status.decode_probe(probe.read(state), DSN)['state'] == 'RUNNING'
    assert all(child.poll() is not None for child in children)


@pytest.mark.parametrize('mode', ['partial', 'duplicate', 'extra', 'nonboolean',
                                  'base64', 'oversize', 'empty', 'bad_exit', 'no_exit'])
def test_bounded_wire_refuses_bad_frames_and_reaps(state, monkeypatch, mode):
    frame = probe._encode_frame(current(state))
    value = json.loads(frame)
    if mode == 'partial': frame = frame[:-1]
    elif mode == 'duplicate': frame = frame.replace(b'"critical":false', b'"critical":false,"critical":false')
    elif mode == 'extra': frame = json.dumps({**value, 'unexpected': 1}).encode()
    elif mode == 'nonboolean': frame = json.dumps({**value, 'critical': 0}).encode()
    elif mode == 'base64': frame = json.dumps({**value, 'status': '*not-base64*'}).encode()
    elif mode == 'oversize': frame += b' '*(probe.MAX_FRAME_BYTES+1)
    elif mode == 'empty': frame = b''
    program = ('import sys,time; sys.stdout.buffer.write('+repr(frame)+'); sys.stdout.flush(); '
               +('time.sleep(60)' if mode == 'no_exit' else 'sys.exit(2)' if mode == 'bad_exit' else 'sys.exit(0)'))
    children = fault_child(monkeypatch, program)
    with pytest.raises((ValueError, RuntimeError, TimeoutError)):
        probe.read(state, timeout=.4)
    assert len(children) == 1 and children[0].poll() is not None and children[0].stdout.closed


def test_wire_size_guard_removal_would_admit_padded_positive_evidence(state, monkeypatch):
    frame = probe._encode_frame(current(state)) + b' '*(probe.MAX_FRAME_BYTES+1)
    fault_child(monkeypatch, 'import sys; sys.stdout.buffer.write('+repr(frame)+'); sys.stdout.flush()')
    def refuses():
        row = sources._shadow_worker_row(state, DSN)
        assert row.status == model.UNKNOWN, 'oversized frame admitted current worker evidence'
    refuses()
    monkeypatch.setattr(probe, 'MAX_FRAME_BYTES', len(frame)+1)
    with pytest.raises(AssertionError, match='oversized frame admitted'):
        refuses()


def test_late_frame_decode_and_process_startup_cannot_renew_original_deadline(state, monkeypatch):
    current(state)
    launch = probe._launch
    def late_launch(*args):
        time.sleep(.25)
        return launch(*args)
    monkeypatch.setattr(probe, '_launch', late_launch)
    with pytest.raises(TimeoutError):
        probe.read(state, timeout=.2)
    monkeypatch.setattr(probe, '_launch', launch)
    # Inject lateness only after the real bounded frame and child exit. A slow
    # CPU must not make the earlier transport timeout satisfy this falsifier.
    receive, monotonic = probe._receive, probe.time.monotonic
    completed_clock = [None]
    monkeypatch.setattr(probe, 'time', SimpleNamespace(monotonic=lambda:
        monotonic() if completed_clock[0] is None else completed_clock[0]))
    def late_result(process, deadline):
        result = receive(process, deadline)
        completed_clock[0] = deadline+.01
        return result
    monkeypatch.setattr(probe, '_receive', late_result)
    def refuses(reader):
        completed_clock[0] = None
        try:
            reader(state, timeout=2)
        except TimeoutError:
            return
        raise AssertionError('late positive snapshot admitted')
    refuses(probe.read)
    source = textwrap.dedent(inspect.getsource(probe.read))
    needle = 'if time.monotonic() >= deadline:'
    assert source.count(needle) == 1
    namespace = dict(vars(probe))
    exec(compile(source.replace(needle, 'if False:'), 'removed-worker-observation-deadline', 'exec'), namespace)
    with pytest.raises(AssertionError, match='late positive snapshot admitted'):
        refuses(namespace['read'])


def test_unreaped_child_refuses_replacement_and_guard_removal_is_detected(state, monkeypatch):
    current(state)
    class Pending:
        def poll(self): return None
    prior = Pending()
    monkeypatch.setattr(probe, '_UNREAPED', [prior])
    def refuses():
        try:
            probe.read(state)
        except TimeoutError:
            return
        raise AssertionError('replacement admitted while prior child is unreaped')
    refuses()
    monkeypatch.setattr(probe, '_admit', lambda: None)
    with pytest.raises(AssertionError, match='replacement admitted'):
        refuses()


@pytest.mark.parametrize('timeout', [2.001, 10, 0, -1, float('nan'), float('inf'), True])
def test_two_second_contract_cannot_be_extended(state, timeout):
    with pytest.raises(ValueError, match='budget refused'):
        probe.read(state, timeout=timeout)


def test_critical_marker_and_canonical_authentication_still_win_actual_reads(state):
    original = current(state)
    assert status.decode_probe(probe.read(state), DSN)['state'] == 'RUNNING'
    wrapped = json.loads(original['status'])
    wrapped['hmac_sha256'] = '0'*64
    (state/status.NAME).write_text(json.dumps(wrapped))
    assert sources._shadow_worker_row(state, DSN).status == model.UNKNOWN
    (state/status.CRITICAL_NAME).write_text('persistent integrity refusal')
    observed = sources._shadow_worker_row(state, DSN)
    assert observed.status == model.FAIL and observed.value == 'HALTED · INTEGRITY FENCE'
    assert (state/status.CRITICAL_NAME).read_text() == 'persistent integrity refusal'


def test_heavy_multiprocessing_main_is_not_imported_by_native_observer(state, tmp_path):
    current(state)
    script = tmp_path/'heavy-main.py'
    script.write_text(textwrap.dedent('''
        import json,sys,time
        from pathlib import Path
        if __name__ == '__mp_main__':
            time.sleep(3)
        from sentinel import shadow_service_probe as probe,supervisor_io
        if __name__ == '__main__':
            try:
                snapshot = (probe.read(Path(sys.argv[1])) if sys.argv[2] == 'native' else
                    supervisor_io.run(probe.observe,Path(sys.argv[1]),timeout=2,start_method='spawn'))
            except TimeoutError:
                print('TIMEOUT')
            else:
                assert snapshot['status'] is not None
                print('CURRENT')
    '''))
    def run(mode):
        return subprocess.run([sys.executable, '-B', str(script), str(state), mode],
            text=True, capture_output=True, timeout=8)
    native = run('native')
    assert native.returncode == 0 and native.stdout.strip() == 'CURRENT', native.stderr
    # Restoring nested spawn reproduces the incident under the same 2s budget.
    broken = run('nested-spawn')
    assert broken.returncode == 0 and broken.stdout.strip() == 'TIMEOUT', broken.stderr


def _owner_death_case(state, tmp_path, *, guarded):
    if not (state/status.NAME).exists():
        os.mkfifo(state/status.NAME)
    owner = tmp_path/'probe-owner.py'
    owner.write_text(textwrap.dedent('''
        import os,subprocess,sys,time
        from pathlib import Path
        from sentinel import shadow_service_probe as probe
        if sys.argv[2] == 'guarded':
            child = probe._launch(Path(sys.argv[1]),os.getpid())
        else:
            broken = ('import sys; from sentinel import supervisor_io,shadow_service_probe as probe; '
                'supervisor_io._parent_death=lambda _:None; raise SystemExit(probe.main(sys.argv[1:]))')
            child = subprocess.Popen([sys.executable,'-B','-c',broken,sys.argv[1],str(os.getpid())],
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        print(child.pid,flush=True)
        time.sleep(60)
    '''))
    process = subprocess.Popen([sys.executable, '-B', str(owner), str(state),
        'guarded' if guarded else 'unguarded'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    child_pid, child_start, fifo_writer = None, None, None
    try:
        import select
        assert select.select([process.stdout], [], [], 5)[0]
        child_pid = int(process.stdout.readline())
        child_start = Path(f'/proc/{child_pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
        deadline = time.monotonic()+2
        while time.monotonic() < deadline:
            try:
                fifo_writer = os.open(state/status.NAME, os.O_WRONLY | os.O_NONBLOCK)
                break
            except OSError as error:
                if error.errno != errno.ENXIO:
                    raise
                time.sleep(.02)
        else:
            raise AssertionError('native observer did not reach its guarded FIFO read')
        process.kill(); process.wait(timeout=2)
        deadline = time.monotonic()+3
        while alive(child_pid) and time.monotonic() < deadline:
            time.sleep(.02)
        assert not alive(child_pid), 'native observer survived its owner'
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=2)
        process.stdout.close()
        if (child_pid is not None and child_start is not None and alive(child_pid)
                and Path(f'/proc/{child_pid}/stat').read_text().rsplit(')', 1)[1].split()[19] == child_start):
            os.kill(child_pid, signal.SIGKILL)
        if fifo_writer is not None:
            os.close(fifo_writer)


def test_owner_death_kills_native_filesystem_reader_and_removed_guard_is_detected(state, tmp_path):
    _owner_death_case(state, tmp_path, guarded=True)
    with pytest.raises(AssertionError, match='native observer survived its owner'):
        _owner_death_case(state, tmp_path, guarded=False)
