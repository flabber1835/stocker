"""Owned fresh exchanges, hostile frames and shared half-core qualification."""
from datetime import datetime, timezone
import errno
import inspect
import json
import os
from pathlib import Path
import resource
import select
import signal
import subprocess
import sys
import textwrap
import time
from types import SimpleNamespace

import pytest

from sentinel import shadow_service_probe as probe, shadow_service_status as status
from tests.sentinel.test_shadow_worker_monitoring import A, DSN, state  # noqa: F401

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='native Linux process ownership')


def publish(state):
    stamp = datetime.now(timezone.utc)
    status.publish(state/status.CRITICAL_NAME, A, now=stamp)
    return stamp


def alive(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] not in {'Z', 'X', 'x'}
    except FileNotFoundError:
        return False


def child_factory(monkeypatch, program):
    compile(program, 'qualification-native-child', 'exec')
    children = []
    def launch(*_):
        child = subprocess.Popen([sys.executable, '-B', '-c', program],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        children.append(child)
        return child
    monkeypatch.setattr(probe, '_launch_observer', launch)
    return children


def response_program(state, *, alter='', suffix='time.sleep(60)', prefix=''):
    value = json.loads(probe._response(probe.observe(state), 'a'*32))
    return ('import sys,json,time; '+prefix+
        'request=json.loads(sys.stdin.buffer.readline()); '
        'value='+repr(value)+'; value["nonce"]=request["nonce"]; '+alter+
        'frame=json.dumps(value).encode()+bytes([10]); '
        'sys.stdout.buffer.write(frame); sys.stdout.flush(); '+suffix)


def test_lazy_actual_child_reuses_process_but_never_status_or_negative_bytes(state, monkeypatch):
    launch, children = probe._launch_observer, []
    def owned(*args):
        child = launch(*args)
        children.append(child)
        return child
    monkeypatch.setattr(probe, '_launch_observer', owned)
    owner = probe.Observer(state)
    assert not children
    try:
        stamps = []
        for _ in range(20):
            stamp = publish(state)
            snapshot = owner.read()
            decoded = status.decode_probe(snapshot, DSN)
            assert decoded['state'] == 'RUNNING'
            assert decoded['observed_at'] == stamp
            stamps.append(decoded['observed_at'])
        assert len(set(stamps)) == 20 and len(children) == 1
        (state/status.PENDING_NAME).write_bytes(b'new pending evidence')
        snapshot = owner.read()
        assert snapshot['pending'] == snapshot['latest_pending'] == b'new pending evidence'
        with pytest.raises(ValueError):
            status.decode_probe(snapshot, DSN)
        (state/status.CRITICAL_NAME).write_bytes(b'persistent integrity fence')
        assert status.decode_probe(owner.read(), DSN)['state'] == 'FENCED'
        assert len(children) == 1 and children[0].poll() is None
    finally:
        owner.close()
    assert children[0].poll() is not None and children[0].stdout.closed and children[0].stdin.closed
    owner.close()
    with pytest.raises(RuntimeError, match='ownership refused'):
        owner.read()


def test_reusable_child_has_only_credential_free_environment(state, monkeypatch):
    publish(state)
    for key in ('SENTINEL_DATABASE_URL', 'SENTINEL_PUBLICATION_RECEIPT_KEY',
                'ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY'):
        monkeypatch.setenv(key, 'private-canary-not-for-native-observer')
    popen = subprocess.Popen
    def launch(*args, **kwargs):
        assert set(kwargs['env']) == {'PATH', 'LANG', 'PYTHONPATH',
            'PYTHONDONTWRITEBYTECODE', 'PYTHONUNBUFFERED'}
        assert 'private-canary' not in json.dumps(kwargs['env'])
        return popen(*args, **kwargs)
    monkeypatch.setattr(probe.subprocess, 'Popen', launch)
    with probe.Observer(state) as owner:
        assert owner.read() == probe.observe(state)


def test_largest_reusable_response_preserves_all_three_bounded_blobs(state):
    for name in (status.NAME, status.PENDING_NAME):
        (state/name).write_bytes(b'x'*probe.MAX_BYTES)
    with probe.Observer(state) as owner:
        assert owner.read() == probe.observe(state)


@pytest.mark.parametrize('mode', ['foreign', 'duplicate', 'extra', 'bad_snapshot', 'oversized', 'partial', 'extra_frame'])
def test_exchange_rejects_foreign_malformed_partial_and_extra_frames(state, monkeypatch, mode):
    publish(state)
    alter = {'foreign': 'value["nonce"]="0"*32; ',
             'extra': 'value["unreviewed"]=True; ',
             'bad_snapshot': 'value["snapshot"]["critical"]=0; '}.get(mode, '')
    program = response_program(state, alter=alter)
    if mode == 'duplicate':
        program = program.replace('sys.stdout.buffer.write(frame)',
            'sys.stdout.buffer.write(frame.replace(b\'"nonce":\',b\'"nonce":"'+b'0'.decode()*32+'","nonce":\'))')
    elif mode == 'oversized':
        program = program.replace('sys.stdout.buffer.write(frame)',
            'sys.stdout.buffer.write(frame[:-1]+b" "*'+str(probe.MAX_RESPONSE_BYTES+1)+')')
    elif mode == 'partial':
        program = program.replace('sys.stdout.buffer.write(frame)', 'sys.stdout.buffer.write(frame[:-1])')
    elif mode == 'extra_frame':
        program = program.replace('sys.stdout.buffer.write(frame)', 'sys.stdout.buffer.write(frame+frame)')
    children = child_factory(monkeypatch, program)
    with probe.Observer(state) as owner:
        with pytest.raises((ValueError, RuntimeError, probe.ProbeTimeout)):
            owner.read(timeout=.5 if mode == 'partial' else 2)
        assert owner._process is None
    assert len(children) == 1 and children[0].poll() == -signal.SIGKILL


def test_idle_unsolicited_reply_is_rejected_before_another_request(state, monkeypatch):
    publish(state)
    children = child_factory(monkeypatch, response_program(state,
        suffix='time.sleep(.1); sys.stdout.buffer.write(frame); sys.stdout.flush(); time.sleep(60)'))
    send, sent = probe._send_request, []
    def record(*args):
        sent.append(args[1])
        return send(*args)
    monkeypatch.setattr(probe, '_send_request', record)
    with probe.Observer(state) as owner:
        assert owner.read()['status'] is not None
        assert select.select([children[0].stdout], [], [], 2)[0]
        with pytest.raises(ValueError, match='unsolicited'):
            owner.read()
    assert len(sent) == 1 and children[0].poll() is not None


def test_old_response_nonce_refuses_a_second_exchange_and_removed_guard_is_detected(state, monkeypatch):
    publish(state)
    value = json.loads(probe._response(probe.observe(state), 'a'*32))
    program = ('import sys,json,time; request=json.loads(sys.stdin.buffer.readline()); '
        'value='+repr(value)+'; value["nonce"]=request["nonce"]; '
        'frame=json.dumps(value).encode()+bytes([10]); '
        'sys.stdout.buffer.write(frame); sys.stdout.flush(); '
        'sys.stdin.buffer.readline(); sys.stdout.buffer.write(frame); sys.stdout.flush(); time.sleep(60)')
    child_factory(monkeypatch, program)
    def refuses():
        with probe.Observer(state) as owner:
            owner.read()
            try:
                owner.read()
            except ValueError as exc:
                assert 'nonce' in str(exc)
                return
            raise AssertionError('previous positive response admitted')
    refuses()
    source = textwrap.dedent(inspect.getsource(probe._decode_response))
    needle = "if value['nonce'] != nonce:"
    assert source.count(needle) == 1
    namespace = dict(vars(probe))
    exec(compile(source.replace(needle, 'if False:'), 'removed-response-nonce', 'exec'), namespace)
    monkeypatch.setattr(probe, '_decode_response', namespace['_decode_response'])
    with pytest.raises(AssertionError, match='previous positive response admitted'):
        refuses()


def test_cached_previous_positive_is_detected(state, monkeypatch):
    def fresh(observer):
        for _ in range(2):
            stamp = publish(state)
            decoded = status.decode_probe(observer.read(), DSN)
            assert decoded['observed_at'] == stamp, 'cached previous positive admitted'
        (state/status.CRITICAL_NAME).write_text('persistent fence')
        assert status.decode_probe(observer.read(), DSN)['state'] == 'FENCED'
    with probe.Observer(state) as observer:
        fresh(observer)
    (state/status.CRITICAL_NAME).unlink()
    real, cached = probe.Observer.read, []
    def broken(self, **kwargs):
        if not cached:
            cached.append(real(self, **kwargs))
        return cached[0]
    monkeypatch.setattr(probe.Observer, 'read', broken)
    with probe.Observer(state) as observer:
        with pytest.raises(AssertionError, match='cached previous positive admitted'):
            fresh(observer)


def test_first_launch_and_serialization_consume_the_original_deadline(state, monkeypatch):
    publish(state)
    monotonic, launch, request = time.monotonic, probe._launch_observer, probe._request
    shifted = [None]
    monkeypatch.setattr(probe, 'time', SimpleNamespace(monotonic=lambda:
        monotonic() if shifted[0] is None else shifted[0]))
    def late_launch(*args):
        result = launch(*args)
        shifted[0] = monotonic()+2.01
        return result
    monkeypatch.setattr(probe, '_launch_observer', late_launch)
    with probe.Observer(state) as owner:
        with pytest.raises(probe.ProbeTimeout) as exc:
            owner.read()
        assert exc.value.probe_stage == 'LAUNCH' and owner._process is None
    shifted[0] = None
    monkeypatch.setattr(probe, '_launch_observer', launch)
    def late_request(*args):
        result = request(*args)
        shifted[0] = monotonic()+2.01
        return result
    monkeypatch.setattr(probe, '_request', late_request)
    with probe.Observer(state) as owner:
        with pytest.raises(probe.ProbeTimeout) as exc:
            owner.read()
        assert exc.value.probe_stage == 'SEND'


def test_late_decode_refuses_and_removing_original_deadline_is_detected(state, monkeypatch):
    publish(state)
    decode, send, monotonic = probe._decode_response, probe._send_request, time.monotonic
    original, shifted = [None], [None]
    def capture(process, frame, deadline):
        original[0] = deadline
        return send(process, frame, deadline)
    def late(*args):
        result = decode(*args)
        shifted[0] = original[0]+.01
        return result
    monkeypatch.setattr(probe, '_send_request', capture)
    monkeypatch.setattr(probe, '_decode_response', late)
    monkeypatch.setattr(probe, 'time', SimpleNamespace(monotonic=lambda:
        monotonic() if shifted[0] is None else shifted[0]))
    def refuses():
        shifted[0] = None
        with probe.Observer(state) as owner:
            try:
                owner.read()
            except probe.ProbeTimeout as exc:
                assert exc.probe_stage == 'DECODE'
                return
            raise AssertionError('late positive response admitted')
    refuses()
    check = probe._check_deadline
    monkeypatch.setattr(probe, '_check_deadline', lambda deadline, stage:
        None if stage == 'DECODE' else check(deadline, stage))
    with pytest.raises(AssertionError, match='late positive response admitted'):
        refuses()


def test_each_warm_request_has_its_own_budget_and_failed_child_is_reaped(state, monkeypatch):
    publish(state)
    launch, children = probe._launch_observer, []
    def record(*args):
        child = launch(*args); children.append(child); return child
    monkeypatch.setattr(probe, '_launch_observer', record)
    with probe.Observer(state) as owner:
        owner.read()
        (state/status.NAME).unlink()
        os.mkfifo(state/status.NAME)
        started = time.monotonic()
        with pytest.raises(probe.ProbeTimeout) as exc:
            owner.read(timeout=.2)
        assert exc.value.probe_stage == 'RECEIVE'
        assert time.monotonic()-started < 1.5
        assert owner._process is None and children[0].poll() is not None
        (state/status.NAME).unlink(); publish(state)
        assert status.decode_probe(owner.read(), DSN)['state'] == 'RUNNING'
        assert len(children) == 2


def test_blocked_request_transmission_uses_original_deadline(state, monkeypatch):
    children = child_factory(monkeypatch, 'import time; time.sleep(60)')
    launch = probe._launch_observer
    def full_pipe(*args):
        child = launch(*args)
        descriptor = child.stdin.fileno(); os.set_blocking(descriptor, False)
        while True:
            try: os.write(descriptor, b'x'*4096)
            except BlockingIOError: return child
    monkeypatch.setattr(probe, '_launch_observer', full_pipe)
    with probe.Observer(state) as owner:
        with pytest.raises(probe.ProbeTimeout) as exc:
            owner.read(timeout=.2)
        assert exc.value.probe_stage == 'SEND'
    assert len(children) == 1 and children[0].poll() is not None


def test_dead_child_reply_is_not_a_current_observation(state, monkeypatch):
    publish(state)
    children = child_factory(monkeypatch, response_program(state, suffix='sys.exit(0)'))
    receive = probe._receive_response
    def completed(process, deadline):
        process.wait(timeout=deadline-time.monotonic())
        return receive(process, deadline)
    monkeypatch.setattr(probe, '_receive_response', completed)
    with probe.Observer(state) as owner:
        with pytest.raises(RuntimeError, match='observer exited'):
            owner.read()
    assert children[0].poll() == 0


def test_unreaped_replacement_guard_has_an_executed_falsifier(state, monkeypatch):
    publish(state)
    class Stuck:
        def poll(self): return None
    monkeypatch.setattr(probe, '_UNREAPED', [Stuck()])
    def refuses():
        with probe.Observer(state) as owner:
            try:
                owner.read()
            except probe.ProbeTimeout as exc:
                assert exc.probe_stage == 'ADMISSION'
                return
            raise AssertionError('replacement admitted over unreaped observer')
    refuses()
    monkeypatch.setattr(probe, '_admit', lambda: None)
    with pytest.raises(AssertionError, match='replacement admitted over unreaped observer'):
        refuses()


def test_explicit_close_retains_unreaped_process_and_refuses_any_replacement(state, monkeypatch):
    class Stream:
        closed = False
        def close(self): self.closed = True
    class Stuck:
        stdout, stdin = Stream(), Stream()
        killed = False
        def poll(self): return None
        def kill(self): self.killed = True
        def wait(self, *, timeout):
            assert timeout == 1
            raise subprocess.TimeoutExpired('owned-native-child', timeout)
    prior = Stuck()
    monkeypatch.setattr(probe, '_UNREAPED', [])
    owner = probe.Observer(state); owner._process = prior
    with pytest.raises(probe.ProbeTimeout) as exc:
        owner.close()
    assert exc.value.probe_stage == 'REAP'
    assert prior.killed and prior.stdout.closed and prior.stdin.closed and probe._UNREAPED == [prior]
    monkeypatch.setattr(probe, '_launch_observer', lambda *_: pytest.fail('unreaped replacement launched'))
    with probe.Observer(state) as other:
        with pytest.raises(probe.ProbeTimeout) as exc:
            other.read()
        assert exc.value.probe_stage == 'ADMISSION'


def test_single_exchange_lock_refuses_concurrency_without_launching(state, monkeypatch):
    owner = probe.Observer(state)
    monkeypatch.setattr(probe, '_launch_observer', lambda *_: pytest.fail('concurrent call launched child'))
    assert owner._lock.acquire(False)
    try:
        with pytest.raises(RuntimeError, match='concurrent'):
            owner.read()
        with pytest.raises(RuntimeError, match='active'):
            owner.close()
    finally:
        owner._lock.release(); owner.close()


def fork_refusal_case(state):
    publish(state)
    with probe.Observer(state) as owner:
        owner.read()
        original = owner._process
        pid = os.fork()
        if pid == 0:
            refused = 0
            for operation in (owner.read, owner.close):
                try:
                    operation()
                except RuntimeError:
                    refused += 1
                except BaseException:
                    pass
            os._exit(0 if refused == 2 else 2)
        deadline = time.monotonic()+3
        while True:
            ended, result = os.waitpid(pid, os.WNOHANG)
            if ended:
                assert os.waitstatus_to_exitcode(result) == 0
                break
            if time.monotonic() >= deadline:
                os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
                raise AssertionError('inherited observer call did not refuse finitely')
            time.sleep(.01)
        if select.select([original.stdout], [], [], .2)[0]:
            original.wait(timeout=1)
        assert original.poll() is None, 'inherited observer killed the original owned child'
        assert status.decode_probe(owner.read(), DSN)['state'] == 'RUNNING'


def test_fork_inherited_read_and_close_cannot_kill_owner_and_mutant_is_detected(state, monkeypatch):
    fork_refusal_case(state)
    original = probe.Observer.read
    def unsafe(self, **kwargs):
        if self._owner != os.getpid():
            # The prior bug cleaned a foreign owner's child on refusal.
            if self._process is not None:
                os.kill(self._process.pid, signal.SIGKILL)
            raise RuntimeError('inherited owner refused after unsafe cleanup')
        return original(self, **kwargs)
    monkeypatch.setattr(probe.Observer, 'read', unsafe)
    with pytest.raises(AssertionError, match='inherited observer killed'):
        fork_refusal_case(state)


@pytest.mark.parametrize('timeout', [True, 0, -1, 2.001, float('inf'), float('nan')])
def test_reusable_budget_cannot_be_extended(state, timeout):
    with probe.Observer(state) as owner:
        with pytest.raises(ValueError, match='budget refused'):
            owner.read(timeout=timeout)


def test_timeout_diagnostics_are_closed_and_contain_no_private_detail():
    for stage in probe.STAGES:
        error = probe.ProbeTimeout(stage)
        assert isinstance(error, TimeoutError) and error.probe_stage == stage
        assert str(error) == 'worker snapshot exceeded its wall-clock budget'
    with pytest.raises(ValueError):
        probe.ProbeTimeout('/private/arbitrary path')


def owner_death_case(state, tmp_path, *, guarded, blocked=False):
    if blocked:
        (state/status.NAME).unlink(missing_ok=True)
        os.mkfifo(state/status.NAME)
    else:
        publish(state)
    script = tmp_path/'reusable-owner.py'
    script.write_text(textwrap.dedent('''
        import os,subprocess,sys,time
        from pathlib import Path
        from sentinel import shadow_service_probe as probe
        if sys.argv[2]=='unguarded':
            def launch(directory,parent):
                code=('import sys;from sentinel import supervisor_io,shadow_service_probe as p;'
                    'supervisor_io._parent_death=lambda _:None;raise SystemExit(p.main(sys.argv[1:]))')
                return subprocess.Popen([sys.executable,'-B','-c',code,str(directory),str(parent),'serve'],
                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            probe._launch_observer=launch
        if sys.argv[3]=='blocked':
            actual=probe._launch_observer
            def reported(directory,parent):
                child=actual(directory,parent);print(child.pid,flush=True);return child
            probe._launch_observer=reported
        owner=probe.Observer(Path(sys.argv[1]));owner.read()
        if sys.argv[3]!='blocked':print(owner._process.pid,flush=True)
        time.sleep(60)
    '''))
    process = subprocess.Popen([sys.executable, '-B', str(script), str(state),
        'guarded' if guarded else 'unguarded', 'blocked' if blocked else 'idle'], stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True)
    pid, start, writer = None, None, None
    try:
        assert select.select([process.stdout], [], [], 6)[0]
        pid = int(process.stdout.readline())
        start = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
        if blocked:
            deadline = time.monotonic()+1.5
            while time.monotonic() < deadline:
                try:
                    writer = os.open(state/status.NAME, os.O_WRONLY | os.O_NONBLOCK)
                    break
                except OSError as exc:
                    if exc.errno != errno.ENXIO: raise
                    time.sleep(.01)
            assert writer is not None, 'native observer did not enter guarded FIFO read'
            # Holding this writer prevents EOF from unblocking the actual raw
            # read when the owner dies. Only parent-death supervision can stop
            # the blocked child before this test releases the FIFO descriptor.
        process.kill(); process.wait(timeout=2)
        deadline = time.monotonic()+1
        while alive(pid) and time.monotonic() < deadline: time.sleep(.02)
        assert not alive(pid), 'native observer survived collector death'
    finally:
        if process.poll() is None: process.kill(); process.wait(timeout=2)
        process.stdout.close()
        if (pid is not None and start is not None and alive(pid)
                and Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19] == start):
            os.kill(pid, signal.SIGKILL)
        if writer is not None:
            os.close(writer)


