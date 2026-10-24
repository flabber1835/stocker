"""Owned whole-worker faults; no production transport or process fallback."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import multiprocessing
from multiprocessing.managers import BaseManager
import os
from pathlib import Path
import signal
import threading
import time
import uuid

import httpx

from tools.opening_gateway_qualification import Response
from tests.support.current_workflow_faults import DurableWorkflowAlpaca


class ServiceWorkflowAlpaca(DurableWorkflowAlpaca):
    """Independent fsynced provider survives complete worker termination."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mode = 'CONNECTED'
        self.gate = threading.Event()
        self.gate.set()

    def set_mode(self, mode):
        assert mode in {'CONNECTED', 'DISCONNECTED', 'BLOCK_LOOKUP'}
        with self._lock:
            self.mode = mode
            self.faults.append({'point': 'TRANSPORT_MODE', 'mode': mode})
            self._persist()
            if mode == 'BLOCK_LOOKUP':
                self.gate.clear()
            else:
                self.gate.set()

    def request(self, method, url, parameters, callback_pid, worker_pid):
        if method == 'GET':
            with self._lock:
                mode = self.mode
                if mode != 'CONNECTED':
                    self.requests['GET ' + self.path(url)] += 1
                    self.faults.append({
                        'point': 'BLOCKED_LOOKUP' if mode == 'BLOCK_LOOKUP' else 'TRANSPORT_DISCONNECTED',
                        'callback_pid': callback_pid, 'worker_pid': worker_pid,
                        'path': self.path(url),
                    })
                    self._persist()
            if mode == 'BLOCK_LOOKUP':
                assert self.gate.wait(timeout=180), 'bounded private provider gate expired'
                return {'disconnected': True}
            if mode == 'DISCONNECTED':
                return {'disconnected': True}
        return super().request(method, url, parameters, callback_pid)


@contextmanager
def independent_service_provider(*, state_path, clock, **kwargs):
    class Manager(BaseManager):
        pass
    Manager.register('Provider', lambda: ServiceWorkflowAlpaca(state_path=state_path, clock=clock, **kwargs),
        exposed=('request', 'snapshot', 'set_clock', 'set_mode', 'complete_first'))
    manager = Manager(ctx=multiprocessing.get_context('fork'), shutdown_timeout=5)
    manager.start()
    try:
        yield manager.Provider(), manager._process.pid
    finally:
        manager.shutdown()


class ServiceProxyTransport:
    """Local RPC simulates connection loss after acceptance and during reads."""

    def __init__(self, provider, *, worker_pid):
        class Client:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, url, headers=None, params=None):
                value = provider.request('GET', url, dict(params or {}), os.getpid(), worker_pid)
                if value.get('disconnected'):
                    raise httpx.ConnectError('private simulated transport is disconnected')
                return Response(value['payload'], text=value['text'], status=value['status'])

            async def post(self, url, headers=None, json=None):
                value = provider.request('POST', url, dict(json or {}), os.getpid(), worker_pid)
                if value['kill_before_response']:
                    # The order already exists at the independent provider.
                    # The real executor owns UNKNOWN persistence/reconciliation.
                    raise httpx.ReadTimeout('private accepted response was lost')
                return Response(value['payload'], text=value['text'], status=value['status'])

            async def delete(self, *_args, **_kwargs):
                raise AssertionError('whole-worker recovery cannot cancel orders')
        self.AsyncClient = Client


def linux_process_identity(pid):
    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return {'pid': pid, 'state': fields[0], 'parent_pid': int(fields[1]), 'start_ticks': int(fields[19])}


def assert_owned_worker(identity, *, expected_parent_pid, expected_pid, expected_start_ticks):
    """No caller-supplied arbitrary PID can be an owned-worker signal target."""
    assert type(expected_pid) is int and expected_pid > 1
    assert expected_pid != expected_parent_pid == os.getpid()
    assert identity['pid'] == expected_pid
    assert identity['parent_pid'] == expected_parent_pid
    assert identity['state'] not in {'Z', 'X'}
    assert type(identity['start_ticks']) is int and identity['start_ticks'] > 0
    assert type(expected_start_ticks) is int and expected_start_ticks > 0
    assert identity['start_ticks'] == expected_start_ticks


def process_gone_or_zombie(pid, *, start_ticks):
    try:
        found = linux_process_identity(pid)
    except FileNotFoundError:
        return True
    return found['start_ticks'] != start_ticks or found['state'] in {'Z', 'X'}


def wait_until(check, *, seconds, description):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError('private service timeout: ' + description)


@contextmanager
def whole_service_process(factory, *, name, evidence_path):
    """A real complete ProductionAutomation.run process with exact PID ownership."""
    context = multiprocessing.get_context('fork')
    parent_channel, child_channel = context.Pipe(duplex=False)
    stop = context.Event()
    nonce = uuid.uuid4().hex
    parent_pid = os.getpid()

    def run():
        try:
            assert os.getppid() == parent_pid
            service = factory(name)
            identity = linux_process_identity(os.getpid())
            child_channel.send({'nonce': nonce, 'identity': identity})
            child_channel.close()
            count = asyncio.run(service.run(stop=stop,
                clock=lambda: datetime.now(timezone.utc)))
            evidence_path.write_text(json.dumps({'status': 'STOPPED', 'ticks': count}, sort_keys=True))
        except BaseException as exc:
            evidence_path.write_text(json.dumps({'status': 'FAILED', 'type': type(exc).__name__}, sort_keys=True))
            raise

    process = context.Process(target=run, name='sentinel-private-whole-service-' + nonce)
    process.start()
    child_channel.close()
    # Retain ownership before waiting for startup. Even a factory failure or
    # hung startup must remain cleanable through this exact direct child.
    pidfd = os.pidfd_open(process.pid)
    identity = linux_process_identity(process.pid)
    try:
        assert_owned_worker(identity, expected_parent_pid=parent_pid, expected_pid=process.pid,
            expected_start_ticks=identity['start_ticks'])
        assert parent_channel.poll(15), 'owned service did not publish its process identity'
        ready = parent_channel.recv()
        assert ready['nonce'] == nonce
        assert ready['identity']['pid'] == identity['pid']
        assert ready['identity']['parent_pid'] == identity['parent_pid']
        assert ready['identity']['start_ticks'] == identity['start_ticks']
        assert linux_process_identity(process.pid)['start_ticks'] == identity['start_ticks']

        def kill():
            current = linux_process_identity(process.pid)
            assert_owned_worker(current, expected_parent_pid=parent_pid, expected_pid=process.pid,
                expected_start_ticks=identity['start_ticks'])
            signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            process.join(timeout=10)
            assert not process.is_alive() and process.exitcode == -signal.SIGKILL

        yield {'process': process, 'identity': identity, 'kill': kill, 'stop': stop}
    finally:
        stop.set()
        process.join(timeout=12)
        if process.is_alive():
            assert pidfd is not None and identity is not None
            current = linux_process_identity(process.pid)
            assert_owned_worker(current, expected_parent_pid=parent_pid, expected_pid=process.pid,
                expected_start_ticks=identity['start_ticks'])
            signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            process.join(timeout=10)
        assert not process.is_alive()
        if pidfd is not None:
            os.close(pidfd)
        parent_channel.close()
