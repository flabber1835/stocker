"""Reusable collection retains only process-local projections, with finite IPC."""
from datetime import datetime, timedelta, timezone
import json
import multiprocessing
import os
from pathlib import Path
import signal
from types import SimpleNamespace
import time

import pytest

from sentinel import supervisor_io
from sentinel.panel import projection_worker as worker

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='deployed collector uses Linux parent-death supervision')
PRIVATE = 'postgresql://fixture:private-password@private-host/private-account'
_LOADS = 0


def published(value):
    return dict(outcome='PUBLISHED', valid_until=(
        datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat(), type=value)


def memo_probe(filename, prior_failed):
    """Only canonical authority loading is a named isolated fixture here."""
    from sentinel import dual_plan_authority
    from sentinel.panel import intent_memo
    global _LOADS
    current = json.loads(Path(filename).read_text())
    original_version, original_load = intent_memo.row_version, dual_plan_authority.load_authority
    def load(*args, **kwargs):
        global _LOADS
        _LOADS += 1
        return dict(plan_id='fixture-plan', authority_sha256='a'*64,
            plan_fingerprint='b'*64, decision_session='2031-01-01', tickers={},
            broker_observation=dict(completeness='COMPLETE', account_identity=['fixture'],
                observed_at='2031-01-01T00:00:00+00:00', positions=[]))
    try:
        intent_memo.row_version = lambda *args: ('2031-01-01', 'fixture',
            str(current['version']), '(0,1)', 'a'*64)
        dual_plan_authority.load_authority = load
        projection = intent_memo.memo.read(SimpleNamespace(info=SimpleNamespace(dsn='credential-free-fixture')),
                                           plan_id='fixture-plan')
        assert 'authority_sha256' not in projection
    finally:
        intent_memo.row_version, dual_plan_authority.load_authority = original_version, original_load
    # Mutable evidence is independently observed for every collection. It is
    # never borrowed from the dated-intent memo or a previous whole result.
    return published(f'{os.getpid()}:{_LOADS}:{id(intent_memo.memo)}:'
                     +current['mutable']+':'+str(prior_failed))


def timeout_probe(prior_failed):
    if prior_failed:
        time.sleep(60)
    return published(str(os.getpid()))


def private_exception(prior_failed):
    if prior_failed:
        raise ValueError(PRIVATE)
    return published(str(os.getpid()))


def protocol_probe(filename, prior_failed):
    mode = Path(filename).read_text()
    Path(filename+'.pid').write_text(str(os.getpid()))
    if mode == 'oversized':
        return {'outcome': 'PUBLISHED', 'type': 'x'*(worker.MAX_BYTES+1)}
    if mode == 'unknown':
        return {'outcome': 'PUBLISHED', 'unexpected': 'field'}
    if mode == 'nonstring':
        return {'outcome': 'FAILED', 'type': 1}
    if mode == 'outcome':
        return {'outcome': 'invented'}
    if mode == 'missing_expiry':
        return {'outcome': 'PUBLISHED', 'type': 'fixture'}
    if mode == 'naive_expiry':
        return {'outcome': 'PUBLISHED', 'valid_until': '2031-01-01T00:00:00'}
    if mode == 'failed_expiry':
        return {**published('ValueError'), 'outcome': 'FAILED'}
    return published(str(os.getpid()))


def oversized_wire(channel, function, args, parent_pid):
    supervisor_io._parent_death(parent_pid)
    try:
        channel.recv_bytes(maxlength=1)
        channel.send_bytes(b'x'*(worker.MAX_BYTES+1))
    finally:
        channel.close()


def malformed_wire(channel, function, args, parent_pid):
    supervisor_io._parent_death(parent_pid)
    try:
        channel.recv_bytes(maxlength=1)
        channel.send_bytes(b'not-json')
    finally:
        channel.close()


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    status = Path('/proc')/str(pid)/'stat'
    if status.exists():
        # A dead parent's child may wait for container PID1 to reap its zombie.
        return status.read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    return True


def test_two_calls_keep_same_pid_and_intent_memo_but_reobserve_mutable_facts(tmp_path):
    filename = tmp_path/'mutable.json'
    filename.write_text(json.dumps({'version': 1, 'mutable': 'first'}))
    collection = worker.Worker(memo_probe, str(filename))
    try:
        first = collection.call(False, timeout=20)
        filename.write_text(json.dumps({'version': 1, 'mutable': 'second'}))
        second = collection.call(True, timeout=20)
        first_pid, first_loads, memo_id, first_mutable, first_flag = first['type'].split(':')
        second_pid, second_loads, second_memo, second_mutable, second_flag = second['type'].split(':')
        assert first_pid == second_pid and memo_id == second_memo
        assert first_loads == second_loads == '1'
        assert (first_mutable, first_flag) == ('first', 'False')
        assert (second_mutable, second_flag) == ('second', 'True')
        filename.write_text(json.dumps({'version': 2, 'mutable': 'third'}))
        third = collection.call(False, timeout=20)
        assert third['type'].split(':') == [first_pid, '2', memo_id, 'third', 'False']
        pid = int(first_pid)
    finally:
        collection.close()
    assert not alive(pid) and collection.process is None


def test_hung_call_is_killed_and_reaped_then_next_call_gets_a_fresh_pid():
    collection = worker.Worker(timeout_probe)
    try:
        first_pid = int(collection.call(False, timeout=20)['type'])
        started = time.monotonic()
        with pytest.raises(TimeoutError, match='wall-clock'):
            collection.call(True, timeout=.15)
        assert time.monotonic()-started < 3
        assert collection.process is None and not alive(first_pid)
        next_pid = int(collection.call(False, timeout=20)['type'])
        assert next_pid != first_pid
    finally:
        collection.close()
    assert not alive(next_pid)


@pytest.mark.parametrize('mode', ['oversized', 'unknown', 'nonstring', 'outcome',
                                  'missing_expiry', 'naive_expiry', 'failed_expiry'])
def test_invalid_child_metadata_refuses_reaps_and_does_not_poison_successor(tmp_path, mode):
    filename = tmp_path/'mode'
    filename.write_text(mode)
    collection = worker.Worker(protocol_probe, str(filename))
    try:
        with pytest.raises((OSError, EOFError, ValueError)):
            collection.call(False, timeout=20)
        rejected_pid = int(Path(str(filename)+'.pid').read_text())
        assert collection.process is None and not alive(rejected_pid)
        filename.write_text('valid')
        next_pid = int(collection.call(False, timeout=20)['type'])
        assert next_pid != rejected_pid
    finally:
        collection.close()


@pytest.mark.parametrize('server', [oversized_wire, malformed_wire])
def test_parent_enforces_wire_bound_and_json_schema_before_acceptance(monkeypatch, server):
    monkeypatch.setattr(worker, '_serve', server)
    collection = worker.Worker(timeout_probe)
    try:
        with pytest.raises((OSError, EOFError, ValueError)):
            collection.call(False, timeout=20)
        assert collection.process is None
    finally:
        collection.close()


def test_child_exception_preserves_type_and_hides_private_message(capfd):
    collection = worker.Worker(private_exception)
    try:
        first_pid = collection.call(False, timeout=20)['type']
        failed = collection.call(True, timeout=20)
        assert failed == {'outcome': 'FAILED', 'type': 'ValueError'}
        assert PRIVATE not in json.dumps(failed)
        assert collection.call(False, timeout=20)['type'] == first_pid
    finally:
        collection.close()
    captured = capfd.readouterr()
    assert PRIVATE not in captured.out and PRIVATE not in captured.err


def parent_death_probe(filename, prior_failed):
    if prior_failed:
        Path(filename+'.active').write_text(str(os.getpid()))
        time.sleep(60)
    return published(str(os.getpid()))


def serve_without_parent_death(channel, function, args, parent_pid):
    """Executed removed-kernel-guard control, still using the real worker IPC."""
    try:
        while True:
            command = channel.recv_bytes(maxlength=1)
            if command == b'S':
                return
            channel.send_bytes(worker._result(function(*args, command == b'1')))
    finally:
        channel.close()


def parent_with_worker(filename, protected):
    if not protected:
        worker._serve = serve_without_parent_death
    collection = worker.Worker(parent_death_probe, filename)
    result = collection.call(False, timeout=20)
    Path(filename).write_text(result['type'])
    collection.call(True, timeout=60)


def assert_parent_death_kills_blocked_worker(tmp_path, protected=True):
    filename = tmp_path/'worker.pid'
    parent = multiprocessing.get_context('spawn').Process(target=parent_with_worker,
                                                        args=(str(filename), protected))
    parent.start()
    child_pid = None
    try:
        until = time.monotonic()+20
        active = Path(str(filename)+'.active')
        while not active.exists() and time.monotonic() < until:
            assert parent.is_alive(), 'collector parent exited before readiness'
            time.sleep(.02)
        assert filename.exists() and active.exists(), 'collector did not enter its owned blocked call'
        child_pid = int(filename.read_text())
        assert active.read_text() == str(child_pid)
        assert alive(child_pid)
        parent.kill()
        parent.join(3)
        assert not parent.is_alive()
        until = time.monotonic()+3
        while alive(child_pid) and time.monotonic() < until:
            time.sleep(.02)
        assert not alive(child_pid), 'persistent collector survived its owner'
    finally:
        if parent.is_alive():
            parent.kill()
            parent.join(3)
        parent.close()
        if child_pid is not None and alive(child_pid):
            os.kill(child_pid, signal.SIGKILL)


def test_parent_death_kills_persistent_worker_during_a_blocked_call(tmp_path):
    assert_parent_death_kills_blocked_worker(tmp_path)


def test_removed_parent_death_guard_is_detected(tmp_path):
    with pytest.raises(AssertionError, match='survived its owner'):
        assert_parent_death_kills_blocked_worker(tmp_path, protected=False)
