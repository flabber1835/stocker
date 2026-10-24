"""Private exact-b2 interpreter/kernel qualification, never financial readiness.

Run inside the reviewed predecessor image, offline, with no host state mounts,
no operational credentials and only a private writable /tmp. Standard input is
one JSON object with schema sentinel.b2-drain-image-input/1, compat_source (the
unchanged candidate shadow_drain_compat.py text) and its compat_sha256.

The host must independently inspect/select the exact image. This program also
checks its sealed source revision and explicit runtime identity. All signals
target children created here, through bound Linux pidfds; no installed service,
database, broker, backtest, backup or restore is accessed.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types

PREDECESSOR = 'b2e308bb664718da373175f1a7d988d07b159ae2'
IMAGE = 'sha256:213e53efe9849a53a5b61966af6f252aa31ea697416d40712603098a0c8e7002'
PRIVATE_DSN = 'postgresql://qualification.invalid/b2-drain-image-private'
PRIVATE_KEY = 'sentinel-b2-drain-private-qualification-key-20261023'
INPUT_SCHEMA = 'sentinel.b2-drain-image-input/1'

FIXTURE = r'''import json,pathlib,subprocess,sys,time
state=pathlib.Path(sys.argv[2])
child=None
if sys.argv[3]=='busy':
    child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(90)'])
(state/'fixture-ready.json').write_text(json.dumps({'child':child.pid if child else None}))
while True:
    with (state/'admission-ticks').open('ab',buffering=0) as stream:
        stream.write(b'+')
    time.sleep(.005)
'''


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def environment():
    require(sys.platform == 'linux', 'exact-b2 qualification requires Linux')
    require(os.environ.get('SENTINEL_IMAGE_SOURCE_REVISION') == PREDECESSOR,
            'sealed predecessor source revision differs')
    require(os.environ.get('SENTINEL_GIT_COMMIT') == PREDECESSOR
            and os.environ.get('SENTINEL_RUNTIME_IMAGE_DIGEST') == IMAGE,
            'explicit predecessor runtime identity differs')
    require(os.environ.get('SENTINEL_LOCAL_PAPER_MODE') == 'OWNER_AUTHORIZED_FUNCTION_FIRST_V1',
            'explicit private PAPER envelope is required')
    for name in ('ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'OPENFIGI_API_KEY',
                 'SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY', 'SENTINEL_POSTGRES_PASSWORD'):
        require(not os.environ.get(name), 'operational credentials are forbidden: '+name)
    require(os.environ.get('SENTINEL_DATABASE_URL', '') in ('', PRIVATE_DSN),
            'operational database URL is forbidden')
    require(os.environ.get('SENTINEL_PUBLICATION_RECEIPT_KEY', '') in ('', PRIVATE_KEY),
            'operational receipt key is forbidden')
    require(hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'),
            'bound Linux pidfd APIs are unavailable')
    os.environ['SENTINEL_DATABASE_URL'] = PRIVATE_DSN
    os.environ['SENTINEL_PUBLICATION_RECEIPT_KEY'] = PRIVATE_KEY


def input_source():
    raw = sys.stdin.buffer.read(1024*1024+1)
    require(len(raw) <= 1024*1024, 'qualification input exceeds its bound')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate qualification input field')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    require(isinstance(value, dict) and set(value) == {'schema', 'compat_source', 'compat_sha256'}
            and value['schema'] == INPUT_SCHEMA and isinstance(value['compat_source'], str),
            'qualification input shape differs')
    source = value['compat_source'].encode('utf-8')
    require(hashlib.sha256(source).hexdigest() == value['compat_sha256'],
            'frozen compatibility source hash differs')
    module = types.ModuleType('sentinel_b2_private_compatibility_fixture')
    exec(compile(source, '<frozen-qualified-shadow-drain-compat>', 'exec'), module.__dict__)
    require(module.PREDECESSOR == PREDECESSOR and module.SCHEMA == 'sentinel.shadow-drain-compat/1',
            'compatibility bridge subject differs')
    return module, value['compat_sha256']


def wait_until(predicate, *, seconds=3):
    end = time.monotonic()+seconds
    while not predicate():
        require(time.monotonic() < end, 'private process observation exceeded its finite deadline')
        time.sleep(.01)


def ticks(state):
    try:
        return (state/'admission-ticks').stat().st_size
    except FileNotFoundError:
        return 0


@contextmanager
def fixture(state, bridge, *, busy):
    # The exact argv token exercises the predecessor discovery code unchanged.
    process = subprocess.Popen([sys.executable, '-B', '-c', FIXTURE,
        'sentinel.shadow_supervisor', str(state), 'busy' if busy else 'idle'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        start_new_session=True)
    try:
        wait_until(lambda: (state/'fixture-ready.json').exists() and ticks(state) > 0)
        require(process.poll() is None, 'private supervisor fixture exited early')
        current = bridge._supervisors()
        require(current['pid'] == process.pid, 'discovery escaped the private supervisor fixture')
        from sentinel import shadow_service_status as status
        status._write(state/status.NAME, status.Status(
            binding_sha256=status.binding(PRIVATE_DSN), incarnation=os.urandom(16).hex(),
            state='RUNNING', reason='IDLE', observed_at=datetime.now(timezone.utc)))
        yield process, json.loads((state/'fixture-ready.json').read_text())['child']
    finally:
        # This process group was created above and contains only this fixture.
        require(os.getpgid(process.pid) == process.pid if process.poll() is None else True,
                'private fixture process group changed')
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate(timeout=3)


def pidfd_target(fd):
    values = Path('/proc/self/fdinfo/'+str(fd)).read_text().splitlines()
    return int(next(line.split(':', 1)[1] for line in values if line.startswith('Pid:')))


def successful_barrier(root, bridge):
    state = root/'idle'; state.mkdir()
    with fixture(state, bridge, busy=False) as (process, _):
        events = []
        frozen_ticks = None
        original_signal, original_write, original_fsync = signal.pidfd_send_signal, bridge._write, os.fsync
        def send(fd, signum, *args, **kwargs):
            nonlocal frozen_ticks
            require(pidfd_target(fd) == process.pid, 'bridge attempted to signal another process')
            if signum == signal.SIGSTOP:
                require(not events, 'unexpected repeated private hold')
                events.append('SIGSTOP')
            elif signum == signal.SIGKILL:
                require(events[-1] == 'DURABLE_AUTHENTICATED_ACK', 'fatal signal preceded durable acknowledgement')
                require(bridge._process(process.pid)['state'] in {'T', 't'}, 'supervisor resumed before fatal signal')
                require(ticks(state) == frozen_ticks, 'admission advanced after durable barrier')
                events.append('SIGKILL_WHILE_STOPPED')
            else:
                raise RuntimeError('unexpected signal on successful private barrier')
            return original_signal(fd, signum, *args, **kwargs)
        def fsync(fd):
            original_fsync(fd)
            events.append('FSYNC_DIRECTORY' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'FSYNC_FILE')
        def write(target, value):
            nonlocal frozen_ticks
            require(bridge._process(process.pid)['state'] in {'T', 't'}, 'acknowledgement preceded kernel hold')
            frozen_ticks = ticks(state)
            original_write(target, value)
            require(events[-2:] == ['FSYNC_FILE', 'FSYNC_DIRECTORY'], 'barrier publication was not durably synced')
            require(bridge._load(target) == value, 'durable acknowledgement authentication differs')
            require(ticks(state) == frozen_ticks, 'admission raced durable barrier publication')
            events.append('DURABLE_AUTHENTICATED_ACK')
        try:
            signal.pidfd_send_signal, bridge._write, os.fsync = send, write, fsync
            proof = bridge.bridge(state, operation_id='private-b2-idle', request_sha256='a'*64,
                container_id='private-disposable-image-fixture', image=IMAGE)
            process.wait(timeout=3)
            require(process.returncode == -signal.SIGKILL, 'stopped supervisor did not receive fatal SIGKILL')
            require(ticks(state) == frozen_ticks, 'private admission resumed after fatal signal')
            bridge.validate(proof, operation_id='private-b2-idle', request_sha256='a'*64,
                container_id='private-disposable-image-fixture', image=IMAGE, now=datetime.now(timezone.utc))
            require(events == ['SIGSTOP', 'FSYNC_FILE', 'FSYNC_DIRECTORY',
                'DURABLE_AUTHENTICATED_ACK', 'SIGKILL_WHILE_STOPPED'], 'private signal/publication order differs')
            return dict(passed=True, events=events, supervisor_returncode=process.returncode,
                        no_admission_after_hold=True, authenticated_barrier=True)
        finally:
            signal.pidfd_send_signal, bridge._write, os.fsync = original_signal, original_write, original_fsync


def busy_refusal(root, bridge):
    state = root/'busy'; state.mkdir()
    with fixture(state, bridge, busy=True) as (process, child):
        require(child is not None and bridge._process(child)['parent'] == process.pid,
                'private admitted dependency was not established')
        events = []
        original_signal = signal.pidfd_send_signal
        def send(fd, signum, *args, **kwargs):
            require(pidfd_target(fd) == process.pid, 'busy bridge attempted to signal another process')
            require(signum in {signal.SIGSTOP, signal.SIGCONT}, 'busy work received a fatal signal')
            events.append('SIGSTOP' if signum == signal.SIGSTOP else 'SIGCONT')
            return original_signal(fd, signum, *args, **kwargs)
        try:
            signal.pidfd_send_signal = send
            try:
                bridge.bridge(state, operation_id='private-b2-busy', request_sha256='b'*64,
                    container_id='private-disposable-image-fixture', image=IMAGE)
            except ValueError as exc:
                require(str(exc) == 'admitted dependency or worker still exists', 'unexpected busy refusal')
            else:
                raise RuntimeError('bridge failed to refuse already admitted work')
        finally:
            signal.pidfd_send_signal = original_signal
        require(events == ['SIGSTOP', 'SIGCONT'], 'busy supervisor did not resume before any barrier')
        require(not (state/bridge.NAME).exists(), 'busy refusal published a barrier')
        before = ticks(state)
        wait_until(lambda: ticks(state) > before)
        require(process.poll() is None and bridge._process(child)['parent'] == process.pid,
                'busy refusal interrupted the private admitted dependency')
        return dict(passed=True, events=events, barrier_absent=True, existing_work_preserved=True)


def main():
    environment()
    bridge, source_sha256 = input_source()
    with tempfile.TemporaryDirectory(prefix='sentinel-private-b2-drain-', dir='/tmp') as private:
        root = Path(private)
        idle, busy = successful_barrier(root, bridge), busy_refusal(root, bridge)
    print(json.dumps(dict(schema='sentinel.b2-drain-image-qualification/1', passed=True,
        scope='EXACT_PREDECESSOR_INTERPRETER_AND_KERNEL_ONLY', predecessor=PREDECESSOR,
        image=IMAGE, compat_sha256=source_sha256, python=sys.version.split()[0],
        successful_barrier=idle, busy_refusal=busy, financial_readiness_proven=False,
        full_old_book_workflow_proven=False, host_restart_policy_proven=False), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
