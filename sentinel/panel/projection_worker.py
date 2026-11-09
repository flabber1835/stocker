"""One reusable spawned collector, with a fresh finite deadline for each call."""
from __future__ import annotations

import json
import multiprocessing
import os
import time
from datetime import datetime, timedelta

from sentinel import supervisor_io

MAX_BYTES = 2048
_UNREAPED = []


def _result(value):
    if (not isinstance(value, dict) or value.get('outcome') not in {
            'PUBLISHED', 'SUPERSEDED', 'FAILED'}
            or set(value) - {'outcome', 'valid_until', 'type'}
            or any(not isinstance(item, str) or len(item) > 128 for item in value.values())):
        raise ValueError('operational worker protocol refused')
    if value['outcome'] == 'PUBLISHED':
        try:
            expiry = datetime.fromisoformat(value['valid_until'])
        except (KeyError, ValueError):
            raise ValueError('operational worker expiry refused') from None
        if expiry.utcoffset() != timedelta(0):
            raise ValueError('operational worker expiry has no UTC scope')
    elif 'valid_until' in value:
        raise ValueError('unpublished operational worker result has expiry')
    raw = json.dumps(value, allow_nan=False, separators=(',', ':')).encode('ascii')
    if len(raw) > MAX_BYTES:
        raise ValueError('operational worker result exceeds bound')
    return raw


def _serve(channel, function, args, parent_pid):
    supervisor_io._parent_death(parent_pid)
    try:
        try:
            prepare = getattr(function, 'prepare', None)
            if prepare is not None:
                prepare()
        except Exception as exc:
            channel.send_bytes(b'F'+type(exc).__name__.encode('ascii')[:128])
            return
        channel.send_bytes(b'R')
        while True:
            command = channel.recv_bytes(maxlength=1)
            if command == b'S':
                return
            if command not in {b'0', b'1'}:
                raise ValueError('operational worker command refused')
            try:
                value = function(*args, command == b'1')
            except Exception as exc:
                value = {'outcome':'FAILED', 'type':type(exc).__name__}
            # A malformed protocol result ends this child. It cannot be treated
            # as an ordinary source failure and reused for another collection.
            result = _result(value)
            channel.send_bytes(result)
    finally:
        try:
            # Stateful collector callables explicitly own their dependency
            # observers. A forced outer exit is covered by parent-death guards.
            close = getattr(function, 'close', None)
            if close is not None:
                close()
        finally:
            channel.close()


class Worker:
    def __init__(self, function, *args):
        self.function = function
        self.args = args
        self.process = None
        self.channel = None

    def start(self, *, timeout):
        """Bound cold initialization separately when explicitly requested.

        READY attests only dependency initialization, never source/financial
        currentness. A direct call still charges implicit startup to its budget.
        """
        if self.process is not None:
            return
        started = time.monotonic()
        try:
            self._start()
            remaining = timeout-(time.monotonic()-started)
            if remaining <= 0 or not self.channel.poll(remaining):
                raise TimeoutError('operational worker initialization exceeded its wall-clock budget')
            if self.channel.recv_bytes(maxlength=129) != b'R':
                raise ValueError('operational worker initialization refused')
            if time.monotonic()-started >= timeout:
                raise TimeoutError('operational worker initialized after deadline')
        except BaseException:
            self.close()
            raise

    def _start(self):
        for previous in list(_UNREAPED):
            if previous.is_alive():
                raise TimeoutError('prior operational worker is not reaped')
            previous.join(timeout=0)
            previous.close()
            _UNREAPED.remove(previous)
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe(duplex=True)
        process = context.Process(target=_serve,
            args=(child, self.function, self.args, os.getpid()))
        try:
            process.start()
        except BaseException:
            parent.close()
            child.close()
            raise
        child.close()
        self.process, self.channel = process, parent

    def call(self, prior_failed, *, timeout):
        started = time.monotonic()
        if self.process is None:
            self.start(timeout=timeout)
        try:
            self.channel.send_bytes(b'1' if prior_failed else b'0')
            remaining = timeout-(time.monotonic()-started)
            if remaining <= 0 or not self.channel.poll(remaining):
                raise TimeoutError('operational collection exceeded its wall-clock budget')
            raw = self.channel.recv_bytes(maxlength=MAX_BYTES)
            value = json.loads(raw)
            _result(value)
            if time.monotonic()-started >= timeout:
                raise TimeoutError('operational collection result arrived after deadline')
            return value
        except BaseException:
            self.close()
            raise

    def close(self):
        process, channel = self.process, self.channel
        self.process, self.channel = None, None
        if process is None:
            return
        try:
            if process.is_alive():
                try:
                    channel.send_bytes(b'S')
                except (OSError, EOFError):
                    pass
                process.join(timeout=.25)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            if process.is_alive():
                _UNREAPED.append(process)
            else:
                process.join(timeout=0)
                process.close()
        finally:
            channel.close()
