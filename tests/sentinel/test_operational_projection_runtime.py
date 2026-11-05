"""Finite background collection and independent role liveness, without HTTP."""
from datetime import datetime, timedelta, timezone
import inspect
from types import SimpleNamespace
from pathlib import Path

import pytest

from sentinel.panel import projection_service as producer, verification_service as verifier
from sentinel.panel.operational_snapshot import SnapshotUnavailable


def test_shared_projection_roles_have_matching_public_context_without_broker_or_push_secrets():
    import yaml
    root = Path(__file__).resolve().parents[2]
    base = yaml.safe_load((root/'docker-compose.sentinel.yml').read_text())
    overlay = yaml.safe_load((root/'docker-compose.sentinel-automation.yml').read_text())
    panel = {**base['services']['sentinel-panel']['environment'],
             **overlay['services'].get('sentinel-panel', {}).get('environment', {})}
    verifier = overlay['services']['sentinel-verifier']['environment']
    for name in ('SENTINEL_SHADOW_STARTING_CASH', 'SENTINEL_PUBLIC_ORIGIN',
                 'SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY'):
        assert panel[name] == verifier[name]
    assert panel['SENTINEL_SHADOW_STARTING_CASH'] == '${SENTINEL_SHADOW_STARTING_CASH:-50000}'
    assert not {'ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY'} & verifier.keys()


class Stop:
    def __init__(self):
        self.stopped = False
        self.waits = []

    def is_set(self): return self.stopped
    def set(self): self.stopped = True
    def wait(self, seconds):
        self.waits.append(seconds)
        return self.stopped


