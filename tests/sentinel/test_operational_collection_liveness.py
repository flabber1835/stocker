"""Actual bounded child progress cannot renew signed operational readiness."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import inspect
import multiprocessing
import os
from pathlib import Path
from threading import Thread
import time

import pytest

from sentinel.panel import projection_service as producer, projection_worker as worker
from sentinel.panel import verification_health
from tests.sentinel.test_operational_projection_service import (  # noqa: F401
    conn, operational, pg, publish, save_financial,
)

pytestmark = pytest.mark.skipif(
    os.name != 'posix', reason='deployed collection uses Linux parent-death supervision')


@dataclass(frozen=True)
class ControlledCollector:
    """Only collection dependencies are isolated; Worker/Collector are real."""
    directory: str
    mode: str = 'blocked'
    removed: bool = False

    def __call__(self, prior_failed):
        from sentinel import shadow_service_probe
        folder = Path(self.directory)
        original = (producer.HEARTBEAT, producer.publish_once, producer.publish_failure,
                    producer.collect_result, shadow_service_probe.Observer)
        producer.HEARTBEAT = folder / 'heartbeat'

        def unavailable(*_args, **_kwargs):
            (folder / 'negative').write_text('NEGATIVE')
            raise RuntimeError('private negative publication unavailable')

        def collect(*_args, **_kwargs):
            (folder / 'entered').write_text('COLLECT')
            if self.mode == 'blocked' or self.mode == 'timeout' and prior_failed:
                while not (folder / 'release').exists():
                    time.sleep(.01)
            raise producer.CollectionSuperseded('private changed subject')

        producer.publish_once, producer.publish_failure = collect, unavailable
        if self.mode == 'observer_failure':
            def refused(_state_dir):
                raise RuntimeError('private observer construction refused')
            shadow_service_probe.Observer = refused
        elif self.mode == 'write_failure':
            producer.HEARTBEAT = folder / 'heartbeat-directory'
        elif self.mode == 'blocked_write' and prior_failed:
            class BlockedWrite:
                def write_text(self, *_args, **_kwargs):
                    (folder / 'entered').write_text('HEARTBEAT_WRITE')
                    while not (folder / 'release').exists():
                        time.sleep(.01)
            producer.HEARTBEAT = BlockedWrite()
        if self.removed:
            source = inspect.getsource(producer.collect_result)
            pulse = "HEARTBEAT.write_text(datetime.now(timezone.utc).isoformat(), encoding='ascii')"
            assert source.count(pulse) == 1
            namespace = dict(vars(producer))
            exec(compile(source.replace(pulse, 'pass'), '<removed-entry-pulse>', 'exec'), namespace)
            producer.collect_result = namespace['collect_result']
        collection = producer.Collector()
        try:
            return collection('private-unused', 'private-owner', self.directory,
                              'private-instance', prior_failed)
        finally:
            collection.close()
            (producer.HEARTBEAT, producer.publish_once, producer.publish_failure,
             producer.collect_result, shadow_service_probe.Observer) = original


def _async_call(collection, prior_failed=False, timeout=20):
    outcome = {}
    def invoke():
        try:
            outcome['result'] = collection.call(prior_failed, timeout=timeout)
        except BaseException as exc:
            outcome['error'] = exc
    thread = Thread(target=invoke, daemon=True)
    thread.start()
    return thread, outcome


def _entered(folder, thread, outcome, *, timeout=20):
    deadline = time.monotonic() + timeout
    while not (folder / 'entered').exists() and time.monotonic() < deadline:
        assert thread.is_alive(), str(outcome)
        time.sleep(.01)
    assert (folder / 'entered').exists(), 'private child never entered controlled work'


def _assert_pulse_precedes_blocked_work(folder, *, removed=False):
    collection = worker.Worker(ControlledCollector(str(folder), removed=removed))
    thread, outcome = _async_call(collection)
    try:
        _entered(folder, thread, outcome)
        assert thread.is_alive() and not outcome, 'collection completed before observation'
        assert (folder / 'heartbeat').exists(), 'actual child entry produced no liveness pulse'
        stamp = datetime.fromisoformat((folder / 'heartbeat').read_text())
        assert timedelta(0) <= datetime.now(timezone.utc) - stamp <= timedelta(seconds=20)
    finally:
        (folder / 'release').touch()
        thread.join(5)
        collection.close()
    assert not thread.is_alive(), 'private collection did not finish bounded cleanup'
    assert outcome == {'result': {'outcome': 'SUPERSEDED'}}
    return stamp


def test_actual_spawned_collector_pulses_before_blocked_collection_returns(tmp_path):
    _assert_pulse_precedes_blocked_work(tmp_path)


def test_removed_child_entry_pulse_is_detected(tmp_path):
    with pytest.raises(AssertionError, match='produced no liveness pulse'):
        _assert_pulse_precedes_blocked_work(tmp_path, removed=True)


class RefusedSerialization:
    def __reduce__(self):
        raise ValueError('private spawn admission refused')


def test_actual_spawn_serialization_refusal_has_no_entry_pulse(tmp_path, monkeypatch):
    monkeypatch.setattr(producer, 'HEARTBEAT', tmp_path / 'heartbeat')
    collection = worker.Worker(RefusedSerialization())
    try:
        with pytest.raises(ValueError, match='spawn admission refused'):
            collection.call(False, timeout=20)
        assert collection.process is None and not producer.HEARTBEAT.exists()
    finally:
        collection.close()


def _park(ready, release):
    ready.set()
    release.wait(30)


def test_live_unreaped_predecessor_refuses_real_successor_admission(tmp_path):
    context = multiprocessing.get_context('spawn')
    ready, release = context.Event(), context.Event()
    previous = context.Process(target=_park, args=(ready, release))
    previous.start()
    collection = worker.Worker(ControlledCollector(str(tmp_path), mode='quick'))
    try:
        assert ready.wait(20), 'private previous worker never started'
        worker._UNREAPED.append(previous)
        with pytest.raises(TimeoutError, match='not reaped'):
            collection.call(False, timeout=20)
        assert collection.process is None
        assert not (tmp_path / 'heartbeat').exists() and not (tmp_path / 'entered').exists()
    finally:
        if previous in worker._UNREAPED:
            worker._UNREAPED.remove(previous)
        release.set()
        previous.join(3)
        if previous.is_alive():
            previous.kill()
            previous.join(3)
        previous.close()
        collection.close()


def test_observer_construction_refusal_occurs_before_child_entry_pulse(tmp_path):
    collection = worker.Worker(ControlledCollector(str(tmp_path), mode='observer_failure'))
    try:
        assert collection.call(False, timeout=20) == {'outcome': 'FAILED', 'type': 'RuntimeError'}
        assert not (tmp_path / 'heartbeat').exists() and not (tmp_path / 'entered').exists()
    finally:
        collection.close()


def test_heartbeat_write_failure_never_enters_positive_collection(tmp_path):
    (tmp_path / 'heartbeat-directory').mkdir()
    collection = worker.Worker(ControlledCollector(str(tmp_path), mode='write_failure'))
    try:
        assert collection.call(False, timeout=20) == {'outcome': 'FAILED', 'type': 'IsADirectoryError'}
        assert (tmp_path / 'negative').read_text() == 'NEGATIVE'
        assert not (tmp_path / 'heartbeat').exists() and not (tmp_path / 'entered').exists()
    finally:
        collection.close()


@pytest.mark.parametrize('mode', ['timeout', 'blocked_write'])
def test_original_call_deadline_bounds_work_and_heartbeat_write(tmp_path, mode):
    collection = worker.Worker(ControlledCollector(str(tmp_path), mode=mode))
    try:
        # Warm the real spawned worker, then give only this invocation a short
        # private deadline; production's existing 20-second constant is unchanged.
        assert collection.call(False, timeout=20) == {'outcome': 'SUPERSEDED'}
        (tmp_path / 'entered').unlink()
        old = (tmp_path / 'heartbeat').read_text()
        (tmp_path / 'heartbeat').unlink()
        started = time.monotonic()
        with pytest.raises(TimeoutError, match='wall-clock'):
            collection.call(True, timeout=.5)
        assert time.monotonic() - started < 3
        assert collection.process is None
        assert (tmp_path / 'entered').read_text() == (
            'HEARTBEAT_WRITE' if mode == 'blocked_write' else 'COLLECT')
        if mode == 'blocked_write':
            assert not (tmp_path / 'heartbeat').exists()
        else:
            stamp = datetime.fromisoformat((tmp_path / 'heartbeat').read_text())
            assert stamp >= datetime.fromisoformat(old)
            verifier = tmp_path / 'verifier'
            verifier.write_text(stamp.isoformat())
            assert verification_health.health(verifier_path=verifier,
                operational_path=tmp_path / 'heartbeat', now=stamp+timedelta(seconds=45)) == 0
            assert verification_health.health(verifier_path=verifier,
                operational_path=tmp_path / 'heartbeat',
                now=stamp+timedelta(seconds=45, microseconds=1)) == 1
    finally:
        collection.close()


def test_child_pulse_cannot_mask_missing_or_expired_main_owner(tmp_path):
    operational = tmp_path / 'operational'
    verifier = tmp_path / 'verifier'
    now = datetime.now(timezone.utc)
    operational.write_text(now.isoformat())
    assert verification_health.health(verifier_path=verifier, operational_path=operational, now=now) == 1
    verifier.write_text((now-timedelta(seconds=46)).isoformat())
    assert verification_health.health(verifier_path=verifier, operational_path=operational, now=now) == 1


def test_entry_pulse_does_not_renew_signed_negative_financial_or_dashboard_evidence(
        operational, tmp_path, monkeypatch):
    from sentinel.panel import model
    conn, owner, condition = operational
    condition['financial'] = True
    save_financial(conn, 'SHADOW')
    save_financial(conn, 'PAPER')
    publish(operational)
    save_financial(conn, 'PAPER', [model.paper_reconciliation_row(state='MISMATCH')])
    before = producer.read(conn.info.dsn)
    assert before.row('paper_reconciliation').status == model.FAIL
    def retained():
        rows = conn.execute('SELECT scope,subject_sha256,observed_at,valid_until,envelope,signature '
            'FROM sentinel_operational_verification_receipts ORDER BY scope').fetchall()
        conn.rollback()
        return rows
    original = retained()
    heartbeat = tmp_path / 'heartbeat'
    monkeypatch.setattr(producer, 'HEARTBEAT', heartbeat)
    def superseded(*_args, **_kwargs):
        raise producer.CollectionSuperseded('private selected input changed')
    monkeypatch.setattr(producer, 'publish_once', superseded)
    assert producer.collect_result(conn.info.dsn, owner, str(tmp_path), 'private-instance') == {
        'outcome': 'SUPERSEDED'}
    assert heartbeat.exists() and retained() == original
    after = producer.read(conn.info.dsn)
    assert after.row('paper_reconciliation') == before.row('paper_reconciliation')
    assert after.row('paper_reconciliation').status == model.FAIL
    assert after.observation_valid_until == before.observation_valid_until
