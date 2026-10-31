"""Finite activation read retries; real corpus pins and installed host entry.

The local process adapter replaces Docker only. Publication metadata and its
provider contract are explicit fixtures; PostgreSQL's corpus lock, readers.pinned,
child exception protocol, host timing method and startup guards remain native.
No broker, production database, financial authority or release is constructed.
"""
from contextlib import ExitStack, contextmanager
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace
import uuid

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / 'scripts'))
import sentinel_activation_read as read
import sentinel_autonomous_deploy as core
import sentinel_autonomous_deploy_install_entry as install
import sentinel_go_process as processes
from sentinel.feed import _publication_impl as publication, store
from tests.sentinel.test_corpus_publication import pg
from tests.sentinel.test_activation_writer_handoff import appliance

WAIT = 'SENTINEL_ACTIVATION_READ_WAIT={"reason":"CORPUS_LOCK_BUSY","schema":"sentinel.activation-read-wait/1"}'
DECISION = '2026-08-11'


def fixture_publication(session=DECISION, revision=1):
    return publication.Publication(version=revision, previous_version=revision-1 if revision>1 else None,
        run_id='fixture-run-'+str(revision), window_start=DECISION, window_end=session, evidence={})


def publication_subject(session=DECISION, revision=1):
    from sentinel.core.decision import publication_fingerprint
    value = core.data_publication_subject_value(dict(
        publication_fingerprint=publication_fingerprint(fixture_publication(session, revision)),
        visible_frontier=session))
    return core._validation_subject_digest('data_publication', value)


class Clock:
    def __init__(self, now=100.0):
        self.now = now
        self.waits = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert 0 < seconds <= 1
        self.waits.append(seconds)
        self.now += seconds


@pytest.fixture
def owned(monkeypatch):
    """Keep real owned_command naming/signals; substitute external Docker cleanup."""
    removed = []
    monkeypatch.setattr(processes, '_remove_owned', removed.append)
    return removed


def deploy_with(runner, *, seconds=10):
    return SimpleNamespace(cfg=SimpleNamespace(health_timeout=seconds),
                           runner=SimpleNamespace(run=runner))


def completed(code=0, stdout='{"fresh":true}', stderr=''):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


def disposable():
    return ['docker', 'compose', '--project-name', 'isolated-activation-test',
            'run', '--rm', '-T', '--no-deps', '--entrypoint', 'python', 'sentinel', '-c', 'pass']


def child(source):
    environment = {**os.environ, 'PYTHONPATH': str(ROOT)}
    return subprocess.run([sys.executable, '-B', '-c', read.child_code(source)],
                          cwd=ROOT, env=environment, capture_output=True, text=True, timeout=20)


def test_child_emits_only_exact_typed_contention_and_preserves_finally(tmp_path):
    closed = tmp_path / 'connection-closed'
    source = ('from pathlib import Path\n'
              'from sentinel.feed.publication import CorpusLockUnavailable\n'
              'try:\n    raise CorpusLockUnavailable("busy fixture")\n'
              'finally:\n    Path(' + repr(str(closed)) + ').touch()\n')
    answer = child(source)
    assert answer.returncode == 75 and answer.stdout.strip() == WAIT
    assert not answer.stderr and closed.is_file()


@pytest.mark.parametrize('source', [
    'raise ValueError("CorpusLockUnavailable: busy")',
    'from sentinel.feed.publication import CorpusLockUnavailable\n'
    'class Derived(CorpusLockUnavailable): pass\nraise Derived("busy")',
    'raise TimeoutError("busy fixture")',
])
def test_child_does_not_turn_other_errors_into_contention(source):
    answer = child(source)
    assert answer.returncode != 75 and WAIT not in answer.stdout


def test_child_preserves_ordinary_success_and_system_exit():
    answer = child('print("CURRENT-RESULT")')
    assert answer.returncode == 0 and answer.stdout.strip() == 'CURRENT-RESULT'
    answer = child('print("NOT_STARTED"); raise SystemExit(2)')
    assert answer.returncode == 2 and answer.stdout.strip() == 'NOT_STARTED'


