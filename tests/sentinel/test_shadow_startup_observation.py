"""Coherent native snapshots across the actual durable-arm/status handoff."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
import select
import subprocess
import sys
import time

import pytest

from sentinel import shadow_service_probe as probe, shadow_service_status as status
from sentinel import shadow_supervisor as supervisor
from tests.sentinel.test_shadow_worker_monitoring import A, DSN, state  # noqa: F401

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='native Linux process ownership')


def _barrier_child(monkeypatch, descriptor, *, remove_coherence=False, reusable=True):
    """Signal after the first real file capture, outside the response channel."""
    program = '''
import os,sys
from sentinel import shadow_service_probe as probe
original = probe.observe
notified = False
def captured(state):
    global notified
    value = original(state)
    if not notified:
        os.write(int(sys.argv[1]), b'1')
        notified = True
    return value
probe.observe = captured
if sys.argv[2] == 'broken':
    probe._observe_coherent = probe.observe
raise SystemExit(probe.main(sys.argv[3:]))
'''
    children = []
    def launch(directory, parent):
        child = subprocess.Popen([sys.executable, '-B', '-c', program,
            str(descriptor), 'broken' if remove_coherence else 'normal',
            str(directory), str(parent), *(['serve'] if reusable else [])], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, pass_fds=(descriptor,))
        children.append(child)
        return child
    monkeypatch.setattr(probe, '_launch_observer' if reusable else '_launch', launch)
    return children


def _startup_cycle(state, monkeypatch, *, remove_coherence=False, critical=False, reusable=True):
    publish_at = datetime.now(timezone.utc)
    status.publish(state/status.CRITICAL_NAME, A, now=publish_at)
    attempt = supervisor._arm_worker(os.getpid())
    worker = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(30)'])
    read_fd, write_fd = os.pipe()
    children = _barrier_child(monkeypatch, write_fd,
        remove_coherence=remove_coherence, reusable=reusable)
    try:
        with probe.Observer(state) as owner, ThreadPoolExecutor(max_workers=1) as threads:
            result = threads.submit(owner.read if reusable else lambda: probe.read(state))
            assert select.select([read_fd], [], [], 1.5)[0], 'native capture never started'
            assert os.read(read_fd, 1) == b'1'
            # The actual reader has now captured the durable new attempt plus
            # the previous, authenticated idle observation.
            if critical:
                (state/status.CRITICAL_NAME).write_text('qualification integrity fence')
            else:
                supervisor.shadow_worker_liveness.record(
                    attempt, os.getpid(), worker.pid, time.monotonic()+30)
                publish_at = datetime.now(timezone.utc)
                status.publish(state/status.CRITICAL_NAME, A, now=publish_at)
            snapshot = result.result(timeout=2.5)
            try:
                decoded = status.decode_probe(snapshot, DSN)
            except ValueError as exc:
                raise AssertionError('normal startup returned an incoherent observation') from exc
            if critical:
                assert decoded == {'state': 'FENCED', 'reason': 'CRITICAL_LATCH'}
            else:
                assert decoded['reason'] == 'ACTIVE_WORKER'
                assert decoded['attempt_id'] == attempt
                assert decoded['observed_at'] == publish_at
                assert snapshot['pending'] == snapshot['latest_pending']
        assert len(children) == 1 and children[0].poll() is not None
    finally:
        os.close(read_fd)
        os.close(write_fd)
        worker.terminate()
        worker.wait(timeout=5)
        supervisor._clear_worker()


@pytest.mark.parametrize('reusable', [False, True])
def test_actual_durable_arm_and_native_reader_return_only_the_new_matching_status(state, monkeypatch, reusable):
    _startup_cycle(state, monkeypatch, reusable=reusable)


@pytest.mark.parametrize('reusable', [False, True])
def test_removed_coherent_collection_reproduces_the_startup_failure(state, monkeypatch, reusable):
    with pytest.raises(AssertionError, match='normal startup returned an incoherent observation'):
        _startup_cycle(state, monkeypatch, remove_coherence=True, reusable=reusable)


def test_critical_marker_interrupts_a_startup_coherence_wait(state, monkeypatch):
    _startup_cycle(state, monkeypatch, critical=True)


@pytest.mark.parametrize('reusable', [False, True])
def test_persistent_mismatch_keeps_the_original_budget_and_reaps_the_child(state, monkeypatch, reusable):
    status.publish(state/status.CRITICAL_NAME, A)
    supervisor._arm_worker(os.getpid())
    children = []
    name = '_launch_observer' if reusable else '_launch'
    original = getattr(probe, name)
    def launch(*args):
        child = original(*args)
        children.append(child)
        return child
    monkeypatch.setattr(probe, name, launch)
    started = time.monotonic()
    with probe.Observer(state) as owner:
        with pytest.raises(TimeoutError):
            (owner.read(timeout=.5) if reusable else probe.read(state, timeout=.5))
        assert owner._process is None
    assert time.monotonic()-started < 1.5
    assert len(children) == 1 and children[0].poll() is not None


def test_attempt_changed_during_capture_is_recollected_from_the_beginning(state, monkeypatch):
    status.publish(state/status.CRITICAL_NAME, A)
    idle = probe.observe(state)
    supervisor._arm_worker(os.getpid())
    pending = probe.observe(state)
    changed = {**idle, 'latest_pending': pending['latest_pending']}
    samples = iter((changed, pending, idle))
    calls = []
    def capture(directory):
        calls.append(directory)
        return next(samples)
    monkeypatch.setattr(probe, 'observe', capture)
    assert probe._observe_coherent(state) == idle
    assert calls == [state, state, state]


@pytest.mark.parametrize('damage', ['malformed', 'negative', 'critical'])
def test_collection_never_retries_malformed_or_negative_evidence(state, monkeypatch, damage):
    status.publish(state/status.CRITICAL_NAME, A)
    supervisor._arm_worker(os.getpid())
    snapshot = probe.observe(state)
    if damage == 'malformed':
        snapshot['status'] = b'{invalid evidence'
    elif damage == 'negative':
        status.publish(state/status.CRITICAL_NAME, A, stopped=True)
        snapshot = probe.observe(state)
    else:
        snapshot = dict(critical=True, pending=None, status=None, latest_pending=None)
    calls = []
    def capture(_):
        calls.append(True)
        assert len(calls) == 1, 'negative or malformed evidence was retried'
        return snapshot
    monkeypatch.setattr(probe, 'observe', capture)
    assert probe._observe_coherent(state) == snapshot


def test_canonical_authentication_still_rejects_a_coherent_but_forged_status(state):
    status.publish(state/status.CRITICAL_NAME, A)
    snapshot = probe.observe(state)
    wrapped = json.loads(snapshot['status'])
    wrapped['hmac_sha256'] = '0'*64
    snapshot['status'] = json.dumps(wrapped).encode()
    assert not probe._changing_attempt(snapshot)
    with pytest.raises(ValueError, match='authentication failed'):
        status.decode_probe(snapshot, DSN)
