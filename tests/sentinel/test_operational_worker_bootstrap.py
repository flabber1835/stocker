"""Cold dependencies cannot consume/restart short admitted publication work."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import os
from pathlib import Path
import time
from textwrap import dedent
from threading import Event

import pytest

from sentinel.panel import model, presentation, projection_worker as workers
from sentinel.panel import projection_service as producer
from tests.sentinel.test_operational_projection_worker import alive


class ColdCallable:
    def __init__(self, directory, mode='slow'):
        self.directory, self.mode = directory, mode

    def prepare(self):
        Path(self.directory, 'pid').write_text(str(os.getpid()))
        if self.mode == 'failure':
            raise RuntimeError('private dependency information')
        time.sleep(60 if self.mode == 'hung' else .6)
        Path(self.directory, 'initialized').write_text('once')

    def __call__(self, fail):
        if fail:
            time.sleep(60)
        assert Path(self.directory, 'initialized').exists()
        return dict(outcome='PUBLISHED', valid_until=(
            datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat(), type=str(os.getpid()))

    def close(self):
        Path(self.directory, 'closed').write_text('closed')


@pytest.mark.skipif(os.name != 'posix', reason='real deployed subprocess supervision')
def test_explicit_bootstrap_then_short_work_preserves_pid_and_strict_work_deadline(tmp_path):
    worker = workers.Worker(ColdCallable(str(tmp_path)))
    try:
        worker.start(timeout=20)
        first = worker.call(False, timeout=.5)
        worker.start(timeout=.01)  # Already READY; no second cold initialization.
        assert worker.call(False, timeout=.5)['type'] == first['type']
        pid = int(first['type'])
        with pytest.raises(TimeoutError, match='collection exceeded'):
            worker.call(True, timeout=.15)
        assert worker.process is None and not alive(pid)
    finally:
        worker.close()


@pytest.mark.skipif(os.name != 'posix', reason='real deployed subprocess supervision')
@pytest.mark.parametrize('mode', ['slow', 'hung', 'failure'])
def test_implicit_or_failed_initialization_never_renews_a_direct_call_budget(tmp_path, mode):
    worker = workers.Worker(ColdCallable(str(tmp_path), mode))
    try:
        if mode == 'failure':
            with pytest.raises(ValueError, match='initialization refused'):
                worker.start(timeout=20)
            assert (tmp_path/'closed').exists()
        else:
            with pytest.raises(TimeoutError, match='initialization'):
                worker.call(False, timeout=.15)
        assert worker.process is None
        if (tmp_path/'pid').exists():
            assert not alive(int((tmp_path/'pid').read_text()))
    finally:
        worker.close()


def waiting_panel():
    now = datetime(2026, 11, 8, 19, tzinfo=timezone.utc)
    cycle = model.Row('automation_cycle', 'Cycle', 'WAITING_OPEN', model.WARN,
        as_of=now, required_current=True,
        recovery=model.RecoveryEvidence(phase='AUTOMATION_WAITING_OPEN', automatic=True,
                                        deadline=now+timedelta(hours=20)))
    return model.Panel(now=now, local_paper_mode=True, rows=[cycle])


@pytest.mark.parametrize('mode', ['waiting', 'missing', 'wrong_phase'])
def test_nonpreparing_health_never_resolves_calendar_or_preparation_inputs(monkeypatch, mode):
    panel = waiting_panel()
    if mode == 'missing':
        panel = replace(panel, rows=[])
    if mode == 'wrong_phase':
        panel = replace(panel, rows=[replace(panel.rows[0], recovery=None)])
    calls = []
    def should_not_run(_):
        calls.append(True)
        return False
    monkeypatch.setattr(presentation, '_closing_source_proof', should_not_run)
    monkeypatch.setattr(presentation, '_preparation_inputs_current', should_not_run)
    assert not presentation._preparing_work_normal(panel)
    assert calls == [], 'non-preparation evaluated expensive preparation inputs'


def test_removed_phase_gate_has_executed_falsifier(monkeypatch):
    source = inspect.getsource(presentation._preparing_work_normal)
    start = source.index('    if (cycle is None or cycle.recovery is None')
    end = source.index('    if not _closing_source_proof(panel)', start)
    namespace = {}
    exec(compile(source[:start]+source[end:], 'removed-early-phase-gate', 'exec'),
         presentation.__dict__, namespace)
    monkeypatch.setattr(presentation, '_preparing_work_normal', namespace['_preparing_work_normal'])
    with pytest.raises(AssertionError, match='non-preparation evaluated'):
        test_nonpreparing_health_never_resolves_calendar_or_preparation_inputs(monkeypatch, 'waiting')


def test_fast_bootstrap_waits_for_first_full_attempt_without_blocking_later_publication(monkeypatch,tmp_path):
    entered,release,fast_started=Event(),Event(),Event()
    class Full:
        calls=0
        def start(self,*,timeout):assert timeout==20
        def call(self,*_,**__):
            self.calls+=1
            if self.calls==1:return dict(outcome='SUPERSEDED')
            entered.set()
            assert release.wait(3)
            return dict(outcome='PUBLISHED',valid_until=(datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat())
        def close(self):pass
    class Fast:
        def start(self,*,timeout):fast_started.set()
        def call(self,*_,**__):
            return dict(outcome='PUBLISHED',valid_until=(datetime.now(timezone.utc)+timedelta(seconds=10)).isoformat())
        def close(self):pass
    monkeypatch.setattr(producer,'HEARTBEAT',tmp_path/'heartbeat')
    publisher=producer.Publisher('private-db','owner')
    publisher.composition_worker=Full();publisher.worker=Fast()
    publisher.start()
    try:
        assert entered.wait(2)
        assert not fast_started.wait(.15), 'consumer bootstrapped without a component attempt'
        release.set()
        assert fast_started.wait(1)
    finally:
        release.set();publisher.close()


def test_removed_first_component_gate_has_executed_falsifier(monkeypatch,tmp_path):
    source=dedent(inspect.getsource(producer.Publisher.run))
    guard='if not self.component_attempted.wait(.1):'
    assert source.count(guard)==1
    namespace={}
    exec(compile(source.replace(guard,'if False:'), 'removed-first-component-gate','exec'),
         producer.__dict__,namespace)
    monkeypatch.setattr(producer.Publisher,'run',namespace['run'])
    with pytest.raises(AssertionError,match='consumer bootstrapped'):
        test_fast_bootstrap_waits_for_first_full_attempt_without_blocking_later_publication(monkeypatch,tmp_path)


def test_shutdown_wakeup_never_launches_a_consumer_before_any_component(monkeypatch,tmp_path):
    entered=Event();starts=[]
    class Full:
        def start(self,*,timeout):
            entered.set()
            assert publisher.stopped.wait(2)
        def call(self,*_,**__):raise AssertionError('work admitted during shutdown')
        def close(self):pass
    class Fast:
        def start(self,*,timeout):starts.append(True)
        def call(self,*_,**__):raise AssertionError('work admitted during shutdown')
        def close(self):pass
    monkeypatch.setattr(producer,'HEARTBEAT',tmp_path/'heartbeat')
    publisher=producer.Publisher('private-db','owner')
    publisher.composition_worker=Full();publisher.worker=Fast()
    publisher.start()
    assert entered.wait(1)
    publisher.close()
    assert starts==[]