def test_child_cleanup_failure_is_not_reported_as_retryable_contention(tmp_path):
    closed = tmp_path / 'cleanup-ran'
    source = ('from pathlib import Path\n'
              'from sentinel.feed.publication import CorpusLockUnavailable\n'
              'try:\n    raise CorpusLockUnavailable("busy fixture")\n'
              'finally:\n    Path(' + repr(str(closed)) + ').touch()\n'
              '    raise RuntimeError("cleanup failed")\n')
    answer = child(source)
    assert closed.is_file() and answer.returncode != 75
    assert WAIT not in answer.stdout and 'cleanup failed' in answer.stderr


def test_busy_reads_retry_only_the_child_and_shrink_one_original_deadline(monkeypatch, owned):
    clock = Clock()
    monkeypatch.setattr(read.time, 'monotonic', clock.monotonic)
    monkeypatch.setattr(read.time, 'sleep', clock.sleep)
    calls = []
    expected = completed()
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return completed(75, WAIT) if len(calls) < 3 else expected
    obj = deploy_with(run)
    answer = read.run(obj, disposable(), 'native fixture')
    assert answer is expected and len(calls) == 3 and len(clock.waits) == 2
    assert all(kwargs.get('check') is False for _, kwargs in calls)
    limits = [kwargs['timeout'] for _, kwargs in calls]
    assert 0 < limits[2] < limits[1] < limits[0] <= 10
    names = [command[command.index('--name')+1] for command, _ in calls]
    assert len(set(names)) == 3 and names == owned
    assert all(name.startswith('sentinel-go-owned-') for name in names)


@pytest.mark.parametrize('code,out,err', [
    (1, '', 'CorpusLockUnavailable: busy'),
    (75, WAIT.replace('CORPUS_LOCK_BUSY', 'UNREVIEWED_REASON'), ''),
    (75, WAIT + '\n' + WAIT, ''),
    (75, WAIT + '\n{"unexpected":true}', ''),
    (75, 'prefix ' + WAIT, ''),
    (75, '', WAIT),
    (75, WAIT, WAIT),
    (0, '{"fresh":true}', WAIT),
    (0, WAIT, ''),
    (-9, WAIT, ''),
    (-11, '', 'isolated child crashed'),
    (76, WAIT, ''),
    (2, '{"status":"NOT_STARTED"}', ''),
])
def test_unrecognized_subprocess_results_are_permanent(monkeypatch, owned, code, out, err):
    clock = Clock()
    monkeypatch.setattr(read.time, 'monotonic', clock.monotonic)
    monkeypatch.setattr(read.time, 'sleep', clock.sleep)
    calls = []
    obj = deploy_with(lambda command, **kwargs: calls.append(command) or completed(code, out, err))
    with pytest.raises(core.DeployRefused) as refusal:
        read.run(obj, disposable(), 'native fixture')
    assert not isinstance(refusal.value, core.ActivationPending)
    assert len(calls) == 1 and not clock.waits and len(owned) == 1


def test_explicit_nonestablished_code_is_returned_for_the_callers_strict_decoder(owned):
    answer = completed(2, '{"status":"NOT_STARTED"}')
    obj = deploy_with(lambda *a, **k: answer)
    assert read.run(obj, disposable(), 'shadow status', allowed_returncodes=(2,)) is answer


def test_retry_budget_is_minimum_of_every_existing_deadline(monkeypatch, owned):
    clock = Clock()
    monkeypatch.setattr(read.time, 'monotonic', clock.monotonic)
    monkeypatch.setattr(read.time, 'sleep', clock.sleep)
    calls = []
    def busy(command, **kwargs):
        calls.append(kwargs['timeout'])
        # A retry may not renew the budget by re-reading mutable configuration.
        obj.cfg.health_timeout = 999
        obj._causal_wait_deadline = 10000.0
        return completed(75, WAIT)
    obj = deploy_with(busy, seconds=10)
    obj._causal_wait_deadline = 104.0
    with pytest.raises(core.ActivationPending):
        read.run(obj, disposable(), 'native fixture', deadline=103.0, timeout=6)
    assert clock.now == 103.0
    assert calls[0] == 3.0 and all(0 < value <= 3 for value in calls)
    assert calls == sorted(calls, reverse=True)
    assert len(calls) == len(owned)


