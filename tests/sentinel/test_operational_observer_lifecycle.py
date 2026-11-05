"""Explicit collector ownership and closed worker-observation diagnostics."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import inspect
import pickle

import pytest

from sentinel import shadow_service_probe as probe
from sentinel.panel import model, projection_service as service, projection_worker, review, sources


class ClosingCallable:
    def __init__(self, marker):
        self.marker = marker

    def __call__(self, _failed):
        return {'outcome': 'PUBLISHED', 'valid_until':
                (datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat()}

    def close(self):
        Path(self.marker).write_text('closed')


def test_real_spawned_worker_closes_the_selected_callable(tmp_path):
    marker = tmp_path/'closed'
    worker = projection_worker.Worker(ClosingCallable(str(marker)))
    assert worker.call(False, timeout=10)['outcome'] == 'PUBLISHED'
    assert not marker.exists()
    worker.close()
    assert marker.read_text() == 'closed'


def test_removed_callable_cleanup_is_detected(monkeypatch):
    monkeypatch.setattr(projection_worker.supervisor_io, '_parent_death', lambda _: None)
    class Channel:
        def __init__(self):
            self.commands = iter((b'0', b'S'))
        def recv_bytes(self, *, maxlength):
            assert maxlength == 1
            return next(self.commands)
        def send_bytes(self, value):
            assert value
        def close(self):
            pass
    class Selected:
        closed = False
        def __call__(self, _failed):
            return {'outcome': 'SUPERSEDED'}
        def close(self):
            self.closed = True
    def qualifies(serve):
        selected = Selected()
        serve(Channel(), selected, (), 123)
        assert selected.closed, 'collector dependency was not closed'
    qualifies(projection_worker._serve)
    source = inspect.getsource(projection_worker._serve)
    assert source.count('if close is not None:') == 1
    namespace = dict(vars(projection_worker))
    exec(compile(source.replace('if close is not None:', 'if False:'),
                 'removed-collector-dependency-cleanup', 'exec'), namespace)
    with pytest.raises(AssertionError, match='collector dependency was not closed'):
        qualifies(namespace['_serve'])


def test_collector_is_lazy_picklable_reuses_one_observer_and_closes_it(monkeypatch):
    created, calls = [], []
    class Observer:
        def __init__(self, state_dir):
            self.state_dir, self.closed = state_dir, False
            created.append(self)
        def close(self):
            self.closed = True
    monkeypatch.setattr(probe, 'Observer', Observer)
    collector = pickle.loads(pickle.dumps(service.Collector()))
    assert created == []
    def collect(*args, **kwargs):
        calls.append((args, kwargs['shadow_observer']))
        return {'outcome': 'SUPERSEDED'}
    monkeypatch.setattr(service, 'collect_result', collect)
    assert collector('dsn', 'owner', '/state', 'instance') == {'outcome': 'SUPERSEDED'}
    assert collector('dsn', 'owner', '/state', 'instance', True) == {'outcome': 'SUPERSEDED'}
    assert len(created) == 1 and all(value is created[0] for _, value in calls)
    assert calls[1][0][-1] is True
    with pytest.raises(ValueError, match='state directory changed'):
        collector('dsn', 'owner', '/another-state', 'instance')
    assert len(calls) == 2
    collector.close()
    assert created[0].closed and collector.observer is None
    collector.close()


def test_native_timeout_stage_survives_in_review_without_exception_contents():
    diagnostics = {}
    class TimedOut:
        def read(self, *, timeout):
            assert timeout == 2
            error = TimeoutError('private path credential canary')
            error.probe_stage = 'RECEIVE'
            raise error
    row = sources._shadow_worker_row('/state', 'dsn', observer=TimedOut(), diagnostics=diagnostics)
    assert row.status == model.UNKNOWN and row.as_of is None and row.valid_until is None
    assert row.detail == 'No current worker-liveness proof: TimeoutError'
    page = model.Panel(rows=[row], now=datetime.now(timezone.utc), trial_details=diagnostics)
    evidence = review.condition_evidence(page, ['shadow_worker'])['shadow_worker']
    assert evidence['code'] == 'WORKER_OBSERVATION_TIMEOUT'
    assert evidence['probe_stage'] == 'RECEIVE'
    assert 'private' not in str(evidence)+str(diagnostics)+row.detail


def test_arbitrary_exception_stage_cannot_enter_snapshot_or_review():
    diagnostics = {}
    class ForeignStage:
        def read(self, *, timeout):
            error = TimeoutError('private exception')
            error.probe_stage = 'private stage credential canary'
            raise error
    row = sources._shadow_worker_row('/state', 'dsn', observer=ForeignStage(), diagnostics=diagnostics)
    assert diagnostics == {}
    page = model.Panel(rows=[row], now=datetime.now(timezone.utc), trial_details={
        'worker_observation_failure': {'schema': 'sentinel.worker-observation-failure/1',
            'code': 'TIMEOUT', 'stage': 'private stage credential canary'}})
    evidence = review.condition_evidence(page, ['shadow_worker'])['shadow_worker']
    assert evidence['code'] == 'ROW_CONDITION' and 'probe_stage' not in evidence
    assert 'private' not in str(evidence)+row.detail
