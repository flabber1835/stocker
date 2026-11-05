"""Tiny owned filesystem observer; authentication stays in its caller."""
from __future__ import annotations

import base64
import json
import math
import os
from pathlib import Path
import select
import subprocess
import sys
import time
from _thread import allocate_lock

MAX_BYTES = 8192
MAX_FRAME_BYTES = 3 * ((MAX_BYTES + 2) // 3 * 4) + 256
OBSERVATION_SECONDS = 2.0
_SCHEMA = 'sentinel.shadow-service-probe/1'
_BLOBS = ('pending', 'status', 'latest_pending')
_UNREAPED = []
MAX_REQUEST_BYTES = 256
MAX_RESPONSE_BYTES = MAX_FRAME_BYTES + 256
_REQUEST_SCHEMA = 'sentinel.shadow-service-probe-request/1'
_RESPONSE_SCHEMA = 'sentinel.shadow-service-probe-response/1'
STAGES = frozenset({'ADMISSION', 'LAUNCH', 'SEND', 'RECEIVE', 'DECODE', 'REAP'})


class ProbeTimeout(TimeoutError):
    """A closed observation stage; never paths, evidence or exception text."""

    def __init__(self, stage):
        if not isinstance(stage, str) or stage not in STAGES:
            raise ValueError('worker snapshot timeout stage refused')
        self.probe_stage = stage
        super().__init__('worker snapshot exceeded its wall-clock budget')


def raw(path):
    with path.open('rb') as stream:
        value = stream.read(MAX_BYTES+1)
    if len(value) > MAX_BYTES:
        raise ValueError('worker status exceeds its bound')
    return value


def optional(path):
    try:
        return raw(path)
    except FileNotFoundError:
        return None


def observe(state_dir: Path):
    critical = state_dir/'shadow-supervisor-critical.json'
    if critical.exists():
        return {'critical': True, 'pending': None, 'status': None, 'latest_pending': None}
    pending = optional(state_dir/'shadow-supervisor-pending.json')
    value = raw(state_dir/'shadow-service-status.json')
    if critical.exists():
        return {'critical': True, 'pending': None, 'status': None, 'latest_pending': None}
    latest = optional(state_dir/'shadow-supervisor-pending.json')
    return {'critical': False, 'pending': pending, 'status': value, 'latest_pending': latest}


def _encode_frame(snapshot):
    if (not isinstance(snapshot, dict) or set(snapshot) != {'critical', *_BLOBS}
            or type(snapshot['critical']) is not bool
            or any(value is not None and (type(value) is not bytes or len(value) > MAX_BYTES)
                   for key, value in snapshot.items() if key != 'critical')):
        raise ValueError('worker snapshot frame refused')
    result = {'schema': _SCHEMA, 'critical': snapshot['critical'], **{
        key: base64.b64encode(snapshot[key]).decode('ascii')
             if snapshot[key] is not None else None for key in _BLOBS}}
    frame = json.dumps(result, separators=(',', ':'), allow_nan=False).encode('ascii')
    if len(frame) > MAX_FRAME_BYTES:
        raise ValueError('worker snapshot frame exceeds its bound')
    return frame


def _decode_frame(frame):
    if len(frame) > MAX_FRAME_BYTES:
        raise ValueError('worker snapshot frame exceeds its bound')
    def unique(items):
        if len(items) != len({key for key, _ in items}):
            raise ValueError('worker snapshot frame has duplicate fields')
        return dict(items)
    value = json.loads(frame, object_pairs_hook=unique)
    if (not isinstance(value, dict) or set(value) != {'schema', 'critical', *_BLOBS}
            or value['schema'] != _SCHEMA or type(value['critical']) is not bool):
        raise ValueError('worker snapshot frame refused')
    result = {'critical': value['critical']}
    for key in _BLOBS:
        blob = value[key]
        if blob is not None:
            if not isinstance(blob, str) or len(blob) > (MAX_BYTES + 2) // 3 * 4:
                raise ValueError('worker snapshot blob exceeds its bound')
            blob = base64.b64decode(blob, validate=True)
            if len(blob) > MAX_BYTES:
                raise ValueError('worker snapshot blob exceeds its bound')
        result[key] = blob
    if (result['critical'] and any(result[key] is not None for key in _BLOBS)
            or not result['critical'] and result['status'] is None):
        raise ValueError('worker snapshot frame is inconsistent')
    return result


def _admit():
    for prior in list(_UNREAPED):
        if prior.poll() is None:
            raise TimeoutError('prior worker snapshot observer is not reaped')
        _UNREAPED.remove(prior)


def _launch(state_dir, parent_pid):
    # The observer needs code and a directory only, never the caller's DSN,
    # receipt key, broker credentials or push credentials. No path resolution
    # or status-file read occurs in this process.
    environment = {'PATH': os.defpath, 'LANG': 'C.UTF-8',
        'PYTHONPATH': str(Path(__file__).parent.parent),
        'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1'}
    return subprocess.Popen([sys.executable, '-B', '-m',
        'sentinel.shadow_service_probe', str(state_dir), str(parent_pid)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        close_fds=True, env=environment)


def _receive(process, deadline):
    descriptor = process.stdout.fileno()
    os.set_blocking(descriptor, False)
    frame = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([descriptor], [], [], remaining)[0]:
            raise TimeoutError('worker snapshot exceeded its wall-clock budget')
        chunk = os.read(descriptor, min(65536, MAX_FRAME_BYTES + 1 - len(frame)))
        if not chunk:
            break
        frame.extend(chunk)
        if len(frame) > MAX_FRAME_BYTES:
            raise ValueError('worker snapshot frame exceeds its bound')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('worker snapshot exceeded its wall-clock budget')
    try:
        process.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        raise TimeoutError('worker snapshot exceeded its wall-clock budget') from None
    if process.returncode != 0:
        raise RuntimeError('worker snapshot observer failed')
    return _decode_frame(bytes(frame))


def _reap(process):
    try:
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            _UNREAPED.append(process)
    finally:
        process.stdout.close()
        if getattr(process, 'stdin', None) is not None:
            process.stdin.close()


def _nonce(value):
    return (isinstance(value, str) and len(value) == 32
            and all(letter in '0123456789abcdef' for letter in value))


def _unique(items):
    if len(items) != len({key for key, _ in items}):
        raise ValueError('worker snapshot exchange has duplicate fields')
    return dict(items)


def _request(nonce):
    if not _nonce(nonce):
        raise ValueError('worker snapshot request nonce refused')
    return json.dumps({'schema': _REQUEST_SCHEMA, 'nonce': nonce},
                      separators=(',', ':')).encode('ascii') + b'\n'


def _decode_request(frame):
    if not frame.endswith(b'\n') or len(frame) > MAX_REQUEST_BYTES:
        raise ValueError('worker snapshot request frame refused')
    value = json.loads(frame, object_pairs_hook=_unique)
    if (not isinstance(value, dict) or set(value) != {'schema', 'nonce'}
            or value['schema'] != _REQUEST_SCHEMA or not _nonce(value['nonce'])):
        raise ValueError('worker snapshot request refused')
    return value['nonce']


def _response(snapshot, nonce):
    if not _nonce(nonce):
        raise ValueError('worker snapshot response nonce refused')
    value = {'schema': _RESPONSE_SCHEMA, 'nonce': nonce,
             'snapshot': json.loads(_encode_frame(snapshot))}
    frame = json.dumps(value, separators=(',', ':'), allow_nan=False).encode('ascii') + b'\n'
    if len(frame) > MAX_RESPONSE_BYTES:
        raise ValueError('worker snapshot response exceeds its bound')
    return frame


def _decode_response(frame, nonce):
    if not frame.endswith(b'\n') or len(frame) > MAX_RESPONSE_BYTES:
        raise ValueError('worker snapshot response frame refused')
    value = json.loads(frame, object_pairs_hook=_unique)
    if (not isinstance(value, dict) or set(value) != {'schema', 'nonce', 'snapshot'}
            or value['schema'] != _RESPONSE_SCHEMA or not _nonce(value['nonce'])):
        raise ValueError('worker snapshot response refused')
    if value['nonce'] != nonce:
        raise ValueError('worker snapshot response nonce refused')
    return _decode_frame(json.dumps(value['snapshot'], separators=(',', ':'),
                                   allow_nan=False).encode('ascii'))


def _launch_observer(state_dir, parent_pid):
    environment = {'PATH': os.defpath, 'LANG': 'C.UTF-8',
        'PYTHONPATH': str(Path(__file__).parent.parent),
        'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1'}
    return subprocess.Popen([sys.executable, '-B', '-m',
        'sentinel.shadow_service_probe', str(state_dir), str(parent_pid), 'serve'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        close_fds=True, env=environment)


def _check_deadline(deadline, stage):
    if time.monotonic() >= deadline:
        raise ProbeTimeout(stage)


def _send_request(process, frame, deadline):
    if len(frame) > MAX_REQUEST_BYTES:
        raise ValueError('worker snapshot request exceeds its bound')
    descriptor = process.stdin.fileno()
    os.set_blocking(descriptor, False)
    sent = 0
    while sent < len(frame):
        remaining = deadline-time.monotonic()
        if remaining <= 0 or not select.select([], [descriptor], [], remaining)[1]:
            raise ProbeTimeout('SEND')
        try:
            count = os.write(descriptor, frame[sent:])
        except BlockingIOError:
            continue
        if count <= 0:
            raise RuntimeError('worker snapshot request pipe closed')
        sent += count
    _check_deadline(deadline, 'SEND')


def _receive_response(process, deadline):
    descriptor = process.stdout.fileno()
    os.set_blocking(descriptor, False)
    frame = bytearray()
    while True:
        remaining = deadline-time.monotonic()
        if remaining <= 0 or not select.select([descriptor], [], [], remaining)[0]:
            raise ProbeTimeout('RECEIVE')
        chunk = os.read(descriptor, min(65536, MAX_RESPONSE_BYTES + 1-len(frame)))
        if not chunk:
            raise RuntimeError('worker snapshot observer closed its response pipe')
        frame.extend(chunk)
        if len(frame) > MAX_RESPONSE_BYTES:
            raise ValueError('worker snapshot response exceeds its bound')
        if b'\n' in frame:
            if frame.find(b'\n') != len(frame)-1:
                raise ValueError('worker snapshot observer sent extra frames')
            return bytes(frame)


def _idle_observer(process):
    if process.poll() is not None:
        raise RuntimeError('worker snapshot observer exited')
    if select.select([process.stdout.fileno()], [], [], 0)[0]:
        raise ValueError('worker snapshot observer sent unsolicited output')


class Observer:
    """One lazy child, fresh bytes per request and a single absolute deadline."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self._owner = os.getpid()
        self._process = None
        self._last_nonce = None
        self._closed = False
        self._lock = allocate_lock()

    def _discard(self):
        process, self._process = self._process, None
        if process is None:
            return
        try:
            _reap(process)
        except BaseException:
            if process.poll() is None and process not in _UNREAPED:
                _UNREAPED.append(process)
            raise

    def read(self, *, timeout: float = OBSERVATION_SECONDS):
        if (type(timeout) not in {int, float} or not math.isfinite(timeout)
                or not 0 < timeout <= OBSERVATION_SECONDS):
            raise ValueError('worker snapshot budget refused')
        deadline = time.monotonic()+timeout
        if self._owner != os.getpid():
            raise RuntimeError('worker snapshot observer ownership refused')
        if not self._lock.acquire(False):
            raise RuntimeError('concurrent worker snapshot observation refused')
        stage = 'ADMISSION'
        try:
            if self._closed:
                raise RuntimeError('worker snapshot observer ownership refused')
            _admit()
            _check_deadline(deadline, stage)
            if self._process is None:
                stage = 'LAUNCH'
                self._process = _launch_observer(self.state_dir, self._owner)
                _check_deadline(deadline, stage)
            stage = 'ADMISSION'
            _idle_observer(self._process)
            nonce = os.urandom(16).hex()
            if nonce == self._last_nonce:
                raise ValueError('worker snapshot request nonce repeated')
            self._last_nonce = nonce
            stage = 'SEND'
            frame = _request(nonce)
            _check_deadline(deadline, stage)
            _send_request(self._process, frame, deadline)
            stage = 'RECEIVE'
            frame = _receive_response(self._process, deadline)
            stage = 'DECODE'
            result = _decode_response(frame, nonce)
            _idle_observer(self._process)
            _check_deadline(deadline, stage)
            return result
        except BaseException as exc:
            self._discard()
            if isinstance(exc, TimeoutError) and not isinstance(exc, ProbeTimeout):
                raise ProbeTimeout(stage) from None
            raise
        finally:
            self._lock.release()

    def close(self):
        if not self._lock.acquire(False):
            raise RuntimeError('active worker snapshot observer cannot close')
        try:
            if self._owner != os.getpid():
                raise RuntimeError('worker snapshot observer ownership refused')
            self._closed = True
            process = self._process
            self._discard()
            if process is not None and process in _UNREAPED:
                raise ProbeTimeout('REAP')
        finally:
            self._lock.release()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _serve(state_dir):
    previous = None
    while True:
        frame = sys.stdin.buffer.readline(MAX_REQUEST_BYTES+1)
        if not frame:
            return 0
        nonce = _decode_request(frame)
        if nonce == previous:
            raise ValueError('worker snapshot request nonce repeated')
        previous = nonce
        sys.stdout.buffer.write(_response(observe(state_dir), nonce))
        sys.stdout.buffer.flush()


def read(state_dir: Path, *, timeout: float = OBSERVATION_SECONDS):
    """Observe without re-importing the heavy caller's multiprocessing main.

    Launch, the bounded frame and child exit all consume the original budget.
    Cleanup is finite; an uninterruptible child prevents a replacement.
    """
    if (type(timeout) not in {int, float} or not math.isfinite(timeout)
            or not 0 < timeout <= OBSERVATION_SECONDS):
        raise ValueError('worker snapshot budget refused')
    _admit()
    deadline = time.monotonic() + timeout
    process = _launch(state_dir, os.getpid())
    try:
        result = _receive(process, deadline)
        if time.monotonic() >= deadline:
            raise TimeoutError('worker snapshot arrived after its original deadline')
        return result
    finally:
        _reap(process)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) not in {2, 3} or len(args) == 3 and args[2] != 'serve':
        return 2
    try:
        parent_pid = int(args[1])
        if parent_pid <= 0:
            return 2
        # The expected parent check also closes death-before-prctl's race.
        # Import only stdlib supervisor code, never the application main.
        from sentinel.supervisor_io import _parent_death
        _parent_death(parent_pid)
        if len(args) == 3:
            return _serve(Path(args[0]))
        frame = _encode_frame(observe(Path(args[0])))
        sys.stdout.buffer.write(frame)
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
