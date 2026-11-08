"""Short, killable dependency observations for single-threaded supervisors."""
from __future__ import annotations

import multiprocessing
import errno
import json
import math
import os
import re
import signal
import stat
import sys
import time
from typing import TypedDict

_UNREAPED = []
MAX_RECORD_BYTES = 4096
_STAGES = frozenset({'ARM', 'ACTIVE_PROOF', 'SPAWN', 'ACK', 'OWNERSHIP', 'OWNED_RUN',
                     'HEARTBEAT', 'SNAPSHOT', 'CONFIRMATION', 'IDLE_STALL',
                     'CALLBACK_DEADLINE', 'DATABASE_DEADLINE'})
_OUTCOMES = frozenset({'BEGIN', 'ACCEPTED', 'FAILED', 'TERMINATING', 'RECOVERED'})


class ErrorDiagnostic(TypedDict):
    exception_type: str
    errno: int | None
    sqlstate: str | None


def _validate_diagnostic(value) -> ErrorDiagnostic:
    if (not isinstance(value, dict) or set(value) != {'exception_type', 'errno', 'sqlstate'}
            or not isinstance(value['exception_type'], str)
            or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', value['exception_type']) is None
            or value['errno'] is not None and not (
                type(value['errno']) is int and 0 <= value['errno'] <= 4095)
            or value['sqlstate'] is not None and not (
                isinstance(value['sqlstate'], str)
                and re.fullmatch(r'[A-Z0-9]{5}', value['sqlstate']))):
        raise RuntimeError('supervisor dependency diagnostic is malformed')
    return dict(value)


class DependencyError(RuntimeError):
    """Original child type survives IPC without its private exception values."""

    def __init__(self, diagnostic: ErrorDiagnostic):
        self.diagnostic = _validate_diagnostic(diagnostic)
        suffix = (' (statement timeout/cancellation)' if diagnostic['sqlstate'] == '57014'
                  else ' (lock timeout/unavailable)' if diagnostic['sqlstate'] == '55P03' else '')
        super().__init__('supervisor dependency failed: '+diagnostic['exception_type']+suffix)


def error_diagnostic(error: BaseException) -> ErrorDiagnostic:
    if isinstance(error, DependencyError):
        return _validate_diagnostic(error.diagnostic)
    kind = type(error).__name__
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', kind) is None:
        kind = 'Exception'
    number = getattr(error, 'errno', None)
    state = getattr(error, 'sqlstate', None)
    return _validate_diagnostic(dict(exception_type=kind,
        errno=number if type(number) is int and 0 <= number <= 4095 else None,
        sqlstate=state if isinstance(state, str) and re.fullmatch(r'[A-Z0-9]{5}', state) else None))


def _parent_death(parent_pid):
    # Docker can kill the probe parent before its observer cleanup executes.
    # Set the kernel boundary before opening dependencies; close the fork race.
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), 'dependency parent-death signal unavailable')
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), signal.SIGKILL)


def _call(channel, function, args, parent_pid):
    try:
        _parent_death(parent_pid)
        value = function(*args)
        channel.send(('ok', value))
    except Exception as exc:
        channel.send(('error', error_diagnostic(exc)))
    finally:
        channel.close()