def test_actual_idle_parent_death(state, tmp_path):
    owner_death_case(state, tmp_path, guarded=True)


def test_blocked_parent_death_and_removed_guard_falsifier(state, tmp_path):
    owner_death_case(state, tmp_path, guarded=True, blocked=True)
    with pytest.raises(AssertionError, match='native observer survived'):
        owner_death_case(state, tmp_path, guarded=False, blocked=True)


def cpu_usage():
    value = resource.getrusage(resource.RUSAGE_CHILDREN)
    return value.ru_utime+value.ru_stime


def quota_stat():
    root = Path('/sys/fs/cgroup')
    return {name: (root/name).read_text().strip() for name in ('cpu.max', 'cpu.stat') if (root/name).exists()}


def test_sustained_fresh_observation_under_shared_half_core_contention(state):
    """Real sibling CPU work in this test cgroup; no external workload access."""
    program = ('import os,sys,time;from sentinel.supervisor_io import _parent_death;'
        '_parent_death(int(sys.argv[1]));print("READY",flush=True);'
        'deadline=time.monotonic()+120;x=1\n'
        'while time.monotonic()<deadline:\n'
        ' for _ in range(2048):x=(x*1664525+1013904223)&0xffffffff\n')
    siblings, elapsed, stamps = [], [], []
    before = quota_stat()
    cpu_before = cpu_usage()
    started = time.monotonic()
    try:
        for _ in range(3):
            child = subprocess.Popen([sys.executable, '-B', '-c', program, str(os.getpid())],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env={'PATH':os.defpath, 'PYTHONPATH':str(Path(probe.__file__).parent.parent)}, text=True)
            siblings.append(child)
            assert select.select([child.stdout], [], [], 6)[0] and child.stdout.readline().strip() == 'READY'
        with probe.Observer(state) as owner:
            reusable_started = time.monotonic()
            for count in range(12):
                stamp = publish(state)
                tick = time.monotonic(); snapshot = owner.read(); elapsed.append(time.monotonic()-tick)
                decoded = status.decode_probe(snapshot, DSN)
                assert decoded['state'] == 'RUNNING' and decoded['observed_at'] == stamp
                stamps.append(stamp)
                pending = ('fresh-pending-'+str(count)).encode()
                (state/status.PENDING_NAME).write_bytes(pending)
                tick = time.monotonic(); snapshot = owner.read(); elapsed.append(time.monotonic()-tick)
                assert snapshot['pending'] == snapshot['latest_pending'] == pending
                with pytest.raises(ValueError): status.decode_probe(snapshot, DSN)
                (state/status.PENDING_NAME).unlink()
                (state/status.CRITICAL_NAME).write_text('current persistent fence')
                tick = time.monotonic(); snapshot = owner.read(); elapsed.append(time.monotonic()-tick)
                assert status.decode_probe(snapshot, DSN)['state'] == 'FENCED'
                (state/status.CRITICAL_NAME).unlink()
                assert all(child.poll() is None for child in siblings)
            reusable_wall = time.monotonic()-reusable_started
        reusable_cpu = cpu_usage()-cpu_before
        assert len(set(stamps)) == 12 and max(elapsed) < probe.OBSERVATION_SECONDS
        one_shot_cpu_before = cpu_usage(); one_shot_start = time.monotonic()
        for _ in range(6):
            publish(state)
            assert status.decode_probe(probe.read(state), DSN)['state'] == 'RUNNING'
            assert all(child.poll() is None for child in siblings)
        one_shot_cpu = cpu_usage()-one_shot_cpu_before
        one_shot_wall = time.monotonic()-one_shot_start
        assert reusable_cpu < one_shot_cpu*.75, 'reusable observer repeated per-read import CPU'
        print(json.dumps({'contention_siblings':3, 'fresh_signed_updates':len(stamps),
            'reusable_reads':len(elapsed), 'max_original_budget_seconds':probe.OBSERVATION_SECONDS,
            'max_read_seconds':round(max(elapsed),6), 'first_launch_read_seconds':round(elapsed[0],6),
            'reusable_child_cpu_seconds':round(reusable_cpu,6), 'reusable_wall_seconds':round(reusable_wall,6),
            'one_shot_reads':6, 'one_shot_child_cpu_seconds':round(one_shot_cpu,6),
            'one_shot_wall_seconds':round(one_shot_wall,6), 'wall_seconds':round(time.monotonic()-started,6),
            'quota_before':before, 'quota_after':quota_stat()}, sort_keys=True), flush=True)
    finally:
        for child in siblings:
            if child.poll() is None: child.kill()
            child.wait(timeout=2); child.stdout.close()
