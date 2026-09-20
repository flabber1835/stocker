"""Short, killable dependency observations for single-threaded supervisors."""
from __future__ import annotations

import multiprocessing
import os
import signal
import sys

_UNREAPED = []


def _call(channel, function, args):
    try:
        value = function(*args)
        channel.send(('ok', value))
    except Exception as exc:
        channel.send(('error', type(exc).__name__ + ': ' + str(exc)[:1000]))
    finally:
        channel.close()


def run(function, *args, timeout=1.0):
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
    context = multiprocessing.get_context('fork')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_call, args=(sender, function, args))
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
            raise RuntimeError(value)
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


def report(message, *, file=None, flush=True):
    """Best-effort diagnostics cannot block enforcement on a full log pipe."""
    del file, flush
    try:
        run(_stderr, str(message), timeout=0.25)
    except Exception:
        pass