def run(function, *args, timeout=1.0, start_method='fork'):
    """Do not let a silent server socket disable the parent's kill deadline.

    Callers return small fixed-shape rows or None. The child finishes sending
    before we read its pipe, so an incomplete IPC frame cannot block the parent.
    No connection is created in the parent or shared with the supervised worker.
    """
    # SIGKILL cannot immediately reap uninterruptible kernel I/O. Do not grow
    # an unbounded population of observers on a failed filesystem.
    for prior in list(_UNREAPED):
        if prior.is_alive():
            raise TimeoutError('prior supervisor dependency observer is not reaped')
        prior.join(timeout=0)
        prior.close()
        _UNREAPED.remove(prior)
    # Threaded HTTP callers use spawn: inheriting another thread's locks or
    # connection state through fork can deadlock the observer itself.
    context = multiprocessing.get_context(start_method)
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_call, args=(sender, function, args, os.getpid()))
    try:
        process.start()
        sender.close()
        process.join(timeout)
        if process.is_alive():
            os.kill(process.pid, signal.SIGKILL)
            process.join(timeout=1)
            raise TimeoutError('supervisor dependency observation exceeded its wall-clock budget')
        if not receiver.poll():
            raise RuntimeError('supervisor dependency observer exited without a result')
        status, value = receiver.recv()
        if status != 'ok':
            raise DependencyError(value)
        return value
    finally:
        sender.close()
        receiver.close()
        if process.pid is not None:
            if process.is_alive():
                os.kill(process.pid, signal.SIGKILL)
                process.join(timeout=1)
            if not process.is_alive():
                process.close()
            else:
                _UNREAPED.append(process)


def _stderr(message):
    print(message, file=sys.stderr, flush=True)


def _pipe_report(message: str) -> bool | None:
    """One nonblocking pipe write; None selects the finite non-pipe fallback."""
    try:
        descriptor = sys.stderr.fileno()
        if not stat.S_ISFIFO(os.fstat(descriptor).st_mode):
            return None
        maximum = min(MAX_RECORD_BYTES, os.fpathconf(descriptor, 'PC_PIPE_BUF'))
    except (AttributeError, OSError, ValueError):
        return None
    raw = message.encode('utf-8', errors='replace')
    if len(raw)+1 > maximum:
        return False
    try:
        # Reopening creates an independent open-file description. Setting
        # O_NONBLOCK on dup() or the inherited fd would also affect descendants.
        reopened = os.open(f'/proc/self/fd/{descriptor}',
                           os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as exc:
        return None if exc.errno in {errno.ENOENT, errno.EACCES, errno.ENOTDIR} else False
    try:
        return os.write(reopened, raw+b'\n') == len(raw)+1
    except OSError:
        return False
    finally:
        os.close(reopened)


def report(message, *, file=None, flush=True):
    """Best-effort diagnostics cannot block enforcement on a full log pipe."""
    del file, flush
    try:
        message = str(message)
        if len(message.encode('utf-8', errors='replace')) >= MAX_RECORD_BYTES:
            return False
        delivered = _pipe_report(message)
        if delivered is not None:
            return delivered
        run(_stderr, str(message), timeout=0.25)
        return True
    except Exception:
        return False


def report_event(component: str, stage: str, outcome: str, *, error=None,
                 context: dict | None = None, immediate: bool = True) -> bool:
    """Closed diagnostic metadata cannot become financial or liveness evidence."""
    try:
        if component not in {'shadow', 'automation'} or stage not in _STAGES or outcome not in _OUTCOMES:
            return False
        facts = dict(context or {})
        for key, value in facts.items():
            if key in {'incarnation', 'attempt'}:
                valid = isinstance(value, str) and re.fullmatch(r'[a-f0-9]{32}', value)
            elif key in {'child_pid', 'supervisor_pid'}:
                valid = type(value) is int and value > 0
            elif key == 'state':
                valid = value is None or isinstance(value, str) and re.fullmatch(r'[A-Z_]{1,64}', value)
            elif key in {'started', 'completed', 'elapsed_seconds', 'decision_at',
                         'heartbeat_age_seconds', 'lease_seconds', 'worker_started'}:
                valid = value is None or type(value) in {float, int} and math.isfinite(value)
            else:
                valid = False
            if not valid:
                return False
        value = dict(schema='sentinel.supervisor-diagnostic/1', component=component,
                     stage=stage, outcome=outcome, pid=os.getpid(),
                     monotonic_at=time.monotonic(), context=facts,
                     error=error_diagnostic(error) if error is not None else None)
        message = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if immediate:
            return _pipe_report(message) is True
        return report(message)
    except Exception:
        return False