def test_superseded_work_does_not_create_failure_or_clear_a_real_failure(monkeypatch, tmp_path):
    stop, calls = Stop(), []
    answers = ('SUPERSEDED', 'SUPERSEDED', 'FAILED', 'SUPERSEDED', 'PUBLISHED', 'PUBLISHED')
    heartbeat = tmp_path/'operational-heartbeat'
    monkeypatch.setattr(producer, 'HEARTBEAT', heartbeat)
    def runner(function, *args, **kwargs):
        calls.append((function, args, kwargs))
        if len(calls) <= 4:
            assert not heartbeat.exists()
        if len(calls) == len(answers): stop.set()
        return {'outcome': answers[len(calls)-1],
                'valid_until': (datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat()}
    worker = producer.Publisher('private-qualified-db', 'same-owner', stopped=stop, runner=runner)
    worker.run()
    assert [args[-1] for _, args, _ in calls] == [False, False, False, True, True, False]
    assert all(args[1] == 'same-owner' and args[3] == worker.instance for _, args, _ in calls)
    assert all(options == {'timeout': producer.DEADLINE_SECONDS, 'start_method': 'spawn'}
               for _, _, options in calls)
    assert heartbeat.exists() and all(0 <= delay <= 30 for delay in stop.waits)


def test_transport_or_malformed_child_response_is_latched_until_success(monkeypatch, tmp_path):
    stop, previous = Stop(), []
    monkeypatch.setattr(producer, 'HEARTBEAT', tmp_path/'heartbeat')
    monkeypatch.setattr(producer.supervisor_io, 'report', lambda *_: None)
    def runner(_function, *args, **_kwargs):
        previous.append(args[-1])
        if len(previous) == 1: raise TimeoutError('private transport detail')
        if len(previous) == 2: return None
        stop.set()
        return {'outcome': 'PUBLISHED',
                'valid_until': (datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat()}
    producer.Publisher('private-db', 'owner', stopped=stop, runner=runner).run()
    assert previous == [False, True, True]


@pytest.mark.parametrize('alive', [False, True])
def test_shutdown_retains_existing_bounded_join(monkeypatch, tmp_path, alive):
    heartbeat = tmp_path/'heartbeat'
    heartbeat.write_text(datetime.now(timezone.utc).isoformat())
    monkeypatch.setattr(producer, 'HEARTBEAT', heartbeat)
    joined = []
    worker = producer.Publisher('private-db', 'owner')
    worker.thread = SimpleNamespace(join=lambda timeout: joined.append(timeout), is_alive=lambda: alive)
    worker.started = True
    if alive:
        with pytest.raises(TimeoutError, match='bounded shutdown'): worker.close()
    else:
        worker.close()
        assert not heartbeat.exists()
    assert worker.stopped.is_set() and joined == [producer.DEADLINE_SECONDS+3]


def test_shutdown_before_first_financial_refresh_closes_without_starting_a_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(producer, 'HEARTBEAT', tmp_path/'never-started')
    worker = producer.Publisher('private-db', 'owner')
    worker.close()
    assert not worker.started and worker.stopped.is_set()
    assert worker.worker.process is None


@pytest.mark.parametrize('exception,outcome', [
    (producer.CollectionSuperseded('changed subject'), 'SUPERSEDED'),
    (SnapshotUnavailable('SNAPSHOT_PANEL_INVALID'), 'FAILED'),
    (ValueError('private malformed source'), 'FAILED'),
])
def test_only_typed_collection_supersession_is_expected_work(monkeypatch, exception, outcome):
    def refused(*_): raise exception
    monkeypatch.setattr(producer, 'publish_once', refused)
    def unavailable_fallback(*_): raise RuntimeError('private unavailable fallback')
    monkeypatch.setattr(producer, 'publish_failure', unavailable_fallback)
    result = producer.collect_result('unused', 'owner', '/private', 'instance')
    assert result['outcome'] == outcome
    assert 'private' not in str(result)


@pytest.mark.parametrize('defect', ['none', 'missing_verifier', 'missing_projector',
    'stale_verifier', 'stale_projector', 'future_verifier', 'future_projector',
    'malformed_verifier', 'malformed_projector', 'naive_verifier', 'naive_projector'])
def test_role_health_requires_fresh_valid_independent_heartbeats(monkeypatch, tmp_path, defect):
    paths = {'verifier': tmp_path/'verifier', 'projector': tmp_path/'projector'}
    monkeypatch.setattr(verifier, 'HEARTBEAT', paths['verifier'])
    monkeypatch.setattr(producer, 'HEARTBEAT', paths['projector'])
    now = datetime.now(timezone.utc)
    for component, path in paths.items():
        if defect == 'missing_'+component: continue
        value = now
        if defect == 'stale_'+component: value -= timedelta(seconds=46)
        if defect == 'future_'+component: value += timedelta(seconds=1)
        if defect == 'naive_'+component: value = value.replace(tzinfo=None)
        path.write_text('malformed' if defect == 'malformed_'+component else value.isoformat())
    assert verifier.health() == (0 if defect == 'none' else 1)


@pytest.mark.parametrize('remaining,cost,expected', [(30, 2, 26), (10, 6, 2),
    (90, 1, 30), (2, 6, .25)])
def test_adaptive_refresh_accounts_for_original_expiry_and_measured_cost(remaining, cost, expected):
    now = datetime(2031, 4, 21, 20, tzinfo=timezone.utc)
    expiry = now+timedelta(seconds=remaining)
    assert producer.refresh_delay(expiry, now=now, elapsed=cost) == expected


@pytest.mark.parametrize('remaining,cost', [(0, 1), (-1, 1), (30, -1),
    (30, float('inf')), (30, float('nan'))])
def test_adaptive_refresh_refuses_expiry_or_invalid_measurement(remaining, cost):
    now = datetime(2031, 4, 21, 20, tzinfo=timezone.utc)
    with pytest.raises((ValueError, TimeoutError)):
        producer.refresh_delay(now+timedelta(seconds=remaining), now=now, elapsed=cost)


@pytest.mark.parametrize('refusal', [verifier.QueryCanceled, verifier.LockNotAvailable])
def test_projection_starts_once_after_first_successful_financial_refresh(monkeypatch, tmp_path, refusal):
    import time
    stop, refreshes, starts, rolled_back = Stop(), [], [], []
    connection = SimpleNamespace(closed=False, broken=False, rollback=lambda: rolled_back.append(True))
    monkeypatch.setattr(verifier, 'HEARTBEAT', tmp_path/'financial-heartbeat')
    monkeypatch.setattr(verifier, '_renew_owner', lambda *_: time.monotonic()+100)
    def refresh(*_):
        refreshes.append(True)
        if len(refreshes) == 1: raise refusal('private typed availability')
        if len(refreshes) == 3: stop.set()
    monkeypatch.setattr(verifier, '_refresh_readers', refresh)
    verifier._run_owned_loop(connection, {}, 'private-db', 'owner', {}, stop,
        time.monotonic()+100, on_first_refresh=lambda: starts.append(len(refreshes)))
    assert starts == [2] and rolled_back == [True]
    assert verifier.RETRY_POLL_SECONDS in stop.waits and 15 in stop.waits


def test_removed_first_refresh_once_guard_is_detected(monkeypatch, tmp_path):
    code = inspect.getsource(verifier._run_owned_loop)
    guard = 'if on_first_refresh is not None and not projection_started:'
    assert code.count(guard) == 1
    namespace = {}
    exec(compile(code.replace(guard, 'if on_first_refresh is not None:'),
                 '<removed-first-projection-start-guard>', 'exec'), vars(verifier), namespace)
    monkeypatch.setattr(verifier, '_run_owned_loop', namespace['_run_owned_loop'])
    with pytest.raises(AssertionError):
        test_projection_starts_once_after_first_successful_financial_refresh(
            monkeypatch, tmp_path, verifier.QueryCanceled)
