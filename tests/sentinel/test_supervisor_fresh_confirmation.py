"""A stale idle observation cannot terminate a worker that resumed progress."""
import ast
from datetime import datetime, timezone
import inspect
from types import SimpleNamespace

import pytest

from sentinel import automation_supervisor as supervisor


class Finished(Exception):
    pass


def snapshot(age, state='WAITING', callback_age=None):
    return supervisor.InstanceSnapshot(state, age,
        datetime(2031, 1, 1, tzinfo=timezone.utc), callback_age,
        None if callback_age is None else 900-callback_age)


def drive(monkeypatch, observations, *, retry_after_failure=False):
    events = []
    clock = [30.0]
    observations = iter(observations)
    sleeps = []
    monkeypatch.setenv('SENTINEL_AUTOMATION_SUPERVISOR_STARTUP_GRACE_SECONDS', '0')
    monkeypatch.setattr(supervisor.SentinelConfig, 'from_env',
                        lambda: SimpleNamespace(database_url='private-fixture'))
    monkeypatch.setattr(supervisor, 'config_from_env',
                        lambda: SimpleNamespace(lease_seconds=12, callback_deadline_seconds=900))
    monkeypatch.setattr(supervisor.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(supervisor, '_holder_id', lambda: 'same-owned-worker')
    child = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(supervisor, '_spawn', lambda holder: child)
    monkeypatch.setattr(supervisor, '_terminate', lambda value:
                        events.append(('terminate', value is child)))

    def observe(database, holder):
        assert database == 'private-fixture' and holder == 'same-owned-worker'
        events.append(('probe', None))
        answer = next(observations)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def sleep(seconds):
        sleeps.append(seconds)
        if retry_after_failure and len(sleeps) == 1:
            clock[0] += 901
            return
        raise Finished

    def report(message, **kwargs):
        events.append(('report', message))
        if 'terminating stalled' in message:
            clock[0] += 100  # Logging may stall after the decision was consumed.

    monkeypatch.setattr(supervisor, '_snapshot', observe)
    monkeypatch.setattr(supervisor, 'time', SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep))
    monkeypatch.setattr(supervisor.supervisor_io, 'report', report)
    with pytest.raises(Finished):
        supervisor.main()
    return events


def assert_resumed_worker_survives(monkeypatch):
    events = drive(monkeypatch, [snapshot(12.725), snapshot(9.739)])
    assert sum(name == 'probe' for name, _ in events) == 2
    assert not any(name == 'terminate' for name, _ in events), 'resumed worker was killed'


def test_newer_live_heartbeat_cancels_idle_termination(monkeypatch):
    assert_resumed_worker_survives(monkeypatch)


def test_confirmed_idle_stall_is_terminated_before_reporting(monkeypatch):
    events = drive(monkeypatch, [snapshot(12.725), snapshot(13.151)])
    assert ('terminate', True) in events
    killed = next(i for i, event in enumerate(events) if event[0] == 'terminate')
    reported = next(i for i, event in enumerate(events)
                    if event[0] == 'report' and 'terminating stalled' in event[1])
    assert killed < reported, 'logging aged the termination evidence'


def test_healthy_idle_worker_uses_only_one_probe(monkeypatch):
    events = drive(monkeypatch, [snapshot(2)])
    assert events == [('probe', None)]


@pytest.mark.parametrize('callback_age,terminated', [(50, False), (901, True)])
def test_confirmation_preserves_callback_deadline(monkeypatch, callback_age, terminated):
    events = drive(monkeypatch, [snapshot(13),
        snapshot(1, 'RECOVER_CALLBACK', callback_age)])
    assert any(name == 'terminate' for name, _ in events) is terminated


def assert_confirmation_loss_keeps_original_deadline(monkeypatch):
    events = drive(monkeypatch, [snapshot(13), TimeoutError('silent dependency'),
        snapshot(13), TimeoutError('still silent')], retry_after_failure=True)
    assert ('terminate', True) in events, 'confirmation loss renewed its hard deadline'


def test_repeated_failed_confirmation_keeps_first_failure_deadline(monkeypatch):
    assert_confirmation_loss_keeps_original_deadline(monkeypatch)


@pytest.mark.parametrize('elapsed', [1.001, 15, -1, float('nan'), float('inf')])
def test_completed_but_late_or_invalid_probe_is_not_current(monkeypatch, elapsed):
    clock = iter([0, elapsed])
    monkeypatch.setattr(supervisor, 'time', SimpleNamespace(monotonic=lambda: next(clock)))
    monkeypatch.setattr(supervisor.supervisor_io, 'run', lambda *a, **k: snapshot(1))
    with pytest.raises(TimeoutError, match='no longer current'):
        supervisor._snapshot('fixture', 'owned')


def test_original_observation_budget_is_preserved(monkeypatch):
    clock = iter([0, 1])
    monkeypatch.setattr(supervisor, 'time', SimpleNamespace(monotonic=lambda: next(clock)))
    def observed(*args, **kwargs):
        assert kwargs == {'timeout': 1.0}
        return snapshot(1)
    monkeypatch.setattr(supervisor.supervisor_io, 'run', observed)
    assert supervisor._snapshot('fixture', 'owned').heartbeat_age_seconds == 1


def replace_main(monkeypatch, change):
    tree = ast.parse(inspect.getsource(supervisor.main))
    change(tree)
    namespace = {}
    exec(compile(ast.fix_missing_locations(tree), '<removed-supervisor-guard>', 'exec'),
         supervisor.__dict__, namespace)
    monkeypatch.setattr(supervisor, 'main', namespace['main'])


def test_removed_confirmation_is_detected(monkeypatch):
    def remove(tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Try) and any(
                    isinstance(item, ast.Assign) and 'snapshot = _snapshot' in ast.unparse(item)
                    for item in node.body):
                node.body = [item for item in node.body if not (
                    isinstance(item, ast.If) and '_instance_stalled' in ast.unparse(item.test))]
    replace_main(monkeypatch, remove)
    with pytest.raises(AssertionError):
        assert_resumed_worker_survives(monkeypatch)


def test_removed_confirmation_failure_anchor_is_detected(monkeypatch):
    def reset_early(tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Try) and any(
                    isinstance(item, ast.If) and '_instance_stalled' in ast.unparse(item.test)
                    for item in node.body):
                index = next(i for i, item in enumerate(node.body) if isinstance(item, ast.If))
                node.body.insert(index, ast.parse('database_unreadable_since = None').body[0])
    replace_main(monkeypatch, reset_early)
    with pytest.raises(AssertionError, match='renewed its hard deadline'):
        assert_confirmation_loss_keeps_original_deadline(monkeypatch)


def test_removed_elapsed_time_guard_is_detected(monkeypatch):
    tree = ast.parse(inspect.getsource(supervisor._snapshot))
    tree.body[0].body = [node for node in tree.body[0].body if not isinstance(node, ast.If)]
    namespace = {}
    exec(compile(tree, '<removed-probe-time-guard>', 'exec'), supervisor.__dict__, namespace)
    monkeypatch.setattr(supervisor, '_snapshot', namespace['_snapshot'])
    with pytest.raises(pytest.fail.Exception):
        test_completed_but_late_or_invalid_probe_is_not_current(monkeypatch, 15)