def test_expired_deadline_starts_no_child(monkeypatch, owned):
    clock = Clock()
    monkeypatch.setattr(read.time, 'monotonic', clock.monotonic)
    obj = deploy_with(lambda *a, **k: pytest.fail('expired read spawned a child'))
    with pytest.raises(core.ActivationPending):
        read.run(obj, disposable(), 'native fixture', deadline=clock.now)
    assert not owned


def test_late_success_cannot_authorize_after_original_deadline(monkeypatch, owned):
    clock = Clock()
    monkeypatch.setattr(read.time, 'monotonic', clock.monotonic)
    def late(command, **kwargs):
        clock.now += kwargs['timeout'] + .01
        return completed()
    with pytest.raises(core.ActivationPending):
        read.run(deploy_with(late, seconds=2), disposable(), 'native fixture')
    assert len(owned) == 1


def test_timeout_removes_only_its_disposable_child_without_retry(monkeypatch, owned):
    clock = Clock()
    monkeypatch.setattr(read.time, 'monotonic', clock.monotonic)
    monkeypatch.setattr(read.time, 'sleep', clock.sleep)
    commands = []
    def timeout(command, **kwargs):
        commands.append(command)
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])
    with pytest.raises(core.DeployRefused, match='read command or owned cleanup failed'):
        read.run(deploy_with(timeout), disposable(), 'native fixture')
    assert len(commands) == 1 and not clock.waits
    assert owned == [commands[0][commands[0].index('--name')+1]]


def test_other_runner_failures_are_never_retried(monkeypatch, owned):
    clock = Clock()
    monkeypatch.setattr(read.time, 'monotonic', clock.monotonic)
    monkeypatch.setattr(read.time, 'sleep', clock.sleep)
    calls = []
    def corrupt(command, **kwargs):
        calls.append(command)
        raise core.DeployRefused('unknown authority or malformed evidence')
    with pytest.raises(core.DeployRefused, match='unknown authority'):
        read.run(deploy_with(corrupt), disposable(), 'native fixture')
    assert len(calls) == 1 and not clock.waits and len(owned) == 1


@pytest.mark.parametrize('seconds', [0, -1, True, float('inf'), float('nan'), '10'])
def test_invalid_read_budget_never_spawns_a_child(owned, seconds):
    obj = deploy_with(lambda *a, **k: pytest.fail('invalid budget spawned a child'), seconds=seconds)
    with pytest.raises(core.DeployRefused, match='timeout is invalid'):
        read.run(obj, disposable(), 'native fixture')
    assert not owned


@pytest.mark.parametrize('deadline', [True, float('inf'), float('nan'), 'later'])
def test_invalid_parent_deadline_never_spawns_a_child(owned, deadline):
    obj = deploy_with(lambda *a, **k: pytest.fail('invalid deadline spawned a child'))
    with pytest.raises(core.DeployRefused, match='deadline is invalid'):
        read.run(obj, disposable(), 'native fixture', deadline=deadline)
    assert not owned


@pytest.mark.parametrize('timeout', [True, '10', float('nan'), float('inf')])
def test_malformed_caller_timeout_is_terminal_before_spawn(owned, timeout):
    obj = deploy_with(lambda *a, **k: pytest.fail('malformed timeout spawned a child'))
    with pytest.raises(core.DeployRefused, match='caller timeout is invalid') as refusal:
        read.run(obj, disposable(), 'native fixture', timeout=timeout)
    assert not isinstance(refusal.value, core.ActivationPending) and not owned


@pytest.mark.parametrize('timeout', [0, -1])
def test_finite_exhausted_caller_budget_is_pending_before_spawn(owned, timeout):
    obj = deploy_with(lambda *a, **k: pytest.fail('exhausted timeout spawned a child'))
    with pytest.raises(core.ActivationPending, match='no remaining read budget'):
        read.run(obj, disposable(), 'native fixture', timeout=timeout)
    assert not owned


