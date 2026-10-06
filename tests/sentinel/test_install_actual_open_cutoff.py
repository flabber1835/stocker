"""Installation timing is distinct from the database benchmark reserve."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from contextlib import contextmanager

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / 'scripts'))
import sentinel_autonomous_deploy_install_entry as install
import sentinel_install_source_refresh as source


def timing(**changes):
    value = dict(frontier='2026-10-02', target='2026-10-02',
                 target_source_final=True, prospective=True, remaining_ms=60_000,
                 execution_open_at='2026-10-05T13:30:00+00:00')
    value.update(changes)
    return value


@pytest.mark.parametrize('remaining', [1, 1000, 60_000, install.go.MIN_REMAINING_DEADLINE_MARGIN_MS - 1])
def test_completed_go_does_not_require_another_database_benchmark_reserve(remaining):
    assert install.InstallAnytimeDeploy._timing_eligible(timing(remaining_ms=remaining))


@pytest.mark.parametrize('changes', [dict(remaining_ms=0), dict(remaining_ms=-1),
    dict(remaining_ms=True), dict(remaining_ms=1.5), dict(prospective=False),
    dict(target_source_final=False)])
def test_actual_open_and_source_final_guards_remain(changes):
    assert not install.InstallAnytimeDeploy._timing_eligible(timing(**changes))


def wait_instance():
    obj = object.__new__(install.InstallAnytimeDeploy)
    obj._operational_source_only = True
    obj.cfg = SimpleNamespace(data_wait_timeout_seconds=60, data_retry_seconds=1)
    obj._assert_wait_fence = lambda: None
    obj._write_deployment_state = lambda *_a, **_k: None
    obj._readiness_verdict = lambda: {'ready': True}
    obj._base_cli = lambda *_a, **_k: None
    return obj


def test_closed_nonfinal_session_waits_then_refreshes_once(monkeypatch):
    obj = wait_instance()
    clock = iter([
        timing(target='2026-10-05', target_source_final=False, prospective=True),
        timing(target='2026-10-05', target_source_final=True),
        timing(target='2026-10-05', frontier='2026-10-05'),
    ])
    obj._causal_timing = lambda: next(clock)
    events = []
    monkeypatch.setattr(install.time, 'sleep', lambda *_a: events.append('wait'))
    monkeypatch.setattr(source, 'refresh', lambda *_a, **kw: events.append(kw['timing']['target']))
    assert obj._wait_until_causal_ready()['frontier'] == '2026-10-05'
    assert events == ['wait', '2026-10-05']


def test_current_publication_is_not_downloaded_again(monkeypatch):
    obj = wait_instance()
    obj._causal_timing = lambda: timing()
    monkeypatch.setattr(source, 'refresh', lambda *_a, **_k: pytest.fail('duplicate acquisition'))
    assert obj._wait_until_causal_ready()['frontier'] == '2026-10-02'


def test_binding_retry_does_not_reset_the_wait_deadline(monkeypatch):
    obj = wait_instance()
    clock = [100.0]
    monkeypatch.setattr(install.time, 'monotonic', lambda: clock[0])
    obj._causal_timing = lambda: timing()
    assert obj._wait_until_causal_ready()['target'] == '2026-10-02'
    assert obj._causal_wait_deadline == 160.0
    clock[0] = 160.0
    with pytest.raises(install.core.DeployRefused, match='timed out'):
        obj._wait_until_causal_ready()
    assert obj._causal_wait_deadline == 160.0


@pytest.mark.parametrize('changes', [dict(prospective=False, remaining_ms=0),
    dict(target='2026-10-05'), dict(frontier='2026-10-01')])
def test_activation_rechecks_exact_attested_session(changes):
    obj = object.__new__(install.InstallAnytimeDeploy)
    obj.reviewed_validation = SimpleNamespace(mode='dual')
    obj._causal_timing = lambda: timing(**changes)
    with pytest.raises(install.core.DeployRefused, match='exact attested decision'):
        obj.assert_activation_timing('2026-10-02')


def test_open_expiry_before_kill_release_leaves_paper_fenced(tmp_path):
    obj = object.__new__(install.InstallAnytimeDeploy)
    obj.cfg = SimpleNamespace(account_id='paper', deployment_id='fixture', actor='test')
    obj.reviewed_validation = SimpleNamespace(mode='dual')
    obj._deferred_install = lambda: True
    clock = iter([timing(), timing(prospective=False, remaining_ms=0)])
    obj._causal_timing = lambda: next(clock)
    obj.phase = lambda *_a: None
    obj.verify_operator_services = lambda: None
    obj._verify_dual_plan_shadow_reconciliation = lambda: None
    obj._authorized_compose = lambda: ['docker', 'compose']
    calls = []
    plan = {'plan': {'plan_id': 'exact', 'decision_session': '2026-10-02'},
            'database_authorities_match': True}
    def cli(args, **kwargs):
        calls.append(args[0])
        return SimpleNamespace(stdout=json.dumps(plan), returncode=0)
    obj._authorized_cli = obj._base_cli = cli
    obj.runner = SimpleNamespace(run=lambda *_a, **_k: None)
    obj._automation_status = lambda: dict(enabled=True, kill_switch_engaged=True,
                                          certificate_sha256='cert')
    with pytest.raises(install.core.DeployRefused, match='following-open cutoff'):
        obj.prepare_activate_start('cert', '2026-10-02')
    assert 'activate-paper-automation' in calls
    assert 'release-paper-automation-kill-switch' not in calls


def refresh_instance(monkeypatch, results):
    obj = wait_instance()
    obj.env = {'ALPACA_API_KEY': 'fixture-key', 'ALPACA_SECRET_KEY': 'fixture-secret',
               'SENTINEL_PAPER_ACCOUNT_ID': 'must-not-reach-source',
               'SENTINEL_FEED_SERVICE_MODE': 'DEPLOY'}
    obj.base_compose = ['docker', 'compose']
    obj.phase = lambda *_a: None
    obj._causal_timing = lambda: timing(target='2026-10-05', remaining_ms=180_000)
    @contextmanager
    def owned(command):
        yield {'command': command}
    monkeypatch.setattr(source, 'owned_command', owned)
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout=source.MARKER + json.dumps(results.pop(0)))
    obj.runner = SimpleNamespace(run=run)
    monkeypatch.setattr(source.time, 'monotonic', lambda: 100.0)
    return obj, calls


def test_source_refresh_withholds_account_and_preserves_host_deadline(monkeypatch):
    obj, calls = refresh_instance(monkeypatch, [dict(status='PUBLISHED', resume_job_id=None)])
    source.refresh(obj, timing=timing(target='2026-10-05'), deadline=160.0)
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert kwargs['timeout'] == 60.0
    assert 'SENTINEL_PAPER_ACCOUNT_ID' not in kwargs['env']
    assert kwargs['env']['ALPACA_API_KEY'] == 'fixture-key'
    assert 'feed-daily' not in args and 'feed-seed' not in args
    assert source.CODE in args


def test_backup_renewal_resumes_same_job_without_new_wait_budget(monkeypatch):
    job = '12f7a9c2-7bf5-41a9-9ad9-eead86e0d3d4'
    obj, calls = refresh_instance(monkeypatch, [
        dict(status='BACKUP_HORIZON_EXCEEDED', resume_job_id=job),
        dict(status='PUBLISHED', resume_job_id=None)])
    backups = []
    obj._create_backup = lambda **kw: backups.append(kw)
    source.refresh(obj, timing=timing(target='2026-10-05'), deadline=160.0)
    assert backups == [dict(restore_drill=False, deadline=160.0)]
    assert len(calls) == 2
    assert calls[1][1]['env']['SENTINEL_INSTALL_RESUME_JOB_ID'] == job
    assert all(call[1]['timeout'] == 60.0 for call in calls)


def test_source_refresh_never_runs_after_fence_loss(monkeypatch):
    obj, calls = refresh_instance(monkeypatch, [])
    def lost():
        raise install.core.DeployRefused('lost fence')
    obj._assert_wait_fence = lost
    with pytest.raises(install.core.DeployRefused, match='lost fence'):
        source.refresh(obj, timing=timing(target='2026-10-05'), deadline=160.0)
    assert calls == []


@pytest.mark.parametrize('status,resume', [
    ('UNKNOWN', None), ('PUBLISHED', 'unexpected'),
    ('BACKUP_HORIZON_EXCEEDED', 'not-a-job')])
def test_refresh_never_treats_malformed_completion_as_success(monkeypatch, status, resume):
    obj, calls = refresh_instance(monkeypatch, [dict(status=status, resume_job_id=resume)])
    with pytest.raises(install.core.DeployRefused):
        source.refresh(obj, timing=timing(target='2026-10-05'), deadline=160.0)
    assert len(calls) == 1


def test_source_refresh_deadline_exhaustion_starts_no_child(monkeypatch):
    obj, calls = refresh_instance(monkeypatch, [])
    with pytest.raises(install.core.DeployRefused, match='deadline exhausted'):
        source.refresh(obj, timing=timing(target='2026-10-05'), deadline=100.0)
    assert calls == []


# Actual SQL fencing and the exchange calendar exercise the acquisition child.
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg


@pytest.mark.parametrize('instant,target,expected', [
    ('2026-10-05T13:29:59+00:00', '2026-10-02', 'PUBLISHED'),
    ('2026-10-05T13:30:00+00:00', '2026-10-02', 'PUBLISHED'),
    ('2026-10-05T15:00:00+00:00', '2026-10-02', 'PUBLISHED'),
    ('2026-10-05T21:00:00+00:00', '2026-10-05', 'PUBLISHED'),
    ('2026-10-05T19:59:59+00:00', '2026-10-05', 'WINDOW_EXPIRED'),
    ('2026-10-05T20:00:00+00:00', '2026-10-02', 'WINDOW_EXPIRED'),
    ('2026-10-06T03:45:00+00:00', '2026-10-05', 'PUBLISHED'),
    ('2026-10-04T12:00:00+00:00', '2026-10-02', 'PUBLISHED'),
    ('2026-11-26T15:00:00+00:00', '2026-11-25', 'PUBLISHED'),
])
def test_acquisition_child_uses_real_fence_and_calendar(
        conn, monkeypatch, capsys, instant, target, expected):
    import datetime
    from sentinel import schema
    from sentinel.feed import rolling_go_inputs, store
    schema.ensure_schema(conn)
    conn.commit()
    fixed = datetime.datetime.fromisoformat(instant)
    # Keep the real connection open for inspection after the child exits.
    class Connection:
        def __getattr__(self, name):
            return getattr(conn, name)
        def close(self):
            pass
    monkeypatch.setattr(store, 'connect', lambda *_a, **_k: Connection())
    monkeypatch.setattr(rolling_go_inputs, 'require_schemas', lambda *_a: None)
    calls = []
    def prepare(*args, **kwargs):
        calls.append(kwargs)
        return {'status': 'PUBLISHED'}
    monkeypatch.setattr(rolling_go_inputs, '_prepare', prepare)
    monkeypatch.setenv('SENTINEL_DATABASE_URL', 'fixture-only')
    monkeypatch.setenv('SENTINEL_INSTALL_SOURCE_TARGET', target)
    monkeypatch.setenv('SENTINEL_INSTALL_SOURCE_DEADLINE', '2026-10-06T13:30:00+00:00')
    # Replace only the clock read; retain every production branch and SQL guard.
    assert source.CODE.count('now = datetime.now(timezone.utc)') == 1
    child = source.CODE.replace('now = datetime.now(timezone.utc)', 'now = _qualified_now')
    exec(compile(child, '<actual-source-refresh-child>', 'exec'), {'_qualified_now': fixed})
    value = json.loads(capsys.readouterr().out.split(source.MARKER)[-1])
    assert value == dict(status=expected, resume_job_id=None)
    assert len(calls) == (1 if expected == 'PUBLISHED' else 0)
    if calls:
        assert calls[0]['target_session'] == target
        assert calls[0]['wait'] is True


def test_acquisition_child_database_fence_cannot_be_skipped(conn, monkeypatch):
    from sentinel import deployment_fence, schema
    from sentinel.feed import store
    schema.ensure_schema(conn)
    conn.execute('UPDATE sentinel_automation_control SET kill_switch_engaged=FALSE WHERE id=1')
    conn.commit()
    class Connection:
        def __getattr__(self, name):
            return getattr(conn, name)
        def close(self):
            pass
    monkeypatch.setattr(store, 'connect', lambda *_a, **_k: Connection())
    monkeypatch.setenv('SENTINEL_DATABASE_URL', 'fixture-only')
    with pytest.raises(deployment_fence.DeploymentFenceRefused):
        exec(compile(source.CODE, '<actual-source-refresh-child>', 'exec'), {})


def test_binding_commands_share_original_deadline(monkeypatch):
    import datetime
    import sentinel_go_process
    obj = wait_instance()
    clock = [100.0]
    monkeypatch.setattr(install.time, 'monotonic', lambda: clock[0])
    obj._causal_wait_deadline = 160.0
    args = timing(execution_open_at=(datetime.datetime.now(datetime.timezone.utc)
                                    + datetime.timedelta(hours=1)).isoformat())
    calls = []
    def run(argv, **kwargs):
        calls.append(kwargs['timeout'])
        return subprocess.CompletedProcess(argv, 0, stdout='', stderr='')
    monkeypatch.setattr(install.subprocess, 'run', run)
    runner = obj._binding_runner(args)
    runner.run(['git', 'rev-parse', 'HEAD'])
    clock[0] = 150.0
    runner.run(['git', 'status', '--short'])
    assert calls == [60.0, 10.0]
    clock[0] = 160.0
    with pytest.raises(install.CausalSessionExpired, match='cutoff'):
        runner.run(['git', 'status', '--short'])
    assert calls == [60.0, 10.0]


def test_source_child_failure_removes_its_owned_container(monkeypatch):
    obj, calls = refresh_instance(monkeypatch, [])
    events = []
    @contextmanager
    def owned(command):
        events.append('owned')
        try:
            yield {'command': command}
        finally:
            events.append('removed')
    monkeypatch.setattr(source, 'owned_command', owned)
    def failed(*args, **kwargs):
        raise install.core.DeployRefused('fixture timeout')
    obj.runner.run = failed
    with pytest.raises(install.core.DeployRefused, match='fixture timeout'):
        source.refresh(obj, timing=timing(target='2026-10-05'), deadline=160.0)
    assert events == ['owned', 'removed']


def test_wait_budget_bounds_poll_commands_and_restores_runner(monkeypatch):
    obj, calls = refresh_instance(monkeypatch, [])
    delegate = obj.runner
    delegate.env = {}
    delegate.run = lambda command, **kwargs: calls.append((command, kwargs))
    with source.wait_commands(obj, 160.0):
        obj.runner.run(['git', 'status'], timeout=120)
        obj.runner.run(['git', 'status'], timeout=10)
        assert obj.runner.env is delegate.env
    assert obj.runner is delegate
    assert [kwargs['timeout'] for _, kwargs in calls] == [60.0, 10]


def test_expired_poll_budget_starts_no_child_and_restores_runner(monkeypatch):
    obj, calls = refresh_instance(monkeypatch, [])
    delegate = obj.runner
    delegate.env = {}
    with pytest.raises(install.core.DeployRefused, match='deadline exhausted'):
        with source.wait_commands(obj, 100.0):
            obj.runner.run(['git', 'status'])
    assert calls == [] and obj.runner is delegate
