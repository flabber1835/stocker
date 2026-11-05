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

MAX_BYTES = 8192
MAX_FRAME_BYTES = 3 * ((MAX_BYTES + 2) // 3 * 4) + 256
OBSERVATION_SECONDS = 2.0
_SCHEMA = 'sentinel.shadow-service-probe/1'
_BLOBS = ('pending', 'status', 'latest_pending')
_UNREAPED = []


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
    if len(args) != 2:
        return 2
    try:
        parent_pid = int(args[1])
        if parent_pid <= 0:
            return 2
        # The expected parent check also closes death-before-prctl's race.
        # Import only stdlib supervisor code, never the application main.
        from sentinel.supervisor_io import _parent_death
        _parent_death(parent_pid)
        frame = _encode_frame(observe(Path(args[0])))
        sys.stdout.buffer.write(frame)
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