def test_removed_postcommand_deadline_guard_is_killed(monkeypatch, owned):
    source = inspect.getsource(read.run)
    needle = 'if time.monotonic() >= limit:'
    assert source.count(needle) == 1
    namespace = dict(vars(read))
    exec(compile(source.replace(needle, 'if False:'), 'removed-activation-read-deadline', 'exec'), namespace)
    monkeypatch.setattr(read, 'run', namespace['run'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_late_success_cannot_authorize_after_original_deadline(monkeypatch, owned)


def test_overbroad_failure_retry_is_killed(monkeypatch, owned):
    source = inspect.getsource(read.run)
    needle = 'busy = completed.returncode == WAIT_EXIT and output.strip() == WAIT_OUTPUT'
    assert source.count(needle) == 1
    namespace = dict(vars(read))
    exec(compile(source.replace(needle, 'busy = completed.returncode != 0'),
                 'untyped-activation-read-retry', 'exec'), namespace)
    monkeypatch.setattr(read, 'run', namespace['run'])
    with pytest.raises(AssertionError):
        test_unrecognized_subprocess_results_are_permanent(
            monkeypatch, owned, 1, '', 'CorpusLockUnavailable: busy')


@pytest.fixture
def probe(pg):
    from psycopg import sql
    connection = store.connect(pg.sync_dsn)
    table = 'activation_probe_' + uuid.uuid4().hex
    connection.execute(sql.SQL('CREATE TABLE {} (session text NOT NULL, revision bigint NOT NULL)').format(sql.Identifier(table)))
    connection.execute(sql.SQL('INSERT INTO {} VALUES (%s,1)').format(sql.Identifier(table)), (DECISION,))
    connection.commit()
    try:
        yield SimpleNamespace(dsn=pg.sync_dsn, table=table, connection=connection)
    finally:
        connection.rollback()
        connection.execute(sql.SQL('DROP TABLE {}').format(sql.Identifier(table)))
        connection.commit()
        connection.close()


@contextmanager
def corpus_writer(probe):
    connection = store.connect(probe.dsn)
    connection.execute('SELECT pg_advisory_lock(%s)', (publication.CORPUS_LOCK_KEY,))
    connection.commit()
    try:
        yield connection
    finally:
        connection.execute('SELECT pg_advisory_unlock(%s)', (publication.CORPUS_LOCK_KEY,))
        connection.commit()
        connection.close()


class LocalProbeRunner:
    """Execute the exact child code with an actual private PostgreSQL corpus pin."""
    def __init__(self, probe, *, instant='2026-08-12T13:00:00+00:00', after_busy=lambda: None,
                 cleanup_failure=None, cleanup_marker=None):
        self.probe, self.instant, self.after_busy = probe, instant, after_busy
        self.cleanup_failure, self.cleanup_marker = cleanup_failure, cleanup_marker
        self.calls = []
        self.results = []
        self.env = {}

    def run(self, command, **kwargs):
        assert command[:2] == ['docker', 'compose'] and '-c' in command
        self.calls.append((command, kwargs))
        # Only metadata validation is a fixture. The actual public readers.pinned
        # and its native advisory-lock acquisition/unlock/connection disposal run.
        prefix = r'''
import os,sys,datetime,builtins
from pathlib import Path
from types import SimpleNamespace
from psycopg import sql
from sentinel.feed import _publication_impl as publication, publication as facade, readers, operational_snapshot, store
from sentinel import shadow_runtime
def current(conn):
    day,revision=conn.execute(sql.SQL('SELECT session,revision FROM {}').format(sql.Identifier(os.environ['PROBE_TABLE']))).fetchone()
    return publication.Publication(version=revision,previous_version=revision-1 if revision>1 else None,
        run_id='fixture-run-'+str(revision),window_start=os.environ['PROBE_ORIGIN_SESSION'],window_end=day,evidence={})
publication.require_current=current
facade._validate_publication=lambda *a,**k:None
readers.is_rolling=lambda pub:True
readers.frontier=lambda conn,pub:pub.window_end
operational_snapshot._bound=lambda *a,**k:{}
operational_snapshot.require_alpaca_openfigi=lambda *a,**k:None
if os.environ.get('PROBE_CLEANUP_FAILURE'):
    real_connect=store.connect
    class FailedCleanup:
        def __init__(self,connection):self.connection=connection
        def __getattr__(self,name):return getattr(self.connection,name)
        def rollback(self):
            self.connection.rollback()
            if os.environ['PROBE_CLEANUP_FAILURE']=='rollback':raise RuntimeError('rollback fixture failed')
        def close(self):
            self.connection.close()
            Path(os.environ['PROBE_CLEANUP_MARKER']).touch()
            if os.environ['PROBE_CLEANUP_FAILURE']=='close':raise RuntimeError('close fixture failed')
    store.connect=lambda *a,**k:FailedCleanup(real_connect(*a,**k))
RealDateTime=datetime.datetime
class ClockDateTime(RealDateTime):
    @classmethod
    def now(cls,tz=None):
        value=RealDateTime.fromisoformat(os.environ['PROBE_NOW'])
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)
probe_globals=globals()
real_import=builtins.__import__
def probe_import(name,globals=None,locals=None,fromlist=(),level=0):
    # Only the exact probe receives a clock fixture. Altering datetime.datetime
    # globally corrupts C-extension datetime assumptions in calendar dependencies.
    if name=='datetime' and globals is probe_globals and fromlist==('datetime','timezone'):
        return SimpleNamespace(datetime=ClockDateTime,timezone=datetime.timezone)
    return real_import(name,globals,locals,fromlist,level)
builtins.__import__=probe_import
'''
        environment = {**os.environ, 'PYTHONPATH': str(ROOT), 'SENTINEL_DATABASE_URL': self.probe.dsn,
                       'PROBE_TABLE': self.probe.table, 'PROBE_NOW': self.instant,
                       'PROBE_ORIGIN_SESSION':DECISION}
        if self.cleanup_failure:
            environment.update(PROBE_CLEANUP_FAILURE=self.cleanup_failure,
                               PROBE_CLEANUP_MARKER=str(self.cleanup_marker))
        answer = subprocess.run([sys.executable, '-B', '-c', prefix + '\n' + command[-1]],
                                cwd=ROOT, env=environment, capture_output=True, text=True,
                                timeout=kwargs.get('timeout', 30))
        self.results.append(answer)
        if answer.returncode == 75:
            assert answer.stdout.strip() == WAIT
            self.after_busy()
        return answer


def timing_host(runner, *, operational=True, mode='dual'):
    obj = object.__new__(install.InstallAnytimeDeploy)
    obj.cfg = SimpleNamespace(health_timeout=30, data_wait_timeout_seconds=30)
    obj.reviewed_validation = SimpleNamespace(mode=mode,data_publication_sha256=publication_subject())
    obj._operational_source_only = operational
    obj.base_compose = ['docker', 'compose']
    obj.runner = runner
    return obj


def test_actual_installed_timing_probe_waits_for_real_postgres_corpus_writer(probe, owned):
    with corpus_writer(probe) as writer:
        def release():
            writer.execute('SELECT pg_advisory_unlock(%s)', (publication.CORPUS_LOCK_KEY,))
            writer.commit()
        runner = LocalProbeRunner(probe, after_busy=release)
        obj = timing_host(runner)
        value = obj._causal_timing()
        assert value['frontier'] == value['target'] == DECISION
        assert len(value['publication_fingerprint']) == 64
        assert value['target_source_final'] is True and value['prospective'] is True
        assert [r.returncode for r in runner.results] == [75, 0]
        assert len(owned) == 2
    assert probe.connection.execute('SELECT pg_try_advisory_lock(%s)', (publication.CORPUS_LOCK_KEY,)).fetchone()[0]
    probe.connection.execute('SELECT pg_advisory_unlock(%s)', (publication.CORPUS_LOCK_KEY,))
    probe.connection.rollback()


@pytest.mark.parametrize('instant,eligible', [
    ('2026-08-12T13:00:00+00:00',True),
    ('2026-08-12T13:30:00+00:00',False),
])
def test_ordinary_paper_without_reviewed_publication_subject_keeps_its_open_guard(probe, owned, instant, eligible):
    runner = LocalProbeRunner(probe, instant=instant)
    obj = timing_host(runner, operational=False, mode='paper')
    obj.reviewed_validation.data_publication_sha256 = None
    if eligible:
        obj.assert_activation_timing(DECISION)
    else:
        with pytest.raises(core.ActivationPending, match='following-open cutoff'):
            obj.assert_activation_timing(DECISION)
    assert [answer.returncode for answer in runner.results] == [0]
    assert len(owned) == 1


@pytest.mark.parametrize('failure', ['rollback', 'close'])
def test_actual_causal_child_cleanup_failure_refuses_without_retry(probe, owned, tmp_path, failure):
    marker = tmp_path / 'closed-native-connection'
    with corpus_writer(probe):
        runner = LocalProbeRunner(probe, cleanup_failure=failure, cleanup_marker=marker)
        with pytest.raises(core.DeployRefused, match='command refused'):
            timing_host(runner)._causal_timing()
        assert marker.is_file() and len(runner.results) == 1
        answer = runner.results[0]
        assert answer.returncode != 75 and WAIT not in answer.stdout
        assert failure + ' fixture failed' in answer.stderr
    assert len(owned) == 1


@pytest.mark.parametrize('boundary', ['publication', 'close', 'paper-open', 'dual-open'])
def test_actual_probe_reobserves_publication_and_clock_after_contention(probe, owned, boundary):
    from psycopg import sql
    with corpus_writer(probe) as writer:
        runner = LocalProbeRunner(probe)
        def change_and_release():
            if boundary == 'publication':
                writer.execute(sql.SQL('UPDATE {} SET session=%s').format(sql.Identifier(probe.table)), ('2026-08-12',))
                runner.instant = '2026-08-13T13:00:00+00:00'
            elif boundary == 'close':
                runner.instant = '2026-08-12T21:00:00+00:00'
            else:
                runner.instant = '2026-08-12T13:30:00+00:00'
            writer.execute('SELECT pg_advisory_unlock(%s)', (publication.CORPUS_LOCK_KEY,))
            writer.commit()
        runner.after_busy = change_and_release
        obj = timing_host(runner, operational=boundary != 'paper-open',
                          mode='paper' if boundary == 'paper-open' else 'dual')
        if boundary == 'dual-open':
            obj.assert_activation_timing(DECISION)
        else:
            with pytest.raises(core.ActivationPending):
                obj.assert_activation_timing(DECISION)
        assert [r.returncode for r in runner.results] == [75, 0]
        assert len(owned) == 2


@pytest.mark.parametrize('fault', ['missing','null','boolean','short','nonhex','uppercase'])
def test_actual_causal_timing_decoder_rejects_malformed_publication_fingerprint(probe, owned, fault):
    runner = LocalProbeRunner(probe)
    native = runner.run
    def corrupt(command, **kwargs):
        answer = native(command, **kwargs)
        assert answer.returncode == 0
        value = json.loads(answer.stdout)
        if fault == 'missing':value.pop('publication_fingerprint')
        else:value['publication_fingerprint'] = dict(null=None,boolean=True,short='a'*63,
            nonhex='g'*64,uppercase='F'*64)[fault]
        return subprocess.CompletedProcess(answer.args,0,json.dumps(value),answer.stderr)
    runner.run = corrupt
    with pytest.raises(core.DeployRefused, match='causal deployment timing is malformed'):
        timing_host(runner)._causal_timing()
    assert len(runner.results) == 1 and len(owned) == 1


def test_a_prior_success_cannot_replace_a_new_observation_after_writer_changes_source(probe, owned):
    from psycopg import sql
    runner = LocalProbeRunner(probe)
    obj = timing_host(runner)
    first = obj._causal_timing()
    assert first['frontier'] == first['target'] == DECISION
    with corpus_writer(probe) as writer:
        writer.execute(sql.SQL('UPDATE {} SET session=%s').format(sql.Identifier(probe.table)), ('2026-08-12',))
        writer.commit()
        runner.instant = '2026-08-13T13:00:00+00:00'
        def release():
            writer.execute('SELECT pg_advisory_unlock(%s)', (publication.CORPUS_LOCK_KEY,))
            writer.commit()
        runner.after_busy = release
        with pytest.raises(core.ActivationPending):
            obj.assert_activation_timing(DECISION)
    assert [answer.returncode for answer in runner.results] == [0, 75, 0]
    assert len(owned) == 3


def test_reusing_a_successful_timing_result_has_an_executed_falsifier(probe, owned, monkeypatch):
    native = read.run
    previous = []
    def cached(*args, **kwargs):
        if not previous:
            previous.append(native(*args, **kwargs))
        return previous[0]
    monkeypatch.setattr(read, 'run', cached)
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_a_prior_success_cannot_replace_a_new_observation_after_writer_changes_source(probe, owned)


@pytest.mark.parametrize('failure', ['rollback', 'close'])
def test_actual_reconciliation_child_closes_even_when_cleanup_fails(tmp_path, owned, failure):
    marker = tmp_path / 'closed-reconciliation-connection'
    obj = object.__new__(core.AutonomousDeploy)
    obj.cfg = SimpleNamespace(health_timeout=30)
    obj.phase = lambda *_: None
    obj._authorized_compose = lambda: ['docker', 'compose']
    answers = []
    prefix = '''
import os
from pathlib import Path
from sentinel import dual_reconciliation
from sentinel.execution import journal,alpaca
from sentinel.feed import store
from sentinel.feed.publication import CorpusLockUnavailable
class Connection:
    def execute(self,*a,**k):pass
    def rollback(self):
        if os.environ['CLEANUP_FAILURE']=='rollback':raise RuntimeError('rollback fixture failed')
    def close(self):
        Path(os.environ['CLOSED_MARKER']).touch()
        if os.environ['CLEANUP_FAILURE']=='close':raise RuntimeError('close fixture failed')
store.connect=lambda *a,**k:Connection()
alpaca.upgrade_restore_reason=lambda _:None
journal.latest_plan=lambda _:object()
def busy(*a,**k):raise CorpusLockUnavailable('busy fixture')
dual_reconciliation.require_plan_matches_verified_shadow=busy
'''
    def execute(command, **kwargs):
        answer = subprocess.run([sys.executable, '-B', '-c', prefix + '\n' + command[-1]], cwd=ROOT,
            env={**os.environ, 'PYTHONPATH':str(ROOT), 'SENTINEL_DATABASE_URL':'fixture-no-network',
                 'CLEANUP_FAILURE':failure, 'CLOSED_MARKER':str(marker)},
            capture_output=True, text=True, timeout=kwargs.get('timeout',30))
        answers.append(answer)
        return answer
    obj.runner = SimpleNamespace(run=execute)
    with pytest.raises(core.DeployRefused, match='command refused'):
        obj._verify_dual_plan_shadow_reconciliation()
    assert marker.is_file() and len(answers) == 1 and len(owned) == 1
    assert answers[0].returncode != 75 and WAIT not in answers[0].stdout
    assert failure + ' fixture failed' in answers[0].stderr


def test_reconciliation_close_after_rollback_failure_has_an_executed_falsifier(tmp_path, owned, monkeypatch):
    native = read.child_code
    needle = '    try:\n        c.rollback()\n    finally:\n        c.close()'
    def unsafe(code):
        assert code.count(needle) == 1
        return native(code.replace(needle, '    c.rollback()\n    c.close()'))
    monkeypatch.setattr(read, 'child_code', unsafe)
    with pytest.raises(AssertionError):
        test_actual_reconciliation_child_closes_even_when_cleanup_fails(tmp_path, owned, 'rollback')


def test_resumed_startup_rechecks_changed_control_after_real_contention(probe, owned, tmp_path):
    obj, events, control, running = appliance(tmp_path, install.InstallAnytimeDeploy)
    running['shadow'] = False
    control.update(enabled=True, kill_switch_engaged=False)
    obj.cfg.health_timeout = 30
    obj.base_compose = ['docker', 'compose']
    obj._operational_source_only = True
    obj.reviewed_validation.data_publication_sha256 = publication_subject()
    original_run = obj.runner.run
    with corpus_writer(probe) as writer:
        def drift_and_release():
            control['certificate_sha256'] = 'foreign-certificate'
            writer.execute('SELECT pg_advisory_unlock(%s)', (publication.CORPUS_LOCK_KEY,))
            writer.commit()
        local = LocalProbeRunner(probe, after_busy=drift_and_release)
        obj.runner.run = lambda command, **kwargs: (local.run(command, **kwargs)
            if command[:2] == ['docker', 'compose'] and '-c' in command else original_run(command, **kwargs))
        obj.assert_activation_timing = install.InstallAnytimeDeploy.assert_activation_timing.__get__(obj)
        with pytest.raises(core.DeployRefused, match='released automation control differs'):
            with obj.activation_transition():
                obj.start_activated_runtime('certificate', DECISION)
        assert [r.returncode for r in local.results] == [75, 0]
    assert control['kill_switch_engaged'] is True
    assert not running['shadow'] and not running['automation']
    assert 'start-collector' not in events and 'start-automation' not in events


def test_same_session_republication_after_match_refuses_before_dispatch(probe, owned, tmp_path):
    from psycopg import sql
    obj, events, control, running = appliance(tmp_path, install.InstallAnytimeDeploy)
    running['shadow'] = False
    control.update(enabled=True, kill_switch_engaged=False)
    obj.cfg.health_timeout = 30
    obj.base_compose = ['docker', 'compose']
    obj._operational_source_only = True
    obj.reviewed_validation.data_publication_sha256 = publication_subject()
    original_run = obj.runner.run
    local = LocalProbeRunner(probe)
    # A prior successful native timing result is an observation, never a reusable
    # permission after the publisher replaces same-session content.
    first = timing_host(local)._causal_timing()
    assert first['frontier'] == first['target'] == DECISION
    before = first['publication_fingerprint']
    original_reconcile = obj._verify_dual_plan_shadow_reconciliation
    with ExitStack() as resources:
        def reconcile_then_publish():
            original_reconcile()  # Explicit economic MATCH fixture boundary.
            writer = resources.enter_context(corpus_writer(probe))
            writer.execute(sql.SQL('UPDATE {} SET revision=revision+1').format(sql.Identifier(probe.table)))
            writer.commit()
            def release():
                writer.execute('SELECT pg_advisory_unlock(%s)', (publication.CORPUS_LOCK_KEY,))
                writer.commit()
            local.after_busy = release
        obj._verify_dual_plan_shadow_reconciliation = reconcile_then_publish
        obj.runner.run = lambda command, **kwargs: (local.run(command, **kwargs)
            if command[:2] == ['docker', 'compose'] and '-c' in command else original_run(command, **kwargs))
        obj.assert_activation_timing = install.InstallAnytimeDeploy.assert_activation_timing.__get__(obj)
        with pytest.raises(core.ActivationPending, match='source publication changed'):
            with obj.activation_transition():
                obj.start_activated_runtime('certificate', DECISION)
    assert [answer.returncode for answer in local.results] == [0,75,0]
    after = json.loads(local.results[-1].stdout)
    assert after['frontier'] == DECISION and after['publication_fingerprint'] != before
    assert 'reconcile-resumed' in events and control['kill_switch_engaged'] is True
    assert not running['automation']
    assert 'start-collector' not in events and 'start-automation' not in events


def test_removed_same_session_publication_guard_has_an_executed_falsifier(probe, owned, tmp_path, monkeypatch):
    source = textwrap.dedent(inspect.getsource(install.InstallAnytimeDeploy.assert_activation_timing))
    needle = '!= reviewed.data_publication_sha256'
    assert source.count(needle) == 1
    namespace = dict(vars(install))
    exec(compile(source.replace(needle,needle+' and False'), 'removed-same-session-source-guard','exec'),namespace)
    monkeypatch.setattr(install.InstallAnytimeDeploy,'assert_activation_timing',namespace['assert_activation_timing'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_same_session_republication_after_match_refuses_before_dispatch(probe, owned, tmp_path)
